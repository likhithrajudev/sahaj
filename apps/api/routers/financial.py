"""Consent-gated endpoints for authorised credit, lender and insurer integrations."""
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth.deps import current_user
from auth.store import User
from gateway.middleware import client_ip
from financial import providers, store
from trust import consent, consents

router = APIRouter(prefix="/financial", tags=["Financial products"])


class Action(BaseModel):
    provider: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,50}$")
    consent_version: str = Field(min_length=1, max_length=80)
    confirmed: bool = False


class BureauIdentity(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    pan: str = Field(pattern=r"^[A-Za-z]{5}[0-9]{4}[A-Za-z]$")
    date_of_birth: date
    mobile: str = Field(pattern=r"^\+?[0-9]{10,15}$")


class CreditCheckRequest(Action):
    identity: BureauIdentity


class LoanOffersRequest(Action):
    credit_check_id: str
    amount_inr: int = Field(gt=0, le=100_000_000)
    tenure_months: int = Field(gt=0, le=480)
    purpose: str = Field(min_length=1, max_length=120)


class LoanApplicationRequest(Action):
    offer_id: str = Field(min_length=1, max_length=200)
    kfs_version: str = Field(min_length=1, max_length=120)
    kfs_accepted: bool = False
    applicant: dict[str, str | int | float | bool] = Field(max_length=40)


class InsuranceQuoteRequest(Action):
    product_id: str = Field(min_length=1, max_length=200)
    applicant: dict[str, str | int | float | bool] = Field(max_length=40)


class InsurancePurchaseRequest(Action):
    quote_id: str = Field(min_length=1, max_length=200)
    terms_version: str = Field(min_length=1, max_length=120)


def _provider(name: str, capability: str):
    provider = providers.get(name, capability)
    if provider is None:
        raise HTTPException(503, {"code": "provider_unavailable", "message":
                                 f"No configured provider supports {capability.replace('_', ' ')}."})
    return provider


async def _grant(user: User, purpose: str, action: Action, request: Request) -> None:
    if not consent.is_active(user.subject, "conversation"):
        raise HTTPException(403, {"code": "requires", "message": "Conversation consent is required first.",
                                  "purpose": "conversation"})
    if not action.confirmed:
        raise HTTPException(409, {"code": "confirmation_required", "message":
                                  "The user must review the provider and the request, then confirm this action."})
    try:
        await consents.set_consent(user, purpose, True, channel="api", version=action.consent_version,
                                   ip=client_ip(request.scope),
                                   details={"provider": action.provider, "action": request.url.path,
                                            "confirmed": True})
    except consents.ConsentError as exc:
        if exc.code == "stale_version":
            detail = {"code": exc.code, "message": exc.message, "current": consent.required(purpose)}
            raise HTTPException(409, detail) from exc
        status = 409 if exc.code == "requires" else 404 if exc.code == "unknown_purpose" else 400
        raise HTTPException(status, {"code": exc.code, "message": exc.message}) from exc


def _object(result: Any) -> dict:
    if not isinstance(result, dict):
        raise HTTPException(502, "The configured provider returned an invalid response.")
    return result


def _https_url(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(502, "The configured provider returned an invalid link.")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise HTTPException(502, "The configured provider returned a non-HTTPS link.")
    return value


@router.get("/providers")
async def provider_capabilities(user: User = Depends(current_user)):
    return {"items": providers.capabilities()}


@router.get("/events")
async def my_financial_events(user: User = Depends(current_user)):
    return {"items": await store.list_for(user.id)}


@router.post("/credit-check", status_code=201)
async def credit_check(body: CreditCheckRequest, request: Request, user: User = Depends(current_user)):
    """Fetch a score through an explicitly authorised bureau adapter; only the provider reference is retained."""
    provider = _provider(body.provider, "credit_check")
    await _grant(user, "credit_bureau", body, request)
    try:
        result = _object(await provider.credit_check(user, body.identity.model_dump()))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "The credit-bureau request failed. Try again shortly.") from exc
    score = result.get("score")
    if score is not None and (isinstance(score, bool) or not isinstance(score, int) or not 300 <= score <= 900):
        raise HTTPException(502, "The provider returned an invalid credit score.")
    reference = result.get("reference")
    if not isinstance(reference, str) or not reference or len(reference) > 200:
        raise HTTPException(502, "The provider returned no valid credit-check reference.")
    status = result.get("score_status", "scored" if score is not None else "unavailable")
    if status not in ("scored", "NA", "NH", "unavailable"):
        raise HTTPException(502, "The provider returned an invalid score status.")
    event = await store.add(user.id, "credit_check", body.provider, reference, status)
    return {"id": str(event["id"]), "provider": body.provider, "bureau": result.get("bureau", "TransUnion CIBIL"),
            "score": score, "score_status": status, "checked_at": result.get("checked_at"),
            "approval_note": "The lender decides eligibility and approval; a bureau score is only one input."}


@router.post("/loan/offers")
async def loan_offers(body: LoanOffersRequest, request: Request, user: User = Depends(current_user)):
    """Request offers only after this user's recent bureau check with the same provider."""
    event = await store.get(user.id, body.credit_check_id)
    if not event or event["kind"] != "credit_check" or event["provider"] != body.provider:
        raise HTTPException(404, "No matching credit check was found for this account and provider.")
    checked_at = event["created_at"]
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - checked_at > timedelta(days=1) or not consent.is_active(user.subject, "credit_bureau"):
        raise HTTPException(409, {"code": "credit_check_expired", "message":
                                  "A fresh, consented credit check is required before requesting loan offers."})
    provider = _provider(body.provider, "loan_offers")
    await _grant(user, "financial_application", body, request)
    try:
        result = _object(await provider.loan_offers(
            user, {"amount_inr": body.amount_inr, "tenure_months": body.tenure_months, "purpose": body.purpose},
            event["provider_reference"]))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "The lender offer request failed. Try again shortly.") from exc
    offers = result.get("offers")
    if not isinstance(offers, list) or len(offers) > 20:
        raise HTTPException(502, "The configured lender returned invalid offers.")
    safe = []
    for offer in offers:
        if not isinstance(offer, dict):
            raise HTTPException(502, "The configured lender returned an invalid offer.")
        clean = dict(offer)
        for field in ("kfs_url", "terms_url"):
            if field in clean:
                clean[field] = _https_url(clean[field])
        safe.append(clean)
    return {"provider": body.provider, "offers": safe, "count": len(safe), "disclaimer":
            "These are lender-provided offers. Review the Key Facts Statement and all terms; only the lender decides approval."}


@router.post("/loan/apply", status_code=201)
async def apply_for_loan(body: LoanApplicationRequest, request: Request, user: User = Depends(current_user)):
    if not body.kfs_accepted:
        raise HTTPException(409, {"code": "kfs_acceptance_required", "message":
                                  "The user must review and accept the lender's current Key Facts Statement."})
    provider = _provider(body.provider, "loan_apply")
    await _grant(user, "financial_application", body, request)
    try:
        result = _object(await provider.loan_apply(user, {
            "offer_id": body.offer_id, "kfs_version": body.kfs_version,
            "applicant": body.applicant,
        }))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "The loan application could not be submitted. Try again shortly.") from exc
    reference, status = result.get("reference"), result.get("status")
    if not isinstance(reference, str) or not reference or status not in ("submitted", "pending", "approved", "declined"):
        raise HTTPException(502, "The lender returned an invalid application result.")
    event = await store.add(user.id, "loan_application", body.provider, reference, status)
    return {"id": str(event["id"]), "provider": body.provider, "status": status,
            "message": "The lender is responsible for the decision and will provide the application documents."}


@router.post("/insurance/quotes")
async def insurance_quotes(body: InsuranceQuoteRequest, request: Request, user: User = Depends(current_user)):
    provider = _provider(body.provider, "insurance_quotes")
    await _grant(user, "financial_application", body, request)
    try:
        result = _object(await provider.insurance_quotes(user, {"product_id": body.product_id,
                                                                 "applicant": body.applicant}))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "The insurer quote request failed. Try again shortly.") from exc
    quotes = result.get("quotes")
    if not isinstance(quotes, list) or len(quotes) > 20:
        raise HTTPException(502, "The configured insurer returned invalid quotes.")
    safe = []
    for quote in quotes:
        if not isinstance(quote, dict):
            raise HTTPException(502, "The configured insurer returned an invalid quote.")
        clean = dict(quote)
        for field in ("terms_url", "checkout_url"):
            if field in clean:
                clean[field] = _https_url(clean[field])
        safe.append(clean)
    return {"provider": body.provider, "quotes": safe, "count": len(safe),
            "disclaimer": "Quotes are subject to the insurer's underwriting and final policy wording."}


@router.post("/insurance/purchase", status_code=201)
async def purchase_insurance(body: InsurancePurchaseRequest, request: Request, user: User = Depends(current_user)):
    provider = _provider(body.provider, "insurance_purchase")
    await _grant(user, "financial_application", body, request)
    try:
        result = _object(await provider.insurance_purchase(user, {
            "quote_id": body.quote_id, "terms_version": body.terms_version,
        }))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "The insurer purchase request failed. Try again shortly.") from exc
    reference, status = result.get("reference"), result.get("status")
    if not isinstance(reference, str) or not reference or status not in ("redirect_required", "pending", "issued"):
        raise HTTPException(502, "The insurer returned an invalid purchase result.")
    event = await store.add(user.id, "insurance_application", body.provider, reference, status)
    return {"id": str(event["id"]), "provider": body.provider, "status": status,
            "checkout_url": _https_url(result.get("checkout_url")),
            "message": "Coverage begins only when the insurer confirms policy issuance and the policy terms."}
