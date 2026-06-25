"""Tests for billing.py — written before the implementation (TDD).

Every edge case in the spec is covered here:
- monthly rollover at month boundaries, including Feb 28/29 clamping
- yearly rollover with Feb 29 -> Feb 28 on non-leap target years
- weekly across month and year boundaries
"""

from datetime import date

import pytest

from app.billing import BillingCycle, next_billing_date, upcoming_within


# ---------------------------------------------------------------------------
# next_billing_date — weekly
# ---------------------------------------------------------------------------


def test_weekly_simple():
    assert next_billing_date(date(2024, 3, 1), BillingCycle.weekly) == date(2024, 3, 8)


def test_weekly_across_month_boundary():
    assert next_billing_date(date(2024, 1, 29), BillingCycle.weekly) == date(2024, 2, 5)


def test_weekly_across_year_boundary():
    assert next_billing_date(date(2024, 12, 30), BillingCycle.weekly) == date(2025, 1, 6)


# ---------------------------------------------------------------------------
# next_billing_date — monthly
# ---------------------------------------------------------------------------


def test_monthly_simple():
    assert next_billing_date(date(2024, 3, 15), BillingCycle.monthly) == date(2024, 4, 15)


def test_monthly_year_rollover():
    assert next_billing_date(date(2024, 12, 10), BillingCycle.monthly) == date(2025, 1, 10)


def test_monthly_jan31_to_feb28_non_leap():
    # 2023 is not a leap year; Feb has 28 days.
    assert next_billing_date(date(2023, 1, 31), BillingCycle.monthly) == date(2023, 2, 28)


def test_monthly_jan31_to_feb29_leap_year():
    # 2024 is a leap year; Feb has 29 days.
    assert next_billing_date(date(2024, 1, 31), BillingCycle.monthly) == date(2024, 2, 29)


def test_monthly_mar31_to_apr30():
    # April only has 30 days.
    assert next_billing_date(date(2024, 3, 31), BillingCycle.monthly) == date(2024, 4, 30)


def test_monthly_may31_to_jun30():
    assert next_billing_date(date(2024, 5, 31), BillingCycle.monthly) == date(2024, 6, 30)


def test_monthly_oct31_to_nov30():
    assert next_billing_date(date(2024, 10, 31), BillingCycle.monthly) == date(2024, 11, 30)


# ---------------------------------------------------------------------------
# next_billing_date — yearly
# ---------------------------------------------------------------------------


def test_yearly_simple():
    assert next_billing_date(date(2024, 6, 15), BillingCycle.yearly) == date(2025, 6, 15)


def test_yearly_feb29_to_feb28_non_leap():
    # 2024 is a leap year, 2025 is not — Feb 29 must clamp to Feb 28.
    assert next_billing_date(date(2024, 2, 29), BillingCycle.yearly) == date(2025, 2, 28)


def test_yearly_feb28_non_leap_to_feb28():
    # Feb 28 in a non-leap year should stay Feb 28 in the next year.
    assert next_billing_date(date(2023, 2, 28), BillingCycle.yearly) == date(2024, 2, 28)


def test_yearly_across_century():
    assert next_billing_date(date(2099, 11, 1), BillingCycle.yearly) == date(2100, 11, 1)


# ---------------------------------------------------------------------------
# upcoming_within
# ---------------------------------------------------------------------------


def test_upcoming_within_today():
    today = date(2024, 3, 1)
    assert upcoming_within(today, today, 7) is True


def test_upcoming_within_last_day():
    today = date(2024, 3, 1)
    assert upcoming_within(date(2024, 3, 8), today, 7) is True


def test_upcoming_within_outside_window():
    today = date(2024, 3, 1)
    assert upcoming_within(date(2024, 3, 9), today, 7) is False


def test_upcoming_within_past_date():
    today = date(2024, 3, 5)
    assert upcoming_within(date(2024, 3, 4), today, 7) is False
