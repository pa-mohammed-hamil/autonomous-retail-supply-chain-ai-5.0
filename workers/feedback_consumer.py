from __future__ import annotations

"""Planned module: feedback consumer. Implementation pending."""

"""
ai/workers/feedback_consumer.py

Autonomous Retail Supply Chain AI 5.0

Features:
- Customer feedback event consumption
- Aspect-based sentiment analysis
- Product-level sentiment aggregation
- Negative review trend detection
- Idempotent event processing
- Durable alert outbox
- Kafka integration
- SQLite persistence
- Privacy-conscious review processing

Python 3.10+
Optional: pip install kafka-python
"""


import json
import sqlite3
import uuid

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ai.nlp.aspect_sentiment import (
    AspectSentimentAnalyzer,
)
from ai.workers.alert_worker import (
    Alert,
    AlertWorker,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class FeedbackConsumerConfig:
    database_path: str = "data/workers/feedback.db"
    minimum_reviews_for_alert: int = 5
    negative_rate_threshold: float = 0.60
    max_review_length: int = 10000

    def __post_init__(self):
        if self.minimum_reviews_for_alert < 1:
            raise ValueError("Invalid minimum reviews")
        if not 0 <= self.negative_rate_threshold <= 1:
            raise ValueError("Invalid negative threshold")
        if self.max_review_length < 1:
            raise ValueError("Invalid review length")


class FeedbackConsumer:

    def __init__(
        self,
        alert_worker: AlertWorker,
        config: FeedbackConsumerConfig | None = None,
        analyzer: AspectSentimentAnalyzer | None = None,
    ):
        self.config = config or FeedbackConsumerConfig()
        self.alert_worker = alert_worker
        self.analyzer = (
            analyzer or AspectSentimentAnalyzer()
        )

        path = Path(self.config.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        self.db = sqlite3.connect(
            str(path), timeout=30
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=30000")

        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS feedback_events (
                event_id TEXT PRIMARY KEY,
                feedback_id TEXT NOT NULL UNIQUE,
                product_id TEXT NOT NULL,
                rating INTEGER NOT NULL,
                occurred_at TEXT NOT NULL,
                processed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS aspect_results (
                event_id TEXT NOT NULL,
                aspect TEXT NOT NULL,
                sentiment TEXT NOT NULL,
                confidence REAL NOT NULL,
                method TEXT NOT NULL,
                PRIMARY KEY (event_id, aspect),
                FOREIGN KEY (event_id)
                    REFERENCES feedback_events(event_id)
            );

            CREATE TABLE IF NOT EXISTS feedback_outbox (
                alert_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                published INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
        """)

        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.commit()

    def validate_event(self, event: dict) -> dict:
        if not isinstance(event, dict):
            raise ValueError("Event must be a dictionary")

        if event.get("event_type") != (
            "feedback.review_received"
        ):
            raise ValueError("Unsupported event type")

        payload = event.get("payload")

        if not isinstance(payload, dict):
            raise ValueError("Invalid event payload")

        event_id = event.get("event_id")
        feedback_id = payload.get("feedback_id")
        product_id = payload.get("product_id")
        rating = payload.get("rating")
        review_text = payload.get("review_text")

        for name, value in (
            ("event_id", event_id),
            ("feedback_id", feedback_id),
            ("product_id", product_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Invalid {name}")

        if (
            isinstance(rating, bool)
            or not isinstance(rating, int)
            or not 1 <= rating <= 5
        ):
            raise ValueError("Rating must be 1-5")

        if (
            not isinstance(review_text, str)
            or not review_text.strip()
            or len(review_text)
            > self.config.max_review_length
        ):
            raise ValueError("Invalid review text")

        occurred_at = datetime.fromisoformat(
            event["occurred_at"].replace("Z", "+00:00")
        )

        if occurred_at.tzinfo is None:
            raise ValueError("Timezone required")

        return {
            "event_id": event_id,
            "feedback_id": feedback_id,
            "product_id": product_id,
            "rating": rating,
            "review_text": review_text,
            "occurred_at": occurred_at.astimezone(
                timezone.utc
            ).isoformat(),
        }

    def product_summary(self, product_id: str) -> dict:
        rows = self.db.execute(
            """
            SELECT rating
            FROM feedback_events
            WHERE product_id = ?
            """,
            (product_id,),
        ).fetchall()

        total = len(rows)
        negative = sum(
            row["rating"] <= 2 for row in rows
        )

        aspect_rows = self.db.execute(
            """
            SELECT ar.aspect, ar.sentiment,
                   COUNT(*) AS mentions
            FROM aspect_results ar
            JOIN feedback_events fe
              ON fe.event_id = ar.event_id
            WHERE fe.product_id = ?
            GROUP BY ar.aspect, ar.sentiment
            """,
            (product_id,),
        ).fetchall()

        aspects = {}

        for row in aspect_rows:
            aspects.setdefault(row["aspect"], {})
            aspects[row["aspect"]][
                row["sentiment"]
            ] = row["mentions"]

        return {
            "product_id": product_id,
            "total_reviews": total,
            "negative_reviews": negative,
            "negative_rate": (
                round(negative / total, 4)
                if total else 0.0
            ),
            "aspects": aspects,
        }

    def process_event(self, event: dict) -> dict:
        data = self.validate_event(event)

        existing = self.db.execute(
            """
            SELECT event_id FROM feedback_events
            WHERE event_id = ? OR feedback_id = ?
            """,
            (
                data["event_id"],
                data["feedback_id"],
            ),
        ).fetchone()

        if existing:
            return {
                "event_id": data["event_id"],
                "status": "duplicate",
            }

        analysis = self.analyzer.analyze(
            review=data["review_text"],
            review_id=data["feedback_id"],
            product_id=data["product_id"],
            include_evidence=False,
        )

        with self.db:
            self.db.execute(
                """
                INSERT INTO feedback_events (
                    event_id, feedback_id,
                    product_id, rating,
                    occurred_at, processed_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    data["event_id"],
                    data["feedback_id"],
                    data["product_id"],
                    data["rating"],
                    data["occurred_at"],
                    utc_now(),
                ),
            )

            for result in analysis["results"]:
                self.db.execute(
                    """
                    INSERT INTO aspect_results (
                        event_id, aspect,
                        sentiment, confidence,
                        method
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        data["event_id"],
                        result["aspect"],
                        result["sentiment"],
                        result["confidence"],
                        result["method"],
                    ),
                )

            summary = self.product_summary(
                data["product_id"]
            )

            if (
                summary["total_reviews"]
                >= self.config.minimum_reviews_for_alert
                and summary["negative_rate"]
                >= self.config.negative_rate_threshold
            ):
                # Stable per-product alert ID:
                # one unresolved alert per product.
                alert_id = (
                    f"negative-feedback-{data['product_id']}"
                )

                alert_payload = {
                    "alert_id": alert_id,
                    "alert_type": "system_failure",
                    "severity": "high",
                    "recipient_reference": (
                        "customer_experience_manager"
                    ),
                    "message": (
                        "High negative feedback rate "
                        f"for product {data['product_id']}: "
                        f"{summary['negative_rate']:.1%} "
                        f"across {summary['total_reviews']} "
                        "reviews."
                    ),
                    "channel": "internal",
                }

                self.db.execute(
                    """
                    INSERT OR IGNORE INTO feedback_outbox (
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

        return {
            "event_id": data["event_id"],
            "status": "processed",
            "aspect_sentiment": analysis["results"],
            "product_summary": summary,
        }

    def publish_pending_alerts(
        self, limit: int = 100
    ) -> dict:
        if not 1 <= limit <= 1000:
            raise ValueError("Invalid limit")

        rows = self.db.execute(
            """
            SELECT *
            FROM feedback_outbox
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

                if result["created"] or (
                    result["status"] == "existing"
                ):
                    with self.db:
                        self.db.execute(
                            """
                            UPDATE feedback_outbox
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
        topic: str = "retail.feedback",
        group_id: str = "feedback-consumer-v1",
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
            value_deserializer=lambda value: (
                json.loads(value.decode("utf-8"))
            ),
            max_poll_records=1,
        )

        try:
            for message in consumer:
                self.process_event(message.value)

                result = self.publish_pending_alerts()

                if result["failed"]:
                    raise RuntimeError(
                        "Alert publishing failed"
                    )

                consumer.commit()

        finally:
            consumer.close()

    def close(self):
        self.db.close()


if __name__ == "__main__":
    alerts = AlertWorker()
    consumer = FeedbackConsumer(alerts)

    example = {
        "event_id": uuid.uuid4().hex,
        "event_type": "feedback.review_received",
        "occurred_at": utc_now(),
        "payload": {
            "feedback_id": uuid.uuid4().hex,
            "product_id": "SKU-101",
            "rating": 2,
            "review_text": (
                "The packaging was damaged and "
                "delivery was slow."
            ),
        },
    }

    print(json.dumps(
        consumer.process_event(example),
        indent=2,
    ))

    print(consumer.publish_pending_alerts())

    consumer.close()
    alerts.close()
