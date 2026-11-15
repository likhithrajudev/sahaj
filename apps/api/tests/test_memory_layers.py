"""The four memory layers: working (live state, resumable), episodic (past conversations), semantic (facts recalled by
meaning) and procedural (versioned prompts and workflows), each isolated per person and per tenant."""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import tenancy
from auth import google, store
from memory import episodic, procedural, semantic, working
from orchestrator import session as session_module
from orchestrator.turn import Turn
from trust import consent, ledger

USER = store.User(id="11111111-1111-1111-1111-111111111111", email="a@x.com", name="A", picture=None, language="en-IN",
                  platform="web", role="user", username="a", tenant_id="paytm")


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LEDGER_DB", str(tmp_path / "ledger.db"))
    monkeypatch.setattr(ledger, "_conn", None)
    monkeypatch.setattr(config, "JWT_SECRET", "x" * 40)
    working.use(working.InProcess())
    procedural.invalidate()
    yield
    working.use(None)


# ---------------------------------------------------------------- 1. working memory (no database)
def test_in_process_working_memory_expires(monkeypatch):
    store_ = working.InProcess()
    clock = [100.0]
    monkeypatch.setattr(working.time, "monotonic", lambda: clock[0])

    async def go():
        await store_.set("k", "v", 10)
        assert await store_.get("k") == "v"
        clock[0] += 11
        assert await store_.get("k") is None
    asyncio.run(go())


def test_redis_working_memory_round_trip_with_ttl():
    import fakeredis
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    working.use(working.RedisStore(client))

    async def go():
        await working.save(USER, "sess-1", {"user_id": USER.id, "history": [{"role": "user", "content": "hi"}]})
        k = working.key("paytm", USER.id, "sess-1")
        assert k == f"sahaj:wm:paytm:{USER.id}:sess-1"
        assert 0 < await client.ttl(k) <= config.WORKING_MEMORY_TTL_SECONDS
        assert (await working.load(USER, "sess-1"))["history"][0]["content"] == "hi"
        other_tenant = store.User(**{**USER.__dict__, "tenant_id": "acme-bank"})
        other_person = store.User(**{**USER.__dict__, "id": "22222222-2222-2222-2222-222222222222"})
        assert await working.load(other_tenant, "sess-1") is None      # the session id alone opens nothing
        assert await working.load(other_person, "sess-1") is None
        await working.drop(USER, "sess-1")
        assert await working.load(USER, "sess-1") is None
    asyncio.run(go())


def test_working_memory_failure_never_breaks_a_conversation():
    class Broken:
        async def get(self, k): raise ConnectionError("redis down")
        async def set(self, k, v, ttl): raise ConnectionError("redis down")
        async def delete(self, k): raise ConnectionError("redis down")
    working.use(Broken())

    async def go():
        await working.save(USER, "s", {})
        assert await working.load(USER, "s") is None
        await working.drop(USER, "s")
    asyncio.run(go())


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)

    async def send_bytes(self, data):
        pass


class Graph:
    async def astream(self, state, config, stream_mode):
        yield "values", {"turn": Turn(text="Answer.", judge=False, prechecked=True), "path": ["classify", "insurance_rag", "guard"],
                         "intent": __import__("orchestrator.intent", fromlist=["Intent"]).Intent(intent="insurance_explain", confidence=0.9)}


def test_a_dropped_conversation_resumes_from_working_memory(monkeypatch):
    monkeypatch.setattr(session_module, "GRAPH", Graph())
    consent.grant(USER.subject, "conversation", version=consent.PURPOSES["conversation"]["version"])

    async def go():
        first = session_module.Session(FakeWS(), USER)
        await first.start()
        await first.on_text("what is a waiting period")
        await first.on_text("and for maternity")
        assert len(first.history) == 4
        # the connection drops; a new one asks to resume
        ws = FakeWS()
        again = session_module.Session(ws, USER, resume=first.id)
        await again.start()
        assert again.id == first.id and ws.sent[0]["resumed"] is True and again.history == first.history
        assert again.last_intent == "insurance_explain" and again._turns == 2
        # nobody else can resume it, even knowing the id
        stranger = store.User(**{**USER.__dict__, "id": "33333333-3333-3333-3333-333333333333"})
        ws2 = FakeWS()
        other = session_module.Session(ws2, stranger, resume=first.id)
        await other.start()
        assert other.id != first.id and ws2.sent[0]["resumed"] is False and other.history == []
        # withdrawing conversation consent forgets it, so there is nothing to resume
        await again.on_control(json.dumps({"type": "consent", "purpose": "conversation", "granted": False}))
        await asyncio.sleep(0)
        assert await working.load(USER, first.id) is None
    asyncio.run(go())


# ---------------------------------------------------------------- 4. procedural memory (no database)
def test_procedures_fall_back_to_the_built_in_defaults():
    from agents.base import CORE
    from orchestrator.prompts import CLASSIFIER_SYSTEM
    assert procedural.text("answer.core_rules") == CORE and procedural.text("intent.classifier") == CLASSIFIER_SYSTEM
    assert set(procedural.versions().values()) == {"default"}
    assert len([l for l in procedural.text("fine_print.checklist.loan").splitlines() if l.strip()]) >= 8


@pytest.mark.parametrize("name, content, ok", [
    ("intent.classifier", 'Classify. Reply {"intent": .., "confidence": .., "search": ..}', True),
    ("intent.classifier", "Classify the message please, no JSON keys here at all", False),
    ("fine_print.checklist.loan", "fees\ncharges\npenalties\nGST", True),
    ("fine_print.checklist.loan", "only one topic here", False),
    ("answer.core_rules", "Answer only from documents and add the source tag after each fact.", True),
    ("answer.core_rules", "Answer however you like, there are no rules at all now.", False),
    ("no.such.procedure", "x" * 30, False), ("answer.fine_print", "short", False),
])
def test_procedure_versions_are_validated(name, content, ok):
    assert (procedural.validate(name, content) is None) is ok


# ---------------------------------------------------------------- against Postgres
DB = os.getenv("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB, reason="set TEST_DATABASE_URL to run the Postgres tests")


async def with_app(scenario, monkeypatch):
    import httpx
    from psycopg_pool import AsyncConnectionPool
    from rag import store as rag_store
    from tests.dbsetup import init_all
    from tests.test_documents import embed
    from main import app

    monkeypatch.setattr(config, "DATABASE_URL", DB)
    await rag_store.init_schema()
    pool = AsyncConnectionPool(DB, min_size=1, max_size=4, open=False, configure=rag_store._configure, kwargs={"autocommit": True})
    await pool.open(wait=True)
    monkeypatch.setattr(rag_store, "_pool", pool)
    await init_all()
    async with pool.connection() as conn:
        await conn.execute("TRUNCATE users CASCADE")
        await conn.execute("DELETE FROM procedures")
        await conn.execute("DELETE FROM tenants WHERE id <> %s", (config.DEFAULT_TENANT,))
        await conn.execute("INSERT INTO tenants (id, name) VALUES ('acme-bank', 'Acme') ON CONFLICT DO NOTHING")

    async def vectors(texts):
        return [embed(t) for t in texts]
    import rag.embeddings as emb
    monkeypatch.setattr(emb, "embed_passages", vectors)
    monkeypatch.setattr(emb, "embed_queries", vectors)
    monkeypatch.setattr(config, "SEMANTIC_MIN_SIMILARITY", 0.2)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            await scenario(client, pool)
    finally:
        await pool.close()


async def login(c, monkeypatch, sub, email, tenant=None):
    async def verified(token):
        return {"sub": sub, "email": email, "email_verified": True, "name": "N"}
    monkeypatch.setattr(google, "verify_id_token", verified)
    monkeypatch.setattr(config, "GOOGLE_CLIENT_IDS", ["c"])
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"boss@x.com", "boss@acme.com"})
    s = (await c.post("/auth/google", json={"id_token": "t"}, headers={"X-Tenant-ID": tenant} if tenant else {})).json()
    return s["user"], {"Authorization": f"Bearer {s['access_token']}"}


@needs_db
def test_episodes_and_facts_are_kept_recalled_by_meaning_and_erased(monkeypatch):
    from memory import service

    async def note(history):
        return {"summary": "Asked about the waiting period for a family health plan.",
                "facts": {"interests": "family health insurance", "preferred_style": "short answers", "goals": "cover parents"}}
    monkeypatch.setattr(service, "summarise", note)

    async def scenario(c, pool):
        user_d, h = await login(c, monkeypatch, "g-1", "asha@x.com")
        user = await store.get_user(user_d["id"])
        v = consent.PURPOSES
        await c.put("/consents/conversation", json={"granted": True, "version": v["conversation"]["version"]}, headers=h)
        monkeypatch.setattr(session_module, "GRAPH", Graph())
        s = session_module.Session(FakeWS(), user)
        await s.start()
        await s.on_text("waiting period for my parents")
        await s.close()
        assert (await c.get("/users/me/memory", headers=h)).json()["episodes"] == []        # no memory consent: nothing kept

        await c.put("/consents/memory", json={"granted": True, "version": v["memory"]["version"]}, headers=h)
        s = session_module.Session(FakeWS(), user)
        await s.start()
        await s.on_text("waiting period for my parents")
        await s.on_text("and maternity cover")
        await s.close()
        mem = (await c.get("/users/me/memory", headers=h)).json()
        (ep,) = mem["episodes"]
        assert ep["outcome"] == "answered" and ep["turns"] == 2 and ep["intents"] == {"insurance_explain": 2}
        assert ep["summary"].startswith("Asked about the waiting period") and ep["session_id"] == s.id
        assert {f["key"] for f in mem["facts"]} == {"interests", "preferred_style", "goals"}
        assert all("embedding" not in f for f in mem["facts"])

        # semantic recall: preferences always, other facts and episodes when they bear on the question
        recalled = await semantic.recall(user.id, "family health insurance for parents waiting period")
        assert "preferred style: short answers" in recalled and "family health insurance" in recalled
        assert "Related earlier conversations" in recalled
        unrelated = await semantic.recall(user.id, "car loan emi")
        assert "preferred style" in unrelated and "family health insurance" not in unrelated
        # a resumed conversation updates its episode rather than adding one
        s2 = session_module.Session(FakeWS(), user, resume=s.id)
        await s2.start()
        await s2.on_text("thanks")
        await s2.close()
        (ep,) = (await c.get("/users/me/memory", headers=h)).json()["episodes"]
        assert ep["turns"] == 3

        # other people (and other tenants) never see it
        other_d, oh = await login(c, monkeypatch, "g-2", "bob@x.com")
        assert (await c.get("/users/me/memory", headers=oh)).json()["episodes"] == []
        assert await semantic.recall(other_d["id"], "family health insurance") is None
        assert (await c.delete(f"/users/me/memory/episodes/{ep['id']}", headers=oh)).status_code == 404
        # export, then withdrawal erases both layers
        assert len((await c.get("/users/me/export", headers=h)).json()["conversations"]) == 1
        out = (await c.put("/consents/memory", json={"granted": False}, headers=h)).json()
        assert out["erased"]["episodes"] == 1 and out["erased"]["memories"] == 3
        mem = (await c.get("/users/me/memory", headers=h)).json()
        assert mem["episodes"] == [] and mem["facts"] == []
    asyncio.run(with_app(scenario, monkeypatch))


@needs_db
def test_procedures_are_versioned_per_tenant_audited_and_rolled_back(monkeypatch):
    async def scenario(c, pool):
        _, hb = await login(c, monkeypatch, "g-b", "boss@x.com")
        _, hu = await login(c, monkeypatch, "g-u", "user@x.com")
        _, ha = await login(c, monkeypatch, "g-a", "boss@acme.com", tenant="acme-bank")
        assert (await c.get("/admin/procedures", headers=hu)).status_code == 403
        listed = {p["name"]: p for p in (await c.get("/admin/procedures", headers=hb)).json()}
        assert listed["fine_print.checklist.loan"]["running"] == "default"

        name = "fine_print.checklist.loan"
        assert (await c.post(f"/admin/procedures/{name}", headers=hb, json={"content": "one"})).status_code == 422
        assert (await c.post("/admin/procedures/nope", headers=hb, json={"content": "x" * 30})).status_code == 404
        v1 = (await c.post(f"/admin/procedures/{name}", headers=hb, json={"content": "fees\npenalties\nprepayment", "note": "short list"})).json()
        v2 = (await c.post(f"/admin/procedures/{name}", headers=hb, json={"content": "fees\npenalties\nprepayment\nGST"})).json()
        assert (v1["version"], v2["version"], v1["status"]) == (1, 2, "draft")
        with tenancy.as_tenant("paytm"):
            await procedural.refresh(force=True)
            assert procedural.text(name) != "fees\npenalties\nprepayment"                    # a draft changes nothing
        assert (await c.post(f"/admin/procedures/{name}/versions/2/activate", headers=hb)).status_code == 200
        with tenancy.as_tenant("paytm"):
            await procedural.refresh(force=True)
            assert procedural.text(name).endswith("GST") and procedural.versions()[name] == "tenant:v2"
        with tenancy.as_tenant("acme-bank"):                                                  # another tenant is untouched
            await procedural.refresh(force=True)
            assert procedural.versions()[name] == "default"
        assert [v["version"] for v in (await c.get(f"/admin/procedures/{name}", headers=ha)).json()["versions"]] == []
        assert (await c.post(f"/admin/procedures/{name}/versions/2/activate", headers=ha)).status_code == 404

        # rollback to v1, then reset to the default; every step is in the ledger
        await c.post(f"/admin/procedures/{name}/versions/1/activate", headers=hb)
        with tenancy.as_tenant("paytm"):
            await procedural.refresh(force=True)
            assert procedural.versions()[name] == "tenant:v1"
        assert (await c.delete(f"/admin/procedures/{name}/active", headers=hb)).json()["retired"] == 1
        with tenancy.as_tenant("paytm"):
            await procedural.refresh(force=True)
            assert procedural.versions()[name] == "default"
        events = [(e["payload"]["event"], e["payload"].get("version")) for e in ledger.entries(subject="tenant:paytm", kind="procedure")]
        assert events == [("activated", 2), ("activated", 1), ("reset_to_default", None)]

        # a platform-wide version ('public') applies to every tenant that has not set its own
        with tenancy.system():
            async with __import__("rag.store", fromlist=["pool"]).pool().connection() as conn:
                await conn.execute("INSERT INTO procedures (tenant_id, name, version, content, status) VALUES "
                                   "('public', %s, 1, 'platform\\nfees\\npenalties', 'active')", (name,))
        for t in ("paytm", "acme-bank"):
            with tenancy.as_tenant(t):
                procedural.invalidate()
                await procedural.refresh(force=True)
                assert procedural.versions()[name] == "platform:v1" and procedural.text(name).startswith("platform")
    asyncio.run(with_app(scenario, monkeypatch))
