"""Sahaj's own access tokens: short-lived signed JWTs. Refresh tokens are opaque (see auth/store.py)."""
import time
import uuid
from typing import Tuple

import jwt

import config
from auth.store import InvalidToken, Unavailable, User

ALGORITHM = "HS256"
AUDIENCE = "sahaj-api"


def _secret() -> str:
    if not config.JWT_SECRET or len(config.JWT_SECRET) < 32:
        raise Unavailable("Sign-in is disabled: set JWT_SECRET (at least 32 characters).")
    return config.JWT_SECRET


def issue_access(user: User) -> Tuple[str, int]:
    """(token, seconds until it expires)."""
    now = int(time.time())
    ttl = config.ACCESS_TOKEN_MINUTES * 60
    claims = {"iss": config.JWT_ISSUER, "aud": AUDIENCE, "sub": user.id, "role": user.role, "platform": user.platform,
              "type": "access", "iat": now, "exp": now + ttl, "jti": uuid.uuid4().hex}
    return jwt.encode(claims, _secret(), algorithm=ALGORITHM), ttl


def decode_access(token: str) -> dict:
    try:
        claims = jwt.decode(token, _secret(), algorithms=[ALGORITHM], audience=AUDIENCE, issuer=config.JWT_ISSUER,
                            options={"require": ["exp", "iat", "sub", "iss", "aud"]})
    except jwt.PyJWTError as e:
        raise InvalidToken(str(e)) from e
    if claims.get("type") != "access":
        raise InvalidToken("Not an access token.")
    return claims
