"""Gives a verified reply a shape a UI can render: a summary, one point per statement with the source behind it,
and fixed notes (such as disclosures) kept apart. It only splits and labels text that already passed the guardrails
and fact-check: no model call, nothing added or reworded, so the `text` of the reply and this view always agree."""
import re
from typing import Dict, List

from trust.guardrails import CITE, strip_citations

SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")  # "1.5 lakh" has no space after its dot, so it is not split
LEADING_TAGS = re.compile(r"^(?:\s*\[[\w.\-]+:[\w.\-]+\])+")


def points(text: str) -> List[dict]:
    """One entry per statement: {"text": without tags, "tags": [source ids]}. A tag that sits after the full stop
    belongs to the statement before it."""
    found: List[dict] = []
    for segment in SENTENCE_END.split(text.strip()):
        lead = LEADING_TAGS.match(segment)
        if lead and found:
            found[-1]["tags"] += [t for t in CITE.findall(lead.group()) if t not in found[-1]["tags"]]
            segment = segment[lead.end():]
        clean = strip_citations(segment).strip()
        if clean:
            found.append({"text": clean, "tags": list(dict.fromkeys(CITE.findall(segment)))})
    return found


def build(text: str, notes: List[str], sources: Dict[str, str], kind: str) -> dict:
    """The structured view of a reply. `sources` is what the reply was allowed to cite: tags outside it are dropped."""
    items = [{"text": p["text"], "sources": [t for t in p["tags"] if t in sources]} for p in points(text)]
    used = list(dict.fromkeys(t for item in items for t in item["sources"]))
    return {
        "kind": kind,
        "summary": items[0]["text"] if items else "",
        "points": items,
        "sources": [{"id": t, "text": sources[t]} for t in used],
        "notes": notes,
    }
