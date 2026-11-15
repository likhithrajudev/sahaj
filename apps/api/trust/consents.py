"""Granting and withdrawing consent, with everything that has to happen around it: checking the person saw the current
text, keeping dependent purposes in step, and erasing what a withdrawn purpose allowed Sahaj to hold.

The ledger entry is written FIRST, so a withdrawal takes effect at once even if erasing then fails (the error is
reported and the erasure can be repeated). Used by REST, WebSocket and SSE alike, so every route records the same way."""
import hashlib
import logging
from typing import Dict, List, Optional

import config
from trust import consent

log = logging.getLogger("sahaj.consent")


class ConsentError(Exception):
    def __init__(self, code: str, message: str, purpose: Optional[str] = None):
        super().__init__(message)
        self.code, self.message, self.purpose = code, message, purpose


def client_ref(ip: Optional[str]) -> Optional[str]:
    """A salted hash of the client address: enough to tell two decisions came from the same place, not to find the person."""
    if not ip:
        return None
    return hashlib.sha256(((config.JWT_SECRET or "sahaj") + ip).encode()).hexdigest()[:16]


async def _erase(user, purpose: str) -> Dict[str, int]:
    """What Sahaj holds only because of this purpose."""
    if purpose == "memory":
        from memory import store as memory_store
        return {"memories": await memory_store.delete_all(user.id)}
    if purpose == "documents":   # the files the person uploaded (recordings have their own consent)
        from storage import files
        return {"files": await files.purge(user, files.UPLOADABLE)}
    if purpose == "conversation_records":
        from storage import files
        return {"recordings": await files.purge(user, files.RECORDINGS)}
    if purpose == "document_analysis":
        from storage import index
        return {"document_passages": await index.forget(user.id)}
    return {}


async def withdraw(user, purpose: str, *, channel: str, ip: Optional[str] = None) -> Dict:
    """Withdraw one purpose and, first, every purpose that depends on it. {"withdrawn": [...], "erased": {...}}"""
    withdrawn, erased, failures = [], {}, []
    for p in [*consent.dependents(purpose), purpose]:
        if not consent.is_active(user.subject, p):
            continue
        consent.revoke(user.subject, p, channel=channel, meta={"client": client_ref(ip)})
        withdrawn.append(p)
        try:
            erased.update(await _erase(user, p))
        except Exception as e:
            log.error("Erasure after withdrawing %s failed for a user: %s", p, e)
            failures.append(p)
    if failures:
        raise ConsentError("erasure_failed", f"Consent was withdrawn but erasing the data for {', '.join(failures)} failed. "
                                             "Withdraw again to retry.", failures[0])
    return {"withdrawn": withdrawn, "erased": erased}


async def set_consent(user, purpose: str, granted: bool, *, channel: str, version: Optional[str] = None,
                      ip: Optional[str] = None) -> Dict:
    """Record a decision. Granting needs the version of the text the person saw when `version` is given (and the REST
    API always requires it). Returns {"purpose", "granted", "withdrawn", "erased"}."""
    if purpose not in consent.PURPOSES:
        raise ConsentError("unknown_purpose", f"Unknown consent purpose: {purpose}", purpose)
    if not granted:
        return {"purpose": purpose, "granted": False, **await withdraw(user, purpose, channel=channel, ip=ip)}

    current = consent.PURPOSES[purpose]["version"]
    if version is not None and version != current:
        raise ConsentError("stale_version", "This consent text has changed. Show the current text and ask again.", purpose)
    needs = consent.META[purpose]["requires"]
    if needs and not consent.is_active(user.subject, needs):
        raise ConsentError("requires", f"'{purpose}' needs '{needs}' consent first.", needs)
    consent.grant(user.subject, purpose, channel=channel, meta={"client": client_ref(ip)}, version=version)
    return {"purpose": purpose, "granted": True, "withdrawn": [], "erased": {}}


def missing_required(user) -> List[str]:
    return [p for p, m in consent.META.items() if m["required"] and not consent.is_active(user.subject, p)]
