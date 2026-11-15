from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth.deps import current_user
from auth.store import User
from services import telemetry
from services.firecrawl import FirecrawlError, FirecrawlUnavailable, search_insurance, search_web
from usage import ledger

router = APIRouter(prefix="/search", tags=["Search"])


class InsuranceSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: Optional[int] = Field(None, ge=1, le=10)


class WebSearchRequest(InsuranceSearchRequest):
    domain: Literal["insurance", "loan"]


async def _search(query: str, domain: str, limit: Optional[int], user: User):
    if not query.strip():
        raise HTTPException(422, "A search query is required.")
    status = await ledger.status(user.id)
    if status["exceeded"]:
        raise HTTPException(402, "The monthly usage budget has been reached.")
    calls: list = []
    channel = telemetry.current_channel.set("text")
    meter = telemetry.current_meter.set(calls)
    try:
        result = await (search_insurance(query, limit) if domain == "insurance" else search_web(query, domain, limit))
    except FirecrawlUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except FirecrawlError as exc:
        raise HTTPException(502, str(exc)) from exc
    finally:
        telemetry.current_meter.reset(meter)
        telemetry.current_channel.reset(channel)
    await ledger.add(user.id, calls)
    return result


@router.post("/insurance")
async def insurance_search(body: InsuranceSearchRequest, user: User = Depends(current_user)):
    return await _search(body.query, "insurance", body.limit, user)


@router.post("/web")
async def web_search(body: WebSearchRequest, user: User = Depends(current_user)):
    return await _search(body.query, body.domain, body.limit, user)
