import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _safe_label(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Labels cannot be blank.")
    digits = re.sub(r"\D", "", value)
    if 12 <= len(digits) <= 19 or re.search(r"\b(?:cvv|cvc|security code|pin|password)\b\D*\d{3,}", value, re.I):
        raise ValueError("Labels cannot contain a full card number or long account identifier.")
    return value


class CreditCardRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)
    last_four: Optional[str] = Field(None, pattern=r"^\d{4}$")
    outstanding_balance: int = Field(ge=0, le=100_000_000)
    minimum_due: Optional[int] = Field(None, ge=0, le=100_000_000)
    due_day: Optional[int] = Field(None, ge=1, le=31)
    annual_interest_rate_percent: Optional[float] = Field(None, ge=0, le=100, allow_inf_nan=False)

    @field_validator("label")
    @classmethod
    def label_is_safe(cls, value: str) -> str:
        return _safe_label(value)


class LoanRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=100)
    monthly_emi: int = Field(ge=0, le=100_000_000)
    outstanding_principal: int = Field(ge=0, le=1_000_000_000)
    due_day: Optional[int] = Field(None, ge=1, le=31)
    annual_interest_rate_percent: Optional[float] = Field(None, ge=0, le=60, allow_inf_nan=False)
    remaining_months: Optional[int] = Field(None, ge=0, le=600)

    @field_validator("label")
    @classmethod
    def label_is_safe(cls, value: str) -> str:
        return _safe_label(value)


class InventoryReplacement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credit_cards: list[CreditCardRecord] = Field(max_length=20)
    loans: list[LoanRecord] = Field(max_length=20)
    confirmed: bool = False

    @model_validator(mode="after")
    def bounded_total(self):
        if len(self.credit_cards) + len(self.loans) > 30:
            raise ValueError("The financial inventory can contain at most 30 items.")
        return self
