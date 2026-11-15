import asyncio
import logging
from urllib.parse import quote

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import config
from auth.deps import current_user
from auth.store import User
from gateway.middleware import client_ip
from observability.metrics import FILE_EVENTS
from storage import blob, files, index
from routers.consents import fail
from trust import consent, consents

log = logging.getLogger("sahaj.files")
router = APIRouter(prefix="/files", tags=["Files"])


class ConsentUpdate(BaseModel):
    """Kept for existing clients. New code should use PUT /consents/{purpose}, which requires the shown `version`."""
    granted: bool
    version: Optional[str] = None


_tasks: set = set()   # background indexing jobs, kept so they are not garbage collected mid-run


def _public(row: dict) -> dict:
    return {"id": str(row["id"]), "filename": row["filename"], "content_type": row["content_type"],
            "size_bytes": row["size_bytes"], "sha256": row["sha256"], "created_at": row["created_at"],
            "index_status": row.get("index_status", "none"), "indexed_chunks": row.get("indexed_chunks", 0),
            "category": row.get("category", "document")}


def _owns_blob(user: User, row: dict) -> bool:
    prefixes = (f"{files.folder(user)}/", f"users/{user.id}/")
    return isinstance(row.get("blob_name"), str) and row["blob_name"].startswith(prefixes)


def index_readable(content_type: str) -> bool:
    """PDFs, common office documents, text and photos can be read; other uploads are kept but not read."""
    return content_type in ("application/pdf", "image/png", "image/jpeg", "text/plain",
                             "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             "application/vnd.openxmlformats-officedocument.presentationml.presentation")


def _ocr_language(language: Optional[str]) -> str:
    return language if language in ("hi-IN", "bn-IN", "ta-IN", "te-IN", "mr-IN", "gu-IN", "kn-IN", "ml-IN", "od-IN", "pa-IN") else "en-IN"


def _index_in_background(user_id: str, file_id: str, data: bytes, content_type: str, language: Optional[str] = None) -> None:
    task = asyncio.create_task(index.index_file(user_id, file_id, data, content_type, _ocr_language(language)))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


@router.get("")
async def list_files(category: Optional[str] = Query(None, description="image, document, audio, voice or transcript"),
                     user: User = Depends(current_user)):
    return {"consent": consent.is_active(user.subject, "documents"), "consent_text": consent.required("documents"),
            "analysis_consent": consent.is_active(user.subject, "document_analysis"),
            "analysis_consent_text": consent.required("document_analysis"),
            "limits": {"max_bytes": config.MAX_UPLOAD_BYTES, "max_files": config.MAX_FILES_PER_USER,
                       "types": ["images (PNG, JPEG, WebP, GIF)", "PDF", "Word, Excel, PowerPoint", "plain text",
                                 "audio (WAV, MP3, OGG, FLAC, M4A, WebM)"]},
            "folder": f"{files.folder(user)}/",
            "items": [_public(r) for r in await files.list_for(user.id, category) if _owns_blob(user, r)]}


@router.put("/consent")
async def set_consent(body: ConsentUpdate, request: Request, user: User = Depends(current_user)):
    """Allow or stop storing documents. Stopping deletes every stored file (and ends document analysis). Same as
    PUT /consents/documents."""
    try:
        result = await consents.set_consent(user, "documents", body.granted, channel="api", version=body.version, ip=client_ip(request.scope))
    except consents.ConsentError as e:
        raise fail(e)
    return {"consent": body.granted, "deleted": result["erased"].get("files", 0)}


@router.post("", status_code=201)
async def upload(file: UploadFile, user: User = Depends(current_user)):
    """Store one file in the person's folder (<username>/images, documents or audio), up to MAX_UPLOAD_BYTES: images, PDFs,
    Word/Excel/PowerPoint files, plain text and audio. Needs the 'documents' consent."""
    store = blob.get()   # 503 first if storage is not configured
    if not consent.is_active(user.subject, "documents"):
        raise HTTPException(403, "Documents consent is needed first: PUT /consents/documents.")
    if await files.count(user.id) >= config.MAX_FILES_PER_USER:
        raise HTTPException(409, f"You can store up to {config.MAX_FILES_PER_USER} files. Delete one first.")
    data = await file.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"The file is larger than {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    if not data:
        raise HTTPException(400, "The file is empty.")
    sniffed = files.sniff(data)
    if sniffed is None:
        FILE_EVENTS.labels("rejected_type").inc()
        raise HTTPException(415, "That file type is not accepted. Images, PDFs, Word/Excel/PowerPoint files, plain text and audio are.")
    kind, category, ext = sniffed
    name = files.blob_name(files.folder(user), category, ext)
    await store.put(name, data, kind)
    try:
        row = await files.add(user.id, files.safe_name(file.filename), kind, data, name, category)
    except Exception:
        await store.delete(name)   # no record, so no orphan blob
        raise
    FILE_EVENTS.labels("uploaded").inc()
    if index_readable(kind) and consent.is_active(user.subject, "document_analysis"):   # read it so questions can be asked about it
        _index_in_background(user.id, str(row["id"]), data, kind, user.language)
        row = {**row, "index_status": "indexing"}
    return _public(row)


@router.put("/analysis/consent")
async def set_analysis_consent(body: ConsentUpdate, request: Request, user: User = Depends(current_user)):
    """Allow or stop Sahaj reading your PDFs to answer questions about them. Allowing also reads the PDFs already
    stored; stopping removes what was learned from them (the files stay). Same as PUT /consents/document_analysis."""
    try:
        result = await consents.set_consent(user, "document_analysis", body.granted, channel="api", version=body.version, ip=client_ip(request.scope))
    except consents.ConsentError as e:
        raise fail(e)
    if not body.granted:
        return {"consent": False, "forgotten": result["erased"].get("document_passages", 0)}
    queued = 0
    for row in await files.list_for(user.id):
        if _owns_blob(user, row) and index_readable(row["content_type"]) and row["index_status"] in ("none", "failed", "over_budget"):
            full = await files.get(user.id, str(row["id"]))
            data = b"".join([c async for c in blob.get().stream(full["blob_name"])])
            _index_in_background(user.id, str(row["id"]), data, row["content_type"], user.language)
            queued += 1
    return {"consent": True, "queued": queued}


@router.get("/{file_id}")
async def download(file_id: str, user: User = Depends(current_user)):
    """The file itself, to its owner only."""
    row = await files.get(user.id, file_id)
    if row is None or not _owns_blob(user, row):
        raise HTTPException(404, "No such file.")
    FILE_EVENTS.labels("downloaded").inc()
    return StreamingResponse(blob.get().stream(row["blob_name"]), media_type=row["content_type"], headers={
        "Content-Disposition": f"attachment; filename=\"{row['filename']}\"; filename*=UTF-8''{quote(row['filename'])}",
        "Content-Length": str(row["size_bytes"]), "Cache-Control": "private, no-store"})


@router.delete("/{file_id}", status_code=204)
async def delete(file_id: str, user: User = Depends(current_user)):
    row = await files.get(user.id, file_id)
    if row is None or not _owns_blob(user, row):
        raise HTTPException(404, "No such file.")
    await blob.get().delete(row["blob_name"])
    await files.remove(user.id, file_id)
    FILE_EVENTS.labels("deleted").inc()
    return Response(status_code=204)
