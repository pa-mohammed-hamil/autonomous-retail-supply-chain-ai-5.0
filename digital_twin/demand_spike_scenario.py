"""Planned module: demand spike scenario. Implementation pending."""

"""
File: ai/simulation/demand_spike_scenario.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+ | Standard library only

Features:
- Demand spike simulation
- Forecast demand increase
- Available stock evaluation
- Stockout risk
- Fulfillment rate
- Safety stock requirements
- Replenishment recommendation
- Estimated lost contribution

Deterministic what-if analysis only.
"""

from __future__ import annotations

from decimal import (
    Decimal,
    InvalidOperation,
    ROUND_CEILING,
)
from typing import Any


def nonnegative(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(
        value, (str, int, Decimal)
    ):
        raise ValueError(f"Invalid {name}")

    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid {name}") from exc

    if not result.is_finite() or result < 0:
        raise ValueError(f"Invalid {name}")

    return result


def ceil_units(value: Decimal) -> int:
    return int(
        value.to_integral_value(
            rounding=ROUND_CEILING
        )
    )


class DemandSpikeScenario:

    def __init__(self, currency: str = "INR"):
        if not isinstance(currency, str) or not currency.strip():
            raise ValueError("currency is required")

        self.currency = currency.strip().upper()

    def simulate(
        self,
        product_id: str,
        baseline_daily_demand: Any,
        spike_percent: Any,
        spike_duration_days: Any,
        available_stock: Any,
        incoming_stock: Any = "0",
        safety_stock: Any = "0",
        selling_price_per_unit: Any = "0",
        variable_cost_per_unit: Any = "0",
        recoverable_fraction: Any = "0",
    ) -> dict:

        if (
            not isinstance(product_id, str)
            or not product_id.strip()
        ):
            raise ValueError("product_id is required")

        baseline = nonnegative(
            baseline_daily_demand,
            "baseline_daily_demand",
        )

        spike = nonnegative(
            spike_percent, "spike_percent"
        )

        days = nonnegative(
            spike_duration_days,
            "spike_duration_days",
        )

        if days <= 0:
            raise ValueError(
                "spike_duration_days must be positive"
            )

        stock = nonnegative(
            available_stock, "available_stock"
        )

        incoming = nonnegative(
            incoming_stock, "incoming_stock"
        )

        safety = nonnegative(
            safety_stock, "safety_stock"
        )

        price = nonnegative(
            selling_price_per_unit,
            "selling_price_per_unit",
        )

        variable_cost = nonnegative(
            variable_cost_per_unit,
            "variable_cost_per_unit",
        )

        recoverable = nonnegative(
            recoverable_fraction,
            "recoverable_fraction",
        )

        if recoverable > 1:
            raise ValueError(
                "recoverable_fraction must be 0 to 1"
            )

        demand_multiplier = (
            Decimal("1") + spike / Decimal("100")
        )

        projected_daily_demand = (
            baseline * demand_multiplier
        )

        total_projected_demand = ceil_units(
            projected_daily_demand * days
        )

        baseline_period_demand = ceil_units(
            baseline * days
        )

        total_available = stock + incoming

        fulfillable_units = min(
            Decimal(total_projected_demand),
            total_available,
        )

        shortage_units = max(
            Decimal("0"),
            Decimal(total_projected_demand)
            - total_available,
        )

        # Stock needed to satisfy forecast demand
        # and retain the target safety stock.
        recommended_replenishment = ceil_units(
            max(
                Decimal("0"),
                Decimal(total_projected_demand)
                + safety
                - total_available,
            )
        )

        fulfillment_rate = (
            fulfillable_units
            / Decimal(total_projected_demand)
            * 100
            if total_projected_demand > 0
            else Decimal("100")
        )

        permanently_lost_units = (
            shortage_units * (1 - recoverable)
        )

        contribution_margin = (
            price - variable_cost
        )

        estimated_lost_contribution = (
            permanently_lost_units
            * contribution_margin
        )

        return {
            "product_id": product_id.strip(),
            "currency": self.currency,
            "baseline_daily_demand": str(baseline),
            "spike_percent": str(spike),
            "spike_duration_days": str(days),
            "projected_daily_demand": str(
                projected_daily_demand
            ),
            "baseline_period_demand_units": (
                baseline_period_demand
            ),
            "projected_demand_units": (
                total_projected_demand
            ),
            "additional_demand_units": (
                total_projected_demand
                - baseline_period_demand
            ),
            "available_stock_units": str(stock),
            "incoming_stock_units": str(incoming),
            "total_supply_units": str(
                total_available
            ),
            "fulfillable_units": str(
                fulfillable_units
            ),
            "shortage_units": str(shortage_units),
            "stockout_expected": shortage_units > 0,
            "fulfillment_rate_percent": round(
                float(fulfillment_rate), 2
            ),
            "recommended_replenishment_units": (
                recommended_replenishment
            ),
            "estimated_lost_contribution": str(
                estimated_lost_contribution.quantize(
                    Decimal("0.01")
                )
            ),
            "simulation_only": True,
            "approval_required_for_orders": True,
        }

    def compare_spikes(
        self,
        base_inputs: dict,
        spike_percentages: list[Any],
    ) -> dict:

        if not isinstance(base_inputs, dict):
            raise ValueError(
                "base_inputs must be a dictionary"
            )

        if (
            not isinstance(spike_percentages, list)
            or not 1 <= len(spike_percentages) <= 50
        ):
            raise ValueError(
                "Provide 1 to 50 spike percentages"
            )

        results = []

        for percentage in spike_percentages:
            scenario = dict(base_inputs)
            scenario["spike_percent"] = percentage

            results.append(
                self.simulate(**scenario)
            )

        return {
            "currency": self.currency,
            "scenario_count": len(results),
            "scenarios": results,
            "worst_shortage_scenario": max(
                results,
                key=lambda result: Decimal(
                    result["shortage_units"]
                ),
            ),
        }
