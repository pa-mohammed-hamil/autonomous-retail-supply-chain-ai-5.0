"""Planned module: stockout scenario. Implementation pending."""

"""
ai/simulation/stockout_scenario.py

Autonomous Retail Supply Chain AI 5.0

Stockout what-if analysis.
Python 3.10+ | Standard library only.
"""

from __future__ import annotations

from decimal import (
    Decimal,
    InvalidOperation,
    ROUND_HALF_UP,
)
from typing import Any


CENT = Decimal("0.01")


def nonnegative(value: Any, name: str) -> Decimal:
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
        raise ValueError(f"{name} must be nonnegative")

    return result


def money(value: Decimal) -> str:
    return str(
        value.quantize(
            CENT, rounding=ROUND_HALF_UP
        )
    )


class StockoutScenario:

    def __init__(self, currency: str = "INR"):
        if not isinstance(currency, str) or not currency.strip():
            raise ValueError("currency is required")

        self.currency = currency.strip().upper()

    def simulate(
        self,
        product_id: str,
        expected_demand_units: Any,
        available_stock_units: Any,
        incoming_stock_units: Any = "0",
        emergency_stock_units: Any = "0",
        selling_price_per_unit: Any = "0",
        variable_cost_per_unit: Any = "0",
        backorder_fraction: Any = "0",
        recoverable_fraction: Any = "0",
        emergency_replenishment_cost: Any = "0",
        backorder_cost_per_unit: Any = "0",
        customer_penalties: Any = "0",
        safety_stock_units: Any = "0",
    ) -> dict:

        if not isinstance(product_id, str) or not product_id.strip():
            raise ValueError("product_id is required")

        demand = nonnegative(
            expected_demand_units,
            "expected_demand_units",
        )
        stock = nonnegative(
            available_stock_units,
            "available_stock_units",
        )
        incoming = nonnegative(
            incoming_stock_units,
            "incoming_stock_units",
        )
        emergency = nonnegative(
            emergency_stock_units,
            "emergency_stock_units",
        )

        price = nonnegative(
            selling_price_per_unit,
            "selling_price_per_unit",
        )
        variable = nonnegative(
            variable_cost_per_unit,
            "variable_cost_per_unit",
        )

        if variable > price:
            raise ValueError(
                "Variable cost exceeds selling price; "
                "negative margins require a separate model"
            )

        backorder_fraction = nonnegative(
            backorder_fraction,
            "backorder_fraction",
        )
        recoverable_fraction = nonnegative(
            recoverable_fraction,
            "recoverable_fraction",
        )

        if backorder_fraction > 1:
            raise ValueError(
                "backorder_fraction must be 0 to 1"
            )

        if recoverable_fraction > 1:
            raise ValueError(
                "recoverable_fraction must be 0 to 1"
            )

        emergency_cost = nonnegative(
            emergency_replenishment_cost,
            "emergency_replenishment_cost",
        )
        backorder_unit_cost = nonnegative(
            backorder_cost_per_unit,
            "backorder_cost_per_unit",
        )
        penalties = nonnegative(
            customer_penalties,
            "customer_penalties",
        )
        safety = nonnegative(
            safety_stock_units,
            "safety_stock_units",
        )

        # Incoming and emergency quantities are assumed
        # available before the modeled demand occurs.
        supply = stock + incoming + emergency

        fulfilled = min(demand, supply)
        shortage = max(
            Decimal("0"), demand - supply
        )

        backordered = (
            shortage * backorder_fraction
        )

        remaining_shortage = (
            shortage - backordered
        )

        permanently_lost = (
            remaining_shortage
            * (1 - recoverable_fraction)
        )

        deferred_recoverable = (
            remaining_shortage * recoverable_fraction
        )

        margin = price - variable

        lost_revenue = permanently_lost * price
        lost_contribution = (
            permanently_lost * margin
        )

        backorder_cost = (
            backordered * backorder_unit_cost
        )

        economic_loss = (
            lost_contribution
            + backorder_cost
            + emergency_cost
            + penalties
        )

        fill_rate = (
            fulfilled / demand * 100
            if demand > 0 else Decimal("100")
        )

        shortage_rate = (
            shortage / demand * 100
            if demand > 0 else Decimal("0")
        )

        replenishment_required = max(
            Decimal("0"),
            demand + safety - supply,
        )

        return {
            "product_id": product_id.strip(),
            "currency": self.currency,
            "expected_demand_units": str(demand),
            "available_supply_units": str(supply),
            "fulfilled_units": str(fulfilled),
            "shortage_units": str(shortage),
            "backordered_units": str(backordered),
            "deferred_recoverable_units": str(
                deferred_recoverable
            ),
            "permanently_lost_units": str(
                permanently_lost
            ),
            "stockout_expected": shortage > 0,
            "fill_rate_percent": money(fill_rate),
            "shortage_rate_percent": money(
                shortage_rate
            ),
            "lost_sales_revenue": money(
                lost_revenue
            ),
            "lost_contribution": money(
                lost_contribution
            ),
            "backorder_cost": money(
                backorder_cost
            ),
            "emergency_replenishment_cost": money(
                emergency_cost
            ),
            "customer_penalties": money(penalties),
            "estimated_economic_loss": money(
                economic_loss
            ),
            "additional_replenishment_units": str(
                replenishment_required
            ),
            "simulation_only": True,
        }

    def compare_scenarios(
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

        results.sort(
            key=lambda result: (
                Decimal(
                    result["estimated_economic_loss"]
                ),
                Decimal(result["shortage_units"]),
            )
        )

        return {
            "currency": self.currency,
            "scenario_count": len(results),
            "ranked_scenarios": results,
            "lowest_estimated_loss": results[0],
            "recommendation_only": True,
        }
