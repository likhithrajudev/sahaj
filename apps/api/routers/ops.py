import hmac
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

import config
from auth import store
from financial import providers

router = APIRouter(tags=["Operations"], include_in_schema=False)


@router.get("/metrics")
async def prometheus_metrics(authorization: Optional[str] = Header(None)):
    """Prometheus scrape target. Set METRICS_TOKEN to require `Authorization: Bearer <token>`; keep it off the public internet."""
    if config.METRICS_TOKEN:
        supplied = authorization[7:] if authorization and authorization.lower().startswith("bearer ") else ""
        if not hmac.compare_digest(supplied, config.METRICS_TOKEN):
            raise HTTPException(401, "Invalid metrics token.", headers={"WWW-Authenticate": "Bearer"})
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/ready")
async def ready():
    """Readiness: can this instance serve traffic (is the database reachable)? /health only says the process is up."""
    import tenancy
    try:
        with tenancy.system():
            async with store.db().connection() as conn:
                await conn.execute("SELECT 1")
    except Exception as e:  # any failure means not ready; the reason goes to the log, not to the caller
        import logging
        logging.getLogger("sahaj.ready").warning("Not ready: %s", e)
        raise HTTPException(503, "Not ready: the database is unreachable.")
    try:
        from storage import blob
        storage = "ok" if await blob.get().ready() else "down"
    except Exception:  # not configured: uploads are off, the rest of the service is fine
        storage = "not configured"
    return {"status": "ready", "storage": storage, "knowledge_base": await _knowledge_base(),
            "features": {"google_sign_in": bool(config.GOOGLE_CLIENT_IDS),
                         "web_search": bool(config.FIRECRAWL_API_KEY),
                         "financial_providers": providers.capabilities()}}


async def _knowledge_base() -> dict:
    """Whether questions can be answered: the embedding model is loaded and the knowledge base has clauses."""
    import tenancy
    from rag import embeddings, store as rag_store
    try:
        with tenancy.system():
            have = await rag_store.stats()
    except Exception:
        return {"ok": False, "problem": "database unavailable", "clauses": 0}
    if not have["clauses"]:
        return {"ok": False, "problem": "empty: run `python -m rag.ingest`", **have}
    if not embeddings.loaded():
        return {"ok": False, "problem": "OPENAI_API_KEY not set: queries cannot be embedded", **have}
    return {"ok": True, **have}
