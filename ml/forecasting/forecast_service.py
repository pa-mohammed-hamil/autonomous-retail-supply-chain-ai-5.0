=
"""
ai/forecasting/forecast_service.py

Unified Retail Demand Forecasting Service

Supports:
- Baseline models
- ARIMA
- Exponential smoothing
- Automatic model selection
- Rolling-origin backtesting
- Forecasting per SKU/store
- CSV/JSON export

Dependencies:
numpy, pandas, statsmodels

Run from project root:
python -m ai.forecasting.forecast_service
"""

from __future__ import annotations

import csv
import json
import math

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Sequence

from ai.forecasting.baseline_forecast import (
    BaselineForecaster,
)
from ai.forecasting.arima_forecast import (
    ARIMAForecaster,
)
from ai.forecasting.exponential_smoothing import (
    ExponentialSmoothingForecaster,
)


@dataclass(frozen=True)
class ForecastConfig:
    horizon: int = 7
    season_length: int = 7
    initial_train_size: int = 42
    backtest_step: int = 7
    metric: str = "mae"

    def __post_init__(self):
        for name in (
            "horizon",
            "season_length",
            "initial_train_size",
            "backtest_step",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 1
            ):
                raise ValueError(
                    f"{name} must be positive"
                )

        if self.metric not in {
            "mae", "rmse", "wape_percent"
        }:
            raise ValueError("Unsupported metric")


class ForecastService:

    def __init__(
        self,
        config: ForecastConfig | None = None,
    ):
        self.config = config or ForecastConfig()

    @staticmethod
    def _validate(values: Sequence[float]):
        series = [float(x) for x in values]

        if not series or any(
            not math.isfinite(x) or x < 0
            for x in series
        ):
            raise ValueError(
                "Demand must be finite, "
                "nonnegative and nonempty"
            )

        return series

    def _create_model(self, name: str):
        season = self.config.season_length

        if name == "naive":
            return BaselineForecaster(
                method="naive"
            )

        if name == "seasonal_naive":
            return BaselineForecaster(
                method="seasonal_naive",
                season_length=season,
            )

        if name == "moving_average":
            return BaselineForecaster(
                method="moving_average",
                window=season,
            )

        if name == "arima":
            return ARIMAForecaster(
                order=(1, 1, 1)
            )

        if name == "exponential_smoothing":
            return ExponentialSmoothingForecaster(
                method="holt_winters_add",
                seasonal_periods=season,
            )

        raise ValueError(
            f"Unsupported model: {name}"
        )

    @staticmethod
    def _forecast_values(model, horizon: int):
        result = model.predict(horizon)

        if isinstance(result, dict):
            return result["forecast"]

        return result

    def evaluate_models(
        self,
        values: Sequence[float],
        model_names: Sequence[str] | None = None,
    ) -> list[dict]:
        series = self._validate(values)

        names = list(model_names or (
            "naive",
            "seasonal_naive",
            "moving_average",
            "arima",
            "exponential_smoothing",
        ))

        if not names:
            raise ValueError("No models selected")

        if (
            self.config.initial_train_size
            + self.config.horizon
            > len(series)
        ):
            raise ValueError(
                "Insufficient history for backtesting"
            )

        results = []

        for name in names:
            try:
                model = self._create_model(name)

                report = model.backtest(
                    series,
                    initial_train_size=(
                        self.config.initial_train_size
                    ),
                    horizon=self.config.horizon,
                    step=self.config.backtest_step,
                )

                metrics = report["overall_metrics"]
                score = metrics[self.config.metric]

                if score is None or not math.isfinite(
                    float(score)
                ):
                    raise ValueError(
                        "Undefined evaluation score"
                    )

                results.append({
                    "model": name,
                    "status": "success",
                    "score": float(score),
                    "metrics": metrics,
                    "fold_count": report["fold_count"],
                })

            except (
                ValueError,
                RuntimeError,
                ArithmeticError,
                ImportError,
            ) as exc:
                results.append({
                    "model": name,
                    "status": "failed",
                    "error": str(exc),
                })

        results.sort(
            key=lambda row: (
                row["status"] != "success",
                row.get("score", float("inf")),
            )
        )

        return results

    def forecast(
        self,
        values: Sequence[float],
        model_name: str = "auto",
        horizon: int | None = None,
    ) -> dict:
        series = self._validate(values)

        steps = (
            horizon
            if horizon is not None
            else self.config.horizon
        )

        if (
            isinstance(steps, bool)
            or not isinstance(steps, int)
            or steps < 1
        ):
            raise ValueError(
                "horizon must be positive"
            )

        comparison = []

        if model_name == "auto":
            comparison = self.evaluate_models(
                series
            )

            successful = [
                row for row in comparison
                if row["status"] == "success"
            ]

            if not successful:
                raise RuntimeError(
                    "No forecasting model succeeded"
                )

            model_name = successful[0]["model"]

        model = self._create_model(model_name)
        model.fit(series)

        predictions = self._forecast_values(
            model,
            steps,
        )

        if (
            len(predictions) != steps
            or any(
                not math.isfinite(float(x))
                for x in predictions
            )
        ):
            raise RuntimeError(
                "Invalid forecast output"
            )

        return {
            "selected_model": model_name,
            "horizon": steps,
            "history_length": len(series),
            "forecast": [
                round(max(0.0, float(x)), 4)
                for x in predictions
            ],
            "model_comparison": comparison,
        }

    def forecast_groups(
        self,
        records: Sequence[dict],
        group_columns: tuple[str, ...] = (
            "store_id", "sku"
        ),
        date_column: str = "date",
        demand_column: str = "actual_demand",
        model_name: str = "auto",
        horizon: int | None = None,
    ) -> list[dict]:
        if not records:
            raise ValueError("No records supplied")

        groups = {}

        for row in records:
            key = tuple(
                str(row[column])
                for column in group_columns
            )

            day = date.fromisoformat(
                str(row[date_column])
            )

            value = float(row[demand_column])

            if not math.isfinite(value) or value < 0:
                raise ValueError(
                    "Demand must be nonnegative"
                )

            daily = groups.setdefault(key, {})

            if day in daily:
                raise ValueError(
                    f"Duplicate group/date: {key} {day}"
                )

            daily[day] = value

        output = []

        for key, daily in sorted(groups.items()):
            start = min(daily)
            end = max(daily)

            # Missing dates are assumed to
            # represent zero demand. Use only
            # when that matches your data.
            history = []
            current = start

            while current <= end:
                history.append(
                    daily.get(current, 0.0)
                )
                current += timedelta(days=1)

            result = self.forecast(
                history,
                model_name=model_name,
                horizon=horizon,
            )

            for step, prediction in enumerate(
                result["forecast"],
                start=1,
            ):
                forecast_date = (
                    end + timedelta(days=step)
                )

                output.append({
                    **dict(zip(group_columns, key)),
                    "date": forecast_date.isoformat(),
                    "forecast_step": step,
                    "predicted_demand": prediction,
                    "model": result["selected_model"],
                })

        return output

    @staticmethod
    def save_json(data, path: str):
        output = Path(path)
        output.parent.mkdir(
            parents=True, exist_ok=True
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
    def save_csv(rows, path: str):
        if not rows:
            raise ValueError("No rows to export")

        output = Path(path)
        output.parent.mkdir(
            parents=True, exist_ok=True
        )

        columns = list(dict.fromkeys(
            key for row in rows for key in row
        ))

        with output.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file, fieldnames=columns
            )
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    service = ForecastService(
        ForecastConfig(
            horizon=7,
            initial_train_size=42,
            backtest_step=7,
        )
    )

    weekly = [
        110, 115, 120, 130, 145, 160, 150
    ]

    demand = [
        weekly[i % 7] + i * 0.2
        for i in range(84)
    ]

    result = service.forecast(
        demand,
        model_name="auto",
    )

    service.save_json(
        result,
        "data/forecasts/forecast_service.json",
    )

    print(json.dumps(result, indent=2))
