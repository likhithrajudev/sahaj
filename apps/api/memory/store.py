"""What Sahaj remembers about a person between conversations. Every row belongs to one user and goes when they
withdraw the 'memory' consent, delete an item, or delete their account."""
from typing import List

from psycopg.rows import dict_row

import config
from auth.store import db


async def all_for(user_id: str) -> List[dict]:
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT id, kind, key, content, created_at, updated_at FROM user_memories "
                          "WHERE user_id = %s ORDER BY kind, created_at DESC", (user_id,))
        return await cur.fetchall()


async def for_prompt(user_id: str) -> List[dict]:
    """Facts, plus the most recent few summaries."""
    async with db().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """(SELECT kind, key, content FROM user_memories WHERE user_id = %(u)s AND kind = 'fact' ORDER BY key)
               UNION ALL
               (SELECT kind, key, content FROM user_memories WHERE user_id = %(u)s AND kind = 'summary'
                ORDER BY created_at DESC LIMIT %(n)s)""",
            {"u": user_id, "n": config.MEMORY_PROMPT_SUMMARIES})
        return await cur.fetchall()


async def save(user_id: str, summary: str, facts: dict) -> None:
    async with db().connection() as conn:
        async with conn.transaction():
            if summary:
                await conn.execute("INSERT INTO user_memories (user_id, kind, content) VALUES (%s, 'summary', %s)",
                                   (user_id, summary))
                await conn.execute(
                    """DELETE FROM user_memories WHERE user_id = %(u)s AND kind = 'summary' AND id NOT IN
                       (SELECT id FROM user_memories WHERE user_id = %(u)s AND kind = 'summary'
                        ORDER BY created_at DESC LIMIT %(n)s)""",
                    {"u": user_id, "n": config.MEMORY_MAX_SUMMARIES})
            for key, value in facts.items():
                await conn.execute(
                    """INSERT INTO user_memories (user_id, kind, key, content) VALUES (%s, 'fact', %s, %s)
                       ON CONFLICT (user_id, key) WHERE kind = 'fact'
                       DO UPDATE SET content = EXCLUDED.content, updated_at = now()""",
                    (user_id, key, value))


async def delete_one(user_id: str, memory_id: int) -> bool:
    async with db().connection() as conn:
        cur = await conn.execute("DELETE FROM user_memories WHERE user_id = %s AND id = %s", (user_id, memory_id))
        return cur.rowcount > 0


async def delete_all(user_id: str) -> int:
    async with db().connection() as conn:
        cur = await conn.execute("DELETE FROM user_memories WHERE user_id = %s", (user_id,))
        return cur.rowcount
