"""
Billing date arithmetic — pure functions, no I/O.

Keeping date logic here (separate from the ORM and API layers) means every
edge case can be exercised in fast, dependency-free unit tests, and the same
functions can be reused by any future scheduling layer without touching the
web layer.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from enum import Enum


class BillingCycle(str, Enum):
    weekly = "weekly"
    monthly = "monthly"
    yearly = "yearly"


def next_billing_date(current_date: date, cycle: BillingCycle) -> date:
    """Return the next charge date after *current_date* for the given cycle.

    Why clamp instead of raising? Billing systems silently move impossible
    dates (e.g. Feb 30) to the last valid day of the month — that is the
    behaviour users expect and matches what Stripe/GoCardless do.
    """
    if cycle is BillingCycle.weekly:
        return current_date + timedelta(weeks=1)

    if cycle is BillingCycle.monthly:
        year, month, day = current_date.year, current_date.month, current_date.day
        month += 1
        if month > 12:
            month = 1
            year += 1
        # Clamp to the last valid day in the target month.
        day = min(day, calendar.monthrange(year, month)[1])
        return date(year, month, day)

    if cycle is BillingCycle.yearly:
        year, month, day = current_date.year + 1, current_date.month, current_date.day
        # Clamp Feb 29 to Feb 28 when the next year is not a leap year.
        day = min(day, calendar.monthrange(year, month)[1])
        return date(year, month, day)

    raise ValueError(f"Unknown billing cycle: {cycle!r}")  # pragma: no cover


def upcoming_within(next_date: date, today: date, days: int) -> bool:
    """Return True if *next_date* falls within *days* days from *today* (inclusive)."""
    return today <= next_date <= today + timedelta(days=days)
