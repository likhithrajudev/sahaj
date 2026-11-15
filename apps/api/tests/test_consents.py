"""Consent: what is recorded, when it counts, how withdrawal cascades and erases, and the API a consent screen drives."""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from auth import google, store
from orchestrator import session as session_module
from trust import consent, consents, ledger

USER = store.User(id="11111111-1111-1111-1111-111111111111", email="a@example.com", name="Asha", picture=None,
                  language="en-IN", platform="web", role="user")


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LEDGER_DB", str(tmp_path / "ledger.db"))
    monkeypatch.setattr(ledger, "_conn", None)
    monkeypatch.setattr(config, "JWT_SECRET", "x" * 40)


@pytest.fixture
def erased(monkeypatch):
    calls = []

    async def fake(user, purpose):
        calls.append(purpose)
        return {"things": 1} if purpose in ("memory", "documents", "document_analysis", "conversation_records") else {}
    monkeypatch.setattr(consents, "_erase", fake)
    return calls


def run(coro):
    return asyncio.run(coro)


def decide(purpose, granted, version="current", **kw):
    version = consent.PURPOSES[purpose]["version"] if version == "current" else version
    return run(consents.set_consent(USER, purpose, granted, channel="api", version=version, **kw))


# ---------------------------------------------------------------- what a record holds
def test_a_grant_records_what_was_agreed_to_and_how(monkeypatch):
    decide("memory", True, ip="203.0.113.7")
    rec = ledger.entries(subject=USER.subject, kind="consent")[0]["payload"]
    assert rec["purpose"] == "memory" and rec["event"] == "granted" and rec["channel"] == "api"
    assert rec["version"] == consent.PURPOSES["memory"]["version"] and rec["text_sha256"] == consent.sha256("memory")
    assert rec["version_confirmed"] is True and rec["expires_at"] > time.time() + 300 * 86400
    assert rec["client"] and "203.0.113.7" not in json.dumps(rec)       # a hash of the address, never the address


def test_a_grant_without_the_shown_version_is_recorded_as_unconfirmed():
    run(consents.set_consent(USER, "memory", True, channel="ws"))
    assert ledger.entries(subject=USER.subject, kind="consent")[0]["payload"]["version_confirmed"] is False


def test_history_lists_decisions_in_order_with_the_chain_hash(erased):
    decide("memory", True)
    decide("memory", False)
    h = consent.history(USER.subject)
    assert [x["event"] for x in h] == ["granted", "revoked"] and all(x["ledger_hash"] and x["text_sha256"] for x in h)
    assert consent.history(USER.subject, "documents") == [] and ledger.verify()["intact"]


# ---------------------------------------------------------------- when a grant counts
def test_a_changed_text_asks_everyone_again(monkeypatch):
    decide("memory", True)
    assert consent.is_active(USER.subject, "memory")
    monkeypatch.setitem(consent.PURPOSES["memory"], "version", "2027-new-text")
    assert not consent.is_active(USER.subject, "memory")
    item = next(i for i in consent.status(USER.subject) if i["purpose"] == "memory")
    assert item["granted"] is False and item["action"] == "renew" and item["granted_version"] != item["version"]


def test_an_expired_grant_stops_counting(monkeypatch):
    decide("memory", True)
    real = time.time
    monkeypatch.setattr(consent.time, "time", lambda: real() + 366 * 86400)
    assert not consent.is_active(USER.subject, "memory")
    assert next(i for i in consent.status(USER.subject) if i["purpose"] == "memory")["action"] == "renew"


def test_status_tells_the_screen_what_to_offer(erased):
    items = {i["purpose"]: i for i in consent.status(USER.subject)}
    assert set(items) == set(consent.PURPOSES) and all(i["action"] == "ask" and not i["granted"] for i in items.values())
    assert items["conversation"]["required"] is True and items["document_analysis"]["requires"] == "documents"
    assert all(i["title"] and i["text"] and i["version"] and i["withdrawal"] for i in items.values())
    decide("conversation", True)
    assert next(i for i in consent.status(USER.subject) if i["purpose"] == "conversation")["action"] == "none"
    assert consents.missing_required(USER) == []


# ---------------------------------------------------------------- the service
def test_stale_unknown_and_missing_prerequisites_are_refused(erased):
    with pytest.raises(consents.ConsentError) as e:
        decide("memory", True, version="an-old-version")
    assert e.value.code == "stale_version"
    with pytest.raises(consents.ConsentError) as e:
        decide("telepathy", True, version="x")
    assert e.value.code == "unknown_purpose"
    with pytest.raises(consents.ConsentError) as e:
        decide("document_analysis", True)
    assert e.value.code == "requires" and e.value.purpose == "documents"
    assert ledger.entries(subject=USER.subject, kind="consent") == []        # a refusal records nothing


def test_withdrawing_a_purpose_withdraws_what_depends_on_it_and_erases(erased):
    decide("documents", True)
    decide("document_analysis", True)
    out = decide("documents", False)
    assert out["withdrawn"] == ["document_analysis", "documents"] and erased == ["document_analysis", "documents"]
    assert not consent.active(USER.subject)
    events = [(x["purpose"], x["event"]) for x in consent.history(USER.subject)]
    assert events[-2:] == [("document_analysis", "revoked"), ("documents", "revoked")]


def test_withdrawing_what_was_never_granted_changes_nothing(erased):
    assert decide("memory", False)["withdrawn"] == [] and erased == [] and consent.history(USER.subject) == []


def test_financial_profile_grant_and_withdrawal_purge_private_inventory(monkeypatch):
    calls = []

    async def erase(user, purpose):
        calls.append((user.id, purpose))
        return {"financial_inventory_items": 2}

    monkeypatch.setattr(consents, "_erase", erase)
    decide("conversation", True)
    decide("financial_profile", True)
    result = decide("financial_profile", False)
    assert result["erased"]["financial_inventory_items"] == 2
    assert calls == [(USER.id, "financial_profile"), (USER.id, "financial_profile")]
    assert not consent.is_active(USER.subject, "financial_profile")


def test_a_failed_erasure_is_reported_but_the_withdrawal_stands(monkeypatch):
    async def boom(user, purpose):
        raise OSError("storage down")
    monkeypatch.setattr(consents, "_erase", boom)
    decide("memory", True)
    with pytest.raises(consents.ConsentError) as e:
        decide("memory", False)
    assert e.value.code == "erasure_failed" and not consent.is_active(USER.subject, "memory")   # withdrawn regardless


# ---------------------------------------------------------------- the conversation
class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)


def conversation(erased_fixture=None):
    ws = FakeWS()
    return session_module.Session(ws, USER, "198.51.100.2"), ws


def say(s, **msg):
    run(s.on_control(json.dumps({"type": "consent", **msg})))


def test_consent_given_in_one_conversation_carries_to_the_next(erased):
    s1, ws1 = conversation()
    run(s1.start())
    assert ws1.sent[-1]["type"] == "consent_required" and ws1.sent[-1]["purpose"] == "conversation"
    say(s1, purpose="conversation", granted=True, version=consent.PURPOSES["conversation"]["version"])
    assert ws1.sent[-1] == {"type": "consent", "purpose": "conversation", "status": "granted"}
    s2, ws2 = conversation()
    run(s2.start())
    assert [m["type"] for m in ws2.sent] == ["session"]               # not asked again


def test_a_stale_version_over_the_socket_gets_the_current_text(erased):
    s, ws = conversation()
    say(s, purpose="memory", granted=True, version="old")
    assert [m["type"] for m in ws.sent] == ["error", "consent_required"] and ws.sent[1]["version"] == consent.PURPOSES["memory"]["version"]
    assert not consent.is_active(USER.subject, "memory")


def test_a_missing_prerequisite_and_an_unknown_purpose_over_the_socket(erased):
    s, ws = conversation()
    say(s, purpose="needs_analysis", granted=True)
    say(s, purpose="telepathy", granted=True)
    assert [m["type"] for m in ws.sent] == ["error", "error"] and "conversation" in ws.sent[0]["message"]


def test_withdrawing_conversation_consent_cascades_and_forgets_the_conversation(erased):
    s, ws = conversation()
    say(s, purpose="conversation", granted=True)
    say(s, purpose="needs_analysis", granted=True)
    s.history = [{"role": "user", "content": "hi"}]
    s.flow = object()
    ws.sent.clear()
    say(s, purpose="conversation", granted=False)
    assert [(m["purpose"], m["status"]) for m in ws.sent] == [("needs_analysis", "revoked"), ("conversation", "revoked")]
    assert s.history == [] and s.flow is None and not consent.active(USER.subject)


def test_a_withdrawal_made_elsewhere_takes_effect_in_a_running_conversation(erased):
    s, ws = conversation()
    say(s, purpose="conversation", granted=True)
    say(s, purpose="memory", granted=True)
    s.memory, s.history = "likes term plans", [{"role": "user", "content": "hi"}]
    decide("memory", False)                      # the person does it from their settings, via the REST API
    run(s._has_consent())
    assert s.memory is None and s.history == [{"role": "user", "content": "hi"}]   # memory gone, conversation still allowed
    decide("conversation", False)
    ws.sent.clear()
    assert run(s._has_consent()) is False and s.history == [] and ws.sent[0]["type"] == "consent_required"


def test_a_conversations_audit_trail_shows_the_consents_it_relied_on(erased):
    s, _ = conversation()
    say(s, purpose="conversation", granted=True)
    say(s, purpose="memory", granted=True)
    run(s._has_consent())
    run(s._has_consent())                         # noted once, not on every turn
    relied = [(e["payload"]["purpose"], e["payload"]["event"]) for e in ledger.entries(subject=s.id, kind="consent")]
    assert sorted(relied) == [("conversation", "in_effect"), ("memory", "in_effect")]


# ---------------------------------------------------------------- the API a consent screen drives
DB = os.getenv("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB, reason="set TEST_DATABASE_URL to run the Postgres tests")


async def with_app(scenario, monkeypatch):
    import httpx
    from psycopg_pool import AsyncConnectionPool
    from rag import store as rag_store
    from storage import blob, files, index
    from storage.blob import MemoryBlobStore
    from main import app

    monkeypatch.setattr(config, "DATABASE_URL", DB)
    pool = AsyncConnectionPool(DB, min_size=1, max_size=3, open=False, configure=rag_store._configure, kwargs={"autocommit": True})
    await rag_store.init_schema()
    await pool.open(wait=True)
    monkeypatch.setattr(rag_store, "_pool", pool)
    await store.init_schema()
    from tests.dbsetup import init_all
    await init_all()
    await files.init_schema()
    await index.init_schema()
    async with pool.connection() as conn:
        await conn.execute("TRUNCATE users CASCADE")
    blob.use(MemoryBlobStore())
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            await scenario(client)
    finally:
        blob.use(None)
        await pool.close()


async def login(c, monkeypatch, sub="g-1", email="a@example.com"):
    async def verified(token):
        return {"sub": sub, "email": email, "email_verified": True, "name": "N"}
    monkeypatch.setattr(google, "verify_id_token", verified)
    monkeypatch.setattr(config, "GOOGLE_CLIENT_IDS", ["c"])
    s = (await c.post("/auth/google", json={"id_token": "t"})).json()
    return s["user"]["id"], {"Authorization": f"Bearer {s['access_token']}"}


@needs_db
def test_consent_screen_api(monkeypatch):
    async def scenario(c):
        me, h = await login(c, monkeypatch)
        assert (await c.get("/consents")).status_code == 401

        listing = (await c.get("/consents", headers=h)).json()
        assert len(listing["items"]) == 7 and listing["missing_required"] == ["conversation"]
        mem = next(i for i in listing["items"] if i["purpose"] == "memory")
        assert mem["action"] == "ask" and mem["text"] and mem["withdrawal"] and mem["title"]

        # granting needs the version that was shown
        assert (await c.put("/consents/memory", json={"granted": True}, headers=h)).status_code == 422
        stale = await c.put("/consents/memory", json={"granted": True, "version": "old"}, headers=h)
        assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale_version"
        assert stale.json()["detail"]["current"]["version"] == mem["version"]       # the new text, ready to show
        assert (await c.put("/consents/telepathy", json={"granted": True, "version": "x"}, headers=h)).status_code == 404

        ok = await c.put("/consents/memory", json={"granted": True, "version": mem["version"]}, headers=h)
        assert ok.status_code == 200 and ok.json()["item"]["granted"] is True and ok.json()["item"]["action"] == "none"
        assert (await c.get("/users/me", headers=h)).json()["memory_consent"] is True

        # a prerequisite is enforced, and the record shows how each decision was made
        need = await c.put("/consents/document_analysis", json={"granted": True, "version": consent.PURPOSES["document_analysis"]["version"]}, headers=h)
        assert need.status_code == 409 and need.json()["detail"]["code"] == "requires"
        history = (await c.get("/consents/history", headers=h)).json()["items"]
        assert [(x["purpose"], x["event"]) for x in history] == [("memory", "granted")]
        assert history[0]["version_confirmed"] is True and history[0]["channel"] == "api" and history[0]["request_id"]
        assert (await c.get("/consents/history?purpose=documents", headers=h)).json()["items"] == []
        assert (await c.get("/consents/history?purpose=telepathy", headers=h)).status_code == 404

        # the old per-feature endpoints still work and land in the same record
        await c.put("/files/consent", json={"granted": True}, headers=h)
        assert "documents" in {x["purpose"] for x in (await c.get("/consents/history", headers=h)).json()["items"]}
    run(with_app(scenario, monkeypatch))


@needs_db
def test_withdrawal_over_the_api_cascades_and_erases_for_real(monkeypatch):
    from memory import store as memory_store
    from storage import blob
    pdf = b"%PDF-1.4 hello"

    async def scenario(c):
        me, h = await login(c, monkeypatch)
        v = lambda p: consent.PURPOSES[p]["version"]
        for p in ("memory", "documents", "document_analysis"):
            assert (await c.put(f"/consents/{p}", json={"granted": True, "version": v(p)}, headers=h)).status_code == 200
        await memory_store.save(me, "Asked about term plans.", {"interests": "term insurance"})
        assert (await c.post("/files", files={"file": ("a.pdf", pdf)}, headers=h)).status_code == 201
        assert len(blob.get().blobs) == 1

        out = (await c.put("/consents/documents", json={"granted": False}, headers=h)).json()
        assert out["withdrawn"] == ["document_analysis", "documents"] and out["erased"]["files"] == 1
        assert blob.get().blobs == {} and (await c.get("/files", headers=h)).json()["items"] == []
        assert not consent.is_active(f"user:{me}", "document_analysis")
        assert await memory_store.all_for(me)                                   # memory consent was untouched

        out = (await c.put("/consents/memory", json={"granted": False}, headers=h)).json()
        assert out["withdrawn"] == ["memory"] and out["erased"]["memories"] == 2 and await memory_store.all_for(me) == []
        assert (await c.put("/consents/memory", json={"granted": False}, headers=h)).json()["withdrawn"] == []   # again: nothing to do
        assert [x["event"] for x in (await c.get("/consents/history?purpose=memory", headers=h)).json()["items"]] == ["granted", "revoked"]

        # deleting the account records every withdrawal first
        await c.put("/consents/conversation", json={"granted": True, "version": v("conversation")}, headers=h)
        assert (await c.delete("/users/me", headers=h)).status_code == 204
        last = consent.history(f"user:{me}", "conversation")[-1]
        assert last["event"] == "revoked" and last["channel"] == "account_deletion"
    run(with_app(scenario, monkeypatch))
