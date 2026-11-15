"""What calls cost, the monthly limit per person, which provider answers which channel, and the savings."""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from auth import google, store
from orchestrator import intent, session as session_module
from orchestrator.turn import Turn
from services import llm, telemetry
from trust import ledger
from usage import ledger as usage_ledger, pricing

USER = store.User(id="11111111-1111-1111-1111-111111111111", email="a@example.com", name="Asha", picture=None,
                  language="en-IN", platform="web", role="user", username="a")


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LEDGER_DB", str(tmp_path / "ledger.db"))
    monkeypatch.setattr(ledger, "_conn", None)
    monkeypatch.setattr(config, "JWT_SECRET", "x" * 40)


# ---------------------------------------------------------------- prices
def test_llm_cost_splits_cached_input_from_fresh(monkeypatch):
    for name, v in (("OPENAI_PRICE_IN_PER_M", 0.15), ("OPENAI_PRICE_CACHED_PER_M", 0.075), ("OPENAI_PRICE_OUT_PER_M", 0.60)):
        monkeypatch.setattr(config, name, v)
    # 1000 input of which 600 cached, 200 output: 400 * 0.15 + 600 * 0.075 + 200 * 0.60 = 225 per million
    assert pricing.llm_cost("openai", 1000, 200, 600) == pytest.approx(225 / 1e6)
    assert pricing.llm_cost("openai", 1000, 200) == pytest.approx((150 + 120) / 1e6)
    assert pricing.llm_cost("openai", 100, 0, 5000) == pytest.approx(100 * 0.075 / 1e6)     # cached can never exceed input
    assert pricing.llm_cost("sarvam", 1_000_000, 0) == config.SARVAM_LLM_PRICE_IN_PER_M


def test_speech_costs(monkeypatch):
    monkeypatch.setattr(config, "SARVAM_STT_PRICE_PER_HOUR", 0.36)
    monkeypatch.setattr(config, "SARVAM_TTS_PRICE_PER_10K_CHARS", 0.20)
    monkeypatch.setattr(config, "STT_BYTES_PER_SECOND", 4000)
    assert pricing.stt_seconds(40000) == 10 and pricing.stt_cost(3600) == pytest.approx(0.36)
    assert pricing.tts_cost(5000) == pytest.approx(0.10)


def test_budget_period_is_the_calendar_month():
    start, reset = usage_ledger.period(datetime(2026, 11, 15, 9, 30, tzinfo=timezone.utc))
    assert (start.month, start.day, reset.month, reset.day, reset.year) == (11, 1, 12, 1, 2026)
    assert usage_ledger.period(datetime(2026, 12, 31, tzinfo=timezone.utc))[1] == datetime(2027, 1, 1, tzinfo=timezone.utc)


# ---------------------------------------------------------------- which model answers
@pytest.mark.parametrize("channel, voice, text, key, expected", [
    ("voice", "sarvam", "openai", "sk-x", "sarvam"), ("text", "sarvam", "openai", "sk-x", "openai"),
    ("text", "sarvam", "openai", None, "sarvam"),            # no OpenAI key: typed turns fall back to Sarvam
    ("voice", "openai", "openai", "sk-x", "openai"),         # voice can be pointed at OpenAI by configuration
    ("text", "sarvam", "sarvam", "sk-x", "sarvam"),
])
def test_provider_follows_the_channel(monkeypatch, channel, voice, text, key, expected):
    monkeypatch.setattr(config, "VOICE_LLM_PROVIDER", voice)
    monkeypatch.setattr(config, "TEXT_LLM_PROVIDER", text)
    monkeypatch.setattr(config, "OPENAI_API_KEY", key)
    assert llm.provider_for(channel) == expected
    telemetry.current_channel.set(channel)
    assert llm.model()._llm_type == expected


def test_openai_requests_are_shaped_for_openai(monkeypatch):
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-secret")
    telemetry.current_channel.set("text")
    telemetry.current_session.set("sess-1")
    m = llm.model(max_tokens=150)
    body = m._request([], None)
    assert body["max_completion_tokens"] == 150 and "max_tokens" not in body and body["prompt_cache_key"] == "sess-1"
    assert m._headers() == {"Authorization": "Bearer sk-secret"} and m.base_url == config.OPENAI_BASE_URL
    sarvam = llm.ChatSarvam(api_key="k", affinity="s", max_tokens=150)._request([], None)
    assert sarvam["max_tokens"] == 150 and "prompt_cache_key" not in sarvam


def test_every_kind_of_call_has_a_ceiling_on_its_reply():
    assert llm.MAX_TOKENS["fact_check"] <= 10 and llm.MAX_TOKENS["classify"] <= 200 and llm.MAX_TOKENS["answer"] <= 600


def test_a_call_is_costed_and_metered_with_its_provider(monkeypatch):
    async def fake_invoke(self, messages, config=None, **kw):
        from langchain_core.messages import AIMessage
        return AIMessage(content="ok", usage_metadata={"input_tokens": 1000, "output_tokens": 100, "total_tokens": 1100,
                                                      "input_token_details": {"cache_read": 400}})
    monkeypatch.setattr(llm.ChatOpenAI, "ainvoke", fake_invoke)
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-x")
    calls = []
    telemetry.current_meter.set(calls)
    telemetry.current_channel.set("text")
    assert asyncio.run(llm.chat([{"role": "user", "content": "hi"}], purpose="answer")) == "ok"
    (e,) = calls
    assert (e["kind"], e["provider"], e["model"], e["purpose"], e["channel"]) == ("llm", "openai", config.OPENAI_CHAT_MODEL, "answer", "text")
    assert e["input_tokens"] == 1000 and e["cached_tokens"] == 400 and e["cost_usd"] == pytest.approx(pricing.llm_cost("openai", 1000, 100, 400))


# ---------------------------------------------------------------- savings
@pytest.mark.parametrize("text, expected", [("hi", "greeting"), ("Hello!", "greeting"), ("  NAMASTE ", "greeting"), ("नमस्ते", "greeting"),
                                            ("Talk to a human", "human_handoff"), ("talk to a person, please", None),
                                            ("hi, what is the waiting period", None), ("what is EMI", None)])
def test_obvious_messages_need_no_model_call(text, expected):
    found = intent.fast_intent(text)
    assert (found.intent if found else None) == expected and (found is None or found.confidence == 1.0)


def test_classify_skips_the_model_for_a_greeting_but_not_mid_flow(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("the model must not be called")
    monkeypatch.setattr(intent.llm, "chat", boom)
    assert asyncio.run(intent.classify("hello", None, False, None)).intent == "greeting"
    called = []

    async def answer(messages, purpose, cache=None):
        called.append(purpose)
        return '{"intent": "loan_calculator", "confidence": 0.9}'
    monkeypatch.setattr(intent.llm, "chat", answer)
    asyncio.run(intent.classify("hello", None, True, "age"))        # "hello" as an answer inside a flow is not a greeting
    assert called == ["classify"]


# ---------------------------------------------------------------- the monthly limit, in a conversation
class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)

    async def send_bytes(self, data):
        pass


class FakeGraph:
    async def astream(self, state, config, stream_mode):
        # a turn that makes one costed model call, as the real graph would
        telemetry.record_llm("answer", 10.0, {"input_tokens": 500, "output_tokens": 50, "input_token_details": {}}, False, "openai", "gpt-4o-mini")
        yield "values", {"turn": Turn(text="Fine.", judge=False, prechecked=True), "path": ["guard"]}


def conversation(monkeypatch, state):
    saved, flushed = [], []

    async def status(user_id):
        return state

    async def add(user_id, events):
        flushed.extend(events)
    monkeypatch.setattr(usage_ledger, "status", status)
    monkeypatch.setattr(usage_ledger, "add", add)
    monkeypatch.setattr(session_module, "GRAPH", FakeGraph())
    ws = FakeWS()
    s = session_module.Session(ws, USER)
    asyncio.run(s.on_control(json.dumps({"type": "consent", "purpose": "conversation", "granted": True})))
    ws.sent.clear()
    return s, ws, flushed


def test_a_turn_over_the_limit_is_refused_before_anything_is_spent(monkeypatch):
    s, ws, flushed = conversation(monkeypatch, {"spent": 5.02, "budget": 5.0, "exceeded": True, "warn": True, "known": True})
    asyncio.run(s.on_text("what is a waiting period"))
    assert [m["type"] for m in ws.sent] == ["budget_exceeded", "error"] and ws.sent[0]["budget_usd"] == 5.0 and ws.sent[0]["resets_at"]
    assert flushed == [] and s.history == []                       # nothing was processed, so nothing was spent


def test_a_turn_under_the_limit_runs_and_its_cost_is_recorded(monkeypatch):
    s, ws, flushed = conversation(monkeypatch, {"spent": 1.0, "budget": 5.0, "exceeded": False, "warn": False, "known": True})
    asyncio.run(s.on_text("what is a waiting period"))
    assert "assistant" in [m["type"] for m in ws.sent] and "usage_warning" not in [m["type"] for m in ws.sent]
    (e,) = flushed
    assert e["provider"] == "openai" and e["channel"] == "text" and e["trace_id"] and e["cost_usd"] > 0


def test_the_person_is_warned_once_as_they_near_the_limit(monkeypatch):
    s, ws, _ = conversation(monkeypatch, {"spent": 4.2, "budget": 5.0, "exceeded": False, "warn": True, "known": True})
    asyncio.run(s.on_text("one"))
    asyncio.run(s.on_text("two"))
    warnings = [m for m in ws.sent if m["type"] == "usage_warning"]
    assert len(warnings) == 1 and warnings[0]["percent_used"] == 84.0


def test_the_limit_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(config, "BUDGET_ENABLED", False)
    s, ws, _ = conversation(monkeypatch, {"spent": 99, "budget": 5.0, "exceeded": True, "warn": True, "known": True})
    asyncio.run(s.on_text("hi there"))
    assert "budget_exceeded" not in [m["type"] for m in ws.sent]


def test_an_unreadable_ledger_never_locks_people_out(monkeypatch):
    # no database pool in this process: status() must fail open
    state = asyncio.run(usage_ledger.status(USER.id))
    assert state["exceeded"] is False and state["known"] is False


# ---------------------------------------------------------------- against Postgres
DB = os.getenv("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB, reason="set TEST_DATABASE_URL to run the Postgres tests")


async def with_app(scenario, monkeypatch):
    import httpx
    from psycopg_pool import AsyncConnectionPool
    from rag import store as rag_store
    from main import app

    pool = AsyncConnectionPool(DB, min_size=1, max_size=3, open=False, kwargs={"autocommit": True})
    await pool.open(wait=True)
    monkeypatch.setattr(rag_store, "_pool", pool)
    await store.init_schema()
    from tests.dbsetup import init_all
    await init_all()
    await usage_ledger.init_schema()
    async with pool.connection() as conn:
        await conn.execute("TRUNCATE users CASCADE")
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            await scenario(client)
    finally:
        await pool.close()


async def login(c, monkeypatch, sub, email):
    async def verified(token):
        return {"sub": sub, "email": email, "email_verified": True, "name": "N"}
    monkeypatch.setattr(google, "verify_id_token", verified)
    monkeypatch.setattr(config, "GOOGLE_CLIENT_IDS", ["c"])
    s = (await c.post("/auth/google", json={"id_token": "t"})).json()
    return s["user"]["id"], {"Authorization": f"Bearer {s['access_token']}"}


@needs_db
def test_usage_is_tracked_per_person_summarised_and_limited(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"boss@example.com"})

    async def scenario(c):
        me, h = await login(c, monkeypatch, "g-1", "a@example.com")
        other, oh = await login(c, monkeypatch, "g-2", "b@example.com")
        _, boss = await login(c, monkeypatch, "g-b", "boss@example.com")
        assert (await c.get("/users/me/usage")).status_code == 401

        empty = (await c.get("/users/me/usage", headers=h)).json()
        assert empty["spent_usd"] == 0 and empty["budget_usd"] == config.USER_BUDGET_USD and empty["remaining_usd"] == config.USER_BUDGET_USD

        await usage_ledger.add(me, [
            {"kind": "llm", "provider": "openai", "model": "gpt-4o-mini", "purpose": "answer", "channel": "text", "input_tokens": 900,
             "output_tokens": 80, "cached_tokens": 300, "cost_usd": 0.0004},
            {"kind": "llm", "provider": "sarvam", "model": "m", "purpose": "classify", "channel": "voice", "input_tokens": 1700,
             "output_tokens": 40, "cost_usd": 0.0005},
            {"kind": "stt", "provider": "sarvam", "purpose": "stt", "channel": "voice", "units": 12.5, "cost_usd": 0.0012},
            {"kind": "tts", "provider": "sarvam", "purpose": "tts", "channel": "voice", "units": 300, "cost_usd": 0.0054}])
        await usage_ledger.add(other, [{"kind": "llm", "provider": "openai", "purpose": "answer", "channel": "text", "cost_usd": 1.25}])

        mine = (await c.get("/users/me/usage", headers=h)).json()
        assert mine["spent_usd"] == pytest.approx(0.0075) and mine["model_calls"] == 2        # the other person's spend is not mine
        assert mine["by_provider"] == {"sarvam": pytest.approx(0.0071), "openai": pytest.approx(0.0004)}
        assert set(mine["by_kind"]) == {"llm", "stt", "tts"} and mine["by_channel"]["voice"] == pytest.approx(0.0071)
        assert mine["tokens"] == {"input": 2600, "output": 120, "cached_input": 300} and mine["estimate"] is True
        assert mine["remaining_usd"] == pytest.approx(config.USER_BUDGET_USD - 0.0075)

        # the limit: an admin can change one person's
        assert (await c.patch(f"/admin/users/{me}/budget", headers=h, json={"budget_usd": 1})).status_code == 403
        r = await c.patch(f"/admin/users/{me}/budget", headers=boss, json={"budget_usd": 0.0075})
        assert r.json()["budget_usd"] == 0.0075
        assert (await usage_ledger.status(me))["exceeded"] is True and (await usage_ledger.status(other))["exceeded"] is False
        await c.patch(f"/admin/users/{me}/budget", headers=boss, json={"budget_usd": None})
        assert (await usage_ledger.status(me))["budget"] == config.USER_BUDGET_USD
        assert (await c.patch("/admin/users/22222222-2222-2222-2222-222222222222/budget", headers=boss, json={"budget_usd": 3})).status_code == 404
        assert (await c.patch(f"/admin/users/{me}/budget", headers=boss, json={"budget_usd": -1})).status_code == 422

        top = (await c.get("/admin/usage", headers=boss)).json()
        assert [i["email"] for i in top["items"]] == ["b@example.com", "a@example.com"] and top["items"][0]["spent_usd"] == 1.25
        assert (await c.get("/admin/usage", headers=h)).status_code == 403

        # old months do not count, and deleting the account removes the ledger
        async with __import__("auth.store", fromlist=["db"]).db().connection() as conn:
            await conn.execute("UPDATE usage_events SET at = at - interval '40 days' WHERE user_id = %s", (me,))
        assert (await c.get("/users/me/usage", headers=h)).json()["spent_usd"] == 0
        assert (await c.delete("/users/me", headers=oh)).status_code == 204
        async with __import__("auth.store", fromlist=["db"]).db().connection() as conn:
            assert (await (await conn.execute("SELECT count(*) FROM usage_events WHERE user_id = %s", (other,))).fetchone())[0] == 0
    asyncio.run(with_app(scenario, monkeypatch))


# ---------------------------------------------------------------- a speech outage does not lose the turn
def test_a_text_to_speech_failure_keeps_the_reply_the_record_and_done(monkeypatch):
    async def broken(text, lang):
        raise RuntimeError("bulbul model is currently unavailable")
        yield b""
    s, ws, flushed = conversation(monkeypatch, {"spent": 0, "budget": 5.0, "exceeded": False, "warn": False, "known": True})
    monkeypatch.setattr(session_module, "speak", broken)
    asyncio.run(s.on_text("what is a waiting period", speak_reply=True))
    types = [m["type"] for m in ws.sent]
    assert "assistant" in types and types[-1] == "done" and "error" not in types
    assert {"type": "status", "stage": "speech_unavailable"} in ws.sent
    assert [e["kind"] for e in flushed] == ["llm"]            # no speech was produced, so none is charged


def test_tests_never_trace_to_langsmith():
    from observability import tracing
    assert os.environ["LANGSMITH_TRACING"] == "false" and tracing.enabled() is False
