"""Typed messages, progress events and the SSE chat endpoint, with the graph stubbed (no model, no database)."""
import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from auth import store, tokens
from orchestrator import registry, session as session_module
from orchestrator.turn import Turn
from trust import ledger

USER = store.User(id="11111111-1111-1111-1111-111111111111", email="a@example.com", name="Asha", picture=None,
                  language="en-IN", platform="web", role="user")
OTHER = store.User(id="22222222-2222-2222-2222-222222222222", email="b@example.com", name="B", picture=None,
                   language="en-IN", platform="web", role="user")


class FakeGraph:
    """Yields what LangGraph's astream yields for stream_mode=["updates", "values"]."""
    seen = []

    async def astream(self, state, config, stream_mode):
        FakeGraph.seen.append(state["text"])
        yield "updates", {"classify": {}}
        yield "updates", {"insurance_rag": {}}
        turn = Turn(text="The waiting period is 30 days.", judge=False, prechecked=True)
        yield "updates", {"guard": {}}
        yield "values", {"turn": turn, "path": ["classify", "insurance_rag", "guard"]}


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LEDGER_DB", str(tmp_path / "ledger.db"))
    monkeypatch.setattr(ledger, "_conn", None)
    monkeypatch.setattr(config, "JWT_SECRET", "x" * 40)
    monkeypatch.setattr(session_module, "GRAPH", FakeGraph())
    FakeGraph.seen.clear()
    registry._entries.clear()

    async def get_user(user_id):
        return {USER.id: USER, OTHER.id: OTHER}.get(user_id)
    monkeypatch.setattr(store, "get_user", get_user)

    async def spoken(text, lang):  # a typed turn must not synthesise speech unless asked
        raise AssertionError("speech was requested")
        yield b""
    monkeypatch.setattr(session_module, "speak", spoken)


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)

    async def send_bytes(self, data):
        self.sent.append(("audio", len(data)))


def types(ws):
    return [m["type"] for m in ws.sent]


CONSENT = json.dumps({"type": "consent", "purpose": "conversation", "granted": True})


def test_typed_message_follows_the_same_path_with_progress_and_no_audio():
    ws = FakeWS()
    s = session_module.Session(ws, USER)

    async def go():
        await s.on_control(CONSENT)
        ws.sent.clear()
        await s.on_control(json.dumps({"type": "text", "text": "what is the waiting period"}))
    asyncio.run(go())
    assert types(ws) == ["user", "status", "status", "assistant", "done"]
    assert [m["stage"] for m in ws.sent if m["type"] == "status"] == ["thinking", "checking"]
    assert ws.sent[3]["text"] == "The waiting period is 30 days."


def test_typed_message_masks_personal_details_and_needs_consent():
    ws = FakeWS()
    s = session_module.Session(ws, USER)
    asyncio.run(s.on_control(json.dumps({"type": "text", "text": "hi"})))
    assert types(ws) == ["consent_required"] and FakeGraph.seen == []   # no consent, nothing processed
    asyncio.run(s.on_control(CONSENT))
    asyncio.run(s.on_control(json.dumps({"type": "text", "text": "my pan is ABCDE1234F"})))
    assert FakeGraph.seen == ["my pan is [PAN_1]"]
    assert {"type": "user", "text": "my pan is [PAN_1]"} in ws.sent


@pytest.mark.parametrize("message", [{"type": "text"}, {"type": "text", "text": "  "}, {"type": "text", "text": 5},
                                     {"type": "text", "text": "x" * 2001}])
def test_bad_text_messages_are_rejected(message):
    ws = FakeWS()
    s = session_module.Session(ws, USER)
    asyncio.run(s.on_control(CONSENT))
    ws.sent.clear()
    asyncio.run(s.on_control(json.dumps(message)))
    assert types(ws) == ["error"] and FakeGraph.seen == []


def test_speech_is_only_produced_when_asked(monkeypatch):
    async def spoken(text, lang):
        yield b"mp3"
    monkeypatch.setattr(session_module, "speak", spoken)
    ws = FakeWS()
    s = session_module.Session(ws, USER)
    asyncio.run(s.on_control(CONSENT))
    ws.sent.clear()
    asyncio.run(s.on_control(json.dumps({"type": "text", "text": "hi", "speak": True})))
    assert ("audio", 3) in ws.sent and ws.sent[-1] == {"type": "done"} and {"type": "status", "stage": "speaking"} in ws.sent


# ---------------------------------------------------------------- the SSE endpoint
def bearer(user):
    return {"Authorization": f"Bearer {tokens.issue_access(user)[0]}"}


def post(body, user=USER):
    from main import app

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/chat/stream", json=body, headers=bearer(user))
            return r, [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    return asyncio.run(go())


def test_chat_stream_conversation():
    async def go():
        from main import app
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            async def send(message, sid=None, user=USER):
                r = await c.post("/chat/stream", json={"session_id": sid, "message": message}, headers=bearer(user))
                return r, [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]

            r, events = await send({"type": "text", "text": "hello"})
            assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
            assert [e["type"] for e in events] == ["session", "consent_required"]   # no consent yet
            sid = events[0]["id"]

            _, events = await send({"type": "consent", "purpose": "conversation", "granted": True}, sid)
            assert events == [{"type": "consent", "purpose": "conversation", "status": "granted"}]

            _, events = await send({"type": "text", "text": "what is the waiting period"}, sid)
            assert [e["type"] for e in events] == ["user", "status", "status", "assistant", "done"]

            # history carries over to the next request
            assert len(registry._entries[sid].session.history) == 2

            # someone else's conversation, or an unknown one, is a 404
            assert (await send({"type": "text", "text": "hi"}, sid, OTHER))[0].status_code == 404
            assert (await send({"type": "text", "text": "hi"}, "nope"))[0].status_code == 404

            assert (await c.delete(f"/chat/{sid}", headers=bearer(OTHER))).status_code == 404
            assert (await c.delete(f"/chat/{sid}", headers=bearer(USER))).status_code == 204
            assert (await send({"type": "text", "text": "hi"}, sid))[0].status_code == 404
    asyncio.run(go())


def test_chat_stream_requires_sign_in_and_a_message():
    from main import app

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            assert (await c.post("/chat/stream", json={"message": {"type": "text", "text": "hi"}})).status_code == 401
            assert (await c.post("/chat/stream", json={}, headers=bearer(USER))).status_code == 422
            r = await c.post("/chat/stream", json={"message": {"type": "bogus"}}, headers=bearer(USER))
            assert [json.loads(l[6:])["type"] for l in r.text.splitlines() if l.startswith("data: ")] == ["session", "error"]
    asyncio.run(go())


def test_idle_conversations_are_swept_and_the_per_user_cap_holds(monkeypatch):
    async def go():
        entry, _ = registry.acquire(USER, None)
        entry.last_used -= registry.IDLE_SECONDS + 1
        await registry.sweep()
        assert entry.session.id not in registry._entries
        for _ in range(registry.MAX_PER_USER + 2):
            registry.acquire(USER, None)
        await asyncio.sleep(0)
        assert len([e for e in registry._entries.values() if e.user_id == USER.id]) == registry.MAX_PER_USER
    asyncio.run(go())


# ---------------------------------------------------------------- structured replies
from orchestrator import structure

SRC = {"doc:1.1": "1.1 Waiting period. 30 days.", "doc:2.3": "2.3 Cover. Up to 1.5 lakh."}


def test_structure_splits_statements_and_keeps_their_sources():
    text = "The waiting period is 30 days. [doc:1.1] Cover is up to 1.5 lakh [doc:2.3]. Ask me anything else?"
    s = structure.build(text, ["Premiums are indicative."], SRC, "answer")
    assert [p["text"] for p in s["points"]] == ["The waiting period is 30 days.", "Cover is up to 1.5 lakh.", "Ask me anything else?"]
    assert [p["sources"] for p in s["points"]] == [["doc:1.1"], ["doc:2.3"], []]
    assert s["summary"] == "The waiting period is 30 days."
    assert [x["id"] for x in s["sources"]] == ["doc:1.1", "doc:2.3"] and s["notes"] == ["Premiums are indicative."]
    assert "[" not in "".join(p["text"] for p in s["points"])


def test_structure_drops_tags_the_reply_was_not_allowed_to_cite_and_handles_hindi_and_empty():
    s = structure.build("प्रतीक्षा अवधि 30 दिन है। [doc:1.1] यह गलत है [doc:9.9]।", [], SRC, "answer")
    assert [p["sources"] for p in s["points"]] == [["doc:1.1"], []]
    assert structure.build("", [], {}, "ask")["points"] == []


def test_assistant_event_carries_the_structured_view_and_unchanged_text():
    ws = FakeWS()
    s = session_module.Session(ws, USER)
    asyncio.run(s.on_control(CONSENT))
    asyncio.run(s.on_control(json.dumps({"type": "text", "text": "waiting period?"})))
    reply = next(m for m in ws.sent if m["type"] == "assistant")
    assert reply["text"] == "The waiting period is 30 days." and reply["structured"]["summary"] == reply["text"]
    assert reply["structured"]["kind"] == "answer" and reply["structured"]["sources"] == []


# ---------------------------------------------------------------- trust badge and suggestions
from orchestrator import suggest


@pytest.mark.parametrize("kwargs, level", [
    (dict(blocked=True, from_cache=False, prechecked=False, judged=True, sources=2, kind="answer"), "blocked"),
    (dict(blocked=False, from_cache=False, prechecked=False, judged=True, sources=2, kind="answer"), "verified"),
    (dict(blocked=False, from_cache=True, prechecked=True, judged=False, sources=2, kind="answer"), "verified"),
    (dict(blocked=False, from_cache=False, prechecked=True, judged=False, sources=0, kind="answer"), "engine"),
    (dict(blocked=False, from_cache=False, prechecked=False, judged=False, sources=3, kind="recommendation"), "engine"),
    (dict(blocked=False, from_cache=False, prechecked=False, judged=False, sources=0, kind="answer"), "checked"),
])
def test_verification_levels(kwargs, level):
    assert suggest.verification(**kwargs)["level"] == level


def test_suggestions():
    assert len(suggest.for_intent("insurance_explain", "en-IN", "answer", False)) == 3
    assert suggest.for_intent("insurance_explain", "hi-IN", "answer", False)[0] != suggest.for_intent("insurance_explain", "en-IN", "answer", False)[0]
    assert suggest.for_intent("insurance_explain", "ta-IN", "answer", False) == suggest.SUGGESTIONS["insurance_explain"]["en-IN"]   # falls back to English
    assert suggest.for_intent("insurance_explain", "en-IN", "ask", False) == []        # a question is pending
    assert suggest.for_intent("insurance_explain", "en-IN", "answer", True) == []      # a person has taken over
    assert suggest.for_intent("something_new", "en-IN", "answer", False) == suggest.SUGGESTIONS["greeting"]["en-IN"]


def test_assistant_event_carries_verification_and_suggestions():
    ws = FakeWS()
    s = session_module.Session(ws, USER)
    asyncio.run(s.on_control(CONSENT))
    asyncio.run(s.on_control(json.dumps({"type": "text", "text": "hi"})))
    reply = next(m for m in ws.sent if m["type"] == "assistant")
    assert reply["verification"]["level"] == "engine" and "guardrails" in reply["verification"]["checks"]
    assert len(reply["suggestions"]) == 3
