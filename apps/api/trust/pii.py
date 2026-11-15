"""PII masking. Raw identifiers never reach the LLM, the logs or the audit trail.

Mask everything that *looks like* PII (over-masking is the safe direction), keep the
real values in a per-session Vault, and only call `reveal()` inside a tool that
genuinely needs the value.
"""
import re
import unicodedata
from typing import Dict

# Order matters: more specific patterns first.
PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("UPI", re.compile(r"(?<![\w.])[\w.\-]{2,}@[a-z]{2,}\b", re.I)),
    # Whitespace allowed between characters because speech-to-text spaces things out ("A B C D E 1234 F").
    ("PAN", re.compile(r"(?<![A-Za-z0-9])(?:[A-Z]\s*){5}(?:\d\s*){4}[A-Z](?![A-Za-z0-9])", re.I)),
    ("AADHAAR", re.compile(r"(?<!\d)[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}(?!\d)")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")),
    ("ACCOUNT", re.compile(r"(?<!\d)\d{9,18}(?!\d)")),
]


# Speech-to-text often spells identifiers out: "A B C D E 1 2 3 4 F". Join such runs first.
SPELLED_OUT = re.compile(r"(?<![\w])(?:[A-Za-z0-9][\s,.-]{1,2}){7,}[A-Za-z0-9](?![\w])")


def normalise_digits(text: str) -> str:
    """Turn Devanagari, Tamil, Bengali... digits into ASCII so patterns can see them."""
    return "".join(str(unicodedata.decimal(c)) if c.isdecimal() else c for c in text)


class Vault:
    def __init__(self):
        self._by_token: Dict[str, str] = {}
        self._by_value: Dict[str, str] = {}
        self._counts: Dict[str, int] = {}

    def mask(self, text: str) -> str:
        text = SPELLED_OUT.sub(lambda m: re.sub(r"[\s,.-]", "", m.group()), text)
        for label, pattern in PATTERNS:
            text = pattern.sub(lambda m, label=label: self._token(label, m.group()), text)
        return text

    def reveal(self, text: str) -> str:
        for token, value in self._by_token.items():
            text = text.replace(token, value)
        return text

    def clear(self) -> None:
        self._by_token.clear()
        self._by_value.clear()
        self._counts.clear()

    def _token(self, label: str, value: str) -> str:
        if value in self._by_value:
            return self._by_value[value]
        self._counts[label] = self._counts.get(label, 0) + 1
        token = f"[{label}_{self._counts[label]}]"
        self._by_value[value] = token
        self._by_token[token] = value
        return token
