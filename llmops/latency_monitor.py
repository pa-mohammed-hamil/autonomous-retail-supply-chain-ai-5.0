"""Planned module: latency monitor. Implementation pending."""

"""
ai/llmops/latency_monitor.py

Latency monitoring for Autonomous Retail
Supply Chain AI 5.0.

Features:
- LLM, agent, tool and RAG latency tracking
- Time-to-first-token (TTFT)
- End-to-end response latency
- P50, P95 and P99 percentiles
- Success/error rates
- Configurable latency SLOs
- Slow-operation alerts
- SQLite persistence
- Trace correlation
- JSON dashboard reports

Standard library only. Python 3.10+.

Uses time.perf_counter() for elapsed durations
and UTC timestamps for audit records.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
import uuid

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None

    if not 0 <= p <= 100:
        raise ValueError("Percentile must be 0-100")

    ordered = sorted(values)
    position = (len(ordered) - 1) * p / 100

    lower = math.floor(position)
    upper = math.ceil(position)

    if lower == upper:
        return ordered[lower]

    fraction = position - lower

    return (
        ordered[lower] * (1 - fraction)
        + ordered[upper] * fraction
    )


@dataclass(frozen=True)
class LatencyConfig:
    database_path: str = "data/llmops/latency.db"
    default_slo_ms: float = 3000.0
    slow_request_multiplier: float = 1.5

    def __post_init__(self):
        if self.default_slo_ms <= 0:
            raise ValueError("SLO must be positive")

        if self.slow_request_multiplier < 1:
            raise ValueError("Invalid slow request multiplier")


@dataclass
class LatencyMeasurement:
    operation_id: str
    operation_name: str
    operation_type: str
    started_at: str
    started_counter: float
    trace_id: str | None = None
    agent_name: str | None = None
    model: str | None = None
    first_token_counter: float | None = None


class LatencyMonitor:

    VALID_TYPES = {
        "llm",
        "agent",
        "tool",
        "retrieval",
        "rag",
        "workflow",
        "embedding",
        "reranking",
    }

    def __init__(
        self,
        config: LatencyConfig | None = None,
    ):
        self.config = config or LatencyConfig()

        path = Path(self.config.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        self.db = sqlite3.connect(
            str(path),
            timeout=30,
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")

        self.db.execute("""
            CREATE TABLE IF NOT EXISTS latency_records (
                operation_id TEXT PRIMARY KEY,
                trace_id TEXT,
                agent_name TEXT,
                model TEXT,
                operation_name TEXT NOT NULL,
                operation_type TEXT NOT NULL,
                duration_ms REAL NOT NULL,
                ttft_ms REAL,
                success INTEGER NOT NULL,
                error_type TEXT,
                slo_ms REAL NOT NULL,
                slo_breached INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL
            )
        """)

        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_latency_operation
            ON latency_records(operation_type, operation_name)
        """)

        self.db.commit()
        self.slos: dict[str, float] = {}

    def set_slo(
        self,
        operation_name: str,
        slo_ms: float,
    ) -> None:
        if not operation_name.strip():
            raise ValueError("Operation name required")

        if not math.isfinite(slo_ms) or slo_ms <= 0:
            raise ValueError("Invalid SLO")

        self.slos[operation_name] = slo_ms

    def start(
        self,
        operation_name: str,
        operation_type: str,
        trace_id: str | None = None,
        agent_name: str | None = None,
        model: str | None = None,
    ) -> LatencyMeasurement:
        if not operation_name.strip():
            raise ValueError("Operation name required")

        if operation_type not in self.VALID_TYPES:
            raise ValueError("Unsupported operation type")

        return LatencyMeasurement(
            operation_id=uuid.uuid4().hex,
            operation_name=operation_name,
            operation_type=operation_type,
            started_at=utc_now(),
            started_counter=time.perf_counter(),
            trace_id=trace_id,
            agent_name=agent_name,
            model=model,
        )

    @staticmethod
    def mark_first_token(
        measurement: LatencyMeasurement,
    ) -> None:
        if measurement.first_token_counter is None:
            measurement.first_token_counter = (
                time.perf_counter()
            )

    def finish(
        self,
        measurement: LatencyMeasurement,
        success: bool = True,
        error_type: str | None = None,
    ) -> dict:
        finished_counter = time.perf_counter()

        duration_ms = (
            finished_counter
            - measurement.started_counter
        ) * 1000

        ttft_ms = None

        if measurement.first_token_counter is not None:
            ttft_ms = (
                measurement.first_token_counter
                - measurement.started_counter
            ) * 1000

            if ttft_ms > duration_ms:
                raise ValueError(
                    "First token occurred after completion"
                )

        slo_ms = self.slos.get(
            measurement.operation_name,
            self.config.default_slo_ms,
        )

        breached = duration_ms > slo_ms

        with self.db:
            self.db.execute(
                """
                INSERT INTO latency_records (
                    operation_id, trace_id, agent_name,
                    model, operation_name, operation_type,
                    duration_ms, ttft_ms, success,
                    error_type, slo_ms, slo_breached,
                    started_at, finished_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    measurement.operation_id,
                    measurement.trace_id,
                    measurement.agent_name,
                    measurement.model,
                    measurement.operation_name,
                    measurement.operation_type,
                    duration_ms,
                    ttft_ms,
                    int(success),
                    error_type,
                    slo_ms,
                    int(breached),
                    measurement.started_at,
                    utc_now(),
                ),
            )

        slow = duration_ms > (
            slo_ms * self.config.slow_request_multiplier
        )

        return {
            "operation_id": measurement.operation_id,
            "trace_id": measurement.trace_id,
            "duration_ms": round(duration_ms, 3),
            "ttft_ms": (
                round(ttft_ms, 3)
                if ttft_ms is not None
                else None
            ),
            "success": success,
            "slo_ms": slo_ms,
            "slo_breached": breached,
            "slow_request": slow,
            "alert": (
                "slow_operation"
                if slow
                else "slo_breach"
                if breached
                else None
            ),
        }

    @contextmanager
    def measure(
        self,
        operation_name: str,
        operation_type: str,
        trace_id: str | None = None,
        agent_name: str | None = None,
        model: str | None = None,
    ) -> Iterator[LatencyMeasurement]:
        measurement = self.start(
            operation_name=operation_name,
            operation_type=operation_type,
            trace_id=trace_id,
            agent_name=agent_name,
            model=model,
        )

        try:
            yield measurement
        except Exception as exc:
            self.finish(
                measurement,
                success=False,
                error_type=type(exc).__name__,
            )
            raise
        else:
            self.finish(
                measurement,
                success=True,
            )

    def summary(
        self,
        operation_type: str | None = None,
        operation_name: str | None = None,
        agent_name: str | None = None,
    ) -> dict:
        query = "SELECT * FROM latency_records WHERE 1=1"
        params = []

        filters = {
            "operation_type": operation_type,
            "operation_name": operation_name,
            "agent_name": agent_name,
        }

        for column, value in filters.items():
            if value is not None:
                query += f" AND {column} = ?"
                params.append(value)

        rows = self.db.execute(
            query,
            params,
        ).fetchall()

        durations = [
            row["duration_ms"]
            for row in rows
        ]

        ttfts = [
            row["ttft_ms"]
            for row in rows
            if row["ttft_ms"] is not None
        ]

        count = len(rows)

        return {
            "request_count": count,
            "success_count": sum(
                row["success"] for row in rows
            ),
            "error_count": sum(
                not row["success"] for row in rows
            ),
            "success_rate": (
                round(
                    sum(row["success"] for row in rows)
                    / count,
                    4,
                )
                if count else None
            ),
            "latency_ms": {
                "mean": round(mean(durations), 3)
                if durations else None,
                "p50": percentile(durations, 50),
                "p95": percentile(durations, 95),
                "p99": percentile(durations, 99),
                "max": max(durations)
                if durations else None,
            },
            "ttft_ms": {
                "p50": percentile(ttfts, 50),
                "p95": percentile(ttfts, 95),
                "p99": percentile(ttfts, 99),
                "sample_count": len(ttfts),
            },
            "slo_breach_count": sum(
                row["slo_breached"]
                for row in rows
            ),
            "slo_breach_rate": (
                round(
                    sum(
                        row["slo_breached"]
                        for row in rows
                    ) / count,
                    4,
                )
                if count else None
            ),
        }

    def dashboard_payload(self) -> dict:
        rows = self.db.execute(
            """
            SELECT DISTINCT operation_type
            FROM latency_records
            ORDER BY operation_type
            """
        ).fetchall()

        return {
            "title": "Retail AI Latency Monitoring",
            "overall": self.summary(),
            "by_operation_type": {
                row["operation_type"]: self.summary(
                    operation_type=row["operation_type"]
                )
                for row in rows
            },
            "generated_at": utc_now(),
        }

    def close(self):
        self.db.close()


if __name__ == "__main__":
    monitor = LatencyMonitor()

    monitor.set_slo(
        "inventory_rag",
        2000.0,
    )

    with monitor.measure(
        operation_name="inventory_rag",
        operation_type="rag",
        trace_id="trace-001",
        agent_name="inventory_agent",
    ):
        time.sleep(0.05)

    with monitor.measure(
        operation_name="llm_response",
        operation_type="llm",
        trace_id="trace-001",
        agent_name="inventory_agent",
        model="demo-llm",
    ) as measurement:
        time.sleep(0.02)
        monitor.mark_first_token(measurement)
        time.sleep(0.03)

    print(
        json.dumps(
            monitor.dashboard_payload(),
            indent=2,
        )
    )

    monitor.close()
