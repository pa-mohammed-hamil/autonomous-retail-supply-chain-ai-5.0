from __future__ import annotations


"""
ai/workers/escalation_worker.py

Autonomous Retail Supply Chain AI 5.0

Features:
- Multi-level alert escalation
- SLA deadline monitoring
- Severity-based escalation policies
- Human acknowledgment
- Role-based escalation routing
- Automatic escalation notifications
- Retry-safe escalation outbox
- Duplicate escalation prevention
- Escalation history and audit logs
- SQLite persistence

Python 3.10+
Standard library only.

External notifications are handled by
ai.workers.alert_worker.AlertWorker.

Approval and user identity must be verified
by trusted backend authentication services.
"""


import json
import sqlite3
import uuid

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai.workers.alert_worker import (
    Alert,
    AlertWorker,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(value: str) -> datetime:
    result = datetime.fromisoformat(value)

    if result.tzinfo is None:
        raise ValueError("Timezone required")

    return result.astimezone(timezone.utc)


@dataclass(frozen=True)
class EscalationConfig:
    database_path: str = (
        "data/workers/escalations.db"
    )
    max_level: int = 3
    default_sla_minutes: int = 30

    def __post_init__(self):
        if self.max_level < 1:
            raise ValueError("Invalid maximum level")

        if self.default_sla_minutes < 1:
            raise ValueError("Invalid SLA")


@dataclass(frozen=True)
class EscalationPolicy:
    severity: str
    sla_minutes: int
    recipients: tuple[str, ...]

    def __post_init__(self):
        if self.severity not in {
            "info",
            "warning",
            "high",
            "critical",
        }:
            raise ValueError("Invalid severity")

        if self.sla_minutes < 1:
            raise ValueError("Invalid SLA")

        if not self.recipients:
            raise ValueError(
                "Escalation recipients required"
            )


class EscalationWorker:

    def __init__(
        self,
        alert_worker: AlertWorker,
        config: EscalationConfig | None = None,
    ):
        self.alert_worker = alert_worker
        self.config = config or EscalationConfig()

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
            CREATE TABLE IF NOT EXISTS escalations (
                escalation_id TEXT PRIMARY KEY,
                source_alert_id TEXT NOT NULL UNIQUE,
                severity TEXT NOT NULL,
                description TEXT NOT NULL,
                level INTEGER NOT NULL,
                status TEXT NOT NULL,
                next_escalation_at TEXT NOT NULL,
                acknowledged_by TEXT,
                acknowledged_at TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS escalation_outbox (
                notification_id TEXT PRIMARY KEY,
                escalation_id TEXT NOT NULL,
                level INTEGER NOT NULL,
                recipient TEXT NOT NULL,
                message TEXT NOT NULL,
                published INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS escalation_audit (
                audit_id TEXT PRIMARY KEY,
                escalation_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)

        self.db.commit()

        self.policies = {
            "info": EscalationPolicy(
                "info", 120,
                ("operations_team",),
            ),
            "warning": EscalationPolicy(
                "warning", 60,
                (
                    "operations_team",
                    "operations_manager",
                ),
            ),
            "high": EscalationPolicy(
                "high", 30,
                (
                    "operations_manager",
                    "regional_manager",
                    "corporate_operations",
                ),
            ),
            "critical": EscalationPolicy(
                "critical", 10,
                (
                    "emergency_response_team",
                    "operations_director",
                    "corporate_escalation_team",
                ),
            ),
        }

    def register_policy(
        self,
        policy: EscalationPolicy,
    ) -> None:
        self.policies[policy.severity] = policy

    def _audit(
        self,
        escalation_id: str,
        action: str,
        actor: str,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO escalation_audit (
                audit_id, escalation_id,
                action, actor, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                escalation_id,
                action,
                actor,
                utc_now().isoformat(),
            ),
        )

    def _queue_notification(
        self,
        escalation_id: str,
        level: int,
        recipient: str,
        description: str,
    ) -> None:
        notification_id = (
            f"escalation-{escalation_id}-L{level}"
        )

        message = (
            f"Escalation level {level}: "
            f"{description}"
        )

        self.db.execute(
            """
            INSERT OR IGNORE INTO escalation_outbox (
                notification_id, escalation_id,
                level, recipient, message,
                published, created_at
            )
            VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (
                notification_id,
                escalation_id,
                level,
                recipient,
                message,
                utc_now().isoformat(),
            ),
        )

    def create_escalation(
        self,
        source_alert_id: str,
        severity: str,
        description: str,
    ) -> dict:
        if severity not in self.policies:
            raise ValueError(
                "No escalation policy configured"
            )

        if not source_alert_id.strip():
            raise ValueError(
                "Source alert ID required"
            )

        if not description.strip():
            raise ValueError(
                "Description required"
            )

        policy = self.policies[severity]

        existing = self.db.execute(
            """
            SELECT escalation_id
            FROM escalations
            WHERE source_alert_id = ?
            """,
            (source_alert_id,),
        ).fetchone()

        if existing:
            return {
                "escalation_id": existing["escalation_id"],
                "created": False,
            }

        escalation_id = uuid.uuid4().hex

        deadline = (
            utc_now()
            + timedelta(
                minutes=policy.sla_minutes
            )
        )

        with self.db:
            self.db.execute(
                """
                INSERT INTO escalations (
                    escalation_id, source_alert_id,
                    severity, description, level,
                    status, next_escalation_at,
                    created_at
                )
                VALUES (?, ?, ?, ?, 1, 'open', ?, ?)
                """,
                (
                    escalation_id,
                    source_alert_id,
                    severity,
                    description,
                    deadline.isoformat(),
                    utc_now().isoformat(),
                ),
            )

            self._queue_notification(
                escalation_id,
                1,
                policy.recipients[0],
                description,
            )

            self._audit(
                escalation_id,
                "created",
                "system",
            )

        return {
            "escalation_id": escalation_id,
            "created": True,
            "level": 1,
            "next_escalation_at": deadline.isoformat(),
        }

    def acknowledge(
        self,
        escalation_id: str,
        acknowledged_by: str,
        identity_verified: bool,
    ) -> dict:
        if not identity_verified:
            raise PermissionError(
                "Verified identity required"
            )

        if not acknowledged_by.strip():
            raise ValueError(
                "Acknowledging user required"
            )

        with self.db:
            cursor = self.db.execute(
                """
                UPDATE escalations
                SET status = 'acknowledged',
                    acknowledged_by = ?,
                    acknowledged_at = ?
                WHERE escalation_id = ?
                  AND status = 'open'
                """,
                (
                    acknowledged_by,
                    utc_now().isoformat(),
                    escalation_id,
                ),
            )

            if cursor.rowcount:
                self._audit(
                    escalation_id,
                    "acknowledged",
                    acknowledged_by,
                )

        if not cursor.rowcount:
            raise ValueError(
                "Escalation not open or not found"
            )

        return {
            "escalation_id": escalation_id,
            "acknowledged": True,
        }

    def process_due(
        self,
        limit: int = 100,
    ) -> dict:
        if not 1 <= limit <= 1000:
            raise ValueError("Invalid limit")

        now = utc_now()

        # BEGIN IMMEDIATE serializes escalation
        # decisions across SQLite worker processes.
        self.db.execute("BEGIN IMMEDIATE")

        try:
            rows = self.db.execute(
                """
                SELECT *
                FROM escalations
                WHERE status = 'open'
                  AND next_escalation_at <= ?
                ORDER BY next_escalation_at
                LIMIT ?
                """,
                (
                    now.isoformat(),
                    limit,
                ),
            ).fetchall()

            escalated = 0
            exhausted = 0

            for row in rows:
                policy = self.policies[
                    row["severity"]
                ]

                maximum = min(
                    self.config.max_level,
                    len(policy.recipients),
                )

                if row["level"] >= maximum:
                    # Keep unresolved incidents visible.
                    self.db.execute(
                        """
                        UPDATE escalations
                        SET status = 'max_level_reached'
                        WHERE escalation_id = ?
                        """,
                        (row["escalation_id"],),
                    )

                    self._audit(
                        row["escalation_id"],
                        "max_level_reached",
                        "worker",
                    )

                    exhausted += 1
                    continue

                new_level = row["level"] + 1

                deadline = (
                    now
                    + timedelta(
                        minutes=policy.sla_minutes
                    )
                )

                self.db.execute(
                    """
                    UPDATE escalations
                    SET level = ?,
                        next_escalation_at = ?
                    WHERE escalation_id = ?
                    """,
                    (
                        new_level,
                        deadline.isoformat(),
                        row["escalation_id"],
                    ),
                )

                self._queue_notification(
                    row["escalation_id"],
                    new_level,
                    policy.recipients[new_level - 1],
                    row["description"],
                )

                self._audit(
                    row["escalation_id"],
                    f"escalated_to_level_{new_level}",
                    "worker",
                )

                escalated += 1

            self.db.commit()

        except Exception:
            self.db.rollback()
            raise

        return {
            "escalated": escalated,
            "max_level_reached": exhausted,
        }

    def publish_notifications(
        self,
        limit: int = 100,
    ) -> dict:
        if not 1 <= limit <= 1000:
            raise ValueError("Invalid limit")

        rows = self.db.execute(
            """
            SELECT *
            FROM escalation_outbox
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
                        alert_id=row["notification_id"],
                        alert_type="system_failure",
                        severity="high",
                        recipient_reference=row["recipient"],
                        message=row["message"],
                        channel="internal",
                    )
                )

                if result["created"] or (
                    result["status"] == "existing"
                ):
                    with self.db:
                        self.db.execute(
                            """
                            UPDATE escalation_outbox
                            SET published = 1
                            WHERE notification_id = ?
                            """,
                            (row["notification_id"],),
                        )

                    published += 1

            except Exception:
                failed += 1

        return {
            "published": published,
            "failed": failed,
        }

    def summary(self) -> dict:
        rows = self.db.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM escalations
            GROUP BY status
            """
        ).fetchall()

        return {
            "statuses": {
                row["status"]: row["count"]
                for row in rows
            }
        }

    def close(self):
        self.db.close()


if __name__ == "__main__":
    alert_worker = AlertWorker()

    worker = EscalationWorker(
        alert_worker=alert_worker
    )

    print(
        worker.create_escalation(
            source_alert_id="supplier-risk-001",
            severity="high",
            description=(
                "Critical supplier shipment delayed."
            ),
        )
    )

    print(worker.process_due())
    print(worker.publish_notifications())
    print(json.dumps(worker.summary(), indent=2))

    worker.close()
    alert_worker.close()
