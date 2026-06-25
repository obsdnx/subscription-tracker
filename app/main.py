"""FastAPI application — routes and dependency wiring."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.billing import BillingCycle, next_billing_date, upcoming_within
from app.db import engine, get_db
from app.models import Base, BillingCycleModel, Subscription, SubscriptionStatus
from app.schemas import (
    CategorySpend,
    MonthlySpendResponse,
    SubscriptionCreate,
    SubscriptionPatch,
    SubscriptionRead,
)

_STATIC = Path(__file__).parent / "static"

# Create tables on startup (idempotent; migrations would replace this in prod).
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Subscription Tracker", version="1.0.0")


@app.get("/", include_in_schema=False)
def serve_ui() -> FileResponse:
    """Serve the single-page UI from app/static/index.html."""
    return FileResponse(_STATIC / "index.html")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_or_404(db: Session, sub_id: int) -> Subscription:
    sub = db.get(Subscription, sub_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return sub


def _monthly_equivalent(cost: float, cycle: BillingCycleModel) -> float:
    """Normalise any billing cycle to a monthly figure."""
    if cycle == BillingCycleModel.weekly:
        return cost * 52 / 12
    if cycle == BillingCycleModel.yearly:
        return cost / 12
    return cost  # monthly


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------


@app.post("/subscriptions", response_model=SubscriptionRead, status_code=201)
def create_subscription(
    payload: SubscriptionCreate, db: Session = Depends(get_db)
) -> Subscription:
    """Create a new subscription and persist it."""
    sub = Subscription(
        name=payload.name,
        cost=payload.cost,
        currency=payload.currency,
        billing_cycle=BillingCycleModel(payload.billing_cycle.value),
        next_billing_date=payload.next_billing_date,
        category=payload.category,
        status=SubscriptionStatus.active,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


@app.get("/subscriptions/upcoming", response_model=list[SubscriptionRead])
def list_upcoming(
    days: int = Query(default=7, ge=0),
    db: Session = Depends(get_db),
) -> list[Subscription]:
    """Return active subscriptions whose next billing date falls within *days* days.

    Declared before /subscriptions/{id} so FastAPI doesn't mistake 'upcoming'
    for an integer id.
    """
    today = date.today()
    subs = db.query(Subscription).filter(
        Subscription.status == SubscriptionStatus.active
    ).all()
    return [s for s in subs if upcoming_within(s.next_billing_date, today, days)]


@app.get("/subscriptions", response_model=list[SubscriptionRead])
def list_subscriptions(
    status: Optional[SubscriptionStatus] = Query(default=None),
    category: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
) -> list[Subscription]:
    """List subscriptions with optional status and category filters."""
    q = db.query(Subscription)
    if status is not None:
        q = q.filter(Subscription.status == status)
    if category is not None:
        q = q.filter(Subscription.category == category)
    return q.all()


@app.get("/subscriptions/{sub_id}", response_model=SubscriptionRead)
def get_subscription(sub_id: int, db: Session = Depends(get_db)) -> Subscription:
    """Fetch a single subscription by id; 404 if not found."""
    return _get_or_404(db, sub_id)


@app.patch("/subscriptions/{sub_id}", response_model=SubscriptionRead)
def patch_subscription(
    sub_id: int, payload: SubscriptionPatch, db: Session = Depends(get_db)
) -> Subscription:
    """Partially update a subscription (e.g. cancel it or correct the cost)."""
    sub = _get_or_404(db, sub_id)
    update_data = payload.model_dump(exclude_unset=True)
    if "billing_cycle" in update_data:
        update_data["billing_cycle"] = BillingCycleModel(update_data["billing_cycle"])
    for field, value in update_data.items():
        setattr(sub, field, value)
    db.commit()
    db.refresh(sub)
    return sub


@app.delete("/subscriptions/{sub_id}", status_code=204)
def delete_subscription(sub_id: int, db: Session = Depends(get_db)) -> None:
    """Permanently remove a subscription and its charges."""
    sub = _get_or_404(db, sub_id)
    db.delete(sub)
    db.commit()


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


@app.get("/analytics/monthly-spend", response_model=MonthlySpendResponse)
def monthly_spend(db: Session = Depends(get_db)) -> MonthlySpendResponse:
    """Return total monthly spend and a per-category breakdown.

    Every cycle is normalised to a monthly equivalent:
      weekly  → cost × 52 / 12
      monthly → cost
      yearly  → cost / 12
    Only active subscriptions are included.
    """
    active_subs = db.query(Subscription).filter(
        Subscription.status == SubscriptionStatus.active
    ).all()

    totals: dict[str, float] = {}
    for sub in active_subs:
        monthly = _monthly_equivalent(float(sub.cost), sub.billing_cycle)
        totals[sub.category] = totals.get(sub.category, 0.0) + monthly

    by_category = [
        CategorySpend(category=cat, monthly_equivalent=round(amount, 2))
        for cat, amount in totals.items()
    ]
    total_monthly = round(sum(totals.values()), 2)

    return MonthlySpendResponse(total_monthly=total_monthly, by_category=by_category)
