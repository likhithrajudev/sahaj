"""Asking questions about a person's own PDFs: reading, masking before anything is stored, per-user retrieval."""
import asyncio
import hashlib
import math
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from auth import google, store
from rag import retrieve as retrieve_module
from storage import blob, files, index
from storage.blob import MemoryBlobStore
from trust import consent, ledger


def make_pdf(pages):
    """A small valid PDF with one line of text per page (built by hand so no PDF library is needed to test)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        n = len(objs) + 1
        stream = "BT /F1 12 Tf 50 700 Td (%s) Tj ET" % text.replace("(", "[").replace(")", "]")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {n + 1} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        kids.append(f"{n} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def embed(text):
    """A stand-in for the embedding model: words hashed into a normalised vector, so shared words mean similarity."""
    v = [0.0] * config.EMBED_DIM
    for w in re.findall(r"[a-z]+", text.lower()):
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % config.EMBED_DIM] += 1
    norm = math.sqrt(sum(x * x for x in v)) or 1
    return [x / norm for x in v]


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LEDGER_DB", str(tmp_path / "ledger.db"))
    monkeypatch.setattr(ledger, "_conn", None)
    monkeypatch.setattr(config, "JWT_SECRET", "x" * 40)

    async def passages(texts):
        return [embed(t) for t in texts]
    monkeypatch.setattr(index, "embed_passages", passages)
    monkeypatch.setattr(retrieve_module, "embed_queries", passages)
    monkeypatch.setattr(config, "RETRIEVAL_MIN_SIMILARITY", 0.2)
    yield
    blob.use(None)


# ---------------------------------------------------------------- reading and masking (no database)
def test_pdf_text_is_read_page_by_page():
    pages = index.pdf_pages(make_pdf(["The waiting period is 30 days.", "Premium is paid yearly."]))
    assert [p for p, _ in pages] == [1, 2] and "waiting period" in pages[0][1]


def test_unreadable_or_textless_pdfs_do_not_crash_indexing():
    with pytest.raises(Exception):
        index.pdf_pages(b"%PDF-1.4 not really")
    assert index.pdf_pages(make_pdf([""])) == []


def test_personal_identifiers_are_masked_before_storage():
    pages = [(1, "Borrower PAN ABCDE1234F, phone 98765 43210, account 123456789012. Interest is 9.5 percent a year.")]
    text = index.chunk(pages)[0]["content"]
    assert "ABCDE1234F" not in text and "9876543210" not in text and "123456789012" not in text
    assert "[PAN_1]" in text and "9.5 percent" in text


def test_chunking_labels_pages_and_respects_limits(monkeypatch):
    monkeypatch.setattr(config, "DOC_CHUNK_CHARS", 100)
    long = " ".join(f"Sentence number {i} is here and says something useful." for i in range(30))
    chunks = index.chunk([(1, long), (2, "Second page has a reasonable amount of text on it.")])
    assert all(len(c["content"]) <= 100 for c in chunks) and chunks[-1]["clause"].startswith("p2.")
    assert len({c["clause"] for c in chunks}) == len(chunks)
    monkeypatch.setattr(config, "DOC_MAX_CHUNKS", 3)
    assert len(index.chunk([(1, long)])) == 3
    assert index.chunk([(1, "short"), (2, "12")]) == []   # headings and page numbers are dropped


# ---------------------------------------------------------------- end to end against Postgres
DB = os.getenv("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB, reason="set TEST_DATABASE_URL to run the Postgres tests")


async def with_app(scenario, monkeypatch):
    import httpx
    from psycopg_pool import AsyncConnectionPool
    from rag import store as rag_store
    from main import app

    monkeypatch.setattr(config, "DATABASE_URL", DB)
    await rag_store.init_schema()
    pool = AsyncConnectionPool(DB, min_size=1, max_size=3, open=False, configure=rag_store._configure, kwargs={"autocommit": True})
    await pool.open(wait=True)
    monkeypatch.setattr(rag_store, "_pool", pool)
    await store.init_schema()
    from tests.dbsetup import init_all
    await init_all()
    await files.init_schema()
    await index.init_schema()
    async with pool.connection() as conn:
        await conn.execute("TRUNCATE users CASCADE")
    blobs = MemoryBlobStore()
    blob.use(blobs)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            await scenario(client, blobs)
    finally:
        await pool.close()


async def login(c, monkeypatch, sub, email):
    async def verified(token):
        return {"sub": sub, "email": email, "email_verified": True, "name": "N"}
    monkeypatch.setattr(google, "verify_id_token", verified)
    monkeypatch.setattr(config, "GOOGLE_CLIENT_IDS", ["c"])
    s = (await c.post("/auth/google", json={"id_token": "t"})).json()
    return s["user"]["id"], {"Authorization": f"Bearer {s['access_token']}"}


async def settled(c, h, file_id, want="ready"):
    for _ in range(100):
        item = next(i for i in (await c.get("/files", headers=h)).json()["items"] if i["id"] == file_id)
        if item["index_status"] not in ("indexing", "none"):
            return item
        await asyncio.sleep(0.05)
    return item


@needs_db
def test_documents_are_indexed_searched_per_person_and_forgotten(monkeypatch):
    loan = make_pdf(["The prepayment charge on this loan is 2 percent of the amount prepaid.",
                     "Borrower PAN ABCDE1234F. The processing fee is 1 percent of the loan amount."])

    async def scenario(c, blobs):
        me, h = await login(c, monkeypatch, "g-1", "a@example.com")
        other, oh = await login(c, monkeypatch, "g-2", "b@example.com")
        for headers in (h, oh):
            await c.put("/files/consent", json={"granted": True}, headers=headers)
        listing = (await c.get("/files", headers=h)).json()
        assert listing["analysis_consent"] is False and listing["analysis_consent_text"]["purpose"] == "document_analysis"

        # without the analysis consent the file is stored but not read
        f = (await c.post("/files", files={"file": ("offer.pdf", loan)}, headers=h)).json()
        assert f["index_status"] == "none"
        assert (await c.put("/files/analysis/consent", json={"granted": True}, headers=oh)).status_code == 200

        # granting it reads the PDFs already stored
        r = (await c.put("/files/analysis/consent", json={"granted": True}, headers=h)).json()
        assert r == {"consent": True, "queued": 1}
        item = await settled(c, h, f["id"])
        assert item["index_status"] == "ready" and item["indexed_chunks"] >= 1

        # the stored text is masked
        from auth.store import db
        async with db().connection() as conn:
            rows = await (await conn.execute("SELECT content FROM user_doc_chunks WHERE user_id = %s", (me,))).fetchall()
        assert rows and not any("ABCDE1234F" in r[0] for r in rows) and any("[PAN_1]" in r[0] for r in rows)

        # retrieval finds it for its owner, with a citable key, and never for anyone else
        hits = await retrieve_module.retrieve("loan", "what is the prepayment charge", [], user_id=me)
        mine = [x for x in hits if x.get("personal")]
        assert mine and mine[0]["key"].startswith("mydoc-") and "offer.pdf" in mine[0]["text"] and "prepayment" in mine[0]["text"]
        assert not [x for x in await retrieve_module.retrieve("loan", "what is the prepayment charge", [], user_id=other) if x.get("personal")]
        assert not [x for x in await retrieve_module.retrieve("loan", "what is the prepayment charge", []) if x.get("personal")]

        # a new upload by someone with consent is read straight away
        g = (await c.post("/files", files={"file": ("second.pdf", make_pdf(["Second document about a claim process."]))}, headers=h)).json()
        assert g["index_status"] == "indexing" and (await settled(c, h, g["id"]))["index_status"] == "ready"

        # a photo is read by OCR (mocked here) and becomes searchable like any PDF
        async def fake_ocr(data, content_type, language="en-IN"):
            return [(1, "Pharmacy bill from City Hospital. Prescription attached for all medicines.")], 1
        monkeypatch.setattr(index.ocr, "read", fake_ocr)
        png = b"\x89PNG\r\n\x1a\n" + b"x" * 40
        p = (await c.post("/files", files={"file": ("bill.png", png)}, headers=h)).json()
        assert p["category"] == "image" and (await settled(c, h, p["id"]))["index_status"] == "ready"
        assert any("pharmacy" in x["text"].lower() for x in await retrieve_module.retrieve("insurance", "pharmacy bill prescription", [], user_id=me))
        # a scanned PDF that OCR finds nothing on is "empty"
        async def nothing(data, content_type, language="en-IN"):
            return [], 1
        monkeypatch.setattr(index.ocr, "read", nothing)
        e = (await c.post("/files", files={"file": ("blank.pdf", make_pdf([""]))}, headers=h)).json()
        assert (await settled(c, h, e["id"]))["index_status"] == "empty"

        # deleting a file removes what was learned from it
        assert (await c.delete(f"/files/{g['id']}", headers=h)).status_code == 204
        async with db().connection() as conn:
            left = (await (await conn.execute("SELECT count(*) FROM user_doc_chunks WHERE file_id = %s", (g["id"],))).fetchone())[0]
        assert left == 0

        # withdrawing the analysis consent forgets everything learned, and keeps the files
        r = (await c.put("/files/analysis/consent", json={"granted": False}, headers=h)).json()
        assert r["consent"] is False and r["forgotten"] >= 1
        assert not await index.has_documents(me)
        items = (await c.get("/files", headers=h)).json()["items"]
        assert len(items) >= 2 and all(i["index_status"] == "none" for i in items)
        assert (await c.put("/files/analysis/consent", json={"granted": True}, headers=h)).status_code == 200

        # withdrawing document storage consent drops the analysis consent as well
        await c.put("/files/consent", json={"granted": False}, headers=h)
        assert not consent.is_active(f"user:{me}", "document_analysis") and not await index.has_documents(me)
    asyncio.run(with_app(scenario, monkeypatch))


@needs_db
def test_analysis_needs_documents_consent_first_and_a_bad_pdf_fails_safely(monkeypatch):
    async def scenario(c, blobs):
        me, h = await login(c, monkeypatch, "g-1", "a@example.com")
        assert (await c.put("/files/analysis/consent", json={"granted": True}, headers=h)).status_code == 409
        await c.put("/files/consent", json={"granted": True}, headers=h)
        await c.put("/files/analysis/consent", json={"granted": True}, headers=h)
        f = (await c.post("/files", files={"file": ("broken.pdf", b"%PDF-1.4 truncated nonsense")}, headers=h)).json()
        assert (await settled(c, h, f["id"]))["index_status"] == "failed"
        assert not await index.has_documents(me)
    asyncio.run(with_app(scenario, monkeypatch))


@needs_db
def test_graph_only_searches_documents_for_people_who_allowed_it(monkeypatch):
    from orchestrator import graph

    class S:
        def __init__(self, user):
            self.user = user

    async def scenario(c, blobs):
        me, h = await login(c, monkeypatch, "g-1", "a@example.com")
        user = await store.get_user(me)
        assert await graph._document_user(S(user)) is None                    # nothing indexed, no consent
        await c.put("/files/consent", json={"granted": True}, headers=h)
        await c.put("/files/analysis/consent", json={"granted": True}, headers=h)
        f = (await c.post("/files", files={"file": ("a.pdf", make_pdf(["Cover includes hospital stays and surgery."]))}, headers=h)).json()
        await settled(c, h, f["id"])
        assert await graph._document_user(S(user)) == me
        assert await graph._document_user(object()) is None                    # a session with no user (tests, tools)
        await c.put("/files/analysis/consent", json={"granted": False}, headers=h)
        assert await graph._document_user(S(user)) is None
    asyncio.run(with_app(scenario, monkeypatch))
