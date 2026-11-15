"""Sign-in, tokens, per-user memory. Tests that need Postgres run only when TEST_DATABASE_URL is set
(a throwaway database with the pgvector extension)."""
import asyncio
import os
import sys
import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from auth import deps, google, store, tokens
from memory import service as memory
from trust import consent, ledger

SECRET = "x" * 40
USER = store.User(id="11111111-1111-1111-1111-111111111111", email="a@example.com", name="Asha", picture=None,
                  language="en-IN", platform="web", role="user")


@pytest.fixture(autouse=True)
def settings(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LEDGER_DB", str(tmp_path / "ledger.db"))
    monkeypatch.setattr(ledger, "_conn", None)
    monkeypatch.setattr(config, "JWT_SECRET", SECRET)
    monkeypatch.setattr(config, "GOOGLE_CLIENT_IDS", ["client-1"])
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())


# ---------------------------------------------------------------- access tokens
def test_access_token_round_trip():
    token, ttl = tokens.issue_access(USER)
    claims = tokens.decode_access(token)
    assert claims["sub"] == USER.id and claims["role"] == "user" and ttl == config.ACCESS_TOKEN_MINUTES * 60


def test_access_token_rejects_tampering_expiry_wrong_type_and_other_keys():
    token, _ = tokens.issue_access(USER)
    with pytest.raises(store.InvalidToken):
        tokens.decode_access(token[:-2] + "xx")
    now = int(time.time())
    base = {"iss": config.JWT_ISSUER, "aud": tokens.AUDIENCE, "sub": USER.id, "iat": now, "exp": now + 60, "type": "access"}
    with pytest.raises(store.InvalidToken):
        tokens.decode_access(jwt.encode({**base, "exp": now - 10}, SECRET, "HS256"))
    with pytest.raises(store.InvalidToken):
        tokens.decode_access(jwt.encode({**base, "type": "refresh"}, SECRET, "HS256"))
    with pytest.raises(store.InvalidToken):
        tokens.decode_access(jwt.encode(base, "y" * 40, "HS256"))
    with pytest.raises(store.InvalidToken):  # an unsigned token must never be accepted
        tokens.decode_access(jwt.encode(base, None, "none"))


def test_auth_is_disabled_without_a_strong_secret(monkeypatch):
    monkeypatch.setattr(config, "JWT_SECRET", "short")
    with pytest.raises(store.Unavailable):
        tokens.issue_access(USER)


# ---------------------------------------------------------------- Google ID tokens
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def google_token(**overrides):
    now = int(time.time())
    claims = {"iss": "https://accounts.google.com", "aud": "client-1", "sub": "g-1", "email": "a@example.com",
              "email_verified": True, "name": "Asha", "iat": now, "exp": now + 300, **overrides}
    return jwt.encode(claims, KEY, "RS256")


@pytest.fixture
def google_keys(monkeypatch):
    monkeypatch.setattr(google, "_signing_key", lambda token: KEY.public_key())


def verify(token):
    return asyncio.run(google.verify_id_token(token))


def test_valid_google_token(google_keys):
    assert verify(google_token())["sub"] == "g-1"


@pytest.mark.parametrize("overrides", [
    {"aud": "someone-elses-app"}, {"iss": "https://evil.example"}, {"exp": int(time.time()) - 5},
    {"email_verified": False}, {"email": None},
])
def test_bad_google_tokens_are_rejected(google_keys, overrides):
    with pytest.raises(store.InvalidToken):
        verify(google_token(**overrides))


def test_google_token_signed_by_another_key_is_rejected(monkeypatch):
    monkeypatch.setattr(google, "_signing_key", lambda token: rsa.generate_private_key(65537, 2048).public_key())
    with pytest.raises(store.InvalidToken):
        verify(google_token())


def test_google_sign_in_is_disabled_without_client_ids(monkeypatch, google_keys):
    monkeypatch.setattr(config, "GOOGLE_CLIENT_IDS", [])
    with pytest.raises(store.Unavailable):
        verify(google_token())


# ---------------------------------------------------------------- the WebSocket handshake
class Handshake:
    def __init__(self, headers=None, query=None):
        self.headers, self.query_params = headers or {}, query or {}


def ws_user(ws, monkeypatch):
    async def get_user(user_id):
        return USER if user_id == USER.id else None
    monkeypatch.setattr(store, "get_user", get_user)
    return asyncio.run(deps.websocket_user(ws))


def test_websocket_accepts_a_token_in_the_header_or_query(monkeypatch):
    token, _ = tokens.issue_access(USER)
    assert ws_user(Handshake({"authorization": f"Bearer {token}"}), monkeypatch).id == USER.id
    assert ws_user(Handshake(query={"access_token": token}), monkeypatch).id == USER.id


def test_websocket_refuses_missing_or_bad_tokens(monkeypatch):
    assert ws_user(Handshake(), monkeypatch) is None
    assert ws_user(Handshake(query={"access_token": "nonsense"}), monkeypatch) is None


def test_voice_socket_closes_with_4401_when_not_signed_in():
    from fastapi.testclient import TestClient
    from main import app
    client = TestClient(app)  # not used as a context manager: no lifespan, which would load the embedding model
    with client.websocket_connect("/ws/voice") as ws:
        closed = ws.receive()
    assert closed["type"] == "websocket.close" and closed["code"] == 4401


# ---------------------------------------------------------------- memory: what may be stored
@pytest.mark.parametrize("text", ["my number is 9876543210", "call asha@example.com", "see https://x.example",
                                  "[PAN_1] holder", "cover of 50 lakh", "<script>"])
def test_unsafe_memory_text_is_dropped(text):
    assert memory.clean(text, 200) is None


def test_memory_parse_keeps_only_allowed_safe_items():
    raw = ('Sure! {"summary": "Asked about term insurance.", "facts": {"interests": "term insurance", '
           '"phone": "none", "goals": "compare plans 2025", "preferred_style": "short answers"}} done')
    note = memory.parse(raw)
    assert note["summary"] == "Asked about term insurance."
    assert note["facts"] == {"interests": "term insurance", "preferred_style": "short answers"}


@pytest.mark.parametrize("raw", ["not json", "[]", '{"summary": 5, "facts": []}', ""])
def test_memory_parse_survives_garbage(raw):
    assert memory.parse(raw) == {"summary": "", "facts": {}}


def test_memory_render():
    rows = [{"kind": "fact", "key": "preferred_language", "content": "Hindi"},
            {"kind": "summary", "key": None, "content": "Asked about term insurance."}]
    text = memory.render(rows)
    assert "preferred language: Hindi" in text and "Asked about term insurance." in text
    assert memory.render([]) is None


def test_remember_stores_only_the_filtered_note(monkeypatch):
    saved = []

    async def chat(messages, purpose):
        assert "[gave personal details]" not in messages[1]["content"]  # placeholders never reach the model
        return '{"summary": "Wanted a term plan.", "facts": {"interests": "term insurance 9876543210"}}'

    async def save(user_id, summary, facts):
        saved.append((user_id, summary, facts))

    monkeypatch.setattr(memory, "chat", chat)
    monkeypatch.setattr(memory.store, "save", save)
    history = [{"role": "user", "content": "I want a term plan"}, {"role": "assistant", "content": "Sure."},
               {"role": "user", "content": "and what about a health plan"}, {"role": "assistant", "content": "Yes."},
               {"role": "user", "content": "[gave personal details]"}]
    assert asyncio.run(memory.remember(USER.id, history)) is True
    assert saved == [(USER.id, "Wanted a term plan.", {})]   # the fact with a phone number was dropped


def test_remember_does_nothing_when_only_placeholders_were_exchanged(monkeypatch):
    async def chat(*a, **k):
        raise AssertionError("the model must not be called")
    monkeypatch.setattr(memory, "chat", chat)
    history = [{"role": "user", "content": "[gave personal details]"}, {"role": "assistant", "content": "[read back]"}]
    assert asyncio.run(memory.remember(USER.id, history)) is False


# ---------------------------------------------------------------- the session and its memory consent
class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, data):
        self.sent.append(data)


def make_session(monkeypatch, rows=None):
    from orchestrator import session as session_module
    erased = []

    async def for_prompt(user_id):
        return rows or []

    async def delete_all(user_id):
        erased.append(user_id)
        return 1

    async def no_episodes(user_id):
        return 0

    monkeypatch.setattr(session_module.memory_store, "for_prompt", for_prompt)
    monkeypatch.setattr(session_module.memory_store, "delete_all", delete_all)
    monkeypatch.setattr("memory.episodic.delete_all", no_episodes)
    return session_module.Session(FakeWS(), USER), erased


def test_memory_is_not_loaded_without_consent(monkeypatch):
    s, _ = make_session(monkeypatch, [{"kind": "fact", "key": "interests", "content": "term insurance"}])
    asyncio.run(s.start())
    assert s.memory is None and s.ws.sent[0]["memory"] is False


def test_memory_consent_belongs_to_the_person_and_loads_memory(monkeypatch):
    rows = [{"kind": "fact", "key": "interests", "content": "term insurance"}]
    s, _ = make_session(monkeypatch, rows)
    asyncio.run(s.on_control('{"type": "consent", "purpose": "memory", "granted": true}'))
    assert consent.is_active(USER.subject, "memory") and not consent.is_active(s.id, "memory")
    assert "term insurance" in s.memory
    # a later conversation by the same person starts with it
    s2, _ = make_session(monkeypatch, rows)
    asyncio.run(s2.start())
    assert s2.ws.sent[0]["memory"] is True


def test_withdrawing_memory_consent_erases_it(monkeypatch):
    s, erased = make_session(monkeypatch, [{"kind": "fact", "key": "interests", "content": "term insurance"}])
    asyncio.run(s.on_control('{"type": "consent", "purpose": "memory", "granted": true}'))
    asyncio.run(s.on_control('{"type": "consent", "purpose": "memory", "granted": false}'))
    assert s.memory is None and erased == [USER.id]
    assert s.ws.sent[-1] == {"type": "consent", "purpose": "memory", "status": "revoked"}


def test_close_remembers_only_with_consent(monkeypatch):
    calls = []

    async def remember(session):
        calls.append(session.user.id)

    s, _ = make_session(monkeypatch)
    monkeypatch.setattr("orchestrator.session.memory.remember_conversation", remember)
    s.history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    asyncio.run(s.close())
    assert calls == []
    consent.grant(USER.subject, "memory")
    asyncio.run(s.close())
    assert calls == [USER.id]


# ---------------------------------------------------------------- end to end against Postgres
DB = os.getenv("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB, reason="set TEST_DATABASE_URL to run the Postgres tests")


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
    async with pool.connection() as conn:
        await conn.execute("TRUNCATE users CASCADE")
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            await scenario(client)
    finally:
        await pool.close()


def sign_in_as(monkeypatch, sub="g-1", email="a@example.com"):
    async def verified(token):
        return {"sub": sub, "email": email, "email_verified": True, "name": "Asha", "picture": "http://p"}
    monkeypatch.setattr(google, "verify_id_token", verified)


def bearer(session):
    return {"Authorization": f"Bearer {session['access_token']}"}


@needs_db
def test_sign_in_profile_refresh_and_logout(monkeypatch):
    sign_in_as(monkeypatch)

    async def scenario(c):
        r = await c.post("/auth/google", json={"id_token": "t", "platform": "android"})
        assert r.status_code == 200, r.text
        first = r.json()
        assert first["user"]["platform"] == "android" and first["user"]["role"] == "user"

        assert (await c.get("/users/me")).status_code == 401
        me = await c.get("/users/me", headers=bearer(first))
        assert me.json()["email"] == "a@example.com" and me.json()["memory_consent"] is False

        r = await c.patch("/users/me", headers=bearer(first), json={"language": "hi-IN", "name": "Asha K"})
        assert r.json()["language"] == "hi-IN" and r.json()["name"] == "Asha K"
        assert (await c.patch("/users/me", headers=bearer(first), json={"language": "klingon"})).status_code == 422

        # signing in again is the same account
        again = (await c.post("/auth/google", json={"id_token": "t"})).json()
        assert again["user"]["id"] == first["user"]["id"] and again["user"]["name"] == "Asha K"

        # a refresh token works once; spending it again revokes the whole family, including the replacement
        second = (await c.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})).json()
        assert second["refresh_token"] != first["refresh_token"]
        assert (await c.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})).status_code == 401
        assert (await c.post("/auth/refresh", json={"refresh_token": second["refresh_token"]})).status_code == 401

        # logout revokes the device's refresh token
        third = (await c.post("/auth/google", json={"id_token": "t"})).json()
        assert (await c.post("/auth/logout", json={"refresh_token": third["refresh_token"]})).status_code == 204
        assert (await c.post("/auth/refresh", json={"refresh_token": third["refresh_token"]})).status_code == 401
        assert (await c.post("/auth/refresh", json={"refresh_token": "never-issued"})).status_code == 401

    asyncio.run(with_app(scenario, monkeypatch))


@needs_db
def test_google_failures_and_missing_config(monkeypatch):
    async def scenario(c):
        async def bad(token):
            raise store.InvalidToken("Invalid Google token: nope")
        monkeypatch.setattr(google, "verify_id_token", bad)
        assert (await c.post("/auth/google", json={"id_token": "t"})).status_code == 401
        monkeypatch.setattr(config, "JWT_SECRET", None)
        assert (await c.post("/auth/google", json={"id_token": "t"})).status_code == 503

    asyncio.run(with_app(scenario, monkeypatch))


@needs_db
def test_roles_and_admin_routes(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"boss@example.com"})

    async def scenario(c):
        sign_in_as(monkeypatch, "g-user", "a@example.com")
        user = (await c.post("/auth/google", json={"id_token": "t"})).json()
        sign_in_as(monkeypatch, "g-boss", "Boss@example.com")
        boss = (await c.post("/auth/google", json={"id_token": "t"})).json()
        assert user["user"]["role"] == "user" and boss["user"]["role"] == "admin"

        assert (await c.get("/admin/users", headers=bearer(user))).status_code == 403
        listed = (await c.get("/admin/users", headers=bearer(boss))).json()
        assert {u["email"] for u in listed} == {"a@example.com", "Boss@example.com"}

        uid = user["user"]["id"]
        r = await c.patch(f"/admin/users/{uid}/role", headers=bearer(boss), json={"role": "admin"})
        assert r.json()["role"] == "admin"
        # the role is read from the database, so the user's existing token is an admin token now
        assert (await c.get("/admin/users", headers=bearer(user))).status_code == 200
        bid = boss["user"]["id"]
        assert (await c.patch(f"/admin/users/{bid}/role", headers=bearer(boss), json={"role": "user"})).status_code == 400
        assert (await c.patch("/admin/users/22222222-2222-2222-2222-222222222222/role", headers=bearer(boss),
                              json={"role": "user"})).status_code == 404

    asyncio.run(with_app(scenario, monkeypatch))


@needs_db
def test_memory_lifecycle_and_account_deletion(monkeypatch):
    sign_in_as(monkeypatch)
    from memory import store as memory_store

    async def scenario(c):
        s = (await c.post("/auth/google", json={"id_token": "t"})).json()
        uid = s["user"]["id"]
        empty = (await c.get("/users/me/memory", headers=bearer(s))).json()
        assert empty["consent"] is False and empty["items"] == [] and empty["consent_text"]["purpose"] == "memory"

        r = await c.put("/users/me/memory/consent", headers=bearer(s), json={"granted": True})
        assert r.json()["consent"] is True
        await memory_store.save(uid, "Asked about term insurance.", {"interests": "term insurance"})
        await memory_store.save(uid, "Asked about EMI.", {"interests": "home loan EMI"})  # same fact key: replaced
        items = (await c.get("/users/me/memory", headers=bearer(s))).json()["items"]
        assert sorted(i["content"] for i in items) == ["Asked about EMI.", "Asked about term insurance.", "home loan EMI"]

        rows = await memory_store.for_prompt(uid)
        assert memory.render(rows).startswith("interests: home loan EMI")

        one = items[0]["id"]
        assert (await c.delete(f"/users/me/memory/{one}", headers=bearer(s))).status_code == 204
        assert (await c.delete(f"/users/me/memory/{one}", headers=bearer(s))).status_code == 404

        # only the most recent summaries are kept
        monkeypatch.setattr(config, "MEMORY_MAX_SUMMARIES", 2)
        for n in ("one", "two", "three"):
            await memory_store.save(uid, f"Summary {n}.", {})
        kinds = [i["content"] for i in (await c.get("/users/me/memory", headers=bearer(s))).json()["items"]
                 if i["kind"] == "summary"]
        assert sorted(kinds) == ["Summary three.", "Summary two."]

        # withdrawing consent erases everything
        r = await c.put("/users/me/memory/consent", headers=bearer(s), json={"granted": False})
        assert r.json()["consent"] is False and r.json()["erased"] >= 2
        assert (await c.get("/users/me/memory", headers=bearer(s))).json()["items"] == []

        # one person cannot see or delete another's memory
        sign_in_as(monkeypatch, "g-2", "b@example.com")
        other = (await c.post("/auth/google", json={"id_token": "t"})).json()
        await memory_store.save(uid, "Mine.", {})
        assert (await c.get("/users/me/memory", headers=bearer(other))).json()["items"] == []
        mine = (await memory_store.all_for(uid))[0]["id"]
        assert (await c.delete(f"/users/me/memory/{mine}", headers=bearer(other))).status_code == 404

        # deleting the account removes the person, their tokens and their memory
        assert (await c.delete("/users/me", headers=bearer(s))).status_code == 204
        assert (await c.get("/users/me", headers=bearer(s))).status_code == 401
        assert (await c.post("/auth/refresh", json={"refresh_token": s["refresh_token"]})).status_code == 401
        assert await memory_store.all_for(uid) == []
        assert not consent.is_active(f"user:{uid}", "memory")

    asyncio.run(with_app(scenario, monkeypatch))
