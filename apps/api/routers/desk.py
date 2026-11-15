"""The customer executive desk: people who take over conversations the AI should not handle alone.

Executives (role `executive`, or `admin`) see a live queue ordered by priority and age, claim a case, read the masked
conversation that led to it, chat with the customer in that same conversation, schedule video KYC, and resolve it. The
customer side lets a person ask for someone (video KYC, a callback, a complaint), read replies when they were offline,
answer, and cancel."""
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from auth.deps import current_user, require_role, websocket_user
from auth.store import User, get_user
from desk import live, store as desk
from observability.metrics import CASE_EVENTS
from trust import consent
from trust.audit import Trace
from trust.pii import Vault, normalise_digits

router = APIRouter(tags=["Executive desk"])
executive = require_role("executive", "admin")
UNAUTHORIZED, FORBIDDEN = 4401, 4403


class Message(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class Resolution(BaseModel):
    outcome: Literal["resolved", "escalated_offline", "no_response", "duplicate"]
    resolution: str = Field(min_length=1, max_length=2000, description="What was done, for the record")
    message: Optional[str] = Field(None, max_length=1000, description="A closing note the customer sees")


class VideoKyc(BaseModel):
    scheduled_for: datetime
    meeting_url: Optional[str] = Field(None, max_length=500, pattern=r"^https://")


class CaseRequest(BaseModel):
    kind: Literal["video_kyc", "callback", "complaint", "help"]
    note: Optional[str] = Field(None, max_length=500)


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def _card(case: dict) -> dict:
    return {k: _iso(case.get(k)) for k in ("id", "reference", "kind", "reason", "priority", "status", "language", "created_at",
                                            "sla_due_at", "scheduled_for")}


async def _own(case_id: str, me: User) -> dict:
    case = await desk.get(case_id)
    if case is None:
        raise HTTPException(404, "No such case.")
    if case["status"] != "assigned" or case["assigned_to"] != me.id:
        raise HTTPException(409, "Claim this case first.")
    return case


# ---------------------------------------------------------------- executives
@router.get("/desk/queue")
async def queue(view: Literal["open", "mine", "overdue", "all"] = "open", me: User = Depends(executive)):
    """Cases by priority (urgent, high, normal) then age. `overdue` are past their pick-up time."""
    return {"items": [{**_card(c), "customer": {"name": c["customer_name"], "username": c["customer_username"]},
                       "overdue": c["overdue"], "messages": c["messages"], "assigned_to": c["assigned_to"]}
                      for c in await desk.queue(view, me.id)],
            "stats": await desk.stats()}


@router.get("/desk/cases/{case_id}")
async def case_detail(case_id: str, _: User = Depends(executive)):
    """Everything an executive needs to pick up: why the case exists, the masked conversation before it, the thread since,
    who the customer is, what they have agreed to, and the audit trace of the turn that raised it."""
    case = await desk.get(case_id)
    if case is None:
        raise HTTPException(404, "No such case.")
    customer = await get_user(case["user_id"])
    return {"case": {**_card(case), "note": case["note"], "assigned_to": case["assigned_to"], "outcome": case["outcome"],
                     "resolution": case["resolution"], "meeting_url": case["meeting_url"], "trace_id": case["trace_id"],
                     "session_id": case["session_id"], "channel": case["channel"]},
            "conversation_before": case["summary"],
            "messages": [{**m, "at": _iso(m["at"])} for m in await desk.messages(case_id)],
            "customer": {"name": customer.name, "username": customer.username, "email": customer.email,
                         "language": customer.language, "platform": customer.platform,
                         "online": live.online(customer.id), "consents": consent.active(customer.subject)} if customer else None}


@router.post("/desk/cases/{case_id}/claim")
async def claim(case_id: str, me: User = Depends(executive)):
    """Take a case. If someone else got there first: 409."""
    case = await desk.claim(case_id, me.id)
    if case is None:
        raise HTTPException(409, "This case is no longer waiting.")
    CASE_EVENTS.labels("claimed").inc()
    who = {"name": me.name or "Sahaj team"}
    await desk.add_message(case_id, "system", f"{who['name']} from the Sahaj team joined.")
    await live.to_customer(case["user_id"], {"type": "agent_joined", "case_id": case_id, "agent": who})
    await live.to_executives({"type": "case_claimed", "case_id": case_id, "by": me.id})
    return _card(case)


@router.post("/desk/cases/{case_id}/release")
async def release(case_id: str, me: User = Depends(executive)):
    """Put a claimed case back in the queue (for example at the end of a shift)."""
    case = await desk.release(case_id, me.id)
    if case is None:
        raise HTTPException(409, "You are not handling this case.")
    CASE_EVENTS.labels("released").inc()
    await live.to_customer(case["user_id"], {"type": "agent_left", "case_id": case_id})
    await live.to_executives({"type": "case_released", "case_id": case_id})
    return _card(case)


@router.post("/desk/cases/{case_id}/messages", status_code=201)
async def reply(case_id: str, body: Message, me: User = Depends(executive)):
    """Write to the customer. It appears in their open conversation at once, or when they next come back."""
    case = await _own(case_id, me)
    message = await desk.add_message(case_id, "executive", body.text.strip(), me.id)
    delivered = await live.to_customer(case["user_id"], {"type": "agent_message", "case_id": case_id, "text": message["text"],
                                                         "agent": {"name": me.name or "Sahaj team"}, "at": _iso(message["at"])})
    CASE_EVENTS.labels("executive_message").inc()
    return {**message, "at": _iso(message["at"]), "delivered_live": delivered > 0}


@router.post("/desk/cases/{case_id}/video-kyc")
async def schedule_video_kyc(case_id: str, body: VideoKyc, me: User = Depends(executive)):
    """Book the video KYC call (it is done by a person, as RBI requires). The customer is told the time and the link."""
    case = await _own(case_id, me)
    if case["kind"] != "video_kyc":
        raise HTTPException(409, "This is not a video KYC case.")
    if body.scheduled_for.tzinfo is None or body.scheduled_for <= datetime.now(timezone.utc):
        raise HTTPException(422, "scheduled_for must be a future time with a timezone.")
    case = await desk.schedule(case_id, me.id, body.scheduled_for, body.meeting_url)
    await desk.add_message(case_id, "system", f"Video KYC booked for {body.scheduled_for.isoformat()}.")
    await live.to_customer(case["user_id"], {"type": "video_kyc_scheduled", "case_id": case_id,
                                             "scheduled_for": body.scheduled_for.isoformat(), "meeting_url": body.meeting_url})
    CASE_EVENTS.labels("video_kyc_scheduled").inc()
    return _card(case)


@router.post("/desk/cases/{case_id}/resolve")
async def resolve(case_id: str, body: Resolution, me: User = Depends(executive)):
    """Close the case. The customer's conversation goes back to the AI."""
    await _own(case_id, me)
    case = await desk.close(case_id, "resolved", me.id, body.outcome, body.resolution)
    if body.message:
        await desk.add_message(case_id, "executive", body.message, me.id)
    await live.to_customer(case["user_id"], {"type": "handoff_closed", "case_id": case_id, "status": "resolved",
                                             "outcome": body.outcome, "message": body.message})
    await live.to_executives({"type": "case_closed", "case_id": case_id, "status": "resolved"})
    CASE_EVENTS.labels("resolved").inc()
    return _card(case)


@router.websocket("/ws/desk")
async def desk_socket(ws: WebSocket):
    """Live desk for executives: a snapshot of the queue, then every new case, customer message, claim and close."""
    user = await websocket_user(ws)
    await ws.accept()
    if user is None:
        return await ws.close(code=UNAUTHORIZED, reason="Sign in first.")
    if user.role not in ("executive", "admin"):
        return await ws.close(code=FORBIDDEN, reason="For customer executives only.")
    live.join_executive(user.tenant_id, user.id, ws)
    try:
        await ws.send_json({"type": "queue", "items": [_card(c) for c in await desk.queue("all", user.id)], "stats": await desk.stats()})
        while True:
            await ws.receive_text()   # the desk talks over REST; this socket only listens (and notices a disconnect)
    except WebSocketDisconnect:
        pass
    finally:
        live.leave_executive(user.tenant_id, user.id, ws)


# ---------------------------------------------------------------- customers
@router.get("/cases")
async def my_cases(user: User = Depends(current_user)):
    """The person's cases, newest first, with the thread of the active one (so replies sent while they were away show)."""
    items = await desk.for_customer(user.id)
    active = next((c for c in items if c["status"] in desk.ACTIVE), None)
    return {"items": [{k: _iso(v) for k, v in c.items()} for c in items],
            "active_messages": [{**m, "at": _iso(m["at"])} for m in await desk.messages(active["id"])] if active else []}


@router.post("/cases", status_code=201)
async def ask_for_a_person(body: CaseRequest, user: User = Depends(current_user)):
    """Ask for a person without a conversation open: video KYC (needs the video_kyc consent), a callback, a complaint, or help."""
    if body.kind == "video_kyc" and not consent.is_active(user.subject, "video_kyc"):
        raise HTTPException(409, {"code": "requires", "message": "Video KYC needs the 'video_kyc' consent first.", "purpose": "video_kyc"})
    from trust import handoff
    reason = {"help": "user_requested"}.get(body.kind, body.kind)
    note = Vault().mask(normalise_digits(body.note)) if body.note else None
    trace = Trace(f"user:{user.id}")
    case = await handoff.create(f"user:{user.id}", reason, [], trace.id, user=user, language=user.language, channel="api", note=note)
    trace.add("handoff", reason=reason, reference=case["reference"])
    trace.save()
    return {k: _iso(case[k]) for k in ("id", "reference", "kind", "priority", "status", "sla_due_at")}


@router.post("/cases/{case_id}/messages", status_code=201)
async def customer_reply(case_id: str, body: Message, user: User = Depends(current_user)):
    case = await desk.get(case_id)
    if case is None or case["user_id"] != user.id:
        raise HTTPException(404, "No such case.")
    if case["status"] not in desk.ACTIVE:
        raise HTTPException(409, "This case is closed.")
    text = Vault().mask(normalise_digits(body.text.strip()))
    message = await desk.add_message(case_id, "customer", text)
    await live.to_executives({"type": "customer_message", "case_id": case_id, "text": text, "at": _iso(message["at"])})
    return {**message, "at": _iso(message["at"])}


@router.post("/cases/{case_id}/cancel")
async def cancel(case_id: str, user: User = Depends(current_user)):
    case = await desk.get(case_id)
    if case is None or case["user_id"] != user.id:
        raise HTTPException(404, "No such case.")
    closed = await desk.close(case_id, "cancelled", f"user:{user.id}", "cancelled_by_customer", None)
    if closed is None:
        raise HTTPException(409, "This case is already closed.")
    await live.to_customer(user.id, {"type": "handoff_closed", "case_id": case_id, "status": "cancelled"})
    await live.to_executives({"type": "case_closed", "case_id": case_id, "status": "cancelled"})
    return _card(closed)
