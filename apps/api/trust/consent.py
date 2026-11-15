"""Consent ledger: purpose-bound, versioned, revocable, recorded in the hash chain.

Revoking appends a new entry; nothing is ever edited. The consent texts below are
DRAFTS and need compliance/legal review before production.
"""
import hashlib
import time
from typing import Dict, List

from trust import ledger

PURPOSES = {
    "conversation": {
        "version": "2026-11-draft-1",
        "text": (
            "Sahaj will process your voice and the details you share to answer your questions "
            "about insurance and loans. Personal identifiers such as PAN and Aadhaar are masked, "
            "and a record of this conversation is kept for audit. You can withdraw consent at any time."
        ),
    },
    "needs_analysis": {
        "version": "2026-11-draft-1",
        "text": (
            "To suggest suitable insurance, Sahaj will use the details you tell it, such as your age, income, "
            "dependents and existing cover. Your exact details are kept only during this conversation. A record of "
            "the suggestion, using ranges instead of exact figures, is kept for audit, and what you say in answer to the "
            "questions is not kept. "
            "You can withdraw consent at any time."
        ),
    },
    "memory": {
        "version": "2026-11-draft-1",
        "text": (
            "Sahaj can remember a short summary of your conversations and a few preferences, such as the language you "
            "speak and the topics you asked about, so it can help you better next time. It never keeps numbers, "
            "identifiers, contact or health details. You can see what is remembered and delete any of it, and "
            "withdrawing consent erases it all."
        ),
    },
    "video_kyc": {
        "version": "2026-11-draft-1",
        "text": (
            "To verify your identity, we will record a live video session, capture your photo and "
            "compare it with your identity documents, as required for KYC. "
            "You can withdraw consent at any time."
        ),
    },
}


def required(purpose: str) -> dict:
    return {"purpose": purpose, **PURPOSES[purpose]}


def _record(subject: str, purpose: str, event: str, channel: str, ttl_days: int = 365) -> dict:
    spec = PURPOSES[purpose]
    return ledger.append("consent", subject, {
        "purpose": purpose,
        "event": event,
        "version": spec["version"],
        "text_sha256": hashlib.sha256(spec["text"].encode()).hexdigest(),
        "channel": channel,
        "expires_at": time.time() + ttl_days * 86400 if event == "granted" else None,
    })


def grant(subject: str, purpose: str, channel: str = "app") -> dict:
    return _record(subject, purpose, "granted", channel)


def revoke(subject: str, purpose: str, channel: str = "app") -> dict:
    return _record(subject, purpose, "revoked", channel)


def _latest(subject: str) -> Dict[str, dict]:
    state = {}
    for entry in ledger.entries(subject=subject, kind="consent"):
        state[entry["payload"]["purpose"]] = entry["payload"]
    return state


def is_active(subject: str, purpose: str) -> bool:
    latest = _latest(subject).get(purpose)
    return bool(latest and latest["event"] == "granted" and latest["expires_at"] > time.time())


def active(subject: str) -> List[str]:
    return [p for p in _latest(subject) if is_active(subject, p)]
