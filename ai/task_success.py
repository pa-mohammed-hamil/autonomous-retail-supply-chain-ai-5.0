"""Planned module: task success. Implementation pending."""

"""
File: ai/observability/task_success.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+ | Standard library only

Features:
- Task execution outcomes
- Verified task success
- Failure classification
- Approval-pending tracking
- Agent-level performance
- Tenant-scoped history
"""

from __future__ import annotations

import threading
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


TASK_STATUSES = frozenset({
    "completed",
    "failed",
    "pending_approval",
    "cancelled",
})

FAILURE_TYPES = frozenset({
    "validation_error",
    "timeout",
    "tool_error",
    "verification_failed",
    "policy_rejection",
    "dependency_failure",
    "unknown",
})


@dataclass(frozen=True)
class TaskOutcome:
    task_id: str
    tenant_id: str
    agent_id: str
    task_type: str
    status: str
    verified: bool
    failure_type: str | None
    timestamp: str


class TaskSuccessMetrics:

    def __init__(self, max_records: int = 100000):
        if (
            isinstance(max_records, bool)
            or not isinstance(max_records, int)
            or max_records < 1
        ):
            raise ValueError(
                "max_records must be positive"
            )

        self.max_records = max_records

        self._records: dict[
            tuple[str, str], TaskOutcome
        ] = {}

        self._lock = threading.RLock()

    @staticmethod
    def _text(value: Any, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} is required")
        return value.strip()

    def record_task(
        self,
        tenant_id: str,
        agent_id: str,
        task_type: str,
        status: str,
        verified: bool = False,
        failure_type: str | None = None,
        task_id: str | None = None,
    ) -> dict:

        tenant_id = self._text(
            tenant_id, "tenant_id"
        )
        agent_id = self._text(
            agent_id, "agent_id"
        )
        task_type = self._text(
            task_type, "task_type"
        )

        if status not in TASK_STATUSES:
            raise ValueError("Unsupported task status")

        if not isinstance(verified, bool):
            raise ValueError("verified must be boolean")

        if verified and status != "completed":
            raise ValueError(
                "Only completed tasks can be verified"
            )

        if status == "failed":
            if failure_type not in FAILURE_TYPES:
                raise ValueError(
                    "Failed tasks need a valid failure_type"
                )
        elif failure_type is not None:
            raise ValueError(
                "failure_type is only valid for failed tasks"
            )

        task_id = (
            self._text(task_id, "task_id")
            if task_id is not None
            else str(uuid4())
        )

        outcome = TaskOutcome(
            task_id=task_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            task_type=task_type,
            status=status,
            verified=verified,
            failure_type=failure_type,
            timestamp=datetime.now(
                timezone.utc
            ).isoformat(),
        )

        with self._lock:
            key = (tenant_id, task_id)

            if key in self._records:
                raise ValueError(
                    "Task already recorded"
                )

            self._records[key] = outcome

            while len(self._records) > self.max_records:
                oldest = next(iter(self._records))
                del self._records[oldest]

        return asdict(outcome)

    def summary(
        self,
        tenant_id: str,
        agent_id: str | None = None,
    ) -> dict:

        tenant_id = self._text(
            tenant_id, "tenant_id"
        )

        with self._lock:
            records = [
                record
                for record in self._records.values()
                if record.tenant_id == tenant_id
                and (
                    agent_id is None
                    or record.agent_id == agent_id
                )
            ]

        counts = Counter(
            record.status for record in records
        )

        total = len(records)

        completed = counts["completed"]
        failed = counts["failed"]

        verified = sum(
            record.status == "completed"
            and record.verified
            for record in records
        )

        # Pending and cancelled tasks are excluded
        # from the resolved-task denominator.
        resolved = completed + failed

        failure_counts = Counter(
            record.failure_type
            for record in records
            if record.failure_type is not None
        )

        return {
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "total_tasks": total,
            "completed_tasks": completed,
            "failed_tasks": failed,
            "pending_approval_tasks": counts[
                "pending_approval"
            ],
            "cancelled_tasks": counts[
                "cancelled"
            ],
            "verified_success_tasks": verified,
            "execution_success_rate_percent": (
                round(
                    completed / resolved * 100,
                    2,
                )
                if resolved else None
            ),
            "verified_success_rate_percent": (
                round(
                    verified / resolved * 100,
                    2,
                )
                if resolved else None
            ),
            "failure_rate_percent": (
                round(
                    failed / resolved * 100,
                    2,
                )
                if resolved else None
            ),
            "verification_rate_of_completed_percent": (
                round(
                    verified / completed * 100,
                    2,
                )
                if completed else None
            ),
            "failure_types": dict(
                failure_counts
            ),
            "denominator": (
                "completed_plus_failed_tasks"
            ),
        }

    def agent_breakdown(
        self,
        tenant_id: str,
    ) -> dict:

        with self._lock:
            agent_ids = sorted({
                record.agent_id
                for record in self._records.values()
                if record.tenant_id == tenant_id
            })

        return {
            "tenant_id": tenant_id,
            "agents": [
                self.summary(
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                )
                for agent_id in agent_ids
            ],
        }

    def task_history(
        self,
        tenant_id: str,
        limit: int = 50,
    ) -> dict:

        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise ValueError(
                "limit must be between 1 and 100"
            )

        with self._lock:
            records = [
                asdict(record)
                for record in self._records.values()
                if record.tenant_id == tenant_id
            ]

        return {
            "tenant_id": tenant_id,
            "task_count": len(records),
            "tasks": records[-limit:],
        }
