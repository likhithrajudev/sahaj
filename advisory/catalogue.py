"""The product catalogue. Today a fictional sample file; later fed from an insurer or aggregator API."""
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from advisory.rules import CRORE, LAKH

PATH = Path(__file__).resolve().parent.parent / "catalogue" / "sample-catalogue.json"


@lru_cache(maxsize=None)
def _load() -> dict:
    raw = PATH.read_bytes()
    data = json.loads(raw)
    data["sha256"] = hashlib.sha256(raw).hexdigest()
    return data


def products(goal: Optional[str] = None) -> List[dict]:
    return [p for p in _load()["products"] if goal is None or p["goal"] == goal]


def by_id(pid: str) -> dict:
    return next(p for p in _load()["products"] if p["id"] == pid)


def version() -> str:
    return _load()["sha256"]


def is_sample() -> bool:
    return bool(_load().get("sample"))


def find_in_text(text: str) -> List[str]:
    """Ids of products whose distinctive name word ("lotus", "neem", ...) appears in `text`."""
    lowered = text.lower()
    found = []
    for p in _load()["products"]:
        word = p["name"].split()[0].lower()  # "Lotus" in "Lotus Care (SAMPLE)"
        if re.search(rf"\b{re.escape(word)}\b", lowered) and p["id"] not in found:
            found.append(p["id"])
    return found


def money(n: float) -> str:
    """'Rs 1,20,00,000 (1.2 crore)': both forms, so the model may say either and still match the facts."""
    digits = str(int(round(n)))
    head, tail, parts = digits[:-3], digits[-3:], []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    grouped = "Rs " + ",".join(parts + [tail])
    if n >= CRORE:
        return f"{grouped} ({n / CRORE:g} crore)"
    if n >= LAKH:
        return f"{grouped} ({n / LAKH:g} lakh)"
    return grouped
