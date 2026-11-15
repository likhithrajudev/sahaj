"""Uploaded files: the bytes live in blob storage, the record (owner, name, type, size, hash) in Postgres."""
import hashlib
import io
import re
import unicodedata
import uuid
import zipfile
from typing import List, Optional

from psycopg.rows import dict_row

import config
from auth.store import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_files (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename     TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes   BIGINT NOT NULL,
    sha256       TEXT NOT NULL,
    blob_name    TEXT NOT NULL UNIQUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    index_status TEXT NOT NULL DEFAULT 'none',
    indexed_chunks INT NOT NULL DEFAULT 0
);
ALTER TABLE user_files ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'document';
CREATE INDEX IF NOT EXISTS user_files_user_idx ON user_files(user_id, created_at DESC);
"""

# Where each kind of file lives under the person's folder: <username>/<folder>/<id>.<ext>
FOLDERS = {"image": "images", "document": "documents", "audio": "audio",
           "voice": "voice", "transcript": "transcripts"}   # voice and transcript are recorded by Sahaj, not uploaded
UPLOADABLE = ("image", "document", "audio")
RECORDINGS = ("voice", "transcript")   # made only with the conversation_records consent


def _ooxml(b: bytes) -> Optional[tuple]:
    """Word, Excel and PowerPoint files are zip archives; the folder names inside say which. Nothing is extracted."""
    if not b.startswith(b"PK\x03\x04"):
        return None
    try:
        names = zipfile.ZipFile(io.BytesIO(b)).namelist()
    except (zipfile.BadZipFile, OSError):
        return None
    if "[Content_Types].xml" not in names:
        return None
    for prefix, kind, ext in (("word/", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
                              ("xl/", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
                              ("ppt/", "application/vnd.openxmlformats-officedocument.presentationml.presentation", "pptx")):
        if any(n.startswith(prefix) for n in names):
            return kind, "document", ext
    return None


_CONTROL = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f]")   # anything in a text file that is not a tab, newline or printable


def _text(b: bytes) -> Optional[tuple]:
    """Plain text: valid UTF-8 throughout and nothing but tabs, newlines and printable characters. The whole file is
    checked (uploads are capped, so this is cheap)."""
    if not b:
        return None
    try:
        text = b.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if _CONTROL.search(text):
        return None
    return "text/plain", "document", "txt"


# What is accepted, decided from the bytes and never from the name or the type the caller declared. Anything else
# (programs, scripts, archives, video) is refused.
SIGNATURES = [
    (lambda b: b.startswith(b"%PDF-"), ("application/pdf", "document", "pdf")),
    (lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"), ("image/png", "image", "png")),
    (lambda b: b.startswith(b"\xff\xd8\xff"), ("image/jpeg", "image", "jpg")),
    (lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP", ("image/webp", "image", "webp")),
    (lambda b: b[:6] in (b"GIF87a", b"GIF89a"), ("image/gif", "image", "gif")),
    (lambda b: b[:4] == b"RIFF" and b[8:12] == b"WAVE", ("audio/wav", "audio", "wav")),
    (lambda b: b.startswith(b"ID3") or b[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"), ("audio/mpeg", "audio", "mp3")),
    (lambda b: b.startswith(b"OggS"), ("audio/ogg", "audio", "ogg")),
    (lambda b: b.startswith(b"fLaC"), ("audio/flac", "audio", "flac")),
    (lambda b: b[4:8] == b"ftyp", ("audio/mp4", "audio", "m4a")),
    (lambda b: b.startswith(b"\x1a\x45\xdf\xa3"), ("audio/webm", "audio", "webm")),   # browser recordings (MediaRecorder)
    (_ooxml, None),
    (_text, None),
]


def sniff(data: bytes) -> Optional[tuple]:
    """(content type, category, extension) of an accepted file, or None."""
    for test, result in SIGNATURES:
        try:
            matched = test(data)
        except Exception:
            matched = None
        if matched:
            return result or matched
    return None


def safe_name(name: Optional[str]) -> str:
    """A display name with no path, control characters or surprises."""
    name = unicodedata.normalize("NFC", (name or "file").replace("\\", "/").split("/")[-1])
    name = re.sub(r"[\x00-\x1f\x7f\"<>|:*?]", "", name).strip(". ")
    return name[:120] or "file"


def folder(user) -> str:
    """The person's folder: <tenant>/<username>. The tenant comes first, so one tenant's files never share a prefix with
    another's, and a tenant's whole data can be listed, exported or deleted by prefix."""
    return f"{user.tenant_id}/{user.username}"


def blob_name(owner: str, category: str, ext: str, *, group: Optional[str] = None, stem: Optional[str] = None) -> str:
    """The key of a stored file: <tenant>/<username>/<folder>/[<group>/]<id>.<ext> (`owner` is `folder(user)`). Every part
    comes from our own checked values (tenant and username are derived and sanitised, the extension from what the bytes
    are), never from what the caller typed."""
    parts = [owner, FOLDERS[category]] + ([group] if group else [])
    return "/".join(parts + [f"{stem or uuid.uuid4().hex}.{ext}"])


def prefixes(user, categories: Optional[tuple] = None) -> List[str]:
    """Key prefixes under which a person's files live (plus the earlier users/<id>/ layout, so nothing is left behind)."""
    folders = [FOLDERS[c] for c in (categories or tuple(FOLDERS))]
    found = [f"{folder(user)}/{f}/" for f in folders]
    return found + ([f"users/{user.id}/"] if categories is None else [])


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def init_schema() -> None:
    from tenancy.db import create_tables
    await create_tables(db(), SCHEMA)


async def add(user_id: str, filename: str, content_type: str, data: bytes, blob: str, category: str = "document") -> dict:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """INSERT INTO user_files (user_id, filename, content_type, size_bytes, sha256, blob_name, category)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               RETURNING id, filename, content_type, size_bytes, sha256, blob_name, created_at, index_status, indexed_chunks, category""",
            (user_id, filename, content_type, len(data), digest(data), blob, category))
        return await cur.fetchone()


async def count(user_id: str) -> int:
    """Files the person uploaded themselves (recordings Sahaj makes do not count against their limit)."""
    async with db().connection() as conn:
        cur = await conn.execute("SELECT count(*) FROM user_files WHERE user_id = %s AND category = ANY(%s)",
                                 (user_id, list(UPLOADABLE)))
        return (await cur.fetchone())[0]


async def list_for(user_id: str, category: Optional[str] = None) -> List[dict]:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT id, filename, content_type, size_bytes, sha256, blob_name, created_at, index_status, indexed_chunks, category "
                          "FROM user_files WHERE user_id = %(u)s AND (%(c)s::text IS NULL OR category = %(c)s) "
                          "ORDER BY created_at DESC", {"u": user_id, "c": category})
        return await cur.fetchall()


async def get(user_id: str, file_id: str) -> Optional[dict]:
    try:
        uuid.UUID(file_id)
    except ValueError:
        return None
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM user_files WHERE user_id = %s AND id = %s", (user_id, file_id))
        return await cur.fetchone()


async def remove(user_id: str, file_id: str) -> None:
    async with db().connection() as conn:
        await conn.execute("DELETE FROM user_files WHERE user_id = %s AND id = %s", (user_id, file_id))


async def purge(user, categories: Optional[tuple] = None) -> int:
    """Delete a person's files, all of them or only some categories: the blobs first (so none is left without a record
    pointing at it), then the records. Returns how many files there were."""
    from auth.store import Unavailable
    from storage import blob
    cats = list(categories or FOLDERS)
    async with db().connection() as conn:
        names = [r[0] for r in await (await conn.execute("SELECT blob_name FROM user_files WHERE user_id = %s AND category = ANY(%s)",
                                                         (user.id, cats))).fetchall()]
    try:
        store, covered = blob.get(), tuple(prefixes(user, categories))
        allowed = covered + (f"users/{user.id}/",)
        for prefix in covered:
            await store.delete_prefix(prefix)
        for name in names:                    # anything stored elsewhere (an earlier layout) is removed by name
            if name.startswith(allowed) and not name.startswith(covered):
                await store.delete(name)
    except Unavailable:
        pass   # storage was never set up, so nothing is stored
    async with db().connection() as conn:
        await conn.execute("DELETE FROM user_files WHERE user_id = %s AND category = ANY(%s)", (user.id, cats))
    return len(names)
