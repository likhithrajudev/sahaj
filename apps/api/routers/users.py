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
from services.tts import SUPPORTED_LANGUAGES

router = APIRouter(tags=["Users"])


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    language: Optional[str] = Field(None, pattern=rf"^(?:{'|'.join(SUPPORTED_LANGUAGES)})$",
                                    description="Supported Indian language tag, for example en-IN, hi-IN or mai-IN")
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


@router.get("/languages")
async def supported_languages():
    from services.tts import BORROWED, VOICES
    return {"items": [{"code": code, "name": name, "speech_output": code in VOICES,
                       "speech_output_borrowed": code in BORROWED and BORROWED[code][1] is not None}
                      for code, name in SUPPORTED_LANGUAGES.items()]}


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
    """Everything the person can export: profile, consent history, memory, private inventory, files and feedback."""
    from memory import episodic
    from financial import inventory as inventory_store
    consents = [{"purpose": e["payload"]["purpose"], "event": e["payload"]["event"], "version": e["payload"]["version"],
                 "recorded_at": e["created_at"]} for e in ledger.entries(subject=user.subject, kind="consent")]
    data = {"exported_at": time.time(), "profile": user.public(), "consents": consents,
            "memory": [{k: v for k, v in m.items() if k != "embedding"} for m in await memory_store.all_for(user.id)],
            "conversations": await episodic.list_for(user.id, 500),
            "files": await file_store.list_for(user.id),
            "financial_inventory": await inventory_store.list_for(user.id) if consent.is_active(user.subject, "financial_profile") else [],
            "feedback": await feedback_store.for_user(user.id),
            "note": "Conversation audit records are kept without your identity (they carry a random session id only)."}
    return JSONResponse(jsonable_encoder(data), headers={"Content-Disposition": 'attachment; filename="sahaj-my-data.json"'})


# ---------- memory
@router.get("/users/me/memory")
async def get_memory(user: store.User = Depends(current_user)):
    """Everything Sahaj remembers about the person."""
    from memory import episodic
    items = await memory_store.all_for(user.id)
    return {"consent": consent.is_active(user.subject, "memory"), "consent_text": consent.required("memory"),
            "facts": [{k: v for k, v in i.items() if k != "embedding"} for i in items if i["kind"] == "fact"],
            "episodes": await episodic.list_for(user.id),
            "items": [{k: v for k, v in i.items() if k != "embedding"} for i in items]}


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


@router.delete("/users/me/memory/episodes/{episode_id}", status_code=204)
async def delete_episode(episode_id: str, user: store.User = Depends(current_user)):
    from memory import episodic
    if not await episodic.delete_one(user.id, episode_id):
        raise HTTPException(404, "No such conversation in memory.")
    return Response(status_code=204)


@router.delete("/users/me/memory")
async def delete_memory(user: store.User = Depends(current_user)):
    from memory import episodic
    return {"erased": await memory_store.delete_all(user.id) + await episodic.delete_all(user.id)}


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
