"""Transaction source abstraction.

Why this seam exists: the tracker currently works with manually entered
subscriptions, but a future version will ingest real transactions from a bank
feed or CSV export and auto-detect recurring charges.  Defining the interface
here means that new adapters (CSV, Plaid, Nordigen, Kafka consumer) can be
added as TransactionSource subclasses without touching the API layer or the
billing logic at all.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class RawTransaction:
    """A single transaction as it arrives from an external source.

    subscription_id is None for sources that don't map directly to a known
    subscription (e.g. a raw bank feed).  SimulatedSource always sets it.
    """

    merchant: str
    amount: float
    occurred_on: date
    currency: str
    subscription_id: Optional[int] = field(default=None)


class TransactionSource(ABC):
    """Abstract base for any data source that can provide raw transactions."""

    @abstractmethod
    def fetch(self) -> list[RawTransaction]:
        """Return a list of raw transactions from this source."""
        ...


class ManualSource(TransactionSource):
    """Null source used when subscriptions are entered manually via the API.

    Returning an empty list means callers that iterate over fetch() work
    correctly with zero special-casing — they just see no transactions.
    """

    def fetch(self) -> list[RawTransaction]:
        return []


class SimulatedSource(TransactionSource):
    """Stand-in for a real bank feed.

    Queries the database for active subscriptions whose next_billing_date is
    on or before today and returns a RawTransaction for each one.  This lets
    the producer/consumer pipeline run without any external data source.

    The DB session is injected so the source stays testable without needing
    a live database URL.
    """

    def __init__(self, db) -> None:  # Session typed loosely to avoid circular import
        self._db = db

    def fetch(self) -> list[RawTransaction]:
        from app.models import Subscription, SubscriptionStatus  # local to avoid circular

        today = date.today()
        due = (
            self._db.query(Subscription)
            .filter(
                Subscription.status == SubscriptionStatus.active,
                Subscription.next_billing_date <= today,
            )
            .all()
        )
        return [
            RawTransaction(
                merchant=sub.name,
                amount=float(sub.cost),
                occurred_on=sub.next_billing_date,
                currency=sub.currency,
                subscription_id=sub.id,
            )
            for sub in due
        ]
