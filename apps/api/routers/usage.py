from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import config
from auth import store
from auth.deps import current_user, require_role
from usage import ledger

router = APIRouter(tags=["Usage"])


class BudgetUpdate(BaseModel):
    budget_usd: Optional[float] = Field(None, ge=0, le=100000, description="Dollars per month; null goes back to the default")


@router.get("/users/me/usage")
async def my_usage(user: store.User = Depends(current_user)):
    """What the signed-in person has spent this month on model, speech-to-text and text-to-speech calls, against their
    monthly limit, and what the spend was on. Figures are estimates from configured prices, not an invoice."""
    return await ledger.summary(user.id)


@router.get("/admin/usage")
async def spenders(limit: int = Query(20, ge=1, le=200), _: store.User = Depends(require_role("admin"))):
    """This month's biggest spenders, with their limits."""
    return {"default_budget_usd": config.USER_BUDGET_USD, "period": ledger.period()[0].isoformat(),
            "items": await ledger.top_spenders(limit)}


@router.patch("/admin/users/{user_id}/budget")
async def set_budget(user_id: str, body: BudgetUpdate, _: store.User = Depends(require_role("admin"))):
    """Give one person a different monthly limit (or `null` for the default)."""
    if await store.get_user(user_id) is None or not await ledger.set_budget(user_id, body.budget_usd):
        raise HTTPException(404, "No such user.")
    return await ledger.summary(user_id)
