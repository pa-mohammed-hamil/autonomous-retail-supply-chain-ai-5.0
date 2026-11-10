"""Planned module: backtesting. Implementation pending."""

"""
ai/evaluation/backtesting.py

Autonomous Retail Supply Chain AI 5.0

Expanding-Window Forecast Backtesting

Install:
    pip install numpy pandas scikit-learn

Important:
    X must contain point-in-time-safe features.
    All feature preprocessing must be fitted
    inside the estimator pipeline.

    The caller must provide features that
    would actually have been available
    when each forecast was generated.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from sklearn.base import clone
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
)


class RetailBacktester:

    def __init__(
        self,
        model,
        min_train_periods=90,
        test_periods=14,
        step_periods=14,
        gap_periods=0,
    ):
        if min_train_periods < 1:
            raise ValueError(
                "min_train_periods must be >= 1"
            )

        if test_periods < 1:
            raise ValueError(
                "test_periods must be >= 1"
            )

        if step_periods < 1:
            raise ValueError(
                "step_periods must be >= 1"
            )

        if gap_periods < 0:
            raise ValueError(
                "gap_periods cannot be negative"
            )

        self.model = model

        self.min_train_periods = (
            min_train_periods
        )

        self.test_periods = test_periods
        self.step_periods = step_periods
        self.gap_periods = gap_periods

        self.fold_metrics = None
        self.predictions = None

    @staticmethod
    def calculate_metrics(
        actual,
        predicted,
    ):
        actual = np.asarray(
            actual,
            dtype=float,
        )

        predicted = np.asarray(
            predicted,
            dtype=float,
        )

        errors = predicted - actual

        denominator = np.abs(
            actual
        ).sum()

        return {
            "mae": float(
                mean_absolute_error(
                    actual,
                    predicted,
                )
            ),
            "rmse": float(
                np.sqrt(
                    mean_squared_error(
                        actual,
                        predicted,
                    )
                )
            ),
            "bias": float(
                errors.mean()
            ),
            "wape_pct": (
                float(
                    np.abs(errors).sum()
                    / denominator * 100
                )
                if denominator > 0
                else None
            ),
        }

    def run(
        self,
        frame,
        date_col,
        target_col,
        feature_cols,
    ):
        df = frame.copy()

        required = [
            date_col,
            target_col,
            *feature_cols,
        ]

        missing = set(required) - set(
            df.columns
        )

        if missing:
            raise ValueError(
                f"Missing columns: {sorted(missing)}"
            )

        if (
            date_col in feature_cols
            or target_col in feature_cols
        ):
            raise ValueError(
                "Date/target must not be "
                "included as raw features"
            )

        df[date_col] = pd.to_datetime(
            df[date_col],
            errors="raise",
            utc=True,
        )

        if df[date_col].isna().any():
            raise ValueError(
                "Invalid dates"
            )

        df[target_col] = pd.to_numeric(
            df[target_col],
            errors="raise",
        )

        if not np.isfinite(
            df[target_col].to_numpy(
                dtype=float
            )
        ).all():
            raise ValueError(
                "Target must be finite"
            )

        df = df.sort_values(
            date_col
        ).reset_index(drop=True)

        # Split by unique dates, not rows.
        dates = pd.DatetimeIndex(
            sorted(
                df[date_col]
                .dt.normalize()
                .unique()
            )
        )

        n_dates = len(dates)

        minimum_required = (
            self.min_train_periods
            + self.gap_periods
            + self.test_periods
        )

        if n_dates < minimum_required:
            raise ValueError(
                "Insufficient historical dates"
            )

        fold_results = []
        prediction_results = []

        fold_number = 0

        for train_end in range(
            self.min_train_periods,
            n_dates
            - self.gap_periods
            - self.test_periods
            + 1,
            self.step_periods,
        ):
            fold_number += 1

            test_start = (
                train_end
                + self.gap_periods
            )

            test_end = (
                test_start
                + self.test_periods
            )

            train_dates = dates[
                :train_end
            ]

            test_dates = dates[
                test_start:test_end
            ]

            train = df[
                df[date_col]
                .dt.normalize()
                .isin(train_dates)
            ]

            test = df[
                df[date_col]
                .dt.normalize()
                .isin(test_dates)
            ]

            model = clone(
                self.model
            )

            model.fit(
                train[feature_cols],
                train[target_col],
            )

            predictions = model.predict(
                test[feature_cols]
            )

            metrics = (
                self.calculate_metrics(
                    test[target_col],
                    predictions,
                )
            )

            fold_results.append({
                "fold": fold_number,
                "train_start": str(
                    train_dates[0].date()
                ),
                "train_end": str(
                    train_dates[-1].date()
                ),
                "test_start": str(
                    test_dates[0].date()
                ),
                "test_end": str(
                    test_dates[-1].date()
                ),
                "train_rows": len(train),
                "test_rows": len(test),
                **metrics,
            })

            fold_predictions = test[
                [date_col, target_col]
            ].copy()

            fold_predictions[
                "predicted"
            ] = predictions

            fold_predictions[
                "fold"
            ] = fold_number

            prediction_results.append(
                fold_predictions
            )

        if not fold_results:
            raise RuntimeError(
                "No backtest folds generated"
            )

        self.fold_metrics = (
            pd.DataFrame(
                fold_results
            )
        )

        self.predictions = pd.concat(
            prediction_results,
            ignore_index=True,
        )

        return self.fold_metrics

    def summary(self):
        if self.predictions is None:
            raise RuntimeError(
                "Run backtesting first"
            )

        actual_col = (
            self.predictions.columns[1]
        )

        metrics = self.calculate_metrics(
            self.predictions[actual_col],
            self.predictions["predicted"],
        )

        metrics["fold_count"] = len(
            self.fold_metrics
        )

        metrics["evaluated_predictions"] = len(
            self.predictions
        )

        return metrics

    def save(
        self,
        output_dir="reports/backtesting",
    ):
        if self.fold_metrics is None:
            raise RuntimeError(
                "Run backtesting first"
            )

        directory = Path(
            output_dir
        )

        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.fold_metrics.to_csv(
            directory / "fold_metrics.csv",
            index=False,
        )

        self.predictions.to_csv(
            directory / "predictions.csv",
            index=False,
        )

        (
            directory / "summary.json"
        ).write_text(
            json.dumps(
                self.summary(),
                indent=2,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    rng = np.random.default_rng(42)

    n = 240

    dates = pd.date_range(
        "2026-01-01",
        periods=n,
        freq="D",
    )

    df = pd.DataFrame({
        "date": dates,
        "price": rng.uniform(
            50, 150, n
        ),
        "promotion": rng.integers(
            0, 2, n
        ),
        "weekday": dates.dayofweek,
    })

    df["demand"] = (
        130
        - 0.4 * df["price"]
        + 20 * df["promotion"]
        + 8 * np.sin(
            2 * np.pi
            * np.arange(n) / 7
        )
        + rng.normal(0, 5, n)
    )

    model = RandomForestRegressor(
        n_estimators=100,
        random_state=42,
        n_jobs=-1,
    )

    backtester = RetailBacktester(
        model=model,
        min_train_periods=90,
        test_periods=14,
        step_periods=14,
        gap_periods=0,
    )

    results = backtester.run(
        frame=df,
        date_col="date",
        target_col="demand",
        feature_cols=[
            "price",
            "promotion",
            "weekday",
        ],
    )

    print("\nBacktest folds:")
    print(
        results.to_string(
            index=False
        )
    )

    print("\nSummary:")
    print(
        json.dumps(
            backtester.summary(),
            indent=2,
        )
    )

    backtester.save()
