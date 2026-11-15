"""Multi-tenant isolation, enforced by Postgres row-level security: one tenant can never see or change another's data,
even by id, even if application code forgot a filter."""
import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import tenancy
from auth import google, store
from trust import ledger

DB = os.getenv("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB, reason="set TEST_DATABASE_URL to run the Postgres tests")


def test_tenant_ids_are_checked():
    for good in ("paytm", "acme-bank", "nbfc1"):
        assert tenancy.valid(good)
    for bad in ("", "A", "Paytm", "x" * 40, "a b", "../x", "-x", "paytm;drop", None):
        assert not tenancy.valid(bad)
    with pytest.raises(tenancy.TenantError):
        tenancy.use("Bad Tenant")


def test_system_and_tenant_contexts_nest_and_restore():
    tenancy.use("paytm")
    with tenancy.system():
        assert tenancy.is_system()
        with tenancy.as_tenant("acme-bank"):
            assert tenancy.get() == "acme-bank" and not tenancy.is_system()
        assert tenancy.is_system()
    assert tenancy.get() == "paytm" and not tenancy.is_system()


async def with_app(scenario, monkeypatch, tmp_path):
    import httpx
    from psycopg_pool import AsyncConnectionPool
    from rag import store as rag_store
    from storage import blob, files, index
    from storage.blob import MemoryBlobStore
    from desk import store as desk
    from usage import ledger as usage_ledger
    from main import app

    monkeypatch.setattr(config, "LEDGER_DB", str(tmp_path / "ledger.db"))
    monkeypatch.setattr(ledger, "_conn", None)
    monkeypatch.setattr(config, "JWT_SECRET", "x" * 40)
    monkeypatch.setattr(config, "ADMIN_API_KEY", "platform-key")
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"boss@acme.example", "boss@paytm.example"})
    monkeypatch.setattr(config, "DATABASE_URL", DB)
    await rag_store.init_schema()
    raw = AsyncConnectionPool(DB, min_size=1, max_size=4, open=False, configure=rag_store._configure, kwargs={"autocommit": True})
    await raw.open(wait=True)
    monkeypatch.setattr(rag_store, "_pool", raw)
    for init in (store.init_schema, files.init_schema, index.init_schema, usage_ledger.init_schema, desk.init_schema):
        await init()
    async with raw.connection() as conn:   # the owner, outside isolation: a clean slate
        await conn.execute("TRUNCATE users CASCADE")
        await conn.execute("DELETE FROM tenants WHERE id <> %s", (config.DEFAULT_TENANT,))
        await conn.execute("DELETE FROM knowledge_chunks WHERE tenant_id <> 'public'")
    blob.use(MemoryBlobStore())
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            await scenario(client, raw)
    finally:
        blob.use(None)
        await raw.close()


async def login(c, monkeypatch, sub, email, tenant=None, name="N"):
    async def verified(token):
        return {"sub": sub, "email": email, "email_verified": True, "name": name}
    monkeypatch.setattr(google, "verify_id_token", verified)
    monkeypatch.setattr(config, "GOOGLE_CLIENT_IDS", ["c"])
    r = await c.post("/auth/google", json={"id_token": "t"}, headers={"X-Tenant-ID": tenant} if tenant else {})
    return r


@needs_db
def test_tenants_are_isolated_in_the_database(monkeypatch, tmp_path):
    from desk import store as desk
    from memory import store as memory_store
    from storage import blob
    from trust import consent

    async def scenario(c, raw):
        P = {"X-Admin-Key": "platform-key"}
        # the platform creates a second tenant; tenants cannot be created without the platform key
        assert (await c.post("/platform/tenants", json={"id": "acme-bank", "name": "Acme"})).status_code == 401
        r = await c.post("/platform/tenants", headers=P, json={"id": "acme-bank", "name": "Acme Bank", "settings": {"budget_usd": 2}})
        assert r.status_code == 201
        assert (await c.post("/platform/tenants", headers=P, json={"id": "acme-bank", "name": "x"})).status_code == 409
        assert (await login(c, monkeypatch, "g-1", "a@x.com", tenant="nobody-here")).status_code == 403
        assert (await login(c, monkeypatch, "g-1", "a@x.com", tenant="Bad Id")).status_code == 400

        # the same Google account signs in to both tenants: two separate accounts, same username in each
        pa = (await login(c, monkeypatch, "g-1", "asha@x.com")).json()
        ac = (await login(c, monkeypatch, "g-1", "asha@x.com", tenant="acme-bank")).json()
        assert pa["user"]["id"] != ac["user"]["id"] and pa["user"]["tenant"] == "paytm" and ac["user"]["tenant"] == "acme-bank"
        assert pa["user"]["username"] == ac["user"]["username"] == "asha"
        hp, ha = ({"Authorization": f"Bearer {s['access_token']}"} for s in (pa, ac))

        # each stores things: files, memory, a case
        for h in (hp, ha):
            await c.put("/files/consent", json={"granted": True}, headers=h)
            await c.put("/users/me/memory/consent", json={"granted": True}, headers=h)
        fp = (await c.post("/files", files={"file": ("p.pdf", b"%PDF-1.4 paytm")}, headers=hp)).json()
        fa = (await c.post("/files", files={"file": ("a.pdf", b"%PDF-1.4 acme")}, headers=ha)).json()
        with tenancy.as_tenant("paytm"):
            await memory_store.save(pa["user"]["id"], "Paytm person's note.", {"interests": "term insurance"})
        case = (await c.post("/cases", json={"kind": "callback"}, headers=ha)).json()
        assert sorted(blob.get().blobs)[0].startswith("acme-bank/asha/") and sorted(blob.get().blobs)[1].startswith("paytm/asha/")

        # by id, across tenants: not found, never forbidden-but-visible
        assert (await c.get(f"/files/{fa['id']}", headers=hp)).status_code == 404
        assert (await c.delete(f"/files/{fa['id']}", headers=hp)).status_code == 404
        assert (await c.post(f"/cases/{case['id']}/cancel", headers=hp)).status_code == 404
        assert [i["id"] for i in (await c.get("/files", headers=ha)).json()["items"]] == [fa["id"]]
        assert (await c.get("/users/me/memory", headers=ha)).json()["items"] == []

        # admins and executives see only their own tenant
        bp = (await login(c, monkeypatch, "g-bp", "boss@paytm.example")).json()
        ba = (await login(c, monkeypatch, "g-ba", "boss@acme.example", tenant="acme-bank")).json()
        hbp, hba = ({"Authorization": f"Bearer {s['access_token']}"} for s in (bp, ba))
        assert {u["tenant"] for u in (await c.get("/admin/users", headers=hba)).json()} == {"acme-bank"}
        assert {u["tenant"] for u in (await c.get("/admin/users", headers=hbp)).json()} == {"paytm"}
        assert (await c.patch(f"/admin/users/{pa['user']['id']}/role", headers=hba, json={"role": "admin"})).status_code == 404
        assert (await c.get("/desk/queue?view=all", headers=hbp)).json()["items"] == []          # Acme's case is not Paytm's
        assert [i["id"] for i in (await c.get("/desk/queue?view=all", headers=hba)).json()["items"]] == [case["id"]]
        assert (await c.post(f"/desk/cases/{case['id']}/claim", headers=hbp)).status_code == 409
        assert (await c.get(f"/desk/cases/{case['id']}", headers=hbp)).status_code == 404

        # a refresh token only works in its own tenant, and says which one it is
        assert pa["refresh_token"].startswith("paytm.") and ac["refresh_token"].startswith("acme-bank.")
        forged = "paytm." + ac["refresh_token"].split(".", 1)[1]
        assert (await c.post("/auth/refresh", json={"refresh_token": forged})).status_code == 401

        # the tenant's default monthly limit applies to its people
        assert (await c.get("/users/me/usage", headers=ha)).json()["budget_usd"] == 2
        assert (await c.get("/users/me/usage", headers=hp)).json()["budget_usd"] == config.USER_BUDGET_USD

        # suspending a tenant stops sign-in at once
        await c.patch("/platform/tenants/acme-bank", headers=P, json={"status": "suspended"})
        assert (await login(c, monkeypatch, "g-1", "asha@x.com", tenant="acme-bank")).status_code == 403
        tenants = {t["id"]: t for t in (await c.get("/platform/tenants", headers=P)).json()}
        assert tenants["acme-bank"]["status"] == "suspended" and tenants["acme-bank"]["users"] == 2
    asyncio.run(with_app(scenario, monkeypatch, tmp_path))


@needs_db
def test_the_database_itself_refuses_cross_tenant_access(monkeypatch, tmp_path):
    """The guarantee does not depend on our queries: raw SQL with no filter at all still sees one tenant only."""
    from rag import store as rag_store

    async def scenario(c, raw):
        await c.post("/platform/tenants", headers={"X-Admin-Key": "platform-key"}, json={"id": "acme-bank", "name": "Acme"})
        await login(c, monkeypatch, "g-1", "p@x.com")
        await login(c, monkeypatch, "g-2", "q@x.com", tenant="acme-bank")
        pool = rag_store.pool()

        async def as_(tenant, sql, *args):
            with tenancy.as_tenant(tenant):
                async with pool.connection() as conn:
                    return await (await conn.execute(sql, args or None)).fetchall()

        assert [r[0] for r in await as_("paytm", "SELECT email FROM users")] == ["p@x.com"]
        assert [r[0] for r in await as_("acme-bank", "SELECT email FROM users")] == ["q@x.com"]
        assert (await as_("paytm", "SELECT current_user"))[0][0] == config.DB_APP_ROLE        # requests run as the restricted role

        # no tenant at all: nothing visible, nothing writable (fails closed)
        tenancy.current_tenant.set(None)
        async with pool.connection() as conn:
            assert await (await conn.execute("SELECT count(*) FROM users")).fetchall() == [(0,)]
            with pytest.raises(Exception):
                await conn.execute("INSERT INTO users (google_sub, email) VALUES ('g-x', 'x@x.com')")
        tenancy.current_tenant.set("paytm")

        # writing a row into another tenant is refused by the policy, even with the tenant named explicitly
        with tenancy.as_tenant("paytm"):
            async with pool.connection() as conn:
                with pytest.raises(Exception):
                    await conn.execute("INSERT INTO users (google_sub, email, tenant_id) VALUES ('g-y', 'y@x.com', 'acme-bank')")
                cur = await conn.execute("UPDATE users SET name = 'hacked' WHERE email = 'q@x.com'")
                assert cur.rowcount == 0                                                    # invisible, so untouchable
                assert (await conn.execute("DELETE FROM users WHERE email = 'q@x.com'")).rowcount == 0
        assert [r[0] for r in await as_("acme-bank", "SELECT coalesce(name, '') FROM users")] == ["N"]

        # the tenants table is the platform's: requests cannot change it
        with tenancy.as_tenant("paytm"):
            async with pool.connection() as conn:
                with pytest.raises(Exception):
                    await conn.execute("UPDATE tenants SET status = 'active'")

        # the shared knowledge base: every tenant reads 'public'; a tenant's own documents stay its own
        zero = f"array_fill(0.0::real, ARRAY[{config.EMBED_DIM}])::vector"
        with tenancy.system():
            async with pool.connection() as conn:
                for tenant, doc in (("public", "shared-doc"), ("acme-bank", "acme-private")):
                    await conn.execute(f"""INSERT INTO knowledge_chunks (tenant_id, domain, doc_id, clause, content, content_sha256, embed_model, embedding)
                                           VALUES (%s, 'loan', %s, '1.1', 'text', 'sha', 'm', {zero}) ON CONFLICT DO NOTHING""", (tenant, doc))
        public = (await as_("paytm", "SELECT count(*) FROM knowledge_chunks WHERE tenant_id = 'public'"))[0][0]
        assert (await as_("paytm", "SELECT count(*) FROM knowledge_chunks WHERE doc_id = 'acme-private'"))[0][0] == 0
        assert (await as_("acme-bank", "SELECT count(*) FROM knowledge_chunks WHERE doc_id = 'acme-private'"))[0][0] == 1
        assert public >= 1 and (await as_("acme-bank", "SELECT count(*) FROM knowledge_chunks WHERE tenant_id = 'public'"))[0][0] == public
        with tenancy.as_tenant("acme-bank"):
            async with pool.connection() as conn:
                assert (await conn.execute("DELETE FROM knowledge_chunks WHERE tenant_id = 'public'")).rowcount == 0   # read-only for tenants
                assert (await conn.execute("UPDATE knowledge_chunks SET content = 'x' WHERE tenant_id = 'public'")).rowcount == 0
                with pytest.raises(Exception):
                    await conn.execute(f"""INSERT INTO knowledge_chunks (tenant_id, domain, doc_id, clause, content, content_sha256, embed_model, embedding)
                                           VALUES ('public', 'loan', 'fake', '9.9', 'planted', 'sha', 'm', {zero})""")
        assert public == (await as_("paytm", "SELECT count(*) FROM knowledge_chunks WHERE tenant_id = 'public'"))[0][0]
    asyncio.run(with_app(scenario, monkeypatch, tmp_path))
