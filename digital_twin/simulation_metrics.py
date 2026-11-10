"""Planned module: simulation metrics. Implementation pending."""

"""
ai/simulation/simulation_metrics.py

Autonomous Retail Supply Chain AI 5.0

Simulation KPI and performance evaluation.

Python 3.10+ | Standard library only.

Metrics:
- Inventory fill rate
- Stockout rate
- Delivery on-time rate
- Total cost
- Cost per fulfilled unit
- Lost contribution
- Cost savings
- Simulation execution success rate
- Latency percentiles
"""

from __future__ import annotations

from decimal import (
    Decimal,
    InvalidOperation,
    ROUND_HALF_UP,
)
from typing import Any
import math


CENT = Decimal("0.01")


def dec(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(
        value, (str, int, Decimal)
    ):
        raise ValueError(
            f"{name} must be an integer or decimal string"
        )

    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid {name}") from exc

    if not result.is_finite() or result < 0:
        raise ValueError(f"Invalid {name}")

    return result


def fmt(value: Decimal) -> str:
    return str(
        value.quantize(
            CENT, rounding=ROUND_HALF_UP
        )
    )


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    lower = math.floor(position)
    upper = math.ceil(position)

    if lower == upper:
        return ordered[lower]

    fraction = position - lower

    return (
        ordered[lower] * (1 - fraction)
        + ordered[upper] * fraction
    )


class SimulationMetrics:

    def __init__(self, currency: str = "INR"):
        if (
            not isinstance(currency, str)
            or not currency.strip()
        ):
            raise ValueError("currency required")

        self.currency = currency.strip().upper()

    def evaluate_inventory(
        self,
        demand_units: Any,
        fulfilled_units: Any,
        stockout_days: Any,
        simulated_days: Any,
        holding_cost: Any = "0",
        lost_contribution: Any = "0",
    ) -> dict:

        demand = dec(demand_units, "demand_units")
        fulfilled = dec(
            fulfilled_units, "fulfilled_units"
        )
        stockouts = dec(
            stockout_days, "stockout_days"
        )
        days = dec(
            simulated_days, "simulated_days"
        )
        holding = dec(
            holding_cost, "holding_cost"
        )
        lost = dec(
            lost_contribution, "lost_contribution"
        )

        if fulfilled > demand:
            raise ValueError(
                "Fulfilled units exceed demand"
            )

        if stockouts > days:
            raise ValueError(
                "Stockout days exceed simulated days"
            )

        fill_rate = (
            fulfilled / demand * 100
            if demand > 0 else Decimal("100")
        )

        stockout_rate = (
            stockouts / days * 100
            if days > 0 else None
        )

        return {
            "currency": self.currency,
            "demand_units": str(demand),
            "fulfilled_units": str(fulfilled),
            "unfulfilled_units": str(
                demand - fulfilled
            ),
            "fill_rate_percent": fmt(fill_rate),
            "stockout_day_rate_percent": (
                fmt(stockout_rate)
                if stockout_rate is not None
                else None
            ),
            "holding_cost": fmt(holding),
            "lost_contribution": fmt(lost),
        }

    def evaluate_delivery(
        self,
        total_deliveries: Any,
        on_time_deliveries: Any,
        total_transport_cost: Any = "0",
    ) -> dict:

        total = dec(
            total_deliveries,
            "total_deliveries",
        )
        on_time = dec(
            on_time_deliveries,
            "on_time_deliveries",
        )
        cost = dec(
            total_transport_cost,
            "total_transport_cost",
        )

        if on_time > total:
            raise ValueError(
                "On-time deliveries exceed total"
            )

        rate = (
            on_time / total * 100
            if total > 0 else None
        )

        return {
            "currency": self.currency,
            "total_deliveries": str(total),
            "on_time_deliveries": str(on_time),
            "late_deliveries": str(
                total - on_time
            ),
            "on_time_rate_percent": (
                fmt(rate) if rate is not None else None
            ),
            "transport_cost": fmt(cost),
            "average_cost_per_delivery": (
                fmt(cost / total)
                if total > 0 else None
            ),
        }

    def evaluate_financials(
        self,
        procurement_cost: Any = "0",
        transport_cost: Any = "0",
        warehouse_cost: Any = "0",
        holding_cost: Any = "0",
        shortage_cost: Any = "0",
        other_cost: Any = "0",
        fulfilled_units: Any = "0",
    ) -> dict:

        components = {
            "procurement": procurement_cost,
            "transport": transport_cost,
            "warehouse": warehouse_cost,
            "holding": holding_cost,
            "shortage": shortage_cost,
            "other": other_cost,
        }

        values = {
            key: dec(value, key)
            for key, value in components.items()
        }

        fulfilled = dec(
            fulfilled_units, "fulfilled_units"
        )

        total = sum(
            values.values(), Decimal("0")
        )

        return {
            "currency": self.currency,
            "cost_breakdown": {
                key: fmt(value)
                for key, value in values.items()
            },
            "total_cost": fmt(total),
            "fulfilled_units": str(fulfilled),
            "cost_per_fulfilled_unit": (
                fmt(total / fulfilled)
                if fulfilled > 0 else None
            ),
        }

    def compare_baseline(
        self,
        baseline_cost: Any,
        optimized_cost: Any,
        baseline_service_level: Any,
        optimized_service_level: Any,
    ) -> dict:

        baseline = dec(
            baseline_cost, "baseline_cost"
        )
        optimized = dec(
            optimized_cost, "optimized_cost"
        )

        base_service = dec(
            baseline_service_level,
            "baseline_service_level",
        )
        new_service = dec(
            optimized_service_level,
            "optimized_service_level",
        )

        if base_service > 100 or new_service > 100:
            raise ValueError(
                "Service levels must be <= 100%"
            )

        savings = baseline - optimized

        savings_percent = (
            savings / baseline * 100
            if baseline > 0 else None
        )

        return {
            "currency": self.currency,
            "baseline_cost": fmt(baseline),
            "optimized_cost": fmt(optimized),
            "cost_savings": fmt(savings),
            "savings_percent": (
                fmt(savings_percent)
                if savings_percent is not None
                else None
            ),
            "baseline_service_level_percent": (
                fmt(base_service)
            ),
            "optimized_service_level_percent": (
                fmt(new_service)
            ),
            "service_level_change_percentage_points": (
                fmt(new_service - base_service)
            ),
            "cost_reduction": savings > 0,
            "simulation_only": True,
        }

    def evaluate_engine(
        self,
        runs: list[dict],
    ) -> dict:

        if not isinstance(runs, list):
            raise ValueError("runs must be a list")

        if not runs:
            return {
                "total_runs": 0,
                "completed": 0,
                "failed": 0,
                "success_rate_percent": None,
                "latency_ms": None,
            }

        completed = sum(
            run.get("status") == "completed"
            for run in runs
        )

        failed = sum(
            run.get("status") == "failed"
            for run in runs
        )

        durations = []

        for run in runs:
            duration = run.get("duration_ms")

            if (
                isinstance(duration, bool)
                or not isinstance(
                    duration, (int, float)
                )
                or not math.isfinite(duration)
                or duration < 0
            ):
                raise ValueError(
                    "Invalid duration_ms"
                )

            durations.append(float(duration))

        return {
            "total_runs": len(runs),
            "completed": completed,
            "failed": failed,
            "success_rate_percent": round(
                completed / len(runs) * 100, 2
            ),
            "latency_ms": {
                "average": round(
                    sum(durations) / len(durations), 3
                ),
                "p50": round(
                    percentile(durations, 0.50), 3
                ),
                "p95": round(
                    percentile(durations, 0.95), 3
                ),
                "p99": round(
                    percentile(durations, 0.99), 3
                ),
                "maximum": round(
                    max(durations), 3
                ),
            },
        }
