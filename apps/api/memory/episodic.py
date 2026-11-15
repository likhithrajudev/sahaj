"""Layer 2 - episodic memory: what happened in past conversations. One episode per conversation: when, on which channel
and in which language, what was asked about (intents), how it ended (answered, handed to a person, abandoned), and a
short masked summary. Kept in Postgres, per person, only with their `memory` consent; erased when it is withdrawn.

Each summary is also embedded, so semantic recall (semantic.py) can bring back the past conversations that bear on the
question being asked now, rather than just the latest ones."""
from collections import Counter
from datetime import datetime, timezone
from typing import List, Optional

from pgvector import Vector
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import config
from auth.store import db

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS episodes (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id     TEXT NOT NULL,
    started_at     TIMESTAMPTZ NOT NULL,
    ended_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    channel        TEXT,
    language       TEXT,
    turns          INT NOT NULL DEFAULT 0,
    intents        JSONB NOT NULL DEFAULT '{{}}',
    outcome        TEXT NOT NULL,
    case_reference TEXT,
    summary        TEXT,
    embedding      vector({int(config.EMBED_DIM)}),
    UNIQUE (user_id, session_id)
);
CREATE INDEX IF NOT EXISTS episodes_user_idx ON episodes(user_id, ended_at DESC);
"""


async def init_schema() -> None:
    from tenancy.db import create_tables
    await create_tables(db(), SCHEMA)


def describe(session) -> dict:
    """The facts of a conversation, from the session itself (no model call)."""
    intents = Counter(m.get("intent") for m in session.history if m["role"] == "user" and m.get("intent"))
    outcome = "handed_to_person" if session.case else ("answered" if session._turns else "abandoned")
    return {"session_id": session.id, "started_at": session.started_at, "channel": session.channel,
            "language": session.user.language, "turns": session._turns, "intents": dict(intents), "outcome": outcome,
            "case_reference": session.case["reference"] if session.case else None}


async def record(user, facts: dict, summary: Optional[str], embedding: Optional[List[float]]) -> None:
    """Write (or, for a resumed conversation, update) the episode."""
    async with db().connection() as conn:
        await conn.execute(
            """INSERT INTO episodes (user_id, session_id, started_at, channel, language, turns, intents, outcome, case_reference,
                                     summary, embedding)
               VALUES (%(u)s, %(session_id)s, %(started_at)s, %(channel)s, %(language)s, %(turns)s, %(intents)s, %(outcome)s,
                       %(case_reference)s, %(summary)s, %(embedding)s)
               ON CONFLICT (user_id, session_id) DO UPDATE SET ended_at = now(), turns = EXCLUDED.turns, intents = EXCLUDED.intents,
                   outcome = EXCLUDED.outcome, case_reference = EXCLUDED.case_reference,
                   summary = COALESCE(EXCLUDED.summary, episodes.summary), embedding = COALESCE(EXCLUDED.embedding, episodes.embedding)""",
            {**facts, "u": user.id, "intents": Jsonb(facts["intents"]), "summary": summary,
             "embedding": Vector(embedding) if embedding else None,
             "started_at": facts["started_at"] or datetime.now(timezone.utc)})


async def list_for(user_id: str, limit: int = 50) -> List[dict]:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("""SELECT id, session_id, started_at, ended_at, channel, language, turns, intents, outcome, case_reference,
                                    summary FROM episodes WHERE user_id = %s ORDER BY ended_at DESC LIMIT %s""", (user_id, limit))
        return [{**r, "id": str(r["id"])} for r in await cur.fetchall()]


async def similar(user_id: str, vector: List[float], k: int) -> List[dict]:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("""SELECT summary, ended_at, outcome, 1 - (embedding <=> %(v)s) AS similarity FROM episodes
                             WHERE user_id = %(u)s AND embedding IS NOT NULL AND summary IS NOT NULL
                             ORDER BY embedding <=> %(v)s LIMIT %(k)s""", {"v": Vector(vector), "u": user_id, "k": k})
        return await cur.fetchall()


async def delete_one(user_id: str, episode_id: str) -> bool:
    import uuid
    try:
        uuid.UUID(episode_id)
    except ValueError:
        return False
    async with db().connection() as conn:
        return (await conn.execute("DELETE FROM episodes WHERE user_id = %s AND id = %s", (user_id, episode_id))).rowcount > 0


async def delete_all(user_id: str) -> int:
    async with db().connection() as conn:
        return (await conn.execute("DELETE FROM episodes WHERE user_id = %s", (user_id,))).rowcount
