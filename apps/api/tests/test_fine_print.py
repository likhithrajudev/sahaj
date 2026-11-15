"""Explaining the hidden terms and costs of insurance and loans: grounded in the documents, cited, same for voice and text."""
import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from orchestrator import graph as g
from orchestrator.intent import INTENTS
from rag import loader


def test_the_fine_print_explainers_load_as_citable_clauses():
    for domain, wanted in (("insurance", {"1.1", "1.2", "1.5", "1.6", "2.1"}), ("loan", {"1.1", "1.2", "1.4", "2.2", "2.3"})):
        clauses = {c["clause"]: c for c in loader.load_chunks(domain) if c["doc_id"] == "concepts-fine-print"}
        assert wanted <= set(clauses) and all(len(c["content"]) < 1800 for c in clauses.values())   # each fits one embedding
        assert "concepts-fine-print" in loader.concept_docs(domain)
    loan = {c["clause"]: c["content"] for c in loader.load_chunks("loan") if c["doc_id"] == "concepts-fine-print"}
    assert "1 January 2026" in loan["2.2"] and "not less than one day" in loan["2.3"] and "APR" in loan["1.1"]
    ins = {c["clause"]: c["content"] for c in loader.load_chunks("insurance") if c["doc_id"] == "concepts-fine-print"}
    assert "36 months" in ins["1.5"] and "60 months" in ins["1.6"] and "30 days" in ins["2.1"]


def test_fine_print_is_its_own_intent_and_route():
    assert {"insurance_fine_print", "loan_fine_print"} <= set(INTENTS)
    assert g.ROUTES["insurance_fine_print"] == g.ROUTES["loan_fine_print"] == "fine_print"
    from orchestrator.prompts import CLASSIFIER_SYSTEM
    assert "insurance_fine_print" in CLASSIFIER_SYSTEM and "loan_fine_print" in CLASSIFIER_SYSTEM


def test_hidden_charges_are_offered_as_a_follow_up():
    from orchestrator import suggest
    assert "What are the hidden charges?" in suggest.for_intent("loan_explain", "en-IN", "answer", False)
    assert "इसमें छुपी शर्तें क्या हैं?" in suggest.for_intent("insurance_explain", "hi-IN", "answer", False)


def test_every_answer_is_told_to_include_limits_and_charges():
    from agents.base import BRIEF, DEEP, FINE_PRINT
    assert "limit, charge, exclusion or waiting period" in BRIEF and "charges" in DEEP
    assert "concepts-" in FINE_PRINT and "on purpose" in FINE_PRINT


DB = os.getenv("TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB, reason="set TEST_DATABASE_URL to run the Postgres tests")


class FakeSession:
    def __init__(self, user=None):
        from trust.pii import Vault
        self.id, self.vault, self.history, self.focus, self.memory, self.flow, self.calc = "s1", Vault(), [], [], None, None, None
        self.agent = self.last_intent = self.pending = None
        self.user = user

    def _can_advise(self):
        return True


@needs_db
def test_fine_print_cites_the_offer_and_the_explainers_and_lists_every_topic(monkeypatch):
    """With the real knowledge base (loan explainers and the sample Key Facts Statement) and a stand-in embedding model."""
    from psycopg_pool import AsyncConnectionPool
    from rag import ingest, store as rag_store
    from tests.test_documents import embed
    from trust.audit import Trace
    from orchestrator.intent import Intent

    asked = {}

    async def vectors(texts):
        return [embed(t) for t in texts]

    async def fake_generate(role, sources, text, previous, language, depth, advice=False, purpose="answer", memory=None):
        asked.update(sources=sources, depth=depth)
        key = next(iter(sources))
        return f"The processing fee is deducted from the loan amount. [{key}]"

    async def scenario():
        monkeypatch.setattr(config, "DATABASE_URL", DB)
        await rag_store.init_schema()
        pool = AsyncConnectionPool(DB, min_size=1, max_size=3, open=False, configure=rag_store._configure, kwargs={"autocommit": True})
        await pool.open(wait=True)
        monkeypatch.setattr(rag_store, "_pool", pool)
        import rag.embeddings as emb
        monkeypatch.setattr(emb, "embed_queries", vectors)
        monkeypatch.setattr(ingest, "embed_passages", vectors)
        monkeypatch.setattr(config, "EMBED_MODEL", "test-hash-embedding")
        monkeypatch.setattr(config, "RETRIEVAL_MIN_SIMILARITY", 0.1)
        monkeypatch.setattr(g, "generate", fake_generate)
        try:
            from tenancy.db import secure
            await secure(rag_store.pool())
            await ingest.sync_all()
            state = {"text": "what are the hidden charges in my loan", "lang": "en-IN", "language": "English", "path": [],
                     "intent": Intent(intent="loan_fine_print", confidence=0.95, search="hidden charges loan")}
            trace = Trace("s1")
            out = await g.fine_print.__wrapped__(state, {"configurable": {"session": FakeSession(), "trace": trace}})
        finally:
            await pool.close()
        return out, trace

    out, trace = asyncio.run(scenario())
    turn = out["turn"]
    keys = list(asked["sources"])
    assert any(k.startswith("concepts-fine-print:") for k in keys) and any(k.startswith("sample-kfs:") for k in keys)
    assert len(keys) <= g.FINE_PRINT_SOURCES
    assert not keys[0].startswith("concepts-")                     # the offer's own clauses come first
    assert asked["depth"].startswith("The user wants the hidden terms")
    assert turn.kind == "fine_print" and turn.judge and turn.detailed and turn.card["domain"] == "loan"
    topics = [t["topic"] for t in turn.card["topics"]]
    assert len(topics) >= 8 and "processing fee and GST on fees" in topics
    assert all(set(t["sources"]) <= set(keys) for t in turn.card["topics"])


# ---------------------------------------------------------------- citation repair
from trust import guardrails

SRC = {"kfs:2.1": "A one-time processing fee of 2 percent of the loan amount is charged at disbursal.",
       "fp:2.1": "Late payments can attract penal charges. Penal charges must be reasonable, disclosed in the Key Facts Statement, and are not added to the interest rate.",
       "fp:2.2": "Some loans charge a fee for repaying early. Floating-rate loans to individuals carry no prepayment charge from 1 January 2026."}


def test_a_statement_tagged_with_the_wrong_clause_is_moved_to_the_right_one():
    reply = ("A processing fee of 2 percent is charged at disbursal [kfs:2.1]. Penal charges must be reasonable, disclosed in the "
             "Key Facts Statement and are not added to the interest rate [fp:2.2].")
    fixed, n = guardrails.repair_citations(reply, SRC)
    assert n == 1 and "[fp:2.1]." in fixed and "[kfs:2.1]" in fixed and "[fp:2.2]" not in fixed


def test_correct_tags_unclear_matches_and_other_languages_are_left_alone():
    right = "Floating-rate loans to individuals carry no prepayment charge from 1 January 2026 [fp:2.2]."
    assert guardrails.repair_citations(right, SRC) == (right, 0)
    vague = "There are some charges to keep in mind [kfs:2.1]."
    assert guardrails.repair_citations(vague, SRC) == (vague, 0)
    hindi = "डिस्बर्सल के समय 2 प्रतिशत प्रोसेसिंग शुल्क लिया जाता है [fp:2.2]।"
    assert guardrails.repair_citations(hindi, SRC)[1] == 0          # no clear winner: the fact-check decides
    unknown = "Something about a tag we never gave [zz:9.9]."
    assert guardrails.repair_citations(unknown, SRC) == (unknown, 0)   # unknown tags stay, and the checks block them
