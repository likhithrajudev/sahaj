"""Owner-scoped drafts and private attachments, separate from the RAG index."""
import json
from contextlib import asynccontextmanager

from psycopg.rows import dict_row

from auth.store import db
from tenancy.db import create_tables

SCHEMA = """
CREATE TABLE IF NOT EXISTS journey_drafts (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('claim', 'loan')),
    state JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS journey_drafts_owner_idx ON journey_drafts (user_id, created_at DESC);
CREATE TABLE IF NOT EXISTS journey_attachments (
    id UUID PRIMARY KEY,
    draft_id UUID NOT NULL REFERENCES journey_drafts(id) ON DELETE CASCADE,
    content_type TEXT NOT NULL,
    body BYTEA NOT NULL
);
"""


async def init_schema():
    await create_tables(db(), SCHEMA)


async def list_for(user_id):
    async with db().connection() as conn:
        cur = await conn.execute(
            "SELECT state FROM journey_drafts WHERE user_id = %s ORDER BY created_at DESC LIMIT 25",
            (user_id,),
        )
        return [row[0] for row in await cur.fetchall()]


@asynccontextmanager
async def draft(user_id, draft_id, *, write=False):
    async with db().connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        sql = "SELECT state FROM journey_drafts WHERE id = %s AND user_id = %s"
        await cur.execute(sql + (" FOR UPDATE" if write else ""), (draft_id, user_id))
        row = await cur.fetchone()
        yield conn, row["state"] if row else None


async def create(user_id, state):
    async with db().connection() as conn:
        await conn.execute("INSERT INTO journey_drafts (id, user_id, kind, state) VALUES (%s,%s,%s,%s::jsonb)",
                           (state["id"], user_id, state["kind"], json.dumps(state)))


async def save(conn, state):
    await conn.execute("UPDATE journey_drafts SET state = %s::jsonb WHERE id = %s",
                       (json.dumps(state), state["id"]))


async def forget(user_id):
    async with db().connection() as conn:
        result = await conn.execute("DELETE FROM journey_drafts WHERE user_id = %s", (user_id,))
        return result.rowcount
