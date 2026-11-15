"""OCR with Sarvam's Document AI ("Parse"): scanned PDFs and photos of documents, 23 languages.

The API is asynchronous: submit the file, poll the job, then download a zip holding the Markdown and, per page, the
text blocks in reading order. Pages are rebuilt from those blocks, so an answer can still cite the page it came from.
The original filename is never sent. The text that comes back is raw: callers must mask it before storing it or
showing it to any model (storage/index.py does)."""
import asyncio
import io
import json
import logging
import time
import zipfile
from typing import List, Optional, Tuple

import httpx

import config

log = logging.getLogger("sahaj.ocr")
TERMINAL = {"completed", "partially_completed", "failed", "rejected"}
ACCEPTED = {"application/pdf": "document.pdf", "image/png": "page.png", "image/jpeg": "page.jpg"}
_transport = None   # tests put a mock transport here


class OcrError(RuntimeError):
    pass


def supported(content_type: str) -> bool:
    return content_type in ACCEPTED


def first_pages(pdf: bytes, limit: int) -> bytes:
    """The first `limit` pages of a PDF (Sarvam reads at most 30 per document)."""
    from pypdf import PdfReader, PdfWriter
    try:
        reader = PdfReader(io.BytesIO(pdf))
        if len(reader.pages) <= limit:
            return pdf
    except Exception:   # we cannot open it, Sarvam may still read it: send it as it is and let the page limit decide
        return pdf
    writer = PdfWriter()
    for page in reader.pages[:limit]:
        writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def pages_from_zip(blob: bytes) -> List[Tuple[int, str]]:
    """[(page number, text)] from the job's output: each page's blocks in reading order, or the Markdown split at its
    page breaks if there is no per-page metadata."""
    zf = zipfile.ZipFile(io.BytesIO(blob))
    pages = []
    for name in sorted(n for n in zf.namelist() if "/metadata/page_" in n and n.endswith(".json")):
        meta = json.loads(zf.read(name))
        blocks = sorted(meta.get("blocks", []), key=lambda b: b.get("reading_order", 0))
        text = "\n\n".join(b["text"].strip() for b in blocks if (b.get("text") or "").strip())
        if text:
            pages.append((int(meta.get("page_num", len(pages) + 1)), text))
    if pages:
        return pages
    md = next((zf.read(n).decode("utf-8", "replace") for n in zf.namelist() if n.endswith(".md")), "")
    return [(i, part.strip()) for i, part in enumerate(md.split("\n---\n"), start=1) if part.strip()]


async def read(data: bytes, content_type: str, language: str = "en-IN") -> Tuple[List[Tuple[int, str]], int]:
    """(pages, pages billed). Raises OcrError if Sarvam cannot read it."""
    if not supported(content_type):
        raise OcrError(f"OCR does not read {content_type}.")
    if not config.SARVAM_API_KEY:
        raise OcrError("SARVAM_API_KEY is not set.")
    if content_type == "application/pdf":
        data = await asyncio.to_thread(first_pages, data, config.OCR_MAX_PAGES)
    headers = {"api-subscription-key": config.SARVAM_API_KEY}
    async with httpx.AsyncClient(base_url=config.SARVAM_BASE_URL, timeout=60, transport=_transport) as client:
        r = await client.post("/doc-ai/v1/job/parse", headers=headers,
                              files={"file": (ACCEPTED[content_type], data, content_type)},
                              data={"language": language, "output_format": "md"})
        if r.status_code >= 300:
            raise OcrError(f"Sarvam refused the document ({r.status_code}): {r.text[:200]}")
        job = r.json()["job_id"]
        deadline, delay = time.monotonic() + config.OCR_TIMEOUT_SECONDS, 1.0
        while True:
            status = (await client.get(f"/doc-ai/v1/job/{job}/status", headers=headers)).json()
            if status.get("status") in TERMINAL:
                break
            if time.monotonic() > deadline:
                raise OcrError(f"OCR job {job} did not finish in {config.OCR_TIMEOUT_SECONDS} s.")
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 5.0)
        usage = status.get("usage") or {}
        billed = int(usage.get("pages_processed") or usage.get("pages_total") or 0)
        if status["status"] in ("failed", "rejected"):
            raise OcrError(f"OCR job {job} {status['status']}.")
        link = (await client.get(f"/doc-ai/v1/job/{job}/download-url", headers=headers)).json()["url"]
        blob = (await client.get(link)).content   # a pre-signed link: no key is sent with it
    pages = pages_from_zip(blob)
    if status["status"] == "partially_completed":
        log.warning("OCR job %s read %s of %s pages.", job, usage.get("pages_succeeded"), usage.get("pages_total"))
    return pages, billed
