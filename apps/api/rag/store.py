"""pgvector storage and cosine-similarity search."""
import logging
from typing import Dict, List, Optional

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector_async
from psycopg_pool import AsyncConnectionPool, PoolTimeout

import config

log = logging.getLogger("sahaj.rag")
_pool = None

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id             BIGSERIAL PRIMARY KEY,
    domain         TEXT NOT NULL,
    doc_id         TEXT NOT NULL,
    clause         TEXT NOT NULL,
    content        TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    embed_model    TEXT NOT NULL,
    embedding      vector({int(config.EMBED_DIM)}) NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (domain, doc_id, clause)
);
CREATE INDEX IF NOT EXISTS knowledge_chunks_embedding_idx
    ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);
"""


async def vector_dim(conn, table: str) -> Optional[int]:
    """The dimension of `table`.embedding, or None if the table does not exist."""
    row = await (await conn.execute(
        "SELECT a.atttypmod FROM pg_attribute a WHERE a.attrelid = to_regclass(%s) AND a.attname = 'embedding'", (table,))).fetchone()
    return row[0] if row else None


async def init_schema() -> None:
    async with await psycopg.AsyncConnection.connect(config.DATABASE_URL, autocommit=True) as conn:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        for table in ("knowledge_chunks", "embedding_cache"):
            dim = await vector_dim(conn, table)
            if dim is not None and dim != config.EMBED_DIM:   # embeddings from another model: rebuilt from knowledge/
                log.warning("%s holds %s-dimension embeddings; EMBED_DIM is %s. Rebuilding it.", table, dim, config.EMBED_DIM)
                await conn.execute(f"DROP TABLE {table}")   # table name is one of the two literals above
        await conn.execute(SCHEMA)


async def _configure(conn) -> None:
    await register_vector_async(conn)
    # With the domain filter, plain HNSW can return fewer than k rows. Iterative scan keeps searching.
    await conn.execute("SET hnsw.iterative_scan = strict_order")


async def open_pool() -> None:
    """Fail soft: the app still starts without a database, but nothing can be retrieved (so no answers)."""
    global _pool
    try:
        await init_schema()
        _pool = AsyncConnectionPool(
            config.DATABASE_URL, min_size=1, max_size=5, open=False,
            configure=_configure, kwargs={"autocommit": True},
        )
        await _pool.open(wait=True, timeout=10)
        from tenancy.db import secure
        await secure(pool())   # tenants, the restricted role, row-level security on every tenant table
    except (psycopg.Error, PoolTimeout, OSError) as e:
        log.warning("Knowledge base unavailable, check DATABASE_URL and that Postgres has pgvector: %s", e)
        _pool = None


async def close_pool() -> None:
    if _pool:
        await _pool.close()


def pool():
    """The connection pool, wrapped so every connection carries the caller's tenant (see tenancy/db.py)."""
    if _pool is None:
        raise RuntimeError("The knowledge base is unavailable, so I can't answer right now.")
    from tenancy.db import TenantPool
    return TenantPool(_pool)


async def existing(domain: str, tenant: str = "public") -> Dict[str, dict]:
    async with pool().connection() as conn:
        cur = await conn.execute(
            "SELECT doc_id || ':' || clause, content_sha256, embed_model FROM knowledge_chunks WHERE domain = %s AND tenant_id = %s",
            (domain, tenant),
        )
        return {key: {"sha256": sha, "model": model} for key, sha, model in await cur.fetchall()}


async def sync(domain: str, chunks: List[dict], keep_keys: List[str], tenant: str = "public") -> None:
    """Upsert `chunks` (each with an `embedding`) and delete clauses no longer in the source documents,
    so a withdrawn clause can never be served. The documents in knowledge/ belong to the 'public' tenant: every
    tenant can read them, and a tenant's own documents are added under its id."""
    async with pool().connection() as conn:
        async with conn.transaction():
            for c in chunks:
                await conn.execute(
                    """INSERT INTO knowledge_chunks (tenant_id, domain, doc_id, clause, content, content_sha256, embed_model, embedding)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (tenant_id, domain, doc_id, clause) DO UPDATE SET
                           content = EXCLUDED.content, content_sha256 = EXCLUDED.content_sha256,
                           embed_model = EXCLUDED.embed_model, embedding = EXCLUDED.embedding, updated_at = now()""",
                    (tenant, domain, c["doc_id"], c["clause"], c["content"], c["sha256"], config.EMBED_MODEL, Vector(c["embedding"])),
                )
            await conn.execute(
                "DELETE FROM knowledge_chunks WHERE tenant_id = %s AND domain = %s AND doc_id || ':' || clause <> ALL(%s)",
                (tenant, domain, keep_keys),
            )


async def search(domain: str, vector: List[float], k: int, doc_ids: Optional[List[str]] = None) -> List[dict]:
    """The k clauses of `domain` closest to `vector` by cosine distance, with similarity = 1 - distance.
    `doc_ids` limits the search to those documents (for example one named plan)."""
    only = "AND doc_id = ANY(%s)" if doc_ids else ""
    args = (Vector(vector), domain) + ((doc_ids,) if doc_ids else ()) + (Vector(vector), k)
    async with pool().connection() as conn:
        cur = await conn.execute(
            f"""SELECT doc_id || ':' || clause, content, content_sha256, 1 - (embedding <=> %s) AS similarity
                FROM knowledge_chunks WHERE domain = %s {only}
                ORDER BY embedding <=> %s LIMIT %s""",
            args,
        )
        return [
            {"key": key, "text": text, "sha256": sha, "similarity": float(sim)}
            for key, text, sha, sim in await cur.fetchall()
        ]


async def stats() -> dict:
    """What the knowledge base holds: {"clauses": n, "domains": {domain: n}}. Raises RuntimeError if there is no database."""
    async with pool().connection() as conn:
        cur = await conn.execute("SELECT domain, count(*) FROM knowledge_chunks GROUP BY domain ORDER BY domain")
        domains = {d: n for d, n in await cur.fetchall()}
    return {"clauses": sum(domains.values()), "domains": domains}
