from __future__ import annotations

"""Planned module: inventory consumer. Implementation pending."""

"""
ai/workers/inventory_consumer.py

Autonomous Retail Supply Chain AI 5.0

Features:
- Real-time inventory event consumption
- Warehouse/SKU inventory state
- Stockout and low-stock detection
- Reorder-point monitoring
- Out-of-order event protection
- Idempotent processing
- Durable notification outbox
- Kafka integration
- SQLite persistence

Python 3.10+
Optional: pip install kafka-python

Expected event:
{
    "event_id": "inv-001",
    "event_type": "inventory.snapshot_updated",
    "occurred_at": "2026-10-26T06:00:00Z",
    "payload": {
        "sku": "SKU-101",
        "warehouse_id": "WH-KOCHI",
        "on_hand": 30,
        "reserved": 12,
        "available": 18
    }
}
"""


import json
import sqlite3
import uuid

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ai.workers.alert_worker import Alert, AlertWorker


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Timestamp must be a string")

    timestamp = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

    if timestamp.tzinfo is None:
        raise ValueError("Timezone required")

    return timestamp.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class InventoryConsumerConfig:
    database_path: str = "data/workers/inventory.db"
    default_reorder_point: int = 20
    low_stock_severity: str = "warning"
    stockout_severity: str = "high"

    def __post_init__(self):
        if self.default_reorder_point < 0:
            raise ValueError("Invalid reorder point")


class InventoryConsumer:

    def __init__(
        self,
        alert_worker: AlertWorker,
        config: InventoryConsumerConfig | None = None,
    ):
        self.config = config or InventoryConsumerConfig()
        self.alert_worker = alert_worker

        path = Path(self.config.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        self.db = sqlite3.connect(
            str(path), timeout=30
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")

        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS inventory_events (
                event_id TEXT PRIMARY KEY,
                warehouse_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                processed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS inventory_state (
                warehouse_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                on_hand INTEGER NOT NULL,
                reserved INTEGER NOT NULL,
                available INTEGER NOT NULL,
                reorder_point INTEGER NOT NULL,
                stock_status TEXT NOT NULL,
                last_event_id TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (warehouse_id, sku)
            );

            CREATE TABLE IF NOT EXISTS inventory_alert_outbox (
                alert_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                published INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
        """)

        self.db.commit()

    def set_reorder_point(
        self,
        warehouse_id: str,
        sku: str,
        reorder_point: int,
    ) -> None:
        if (
            isinstance(reorder_point, bool)
            or not isinstance(reorder_point, int)
            or reorder_point < 0
        ):
            raise ValueError("Invalid reorder point")

        with self.db:
            self.db.execute(
                """
                UPDATE inventory_state
                SET reorder_point = ?,
                    stock_status = CASE
                        WHEN available = 0
                            THEN 'stockout'
                        WHEN available <= ?
                            THEN 'low_stock'
                        ELSE 'healthy'
                    END
                WHERE warehouse_id = ? AND sku = ?
                """,
                (
                    reorder_point,
                    reorder_point,
                    warehouse_id,
                    sku,
                ),
            )

    @staticmethod
    def validate_event(event: dict) -> dict:
        if not isinstance(event, dict):
            raise ValueError("Invalid event")

        if event.get("event_type") != (
            "inventory.snapshot_updated"
        ):
            raise ValueError("Unsupported event type")

        payload = event.get("payload")

        if not isinstance(payload, dict):
            raise ValueError("Invalid payload")

        event_id = event.get("event_id")
        warehouse_id = payload.get("warehouse_id")
        sku = payload.get("sku")

        for value in (event_id, warehouse_id, sku):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Missing event identifier")

        on_hand = payload.get("on_hand")
        reserved = payload.get("reserved")
        available = payload.get("available")

        for value in (on_hand, reserved, available):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ValueError("Invalid inventory quantity")

        if reserved > on_hand:
            raise ValueError("Reserved exceeds on-hand")

        if available != on_hand - reserved:
            raise ValueError(
                "Available stock is inconsistent"
            )

        return {
            "event_id": event_id,
            "warehouse_id": warehouse_id,
            "sku": sku,
            "on_hand": on_hand,
            "reserved": reserved,
            "available": available,
            "occurred_at": parse_timestamp(
                event["occurred_at"]
            ),
        }

    def get_inventory(
        self,
        warehouse_id: str,
        sku: str,
    ) -> dict | None:
        row = self.db.execute(
            """
            SELECT * FROM inventory_state
            WHERE warehouse_id = ? AND sku = ?
            """,
            (warehouse_id, sku),
        ).fetchone()

        return dict(row) if row else None

    def process_event(self, event: dict) -> dict:
        data = self.validate_event(event)

        self.db.execute("BEGIN IMMEDIATE")

        try:
            duplicate = self.db.execute(
                """
                SELECT 1 FROM inventory_events
                WHERE event_id = ?
                """,
                (data["event_id"],),
            ).fetchone()

            if duplicate:
                self.db.commit()
                return {
                    "event_id": data["event_id"],
                    "status": "duplicate",
                }

            previous = self.get_inventory(
                data["warehouse_id"],
                data["sku"],
            )

            self.db.execute(
                """
                INSERT INTO inventory_events (
                    event_id, warehouse_id, sku,
                    occurred_at, processed_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    data["event_id"],
                    data["warehouse_id"],
                    data["sku"],
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
                    "status": "stale_snapshot",
                }

            reorder_point = (
                previous["reorder_point"]
                if previous
                else self.config.default_reorder_point
            )

            if data["available"] == 0:
                status = "stockout"
            elif data["available"] <= reorder_point:
                status = "low_stock"
            else:
                status = "healthy"

            self.db.execute(
                """
                INSERT INTO inventory_state (
                    warehouse_id, sku, on_hand,
                    reserved, available,
                    reorder_point, stock_status,
                    last_event_id, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(warehouse_id, sku)
                DO UPDATE SET
                    on_hand = excluded.on_hand,
                    reserved = excluded.reserved,
                    available = excluded.available,
                    reorder_point = excluded.reorder_point,
                    stock_status = excluded.stock_status,
                    last_event_id = excluded.last_event_id,
                    updated_at = excluded.updated_at
                """,
                (
                    data["warehouse_id"],
                    data["sku"],
                    data["on_hand"],
                    data["reserved"],
                    data["available"],
                    reorder_point,
                    status,
                    data["event_id"],
                    data["occurred_at"],
                ),
            )

            previous_status = (
                previous["stock_status"]
                if previous else None
            )

            if (
                status in {"low_stock", "stockout"}
                and status != previous_status
            ):
                alert_id = (
                    f"inventory-{data['event_id']}"
                )

                payload = {
                    "alert_id": alert_id,
                    "alert_type": (
                        "inventory_stockout"
                        if status == "stockout"
                        else "low_inventory"
                    ),
                    "severity": (
                        self.config.stockout_severity
                        if status == "stockout"
                        else self.config.low_stock_severity
                    ),
                    "recipient_reference": (
                        f"warehouse_manager:"
                        f"{data['warehouse_id']}"
                    ),
                    "message": (
                        f"{status.upper()}: "
                        f"{data['sku']} at "
                        f"{data['warehouse_id']}. "
                        f"Available: {data['available']}; "
                        f"reorder point: {reorder_point}."
                    ),
                    "channel": "internal",
                }

                self.db.execute(
                    """
                    INSERT INTO inventory_alert_outbox (
                        alert_id, payload_json,
                        published, created_at
                    )
                    VALUES (?, ?, 0, ?)
                    """,
                    (
                        alert_id,
                        json.dumps(payload),
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
            "stock_status": status,
            "available": data["available"],
            "reorder_point": reorder_point,
        }

    def publish_pending_alerts(
        self,
        limit: int = 100,
    ) -> dict:
        if not 1 <= limit <= 1000:
            raise ValueError("Invalid limit")

        rows = self.db.execute(
            """
            SELECT * FROM inventory_alert_outbox
            WHERE published = 0
            ORDER BY created_at
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        published = 0
        failed = 0

        for row in rows:
            try:
                payload = json.loads(
                    row["payload_json"]
                )

                result = self.alert_worker.enqueue(
                    Alert(**payload)
                )

                if (
                    result["created"]
                    or result["status"] == "existing"
                ):
                    with self.db:
                        self.db.execute(
                            """
                            UPDATE inventory_alert_outbox
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
        topic: str = "retail.inventory",
        group_id: str = "inventory-consumer-v1",
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
            value_deserializer=lambda data: (
                json.loads(data.decode("utf-8"))
            ),
        )

        try:
            for message in consumer:
                self.process_event(message.value)

                outcome = self.publish_pending_alerts()

                if outcome["failed"]:
                    raise RuntimeError(
                        "Inventory alert publishing failed"
                    )

                consumer.commit()

        finally:
            consumer.close()

    def close(self):
        self.db.close()


if __name__ == "__main__":
    alerts = AlertWorker()
    consumer = InventoryConsumer(alerts)

    event = {
        "event_id": uuid.uuid4().hex,
        "event_type": "inventory.snapshot_updated",
        "occurred_at": utc_now(),
        "payload": {
            "warehouse_id": "WH-KOCHI",
            "sku": "SKU-101",
            "on_hand": 30,
            "reserved": 18,
            "available": 12,
        },
    }

    print(json.dumps(
        consumer.process_event(event),
        indent=2,
    ))

    print(consumer.publish_pending_alerts())

    print(json.dumps(
        consumer.get_inventory(
            "WH-KOCHI", "SKU-101"
        ),
        indent=2,
    ))

    consumer.close()
    alerts.close()
