"""Hand a conversation to a human: a masked packet is recorded and sent to a webhook."""
import uuid
from typing import List

import httpx

import config
from trust import consent, ledger


async def create(subject: str, reason: str, history: List[dict], trace_id: str) -> str:
    reference = uuid.uuid4().hex[:12]
    packet = {
        "reference": reference,
        "reason": reason,
        "recent_messages": history[-10:],  # already PII-masked
        "active_consents": consent.active(subject),
        "trace_id": trace_id,
        "delivered": False,
    }
    if config.HANDOFF_WEBHOOK_URL:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                (await client.post(config.HANDOFF_WEBHOOK_URL, json={"subject": subject, **packet})).raise_for_status()
            packet["delivered"] = True
        except httpx.HTTPError:
            pass  # still recorded below with delivered=False so it can be retried
    ledger.append("handoff", subject, packet, trace_id)
    return reference
