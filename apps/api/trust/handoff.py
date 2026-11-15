"""Hand a conversation to a person. A case is opened on the executive desk (or the person's open case is reused), it is
recorded in the ledger, posted to HANDOFF_WEBHOOK_URL if one is set, and announced to every executive watching the desk."""
from typing import List, Optional

import httpx

import config
from trust import consent, ledger


async def create(subject: str, reason: str, history: List[dict], trace_id: str, *, user=None, language: Optional[str] = None,
                 channel: Optional[str] = None, note: Optional[str] = None) -> dict:
    """The case ({"id", "reference", "priority", "status", ...}) the conversation is now part of."""
    from desk import live, store as desk
    summary = history[-10:]  # already PII-masked
    case, created = await desk.open_case(user.id, reason, session_id=subject, summary=summary, language=language,
                                         channel=channel, note=note, trace_id=trace_id)
    packet = {"reference": case["reference"], "case_id": case["id"], "reason": reason, "priority": case["priority"],
              "recent_messages": summary, "active_consents": consent.active(user.subject), "trace_id": trace_id,
              "delivered": False, "new_case": created}
    if config.HANDOFF_WEBHOOK_URL:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                (await client.post(config.HANDOFF_WEBHOOK_URL, json={"subject": subject, **packet})).raise_for_status()
            packet["delivered"] = True
        except httpx.HTTPError:
            pass  # still recorded below with delivered=False so it can be retried
    ledger.append("handoff", subject, packet, trace_id)
    from observability.metrics import CASE_EVENTS
    CASE_EVENTS.labels("opened" if created else "joined").inc()
    light = {k: case[k] for k in ("id", "reference", "kind", "reason", "priority", "status")}
    case["executives_online"] = bool(live.executives.get(user.tenant_id))
    await live.to_customer(user.id, {"type": "case_attached", "case_id": case["id"], "case": light})   # every open conversation
    await live.to_executives({"type": "case_opened" if created else "case_updated",
                              "case": {k: case[k] for k in ("id", "reference", "kind", "reason", "priority", "status", "language")}
                                      | {"sla_due_at": case["sla_due_at"].isoformat()}})
    return case
