"""What the LLM layer reports while a turn runs: calls, tokens, cache hits. Recorded into the turn's trace, so
the workflow report can show them. Only metadata is recorded, never prompt or reply text."""
from contextvars import ContextVar
from typing import Optional

current_trace: ContextVar = ContextVar("current_trace", default=None)      # trust.audit.Trace of the running turn
current_session: ContextVar[Optional[str]] = ContextVar("current_session", default=None)  # the conversation id
# LangChain looks caches up inside child tasks, so a plain flag set there would be lost. A shared dict survives.
cache_probe: ContextVar[dict] = ContextVar("cache_probe", default=None)  # {"hit": bool}, set by a cache that answers


current_channel: ContextVar[str] = ContextVar("current_channel", default="voice")   # voice | text: picks the model provider
# The billable calls of the running turn, as dicts for usage.ledger. The session flushes them when the turn ends.
current_meter: ContextVar[Optional[list]] = ContextVar("current_meter", default=None)


def meter(event: dict) -> None:
    from observability import metrics
    channel = current_channel.get()
    metrics.COST_USD.labels(event["provider"], event["kind"], channel).inc(event.get("cost_usd", 0))
    m = current_meter.get()
    if m is not None:
        m.append({"channel": channel, **event})


def record_llm(purpose: str, ms: float, usage: Optional[dict], app_cache_hit: bool, provider: str = "sarvam", model: str = "") -> None:
    from usage import pricing
    usage = usage or {}
    details = usage.get("input_token_details") or {}
    tokens_in = 0 if app_cache_hit else usage.get("input_tokens", 0)
    tokens_out = 0 if app_cache_hit else usage.get("output_tokens", 0)
    cached = 0 if app_cache_hit else details.get("cache_read", 0)
    cost = pricing.llm_cost(provider, tokens_in, tokens_out, cached)
    meter({"kind": "llm", "provider": provider, "model": model, "purpose": purpose, "input_tokens": tokens_in,
           "output_tokens": tokens_out, "cached_tokens": cached, "cost_usd": cost})
    trace = current_trace.get()
    if trace is None:
        return
    trace.add("llm", purpose=purpose, ms=round(ms, 1), app_cache_hit=app_cache_hit, provider=provider, model=model,
              input_tokens=tokens_in, output_tokens=tokens_out, cached_tokens=cached, cost_usd=round(cost, 8))


def record_speech(kind: str, units: float, cost: float) -> None:
    """A speech-to-text (units = seconds of audio) or text-to-speech (units = characters) request."""
    meter({"kind": kind, "provider": "sarvam", "model": "", "purpose": kind, "units": units, "cost_usd": cost})
    trace = current_trace.get()
    if trace is not None:
        trace.add(kind, provider="sarvam", units=round(units, 2), cost_usd=round(cost, 8))


def record_cache(layer: str, hit: bool, **info) -> None:
    trace = current_trace.get()
    if trace is not None:
        trace.add("cache", layer=layer, hit=hit, **info)
