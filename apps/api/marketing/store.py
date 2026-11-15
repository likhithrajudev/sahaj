"""Marketing campaigns, sent only to people with the `marketing` consent, delivered to their in-app inbox."""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import config
from auth.store import db
from trust import consent, ledger

SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   TEXT NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    cta_label   TEXT,
    cta_url     TEXT,
    image_blob  TEXT,
    image_type  TEXT,
    audience    JSONB NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'sent', 'cancelled')),
    created_by  UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at     TIMESTAMPTZ,
    recipients  INT NOT NULL DEFAULT 0,
    skipped_cap INT NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS campaign_deliveries (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    TEXT NOT NULL,
    campaign_id  UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    delivered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seen_at      TIMESTAMPTZ,
    clicked_at   TIMESTAMPTZ,
    dismissed_at TIMESTAMPTZ,
    UNIQUE (campaign_id, user_id)
);
CREATE INDEX IF NOT EXISTS campaign_deliveries_user_idx ON campaign_deliveries(user_id, delivered_at DESC);
"""

STATS = """(SELECT count(*) FROM campaign_deliveries d WHERE d.campaign_id = c.id AND d.seen_at IS NOT NULL) AS seen,
           (SELECT count(*) FROM campaign_deliveries d WHERE d.campaign_id = c.id AND d.clicked_at IS NOT NULL) AS clicked"""


async def init_schema() -> None:
    from tenancy.db import create_tables
    await create_tables(db(), SCHEMA)


def _row(r: Optional[dict]) -> Optional[dict]:
    if r is None:
        return None
    return {**r, "id": str(r["id"]), "created_by": str(r["created_by"]) if r.get("created_by") else None}


async def create(fields: dict, author: str) -> dict:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("""INSERT INTO campaigns (title, body, cta_label, cta_url, audience, created_by)
                             VALUES (%(title)s, %(body)s, %(cta_label)s, %(cta_url)s, %(audience)s, %(author)s) RETURNING *""",
                          {**fields, "audience": Jsonb(fields.get("audience") or {}), "author": author})
        return _row(await cur.fetchone())


async def get(campaign_id: str) -> Optional[dict]:
    import uuid
    try:
        uuid.UUID(campaign_id)
    except ValueError:
        return None
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(f"SELECT c.*, {STATS} FROM campaigns c WHERE c.id = %s", (campaign_id,))
        return _row(await cur.fetchone())


async def list_all() -> List[dict]:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(f"SELECT c.*, {STATS} FROM campaigns c ORDER BY c.created_at DESC LIMIT 200")
        return [_row(r) for r in await cur.fetchall()]


async def set_image(campaign_id: str, blob_name: str, content_type: str) -> None:
    async with db().connection() as conn:
        await conn.execute("UPDATE campaigns SET image_blob = %s, image_type = %s WHERE id = %s AND status = 'draft'",
                           (blob_name, content_type, campaign_id))


async def cancel(campaign_id: str) -> bool:
    async with db().connection() as conn:
        return (await conn.execute("UPDATE campaigns SET status = 'cancelled' WHERE id = %s AND status = 'draft'",
                                   (campaign_id,))).rowcount > 0


async def audience(campaign: dict) -> List[dict]:
    """Opted-in people in this tenant matching the campaign's filters (languages, platforms)."""
    want = campaign.get("audience") or {}
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("""SELECT id, language, platform FROM users
                             WHERE (%(langs)s::text[] IS NULL OR language = ANY(%(langs)s))
                               AND (%(plats)s::text[] IS NULL OR platform = ANY(%(plats)s))""",
                          {"langs": want.get("languages") or None, "plats": want.get("platforms") or None})
        rows = await cur.fetchall()
    return [{**r, "id": str(r["id"])} for r in rows if consent.is_active(f"user:{r['id']}", "marketing")]


async def send(campaign_id: str, author: str) -> Optional[dict]:
    """Deliver to the opted-in audience, at most MARKETING_WEEKLY_CAP campaigns per person per 7 days. Draft only."""
    campaign = await get(campaign_id)
    if campaign is None or campaign["status"] != "draft":
        return None
    people = await audience(campaign)
    since = datetime.now(timezone.utc) - timedelta(days=7)
    sent, capped = [], 0
    async with db().connection() as conn:
        async with conn.transaction():
            claimed = await conn.execute("UPDATE campaigns SET status = 'sent', sent_at = now() WHERE id = %s AND status = 'draft'",
                                         (campaign_id,))
            if claimed.rowcount == 0:   # someone else sent it first
                return None
            for p in people:
                recent = (await (await conn.execute("SELECT count(*) FROM campaign_deliveries WHERE user_id = %s AND delivered_at > %s",
                                                    (p["id"], since))).fetchone())[0]
                if recent >= config.MARKETING_WEEKLY_CAP:
                    capped += 1
                    continue
                await conn.execute("INSERT INTO campaign_deliveries (campaign_id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                                   (campaign_id, p["id"]))
                sent.append(p["id"])
            await conn.execute("UPDATE campaigns SET recipients = %s, skipped_cap = %s WHERE id = %s", (len(sent), capped, campaign_id))
    ledger.append("campaign", f"campaign:{campaign_id}", {"event": "sent", "actor": author, "recipients": len(sent), "skipped_cap": capped})
    return {**campaign, "status": "sent", "recipients": len(sent), "skipped_cap": capped, "user_ids": sent}


async def inbox(user_id: str) -> List[dict]:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("""SELECT d.id, d.delivered_at, d.seen_at, d.clicked_at, c.title, c.body, c.cta_label, c.cta_url,
                                    c.image_blob IS NOT NULL AS has_image
                             FROM campaign_deliveries d JOIN campaigns c ON c.id = d.campaign_id
                             WHERE d.user_id = %s AND d.dismissed_at IS NULL ORDER BY d.delivered_at DESC LIMIT 50""", (user_id,))
        return [{**r, "id": str(r["id"])} for r in await cur.fetchall()]


async def delivery(user_id: str, delivery_id: str) -> Optional[dict]:
    import uuid
    try:
        uuid.UUID(delivery_id)
    except ValueError:
        return None
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("""SELECT d.id, c.cta_url, c.image_blob, c.image_type FROM campaign_deliveries d
                             JOIN campaigns c ON c.id = d.campaign_id WHERE d.user_id = %s AND d.id = %s""", (user_id, delivery_id))
        return await cur.fetchone()


async def mark(user_id: str, delivery_id: str, column: str) -> bool:
    assert column in ("seen_at", "clicked_at", "dismissed_at")
    async with db().connection() as conn:
        return (await conn.execute(f"UPDATE campaign_deliveries SET {column} = COALESCE({column}, now()) "
                                   "WHERE user_id = %s AND id = %s", (user_id, delivery_id))).rowcount > 0


async def forget(user_id: str) -> int:
    async with db().connection() as conn:
        return (await conn.execute("DELETE FROM campaign_deliveries WHERE user_id = %s", (user_id,))).rowcount
