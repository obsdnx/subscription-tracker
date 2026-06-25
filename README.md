# Subscription Tracker

A production-grade REST API for tracking recurring subscriptions, built to demonstrate clean backend engineering: test-first development, layered architecture, event-driven charge processing, and a database-agnostic data layer.

**Stack:** Python 3.12 · FastAPI · SQLAlchemy 2.0 · Pydantic v2 · Kafka · PostgreSQL · Docker

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Getting Started](#getting-started)
- [API Reference](#api-reference)
- [Event Pipeline](#event-pipeline)
- [Testing](#testing)
- [Design Decisions](#design-decisions)
- [Roadmap](#roadmap)

---

## Features

- **Subscription management** — create, update, cancel, and delete recurring subscriptions
- **Billing date prediction** — calculates next charge date for weekly, monthly, and yearly cycles with correct calendar edge-case handling (Jan 31 → Feb 28, leap years, year boundaries)
- **Upcoming charges** — query which subscriptions are due within N days
- **Monthly spend analytics** — normalises all billing cycles to a monthly equivalent, broken down by category
- **Event-driven pipeline** — a Kafka producer/consumer that records charges and auto-advances billing dates
- **Web UI** — a clean single-page interface for the full subscription lifecycle
- **Dual database support** — SQLite (zero setup, used in all tests) or PostgreSQL (Docker Compose)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Client / Browser                        │
│                    http://localhost:8000                         │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI  (app/main.py)                     │
│                                                                 │
│  POST /subscriptions        GET /subscriptions/upcoming         │
│  GET  /subscriptions        PATCH /subscriptions/{id}           │
│  GET  /subscriptions/{id}   DELETE /subscriptions/{id}          │
│  GET  /analytics/monthly-spend                                  │
└──────────┬──────────────────────────┬───────────────────────────┘
           │                          │
           ▼                          ▼
┌──────────────────┐      ┌───────────────────────┐
│  app/billing.py  │      │   app/models.py        │
│  (pure functions)│      │   SQLAlchemy 2.0 ORM   │
│                  │      │                        │
│  next_billing_   │      │   Subscription         │
│  date()          │      │   Charge               │
│  upcoming_       │      └──────────┬─────────────┘
│  within()        │                 │
└──────────────────┘                 ▼
                          ┌───────────────────────┐
                          │   app/db.py            │
                          │   DATABASE_URL from env│
                          │   SQLite  │  Postgres  │
                          └───────────────────────┘
```

### Project layout

```
app/
├── main.py        FastAPI app and all endpoints
├── billing.py     Pure date arithmetic — no I/O, fully unit-testable
├── models.py      SQLAlchemy 2.0 ORM (Mapped[T] / mapped_column syntax)
├── schemas.py     Pydantic v2 request/response models
├── db.py          Engine, session factory, DATABASE_URL from env
├── sources.py     TransactionSource ABC + ManualSource + SimulatedSource
├── producer.py    Kafka producer — publishes due charges to "charges" topic
├── consumer.py    Kafka consumer — records charges, advances billing dates
└── static/
    └── index.html Single-page web UI

tests/
├── test_billing.py   18 unit tests for date edge cases (TDD — written first)
├── test_api.py       26 integration tests via FastAPI TestClient
├── test_sources.py   8 tests for SimulatedSource DB queries
└── test_kafka.py     10 tests for producer/consumer (Kafka mocked)
```

---

## Getting Started

### Local — SQLite, no services required

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

- UI: <http://localhost:8000>
- Interactive API docs: <http://localhost:8000/docs>
- Database: auto-created at `./subscriptions.db`

### Docker Compose — PostgreSQL + Kafka

```bash
docker compose up --build
```

This starts PostgreSQL and the API service wired together via `DATABASE_URL`. The database schema is created automatically on first boot.

To also run the event pipeline (producer + consumer):

```bash
docker compose --profile billing up
```

### Running the Kafka pipeline locally

```bash
# Publish charges for all subscriptions due today
python -m app.producer

# Start the consumer loop (records charges, advances billing dates)
python -m app.consumer
```

Both read `KAFKA_BROKER` from the environment (default: `localhost:9092`).

---

## API Reference

| Method   | Path                        | Description                                           |
|----------|-----------------------------|-------------------------------------------------------|
| `POST`   | `/subscriptions`            | Create a subscription                                 |
| `GET`    | `/subscriptions`            | List all; filter with `?status=` and/or `?category=` |
| `GET`    | `/subscriptions/upcoming`   | Active subs due within `?days=7`                      |
| `GET`    | `/subscriptions/{id}`       | Fetch one — 404 if not found                          |
| `PATCH`  | `/subscriptions/{id}`       | Edit any field, or set `status: cancelled`            |
| `DELETE` | `/subscriptions/{id}`       | Remove subscription and its charges                   |
| `GET`    | `/analytics/monthly-spend`  | Total monthly spend and per-category breakdown        |

### Create a subscription

```bash
curl -X POST http://localhost:8000/subscriptions \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Netflix",
    "cost": 17.99,
    "billing_cycle": "monthly",
    "next_billing_date": "2026-07-15",
    "category": "streaming"
  }'
```

```json
{
  "id": 1,
  "name": "Netflix",
  "cost": 17.99,
  "currency": "GBP",
  "billing_cycle": "monthly",
  "next_billing_date": "2026-07-15",
  "category": "streaming",
  "status": "active",
  "created_at": "2026-06-25T09:00:00"
}
```

### Upcoming charges

```bash
curl "http://localhost:8000/subscriptions/upcoming?days=7"
```

### Monthly spend analytics

```bash
curl http://localhost:8000/analytics/monthly-spend
```

```json
{
  "total_monthly": 47.99,
  "by_category": [
    { "category": "streaming",  "monthly_equivalent": 29.98 },
    { "category": "tools",      "monthly_equivalent": 10.00 },
    { "category": "health",     "monthly_equivalent":  8.01 }
  ]
}
```

Normalisation rules: `weekly × 52 ÷ 12`, `monthly as-is`, `yearly ÷ 12`.

### Cancel a subscription

```bash
curl -X PATCH http://localhost:8000/subscriptions/1 \
  -H 'Content-Type: application/json' \
  -d '{"status": "cancelled"}'
```

---

## Event Pipeline

The Kafka layer separates charge *detection* from charge *recording*, making each stage independently scalable and replaceable.

```
┌──────────────────────────────────────────────────────────────────┐
│                     Producer  (app/producer.py)                  │
│                                                                  │
│  TransactionSource.fetch()                                       │
│       │                                                          │
│       ├── ManualSource    → []          (no-op, manual entry)   │
│       ├── SimulatedSource → due subs    (queries DB for today)  │
│       └── (future)        → bank feed, CSV, etc.               │
│                                                                  │
│  For each RawTransaction → publish JSON to Kafka "charges" topic │
└───────────────────────────────┬──────────────────────────────────┘
                                │  Kafka  "charges"  topic
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                     Consumer  (app/consumer.py)                  │
│                                                                  │
│  For each message:                                               │
│    1. INSERT into charges (subscription_id, amount,              │
│                            charged_on, status=settled)           │
│    2. UPDATE subscription.next_billing_date                      │
│       via billing.next_billing_date(current, cycle)              │
└──────────────────────────────────────────────────────────────────┘
```

Adding a new source (CSV import, Plaid webhook, Nordigen feed) means writing one new `TransactionSource` subclass — the producer, consumer, billing logic, and API are untouched.

---

## Testing

```bash
pytest -v
```

```
62 passed in 0.73s
```

All tests run against an in-memory SQLite database using SQLAlchemy's `StaticPool` — no running services required.

| Suite              | Tests | What's covered                                                   |
|--------------------|-------|------------------------------------------------------------------|
| `test_billing`     |  18   | Every date edge case: Feb 28/29, Jan 31, year boundaries        |
| `test_api`         |  26   | Full CRUD, validation (cost ≤ 0 → 422), filters, 404s, analytics|
| `test_sources`     |   8   | SimulatedSource: due/overdue included, future/cancelled excluded |
| `test_kafka`       |  10   | Producer sends correct payloads; consumer inserts charges and advances dates |

### Edge cases explicitly tested

```
monthly:  Jan 31  → Feb 28  (non-leap year)
monthly:  Jan 31  → Feb 29  (leap year, 2024)
monthly:  Mar 31  → Apr 30
yearly:   Feb 29  → Feb 28  (next year is non-leap)
weekly:   Dec 30  → Jan  6  (year boundary)
```

The billing tests were written *before* the implementation — the test suite defined the expected behaviour, then `billing.py` was written to satisfy it.

---

## Design Decisions

### `billing.py` is pure — no I/O, no side effects

All date arithmetic lives in one file with no imports from the rest of the app. This makes it trivially testable (18 tests run in milliseconds, no DB setup) and reusable by any layer — the API, the consumer, and any future scheduler all call the same functions.

### `TransactionSource` — open/closed by design

```python
class TransactionSource(ABC):
    @abstractmethod
    def fetch(self) -> list[RawTransaction]: ...

class ManualSource(TransactionSource):   # → []
class SimulatedSource(TransactionSource):# → active subs due today (from DB)
# Future: CSVSource, PlaidSource, NordigenSource, KafkaSource ...
```

New data sources extend the system without modifying it. The producer only knows about `TransactionSource.fetch()` — it doesn't care whether the transactions came from a bank feed, a CSV, or a simulation.

### SQLAlchemy 2.0 `Mapped[T]` / `mapped_column`

```python
class Subscription(Base):
    id:                Mapped[int]              = mapped_column(primary_key=True)
    name:              Mapped[str]              = mapped_column(String(255))
    cost:              Mapped[float]            = mapped_column(Numeric(12, 2))
    billing_cycle:     Mapped[BillingCycleModel]= mapped_column(Enum(...))
    next_billing_date: Mapped[date]             = mapped_column()
    status:            Mapped[SubscriptionStatus]= mapped_column(...)
```

Column types live in Python annotations — readable by the ORM, mypy, and Pyright without any extra plugins.

### Database-agnostic by default

`DATABASE_URL` is read from the environment. The default (`sqlite:///./subscriptions.db`) means the service runs locally with zero configuration. Swap in a Postgres URL and nothing else changes.

### Kafka consumer is testable without a broker

`process_charge(data: dict)` contains all the business logic — insert a charge, advance the billing date. The Kafka loop in `run()` simply feeds messages to it. Tests call `process_charge` directly, mocking only `SessionLocal`, so the full producer→consumer cycle is verified without any infrastructure.

---

## Roadmap

| Layer | Description |
|-------|-------------|
| **Real transaction source** | Plug in a Nordigen or Plaid adapter as a `TransactionSource` subclass. Auto-detect recurring charges from raw bank transactions. No other code changes. |
| **Airflow DAG** | Nightly job: call `fetch()`, reconcile against known subscriptions, publish to Kafka. Replaces the manual `python -m app.producer` invocation. |
| **Kubernetes + GCP** | Helm chart for the API deployment; Cloud SQL for Postgres; Cloud Pub/Sub as a managed alternative to self-hosted Kafka. |
| **Alerts** | Kafka consumer extension: emit a notification (email, Slack) when a charge lands or when monthly spend exceeds a configured threshold. |
| **Budget tracking** | Per-category spend limits; over-budget warnings surfaced in the analytics endpoint and UI. |
