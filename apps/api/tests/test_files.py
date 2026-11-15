"""File uploads: validation, ownership, consent, cleanup. Postgres tests run only with TEST_DATABASE_URL set; the blob
store is in memory, and the S3 store is exercised against a mock S3."""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from auth import google, store
from auth import store as store_module
from storage import blob, files
from storage.blob import MemoryBlobStore
from trust import consent, ledger

PDF = b"%PDF-1.7\n" + b"x" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 50
JPEG = b"\xff\xd8\xff\xe0" + b"x" * 50
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"x" * 20


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LEDGER_DB", str(tmp_path / "ledger.db"))
    monkeypatch.setattr(ledger, "_conn", None)
    monkeypatch.setattr(config, "JWT_SECRET", "x" * 40)
    yield
    blob.use(None)


# ---------------------------------------------------------------- pure helpers
def _zip(*names):
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, "x")
    return buf.getvalue()


DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
GIF = b"GIF89a" + b"x" * 20
WAV = b"RIFF\x00\x00\x00\x00WAVEfmt " + b"x" * 20
MP3 = b"ID3\x03" + b"x" * 20
WEBM = b"\x1a\x45\xdf\xa3" + b"x" * 20


@pytest.mark.parametrize("data, expected", [
    (PDF, ("application/pdf", "document", "pdf")), (PNG, ("image/png", "image", "png")), (JPEG, ("image/jpeg", "image", "jpg")),
    (WEBP, ("image/webp", "image", "webp")), (GIF, ("image/gif", "image", "gif")),
    (WAV, ("audio/wav", "audio", "wav")), (MP3, ("audio/mpeg", "audio", "mp3")), (WEBM, ("audio/webm", "audio", "webm")),
    (b"\x00\x00\x00\x20ftypM4A " + b"x" * 8, ("audio/mp4", "audio", "m4a")),
    (_zip("[Content_Types].xml", "word/document.xml"), (DOCX, "document", "docx")),
    (_zip("[Content_Types].xml", "xl/workbook.xml"), ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "document", "xlsx")),
    ("नमस्ते, loan offer\n".encode(), ("text/plain", "document", "txt")),
    (b"<html>", ("text/plain", "document", "txt")),     # text, stored and served as plain text, so it never runs
    (_zip("a.txt"), None), (b"MZ\x90\x00\x03\x00", None), (b"abc\x00def", None), (b"", None),
    (b"\x7fELF\x02\x01\x01\x00", None), (b"\x7fELF\x02\x01", None), (b"line one\r\nline\ttwo\n", ("text/plain", "document", "txt")),
    (("é" * 100000).encode(), ("text/plain", "document", "txt")),   # long text is fine
    (b"ok text " * 1500 + b"\xff\xfe broken", None),               # invalid bytes anywhere, even far in, are not
])
def test_files_are_identified_by_their_bytes(data, expected):
    assert files.sniff(data) == expected


@pytest.mark.parametrize("raw, clean", [("../../etc/passwd", "passwd"), ("C:\\Users\\a\\loan.pdf", "loan.pdf"),
                                        ('we"ird<na>me|.pdf', "weirdname.pdf"), ("  ..hidden. ", "hidden"),
                                        ("a\x00b\n.pdf", "ab.pdf"), (None, "file"), ("", "file"), ("x" * 500 + ".pdf", "x" * 120)])
def test_filenames_are_made_safe(raw, clean):
    assert files.safe_name(raw) == clean


def test_blob_names_live_in_the_persons_folder_and_are_unguessable():
    a, b = files.blob_name("asha", "image", "png"), files.blob_name("asha", "image", "png")
    assert a.startswith("asha/images/") and a.endswith(".png") and a != b and len(a.split("/")[-1]) == 36
    assert files.blob_name("asha", "document", "pdf").startswith("asha/documents/")
    assert files.blob_name("asha", "audio", "mp3").startswith("asha/audio/")
    assert files.blob_name("asha", "voice", "webm", group="sess1", stem="0003") == "asha/voice/sess1/0003.webm"
    assert files.blob_name("asha", "transcript", "json", group="sess1", stem="0003") == "asha/transcripts/sess1/0003.json"


def test_memory_store_round_trip_and_prefix_delete():
    async def go():
        s = MemoryBlobStore()
        await s.put("users/u1/a", b"hello", "text/plain")
        await s.put("users/u1/b", b"x", "text/plain")
        await s.put("users/u2/a", b"y", "text/plain")
        with pytest.raises(FileExistsError):
            await s.put("users/u1/a", b"again", "text/plain")   # never overwrite
        assert b"".join([c async for c in s.stream("users/u1/a")]) == b"hello"
        assert await s.delete_prefix("users/u1/") == 2 and list(s.blobs) == ["users/u2/a"]
    asyncio.run(go())


def test_storage_is_unavailable_until_configured(monkeypatch):
    monkeypatch.setattr(config, "AWS_S3_BUCKET", None)
    blob.use(None)
    with pytest.raises(store.Unavailable):
        blob.get()


# ---------------------------------------------------------------- the S3 store, against a mock S3 (the real boto3 calls)
import boto3
from moto import mock_aws
from storage.blob import S3BlobStore

BUCKET = "paytm-sahaj"
REGION = "ap-southeast-2"


@pytest.fixture
def s3(monkeypatch):
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(name, "testing")
    with mock_aws():
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
        yield S3BlobStore(client, BUCKET), client


def keys(client, prefix=""):
    return sorted(o["Key"] for o in client.list_objects_v2(Bucket=BUCKET, Prefix=prefix).get("Contents", []))


def test_s3_round_trip_in_chunks_encrypted_and_typed(s3):
    store, client = s3
    data = bytes(range(256)) * 2000          # 512 KB: more than one chunk
    asyncio.run(store.put("users/u1/a", data, "application/pdf"))
    assert b"".join(asyncio.run(_collect(store.stream("users/u1/a")))) == data
    head = client.head_object(Bucket=BUCKET, Key="users/u1/a")
    assert head["ServerSideEncryption"] == "AES256" and head["ContentType"] == "application/pdf"


async def _collect(stream):
    return [c async for c in stream]


def test_s3_never_overwrites(s3):
    store, client = s3
    asyncio.run(store.put("users/u1/a", b"first", "text/plain"))
    with pytest.raises(FileExistsError):
        asyncio.run(store.put("users/u1/a", b"second", "text/plain"))
    assert client.get_object(Bucket=BUCKET, Key="users/u1/a")["Body"].read() == b"first"


def test_s3_delete_one_and_a_whole_prefix(s3):
    store, client = s3
    for name in ("users/u1/a", "users/u1/b", "users/u10/a", "users/u2/a"):
        asyncio.run(store.put(name, b"x", "text/plain"))
    asyncio.run(store.delete("users/u1/a"))
    asyncio.run(store.delete("users/u1/missing"))                       # deleting what is gone is fine
    assert keys(client) == ["users/u1/b", "users/u10/a", "users/u2/a"]
    assert asyncio.run(store.delete_prefix("users/u1/")) == 1           # u1/ only: u10/ is a different person
    assert keys(client) == ["users/u10/a", "users/u2/a"]


def test_s3_deleting_leaves_no_old_versions_behind(s3):
    store, client = s3
    client.put_bucket_versioning(Bucket=BUCKET, VersioningConfiguration={"Status": "Enabled"})
    asyncio.run(store.put("users/u1/a", b"x", "text/plain"))
    asyncio.run(store.put("users/u1/b", b"y", "text/plain"))
    client.put_object(Bucket=BUCKET, Key="users/u1/b", Body=b"another version")   # a second version of b
    assert asyncio.run(store.delete_prefix("users/u1/")) == 2
    left = client.list_object_versions(Bucket=BUCKET, Prefix="users/u1/")
    assert not left.get("Versions") and not left.get("DeleteMarkers")      # nothing recoverable: erasure is real
    asyncio.run(store.put("users/u2/a", b"z", "text/plain"))
    asyncio.run(store.delete("users/u2/a"))
    assert not client.list_object_versions(Bucket=BUCKET, Prefix="users/u2/").get("DeleteMarkers")


def test_s3_deletes_in_batches_of_a_thousand(s3):
    store, client = s3
    for i in range(1005):
        client.put_object(Bucket=BUCKET, Key=f"users/u1/{i}", Body=b"x")
    assert asyncio.run(store.delete_prefix("users/u1/")) == 1005 and keys(client) == []


def test_s3_readiness(s3):
    store, _ = s3
    assert asyncio.run(store.ready()) is True
    assert asyncio.run(S3BlobStore(store._s3, "no-such-bucket").ready()) is False


def test_s3_is_built_from_settings(monkeypatch):
    monkeypatch.setattr(config, "AWS_S3_BUCKET", None)
    with pytest.raises(store_module.Unavailable):
        S3BlobStore.from_config()
    monkeypatch.setattr(config, "AWS_S3_BUCKET", BUCKET)
    monkeypatch.setattr(config, "AWS_ENDPOINT_URL", "http://localhost:9000")
    monkeypatch.setattr(config, "S3_ACCESS_KEY", "AKIAEXPLICITKEY")      # keys from the settings win over the AWS chain
    monkeypatch.setattr(config, "S3_SECRET_KEY", "secret")
    built = S3BlobStore.from_config()
    assert built._s3._request_signer._credentials.access_key == "AKIAEXPLICITKEY"
    assert built._bucket == BUCKET and built._s3.meta.endpoint_url == "http://localhost:9000" and built._s3.meta.region_name == REGION


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
    await files.init_schema()
    async with pool.connection() as conn:
        await conn.execute("TRUNCATE users CASCADE")
    memory_store = MemoryBlobStore()
    blob.use(memory_store)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            await scenario(client, memory_store)
    finally:
        await pool.close()


def sign_in(monkeypatch, sub, email):
    async def verified(token):
        return {"sub": sub, "email": email, "email_verified": True, "name": "N"}
    monkeypatch.setattr(google, "verify_id_token", verified)
    monkeypatch.setattr(config, "GOOGLE_CLIENT_IDS", ["c"])


async def login(c, monkeypatch, sub="g-1", email="a@example.com"):
    sign_in(monkeypatch, sub, email)
    s = (await c.post("/auth/google", json={"id_token": "t"})).json()
    return s, {"Authorization": f"Bearer {s['access_token']}"}


def upload(c, headers, data=PDF, name="loan offer.pdf", ctype="application/pdf"):
    return c.post("/files", files={"file": (name, data, ctype)}, headers=headers)


@needs_db
def test_upload_download_delete_and_isolation(monkeypatch):
    async def scenario(c, blobs):
        me, h = await login(c, monkeypatch)
        assert (await c.post("/files", files={"file": ("a.pdf", PDF)})).status_code == 401
        assert (await upload(c, h)).status_code == 403                       # no consent yet

        listing = (await c.get("/files", headers=h)).json()
        assert listing["consent"] is False and listing["consent_text"]["purpose"] == "documents" and listing["items"] == []
        assert (await c.put("/files/consent", json={"granted": True}, headers=h)).json()["consent"] is True

        r = await upload(c, h)
        assert r.status_code == 201, r.text
        f = r.json()
        assert f["filename"] == "loan offer.pdf" and f["content_type"] == "application/pdf" and f["size_bytes"] == len(PDF)
        assert len(blobs.blobs) == 1 and next(iter(blobs.blobs)) .startswith(f"{me['user']['username']}/documents/")

        got = await c.get(f"/files/{f['id']}", headers=h)
        assert got.status_code == 200 and got.content == PDF and got.headers["content-type"] == "application/pdf"
        assert "attachment" in got.headers["content-disposition"] and got.headers["cache-control"] == "private, no-store"

        # somebody else cannot see, fetch or delete it
        _, other = await login(c, monkeypatch, "g-2", "b@example.com")
        assert (await c.get("/files", headers=other)).json()["items"] == []
        assert (await c.get(f"/files/{f['id']}", headers=other)).status_code == 404
        assert (await c.delete(f"/files/{f['id']}", headers=other)).status_code == 404
        assert (await c.get("/files/not-a-uuid", headers=h)).status_code == 404

        assert (await c.delete(f"/files/{f['id']}", headers=h)).status_code == 204
        assert blobs.blobs == {} and (await c.get(f"/files/{f['id']}", headers=h)).status_code == 404
    asyncio.run(with_app(scenario, monkeypatch))


@needs_db
def test_upload_validation(monkeypatch):
    async def scenario(c, blobs):
        _, h = await login(c, monkeypatch)
        await c.put("/files/consent", json={"granted": True}, headers=h)
        assert (await upload(c, h, b"MZ\x90 not a document", "virus.pdf", "application/pdf")).status_code == 415  # claims PDF, is not
        assert (await upload(c, h, b"", "empty.pdf")).status_code == 400
        monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 150)
        assert (await upload(c, h, PDF + b"y" * 100)).status_code == 413
        assert (await upload(c, h, PNG, "../../x.png", "text/plain")).json()["content_type"] == "image/png"   # the bytes decide
        assert (await upload(c, h, PNG, "../../x.png")).json()["filename"] == "x.png"
        monkeypatch.setattr(config, "MAX_FILES_PER_USER", 2)
        assert (await upload(c, h, JPEG, "c.jpg")).status_code == 409
        assert len(blobs.blobs) == 2   # rejected uploads left nothing behind
    asyncio.run(with_app(scenario, monkeypatch))


@needs_db
def test_storage_failure_leaves_no_record_and_unconfigured_storage_is_503(monkeypatch):
    async def scenario(c, blobs):
        _, h = await login(c, monkeypatch)
        await c.put("/files/consent", json={"granted": True}, headers=h)

        async def boom(*a, **k):
            raise OSError("db write failed")
        monkeypatch.setattr(files, "add", boom)
        r = await upload(c, h)
        assert r.status_code == 500 and r.json()["request_id"]   # the gateway turns it into a clean error
        assert blobs.blobs == {}                                 # and the blob was removed again

        blob.use(None)
        monkeypatch.setattr(config, "AWS_S3_BUCKET", None)
        assert (await upload(c, h)).status_code == 503
    asyncio.run(with_app(scenario, monkeypatch))


@needs_db
def test_withdrawing_consent_and_deleting_the_account_delete_the_files(monkeypatch):
    async def scenario(c, blobs):
        me, h = await login(c, monkeypatch)
        await c.put("/files/consent", json={"granted": True}, headers=h)
        await upload(c, h)
        await upload(c, h, PNG, "b.png")
        other, oh = await login(c, monkeypatch, "g-2", "b@example.com")
        await c.put("/files/consent", json={"granted": True}, headers=oh)
        await upload(c, oh, JPEG, "theirs.jpg")
        assert len(blobs.blobs) == 3

        r = await c.put("/files/consent", json={"granted": False}, headers=h)
        assert r.json() == {"consent": False, "deleted": 2}
        assert (await c.get("/files", headers=h)).json()["items"] == [] and len(blobs.blobs) == 1   # only theirs is left
        assert (await upload(c, h)).status_code == 403

        await c.put("/files/consent", json={"granted": True}, headers=h)
        await upload(c, h)
        assert (await c.delete("/users/me", headers=h)).status_code == 204
        assert all(n.startswith(f"{other['user']['username']}/") for n in blobs.blobs) and len(blobs.blobs) == 1
    asyncio.run(with_app(scenario, monkeypatch))


# ---------------------------------------------------------------- multipart upload to S3
def test_large_files_go_up_as_an_s3_multipart_upload(s3):
    import os as _os
    store, client = s3
    data = _os.urandom(20 * 1024 * 1024 + 123)           # 3 parts of up to 8 MB
    asyncio.run(store.put("asha/audio/big.wav", data, "audio/wav"))
    head = client.head_object(Bucket=BUCKET, Key="asha/audio/big.wav")
    assert head["ContentLength"] == len(data) and "-" in head["ETag"]          # "<hash>-<parts>": it was multipart
    assert head["ETag"].strip('"').endswith("-3") and head["ServerSideEncryption"] == "AES256" and head["ContentType"] == "audio/wav"
    assert b"".join(asyncio.run(_collect(store.stream("asha/audio/big.wav")))) == data
    with pytest.raises(FileExistsError):                                       # never overwrites, large files included
        asyncio.run(store.put("asha/audio/big.wav", data, "audio/wav"))
    assert client.list_multipart_uploads(Bucket=BUCKET).get("Uploads") is None   # nothing half-finished is left


def test_small_files_stay_a_single_request(s3):
    store, client = s3
    asyncio.run(store.put("asha/images/a.png", PNG, "image/png"))
    assert "-" not in client.head_object(Bucket=BUCKET, Key="asha/images/a.png")["ETag"]


# ---------------------------------------------------------------- folders, categories, recordings (Postgres)
@needs_db
def test_files_land_in_the_persons_folder_by_kind_and_uploads_of_every_kind_work(monkeypatch):
    mp3, docx = MP3 + b"y" * 50, _zip("[Content_Types].xml", "word/document.xml")

    async def scenario(c, blobs):
        me, h = await login(c, monkeypatch)
        assert me["user"]["username"] == "a"
        await c.put("/files/consent", json={"granted": True}, headers=h)
        sent = {"loan.pdf": (PDF, "documents", "document"), "photo.png": (PNG, "images", "image"),
                "pic.jpeg": (JPEG, "images", "image"), "anim.gif": (GIF, "images", "image"),
                "note.m4a": (b"\x00\x00\x00\x20ftypM4A " + b"z" * 30, "audio", "audio"), "voice.mp3": (mp3, "audio", "audio"),
                "letter.docx": (docx, "documents", "document"), "notes.txt": ("नमस्ते\n".encode(), "documents", "document")}
        for name, (data, folder, category) in sent.items():
            r = await c.post("/files", files={"file": (name, data, "application/octet-stream")}, headers=h)   # declared type is ignored
            assert r.status_code == 201, (name, r.text)
            assert r.json()["category"] == category
        assert all(k.startswith("a/") and k.split("/")[1] in ("documents", "images", "audio") for k in blobs.blobs)
        assert sorted(k.split("/")[1] for k in blobs.blobs).count("images") == 3
        assert (await c.get("/files?category=image", headers=h)).json()["items"].__len__() == 3
        assert (await c.get("/files", headers=h)).json()["folder"] == "a/"
        for refused in (b"MZ\x90\x00 program", _zip("a.txt"), b"\x7fELF\x02\x01", b"abc\x00def"):
            assert (await c.post("/files", files={"file": ("x.bin", refused)}, headers=h)).status_code == 415
    asyncio.run(with_app(scenario, monkeypatch))


@needs_db
def test_usernames_are_unique_stable_and_safe(monkeypatch):
    async def scenario(c, blobs):
        a, _ = await login(c, monkeypatch, "g-1", "Asha.K+x@example.com")
        b, _ = await login(c, monkeypatch, "g-2", "asha.k-x@other.com")
        c3, _ = await login(c, monkeypatch, "g-3", "../../etc@evil.com")
        assert (a["user"]["username"], b["user"]["username"]) == ("asha.k-x", "asha.k-x-2") and c3["user"]["username"] == "etc"
        again, _ = await login(c, monkeypatch, "g-1", "asha.new.address@example.com")      # the email changed: the folder does not
        assert again["user"]["username"] == "asha.k-x"
    asyncio.run(with_app(scenario, monkeypatch))


@needs_db
def test_recordings_and_transcripts_need_their_own_consent_and_go_with_it(monkeypatch):
    from orchestrator import session as session_module
    from orchestrator.turn import Turn
    from trust import consent as consent_module

    class FakeGraph:
        async def astream(self, state, config, stream_mode):
            yield "values", {"turn": Turn(text="The waiting period is 30 days.", judge=False, prechecked=True),
                             "path": ["guard"]}

    class FakeWS:
        def __init__(self): self.sent = []
        async def send_json(self, d): self.sent.append(d)
        async def send_bytes(self, b): pass

    async def scenario(c, blobs):
        me, h = await login(c, monkeypatch)
        user = await store.get_user(me["user"]["id"])
        monkeypatch.setattr(session_module, "GRAPH", FakeGraph())

        async def fake_stt(audio, name, ctype):
            return {"transcript": "what is the waiting period", "language_code": "en-IN"}

        async def silent(text, lang):
            return
            yield b""
        monkeypatch.setattr(session_module, "transcribe_audio", fake_stt)
        monkeypatch.setattr(session_module, "speak", silent)
        ws = FakeWS()
        s = session_module.Session(ws, user)
        await s.on_control(json.dumps({"type": "consent", "purpose": "conversation", "granted": True}))
        voice = WEBM + b"v" * 200

        await s.on_audio(voice)                                      # without the consent, nothing is kept
        assert blobs.blobs == {}

        v = lambda p: consent_module.PURPOSES[p]["version"]
        assert (await c.put("/consents/conversation_records", json={"granted": True, "version": v("conversation_records")}, headers=h)).status_code == 200
        await s.on_audio(voice)
        await s.on_control(json.dumps({"type": "text", "text": "and my PAN is ABCDE1234F"}))
        keys = sorted(blobs.blobs)
        sid = s.id
        assert keys == [f"a/transcripts/{sid}/0002.json", f"a/transcripts/{sid}/0003.json", f"a/voice/{sid}/0002.webm"]
        assert blobs.blobs[f"a/voice/{sid}/0002.webm"][0] == voice and blobs.blobs[f"a/voice/{sid}/0002.webm"][1] == "audio/webm"
        transcript = json.loads(blobs.blobs[f"a/transcripts/{sid}/0003.json"][0])
        assert transcript["channel"] == "text" and transcript["assistant"] == "The waiting period is 30 days."
        assert "ABCDE1234F" not in json.dumps(transcript) and "[PAN_1]" in transcript["user"]       # masked in the record

        listing = (await c.get("/files?category=voice", headers=h)).json()["items"]
        assert [i["content_type"] for i in listing] == ["audio/webm"] and listing[0]["filename"].startswith("recording-")
        assert len((await c.get("/files?category=transcript", headers=h)).json()["items"]) == 2
        assert (await c.get("/files", headers=h)).json()["items"].__len__() == 3
        got = await c.get(f"/files/{listing[0]['id']}", headers=h)
        assert got.content == voice

        # recordings do not count against the person's upload limit
        monkeypatch.setattr(config, "MAX_FILES_PER_USER", 1)
        await c.put("/files/consent", json={"granted": True}, headers=h)
        assert (await upload(c, h)).status_code == 201

        # withdrawing the recordings consent deletes them, and only them
        out = (await c.put("/consents/conversation_records", json={"granted": False}, headers=h)).json()
        assert out["erased"] == {"recordings": 3} and sorted(blobs.blobs) == [k for k in sorted(blobs.blobs) if k.startswith("a/documents/")]
        assert len(blobs.blobs) == 1
        # ... and withdrawing conversation consent takes the recordings consent with it
        await c.put("/consents/conversation_records", json={"granted": True, "version": v("conversation_records")}, headers=h)
        out = (await c.put("/consents/conversation", json={"granted": False}, headers=h)).json()
        assert "conversation_records" in out["withdrawn"]
    asyncio.run(with_app(scenario, monkeypatch))
