"""Cases for the customer executive desk.

A case is opened when a conversation needs a person: the customer asked, the AI kept failing, the customer complained or
is in distress, or something only a person may do (video KYC). It carries the masked recent conversation, so the
executive starts with the full context, and its own message thread. Every human action is also written to the
hash-chained ledger, so who did what and when can be audited."""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import config
from auth.store import db
from trust import ledger

# reason -> (kind, priority)
REASONS: Dict[str, tuple] = {
    "user_requested": ("handoff", "normal"),
    "guardrail_failures": ("handoff", "normal"),
    "stuck_in_questions": ("handoff", "normal"),
    "low_confidence": ("handoff", "normal"),
    "complaint": ("complaint", "high"),
    "distress": ("handoff", "urgent"),
    "video_kyc": ("video_kyc", "normal"),
    "callback": ("callback", "normal"),
}
ACTIVE = ("open", "assigned")
PRIORITY_ORDER = "CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 ELSE 2 END"

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reference     TEXT NOT NULL UNIQUE,
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id    TEXT,
    kind          TEXT NOT NULL,
    reason        TEXT NOT NULL,
    priority      TEXT NOT NULL CHECK (priority IN ('urgent', 'high', 'normal')),
    status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'assigned', 'resolved', 'cancelled')),
    language      TEXT,
    channel       TEXT,
    summary       JSONB NOT NULL DEFAULT '[]',     -- the masked recent conversation
    note          TEXT,                            -- what the customer said when asking (masked)
    assigned_to   UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    sla_due_at    TIMESTAMPTZ NOT NULL,
    assigned_at   TIMESTAMPTZ,
    closed_at     TIMESTAMPTZ,
    outcome       TEXT,
    resolution    TEXT,
    scheduled_for TIMESTAMPTZ,                     -- video KYC slot
    meeting_url   TEXT,
    trace_id      TEXT
);
CREATE INDEX IF NOT EXISTS cases_queue_idx ON cases(status, priority, created_at);
CREATE INDEX IF NOT EXISTS cases_user_idx ON cases(user_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS cases_one_active_idx ON cases(user_id) WHERE status IN ('open', 'assigned');
CREATE TABLE IF NOT EXISTS case_messages (
    id        BIGSERIAL PRIMARY KEY,
    case_id   UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    sender    TEXT NOT NULL CHECK (sender IN ('customer', 'executive', 'system')),
    author_id UUID REFERENCES users(id) ON DELETE SET NULL,
    text      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS case_messages_case_idx ON case_messages(case_id, id);
"""

COLUMNS = ("id, reference, user_id, session_id, kind, reason, priority, status, language, channel, summary, note, assigned_to, "
           "created_at, sla_due_at, assigned_at, closed_at, outcome, resolution, scheduled_for, meeting_url, trace_id")


async def init_schema() -> None:
    from tenancy.db import create_tables
    await create_tables(db(), SCHEMA)


def _audit(case: dict, event: str, actor: Optional[str] = None, **extra) -> None:
    ledger.append("case", f"case:{case['id']}", {"event": event, "reference": case["reference"], "kind": case["kind"],
                                                 "reason": case["reason"], "actor": actor, **extra}, case.get("trace_id"))


def _clean(row: Optional[dict]) -> Optional[dict]:
    if row is None:
        return None
    out = dict(row)
    for k in ("id", "user_id", "assigned_to"):
        out[k] = str(out[k]) if out.get(k) else None
    return out


async def active_for(user_id: str) -> Optional[dict]:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(f"SELECT {COLUMNS} FROM cases WHERE user_id = %s AND status IN ('open', 'assigned')", (user_id,))
        return _clean(await cur.fetchone())


async def open_case(user_id: str, reason: str, *, session_id: Optional[str], summary: List[dict], language: Optional[str],
                    channel: Optional[str], note: Optional[str] = None, trace_id: Optional[str] = None) -> tuple:
    """(case, created). A person has at most one active case: asking again adds to it rather than opening another, and
    a more serious reason raises its priority."""
    kind, priority = REASONS.get(reason, ("handoff", "normal"))
    existing = await active_for(user_id)
    if existing:
        rank = {"urgent": 0, "high": 1, "normal": 2}
        if rank[priority] < rank[existing["priority"]]:
            async with db().connection() as conn:
                await conn.execute("UPDATE cases SET priority = %s, sla_due_at = LEAST(sla_due_at, %s) WHERE id = %s",
                                   (priority, datetime.now(timezone.utc) + timedelta(minutes=config.DESK_SLA_MINUTES[priority]),
                                    existing["id"]))
            existing["priority"] = priority
        if note:
            await add_message(existing["id"], "system", f"Asked again ({reason}): {note}")
        return existing, False
    due = datetime.now(timezone.utc) + timedelta(minutes=config.DESK_SLA_MINUTES[priority])
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"""INSERT INTO cases (reference, user_id, session_id, kind, reason, priority, language, channel, summary, note,
                                   sla_due_at, trace_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {COLUMNS}""",
            (secrets.token_hex(6), user_id, session_id, kind, reason, priority, language, channel, Jsonb(summary), note, due, trace_id))
        case = _clean(await cur.fetchone())
    _audit(case, "opened", priority=priority)
    return case, True


async def get(case_id: str) -> Optional[dict]:
    try:
        import uuid
        uuid.UUID(case_id)
    except ValueError:
        return None
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(f"SELECT {COLUMNS} FROM cases WHERE id = %s", (case_id,))
        return _clean(await cur.fetchone())


async def queue(view: str, executive_id: str, limit: int = 100) -> List[dict]:
    """open: waiting for someone; mine: assigned to this executive; overdue: active and past due; all: every active case."""
    where = {"open": "status = 'open'", "mine": "status = 'assigned' AND assigned_to = %(me)s",
             "overdue": "status IN ('open', 'assigned') AND sla_due_at < now()",
             "all": "status IN ('open', 'assigned')"}[view]
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"""SELECT c.id, c.reference, c.kind, c.reason, c.priority, c.status, c.language, c.channel, c.created_at, c.sla_due_at,
                       c.assigned_to, c.scheduled_for, u.name AS customer_name, u.username AS customer_username,
                       (c.sla_due_at < now()) AS overdue,
                       (SELECT count(*) FROM case_messages m WHERE m.case_id = c.id) AS messages
                FROM cases c JOIN users u ON u.id = c.user_id
                WHERE {where} ORDER BY {PRIORITY_ORDER}, c.created_at LIMIT %(n)s""", {"me": executive_id, "n": limit})
        return [_clean(r) for r in await cur.fetchall()]


async def for_customer(user_id: str) -> List[dict]:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("""SELECT id, reference, kind, reason, status, created_at, assigned_at, closed_at, outcome, scheduled_for,
                                    meeting_url FROM cases WHERE user_id = %s ORDER BY created_at DESC LIMIT 50""", (user_id,))
        return [_clean(r) for r in await cur.fetchall()]


async def claim(case_id: str, executive_id: str) -> Optional[dict]:
    """Take an open case. Only one executive can: the update succeeds for the first and finds nothing for the rest."""
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(f"""UPDATE cases SET status = 'assigned', assigned_to = %s, assigned_at = now()
                              WHERE id = %s AND status = 'open' RETURNING {COLUMNS}""", (executive_id, case_id))
        case = _clean(await cur.fetchone())
    if case:
        _audit(case, "claimed", executive_id)
    return case


async def release(case_id: str, executive_id: str) -> Optional[dict]:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(f"""UPDATE cases SET status = 'open', assigned_to = NULL, assigned_at = NULL
                              WHERE id = %s AND status = 'assigned' AND assigned_to = %s RETURNING {COLUMNS}""", (case_id, executive_id))
        case = _clean(await cur.fetchone())
    if case:
        _audit(case, "released", executive_id)
    return case


async def close(case_id: str, status: str, actor: Optional[str], outcome: str, resolution: Optional[str]) -> Optional[dict]:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(f"""UPDATE cases SET status = %s, closed_at = now(), outcome = %s, resolution = %s
                              WHERE id = %s AND status IN ('open', 'assigned') RETURNING {COLUMNS}""",
                          (status, outcome, resolution, case_id))
        case = _clean(await cur.fetchone())
    if case:
        _audit(case, status, actor, outcome=outcome)
    return case


async def schedule(case_id: str, executive_id: str, when: datetime, url: Optional[str]) -> Optional[dict]:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(f"""UPDATE cases SET scheduled_for = %s, meeting_url = %s
                              WHERE id = %s AND status = 'assigned' AND assigned_to = %s RETURNING {COLUMNS}""",
                          (when, url, case_id, executive_id))
        case = _clean(await cur.fetchone())
    if case:
        _audit(case, "video_kyc_scheduled", executive_id, scheduled_for=when.isoformat())
    return case


async def add_message(case_id: str, sender: str, text: str, author_id: Optional[str] = None) -> dict:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("INSERT INTO case_messages (case_id, sender, author_id, text) VALUES (%s, %s, %s, %s) "
                          "RETURNING id, at, sender, text", (case_id, sender, author_id, text))
        return await cur.fetchone()


async def messages(case_id: str) -> List[dict]:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT id, at, sender, text FROM case_messages WHERE case_id = %s ORDER BY id", (case_id,))
        return await cur.fetchall()


async def stats() -> dict:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("""SELECT count(*) FILTER (WHERE status = 'open') AS waiting,
                                    count(*) FILTER (WHERE status = 'assigned') AS in_progress,
                                    count(*) FILTER (WHERE status IN ('open', 'assigned') AND sla_due_at < now()) AS overdue,
                                    count(*) FILTER (WHERE status = 'open' AND priority = 'urgent') AS urgent_waiting,
                                    EXTRACT(EPOCH FROM avg(assigned_at - created_at)) AS avg_wait_seconds
                             FROM cases WHERE created_at > now() - interval '7 days'""")
        row = await cur.fetchone()
    return {k: (round(float(v), 1) if isinstance(v, (float,)) or k == "avg_wait_seconds" and v is not None else v) for k, v in row.items()}
