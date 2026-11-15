"""Verify a Google ID token (the client signs in with Google and sends us the token)."""
import asyncio

import jwt
from jwt import PyJWKClient

import config
from auth.store import InvalidToken, Unavailable

JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ["https://accounts.google.com", "accounts.google.com"]
_jwks = PyJWKClient(JWKS_URL, cache_keys=True, lifespan=3600)


def _signing_key(token: str):
    return _jwks.get_signing_key_from_jwt(token).key  # blocking network call on a cache miss


async def verify_id_token(token: str) -> dict:
    """The verified claims. Checks signature, expiry, issuer and that the token was issued for one of our client ids."""
    if not config.GOOGLE_CLIENT_IDS:
        raise Unavailable("Google sign-in is disabled: set GOOGLE_CLIENT_IDS.")
    try:
        key = await asyncio.to_thread(_signing_key, token)
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=config.GOOGLE_CLIENT_IDS, issuer=ISSUERS,
                            options={"require": ["exp", "iat", "sub", "aud", "iss"]})
    except jwt.PyJWTError as e:
        raise InvalidToken(f"Invalid Google token: {e}") from e
    if not claims.get("email") or claims.get("email_verified") is not True:
        raise InvalidToken("The Google account's email is not verified.")
    return claims
