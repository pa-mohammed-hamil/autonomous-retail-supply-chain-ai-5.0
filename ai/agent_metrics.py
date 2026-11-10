"""Planned module: agent metrics. Implementation pending."""

"""
File: ai/observability/agent_metrics.py
Python 3.10+ | Standard library only
"""

from __future__ import annotations

import math
import threading
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from statistics import mean
from typing import Any


@dataclass(frozen=True)
class AgentExecutionMetric:
    tenant_id: str
    agent_id: str
    task_type: str
    success: bool
    duration_ms: float
    timestamp: str


class AgentMetrics:

    def __init__(self, max_records: int = 100000):
        if max_records < 1:
            raise ValueError("max_records must be positive")

        self.max_records = max_records
        self._records: list[AgentExecutionMetric] = []
        self._lock = threading.RLock()

    def record(
        self,
        tenant_id: str,
        agent_id: str,
        task_type: str,
        success: bool,
        duration_ms: float,
    ) -> dict[str, Any]:

        for name, value in {
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "task_type": task_type,
        }.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")

        if not isinstance(success, bool):
            raise ValueError("success must be boolean")

        if (
            isinstance(duration_ms, bool)
            or not isinstance(duration_ms, (int, float))
            or not math.isfinite(duration_ms)
            or duration_ms < 0
        ):
            raise ValueError("Invalid duration_ms")

        metric = AgentExecutionMetric(
            tenant_id=tenant_id,
            agent_id=agent_id,
            task_type=task_type,
            success=success,
            duration_ms=float(duration_ms),
            timestamp=datetime.now(
                timezone.utc
            ).isoformat(),
        )

        with self._lock:
            self._records.append(metric)
            if len(self._records) > self.max_records:
                del self._records[
                    :len(self._records) - self.max_records
                ]

        return asdict(metric)

    @staticmethod
    def _percentile(values: list[float], p: float):
        if not values:
            return None

        ordered = sorted(values)
        index = math.ceil(p * len(ordered)) - 1
        return round(ordered[max(0, index)], 2)

    def summary(
        self,
        tenant_id: str,
        agent_id: str | None = None,
    ) -> dict:

        with self._lock:
            records = [
                r for r in self._records
                if r.tenant_id == tenant_id
                and (
                    agent_id is None
                    or r.agent_id == agent_id
                )
            ]

        total = len(records)
        successes = sum(r.success for r in records)
        failures = total - successes
        latencies = [r.duration_ms for r in records]

        return {
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "execution_count": total,
            "success_count": successes,
            "failure_count": failures,
            "success_rate_percent": (
                round(successes / total * 100, 2)
                if total else None
            ),
            "failure_rate_percent": (
                round(failures / total * 100, 2)
                if total else None
            ),
            "average_latency_ms": (
                round(mean(latencies), 2)
                if latencies else None
            ),
            "p50_latency_ms": self._percentile(
                latencies, 0.50
            ),
            "p95_latency_ms": self._percentile(
                latencies, 0.95
            ),
            "task_counts": dict(
                Counter(r.task_type for r in records)
            ),
            "storage": "bounded_in_memory",
        }

    def agent_breakdown(self, tenant_id: str) -> dict:
        with self._lock:
            agent_ids = sorted({
                r.agent_id
                for r in self._records
                if r.tenant_id == tenant_id
            })

        return {
            "tenant_id": tenant_id,
            "agents": [
                self.summary(tenant_id, agent_id)
                for agent_id in agent_ids
            ],
        }
