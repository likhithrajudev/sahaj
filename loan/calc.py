"""Exact loan arithmetic. The model never computes these: it only reports what this module returns.

Reducing-balance method: interest each month is charged on the balance still owed. A lender's own figure can differ
slightly (rounding, fees, day-count), which the facts say.
"""
import math
from typing import Dict


def emi(principal: float, annual_rate_percent: float, months: int) -> float:
    r = annual_rate_percent / 12 / 100
    if r == 0:
        return principal / months
    growth = (1 + r) ** months
    return principal * r * growth / (growth - 1)


def _run(principal: float, annual_rate_percent: float, payment: float, max_months: int = 1200) -> Dict[str, float]:
    """Pay `payment` a month until the balance is gone. Returns months taken and total interest."""
    r = annual_rate_percent / 12 / 100
    balance, interest, months = principal, 0.0, 0
    while balance > 0.005 and months < max_months:
        charge = balance * r
        if payment <= charge:  # the payment never reduces the balance
            raise ValueError("payment too small to ever repay the loan")
        interest += charge
        balance = balance + charge - payment if balance + charge > payment else 0.0
        months += 1
    return {"months": months, "interest": interest}


def summary(principal: float, annual_rate_percent: float, months: int) -> Dict[str, float]:
    payment = emi(principal, annual_rate_percent, months)
    total = payment * months
    return {"emi": round(payment), "total_payment": round(total), "total_interest": round(total - principal)}


def prepayment(outstanding: float, annual_rate_percent: float, remaining_months: int, prepay: float,
               mode: str = "reduce_tenure") -> Dict[str, float]:
    """Effect of paying `prepay` extra now. `reduce_tenure` keeps the EMI and finishes sooner; `reduce_emi` keeps the
    tenure and lowers the EMI."""
    if not 0 < prepay < outstanding:
        raise ValueError("prepayment must be more than zero and less than the outstanding amount")
    payment = emi(outstanding, annual_rate_percent, remaining_months)
    before = _run(outstanding, annual_rate_percent, payment)
    remaining = outstanding - prepay
    if mode == "reduce_emi":
        new_payment = emi(remaining, annual_rate_percent, remaining_months)
        after = _run(remaining, annual_rate_percent, new_payment)
    else:
        new_payment = payment
        after = _run(remaining, annual_rate_percent, payment)
    return {
        "emi_before": round(payment), "emi_after": round(new_payment),
        "months_before": before["months"], "months_after": after["months"],
        "months_saved": before["months"] - after["months"],
        "interest_before": round(before["interest"]), "interest_after": round(after["interest"]),
        "interest_saved": round(before["interest"] - after["interest"]),
    }
