"""FastAPI dependencies: who is calling, and are they allowed."""
from typing import Optional

from fastapi import Depends, HTTPException, WebSocket
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth import store, tokens

bearer = HTTPBearer(auto_error=False)


async def user_from_token(token: Optional[str]) -> store.User:
    """The user a valid access token belongs to. The database is the authority, so a deleted user or a changed role
    takes effect at once rather than when the token expires."""
    if not token:
        raise HTTPException(401, "Missing access token.", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = tokens.decode_access(token)
    except store.InvalidToken as e:
        raise HTTPException(401, str(e), headers={"WWW-Authenticate": "Bearer"})
    user = await store.get_user(claims["sub"])
    if user is None:
        raise HTTPException(401, "This account no longer exists.", headers={"WWW-Authenticate": "Bearer"})
    return user


async def current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> store.User:
    return await user_from_token(creds.credentials if creds else None)


def require_role(*roles: str):
    async def check(user: store.User = Depends(current_user)) -> store.User:
        if user.role not in roles:
            raise HTTPException(403, "You don't have access to this.")
        return user
    return check


async def websocket_user(ws: WebSocket) -> Optional[store.User]:
    """The user for a WebSocket handshake, or None. Browsers cannot set headers on a WebSocket, so the access token
    may also come as ?access_token=... (use a short-lived token: URLs end up in logs)."""
    header = ws.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else ws.query_params.get("access_token")
    try:
        return await user_from_token(token)
    except HTTPException:
        return None
