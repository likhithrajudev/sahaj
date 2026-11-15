import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from agents.base import BRIEF, CORE, DEEP, system_prompt
from orchestrator import graph as g
from orchestrator.intent import INTENTS, Intent
from orchestrator.prompts import CLASSIFIER_SYSTEM
from orchestrator.turn import Turn
from services import cache, telemetry
from trust.audit import Trace
from trust.pii import Vault


class FakeSession:
    """Just the parts of Session the graph reads and writes."""

    def __init__(self):
        self.id, self.vault, self.history = "s1", Vault(), []
        self.flow = self.calc = self.agent = self.last_intent = self.pending = None
        self.focus, self.consented, self.memory = [], True, None

    def _can_advise(self):
        return self.consented


HIT = {"key": "doc:1.1", "text": "1.1 Waiting period\nThe waiting period is 30 days.", "sha256": "aaa", "similarity": 0.9}


@pytest.fixture
def stubs(monkeypatch):
    """No network, no database: the model, retrieval and fact-check are replaced, and call counts are kept."""
    calls = {"generate": 0, "classify": 0, "retrieve": 0, "grounded": 0}
    state = {"intent": Intent(intent="insurance_explain", confidence=0.95), "hits": [HIT]}

    async def classify_intent(text, previous, in_flow, asking):
        calls["classify"] += 1
        return state["intent"]

    async def retrieve(domain, text, history, deep=False, scope=None, user_id=None):
        calls["retrieve"] += 1
        return state["hits"]

    async def generate(role, sources, text, previous, language, depth, advice=False, purpose="answer", memory=None):
        calls["generate"] += 1
        return "The waiting period is 30 days [doc:1.1]."

    async def phrase(instruction, language):
        return "ASK: " + instruction

    async def grounded(reply, sources, question, detailed=False):
        calls["grounded"] += 1
        return True
    monkeypatch.setattr(g, "classify_intent", classify_intent)
    monkeypatch.setattr(g, "retrieve", retrieve)
    monkeypatch.setattr(g, "generate", generate)
    monkeypatch.setattr(g, "phrase", phrase)
    monkeypatch.setattr(g.guardrails, "is_grounded", grounded)
    cache.ANSWER_CACHE.clear()
    return calls, state


def run(text, session=None, lang="en-IN"):
    session = session or FakeSession()
    trace = Trace("s1")
    telemetry.current_trace.set(trace)
    result = asyncio.run(g.GRAPH.ainvoke({"text": text, "lang": lang, "language": "English", "path": []},
                                         config={"configurable": {"session": session, "trace": trace}}))
    return result, trace, session


# ---------------------------------------------------------------- routing
@pytest.mark.parametrize("intent, node", [
    ("insurance_explain", "insurance_rag"), ("insurance_advice", "advice"), ("insurance_compare", "compare"),
    ("loan_explain", "loan_rag"), ("loan_guidance", "loan_rag"), ("loan_calculator", "calculator"),
    ("loan_rates_comparison", "decline"), ("out_of_scope", "decline"), ("greeting", "greeting"),
    ("human_handoff", "handoff"),
])
def test_every_intent_has_a_route(stubs, monkeypatch, intent, node):
    calls, state = stubs
    state["intent"] = Intent(intent=intent, confidence=0.95)

    async def noop(self, *a, **k):  # the calculator and the advice flow are tested on their own
        return Turn("x", kind="ask", judge=False)
    monkeypatch.setattr(g.LoanCalc, "handle", noop)
    monkeypatch.setattr(g.AdviceFlow, "handle", noop)
    result, trace, _ = run("anything")
    assert result["path"] == ["continue_active", "classify", node] + ([] if intent == "human_handoff" else ["guard"])


def test_all_declared_intents_are_routed():
    assert set(g.ROUTES) == set(INTENTS)


def test_low_confidence_asks_instead_of_guessing(stubs):
    calls, state = stubs
    state["intent"] = Intent(intent="loan_explain", confidence=0.4)
    result, _, _ = run("what about that one?")
    assert result["path"] == ["continue_active", "classify", "clarify", "guard"] and result["turn"].kind == "ask"
    assert calls["retrieve"] == 0   # nothing was looked up on a guess


def test_a_request_for_a_person_is_never_second_guessed(stubs):
    calls, state = stubs
    state["intent"] = Intent(intent="human_handoff", confidence=0.2)
    result, _, _ = run("get me someone")
    assert result["handoff"] == "user_requested" and "turn" not in result


def test_term_versus_whole_life_is_an_explanation_not_a_comparison(stubs):
    calls, state = stubs
    state["intent"] = Intent(intent="insurance_compare", confidence=0.9)
    result, _, _ = run("what is the difference between term and whole life insurance")
    assert "insurance_rag" in result["path"] and "compare" not in result["path"]


def test_rates_and_out_of_scope_get_fixed_honest_text_without_the_model(stubs):
    calls, state = stubs
    state["intent"] = Intent(intent="loan_rates_comparison", confidence=0.95)
    rates, _, _ = run("will this loan be approved")
    state["intent"] = Intent(intent="out_of_scope", confidence=0.95)
    other, _, _ = run("tell me a joke")
    assert "lender can decide" in rates["turn"].text and "only help with insurance and loans" in other["turn"].text
    assert calls["generate"] == 0   # nothing was improvised


def test_advice_needs_permission_first(stubs, monkeypatch):
    calls, state = stubs
    state["intent"] = Intent(intent="insurance_advice", confidence=0.95)
    monkeypatch.setattr(g.catalogue, "is_sample", lambda: False)
    s = FakeSession()
    s.consented = False
    result, _, session = run("which plan should I buy", s)
    assert result["turn"].request_consent == "needs_analysis" and session.pending == ("which plan should I buy", "en-IN")


def test_sample_insurance_advice_uses_generic_live_search(stubs, monkeypatch):
    _, state = stubs
    state["intent"] = Intent(intent="insurance_advice", confidence=0.95)
    monkeypatch.setattr(g.catalogue, "is_sample", lambda: True)
    calls = []

    async def live_search(state, run_config, domain, query_override=None):
        calls.append((domain, query_override))
        return Turn("Current insurer pages [web:1].", sources={"web:1": "Official product page."})

    monkeypatch.setattr(g, "_web_search_turn", live_search)
    result, _, session = run("Which health insurance should I buy? I have diabetes.", FakeSession())

    assert result["turn"].sources == {"web:1": "Official product page."}
    assert calls == [("insurance", "current health insurance plans India official insurer product features")]
    assert session.flow is None and session.pending is None


def test_sample_insurance_comparison_uses_live_search(stubs, monkeypatch):
    _, state = stubs
    state["intent"] = Intent(intent="insurance_compare", confidence=0.95, search="compare Lotus and Neem plans")
    monkeypatch.setattr(g.catalogue, "is_sample", lambda: True)
    calls = []

    async def live_search(state, run_config, domain, query_override=None):
        calls.append((domain, query_override))
        return Turn("Current insurer pages [web:1].", sources={"web:1": "Official product page."})

    monkeypatch.setattr(g, "_web_search_turn", live_search)
    result, _, _ = run("Compare two health plans")

    assert result["turn"].sources == {"web:1": "Official product page."}
    assert calls == [("insurance", "compare Lotus and Neem plans")]


def test_an_active_conversation_gets_the_first_look(stubs, monkeypatch):
    calls, state = stubs

    class Flow:
        active, asking = True, "age"

        async def handle(self, *a, **k):
            return Turn("what is your income?", kind="ask", judge=False)
    s = FakeSession()
    s.flow = Flow()
    result, trace, _ = run("34", s)
    assert result["path"] == ["continue_active", "guard"] and calls["classify"] == 0   # no classifier call needed


# ---------------------------------------------------------------- the verified-answer cache
def test_a_verified_answer_is_reused(stubs):
    calls, _ = stubs
    first, _, _ = run("what is the waiting period")
    second, trace, _ = run("what is the waiting period")
    assert calls["generate"] == 1 and calls["grounded"] == 1       # the second answer cost neither
    assert second["turn"].from_cache and second["turn"].text == first["turn"].text
    assert second["problem"] is None


def test_cache_is_not_used_for_personal_questions(stubs):
    calls, _ = stubs
    run("my income is 12 lakh, what is the waiting period")
    run("my income is 12 lakh, what is the waiting period")
    assert calls["generate"] == 2 and len(cache.ANSWER_CACHE) == 0


def test_cache_is_not_used_while_an_analysis_is_active(stubs):
    calls, _ = stubs

    class Flow:
        active, asking = True, "age"

        async def handle(self, *a, **k):
            return None
    s = FakeSession()
    s.flow = Flow()
    run("what is a waiting period", s)
    assert len(cache.ANSWER_CACHE) == 0


def test_a_blocked_answer_is_never_cached(stubs, monkeypatch):
    calls, _ = stubs

    async def not_grounded(*a, **k):
        return False
    monkeypatch.setattr(g.guardrails, "is_grounded", not_grounded)
    result, _, _ = run("what is the waiting period")
    assert result["problem"] == "unsupported_claim" and len(cache.ANSWER_CACHE) == 0


def test_editing_a_clause_invalidates_the_cached_answer(stubs):
    calls, state = stubs
    run("what is the waiting period")
    state["hits"] = [{**HIT, "sha256": "bbb"}]    # the document changed
    again, _, _ = run("what is the waiting period")
    assert calls["generate"] == 2 and not again["turn"].from_cache


def test_cache_can_be_switched_off(stubs, monkeypatch):
    calls, _ = stubs
    monkeypatch.setattr(config, "APP_CACHE_ENABLED", False)
    run("what is the waiting period")
    run("what is the waiting period")
    assert calls["generate"] == 2


def test_graph_records_node_timings_and_cache_use(stubs):
    run("what is the waiting period")
    _, trace, _ = run("what is the waiting period")
    names = [s["name"] for s in trace.steps if s["step"] == "node"]
    assert names == ["continue_active", "classify", "insurance_rag", "guard"]
    assert any(s["step"] == "cache" and s["layer"] == "verified_answers" and s["hit"] for s in trace.steps)


# ---------------------------------------------------------------- the stores themselves
def test_entries_expire():
    store = cache.TTLStore(ttl=0, max_entries=10)
    store.set("k", "v")
    time.sleep(0.01)
    assert store.get("k") is None


def test_oldest_entries_are_evicted_first():
    store = cache.TTLStore(ttl=100, max_entries=2)
    store.set("a", 1), store.set("b", 2), store.get("a"), store.set("c", 3)
    assert store.get("b") is None and store.get("a") == 1 and store.get("c") == 3


def test_hit_rate_is_counted():
    store = cache.TTLStore(ttl=100, max_entries=10)
    store.set("a", 1)
    store.get("a"), store.get("zzz")
    assert store.stats()["hit_rate"] == 0.5


def test_nothing_in_the_caches_is_persisted():
    import inspect
    from services import cache as module
    source = inspect.getsource(module)
    assert "sqlite" not in source and "open(" not in source and "pickle" not in source


# ---------------------------------------------------------------- prompts built for prefix caching
def test_generation_prompt_starts_identically_whatever_the_question():
    a = system_prompt("insurance assistant", {"x:1.1": "one"}, "English", BRIEF)
    b = system_prompt("insurance assistant", {"y:9.9": "two"}, "Hindi", DEEP)
    assert a.startswith(CORE) and b.startswith(CORE)
    shared = os.path.commonprefix([a, b])
    # variable text (language, depth, example tag, documents) only comes after the fixed role line
    assert len(shared) > len(CORE) and "Documents (the clauses" not in shared and "x:1.1" not in shared


def test_classifier_prompt_is_one_fixed_text_and_long_enough_to_cache():
    from orchestrator.intent import PROMPT
    one = PROMPT.format_messages(system=CLASSIFIER_SYSTEM, previous="none", in_flow="no", asking="nothing", message="hello")
    two = PROMPT.format_messages(system=CLASSIFIER_SYSTEM, previous="loan_explain", in_flow="yes", asking="age", message="34")
    assert one[0].content == two[0].content == CLASSIFIER_SYSTEM      # everything that varies is in the user message
    assert len(CLASSIFIER_SYSTEM) > 4000                               # roughly 1,000+ tokens: enough for Sarvam to cache


def test_classifier_prompt_has_no_contradictory_duplicate_intents():
    for intent in INTENTS:
        assert CLASSIFIER_SYSTEM.count(f"\n{intent}\n") == 1, intent   # each intent defined exactly once


def test_a_greeting_does_not_become_the_previous_question(stubs):
    calls, _ = stubs
    s = FakeSession()
    s.history = [{"role": "user", "content": "hello", "intent": "greeting"}]
    run("what is the waiting period", s)
    again, _, _ = run("what is the waiting period", FakeSession())   # a different person, no history
    assert again["turn"].from_cache and calls["generate"] == 1
