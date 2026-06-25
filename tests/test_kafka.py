"""Tests for the Kafka producer and consumer layer.

Kafka is mocked so these tests run without a broker.  The consumer's
process_charge() function is tested directly — it contains all the business
logic; the consumer loop itself just feeds messages to it.

Session note: process_charge() calls SessionLocal() to open its own session
and calls db.close() when done.  In tests we patch SessionLocal to return our
in-memory test session.  After process_charge() calls close(), the session is
still usable for new queries but any previously loaded instances are detached,
so we re-query instead of calling db.refresh(instance).
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.billing import BillingCycle, next_billing_date
from app.consumer import process_charge
from app.models import (
    Base, BillingCycleModel, Charge, ChargeStatus, Subscription, SubscriptionStatus,
)
from app.sources import ManualSource, RawTransaction, SimulatedSource


# ---------------------------------------------------------------------------
# Shared DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    # Patch SessionLocal in the consumer so process_charge uses our in-memory DB.
    with patch("app.consumer.SessionLocal", return_value=session):
        yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


def _make_sub(db, name="Netflix", cost=9.99, cycle=BillingCycleModel.monthly,
              next_date=None, status=SubscriptionStatus.active):
    sub = Subscription(
        name=name, cost=cost, currency="GBP",
        billing_cycle=cycle,
        next_billing_date=next_date or date.today(),
        category="test", status=status,
    )
    db.add(sub)
    db.commit()
    return db.get(Subscription, sub.id)  # load with primary key to guarantee persistence


# ---------------------------------------------------------------------------
# Producer tests  (app.producer.KafkaProducer is patchable at module level)
# ---------------------------------------------------------------------------


def test_producer_sends_one_message_per_transaction():
    from app.producer import publish

    tx = RawTransaction(merchant="Netflix", amount=9.99, occurred_on=date.today(),
                        currency="GBP", subscription_id=1)
    source = MagicMock()
    source.fetch.return_value = [tx]

    mock_producer = MagicMock()
    with patch("app.producer.KafkaProducer", return_value=mock_producer):
        count = publish(source, broker="mock:9092")

    assert count == 1
    mock_producer.send.assert_called_once()
    topic, payload = mock_producer.send.call_args[0]
    assert topic == "charges"
    assert payload["subscription_id"] == 1
    assert payload["amount"] == 9.99
    assert payload["merchant"] == "Netflix"
    assert payload["currency"] == "GBP"
    assert payload["occurred_on"] == date.today().isoformat()


def test_producer_flushes_and_closes():
    from app.producer import publish

    source = MagicMock()
    source.fetch.return_value = [
        RawTransaction("X", 1.0, date.today(), "GBP", subscription_id=1)
    ]
    mock_producer = MagicMock()
    with patch("app.producer.KafkaProducer", return_value=mock_producer):
        publish(source, broker="mock:9092")

    mock_producer.flush.assert_called_once()
    mock_producer.close.assert_called_once()


def test_producer_returns_zero_when_nothing_due():
    from app.producer import publish

    source = ManualSource()
    mock_producer = MagicMock()
    with patch("app.producer.KafkaProducer", return_value=mock_producer):
        count = publish(source, broker="mock:9092")

    assert count == 0
    mock_producer.send.assert_not_called()


def test_producer_sends_multiple_messages():
    from app.producer import publish

    txns = [
        RawTransaction("A", 1.0, date.today(), "GBP", subscription_id=1),
        RawTransaction("B", 2.0, date.today(), "GBP", subscription_id=2),
        RawTransaction("C", 3.0, date.today(), "GBP", subscription_id=3),
    ]
    source = MagicMock()
    source.fetch.return_value = txns
    mock_producer = MagicMock()
    with patch("app.producer.KafkaProducer", return_value=mock_producer):
        count = publish(source, broker="mock:9092")

    assert count == 3
    assert mock_producer.send.call_count == 3


# ---------------------------------------------------------------------------
# Consumer tests  (process_charge is tested directly — no Kafka needed)
# ---------------------------------------------------------------------------


def test_process_charge_creates_charge_row(db):
    sub = _make_sub(db, next_date=date.today())
    process_charge({
        "subscription_id": sub.id,
        "merchant": sub.name,
        "amount": float(sub.cost),
        "currency": sub.currency,
        "occurred_on": date.today().isoformat(),
    })

    charge = db.query(Charge).filter_by(subscription_id=sub.id).first()
    assert charge is not None
    assert float(charge.amount) == pytest.approx(9.99)
    assert charge.charged_on == date.today()
    assert charge.status == ChargeStatus.settled


def test_process_charge_advances_monthly_billing_date(db):
    today = date.today()
    sub = _make_sub(db, next_date=today, cycle=BillingCycleModel.monthly)
    sub_id = sub.id
    process_charge({
        "subscription_id": sub_id, "merchant": sub.name,
        "amount": float(sub.cost), "currency": sub.currency,
        "occurred_on": today.isoformat(),
    })

    updated = db.get(Subscription, sub_id)
    assert updated.next_billing_date == next_billing_date(today, BillingCycle.monthly)


def test_process_charge_advances_yearly_billing_date(db):
    today = date.today()
    sub = _make_sub(db, next_date=today, cycle=BillingCycleModel.yearly)
    sub_id = sub.id
    process_charge({
        "subscription_id": sub_id, "merchant": sub.name,
        "amount": float(sub.cost), "currency": sub.currency,
        "occurred_on": today.isoformat(),
    })

    updated = db.get(Subscription, sub_id)
    assert updated.next_billing_date == next_billing_date(today, BillingCycle.yearly)


def test_process_charge_advances_weekly_billing_date(db):
    today = date.today()
    sub = _make_sub(db, next_date=today, cycle=BillingCycleModel.weekly)
    sub_id = sub.id
    process_charge({
        "subscription_id": sub_id, "merchant": sub.name,
        "amount": float(sub.cost), "currency": sub.currency,
        "occurred_on": today.isoformat(),
    })

    updated = db.get(Subscription, sub_id)
    assert updated.next_billing_date == next_billing_date(today, BillingCycle.weekly)


def test_process_charge_unknown_subscription_is_skipped(db):
    process_charge({
        "subscription_id": 9999, "merchant": "Ghost",
        "amount": 5.0, "currency": "GBP",
        "occurred_on": date.today().isoformat(),
    })
    assert db.query(Charge).count() == 0


def test_simulated_source_then_process_charge_full_cycle(db):
    """Integration: SimulatedSource produces → process_charge consumes."""
    today = date.today()
    sub = _make_sub(db, next_date=today)
    sub_id = sub.id

    txns = SimulatedSource(db).fetch()
    assert len(txns) == 1

    process_charge({
        "subscription_id": txns[0].subscription_id,
        "merchant": txns[0].merchant,
        "amount": txns[0].amount,
        "currency": txns[0].currency,
        "occurred_on": txns[0].occurred_on.isoformat(),
    })

    assert db.query(Charge).count() == 1
    updated = db.get(Subscription, sub_id)
    assert updated.next_billing_date == next_billing_date(today, BillingCycle.monthly)
