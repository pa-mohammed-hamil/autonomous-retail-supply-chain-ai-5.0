from __future__ import annotations

"""Planned module: demand service. Implementation pending."""

"""
backend/services/demand_service.py

Autonomous Retail Supply Chain AI 5.0

Demand Forecasting and Planning Service

Python 3.10+
Dependencies: standard library only

Features:
- Tenant-scoped demand history
- Daily demand aggregation
- Moving-average forecasting
- Exponential smoothing forecasting
- Optional external ML forecasting
- Demand trend analysis
- Forecast accuracy evaluation
- Reorder recommendations
- JSON report export

The baseline is deterministic.

For production, use:
- Database-backed historical records
- Model registry and versioning
- Time-series backtesting
- Seasonal and promotional features
- Stockout-censored demand correction
- Authorization and audit logging
"""


import json
import math
import statistics

from collections import defaultdict
from dataclasses import (
    asdict,
    dataclass,
)
from datetime import (
    date,
    timedelta,
)
from pathlib import Path
from typing import (
    Any,
    Callable,
    Iterable,
)


def nonnegative(
    value: float,
    name: str,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(
            value,
            (int, float),
        )
        or not math.isfinite(
            value
        )
        or value < 0
    ):
        raise ValueError(
            f"{name} must be a finite "
            "nonnegative number"
        )

    return float(value)


@dataclass(frozen=True)
class DemandRecord:
    tenant_id: str
    sku: str
    warehouse_id: str
    demand_date: str
    quantity: float


@dataclass(frozen=True)
class DemandForecast:
    tenant_id: str
    sku: str
    warehouse_id: str
    method: str
    history_days: int
    horizon_days: int
    daily_predictions: list[dict[str, Any]]
    total_predicted_demand: float
    average_daily_demand: float


@dataclass(frozen=True)
class DemandTrend:
    tenant_id: str
    sku: str
    warehouse_id: str
    recent_average: float
    previous_average: float
    percentage_change: float | None
    direction: str


@dataclass(frozen=True)
class ReorderRecommendation:
    tenant_id: str
    sku: str
    warehouse_id: str
    current_stock: float
    lead_time_days: int
    safety_stock: float
    expected_lead_time_demand: float
    target_stock: float
    suggested_order_quantity: float
    requires_approval: bool


class RetailDemandService:
    """
    Demand intelligence service.

    All records must belong to
    the service's tenant.

    Historical daily records are
    aggregated by SKU, warehouse,
    and date.

    Missing calendar days are filled
    with zero only when the caller
    confirms a complete sales history.
    """

    def __init__(
        self,
        tenant_id: str,
        ml_predictor: (
            Callable[
                [list[float], int],
                list[float],
            ]
            | None
        ) = None,
    ):
        if (
            not isinstance(tenant_id, str)
            or not tenant_id.strip()
        ):
            raise ValueError(
                "tenant_id is required"
            )

        self.tenant_id = tenant_id
        self.ml_predictor = ml_predictor

    def _validate_records(
        self,
        records: Iterable[DemandRecord],
    ) -> list[DemandRecord]:
        items = list(records)

        for record in items:
            if (
                record.tenant_id
                != self.tenant_id
            ):
                raise PermissionError(
                    "Cross-tenant demand record"
                )

            if (
                not record.sku.strip()
                or not record.warehouse_id.strip()
            ):
                raise ValueError(
                    "SKU and warehouse required"
                )

            date.fromisoformat(
                record.demand_date
            )

            nonnegative(
                record.quantity,
                "quantity",
            )

        return items

    def daily_demand(
        self,
        records: Iterable[DemandRecord],
        sku: str,
        warehouse_id: str,
        fill_missing_days: bool = False,
    ) -> list[dict[str, Any]]:
        items = self._validate_records(
            records
        )

        daily = defaultdict(float)

        for record in items:
            if (
                record.sku == sku
                and record.warehouse_id
                == warehouse_id
            ):
                daily[
                    record.demand_date
                ] += record.quantity

        if not daily:
            return []

        dates = sorted(
            date.fromisoformat(day)
            for day in daily
        )

        if fill_missing_days:
            current = dates[0]
            end = dates[-1]

            while current <= end:
                daily.setdefault(
                    current.isoformat(),
                    0.0,
                )

                current += timedelta(
                    days=1
                )

        return [
            {
                "date": day,
                "quantity": round(
                    quantity, 4
                ),
            }
            for day, quantity in sorted(
                daily.items()
            )
        ]

    @staticmethod
    def _moving_average(
        history: list[float],
        horizon: int,
        window: int,
    ) -> list[float]:
        if window <= 0:
            raise ValueError(
                "window must be positive"
            )

        if not history:
            raise ValueError(
                "Demand history required"
            )

        forecast_value = (
            statistics.mean(
                history[-window:]
            )
        )

        return [
            max(0.0, forecast_value)
            for _ in range(horizon)
        ]

    @staticmethod
    def _exponential_smoothing(
        history: list[float],
        horizon: int,
        alpha: float,
    ) -> list[float]:
        if not 0 < alpha <= 1:
            raise ValueError(
                "alpha must be in (0, 1]"
            )

        if not history:
            raise ValueError(
                "Demand history required"
            )

        level = history[0]

        for actual in history[1:]:
            level = (
                alpha * actual
                + (1 - alpha) * level
            )

        return [
            max(0.0, level)
            for _ in range(horizon)
        ]

    def forecast(
        self,
        records: Iterable[DemandRecord],
        sku: str,
        warehouse_id: str,
        horizon_days: int = 7,
        method: str = "moving_average",
        window: int = 7,
        alpha: float = 0.3,
        fill_missing_days: bool = False,
    ) -> DemandForecast:
        if (
            isinstance(horizon_days, bool)
            or not isinstance(
                horizon_days,
                int,
            )
            or not 1 <= horizon_days <= 365
        ):
            raise ValueError(
                "horizon_days must be 1-365"
            )

        daily = self.daily_demand(
            records,
            sku,
            warehouse_id,
            fill_missing_days,
        )

        if not daily:
            raise ValueError(
                "No demand history found"
            )

        history = [
            float(item["quantity"])
            for item in daily
        ]

        if method == "moving_average":
            predictions = (
                self._moving_average(
                    history,
                    horizon_days,
                    window,
                )
            )

        elif method == "exponential_smoothing":
            predictions = (
                self._exponential_smoothing(
                    history,
                    horizon_days,
                    alpha,
                )
            )

        elif method == "ml":
            if self.ml_predictor is None:
                raise ValueError(
                    "ML predictor not configured"
                )

            predictions = (
                self.ml_predictor(
                    history,
                    horizon_days,
                )
            )

        else:
            raise ValueError(
                "Unsupported forecasting method"
            )

        predictions = list(
            predictions
        )

        if len(predictions) != horizon_days:
            raise ValueError(
                "Predictor returned incorrect "
                "forecast horizon"
            )

        predictions = [
            nonnegative(
                value,
                "prediction",
            )
            for value in predictions
        ]

        last_date = date.fromisoformat(
            daily[-1]["date"]
        )

        output = [
            {
                "date": (
                    last_date
                    + timedelta(days=i)
                ).isoformat(),
                "predicted_demand": round(
                    value, 4
                ),
            }
            for i, value in enumerate(
                predictions,
                start=1,
            )
        ]

        total = sum(
            predictions
        )

        return DemandForecast(
            tenant_id=self.tenant_id,
            sku=sku,
            warehouse_id=warehouse_id,
            method=method,
            history_days=len(history),
            horizon_days=horizon_days,
            daily_predictions=output,
            total_predicted_demand=round(
                total, 4
            ),
            average_daily_demand=round(
                total / horizon_days,
                4,
            ),
        )

    def detect_trend(
        self,
        records: Iterable[DemandRecord],
        sku: str,
        warehouse_id: str,
        window: int = 7,
        fill_missing_days: bool = False,
        threshold_pct: float = 10.0,
    ) -> DemandTrend:
        if window < 1:
            raise ValueError(
                "window must be positive"
            )

        nonnegative(
            threshold_pct,
            "threshold_pct",
        )

        daily = self.daily_demand(
            records,
            sku,
            warehouse_id,
            fill_missing_days,
        )

        if len(daily) < 2 * window:
            raise ValueError(
                "At least two complete "
                "windows are required"
            )

        values = [
            float(item["quantity"])
            for item in daily
        ]

        previous = statistics.mean(
            values[-2 * window:-window]
        )

        recent = statistics.mean(
            values[-window:]
        )

        if previous == 0:
            change = (
                0.0
                if recent == 0
                else None
            )

            direction = (
                "stable"
                if recent == 0
                else "new_demand"
            )

        else:
            change = (
                (recent - previous)
                / previous * 100
            )

            if change > threshold_pct:
                direction = "increasing"
            elif change < -threshold_pct:
                direction = "decreasing"
            else:
                direction = "stable"

        return DemandTrend(
            tenant_id=self.tenant_id,
            sku=sku,
            warehouse_id=warehouse_id,
            recent_average=round(
                recent, 4
            ),
            previous_average=round(
                previous, 4
            ),
            percentage_change=(
                round(change, 2)
                if change is not None
                else None
            ),
            direction=direction,
        )

    @staticmethod
    def evaluate_forecast(
        actual: list[float],
        predicted: list[float],
    ) -> dict[str, float | None]:
        if (
            not actual
            or len(actual) != len(predicted)
        ):
            raise ValueError(
                "Actual and predicted arrays "
                "must be equal and nonempty"
            )

        actual = [
            nonnegative(
                value,
                "actual",
            )
            for value in actual
        ]

        predicted = [
            nonnegative(
                value,
                "predicted",
            )
            for value in predicted
        ]

        errors = [
            abs(a - p)
            for a, p in zip(
                actual,
                predicted,
            )
        ]

        mae = statistics.mean(
            errors
        )

        rmse = math.sqrt(
            statistics.mean(
                [
                    (a - p) ** 2
                    for a, p in zip(
                        actual,
                        predicted,
                    )
                ]
            )
        )

        actual_sum = sum(actual)

        wape = (
            sum(errors)
            / actual_sum * 100
            if actual_sum > 0
            else None
        )

        percentage_errors = [
            abs(a - p) / a * 100
            for a, p in zip(
                actual,
                predicted,
            )
            if a > 0
        ]

        mape = (
            statistics.mean(
                percentage_errors
            )
            if percentage_errors
            else None
        )

        return {
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "wape_pct": (
                round(wape, 2)
                if wape is not None
                else None
            ),
            "mape_pct": (
                round(mape, 2)
                if mape is not None
                else None
            ),
        }

    def recommend_reorder(
        self,
        forecast: DemandForecast,
        current_stock: float,
        lead_time_days: int,
        safety_stock: float,
        incoming_stock: float = 0.0,
        reserved_stock: float = 0.0,
    ) -> ReorderRecommendation:
        if forecast.tenant_id != self.tenant_id:
            raise PermissionError(
                "Cross-tenant forecast"
            )

        if (
            isinstance(lead_time_days, bool)
            or not isinstance(
                lead_time_days,
                int,
            )
            or lead_time_days < 0
        ):
            raise ValueError(
                "Invalid lead time"
            )

        current_stock = nonnegative(
            current_stock,
            "current_stock",
        )

        safety_stock = nonnegative(
            safety_stock,
            "safety_stock",
        )

        incoming_stock = nonnegative(
            incoming_stock,
            "incoming_stock",
        )

        reserved_stock = nonnegative(
            reserved_stock,
            "reserved_stock",
        )

        if lead_time_days <= (
            forecast.horizon_days
        ):
            expected_demand = sum(
                item["predicted_demand"]
                for item in (
                    forecast.daily_predictions[
                        :lead_time_days
                    ]
                )
            )
        else:
            # Explicit constant-demand
            # extrapolation beyond the
            # available forecast horizon.
            expected_demand = (
                forecast.total_predicted_demand
                + (
                    lead_time_days
                    - forecast.horizon_days
                )
                * forecast.average_daily_demand
            )

        target_stock = (
            expected_demand
            + safety_stock
        )

        available_stock = (
            current_stock
            + incoming_stock
            - reserved_stock
        )

        order_quantity = max(
            0.0,
            target_stock - available_stock,
        )

        return ReorderRecommendation(
            tenant_id=self.tenant_id,
            sku=forecast.sku,
            warehouse_id=forecast.warehouse_id,
            current_stock=current_stock,
            lead_time_days=lead_time_days,
            safety_stock=safety_stock,
            expected_lead_time_demand=round(
                expected_demand, 4
            ),
            target_stock=round(
                target_stock, 4
            ),
            suggested_order_quantity=round(
                order_quantity, 4
            ),
            requires_approval=(
                order_quantity > 0
            ),
        )

    @staticmethod
    def export_json(
        data: Any,
        output_path: str | Path,
    ) -> Path:
        output = Path(
            output_path
        )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        payload = (
            asdict(data)
            if hasattr(
                data,
                "__dataclass_fields__",
            )
            else data
        )

        output.write_text(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return output


if __name__ == "__main__":
    service = RetailDemandService(
        tenant_id="demo"
    )

    quantities = [
        18, 20, 19, 22, 21, 24, 23,
        25, 27, 26, 29, 30, 28, 32,
    ]

    start = date(
        2026, 10, 1
    )

    records = [
        DemandRecord(
            tenant_id="demo",
            sku="SKU001",
            warehouse_id="WH001",
            demand_date=(
                start
                + timedelta(days=i)
            ).isoformat(),
            quantity=quantity,
        )
        for i, quantity in enumerate(
            quantities
        )
    ]

    forecast = service.forecast(
        records=records,
        sku="SKU001",
        warehouse_id="WH001",
        horizon_days=7,
        method="moving_average",
        window=7,
    )

    trend = service.detect_trend(
        records=records,
        sku="SKU001",
        warehouse_id="WH001",
        window=7,
    )

    reorder = service.recommend_reorder(
        forecast=forecast,
        current_stock=50,
        lead_time_days=7,
        safety_stock=25,
        incoming_stock=10,
    )

    print(
        json.dumps(
            {
                "forecast": asdict(
                    forecast
                ),
                "trend": asdict(
                    trend
                ),
                "reorder": asdict(
                    reorder
                ),
            },
            indent=2,
        )
    )

    service.export_json(
        forecast,
        "reports/demand_forecast.json",
    )
