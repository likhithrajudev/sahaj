import asyncio
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from auth.store import User
from auth.deps import current_user
from orchestrator import commands
from orchestrator.session import Session
from services import firecrawl, telemetry
from services.tts import SUPPORTED_LANGUAGES, detect_script_language, resolve_text_language
from trust.audit import Trace
from usage import ledger


class FakeSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, value):
        self.sent.append(value)


USER = User(id="11111111-1111-1111-1111-111111111111", email="a@example.com", name="Asha", picture=None,
            language="en-IN", platform="web", role="user")


def test_firecrawl_search_is_india_scoped_scrapes_pages_and_records_usage(monkeypatch):
    monkeypatch.setattr(config, "FIRECRAWL_API_KEY", "fc-test")
    monkeypatch.setattr(config, "FIRECRAWL_PRICE_PER_CREDIT_USD", 0.002)
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"success": True, "creditsUsed": 12, "data": {"web": [{
                "title": "Policy page", "url": "https://insurer.example/policy", "description": "Official details",
                "markdown": "Waiting period and cover details.",
            }], "news": []}}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return Response()

    monkeypatch.setattr(firecrawl.httpx, "AsyncClient", Client)
    meter = []
    token = telemetry.current_meter.set(meter)
    try:
        result = asyncio.run(firecrawl.search_insurance("current health plans", 3))
    finally:
        telemetry.current_meter.reset(token)
    assert result["results"][0]["url"] == "https://insurer.example/policy"
    assert calls[0][0] == "https://api.firecrawl.dev/v2/search"
    assert calls[0][1]["json"]["country"] == "IN"
    assert calls[0][1]["json"]["scrapeOptions"]["formats"] == ["markdown"]
    assert meter[0]["kind"] == "websearch" and meter[0]["units"] == 12 and meter[0]["cost_usd"] == 0.024
    assert "URL: https://insurer.example/policy" in firecrawl.sources_for(result["results"])["web:1"]


def test_firecrawl_is_explicitly_disabled_without_a_key(monkeypatch):
    monkeypatch.setattr(config, "FIRECRAWL_API_KEY", None)
    with pytest.raises(firecrawl.FirecrawlUnavailable):
        asyncio.run(firecrawl.search_insurance("health insurance"))


def test_text_commands_are_parsed_and_shortcut_replies_are_not_saved(monkeypatch):
    command = commands.parse("  /help ")
    assert command == commands.Command("/help")
    assert commands.parse("normal question") is None

    socket = FakeSocket()
    session = Session(socket, USER)
    session.speaking = False
    asyncio.run(session._run_command(command, "en-IN", Trace(session.id)))
    assistant = next(event for event in socket.sent if event["type"] == "assistant")
    assert "/usage" in assistant["text"] and "/clear" in assistant["text"]
    assert session.history == []


def test_clear_shortcut_drops_working_memory(monkeypatch):
    dropped = []

    async def drop(user, session_id):
        dropped.append((user.id, session_id))

    monkeypatch.setattr("memory.working.drop", drop)
    session = Session(FakeSocket(), USER)
    session.history = [{"role": "user", "content": "old context"}]
    session.speaking = False
    asyncio.run(session._run_command(commands.Command("/clear"), "en-IN", Trace(session.id)))
    assert session.history == [] and session.last_intent is None and dropped == [(USER.id, session.id)]


def test_supported_locales_and_script_detection_include_text_only_languages():
    assert "mai-IN" in SUPPORTED_LANGUAGES and "mni-IN" in SUPPORTED_LANGUAGES
    assert detect_script_language("வணக்கம்") == "ta-IN"
    assert resolve_text_language("en-IN", "en-IN", "ನಮಸ್ಕಾರ") == "kn-IN"
    assert resolve_text_language("mr-IN", "en-IN", "नमस्कार") == "mr-IN"
    assert resolve_text_language("en-IN", "mr-IN", "namaskar") == "mr-IN"


def test_auth_config_and_language_catalogue_are_available_without_frontend_changes(monkeypatch):
    from main import app

    monkeypatch.setattr(config, "PUBLIC_API_URL", "https://api.example.com")

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            auth = await client.get("/auth/config")
            languages = await client.get("/languages")
        return auth.json(), languages.json()

    auth, languages = asyncio.run(run())
    assert auth["api_base_url"] == "https://api.example.com"
    assert auth["google_authorized_origin"] == "https://api.example.com"
    assert auth["google_redirect_uri"] is None
    assert {item["code"] for item in languages["items"]} == set(SUPPORTED_LANGUAGES)


def test_authenticated_insurance_search_api_returns_firecrawl_results_and_meters(monkeypatch):
    from main import app
    from routers import search as search_router

    captured = []
    previous = app.dependency_overrides.get(current_user)
    app.dependency_overrides[current_user] = lambda: USER

    async def within_budget(user_id):
        return {"exceeded": False}

    async def search(query, limit=None):
        captured.append((query, limit))
        return {"provider": "firecrawl", "query": query, "results": []}

    async def add(user_id, events):
        captured.append((user_id, events))

    monkeypatch.setattr(ledger, "status", within_budget)
    monkeypatch.setattr(search_router, "search_insurance", search)
    monkeypatch.setattr(ledger, "add", add)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/search/insurance", json={"query": "health insurance platforms", "limit": 4})

    try:
        response = asyncio.run(run())
    finally:
        if previous is None:
            app.dependency_overrides.pop(current_user, None)
        else:
            app.dependency_overrides[current_user] = previous
    assert response.status_code == 200 and response.json()["provider"] == "firecrawl"
    assert captured[0] == ("health insurance platforms", 4)
    assert captured[1][0] == USER.id
