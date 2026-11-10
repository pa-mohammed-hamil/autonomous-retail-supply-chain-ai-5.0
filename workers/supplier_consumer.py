from __future__ import annotations

"""Planned module: supplier consumer. Implementation pending."""

"""
ai/workers/supplier_consumer.py

Real-time supplier performance consumer.

Features:
- Supplier performance event processing
- On-time delivery monitoring
- Product quality rate monitoring
- Lead-time tracking
- Available capacity tracking
- Supplier risk scoring
- Configurable risk thresholds
- Supplier disruption alerts
- Durable alert outbox
- Kafka integration
- SQLite persistence

Python 3.10+
Optional dependency: kafka-python

Expected event:
{
    "event_id": "supplier-001",
    "event_type": "supplier.performance_updated",
    "occurred_at": "2026-10-26T06:00:00Z",
    "payload": {
        "supplier_id": "SUP-001",
        "sku": "SKU-101",
        "on_time_rate": 0.82,
        "quality_rate": 0.95,
        "lead_time_days": 8,
        "available_capacity": 1000
    }
}
"""


import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ai.workers.alert_worker import (
    Alert,
    AlertWorker,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: str) -> str:
    timestamp = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

    if timestamp.tzinfo is None:
        raise ValueError("Timezone required")

    return timestamp.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class SupplierConsumerConfig:
    database_path: str = "data/workers/suppliers.db"
    minimum_on_time_rate: float = 0.90
    minimum_quality_rate: float = 0.95
    maximum_lead_time_days: float = 14.0
    minimum_available_capacity: int = 100
    high_risk_threshold: float = 0.50

    def __post_init__(self):
        for value in (
            self.minimum_on_time_rate,
            self.minimum_quality_rate,
            self.high_risk_threshold,
        ):
            if not 0 <= value <= 1:
                raise ValueError("Invalid rate threshold")

        if self.maximum_lead_time_days <= 0:
            raise ValueError("Invalid lead-time limit")

        if self.minimum_available_capacity < 0:
            raise ValueError("Invalid capacity limit")


class SupplierConsumer:

    def __init__(
        self,
        alert_worker: AlertWorker,
        config: SupplierConsumerConfig | None = None,
    ):
        self.alert_worker = alert_worker
        self.config = (
            config or SupplierConsumerConfig()
        )

        path = Path(self.config.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        self.db = sqlite3.connect(str(path), timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=30000")

        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS supplier_events (
                event_id TEXT PRIMARY KEY,
                supplier_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                on_time_rate REAL NOT NULL,
                quality_rate REAL NOT NULL,
                lead_time_days REAL NOT NULL,
                available_capacity INTEGER NOT NULL,
                risk_score REAL NOT NULL,
                risk_level TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                processed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS supplier_state (
                supplier_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                on_time_rate REAL NOT NULL,
                quality_rate REAL NOT NULL,
                lead_time_days REAL NOT NULL,
                available_capacity INTEGER NOT NULL,
                risk_score REAL NOT NULL,
                risk_level TEXT NOT NULL,
                last_event_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (supplier_id, sku)
            );

            CREATE TABLE IF NOT EXISTS supplier_alert_outbox (
                alert_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                published INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
        """)

        self.db.commit()

    @staticmethod
    def validate_event(event: dict) -> dict:
        if not isinstance(event, dict):
            raise ValueError("Invalid event")

        if event.get("event_type") != (
            "supplier.performance_updated"
        ):
            raise ValueError("Unsupported event type")

        payload = event.get("payload")

        if not isinstance(payload, dict):
            raise ValueError("Invalid payload")

        event_id = event.get("event_id")
        supplier_id = payload.get("supplier_id")
        sku = payload.get("sku")

        for value in (event_id, supplier_id, sku):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Missing identifier")

        numeric_fields = (
            "on_time_rate",
            "quality_rate",
            "lead_time_days",
        )

        for field in numeric_fields:
            value = payload.get(field)

            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"Invalid {field}")

        for field in ("on_time_rate", "quality_rate"):
            if not 0 <= payload[field] <= 1:
                raise ValueError(f"Invalid {field}")

        if payload["lead_time_days"] < 0:
            raise ValueError("Invalid lead time")

        capacity = payload.get("available_capacity")

        if (
            isinstance(capacity, bool)
            or not isinstance(capacity, int)
            or capacity < 0
        ):
            raise ValueError("Invalid capacity")

        return {
            "event_id": event_id,
            "supplier_id": supplier_id,
            "sku": sku,
            "on_time_rate": float(
                payload["on_time_rate"]
            ),
            "quality_rate": float(
                payload["quality_rate"]
            ),
            "lead_time_days": float(
                payload["lead_time_days"]
            ),
            "available_capacity": capacity,
            "occurred_at": parse_time(
                event["occurred_at"]
            ),
        }

    def calculate_risk(self, data: dict) -> dict:
        config = self.config

        delivery_risk = (
            1.0 - data["on_time_rate"]
        )

        quality_risk = (
            1.0 - data["quality_rate"]
        )

        lead_time_risk = min(
            1.0,
            data["lead_time_days"]
            / config.maximum_lead_time_days,
        )

        capacity_risk = (
            max(
                0.0,
                (
                    config.minimum_available_capacity
                    - data["available_capacity"]
                )
                / config.minimum_available_capacity,
            )
            if config.minimum_available_capacity > 0
            else 0.0
        )

        risk_score = (
            0.35 * delivery_risk
            + 0.30 * quality_risk
            + 0.20 * lead_time_risk
            + 0.15 * capacity_risk
        )

        if risk_score >= config.high_risk_threshold:
            risk_level = "high"
        elif risk_score >= 0.25:
            risk_level = "medium"
        else:
            risk_level = "low"

        violations = []

        if (
            data["on_time_rate"]
            < config.minimum_on_time_rate
        ):
            violations.append("late_deliveries")

        if (
            data["quality_rate"]
            < config.minimum_quality_rate
        ):
            violations.append("quality_below_target")

        if (
            data["lead_time_days"]
            > config.maximum_lead_time_days
        ):
            violations.append("long_lead_time")

        if (
            data["available_capacity"]
            < config.minimum_available_capacity
        ):
            violations.append("low_capacity")

        return {
            "risk_score": round(risk_score, 4),
            "risk_level": risk_level,
            "violations": violations,
        }

    def get_supplier(
        self,
        supplier_id: str,
        sku: str,
    ) -> dict | None:
        row = self.db.execute(
            """
            SELECT *
            FROM supplier_state
            WHERE supplier_id = ? AND sku = ?
            """,
            (supplier_id, sku),
        ).fetchone()

        return dict(row) if row else None

    def process_event(self, event: dict) -> dict:
        data = self.validate_event(event)
        risk = self.calculate_risk(data)

        self.db.execute("BEGIN IMMEDIATE")

        try:
            existing = self.db.execute(
                """
                SELECT 1 FROM supplier_events
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

            previous = self.get_supplier(
                data["supplier_id"],
                data["sku"],
            )

            self.db.execute(
                """
                INSERT INTO supplier_events (
                    event_id, supplier_id, sku,
                    on_time_rate, quality_rate,
                    lead_time_days, available_capacity,
                    risk_score, risk_level,
                    occurred_at, processed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["event_id"],
                    data["supplier_id"],
                    data["sku"],
                    data["on_time_rate"],
                    data["quality_rate"],
                    data["lead_time_days"],
                    data["available_capacity"],
                    risk["risk_score"],
                    risk["risk_level"],
                    data["occurred_at"],
                    utc_now(),
                ),
            )

            if previous and (
                data["occurred_at"]
                <= previous["updated_at"]
            ):
                self.db.commit()
                return {
                    "event_id": data["event_id"],
                    "status": "stale_event",
                }

            self.db.execute(
                """
                INSERT INTO supplier_state (
                    supplier_id, sku, on_time_rate,
                    quality_rate, lead_time_days,
                    available_capacity, risk_score,
                    risk_level, last_event_id, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(supplier_id, sku)
                DO UPDATE SET
                    on_time_rate = excluded.on_time_rate,
                    quality_rate = excluded.quality_rate,
                    lead_time_days = excluded.lead_time_days,
                    available_capacity = excluded.available_capacity,
                    risk_score = excluded.risk_score,
                    risk_level = excluded.risk_level,
                    last_event_id = excluded.last_event_id,
                    updated_at = excluded.updated_at
                """,
                (
                    data["supplier_id"],
                    data["sku"],
                    data["on_time_rate"],
                    data["quality_rate"],
                    data["lead_time_days"],
                    data["available_capacity"],
                    risk["risk_score"],
                    risk["risk_level"],
                    data["event_id"],
                    data["occurred_at"],
                ),
            )

            previous_risk = (
                previous["risk_level"]
                if previous else None
            )

            if (
                risk["risk_level"] == "high"
                and previous_risk != "high"
            ):
                alert_id = (
                    f"supplier-risk-{data['event_id']}"
                )

                alert_payload = {
                    "alert_id": alert_id,
                    "alert_type": "supplier_disruption",
                    "severity": "high",
                    "recipient_reference": (
                        "procurement_manager"
                    ),
                    "message": (
                        f"High supplier risk: "
                        f"{data['supplier_id']} / "
                        f"{data['sku']}. "
                        f"Score: {risk['risk_score']}. "
                        f"Violations: "
                        f"{', '.join(risk['violations'])}"
                    ),
                    "channel": "internal",
                }

                self.db.execute(
                    """
                    INSERT OR IGNORE INTO supplier_alert_outbox (
                        alert_id, payload_json,
                        published, created_at
                    )
                    VALUES (?, ?, 0, ?)
                    """,
                    (
                        alert_id,
                        json.dumps(alert_payload),
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
            "risk": risk,
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
            FROM supplier_alert_outbox
            WHERE published = 0
            ORDER BY created_at
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        published = failed = 0

        for row in rows:
            try:
                result = self.alert_worker.enqueue(
                    Alert(
                        **json.loads(
                            row["payload_json"]
                        )
                    )
                )

                if (
                    result["created"]
                    or result["status"] == "existing"
                ):
                    with self.db:
                        self.db.execute(
                            """
                            UPDATE supplier_alert_outbox
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
        topic: str = "retail.suppliers",
        group_id: str = "supplier-consumer-v1",
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

                outcome = self.publish_pending_alerts()

                if outcome["failed"]:
                    raise RuntimeError(
                        "Supplier alert publishing failed"
                    )

                consumer.commit()

        finally:
            consumer.close()

    def close(self):
        self.db.close()


if __name__ == "__main__":
    alerts = AlertWorker()
    consumer = SupplierConsumer(alerts)

    event = {
        "event_id": "supplier-demo-001",
        "event_type": "supplier.performance_updated",
        "occurred_at": utc_now(),
        "payload": {
            "supplier_id": "SUP-001",
            "sku": "SKU-101",
            "on_time_rate": 0.75,
            "quality_rate": 0.88,
            "lead_time_days": 20,
            "available_capacity": 40,
        },
    }

    print(json.dumps(
        consumer.process_event(event),
        indent=2,
    ))

    print(consumer.publish_pending_alerts())

    print(json.dumps(
        consumer.get_supplier("SUP-001", "SKU-101"),
        indent=2,
    ))

    consumer.close()
    alerts.close()
