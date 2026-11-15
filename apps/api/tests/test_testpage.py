"""The development test console and its local-only sign-in."""
import asyncio
import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from auth import store

DB = os.getenv("TEST_DATABASE_URL")


def call(method, path, client=("127.0.0.1", 5000), **kw):
    from main import app

    async def go():
        transport = httpx.ASGITransport(app=app, client=client)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            return await c.request(method, path, **kw)
    return asyncio.run(go())


def test_the_console_is_served_and_home_redirects_to_it():
    page = call("GET", "/test/")
    assert page.status_code == 200 and "Sahaj test console" in page.text
    assert call("GET", "/", follow_redirects=False).headers["location"] == "/test/"


def test_console_script_builds_dom_without_innerhtml():
    html = (Path(__file__).resolve().parent.parent / "static" / "index.html").read_text()
    assert "innerHTML" not in html     # replies and file names are shown as text, never as markup


def test_dev_login_is_off_by_default(monkeypatch):
    monkeypatch.setattr(config, "DEV_LOGIN", False)
    assert call("GET", "/auth/config").json()["dev_login"] is False
    assert call("POST", "/auth/dev", json={"email": "a@example.com"}).status_code == 404


@pytest.mark.parametrize("client, environment, allowed", [
    (("127.0.0.1", 1), "development", True), (("::1", 1), "development", True),
    (("203.0.113.9", 1), "development", False),          # not this machine
    (("127.0.0.1", 1), "production", False),             # a deployed instance, even with the flag left on
])
def test_dev_login_only_for_this_machine_in_development(monkeypatch, client, environment, allowed):
    monkeypatch.setattr(config, "DEV_LOGIN", True)
    monkeypatch.setattr(config, "ENVIRONMENT", environment)
    assert call("GET", "/auth/config", client=client).json()["dev_login"] is allowed
    assert (call("POST", "/auth/dev", client=client, json={"email": "a@example.com"}).status_code == 404) is (not allowed)


def test_dev_login_validates_the_email(monkeypatch):
    monkeypatch.setattr(config, "DEV_LOGIN", True)
    assert call("POST", "/auth/dev", json={"email": "not-an-email"}).status_code == 422


def test_google_client_id_is_advertised_when_configured(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CLIENT_IDS", ["abc.apps.googleusercontent.com"])
    assert call("GET", "/auth/config").json()["google_client_id"] == "abc.apps.googleusercontent.com"
