import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from auth import google, store
from desk import live
from orchestrator import session as session_module
from storage import blob
from storage.blob import MemoryBlobStore
from trust import consent, ledger

DB = os.getenv("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB, reason="set TEST_DATABASE_URL to run the Postgres tests")
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LEDGER_DB", str(tmp_path / "ledger.db"))
    monkeypatch.setattr(ledger, "_conn", None)
    monkeypatch.setattr(config, "JWT_SECRET", "x" * 40)
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"boss@x.com", "boss@acme.com"})
    live.customers.clear()
    blob.use(MemoryBlobStore())
    yield
    blob.use(None)


def test_marketing_is_an_optional_consent_that_erases_offers_on_withdrawal():
    m = consent.required("marketing")
    assert m["required"] is False and m["requires"] is None and "inbox" in m["withdrawal"]


async def with_app(scenario, monkeypatch):
    import httpx
    from psycopg_pool import AsyncConnectionPool
    from rag import store as rag_store
    from tests.dbsetup import init_all
    from main import app

    pool = AsyncConnectionPool(DB, min_size=1, max_size=4, open=False, kwargs={"autocommit": True})
    await pool.open(wait=True)
    monkeypatch.setattr(rag_store, "_pool", pool)
    await init_all()
    async with pool.connection() as conn:
        await conn.execute("TRUNCATE users CASCADE")
        await conn.execute("DELETE FROM campaigns")
        await conn.execute("INSERT INTO tenants (id, name) VALUES ('acme-bank', 'Acme') ON CONFLICT DO NOTHING")
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            await scenario(client)
    finally:
        await pool.close()


async def login(c, monkeypatch, sub, email, tenant=None, platform="web"):
    async def verified(token):
        return {"sub": sub, "email": email, "email_verified": True, "name": "N"}
    monkeypatch.setattr(google, "verify_id_token", verified)
    monkeypatch.setattr(config, "GOOGLE_CLIENT_IDS", ["c"])
    s = (await c.post("/auth/google", json={"id_token": "t", "platform": platform},
                      headers={"X-Tenant-ID": tenant} if tenant else {})).json()
    return s["user"], {"Authorization": f"Bearer {s['access_token']}"}


async def opt_in(c, h):
    v = consent.PURPOSES["marketing"]["version"]
    assert (await c.put("/consents/marketing", json={"granted": True, "version": v}, headers=h)).status_code == 200


@needs_db
def test_offers_reach_only_people_who_opted_in_in_this_tenant(monkeypatch):
    class FakeWS:
        def __init__(self):
            self.sent = []

        async def send_json(self, d):
            self.sent.append(d)

        async def send_bytes(self, b):
            pass

    async def scenario(c):
        _, boss = await login(c, monkeypatch, "g-b", "boss@x.com")
        yes_d, yes = await login(c, monkeypatch, "g-1", "yes@x.com")
        _, no = await login(c, monkeypatch, "g-2", "no@x.com")
        android_d, android = await login(c, monkeypatch, "g-3", "droid@x.com", platform="android")
        _, acme = await login(c, monkeypatch, "g-4", "acme@x.com", tenant="acme-bank")
        _, acme_boss = await login(c, monkeypatch, "g-5", "boss@acme.com", tenant="acme-bank")
        for h in (yes, android, acme):
            await opt_in(c, h)
        assert (await c.post("/admin/campaigns", headers=yes, json={"title": "x", "body": "y"})).status_code == 403

        # the admin sees the users
        assert {u["email"] for u in (await c.get("/admin/users", headers=boss)).json()} >= {"yes@x.com", "no@x.com"}

        r = await c.post("/admin/campaigns", headers=boss, json={"title": "Health cover from Rs 299", "body": "Family floater, no room rent cap.",
                                                                 "cta_label": "See plans", "cta_url": "https://paytm.example/health"})
        assert r.status_code == 201 and r.json()["status"] == "draft"
        cid = r.json()["id"]
        assert (await c.post("/admin/campaigns", headers=boss, json={"title": "x", "body": "y", "cta_url": "http://insecure"})).status_code == 422
        assert (await c.post(f"/admin/campaigns/{cid}/image", headers=boss, files={"file": ("a.exe", b"MZ\x90 program")})).status_code == 415
        assert (await c.post(f"/admin/campaigns/{cid}/image", headers=boss, files={"file": ("ad.png", PNG)})).json()["has_image"]
        assert (await c.get(f"/admin/campaigns/{cid}", headers=boss)).json()["audience_size"] == 2   # opted-in, this tenant
        assert (await c.get(f"/admin/campaigns/{cid}", headers=acme_boss)).status_code == 404     # another tenant's campaign

        # an open conversation gets it live
        import tenancy
        with tenancy.as_tenant("paytm"):   # the in-process client shares this context; a real server isolates requests
            user = await store.get_user(yes_d["id"])
            ws = FakeWS()
            s = session_module.Session(ws, user)
            await s.start(ask_consent=False)
        r = await c.post(f"/admin/campaigns/{cid}/send", headers=boss)
        assert r.status_code == 200 and r.json()["recipients"] == 2 and r.json()["status"] == "sent"
        assert any(m["type"] == "inbox" and m["item"]["title"].startswith("Health cover") for m in ws.sent)
        assert (await c.post(f"/admin/campaigns/{cid}/send", headers=boss)).status_code == 409   # never twice

        inbox = (await c.get("/inbox", headers=yes)).json()
        (item,) = inbox["items"]
        assert inbox["marketing_consent"] and item["cta_label"] == "See plans" and item["has_image"]
        assert (await c.get("/inbox", headers=no)).json()["items"] == []                         # never opted in
        assert (await c.get("/inbox", headers=acme)).json()["items"] == []                       # other tenant
        img = await c.get(f"/inbox/{item['id']}/image", headers=yes)
        assert img.status_code == 200 and img.content == PNG
        assert (await c.get(f"/inbox/{item['id']}/image", headers=no)).status_code == 404

        await c.post(f"/inbox/{item['id']}/seen", headers=yes)
        assert (await c.post(f"/inbox/{item['id']}/click", headers=yes)).json()["url"] == "https://paytm.example/health"
        stats = (await c.get(f"/admin/campaigns/{cid}", headers=boss)).json()
        assert (stats["seen"], stats["clicked"]) == (1, 1)
        assert ledger.entries(subject=f"campaign:{cid}", kind="campaign")[0]["payload"]["recipients"] == 2

        # an audience filter
        r = await c.post("/admin/campaigns", headers=boss, json={"title": "App only", "body": "b", "audience": {"platforms": ["android"]}})
        assert (await c.post(f"/admin/campaigns/{r.json()['id']}/send", headers=boss)).json()["recipients"] == 1
        assert [i["title"] for i in (await c.get("/inbox", headers=android)).json()["items"]] == ["App only", "Health cover from Rs 299"]

        # the weekly cap
        monkeypatch.setattr(config, "MARKETING_WEEKLY_CAP", 2)
        r = await c.post("/admin/campaigns", headers=boss, json={"title": "Third", "body": "b"})
        sent = (await c.post(f"/admin/campaigns/{r.json()['id']}/send", headers=boss)).json()
        assert (sent["recipients"], sent["skipped_cap"]) == (1, 1)                                 # the android user already had 2

        # dismiss, then withdrawing consent removes what is left
        await c.delete(f"/inbox/{item['id']}", headers=yes)
        assert [i["title"] for i in (await c.get("/inbox", headers=yes)).json()["items"]] == ["Third"]
        out = (await c.put("/consents/marketing", json={"granted": False}, headers=yes)).json()
        assert out["erased"]["offers"] == 2 and (await c.get("/inbox", headers=yes)).json()["items"] == []
        r = await c.post("/admin/campaigns", headers=boss, json={"title": "After", "body": "b"})
        after = (await c.post(f"/admin/campaigns/{r.json()['id']}/send", headers=boss)).json()
        assert (after["recipients"], after["skipped_cap"]) == (0, 1)   # only the android user is opted in, and they hit the cap
    asyncio.run(with_app(scenario, monkeypatch))
