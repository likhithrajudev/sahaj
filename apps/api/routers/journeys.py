"""Review and submit a simulated insurance claim or loan application."""
import hashlib
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field

from auth.deps import current_user
from auth.store import User
from journeys import rules, store
from services import telemetry
from storage import files, index
from trust import consent
from usage import ledger

router = APIRouter(prefix="/drafts", tags=["Demo drafts"])
MAX_UPLOAD = 8 * 1024 * 1024


class NewDraft(BaseModel):
    kind: Literal["claim", "loan"]


class Review(BaseModel):
    fields: dict[str, str] = Field(max_length=16)
    confirm: bool = False
    revision: int = Field(ge=0)


class Submission(BaseModel):
    revision: int = Field(ge=0)


def allowed(user):
    if not all(consent.is_active(user.subject, purpose) for purpose in ("documents", "document_analysis")):
        raise HTTPException(403, "Allow document storage and analysis to use this draft.")


def get_state(state):
    if state is None:
        raise HTTPException(404, "Draft not found.")
    return state


def editable(state, revision=None):
    get_state(state)
    if state["reference"]:
        raise HTTPException(409, "This demo submission is already complete.")
    if revision is not None and revision != state["revision"]:
        raise HTTPException(409, "The draft changed. Refresh it before saving.")


def invalidate(state):
    state["confirmed"] = False
    state["revision"] += 1


def owned(user: User = Depends(current_user)) -> User:
    allowed(user)
    return user


@router.get("")
async def list_drafts(user: User = Depends(owned)):
    return [rules.state_view(state) for state in await store.list_for(user.id)]


@router.post("", status_code=201)
async def new_draft(body: NewDraft, user: User = Depends(owned)):
    state = {"id": str(uuid4()), "kind": body.kind, "documents": [], "reviewed": {},
             "confirmed": False, "reference": None, "submitted_at": None, "revision": 0}
    await store.create(user.id, state)
    return rules.state_view(state)


@router.get("/{draft_id}")
async def get_draft(draft_id: UUID, user: User = Depends(owned)):
    async with store.draft(user.id, draft_id) as (_, state):
        return rules.state_view(get_state(state))


@router.post("/{draft_id}/attachments")
async def attach(draft_id: UUID, file: UploadFile, user: User = Depends(owned)):
    data = await file.read(MAX_UPLOAD + 1)
    if not data or len(data) > MAX_UPLOAD:
        raise HTTPException(422, "Choose a nonempty PDF, JPEG or PNG under 8 MiB.")
    sniffed = files.sniff(data)
    if not sniffed or sniffed[0] not in ("application/pdf", "image/jpeg", "image/png"):
        raise HTTPException(415, "Choose a PDF, JPEG or PNG.")
    kind = sniffed[0]
    digest = hashlib.sha256(data).hexdigest()
    async with store.draft(user.id, draft_id) as (_, state):
        editable(state)
        if any(doc["digest"] == digest for doc in state["documents"]):
            return rules.state_view(state)
        journey = state["kind"]
    if (await ledger.status(user.id))["exceeded"]:
        raise HTTPException(429, "This account has reached its monthly processing limit.")
    calls: list = []
    token = telemetry.current_meter.set(calls)
    channel = telemetry.current_channel.set("documents")
    try:
        pages, method = await index._text(data, kind, user.language or "en-IN")
    except Exception:
        raise HTTPException(422, "Couldn't read this file. Try a clear photo or a PDF with selectable text.") from None
    finally:
        telemetry.current_meter.reset(token)
        telemetry.current_channel.reset(channel)
        await ledger.add(user.id, calls)
    doc_type, fields = rules.extract_fields(journey, "\n".join(text for _, text in pages))
    if doc_type == "Other" or not fields:
        raise HTTPException(422, "Couldn't identify this document. For the demo, use a clear, labeled sample.")
    async with store.draft(user.id, draft_id, write=True) as (conn, state):
        allowed(user)  # OCR may have been running when the user withdrew consent
        editable(state)
        if any(doc["digest"] == digest for doc in state["documents"]):
            return rules.state_view(state)
        if any(doc["type"] == doc_type for doc in state["documents"]):
            raise HTTPException(409, f"Remove the current {doc_type.lower()} before replacing it.")
        attachment_id = str(uuid4())
        state["documents"].append({"id": attachment_id, "digest": digest, "filename": files.safe_name(file.filename),
                                   "type": doc_type, "fields": fields, "method": method})
        await conn.execute("INSERT INTO journey_attachments (id, draft_id, content_type, body) VALUES (%s,%s,%s,%s)",
                           (attachment_id, draft_id, kind, data))
        for key in fields:
            state["reviewed"].pop(key, None)
        invalidate(state)
        await store.save(conn, state)
        return rules.state_view(state)


@router.get("/{draft_id}/attachments/{attachment_id}")
async def attachment(draft_id: UUID, attachment_id: UUID, user: User = Depends(owned)):
    async with store.draft(user.id, draft_id) as (conn, state):
        get_state(state)
        cur = await conn.execute("SELECT content_type, body FROM journey_attachments WHERE id = %s AND draft_id = %s",
                                 (attachment_id, draft_id))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(404, "Attachment not found.")
        return Response(row[1], media_type=row[0], headers={"Cache-Control": "private, no-store"})


@router.delete("/{draft_id}/attachments/{attachment_id}")
async def remove(draft_id: UUID, attachment_id: UUID, user: User = Depends(owned)):
    async with store.draft(user.id, draft_id, write=True) as (conn, state):
        editable(state)
        doc = next((doc for doc in state["documents"] if doc["id"] == str(attachment_id)), None)
        if not doc:
            raise HTTPException(404, "Attachment not found.")
        await conn.execute("DELETE FROM journey_attachments WHERE id = %s AND draft_id = %s", (attachment_id, draft_id))
        state["documents"].remove(doc)
        for key in doc["fields"]:
            state["reviewed"].pop(key, None)
        invalidate(state)
        await store.save(conn, state)
        return rules.state_view(state)


@router.patch("/{draft_id}/review")
async def review(draft_id: UUID, body: Review, user: User = Depends(owned)):
    async with store.draft(user.id, draft_id, write=True) as (conn, state):
        editable(state, body.revision)
        labels = rules.state_view(state)["field_labels"]
        if body.fields.keys() - labels.keys():
            raise HTTPException(422, "This draft does not contain all supplied fields.")
        for key, raw in body.fields.items():
            value = raw.strip()
            if len(value) > 160:
                raise HTTPException(422, f"{labels[key]} is too long.")
            if value and key in rules.DATE_FIELDS:
                value = rules.date_value(value)
            elif value and key in rules.MONEY_FIELDS:
                value = rules.money(value)
            if raw.strip() and not value:
                raise HTTPException(422, f"Enter a valid {labels[key].lower()}.")
            state["reviewed"][key] = value
        state["confirmed"] = body.confirm
        state["revision"] += 1
        view = rules.state_view(state)
        admitted, discharged = (view["fields"].get(key) for key in ("admitted", "discharged"))
        if admitted and discharged and admitted > discharged:
            raise HTTPException(422, "Discharge date must be on or after admission.")
        if body.confirm and view["status"] != "ready":
            missing_documents = [label for label, present in view["checklist"].items() if not present]
            if missing_documents:
                raise HTTPException(422, f"Add the missing documents: {', '.join(missing_documents)}.")
            incomplete_fields = dict.fromkeys([*view["missing_fields"], *view["conflicts"]])
            raise HTTPException(422, f"Review these fields: {', '.join(labels[key] for key in incomplete_fields)}.")
        await store.save(conn, state)
        return view


@router.post("/{draft_id}/submit")
async def submit(draft_id: UUID, body: Submission, user: User = Depends(owned)):
    async with store.draft(user.id, draft_id, write=True) as (conn, state):
        get_state(state)
        if state["reference"]:
            return rules.state_view(state)
        editable(state, body.revision)
        if rules.state_view(state)["status"] != "ready":
            raise HTTPException(409, "Review and confirm the draft before submitting.")
        state["reference"] = f"DEMO-{state['kind'].upper()}-{uuid4().hex[:8].upper()}"
        state["submitted_at"] = datetime.now(timezone.utc).isoformat()
        state["revision"] += 1
        await store.save(conn, state)
        return rules.state_view(state)
