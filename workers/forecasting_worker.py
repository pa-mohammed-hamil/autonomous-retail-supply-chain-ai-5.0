from __future__ import annotations

"""Planned module: forecasting worker. Implementation pending."""

"""
ai/workers/forecasting_worker.py

Autonomous Retail Supply Chain AI 5.0

Features:
- Background demand forecasting
- Multi-SKU and multi-store jobs
- Pluggable forecasting models
- Moving-average baseline
- Forecast horizons
- Prediction persistence
- Model version tracking
- Retry and dead-letter handling
- Forecast accuracy evaluation
- MAE, RMSE, WAPE
- SQLite persistence

Python 3.10+
Standard library only.

Production models can be connected using
register_model(). Forecasts are predictions,
not guaranteed future sales.
"""


import json
import math
import sqlite3
import uuid

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Callable


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Input: historical daily quantities, horizon.
# Output: one predicted quantity per future day.
ForecastModel = Callable[
    [list[float], int],
    list[float],
]


@dataclass(frozen=True)
class ForecastingWorkerConfig:
    database_path: str = (
        "data/workers/forecasts.db"
    )
    max_attempts: int = 3
    retry_base_seconds: int = 10
    max_horizon_days: int = 90
    minimum_history_days: int = 7

    def __post_init__(self):
        if self.max_attempts < 1:
            raise ValueError("Invalid attempts")
        if self.retry_base_seconds < 1:
            raise ValueError("Invalid retry delay")
        if self.max_horizon_days < 1:
            raise ValueError("Invalid horizon")
        if self.minimum_history_days < 1:
            raise ValueError("Invalid history")


@dataclass(frozen=True)
class ForecastJob:
    job_id: str
    store_id: str
    sku: str
    model_name: str
    model_version: str
    horizon_days: int
    historical_demand: tuple[float, ...]


class ForecastingWorker:

    def __init__(
        self,
        config: ForecastingWorkerConfig | None = None,
    ):
        self.config = (
            config or ForecastingWorkerConfig()
        )

        path = Path(self.config.database_path)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.db = sqlite3.connect(
            str(path), timeout=30
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=30000")

        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS forecast_jobs (
                job_id TEXT PRIMARY KEY,
                store_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                model_name TEXT NOT NULL,
                model_version TEXT NOT NULL,
                horizon_days INTEGER NOT NULL,
                history_json TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                error_type TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS forecasts (
                job_id TEXT NOT NULL,
                forecast_date TEXT NOT NULL,
                store_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                model_name TEXT NOT NULL,
                model_version TEXT NOT NULL,
                predicted_units REAL NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (job_id, forecast_date)
            );

            CREATE TABLE IF NOT EXISTS forecast_actuals (
                job_id TEXT NOT NULL,
                forecast_date TEXT NOT NULL,
                actual_units REAL NOT NULL,
                recorded_at TEXT NOT NULL,
                PRIMARY KEY (job_id, forecast_date)
            );
        """)

        self.db.commit()

        self.models: dict[
            str, ForecastModel
        ] = {
            "moving_average": self.moving_average
        }

    @staticmethod
    def moving_average(
        history: list[float],
        horizon: int,
    ) -> list[float]:
        if not history:
            raise ValueError("History required")

        window = history[-7:]
        estimate = mean(window)

        return [
            max(0.0, estimate)
            for _ in range(horizon)
        ]

    def register_model(
        self,
        name: str,
        model: ForecastModel,
    ) -> None:
        if not name.strip():
            raise ValueError("Model name required")

        if not callable(model):
            raise ValueError("Model must be callable")

        self.models[name] = model

    def enqueue(self, job: ForecastJob) -> dict:
        if not job.job_id.strip():
            raise ValueError("Job ID required")

        if not job.store_id.strip() or not job.sku.strip():
            raise ValueError(
                "Store and SKU required"
            )

        if not job.model_name.strip():
            raise ValueError("Model required")

        if not job.model_version.strip():
            raise ValueError(
                "Model version required"
            )

        if not (
            1 <= job.horizon_days
            <= self.config.max_horizon_days
        ):
            raise ValueError(
                "Forecast horizon out of range"
            )

        if (
            len(job.historical_demand)
            < self.config.minimum_history_days
        ):
            raise ValueError(
                "Insufficient historical demand"
            )

        for value in job.historical_demand:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(
                    "Invalid historical demand"
                )

        with self.db:
            cursor = self.db.execute(
                """
                INSERT OR IGNORE INTO forecast_jobs (
                    job_id, store_id, sku,
                    model_name, model_version,
                    horizon_days, history_json,
                    status, next_attempt_at,
                    created_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?,
                    'pending', ?, ?
                )
                """,
                (
                    job.job_id,
                    job.store_id,
                    job.sku,
                    job.model_name,
                    job.model_version,
                    job.horizon_days,
                    json.dumps(
                        job.historical_demand
                    ),
                    utc_now().isoformat(),
                    utc_now().isoformat(),
                ),
            )

        return {
            "job_id": job.job_id,
            "created": cursor.rowcount == 1,
        }

    def process_one(self) -> dict | None:
        self.db.execute("BEGIN IMMEDIATE")

        try:
            row = self.db.execute(
                """
                SELECT *
                FROM forecast_jobs
                WHERE status IN ('pending', 'retry')
                  AND next_attempt_at <= ?
                ORDER BY created_at
                LIMIT 1
                """,
                (utc_now().isoformat(),),
            ).fetchone()

            if row is None:
                self.db.commit()
                return None

            self.db.execute(
                """
                UPDATE forecast_jobs
                SET status = 'processing',
                    attempts = attempts + 1
                WHERE job_id = ?
                """,
                (row["job_id"],),
            )

            self.db.commit()

        except Exception:
            self.db.rollback()
            raise

        job = dict(row)
        attempt = job["attempts"] + 1

        try:
            model = self.models.get(
                job["model_name"]
            )

            if model is None:
                raise RuntimeError(
                    "Forecast model not registered"
                )

            history = json.loads(
                job["history_json"]
            )

            predictions = model(
                history,
                job["horizon_days"],
            )

            if (
                not isinstance(predictions, list)
                or len(predictions)
                != job["horizon_days"]
            ):
                raise ValueError(
                    "Invalid forecast output length"
                )

            for value in predictions:
                if (
                    isinstance(value, bool)
                    or not isinstance(
                        value, (int, float)
                    )
                    or not math.isfinite(value)
                    or value < 0
                ):
                    raise ValueError(
                        "Invalid prediction"
                    )

            start_date = (
                utc_now().date()
                + timedelta(days=1)
            )

            with self.db:
                for index, prediction in enumerate(
                    predictions
                ):
                    forecast_date = (
                        start_date
                        + timedelta(days=index)
                    ).isoformat()

                    self.db.execute(
                        """
                        INSERT OR IGNORE INTO forecasts (
                            job_id, forecast_date,
                            store_id, sku,
                            model_name, model_version,
                            predicted_units, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            job["job_id"],
                            forecast_date,
                            job["store_id"],
                            job["sku"],
                            job["model_name"],
                            job["model_version"],
                            float(prediction),
                            utc_now().isoformat(),
                        ),
                    )

                self.db.execute(
                    """
                    UPDATE forecast_jobs
                    SET status = 'completed',
                        completed_at = ?,
                        error_type = NULL
                    WHERE job_id = ?
                    """,
                    (
                        utc_now().isoformat(),
                        job["job_id"],
                    ),
                )

            return {
                "job_id": job["job_id"],
                "status": "completed",
                "predictions": predictions,
                "model": job["model_name"],
                "model_version": job["model_version"],
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
                    UPDATE forecast_jobs
                    SET status = ?,
                        next_attempt_at = ?,
                        error_type = ?
                    WHERE job_id = ?
                    """,
                    (
                        status,
                        next_time.isoformat(),
                        type(exc).__name__,
                        job["job_id"],
                    ),
                )

            return {
                "job_id": job["job_id"],
                "status": status,
                "error_type": type(exc).__name__,
            }

    def record_actual(
        self,
        job_id: str,
        forecast_date: str,
        actual_units: float,
    ) -> None:
        if (
            isinstance(actual_units, bool)
            or not isinstance(
                actual_units, (int, float)
            )
            or not math.isfinite(actual_units)
            or actual_units < 0
        ):
            raise ValueError("Invalid actual units")

        existing = self.db.execute(
            """
            SELECT 1
            FROM forecasts
            WHERE job_id = ?
              AND forecast_date = ?
            """,
            (job_id, forecast_date),
        ).fetchone()

        if not existing:
            raise ValueError(
                "Forecast record not found"
            )

        with self.db:
            self.db.execute(
                """
                INSERT INTO forecast_actuals (
                    job_id, forecast_date,
                    actual_units, recorded_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(job_id, forecast_date)
                DO UPDATE SET
                    actual_units = excluded.actual_units,
                    recorded_at = excluded.recorded_at
                """,
                (
                    job_id,
                    forecast_date,
                    actual_units,
                    utc_now().isoformat(),
                ),
            )

    def evaluate(self, job_id: str) -> dict:
        rows = self.db.execute(
            """
            SELECT f.predicted_units,
                   a.actual_units
            FROM forecasts f
            JOIN forecast_actuals a
              ON a.job_id = f.job_id
             AND a.forecast_date = f.forecast_date
            WHERE f.job_id = ?
            """,
            (job_id,),
        ).fetchall()

        if not rows:
            return {
                "job_id": job_id,
                "status": "awaiting_actuals",
            }

        errors = [
            row["predicted_units"]
            - row["actual_units"]
            for row in rows
        ]

        mae = mean(
            abs(error) for error in errors
        )

        rmse = math.sqrt(
            mean(
                error ** 2 for error in errors
            )
        )

        total_actual = sum(
            row["actual_units"]
            for row in rows
        )

        wape = (
            sum(abs(error) for error in errors)
            / total_actual
            if total_actual > 0
            else None
        )

        return {
            "job_id": job_id,
            "evaluated_days": len(rows),
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "wape": (
                round(wape, 4)
                if wape is not None
                else None
            ),
        }

    def get_forecast(
        self, job_id: str
    ) -> list[dict]:
        rows = self.db.execute(
            """
            SELECT forecast_date,
                   store_id, sku,
                   predicted_units,
                   model_name, model_version
            FROM forecasts
            WHERE job_id = ?
            ORDER BY forecast_date
            """,
            (job_id,),
        ).fetchall()

        return [dict(row) for row in rows]

    def close(self):
        self.db.close()


if __name__ == "__main__":
    worker = ForecastingWorker()

    job = ForecastJob(
        job_id=uuid.uuid4().hex,
        store_id="STORE-KOCHI-01",
        sku="SKU-101",
        model_name="moving_average",
        model_version="1.0.0",
        horizon_days=7,
        historical_demand=(
            20, 22, 21, 24, 23,
            27, 25, 26, 28, 30,
            29, 31, 32, 30,
        ),
    )

    worker.enqueue(job)

    print(json.dumps(
        worker.process_one(),
        indent=2,
    ))

    print(json.dumps(
        worker.get_forecast(job.job_id),
        indent=2,
    ))

    worker.close()
