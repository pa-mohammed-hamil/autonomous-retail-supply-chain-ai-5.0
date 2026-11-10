from __future__ import annotations

"""Planned module: alert worker. Implementation pending."""

"""
ai/workers/alert_worker.py

Autonomous Retail Supply Chain AI 5.0

Features:
- Background alert processing
- Inventory stockout notifications
- Demand spike alerts
- Supplier disruption alerts
- Delivery delay notifications
- Warehouse safety alerts
- Retry with exponential backoff
- Dead-letter queue
- Idempotent alert submission
- SQLite persistence
- Pluggable email/SMS/push adapters
- Approval-aware alert processing

Python 3.10+
Standard library only.

Notification adapters must be configured
separately. No live SMS/email is sent by default.
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


def iso_now() -> str:
    return utc_now().isoformat()


@dataclass(frozen=True)
class AlertWorkerConfig:
    database_path: str = "data/workers/alerts.db"
    max_attempts: int = 5
    retry_base_seconds: int = 5
    poll_interval_seconds: float = 2.0
    lease_seconds: int = 120
    max_message_length: int = 2000

    def __post_init__(self):
        if self.max_attempts < 1:
            raise ValueError("Invalid max_attempts")
        if self.retry_base_seconds < 1:
            raise ValueError("Invalid retry delay")
        if self.lease_seconds < 1:
            raise ValueError("Invalid lease")
        if self.poll_interval_seconds <= 0:
            raise ValueError("Invalid polling interval")


@dataclass(frozen=True)
class Alert:
    alert_id: str
    alert_type: str
    severity: str
    recipient_reference: str
    message: str
    channel: str = "internal"
    requires_approval: bool = False


# Adapter signature:
# adapter(recipient_reference, message, alert_id)
# Must raise an exception on delivery failure.
NotificationAdapter = Callable[[str, str, str], None]


class AlertWorker:

    ALERT_TYPES = {
        "inventory_stockout",
        "low_inventory",
        "demand_spike",
        "supplier_disruption",
        "delivery_delay",
        "warehouse_safety",
        "payment_risk",
        "system_failure",
    }

    SEVERITIES = {
        "info",
        "warning",
        "high",
        "critical",
    }

    CHANNELS = {
        "internal",
        "email",
        "sms",
        "push",
        "webhook",
    }

    def __init__(
        self,
        config: AlertWorkerConfig | None = None,
    ):
        self.config = config or AlertWorkerConfig()

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

        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS alerts (
                alert_id TEXT PRIMARY KEY,
                alert_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                recipient_reference TEXT NOT NULL,
                message TEXT NOT NULL,
                channel TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                requires_approval INTEGER NOT NULL,
                approved INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                lease_until TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                delivered_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_alert_queue
            ON alerts(status, next_attempt_at);

            CREATE TABLE IF NOT EXISTS alert_audit (
                audit_id TEXT PRIMARY KEY,
                alert_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
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
        message: str,
        alert_id: str,
    ) -> None:
        # Internal delivery means the alert is
        # durably recorded, not externally sent.
        return None

    def register_adapter(
        self,
        channel: str,
        adapter: NotificationAdapter,
    ) -> None:
        if channel not in self.CHANNELS:
            raise ValueError("Invalid channel")

        if not callable(adapter):
            raise ValueError("Adapter must be callable")

        self.adapters[channel] = adapter

    def _audit(
        self,
        alert_id: str,
        action: str,
        actor: str,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO alert_audit (
                audit_id, alert_id, action,
                actor, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                alert_id,
                action,
                actor,
                iso_now(),
            ),
        )

    def enqueue(self, alert: Alert) -> dict:
        if alert.alert_type not in self.ALERT_TYPES:
            raise ValueError("Invalid alert type")

        if alert.severity not in self.SEVERITIES:
            raise ValueError("Invalid severity")

        if alert.channel not in self.CHANNELS:
            raise ValueError("Invalid channel")

        if not alert.alert_id.strip():
            raise ValueError("Alert ID required")

        if not alert.recipient_reference.strip():
            raise ValueError("Recipient reference required")

        if (
            not alert.message.strip()
            or len(alert.message)
            > self.config.max_message_length
        ):
            raise ValueError("Invalid alert message")

        initial_status = (
            "pending_approval"
            if alert.requires_approval
            else "pending"
        )

        with self.db:
            cursor = self.db.execute(
                """
                INSERT OR IGNORE INTO alerts (
                    alert_id, alert_type, severity,
                    recipient_reference, message,
                    channel, status, attempts,
                    requires_approval, approved,
                    next_attempt_at, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 0, ?, ?)
                """,
                (
                    alert.alert_id,
                    alert.alert_type,
                    alert.severity,
                    alert.recipient_reference,
                    alert.message,
                    alert.channel,
                    initial_status,
                    int(alert.requires_approval),
                    iso_now(),
                    iso_now(),
                ),
            )

            if cursor.rowcount == 1:
                self._audit(
                    alert.alert_id,
                    "enqueued",
                    "system",
                )

        return {
            "alert_id": alert.alert_id,
            "created": cursor.rowcount == 1,
            "status": initial_status
            if cursor.rowcount == 1
            else "existing",
        }

    def approve(
        self,
        alert_id: str,
        approved_by: str,
        approval_verified: bool,
    ) -> dict:
        # approval_verified must originate from
        # trusted server-side authorization.
        if not approval_verified:
            raise PermissionError(
                "Verified approval required"
            )

        if not approved_by.strip():
            raise ValueError("Approver required")

        with self.db:
            cursor = self.db.execute(
                """
                UPDATE alerts
                SET status = 'pending',
                    approved = 1
                WHERE alert_id = ?
                  AND status = 'pending_approval'
                """,
                (alert_id,),
            )

            if cursor.rowcount:
                self._audit(
                    alert_id,
                    "approved",
                    approved_by,
                )

        if not cursor.rowcount:
            raise ValueError(
                "Alert not found or not awaiting approval"
            )

        return {
            "alert_id": alert_id,
            "approved": True,
        }

    def _claim_next(self) -> dict | None:
        now = iso_now()

        self.db.execute("BEGIN IMMEDIATE")

        try:
            row = self.db.execute(
                """
                SELECT *
                FROM alerts
                WHERE (
                    status IN ('pending', 'retry')
                    AND next_attempt_at <= ?
                )
                OR (
                    status = 'processing'
                    AND lease_until <= ?
                )
                ORDER BY created_at
                LIMIT 1
                """,
                (now, now),
            ).fetchone()

            if row is None:
                self.db.commit()
                return None

            lease_until = (
                utc_now()
                + timedelta(
                    seconds=self.config.lease_seconds
                )
            ).isoformat()

            self.db.execute(
                """
                UPDATE alerts
                SET status = 'processing',
                    attempts = attempts + 1,
                    lease_until = ?
                WHERE alert_id = ?
                """,
                (
                    lease_until,
                    row["alert_id"],
                ),
            )

            self.db.commit()

            return dict(row)

        except Exception:
            self.db.rollback()
            raise

    def process_one(self) -> dict | None:
        alert = self._claim_next()

        if alert is None:
            return None

        alert_id = alert["alert_id"]
        attempt = alert["attempts"] + 1

        try:
            adapter = self.adapters.get(
                alert["channel"]
            )

            if adapter is None:
                raise RuntimeError(
                    "Notification adapter not configured"
                )

            adapter(
                alert["recipient_reference"],
                alert["message"],
                alert_id,
            )

            with self.db:
                self.db.execute(
                    """
                    UPDATE alerts
                    SET status = 'delivered',
                        delivered_at = ?,
                        lease_until = NULL,
                        last_error = NULL
                    WHERE alert_id = ?
                      AND status = 'processing'
                    """,
                    (
                        iso_now(),
                        alert_id,
                    ),
                )

                self._audit(
                    alert_id,
                    "delivered",
                    "worker",
                )

            return {
                "alert_id": alert_id,
                "status": "delivered",
                "attempt": attempt,
            }

        except Exception as exc:
            if attempt >= self.config.max_attempts:
                next_status = "dead_letter"
                next_time = iso_now()
            else:
                next_status = "retry"
                delay = min(
                    self.config.retry_base_seconds
                    * (2 ** (attempt - 1)),
                    3600,
                )
                next_time = (
                    utc_now()
                    + timedelta(seconds=delay)
                ).isoformat()

            with self.db:
                self.db.execute(
                    """
                    UPDATE alerts
                    SET status = ?,
                        next_attempt_at = ?,
                        lease_until = NULL,
                        last_error = ?
                    WHERE alert_id = ?
                      AND status = 'processing'
                    """,
                    (
                        next_status,
                        next_time,
                        type(exc).__name__,
                        alert_id,
                    ),
                )

                self._audit(
                    alert_id,
                    next_status,
                    "worker",
                )

            return {
                "alert_id": alert_id,
                "status": next_status,
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
            FROM alerts
            GROUP BY status
            """
        ).fetchall()

        return {
            "statuses": {
                row["status"]: row["count"]
                for row in rows
            },
            "external_delivery_configured": [
                channel
                for channel in self.adapters
                if channel != "internal"
            ],
        }

    def close(self) -> None:
        self.db.close()


if __name__ == "__main__":
    worker = AlertWorker()

    worker.enqueue(
        Alert(
            alert_id="low-stock-SKU101-WHKOCHI",
            alert_type="low_inventory",
            severity="high",
            recipient_reference="inventory_manager",
            message=(
                "SKU-101 stock is below "
                "the configured reorder point."
            ),
            channel="internal",
        )
    )

    print(worker.process_one())
    print(json.dumps(worker.summary(), indent=2))

    worker.close()
