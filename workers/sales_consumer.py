from __future__ import annotations

"""Planned module: sales consumer. Implementation pending."""

"""
ai/workers/sales_consumer.py

Real-time retail sales consumer.

Features:
- POS transaction processing
- Sales and return tracking
- Revenue and quantity aggregation
- Multi-store / multi-SKU analytics
- Idempotent event ingestion
- Durable demand-event outbox
- Outbox publishing through an adapter
- Optional Kafka consumer
- SQLite persistence

Python 3.10+
Optional dependency: kafka-python

Expected event:
{
    "event_id": "sale-001",
    "event_type": "pos.transaction_recorded",
    "occurred_at": "2026-10-26T06:00:00Z",
    "payload": {
        "store_id": "STORE-001",
        "transaction_id": "TX-001",
        "line_id": "LINE-001",
        "sku": "SKU-101",
        "transaction_type": "sale",
        "quantity": 3,
        "unit_price": 120.0,
        "currency": "INR"
    }
}
"""


import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: str) -> str:
    timestamp = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )
    if timestamp.tzinfo is None:
        raise ValueError("Timezone required")
    return timestamp.astimezone(timezone.utc).isoformat()


# Publisher receives a complete demand event.
DemandPublisher = Callable[[dict], None]


@dataclass(frozen=True)
class SalesConsumerConfig:
    database_path: str = "data/workers/sales.db"
    max_quantity: int = 100000
    max_unit_price: float = 10000000.0

    def __post_init__(self):
        if self.max_quantity < 1:
            raise ValueError("Invalid quantity limit")
        if self.max_unit_price <= 0:
            raise ValueError("Invalid price limit")


class SalesConsumer:

    def __init__(
        self,
        config: SalesConsumerConfig | None = None,
        demand_publisher: DemandPublisher | None = None,
    ):
        self.config = config or SalesConsumerConfig()
        self.demand_publisher = demand_publisher

        path = Path(self.config.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        self.db = sqlite3.connect(str(path), timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=30000")

        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sales_events (
                event_id TEXT PRIMARY KEY,
                store_id TEXT NOT NULL,
                transaction_id TEXT NOT NULL,
                line_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                transaction_type TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                currency TEXT NOT NULL,
                revenue_delta REAL NOT NULL,
                occurred_at TEXT NOT NULL,
                processed_at TEXT NOT NULL,
                UNIQUE(transaction_id, line_id, transaction_type)
            );

            CREATE INDEX IF NOT EXISTS idx_sales_analytics
            ON sales_events(
                store_id, sku, occurred_at
            );

            CREATE TABLE IF NOT EXISTS sales_outbox (
                outbox_id TEXT PRIMARY KEY,
                event_json TEXT NOT NULL,
                published INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
        """)
        self.db.commit()

    def validate_event(self, event: dict) -> dict:
        if not isinstance(event, dict):
            raise ValueError("Invalid event")

        if event.get("event_type") != (
            "pos.transaction_recorded"
        ):
            raise ValueError("Unsupported event type")

        payload = event.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("Invalid payload")

        event_id = event.get("event_id")

        for field in (
            "store_id",
            "transaction_id",
            "line_id",
            "sku",
            "currency",
        ):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Invalid {field}")

        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("Invalid event ID")

        transaction_type = payload.get("transaction_type")

        if transaction_type not in {"sale", "return"}:
            raise ValueError("Invalid transaction type")

        quantity = payload.get("quantity")
        unit_price = payload.get("unit_price")

        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or not 1 <= quantity <= self.config.max_quantity
        ):
            raise ValueError("Invalid quantity")

        if (
            isinstance(unit_price, bool)
            or not isinstance(unit_price, (int, float))
            or not math.isfinite(unit_price)
            or not 0 <= unit_price <= self.config.max_unit_price
        ):
            raise ValueError("Invalid unit price")

        return {
            "event_id": event_id,
            "store_id": payload["store_id"],
            "transaction_id": payload["transaction_id"],
            "line_id": payload["line_id"],
            "sku": payload["sku"],
            "transaction_type": transaction_type,
            "quantity": quantity,
            "unit_price": float(unit_price),
            "currency": payload["currency"].upper(),
            "occurred_at": parse_time(event["occurred_at"]),
        }

    def process_event(self, event: dict) -> dict:
        data = self.validate_event(event)

        sign = (
            1 if data["transaction_type"] == "sale"
            else -1
        )

        revenue_delta = (
            sign * data["quantity"] * data["unit_price"]
        )

        self.db.execute("BEGIN IMMEDIATE")

        try:
            existing = self.db.execute(
                """
                SELECT event_id FROM sales_events
                WHERE event_id = ?
                """,
                (data["event_id"],),
            ).fetchone()

            if existing:
                self.db.commit()
                return {
                    "event_id": data["event_id"],
                    "status": "duplicate",
                }

            cursor = self.db.execute(
                """
                INSERT OR IGNORE INTO sales_events (
                    event_id, store_id, transaction_id,
                    line_id, sku, transaction_type,
                    quantity, unit_price, currency,
                    revenue_delta, occurred_at, processed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["event_id"],
                    data["store_id"],
                    data["transaction_id"],
                    data["line_id"],
                    data["sku"],
                    data["transaction_type"],
                    data["quantity"],
                    data["unit_price"],
                    data["currency"],
                    revenue_delta,
                    data["occurred_at"],
                    utc_now(),
                ),
            )

            if cursor.rowcount == 0:
                self.db.commit()
                return {
                    "event_id": data["event_id"],
                    "status": "duplicate_transaction_line",
                }

            if data["transaction_type"] == "sale":
                demand_event = {
                    "event_id": (
                        f"demand-{data['event_id']}"
                    ),
                    "event_type": "pos.transaction_recorded",
                    "occurred_at": data["occurred_at"],
                    "payload": {
                        "store_id": data["store_id"],
                        "transaction_id": data["transaction_id"],
                        "line_id": data["line_id"],
                        "sku": data["sku"],
                        "transaction_type": "sale",
                        "quantity": data["quantity"],
                        "unit_price": data["unit_price"],
                        "currency": data["currency"],
                    },
                }

                self.db.execute(
                    """
                    INSERT OR IGNORE INTO sales_outbox (
                        outbox_id, event_json,
                        published, created_at
                    )
                    VALUES (?, ?, 0, ?)
                    """,
                    (
                        demand_event["event_id"],
                        json.dumps(demand_event),
                        utc_now(),
                    ),
                )

            self.db.commit()

        except Exception:
            self.db.rollback()
            raise

        return {
            "event_id": data["event_id"],
            "status": "processed",
            "revenue_delta": round(revenue_delta, 2),
            "currency": data["currency"],
        }

    def sales_summary(
        self,
        store_id: str | None = None,
        sku: str | None = None,
        currency: str | None = None,
    ) -> dict:
        query = """
            SELECT
                currency,
                SUM(
                    CASE WHEN transaction_type = 'sale'
                    THEN quantity ELSE 0 END
                ) AS units_sold,
                SUM(
                    CASE WHEN transaction_type = 'return'
                    THEN quantity ELSE 0 END
                ) AS units_returned,
                SUM(revenue_delta) AS net_revenue,
                COUNT(*) AS transaction_lines
            FROM sales_events
            WHERE 1 = 1
        """

        params = []

        if store_id is not None:
            query += " AND store_id = ?"
            params.append(store_id)

        if sku is not None:
            query += " AND sku = ?"
            params.append(sku)

        if currency is not None:
            query += " AND currency = ?"
            params.append(currency.upper())

        query += " GROUP BY currency"

        rows = self.db.execute(
            query, params
        ).fetchall()

        return {
            "store_id": store_id,
            "sku": sku,
            "currencies": [
                dict(row) for row in rows
            ],
        }

    def publish_pending(
        self,
        limit: int = 100,
    ) -> dict:
        if self.demand_publisher is None:
            raise RuntimeError(
                "Demand publisher not configured"
            )

        if not 1 <= limit <= 1000:
            raise ValueError("Invalid limit")

        rows = self.db.execute(
            """
            SELECT * FROM sales_outbox
            WHERE published = 0
            ORDER BY created_at
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        published = failed = 0

        for row in rows:
            try:
                event = json.loads(
                    row["event_json"]
                )

                self.demand_publisher(event)

                with self.db:
                    self.db.execute(
                        """
                        UPDATE sales_outbox
                        SET published = 1
                        WHERE outbox_id = ?
                        """,
                        (row["outbox_id"],),
                    )

                published += 1

            except Exception:
                failed += 1

        return {
            "published": published,
            "failed": failed,
        }

    def consume_kafka(
        self,
        bootstrap_servers: str,
        topic: str = "retail.sales",
        group_id: str = "sales-consumer-v1",
    ) -> None:
        try:
            from kafka import KafkaConsumer
        except ImportError as exc:
            raise RuntimeError(
                "Install kafka-python"
            ) from exc

        consumer = KafkaConsumer(
            topic,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            max_poll_records=1,
            value_deserializer=lambda raw: (
                json.loads(raw.decode("utf-8"))
            ),
        )

        try:
            for message in consumer:
                self.process_event(message.value)
                consumer.commit()

        finally:
            consumer.close()

    def close(self):
        self.db.close()


if __name__ == "__main__":
    consumer = SalesConsumer(
        demand_publisher=lambda event: print(
            "DEMAND EVENT:",
            json.dumps(event),
        )
    )

    event = {
        "event_id": "sale-demo-001",
        "event_type": "pos.transaction_recorded",
        "occurred_at": utc_now(),
        "payload": {
            "store_id": "STORE-KOCHI-01",
            "transaction_id": "TX-001",
            "line_id": "LINE-001",
            "sku": "SKU-101",
            "transaction_type": "sale",
            "quantity": 3,
            "unit_price": 120.0,
            "currency": "INR",
        },
    }

    print(consumer.process_event(event))
    print(consumer.publish_pending())
    print(json.dumps(
        consumer.sales_summary(),
        indent=2,
    ))

    consumer.close()
