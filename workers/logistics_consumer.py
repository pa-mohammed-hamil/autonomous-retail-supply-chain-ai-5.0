from __future__ import annotations

"""Planned module: logistics consumer. Implementation pending."""

"""
ai/workers/market_trend_consumer.py

Autonomous Retail Supply Chain AI 5.0

Features:
- Market price event consumption
- Demand index tracking
- Competitor price monitoring
- Rolling market trend analysis
- Price change detection
- Demand growth detection
- Market volatility metrics
- Idempotent event processing
- Durable alert outbox
- Kafka integration
- SQLite persistence

Python 3.10+
Optional: pip install kafka-python

Expected event:
{
    "event_id": "market-001",
    "event_type": "market.signal_updated",
    "occurred_at": "2026-10-26T06:00:00Z",
    "payload": {
        "sku": "SKU-101",
        "market": "Kerala",
        "competitor_id": "COMP-001",
        "price": 120.0,
        "currency": "INR",
        "demand_index": 108.0
    }
}

Market prices and demand indices must
originate from authorized, reliable sources.
"""


import json
import math
import sqlite3
import uuid

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev

from ai.workers.alert_worker import (
    Alert,
    AlertWorker,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class MarketTrendConfig:
    database_path: str = (
        "data/workers/market_trends.db"
    )
    price_change_threshold: float = 0.10
    demand_growth_threshold: float = 0.20
    history_window: int = 30
    minimum_observations: int = 3

    def __post_init__(self):
        if self.price_change_threshold <= 0:
            raise ValueError("Invalid price threshold")
        if self.demand_growth_threshold <= 0:
            raise ValueError("Invalid demand threshold")
        if self.history_window < 2:
            raise ValueError("Invalid history window")
        if self.minimum_observations < 2:
            raise ValueError("Invalid minimum observations")


class MarketTrendConsumer:

    def __init__(
        self,
        alert_worker: AlertWorker,
        config: MarketTrendConfig | None = None,
    ):
        self.config = config or MarketTrendConfig()
        self.alert_worker = alert_worker

        path = Path(self.config.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        self.db = sqlite3.connect(
            str(path), timeout=30
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")

        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS market_signals (
                event_id TEXT PRIMARY KEY,
                sku TEXT NOT NULL,
                market TEXT NOT NULL,
                competitor_id TEXT NOT NULL,
                price REAL NOT NULL,
                currency TEXT NOT NULL,
                demand_index REAL NOT NULL,
                occurred_at TEXT NOT NULL,
                processed_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_market_signals
            ON market_signals(
                sku, market, competitor_id, occurred_at
            );

            CREATE TABLE IF NOT EXISTS market_alert_outbox (
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
            "market.signal_updated"
        ):
            raise ValueError("Unsupported event type")

        payload = event.get("payload")

        if not isinstance(payload, dict):
            raise ValueError("Invalid payload")

        required = (
            "sku",
            "market",
            "competitor_id",
            "currency",
        )

        for field in required:
            value = payload.get(field)

            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"Invalid {field}"
                )

        price = payload.get("price")
        demand_index = payload.get("demand_index")

        for name, value in (
            ("price", price),
            ("demand_index", demand_index),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(
                    f"Invalid {name}"
                )

        if price <= 0:
            raise ValueError(
                "Market price must be positive"
            )

        event_id = event.get("event_id")

        if not isinstance(event_id, str) or not event_id:
            raise ValueError("Event ID required")

        timestamp = datetime.fromisoformat(
            event["occurred_at"].replace("Z", "+00:00")
        )

        if timestamp.tzinfo is None:
            raise ValueError("Timezone required")

        return {
            "event_id": event_id,
            "sku": payload["sku"],
            "market": payload["market"],
            "competitor_id": payload["competitor_id"],
            "price": float(price),
            "currency": payload["currency"],
            "demand_index": float(demand_index),
            "occurred_at": timestamp.astimezone(
                timezone.utc
            ).isoformat(),
        }

    def trend_summary(
        self,
        sku: str,
        market: str,
        competitor_id: str,
        currency: str,
    ) -> dict:
        rows = self.db.execute(
            """
            SELECT price, demand_index, occurred_at
            FROM market_signals
            WHERE sku = ?
              AND market = ?
              AND competitor_id = ?
              AND currency = ?
            ORDER BY occurred_at DESC, event_id DESC
            LIMIT ?
            """,
            (
                sku,
                market,
                competitor_id,
                currency,
                self.config.history_window,
            ),
        ).fetchall()

        rows = list(reversed(rows))

        if not rows:
            return {
                "status": "no_data",
                "observation_count": 0,
            }

        prices = [
            row["price"] for row in rows
        ]

        demand = [
            row["demand_index"] for row in rows
        ]

        first_price = prices[0]
        latest_price = prices[-1]

        price_change = (
            (latest_price - first_price)
            / first_price
        )

        first_demand = demand[0]
        latest_demand = demand[-1]

        demand_growth = (
            (latest_demand - first_demand)
            / first_demand
            if first_demand > 0
            else None
        )

        volatility = (
            pstdev(prices) / mean(prices)
            if len(prices) >= 2
            else 0.0
        )

        sufficient_data = (
            len(rows)
            >= self.config.minimum_observations
        )

        return {
            "sku": sku,
            "market": market,
            "competitor_id": competitor_id,
            "currency": currency,
            "observation_count": len(rows),
            "first_price": first_price,
            "latest_price": latest_price,
            "average_price": round(
                mean(prices), 4
            ),
            "price_change_percent": round(
                price_change * 100, 2
            ),
            "price_volatility": round(
                volatility, 4
            ),
            "first_demand_index": first_demand,
            "latest_demand_index": latest_demand,
            "demand_growth_percent": (
                round(demand_growth * 100, 2)
                if demand_growth is not None
                else None
            ),
            "sufficient_data": sufficient_data,
            "price_alert": (
                sufficient_data
                and abs(price_change)
                >= self.config.price_change_threshold
            ),
            "demand_alert": (
                sufficient_data
                and demand_growth is not None
                and demand_growth
                >= self.config.demand_growth_threshold
            ),
        }

    def process_event(self, event: dict) -> dict:
        data = self.validate_event(event)

        self.db.execute("BEGIN IMMEDIATE")

        try:
            cursor = self.db.execute(
                """
                INSERT OR IGNORE INTO market_signals (
                    event_id, sku, market,
                    competitor_id, price, currency,
                    demand_index, occurred_at,
                    processed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["event_id"],
                    data["sku"],
                    data["market"],
                    data["competitor_id"],
                    data["price"],
                    data["currency"],
                    data["demand_index"],
                    data["occurred_at"],
                    utc_now(),
                ),
            )

            if cursor.rowcount == 0:
                self.db.commit()
                return {
                    "event_id": data["event_id"],
                    "status": "duplicate",
                }

            trend = self.trend_summary(
                data["sku"],
                data["market"],
                data["competitor_id"],
                data["currency"],
            )

            alerts = []

            if trend["price_alert"]:
                alerts.append(
                    (
                        "price_change",
                        f"Market price changed "
                        f"{trend['price_change_percent']}% "
                        f"for {data['sku']} in "
                        f"{data['market']}."
                    )
                )

            if trend["demand_alert"]:
                alerts.append(
                    (
                        "demand_growth",
                        f"Demand index increased "
                        f"{trend['demand_growth_percent']}% "
                        f"for {data['sku']} in "
                        f"{data['market']}."
                    )
                )

            for alert_type, message in alerts:
                alert_id = (
                    f"market-{alert_type}-"
                    f"{data['event_id']}"
                )

                payload = {
                    "alert_id": alert_id,
                    "alert_type": (
                        "demand_spike"
                        if alert_type == "demand_growth"
                        else "system_failure"
                    ),
                    "severity": "warning",
                    "recipient_reference": (
                        "market_intelligence_team"
                    ),
                    "message": message,
                    "channel": "internal",
                }

                self.db.execute(
                    """
                    INSERT OR IGNORE INTO market_alert_outbox (
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
            "trend": trend,
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
            FROM market_alert_outbox
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
                            UPDATE market_alert_outbox
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
        topic: str = "retail.market",
        group_id: str = "market-trend-consumer-v1",
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

                result = self.publish_pending_alerts()

                if result["failed"]:
                    raise RuntimeError(
                        "Market alert publishing failed"
                    )

                consumer.commit()

        finally:
            consumer.close()

    def close(self):
        self.db.close()


if __name__ == "__main__":
    alerts = AlertWorker()
    consumer = MarketTrendConsumer(alerts)

    for index, (price, demand) in enumerate(
        [
            (120.0, 100.0),
            (130.0, 110.0),
            (145.0, 135.0),
        ]
    ):
        event = {
            "event_id": uuid.uuid4().hex,
            "event_type": "market.signal_updated",
            "occurred_at": (
                datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
            ),
            "payload": {
                "sku": "SKU-101",
                "market": "Kerala",
                "competitor_id": "COMP-001",
                "price": price,
                "currency": "INR",
                "demand_index": demand,
            },
        }

        print(
            json.dumps(
                consumer.process_event(event),
                indent=2,
            )
        )

    print(consumer.publish_pending_alerts())

    consumer.close()
    alerts.close()
