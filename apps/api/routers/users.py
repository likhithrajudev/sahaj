from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from auth import store
from auth.deps import current_user, require_role
from memory import store as memory_store
from trust import consent

router = APIRouter(tags=["Users"])


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    language: Optional[str] = Field(None, pattern=r"^[a-z]{2}-IN$", description="For example en-IN, hi-IN")
    platform: Optional[Literal["web", "android", "ios"]] = None


class ConsentUpdate(BaseModel):
    granted: bool


class RoleUpdate(BaseModel):
    role: Literal["user", "admin"]


# ---------- the signed-in person
@router.get("/users/me")
async def me(user: store.User = Depends(current_user)):
    return {**user.public(), "memory_consent": consent.is_active(user.subject, "memory")}


@router.patch("/users/me")
async def update_me(body: ProfileUpdate, user: store.User = Depends(current_user)):
    updated = await store.update_profile(user.id, body.model_dump(exclude_none=True))
    return updated.public()


@router.delete("/users/me", status_code=204)
async def delete_me(user: store.User = Depends(current_user)):
    """Delete the account together with its sign-ins and everything remembered about the person."""
    if consent.is_active(user.subject, "memory"):
        consent.revoke(user.subject, "memory", channel="api")
    await store.delete_user(user.id)
    return Response(status_code=204)


# ---------- memory
@router.get("/users/me/memory")
async def get_memory(user: store.User = Depends(current_user)):
    """Everything Sahaj remembers about the person."""
    return {"consent": consent.is_active(user.subject, "memory"), "consent_text": consent.required("memory"),
            "items": await memory_store.all_for(user.id)}


@router.put("/users/me/memory/consent")
async def set_memory_consent(body: ConsentUpdate, user: store.User = Depends(current_user)):
    """Allow or stop remembering. Stopping also erases what is already remembered."""
    if body.granted:
        consent.grant(user.subject, "memory", channel="api")
        return {"consent": True, "erased": 0}
    consent.revoke(user.subject, "memory", channel="api")
    return {"consent": False, "erased": await memory_store.delete_all(user.id)}


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
