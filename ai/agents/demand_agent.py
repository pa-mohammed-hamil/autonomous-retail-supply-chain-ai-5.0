"""Planned module: demand agent. Implementation pending."""

"""
File: ai/agents/demand_agent.py
Project: Autonomous Retail Supply Chain AI 5.0

Demand forecasting and replenishment agent.

Features:
- Historical sales validation
- Simple moving average
- Weighted moving average
- Linear trend forecast
- Seasonal naive forecast
- Multi-period forecasts
- Inventory demand coverage
- Reorder quantity recommendations
- Forecast accuracy metrics
- BaseAgent integration

Python 3.10+
Standard library only.

Assumptions:
- Sales history is ordered oldest to newest.
- Observations have equally spaced intervals.
- Sales are used as a proxy for demand.
- Stockouts and censored sales require correction
  before using forecasts for purchasing decisions.
"""

from __future__ import annotations

import math
from statistics import mean
from typing import Any

from .base_agent import (
    BaseAgent,
    AgentRequest,
    AgentValidationError,
)


class DemandAgent(BaseAgent):

    METHODS = frozenset({
        "moving_average",
        "weighted_average",
        "linear_trend",
        "seasonal_naive",
    })

    def __init__(
        self,
        working_memory: Any | None = None,
    ) -> None:
        super().__init__(
            agent_id="demand_agent",
            name="Demand Forecast Intelligence Agent",
            capabilities={
                "forecast_demand",
                "analyze_stockout_risk",
                "recommend_replenishment",
                "evaluate_forecast",
            },
            working_memory=working_memory,
        )

    @staticmethod
    def _nonnegative(
        value: Any,
        name: str,
    ) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise AgentValidationError(
                f"{name} must be finite and nonnegative."
            )

        return float(value)

    def _history(
        self,
        value: Any,
    ) -> list[float]:
        if (
            not isinstance(value, list)
            or not value
            or len(value) > 10000
        ):
            raise AgentValidationError(
                "sales_history must contain "
                "1 to 10000 observations."
            )

        return [
            self._nonnegative(
                item, "sales observation"
            )
            for item in value
        ]

    @staticmethod
    def _positive_int(
        value: Any,
        name: str,
        maximum: int = 365,
    ) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 1 <= value <= maximum
        ):
            raise AgentValidationError(
                f"{name} must be between 1 and {maximum}."
            )

        return value

    def _forecast(
        self,
        history: list[float],
        method: str,
        horizon: int,
        window: int,
        seasonal_period: int,
    ) -> list[float]:
        if method not in self.METHODS:
            raise AgentValidationError(
                "Unsupported forecasting method."
            )

        if method == "moving_average":
            if window > len(history):
                raise AgentValidationError(
                    "Window exceeds available history."
                )

            series = list(history)
            forecasts = []

            for _ in range(horizon):
                prediction = mean(series[-window:])
                prediction = max(0.0, prediction)

                forecasts.append(prediction)
                series.append(prediction)

            return forecasts

        if method == "weighted_average":
            if window > len(history):
                raise AgentValidationError(
                    "Window exceeds available history."
                )

            series = list(history)
            forecasts = []
            weights = list(range(1, window + 1))
            denominator = sum(weights)

            for _ in range(horizon):
                recent = series[-window:]

                prediction = sum(
                    value * weight
                    for value, weight in zip(
                        recent, weights
                    )
                ) / denominator

                prediction = max(0.0, prediction)

                forecasts.append(prediction)
                series.append(prediction)

            return forecasts

        if method == "linear_trend":
            if len(history) < 2:
                raise AgentValidationError(
                    "Linear trend requires at least "
                    "two observations."
                )

            n = len(history)
            x_mean = (n - 1) / 2
            y_mean = mean(history)

            denominator = sum(
                (x - x_mean) ** 2
                for x in range(n)
            )

            slope = sum(
                (x - x_mean) * (y - y_mean)
                for x, y in enumerate(history)
            ) / denominator

            intercept = y_mean - slope * x_mean

            return [
                max(
                    0.0,
                    intercept + slope * (n + step),
                )
                for step in range(horizon)
            ]

        if seasonal_period > len(history):
            raise AgentValidationError(
                "Seasonal period exceeds history length."
            )

        return [
            history[
                -seasonal_period
                + (step % seasonal_period)
            ]
            for step in range(horizon)
        ]

    def _forecast_task(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        product_id = payload.get("product_id")

        if (
            not isinstance(product_id, str)
            or not product_id.strip()
        ):
            raise AgentValidationError(
                "product_id is required."
            )

        history = self._history(
            payload.get("sales_history")
        )

        method = payload.get(
            "method", "moving_average"
        )

        horizon = self._positive_int(
            payload.get("horizon", 7),
            "horizon",
        )

        window = self._positive_int(
            payload.get("window", 3),
            "window",
        )

        seasonal_period = self._positive_int(
            payload.get("seasonal_period", 7),
            "seasonal_period",
        )

        predictions = self._forecast(
            history,
            method,
            horizon,
            window,
            seasonal_period,
        )

        total = sum(predictions)

        return {
            "product_id": product_id,
            "method": method,
            "historical_periods": len(history),
            "forecast_horizon": horizon,
            "forecast_by_period": [
                round(value, 2)
                for value in predictions
            ],
            "total_forecast_units": round(total, 2),
            "average_forecast_per_period": round(
                total / horizon, 2
            ),
            "historical_average": round(
                mean(history), 2
            ),
            "methodology": (
                "Statistical baseline using "
                "historical sales."
            ),
            "limitations": [
                "Sales may underestimate actual demand "
                "during stockouts.",
                "Promotions, holidays and external "
                "factors are not modeled.",
                "Forecast uncertainty intervals "
                "are not calculated.",
            ],
        }

    def _stockout_risk(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        product_id = payload.get("product_id")

        if (
            not isinstance(product_id, str)
            or not product_id.strip()
        ):
            raise AgentValidationError(
                "product_id is required."
            )

        stock = self._nonnegative(
            payload.get("available_stock"),
            "available_stock",
        )

        daily_demand = self._nonnegative(
            payload.get("daily_demand"),
            "daily_demand",
        )

        lead_time = self._positive_int(
            payload.get("lead_time_days"),
            "lead_time_days",
        )

        safety_stock = self._nonnegative(
            payload.get("safety_stock", 0),
            "safety_stock",
        )

        expected_demand = daily_demand * lead_time

        reorder_point = (
            expected_demand + safety_stock
        )

        shortage = max(
            0.0,
            reorder_point - stock,
        )

        if stock < expected_demand:
            risk = "high"
        elif stock < reorder_point:
            risk = "medium"
        else:
            risk = "low"

        days_of_cover = (
            stock / daily_demand
            if daily_demand > 0
            else None
        )

        return {
            "product_id": product_id,
            "available_stock": stock,
            "lead_time_days": lead_time,
            "expected_lead_time_demand": round(
                expected_demand, 2
            ),
            "safety_stock": safety_stock,
            "reorder_point": round(
                reorder_point, 2
            ),
            "stockout_risk": risk,
            "reorder_gap": round(shortage, 2),
            "estimated_days_of_cover": (
                round(days_of_cover, 2)
                if days_of_cover is not None
                else None
            ),
        }

    def _replenishment(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        risk = self._stockout_risk(payload)

        target_cover_days = self._positive_int(
            payload.get("target_cover_days", 14),
            "target_cover_days",
        )

        daily_demand = self._nonnegative(
            payload.get("daily_demand"),
            "daily_demand",
        )

        incoming_stock = self._nonnegative(
            payload.get("incoming_stock", 0),
            "incoming_stock",
        )

        target_stock = (
            daily_demand * target_cover_days
            + risk["safety_stock"]
        )

        quantity = max(
            0,
            math.ceil(
                target_stock
                - risk["available_stock"]
                - incoming_stock
            ),
        )

        return {
            **risk,
            "target_cover_days": target_cover_days,
            "incoming_stock": incoming_stock,
            "target_stock": round(
                target_stock, 2
            ),
            "recommended_order_quantity": quantity,
            "approval_required": True,
            "recommendation_only": True,
        }

    def _evaluate_forecast(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        actual = self._history(
            payload.get("actual")
        )

        predicted = self._history(
            payload.get("predicted")
        )

        if len(actual) != len(predicted):
            raise AgentValidationError(
                "actual and predicted must "
                "have equal lengths."
            )

        errors = [
            actual_value - predicted_value
            for actual_value, predicted_value
            in zip(actual, predicted)
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

        nonzero_actual = [
            (
                abs(error) / actual_value
            )
            for actual_value, error
            in zip(actual, errors)
            if actual_value > 0
        ]

        mape = (
            mean(nonzero_actual) * 100
            if nonzero_actual
            else None
        )

        total_actual = sum(actual)

        wape = (
            sum(abs(error) for error in errors)
            / total_actual * 100
            if total_actual > 0
            else None
        )

        return {
            "observations": len(actual),
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "mape_percent": (
                round(mape, 4)
                if mape is not None
                else None
            ),
            "mape_excluded_zero_actuals": (
                len(actual) - len(nonzero_actual)
            ),
            "wape_percent": (
                round(wape, 4)
                if wape is not None
                else None
            ),
            "forecast_bias": round(
                mean(
                    predicted_value - actual_value
                    for actual_value, predicted_value
                    in zip(actual, predicted)
                ),
                4,
            ),
        }

    def process(
        self,
        request: AgentRequest,
    ) -> dict[str, Any]:
        task = request.task_type
        payload = request.payload

        if task == "forecast_demand":
            return self._forecast_task(payload)

        if task == "analyze_stockout_risk":
            return self._stockout_risk(payload)

        if task == "recommend_replenishment":
            return self._replenishment(payload)

        if task == "evaluate_forecast":
            return self._evaluate_forecast(payload)

        raise AgentValidationError(
            "Unsupported demand agent task."
        )


if __name__ == "__main__":
    from .base_agent import AgentContext

    agent = DemandAgent()

    context = AgentContext(
        tenant_id="retail_company_001",
        user_id="inventory_manager_001",
        workflow_id="WF-DEMAND-001",
        task_id="TASK-001",
    )

    response = agent.execute(
        AgentRequest(
            task_type="forecast_demand",
            context=context,
            payload={
                "product_id": "SKU-1001",
                "sales_history": [
                    80, 85, 90, 100, 95,
                    110, 120, 115, 125, 130,
                ],
                "method": "weighted_average",
                "window": 3,
                "horizon": 7,
            },
        )
    )

    print(response)
