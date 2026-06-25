"""Tests for SimulatedSource — verifies which subscriptions are selected as 'due'."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, BillingCycleModel, Subscription, SubscriptionStatus
from app.sources import SimulatedSource


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
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


def _sub(db, name: str, next_date: date, status=SubscriptionStatus.active) -> Subscription:
    s = Subscription(
        name=name,
        cost=9.99,
        currency="GBP",
        billing_cycle=BillingCycleModel.monthly,
        next_billing_date=next_date,
        category="test",
        status=status,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def test_due_today_is_included(db):
    _sub(db, "DueToday", date.today())
    txns = SimulatedSource(db).fetch()
    assert len(txns) == 1
    assert txns[0].merchant == "DueToday"


def test_overdue_is_included(db):
    _sub(db, "Overdue", date.today() - timedelta(days=3))
    txns = SimulatedSource(db).fetch()
    assert len(txns) == 1


def test_future_is_excluded(db):
    _sub(db, "Future", date.today() + timedelta(days=1))
    txns = SimulatedSource(db).fetch()
    assert txns == []


def test_cancelled_is_excluded(db):
    _sub(db, "Cancelled", date.today(), status=SubscriptionStatus.cancelled)
    txns = SimulatedSource(db).fetch()
    assert txns == []


def test_subscription_id_is_set(db):
    sub = _sub(db, "WithId", date.today())
    txns = SimulatedSource(db).fetch()
    assert txns[0].subscription_id == sub.id


def test_fields_map_correctly(db):
    _sub(db, "Netflix", date.today())
    tx = SimulatedSource(db).fetch()[0]
    assert tx.merchant == "Netflix"
    assert tx.amount == pytest.approx(9.99)
    assert tx.currency == "GBP"
    assert tx.occurred_on == date.today()


def test_multiple_due(db):
    _sub(db, "A", date.today())
    _sub(db, "B", date.today() - timedelta(days=1))
    _sub(db, "C", date.today() + timedelta(days=1))  # not due
    txns = SimulatedSource(db).fetch()
    assert len(txns) == 2
    assert {t.merchant for t in txns} == {"A", "B"}


def test_empty_db(db):
    assert SimulatedSource(db).fetch() == []
