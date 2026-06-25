"""Pydantic v2 request/response schemas.

Keeping schemas separate from ORM models means the API contract can evolve
independently of the database shape — a common source of friction in monoliths
that mix the two.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.billing import BillingCycle
from app.models import ChargeStatus, SubscriptionStatus


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------


class SubscriptionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    cost: float = Field(..., gt=0, description="Must be a positive amount")
    currency: str = Field(default="GBP", min_length=3, max_length=3)
    billing_cycle: BillingCycle
    next_billing_date: date
    category: str = Field(default="uncategorised", max_length=100)

    @field_validator("currency")
    @classmethod
    def currency_upper(cls, v: str) -> str:
        return v.upper()


class SubscriptionPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    cost: Optional[float] = Field(default=None, gt=0)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    billing_cycle: Optional[BillingCycle] = None
    next_billing_date: Optional[date] = None
    category: Optional[str] = Field(default=None, max_length=100)
    status: Optional[SubscriptionStatus] = None

    @field_validator("currency")
    @classmethod
    def currency_upper(cls, v: Optional[str]) -> Optional[str]:
        return v.upper() if v else v


class SubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    cost: float
    currency: str
    billing_cycle: BillingCycle
    next_billing_date: date
    category: str
    status: SubscriptionStatus
    created_at: datetime


# ---------------------------------------------------------------------------
# Charge
# ---------------------------------------------------------------------------


class ChargeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subscription_id: int
    amount: float
    charged_on: date
    status: ChargeStatus


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


class CategorySpend(BaseModel):
    category: str
    monthly_equivalent: float


class MonthlySpendResponse(BaseModel):
    total_monthly: float
    by_category: list[CategorySpend]
