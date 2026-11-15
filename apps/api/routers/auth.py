from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from auth import google, store, tokens

router = APIRouter(prefix="/auth", tags=["Auth"])

Platform = Literal["web", "android", "ios"]


class GoogleLogin(BaseModel):
    id_token: str = Field(description="The ID token Google gave the client after sign-in")
    platform: Platform = "web"


class RefreshRequest(BaseModel):
    refresh_token: str


async def _session(user: store.User, refresh_token: str) -> dict:
    access, expires_in = tokens.issue_access(user)
    return {"access_token": access, "refresh_token": refresh_token, "token_type": "bearer",
            "expires_in": expires_in, "user": user.public()}


@router.post("/google")
async def google_login(body: GoogleLogin):
    """Exchange a Google ID token for Sahaj tokens. Creates the account on first sign-in."""
    tokens._secret()  # fail with 503 before touching Google if signing is not configured
    try:
        claims = await google.verify_id_token(body.id_token)
    except store.InvalidToken as e:
        raise HTTPException(401, str(e))
    user = await store.upsert_google_user(claims, body.platform)
    return await _session(user, await store.issue_refresh(user.id, body.platform))


@router.post("/refresh")
async def refresh(body: RefreshRequest):
    """Spend a refresh token for a new access token and a new refresh token. Each refresh token works once."""
    try:
        user_id, new_refresh, _ = await store.rotate_refresh(body.refresh_token)
    except store.InvalidToken as e:
        raise HTTPException(401, str(e))
    user = await store.get_user(user_id)
    if user is None:
        raise HTTPException(401, "This account no longer exists.")
    return await _session(user, new_refresh)


@router.post("/logout", status_code=204)
async def logout(body: RefreshRequest):
    """Sign out this device: the refresh token (and any it was exchanged for) stops working."""
    await store.revoke_refresh(body.refresh_token)
    return Response(status_code=204)
