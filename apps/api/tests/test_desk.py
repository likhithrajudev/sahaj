"""The customer executive desk: escalation, the queue, live takeover, video KYC, closing, and the audit of it all."""
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from auth import google, store, tokens
from desk import escalation, live, store as desk
from orchestrator import session as session_module
from orchestrator.turn import Turn
from trust import consent, ledger


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LEDGER_DB", str(tmp_path / "ledger.db"))
    monkeypatch.setattr(ledger, "_conn", None)
    monkeypatch.setattr(config, "JWT_SECRET", "x" * 40)
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"boss@example.com"})
    live.customers.clear()
    live.executives.clear()


# ---------------------------------------------------------------- what needs a person (no database)
@pytest.mark.parametrize("text, expected", [
    ("I want to file a complaint about my claim", "complaint"), ("this is a fraud, you cheated me", "complaint"),
    ("मुझे शिकायत करनी है", "complaint"), ("ye dhokha hai", "complaint"), ("I will take legal action", "complaint"),
    ("the recovery agent came to my home and threatened my family", "distress"), ("I want to kill myself", "distress"),
    ("मैं आत्महत्या कर लूँगा", "distress"),
    ("my father was admitted to hospital yesterday", None),      # the start of a claim, not distress
    ("what is the waiting period", None), ("how do I raise a claim", None), ("can I complete the form later", None),
])
def test_escalation_detection(text, expected):
    assert escalation.detect(text) == expected


def test_acknowledgements_exist_in_english_and_hindi_with_fallback():
    for reason in ("distress", "complaint"):
        assert escalation.acknowledgement(reason, "hi-IN") != escalation.acknowledgement(reason, "en-IN")
        assert escalation.acknowledgement(reason, "ta-IN") == escalation.acknowledgement(reason, "en-IN")


def test_desk_socket_refuses_strangers_and_customers(monkeypatch):
    from fastapi.testclient import TestClient
    from main import app
    customer = store.User(id="11111111-1111-1111-1111-111111111111", email="a@x.com", name="A", picture=None,
                          language="en-IN", platform="web", role="user", username="a")

    async def get_user(user_id):
        return customer
    monkeypatch.setattr(store, "get_user", get_user)
    client = TestClient(app)
    with client.websocket_connect("/ws/desk") as ws:
        assert ws.receive()["code"] == 4401
    token = tokens.issue_access(customer)[0]
    with client.websocket_connect(f"/ws/desk?access_token={token}") as ws:
        assert ws.receive()["code"] == 4403


# ---------------------------------------------------------------- the whole desk, against Postgres
DB = os.getenv("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB, reason="set TEST_DATABASE_URL to run the Postgres tests")


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)

    async def send_bytes(self, data):
        pass

    def types(self):
        return [m["type"] for m in self.sent]

    def last(self, kind):
        return next(m for m in reversed(self.sent) if m["type"] == kind)


class Graph:
    """Answers, or asks a clarifying question, as told; counts how often the AI was used."""
    calls, clarify = 0, False

    async def astream(self, state, config, stream_mode):
        Graph.calls += 1
        path = ["classify", "clarify", "guard"] if Graph.clarify else ["classify", "insurance_rag", "guard"]
        yield "values", {"turn": Turn(text="An answer from the AI.", judge=False, prechecked=True), "path": path}


async def with_app(scenario, monkeypatch):
    import httpx
    from psycopg_pool import AsyncConnectionPool
    from rag import store as rag_store
    from usage import ledger as usage_ledger
    from main import app

    pool = AsyncConnectionPool(DB, min_size=1, max_size=4, open=False, kwargs={"autocommit": True})
    await pool.open(wait=True)
    monkeypatch.setattr(rag_store, "_pool", pool)
    await store.init_schema()
    await usage_ledger.init_schema()
    await desk.init_schema()
    async with pool.connection() as conn:
        await conn.execute("TRUNCATE users CASCADE")
    monkeypatch.setattr(session_module, "GRAPH", Graph())
    Graph.calls, Graph.clarify = 0, False

    async def silent(text, lang):
        return
        yield b""
    monkeypatch.setattr(session_module, "speak", silent)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            await scenario(client)
    finally:
        await pool.close()


async def login(c, monkeypatch, sub, email, name="N"):
    async def verified(token):
        return {"sub": sub, "email": email, "email_verified": True, "name": name}
    monkeypatch.setattr(google, "verify_id_token", verified)
    monkeypatch.setattr(config, "GOOGLE_CLIENT_IDS", ["c"])
    s = (await c.post("/auth/google", json={"id_token": "t"})).json()
    return s["user"], {"Authorization": f"Bearer {s['access_token']}"}


async def customer_session(user_dict):
    user = await store.get_user(user_dict["id"])
    ws = FakeWS()
    s = session_module.Session(ws, user)
    consent.grant(user.subject, "conversation", version=consent.PURPOSES["conversation"]["version"])
    await s.start()
    return s, ws


async def make_executive(c, boss, user_dict):
    r = await c.patch(f"/admin/users/{user_dict['id']}/role", headers=boss, json={"role": "executive"})
    assert r.status_code == 200 and r.json()["role"] == "executive"


@needs_db
def test_a_complaint_goes_to_an_executive_who_takes_over_the_live_conversation(monkeypatch):
    async def scenario(c):
        cust, ch = await login(c, monkeypatch, "g-c", "asha@example.com", "Asha")
        agent, ah = await login(c, monkeypatch, "g-e", "ravi@example.com", "Ravi")
        _, boss = await login(c, monkeypatch, "g-b", "boss@example.com", "Boss")
        assert (await c.get("/desk/queue", headers=ah)).status_code == 403          # not an executive yet
        await make_executive(c, boss, agent)

        s, ws = await customer_session(cust)
        assert ws.sent[0]["type"] == "session" and ws.sent[0]["case"] is None
        await s.on_text("I want to complain, you charged me twice for the same policy")
        assert Graph.calls == 0                                                       # the AI never got it
        assert "assistant" in ws.types() and ws.last("handoff")["case"]["kind"] == "complaint"
        assert ws.last("handoff")["case"]["priority"] == "high" and ws.last("handoff")["case"]["status"] == "waiting"

        q = (await c.get("/desk/queue", headers=ah)).json()
        (item,) = q["items"]
        assert item["customer"] == {"name": "Asha", "username": "asha"} and item["reason"] == "complaint" and q["stats"]["waiting"] == 1
        case_id = item["id"]
        detail = (await c.get(f"/desk/cases/{case_id}", headers=ah)).json()
        assert detail["customer"]["online"] is True and "conversation" in detail["customer"]["consents"]
        assert any("complain" in m["content"] for m in detail["conversation_before"])          # the context comes with it
        assert detail["case"]["note"].startswith("I want to complain")

        # while waiting, the customer's words go to the case, not the AI
        await s.on_text("my PAN is ABCDE1234F if you need it")
        assert Graph.calls == 0 and ws.last("status")["stage"] == "waiting_for_executive"
        # an executive must claim before writing; then the customer sees them join and reply, live
        assert (await c.post(f"/desk/cases/{case_id}/messages", headers=ah, json={"text": "Hi"})).status_code == 409
        assert (await c.post(f"/desk/cases/{case_id}/claim", headers=ah)).status_code == 200
        assert (await c.post(f"/desk/cases/{case_id}/claim", headers=ah)).status_code == 409   # nobody claims twice
        assert ws.last("agent_joined")["agent"] == {"name": "Ravi"}
        r = await c.post(f"/desk/cases/{case_id}/messages", headers=ah, json={"text": "Hello Asha, I can see the double charge. Refund started."})
        assert r.status_code == 201 and r.json()["delivered_live"] is True
        assert ws.last("agent_message")["text"].startswith("Hello Asha")
        await s.on_text("thank you")
        thread = (await c.get(f"/desk/cases/{case_id}", headers=ah)).json()["messages"]
        assert [m["sender"] for m in thread] == ["customer", "system", "executive", "customer"]
        assert "ABCDE1234F" not in json.dumps(thread) and "[PAN_1]" in thread[0]["text"]          # masked for the executive too

        # resolving hands the conversation back to the AI
        r = await c.post(f"/desk/cases/{case_id}/resolve", headers=ah,
                         json={"outcome": "resolved", "resolution": "Duplicate premium refunded", "message": "Refund done."})
        assert r.status_code == 200 and ws.last("handoff_closed")["status"] == "resolved" and s.case is None
        await s.on_text("what is a waiting period")
        assert Graph.calls == 1 and ws.last("assistant")["text"] == "An answer from the AI."
        assert (await c.get("/desk/queue", headers=ah)).json()["items"] == []

        # every human action is in the hash-chained ledger, with who did it
        events = [(e["payload"]["event"], e["payload"]["actor"]) for e in ledger.entries(subject=f"case:{case_id}", kind="case")]
        assert events == [("opened", None), ("claimed", agent["id"]), ("resolved", agent["id"])] and ledger.verify()["intact"]

        # the customer can read the history
        mine = (await c.get("/cases", headers=ch)).json()
        assert mine["items"][0]["status"] == "resolved" and mine["active_messages"] == []
    asyncio.run(with_app(scenario, monkeypatch))


@needs_db
def test_distress_is_urgent_and_raises_an_existing_case(monkeypatch):
    async def scenario(c):
        cust, _ = await login(c, monkeypatch, "g-c", "asha@example.com")
        s, ws = await customer_session(cust)
        await s.on_control(json.dumps({"type": "handoff"}))                    # the button
        assert ws.last("handoff")["case"]["priority"] == "normal"
        first = s.case["id"]
        s._set_case(None)                                                      # (as if from another device)
        await s.on_text("the recovery agent is threatening my family")
        assert s.case["id"] == first and s.case["priority"] == "urgent"        # same case, now urgent
        row = await desk.get(first)
        assert row["priority"] == "urgent" and row["sla_due_at"] <= datetime.now(timezone.utc) + timedelta(minutes=config.DESK_SLA_MINUTES["urgent"] + 1)
    asyncio.run(with_app(scenario, monkeypatch))


@needs_db
def test_repeated_low_confidence_brings_in_a_person(monkeypatch):
    async def scenario(c):
        cust, _ = await login(c, monkeypatch, "g-c", "asha@example.com")
        s, ws = await customer_session(cust)
        Graph.clarify = True
        await s.on_text("hmm the thing")
        assert s.case is None
        await s.on_text("that other thing")
        assert s.case and s.case["reason"] == "low_confidence"
    asyncio.run(with_app(scenario, monkeypatch))


@needs_db
def test_video_kyc_needs_consent_and_is_booked_by_an_executive(monkeypatch):
    async def scenario(c):
        cust, ch = await login(c, monkeypatch, "g-c", "asha@example.com")
        agent, ah = await login(c, monkeypatch, "g-e", "ravi@example.com", "Ravi")
        _, boss = await login(c, monkeypatch, "g-b", "boss@example.com")
        await make_executive(c, boss, agent)
        s, ws = await customer_session(cust)

        await s.on_control(json.dumps({"type": "handoff", "reason": "video_kyc"}))
        assert ws.last("consent_required")["purpose"] == "video_kyc" and s.case is None
        assert (await c.post("/cases", headers=ch, json={"kind": "video_kyc"})).status_code == 409
        consent.grant(f"user:{cust['id']}", "video_kyc", version=consent.PURPOSES["video_kyc"]["version"])

        r = await c.post("/cases", headers=ch, json={"kind": "video_kyc", "note": "evenings please"})   # from another device
        assert r.status_code == 201 and r.json()["kind"] == "video_kyc"
        assert s.case and s.case["kind"] == "video_kyc" and ws.last("handoff")["case"]["kind"] == "video_kyc"   # the open conversation knows
        case_id = r.json()["id"]
        await c.post(f"/desk/cases/{case_id}/claim", headers=ah)
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        assert (await c.post(f"/desk/cases/{case_id}/video-kyc", headers=ah, json={"scheduled_for": past})).status_code == 422
        assert (await c.post(f"/desk/cases/{case_id}/video-kyc", headers=ah,
                             json={"scheduled_for": "2030-01-01T10:00:00+05:30", "meeting_url": "http://insecure"})).status_code == 422
        when = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0).isoformat()
        r = await c.post(f"/desk/cases/{case_id}/video-kyc", headers=ah, json={"scheduled_for": when, "meeting_url": "https://meet.example/kyc1"})
        assert r.status_code == 200 and ws.last("video_kyc_scheduled")["meeting_url"] == "https://meet.example/kyc1"
        assert (await c.get("/cases", headers=ch)).json()["items"][0]["meeting_url"] == "https://meet.example/kyc1"

        # a non-video case cannot be booked
        await c.post(f"/desk/cases/{case_id}/resolve", headers=ah, json={"outcome": "resolved", "resolution": "KYC done"})
        other = (await c.post("/cases", headers=ch, json={"kind": "callback"})).json()
        await c.post(f"/desk/cases/{other['id']}/claim", headers=ah)
        assert (await c.post(f"/desk/cases/{other['id']}/video-kyc", headers=ah, json={"scheduled_for": when})).status_code == 409
    asyncio.run(with_app(scenario, monkeypatch))


@needs_db
def test_customers_can_reply_offline_cancel_and_only_touch_their_own_cases(monkeypatch):
    async def scenario(c):
        cust, ch = await login(c, monkeypatch, "g-c", "asha@example.com")
        other, oh = await login(c, monkeypatch, "g-o", "bob@example.com")
        agent, ah = await login(c, monkeypatch, "g-e", "ravi@example.com", "Ravi")
        _, boss = await login(c, monkeypatch, "g-b", "boss@example.com")
        await make_executive(c, boss, agent)
        case = (await c.post("/cases", headers=ch, json={"kind": "callback", "note": "call me on 9876543210"})).json()
        assert "9876543210" not in json.dumps((await c.get(f"/desk/cases/{case['id']}", headers=ah)).json())   # masked

        # one active case per person: asking again joins it
        again = (await c.post("/cases", headers=ch, json={"kind": "help"})).json()
        assert again["id"] == case["id"]

        await c.post(f"/desk/cases/{case['id']}/claim", headers=ah)
        await c.post(f"/desk/cases/{case['id']}/messages", headers=ah, json={"text": "I'll call you at 5pm."})   # customer offline
        mine = (await c.get("/cases", headers=ch)).json()
        assert mine["active_messages"][-1]["text"] == "I'll call you at 5pm."                 # waiting for them when they come back
        assert (await c.post(f"/cases/{case['id']}/messages", headers=ch, json={"text": "ok thanks"})).status_code == 201
        assert (await c.post(f"/cases/{case['id']}/messages", headers=oh, json={"text": "hi"})).status_code == 404
        assert (await c.post(f"/cases/{case['id']}/cancel", headers=oh)).status_code == 404
        assert (await c.post(f"/desk/cases/{case['id']}/release", headers=ah)).status_code == 200
        assert (await c.get("/desk/queue?view=open", headers=ah)).json()["items"][0]["id"] == case["id"]

        # a conversation opened now carries on with the person, not the AI
        s, ws = await customer_session(cust)
        assert ws.sent[0]["case"]["id"] == case["id"]
        await s.on_text("are you there?")
        assert Graph.calls == 0
        await s.on_control(json.dumps({"type": "handoff_cancel"}))
        assert ws.last("handoff_closed")["status"] == "cancelled" and s.case is None
        assert (await c.post(f"/cases/{case['id']}/cancel", headers=ch)).status_code == 409
        assert (await desk.get(case["id"]))["status"] == "cancelled"
    asyncio.run(with_app(scenario, monkeypatch))
