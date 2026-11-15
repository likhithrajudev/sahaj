"""Follow-up questions a person can tap, and the trust summary shown with a reply. Both are fixed and deterministic:
suggestions are written ahead of time for things Sahaj can really do, so tapping one always leads somewhere, and the
trust summary only reports what the checks actually did."""
from typing import List, Optional

SUGGESTIONS = {
    "insurance_explain": {
        "en-IN": ["What are the hidden terms?", "Which plan suits me?", "What is not covered?"],
        "hi-IN": ["इसमें छुपी शर्तें क्या हैं?", "मेरे लिए कौन सा प्लान ठीक है?", "क्या कवर नहीं है?"]},
    "insurance_fine_print": {
        "en-IN": ["How do I avoid a claim cut?", "What is the waiting period?", "Talk to a person"],
        "hi-IN": ["क्लेम कटने से कैसे बचें?", "प्रतीक्षा अवधि क्या है?", "किसी इंसान से बात करें"]},
    "loan_fine_print": {
        "en-IN": ["What will I pay in total?", "Can I prepay without a charge?", "Talk to a person"],
        "hi-IN": ["कुल कितना चुकाना होगा?", "क्या बिना शुल्क पहले चुका सकता हूँ?", "किसी इंसान से बात करें"]},
    "insurance_advice": {
        "en-IN": ["Compare these plans", "What is the waiting period?", "Talk to a person"],
        "hi-IN": ["इन प्लान की तुलना करें", "प्रतीक्षा अवधि क्या है?", "किसी इंसान से बात करें"]},
    "insurance_compare": {
        "en-IN": ["Which one is better for me?", "What is the waiting period?", "What is not covered?"],
        "hi-IN": ["मेरे लिए कौन सा बेहतर है?", "प्रतीक्षा अवधि क्या है?", "क्या कवर नहीं है?"]},
    "loan_explain": {
        "en-IN": ["What are the hidden charges?", "Work out my EMI", "Can I prepay the loan?"],
        "hi-IN": ["छुपे हुए शुल्क क्या हैं?", "मेरी EMI निकालें", "क्या मैं लोन पहले चुका सकता हूँ?"]},
    "loan_guidance": {
        "en-IN": ["Work out my EMI", "What happens if I miss a payment?", "Talk to a person"],
        "hi-IN": ["मेरी EMI निकालें", "किस्त चूकने पर क्या होता है?", "किसी इंसान से बात करें"]},
    "loan_calculator": {
        "en-IN": ["What if I prepay some amount?", "What are the charges?", "Explain my loan offer"],
        "hi-IN": ["कुछ रकम पहले चुकाऊँ तो?", "शुल्क क्या हैं?", "मेरा लोन ऑफर समझाएँ"]},
    "greeting": {
        "en-IN": ["Explain health insurance", "Work out a loan EMI", "Which insurance suits me?"],
        "hi-IN": ["हेल्थ इंश्योरेंस समझाएँ", "लोन की EMI निकालें", "मेरे लिए कौन सा इंश्योरेंस ठीक है?"]},
}
DEFAULT = "greeting"


def for_intent(intent: Optional[str], lang: str, kind: str, handed_off: bool) -> List[str]:
    """Up to three tappable follow-ups. None while the assistant is itself asking a question (the answer is the
    next message), and none once a person has taken over."""
    if handed_off or kind in ("ask", "confirm", "command"):
        return []
    table = SUGGESTIONS.get(intent or DEFAULT, SUGGESTIONS[DEFAULT])
    return table.get(lang) or table["en-IN"]


def verification(*, blocked: bool, from_cache: bool, prechecked: bool, judged: bool, sources: int, kind: str) -> dict:
    """How this reply was checked, for a trust badge. `level`: verified (every statement tied to a source and
    fact-checked), engine (built from the recommendation or calculation engine's own figures), checked (screened by
    the guardrails, nothing to cite) or blocked (the draft failed the checks and a safe reply was shown instead)."""
    if blocked:
        level = "blocked"
    elif kind == "command":
        level = "checked"
    elif kind in ("recommendation", "compare") or (prechecked and not from_cache and not sources):
        level = "engine"
    elif sources and (judged or from_cache):
        level = "verified"
    else:
        level = "checked"
    return {"level": level, "sources": sources, "from_cache": from_cache,
            "checks": ["guardrails"] + (["fact_check"] if judged or from_cache else [])}
