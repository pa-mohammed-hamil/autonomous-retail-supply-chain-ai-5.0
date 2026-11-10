"""Planned module: experiment tracker. Implementation pending."""

"""
ai/mlops/experiment_tracker.py

Experiment tracking for retail AI models.

Features:
- Experiment and run management
- Parameters and metric histories
- Dataset provenance
- SHA-256 artifact records
- Run comparisons
- Best-run selection
- JSON export

SQLite-based local MLOps implementation.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ExperimentTracker:

    VALID_STATUSES = {
        "running",
        "completed",
        "failed",
        "cancelled",
    }

    def __init__(
        self,
        database_path: str = (
            "storage/mlops/experiments.db"
        ),
    ):
        path = Path(database_path)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self.database_path = str(path)
        self._initialize()

    @staticmethod
    def _now() -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()

    def _connect(self):
        conn = sqlite3.connect(
            self.database_path,
            timeout=10,
        )
        conn.row_factory = sqlite3.Row
        conn.execute(
            "PRAGMA foreign_keys = ON"
        )
        conn.execute(
            "PRAGMA busy_timeout = 10000"
        )
        return conn

    def _initialize(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    experiment_id TEXT NOT NULL,
                    run_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    dataset_id TEXT NOT NULL,
                    dataset_version TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    FOREIGN KEY(experiment_id)
                        REFERENCES experiments(experiment_id)
                );

                CREATE TABLE IF NOT EXISTS metrics (
                    metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    value REAL NOT NULL,
                    step INTEGER NOT NULL,
                    logged_at TEXT NOT NULL,
                    FOREIGN KEY(run_id)
                        REFERENCES runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    artifact_path TEXT NOT NULL,
                    artifact_sha256 TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id)
                        REFERENCES runs(run_id)
                );

                CREATE INDEX IF NOT EXISTS
                    idx_runs_experiment
                ON runs(experiment_id);

                CREATE INDEX IF NOT EXISTS
                    idx_metrics_run_name
                ON metrics(run_id, name, step);
            """)

    def create_experiment(
        self,
        name: str,
        description: str = "",
    ) -> str:
        if not name.strip():
            raise ValueError(
                "Experiment name required"
            )

        experiment_id = uuid.uuid4().hex

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO experiments
                VALUES (?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    name,
                    description,
                    self._now(),
                ),
            )

        return experiment_id

    def start_run(
        self,
        experiment_id: str,
        run_name: str,
        dataset_id: str,
        dataset_version: str,
        parameters: dict[str, Any],
    ) -> str:

        if not all([
            run_name,
            dataset_id,
            dataset_version,
        ]):
            raise ValueError(
                "Run and dataset details required"
            )

        run_id = uuid.uuid4().hex

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    run_id, experiment_id,
                    run_name, status,
                    dataset_id, dataset_version,
                    parameters_json,
                    started_at, ended_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    run_id,
                    experiment_id,
                    run_name,
                    "running",
                    dataset_id,
                    dataset_version,
                    json.dumps(
                        parameters,
                        allow_nan=False,
                    ),
                    self._now(),
                ),
            )

        return run_id

    def log_metric(
        self,
        run_id: str,
        name: str,
        value: float,
        step: int = 0,
    ) -> None:

        if not name:
            raise ValueError(
                "Metric name required"
            )

        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError(
                "Metric must be finite and numeric"
            )

        if (
            isinstance(step, bool)
            or not isinstance(step, int)
            or step < 0
        ):
            raise ValueError(
                "Step must be a nonnegative integer"
            )

        with self._connect() as conn:
            run = conn.execute(
                """
                SELECT status FROM runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()

            if run is None:
                raise ValueError(
                    "Run not found"
                )

            if run["status"] != "running":
                raise ValueError(
                    "Cannot log to a finished run"
                )

            conn.execute(
                """
                INSERT INTO metrics (
                    run_id, name, value,
                    step, logged_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    name,
                    float(value),
                    step,
                    self._now(),
                ),
            )

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()

        with path.open("rb") as file:
            for chunk in iter(
                lambda: file.read(1024 * 1024),
                b"",
            ):
                digest.update(chunk)

        return digest.hexdigest()

    def log_artifact(
        self,
        run_id: str,
        artifact_path: str,
        artifact_type: str = "model",
    ) -> dict:

        path = Path(artifact_path).resolve()

        if not path.is_file():
            raise FileNotFoundError(path)

        artifact_id = uuid.uuid4().hex
        sha256 = self._hash_file(path)

        with self._connect() as conn:
            run = conn.execute(
                """
                SELECT status FROM runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()

            if run is None or run["status"] != "running":
                raise ValueError(
                    "An active run is required"
                )

            conn.execute(
                """
                INSERT INTO artifacts
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    run_id,
                    str(path),
                    sha256,
                    artifact_type,
                    self._now(),
                ),
            )

        return {
            "artifact_id": artifact_id,
            "path": str(path),
            "sha256": sha256,
        }

    def end_run(
        self,
        run_id: str,
        status: str = "completed",
    ) -> None:

        if status not in {
            "completed",
            "failed",
            "cancelled",
        }:
            raise ValueError(
                "Invalid final status"
            )

        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE runs
                SET status = ?, ended_at = ?
                WHERE run_id = ?
                  AND status = 'running'
                """,
                (
                    status,
                    self._now(),
                    run_id,
                ),
            )

            if cursor.rowcount != 1:
                raise ValueError(
                    "Run not found or already finished"
                )

    def get_run(
        self,
        run_id: str,
    ) -> dict:

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()

            if row is None:
                raise ValueError(
                    "Run not found"
                )

            metrics = conn.execute(
                """
                SELECT name, value, step, logged_at
                FROM metrics
                WHERE run_id = ?
                ORDER BY step, metric_id
                """,
                (run_id,),
            ).fetchall()

            artifacts = conn.execute(
                """
                SELECT artifact_id, artifact_path,
                       artifact_sha256, artifact_type
                FROM artifacts
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchall()

        result = dict(row)
        result["parameters"] = json.loads(
            result.pop("parameters_json")
        )
        result["metrics"] = [
            dict(item) for item in metrics
        ]
        result["artifacts"] = [
            dict(item) for item in artifacts
        ]

        return result

    def compare_runs(
        self,
        experiment_id: str,
        metric_name: str,
        higher_is_better: bool = True,
    ) -> list[dict]:

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT r.run_id, r.run_name,
                       r.dataset_id,
                       r.dataset_version,
                       r.status
                FROM runs r
                WHERE r.experiment_id = ?
                  AND r.status = 'completed'
                """,
                (experiment_id,),
            ).fetchall()

            comparisons = []

            for row in rows:
                metric = conn.execute(
                    """
                    SELECT value
                    FROM metrics
                    WHERE run_id = ?
                      AND name = ?
                    ORDER BY step DESC,
                             metric_id DESC
                    LIMIT 1
                    """,
                    (
                        row["run_id"],
                        metric_name,
                    ),
                ).fetchone()

                if metric is not None:
                    comparisons.append({
                        **dict(row),
                        "metric_name": metric_name,
                        "metric_value": metric["value"],
                    })

        return sorted(
            comparisons,
            key=lambda item: item["metric_value"],
            reverse=higher_is_better,
        )

    def best_run(
        self,
        experiment_id: str,
        metric_name: str,
        higher_is_better: bool = True,
    ) -> dict | None:

        ranked = self.compare_runs(
            experiment_id,
            metric_name,
            higher_is_better,
        )

        return ranked[0] if ranked else None

    def export_run(
        self,
        run_id: str,
        output_path: str,
    ) -> str:

        report = self.get_run(run_id)
        path = Path(output_path)

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            json.dumps(
                report,
                indent=2,
                allow_nan=False,
            ),
            encoding="utf-8",
        )

        return str(path)
