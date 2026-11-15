"""The model's three small jobs in the advisory flow: read fields out of what the person said, tell yes from no,
and phrase a question. None of them decides anything: every extracted value is re-checked in code."""
import json
import re
from typing import Any, Dict, Optional

from advisory.profile import SPEC, SPECS, Profile, Spec, bare_answer, children_in, parse_int, parse_money
from services.chat import chat

EXTRACT = """You read what a person said about themselves for an insurance needs analysis.
Return ONLY a JSON object. Each key is a field name from the list; each value is {{"value": ..., "evidence": "..."}}
where evidence is the exact words from the message that state it. Include a field ONLY if the message clearly states
it. Never guess or infer. If unsure, leave the field out. Money values are whole numbers of rupees
("12 lakh" = 1200000, "1.5 crore" = 15000000) and the evidence must contain the amount as spoken.
The question just asked was about: {asking}. A plain "yes" or "no" is the answer to that field.

Fields:
{fields}

Message: {message}"""

YES_NO = """A person was read a summary of their details and asked if it is correct. Their reply is below.
Answer with exactly one word: YES if they agree it is correct, NO if they say something is wrong or want a change,
UNCLEAR if it is neither.

Reply: {message}"""

PHRASE = """You are Sahaj, a warm insurance assistant speaking out loud. Say the following to the user in {language}, in its
native script, as one or two short natural spoken sentences. Ask only ONE question. Add nothing else: no lists, no
emojis, no digits, and never repeat or mention these instructions.
Say: {instruction}"""

ZERO = re.compile(r"\b(none|no|nil|zero|nothing|nahi|nahin)\b|^\s*0\s*$|नहीं|शून्य", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def _describe(spec: Spec) -> str:
    kind = {"int": f"whole number from {spec.lo:g} to {spec.hi:g}", "money": "rupees, whole number", "bool": "true or false",
            "choice": "one of: " + ", ".join(spec.choices),
            "list": "list using only: " + ", ".join(spec.choices) + "; empty list if nothing matters most"}[spec.kind]
    return f"- {spec.name} ({kind}): {spec.ask['*']}"


def _candidates(profile: Profile):
    goal = profile.get("goal")
    # The goal is only up for extraction until it is set: a stray reading must not turn health into life insurance.
    if goal is None:
        return [s for s in SPECS if s.name in ("goal", "age", "annual_income")]
    return [s for s in SPECS if s.name != "goal" and goal in s.goals]


def verified(spec: Spec, item: Any, text: str) -> Optional[Any]:
    """The value if it is backed by the person's own words, else None."""
    if not isinstance(item, dict) or "value" not in item:
        return None
    value, evidence = item["value"], str(item.get("evidence", ""))
    if not evidence.strip() or _norm(evidence) not in _norm(text):
        return None  # the model quoted something the person did not say
    if spec.kind in ("money", "int"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        parsed = parse_money(evidence) if spec.kind == "money" else parse_int(evidence)
        if parsed is None:
            return 0 if value == 0 and ZERO.search(evidence) else None
        return value if int(value) == parsed else None  # catches "12 lakh" being read as 12 crore, and the like
    if spec.kind == "choice" and value not in spec.choices:
        return None
    if spec.kind == "list" and (not isinstance(value, list) or any(v not in spec.choices for v in value)):
        return None
    return value


async def extract(text: str, profile: Profile, asking: Optional[str]) -> Dict[str, Any]:
    """Fields the person stated in `text`, each verified. Not yet validated against the profile's ranges.

    Yes/no and list answers are accepted only for the question that was just asked. The model would otherwise
    volunteer things like "no medical condition" from a message that never mentioned it.
    """
    spec_asked = SPEC.get(asking or "")
    bare = bare_answer(text)
    if spec_asked is not None and bare is not None:  # a plain yes or no needs no model
        if spec_asked.kind == "bool":
            return {spec_asked.name: bare}
        if bare is False and spec_asked.kind in ("money", "int") and spec_asked.lo == 0:
            return {spec_asked.name: 0}
        if bare is False and spec_asked.kind == "list":
            return {spec_asked.name: []}
    candidates = _candidates(profile)
    prompt = EXTRACT.format(asking=asking or "anything", fields="\n".join(_describe(s) for s in candidates),
                            message=text)
    raw = await chat([{"role": "system", "content": prompt}, {"role": "user", "content": "Return the JSON now."}], purpose="extract")
    start, end = raw.find("{"), raw.rfind("}")
    try:
        data = json.loads(raw[start:end + 1])
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    found = []  # (spec, value, evidence)
    for spec in candidates:
        if spec.kind in ("bool", "list") and spec.name != asking:
            continue
        if spec.name in data:
            value = verified(spec, data[spec.name], text)
            if value is not None:
                found.append((spec, value, _norm(str(data[spec.name].get("evidence", "")))))

    # A field the question was not about needs real evidence. The model sometimes backs many fields with one
    # throwaway word ("no", "any"), which is not the person saying those things.
    uses = {}
    for _, _, evidence in found:
        uses[evidence] = uses.get(evidence, 0) + 1
    out = {}
    for spec, value, evidence in found:
        if spec.name != asking and (len(evidence) < 4 or uses[evidence] > 1):
            continue
        out[spec.name] = value
    # The model sometimes names the family but not the number of children, so read that part in code.
    if "children" not in out and "children" not in profile.values and \
            "family" in (out.get("members"), profile.get("members")):
        count = children_in(text)
        if count is not None:
            out["children"] = count
    return out


def apply(profile: Profile, extracted: Dict[str, Any]) -> None:
    """Store extracted values in field order, so 'family' is known before 'children' is considered."""
    for spec in SPECS:
        if spec.name not in extracted:
            continue
        if spec.name == "goal" and profile.get("goal"):
            continue
        if spec.name != "goal" and profile.get("goal") not in spec.goals:
            continue
        if spec.applies(profile.values):
            profile.set(spec.name, extracted[spec.name])


async def agrees(text: str) -> Optional[bool]:
    """True for yes, False for no, None if unclear."""
    reply = (await chat([{"role": "system", "content": YES_NO.format(message=text)},
                         {"role": "user", "content": "Answer now."}], purpose="yes_no")).strip().upper()
    return True if reply.startswith("YES") else False if reply.startswith("NO") else None


async def phrase(instruction: str, language: str) -> str:
    return await chat([{"role": "system", "content": PHRASE.format(language=language, instruction=instruction)},
                       {"role": "user", "content": "Say it now."}], purpose="phrase")
