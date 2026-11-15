from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from auth.deps import current_user
from auth.store import User
from gateway.middleware import client_ip
from observability.metrics import CONSENT_EVENTS
from trust import consent, consents

router = APIRouter(prefix="/consents", tags=["Consent"])


class Decision(BaseModel):
    granted: bool
    version: Optional[str] = None   # the `version` of the text that was shown: required when granting


def fail(e: consents.ConsentError) -> HTTPException:
    status = {"unknown_purpose": 404, "stale_version": 409, "requires": 409, "erasure_failed": 500}.get(e.code, 400)
    detail = {"code": e.code, "message": e.message}
    if e.code == "stale_version" and e.purpose:
        detail["current"] = consent.required(e.purpose)   # so the UI can show the new text straight away
    return HTTPException(status, detail)


@router.get("")
async def list_consents(user: User = Depends(current_user)):
    """Everything a consent screen needs: each purpose with its text and version, whether it is on, since when and until
    when, and the `action` to offer (`ask`, `renew` or `none`). `missing_required` lists what must be granted before
    Sahaj can be used."""
    return {"items": consent.status(user.subject), "missing_required": consents.missing_required(user)}


@router.put("/{purpose}")
async def decide(purpose: str, body: Decision, request: Request, user: User = Depends(current_user)):
    """Grant or withdraw one purpose. Granting needs the `version` that was shown. Withdrawing also withdraws what depends
    on it and erases what it allowed Sahaj to hold; the response lists both."""
    if body.granted and body.version is None:
        raise HTTPException(422, {"code": "version_required", "message": "Send the `version` of the consent text that was shown."})
    try:
        result = await consents.set_consent(user, purpose, body.granted, channel="api", version=body.version, ip=client_ip(request.scope))
    except consents.ConsentError as e:
        raise fail(e)
    CONSENT_EVENTS.labels(purpose, "granted" if body.granted else "withdrawn").inc()
    return {**result, "item": next(i for i in consent.status(user.subject) if i["purpose"] == purpose)}


@router.get("/history")
async def history(purpose: Optional[str] = Query(None), user: User = Depends(current_user)):
    """The person's own consent record, oldest first: what they agreed to (version and text hash), when, how, and for how long."""
    if purpose is not None and purpose not in consent.PURPOSES:
        raise HTTPException(404, {"code": "unknown_purpose", "message": f"Unknown consent purpose: {purpose}"})
    return {"items": consent.history(user.subject, purpose)}
