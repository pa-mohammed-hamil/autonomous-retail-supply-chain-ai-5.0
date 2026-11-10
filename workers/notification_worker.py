from __future__ import annotations

"""Planned module: notification worker. Implementation pending."""

"""
ai/workers/notification_worker.py

Autonomous Retail Supply Chain AI 5.0

Features:
- Asynchronous notification queue
- Email/SMS/push/webhook/internal channels
- Notification templates
- Recipient channel preferences
- Retry with exponential backoff
- Dead-letter handling
- Delivery status tracking
- Idempotent notification submission
- SQLite persistence
- Pluggable notification providers

Python 3.10+
Standard library only.

No real external notifications are sent
until provider adapters are registered.

Provider adapters should support
idempotency keys where possible.
"""


import json
import sqlite3
import time
import uuid

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Adapter(recipient_reference, subject, body, notification_id)
NotificationAdapter = Callable[
    [str, str, str, str],
    None,
]


@dataclass(frozen=True)
class NotificationConfig:
    database_path: str = (
        "data/workers/notifications.db"
    )
    max_attempts: int = 5
    retry_base_seconds: int = 5
    lease_seconds: int = 120
    poll_interval_seconds: float = 2.0
    max_body_length: int = 10000

    def __post_init__(self):
        if self.max_attempts < 1:
            raise ValueError("Invalid attempts")
        if self.retry_base_seconds < 1:
            raise ValueError("Invalid retry delay")
        if self.lease_seconds < 1:
            raise ValueError("Invalid lease")
        if self.poll_interval_seconds <= 0:
            raise ValueError("Invalid polling interval")


@dataclass(frozen=True)
class Notification:
    notification_id: str
    recipient_reference: str
    channel: str
    subject: str
    body: str
    category: str = "operational"
    priority: str = "normal"


class NotificationWorker:

    CHANNELS = {
        "internal", "email", "sms",
        "push", "webhook",
    }

    PRIORITIES = {
        "low", "normal", "high", "critical",
    }

    def __init__(
        self,
        config: NotificationConfig | None = None,
    ):
        self.config = config or NotificationConfig()

        path = Path(self.config.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        self.db = sqlite3.connect(str(path), timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=30000")

        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS notifications (
                notification_id TEXT PRIMARY KEY,
                recipient_reference TEXT NOT NULL,
                channel TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                category TEXT NOT NULL,
                priority TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                lease_until TEXT,
                error_type TEXT,
                created_at TEXT NOT NULL,
                delivered_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_notification_queue
            ON notifications(status, next_attempt_at);

            CREATE TABLE IF NOT EXISTS recipient_preferences (
                recipient_reference TEXT NOT NULL,
                channel TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                PRIMARY KEY (recipient_reference, channel)
            );

            CREATE TABLE IF NOT EXISTS notification_audit (
                audit_id TEXT PRIMARY KEY,
                notification_id TEXT NOT NULL,
                action TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        self.db.commit()

        self.adapters: dict[
            str, NotificationAdapter
        ] = {
            "internal": self._internal_adapter
        }

        self.running = False

    @staticmethod
    def _internal_adapter(
        recipient: str,
        subject: str,
        body: str,
        notification_id: str,
    ) -> None:
        # The queue itself provides the
        # durable internal notification record.
        return None

    def register_adapter(
        self,
        channel: str,
        adapter: NotificationAdapter,
    ) -> None:
        if channel not in self.CHANNELS:
            raise ValueError("Unsupported channel")
        if not callable(adapter):
            raise ValueError("Adapter must be callable")
        self.adapters[channel] = adapter

    def set_preference(
        self,
        recipient_reference: str,
        channel: str,
        enabled: bool,
    ) -> None:
        # Call only after verifying the
        # recipient's identity and authority.
        if channel not in self.CHANNELS:
            raise ValueError("Invalid channel")

        with self.db:
            self.db.execute(
                """
                INSERT INTO recipient_preferences (
                    recipient_reference, channel, enabled
                )
                VALUES (?, ?, ?)
                ON CONFLICT(recipient_reference, channel)
                DO UPDATE SET enabled = excluded.enabled
                """,
                (
                    recipient_reference,
                    channel,
                    int(enabled),
                ),
            )

    def _channel_enabled(
        self,
        recipient_reference: str,
        channel: str,
    ) -> bool:
        row = self.db.execute(
            """
            SELECT enabled
            FROM recipient_preferences
            WHERE recipient_reference = ?
              AND channel = ?
            """,
            (recipient_reference, channel),
        ).fetchone()

        return bool(row["enabled"]) if row else True

    def _audit(
        self,
        notification_id: str,
        action: str,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO notification_audit (
                audit_id, notification_id,
                action, created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                notification_id,
                action,
                utc_now().isoformat(),
            ),
        )

    def enqueue(self, notification: Notification) -> dict:
        if notification.channel not in self.CHANNELS:
            raise ValueError("Invalid channel")

        if notification.priority not in self.PRIORITIES:
            raise ValueError("Invalid priority")

        if not notification.notification_id.strip():
            raise ValueError("Notification ID required")

        if not notification.recipient_reference.strip():
            raise ValueError("Recipient required")

        if (
            not notification.body.strip()
            or len(notification.body)
            > self.config.max_body_length
        ):
            raise ValueError("Invalid body")

        if not self._channel_enabled(
            notification.recipient_reference,
            notification.channel,
        ):
            return {
                "notification_id": notification.notification_id,
                "created": False,
                "status": "channel_disabled",
            }

        with self.db:
            cursor = self.db.execute(
                """
                INSERT OR IGNORE INTO notifications (
                    notification_id, recipient_reference,
                    channel, subject, body,
                    category, priority, status,
                    next_attempt_at, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?,
                        'pending', ?, ?)
                """,
                (
                    notification.notification_id,
                    notification.recipient_reference,
                    notification.channel,
                    notification.subject,
                    notification.body,
                    notification.category,
                    notification.priority,
                    utc_now().isoformat(),
                    utc_now().isoformat(),
                ),
            )

            if cursor.rowcount:
                self._audit(
                    notification.notification_id,
                    "enqueued",
                )

        return {
            "notification_id": notification.notification_id,
            "created": cursor.rowcount == 1,
            "status": (
                "pending"
                if cursor.rowcount
                else "existing"
            ),
        }

    def _claim_next(self) -> dict | None:
        now = utc_now()

        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                """
                SELECT *
                FROM notifications
                WHERE (
                    status IN ('pending', 'retry')
                    AND next_attempt_at <= ?
                )
                OR (
                    status = 'processing'
                    AND lease_until <= ?
                )
                ORDER BY
                    CASE priority
                        WHEN 'critical' THEN 0
                        WHEN 'high' THEN 1
                        WHEN 'normal' THEN 2
                        ELSE 3
                    END,
                    created_at
                LIMIT 1
                """,
                (now.isoformat(), now.isoformat()),
            ).fetchone()

            if row is None:
                self.db.commit()
                return None

            lease_until = (
                now + timedelta(
                    seconds=self.config.lease_seconds
                )
            ).isoformat()

            self.db.execute(
                """
                UPDATE notifications
                SET status = 'processing',
                    attempts = attempts + 1,
                    lease_until = ?
                WHERE notification_id = ?
                """,
                (
                    lease_until,
                    row["notification_id"],
                ),
            )

            self.db.commit()
            return dict(row)

        except Exception:
            self.db.rollback()
            raise

    def process_one(self) -> dict | None:
        row = self._claim_next()

        if row is None:
            return None

        notification_id = row["notification_id"]
        attempt = row["attempts"] + 1

        try:
            if not self._channel_enabled(
                row["recipient_reference"],
                row["channel"],
            ):
                with self.db:
                    self.db.execute(
                        """
                        UPDATE notifications
                        SET status = 'cancelled',
                            lease_until = NULL
                        WHERE notification_id = ?
                        """,
                        (notification_id,),
                    )
                    self._audit(
                        notification_id,
                        "cancelled_preference",
                    )

                return {
                    "notification_id": notification_id,
                    "status": "cancelled",
                }

            adapter = self.adapters.get(row["channel"])

            if adapter is None:
                raise RuntimeError(
                    "Notification adapter not configured"
                )

            adapter(
                row["recipient_reference"],
                row["subject"],
                row["body"],
                notification_id,
            )

            with self.db:
                self.db.execute(
                    """
                    UPDATE notifications
                    SET status = 'delivered',
                        delivered_at = ?,
                        lease_until = NULL,
                        error_type = NULL
                    WHERE notification_id = ?
                    """,
                    (
                        utc_now().isoformat(),
                        notification_id,
                    ),
                )
                self._audit(
                    notification_id,
                    "delivered",
                )

            return {
                "notification_id": notification_id,
                "status": "delivered",
                "attempt": attempt,
            }

        except Exception as exc:
            if attempt >= self.config.max_attempts:
                status = "dead_letter"
                next_attempt = utc_now()
            else:
                status = "retry"
                delay = min(
                    self.config.retry_base_seconds
                    * (2 ** (attempt - 1)),
                    3600,
                )
                next_attempt = (
                    utc_now() + timedelta(seconds=delay)
                )

            with self.db:
                self.db.execute(
                    """
                    UPDATE notifications
                    SET status = ?,
                        next_attempt_at = ?,
                        lease_until = NULL,
                        error_type = ?
                    WHERE notification_id = ?
                    """,
                    (
                        status,
                        next_attempt.isoformat(),
                        type(exc).__name__,
                        notification_id,
                    ),
                )
                self._audit(
                    notification_id,
                    status,
                )

            return {
                "notification_id": notification_id,
                "status": status,
                "attempt": attempt,
                "error_type": type(exc).__name__,
            }

    def run(self) -> None:
        self.running = True
        try:
            while self.running:
                result = self.process_one()
                if result is None:
                    time.sleep(
                        self.config.poll_interval_seconds
                    )
        finally:
            self.running = False

    def stop(self) -> None:
        self.running = False

    def summary(self) -> dict:
        rows = self.db.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM notifications
            GROUP BY status
            """
        ).fetchall()

        return {
            "statuses": {
                row["status"]: row["count"]
                for row in rows
            },
            "configured_channels": sorted(
                self.adapters
            ),
        }

    def close(self) -> None:
        self.db.close()


if __name__ == "__main__":
    worker = NotificationWorker()

    notification = Notification(
        notification_id="notification-demo-001",
        recipient_reference="operations_manager",
        channel="internal",
        subject="Inventory Warning",
        body=(
            "SKU-101 inventory is below "
            "the configured reorder point."
        ),
        category="inventory",
        priority="high",
    )

    print(json.dumps(
        worker.enqueue(notification), indent=2
    ))
    print(json.dumps(
        worker.process_one(), indent=2
    ))
    print(json.dumps(
        worker.summary(), indent=2
    ))

    worker.close()
