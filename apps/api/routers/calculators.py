from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth.deps import current_user
from auth.store import User
from loan import calc

router = APIRouter(prefix="/calculators", tags=["Calculators"])


class EmiRequest(BaseModel):
    principal: int = Field(ge=1_000, le=1_000_000_000)
    annual_rate_percent: float = Field(ge=0.1, le=60, allow_inf_nan=False)
    tenure_months: int = Field(ge=1, le=480)


class PrepaymentRequest(EmiRequest):
    prepay_amount: int = Field(gt=0, le=1_000_000_000)
    mode: Literal["reduce_tenure", "reduce_emi"] = "reduce_tenure"


DISCLAIMER = "Estimate using the reducing-balance method. A lender's figure can differ because of rounding, fees, and its day-count rules."


@router.post("/emi")
async def calculate_emi(body: EmiRequest, _: User = Depends(current_user)):
    result = calc.summary(body.principal, body.annual_rate_percent, body.tenure_months)
    return {"kind": "emi", "currency": "INR", "method": "reducing_balance",
            "inputs": body.model_dump(), "result": result, "disclaimer": DISCLAIMER}


@router.post("/prepayment")
async def calculate_prepayment(body: PrepaymentRequest, _: User = Depends(current_user)):
    try:
        result = calc.prepayment(body.principal, body.annual_rate_percent, body.tenure_months,
                                 body.prepay_amount, body.mode)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"kind": "prepayment", "currency": "INR", "method": "reducing_balance",
            "inputs": body.model_dump(), "result": result, "disclaimer": DISCLAIMER}
