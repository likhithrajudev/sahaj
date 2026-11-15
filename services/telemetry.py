"""What the LLM layer reports while a turn runs: calls, tokens, cache hits. Recorded into the turn's trace, so
the workflow report can show them. Only metadata is recorded, never prompt or reply text."""
from contextvars import ContextVar
from typing import Optional

current_trace: ContextVar = ContextVar("current_trace", default=None)      # trust.audit.Trace of the running turn
current_session: ContextVar[Optional[str]] = ContextVar("current_session", default=None)  # the conversation id
# LangChain looks caches up inside child tasks, so a plain flag set there would be lost. A shared dict survives.
cache_probe: ContextVar[dict] = ContextVar("cache_probe", default=None)  # {"hit": bool}, set by a cache that answers


def record_llm(purpose: str, ms: float, usage: Optional[dict], app_cache_hit: bool) -> None:
    trace = current_trace.get()
    if trace is None:
        return
    usage = usage or {}
    details = usage.get("input_token_details") or {}
    trace.add("llm", purpose=purpose, ms=round(ms, 1), app_cache_hit=app_cache_hit,
              input_tokens=0 if app_cache_hit else usage.get("input_tokens", 0),
              output_tokens=0 if app_cache_hit else usage.get("output_tokens", 0),
              cached_tokens=0 if app_cache_hit else details.get("cache_read", 0))


def record_cache(layer: str, hit: bool, **info) -> None:
    trace = current_trace.get()
    if trace is not None:
        trace.add("cache", layer=layer, hit=hit, **info)
