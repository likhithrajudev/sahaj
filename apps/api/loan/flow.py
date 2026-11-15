"""The loan calculator conversation: gather the numbers, then let code work out the answer.

Like the advisory flow, the model only reads what the person said and phrases the reply. Each value it reads must be
backed by the person's own words and re-parse to the same number, and the arithmetic is loan/calc.py.
"""
import json
import re
from typing import Any, Dict, Optional

from advisory.catalogue import money
from advisory.extract import phrase
from advisory.profile import bare_answer, parse_int, parse_money
from agents.base import generate
from loan import calc
from orchestrator.turn import Turn
from services.llm import chat

ROLE = "loan calculator assistant"
SAY = "State the results in separate short sentences, one figure each. Add no comment of your own."

EXTRACT = """You read the numbers a person gave for a loan calculation. Return ONLY a JSON object. Each key is a field
from the list; each value is {{"value": ..., "evidence": "..."}} where evidence is the exact words from the message
that state it. Include a field ONLY if the message clearly states it. Never guess.

Fields:
- principal: the loan amount in rupees, whole number ("5 lakh" = 500000). For a prepayment question this is the amount still owed.
- annual_rate_percent: the yearly interest rate as a number (11 for "11 percent").
- tenure_months: the repayment period in MONTHS ("3 years" = 36). For a prepayment question, the time still left.
- prepay_amount: an extra part-payment to be made now, in rupees.
- mode: "reduce_tenure" or "reduce_emi", only if they say which they want.

Message: {message}"""

RATE_WORDS = re.compile(r"%|percent|per cent|प्रतिशत|फीसदी|फ़ीसदी|pc\b", re.I)
YEAR = re.compile(r"year|yr|साल|वर्ष", re.I)
MONTH = re.compile(r"month|महीन|मास", re.I)
LIMITS = {"principal": (1_000, 100 * 10_000_000), "annual_rate_percent": (0.1, 60), "tenure_months": (1, 480),
          "prepay_amount": (1, 100 * 10_000_000)}
ASK = {"principal": "the loan amount (or, for a part-payment, the amount still owed)",
       "annual_rate_percent": "the yearly interest rate",
       "tenure_months": "how long the loan runs (or, for a part-payment, how much time is left)",
       "prepay_amount": "how much extra they want to pay now"}
STUCK = {"en-IN": "I'm having trouble with those numbers. Let me connect you to a person who can help.",
         "hi-IN": "मुझे इन आँकड़ों में दिक्कत हो रही है। मैं आपको किसी ऐसे व्यक्ति से जोड़ता हूँ जो मदद कर सके।"}
MAX_MISSES = 3


def _number(text: str) -> Optional[float]:
    match = re.search(r"\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def verified(name: str, item: Any, text: str) -> Optional[Any]:
    """The value if the person's own words support it."""
    if not isinstance(item, dict) or "value" not in item:
        return None
    value, evidence = item["value"], str(item.get("evidence", ""))
    if not evidence.strip() or re.sub(r"\s+", " ", evidence.lower()) not in re.sub(r"\s+", " ", text.lower()):
        return None
    if name == "mode":
        return value if value in ("reduce_tenure", "reduce_emi") else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if name in ("principal", "prepay_amount"):
        return value if parse_money(evidence) == int(value) else None
    if name == "annual_rate_percent":
        n = _number(evidence)
        return value if n is not None and RATE_WORDS.search(evidence) and abs(n - value) < 1e-9 else None
    if name == "tenure_months":
        n = _number(evidence) or parse_int(evidence)
        if n is None:
            return None
        factor = 12 if YEAR.search(evidence) else 1 if MONTH.search(evidence) else None
        return value if factor and abs(n * factor - value) < 1e-9 else None
    return None


async def extract(text: str) -> Dict[str, Any]:
    raw = await chat([{"role": "system", "content": EXTRACT.format(message=text)},
                      {"role": "user", "content": "Return the JSON now."}], purpose="extract")
    try:
        data = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    except ValueError:
        return {}
    out = {}
    for name in (*LIMITS, "mode"):
        if isinstance(data, dict) and name in data:
            value = verified(name, data[name], text)
            if value is not None and (name == "mode" or LIMITS[name][0] <= value <= LIMITS[name][1]):
                out[name] = value
    return out


class LoanCalc:
    def __init__(self):
        self.values: Dict[str, Any] = {}
        self.active = True
        self.misses = 0

    def missing(self):
        need = ["principal", "annual_rate_percent", "tenure_months"] + (["prepay_amount"] if "prepay_amount" in self.values else [])
        return [n for n in need if n not in self.values]

    async def handle(self, text: str, lang_code: str, language: str, force: bool = False) -> Optional[Turn]:
        """React to a message. With force=False, returns None if it gave no numbers (so it can be classified as
        something else); with force=True it always answers."""
        extracted = await extract(text)
        self.values.update(extracted)
        if not extracted and not force:
            return None
        self.misses = 0 if extracted else self.misses + 1
        if self.misses >= MAX_MISSES:
            self.active = False
            return Turn(text=STUCK.get(lang_code, STUCK["en-IN"]), kind="ask", agent="loan", judge=False,
                        handoff_after=True, sensitive_input=bool(extracted))
        missing = self.missing()
        if missing:
            wanted = "; ".join(ASK[n] for n in missing)
            ask = await phrase(f"ask the user for {wanted}", language)
            return Turn(text=ask, kind="ask", agent="loan", judge=False, sensitive_input=bool(extracted))
        return await self._result(language)

    async def _result(self, language: str) -> Turn:
        v = self.values
        self.active = False
        try:
            if "prepay_amount" in v:
                mode = v.get("mode", "reduce_tenure")
                r = calc.prepayment(v["principal"], v["annual_rate_percent"], int(v["tenure_months"]), v["prepay_amount"], mode)
                fact = (f"For {money(v['principal'])} still owed at {v['annual_rate_percent']:g} percent a year with "
                        f"{int(v['tenure_months'])} months left, paying an extra {money(v['prepay_amount'])} now and "
                        + ("keeping the same monthly instalment" if mode == "reduce_tenure" else "keeping the same tenure")
                        + f": the instalment goes from {money(r['emi_before'])} to {money(r['emi_after'])}; the loan ends in "
                        f"{r['months_after']} months instead of {r['months_before']}; total interest from the "
                        f"{money(r['interest_before'])} to {money(r['interest_after'])}, a saving of {money(r['interest_saved'])}. "
                        "This uses the reducing-balance method; a lender's own figure can differ slightly.")
                key, card = "calc:prepay", {"type": "loan_calculation", "kind": "prepayment", "inputs": dict(v), "result": r}
            else:
                r = calc.summary(v["principal"], v["annual_rate_percent"], int(v["tenure_months"]))
                fact = (f"For a loan of {money(v['principal'])} at {v['annual_rate_percent']:g} percent a year over "
                        f"{int(v['tenure_months'])} months: the monthly instalment (EMI) is {money(r['emi'])}, the total "
                        f"repayment is {money(r['total_payment'])} and the total interest is {money(r['total_interest'])}. "
                        "This uses the reducing-balance method; a lender's own figure can differ slightly.")
                key, card = "calc:emi", {"type": "loan_calculation", "kind": "emi", "inputs": dict(v), "result": r}
        except ValueError as problem:
            ask = await phrase(f"tell the user that these numbers do not work ({problem}) and ask them to check them", language)
            self.active, self.values = True, {}
            return Turn(text=ask, kind="ask", agent="loan", judge=False, sensitive_input=True)
        sources = {key: fact}
        text = await generate(ROLE, sources, "Tell me the result.", None, language, SAY)
        return Turn(text=text, kind="calc", agent="loan", sources=sources, detailed=True, asked="State the calculation result.",
                    card=card, sensitive_input=True)
