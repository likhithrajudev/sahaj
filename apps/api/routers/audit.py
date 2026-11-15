import hmac
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse

import config
from report import render, workflow
from services import cache
from trust import ledger


def require_admin(x_admin_key: Optional[str] = Header(None)) -> None:
    if not config.ADMIN_API_KEY:
        raise HTTPException(503, "Audit API is disabled: set ADMIN_API_KEY.")
    if not x_admin_key or not hmac.compare_digest(x_admin_key, config.ADMIN_API_KEY):
        raise HTTPException(401, "Invalid admin key.")


router = APIRouter(prefix="/audit", tags=["Audit"], dependencies=[Depends(require_admin)])


@router.get("/verify")
def verify():
    """Recompute the hash chain. `intact: false` means a record was altered or removed."""
    return ledger.verify()


@router.get("/session/{subject}")
def session_records(subject: str):
    """Everything recorded for one session: consents, turns and handoffs, in order."""
    return ledger.entries(subject=subject)


@router.get("/trace/{trace_id}")
def trace(trace_id: str):
    """The full step-by-step trace of a single turn."""
    return ledger.entries(trace_id=trace_id)


def _format(report: dict, format: str):
    if format == "md":
        return PlainTextResponse(render.to_markdown(report), media_type="text/markdown")
    if format == "html":
        return HTMLResponse(render.to_html(report))
    if format != "json":
        raise HTTPException(400, "format must be json, md or html")
    return report


@router.get("/report/{subject}")
def session_report(subject: str, format: str = Query("json", description="json, md or html"),
                   include_text: bool = Query(True, description="false drops transcripts and replies, leaving metrics only")):
    """The workflow report for one conversation: intents, route through the graph, timings, tokens, cache hits,
    guardrail results, consents, handoffs and recommendations (ranges only)."""
    if not ledger.entries(subject=subject, kind="audit"):
        raise HTTPException(404, "No audited turns for that session.")
    return _format(workflow.build(subject, include_text), format)


@router.get("/report")
def overview_report(limit: int = Query(50, ge=1, le=500), format: str = Query("json", description="json, md or html")):
    """The same measures across the most recent sessions (no per-turn detail)."""
    return _format(workflow.build_overview(limit), format)


@router.get("/caches")
def cache_stats():
    """Live hit rates of the in-memory caches since this process started."""
    return cache.all_stats()
