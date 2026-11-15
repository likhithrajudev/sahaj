"""Minimal, per-user references for provider actions. Applicant details and bureau scores are never stored here."""
import uuid
from typing import Optional

from psycopg.rows import dict_row

from auth.store import db
from tenancy.db import create_tables

SCHEMA = """
CREATE TABLE IF NOT EXISTS financial_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('credit_check', 'loan_application', 'insurance_application')),
    provider TEXT NOT NULL,
    provider_reference TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS financial_events_user_idx ON financial_events(user_id, created_at DESC);
"""


async def init_schema() -> None:
    await create_tables(db(), SCHEMA)


async def add(user_id: str, kind: str, provider: str, reference: str, status: str) -> dict:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("""INSERT INTO financial_events (user_id, kind, provider, provider_reference, status)
                             VALUES (%s, %s, %s, %s, %s)
                             RETURNING id, kind, provider, status, created_at""",
                          (user_id, kind, provider, reference, status))
        return await cur.fetchone()


async def get(user_id: str, event_id: str) -> Optional[dict]:
    try:
        uuid.UUID(event_id)
    except ValueError:
        return None
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("""SELECT id, kind, provider, provider_reference, status, created_at
                             FROM financial_events WHERE user_id = %s AND id = %s""", (user_id, event_id))
        return await cur.fetchone()


async def list_for(user_id: str) -> list[dict]:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("""SELECT id, kind, provider, status, created_at FROM financial_events
                             WHERE user_id = %s ORDER BY created_at DESC LIMIT 100""", (user_id,))
        return await cur.fetchall()


async def forget(user_id: str, kinds: tuple[str, ...]) -> int:
    async with db().connection() as conn:
        cur = await conn.execute("DELETE FROM financial_events WHERE user_id = %s AND kind = ANY(%s)",
                                 (user_id, list(kinds)))
        return cur.rowcount
