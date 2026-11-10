"""Planned module: kafka consumer. Implementation pending."""

"""
ai/pipelines/kafka_consumer.py

Kafka event consumer for the retail supply-chain
AI platform.

Features:
- Kafka consumer group support
- JSON event deserialization
- Event schema validation
- Manual offset commits
- Dead-letter queue integration
- Idempotency using SQLite
- Registered event handlers
- Graceful shutdown
- Structured processing results

Dependencies:
    pip install kafka-python

Local Kafka:
    localhost:9092

Important:
- Kafka offsets are committed only after
  successful handling or durable DLQ storage.
- DLQ and Kafka commits are not one atomic
  transaction.
- Handlers must be idempotent.
- For consequential actions, require explicit
  authorization and independent safeguards.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ai.pipelines.dead_letter_queue import (
    DeadLetterQueue,
    DLQConfig,
)
from ai.pipelines.event_validation import (
    EventValidation,
    EventValidationConfig,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KafkaConsumerConfig:
    bootstrap_servers: tuple[str, ...] = (
        "localhost:9092",
    )
    topics: tuple[str, ...] = (
        "retail.inventory",
        "retail.sales",
        "retail.suppliers",
        "retail.logistics",
        "retail.warehouse",
        "retail.feedback",
    )
    group_id: str = "retail-ai-consumers-v1"
    auto_offset_reset: str = "earliest"
    poll_timeout_ms: int = 1000
    max_poll_records: int = 100
    idempotency_db_path: str = (
        "data/kafka_consumer_idempotency.db"
    )

    def __post_init__(self):
        if not self.bootstrap_servers:
            raise ValueError(
                "bootstrap_servers required"
            )

        if not self.topics:
            raise ValueError(
                "At least one Kafka topic required"
            )

        if self.auto_offset_reset not in {
            "earliest",
            "latest",
        }:
            raise ValueError(
                "Invalid auto_offset_reset"
            )

        if self.poll_timeout_ms < 1:
            raise ValueError(
                "poll_timeout_ms must be positive"
            )

        if self.max_poll_records < 1:
            raise ValueError(
                "max_poll_records must be positive"
            )


class EventIdempotencyStore:
    """
    Tracks processed event IDs.

    This prevents reprocessing after successful
    commits, but cannot guarantee exactly-once
    external side effects by itself.
    """

    def __init__(self, database_path: str):
        path = Path(database_path)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.connection = sqlite3.connect(
            str(path),
            timeout=30,
            isolation_level=None,
        )

        self.connection.execute(
            "PRAGMA journal_mode=WAL"
        )

        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_events (
                event_id TEXT PRIMARY KEY,
                processed_at TEXT NOT NULL
            )
            """
        )

    def exists(self, event_id: str) -> bool:
        row = self.connection.execute(
            """
            SELECT 1
            FROM processed_events
            WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()

        return row is not None

    def mark_processed(
        self,
        event_id: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT OR IGNORE INTO processed_events (
                event_id, processed_at
            )
            VALUES (?, ?)
            """,
            (
                event_id,
                datetime.now(
                    timezone.utc
                ).isoformat(),
            ),
        )

    def close(self):
        self.connection.close()


class RetailKafkaConsumer:

    def __init__(
        self,
        config: KafkaConsumerConfig | None = None,
        dlq: DeadLetterQueue | None = None,
        validator: EventValidation | None = None,
    ):
        self.config = config or KafkaConsumerConfig()

        self.dlq = dlq or DeadLetterQueue(
            DLQConfig()
        )
        self._owns_dlq = dlq is None

        self.validator = validator or EventValidation(
            EventValidationConfig()
        )

        self.idempotency = EventIdempotencyStore(
            self.config.idempotency_db_path
        )

        self.handlers: dict[
            str,
            Callable[[dict], None],
        ] = {}

        self.consumer = None
        self.stop_event = threading.Event()

    def register_handler(
        self,
        event_type: str,
        handler: Callable[[dict], None],
    ) -> None:
        if not event_type:
            raise ValueError(
                "event_type required"
            )

        if not callable(handler):
            raise ValueError(
                "handler must be callable"
            )

        self.handlers[event_type] = handler

    def connect(self):
        try:
            from kafka import KafkaConsumer
        except ImportError as exc:
            raise RuntimeError(
                "Install kafka-python: "
                "pip install kafka-python"
            ) from exc

        self.consumer = KafkaConsumer(
            *self.config.topics,
            bootstrap_servers=list(
                self.config.bootstrap_servers
            ),
            group_id=self.config.group_id,
            enable_auto_commit=False,
            auto_offset_reset=(
                self.config.auto_offset_reset
            ),
            max_poll_records=(
                self.config.max_poll_records
            ),
            value_deserializer=None,
            key_deserializer=None,
            consumer_timeout_ms=(
                self.config.poll_timeout_ms
            ),
        )

    @staticmethod
    def _decode_message(
        raw_value: bytes,
    ) -> dict:
        if not isinstance(raw_value, bytes):
            raise ValueError(
                "Kafka message value must be bytes"
            )

        event = json.loads(
            raw_value.decode("utf-8")
        )

        if not isinstance(event, dict):
            raise ValueError(
                "Event must be a JSON object"
            )

        return event

    @staticmethod
    def _fallback_event_id(message) -> str:
        identity = (
            f"{message.topic}:"
            f"{message.partition}:"
            f"{message.offset}"
        )

        return "kafka-" + hashlib.sha256(
            identity.encode("utf-8")
        ).hexdigest()

    def _send_to_dlq(
        self,
        message,
        event: dict | None,
        error: str,
    ) -> dict:
        fallback_id = self._fallback_event_id(
            message
        )

        # Use Kafka record identity for invalid
        # messages to avoid collisions with valid
        # business event IDs.
        dlq_event_id = fallback_id

        payload = {
            "kafka_topic": message.topic,
            "kafka_partition": message.partition,
            "kafka_offset": message.offset,
            "original_event": event,
        }

        if event is None:
            payload["raw_value_hex"] = (
                message.value.hex()
                if isinstance(
                    message.value, bytes
                )
                else None
            )

        return self.dlq.enqueue(
            event_id=dlq_event_id,
            event_type="kafka.processing_failed",
            payload=payload,
            error_message=error,
        )

    def process_message(
        self,
        message,
    ) -> dict:
        """
        Process one Kafka record.

        The caller commits its offset only when
        this method returns acknowledged=True.
        """

        event = None

        try:
            event = self._decode_message(
                message.value
            )

            validation = self.validator.validate(
                event
            )

            if not validation["valid"]:
                raise ValueError(
                    "Event validation failed: "
                    + "; ".join(
                        validation["errors"]
                    )
                )

            event_id = event["event_id"]
            event_type = event["event_type"]

            if self.idempotency.exists(event_id):
                return {
                    "acknowledged": True,
                    "status": "already_processed",
                    "event_id": event_id,
                }

            handler = self.handlers.get(
                event_type
            )

            if handler is None:
                raise ValueError(
                    f"No handler for {event_type}"
                )

            handler(event)

            self.idempotency.mark_processed(
                event_id
            )

            return {
                "acknowledged": True,
                "status": "processed",
                "event_id": event_id,
            }

        except Exception as exc:
            logger.exception(
                "Kafka event processing failed"
            )

            try:
                dlq_result = self._send_to_dlq(
                    message=message,
                    event=event,
                    error=str(exc),
                )

                if (
                    not dlq_result["inserted"]
                    and not dlq_result["duplicate"]
                ):
                    raise RuntimeError(
                        "DLQ insertion not confirmed"
                    )

                return {
                    "acknowledged": True,
                    "status": "sent_to_dlq",
                    "event_id": (
                        event.get("event_id")
                        if isinstance(event, dict)
                        else None
                    ),
                }

            except Exception:
                logger.exception(
                    "Failed to persist Kafka event to DLQ"
                )

                return {
                    "acknowledged": False,
                    "status": "dlq_failed",
                }

    def run(self):
        """
        Start consuming messages.

        Process records in partition order and
        commit offsets after each acknowledged
        message. Stop processing on failures
        that could otherwise skip a record.
        """

        if self.consumer is None:
            self.connect()

        logger.info(
            "Kafka consumer started: %s",
            self.config.group_id,
        )

        try:
            while not self.stop_event.is_set():
                batches = self.consumer.poll(
                    timeout_ms=(
                        self.config.poll_timeout_ms
                    ),
                    max_records=(
                        self.config.max_poll_records
                    ),
                )

                for _, messages in batches.items():
                    for message in messages:
                        if self.stop_event.is_set():
                            break

                        result = self.process_message(
                            message
                        )

                        if not result["acknowledged"]:
                            logger.error(
                                "Unacknowledged event; "
                                "stopping consumer"
                            )
                            self.stop_event.set()
                            break

                        # Commit the acknowledged record.
                        # In production, use explicit
                        # TopicPartition/OffsetAndMetadata
                        # offsets for precise per-partition
                        # commit tracking.
                        self.consumer.commit()

                    if self.stop_event.is_set():
                        break

        finally:
            self.close()

    def stop(self):
        self.stop_event.set()

    def close(self):
        if self.consumer is not None:
            self.consumer.close()
            self.consumer = None

        self.idempotency.close()

        if self._owns_dlq:
            self.dlq.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO
    )

    consumer = RetailKafkaConsumer()

    def handle_inventory(event: dict):
        payload = event["payload"]

        print(
            "Inventory event:",
            payload["sku"],
            payload["available"],
        )

        # Read-only handler.
        # Add approved downstream integrations here.

    def handle_sales(event: dict):
        print(
            "Sales event:",
            event["payload"]["transaction_id"],
        )

    consumer.register_handler(
        "inventory.snapshot_updated",
        handle_inventory,
    )

    consumer.register_handler(
        "pos.transaction_recorded",
        handle_sales,
    )

    try:
        consumer.run()
    except KeyboardInterrupt:
        consumer.stop()
