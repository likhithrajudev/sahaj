"""Ratings on replies, the admin review, and the personal data export."""
import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from auth import feedback, google, store
from memory import store as memory_store
from storage import blob, files
from storage.blob import MemoryBlobStore
from trust import consent, ledger
from trust.audit import Trace

DB = os.getenv("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB, reason="set TEST_DATABASE_URL to run the Postgres tests")


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LEDGER_DB", str(tmp_path / "ledger.db"))
    monkeypatch.setattr(ledger, "_conn", None)
    monkeypatch.setattr(config, "JWT_SECRET", "x" * 40)
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"boss@example.com"})
    yield
    blob.use(None)


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
    await files.init_schema()
    await feedback.init_schema()
    async with pool.connection() as conn:
        await conn.execute("TRUNCATE users CASCADE")
    blob.use(MemoryBlobStore())
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            await scenario(client)
    finally:
        await pool.close()


async def login(c, monkeypatch, sub, email):
    async def verified(token):
        return {"sub": sub, "email": email, "email_verified": True, "name": "Asha"}
    monkeypatch.setattr(google, "verify_id_token", verified)
    monkeypatch.setattr(config, "GOOGLE_CLIENT_IDS", ["c"])
    s = (await c.post("/auth/google", json={"id_token": "t"})).json()
    return s["user"]["id"], {"Authorization": f"Bearer {s['access_token']}"}


@needs_db
def test_feedback_is_stored_once_per_reply_and_reviewed_by_admins(monkeypatch):
    trace = Trace("session-1")
    trace.add("guardrail", verdict="pass")
    trace.save()

    async def scenario(c):
        me, h = await login(c, monkeypatch, "g-1", "a@example.com")
        _, boss = await login(c, monkeypatch, "g-b", "boss@example.com")

        assert (await c.post("/feedback", json={"trace_id": trace.id, "rating": "up"})).status_code == 401
        assert (await c.post("/feedback", json={"trace_id": "0" * 32, "rating": "up"}, headers=h)).status_code == 404   # no such reply
        assert (await c.post("/feedback", json={"trace_id": trace.id, "rating": "meh"}, headers=h)).status_code == 422
        assert (await c.post("/feedback", json={"trace_id": "x y", "rating": "up"}, headers=h)).status_code == 422

        assert (await c.post("/feedback", json={"trace_id": trace.id, "rating": "up"}, headers=h)).status_code == 204
        r = await c.post("/feedback", json={"trace_id": trace.id, "rating": "down", "comment": "wrong, my PAN ABCDE1234F"}, headers=h)
        assert r.status_code == 204                                                          # rating again replaces

        assert (await c.get("/admin/feedback", headers=h)).status_code == 403
        review = (await c.get("/admin/feedback", headers=boss)).json()
        assert review["counts"] == {"up": 0, "down": 1} and len(review["recent"]) == 1
        row = review["recent"][0]
        assert row["trace_id"] == trace.id and "ABCDE1234F" not in row["comment"] and "[PAN_1]" in row["comment"]
        assert (await c.get("/admin/feedback?rating=up", headers=boss)).json()["recent"] == []
    asyncio.run(with_app(scenario, monkeypatch))


@needs_db
def test_data_export_holds_everything_about_the_person_and_nothing_about_others(monkeypatch):
    trace = Trace("s")
    trace.save()

    async def scenario(c):
        me, h = await login(c, monkeypatch, "g-1", "a@example.com")
        other, _ = await login(c, monkeypatch, "g-2", "b@example.com")
        assert (await c.get("/users/me/export")).status_code == 401

        await c.put("/users/me/memory/consent", json={"granted": True}, headers=h)
        await memory_store.save(me, "Asked about term insurance.", {"interests": "term insurance"})
        await memory_store.save(other, "Someone else's note.", {})
        await c.put("/files/consent", json={"granted": True}, headers=h)
        await c.post("/files", files={"file": ("offer.pdf", b"%PDF-1.4 hello")}, headers=h)
        await c.post("/feedback", json={"trace_id": trace.id, "rating": "up"}, headers=h)

        r = await c.get("/users/me/export", headers=h)
        assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
        data = r.json()
        assert data["profile"]["email"] == "a@example.com"
        assert {c["purpose"] for c in data["consents"]} == {"memory", "documents"}
        assert [m["content"] for m in data["memory"] if m["kind"] == "summary"] == ["Asked about term insurance."]
        assert [f["filename"] for f in data["files"]] == ["offer.pdf"] and "blob_name" not in data["files"][0]
        assert [f["rating"] for f in data["feedback"]] == ["up"]
        assert "Someone else" not in r.text
    asyncio.run(with_app(scenario, monkeypatch))
