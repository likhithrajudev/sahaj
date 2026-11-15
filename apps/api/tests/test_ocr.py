"""OCR through Sarvam's Document AI, against a mock of its API: the job flow, page rebuilding, failures, and the cost."""
import asyncio
import io
import json
import os
import sys
import zipfile
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from services import ocr, telemetry
from trust import ledger


def zip_output(pages, md=None, with_metadata=True):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", json.dumps({"status": "completed"}))
        z.writestr("document.pdf/document.md", md or "\n\n---\n\n".join(t for _, t in pages))
        if with_metadata:
            for n, text in pages:
                # blocks deliberately out of reading order
                parts = text.split(" | ")
                blocks = [{"text": p, "reading_order": i + 1} for i, p in enumerate(parts)][::-1]
                z.writestr(f"document.pdf/metadata/page_{n:03d}.json", json.dumps({"page_num": n, "blocks": blocks}))
    return buf.getvalue()


class FakeSarvam:
    """Enough of the Document AI API: create, status (pending then the final state), download link, the zip."""

    def __init__(self, pages, final="completed", polls_before_done=2, create_status=201):
        self.pages, self.final, self.left, self.create_status = pages, final, polls_before_done, create_status
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/doc-ai/v1/job/parse":
            if self.create_status >= 300:
                return httpx.Response(self.create_status, json={"error": "nope"})
            return httpx.Response(201, json={"job_id": "job-1", "status": "pending"})
        if path.endswith("/status"):
            if self.left > 0:
                self.left -= 1
                return httpx.Response(200, json={"status": "running"})
            return httpx.Response(200, json={"status": self.final, "usage": {"pages_total": len(self.pages),
                                                                             "pages_processed": len(self.pages)}})
        if path.endswith("/download-url"):
            return httpx.Response(200, json={"method": "GET", "url": "https://files.example/out.zip"})
        if request.url.host == "files.example":
            return httpx.Response(200, content=zip_output(self.pages))
        return httpx.Response(404)


@pytest.fixture
def sarvam(monkeypatch):
    monkeypatch.setattr(config, "SARVAM_API_KEY", "sk-sarvam-test")

    async def no_wait(_):
        return None
    monkeypatch.setattr(ocr.asyncio, "sleep", no_wait)

    def install(fake):
        monkeypatch.setattr(ocr, "_transport", httpx.MockTransport(fake))
        return fake
    return install


def test_reads_pages_in_reading_order_and_reports_pages_billed(sarvam):
    fake = sarvam(FakeSarvam([(1, "FINAL BILL | Room rent Rs 9000"), (2, "Pharmacy Rs 2450 | Total Rs 11450")]))
    pages, billed = asyncio.run(ocr.read(b"\x89PNG\r\n\x1a\n...", "image/png", "hi-IN"))
    assert pages == [(1, "FINAL BILL\n\nRoom rent Rs 9000"), (2, "Pharmacy Rs 2450\n\nTotal Rs 11450")] and billed == 2
    create = fake.requests[0]
    assert create.headers["api-subscription-key"] == "sk-sarvam-test"
    body = create.content.decode("latin-1")
    assert 'name="language"' in body and "hi-IN" in body and 'name="output_format"' in body and "md" in body
    assert 'filename="page.png"' in body                                         # never the person's own filename
    download = next(r for r in fake.requests if r.url.host == "files.example")
    assert "api-subscription-key" not in download.headers                        # the key is not sent to the file link


def test_markdown_is_used_when_there_is_no_page_metadata():
    blob = zip_output([(1, "one"), (2, "two")], md="Page one text\n\n---\n\nPage two text", with_metadata=False)
    assert ocr.pages_from_zip(blob) == [(1, "Page one text"), (2, "Page two text")]


@pytest.mark.parametrize("fake, message", [
    (FakeSarvam([], final="failed"), "failed"), (FakeSarvam([], final="rejected"), "rejected"),
    (FakeSarvam([], create_status=422), "refused"),
])
def test_failures_raise(sarvam, fake, message):
    sarvam(fake)
    with pytest.raises(ocr.OcrError, match=message):
        asyncio.run(ocr.read(b"%PDF-1.4", "application/pdf"))


def test_a_job_that_never_finishes_times_out(sarvam, monkeypatch):
    sarvam(FakeSarvam([(1, "x")], polls_before_done=10**6))
    monkeypatch.setattr(config, "OCR_TIMEOUT_SECONDS", 0)
    with pytest.raises(ocr.OcrError, match="did not finish"):
        asyncio.run(ocr.read(b"\xff\xd8\xff", "image/jpeg"))


def test_only_pdfs_and_photos_go_to_ocr(sarvam):
    assert ocr.supported("image/png") and ocr.supported("image/jpeg") and ocr.supported("application/pdf")
    assert not ocr.supported("image/webp") and not ocr.supported("text/plain")
    with pytest.raises(ocr.OcrError):
        asyncio.run(ocr.read(b"GIF89a", "image/gif"))


def test_long_scans_are_cut_to_sarvams_page_limit():
    from pypdf import PdfReader
    from tests.test_documents import make_pdf
    pdf = make_pdf([f"page {i}" for i in range(35)])
    assert len(PdfReader(io.BytesIO(ocr.first_pages(pdf, 30))).pages) == 30
    short = make_pdf(["one", "two"])
    assert ocr.first_pages(short, 30) == short


# ---------------------------------------------------------------- reading a document into the person's index (Postgres)
DB = os.getenv("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB, reason="set TEST_DATABASE_URL to run the Postgres tests")


@needs_db
def test_scans_and_photos_are_read_by_ocr_masked_and_charged_to_the_person(sarvam, monkeypatch, tmp_path):
    from psycopg_pool import AsyncConnectionPool
    from auth import store
    from rag import store as rag_store
    from storage import files, index
    from tests.test_documents import embed, make_pdf
    from usage import ledger as usage_ledger

    monkeypatch.setattr(config, "LEDGER_DB", str(tmp_path / "ledger.db"))
    monkeypatch.setattr(ledger, "_conn", None)
    monkeypatch.setattr(config, "DATABASE_URL", DB)

    async def vectors(texts):
        return [embed(t) for t in texts]
    monkeypatch.setattr(index, "embed_passages", vectors)

    async def scenario():
        await rag_store.init_schema()
        pool = AsyncConnectionPool(DB, min_size=1, max_size=3, open=False, configure=rag_store._configure, kwargs={"autocommit": True})
        await pool.open(wait=True)
        monkeypatch.setattr(rag_store, "_pool", pool)
        try:
            await store.init_schema(); await files.init_schema(); await index.init_schema(); await usage_ledger.init_schema()
            from tests.dbsetup import init_all
            await init_all()
            async with pool.connection() as conn:
                await conn.execute("TRUNCATE users CASCADE")
            user = await store.upsert_google_user({"sub": "g-1", "email": "a@example.com"}, "web")

            async def add(content_type, data):
                row = await files.add(user.id, "x", content_type, data, f"{user.username}/x/{len(data)}{content_type[-3:]}", "document")
                return str(row["id"])

            # a photo of a bill: read by OCR, identifiers masked before storage, OCR pages billed to the person
            fake = sarvam(FakeSarvam([(1, "CITY HOSPITAL FINAL BILL | Patient PAN ABCDE1234F, phone 98765 43210 | Total payable Rs 11450")]))
            photo = await add("image/png", b"\x89PNG\r\n\x1a\nphoto")
            assert await index.index_file(user.id, photo, b"\x89PNG\r\n\x1a\nphoto", "image/png") == "ready"
            async with pool.connection() as conn:
                (text,) = (await (await conn.execute("SELECT content FROM user_doc_chunks WHERE file_id = %s", (photo,))).fetchone())
            assert "ABCDE1234F" not in text and "9876543210" not in text and "[PAN_1]" in text and "11450" in text
            assert any(r.url.path == "/doc-ai/v1/job/parse" for r in fake.requests)

            # a PDF with a text layer is read here, for free: Sarvam is not called
            fake = sarvam(FakeSarvam([(1, "should not be used")]))
            text_pdf = make_pdf(["The prepayment charge is 2 percent of the amount prepaid."])
            doc = await add("application/pdf", text_pdf)
            assert await index.index_file(user.id, doc, text_pdf, "application/pdf") == "ready" and fake.requests == []

            # a scanned PDF (no text layer) goes to OCR
            fake = sarvam(FakeSarvam([(1, "Discharge summary | Admitted 12 Nov, discharged 15 Nov")]))
            scan = make_pdf([""])
            sid = await add("application/pdf", scan)
            assert await index.index_file(user.id, sid, scan, "application/pdf") == "ready" and fake.requests

            # what reading cost is in the person's ledger: OCR pages and embeddings
            summary = await usage_ledger.summary(user.id)
            assert summary["by_kind"].get("ocr") == pytest.approx(2 * config.SARVAM_OCR_PRICE_PER_PAGE)
            assert summary["by_channel"] == {"documents": pytest.approx(summary["spent_usd"])}

            # OCR failing leaves the file "failed", not a crash; and nothing is read once the limit is used up
            sarvam(FakeSarvam([], final="failed"))
            bad = await add("image/jpeg", b"\xff\xd8\xffbad")
            assert await index.index_file(user.id, bad, b"\xff\xd8\xffbad", "image/jpeg") == "failed"
            await usage_ledger.set_budget(user.id, 0.0001)
            fake = sarvam(FakeSarvam([(1, "x")]))
            late = await add("image/png", b"\x89PNG\r\n\x1a\nlate")
            assert await index.index_file(user.id, late, b"\x89PNG\r\n\x1a\nlate", "image/png") == "over_budget" and fake.requests == []
            # a WebP is kept but cannot be read
            await usage_ledger.set_budget(user.id, None)
            webp = await add("image/webp", b"RIFF....WEBP")
            assert await index.index_file(user.id, webp, b"RIFF....WEBP", "image/webp") == "unsupported"
        finally:
            await pool.close()
    asyncio.run(scenario())
