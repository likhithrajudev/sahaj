"""Regressions for scoped document answers and the two demo drafts."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

from orchestrator import graph
from orchestrator.intent import Intent
from orchestrator.session import Session
from rag import embeddings
from routers import files as files_router
from storage import index
from trust.audit import Trace
from trust.pii import Vault

from tests.test_documents import embed, env, login, make_pdf, needs_db, with_app


def test_long_pdf_line_keeps_the_end():
    text = " ".join(["Long"] * 80) + " The final clause is preserved."
    assert " ".join(index.passages(text, 90)) == text


def test_empty_selected_source_does_not_generate_or_search_elsewhere(monkeypatch):
    async def mock_classify(*args, **kwargs):
        return Intent(intent="out_of_scope", confidence=0.1, search="eligible expenses")

    async def mock_embed(queries, *, cache_query):
        assert not cache_query
        return [embed(queries[0])]

    async def valid(_):
        return {"name": "selected"}

    async def empty(user_id, vector, k, file_id):
        assert user_id == "u" and file_id == "one"
        return []

    async def unexpected(*args, **kwargs):
        raise AssertionError("selected empty evidence must not generate or search another source")

    monkeypatch.setattr(graph, "classify_intent", mock_classify)
    monkeypatch.setattr(graph, "generate", unexpected)
    monkeypatch.setattr(graph, "retrieve", unexpected)
    monkeypatch.setattr(graph, "_web_search_turn", unexpected)
    monkeypatch.setattr(embeddings, "embed_queries", mock_embed)
    monkeypatch.setattr(index, "search", empty)
    session = SimpleNamespace(selected_document={"id": "one"}, user=SimpleNamespace(id="u"),
                              _readable_pdf=valid, flow=None, calc=None, last_intent=None,
                              history=[], vault=Vault())
    result = asyncio.run(graph.GRAPH.ainvoke(
        {"text": "How long?", "lang": "kn-IN", "language": "Kannada", "path": []},
        config={"configurable": {"session": session, "trace": Trace("test")}},
    ))
    assert result["path"] == ["continue_active", "classify", "selected_document", "guard"]
    assert result["turn"].text == graph.NO_EVIDENCE["kn-IN"]
    assert result["turn"].sources == {}


@needs_db
def test_owned_pdf_and_drafts_in_postgres(monkeypatch):
    from auth import store

    images = Path(__file__).parent / "fixtures" / "finals"
    ocr_content = {
        "discharge": "DISCHARGE SUMMARY\nPatient name: Arjun Rao\nHospital: Lakeside Demo Hospital\nAdmission date: 2026-11-10\nDischarge date: 2026-11-12",
        "hospital": "HOSPITAL BILL\nPatient name: Arjun Rao\nBill number: DEMO-HB-104\nTotal amount: INR 28,400.00",
        "pharmacy": "PHARMACY BILL\nPatient name: Arjun Rao\nTotal amount: INR 1,250.00",
        "prescription": "PRESCRIPTION\nPatient name: Arjun Rao",
        "payslip": "PAYSLIP\nEmployee name: Meera Das\nEmployer: Riverbend Demo Services\nNet pay: INR 42,000.00",
    }
    fixture_by_bytes = {(images / f"{name}.png").read_bytes(): text for name, text in ocr_content.items()}

    async def mock_ocr(data, content_type, language):
        assert content_type == "image/png"
        return [(1, fixture_by_bytes[data])], 1

    async def scenario(c, blobs):
        user_id, owner = await login(c, monkeypatch, "finals-a", "finals-a@example.com")
        second_id, other = await login(c, monkeypatch, "finals-b", "finals-b@example.com")
        for headers in (owner, other):
            assert (await c.put("/files/consent", json={"granted": True}, headers=headers)).is_success
            assert (await c.put("/files/analysis/consent", json={"granted": True}, headers=headers)).is_success
        from trust import consent
        consent.grant(f"user:{user_id}", "conversation")

        ids = []
        for filename, pages in (("star.pdf", ["Policy introduction here.", "Eligible post discharge expenses for up to 90 days."]),
                                ("hdfc.pdf", ["Eligible post discharge expenses for up to 180 days."])):
            result = await c.post("/files", files={"file": (filename, make_pdf(pages))}, headers=owner)
            assert result.status_code == 201, result.text
            assert result.json()["index_status"] == "indexing"
            ids.append(result.json()["id"])
            await asyncio.wait_for(asyncio.gather(*tuple(files_router._tasks)), timeout=60)
            listing = (await c.get("/files", headers=owner)).json()["items"]
            source = next(item for item in listing if item["id"] == ids[-1])
            assert source["index_status"] == "ready" and source["total_pages"] == len(pages)

        class Socket:
            sent = []

            async def send_json(self, payload):
                self.sent.append(payload)

        socket = Socket()
        session = Session(socket, await store.get_user(user_id))
        await session.on_control('{"type":"select_document","file_id":"%s"}' % ids[0])
        assert socket.sent[-1]["document"]["id"] == ids[0]
        resumed = Session(socket, session.user)
        assert await resumed.restore(session.id)
        assert resumed.selected_document == session.selected_document
        other_session = Session(socket, await store.get_user(second_id))
        await other_session.on_control('{"type":"select_document","file_id":"%s"}' % ids[0])
        assert socket.sent[-1]["document"] is None and socket.sent[-1]["error"]
        v = embed("eligible post discharge expenses")
        for selected_id, page, value in zip(ids, (2, 1), ("90", "180")):
            hits = await index.search(user_id, v, 1, file_id=selected_id)
            assert hits[0]["citation"]["page"] == page and value in hits[0]["text"]
            assert hits[0]["citation"]["file_id"] == selected_id
        preview = await c.get(f"/files/{ids[0]}?inline=true", headers=owner)
        assert preview.content.startswith(b"%PDF") and preview.headers["content-disposition"].startswith("inline")
        assert (await c.get(f"/files/{ids[0]}?inline=true", headers=other)).status_code == 404

        monkeypatch.setattr(index.ocr, "read", mock_ocr)
        draft = (await c.post("/drafts", json={"kind": "claim"}, headers=owner)).json()
        claim = f"/drafts/{draft['id']}"

        async def add(path, name):
            result = await c.post(path + "/attachments", files={"file": (f"{name}.png", (images / f"{name}.png").read_bytes())},
                                  headers=owner)
            assert result.status_code == 200, result.text
            return result.json()

        for name in ("discharge", "hospital", "pharmacy"):
            draft = await add(claim, name)
        assert draft["fields"]["hospital_total"] == "28400.00"
        assert draft["checklist"]["Prescription"] is False
        rev = {"revision": draft["revision"]}
        assert (await c.post(claim + "/submit", json=rev, headers=owner)).status_code == 409
        assert (await c.patch(claim + "/review", json={**rev, "fields": {}, "confirm": True}, headers=owner)).status_code == 422
        attachment = f"{claim}/attachments/{draft['documents'][0]['id']}"
        assert (await c.get(attachment, headers=other)).status_code == 404
        assert (await c.get(claim, headers=other)).status_code == 404
        draft = await add(claim, "prescription")
        r = await c.patch(claim + "/review", json={"revision": draft["revision"], "confirm": True,
                                                   "fields": {"hospital_total": "28500"}}, headers=owner)
        assert r.status_code == 200, r.text
        ready = r.json()
        assert ready["status"] == "ready"
        assert (await c.get(claim, headers=owner)).json()["fields"]["hospital_total"] == "28500.00"
        saved = await c.patch(claim + "/review", json={"revision": ready["revision"],
                                                      "fields": {"hospital_total": "28600"}}, headers=owner)
        assert saved.json()["status"] == "draft"
        assert (await c.post(claim + "/submit", json={"revision": ready["revision"]}, headers=owner)).status_code == 409
        ready = (await c.patch(claim + "/review", json={"revision": saved.json()["revision"], "confirm": True,
                                                       "fields": {}}, headers=owner)).json()
        body = {"revision": ready["revision"]}
        submitted = await c.post(claim + "/submit", json=body, headers=owner)
        assert submitted.json()["reference"].startswith("DEMO-CLAIM-")
        assert (await c.post(claim + "/submit", json=body, headers=owner)).json()["reference"] == submitted.json()["reference"]

        loan = (await c.post("/drafts", json={"kind": "loan"}, headers=owner)).json()
        path = f"/drafts/{loan['id']}"
        loan = await add(path, "payslip")
        assert loan["offer"]["total_repayment"] == 23274
        assert loan["fields"]["net_pay"] == "42000.00"
        ready = (await c.patch(path + "/review", json={"revision": loan["revision"], "confirm": True,
                                                       "fields": {"purpose": "School fees"}}, headers=owner)).json()
        assert (await c.post(path + "/submit", json={"revision": ready["revision"]}, headers=owner)).json()["reference"].startswith("DEMO-LOAN-")

        revoked = await c.put("/files/analysis/consent", json={"granted": False}, headers=owner)
        assert revoked.is_success, revoked.text
        assert await session._readable_pdf(ids[0]) is None
        assert await resumed.restore(session.id)
        assert resumed.selected_document["unavailable"] is True
        assert (await c.get(claim, headers=owner)).status_code == 403
        assert (await c.put("/files/analysis/consent", json={"granted": True}, headers=owner)).is_success
        assert (await c.get(claim, headers=owner)).status_code == 404

    asyncio.run(with_app(scenario, monkeypatch))
