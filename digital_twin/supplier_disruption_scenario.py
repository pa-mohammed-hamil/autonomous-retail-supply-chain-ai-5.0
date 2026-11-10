"""Planned module: supplier disruption scenario. Implementation pending."""

"""
ai/simulation/supplier_disruption_scenario.py

Autonomous Retail Supply Chain AI 5.0

Supplier disruption what-if simulator.

Python 3.10+ | Standard library only.

Assumptions:
- One product and one planning horizon per scenario.
- All available and alternative supply is usable
  within the modeled horizon.
- Disruption and recovery percentages are scenario
  inputs, not AI-predicted probabilities.
- No actual supplier orders are created.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


CENT = Decimal("0.01")


def num(value: Any, name: str) -> Decimal:
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


def pct(value: Any, name: str) -> Decimal:
    result = num(value, name)

    if result > 100:
        raise ValueError(
            f"{name} must be between 0 and 100"
        )

    return result / Decimal("100")


def cash(value: Decimal) -> str:
    return str(
        value.quantize(
            CENT, rounding=ROUND_HALF_UP
        )
    )


class SupplierDisruptionScenario:

    def __init__(self, currency: str = "INR"):
        if not isinstance(currency, str) or not currency.strip():
            raise ValueError("currency is required")

        self.currency = currency.strip().upper()

    def simulate(
        self,
        scenario_id: str,
        supplier_id: str,
        product_id: str,
        planned_supply_units: Any,
        disruption_percent: Any,
        recovery_percent: Any = "0",
        alternative_supply_units: Any = "0",
        current_inventory_units: Any = "0",
        demand_units: Any = "0",
        unit_contribution_margin: Any = "0",
        recoverable_demand_fraction: Any = "0",
        emergency_sourcing_cost: Any = "0",
        delay_penalty: Any = "0",
        other_incremental_cost: Any = "0",
        disruption_duration_days: Any = "0",
    ) -> dict:

        for name, value in (
            ("scenario_id", scenario_id),
            ("supplier_id", supplier_id),
            ("product_id", product_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")

        planned = num(
            planned_supply_units, "planned_supply_units"
        )
        disruption = pct(
            disruption_percent, "disruption_percent"
        )
        recovery = pct(
            recovery_percent, "recovery_percent"
        )

        alternative = num(
            alternative_supply_units,
            "alternative_supply_units",
        )
        inventory = num(
            current_inventory_units,
            "current_inventory_units",
        )
        demand = num(demand_units, "demand_units")

        margin = num(
            unit_contribution_margin,
            "unit_contribution_margin",
        )

        recoverable = num(
            recoverable_demand_fraction,
            "recoverable_demand_fraction",
        )

        if recoverable > 1:
            raise ValueError(
                "recoverable_demand_fraction must be 0 to 1"
            )

        emergency_cost = num(
            emergency_sourcing_cost,
            "emergency_sourcing_cost",
        )
        penalty = num(delay_penalty, "delay_penalty")
        other = num(
            other_incremental_cost,
            "other_incremental_cost",
        )
        duration = num(
            disruption_duration_days,
            "disruption_duration_days",
        )

        disrupted_units = planned * disruption

        recovered_units = (
            disrupted_units * recovery
        )

        effective_supplier_supply = (
            planned - disrupted_units + recovered_units
        )

        total_supply = (
            inventory
            + effective_supplier_supply
            + alternative
        )

        fulfilled = min(demand, total_supply)

        shortage = max(
            Decimal("0"),
            demand - total_supply,
        )

        permanently_lost_units = (
            shortage * (1 - recoverable)
        )

        lost_contribution = (
            permanently_lost_units * margin
        )

        total_impact = (
            lost_contribution
            + emergency_cost
            + penalty
            + other
        )

        fill_rate = (
            fulfilled / demand * 100
            if demand > 0 else Decimal("100")
        )

        if shortage > 0:
            risk_level = "high"
        elif disruption > 0:
            risk_level = "moderate"
        else:
            risk_level = "low"

        return {
            "scenario_id": scenario_id.strip(),
            "supplier_id": supplier_id.strip(),
            "product_id": product_id.strip(),
            "currency": self.currency,
            "disruption_duration_days": str(duration),
            "planned_supply_units": str(planned),
            "disrupted_supply_units": str(
                disrupted_units
            ),
            "recovered_supply_units": str(
                recovered_units
            ),
            "effective_supplier_supply_units": str(
                effective_supplier_supply
            ),
            "alternative_supply_units": str(
                alternative
            ),
            "total_available_supply_units": str(
                total_supply
            ),
            "demand_units": str(demand),
            "fulfilled_units": str(fulfilled),
            "shortage_units": str(shortage),
            "permanently_lost_units": str(
                permanently_lost_units
            ),
            "fill_rate_percent": cash(fill_rate),
            "lost_contribution": cash(
                lost_contribution
            ),
            "emergency_sourcing_cost": cash(
                emergency_cost
            ),
            "delay_penalty": cash(penalty),
            "other_incremental_cost": cash(other),
            "estimated_total_impact": cash(
                total_impact
            ),
            "risk_level": risk_level,
            "simulation_only": True,
            "human_approval_required": True,
        }

    def compare_disruptions(
        self,
        scenarios: list[dict],
    ) -> dict:

        if (
            not isinstance(scenarios, list)
            or not 2 <= len(scenarios) <= 50
        ):
            raise ValueError(
                "Provide 2 to 50 scenarios"
            )

        results = [
            self.simulate(**scenario)
            for scenario in scenarios
        ]

        ids = [
            result["scenario_id"]
            for result in results
        ]

        if len(ids) != len(set(ids)):
            raise ValueError(
                "Scenario IDs must be unique"
            )

        results.sort(
            key=lambda result: (
                Decimal(
                    result["estimated_total_impact"]
                ),
                Decimal(result["shortage_units"]),
            )
        )

        return {
            "currency": self.currency,
            "scenario_count": len(results),
            "ranked_scenarios": results,
            "lowest_estimated_impact_scenario": (
                results[0]["scenario_id"]
            ),
            "recommendation_only": True,
        }
