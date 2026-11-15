"""What Sahaj must know about a person before it may recommend anything.

Exact values live in session memory only. The audit trail gets `bands()`, ranges that cannot identify anyone.
"""
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from advisory.catalogue import money
from advisory.rules import CRORE, LAKH

LIFE = ("term", "whole_life")
GOALS = ("health", "term", "whole_life")
PRIORITIES = ("low_premium", "claim_reliability", "low_waiting", "pre_existing_cover", "riders")


@dataclass(frozen=True)
class Spec:
    name: str
    kind: str                    # int | money | bool | choice | list
    ask: Dict[str, str]          # what to ask, per goal ("*" = any goal); phrased by the model, never shown raw
    goals: tuple = GOALS
    lo: float = 0
    hi: float = 0
    choices: tuple = ()
    applies: Callable = lambda p: True


SPECS: List[Spec] = [
    Spec("goal", "choice", {"*": "whether they want health insurance, term life insurance or whole life insurance. "
                                 "If they are unsure, say you can explain the difference between term and whole life"},
         choices=GOALS),
    Spec("age", "int", {"health": "the age of the eldest person who would be covered",
                        "*": "their age"}, lo=18, hi=70),
    Spec("annual_income", "money", {"*": "their approximate income per year"}, lo=50_000, hi=50 * CRORE),
    Spec("dependents", "int", {"*": "how many people depend on their income, such as spouse, children or parents"},
         goals=LIFE, lo=0, hi=10),
    Spec("existing_life_cover", "money", {"*": "the total life insurance cover they already have, including any from "
                                               "an employer, or zero if none"}, goals=LIFE, lo=0, hi=100 * CRORE),
    Spec("liabilities", "money", {"*": "the total of loans they still owe, such as home or car loans, or zero if none"},
         goals=LIFE, lo=0, hi=100 * CRORE),
    Spec("smoker", "bool", {"*": "whether they smoke or use tobacco"}, goals=LIFE),
    Spec("city_tier", "choice", {"*": "whether they live in a large metro city or in another city or town"},
         goals=("health",), choices=("metro", "non_metro")),
    Spec("members", "choice", {"*": "who the health cover is for: only themselves, themselves and a spouse, "
                                    "or a family with children"},
         goals=("health",), choices=("self", "self_spouse", "family")),
    Spec("children", "int", {"*": "how many children would be covered (also give this whenever they mention a number of "
                                  "children, even if the question was about something else)"}, goals=("health",), lo=1, hi=6,
         applies=lambda p: p.get("members") == "family"),
    Spec("existing_health_source", "choice", {"*": "whether they already have health insurance, and if so whether it "
                                                   "is from an employer or one they bought themselves"},
         goals=("health",), choices=("none", "employer", "personal")),
    Spec("existing_health_cover", "money", {"*": "the sum insured of the health insurance they bought themselves"},
         goals=("health",), lo=0, hi=10 * CRORE, applies=lambda p: p.get("existing_health_source") == "personal"),
    Spec("pre_existing", "bool", {"*": "whether anyone to be covered has an existing medical condition such as "
                                       "diabetes or high blood pressure"}, goals=("health",)),
    Spec("maternity_needed", "bool", {"*": "whether they want maternity expenses covered"}, goals=("health",),
         applies=lambda p: p.get("members") in ("self_spouse", "family")),
    Spec("priorities", "list", {"*": "whether anything matters most to them, such as the lowest price, how reliably "
                                     "claims are paid, or shorter waiting periods, or nothing in particular"},
         choices=PRIORITIES),
]
SPEC = {s.name: s for s in SPECS}

_UNITS = {"lakh": LAKH, "lakhs": LAKH, "lac": LAKH, "lacs": LAKH, "लाख": LAKH,
          "crore": CRORE, "crores": CRORE, "cr": CRORE, "करोड़": CRORE, "करोड": CRORE,
          "thousand": 1000, "k": 1000, "हजार": 1000, "हज़ार": 1000}
_ONES = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                    "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
_COMPOUND_ONES = list(_ONES)[1:10]  # "twenty five": English only; Hindi 21-99 are separate words, so not covered
_HINDI = {"शून्य": 0, "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6, "छः": 6, "सात": 7, "आठ": 8,
          "नौ": 9, "दस": 10, "ग्यारह": 11, "बारह": 12, "तेरह": 13, "चौदह": 14, "पंद्रह": 15, "पन्द्रह": 15, "सोलह": 16,
          "सत्रह": 17, "अठारह": 18, "उन्नीस": 19, "बीस": 20, "तीस": 30, "चालीस": 40, "पचास": 50, "साठ": 60, "सत्तर": 70,
          "अस्सी": 80, "नब्बे": 90}
_WORDS = {**_ONES, **_TENS, **_HINDI}
_ALT = lambda words: "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
_LETTER = r"A-Za-z\u0900-\u097F"
_NUMBER = re.compile(
    rf"(?<![\w\u0900-\u097F])(\d[\d,]*(?:\.\d+)?|(?:{_ALT(_TENS)})(?:[\s-]+(?:{_ALT(_COMPOUND_ONES)}))?(?![{_LETTER}])|"
    rf"(?:{_ALT(list(_ONES) + list(_HINDI))})(?![{_LETTER}]))\s*([{_LETTER}]+)?", re.I)


def _to_number(token: str) -> float:
    token = token.lower().strip()
    if token[0].isdigit():
        return float(token.replace(",", ""))
    return sum(_WORDS.get(w, 0) for w in re.split(r"[\s-]+", token))


def parse_money(text: str) -> Optional[int]:
    """Rupees written in `text` ("12 lakh", "twelve lakh", "1.5 crore", "90,000", "50k"), else None."""
    match = _NUMBER.search(text.replace("₹", " ").replace("Rs.", " ").replace("Rs", " "))
    if not match:
        return None
    unit = (match.group(2) or "").lower()
    if unit not in _UNITS:
        unit = ""  # a trailing ordinary word, not a unit
    return int(round(_to_number(match.group(1)) * _UNITS.get(unit, 1)))


def parse_int(text: str) -> Optional[int]:
    match = _NUMBER.search(text)
    return int(_to_number(match.group(1))) if match else None


_CHILD = re.compile(r"(kids?|children|child|बच्चे|बच्चों|बच्चा|बेटियां|बेटे|बेटी|बेटा)", re.I)


def children_in(text: str) -> Optional[int]:
    """A count written just before a word for children ("our 2 kids", "दो बच्चे"), else None."""
    word = _CHILD.search(text)
    if not word:
        return None
    numbers = list(_NUMBER.finditer(text[max(0, word.start() - 25):word.start()]))
    return int(_to_number(numbers[-1].group(1))) if numbers else None


YES_WORDS = {"yes", "yeah", "yep", "yup", "sure", "correct", "right", "haan", "han", "ha", "हाँ", "हां", "जी"}
NO_WORDS = {"no", "nope", "nah", "nahi", "nahin", "na", "नहीं", "ना", "नही", "none", "nothing", "nil", "zero"}


def bare_answer(text: str) -> Optional[bool]:
    """True/False if `text` is only a yes or a no (nothing else), else None."""
    words = re.findall(r"[\w\u0900-\u097F]+", text.lower())
    if words and all(w in YES_WORDS for w in words):
        return True
    if words and all(w in NO_WORDS for w in words):
        return False
    return None


class Profile:
    def __init__(self):
        self.values: Dict[str, Any] = {}
        self.confirmed = False
        self.asked_optional = False  # the optional "what matters most" question has been put to the user

    def get(self, name: str, default=None):
        return self.values.get(name, default)

    def set(self, name: str, value: Any) -> bool:
        """Store `value` if it is valid for the field. Returns False (and stores nothing) otherwise."""
        spec = SPEC.get(name)
        if spec is None:
            return False
        if spec.kind in ("int", "money"):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not spec.lo <= value <= spec.hi:
                return False
            value = int(value)
        elif spec.kind == "bool":
            if not isinstance(value, bool):
                return False
        elif spec.kind == "choice":
            if value not in spec.choices:
                return False
        elif spec.kind == "list":
            if not isinstance(value, list) or any(v not in spec.choices for v in value):
                return False
        if self.values.get(name) != value:
            self.values[name] = value
            self.confirmed = False  # any change must be confirmed again
        return True

    def relevant(self) -> List[Spec]:
        goal = self.get("goal")
        return [s for s in SPECS if s.name == "goal" or (goal in s.goals and s.applies(self.values))]

    def next_missing(self) -> Optional[Spec]:
        for spec in self.relevant():
            if spec.name == "priorities":
                if not self.asked_optional:
                    return spec
            elif spec.name not in self.values:
                return spec
        return None

    def progress(self) -> Optional[Tuple[int, int]]:
        """(answered, total) questions for the person's goal, for a progress bar. None until the goal is known,
        because the number of questions depends on it."""
        if self.get("goal") not in GOALS:
            return None
        relevant = self.relevant()
        answered = sum(1 for s in relevant if (self.asked_optional if s.name == "priorities" else s.name in self.values))
        return answered, len(relevant)

    def complete(self) -> bool:
        return self.get("goal") in GOALS and self.next_missing() is None

    def members_count(self) -> int:
        members = self.get("members", "self")
        return {"self": 1, "self_spouse": 2}.get(members) or min(2 + self.get("children", 1), 4)

    def question_for(self, spec: Spec) -> str:
        return spec.ask.get(self.get("goal"), spec.ask["*"])

    def summary(self) -> str:
        """Plain-English read-back, with every figure in both digit and lakh/crore form."""
        v = self.values
        goal = {"health": "health insurance", "term": "term life insurance", "whole_life": "whole life insurance"}[v["goal"]]
        parts = [f"Looking for {goal}"]
        parts.append(f"age {v['age']}" + (" for the eldest person covered" if v["goal"] == "health" else ""))
        parts.append(f"yearly income {money(v['annual_income'])}")
        if v["goal"] in LIFE:
            parts += [f"{v['dependents']} dependents", f"existing life cover {money(v['existing_life_cover'])}",
                      f"loans owed {money(v['liabilities'])}", "smoker" if v["smoker"] else "non-smoker"]
        else:
            members = {"self": "only themselves", "self_spouse": "themselves and a spouse",
                       "family": f"a family with {v.get('children', 0)} children"}[v["members"]]
            parts += [("lives in a metro city" if v["city_tier"] == "metro" else "lives outside the large metro cities"),
                      f"cover for {members}"]
            source = v["existing_health_source"]
            parts.append("no existing health insurance" if source == "none" else
                         "health insurance from an employer" if source == "employer" else
                         f"own health insurance of {money(v['existing_health_cover'])}")
            parts.append("has an existing medical condition" if v["pre_existing"] else "no existing medical condition")
            if "maternity_needed" in v:
                parts.append("wants maternity cover" if v["maternity_needed"] else "does not need maternity cover")
        priorities = v.get("priorities") or []
        parts.append("most important: " + ", ".join(p.replace("_", " ") for p in priorities) if priorities
                     else "no particular priority")
        return "; ".join(parts) + "."

    def bands(self) -> Dict[str, Any]:
        """Ranges only, for the audit trail. Never exact figures."""
        v = self.values
        out = {"goal": v.get("goal"), "age_band": _age_band(v.get("age")),
               "income_band": _money_band(v.get("annual_income"))}
        for key in ("dependents", "smoker", "city_tier", "members", "children", "existing_health_source",
                    "pre_existing", "maternity_needed", "priorities"):
            if key in v:
                out[key] = v[key]
        for key in ("existing_life_cover", "liabilities", "existing_health_cover"):
            if key in v:
                out[f"{key}_band"] = _money_band(v[key])
        return out


def _age_band(age) -> Optional[str]:
    return None if age is None else f"{age // 5 * 5}-{age // 5 * 5 + 4}"


def _money_band(n) -> Optional[str]:
    if n is None:
        return None
    for limit, label in ((1, "none"), (3 * LAKH, "under 3 lakh"), (6 * LAKH, "3-6 lakh"), (10 * LAKH, "6-10 lakh"),
                         (15 * LAKH, "10-15 lakh"), (25 * LAKH, "15-25 lakh"), (50 * LAKH, "25-50 lakh"),
                         (CRORE, "50 lakh-1 crore"), (5 * CRORE, "1-5 crore")):
        if n < limit:
            return label
    return "over 5 crore"
