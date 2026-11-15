"""The gateway layer (request ids, rate limits, body cap, headers, access log), Prometheus metrics and LangSmith setup."""
import asyncio
import logging
import os
import sys
from pathlib import Path

import httpx
import pytest
from prometheus_client import REGISTRY

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from gateway import limiter as limiter_module
from observability import tracing
from trust import ledger
from trust.audit import Trace


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LEDGER_DB", str(tmp_path / "ledger.db"))
    monkeypatch.setattr(ledger, "_conn", None)
    monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", True)
    limiter_module.LIMITER.reset()


def call(method, path, **kw):
    from main import app

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            return await c.request(method, path, **kw)
    return asyncio.run(go())


def sample(name, **labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


# ---------------------------------------------------------------- request ids, headers
def test_every_response_has_a_request_id_and_security_headers():
    r = call("GET", "/health")
    assert len(r.headers["x-request-id"]) == 32
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"


def test_a_sensible_request_id_is_kept_and_a_bad_one_replaced():
    assert call("GET", "/health", headers={"X-Request-ID": "abc-12345678"}).headers["x-request-id"] == "abc-12345678"
    bad = call("GET", "/health", headers={"X-Request-ID": "x\ny" * 5})
    assert bad.headers["x-request-id"] != "x\ny" * 5 and len(bad.headers["x-request-id"]) == 32


def test_responses_holding_tokens_or_personal_data_are_not_cacheable():
    assert call("POST", "/auth/refresh", json={"refresh_token": "x"}).headers["cache-control"] == "no-store"
    assert "cache-control" not in call("GET", "/health").headers


# ---------------------------------------------------------------- rate limiting
def test_rate_limit_returns_429_with_retry_after_and_counts_it(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_AUTH_PER_MIN", 3)
    before = sample("sahaj_rate_limited_total", limit="auth")
    codes = [call("POST", "/auth/refresh", json={"refresh_token": "x"}).status_code for _ in range(5)]
    assert codes[:3] != [429] * 3 and codes[3:] == [429, 429]
    r = call("POST", "/auth/refresh", json={"refresh_token": "x"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1 and r.json()["request_id"] == r.headers["x-request-id"]
    assert sample("sahaj_rate_limited_total", limit="auth") == before + 3


def test_limits_are_per_class_and_health_is_exempt(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_AUTH_PER_MIN", 1)
    monkeypatch.setattr(config, "RATE_LIMIT_DEFAULT_PER_MIN", 1)
    call("POST", "/auth/refresh", json={"refresh_token": "x"})
    assert call("POST", "/auth/refresh", json={"refresh_token": "x"}).status_code == 429
    assert all(call("GET", "/health").status_code == 200 for _ in range(5))   # exempt
    assert call("GET", "/users/me").status_code == 401                           # the default class has its own bucket


def test_rate_limit_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(config, "RATE_LIMIT_AUTH_PER_MIN", 1)
    assert all(call("POST", "/auth/refresh", json={"refresh_token": "x"}).status_code != 429 for _ in range(4))


def test_forwarded_for_is_only_trusted_when_configured(monkeypatch):
    monkeypatch.setattr(config, "RATE_LIMIT_AUTH_PER_MIN", 1)
    h = lambda ip: {"X-Forwarded-For": ip}
    call("POST", "/auth/refresh", json={"refresh_token": "x"}, headers=h("1.1.1.1"))
    assert call("POST", "/auth/refresh", json={"refresh_token": "x"}, headers=h("2.2.2.2")).status_code == 429  # one client
    limiter_module.LIMITER.reset()
    monkeypatch.setattr(config, "TRUST_PROXY_HEADERS", True)
    call("POST", "/auth/refresh", json={"refresh_token": "x"}, headers=h("1.1.1.1"))
    assert call("POST", "/auth/refresh", json={"refresh_token": "x"}, headers=h("2.2.2.2")).status_code != 429


def test_bucket_refills_over_time(monkeypatch):
    lim = limiter_module.Limiter()
    clock = [100.0]
    monkeypatch.setattr(limiter_module.time, "monotonic", lambda: clock[0])
    assert lim.check("c", "ip", 60) is None
    for _ in range(59):
        assert lim.check("c", "ip", 60) is None
    wait = lim.check("c", "ip", 60)
    assert wait is not None and 0 < wait <= 1.01
    clock[0] += 2
    assert lim.check("c", "ip", 60) is None


def test_voice_socket_connections_are_rate_limited(monkeypatch):
    from fastapi.testclient import TestClient
    from main import app
    monkeypatch.setattr(config, "RATE_LIMIT_WS_PER_MIN", 1)
    client = TestClient(app)
    with client.websocket_connect("/ws/voice") as ws:     # allowed: refused later for having no token (4401)
        assert ws.receive()["code"] == 4401
    with pytest.raises(Exception):                          # refused at the gateway, before it is accepted
        with client.websocket_connect("/ws/voice"):
            pass


# ---------------------------------------------------------------- body size
def test_oversized_bodies_are_refused(monkeypatch):
    monkeypatch.setattr(config, "MAX_BODY_BYTES", 100)
    r = call("POST", "/auth/refresh", content=b"x" * 500, headers={"content-type": "application/json"})
    assert r.status_code == 413 and "request_id" in r.json()

    async def chunks():  # no Content-Length: the gateway has to count
        for _ in range(10):
            yield b"x" * 50
    r = call("POST", "/auth/refresh", content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413


# ---------------------------------------------------------------- access log and metrics
def test_access_log_never_contains_the_query_string(caplog):
    with caplog.at_level(logging.INFO, logger="sahaj.access"):
        logging.getLogger("sahaj").propagate = True   # setup() turns it off; caplog needs it
        call("GET", "/health?access_token=SECRET")
    lines = [r for r in caplog.records if r.name == "sahaj.access"]
    assert lines and all("SECRET" not in r.getMessage() and r.request_id for r in lines)


def test_http_metrics_use_route_templates():
    before = sample("sahaj_http_requests_total", method="GET", route="/health", status="200")
    call("GET", "/health")
    call("DELETE", "/users/me/memory/123")   # 401, but the route template is what is labelled
    assert sample("sahaj_http_requests_total", method="GET", route="/health", status="200") == before + 1
    assert sample("sahaj_http_requests_total", method="DELETE", route="/users/me/memory/{memory_id}", status="401") >= 1
    body = call("GET", "/metrics").text
    assert "/users/me/memory/123" not in body and "sahaj_http_request_seconds_bucket" in body


def test_metrics_endpoint_token(monkeypatch):
    monkeypatch.setattr(config, "METRICS_TOKEN", "s3cret-token")
    assert call("GET", "/metrics").status_code == 401
    assert call("GET", "/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert call("GET", "/metrics", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200


def test_ready_is_503_without_a_database():
    assert call("GET", "/ready").status_code == 503


def test_trace_steps_become_metrics():
    t = Trace("s")
    before_llm = sample("sahaj_llm_tokens_total", purpose="answer", kind="input")
    before_hit = sample("sahaj_cache_total", layer="verified_answers", result="hit")
    t.add("llm", purpose="answer", ms=420.0, app_cache_hit=False, input_tokens=100, output_tokens=20, cached_tokens=60)
    t.add("cache", layer="verified_answers", hit=True)
    t.add("guardrail", verdict="pass", agent="insurance", kind="answer", from_cache=False, reply="x")
    t.add("intent", intent="greeting", confidence=0.9, source="classifier")
    t.add("handoff", reason="user_requested", reference="r")
    assert sample("sahaj_llm_tokens_total", purpose="answer", kind="input") == before_llm + 100
    assert sample("sahaj_llm_tokens_total", purpose="answer", kind="cached") >= 60
    assert sample("sahaj_cache_total", layer="verified_answers", result="hit") == before_hit + 1
    assert sample("sahaj_guardrail_total", verdict="pass", agent="insurance") >= 1
    assert sample("sahaj_intents_total", intent="greeting", source="classifier") >= 1
    assert len(t.steps) == 5   # recording is unchanged


def test_a_metrics_failure_never_breaks_a_turn():
    Trace("s").add("llm", purpose="answer")   # missing fields: must not raise


# ---------------------------------------------------------------- LangSmith
@pytest.fixture
def clean_env(monkeypatch):
    for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING", "LANGSMITH_API_KEY",
                 "LANGSMITH_PROJECT", "LANGSMITH_HIDE_INPUTS", "LANGSMITH_HIDE_OUTPUTS", "LANGSMITH_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)


def test_tracing_is_off_by_default_and_overrides_stray_environment(clean_env, monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")     # an old name someone left behind
    monkeypatch.setattr(config, "LANGSMITH_TRACING", False)
    assert tracing.setup() is False
    assert os.environ["LANGCHAIN_TRACING_V2"] == "false" and os.environ["LANGSMITH_TRACING"] == "false"


def test_tracing_needs_both_the_flag_and_a_key(clean_env, monkeypatch):
    monkeypatch.setattr(config, "LANGSMITH_TRACING", True)
    monkeypatch.setattr(config, "LANGSMITH_API_KEY", None)
    assert tracing.setup() is False and os.environ["LANGSMITH_TRACING"] == "false"


def test_tracing_on_hides_prompts_by_default(clean_env, monkeypatch):
    monkeypatch.setattr(config, "LANGSMITH_TRACING", True)
    monkeypatch.setattr(config, "LANGSMITH_API_KEY", "lsv2_test")
    monkeypatch.setattr(config, "LANGSMITH_PROJECT", "sahaj-test")
    monkeypatch.setattr(config, "LANGSMITH_HIDE_IO", True)
    assert tracing.setup() is True
    assert os.environ["LANGSMITH_TRACING"] == "true" and os.environ["LANGSMITH_PROJECT"] == "sahaj-test"
    assert os.environ["LANGSMITH_HIDE_INPUTS"] == "true" and os.environ["LANGSMITH_HIDE_OUTPUTS"] == "true"
    monkeypatch.setattr(config, "LANGSMITH_HIDE_IO", False)
    tracing.setup()
    assert os.environ["LANGSMITH_HIDE_INPUTS"] == "false"


def test_run_config_describes_the_turn_without_identifying_the_person():
    uid = "11111111-1111-1111-1111-111111111111"
    rc = tracing.run_config(session_id="s1", user_id=uid, language="hi-IN", channel="text", trace_id="t1", memory=True)
    assert rc["run_name"] == "sahaj_turn" and {"channel:text", "lang:hi-IN", "memory"} <= set(rc["tags"])
    assert rc["metadata"]["audit_trace_id"] == "t1" and rc["metadata"]["user_ref"] == tracing.person(uid)
    assert uid not in str(rc) and tracing.person(uid) == tracing.person(uid) != tracing.person("someone-else")
