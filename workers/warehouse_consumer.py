from __future__ import annotations

"""Planned module: warehouse consumer. Implementation pending."""

"""
ai/workers/warehouse_consumer.py

Autonomous Retail Supply Chain AI 5.0

Warehouse event processing worker.

Features:
- Warehouse movement ingestion
- Receiving / picking / packing / dispatch
- Returns and stock adjustments
- Stock balance tracking
- Negative inventory prevention
- Idempotent event processing
- Event-time ordering
- Warehouse anomaly detection
- Durable alert outbox
- Inventory snapshot publishing
- Warehouse KPI analytics
- Optional Kafka integration

Python 3.10+
Optional: pip install kafka-python

Expected event:
{
    "event_id": "wh-001",
    "event_type": "warehouse.movement_recorded",
    "occurred_at": "2026-10-26T06:00:00Z",
    "payload": {
        "warehouse_id": "WH-KOCHI",
        "sku": "SKU-101",
        "movement_type": "receiving",
        "quantity": 50
    }
}

Additional optional fields:
- reference_id
- operator_reference
- reason
- source_location
- destination_location

This is a development baseline.
"""


import json
import sqlite3
import uuid

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Timestamp must be a string")

    result = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )

    if result.tzinfo is None:
        raise ValueError("Timezone required")

    return result.astimezone(timezone.utc).isoformat()


InventoryPublisher = Callable[[dict], None]


@dataclass(frozen=True)
class WarehouseConsumerConfig:
    database_path: str = (
        "data/workers/warehouse.db"
    )
    max_movement_quantity: int = 100000
    anomaly_quantity_threshold: int = 5000
    low_stock_threshold: int = 20
    prevent_negative_stock: bool = True

    def __post_init__(self):
        if self.max_movement_quantity < 1:
            raise ValueError(
                "Invalid maximum movement quantity"
            )

        if self.anomaly_quantity_threshold < 1:
            raise ValueError(
                "Invalid anomaly threshold"
            )

        if self.low_stock_threshold < 0:
            raise ValueError(
                "Invalid low-stock threshold"
            )


class WarehouseConsumer:

    MOVEMENT_TYPES = {
        "receiving",
        "picking",
        "packing",
        "dispatch",
        "return",
        "adjustment_in",
        "adjustment_out",
    }

    # Only physical stock-changing movements
    # affect on-hand inventory.
    STOCK_DELTAS = {
        "receiving": 1,
        "picking": 0,
        "packing": 0,
        "dispatch": -1,
        "return": 1,
        "adjustment_in": 1,
        "adjustment_out": -1,
    }

    def __init__(
        self,
        config: WarehouseConsumerConfig | None = None,
        inventory_publisher: InventoryPublisher | None = None,
    ):
        self.config = (
            config or WarehouseConsumerConfig()
        )

        self.inventory_publisher = inventory_publisher

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
        self.db.execute("PRAGMA foreign_keys=ON")

        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS warehouse_events (
                event_id TEXT PRIMARY KEY,
                warehouse_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                movement_type TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                stock_delta INTEGER NOT NULL,
                reference_id TEXT,
                operator_reference TEXT,
                reason TEXT,
                occurred_at TEXT NOT NULL,
                processed_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_warehouse_events
            ON warehouse_events(
                warehouse_id, sku, occurred_at
            );

            CREATE TABLE IF NOT EXISTS warehouse_stock (
                warehouse_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                on_hand INTEGER NOT NULL DEFAULT 0,
                reserved INTEGER NOT NULL DEFAULT 0,
                available INTEGER NOT NULL DEFAULT 0,
                last_event_id TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (warehouse_id, sku)
            );

            CREATE TABLE IF NOT EXISTS warehouse_outbox (
                event_id TEXT PRIMARY KEY,
                event_json TEXT NOT NULL,
                published INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS warehouse_alerts (
                alert_id TEXT PRIMARY KEY,
                warehouse_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS warehouse_audit (
                audit_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                action TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)

        self.db.commit()

    def validate_event(self, event: dict) -> dict:
        if not isinstance(event, dict):
            raise ValueError("Event must be a dictionary")

        if event.get("event_type") != (
            "warehouse.movement_recorded"
        ):
            raise ValueError(
                "Unsupported warehouse event type"
            )

        payload = event.get("payload")

        if not isinstance(payload, dict):
            raise ValueError("Invalid event payload")

        event_id = event.get("event_id")
        warehouse_id = payload.get("warehouse_id")
        sku = payload.get("sku")
        movement_type = payload.get("movement_type")
        quantity = payload.get("quantity")

        for name, value in (
            ("event_id", event_id),
            ("warehouse_id", warehouse_id),
            ("sku", sku),
        ):
            if (
                not isinstance(value, str)
                or not value.strip()
            ):
                raise ValueError(f"Invalid {name}")

        if movement_type not in self.MOVEMENT_TYPES:
            raise ValueError(
                "Unsupported movement type"
            )

        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or not (
                1 <= quantity
                <= self.config.max_movement_quantity
            )
        ):
            raise ValueError(
                "Invalid movement quantity"
            )

        return {
            "event_id": event_id,
            "warehouse_id": warehouse_id,
            "sku": sku,
            "movement_type": movement_type,
            "quantity": quantity,
            "reference_id": payload.get("reference_id"),
            "operator_reference": payload.get(
                "operator_reference"
            ),
            "reason": payload.get("reason"),
            "occurred_at": parse_timestamp(
                event["occurred_at"]
            ),
        }

    def get_stock(
        self,
        warehouse_id: str,
        sku: str,
    ) -> dict:
        row = self.db.execute(
            """
            SELECT *
            FROM warehouse_stock
            WHERE warehouse_id = ?
              AND sku = ?
            """,
            (warehouse_id, sku),
        ).fetchone()

        if row is None:
            return {
                "warehouse_id": warehouse_id,
                "sku": sku,
                "on_hand": 0,
                "reserved": 0,
                "available": 0,
                "last_event_id": None,
                "updated_at": None,
            }

        return dict(row)

    def _audit(
        self,
        event_id: str,
        action: str,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO warehouse_audit (
                audit_id, event_id,
                action, created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                event_id,
                action,
                utc_now(),
            ),
        )

    def _create_alert(
        self,
        event_id: str,
        warehouse_id: str,
        sku: str,
        alert_type: str,
        severity: str,
        message: str,
    ) -> None:
        alert_id = (
            f"warehouse-{alert_type}-{event_id}"
        )

        self.db.execute(
            """
            INSERT OR IGNORE INTO warehouse_alerts (
                alert_id, warehouse_id, sku,
                alert_type, severity,
                message, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert_id,
                warehouse_id,
                sku,
                alert_type,
                severity,
                message,
                utc_now(),
            ),
        )

    def _queue_inventory_snapshot(
        self,
        data: dict,
        stock: dict,
    ) -> None:
        event = {
            "event_id": (
                f"inventory-from-{data['event_id']}"
            ),
            "event_type": (
                "inventory.snapshot_updated"
            ),
            "occurred_at": data["occurred_at"],
            "payload": {
                "warehouse_id": data["warehouse_id"],
                "sku": data["sku"],
                "on_hand": stock["on_hand"],
                "reserved": stock["reserved"],
                "available": stock["available"],
            },
        }

        self.db.execute(
            """
            INSERT OR IGNORE INTO warehouse_outbox (
                event_id, event_json,
                published, created_at
            )
            VALUES (?, ?, 0, ?)
            """,
            (
                event["event_id"],
                json.dumps(event),
                utc_now(),
            ),
        )

    def process_event(self, event: dict) -> dict:
        data = self.validate_event(event)

        self.db.execute("BEGIN IMMEDIATE")

        try:
            existing = self.db.execute(
                """
                SELECT 1
                FROM warehouse_events
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

            previous = self.get_stock(
                data["warehouse_id"],
                data["sku"],
            )

            if (
                previous["updated_at"] is not None
                and data["occurred_at"]
                < previous["updated_at"]
            ):
                # Do not silently apply old
                # absolute-state snapshots.
                self.db.commit()
                return {
                    "event_id": data["event_id"],
                    "status": "stale_event",
                }

            delta = (
                self.STOCK_DELTAS[
                    data["movement_type"]
                ]
                * data["quantity"]
            )

            new_on_hand = (
                previous["on_hand"] + delta
            )

            reserved = previous["reserved"]

            if (
                self.config.prevent_negative_stock
                and new_on_hand < reserved
            ):
                raise ValueError(
                    "Movement would violate "
                    "available inventory"
                )

            new_available = (
                new_on_hand - reserved
            )

            self.db.execute(
                """
                INSERT INTO warehouse_events (
                    event_id, warehouse_id,
                    sku, movement_type,
                    quantity, stock_delta,
                    reference_id,
                    operator_reference,
                    reason, occurred_at,
                    processed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["event_id"],
                    data["warehouse_id"],
                    data["sku"],
                    data["movement_type"],
                    data["quantity"],
                    delta,
                    data["reference_id"],
                    data["operator_reference"],
                    data["reason"],
                    data["occurred_at"],
                    utc_now(),
                ),
            )

            self.db.execute(
                """
                INSERT INTO warehouse_stock (
                    warehouse_id, sku,
                    on_hand, reserved,
                    available, last_event_id,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(warehouse_id, sku)
                DO UPDATE SET
                    on_hand = excluded.on_hand,
                    reserved = excluded.reserved,
                    available = excluded.available,
                    last_event_id = excluded.last_event_id,
                    updated_at = excluded.updated_at
                """,
                (
                    data["warehouse_id"],
                    data["sku"],
                    new_on_hand,
                    reserved,
                    new_available,
                    data["event_id"],
                    data["occurred_at"],
                ),
            )

            stock = {
                "on_hand": new_on_hand,
                "reserved": reserved,
                "available": new_available,
            }

            if delta != 0:
                self._queue_inventory_snapshot(
                    data, stock
                )

            if (
                data["quantity"]
                >= self.config.anomaly_quantity_threshold
            ):
                self._create_alert(
                    data["event_id"],
                    data["warehouse_id"],
                    data["sku"],
                    "unusual_movement",
                    "high",
                    (
                        "Unusually large warehouse "
                        f"movement: {data['quantity']} "
                        f"units of {data['sku']}."
                    ),
                )

            if (
                delta < 0
                and new_available
                <= self.config.low_stock_threshold
            ):
                self._create_alert(
                    data["event_id"],
                    data["warehouse_id"],
                    data["sku"],
                    "low_stock",
                    "warning",
                    (
                        f"Low warehouse stock: "
                        f"{data['sku']} has "
                        f"{new_available} available units."
                    ),
                )

            self._audit(
                data["event_id"],
                "movement_processed",
            )

            self.db.commit()

        except Exception:
            self.db.rollback()
            raise

        return {
            "event_id": data["event_id"],
            "status": "processed",
            "movement_type": data["movement_type"],
            "stock_delta": delta,
            "stock": stock,
        }

    def publish_pending(
        self,
        limit: int = 100,
    ) -> dict:
        if self.inventory_publisher is None:
            raise RuntimeError(
                "Inventory publisher not configured"
            )

        if not 1 <= limit <= 1000:
            raise ValueError("Invalid limit")

        rows = self.db.execute(
            """
            SELECT *
            FROM warehouse_outbox
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
                event = json.loads(
                    row["event_json"]
                )

                self.inventory_publisher(event)

                with self.db:
                    self.db.execute(
                        """
                        UPDATE warehouse_outbox
                        SET published = 1
                        WHERE event_id = ?
                        """,
                        (row["event_id"],),
                    )

                published += 1

            except Exception:
                failed += 1

        return {
            "published": published,
            "failed": failed,
        }

    def warehouse_summary(
        self,
        warehouse_id: str,
    ) -> dict:
        stock = self.db.execute(
            """
            SELECT
                COUNT(*) AS sku_count,
                COALESCE(SUM(on_hand), 0) AS on_hand,
                COALESCE(SUM(reserved), 0) AS reserved,
                COALESCE(SUM(available), 0) AS available
            FROM warehouse_stock
            WHERE warehouse_id = ?
            """,
            (warehouse_id,),
        ).fetchone()

        movements = self.db.execute(
            """
            SELECT movement_type,
                   COUNT(*) AS event_count,
                   SUM(quantity) AS total_quantity
            FROM warehouse_events
            WHERE warehouse_id = ?
            GROUP BY movement_type
            """,
            (warehouse_id,),
        ).fetchall()

        alerts = self.db.execute(
            """
            SELECT COUNT(*) AS alert_count
            FROM warehouse_alerts
            WHERE warehouse_id = ?
            """,
            (warehouse_id,),
        ).fetchone()

        return {
            "warehouse_id": warehouse_id,
            "inventory": dict(stock),
            "movements": [
                dict(row) for row in movements
            ],
            "alert_count": alerts["alert_count"],
        }

    def list_alerts(
        self,
        warehouse_id: str,
        limit: int = 100,
    ) -> list[dict]:
        rows = self.db.execute(
            """
            SELECT *
            FROM warehouse_alerts
            WHERE warehouse_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (warehouse_id, limit),
        ).fetchall()

        return [
            dict(row) for row in rows
        ]

    def consume_kafka(
        self,
        bootstrap_servers: str,
        topic: str = "retail.warehouse",
        group_id: str = "warehouse-consumer-v1",
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

                # Commit after durable local
                # processing. Outbox publishing
                # can run independently.
                consumer.commit()

        finally:
            consumer.close()

    def close(self) -> None:
        self.db.close()


if __name__ == "__main__":
    def demo_inventory_publisher(
        event: dict,
    ) -> None:
        print(
            "INVENTORY EVENT:",
            json.dumps(event),
        )

    worker = WarehouseConsumer(
        inventory_publisher=(
            demo_inventory_publisher
        )
    )

    demo_events = [
        {
            "event_id": "wh-receive-001",
            "event_type": "warehouse.movement_recorded",
            "occurred_at": (
                "2026-10-26T06:00:00Z"
            ),
            "payload": {
                "warehouse_id": "WH-KOCHI",
                "sku": "SKU-101",
                "movement_type": "receiving",
                "quantity": 100,
            },
        },
        {
            "event_id": "wh-dispatch-001",
            "event_type": "warehouse.movement_recorded",
            "occurred_at": (
                "2026-10-26T06:05:00Z"
            ),
            "payload": {
                "warehouse_id": "WH-KOCHI",
                "sku": "SKU-101",
                "movement_type": "dispatch",
                "quantity": 30,
            },
        },
    ]

    for event in demo_events:
        print(
            json.dumps(
                worker.process_event(event),
                indent=2,
            )
        )

    print(worker.publish_pending())

    print(
        json.dumps(
            worker.warehouse_summary(
                "WH-KOCHI"
            ),
            indent=2,
        )
    )

    worker.close()
