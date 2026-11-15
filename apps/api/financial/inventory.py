"""Private, per-user credit-card and loan details that the person explicitly confirms."""
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from auth.store import db
from tenancy.db import create_tables

SCHEMA = """
CREATE TABLE IF NOT EXISTS financial_inventory_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL CHECK (item_type IN ('credit_card', 'loan')),
    label TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS financial_inventory_user_idx
    ON financial_inventory_items(user_id, item_type, created_at);
"""


async def init_schema() -> None:
    await create_tables(db(), SCHEMA)


def _public(row: dict) -> dict:
    return {"id": str(row["id"]), "type": row["item_type"], "label": row["label"],
            "details": row["details"], "created_at": row["created_at"], "updated_at": row["updated_at"]}


async def list_for(user_id: str) -> list[dict]:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("""SELECT id, item_type, label, details, created_at, updated_at
                             FROM financial_inventory_items WHERE user_id = %s
                             ORDER BY item_type, created_at, id""", (user_id,))
        return [_public(row) for row in await cur.fetchall()]


async def replace_for(user_id: str, credit_cards: list[dict], loans: list[dict]) -> list[dict]:
    async with db().connection() as conn, conn.transaction(), conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("DELETE FROM financial_inventory_items WHERE user_id = %s", (user_id,))
        for item_type, rows in (("credit_card", credit_cards), ("loan", loans)):
            for item in rows:
                data = dict(item)
                label = data.pop("label")
                await cur.execute("""INSERT INTO financial_inventory_items (user_id, item_type, label, details)
                                     VALUES (%s, %s, %s, %s)""",
                                  (user_id, item_type, label, Jsonb(data)))
        await cur.execute("""SELECT id, item_type, label, details, created_at, updated_at
                             FROM financial_inventory_items WHERE user_id = %s
                             ORDER BY item_type, created_at, id""", (user_id,))
        return [_public(row) for row in await cur.fetchall()]


async def forget(user_id: str) -> int:
    async with db().connection() as conn:
        cur = await conn.execute("DELETE FROM financial_inventory_items WHERE user_id = %s", (user_id,))
        return cur.rowcount


async def delete_one(user_id: str, item_id: str) -> bool:
    try:
        UUID(item_id)
    except ValueError:
        return False
    async with db().connection() as conn:
        cur = await conn.execute("DELETE FROM financial_inventory_items WHERE user_id = %s AND id = %s",
                                 (user_id, item_id))
        return cur.rowcount > 0
