from __future__ import annotations

"""Planned module: report worker. Implementation pending."""

"""
ai/workers/report_worker.py

Autonomous Retail Supply Chain AI 5.0

Features:
- Background KPI report generation
- Daily/weekly/monthly reports
- Inventory and sales analytics
- Demand forecast reporting
- Supplier performance reporting
- Logistics and financial summaries
- Structured JSON reports
- Human-readable Markdown reports
- Retry and dead-letter handling
- Idempotent report jobs
- Optional notification integration
- SQLite persistence

Python 3.10+
Standard library only.

This module accepts verified KPI inputs.
It does not invent or fetch live business data.
"""


import json
import math
import sqlite3
import uuid

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


# Source adapter receives report parameters and
# returns actual metrics from authorized systems.
ReportSource = Callable[[dict], dict]


@dataclass(frozen=True)
class ReportWorkerConfig:
    database_path: str = "data/workers/reports.db"
    output_directory: str = "data/reports"
    max_attempts: int = 3
    retry_base_seconds: int = 10
    lease_seconds: int = 300

    def __post_init__(self):
        if self.max_attempts < 1:
            raise ValueError("Invalid attempts")
        if self.retry_base_seconds < 1:
            raise ValueError("Invalid retry delay")
        if self.lease_seconds < 1:
            raise ValueError("Invalid lease")


@dataclass(frozen=True)
class ReportJob:
    job_id: str
    report_type: str
    period_start: str
    period_end: str
    source_name: str
    requested_by: str
    recipient_reference: str | None = None


class ReportWorker:

    REPORT_TYPES = {
        "daily",
        "weekly",
        "monthly",
        "inventory",
        "sales",
        "demand",
        "supplier",
        "logistics",
        "finance",
        "executive",
    }

    def __init__(
        self,
        config: ReportWorkerConfig | None = None,
    ):
        self.config = config or ReportWorkerConfig()

        db_path = Path(self.config.database_path)
        db_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.output_directory = Path(
            self.config.output_directory
        )
        self.output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.db = sqlite3.connect(
            str(db_path),
            timeout=30,
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=30000")

        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS report_jobs (
                job_id TEXT PRIMARY KEY,
                report_type TEXT NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                source_name TEXT NOT NULL,
                requested_by TEXT NOT NULL,
                recipient_reference TEXT,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                lease_until TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS generated_reports (
                report_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL UNIQUE,
                report_type TEXT NOT NULL,
                json_path TEXT NOT NULL,
                markdown_path TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)

        self.db.commit()

        self.sources: dict[
            str, ReportSource
        ] = {}

    def register_source(
        self,
        name: str,
        source: ReportSource,
    ) -> None:
        if not name.strip():
            raise ValueError("Source name required")

        if not callable(source):
            raise ValueError("Source must be callable")

        self.sources[name] = source

    @staticmethod
    def validate_metrics(metrics: dict) -> None:
        if not isinstance(metrics, dict):
            raise ValueError(
                "Metrics must be a dictionary"
            )

        if not metrics:
            raise ValueError(
                "Metrics cannot be empty"
            )

        def check(value: Any) -> None:
            if isinstance(value, bool):
                return

            if isinstance(value, (int, float)):
                if not math.isfinite(value):
                    raise ValueError(
                        "Non-finite metric value"
                    )
                return

            if value is None or isinstance(value, str):
                return

            if isinstance(value, dict):
                for item in value.values():
                    check(item)
                return

            if isinstance(value, list):
                for item in value:
                    check(item)
                return

            raise ValueError(
                "Unsupported metric data type"
            )

        check(metrics)

    def enqueue(self, job: ReportJob) -> dict:
        if job.report_type not in self.REPORT_TYPES:
            raise ValueError("Invalid report type")

        for value in (
            job.job_id,
            job.source_name,
            job.requested_by,
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Required field missing")

        start = datetime.fromisoformat(
            job.period_start
        )
        end = datetime.fromisoformat(
            job.period_end
        )

        if end < start:
            raise ValueError(
                "Report period is invalid"
            )

        with self.db:
            cursor = self.db.execute(
                """
                INSERT OR IGNORE INTO report_jobs (
                    job_id, report_type,
                    period_start, period_end,
                    source_name, requested_by,
                    recipient_reference, status,
                    next_attempt_at, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?,
                        'pending', ?, ?)
                """,
                (
                    job.job_id,
                    job.report_type,
                    job.period_start,
                    job.period_end,
                    job.source_name,
                    job.requested_by,
                    job.recipient_reference,
                    iso_now(),
                    iso_now(),
                ),
            )

        return {
            "job_id": job.job_id,
            "created": cursor.rowcount == 1,
        }

    def _claim_next(self) -> dict | None:
        now = utc_now()

        self.db.execute("BEGIN IMMEDIATE")

        try:
            row = self.db.execute(
                """
                SELECT *
                FROM report_jobs
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
                (
                    now.isoformat(),
                    now.isoformat(),
                ),
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
                UPDATE report_jobs
                SET status = 'processing',
                    attempts = attempts + 1,
                    lease_until = ?
                WHERE job_id = ?
                """,
                (
                    lease_until,
                    row["job_id"],
                ),
            )

            self.db.commit()
            return dict(row)

        except Exception:
            self.db.rollback()
            raise

    @staticmethod
    def build_markdown(report: dict) -> str:
        lines = [
            f"# {report['report_type'].title()} "
            "Retail Intelligence Report",
            "",
            f"Period: {report['period_start']} "
            f"to {report['period_end']}",
            "",
            f"Generated: {report['generated_at']}",
            "",
            "## KPI Summary",
            "",
        ]

        for key, value in report["metrics"].items():
            label = key.replace("_", " ").title()

            if isinstance(value, (dict, list)):
                formatted = json.dumps(
                    value,
                    indent=2,
                    ensure_ascii=False,
                )

                lines.extend([
                    f"### {label}",
                    "",
                    "```json",
                    formatted,
                    "```",
                    "",
                ])
            else:
                lines.append(
                    f"- **{label}:** {value}"
                )

        lines.extend([
            "",
            "## Data Quality",
            "",
            "All reported values originate from "
            "the configured report source adapter.",
            "Accuracy depends on the source "
            "system and its validation controls.",
        ])

        return "\n".join(lines)

    def process_one(self) -> dict | None:
        job = self._claim_next()

        if job is None:
            return None

        job_id = job["job_id"]
        attempt = job["attempts"] + 1

        try:
            source = self.sources.get(
                job["source_name"]
            )

            if source is None:
                raise RuntimeError(
                    "Report source not configured"
                )

            metrics = source(job)
            self.validate_metrics(metrics)

            report = {
                "report_id": f"REPORT-{job_id}",
                "job_id": job_id,
                "report_type": job["report_type"],
                "period_start": job["period_start"],
                "period_end": job["period_end"],
                "generated_at": iso_now(),
                "source_name": job["source_name"],
                "metrics": metrics,
            }

            # Filename uses an internal UUID rather
            # than arbitrary external job text.
            report_id = uuid.uuid5(
                uuid.NAMESPACE_URL,
                job_id,
            ).hex

            json_path = (
                self.output_directory
                / f"{report_id}.json"
            )

            markdown_path = (
                self.output_directory
                / f"{report_id}.md"
            )

            json_path.write_text(
                json.dumps(
                    report,
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            markdown_path.write_text(
                self.build_markdown(report),
                encoding="utf-8",
            )

            with self.db:
                self.db.execute(
                    """
                    INSERT OR IGNORE INTO generated_reports (
                        report_id, job_id, report_type,
                        json_path, markdown_path,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        report_id,
                        job_id,
                        job["report_type"],
                        str(json_path),
                        str(markdown_path),
                        iso_now(),
                    ),
                )

                self.db.execute(
                    """
                    UPDATE report_jobs
                    SET status = 'completed',
                        completed_at = ?,
                        lease_until = NULL,
                        last_error = NULL
                    WHERE job_id = ?
                    """,
                    (
                        iso_now(),
                        job_id,
                    ),
                )

            return {
                "job_id": job_id,
                "status": "completed",
                "report_id": report_id,
                "json_path": str(json_path),
                "markdown_path": str(markdown_path),
            }

        except Exception as exc:
            if attempt >= self.config.max_attempts:
                status = "dead_letter"
                next_time = utc_now()
            else:
                status = "retry"
                next_time = (
                    utc_now()
                    + timedelta(
                        seconds=min(
                            self.config.retry_base_seconds
                            * 2 ** (attempt - 1),
                            3600,
                        )
                    )
                )

            with self.db:
                self.db.execute(
                    """
                    UPDATE report_jobs
                    SET status = ?,
                        next_attempt_at = ?,
                        lease_until = NULL,
                        last_error = ?
                    WHERE job_id = ?
                    """,
                    (
                        status,
                        next_time.isoformat(),
                        type(exc).__name__,
                        job_id,
                    ),
                )

            return {
                "job_id": job_id,
                "status": status,
                "error_type": type(exc).__name__,
            }

    def get_report(self, job_id: str) -> dict | None:
        row = self.db.execute(
            """
            SELECT *
            FROM generated_reports
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()

        return dict(row) if row else None

    def summary(self) -> dict:
        rows = self.db.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM report_jobs
            GROUP BY status
            """
        ).fetchall()

        return {
            "statuses": {
                row["status"]: row["count"]
                for row in rows
            },
            "registered_sources": sorted(
                self.sources
            ),
        }

    def close(self) -> None:
        self.db.close()


if __name__ == "__main__":
    worker = ReportWorker()

    def demo_source(job: dict) -> dict:
        # Illustrative data only.
        return {
            "sales": {
                "revenue_inr": 250000,
                "orders": 1200,
            },
            "inventory": {
                "stockouts": 4,
                "inventory_value_inr": 1800000,
            },
            "demand": {
                "forecast_mae": 5.2,
            },
            "supplier": {
                "on_time_delivery_rate": 0.94,
            },
            "finance": {
                "operating_cost_inr": 85000,
            },
        }

    worker.register_source(
        "demo_source",
        demo_source,
    )

    job = ReportJob(
        job_id="daily-retail-report-001",
        report_type="daily",
        period_start="2026-10-25",
        period_end="2026-10-25",
        source_name="demo_source",
        requested_by="operations_manager",
    )

    print(worker.enqueue(job))

    print(json.dumps(
        worker.process_one(),
        indent=2,
    ))

    print(json.dumps(
        worker.summary(),
        indent=2,
    ))

    worker.close()
