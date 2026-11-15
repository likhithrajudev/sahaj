"""Thumbs up/down on replies, so quality problems can be found and traced back to the exact turn (trace_id)."""
from typing import List, Optional

from psycopg.rows import dict_row

from auth.store import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS reply_feedback (
    id         BIGSERIAL PRIMARY KEY,
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    trace_id   TEXT NOT NULL,
    rating     TEXT NOT NULL CHECK (rating IN ('up', 'down')),
    comment    TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, trace_id)
);
CREATE INDEX IF NOT EXISTS reply_feedback_rating_idx ON reply_feedback(rating, created_at DESC);
"""


async def init_schema() -> None:
    async with db().connection() as conn:
        await conn.execute(SCHEMA)


async def save(user_id: str, trace_id: str, rating: str, comment: Optional[str]) -> None:
    """One rating per person per reply; rating again replaces it."""
    async with db().connection() as conn:
        await conn.execute(
            """INSERT INTO reply_feedback (user_id, trace_id, rating, comment) VALUES (%s, %s, %s, %s)
               ON CONFLICT (user_id, trace_id) DO UPDATE SET rating = EXCLUDED.rating, comment = EXCLUDED.comment,
                                                              created_at = now()""",
            (user_id, trace_id, rating, comment))


async def for_user(user_id: str) -> List[dict]:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT trace_id, rating, comment, created_at FROM reply_feedback WHERE user_id = %s "
                          "ORDER BY created_at DESC", (user_id,))
        return await cur.fetchall()


async def summary(rating: Optional[str], limit: int) -> dict:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT rating, count(*) AS n FROM reply_feedback GROUP BY rating")
        counts = {r["rating"]: r["n"] for r in await cur.fetchall()}
        await cur.execute("SELECT trace_id, rating, comment, created_at FROM reply_feedback "
                          "WHERE (%(r)s::text IS NULL OR rating = %(r)s) ORDER BY created_at DESC LIMIT %(n)s",
                          {"r": rating, "n": limit})
        return {"counts": {"up": counts.get("up", 0), "down": counts.get("down", 0)}, "recent": await cur.fetchall()}
