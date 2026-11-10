"""Planned module: planning metrics. Implementation pending."""

"""
File: ai/observability/planning_metrics.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+ | Standard library only

Capabilities:
- Forecast accuracy: MAE, RMSE, WAPE, bias
- Stockout and service-level metrics
- Inventory days of cover
- Replenishment quantity evaluation
- Supply plan feasibility
- Tenant-scoped planning evaluation history

All metrics depend on caller-supplied data.
"""

from __future__ import annotations

import math
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class PlanningEvaluation:
    evaluation_id: str
    tenant_id: str
    product_id: str
    metric_type: str
    result: dict
    timestamp: str


class PlanningMetrics:

    def __init__(self, max_records: int = 10000):
        if (
            isinstance(max_records, bool)
            or not isinstance(max_records, int)
            or max_records < 1
        ):
            raise ValueError(
                "max_records must be positive"
            )

        self.max_records = max_records
        self._records: list[PlanningEvaluation] = []
        self._lock = threading.RLock()

    @staticmethod
    def _number(
        value: Any,
        name: str,
    ) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(
                f"{name} must be finite and nonnegative"
            )

        return float(value)

    @staticmethod
    def _text(value: Any, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} is required")
        return value.strip()

    def _save(
        self,
        tenant_id: str,
        product_id: str,
        metric_type: str,
        result: dict,
    ) -> dict:

        record = PlanningEvaluation(
            evaluation_id=str(uuid4()),
            tenant_id=tenant_id,
            product_id=product_id,
            metric_type=metric_type,
            result=result,
            timestamp=datetime.now(
                timezone.utc
            ).isoformat(),
        )

        with self._lock:
            self._records.append(record)

            overflow = (
                len(self._records) - self.max_records
            )

            if overflow > 0:
                del self._records[:overflow]

        return asdict(record)

    def evaluate_forecast(
        self,
        tenant_id: str,
        product_id: str,
        actual: list[float],
        predicted: list[float],
    ) -> dict:

        tenant_id = self._text(
            tenant_id, "tenant_id"
        )
        product_id = self._text(
            product_id, "product_id"
        )

        if (
            not isinstance(actual, list)
            or not isinstance(predicted, list)
            or not actual
            or len(actual) != len(predicted)
            or len(actual) > 10000
        ):
            raise ValueError(
                "Actual and predicted arrays must "
                "have equal nonzero length <= 10000"
            )

        actual_values = [
            self._number(value, "actual")
            for value in actual
        ]

        predicted_values = [
            self._number(value, "predicted")
            for value in predicted
        ]

        errors = [
            p - a
            for a, p in zip(
                actual_values,
                predicted_values,
            )
        ]

        absolute_errors = [
            abs(error) for error in errors
        ]

        n = len(errors)

        mae = sum(absolute_errors) / n

        rmse = math.sqrt(
            sum(error ** 2 for error in errors) / n
        )

        actual_total = sum(actual_values)

        wape = (
            sum(absolute_errors)
            / actual_total * 100
            if actual_total > 0
            else None
        )

        bias = sum(errors) / n

        result = {
            "sample_count": n,
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "wape_percent": (
                round(wape, 2)
                if wape is not None else None
            ),
            "mean_forecast_bias": round(
                bias, 4
            ),
            "bias_definition": (
                "predicted_minus_actual"
            ),
        }

        return self._save(
            tenant_id,
            product_id,
            "forecast_accuracy",
            result,
        )

    def evaluate_inventory(
        self,
        tenant_id: str,
        product_id: str,
        available_stock: float,
        daily_demand: float,
        demand_units: float,
        fulfilled_units: float,
        stockout_days: int,
        observed_days: int,
    ) -> dict:

        stock = self._number(
            available_stock, "available_stock"
        )
        daily = self._number(
            daily_demand, "daily_demand"
        )
        demand = self._number(
            demand_units, "demand_units"
        )
        fulfilled = self._number(
            fulfilled_units, "fulfilled_units"
        )

        if fulfilled > demand:
            raise ValueError(
                "Fulfilled units cannot exceed demand"
            )

        if (
            isinstance(stockout_days, bool)
            or isinstance(observed_days, bool)
            or not isinstance(stockout_days, int)
            or not isinstance(observed_days, int)
            or observed_days <= 0
            or not 0 <= stockout_days <= observed_days
        ):
            raise ValueError(
                "Invalid observation period"
            )

        days_cover = (
            stock / daily
            if daily > 0 else None
        )

        fill_rate = (
            fulfilled / demand * 100
            if demand > 0 else None
        )

        stockout_rate = (
            stockout_days / observed_days * 100
        )

        result = {
            "available_stock": stock,
            "daily_demand": daily,
            "inventory_days_of_cover": (
                round(days_cover, 2)
                if days_cover is not None else None
            ),
            "demand_units": demand,
            "fulfilled_units": fulfilled,
            "unfulfilled_units": demand - fulfilled,
            "unit_fill_rate_percent": (
                round(fill_rate, 2)
                if fill_rate is not None else None
            ),
            "stockout_day_rate_percent": round(
                stockout_rate, 2
            ),
            "observed_days": observed_days,
        }

        return self._save(
            tenant_id,
            product_id,
            "inventory_performance",
            result,
        )

    def evaluate_replenishment(
        self,
        tenant_id: str,
        product_id: str,
        recommended_quantity: float,
        ordered_quantity: float,
        received_quantity: float,
        target_stock: float,
        ending_stock: float,
    ) -> dict:

        recommended = self._number(
            recommended_quantity,
            "recommended_quantity",
        )
        ordered = self._number(
            ordered_quantity,
            "ordered_quantity",
        )
        received = self._number(
            received_quantity,
            "received_quantity",
        )
        target = self._number(
            target_stock, "target_stock"
        )
        ending = self._number(
            ending_stock, "ending_stock"
        )

        if received > ordered:
            raise ValueError(
                "Received quantity exceeds ordered quantity"
            )

        deviation = ordered - recommended

        receipt_rate = (
            received / ordered * 100
            if ordered > 0 else None
        )

        result = {
            "recommended_quantity": recommended,
            "ordered_quantity": ordered,
            "received_quantity": received,
            "order_deviation_units": deviation,
            "order_deviation_absolute_units": abs(
                deviation
            ),
            "receipt_completion_percent": (
                round(receipt_rate, 2)
                if receipt_rate is not None else None
            ),
            "target_stock": target,
            "ending_stock": ending,
            "target_stock_gap_units": round(
                target - ending, 2
            ),
            "target_met": ending >= target,
        }

        return self._save(
            tenant_id,
            product_id,
            "replenishment_performance",
            result,
        )

    def evaluate_plan_feasibility(
        self,
        tenant_id: str,
        product_id: str,
        proposed_order_quantity: float,
        free_warehouse_capacity: float,
        unit_cost: float,
        available_budget: float,
    ) -> dict:

        quantity = self._number(
            proposed_order_quantity,
            "proposed_order_quantity",
        )
        capacity = self._number(
            free_warehouse_capacity,
            "free_warehouse_capacity",
        )
        cost = self._number(
            unit_cost, "unit_cost"
        )
        budget = self._number(
            available_budget, "available_budget"
        )

        estimated_cost = quantity * cost

        capacity_ok = quantity <= capacity
        budget_ok = estimated_cost <= budget

        result = {
            "proposed_order_quantity": quantity,
            "estimated_cost": round(
                estimated_cost, 2
            ),
            "available_budget": budget,
            "warehouse_capacity_sufficient": (
                capacity_ok
            ),
            "budget_sufficient": budget_ok,
            "feasible_under_checked_constraints": (
                capacity_ok and budget_ok
            ),
            "approval_required": quantity > 0,
            "limitations": (
                "Supplier availability, lead time, "
                "expiry, delivery costs and other "
                "constraints are not evaluated."
            ),
        }

        return self._save(
            tenant_id,
            product_id,
            "plan_feasibility",
            result,
        )

    def history(
        self,
        tenant_id: str,
        product_id: str | None = None,
        limit: int = 50,
    ) -> dict:

        tenant_id = self._text(
            tenant_id, "tenant_id"
        )

        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise ValueError("limit must be 1 to 100")

        with self._lock:
            records = [
                asdict(record)
                for record in self._records
                if record.tenant_id == tenant_id
                and (
                    product_id is None
                    or record.product_id == product_id
                )
            ]

        return {
            "tenant_id": tenant_id,
            "product_id": product_id,
            "total_records": len(records),
            "records": records[-limit:],
        }
