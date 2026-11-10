"""Planned module: daily forecasting. Implementation pending."""

"""
ai/forecasting/daily_forecasting.py

Daily SKU demand forecasting.

Features:
- Weighted moving-average baseline
- Weekday demand adjustment
- Multi-day forecasts
- Historical backtest MAE and RMSE
- Approximate prediction intervals
- Inventory coverage and reorder indicators

Requires daily demand history with zero-sales
days included. Stockouts must be identified
separately because sales can understate demand.

No purchase orders are created.
"""

from __future__ import annotations

import math
import statistics

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class DailySale:
    sku: str
    day: date
    quantity: int

    def __post_init__(self):
        if not self.sku:
            raise ValueError("SKU required")
        if (
            isinstance(self.quantity, bool)
            or not isinstance(self.quantity, int)
            or self.quantity < 0
        ):
            raise ValueError("Invalid sales quantity")


class DailyForecaster:

    @staticmethod
    def _predict_one(
        history: list[DailySale],
        window: int,
    ) -> float:
        recent = history[-window:]

        weights = list(range(1, len(recent) + 1))
        base = sum(
            record.quantity * weight
            for record, weight in zip(recent, weights)
        ) / sum(weights)

        return base

    @staticmethod
    def _weekday_factor(
        history: list[DailySale],
        target_day: date,
    ) -> float:
        if len(history) < 28:
            return 1.0

        overall = statistics.mean(
            item.quantity for item in history
        )

        if overall == 0:
            return 1.0

        matching = [
            item.quantity
            for item in history
            if item.day.weekday() == target_day.weekday()
        ]

        if len(matching) < 4:
            return 1.0

        factor = statistics.mean(matching) / overall

        # Cap extreme adjustments for stability.
        return max(0.5, min(1.5, factor))

    def forecast(
        self,
        sales: list[DailySale],
        sku: str,
        horizon_days: int = 7,
        window: int = 14,
        current_available_stock: int | None = None,
        lead_time_days: int = 5,
        safety_stock: int = 0,
    ) -> dict:

        if (
            isinstance(horizon_days, bool)
            or not isinstance(horizon_days, int)
            or horizon_days <= 0
        ):
            raise ValueError("Invalid forecast horizon")

        if (
            isinstance(window, bool)
            or not isinstance(window, int)
            or window < 2
        ):
            raise ValueError("Invalid window")

        if (
            isinstance(lead_time_days, bool)
            or not isinstance(lead_time_days, int)
            or lead_time_days < 0
        ):
            raise ValueError("Invalid lead time")

        if (
            isinstance(safety_stock, bool)
            or not isinstance(safety_stock, int)
            or safety_stock < 0
        ):
            raise ValueError("Invalid safety stock")

        if current_available_stock is not None and (
            isinstance(current_available_stock, bool)
            or not isinstance(current_available_stock, int)
            or current_available_stock < 0
        ):
            raise ValueError("Invalid available stock")

        history = sorted(
            (item for item in sales if item.sku == sku),
            key=lambda item: item.day,
        )

        if len(history) < window + 7:
            raise ValueError(
                "Insufficient history for forecasting"
            )

        days = [item.day for item in history]

        if len(days) != len(set(days)):
            raise ValueError("Duplicate dates for SKU")

        if any(
            b - a != timedelta(days=1)
            for a, b in zip(days, days[1:])
        ):
            raise ValueError(
                "Daily history must be consecutive"
            )

        # One-step rolling historical errors.
        errors = []

        for i in range(window, len(history)):
            training = history[:i]
            prediction = (
                self._predict_one(training, window)
                * self._weekday_factor(
                    training, history[i].day
                )
            )
            errors.append(
                history[i].quantity - prediction
            )

        mae = statistics.mean(
            abs(error) for error in errors
        )

        rmse = math.sqrt(
            statistics.mean(
                error ** 2 for error in errors
            )
        )

        base = self._predict_one(history, window)
        last_day = history[-1].day

        forecasts = []

        for offset in range(1, horizon_days + 1):
            target = last_day + timedelta(days=offset)

            expected = max(
                0.0,
                base * self._weekday_factor(
                    history, target
                ),
            )

            # Heuristic uncertainty band.
            # Not a calibrated statistical interval.
            margin = 1.96 * rmse * math.sqrt(offset)

            forecasts.append({
                "date": target.isoformat(),
                "expected_units": round(expected, 2),
                "lower_estimate": round(
                    max(0.0, expected - margin), 2
                ),
                "upper_estimate": round(
                    expected + margin, 2
                ),
            })

        total_expected = sum(
            item["expected_units"]
            for item in forecasts
        )

        result = {
            "sku": sku,
            "method": "weighted_moving_average",
            "forecast_horizon_days": horizon_days,
            "forecast": forecasts,
            "total_expected_units": round(
                total_expected, 2
            ),
            "historical_backtest": {
                "mae": round(mae, 2),
                "rmse": round(rmse, 2),
                "evaluated_days": len(errors),
            },
            "interval_type": (
                "heuristic_uncertainty_band"
            ),
            "requires_approval": True,
            "purchase_order_created": False,
        }

        if current_available_stock is not None:
            lead_demand = sum(
                item["expected_units"]
                for item in forecasts[:lead_time_days]
            )

            threshold = lead_demand + safety_stock

            result["inventory_indicator"] = {
                "available_stock": (
                    current_available_stock
                ),
                "forecast_demand_during_visible_lead_time": (
                    round(lead_demand, 2)
                ),
                "safety_stock": safety_stock,
                "reorder_review_recommended": (
                    current_available_stock < threshold
                ),
                "warning": (
                    "Extend forecast horizon to at least "
                    "lead_time_days for complete lead-time "
                    "coverage"
                    if horizon_days < lead_time_days
                    else None
                ),
            }

        return result
