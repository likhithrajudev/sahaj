"""Reply guardrails: no advice (except engine-built recommendations), no invented terms, every claim traceable.

check_reply() is deterministic and fails closed: when in doubt the reply is blocked and
replaced with a fallback (and, repeatedly, a human handoff). Known limits: the advice
patterns cover English and Hindi phrasing only, and numbers written as words
("thirty days") are not checked. Add an LLM judge for those later.
"""
import asyncio
import re
from typing import Dict, List, Optional

from trust.pii import normalise_digits

CITE = re.compile(r"\[([\w.\-]+:[\w.\-]+)\]")
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
# Recommending wording. Allowed only when the engine produced the facts (see check_reply).
ADVICE = [re.compile(p, re.I) for p in (
    r"\bI (would )?(recommend|suggest|advise)\b",
    r"\bbest (plan|policy|loan|option)s? for you\b",
    r"(सलाह|सुझाव) (देता|देती|दूंगा|दूंगी)",
)]
# Directive or pressure wording. Never allowed, even when recommending.
PRESSURE = [re.compile(p, re.I) for p in (
    r"\byou (should|must|need to|have to) (buy|take|choose|get|invest|opt|go for|purchase)\b",
    r"\b(hurry|act now|don'?t miss|limited[- ]time|last chance)\b",
    r"\bguarantee[sd]?\b",
    r"आपको .{0,40}(ले|खरीद|चुन)(ना|नी) (चाहिए|होगा|पड़ेगा)",
)]

FALLBACKS = {
    "hi-IN": "मैं इसकी पुष्टि नहीं कर पा रहा हूँ। क्या आप चाहेंगे कि मैं आपको किसी इंसान से जोड़ दूँ?",
    "en-IN": "I can't confirm that from the documents I have. Would you like me to connect you to a person?",
}


def fallback(language_code: str) -> str:
    return FALLBACKS.get(language_code, FALLBACKS["en-IN"])


def citations(reply: str) -> List[str]:
    return list(dict.fromkeys(CITE.findall(reply)))


def strip_citations(reply: str) -> str:
    return re.sub(r"\s*\[[\w.\-]+:[\w.\-]+\]", "", reply)


GROUNDED = """You are a strict fact-checker for a regulated insurance and lending assistant.
Read the SOURCES and the REPLY. Answer YES if every factual statement in the REPLY is written in the SOURCES. The
REPLY may use different words or another language, and may leave things out. Answer NO if the REPLY adds any
condition, exception, reason, implication or detail that is not in the SOURCES. Offers to connect the user to a
person, refusals to give advice, and statements that information is not available count as YES.
Answer with one word: YES or NO.

SOURCES:
{sources}

REPLY:
{reply}"""

ON_POINT = """Read the QUESTION and the REPLY. Answer YES if the REPLY responds to the QUESTION, or says the information is
not available. Answer NO if the REPLY is mainly about something else, for example it recites a clause on a different
topic instead of answering. Answer with one word: YES or NO.

QUESTION:
{question}

REPLY:
{reply}"""


async def _yes(prompt: str) -> bool:
    from services.chat import chat  # imported here so the pure checks above need no network

    verdict = await chat([{"role": "system", "content": prompt}, {"role": "user", "content": "Answer now."}], purpose="fact_check")
    return verdict.strip().upper().startswith("YES")  # fails closed: anything but a clear YES blocks


async def is_grounded(reply: str, sources: Dict[str, str], question: str, detailed: bool = False) -> bool:
    """Model checks for what the deterministic one can't see: added claims, and true-but-irrelevant answers.

    Two narrow questions, asked in parallel, because one combined prompt was unreliable (it rejected plain refusals
    and verbatim quotes). A detailed answer may cover several clauses, so only the first question applies to it."""
    cited = citations(reply) or list(sources)
    evidence = "\n\n".join(sources[c] for c in cited if c in sources)
    plain = strip_citations(reply)
    checks = [_yes(GROUNDED.format(sources=evidence, reply=plain))]
    if not detailed:
        checks.append(_yes(ON_POINT.format(question=question, reply=plain)))
    return all(await asyncio.gather(*checks))


def check_reply(reply: str, sources: Dict[str, str], allow_recommendation: bool = False) -> Optional[str]:
    """None if the reply is acceptable, otherwise the reason it was blocked.

    `allow_recommendation` is True only for text built from the recommendation engine's facts: it may then say
    which plan ranks highest and why, but still may not tell the person what they must do.
    """
    if any(p.search(reply) for p in PRESSURE):
        return "pressure"
    if not allow_recommendation and any(p.search(reply) for p in ADVICE):
        return "advice"

    cited = citations(reply)
    if any(c not in sources for c in cited):
        return "unknown_citation"

    evidence = normalise_digits(" ".join(sources[c] for c in cited)).replace(",", "")
    claimed = normalise_digits(CITE.sub("", reply)).replace(",", "")
    for number in NUMBER.findall(claimed):
        if not re.search(rf"(?<![\d.]){re.escape(number)}(?!\d)", evidence):
            return "ungrounded_number"
    return None
