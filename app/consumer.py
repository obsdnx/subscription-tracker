"""Kafka consumer — processes 'charges' messages, records charges, advances billing dates.

Run directly:
    python -m app.consumer

For each message the consumer:
  1. Inserts a row into the charges table (subscription_id, amount, charged_on, status=settled).
  2. Advances that subscription's next_billing_date by one billing cycle using
     the same pure billing.next_billing_date() function used everywhere else.

process_charge() is extracted so it can be called from tests without needing a
running Kafka broker — just pass a dict with the same shape as a Kafka message.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date

from app.billing import BillingCycle, next_billing_date
from app.db import SessionLocal
from app.models import BillingCycleModel, Charge, ChargeStatus, Subscription

KAFKA_BROKER: str = os.getenv("KAFKA_BROKER", "localhost:9092")
TOPIC: str = "charges"
GROUP_ID: str = "subscription-tracker-consumer"

log = logging.getLogger(__name__)


def process_charge(data: dict) -> None:
    """Apply a single charge message to the database.

    Idempotency note: a duplicate message would insert a second Charge row.
    A production version would add a unique constraint on (subscription_id,
    charged_on) or use a message-id dedup table.
    """
    db = SessionLocal()
    try:
        sub_id = data["subscription_id"]
        sub: Subscription | None = db.get(Subscription, sub_id)
        if sub is None:
            log.warning("Received charge for unknown subscription %s — skipping.", sub_id)
            return

        charge = Charge(
            subscription_id=sub.id,
            amount=data["amount"],
            charged_on=date.fromisoformat(data["occurred_on"]),
            status=ChargeStatus.settled,
        )
        db.add(charge)

        cycle = BillingCycle(sub.billing_cycle.value)
        sub.next_billing_date = next_billing_date(sub.next_billing_date, cycle)

        db.commit()
        log.info(
            "Charged sub %s (£%.2f); next billing: %s",
            sub.id, data["amount"], sub.next_billing_date,
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def run() -> None:
    """Subscribe to 'charges' and process messages until interrupted."""
    from kafka import KafkaConsumer  # deferred — only needed when actually running

    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=KAFKA_BROKER,
        group_id=GROUP_ID,
        value_deserializer=lambda v: json.loads(v.decode()),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
    )
    log.info("Consumer started — listening on topic '%s'.", TOPIC)

    for message in consumer:
        try:
            process_charge(message.value)
        except Exception as exc:
            log.error("Failed to process message: %s — %s", message.value, exc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run()
