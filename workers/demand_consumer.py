from __future__ import annotations

"""Planned module: demand consumer. Implementation pending."""

"""
ai/workers/demand_consumer.py

Autonomous Retail Supply Chain AI 5.0

Features:
- Real-time retail sales event consumption
- Demand aggregation by SKU and store
- Sliding-window demand metrics
- Demand spike detection
- Minimum baseline safeguards
- Duplicate event protection
- Durable SQLite event processing
- Alert worker integration
- Kafka consumer adapter
- Consumer offset management
- JSON demand summaries

Python 3.10+

Optional dependency:
    pip install kafka-python

Expected event format:
{
    "event_id": "sale-001",
    "event_type": "pos.transaction_recorded",
    "occurred_at": "2026-10-25T12:00:00+00:00",
    "payload": {
        "store_id": "STORE-001",
        "sku": "SKU-101",
        "quantity": 5,
        "transaction_type": "sale"
    }
}
"""


import json
import math
import sqlite3
import uuid

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ai.workers.alert_worker import (
    Alert,
    AlertWorker,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str) -> datetime:
    timestamp = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

    if timestamp.tzinfo is None:
        raise ValueError(
            "Event timestamp must include timezone"
        )

    return timestamp.astimezone(timezone.utc)


@dataclass(frozen=True)
class DemandConsumerConfig:
    database_path: str = "data/workers/demand.db"
    current_window_minutes: int = 60
    baseline_window_minutes: int = 1440
    spike_multiplier: float = 2.0
    minimum_current_units: int = 10
    minimum_baseline_units: int = 5
    max_event_age_hours: int = 72
    max_future_skew_seconds: int = 120

    def __post_init__(self):
        if self.current_window_minutes <= 0:
            raise ValueError("Invalid current window")

        if (
            self.baseline_window_minutes
            <= self.current_window_minutes
        ):
            raise ValueError(
                "Baseline must exceed current window"
            )

        if self.spike_multiplier <= 1:
            raise ValueError(
                "Spike multiplier must exceed 1"
            )

        if self.minimum_current_units < 1:
            raise ValueError(
                "Invalid minimum demand"
            )


class DemandConsumer:

    def __init__(
        self,
        alert_worker: AlertWorker,
        config: DemandConsumerConfig | None = None,
    ):
        self.config = (
            config or DemandConsumerConfig()
        )
        self.alert_worker = alert_worker

        path = Path(self.config.database_path)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.db = sqlite3.connect(
            str(path),
            timeout=30,
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=30000")

        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sales_events (
                event_id TEXT PRIMARY KEY,
                store_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                occurred_at TEXT NOT NULL,
                processed_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_demand_window
            ON sales_events(
                store_id, sku, occurred_at
            );

            CREATE TABLE IF NOT EXISTS demand_alert_outbox (
                alert_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                published INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
        """)

        self.db.commit()

    def validate_event(
        self,
        event: dict,
    ) -> dict:
        if not isinstance(event, dict):
            raise ValueError(
                "Event must be a dictionary"
            )

        if event.get("event_type") != (
            "pos.transaction_recorded"
        ):
            raise ValueError(
                "Unsupported event type"
            )

        event_id = event.get("event_id")

        if (
            not isinstance(event_id, str)
            or not event_id.strip()
        ):
            raise ValueError("Event ID required")

        payload = event.get("payload")

        if not isinstance(payload, dict):
            raise ValueError("Payload required")

        store_id = payload.get("store_id")
        sku = payload.get("sku")
        quantity = payload.get("quantity")
        transaction_type = payload.get(
            "transaction_type"
        )

        if not isinstance(store_id, str) or not store_id:
            raise ValueError("Store ID required")

        if not isinstance(sku, str) or not sku:
            raise ValueError("SKU required")

        if transaction_type != "sale":
            raise ValueError(
                "Only sale transactions are supported"
            )

        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity <= 0
        ):
            raise ValueError(
                "Quantity must be a positive integer"
            )

        occurred_at = parse_time(
            event["occurred_at"]
        )

        now = utc_now()

        if occurred_at > now + timedelta(
            seconds=self.config.max_future_skew_seconds
        ):
            raise ValueError(
                "Event timestamp is in the future"
            )

        if occurred_at < now - timedelta(
            hours=self.config.max_event_age_hours
        ):
            raise ValueError("Stale event")

        return {
            "event_id": event_id,
            "store_id": store_id,
            "sku": sku,
            "quantity": quantity,
            "occurred_at": occurred_at,
        }

    def _sum_units(
        self,
        store_id: str,
        sku: str,
        start: datetime,
        end: datetime,
    ) -> int:
        row = self.db.execute(
            """
            SELECT COALESCE(SUM(quantity), 0)
                AS total_units
            FROM sales_events
            WHERE store_id = ?
              AND sku = ?
              AND occurred_at >= ?
              AND occurred_at < ?
            """,
            (
                store_id,
                sku,
                start.isoformat(),
                end.isoformat(),
            ),
        ).fetchone()

        return int(row["total_units"])

    def demand_metrics(
        self,
        store_id: str,
        sku: str,
        as_of: datetime | None = None,
    ) -> dict:
        now = as_of or utc_now()

        current_start = now - timedelta(
            minutes=self.config.current_window_minutes
        )

        baseline_start = current_start - timedelta(
            minutes=self.config.baseline_window_minutes
        )

        current_units = self._sum_units(
            store_id,
            sku,
            current_start,
            now,
        )

        baseline_units = self._sum_units(
            store_id,
            sku,
            baseline_start,
            current_start,
        )

        baseline_hourly_rate = (
            baseline_units
            / (
                self.config.baseline_window_minutes
                / 60
            )
        )

        current_hourly_rate = (
            current_units
            / (
                self.config.current_window_minutes
                / 60
            )
        )

        if baseline_hourly_rate > 0:
            ratio = (
                current_hourly_rate
                / baseline_hourly_rate
            )
        else:
            ratio = None

        spike_detected = (
            baseline_units
            >= self.config.minimum_baseline_units
            and current_units
            >= self.config.minimum_current_units
            and ratio is not None
            and ratio >= self.config.spike_multiplier
        )

        return {
            "store_id": store_id,
            "sku": sku,
            "current_units": current_units,
            "baseline_units": baseline_units,
            "current_hourly_rate": round(
                current_hourly_rate, 3
            ),
            "baseline_hourly_rate": round(
                baseline_hourly_rate, 3
            ),
            "demand_ratio": (
                round(ratio, 3)
                if ratio is not None
                else None
            ),
            "spike_detected": spike_detected,
            "evaluated_at": now.isoformat(),
        }

    def process_event(
        self,
        event: dict,
    ) -> dict:
        validated = self.validate_event(event)

        event_id = validated["event_id"]
        store_id = validated["store_id"]
        sku = validated["sku"]

        with self.db:
            cursor = self.db.execute(
                """
                INSERT OR IGNORE INTO sales_events (
                    event_id, store_id, sku,
                    quantity, occurred_at, processed_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    store_id,
                    sku,
                    validated["quantity"],
                    validated["occurred_at"].isoformat(),
                    utc_now().isoformat(),
                ),
            )

            inserted = cursor.rowcount == 1

            if not inserted:
                return {
                    "event_id": event_id,
                    "status": "duplicate",
                }

            metrics = self.demand_metrics(
                store_id,
                sku,
            )

            if metrics["spike_detected"]:
                # One alert per store/SKU/hour.
                # Deterministic IDs prevent
                # duplicate alerts on replay.
                current_hour = utc_now().strftime(
                    "%Y%m%d%H"
                )

                alert_id = (
                    f"demand-spike-{store_id}-"
                    f"{sku}-{current_hour}"
                )

                alert = {
                    "alert_id": alert_id,
                    "alert_type": "demand_spike",
                    "severity": "high",
                    "recipient_reference": (
                        f"store_manager:{store_id}"
                    ),
                    "message": (
                        f"Demand spike detected for "
                        f"{sku} at {store_id}. "
                        f"Current units: "
                        f"{metrics['current_units']}. "
                        f"Demand ratio: "
                        f"{metrics['demand_ratio']}."
                    ),
                    "channel": "internal",
                }

                self.db.execute(
                    """
                    INSERT OR IGNORE INTO
                    demand_alert_outbox (
                        alert_id, payload_json,
                        published, created_at
                    )
                    VALUES (?, ?, 0, ?)
                    """,
                    (
                        alert_id,
                        json.dumps(alert),
                        utc_now().isoformat(),
                    ),
                )

        return {
            "event_id": event_id,
            "status": "processed",
            "metrics": metrics,
        }

    def publish_pending_alerts(
        self,
        limit: int = 100,
    ) -> dict:
        if not 1 <= limit <= 1000:
            raise ValueError("Invalid limit")

        rows = self.db.execute(
            """
            SELECT *
            FROM demand_alert_outbox
            WHERE published = 0
            ORDER BY created_at
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        published = 0
        failed = 0

        for row in rows:
            payload = json.loads(
                row["payload_json"]
            )

            try:
                result = self.alert_worker.enqueue(
                    Alert(**payload)
                )

                if result["created"] or (
                    result["status"] == "existing"
                ):
                    with self.db:
                        self.db.execute(
                            """
                            UPDATE demand_alert_outbox
                            SET published = 1
                            WHERE alert_id = ?
                            """,
                            (row["alert_id"],),
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
        group_id: str = "demand-consumer-v1",
    ) -> None:
        """
        Optional Kafka integration.

        Commit offsets only after successful
        processing and outbox publishing.

        Permanent invalid events require a
        separately configured DLQ policy.
        """

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
            value_deserializer=lambda value: (
                json.loads(value.decode("utf-8"))
            ),
            consumer_timeout_ms=1000,
        )

        try:
            for message in consumer:
                self.process_event(message.value)

                result = self.publish_pending_alerts()

                if result["failed"]:
                    raise RuntimeError(
                        "Alert outbox publishing failed"
                    )

                # Sequential consumption:
                # commit after successful handling.
                consumer.commit()

        finally:
            consumer.close()

    def close(self) -> None:
        self.db.close()


if __name__ == "__main__":
    alerts = AlertWorker()
    consumer = DemandConsumer(
        alert_worker=alerts
    )

    now = utc_now()

    demo_events = [
        {
            "event_id": f"sale-{index}",
            "event_type": "pos.transaction_recorded",
            "occurred_at": (
                now - timedelta(minutes=index)
            ).isoformat(),
            "payload": {
                "store_id": "STORE-KOCHI-01",
                "sku": "SKU-101",
                "quantity": 5,
                "transaction_type": "sale",
            },
        }
        for index in range(1, 8)
    ]

    for event in demo_events:
        print(
            json.dumps(
                consumer.process_event(event),
                indent=2,
            )
        )

    print(
        consumer.publish_pending_alerts()
    )

    print(
        json.dumps(
            consumer.demand_metrics(
                "STORE-KOCHI-01",
                "SKU-101",
            ),
            indent=2,
        )
    )

    print(
        json.dumps(
            alerts.summary(),
            indent=2,
        )
    )

    consumer.close()
    alerts.close()
