
"""
ai/optimization/safety_stock_optimizer.py

Safety Stock Optimizer 2.0

Statistical inventory planning for retail.

Assumptions:
- Daily demand is independent and approximately normal.
- Demand and lead-time variation are independent.
- Lead-time demand uses a normal approximation.
- Cycle service level is not the same as fill rate.
- Financial estimates are scenario approximations.

No automatic inventory or procurement changes.
"""

from __future__ import annotations

import math

from dataclasses import dataclass
from statistics import NormalDist


@dataclass(frozen=True)
class SafetyStockInput:
    sku: str
    average_daily_demand: float
    daily_demand_std: float
    average_lead_time_days: float
    lead_time_std_days: float = 0.0
    service_level: float = 0.95
    unit_cost: float = 0.0
    annual_holding_cost_per_unit: float = 0.0
    shortage_cost_per_unit: float = 0.0
    replenishment_cycles_per_year: float = 12.0

    def __post_init__(self):
        if not self.sku.strip():
            raise ValueError("SKU is required")

        fields = (
            "average_daily_demand",
            "daily_demand_std",
            "average_lead_time_days",
            "lead_time_std_days",
            "unit_cost",
            "annual_holding_cost_per_unit",
            "shortage_cost_per_unit",
        )

        for name in fields:
            value = getattr(self, name)

            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(
                    f"{name} must be finite and nonnegative"
                )

        if (
            not math.isfinite(self.service_level)
            or not 0 < self.service_level < 1
        ):
            raise ValueError("Invalid service level")

        if (
            not math.isfinite(
                self.replenishment_cycles_per_year
            )
            or self.replenishment_cycles_per_year <= 0
        ):
            raise ValueError(
                "Invalid replenishment cycle count"
            )


class SafetyStockOptimizer:

    @staticmethod
    def lead_time_demand_std(
        item: SafetyStockInput,
    ) -> float:
        variance = (
            item.average_lead_time_days
            * item.daily_demand_std**2
            + item.average_daily_demand**2
            * item.lead_time_std_days**2
        )

        return math.sqrt(variance)

    def calculate(
        self,
        item: SafetyStockInput,
        service_level: float | None = None,
    ) -> dict:

        level = (
            item.service_level
            if service_level is None
            else service_level
        )

        if (
            isinstance(level, bool)
            or not isinstance(level, (int, float))
            or not math.isfinite(level)
            or not 0 < level < 1
        ):
            raise ValueError(
                "Service level must be between 0 and 1"
            )

        z_score = NormalDist().inv_cdf(level)

        mean_lead_time_demand = (
            item.average_daily_demand
            * item.average_lead_time_days
        )

        std = self.lead_time_demand_std(item)

        # Round the full reorder point to avoid
        # unnecessary rounding differences.
        raw_safety_stock = max(
            0.0,
            z_score * std,
        )

        safety_stock = math.ceil(
            raw_safety_stock
        )

        reorder_point = math.ceil(
            mean_lead_time_demand
            + raw_safety_stock
        )

        if std > 0:
            expected_shortage_per_cycle = (
                std
                * (
                    NormalDist().pdf(z_score)
                    - z_score
                    * (1 - level)
                )
            )
        else:
            expected_shortage_per_cycle = 0.0

        annual_holding_cost = (
            safety_stock
            * item.annual_holding_cost_per_unit
        )

        annual_shortage_cost = (
            expected_shortage_per_cycle
            * item.replenishment_cycles_per_year
            * item.shortage_cost_per_unit
        )

        total_annual_cost = (
            annual_holding_cost
            + annual_shortage_cost
        )

        return {
            "sku": item.sku,
            "service_level": level,
            "z_score": round(z_score, 4),
            "mean_lead_time_demand": round(
                mean_lead_time_demand, 2
            ),
            "lead_time_demand_std": round(
                std, 2
            ),
            "safety_stock_units": safety_stock,
            "reorder_point_units": reorder_point,
            "safety_stock_value": round(
                safety_stock * item.unit_cost, 2
            ),
            "annual_holding_cost": round(
                annual_holding_cost, 2
            ),
            "expected_shortage_units_per_cycle": round(
                expected_shortage_per_cycle, 4
            ),
            "annual_shortage_cost": round(
                annual_shortage_cost, 2
            ),
            "estimated_total_annual_cost": round(
                total_annual_cost, 2
            ),
            "recommendation_only": True,
            "requires_approval": True,
        }

    def optimize_service_level(
        self,
        item: SafetyStockInput,
        candidate_levels: list[float] | None = None,
        minimum_service_level: float = 0.90,
    ) -> dict:

        if not 0 < minimum_service_level < 1:
            raise ValueError(
                "Invalid minimum service level"
            )

        levels = candidate_levels or [
            0.90,
            0.95,
            0.975,
            0.99,
        ]

        results = []

        for level in levels:
            if level < minimum_service_level:
                continue

            results.append(
                self.calculate(
                    item,
                    service_level=level,
                )
            )

        if not results:
            raise ValueError(
                "No candidate meets minimum service level"
            )

        best = min(
            results,
            key=lambda row: (
                row["estimated_total_annual_cost"],
                -row["service_level"],
            ),
        )

        return {
            "sku": item.sku,
            "recommended_service_level": (
                best["service_level"]
            ),
            "recommended_safety_stock_units": (
                best["safety_stock_units"]
            ),
            "recommended_reorder_point_units": (
                best["reorder_point_units"]
            ),
            "estimated_annual_cost": (
                best["estimated_total_annual_cost"]
            ),
            "alternatives": results,
            "requires_approval": True,
        }

    def optimize_portfolio(
        self,
        items: list[SafetyStockInput],
    ) -> dict:

        seen = set()
        recommendations = []

        for item in items:
            if item.sku in seen:
                raise ValueError(
                    f"Duplicate SKU: {item.sku}"
                )

            seen.add(item.sku)

            recommendations.append(
                self.optimize_service_level(item)
            )

        return {
            "total_skus": len(items),
            "recommendations": recommendations,
            "recommendation_only": True,
            "requires_approval": True,
        }
