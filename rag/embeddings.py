"""Local multilingual embeddings (e5 family). Runs in a worker thread so it never blocks the event loop."""
import asyncio
from typing import List

import config
from services import telemetry
from services.cache import EMBEDDING_CACHE

_model = None


def _load():
    global _model
    if _model is None:
        from fastembed import TextEmbedding

        _model = TextEmbedding(config.EMBED_MODEL, cache_dir=config.EMBED_CACHE_DIR)
    return _model


def _embed(texts: List[str]) -> List[List[float]]:
    return [[float(x) for x in v] for v in _load().embed(texts)]


async def warm_up() -> None:
    await asyncio.to_thread(_load)


# e5 models are trained with these prefixes; leaving them out noticeably hurts accuracy.
async def embed_passages(texts: List[str]) -> List[List[float]]:
    return await asyncio.to_thread(_embed, ["passage: " + t for t in texts])


def _personal(text: str) -> bool:
    return any(c.isdigit() for c in text) or "[" in text


async def embed_queries(texts: List[str]) -> List[List[float]]:
    """Embeddings of search queries. Repeated, non-personal queries are served from an in-memory cache."""
    results: List = [None] * len(texts)
    todo = []
    for i, text in enumerate(texts):
        cacheable = config.APP_CACHE_ENABLED and not _personal(text)
        cached = EMBEDDING_CACHE.get(text) if cacheable else None
        if cacheable:
            telemetry.record_cache("embeddings", cached is not None)
        if cached is not None:
            results[i] = cached
        else:
            todo.append((i, text, cacheable))
    if todo:
        vectors = await asyncio.to_thread(_embed, ["query: " + t for _, t, _ in todo])
        for (i, text, cacheable), vector in zip(todo, vectors):
            results[i] = vector
            if cacheable:
                EMBEDDING_CACHE.set(text, vector)
    return results
