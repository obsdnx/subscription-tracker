"""API integration tests using FastAPI TestClient.

Each test gets a fresh in-memory SQLite database via the get_db dependency
override.  StaticPool is used so every connection within a test shares the
same in-memory database — without it each new connection would see an empty
schema because SQLite in-memory databases are connection-scoped.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Base


# ---------------------------------------------------------------------------
# Test database fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """Yield a TestClient backed by a fresh in-memory SQLite database."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_sub(client: TestClient, **overrides) -> dict:
    payload = {
        "name": "Netflix",
        "cost": 9.99,
        "billing_cycle": "monthly",
        "next_billing_date": str(date.today() + timedelta(days=5)),
        "category": "entertainment",
    }
    payload.update(overrides)
    resp = client.post("/subscriptions", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_subscription(client):
    data = _create_sub(client)
    assert data["name"] == "Netflix"
    assert data["cost"] == 9.99
    assert data["currency"] == "GBP"
    assert data["status"] == "active"
    assert data["category"] == "entertainment"
    assert "id" in data


def test_create_subscription_defaults(client):
    data = _create_sub(client, category="uncategorised")
    assert data["category"] == "uncategorised"
    assert data["currency"] == "GBP"


def test_create_subscription_custom_currency(client):
    data = _create_sub(client, currency="usd")
    # validator should upper-case it
    assert data["currency"] == "USD"


# ---------------------------------------------------------------------------
# Validation rejection
# ---------------------------------------------------------------------------


def test_create_rejects_zero_cost(client):
    resp = client.post(
        "/subscriptions",
        json={
            "name": "Bad",
            "cost": 0,
            "billing_cycle": "monthly",
            "next_billing_date": str(date.today()),
        },
    )
    assert resp.status_code == 422


def test_create_rejects_negative_cost(client):
    resp = client.post(
        "/subscriptions",
        json={
            "name": "Bad",
            "cost": -5,
            "billing_cycle": "monthly",
            "next_billing_date": str(date.today()),
        },
    )
    assert resp.status_code == 422


def test_create_rejects_missing_name(client):
    resp = client.post(
        "/subscriptions",
        json={
            "cost": 9.99,
            "billing_cycle": "monthly",
            "next_billing_date": str(date.today()),
        },
    )
    assert resp.status_code == 422


def test_create_rejects_bad_billing_cycle(client):
    resp = client.post(
        "/subscriptions",
        json={
            "name": "Bad",
            "cost": 9.99,
            "billing_cycle": "fortnightly",
            "next_billing_date": str(date.today()),
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# List + filter
# ---------------------------------------------------------------------------


def test_list_subscriptions(client):
    _create_sub(client, name="A")
    _create_sub(client, name="B")
    data = client.get("/subscriptions").json()
    assert len(data) == 2


def test_list_filter_by_status(client):
    sub = _create_sub(client, name="Active")
    _create_sub(client, name="ToBeCancelled")
    # Cancel the second one
    second = client.get("/subscriptions").json()
    second_id = next(s["id"] for s in second if s["name"] == "ToBeCancelled")
    client.patch(f"/subscriptions/{second_id}", json={"status": "cancelled"})

    active = client.get("/subscriptions?status=active").json()
    assert all(s["status"] == "active" for s in active)
    assert len(active) == 1

    cancelled = client.get("/subscriptions?status=cancelled").json()
    assert len(cancelled) == 1


def test_list_filter_by_category(client):
    _create_sub(client, category="streaming")
    _create_sub(client, category="utilities")
    data = client.get("/subscriptions?category=streaming").json()
    assert len(data) == 1
    assert data[0]["category"] == "streaming"


# ---------------------------------------------------------------------------
# Get single
# ---------------------------------------------------------------------------


def test_get_subscription(client):
    created = _create_sub(client)
    fetched = client.get(f"/subscriptions/{created['id']}").json()
    assert fetched["id"] == created["id"]
    assert fetched["name"] == "Netflix"


def test_get_subscription_404(client):
    resp = client.get("/subscriptions/9999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Patch / cancel
# ---------------------------------------------------------------------------


def test_patch_subscription_cost(client):
    sub = _create_sub(client)
    resp = client.patch(f"/subscriptions/{sub['id']}", json={"cost": 12.99})
    assert resp.status_code == 200
    assert resp.json()["cost"] == 12.99


def test_cancel_subscription(client):
    sub = _create_sub(client)
    resp = client.patch(f"/subscriptions/{sub['id']}", json={"status": "cancelled"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_patch_nonexistent_subscription(client):
    resp = client.patch("/subscriptions/9999", json={"cost": 5.00})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def test_delete_subscription(client):
    sub = _create_sub(client)
    resp = client.delete(f"/subscriptions/{sub['id']}")
    assert resp.status_code == 204
    assert client.get(f"/subscriptions/{sub['id']}").status_code == 404


def test_delete_nonexistent_subscription(client):
    resp = client.delete("/subscriptions/9999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Upcoming window
# ---------------------------------------------------------------------------


def test_upcoming_within_window(client):
    today = date.today()
    _create_sub(client, name="SoonDue", next_billing_date=str(today + timedelta(days=3)))
    _create_sub(client, name="FarDue", next_billing_date=str(today + timedelta(days=30)))

    data = client.get("/subscriptions/upcoming?days=7").json()
    names = [s["name"] for s in data]
    assert "SoonDue" in names
    assert "FarDue" not in names


def test_upcoming_excludes_cancelled(client):
    today = date.today()
    sub = _create_sub(client, next_billing_date=str(today + timedelta(days=2)))
    client.patch(f"/subscriptions/{sub['id']}", json={"status": "cancelled"})

    data = client.get("/subscriptions/upcoming?days=7").json()
    assert all(s["status"] == "active" for s in data)


def test_upcoming_default_days(client):
    today = date.today()
    _create_sub(client, next_billing_date=str(today + timedelta(days=5)))
    data = client.get("/subscriptions/upcoming").json()
    assert len(data) == 1


# ---------------------------------------------------------------------------
# Analytics — monthly spend
# ---------------------------------------------------------------------------


def test_monthly_spend_empty(client):
    data = client.get("/analytics/monthly-spend").json()
    assert data["total_monthly"] == 0.0
    assert data["by_category"] == []


def test_monthly_spend_monthly_sub(client):
    _create_sub(client, cost=10.0, billing_cycle="monthly", category="streaming")
    data = client.get("/analytics/monthly-spend").json()
    assert data["total_monthly"] == 10.0


def test_monthly_spend_yearly_normalised(client):
    """A yearly sub at £120/year must appear as £10/month."""
    _create_sub(client, cost=120.0, billing_cycle="yearly", category="tools")
    data = client.get("/analytics/monthly-spend").json()
    assert data["total_monthly"] == pytest.approx(10.0, rel=1e-3)
    cat = data["by_category"][0]
    assert cat["category"] == "tools"
    assert cat["monthly_equivalent"] == pytest.approx(10.0, rel=1e-3)


def test_monthly_spend_weekly_normalised(client):
    """Weekly cost × 52 / 12 ≈ monthly equivalent."""
    _create_sub(client, cost=1.0, billing_cycle="weekly", category="gym")
    data = client.get("/analytics/monthly-spend").json()
    expected = 1.0 * 52 / 12
    assert data["total_monthly"] == pytest.approx(expected, rel=1e-3)


def test_monthly_spend_by_category(client):
    _create_sub(client, cost=10.0, billing_cycle="monthly", category="streaming")
    _create_sub(client, cost=5.0, billing_cycle="monthly", category="streaming")
    _create_sub(client, cost=20.0, billing_cycle="monthly", category="utilities")
    data = client.get("/analytics/monthly-spend").json()
    assert data["total_monthly"] == pytest.approx(35.0, rel=1e-3)
    cats = {c["category"]: c["monthly_equivalent"] for c in data["by_category"]}
    assert cats["streaming"] == pytest.approx(15.0, rel=1e-3)
    assert cats["utilities"] == pytest.approx(20.0, rel=1e-3)


def test_monthly_spend_excludes_cancelled(client):
    sub = _create_sub(client, cost=50.0, billing_cycle="monthly")
    client.patch(f"/subscriptions/{sub['id']}", json={"status": "cancelled"})
    data = client.get("/analytics/monthly-spend").json()
    assert data["total_monthly"] == 0.0
