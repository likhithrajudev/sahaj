"""The orchestrator as a LangGraph graph.

    START -> continue_active --(a reply to the active conversation)--> guard -> END
                  |
                  +--(otherwise)--> classify --> [clarify | insurance_rag | advice | compare | loan_rag | calculator |
                                                  decline | greeting | handoff] --> guard -> END

The graph only decides and produces a `Turn`. Sending it, speaking it and keeping the history stay in the Session,
which is passed in through the config. There is deliberately no checkpointer: a checkpoint would persist what the
person told us, and nothing personal may be stored.
"""
import functools
import time
from typing import Annotated, Any, Dict, List, Optional, TypedDict
import operator

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

import config
from advisory import catalogue, compare as comparison
from advisory.extract import phrase
from advisory.flow import AdviceFlow
from agents import AGENTS
from agents.base import BRIEF, COMPARE, DEEP, generate
from loan.flow import LoanCalc
from orchestrator.intent import Intent, classify as classify_intent
from orchestrator.turn import Turn
from rag.loader import concept_docs, product_docs
from rag.retrieve import retrieve
from services import cache, telemetry
from trust import consent, guardrails

NEED_CONSENT = {"en-IN": "Before I ask about your details, I need your permission. Please confirm on your screen.",
                "hi-IN": "आपकी जानकारी के बारे में पूछने से पहले मुझे आपकी अनुमति चाहिए। कृपया अपनी स्क्रीन पर पुष्टि करें।"}
ASK_FALLBACK = {"en-IN": "Sorry, could you say that again?", "hi-IN": "माफ़ कीजिए, क्या आप दोबारा बता सकते हैं?"}
DECLINE = {
    "loan_rates_comparison": {
        "en-IN": "Only the lender can decide whether to approve a loan. I can look up published lender terms, explain your offer, or work out an EMI.",
        "hi-IN": "लोन मंज़ूर करने का फैसला केवल ऋणदाता कर सकता है। मैं ऋणदाताओं की प्रकाशित शर्तें खोज सकता हूँ, आपके ऑफ़र को समझा सकता हूँ या ईएमआई निकाल सकता हूँ।"},
    "out_of_scope": {
        "en-IN": "I can only help with insurance and loans. I can explain policies, look up current insurance information, explain a loan offer or work out an EMI, or connect you to a person.",
        "hi-IN": "मैं केवल बीमा और लोन में मदद कर सकता हूँ। मैं पॉलिसी समझा सकता हूँ, बीमा की मौजूदा जानकारी खोज सकता हूँ, लोन ऑफ़र समझा सकता हूँ या ईएमआई निकाल सकता हूँ, या आपको किसी व्यक्ति से जोड़ सकता हूँ।"},
}
DECLINE_INSTRUCTION = {
    "loan_rates_comparison": "say only the lender decides loan approval, and offer to search published lender terms, explain their loan offer or work out an EMI",
    "out_of_scope": "tell the user you can only help with insurance and loans, and offer to explain policies, look up current insurance information, explain a loan offer, work out an EMI or connect them to a person",
}
ROUTES = {
    "insurance_explain": "insurance_rag", "insurance_advice": "advice", "insurance_compare": "compare",
    "loan_explain": "loan_rag", "loan_guidance": "loan_rag", "loan_calculator": "calculator",
    "loan_rates_comparison": "decline", "out_of_scope": "decline", "human_handoff": "handoff", "greeting": "greeting",
    "insurance_fine_print": "fine_print", "loan_fine_print": "fine_print",
    "insurance_web_search": "insurance_web_search",
    "loan_web_search": "loan_web_search",
    "insurance_purchase": "financial_action", "loan_application": "financial_action", "credit_check": "financial_action",
    "financial_overview": "financial_overview",
}


class State(TypedDict, total=False):
    text: str
    lang: str
    language: str
    intent: Intent
    turn: Optional[Turn]
    problem: Optional[str]
    handoff: Optional[str]
    path: Annotated[List[str], operator.add]


def _ctx(run: RunnableConfig):
    return run["configurable"]["session"], run["configurable"]["trace"]


def node(fn):
    """Time each node and record it, so the workflow report can show where a turn's time went."""
    @functools.wraps(fn)
    async def wrapper(state: State, config: RunnableConfig):
        _, trace = _ctx(config)
        started = time.perf_counter()
        update = await fn(state, config) or {}
        trace.add("node", name=fn.__name__, ms=round((time.perf_counter() - started) * 1000, 1))
        return {**update, "path": [fn.__name__]}
    return wrapper


def _looks_personal(*texts: Optional[str]) -> bool:
    return any(t and (any(c.isdigit() for c in t) or "[" in t) for t in texts)


def _pick(table: Dict[str, str], lang: str) -> str:
    return table.get(lang, table["en-IN"])


NO_CONTEXT = {"greeting", "out_of_scope", "loan_rates_comparison", "human_handoff"}  # nothing a follow-up could build on


def _previous(session) -> Optional[str]:
    """The user's last substantive question: what a short follow-up ("and the maternity cover?") refers to."""
    return next((m["content"] for m in reversed(session.history)
                 if m["role"] == "user" and m.get("intent") not in NO_CONTEXT), None)


# ---------------------------------------------------------------- entry: a conversation already under way
@node
async def continue_active(state: State, config: RunnableConfig):
    """A reply mid-analysis is usually an answer to the question just asked, so the active conversation reads it first."""
    session, trace = _ctx(config)
    turn, intent = None, None
    inventory_flow = getattr(session, "inventory_flow", None)
    if inventory_flow and inventory_flow.active:
        turn = await inventory_flow.handle(state["text"], state["lang"])
        if not inventory_flow.active:
            session.inventory_flow = None
        return {"turn": turn}
    if session.flow and session.flow.active:
        if catalogue.is_sample():
            goal = session.flow.profile.get("goal")
            session.flow = None
            turn = await _web_search_turn(state, config, "insurance", _insurance_products_query(goal))
        else:
            turn = await session.flow.handle(state["text"], state["lang"], state["language"], session._can_advise(), trace)
        intent = "insurance_advice"
    if turn is None and session.calc and session.calc.active:
        turn = await session.calc.handle(state["text"], state["lang"], state["language"])
        intent = "loan_calculator"
    if turn is None:
        return {}
    trace.add("intent", intent=intent, confidence=1.0, detail="brief", reason="answer to the active conversation", source="context")
    session.last_intent = intent
    return {"turn": turn}


def after_continue(state: State) -> str:
    return "guard" if state.get("turn") else "classify"


# ---------------------------------------------------------------- classify and route
@node
async def classify(state: State, config: RunnableConfig):
    session, trace = _ctx(config)
    in_flow = bool((session.flow and session.flow.active) or (session.calc and session.calc.active))
    asking = session.flow.asking if session.flow and session.flow.active else None
    intent = await classify_intent(state["text"], session.last_intent, in_flow, asking)
    trace.add("intent", intent=intent.intent, confidence=round(intent.confidence, 2), detail=intent.detail,
              reason=intent.reason, source="classifier")
    return {"intent": intent}


def route(state: State) -> str:
    intent = state["intent"]
    if intent.confidence < config.INTENT_MIN_CONFIDENCE and intent.intent != "human_handoff":
        return "clarify"  # not sure what they want: ask, don't guess
    target = ROUTES[intent.intent]
    if target == "compare" and comparison.is_concept_question(state["text"]):
        return "insurance_rag"  # "difference between term and whole life" names kinds of insurance, not plans
    return target


# ---------------------------------------------------------------- handlers
async def _document_user(session) -> Optional[str]:
    """The user whose own documents may be searched, or None: they must have allowed it and have indexed something."""
    user = getattr(session, "user", None)
    if user is None or not consent.is_active(user.subject, "document_analysis"):
        return None
    try:
        from storage import index
        return user.id if await index.has_documents(user.id) else None
    except Exception:  # no database: answer from the built-in knowledge base alone
        return None


async def _rag_turn(session, trace, state: State, domain: str, agent: str, scope: Optional[List[str]]) -> Turn:
    """Retrieve, then answer from the clauses. A verified answer to the same question over the same clauses is reused."""
    text, language, deep = state["text"], state["language"], state["intent"].deep
    # Search with the classifier's English rendering of the question: the clauses are English, and cross-language
    # similarity is weak (a Hindi question scored 0.1-0.2 against the right English clause, 0.6-0.7 once in English).
    query = (state["intent"].search or "").strip() or text
    hits = await retrieve(domain, query, session.history, deep, scope, user_id=await _document_user(session))
    sources = {h["key"]: h["text"] for h in hits}
    trace.add("retrieval", scoped_to=scope, clauses=[
        {"key": h["key"], "similarity": round(h["similarity"], 4), "sha256": h["sha256"]} for h in hits])
    if not hits and state["intent"].intent in ("insurance_explain", "loan_guidance"):
        trace.add("knowledge_fallback", provider="firecrawl", domain=domain)
        return await _web_search_turn(state, config, domain)

    previous = _previous(session)
    in_flow = bool(session.flow and session.flow.active)
    # A reply shaped by someone's memory is theirs alone, so it neither reads from nor goes into the shared cache.
    cacheable = (config.APP_CACHE_ENABLED and not in_flow and not _looks_personal(text, previous) and bool(sources)
                 and not session.memory and not any(h.get("personal") for h in hits))
    import tenancy
    key = (tenancy.get(), domain, " ".join(text.lower().split()), (previous or "").lower(), language, deep,
           tuple(sorted((h["key"], h["sha256"]) for h in hits))) if cacheable else None  # clause hashes: edits invalidate

    if key is not None:
        cached = cache.ANSWER_CACHE.get(key)
        telemetry.record_cache("verified_answers", cached is not None)
        if cached is not None:
            return Turn(text=cached["text"], kind="answer", agent=agent, sources=cached["sources"], prechecked=True,
                        from_cache=True)

    reply = await generate(AGENTS[agent].role, sources, text, previous, language, DEEP if deep else BRIEF,
                           memory=session.memory)
    return Turn(text=session.vault.mask(reply), kind="answer", agent=agent, sources=sources, judge=bool(sources),
                detailed=deep, asked=text, cache_key=key)


@node
async def insurance_rag(state: State, config: RunnableConfig):
    session, trace = _ctx(config)
    # A named plan, else the plans just shown, else only the general explanations. An unnamed question must never be
    # answered with one particular plan's figures as if they were general.
    named_plans = catalogue.find_in_text(state["text"])
    if catalogue.is_sample() and named_plans:
        return {"turn": await _web_search_turn(state, config, "insurance")}
    plans = (named_plans or session.focus) if not catalogue.is_sample() else []
    session.agent = "insurance"
    return {"turn": await _rag_turn(session, trace, state, "insurance", "insurance", plans + concept_docs("insurance"))}


@node
async def loan_rag(state: State, config: RunnableConfig):
    session, trace = _ctx(config)
    # Questions about the user's own offer use the lender's documents; general questions only the general explanations.
    scope = concept_docs("loan") if state["intent"].intent == "loan_guidance" else None
    session.agent = "loan"
    return {"turn": await _rag_turn(session, trace, state, "loan", "loan", scope)}


@node
async def advice(state: State, config: RunnableConfig):
    session, trace = _ctx(config)
    lang = state["lang"]
    if catalogue.is_sample():
        query = _insurance_products_query(state["text"])
        trace.add("insurance_catalogue", status="sample_bypassed", provider="firecrawl")
        return {"turn": await _web_search_turn(state, config, "insurance", query)}
    if not session._can_advise():  # personal details are needed, so ask permission first
        session.pending = (state["text"], lang)
        return {"turn": Turn(_pick(NEED_CONSENT, lang), kind="ask", agent="advice", judge=False,
                             request_consent="needs_analysis")}
    session.flow = session.flow or AdviceFlow(session.id)
    session.agent = "advice"
    return {"turn": await session.flow.handle(state["text"], lang, state["language"], True, trace, force=True)}


@node
async def compare(state: State, config: RunnableConfig):
    session, _ = _ctx(config)
    lang, language, text = state["lang"], state["language"], state["text"]
    if catalogue.is_sample():
        query = (state["intent"].search or "").strip() or text
        return {"turn": await _web_search_turn(state, config, "insurance", query)}
    result = comparison.compare(text, session.flow.profile if session.flow else None)
    session.agent = "insurance"
    if result is None:
        ask = await phrase("ask which plans they want to compare, or whether they mean health, term or whole life "
                           "insurance", language)
        return {"turn": Turn(text=ask, kind="ask", agent="insurance", judge=False, fallback=_pick(ASK_FALLBACK, lang))}
    reply = await generate("insurance assistant", result["facts"], text, _previous(session), language, COMPARE)
    return {"turn": Turn(text=session.vault.mask(reply), kind="compare", agent="insurance", sources=result["facts"],
                         detailed=True, asked=text, card=result["card"])}


FINE_PRINT_SOURCES = 8    # clauses given to the model: enough for the costliest catches; more made it mix up the tags


@node
async def fine_print(state: State, config: RunnableConfig):
    """The hidden terms and costs, for insurance or a loan. Each topic on the checklist (procedural memory) is looked up
    in the person's own documents, the plan or offer being discussed, and the general explanations; the answer states
    what applies, cited, most costly first. The checklist's topics never change between people, so their embeddings
    come from the cache after the first time: the lookups cost no API calls."""
    import config as settings   # `config` is this node's LangGraph run config, not the settings module
    from memory import procedural
    from rag import store
    from rag.embeddings import embed_queries
    session, trace = _ctx(config)
    domain = "loan" if state["intent"].intent == "loan_fine_print" else "insurance"
    session.agent = domain
    named_sample = domain == "insurance" and catalogue.is_sample() and catalogue.find_in_text(state["text"])
    if named_sample:
        return {"turn": await _web_search_turn(state, config, "insurance")}
    topics = [t.strip() for t in procedural.text(f"fine_print.checklist.{domain}").splitlines() if t.strip()]
    named = ((catalogue.find_in_text(state["text"]) or session.focus) if not catalogue.is_sample() else []) \
        if domain == "insurance" else product_docs("loan")
    user_id = await _document_user(session)
    best: Dict[str, dict] = {}
    per_topic = []
    for topic, vector in zip(topics, await embed_queries(topics)):
        found = await store.search(domain, vector, 1, concept_docs(domain))
        if named:
            found += await store.search(domain, vector, 1, named)
        if user_id:
            from storage import index
            found += await index.search(user_id, vector, 1)
        kept = [h for h in found if h["similarity"] >= settings.RETRIEVAL_MIN_SIMILARITY]
        per_topic.append({"topic": topic, "sources": [h["key"] for h in kept]})
        for h in kept:
            if h["similarity"] > best.get(h["key"], {}).get("similarity", 0):
                best[h["key"]] = h
    # The person's own and the product's clauses before the general ones, then by relevance.
    ranked = sorted(best.values(), key=lambda h: (h["key"].split(":")[0].startswith("concepts-"), -h["similarity"]))[:FINE_PRINT_SOURCES]
    sources = {h["key"]: h["text"] for h in ranked}
    trace.add("retrieval", scoped_to=["fine_print", domain], clauses=[
        {"key": h["key"], "similarity": round(h["similarity"], 4), "sha256": h.get("sha256", "")} for h in ranked])
    reply = await generate(AGENTS[domain].role, sources, state["text"], None, state["language"],
                           procedural.text("answer.fine_print"), memory=session.memory)
    reply, repaired = guardrails.repair_citations(reply, sources)   # a statement tagged with a neighbouring clause
    if repaired:
        trace.add("citations_repaired", count=repaired)
    card = {"domain": domain, "topics": [{**t, "sources": [k for k in t["sources"] if k in sources]} for t in per_topic]}
    return {"turn": Turn(text=session.vault.mask(reply), kind="fine_print", agent=domain, sources=sources, judge=bool(sources),
                         detailed=True, asked=state["text"], card=card)}


def _insurance_products_query(value: Optional[str]) -> str:
    goal = value if value in ("health", "term", "whole_life") else comparison.category_in(value or "")
    product = {"health": "health", "term": "term life", "whole_life": "whole life"}.get(goal, "")
    return f"current {product + ' ' if product else ''}insurance plans India official insurer product features"


async def _web_search_turn(state: State, run_config: RunnableConfig, domain: str,
                           query_override: Optional[str] = None) -> Turn:
    from services.firecrawl import FirecrawlError, FirecrawlUnavailable, search_web, sources_for
    session, trace = _ctx(run_config)
    agent = "loan" if domain == "loan" else "insurance"
    session.agent = agent
    intent = state.get("intent")
    query = query_override or ((intent.search or "").strip() if intent else "") or state["text"]
    try:
        result = await search_web(query, domain)
    except (FirecrawlError, FirecrawlUnavailable):
        trace.add("web_search", provider="firecrawl", domain=domain, status="unavailable")
        reply = await phrase("Say that current public web search is unavailable right now and ask the user to try again later",
                             state["language"])
        return Turn(text=reply, kind="answer", agent=agent, judge=False)
    sources = sources_for(result["results"])
    trace.add("web_search", provider="firecrawl", domain=domain, status="ok", query=result["query"], results=len(sources))
    if not sources:
        reply = await phrase("Say that no useful current pages were found and ask the user to narrow the search", state["language"])
        return Turn(text=reply, kind="answer", agent=agent, judge=False)
    reply = await generate(f"{domain} research assistant", sources, state["text"], _previous(session),
                           state["language"], DEEP if state["intent"].deep else BRIEF,
                           purpose="web_search", memory=session.memory)
    if not guardrails.citations(reply):
        first = next(iter(sources))
        reply = f"I found current {domain} pages about this topic. [{first}]"
    reply, repaired = guardrails.repair_citations(reply, sources)
    if repaired:
        trace.add("citations_repaired", count=repaired)
    card = None
    if domain == "insurance":
        card = {"type": "web_search", "provider": "firecrawl", "query": result["query"],
                "results": [{key: item[key] for key in ("title", "url", "description")} for item in result["results"]]}
    return Turn(text=session.vault.mask(reply), kind="answer", agent=agent, sources=sources,
                judge=True, detailed=bool(intent and intent.deep), asked=state["text"], card=card)


@node
async def insurance_web_search(state: State, config: RunnableConfig):
    return {"turn": await _web_search_turn(state, config, "insurance")}


@node
async def loan_web_search(state: State, config: RunnableConfig):
    return {"turn": await _web_search_turn(state, config, "loan")}


@node
async def financial_action(state: State, config: RunnableConfig):
    from financial import providers
    from trust import consent

    session, trace = _ctx(config)
    intent = state["intent"].intent
    if intent == "insurance_purchase":
        kind, capabilities, endpoints, purpose, agent = (
            "insurance_purchase", {"insurance_quotes", "insurance_purchase"},
            ["/financial/insurance/quotes", "/financial/insurance/purchase"],
            "financial_application", "insurance")
    elif intent == "credit_check":
        kind, capabilities, endpoints, purpose, agent = (
            "credit_check", {"credit_check"}, ["/financial/credit-check"], "credit_bureau", "loan")
    else:
        kind, capabilities, endpoints, purpose, agent = (
            "loan_application", {"credit_check", "loan_offers", "loan_apply"},
            ["/financial/credit-check", "/financial/loan/offers", "/financial/loan/apply"],
            "financial_application", "loan")
    available = [p["id"] for p in providers.capabilities() if capabilities.issubset(set(p["capabilities"]))]
    trace.add("financial_workflow", kind=kind, providers=len(available))
    if not available:
        instruction = (f"say the {kind.replace('_', ' ')} process is not connected to an authorised provider yet; "
                       "do not ask the person to send identity, income or health details; offer to explain the process")
    else:
        instruction = (f"say you can start the {kind.replace('_', ' ')} process through the configured provider; "
                       "explain that the user must review the provider, details and disclosures and explicitly confirm; "
                       "for a credit check, explain that a bureau score does not decide loan approval")
    reply = await phrase(instruction, state["language"])
    card = {"type": "financial_workflow", "action": kind, "providers": available, "endpoints": endpoints,
            "consent": consent.required(purpose), "requires_user_confirmation": True}
    return {"turn": Turn(text=reply, kind="ask", agent=agent, judge=False, card=card)}


@node
async def financial_overview(state: State, config: RunnableConfig):
    session, _ = _ctx(config)
    if not consent.is_active(session.user.subject, "financial_profile"):
        from financial import inventory
        await inventory.forget(session.user.id)
        return {"turn": Turn(text="Please review the financial inventory permission on your screen. Then use /inventory to add your cards and EMIs.",
                              kind="ask", agent="general", judge=False, prechecked=True,
                              request_consent="financial_profile")}
    from financial import inventory
    items = await inventory.list_for(session.user.id)
    total_card_balance = sum(int(item["details"].get("outstanding_balance", 0)) for item in items
                             if item["type"] == "credit_card")
    total_emi = sum(int(item["details"].get("monthly_emi", 0)) for item in items if item["type"] == "loan")
    text = "Here is your saved financial inventory. Use /inventory to add or update details."
    if not items:
        text = "Your saved financial inventory is empty. Use /inventory to add your cards and EMIs."
    return {"turn": Turn(text=text, kind="confirm", agent="general", judge=False, prechecked=True,
                         card={"type": "financial_inventory_summary", "currency": "INR", "items": items,
                               "totals": {"credit_card_outstanding": total_card_balance, "monthly_emi": total_emi}})}


@node
async def calculator(state: State, config: RunnableConfig):
    session, _ = _ctx(config)
    if not (session.calc and session.calc.active):
        session.calc = LoanCalc()
    session.agent = "loan"
    return {"turn": await session.calc.handle(state["text"], state["lang"], state["language"], force=True)}


@node
async def decline(state: State, config: RunnableConfig):
    """Things Sahaj cannot do (bank rate comparison, approval prediction) or does not do (anything else): said honestly
    from fixed text, never improvised by the model, so a joke or an instruction in the message gets no compliance."""
    lang, kind = state["lang"], state["intent"].intent
    text = DECLINE[kind].get(lang) or await phrase(DECLINE_INSTRUCTION[kind], state["language"])
    return {"turn": Turn(text=text, kind="answer", agent="loan" if kind == "loan_rates_comparison" else "general", judge=False)}


@node
async def greeting(state: State, config: RunnableConfig):
    session, _ = _ctx(config)
    reply = await generate(AGENTS["general"].role, {}, state["text"], None, state["language"], BRIEF,
                           memory=session.memory)
    return {"turn": Turn(text=session.vault.mask(reply), kind="answer", agent="general", judge=False)}


@node
async def clarify(state: State, config: RunnableConfig):
    ask = await phrase("ask what they would like help with: insurance, a loan, or something else, and what exactly",
                       state["language"])
    return {"turn": Turn(text=ask, kind="ask", agent="general", judge=False, fallback=_pick(ASK_FALLBACK, state["lang"]))}


@node
async def handoff(state: State, config: RunnableConfig):
    return {"handoff": "user_requested"}


# ---------------------------------------------------------------- the checks every reply passes
@node
async def guard(state: State, config: RunnableConfig):
    """Run the guardrails and fact-checks on the reply, unless it was already verified (a cached answer, or a
    read-back or summary the flow checked itself)."""
    session, trace = _ctx(config)
    turn = state["turn"]
    problem = None if turn.prechecked else guardrails.check_reply(turn.text, turn.sources, turn.allow_recommendation)
    if not problem and not turn.prechecked and turn.sources and turn.judge:
        previous = _previous(session)
        asked = f'{turn.asked or state["text"]} (the user\'s previous question was: "{previous}")' if previous else (turn.asked or state["text"])
        if not await guardrails.is_grounded(turn.text, turn.sources, asked, turn.detailed):
            problem = "unsupported_claim"
    # A read-back repeats the person's details, so it is not recorded; nor is what they said to prompt it.
    trace.add("guardrail", verdict=problem or "pass", agent=turn.agent, kind=turn.kind, from_cache=turn.from_cache,
              reply="[withheld: personal details]" if turn.kind == "confirm" else turn.text)
    if turn.sensitive_input:
        trace.withhold("stt", "transcript")
    if turn.cache_key is not None and not problem and not turn.from_cache:
        cache.ANSWER_CACHE.set(turn.cache_key, {"text": turn.text, "sources": turn.sources})  # only verified answers
    return {"problem": problem}


def build() -> StateGraph:
    graph = StateGraph(State)
    for fn in (continue_active, classify, insurance_rag, advice, compare, loan_rag, calculator, decline,
               greeting, clarify, handoff, guard, fine_print, insurance_web_search, loan_web_search, financial_action,
               financial_overview):
        graph.add_node(fn.__name__, fn)
    graph.add_edge(START, "continue_active")
    graph.add_conditional_edges("continue_active", after_continue, {"guard": "guard", "classify": "classify"})
    graph.add_conditional_edges("classify", route, {name: name for name in set(ROUTES.values()) | {"clarify"}})
    for name in ("insurance_rag", "advice", "compare", "loan_rag", "calculator", "decline", "greeting", "clarify", "fine_print", "insurance_web_search", "loan_web_search", "financial_action", "financial_overview"):
        graph.add_edge(name, "guard")
    graph.add_edge("handoff", END)
    graph.add_edge("guard", END)
    return graph


GRAPH = build().compile()
