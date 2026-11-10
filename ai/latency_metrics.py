"""Planned module: latency metrics. Implementation pending."""

"""
File: ai/observability/latency_metrics.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+ | Standard library only

Features:
- Agent and LLM latency tracking
- P50, P90, P95 and P99 latency
- SLO violation tracking
- Slow execution detection
- Per-agent and per-operation reports
- Tenant-scoped bounded history
"""

from __future__ import annotations

import math
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterator


@dataclass(frozen=True)
class LatencyRecord:
    tenant_id: str
    agent_id: str
    operation: str
    duration_ms: float
    slo_ms: float | None
    slo_violated: bool | None
    timestamp: str


class LatencyMetrics:

    def __init__(
        self,
        max_records: int = 100000,
        default_slo_ms: float | None = None,
    ):
        if (
            isinstance(max_records, bool)
            or not isinstance(max_records, int)
            or max_records < 1
        ):
            raise ValueError(
                "max_records must be a positive integer"
            )

        if default_slo_ms is not None:
            self._validate_duration(
                default_slo_ms, "default_slo_ms"
            )

        self.max_records = max_records
        self.default_slo_ms = default_slo_ms

        self._records: list[LatencyRecord] = []
        self._lock = threading.RLock()

    @staticmethod
    def _validate_text(value: str, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} is required")
        return value.strip()

    @staticmethod
    def _validate_duration(value: Any, name: str) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(
                f"{name} must be a finite nonnegative number"
            )
        return float(value)

    @staticmethod
    def _percentile(
        values: list[float],
        percentile: float,
    ) -> float | None:
        if not values:
            return None

        values = sorted(values)

        # Nearest-rank percentile.
        index = max(
            0,
            math.ceil(percentile * len(values)) - 1,
        )

        return round(values[index], 2)

    def record(
        self,
        tenant_id: str,
        agent_id: str,
        operation: str,
        duration_ms: float,
        slo_ms: float | None = None,
    ) -> dict:

        tenant_id = self._validate_text(
            tenant_id, "tenant_id"
        )
        agent_id = self._validate_text(
            agent_id, "agent_id"
        )
        operation = self._validate_text(
            operation, "operation"
        )

        duration = self._validate_duration(
            duration_ms, "duration_ms"
        )

        effective_slo = (
            self.default_slo_ms
            if slo_ms is None
            else self._validate_duration(
                slo_ms, "slo_ms"
            )
        )

        record = LatencyRecord(
            tenant_id=tenant_id,
            agent_id=agent_id,
            operation=operation,
            duration_ms=duration,
            slo_ms=effective_slo,
            slo_violated=(
                duration > effective_slo
                if effective_slo is not None
                else None
            ),
            timestamp=datetime.now(
                timezone.utc
            ).isoformat(),
        )

        with self._lock:
            self._records.append(record)

            overflow = (
                len(self._records) - self.max_records
            )

            if overflow > 0:
                del self._records[:overflow]

        return asdict(record)

    @contextmanager
    def measure(
        self,
        tenant_id: str,
        agent_id: str,
        operation: str,
        slo_ms: float | None = None,
    ) -> Iterator[None]:
        """
        Automatically record elapsed wall-clock time,
        including executions that raise exceptions.
        """
        start = time.perf_counter()

        try:
            yield
        finally:
            elapsed_ms = (
                time.perf_counter() - start
            ) * 1000

            self.record(
                tenant_id=tenant_id,
                agent_id=agent_id,
                operation=operation,
                duration_ms=elapsed_ms,
                slo_ms=slo_ms,
            )

    def summary(
        self,
        tenant_id: str,
        agent_id: str | None = None,
        operation: str | None = None,
    ) -> dict:

        tenant_id = self._validate_text(
            tenant_id, "tenant_id"
        )

        with self._lock:
            records = [
                record
                for record in self._records
                if record.tenant_id == tenant_id
                and (
                    agent_id is None
                    or record.agent_id == agent_id
                )
                and (
                    operation is None
                    or record.operation == operation
                )
            ]

        durations = [
            record.duration_ms for record in records
        ]

        measured = [
            record
            for record in records
            if record.slo_violated is not None
        ]

        violations = sum(
            record.slo_violated
            for record in measured
        )

        return {
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "operation": operation,
            "sample_count": len(records),
            "average_latency_ms": (
                round(
                    sum(durations) / len(durations), 2
                )
                if durations else None
            ),
            "minimum_latency_ms": (
                round(min(durations), 2)
                if durations else None
            ),
            "maximum_latency_ms": (
                round(max(durations), 2)
                if durations else None
            ),
            "p50_latency_ms": self._percentile(
                durations, 0.50
            ),
            "p90_latency_ms": self._percentile(
                durations, 0.90
            ),
            "p95_latency_ms": self._percentile(
                durations, 0.95
            ),
            "p99_latency_ms": self._percentile(
                durations, 0.99
            ),
            "slo_evaluated_count": len(measured),
            "slo_violation_count": violations,
            "slo_violation_rate_percent": (
                round(
                    violations / len(measured) * 100,
                    2,
                )
                if measured else None
            ),
            "storage": "bounded_in_memory",
        }

    def slow_operations(
        self,
        tenant_id: str,
        threshold_ms: float,
        limit: int = 20,
    ) -> dict:

        threshold = self._validate_duration(
            threshold_ms, "threshold_ms"
        )

        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise ValueError("limit must be 1 to 100")

        with self._lock:
            matches = [
                record
                for record in self._records
                if record.tenant_id == tenant_id
                and record.duration_ms > threshold
            ]

        matches.sort(
            key=lambda item: item.duration_ms,
            reverse=True,
        )

        return {
            "threshold_ms": threshold,
            "slow_execution_count": len(matches),
            "executions": [
                asdict(item)
                for item in matches[:limit]
            ],
        }

    def agent_breakdown(
        self,
        tenant_id: str,
    ) -> dict:

        with self._lock:
            agent_ids = sorted({
                record.agent_id
                for record in self._records
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
