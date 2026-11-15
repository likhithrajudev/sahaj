"""Turns an uploaded PDF into searchable, citable clauses that belong to one person.

Text is read page by page, split into short passages, masked for personal identifiers (PAN, Aadhaar, phone, account
numbers...) BEFORE it is embedded or stored, so the AI model is never shown them, and kept in `user_doc_chunks`. Each
passage is cited as [mydoc-<file>:p<page>.<n>], the same way the built-in knowledge base is."""
import asyncio
import io
import logging
import re
from typing import List, Optional, Tuple

from pgvector import Vector
from psycopg.rows import dict_row

import config
from auth.store import db
from rag.embeddings import embed_passages
from trust.pii import Vault, normalise_digits

log = logging.getLogger("sahaj.docindex")

SCHEMA = f"""
ALTER TABLE user_files ADD COLUMN IF NOT EXISTS index_status TEXT NOT NULL DEFAULT 'none';
ALTER TABLE user_files ADD COLUMN IF NOT EXISTS indexed_chunks INT NOT NULL DEFAULT 0;
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
# index_status: none (not read), indexing, ready, empty (no readable text, e.g. a scan), unsupported (an image), failed


async def init_schema() -> None:
    from rag.store import vector_dim
    async with db().connection() as conn:
        dim = await vector_dim(conn, "user_doc_chunks")
        if dim is not None and dim != config.EMBED_DIM:   # made by another embedding model: read the PDFs again
            log.warning("Document passages use %s dimensions; EMBED_DIM is %s. They will be rebuilt.", dim, config.EMBED_DIM)
            await conn.execute("DROP TABLE user_doc_chunks")
            await conn.execute("UPDATE user_files SET index_status = 'none', indexed_chunks = 0 WHERE index_status <> 'none'")
        await conn.execute(SCHEMA)


async def reindex_pending() -> int:
    """Read again every PDF whose owner allows document analysis but which has no passages (after a model change, or a
    failure). Runs at startup, in the background, one file at a time."""
    from psycopg.rows import dict_row
    from storage import blob
    from trust import consent
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("""SELECT f.id, f.user_id, f.blob_name, f.content_type FROM user_files f
                             WHERE f.content_type = 'application/pdf' AND f.index_status IN ('none', 'failed')""")
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
            sentence = sentence[:limit]
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


async def index_file(user_id: str, file_id: str, data: bytes, content_type: str) -> str:
    """Read, mask, embed and store one file. Returns the resulting index_status. Never raises."""
    try:
        if content_type != "application/pdf":
            await _status(file_id, "unsupported")
            return "unsupported"
        await _status(file_id, "indexing")
        pages = await asyncio.to_thread(pdf_pages, data)
        chunks = chunk(pages)
        if not chunks:
            await _status(file_id, "empty")
            return "empty"
        vectors = await embed_passages([c["content"] for c in chunks])
        async with db().connection() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM user_doc_chunks WHERE file_id = %s", (file_id,))
                for c, v in zip(chunks, vectors):
                    await conn.execute(
                        "INSERT INTO user_doc_chunks (user_id, file_id, clause, page, content, embedding) VALUES (%s, %s, %s, %s, %s, %s)",
                        (user_id, file_id, c["clause"], c["page"], c["content"], Vector(v)))
        await _status(file_id, "ready", len(chunks))
        return "ready"
    except Exception as e:   # a bad PDF or a missing model must not take anything down
        log.warning("Could not index file %s: %s", file_id, e)
        try:
            await _status(file_id, "failed")
        except Exception:
            pass
        return "failed"


async def forget(user_id: str) -> int:
    """Remove everything learned from the person's documents (the files themselves stay)."""
    async with db().connection() as conn:
        cur = await conn.execute("DELETE FROM user_doc_chunks WHERE user_id = %s", (user_id,))
        await conn.execute("UPDATE user_files SET index_status = 'none', indexed_chunks = 0 WHERE user_id = %s", (user_id,))
        return cur.rowcount


async def has_documents(user_id: str) -> bool:
    async with db().connection() as conn:
        cur = await conn.execute("SELECT 1 FROM user_doc_chunks WHERE user_id = %s LIMIT 1", (user_id,))
        return await cur.fetchone() is not None


async def search(user_id: str, vector: List[float], k: int) -> List[dict]:
    """The person's own passages closest to `vector`, shaped like knowledge-base hits."""
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """SELECT c.file_id, c.clause, c.page, c.content, f.filename, 1 - (c.embedding <=> %(v)s) AS similarity
               FROM user_doc_chunks c JOIN user_files f ON f.id = c.file_id
               WHERE c.user_id = %(u)s ORDER BY c.embedding <=> %(v)s LIMIT %(k)s""",
            {"v": Vector(vector), "u": user_id, "k": k})
        rows = await cur.fetchall()
    return [{"key": f"mydoc-{str(r['file_id'])[:8]}:{r['clause']}",
             "text": f'(From your document "{r["filename"]}", page {r["page"]}) {r["content"]}',
             "sha256": "", "similarity": float(r["similarity"]), "personal": True} for r in rows]
