"""Planned module: replay. Implementation pending."""

"""
Dead-letter event replay controller.

Integrates:
- DeadLetterQueue
- EventValidation
- EventSchemas
- RetailKafkaProducer

Features:
- Inspect failed events
- Validate original event envelopes
- Manual approval for replay
- Dry-run validation
- Publish replay events to Kafka
- Preserve original event IDs
- Replay audit history
- Batch replay with per-event results

Replay is not automatic.

Important:
The existing DeadLetterQueue.replay() method
resets attempts and makes events available to
DLQ handlers. This module instead republishes
valid original events to Kafka.

To avoid duplicate operational effects, replay
consumers must implement durable idempotency.
"""

from __future__ import annotations

import json
import sqlite3

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai.pipelines.dead_letter_queue import (
    DeadLetterQueue,
)
from ai.pipelines.event_validation import (
    EventValidation,
    EventValidationConfig,
)
from ai.pipelines.kafka_producer import (
    RetailKafkaProducer,
    KafkaProducerConfig,
)


@dataclass(frozen=True)
class ReplayConfig:
    audit_database_path: str = (
        "data/event_replay_audit.db"
    )
    max_batch_size: int = 100
    require_approval: bool = True

    def __post_init__(self):
        if (
            isinstance(self.max_batch_size, bool)
            or not isinstance(self.max_batch_size, int)
            or not 1 <= self.max_batch_size <= 1000
        ):
            raise ValueError("Invalid max_batch_size")


class EventReplay:

    def __init__(
        self,
        dlq: DeadLetterQueue,
        producer: RetailKafkaProducer,
        config: ReplayConfig | None = None,
        validator: EventValidation | None = None,
    ):
        self.dlq = dlq
        self.producer = producer
        self.config = config or ReplayConfig()

        # Historical events may be older than the
        # normal consumer freshness window.
        # Replay still checks schema and timestamps.
        self.validator = validator or EventValidation(
            EventValidationConfig(
                max_event_age_hours=87600,
                reject_stale_events=False,
            )
        )

        path = Path(
            self.config.audit_database_path
        )
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.connection = sqlite3.connect(
            str(path),
            timeout=30,
        )

        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS replay_audit (
                replay_id INTEGER PRIMARY KEY AUTOINCREMENT,
                dlq_event_id TEXT NOT NULL,
                original_event_id TEXT,
                requested_by TEXT NOT NULL,
                approved_by TEXT,
                dry_run INTEGER NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                created_at TEXT NOT NULL
            )
            """
        )

        self.connection.commit()

    def _find_dlq_event(
        self,
        dlq_event_id: str,
    ) -> dict | None:
        """
        Read one record from the existing
        DeadLetterQueue SQLite connection.
        """

        row = self.dlq.connection.execute(
            """
            SELECT *
            FROM dead_letters
            WHERE event_id = ?
            """,
            (dlq_event_id,),
        ).fetchone()

        if row is None:
            return None

        result = dict(row)
        result["payload"] = json.loads(
            result["payload_json"]
        )

        return result

    @staticmethod
    def _extract_event(
        dlq_record: dict,
    ) -> dict:
        payload = dlq_record["payload"]

        # Kafka consumer DLQ format.
        if (
            isinstance(payload, dict)
            and "original_event" in payload
        ):
            original = payload["original_event"]

        # Directly queued event envelope.
        else:
            original = payload

        if not isinstance(original, dict):
            raise ValueError(
                "No structured event envelope available"
            )

        return original

    def _audit(
        self,
        dlq_event_id: str,
        original_event_id: str | None,
        requested_by: str,
        approved_by: str | None,
        dry_run: bool,
        status: str,
        message: str | None = None,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO replay_audit (
                dlq_event_id,
                original_event_id,
                requested_by,
                approved_by,
                dry_run,
                status,
                message,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dlq_event_id,
                original_event_id,
                requested_by,
                approved_by,
                int(dry_run),
                status,
                message,
                datetime.now(
                    timezone.utc
                ).isoformat(),
            ),
        )

        self.connection.commit()

    def inspect(
        self,
        dlq_event_id: str,
    ) -> dict:
        record = self._find_dlq_event(
            dlq_event_id
        )

        if record is None:
            return {
                "found": False,
                "dlq_event_id": dlq_event_id,
            }

        try:
            event = self._extract_event(record)
            validation = self.validator.validate(
                event
            )

        except (ValueError, TypeError) as exc:
            validation = {
                "valid": False,
                "errors": [str(exc)],
                "warnings": [],
            }
            event = None

        return {
            "found": True,
            "dlq_event_id": dlq_event_id,
            "dlq_status": record["status"],
            "attempts": record["attempts"],
            "original_error": record["error_message"],
            "event_id": (
                event.get("event_id")
                if event
                else None
            ),
            "event_type": (
                event.get("event_type")
                if event
                else None
            ),
            "validation": validation,
            "eligible_for_review": (
                record["status"] in {
                    "pending",
                    "exhausted",
                    "quarantined",
                    "resolved",
                }
                and validation["valid"]
            ),
        }

    def replay_one(
        self,
        dlq_event_id: str,
        requested_by: str,
        approved_by: str | None = None,
        dry_run: bool = True,
    ) -> dict:
        """
        Replay one original event.

        Dry-run is the default.

        Real publishing requires:
        - Explicit approval
        - A valid event envelope
        - A configured Kafka producer

        The original event_id is preserved.
        """

        if not requested_by.strip():
            raise ValueError("requested_by required")

        record = self._find_dlq_event(
            dlq_event_id
        )

        if record is None:
            return {
                "replayed": False,
                "status": "not_found",
                "dlq_event_id": dlq_event_id,
            }

        try:
            event = self._extract_event(record)
        except (ValueError, TypeError) as exc:
            return {
                "replayed": False,
                "status": "invalid_dlq_payload",
                "error": str(exc),
            }

        original_event_id = event.get(
            "event_id"
        )

        validation = self.validator.validate(
            event
        )

        if not validation["valid"]:
            self._audit(
                dlq_event_id,
                original_event_id,
                requested_by,
                approved_by,
                dry_run,
                "validation_failed",
                "; ".join(validation["errors"]),
            )

            return {
                "replayed": False,
                "status": "validation_failed",
                "errors": validation["errors"],
            }

        if dry_run:
            self._audit(
                dlq_event_id,
                original_event_id,
                requested_by,
                approved_by,
                True,
                "dry_run_validated",
            )

            return {
                "replayed": False,
                "status": "dry_run_validated",
                "dlq_event_id": dlq_event_id,
                "original_event_id": original_event_id,
                "event_type": event["event_type"],
                "warnings": validation["warnings"],
            }

        if (
            self.config.require_approval
            and (
                not isinstance(approved_by, str)
                or not approved_by.strip()
            )
        ):
            return {
                "replayed": False,
                "status": "approval_required",
                "dlq_event_id": dlq_event_id,
            }

        # Revalidate using the replay-specific
        # validator, then publish the original
        # envelope without changing event_id.
        #
        # The producer applies its own validation,
        # which may reject older historical events.
        # Configure a matching replay-aware producer
        # validator when historical replay is needed.

        result = self.producer.publish_event(
            event
        )

        status = result["status"]
        published = result["published"]

        self._audit(
            dlq_event_id,
            original_event_id,
            requested_by,
            approved_by,
            False,
            status,
            result.get("error"),
        )

        return {
            "replayed": published,
            "status": status,
            "dlq_event_id": dlq_event_id,
            "original_event_id": original_event_id,
            "topic": result.get("topic"),
            "partition": result.get("partition"),
            "offset": result.get("offset"),
            "original_dlq_record_retained": True,
            "downstream_processing_confirmed": False,
        }

    def replay_batch(
        self,
        dlq_event_ids: list[str],
        requested_by: str,
        approved_by: str | None = None,
        dry_run: bool = True,
    ) -> dict:
        if not isinstance(dlq_event_ids, list):
            raise ValueError(
                "dlq_event_ids must be a list"
            )

        if (
            len(dlq_event_ids)
            > self.config.max_batch_size
        ):
            raise ValueError(
                "Replay batch exceeds configured limit"
            )

        results = []

        for event_id in dict.fromkeys(
            dlq_event_ids
        ):
            result = self.replay_one(
                dlq_event_id=event_id,
                requested_by=requested_by,
                approved_by=approved_by,
                dry_run=dry_run,
            )

            results.append(result)

        return {
            "requested_count": len(
                dlq_event_ids
            ),
            "unique_count": len(results),
            "replayed_count": sum(
                result["replayed"]
                for result in results
            ),
            "dry_run": dry_run,
            "results": results,
        }

    def audit_history(
        self,
        limit: int = 100,
    ) -> list[dict]:
        if not 1 <= limit <= 1000:
            raise ValueError("Invalid limit")

        self.connection.row_factory = (
            sqlite3.Row
        )

        rows = self.connection.execute(
            """
            SELECT *
            FROM replay_audit
            ORDER BY replay_id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def close(self):
        self.connection.close()


if __name__ == "__main__":
    from ai.pipelines.event_schemas import (
        EventSchemas,
    )
    from ai.pipelines.dead_letter_queue import (
        DLQConfig,
    )

    dlq = DeadLetterQueue(
        DLQConfig(
            database_path="data/demo_replay_dlq.db"
        )
    )

    producer = RetailKafkaProducer(
        KafkaProducerConfig(dry_run=True)
    )

    event = EventSchemas.create(
        event_type="inventory.snapshot_updated",
        source="inventory_pipeline",
        event_id="inventory-replay-demo-001",
        payload={
            "sku": "SKU-101",
            "warehouse_id": "WH-KOCHI",
            "on_hand": 120,
            "reserved": 20,
            "available": 100,
        },
    )

    dlq.enqueue(
        event_id="failed-kafka-record-001",
        event_type="kafka.processing_failed",
        payload={
            "original_event": event,
            "kafka_topic": "retail.inventory",
            "kafka_partition": 0,
            "kafka_offset": 25,
        },
        error_message="Temporary consumer failure",
    )

    replay = EventReplay(
        dlq=dlq,
        producer=producer,
    )

    print(
        replay.inspect(
            "failed-kafka-record-001"
        )
    )

    result = replay.replay_one(
        dlq_event_id="failed-kafka-record-001",
        requested_by="retail-admin",
        dry_run=True,
    )

    print(result)
    print(replay.audit_history())

    replay.close()
    producer.close()
    dlq.close()
