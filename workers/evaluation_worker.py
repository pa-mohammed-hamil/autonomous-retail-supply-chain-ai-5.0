from __future__ import annotations

"""Planned module: evaluation worker. Implementation pending."""

"""
ai/workers/evaluation_worker.py

Autonomous Retail Supply Chain AI 5.0

Features:
- Background LLM evaluation jobs
- RAG answer quality evaluation
- Hallucination verification integration
- Agent task-success scoring
- Groundedness metrics
- Safety evaluation integration
- Evaluation dashboard persistence
- Retry and dead-letter handling
- Idempotent evaluation jobs
- Evaluation result tracking
- SQLite job queue

Python 3.10+
Standard library only.

Evaluation adapters must return trusted
scores from actual evaluation systems.
This worker never fabricates quality scores.
"""


import json
import sqlite3
import uuid

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Any

from ai.llmops.evaluation_dashboard import (
    EvaluationDashboard,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


EvaluationAdapter = Callable[
    [dict],
    dict[str, float],
]


@dataclass(frozen=True)
class EvaluationWorkerConfig:
    database_path: str = (
        "data/workers/evaluation_jobs.db"
    )
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
class EvaluationJob:
    job_id: str
    trace_id: str
    agent_name: str
    provider: str
    model: str
    model_version: str
    dataset_name: str
    dataset_version: str
    evaluator_name: str
    evaluation_reference: str


class EvaluationWorker:

    def __init__(
        self,
        dashboard: EvaluationDashboard,
        config: EvaluationWorkerConfig | None = None,
    ):
        self.dashboard = dashboard
        self.config = (
            config or EvaluationWorkerConfig()
        )

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
            CREATE TABLE IF NOT EXISTS evaluation_jobs (
                job_id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                model_version TEXT NOT NULL,
                dataset_name TEXT NOT NULL,
                dataset_version TEXT NOT NULL,
                evaluator_name TEXT NOT NULL,
                evaluation_reference TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                lease_until TEXT,
                result_json TEXT,
                error_type TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_eval_queue
            ON evaluation_jobs(
                status, next_attempt_at
            );
        """)

        self.db.commit()

        self.adapters: dict[
            str, EvaluationAdapter
        ] = {}

    def register_evaluator(
        self,
        name: str,
        adapter: EvaluationAdapter,
    ) -> None:
        if not name.strip():
            raise ValueError(
                "Evaluator name required"
            )

        if not callable(adapter):
            raise ValueError(
                "Evaluator must be callable"
            )

        self.adapters[name] = adapter

    def enqueue(
        self,
        job: EvaluationJob,
    ) -> dict:
        required = (
            job.job_id,
            job.trace_id,
            job.agent_name,
            job.provider,
            job.model,
            job.model_version,
            job.dataset_name,
            job.dataset_version,
            job.evaluator_name,
            job.evaluation_reference,
        )

        if any(not value.strip() for value in required):
            raise ValueError(
                "Evaluation job fields required"
            )

        with self.db:
            cursor = self.db.execute(
                """
                INSERT OR IGNORE INTO evaluation_jobs (
                    job_id, trace_id, agent_name,
                    provider, model, model_version,
                    dataset_name, dataset_version,
                    evaluator_name, evaluation_reference,
                    status, next_attempt_at, created_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    'pending', ?, ?
                )
                """,
                (
                    job.job_id,
                    job.trace_id,
                    job.agent_name,
                    job.provider,
                    job.model,
                    job.model_version,
                    job.dataset_name,
                    job.dataset_version,
                    job.evaluator_name,
                    job.evaluation_reference,
                    utc_now().isoformat(),
                    utc_now().isoformat(),
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
                FROM evaluation_jobs
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

            lease = (
                now
                + timedelta(
                    seconds=self.config.lease_seconds
                )
            )

            self.db.execute(
                """
                UPDATE evaluation_jobs
                SET status = 'processing',
                    attempts = attempts + 1,
                    lease_until = ?
                WHERE job_id = ?
                """,
                (
                    lease.isoformat(),
                    row["job_id"],
                ),
            )

            self.db.commit()
            return dict(row)

        except Exception:
            self.db.rollback()
            raise

    def process_one(self) -> dict | None:
        job = self._claim_next()

        if job is None:
            return None

        job_id = job["job_id"]
        attempt = job["attempts"] + 1

        try:
            adapter = self.adapters.get(
                job["evaluator_name"]
            )

            if adapter is None:
                raise RuntimeError(
                    "Evaluation adapter not configured"
                )

            # The reference should resolve to
            # a trusted evaluation dataset,
            # not arbitrary user-provided content.
            metrics = adapter(job)

            if not isinstance(metrics, dict) or not metrics:
                raise ValueError(
                    "Evaluator returned no metrics"
                )

            # Dashboard validates metric names
            # and ranges before persistence.
            result = self.dashboard.record_evaluation(
                agent_name=job["agent_name"],
                provider=job["provider"],
                model=job["model"],
                model_version=job["model_version"],
                dataset_name=job["dataset_name"],
                dataset_version=job["dataset_version"],
                metrics=metrics,
                evaluator=job["evaluator_name"],
                trace_id=job["trace_id"],
                evaluation_prefix=job_id,
            )

            with self.db:
                self.db.execute(
                    """
                    UPDATE evaluation_jobs
                    SET status = 'completed',
                        result_json = ?,
                        completed_at = ?,
                        lease_until = NULL,
                        error_type = NULL
                    WHERE job_id = ?
                      AND status = 'processing'
                    """,
                    (
                        json.dumps(result),
                        utc_now().isoformat(),
                        job_id,
                    ),
                )

            return {
                "job_id": job_id,
                "status": "completed",
                "metrics": metrics,
                "attempt": attempt,
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
                            * (2 ** (attempt - 1)),
                            3600,
                        )
                    )
                )

            with self.db:
                self.db.execute(
                    """
                    UPDATE evaluation_jobs
                    SET status = ?,
                        next_attempt_at = ?,
                        lease_until = NULL,
                        error_type = ?
                    WHERE job_id = ?
                      AND status = 'processing'
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
                "attempt": attempt,
            }

    def get_job(
        self,
        job_id: str,
    ) -> dict | None:
        row = self.db.execute(
            """
            SELECT *
            FROM evaluation_jobs
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()

        if row is None:
            return None

        result = dict(row)

        if result["result_json"]:
            result["result"] = json.loads(
                result.pop("result_json")
            )
        else:
            result.pop("result_json")
            result["result"] = None

        return result

    def summary(self) -> dict:
        rows = self.db.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM evaluation_jobs
            GROUP BY status
            """
        ).fetchall()

        return {
            "statuses": {
                row["status"]: row["count"]
                for row in rows
            },
            "registered_evaluators": sorted(
                self.adapters
            ),
        }

    def close(self):
        self.db.close()


if __name__ == "__main__":
    dashboard = EvaluationDashboard()

    worker = EvaluationWorker(
        dashboard=dashboard
    )

    # Demo adapter uses illustrative scores.
    # Replace with actual labeled evaluation
    # datasets and trusted metric computation.
    def demo_evaluator(job: dict) -> dict:
        return {
            "answer_correctness": 0.94,
            "groundedness": 0.96,
            "retrieval_precision": 0.91,
            "task_success": 0.93,
            "safety_score": 0.99,
        }

    worker.register_evaluator(
        "demo_evaluator",
        demo_evaluator,
    )

    worker.enqueue(
        EvaluationJob(
            job_id="eval-inventory-001",
            trace_id="trace-inventory-001",
            agent_name="inventory_agent",
            provider="demo_provider",
            model="demo_llm",
            model_version="1.0.0",
            dataset_name="retail_eval",
            dataset_version="2026-10",
            evaluator_name="demo_evaluator",
            evaluation_reference="case-001",
        )
    )

    print(
        json.dumps(
            worker.process_one(),
            indent=2,
        )
    )

    print(
        json.dumps(
            worker.summary(),
            indent=2,
        )
    )

    worker.close()
    dashboard.close()
