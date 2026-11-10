
"""
Dead-letter queue for failed retail pipeline events.

Features:
- SQLite-backed durable storage
- Idempotent event insertion
- Retry attempts and exponential backoff
- Claim leases for concurrent workers
- Dead-letter event inspection
- Manual replay requests
- Event quarantine
- Safe acknowledgement
- Failure history

Standard library only. Python 3.10+.

The queue stores failed events. It does not
automatically execute purchases, refunds,
stock changes or external API calls.
"""

from __future__ import annotations

import json
import random
import sqlite3
import uuid

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("Timezone-aware datetime required")
    return dt.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class DLQConfig:
    database_path: str = "data/dead_letter_queue.db"
    max_attempts: int = 5
    initial_backoff_seconds: int = 30
    max_backoff_seconds: int = 3600
    lease_seconds: int = 120

    def __post_init__(self):
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.initial_backoff_seconds < 1:
            raise ValueError("Backoff must be positive")
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("Invalid maximum backoff")
        if self.lease_seconds < 1:
            raise ValueError("Lease must be positive")


class DeadLetterQueue:

    def __init__(self, config: DLQConfig | None = None):
        self.config = config or DLQConfig()

        db_path = Path(self.config.database_path)
        db_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.connection = sqlite3.connect(
            str(db_path),
            timeout=30,
            isolation_level=None,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=30000")

        self._initialize()

    def _initialize(self):
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS dead_letters (
                event_id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                error_message TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                next_retry_at TEXT,
                lease_token TEXT,
                lease_until TEXT,
                last_error_at TEXT,
                CHECK (
                    status IN (
                        'pending',
                        'processing',
                        'resolved',
                        'exhausted',
                        'quarantined'
                    )
                )
            );

            CREATE INDEX IF NOT EXISTS idx_dlq_status_retry
            ON dead_letters(status, next_retry_at);

            CREATE TABLE IF NOT EXISTS dlq_attempt_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                outcome TEXT NOT NULL,
                message TEXT,
                occurred_at TEXT NOT NULL
            );
            """
        )

    def enqueue(
        self,
        event_id: str,
        event_type: str,
        payload: dict[str, Any],
        error_message: str,
    ) -> dict:
        """
        Insert an event only once.

        Repeated event_id values do not overwrite
        existing payloads or retry state.
        """

        if not event_id or not event_type:
            raise ValueError("Event identifiers required")

        if not isinstance(payload, dict):
            raise ValueError("Payload must be a dictionary")

        payload_json = json.dumps(
            payload,
            allow_nan=False,
            separators=(",", ":"),
        )

        now = iso(utc_now())

        cursor = self.connection.execute(
            """
            INSERT OR IGNORE INTO dead_letters (
                event_id, event_type, payload_json,
                error_message, status, attempts,
                created_at, updated_at, next_retry_at,
                last_error_at
            )
            VALUES (?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?)
            """,
            (
                event_id,
                event_type,
                payload_json,
                str(error_message)[:2000],
                now,
                now,
                now,
                now,
            ),
        )

        return {
            "event_id": event_id,
            "inserted": cursor.rowcount == 1,
            "duplicate": cursor.rowcount == 0,
        }

    def claim_next(self) -> dict | None:
        """
        Atomically claim one eligible event.

        A lease prevents simultaneous workers from
        intentionally processing the same queue row.

        Handlers must still be idempotent because a
        lease may expire while work is in progress.
        """

        now_dt = utc_now()
        now = iso(now_dt)
        lease_until = iso(
            now_dt + timedelta(
                seconds=self.config.lease_seconds
            )
        )
        token = uuid.uuid4().hex

        self.connection.execute("BEGIN IMMEDIATE")

        try:
            row = self.connection.execute(
                """
                SELECT *
                FROM dead_letters
                WHERE attempts < ?
                  AND (
                    (
                      status = 'pending'
                      AND next_retry_at <= ?
                    )
                    OR (
                      status = 'processing'
                      AND lease_until <= ?
                    )
                  )
                ORDER BY created_at, event_id
                LIMIT 1
                """,
                (
                    self.config.max_attempts,
                    now,
                    now,
                ),
            ).fetchone()

            if row is None:
                self.connection.execute("COMMIT")
                return None

            attempt = row["attempts"] + 1

            self.connection.execute(
                """
                UPDATE dead_letters
                SET status = 'processing',
                    attempts = ?,
                    lease_token = ?,
                    lease_until = ?,
                    updated_at = ?
                WHERE event_id = ?
                """,
                (
                    attempt,
                    token,
                    lease_until,
                    now,
                    row["event_id"],
                ),
            )

            self.connection.execute("COMMIT")

        except Exception:
            self.connection.execute("ROLLBACK")
            raise

        return {
            "event_id": row["event_id"],
            "event_type": row["event_type"],
            "payload": json.loads(row["payload_json"]),
            "attempt": attempt,
            "lease_token": token,
            "lease_until": lease_until,
        }

    def acknowledge(
        self,
        event_id: str,
        lease_token: str,
    ) -> bool:
        now = iso(utc_now())

        self.connection.execute("BEGIN IMMEDIATE")

        try:
            row = self.connection.execute(
                """
                SELECT attempts
                FROM dead_letters
                WHERE event_id = ?
                  AND lease_token = ?
                  AND status = 'processing'
                  AND lease_until > ?
                """,
                (event_id, lease_token, now),
            ).fetchone()

            if row is None:
                self.connection.execute("COMMIT")
                return False

            self.connection.execute(
                """
                UPDATE dead_letters
                SET status = 'resolved',
                    lease_token = NULL,
                    lease_until = NULL,
                    next_retry_at = NULL,
                    updated_at = ?
                WHERE event_id = ?
                """,
                (now, event_id),
            )

            self.connection.execute(
                """
                INSERT INTO dlq_attempt_history
                (event_id, attempt, outcome, message, occurred_at)
                VALUES (?, ?, 'resolved', NULL, ?)
                """,
                (event_id, row["attempts"], now),
            )

            self.connection.execute("COMMIT")
            return True

        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def fail(
        self,
        event_id: str,
        lease_token: str,
        error_message: str,
        retryable: bool = True,
    ) -> dict:
        now_dt = utc_now()
        now = iso(now_dt)

        self.connection.execute("BEGIN IMMEDIATE")

        try:
            row = self.connection.execute(
                """
                SELECT attempts
                FROM dead_letters
                WHERE event_id = ?
                  AND lease_token = ?
                  AND status = 'processing'
                  AND lease_until > ?
                """,
                (event_id, lease_token, now),
            ).fetchone()

            if row is None:
                self.connection.execute("COMMIT")
                return {
                    "updated": False,
                    "reason": "invalid_or_expired_lease",
                }

            attempts = row["attempts"]

            if not retryable:
                status = "quarantined"
                next_retry = None

            elif attempts >= self.config.max_attempts:
                status = "exhausted"
                next_retry = None

            else:
                status = "pending"

                delay = min(
                    self.config.max_backoff_seconds,
                    self.config.initial_backoff_seconds
                    * (2 ** (attempts - 1)),
                )

                jitter = random.uniform(0, delay * 0.1)

                next_retry = iso(
                    now_dt + timedelta(
                        seconds=delay + jitter
                    )
                )

            self.connection.execute(
                """
                UPDATE dead_letters
                SET status = ?,
                    error_message = ?,
                    next_retry_at = ?,
                    lease_token = NULL,
                    lease_until = NULL,
                    last_error_at = ?,
                    updated_at = ?
                WHERE event_id = ?
                """,
                (
                    status,
                    str(error_message)[:2000],
                    next_retry,
                    now,
                    now,
                    event_id,
                ),
            )

            self.connection.execute(
                """
                INSERT INTO dlq_attempt_history
                (event_id, attempt, outcome, message, occurred_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    attempts,
                    status,
                    str(error_message)[:2000],
                    now,
                ),
            )

            self.connection.execute("COMMIT")

            return {
                "updated": True,
                "event_id": event_id,
                "status": status,
                "next_retry_at": next_retry,
            }

        except Exception:
            self.connection.execute("ROLLBACK")
            raise

    def replay(
        self,
        event_id: str,
        approved: bool = False,
    ) -> dict:
        """
        Request manual replay.

        Requires explicit approval and does not
        immediately execute the event handler.
        """

        if not approved:
            return {
                "replayed": False,
                "reason": "approval_required",
            }

        now = iso(utc_now())

        cursor = self.connection.execute(
            """
            UPDATE dead_letters
            SET status = 'pending',
                attempts = 0,
                next_retry_at = ?,
                lease_token = NULL,
                lease_until = NULL,
                updated_at = ?
            WHERE event_id = ?
              AND status IN (
                'exhausted',
                'quarantined',
                'resolved'
              )
            """,
            (now, now, event_id),
        )

        return {
            "replay_requested": cursor.rowcount == 1,
            "event_id": event_id,
        }

    def list_events(
        self,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if not 1 <= limit <= 1000:
            raise ValueError("Invalid limit")

        if status is None:
            rows = self.connection.execute(
                """
                SELECT * FROM dead_letters
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT * FROM dead_letters
                WHERE status = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (status, limit),
            ).fetchall()

        return [
            {
                **dict(row),
                "payload": json.loads(
                    row["payload_json"]
                ),
                "payload_json": None,
            }
            for row in rows
        ]

    def process_one(
        self,
        handlers: dict[str, Callable[[dict], None]],
    ) -> dict:
        """
        Execute one claimed event.

        Handler functions must be idempotent.
        Never retry irreversible actions without
        their own idempotency and approval controls.
        """

        event = self.claim_next()

        if event is None:
            return {
                "processed": False,
                "reason": "no_ready_events",
            }

        handler = handlers.get(event["event_type"])

        if handler is None:
            return self.fail(
                event["event_id"],
                event["lease_token"],
                "No registered event handler",
                retryable=False,
            )

        try:
            handler(event["payload"])

        except Exception as exc:
            return self.fail(
                event["event_id"],
                event["lease_token"],
                str(exc),
                retryable=True,
            )

        acknowledged = self.acknowledge(
            event["event_id"],
            event["lease_token"],
        )

        return {
            "processed": acknowledged,
            "event_id": event["event_id"],
            "status": (
                "resolved"
                if acknowledged
                else "acknowledgement_failed"
            ),
        }

    def close(self):
        self.connection.close()


if __name__ == "__main__":
    queue = DeadLetterQueue(
        DLQConfig(
            database_path="data/demo_dlq.db",
            max_attempts=3,
        )
    )

    queue.enqueue(
        event_id="EVT-1001",
        event_type="inventory.validation_failed",
        payload={
            "sku": "SKU-101",
            "warehouse_id": "WH-KOCHI",
            "quantity": 100,
        },
        error_message="Temporary validation dependency failure",
    )

    def handle_inventory(payload: dict):
        print("Validated event:", payload)

    result = queue.process_one({
        "inventory.validation_failed": handle_inventory
    })

    print(result)
    print(queue.list_events())

    queue.close()
