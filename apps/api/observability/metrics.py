"""Prometheus metrics, served at /metrics. Labels are small fixed sets (routes by template, intents, purposes): never
a user, session, query string or any text, so nothing personal can reach Prometheus."""
import logging

from prometheus_client import Counter, Gauge, Histogram

log = logging.getLogger("sahaj.metrics")

HTTP_REQUESTS = Counter("sahaj_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_SECONDS = Histogram("sahaj_http_request_seconds", "HTTP request duration (streams: until the stream ends)",
                         ["method", "route"], buckets=(.01, .05, .1, .25, .5, 1, 2.5, 5, 10, 30, 60))
RATE_LIMITED = Counter("sahaj_rate_limited_total", "Requests refused by the rate limiter", ["limit"])
WS_CONNECTIONS = Gauge("sahaj_ws_connections", "Open voice WebSocket connections")

TURNS = Counter("sahaj_turns_total", "Conversation turns", ["channel", "outcome"])
TURN_SECONDS = Histogram("sahaj_turn_seconds", "Time to handle one turn", ["channel"],
                         buckets=(.5, 1, 2, 3, 5, 8, 12, 20, 30, 60))
INTENTS = Counter("sahaj_intents_total", "Classified intents", ["intent", "source"])
GUARDRAIL = Counter("sahaj_guardrail_total", "Reply checks", ["verdict", "agent"])
HANDOFFS = Counter("sahaj_handoffs_total", "Hand-offs to a person", ["reason"])
NODE_SECONDS = Histogram("sahaj_graph_node_seconds", "Time in each orchestrator node", ["node"],
                         buckets=(.005, .02, .1, .5, 1, 2, 5, 10, 30))

LLM_CALLS = Counter("sahaj_llm_calls_total", "Model calls", ["purpose", "cache"])
LLM_SECONDS = Histogram("sahaj_llm_seconds", "Model call duration", ["purpose"], buckets=(.25, .5, 1, 2, 4, 8, 15, 30, 60))
LLM_TOKENS = Counter("sahaj_llm_tokens_total", "Model tokens", ["purpose", "kind"])
CACHE = Counter("sahaj_cache_total", "Cache lookups", ["layer", "result"])

AUTH_EVENTS = Counter("sahaj_auth_events_total", "Sign-in activity", ["event"])
MEMORY_EVENTS = Counter("sahaj_memory_events_total", "Per-user memory activity", ["event"])


def observe(step: str, data: dict) -> None:
    """Turn one audit-trace step into metrics. Called from Trace.add, so every instrumented step is counted once."""
    try:
        if step == "llm":
            purpose = data["purpose"]
            LLM_CALLS.labels(purpose, "hit" if data["app_cache_hit"] else "miss").inc()
            LLM_SECONDS.labels(purpose).observe(data["ms"] / 1000)
            for kind, key in (("input", "input_tokens"), ("output", "output_tokens"), ("cached", "cached_tokens")):
                LLM_TOKENS.labels(purpose, kind).inc(data.get(key, 0))
        elif step == "cache":
            CACHE.labels(data["layer"], "hit" if data["hit"] else "miss").inc()
        elif step == "guardrail":
            GUARDRAIL.labels(data["verdict"], data.get("agent", "")).inc()
        elif step == "intent":
            INTENTS.labels(data["intent"], data.get("source", "")).inc()
        elif step == "node":
            NODE_SECONDS.labels(data["name"]).observe(data["ms"] / 1000)
        elif step == "handoff":
            HANDOFFS.labels(data["reason"]).inc()
    except Exception:  # metrics must never break a conversation
        log.debug("Could not record metrics for %s", step, exc_info=True)

FILE_EVENTS = Counter("sahaj_file_events_total", "File storage activity", ["event"])
FEEDBACK = Counter("sahaj_feedback_total", "Ratings given to replies", ["rating"])
CONSENT_EVENTS = Counter("sahaj_consent_events_total", "Consent decisions", ["purpose", "decision"])
COST_USD = Counter("sahaj_cost_usd_total", "Estimated spend in US dollars", ["provider", "kind", "channel"])
BUDGET_EVENTS = Counter("sahaj_budget_events_total", "Spending-limit events", ["event"])
MARKETING_EVENTS = Counter("sahaj_marketing_events_total", "Offers delivered, seen and clicked", ["event"])
CASE_EVENTS = Counter("sahaj_case_events_total", "Executive desk activity", ["event"])
