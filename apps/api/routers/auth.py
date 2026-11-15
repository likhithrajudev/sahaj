from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

import config
from auth import google, store, tokens
from observability.metrics import AUTH_EVENTS

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
        AUTH_EVENTS.labels("google_rejected").inc()
        raise HTTPException(401, str(e))
    user = await store.upsert_google_user(claims, body.platform)
    AUTH_EVENTS.labels("google_ok").inc()
    return await _session(user, await store.issue_refresh(user.id, body.platform))


@router.post("/refresh")
async def refresh(body: RefreshRequest):
    """Spend a refresh token for a new access token and a new refresh token. Each refresh token works once."""
    try:
        user_id, new_refresh, _ = await store.rotate_refresh(body.refresh_token)
    except store.InvalidToken as e:
        AUTH_EVENTS.labels("refresh_reused" if "already used" in str(e) else "refresh_rejected").inc()
        raise HTTPException(401, str(e))
    AUTH_EVENTS.labels("refresh_ok").inc()
    user = await store.get_user(user_id)
    if user is None:
        raise HTTPException(401, "This account no longer exists.")
    return await _session(user, new_refresh)


@router.post("/logout", status_code=204)
async def logout(body: RefreshRequest):
    """Sign out this device: the refresh token (and any it was exchanged for) stops working."""
    await store.revoke_refresh(body.refresh_token)
    return Response(status_code=204)


LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}


def dev_login_allowed(request: Request) -> bool:
    return (config.DEV_LOGIN and config.ENVIRONMENT == "development" and bool(request.client)
            and request.client.host in LOOPBACK)


@router.get("/config")
async def auth_config(request: Request):
    """What a client needs to start sign-in: the Google client id (public) and whether the dev login is on."""
    return {"google_client_id": config.GOOGLE_CLIENT_IDS[0] if config.GOOGLE_CLIENT_IDS else None,
            "dev_login": dev_login_allowed(request)}


class DevLogin(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=120)
    name: Optional[str] = Field(None, max_length=100)
    platform: Platform = "web"


@router.post("/dev")
async def dev_login(body: DevLogin, request: Request):
    """Sign in as any email without Google. Development on this machine only; elsewhere it does not exist."""
    if not dev_login_allowed(request):
        raise HTTPException(404, "Not found.")
    tokens._secret()
    user = await store.upsert_google_user(
        {"sub": f"dev:{body.email.lower()}", "email": body.email.lower(), "name": body.name or body.email.split("@")[0]},
        body.platform)
    AUTH_EVENTS.labels("dev_login").inc()
    return await _session(user, await store.issue_refresh(user.id, body.platform))
