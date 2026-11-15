"""Layer 3 - semantic memory: what Sahaj knows about a person (stable facts and preferences: language, interests,
goals, answer style), kept in Postgres with an embedding each, so the facts and past episodes that bear on the current
question are recalled by meaning, not just by recency. Only with the `memory` consent.

Recall costs one query embedding per turn, and is skipped entirely for people who have nothing remembered."""
import logging
from typing import Dict, List, Optional

from pgvector import Vector
from psycopg.rows import dict_row

import config
from auth.store import db
from memory import episodic

log = logging.getLogger("sahaj.semantic")
ALWAYS = ("preferred_language", "preferred_style")   # preferences shape every answer, whatever the question

SCHEMA = f"ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS embedding vector({int(config.EMBED_DIM)});"


async def init_schema() -> None:
    from tenancy.db import create_tables
    await create_tables(db(), SCHEMA)


async def store_facts(user_id: str, facts: Dict[str, str]) -> None:
    """Upsert facts with their embeddings (one batched call for all of them)."""
    if not facts:
        return
    from rag.embeddings import embed_passages
    items = list(facts.items())
    vectors = await embed_passages([f"{k.replace('_', ' ')}: {v}" for k, v in items])
    async with db().connection() as conn:
        async with conn.transaction():
            for (k, v), vector in zip(items, vectors):
                await conn.execute(
                    """INSERT INTO user_memories (user_id, kind, key, content, embedding) VALUES (%s, 'fact', %s, %s, %s)
                       ON CONFLICT (user_id, key) WHERE kind = 'fact'
                       DO UPDATE SET content = EXCLUDED.content, embedding = EXCLUDED.embedding, updated_at = now()""",
                    (user_id, k, v, Vector(vector)))


async def _has_anything(user_id: str) -> bool:
    async with db().connection() as conn:
        row = await (await conn.execute(
            "SELECT EXISTS (SELECT 1 FROM user_memories WHERE user_id = %(u)s) OR EXISTS (SELECT 1 FROM episodes WHERE user_id = %(u)s)",
            {"u": user_id})).fetchone()
        return bool(row[0])


async def recall(user_id: str, question: str, k_facts: int = 4, k_episodes: int = 2) -> Optional[str]:
    """The remembered facts and past conversations relevant to `question`, as prompt text, or None."""
    try:
        if not question.strip() or not await _has_anything(user_id):
            return None
        from rag.embeddings import embed_queries
        (vector,) = await embed_queries([question])
        async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """SELECT key, content, CASE WHEN embedding IS NULL THEN 0 ELSE 1 - (embedding <=> %(v)s) END AS similarity
                   FROM user_memories WHERE user_id = %(u)s AND kind = 'fact'""", {"v": Vector(vector), "u": user_id})
            facts = await cur.fetchall()
        chosen = [f for f in facts if f["key"] in ALWAYS]
        ranked = sorted((f for f in facts if f["key"] not in ALWAYS and f["similarity"] >= config.SEMANTIC_MIN_SIMILARITY),
                        key=lambda f: -f["similarity"])
        chosen += ranked[:k_facts]
        episodes = [e for e in await episodic.similar(user_id, vector, k_episodes) if e["similarity"] >= config.SEMANTIC_MIN_SIMILARITY]
        return render(chosen, episodes)
    except Exception as e:   # memory is a help, never a reason for a turn to fail
        log.warning("Could not recall memory: %s", e)
        return None


def render(facts: List[dict], episodes: List[dict]) -> Optional[str]:
    parts = []
    if facts:
        parts.append("; ".join(f"{f['key'].replace('_', ' ')}: {f['content']}" for f in facts))
    if episodes:
        parts.append("Related earlier conversations: " + " ".join(f"({e['ended_at']:%d %b}) {e['summary']}" for e in episodes))
    return " ".join(parts) or None
