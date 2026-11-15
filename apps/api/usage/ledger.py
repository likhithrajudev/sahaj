"""Every billable call a person causes, and what they have spent this period.

One row per call (a model call, a speech-to-text request, a text-to-speech request), with the estimated cost in USD. No
prompt, reply or transcript text is stored here: only who, when, which provider and model, how much, and the cost."""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from psycopg.rows import dict_row

import config
from auth.store import db

log = logging.getLogger("sahaj.usage")

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_events (
    id            BIGSERIAL PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind          TEXT NOT NULL,
    provider      TEXT NOT NULL,
    model         TEXT NOT NULL DEFAULT '',
    purpose       TEXT NOT NULL DEFAULT '',
    channel       TEXT NOT NULL DEFAULT '',
    input_tokens  INT NOT NULL DEFAULT 0,
    output_tokens INT NOT NULL DEFAULT 0,
    cached_tokens INT NOT NULL DEFAULT 0,
    units         DOUBLE PRECISION NOT NULL DEFAULT 0,   -- seconds of audio (stt) or characters (tts)
    cost_usd      NUMERIC(14, 8) NOT NULL DEFAULT 0,
    trace_id      TEXT
);
CREATE INDEX IF NOT EXISTS usage_events_user_at_idx ON usage_events(user_id, at);
ALTER TABLE usage_events DROP CONSTRAINT IF EXISTS usage_events_kind_check;
ALTER TABLE usage_events ADD CONSTRAINT usage_events_kind_check CHECK (kind IN ('llm', 'stt', 'tts', 'embedding'));
ALTER TABLE users ADD COLUMN IF NOT EXISTS budget_usd NUMERIC(12, 4);   -- per-person override; NULL = the default
ALTER TABLE users ALTER COLUMN budget_usd TYPE NUMERIC(12, 4);
"""


async def init_schema() -> None:
    async with db().connection() as conn:
        await conn.execute(SCHEMA)


def period(now: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    """(start, next reset) of the current budget period: the calendar month, in UTC."""
    now = now or datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    reset = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start, reset


async def add(user_id: str, events: List[dict]) -> None:
    """Record the calls a turn made. Never raises: failing to meter must not break a conversation."""
    if not events:
        return
    try:
        async with db().connection() as conn:
            async with conn.transaction():
                for e in events:
                    await conn.execute(
                        """INSERT INTO usage_events (user_id, kind, provider, model, purpose, channel, input_tokens, output_tokens,
                                                     cached_tokens, units, cost_usd, trace_id)
                           VALUES (%(u)s, %(kind)s, %(provider)s, %(model)s, %(purpose)s, %(channel)s, %(input_tokens)s,
                                   %(output_tokens)s, %(cached_tokens)s, %(units)s, %(cost_usd)s, %(trace_id)s)""",
                        {"u": user_id, "model": "", "purpose": "", "channel": "", "input_tokens": 0, "output_tokens": 0,
                         "cached_tokens": 0, "units": 0, "trace_id": None, **e})
    except Exception as e:
        log.warning("Could not record usage: %s", e)


async def spent(user_id: str, since: Optional[datetime] = None) -> float:
    since = since or period()[0]
    async with db().connection() as conn:
        cur = await conn.execute("SELECT COALESCE(sum(cost_usd), 0) FROM usage_events WHERE user_id = %s AND at >= %s", (user_id, since))
        return float((await cur.fetchone())[0])


async def budget(user_id: str) -> float:
    """What this person may spend per period: their own limit if an admin set one, else the default."""
    async with db().connection() as conn:
        row = await (await conn.execute("SELECT budget_usd FROM users WHERE id = %s", (user_id,))).fetchone()
    return float(row[0]) if row and row[0] is not None else config.USER_BUDGET_USD


async def set_budget(user_id: str, usd: Optional[float]) -> bool:
    async with db().connection() as conn:
        cur = await conn.execute("UPDATE users SET budget_usd = %s WHERE id = %s", (usd, user_id))
        return cur.rowcount > 0


async def summary(user_id: str) -> Dict:
    """Where the person stands this period, and what the spend was on."""
    start, reset = period()
    limit = await budget(user_id)
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        breakdown: Dict[str, Dict[str, float]] = {}
        for dim in ("provider", "kind", "purpose", "channel"):
            await cur.execute(f"SELECT {dim} AS k, sum(cost_usd) AS cost FROM usage_events WHERE user_id = %s AND at >= %s GROUP BY {dim} "
                              "ORDER BY 2 DESC", (user_id, start))   # `dim` is one of the four literals above, never input
            breakdown[dim] = {r["k"] or "-": round(float(r["cost"]), 6) for r in await cur.fetchall()}
        await cur.execute("SELECT count(*) AS calls, COALESCE(sum(input_tokens),0) AS i, COALESCE(sum(output_tokens),0) AS o, "
                          "COALESCE(sum(cached_tokens),0) AS c FROM usage_events WHERE user_id = %s AND at >= %s AND kind = 'llm'", (user_id, start))
        t = await cur.fetchone()
    used = sum(breakdown["provider"].values())
    return {"period": {"start": start.isoformat(), "resets_at": reset.isoformat()}, "budget_usd": limit,
            "spent_usd": round(used, 6), "remaining_usd": round(max(limit - used, 0), 6),
            "percent_used": round(100 * used / limit, 1) if limit else None, "enforced": config.BUDGET_ENABLED,
            "model_calls": t["calls"], "tokens": {"input": t["i"], "output": t["o"], "cached_input": t["c"]},
            "by_provider": breakdown["provider"], "by_kind": breakdown["kind"], "by_purpose": breakdown["purpose"],
            "by_channel": breakdown["channel"], "estimate": True}


async def top_spenders(limit: int) -> List[dict]:
    start, _ = period()
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("""SELECT u.id, u.email, u.username, COALESCE(u.budget_usd, %(d)s) AS budget_usd, sum(e.cost_usd) AS spent_usd
                             FROM usage_events e JOIN users u ON u.id = e.user_id WHERE e.at >= %(s)s
                             GROUP BY u.id ORDER BY spent_usd DESC LIMIT %(n)s""", {"d": config.USER_BUDGET_USD, "s": start, "n": limit})
        return [{**r, "id": str(r["id"]), "budget_usd": float(r["budget_usd"]), "spent_usd": round(float(r["spent_usd"]), 6)}
                for r in await cur.fetchall()]


async def status(user_id: str) -> Dict:
    """Spent against the limit right now: {"spent", "budget", "exceeded", "warn"}. Fails open (not exceeded) if the ledger
    cannot be read, so a database hiccup never locks everyone out."""
    try:
        used, limit = await spent(user_id), await budget(user_id)
    except Exception as e:
        log.warning("Could not read usage: %s", e)
        return {"spent": 0.0, "budget": config.USER_BUDGET_USD, "exceeded": False, "warn": False, "known": False}
    return {"spent": used, "budget": limit, "exceeded": config.BUDGET_ENABLED and used >= limit,
            "warn": config.BUDGET_ENABLED and used >= limit * config.BUDGET_WARN_AT, "known": True}
