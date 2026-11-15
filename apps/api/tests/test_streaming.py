import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from auth import store
from orchestrator import session as session_module
from orchestrator.turn import Turn
from trust import consent, ledger

USER = store.User(id="11111111-1111-1111-1111-111111111111", email="a@x.com", name="A", picture=None, language="en-IN",
                  platform="web", role="user", username="a")
REPLY = "Sure. The waiting period for pre-existing diseases is 36 months under your policy. [doc:1.1]"


class Graph:
    async def astream(self, state, config, stream_mode):
        yield "values", {"turn": Turn(text=REPLY, judge=False, prechecked=True, sources={"doc:1.1": "x"}), "path": ["guard"]}


class WS:
    def __init__(self):
        self.events = []

    async def send_json(self, d):
        self.events.append(d)

    async def send_bytes(self, b):
        self.events.append(("audio", b))


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LEDGER_DB", str(tmp_path / "ledger.db"))
    monkeypatch.setattr(ledger, "_conn", None)
    monkeypatch.setattr(config, "TEXT_STREAMING", True)
    monkeypatch.setattr(config, "STREAM_DELAY_MS", 0)
    monkeypatch.setattr(session_module, "GRAPH", Graph())


def run(monkeypatch, speak, text_only=False):
    monkeypatch.setattr(session_module, "speak", speak)
    ws = WS()
    s = session_module.Session(ws, USER)
    consent.grant(USER.subject, "conversation")
    asyncio.run(s.on_text("waiting period?", speak_reply=not text_only))
    return [e if isinstance(e, tuple) else e["type"] for e in ws.events], ws.events


def test_verified_text_streams_then_the_voice_follows(monkeypatch):
    async def speak(text, lang):
        assert "[doc:1.1]" not in text
        for part in (b"a1", b"a2"):
            yield part
    kinds, events = run(monkeypatch, speak)
    deltas = [e["text"] for e in events if isinstance(e, dict) and e["type"] == "assistant_delta"]
    assert "".join(deltas) == "Sure. The waiting period for pre-existing diseases is 36 months under your policy."
    first_audio = kinds.index(("audio", b"a1"))
    assert kinds.index("assistant") < first_audio and max(i for i, k in enumerate(kinds) if k == "assistant_delta") < kinds.index("assistant")
    assert kinds[-1] == "done" and kinds.count(("audio", b"a1")) == 1


def test_a_speech_failure_still_finishes_the_turn(monkeypatch):
    async def broken(text, lang):
        raise RuntimeError("tts down")
        yield b""
    kinds, events = run(monkeypatch, broken)
    assert "assistant" in kinds and kinds[-1] == "done"
    assert {"type": "status", "stage": "speech_unavailable"} in events


def test_typed_turns_stream_text_without_any_voice(monkeypatch):
    async def never(text, lang):
        raise AssertionError("no speech for a typed turn")
        yield b""
    kinds, _ = run(monkeypatch, never, text_only=True)
    assert "assistant_delta" in kinds and not any(isinstance(k, tuple) for k in kinds)


def test_the_core_rules_allow_a_warm_opening_without_facts():
    from agents.base import CORE
    assert "warm, patient person" in CORE and "states no fact" in CORE and "source tag" in CORE
def test_an_unexpected_error_ends_the_turn_not_the_conversation(monkeypatch):
    class Broken:
        async def astream(self, state, config, stream_mode):
            raise KeyError("language_code")
            yield
    monkeypatch.setattr(session_module, "GRAPH", Broken())
    kinds, events = run(monkeypatch, None, text_only=True)
    assert kinds[-1] == "error" and "try again" in events[-1]["message"]
    monkeypatch.setattr(session_module, "GRAPH", Graph())
    kinds, _ = run(monkeypatch, None, text_only=True)
    assert "assistant" in kinds and kinds[-1] == "done"


def test_unclear_audio_without_a_language_uses_the_profile_language(monkeypatch):
    async def stt(audio, filename, content_type):
        return {"transcript": "", "language_code": None}
    monkeypatch.setattr(session_module, "transcribe_audio", stt)
    ws = WS()
    s = session_module.Session(ws, USER)
    consent.grant(USER.subject, "conversation")
    asyncio.run(s.on_audio(b"\x1a\x45\xdf\xa3" + b"\0" * 64))
    assert not any(isinstance(e, dict) and e.get("message", "").startswith("Something went wrong") for e in ws.events)
