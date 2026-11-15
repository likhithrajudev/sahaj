"""Consent ledger: purpose-bound, versioned, revocable, recorded in the hash chain.

Every grant and withdrawal appends an entry; nothing is ever edited. An entry records WHAT was agreed to (purpose, the
version and SHA-256 of the exact text), WHEN, HOW (channel, request id, a hash of the client address) and for HOW LONG.
A grant counts only while it is unexpired AND for the version of the text that is current, so changing a text asks
everyone again. The consent texts below are DRAFTS and need compliance/legal review before production.
"""
import hashlib
import time
from typing import Dict, List, Optional

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
    "documents": {
        "version": "2026-11-draft-1",
        "text": (
            "You can upload documents, such as a loan offer or a policy, so Sahaj can keep them for you. They are stored "
            "privately and only you can open them. Sahaj does not read them yet. You can delete any file at any time, "
            "and withdrawing consent deletes all of them."
        ),
    },
    "document_analysis": {
        "version": "2026-11-draft-2",
        "text": (
            "Sahaj can read the documents you upload, such as a loan offer, a policy or photos of hospital bills, so it can "
            "answer questions about them. Text PDFs are read on our own servers. Scanned PDFs and photos are read by Sarvam "
            "AI's document reading service in India, which sees the page as it is. Personal identifiers such as PAN, "
            "Aadhaar, phone and account numbers are then masked before anything is stored or used to answer. Answers quote "
            "the page they came from. Only you can use your documents, and withdrawing consent removes what Sahaj learned "
            "from them."
        ),
    },
    "conversation_records": {
        "version": "2026-11-draft-1",
        "text": (
            "Sahaj can keep your voice recordings and a written transcript of each conversation in your private folder, so "
            "you can listen back, review and delete them. A recording holds your real voice and anything you say aloud, "
            "including details that are masked everywhere else. In transcripts, identifiers such as PAN, Aadhaar, phone "
            "and account numbers are masked. Only you can open them, and withdrawing consent deletes them all."
        ),
    },
    "video_kyc": {
        "version": "2026-11-draft-2",
        "text": (
            "With your permission, Sahaj will create a case so the service team can arrange a video identity-check "
            "appointment. An authorised official of the relevant regulated entity must conduct the live verification "
            "and may record the session or capture your photo and documents under that entity's process. "
            "Sahaj does not conduct the identity check. This request does not guarantee a loan or insurance approval. "
            "You can withdraw this consent for future appointments; records already held by the provider are subject "
            "to that provider's retention rules."
        ),
    },
    "financial_application": {
        "version": "2026-11-draft-1",
        "text": (
            "When I ask, Sahaj may send the application details I provide to the lender or insurer I select, to request "
            "an offer or process that application. The selected provider makes eligibility, underwriting and approval "
            "decisions. Sahaj does not take payment or issue a policy or loan. I will review the final terms and confirm "
            "before an application or purchase is submitted. Withdrawing stops future sharing; it cannot recall data "
            "already sent to a provider."
        ),
    },
    "credit_bureau": {
        "version": "2026-11-draft-1",
        "text": (
            "At my request, Sahaj may send the identity details I provide to its configured, authorised TransUnion CIBIL "
            "or credit-bureau partner to retrieve my credit score for the loan application I am considering. I will "
            "review and confirm each bureau request. Sahaj does not store my score or credit report. The bureau and its "
            "partner may process the request under their own terms."
        ),
    },
}



# What a UI needs to present each purpose, and how purposes relate. `requires`: cannot be on without it, and goes
# off with it. `withdrawal`: what withdrawing does, to show in the confirmation. `required`: the service cannot be used
# without it. `ttl_days`: how long a grant lasts before the person is asked again.
META = {
    "conversation": {"title": "Process my conversations", "required": True, "requires": None, "ttl_days": 365,
                     "withdrawal": "Sahaj stops answering and forgets this conversation."},
    "needs_analysis": {"title": "Use my details to suggest insurance", "required": False, "requires": "conversation", "ttl_days": 365,
                       "withdrawal": "Sahaj forgets the details you gave and will not suggest plans from them."},
    "memory": {"title": "Remember me between conversations", "required": False, "requires": None, "ttl_days": 365,
               "withdrawal": "Everything Sahaj remembers about you is erased."},
    "documents": {"title": "Store my documents", "required": False, "requires": None, "ttl_days": 365,
                  "withdrawal": "Every file you uploaded is deleted."},
    "document_analysis": {"title": "Read my documents and photos to answer questions", "required": False, "requires": "documents", "ttl_days": 365,
                          "withdrawal": "What Sahaj learned from your documents is erased. The files stay."},
    "conversation_records": {"title": "Keep my voice recordings and transcripts", "required": False, "requires": "conversation",
                             "ttl_days": 365, "withdrawal": "Every stored recording and transcript is deleted."},
    "video_kyc": {"title": "Video identity verification", "required": False, "requires": None, "ttl_days": 365,
                  "withdrawal": "Future Sahaj appointment requests stop. The regulated provider manages records it already holds."},
    "financial_application": {"title": "Share details for an insurance or loan request", "required": False,
                              "requires": "conversation", "ttl_days": 1,
                              "withdrawal": "Sahaj stops sending new application details. Data already sent must be handled with the provider."},
    "credit_bureau": {"title": "Request my credit score", "required": False, "requires": "conversation", "ttl_days": 1,
                      "withdrawal": "Sahaj stops making new bureau requests. A request already sent cannot be recalled."},
}
assert set(META) == set(PURPOSES), "every purpose needs presentation metadata"


def dependents(purpose: str) -> List[str]:
    """Purposes that cannot stand without this one."""
    return [p for p, m in META.items() if m["requires"] == purpose]


def sha256(purpose: str) -> str:
    return hashlib.sha256(PURPOSES[purpose]["text"].encode()).hexdigest()


def required(purpose: str) -> dict:
    return {"purpose": purpose, "title": META[purpose]["title"], "required": META[purpose]["required"],
            "requires": META[purpose]["requires"], "withdrawal": META[purpose]["withdrawal"], **PURPOSES[purpose]}


def _record(subject: str, purpose: str, event: str, channel: str, meta: Optional[dict] = None,
            version: Optional[str] = None) -> dict:
    spec, info = PURPOSES[purpose], META[purpose]
    from gateway.middleware import request_id  # which request carried the decision, for tracing it back
    payload = {
        "purpose": purpose,
        "event": event,
        "version": spec["version"],
        "text_sha256": sha256(purpose),
        # True when the client sent the version it displayed and it matched, so the person agreed to this exact text.
        "version_confirmed": version == spec["version"],
        "channel": channel,
        "request_id": request_id.get(),
        "expires_at": time.time() + info["ttl_days"] * 86400 if event == "granted" else None,
        **(meta or {}),
    }
    return ledger.append("consent", subject, payload)


def grant(subject: str, purpose: str, channel: str = "app", meta: Optional[dict] = None, version: Optional[str] = None) -> dict:
    return _record(subject, purpose, "granted", channel, meta, version)


def revoke(subject: str, purpose: str, channel: str = "app", meta: Optional[dict] = None) -> dict:
    return _record(subject, purpose, "revoked", channel, meta)


def attest(session_id: str, subject: str, done: set) -> None:
    """Note in a conversation's own audit trail which consents it relies on (`in_effect`), pointing at the person's
    consent record. Conversations are audited under a random id, so without this their reports would not show it."""
    for purpose in active(subject):
        if purpose not in done:
            done.add(purpose)
            ledger.append("consent", session_id, {"purpose": purpose, "event": "in_effect", "version": PURPOSES[purpose]["version"],
                                                  "text_sha256": sha256(purpose), "channel": "session", "recorded_under": "person"})


def _latest(subject: str) -> Dict[str, dict]:
    state = {}
    for entry in ledger.entries(subject=subject, kind="consent"):
        if entry["payload"]["event"] in ("granted", "revoked") and entry["payload"]["purpose"] in PURPOSES:
            state[entry["payload"]["purpose"]] = {**entry["payload"], "at": entry["created_at"]}
    return state


def is_active(subject: str, purpose: str) -> bool:
    """Granted, not expired, and for the text as it reads now."""
    latest = _latest(subject).get(purpose)
    return bool(latest and latest["event"] == "granted" and latest["expires_at"] > time.time()
                and latest["version"] == PURPOSES[purpose]["version"])


def active(subject: str) -> List[str]:
    return [p for p in _latest(subject) if is_active(subject, p)]


def status(subject: str) -> List[dict]:
    """One entry per purpose, for a consent screen."""
    latest, now = _latest(subject), time.time()
    out = []
    for purpose, spec in PURPOSES.items():
        last = latest.get(purpose)
        granted = bool(last and last["event"] == "granted")
        expired = bool(granted and last["expires_at"] <= now)
        stale = bool(granted and last["version"] != spec["version"])
        out.append({
            **required(purpose),
            "granted": is_active(subject, purpose),
            "granted_at": last["at"] if granted else None,
            "expires_at": last["expires_at"] if granted else None,
            "granted_version": last["version"] if granted else None,
            # What the UI should do: ask (never granted or withdrawn), renew (expired or the text changed), or nothing.
            "action": "none" if is_active(subject, purpose) else ("renew" if (expired or stale) else "ask"),
        })
    return out


def history(subject: str, purpose: Optional[str] = None) -> List[dict]:
    """The full record, oldest first, as the ledger holds it."""
    return [{"purpose": e["payload"]["purpose"], "event": e["payload"]["event"], "version": e["payload"]["version"],
             "text_sha256": e["payload"]["text_sha256"], "version_confirmed": e["payload"].get("version_confirmed"),
             "channel": e["payload"]["channel"], "request_id": e["payload"].get("request_id"),
             "expires_at": e["payload"].get("expires_at"), "recorded_at": e["created_at"], "ledger_hash": e["hash"]}
            for e in ledger.entries(subject=subject, kind="consent")
            if purpose is None or e["payload"]["purpose"] == purpose]
