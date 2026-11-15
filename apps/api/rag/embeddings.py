"""Embeddings from OpenAI (text-embedding-3-small by default): no model to download or host.

Cost control, in order:
  1. in-memory cache of query embeddings (this process),
  2. a Postgres cache shared by every process and kept across restarts,
  3. only then a call, batched, and metered against the person who asked.
Only text with nothing personal in it is cached (no digits, no masked identifiers)."""
import asyncio
import hashlib
import logging
from typing import List, Optional

import httpx
from pgvector import Vector

import config
from services import telemetry
from services.cache import EMBEDDING_CACHE

log = logging.getLogger("sahaj.embeddings")
BATCH = 256
RETRY_STATUS = {429, 500, 502, 503, 504}

CACHE_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS embedding_cache (
    key        TEXT PRIMARY KEY,            -- sha256 of model, dimension and text
    embedding  vector({int(config.EMBED_DIM)}) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def loaded() -> bool:
    """Embeddings can be made: there is a key to call the API with."""
    return bool(config.OPENAI_API_KEY)


async def warm_up() -> None:
    if not loaded():
        raise RuntimeError("OPENAI_API_KEY is not set, so nothing can be embedded and the knowledge base cannot be searched.")


async def _call(texts: List[str], purpose: str) -> List[List[float]]:
    """One API call per batch of up to 256 texts, with retries on rate limits and server errors."""
    await warm_up()
    vectors: List[List[float]] = []
    async with httpx.AsyncClient(timeout=60) as client:
        for start in range(0, len(texts), BATCH):
            batch = texts[start:start + BATCH]
            for attempt in range(4):
                r = await client.post(f"{config.OPENAI_BASE_URL}/v1/embeddings",
                                      headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
                                      json={"model": config.EMBED_MODEL, "input": batch, "dimensions": config.EMBED_DIM})
                if r.status_code not in RETRY_STATUS or attempt == 3:
                    break
                await asyncio.sleep(2 ** attempt)
            r.raise_for_status()
            data = r.json()
            vectors += [item["embedding"] for item in sorted(data["data"], key=lambda d: d["index"])]
            tokens = (data.get("usage") or {}).get("prompt_tokens", 0)
            telemetry.meter({"kind": "embedding", "provider": "openai", "model": config.EMBED_MODEL, "purpose": purpose,
                             "input_tokens": tokens, "cost_usd": tokens * config.OPENAI_EMBED_PRICE_PER_M / 1_000_000})
    return vectors


async def embed_passages(texts: List[str]) -> List[List[float]]:
    """Embeddings of documents (the knowledge base, a person's PDFs). Not cached: each is embedded once and stored."""
    return await _call(texts, "embed_documents") if texts else []


def _personal(text: str) -> bool:
    return any(c.isdigit() for c in text) or "[" in text


def _key(text: str) -> str:
    return hashlib.sha256(f"{config.EMBED_MODEL}|{config.EMBED_DIM}|{text}".encode()).hexdigest()


async def init_cache() -> None:
    import tenancy
    from rag import store
    with tenancy.system():
        async with store.pool().connection() as conn:
            await conn.execute(CACHE_SCHEMA)
            await conn.execute(f"GRANT SELECT, INSERT ON embedding_cache TO {config.DB_APP_ROLE}")


async def _shared_get(keys: List[str]) -> dict:
    try:
        from rag import store
        async with store.pool().connection() as conn:
            rows = await (await conn.execute("SELECT key, embedding FROM embedding_cache WHERE key = ANY(%s)", (keys,))).fetchall()
        return {k: [float(x) for x in v] for k, v in rows}
    except Exception as e:   # the shared cache is an optimisation: without it we just pay for the call
        log.debug("Embedding cache unavailable: %s", e)
        return {}


async def _shared_put(items: List[tuple]) -> None:
    try:
        from rag import store
        async with store.pool().connection() as conn:
            for key, vector in items:
                await conn.execute("INSERT INTO embedding_cache (key, embedding) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                                   (key, Vector(vector)))
    except Exception as e:
        log.debug("Embedding cache unavailable: %s", e)


async def embed_queries(texts: List[str]) -> List[List[float]]:
    """Embeddings of search queries: from the process cache, then the shared cache, then the API."""
    results: List[Optional[List[float]]] = [None] * len(texts)
    cacheable = [config.APP_CACHE_ENABLED and not _personal(t) for t in texts]
    for i, text in enumerate(texts):
        if cacheable[i] and (hit := EMBEDDING_CACHE.get(text)) is not None:
            results[i] = hit
    shared_wanted = {_key(t): i for i, t in enumerate(texts) if results[i] is None and cacheable[i]}
    if shared_wanted:
        for key, vector in (await _shared_get(list(shared_wanted))).items():
            results[shared_wanted[key]] = vector
            EMBEDDING_CACHE.set(texts[shared_wanted[key]], vector)
    for i, ok in enumerate(cacheable):
        if ok:
            telemetry.record_cache("embeddings", results[i] is not None)
    todo = [i for i, r in enumerate(results) if r is None]
    if todo:
        fresh = await _call([texts[i] for i in todo], "embed_query")
        to_share = []
        for i, vector in zip(todo, fresh):
            results[i] = vector
            if cacheable[i]:
                EMBEDDING_CACHE.set(texts[i], vector)
                to_share.append((_key(texts[i]), vector))
        if to_share:
            await _shared_put(to_share)
    return results
