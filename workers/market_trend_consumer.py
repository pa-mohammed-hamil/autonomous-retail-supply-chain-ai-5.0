from __future__ import annotations

"""Planned module: market trend consumer. Implementation pending."""

"""
ai/workers/market_trend_consumer.py

Market trend event consumer.

Features:
- Kafka-compatible event processing
- Competitor price tracking
- Demand index monitoring
- Rolling trend metrics
- Out-of-order event handling
- Idempotent event ingestion
- Durable alert outbox
- Price and demand alerts

Python 3.10+
Optional dependency: kafka-python
"""


import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev

from ai.workers.alert_worker import Alert, AlertWorker


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str) -> datetime:
    result = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )
    if result.tzinfo is None:
        raise ValueError("Timezone required")
    return result.astimezone(timezone.utc)


@dataclass(frozen=True)
class MarketTrendConfig:
    database_path: str = "data/workers/market_trends.db"
    history_window: int = 30
    minimum_observations: int = 3
    price_change_threshold: float = 0.10
    demand_growth_threshold: float = 0.20

    def __post_init__(self):
        if self.history_window < 2:
            raise ValueError("Invalid history window")
        if not 2 <= self.minimum_observations <= self.history_window:
            raise ValueError("Invalid minimum observations")
        if self.price_change_threshold <= 0:
            raise ValueError("Invalid price threshold")
        if self.demand_growth_threshold <= 0:
            raise ValueError("Invalid demand threshold")


class MarketTrendConsumer:

    def __init__(
        self,
        alert_worker: AlertWorker,
        config: MarketTrendConfig | None = None,
    ):
        self.alert_worker = alert_worker
        self.config = config or MarketTrendConfig()

        path = Path(self.config.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        self.db = sqlite3.connect(str(path), timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=30000")

        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS market_signals (
                event_id TEXT PRIMARY KEY,
                sku TEXT NOT NULL,
                market TEXT NOT NULL,
                competitor_id TEXT NOT NULL,
                currency TEXT NOT NULL,
                price REAL NOT NULL,
                demand_index REAL NOT NULL,
                occurred_at TEXT NOT NULL,
                processed_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_market_history
            ON market_signals(
                sku, market, competitor_id,
                currency, occurred_at
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

        if event.get("event_type") != "market.signal_updated":
            raise ValueError("Unsupported event type")

        event_id = event.get("event_id")
        payload = event.get("payload")

        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("Event ID required")

        if not isinstance(payload, dict):
            raise ValueError("Payload required")

        for field in ("sku", "market", "competitor_id", "currency"):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Invalid {field}")

        price = payload.get("price")
        demand_index = payload.get("demand_index")

        for field, value in (
            ("price", price),
            ("demand_index", demand_index),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"Invalid {field}")

        if price == 0:
            raise ValueError("Price must be positive")

        return {
            "event_id": event_id,
            "sku": payload["sku"],
            "market": payload["market"],
            "competitor_id": payload["competitor_id"],
            "currency": payload["currency"].upper(),
            "price": float(price),
            "demand_index": float(demand_index),
            "occurred_at": parse_time(
                event["occurred_at"]
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
            return {"status": "no_data"}

        prices = [row["price"] for row in rows]
        demand = [row["demand_index"] for row in rows]

        price_change = (
            prices[-1] - prices[0]
        ) / prices[0]

        demand_growth = (
            (demand[-1] - demand[0]) / demand[0]
            if demand[0] > 0
            else None
        )

        volatility = (
            pstdev(prices) / mean(prices)
            if len(prices) > 1
            else 0.0
        )

        sufficient = (
            len(rows) >= self.config.minimum_observations
        )

        return {
            "sku": sku,
            "market": market,
            "competitor_id": competitor_id,
            "currency": currency,
            "observations": len(rows),
            "latest_price": prices[-1],
            "average_price": round(mean(prices), 4),
            "price_change_percent": round(
                price_change * 100, 2
            ),
            "price_volatility": round(volatility, 4),
            "latest_demand_index": demand[-1],
            "demand_growth_percent": (
                round(demand_growth * 100, 2)
                if demand_growth is not None
                else None
            ),
            "price_alert": (
                sufficient
                and abs(price_change)
                >= self.config.price_change_threshold
            ),
            "demand_alert": (
                sufficient
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
                    competitor_id, currency,
                    price, demand_index,
                    occurred_at, processed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["event_id"],
                    data["sku"],
                    data["market"],
                    data["competitor_id"],
                    data["currency"],
                    data["price"],
                    data["demand_index"],
                    data["occurred_at"],
                    now_utc().isoformat(),
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

            for alert_kind, triggered in (
                ("price_change", trend["price_alert"]),
                ("demand_growth", trend["demand_alert"]),
            ):
                if not triggered:
                    continue

                alert_id = (
                    f"market-{alert_kind}-{data['event_id']}"
                )

                metric = (
                    trend["price_change_percent"]
                    if alert_kind == "price_change"
                    else trend["demand_growth_percent"]
                )

                payload = {
                    "alert_id": alert_id,
                    "alert_type": (
                        "demand_spike"
                        if alert_kind == "demand_growth"
                        else "system_failure"
                    ),
                    "severity": "warning",
                    "recipient_reference": (
                        "market_intelligence_team"
                    ),
                    "message": (
                        f"{alert_kind} for {data['sku']} "
                        f"in {data['market']}: {metric}%"
                    ),
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
                        now_utc().isoformat(),
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

    def publish_pending_alerts(self, limit: int = 100) -> dict:
        if not 1 <= limit <= 1000:
            raise ValueError("Invalid limit")

        rows = self.db.execute(
            """
            SELECT * FROM market_alert_outbox
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
                    Alert(**json.loads(row["payload_json"]))
                )

                if result["created"] or result["status"] == "existing":
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

        return {"published": published, "failed": failed}

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
            value_deserializer=lambda raw: json.loads(
                raw.decode("utf-8")
            ),
        )

        try:
            for message in consumer:
                self.process_event(message.value)
                result = self.publish_pending_alerts()

                if result["failed"]:
                    raise RuntimeError(
                        "Alert outbox publishing failed"
                    )

                consumer.commit()
        finally:
            consumer.close()

    def close(self) -> None:
        self.db.close()


if __name__ == "__main__":
    alerts = AlertWorker()
    consumer = MarketTrendConsumer(alerts)

    event = {
        "event_id": "market-demo-001",
        "event_type": "market.signal_updated",
        "occurred_at": now_utc().isoformat(),
        "payload": {
            "sku": "SKU-101",
            "market": "Kerala",
            "competitor_id": "COMP-001",
            "currency": "INR",
            "price": 120.0,
            "demand_index": 108.0,
        },
    }

    print(json.dumps(
        consumer.process_event(event), indent=2
    ))
    print(consumer.publish_pending_alerts())

    consumer.close()
    alerts.close()
