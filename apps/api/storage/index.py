"""Turns an uploaded PDF or photo into searchable, citable clauses that belong to one person.

A PDF with a text layer is read here; a scanned PDF or a photo (PNG, JPEG) is read by Sarvam's OCR (services/ocr.py).
Text is read page by page, split into short passages, masked for personal identifiers (PAN, Aadhaar, phone, account
numbers...) BEFORE it is embedded or stored, so the AI model is never shown them, and kept in `user_doc_chunks`. Each
passage is cited as [mydoc-<file>:p<page>.<n>], the same way the built-in knowledge base is."""
import asyncio
import io
import logging
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple

from pgvector import Vector
from psycopg.rows import dict_row

import config
from auth.store import db
from rag.embeddings import embed_passages
from services import ocr, telemetry
from trust.pii import Vault, normalise_digits

log = logging.getLogger("sahaj.docindex")
MAX_EXPANDED_DOCUMENT_BYTES = 64 * 1024 * 1024

SCHEMA = f"""
ALTER TABLE user_files ADD COLUMN IF NOT EXISTS index_status TEXT NOT NULL DEFAULT 'none';
ALTER TABLE user_files ADD COLUMN IF NOT EXISTS indexed_chunks INT NOT NULL DEFAULT 0;
ALTER TABLE user_files ADD COLUMN IF NOT EXISTS indexed_pages INT[] NOT NULL DEFAULT '{{}}';
ALTER TABLE user_files ADD COLUMN IF NOT EXISTS total_pages INT;
CREATE TABLE IF NOT EXISTS user_doc_chunks (
    id        BIGSERIAL PRIMARY KEY,
    user_id   UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    file_id   UUID NOT NULL REFERENCES user_files(id) ON DELETE CASCADE,
    clause    TEXT NOT NULL,
    page      INT NOT NULL,
    content   TEXT NOT NULL,
    embedding vector({int(config.EMBED_DIM)}) NOT NULL
);
CREATE INDEX IF NOT EXISTS user_doc_chunks_user_idx ON user_doc_chunks(user_id);
CREATE INDEX IF NOT EXISTS user_doc_chunks_file_idx ON user_doc_chunks(file_id);
"""
# index_status: none (not read), indexing, ready, empty (nothing readable), unsupported (a kind OCR cannot read),
# over_budget (the person's monthly limit is used up), failed


async def init_schema() -> None:
    import tenancy
    from rag.store import vector_dim
    from tenancy.db import create_tables
    with tenancy.system():
        async with db().connection() as conn:
            dim = await vector_dim(conn, "user_doc_chunks")
            if dim is not None and dim != config.EMBED_DIM:   # made by another embedding model: read the PDFs again
                log.warning("Document passages use %s dimensions; EMBED_DIM is %s. They will be rebuilt.", dim, config.EMBED_DIM)
                await conn.execute("DROP TABLE user_doc_chunks")
                await conn.execute("UPDATE user_files SET index_status = 'none', indexed_chunks = 0 WHERE index_status <> 'none'")
    await create_tables(db(), SCHEMA)


async def reindex_pending() -> int:
    """Read again every PDF whose owner allows document analysis but which has no passages (after a model change, or a
    failure). Runs at startup, in the background, one file at a time."""
    from psycopg.rows import dict_row
    from storage import blob
    from trust import consent
    import tenancy
    with tenancy.system():
        async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("""SELECT f.id, f.user_id, f.blob_name, f.content_type, f.tenant_id FROM user_files f
                             WHERE f.content_type IN ('application/pdf', 'image/png', 'image/jpeg', 'text/plain',
                               'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                               'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                               'application/vnd.openxmlformats-officedocument.presentationml.presentation')
                               AND f.index_status IN ('none', 'indexing', 'failed')""")
            rows = await cur.fetchall()
    done = 0
    for row in rows:
        if not consent.is_active(f"user:{row['user_id']}", "document_analysis"):
            continue
        try:
            data = b"".join([c async for c in blob.get().stream(row["blob_name"])])
        except Exception as e:
            log.warning("Could not fetch %s for re-indexing: %s", row["id"], e)
            continue
        with tenancy.as_tenant(row["tenant_id"]):   # read and stored as the file's own tenant
            if await index_file(str(row["user_id"]), str(row["id"]), data, row["content_type"]) == "ready":
                done += 1
    return done


def pdf_pages(data: bytes) -> List[Tuple[int, str]]:
    """[(page number, text)] for the first DOC_MAX_PAGES pages that have text. Raises on a file that cannot be parsed."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for number, page in enumerate(reader.pages[:config.DOC_MAX_PAGES], start=1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append((number, text))
    return pages


def passages(text: str, limit: int) -> List[str]:
    """Paragraphs grouped into pieces of at most `limit` characters; a longer paragraph is split at sentence ends."""
    pieces: List[str] = []
    for paragraph in re.split(r"\n\s*\n|\r\n\s*\r\n", text):
        paragraph = " ".join(paragraph.split())
        if not paragraph:
            continue
        sentences = re.split(r"(?<=[.!?।])\s+", paragraph) if len(paragraph) > limit else [paragraph]
        for sentence in sentences:
            while len(sentence) > limit:
                boundary = sentence.rfind(" ", 0, limit + 1)
                boundary = boundary if boundary > 0 else limit
                pieces.append(sentence[:boundary])
                sentence = sentence[boundary:].lstrip()
            if sentence:
                if pieces and len(pieces[-1]) + 1 + len(sentence) <= limit:
                    pieces[-1] += " " + sentence
                else:
                    pieces.append(sentence)
    return pieces


def chunk(pages: List[Tuple[int, str]], vault: Optional[Vault] = None) -> List[dict]:
    """Masked, labelled passages: [{"page", "clause", "content"}]. Capped at DOC_MAX_CHUNKS."""
    vault = vault or Vault()
    out = []
    for page, text in pages:
        for n, piece in enumerate(passages(text, config.DOC_CHUNK_CHARS), start=1):
            masked = vault.mask(normalise_digits(piece))
            if len(masked.strip()) < 20:   # page numbers, stray headings
                continue
            out.append({"page": page, "clause": f"p{page}.{n}", "content": masked})
            if len(out) >= config.DOC_MAX_CHUNKS:
                return out
    return out


async def _status(file_id: str, status: str, chunks: int = 0) -> None:
    async with db().connection() as conn:
        await conn.execute("UPDATE user_files SET index_status = %s, indexed_chunks = %s WHERE id = %s", (status, chunks, file_id))


async def _text(data: bytes, content_type: str, language: str) -> Tuple[List[Tuple[int, str]], str]:
    """(pages, how they were read). Text, office files and PDFs with a text layer are parsed locally; scanned PDFs
    and photos go to Sarvam OCR."""
    if content_type == "application/pdf":
        pages = await asyncio.to_thread(pdf_pages, data)
        if pages:
            return pages, "text"
    if content_type == "text/plain":
        text = data.decode("utf-8").strip()
        return ([(1, text)] if text else []), "text"
    if content_type.startswith("application/vnd.openxmlformats-officedocument."):
        pages = await asyncio.to_thread(office_pages, data, content_type)
        return pages, "text"
    if not ocr.supported(content_type):
        return [], "unsupported"
    pages, billed = await ocr.read(data, content_type, language)
    telemetry.meter({"kind": "ocr", "provider": "sarvam", "model": "sarvam-vision", "purpose": "ocr", "units": billed,
                     "cost_usd": billed * config.SARVAM_OCR_PRICE_PER_PAGE})
    return pages, "ocr"


def office_pages(data: bytes, content_type: str) -> List[Tuple[int, str]]:
    """Extract readable text from DOCX, XLSX and PPTX without executing document content."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if sum(item.file_size for item in members) > MAX_EXPANDED_DOCUMENT_BYTES:
            raise ValueError("The expanded office document is too large to read.")
        files = {item.filename for item in members}
        pages: List[Tuple[int, str]] = []

        def root(name: str):
            if name not in files:
                return None
            return ET.fromstring(archive.read(name))

        if content_type.endswith("wordprocessingml.document"):
            document = root("word/document.xml")
            if document is None:
                return []
            paragraphs = []
            for paragraph in document.iter():
                if paragraph.tag.endswith("}p"):
                    value = " ".join(node.text or "" for node in paragraph.iter() if node.tag.endswith("}t")).strip()
                    if value:
                        paragraphs.append(value)
            text = "\n".join(paragraphs)
            if text:
                pages.append((1, text))
        elif content_type.endswith("spreadsheetml.sheet"):
            shared_root = root("xl/sharedStrings.xml")
            shared = [] if shared_root is None else ["".join(n.text or "" for n in si.iter() if n.tag.endswith("}t"))
                                                      for si in shared_root if si.tag.endswith("}si")]
            sheet_names = sorted((n for n in files if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)),
                                 key=lambda n: int(re.search(r"sheet(\d+)", n).group(1)))
            for page, name in enumerate(sheet_names[:config.DOC_MAX_PAGES], 1):
                sheet = root(name)
                if sheet is None:
                    continue
                rows = []
                for row in sheet.iter():
                    if not row.tag.endswith("}row"):
                        continue
                    cells = []
                    for cell in row:
                        if not cell.tag.endswith("}c"):
                            continue
                        value = next((node.text for node in cell if node.tag.endswith("}v")), None)
                        if cell.attrib.get("t") == "s" and value is not None:
                            try:
                                value = shared[int(value)]
                            except (ValueError, IndexError):
                                value = ""
                        elif cell.attrib.get("t") == "inlineStr":
                            inline = next((node for node in cell if node.tag.endswith("}is")), None)
                            value = "" if inline is None else "".join(n.text or "" for n in inline.iter() if n.tag.endswith("}t"))
                        if value:
                            cells.append(f"{cell.attrib.get('r', '')}: {value}")
                    if cells:
                        rows.append(" | ".join(cells))
                if rows:
                    pages.append((page, "\n".join(rows)))
        elif content_type.endswith("presentationml.presentation"):
            slide_names = sorted((n for n in files if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                                 key=lambda n: int(re.search(r"slide(\d+)", n).group(1)))
            for page, name in enumerate(slide_names[:config.DOC_MAX_PAGES], 1):
                slide = root(name)
                if slide is None:
                    continue
                paragraphs = []
                for paragraph in slide.iter():
                    if paragraph.tag.endswith("}p"):
                        value = " ".join(node.text or "" for node in paragraph.iter() if node.tag.endswith("}t")).strip()
                        if value:
                            paragraphs.append(value)
                if paragraphs:
                    pages.append((page, "\n".join(paragraphs)))
        return pages


async def index_file(user_id: str, file_id: str, data: bytes, content_type: str, language: str = "en-IN") -> str:
    """Read, mask, embed and store one file. Returns the resulting index_status. Never raises.
    What it costs (OCR pages, embeddings) is charged to the person, and nothing is read once they are over their limit."""
    from usage import ledger as usage_ledger
    from trust import consent

    calls: list = []
    token = telemetry.current_meter.set(calls)
    channel = telemetry.current_channel.set("documents")
    try:
        if not consent.is_active(f"user:{user_id}", "document_analysis"):
            await _status(file_id, "none")
            return "none"
        if (await usage_ledger.status(user_id))["exceeded"]:
            await _status(file_id, "over_budget")
            return "over_budget"
        await _status(file_id, "indexing")
        pages, how = await _text(data, content_type, language)
        if how == "unsupported":
            await _status(file_id, "unsupported")
            return "unsupported"
        chunks = chunk(pages)
        if not chunks:
            await _status(file_id, "empty")
            return "empty"
        vectors = await embed_passages([c["content"] for c in chunks])
        if len(vectors) != len(chunks):
            raise RuntimeError("Embedding response did not cover all passages.")
        if content_type == "application/pdf":
            from pypdf import PdfReader
            try:
                total_pages = await asyncio.to_thread(lambda: len(PdfReader(io.BytesIO(data)).pages))
            except Exception:
                total_pages = None  # the OCR service can sometimes read a file that pypdf cannot
        else:
            total_pages = 1
        indexed_pages = sorted({c["page"] for c in chunks})
        async with db().connection() as conn:
            async with conn.transaction():
                row = await (await conn.execute("SELECT id FROM user_files WHERE id = %s AND user_id = %s FOR UPDATE",
                                                (file_id, user_id))).fetchone()
                if not row or not consent.is_active(f"user:{user_id}", "document_analysis"):
                    return "none"
                await conn.execute("DELETE FROM user_doc_chunks WHERE file_id = %s", (file_id,))
                for c, v in zip(chunks, vectors):
                    await conn.execute(
                        "INSERT INTO user_doc_chunks (user_id, file_id, clause, page, content, embedding) VALUES (%s, %s, %s, %s, %s, %s)",
                        (user_id, file_id, c["clause"], c["page"], c["content"], Vector(v)))
                await conn.execute(
                    "UPDATE user_files SET index_status = 'ready', indexed_chunks = %s, indexed_pages = %s, total_pages = %s WHERE id = %s",
                    (len(chunks), indexed_pages, total_pages, file_id),
                )
        log.info("Read file %s (%s, %d passages).", file_id, how, len(chunks))
        return "ready"
    except Exception as e:   # a bad file, an OCR failure or a missing key must not take anything down
        log.warning("Could not index file %s: %s", file_id, e)
        try:
            await _status(file_id, "failed")
        except Exception:
            pass
        return "failed"
    finally:
        telemetry.current_meter.reset(token)
        telemetry.current_channel.reset(channel)
        await usage_ledger.add(user_id, calls)


async def forget(user_id: str) -> int:
    """Remove everything learned from the person's documents (the files themselves stay)."""
    async with db().connection() as conn:
        cur = await conn.execute("DELETE FROM user_doc_chunks WHERE user_id = %s", (user_id,))
        await conn.execute("UPDATE user_files SET index_status = 'none', indexed_chunks = 0, indexed_pages = '{}', total_pages = NULL WHERE user_id = %s", (user_id,))
        return cur.rowcount


async def has_documents(user_id: str) -> bool:
    async with db().connection() as conn:
        cur = await conn.execute("SELECT 1 FROM user_doc_chunks WHERE user_id = %s LIMIT 1", (user_id,))
        return await cur.fetchone() is not None


async def search(user_id: str, vector: List[float], k: int, file_id: Optional[str] = None) -> List[dict]:
    """The person's own passages closest to `vector`, shaped like knowledge-base hits."""
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """SELECT c.file_id, c.clause, c.page, c.content, f.filename, 1 - (c.embedding <=> %(v)s) AS similarity
               FROM user_doc_chunks c JOIN user_files f ON f.id = c.file_id
               WHERE c.user_id = %(u)s AND f.index_status = 'ready'
                 AND (%(f)s::uuid IS NULL OR c.file_id = %(f)s::uuid)
               ORDER BY c.embedding <=> %(v)s LIMIT %(k)s""",
            {"v": Vector(vector), "u": user_id, "k": k, "f": file_id})
        rows = await cur.fetchall()
    return [{"key": f"mydoc-{str(r['file_id'])[:8]}:{r['clause']}",
             "text": f'(From your document "{r["filename"]}", page {r["page"]}) {r["content"]}',
             "sha256": "", "similarity": float(r["similarity"]), "personal": True,
             "citation": {"doc": r["filename"], "file_id": str(r["file_id"]), "page": r["page"], "body": r["content"]}} for r in rows]
