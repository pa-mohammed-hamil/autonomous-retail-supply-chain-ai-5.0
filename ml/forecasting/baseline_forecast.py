"""Planned module: baseline forecast. Implementation pending."""

"""
ai/forecasting/baseline_forecast.py

Autonomous Retail Supply Chain AI 5.0

Baseline Demand Forecasting

Methods:
- Naive forecast
- Seasonal naive forecast
- Moving average forecast
- Drift forecast

Evaluation:
- MAE
- RMSE
- WAPE
- Rolling-origin backtesting

Python 3.10+
Standard library only.
"""

from __future__ import annotations

import csv
import json
import math

from pathlib import Path
from statistics import mean
from typing import Sequence


class BaselineForecaster:

    METHODS = {
        "naive",
        "seasonal_naive",
        "moving_average",
        "drift",
    }

    def __init__(
        self,
        method: str = "seasonal_naive",
        season_length: int = 7,
        window: int = 7,
        nonnegative: bool = True,
    ):
        if method not in self.METHODS:
            raise ValueError(
                f"Unknown method: {method}"
            )

        for name, value in {
            "season_length": season_length,
            "window": window,
        }.items():
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 1
            ):
                raise ValueError(
                    f"{name} must be positive"
                )

        self.method = method
        self.season_length = season_length
        self.window = window
        self.nonnegative = nonnegative
        self.history = None

    @staticmethod
    def _validate(values):
        if isinstance(values, (str, bytes)):
            raise TypeError(
                "Expected numeric observations"
            )

        series = [float(v) for v in values]

        if not series:
            raise ValueError(
                "Empty demand series"
            )

        if any(
            not math.isfinite(v) or v < 0
            for v in series
        ):
            raise ValueError(
                "Demand must be finite and nonnegative"
            )

        return series

    def fit(
        self,
        values: Sequence[float],
    ) -> "BaselineForecaster":
        series = self._validate(values)

        if (
            self.method == "seasonal_naive"
            and len(series) < self.season_length
        ):
            raise ValueError(
                "Not enough seasonal observations"
            )

        if (
            self.method == "drift"
            and len(series) < 2
        ):
            raise ValueError(
                "Drift requires at least two observations"
            )

        self.history = series
        return self

    def predict(
        self,
        steps: int = 7,
    ) -> list[float]:
        if self.history is None:
            raise RuntimeError(
                "Call fit() first"
            )

        if (
            isinstance(steps, bool)
            or not isinstance(steps, int)
            or steps < 1
        ):
            raise ValueError(
                "steps must be positive"
            )

        history = self.history

        if self.method == "naive":
            predictions = [
                history[-1]
            ] * steps

        elif self.method == "seasonal_naive":
            season = history[
                -self.season_length:
            ]

            predictions = [
                season[
                    i % self.season_length
                ]
                for i in range(steps)
            ]

        elif self.method == "moving_average":
            average = mean(
                history[-self.window:]
            )

            predictions = [
                average
            ] * steps

        else:
            drift = (
                history[-1] - history[0]
            ) / (len(history) - 1)

            predictions = [
                history[-1]
                + drift * (i + 1)
                for i in range(steps)
            ]

        if self.nonnegative:
            predictions = [
                max(0.0, value)
                for value in predictions
            ]

        return [
            round(value, 4)
            for value in predictions
        ]

    @staticmethod
    def metrics(actual, predicted):
        actual = list(map(float, actual))
        predicted = list(map(float, predicted))

        if (
            not actual
            or len(actual) != len(predicted)
        ):
            raise ValueError(
                "Metric inputs must have equal "
                "nonzero length"
            )

        if any(
            not math.isfinite(v)
            for v in actual + predicted
        ):
            raise ValueError(
                "Metrics require finite values"
            )

        errors = [
            a - p
            for a, p in zip(
                actual, predicted
            )
        ]

        mae = mean(
            abs(error)
            for error in errors
        )

        rmse = math.sqrt(
            mean(
                error ** 2
                for error in errors
            )
        )

        total_demand = sum(
            abs(a)
            for a in actual
        )

        wape = (
            sum(abs(e) for e in errors)
            / total_demand * 100
            if total_demand > 0
            else None
        )

        return {
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "wape_percent": (
                round(wape, 4)
                if wape is not None
                else None
            ),
        }

    def backtest(
        self,
        values: Sequence[float],
        initial_train_size: int,
        horizon: int = 7,
        step: int = 7,
    ) -> dict:
        series = self._validate(values)

        if any(
            isinstance(v, bool)
            or not isinstance(v, int)
            or v < 1
            for v in (
                initial_train_size,
                horizon,
                step,
            )
        ):
            raise ValueError(
                "Backtest parameters must be positive"
            )

        if (
            initial_train_size + horizon
            > len(series)
        ):
            raise ValueError(
                "Insufficient backtest data"
            )

        folds = []
        all_actual = []
        all_predicted = []

        for train_end in range(
            initial_train_size,
            len(series) - horizon + 1,
            step,
        ):
            model = BaselineForecaster(
                method=self.method,
                season_length=self.season_length,
                window=self.window,
                nonnegative=self.nonnegative,
            )

            model.fit(
                series[:train_end]
            )

            predicted = model.predict(
                horizon
            )

            actual = series[
                train_end:train_end + horizon
            ]

            folds.append({
                "train_end_index": train_end,
                "actual": actual,
                "predicted": predicted,
                "metrics": self.metrics(
                    actual,
                    predicted,
                ),
            })

            all_actual.extend(actual)
            all_predicted.extend(predicted)

        return {
            "model": self.method,
            "fold_count": len(folds),
            "overall_metrics": self.metrics(
                all_actual,
                all_predicted,
            ),
            "folds": folds,
        }

    @staticmethod
    def save_json(data, path):
        output = Path(path)
        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            json.dumps(
                data,
                indent=2,
                allow_nan=False,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def save_csv(
        predictions,
        path,
    ):
        output = Path(path)
        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with output.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.writer(file)

            writer.writerow([
                "forecast_step",
                "predicted_demand",
            ])

            for index, value in enumerate(
                predictions,
                start=1,
            ):
                writer.writerow([
                    index,
                    value,
                ])


if __name__ == "__main__":
    demand = [
        105, 110, 112, 120, 130, 145, 150,
        108, 115, 118, 125, 135, 148, 155,
        112, 118, 121, 128, 140, 152, 160,
    ]

    model = BaselineForecaster(
        method="seasonal_naive",
        season_length=7,
    )

    model.fit(demand)

    forecast = model.predict(
        steps=7
    )

    print("Forecast:", forecast)

    model.save_json(
        {
            "method": model.method,
            "forecast": forecast,
        },
        "data/forecasts/baseline_forecast.json",
    )

    model.save_csv(
        forecast,
        "data/forecasts/baseline_forecast.csv",
    )
