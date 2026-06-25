"""Kafka producer — reads from any TransactionSource and publishes to 'charges'.

Run directly:
    python -m app.producer

The producer is intentionally stateless: it fetches, publishes, flushes, and
exits.  Scheduling (cron / Airflow) is handled externally so this module stays
easy to test in isolation by mocking KafkaProducer.
"""

from __future__ import annotations

import json
import logging
import os
import sys

from kafka import KafkaProducer

from app.sources import TransactionSource

KAFKA_BROKER: str = os.getenv("KAFKA_BROKER", "localhost:9092")
TOPIC: str = "charges"

log = logging.getLogger(__name__)


def publish(source: TransactionSource, broker: str = KAFKA_BROKER) -> int:
    """Fetch transactions from *source* and publish each to Kafka.

    Returns the number of messages sent.  Raises on connection failure so the
    caller (or scheduler) can decide whether to retry.
    """
    transactions = source.fetch()
    if not transactions:
        log.info("No due transactions found — nothing to publish.")
        return 0

    producer = KafkaProducer(
        bootstrap_servers=broker,
        value_serializer=lambda v: json.dumps(v).encode(),
    )

    count = 0
    for tx in transactions:
        payload = {
            "subscription_id": tx.subscription_id,
            "merchant": tx.merchant,
            "amount": tx.amount,
            "currency": tx.currency,
            "occurred_on": tx.occurred_on.isoformat(),
        }
        producer.send(TOPIC, payload)
        log.info("Published charge for sub %s (%s %.2f)", tx.subscription_id, tx.currency, tx.amount)
        count += 1

    producer.flush()
    producer.close()
    return count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    from app.db import SessionLocal
    from app.sources import SimulatedSource

    db = SessionLocal()
    try:
        sent = publish(SimulatedSource(db))
        print(f"Published {sent} charge(s).")
    finally:
        db.close()
