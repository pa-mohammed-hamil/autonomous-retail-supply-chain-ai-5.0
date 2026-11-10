"""Planned module: objective metrics. Implementation pending."""

"""
ai/optimization/objective_metrics.py

Objective metrics for supply chain optimization.

Features:
- Cost savings and improvement percentage
- Constraint violation reporting
- Resource utilization
- Order service level
- Optimization runtime
- Weighted objective scoring
- Feasibility-first candidate comparison

Scores are normalized against explicitly
supplied reference values.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict


def nonnegative(name: str, value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{name} must be finite and >= 0")
    return float(value)


@dataclass(frozen=True)
class OptimizationMetricsInput:
    solution_id: str
    total_cost: float
    distance_km: float
    runtime_seconds: float
    fulfilled_orders: int
    total_orders: int
    used_capacity: float
    available_capacity: float
    constraint_violations: int = 0

    def __post_init__(self):
        if not self.solution_id:
            raise ValueError("Solution ID required")

        for name in (
            "total_cost",
            "distance_km",
            "runtime_seconds",
            "used_capacity",
            "available_capacity",
        ):
            nonnegative(name, getattr(self, name))

        for name in (
            "fulfilled_orders",
            "total_orders",
            "constraint_violations",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ValueError(f"Invalid {name}")

        if self.fulfilled_orders > self.total_orders:
            raise ValueError(
                "Fulfilled orders exceed total orders"
            )

        if self.used_capacity > self.available_capacity:
            raise ValueError(
                "Used capacity exceeds available capacity"
            )

        if (
            self.available_capacity == 0
            and self.used_capacity > 0
        ):
            raise ValueError("No available capacity")


class ObjectiveMetrics:

    @staticmethod
    def calculate(
        data: OptimizationMetricsInput,
    ) -> dict:

        utilization = (
            data.used_capacity / data.available_capacity
            if data.available_capacity > 0
            else 0.0
        )

        service_level = (
            data.fulfilled_orders / data.total_orders
            if data.total_orders > 0
            else 1.0
        )

        return {
            **asdict(data),
            "capacity_utilization": round(
                utilization, 4
            ),
            "order_service_level": round(
                service_level, 4
            ),
            "feasible": (
                data.constraint_violations == 0
            ),
        }

    @staticmethod
    def compare(
        baseline: OptimizationMetricsInput,
        candidate: OptimizationMetricsInput,
    ) -> dict:

        baseline_result = ObjectiveMetrics.calculate(
            baseline
        )
        candidate_result = ObjectiveMetrics.calculate(
            candidate
        )

        savings = (
            baseline.total_cost - candidate.total_cost
        )

        cost_improvement_pct = (
            savings / baseline.total_cost * 100
            if baseline.total_cost > 0
            else None
        )

        distance_reduction = (
            baseline.distance_km - candidate.distance_km
        )

        distance_improvement_pct = (
            distance_reduction
            / baseline.distance_km * 100
            if baseline.distance_km > 0
            else None
        )

        return {
            "baseline_id": baseline.solution_id,
            "candidate_id": candidate.solution_id,
            "cost_savings": round(savings, 2),
            "cost_improvement_percent": (
                round(cost_improvement_pct, 2)
                if cost_improvement_pct is not None
                else None
            ),
            "distance_reduction_km": round(
                distance_reduction, 2
            ),
            "distance_improvement_percent": (
                round(distance_improvement_pct, 2)
                if distance_improvement_pct is not None
                else None
            ),
            "service_level_change": round(
                candidate_result["order_service_level"]
                - baseline_result["order_service_level"],
                4,
            ),
            "candidate_feasible": (
                candidate_result["feasible"]
            ),
            "baseline": baseline_result,
            "candidate": candidate_result,
        }

    @staticmethod
    def weighted_score(
        data: OptimizationMetricsInput,
        reference_cost: float,
        reference_distance: float,
        weights: dict[str, float] | None = None,
    ) -> dict:

        reference_cost = nonnegative(
            "reference_cost", reference_cost
        )
        reference_distance = nonnegative(
            "reference_distance", reference_distance
        )

        if reference_cost == 0 or reference_distance == 0:
            raise ValueError(
                "Reference values must be positive"
            )

        weights = weights or {
            "cost": 0.40,
            "distance": 0.25,
            "service": 0.25,
            "utilization": 0.10,
        }

        expected = {
            "cost",
            "distance",
            "service",
            "utilization",
        }

        if set(weights) != expected:
            raise ValueError("Invalid weight keys")

        for value in weights.values():
            nonnegative("weight", value)

        if not math.isclose(
            sum(weights.values()), 1.0,
            abs_tol=1e-9,
        ):
            raise ValueError("Weights must sum to 1")

        metrics = ObjectiveMetrics.calculate(data)

        # Lower cost and distance produce higher scores.
        cost_score = max(
            0.0,
            1 - data.total_cost / reference_cost,
        )

        distance_score = max(
            0.0,
            1 - data.distance_km / reference_distance,
        )

        score = (
            weights["cost"] * cost_score
            + weights["distance"] * distance_score
            + weights["service"]
            * metrics["order_service_level"]
            + weights["utilization"]
            * metrics["capacity_utilization"]
        )

        return {
            "solution_id": data.solution_id,
            "weighted_score": round(score, 4),
            "feasible": metrics["feasible"],
            "score_interpretation": (
                "Heuristic score; higher is better"
            ),
        }
    