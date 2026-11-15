import time
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from auth import feedback as feedback_store, store
from auth.deps import current_user, require_role
from memory import store as memory_store
from gateway.middleware import client_ip
from routers.consents import fail
from storage import files as file_store
from trust import consent, consents, ledger

router = APIRouter(tags=["Users"])


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    language: Optional[str] = Field(None, pattern=r"^[a-z]{2}-IN$", description="For example en-IN, hi-IN")
    platform: Optional[Literal["web", "android", "ios"]] = None


class ConsentUpdate(BaseModel):
    """Kept for existing clients. New code should use PUT /consents/{purpose}, which requires the shown `version`."""
    granted: bool
    version: Optional[str] = None


class RoleUpdate(BaseModel):
    role: Literal["user", "executive", "admin"]


# ---------- the signed-in person
@router.get("/users/me")
async def me(user: store.User = Depends(current_user)):
    return {**user.public(), "memory_consent": consent.is_active(user.subject, "memory")}


@router.patch("/users/me")
async def update_me(body: ProfileUpdate, user: store.User = Depends(current_user)):
    updated = await store.update_profile(user.id, body.model_dump(exclude_none=True))
    return updated.public()


@router.delete("/users/me", status_code=204)
async def delete_me(request: Request, user: store.User = Depends(current_user)):
    """Delete the account together with its sign-ins, everything remembered about the person and their stored files."""
    for purpose in consent.active(user.subject):   # recorded as withdrawn, and each one erases what it allowed us to hold
        await consents.withdraw(user, purpose, channel="account_deletion", ip=client_ip(request.scope))
    await file_store.purge(user)   # and anything left, whatever its consent status was
    await store.delete_user(user.id)
    return Response(status_code=204)


@router.get("/users/me/export")
async def export_my_data(user: store.User = Depends(current_user)):
    """Everything Sahaj holds about the person, as one JSON download: profile, consent history, memory, the list of
    stored files (download each from /files/{id}) and the ratings they gave."""
    consents = [{"purpose": e["payload"]["purpose"], "event": e["payload"]["event"], "version": e["payload"]["version"],
                 "recorded_at": e["created_at"]} for e in ledger.entries(subject=user.subject, kind="consent")]
    data = {"exported_at": time.time(), "profile": user.public(), "consents": consents,
            "memory": await memory_store.all_for(user.id), "files": await file_store.list_for(user.id),
            "feedback": await feedback_store.for_user(user.id),
            "note": "Conversation audit records are kept without your identity (they carry a random session id only)."}
    return JSONResponse(jsonable_encoder(data), headers={"Content-Disposition": 'attachment; filename="sahaj-my-data.json"'})


# ---------- memory
@router.get("/users/me/memory")
async def get_memory(user: store.User = Depends(current_user)):
    """Everything Sahaj remembers about the person."""
    return {"consent": consent.is_active(user.subject, "memory"), "consent_text": consent.required("memory"),
            "items": await memory_store.all_for(user.id)}


@router.put("/users/me/memory/consent")
async def set_memory_consent(body: ConsentUpdate, request: Request, user: store.User = Depends(current_user)):
    """Allow or stop remembering. Stopping also erases what is already remembered. Same as PUT /consents/memory."""
    try:
        result = await consents.set_consent(user, "memory", body.granted, channel="api", version=body.version, ip=client_ip(request.scope))
    except consents.ConsentError as e:
        raise fail(e)
    return {"consent": body.granted, "erased": result["erased"].get("memories", 0)}


@router.delete("/users/me/memory/{memory_id}", status_code=204)
async def delete_memory_item(memory_id: int, user: store.User = Depends(current_user)):
    if not await memory_store.delete_one(user.id, memory_id):
        raise HTTPException(404, "No such memory.")
    return Response(status_code=204)


@router.delete("/users/me/memory")
async def delete_memory(user: store.User = Depends(current_user)):
    return {"erased": await memory_store.delete_all(user.id)}


# ---------- admin
@router.get("/admin/users")
async def list_users(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                     _: store.User = Depends(require_role("admin"))):
    return [u.public() for u in await store.list_users(limit, offset)]


@router.patch("/admin/users/{user_id}/role")
async def change_role(user_id: str, body: RoleUpdate, admin: store.User = Depends(require_role("admin"))):
    if user_id == admin.id and body.role != "admin":
        raise HTTPException(400, "You can't remove your own admin role.")
    user = await store.set_role(user_id, body.role) if await store.get_user(user_id) else None
    if user is None:
        raise HTTPException(404, "No such user.")
    return user.public()
