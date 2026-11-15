"""Users and refresh tokens, in the same Postgres as the knowledge base."""
import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from psycopg.rows import dict_row

import config
from rag import store as rag_store

log = logging.getLogger("sahaj.auth")

PLATFORMS = ("web", "android", "ios")
ROLES = ("user", "admin")


class Unavailable(RuntimeError):
    """The accounts database or the auth settings are not usable. Becomes a 503."""


class InvalidToken(Exception):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    google_sub    TEXT NOT NULL UNIQUE,
    email         TEXT NOT NULL,
    name          TEXT,
    picture       TEXT,
    language      TEXT NOT NULL DEFAULT 'en-IN',
    platform      TEXT NOT NULL DEFAULT 'web' CHECK (platform IN ('web', 'android', 'ios')),
    role          TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    family_id  UUID NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    platform   TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS refresh_tokens_family_idx ON refresh_tokens(family_id);
CREATE INDEX IF NOT EXISTS refresh_tokens_user_idx ON refresh_tokens(user_id);
CREATE TABLE IF NOT EXISTS user_memories (
    id         BIGSERIAL PRIMARY KEY,
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL CHECK (kind IN ('fact', 'summary')),
    key        TEXT,
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS user_memories_fact_idx ON user_memories(user_id, key) WHERE kind = 'fact';
CREATE INDEX IF NOT EXISTS user_memories_user_idx ON user_memories(user_id, kind, created_at);
"""


@dataclass
class User:
    id: str
    email: str
    name: Optional[str]
    picture: Optional[str]
    language: str
    platform: str
    role: str

    @property
    def subject(self) -> str:
        """The consent-ledger subject for things that belong to the person rather than to one conversation."""
        return f"user:{self.id}"

    def public(self) -> dict:
        return {"id": self.id, "email": self.email, "name": self.name, "picture": self.picture,
                "language": self.language, "platform": self.platform, "role": self.role}


def _user(row: Optional[dict]) -> Optional[User]:
    if row is None:
        return None
    return User(id=str(row["id"]), email=row["email"], name=row["name"], picture=row["picture"],
                language=row["language"], platform=row["platform"], role=row["role"])


def db():
    try:
        return rag_store.pool()
    except RuntimeError as e:
        raise Unavailable("Accounts are unavailable: the database is not reachable.") from e


async def init_schema() -> None:
    try:
        async with db().connection() as conn:
            await conn.execute(SCHEMA)
    except Unavailable as e:
        log.warning("%s", e)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------- users
async def upsert_google_user(claims: dict, platform: str) -> User:
    """Create the user on first sign-in, refresh name/picture/platform on later ones. Admin emails are promoted."""
    admin = (claims["email"] or "").lower() in config.ADMIN_EMAILS
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """INSERT INTO users (google_sub, email, name, picture, platform, role)
               VALUES (%(sub)s, %(email)s, %(name)s, %(picture)s, %(platform)s, CASE WHEN %(admin)s THEN 'admin' ELSE 'user' END)
               ON CONFLICT (google_sub) DO UPDATE SET
                   email = EXCLUDED.email, picture = EXCLUDED.picture, platform = EXCLUDED.platform, last_login_at = now(),
                   name = COALESCE(users.name, EXCLUDED.name),
                   role = CASE WHEN %(admin)s THEN 'admin' ELSE users.role END
               RETURNING *""",
            {"sub": claims["sub"], "email": claims["email"], "name": claims.get("name"),
             "picture": claims.get("picture"), "platform": platform, "admin": admin},
        )
        return _user(await cur.fetchone())


async def get_user(user_id: str) -> Optional[User]:
    try:
        uuid.UUID(user_id)
    except ValueError:
        return None
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        return _user(await cur.fetchone())


async def update_profile(user_id: str, fields: dict) -> Optional[User]:
    allowed = {k: v for k, v in fields.items() if k in ("name", "language", "platform") and v is not None}
    if not allowed:
        return await get_user(user_id)
    sets = ", ".join(f"{k} = %({k})s" for k in allowed)  # keys come from the allow-list above, never from input
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(f"UPDATE users SET {sets} WHERE id = %(id)s RETURNING *", {**allowed, "id": user_id})
        return _user(await cur.fetchone())


async def set_role(user_id: str, role: str) -> Optional[User]:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("UPDATE users SET role = %s WHERE id = %s RETURNING *", (role, user_id))
        return _user(await cur.fetchone())


async def list_users(limit: int, offset: int) -> List[User]:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT %s OFFSET %s", (limit, offset))
        return [_user(r) for r in await cur.fetchall()]


async def delete_user(user_id: str) -> bool:
    """Removes the account; its refresh tokens and memories go with it (ON DELETE CASCADE)."""
    async with db().connection() as conn:
        cur = await conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
        return cur.rowcount > 0


# ---------- refresh tokens: opaque, stored only as a hash, rotated on every use
async def issue_refresh(user_id: str, platform: str, family_id: Optional[str] = None) -> str:
    raw = secrets.token_urlsafe(48)
    async with db().connection() as conn:
        await conn.execute(
            "INSERT INTO refresh_tokens (user_id, family_id, token_hash, platform, expires_at) VALUES (%s, %s, %s, %s, %s)",
            (user_id, family_id or str(uuid.uuid4()), _hash(raw), platform, _now() + timedelta(days=config.REFRESH_TOKEN_DAYS)))
    return raw


async def rotate_refresh(raw: str) -> tuple:
    """Spend a refresh token and issue its replacement in the same family: (user_id, new_raw_token, platform).
    Presenting a token that was already spent means it leaked, so the whole family is revoked."""
    async with db().connection() as conn:
        async with conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM refresh_tokens WHERE token_hash = %s FOR UPDATE", (_hash(raw),))
            row = await cur.fetchone()
            if row is None:
                raise InvalidToken("Unknown refresh token.")
            if row["revoked_at"] is not None:
                await cur.execute("UPDATE refresh_tokens SET revoked_at = now() WHERE family_id = %s AND revoked_at IS NULL",
                                  (row["family_id"],))
                reused = True
            elif row["expires_at"] <= _now():
                raise InvalidToken("Refresh token expired.")
            else:
                await cur.execute("UPDATE refresh_tokens SET revoked_at = now() WHERE id = %s", (row["id"],))
                reused = False
        if reused:  # committed above; reported outside the transaction so the revocation is kept
            raise InvalidToken("Refresh token already used.")
    new = await issue_refresh(str(row["user_id"]), row["platform"], str(row["family_id"]))
    return str(row["user_id"]), new, row["platform"]


async def revoke_refresh(raw: str) -> None:
    """Sign out: revoke this token's whole family (every refresh token descended from the same sign-in)."""
    async with db().connection() as conn:
        await conn.execute(
            "UPDATE refresh_tokens SET revoked_at = now() WHERE revoked_at IS NULL AND family_id = "
            "(SELECT family_id FROM refresh_tokens WHERE token_hash = %s)", (_hash(raw),))


async def revoke_all(user_id: str) -> None:
    async with db().connection() as conn:
        await conn.execute("UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = %s AND revoked_at IS NULL", (user_id,))
