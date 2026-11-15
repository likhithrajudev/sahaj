import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from report import render, workflow
from trust import ledger
from trust.audit import Trace


@pytest.fixture(autouse=True)
def fresh_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LEDGER_DB", str(tmp_path / "ledger.db"))
    monkeypatch.setattr(ledger, "_conn", None)


def llm(t, purpose, ms, i, o, cached, app=False):
    t.add("llm", purpose=purpose, ms=ms, app_cache_hit=app, input_tokens=i, output_tokens=o, cached_tokens=cached)


def turn(subject, transcript, intent, conf, verdict="pass", source="classifier", sensitive=False, reply="ok", from_cache=False, caches=()):
    t = Trace(subject)
    t.add("stt", language="en-IN", transcript="[withheld: personal details]" if sensitive else transcript)
    t.add("intent", intent=intent, confidence=conf, detail="brief", reason="r", source=source)
    llm(t, "classify", 300, 1000, 20, 900)
    llm(t, "answer", 400, 500, 60, 0)
    for layer, hit in caches:
        t.add("cache", layer=layer, hit=hit)
    t.add("retrieval", scoped_to=None, clauses=[{"key": "d:1.1", "similarity": 0.88, "sha256": "x"}])
    t.add("node", name="classify", ms=300), t.add("node", name="guard", ms=100)
    t.add("guardrail", verdict=verdict, agent="insurance", kind="answer", from_cache=from_cache, reply=reply)
    t.add("route", path=["continue_active", "classify", "insurance_rag", "guard"])
    t.save()


def test_report_measures_what_happened():
    turn("s", "what is a waiting period", "insurance_explain", 0.9, caches=[("embeddings", False), ("verified_answers", False)])
    turn("s", "what does the plan not cover", "insurance_explain", 0.8, caches=[("embeddings", True), ("verified_answers", True)], from_cache=True)
    turn("s", "hmm", "greeting", 0.4, verdict="unsupported_claim")
    ledger.append("consent", "s", {"purpose": "conversation", "event": "granted"})
    r = workflow.build("s")
    assert r["overview"]["turns"] == 3
    assert r["intents"]["distribution"] == {"insurance_explain": 2, "greeting": 1}
    assert r["intents"]["mean_confidence"] == pytest.approx(0.7, abs=0.01) and r["intents"]["low_confidence_turns"] == 1
    assert r["llm"]["calls"] == 6 and r["llm"]["input_tokens"] == 4500 and r["llm"]["provider_cached_tokens"] == 2700
    assert r["llm"]["provider_cache_hit_rate"] == pytest.approx(0.6)
    assert r["llm"]["by_purpose"]["classify"]["cached_tokens"] == 2700
    assert r["caches"]["embeddings"] == {"hits": 1, "misses": 1, "hit_rate": 0.5}
    assert r["quality"]["blocked"] == 1 and r["quality"]["fallback_rate"] == pytest.approx(1 / 3, abs=0.001)
    assert r["quality"]["served_from_verified_cache"] == 1
    assert r["latency"]["by_node"]["classify"]["n"] == 3 and r["consents"][0]["purpose"] == "conversation"
    assert "graph TD" in r["routing"]["graph_mermaid"]


def test_personal_answers_never_reach_the_report():
    turn("s", "I earn 12 lakh and live in Bangalore", "insurance_advice", 0.95, sensitive=True, reply="[withheld: personal details]")
    blob = json.dumps(workflow.build("s")) + render.to_markdown(workflow.build("s")) + render.to_html(workflow.build("s"))
    assert "12 lakh" not in blob and "Bangalore" not in blob
    assert workflow.build("s")["overview"]["turns_with_personal_details_withheld"] == 1


def test_metrics_only_mode_drops_every_transcript_and_reply():
    turn("s", "tell me about waiting periods", "insurance_explain", 0.9, reply="A waiting period is...")
    r = workflow.build("s", include_text=False)
    assert "transcript" not in r["turns"][0] and "reply" not in r["turns"][0]
    assert "waiting periods" not in json.dumps(r) and "A waiting period is" not in json.dumps(r)


def test_html_report_escapes_what_users_said():
    turn("s", "<script>alert(1)</script>", "out_of_scope", 0.9)
    page = render.to_html(workflow.build("s"))
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_overview_combines_sessions_without_turn_detail():
    turn("a", "hello", "greeting", 0.95)
    turn("b", "what is a premium", "insurance_explain", 0.9)
    r = workflow.build_overview(10)
    assert r["overview"]["sessions"] == 2 and r["overview"]["turns"] == 2 and r["turns"] == []


def test_estimated_cost_only_when_prices_are_set(monkeypatch):
    turn("s", "hello", "greeting", 0.9)
    assert "estimated_cost" not in workflow.build("s")["llm"]
    for name, value in (("PRICE_INPUT_PER_M", 10.0), ("PRICE_OUTPUT_PER_M", 20.0), ("PRICE_CACHED_PER_M", 1.0)):
        monkeypatch.setattr(config, name, value)
    cost = workflow.build("s")["llm"]["estimated_cost"]
    assert cost["amount"] < cost["without_prompt_cache"]   # cached tokens are cheaper, so the cache saved money


def test_percentiles():
    assert workflow._pct([1, 2, 3, 4, 100], 50) == 3 and workflow._pct([], 95) is None


# ---- the API
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_API_KEY", "k")
    import main
    return TestClient(main.app), {"x-admin-key": "k"}


def test_report_endpoints(client):
    c, h = client
    turn("s", "hello", "greeting", 0.9)
    assert c.get("/audit/report/s", headers=h).json()["overview"]["turns"] == 1
    assert c.get("/audit/report/s?format=md", headers=h).text.startswith("# Sahaj workflow report")
    assert "<table>" in c.get("/audit/report/s?format=html", headers=h).text
    assert c.get("/audit/report/s?format=pdf", headers=h).status_code == 400
    assert c.get("/audit/report/missing", headers=h).status_code == 404
    assert c.get("/audit/report", headers=h).json()["overview"]["sessions"] == 1
    assert "classifier" in c.get("/audit/caches", headers=h).json()


def test_report_endpoints_need_the_admin_key(client):
    c, _ = client
    assert c.get("/audit/report/s").status_code == 401 and c.get("/audit/report").status_code == 401
