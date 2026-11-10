"""Planned module: simulation tools. Implementation pending."""

"""
File: ai/tools/simulation_tools.py
Project: Autonomous Retail Supply Chain AI 5.0

Standard-library simulation utilities.
No database or external API required.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, asdict
from typing import Any, Sequence


class SimulationError(ValueError):
    """Raised for invalid simulation parameters."""


def number(value: Any, name: str, minimum: float = 0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SimulationError(f"{name} must be numeric.")
    try:
        value = float(value)
    except (OverflowError, ValueError) as exc:
        raise SimulationError(f"Invalid {name}.") from exc
    if not math.isfinite(value) or value < minimum:
        raise SimulationError(f"{name} must be finite and >= {minimum}.")
    return value


def positive_int(value: Any, name: str, maximum: int = 100000) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= maximum
    ):
        raise SimulationError(
            f"{name} must be an integer from 1 to {maximum}."
        )
    return value


@dataclass(frozen=True)
class InventoryScenario:
    product_id: str
    initial_stock: int
    daily_demand: float
    lead_time_days: int
    reorder_point: int
    reorder_quantity: int
    unit_cost: float = 0.0
    holding_cost_per_unit_day: float = 0.0
    stockout_penalty_per_unit: float = 0.0

    def validate(self) -> None:
        if not self.product_id.strip():
            raise SimulationError("product_id is required.")

        for field_name in (
            "initial_stock", "reorder_point", "reorder_quantity"
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise SimulationError(f"{field_name} must be >= 0.")

        if (
            isinstance(self.lead_time_days, bool)
            or not isinstance(self.lead_time_days, int)
            or self.lead_time_days < 0
        ):
            raise SimulationError("lead_time_days must be >= 0.")

        for field_name in (
            "daily_demand",
            "unit_cost",
            "holding_cost_per_unit_day",
            "stockout_penalty_per_unit",
        ):
            number(getattr(self, field_name), field_name)


def simulate_inventory(
    scenario: InventoryScenario,
    days: int = 30,
    daily_demand: Sequence[int | float] | None = None,
) -> dict[str, Any]:
    """Simulate daily stock movements and replenishment."""
    scenario.validate()
    positive_int(days, "days", 3650)

    if daily_demand is not None:
        if len(daily_demand) != days:
            raise SimulationError("daily_demand length must equal days.")
        demands = [
            int(math.ceil(number(x, "daily demand")))
            for x in daily_demand
        ]
    else:
        demands = [int(math.ceil(scenario.daily_demand))] * days

    stock = scenario.initial_stock
    pending: list[tuple[int, int]] = []
    lost_sales = 0
    fulfilled = 0
    total_demand = 0
    holding_cost = 0.0
    stockout_cost = 0.0
    purchase_cost = 0.0
    orders_placed = 0
    timeline: list[dict[str, Any]] = []

    for day in range(1, days + 1):
        arriving = sum(
            quantity for arrival, quantity in pending if arrival <= day
        )
        pending = [
            (arrival, quantity)
            for arrival, quantity in pending
            if arrival > day
        ]
        stock += arriving

        demand = demands[day - 1]
        served = min(stock, demand)
        missing = demand - served
        stock -= served

        total_demand += demand
        fulfilled += served
        lost_sales += missing

        holding_cost += stock * scenario.holding_cost_per_unit_day
        stockout_cost += missing * scenario.stockout_penalty_per_unit

        on_order = sum(quantity for _, quantity in pending)
        order_placed = 0

        if (
            scenario.reorder_quantity > 0
            and stock + on_order <= scenario.reorder_point
        ):
            order_placed = scenario.reorder_quantity
            orders_placed += 1
            purchase_cost += order_placed * scenario.unit_cost

            # Zero-day lead time is available next simulated day,
            # avoiding inconsistent same-day ordering.
            arrival_day = day + max(1, scenario.lead_time_days)
            pending.append((arrival_day, order_placed))

        timeline.append({
            "day": day,
            "demand": demand,
            "fulfilled": served,
            "lost_sales": missing,
            "received": arriving,
            "closing_stock": stock,
            "order_placed": order_placed,
            "on_order": sum(q for _, q in pending),
        })

    return {
        "product_id": scenario.product_id,
        "days": days,
        "total_demand": total_demand,
        "fulfilled_units": fulfilled,
        "lost_sales_units": lost_sales,
        "fill_rate_percent": (
            round(100 * fulfilled / total_demand, 2)
            if total_demand else None
        ),
        "ending_stock": stock,
        "pending_units": sum(q for _, q in pending),
        "purchase_orders_placed": orders_placed,
        "holding_cost": round(holding_cost, 2),
        "stockout_penalty": round(stockout_cost, 2),
        "purchase_cost": round(purchase_cost, 2),
        "estimated_total_cost": round(
            holding_cost + stockout_cost + purchase_cost, 2
        ),
        "timeline": timeline,
        "method": "deterministic_discrete_day_simulation",
    }


def simulate_demand_scenarios(
    scenario: InventoryScenario,
    days: int = 30,
    multipliers: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Compare demand growth and decline scenarios."""
    multipliers = multipliers or {
        "low": 0.75,
        "baseline": 1.0,
        "high": 1.25,
        "surge": 1.75,
    }

    results = {}
    for name, multiplier in multipliers.items():
        multiplier = number(multiplier, f"multiplier[{name}]")
        modified = InventoryScenario(
            **{
                **asdict(scenario),
                "daily_demand": scenario.daily_demand * multiplier,
            }
        )
        simulation = simulate_inventory(modified, days)
        simulation.pop("timeline")
        results[name] = simulation

    return {
        "product_id": scenario.product_id,
        "scenarios": results,
    }


def monte_carlo_stockout(
    initial_stock: int,
    mean_daily_demand: float,
    demand_std: float,
    days: int = 30,
    trials: int = 1000,
    seed: int | None = 42,
) -> dict[str, Any]:
    """
    Estimate stockout probability under sampled daily demand.

    This baseline assumes independent, normally distributed demand,
    rounded to nonnegative integer units, without replenishment.
    """
    if isinstance(initial_stock, bool) or not isinstance(initial_stock, int):
        raise SimulationError("initial_stock must be an integer.")
    if initial_stock < 0:
        raise SimulationError("initial_stock cannot be negative.")

    mean = number(mean_daily_demand, "mean_daily_demand")
    std = number(demand_std, "demand_std")
    positive_int(days, "days", 3650)
    positive_int(trials, "trials", 100000)

    rng = random.Random(seed)
    shortages = []
    stockout_trials = 0

    for _ in range(trials):
        total_demand = sum(
            max(0, int(round(rng.gauss(mean, std))))
            for _ in range(days)
        )
        shortage = max(0, total_demand - initial_stock)
        shortages.append(shortage)
        if shortage > 0:
            stockout_trials += 1

    sorted_shortages = sorted(shortages)
    p95_index = min(trials - 1, math.ceil(0.95 * trials) - 1)

    return {
        "trials": trials,
        "days": days,
        "stockout_probability": round(stockout_trials / trials, 4),
        "stockout_probability_percent": round(
            100 * stockout_trials / trials, 2
        ),
        "expected_shortage_units": round(statistics.mean(shortages), 2),
        "p95_shortage_units": sorted_shortages[p95_index],
        "assumptions": [
            "Independent daily demand",
            "Normal demand distribution truncated at zero",
            "No replenishment during the simulation",
        ],
    }


def simulate_supplier_delay(
    expected_lead_time_days: int,
    possible_extra_delay_days: Sequence[int],
    daily_demand: float,
    available_stock: int,
) -> dict[str, Any]:
    """Estimate shortage exposure under supplier delays."""
    if (
        isinstance(expected_lead_time_days, bool)
        or not isinstance(expected_lead_time_days, int)
        or expected_lead_time_days < 0
    ):
        raise SimulationError("Invalid lead time.")

    demand = number(daily_demand, "daily_demand")
    stock = number(available_stock, "available_stock")

    if not possible_extra_delay_days:
        raise SimulationError("At least one delay scenario is required.")

    results = []
    for delay in possible_extra_delay_days:
        if isinstance(delay, bool) or not isinstance(delay, int) or delay < 0:
            raise SimulationError("Delays must be nonnegative integers.")

        total_days = expected_lead_time_days + delay
        expected_demand = demand * total_days

        results.append({
            "extra_delay_days": delay,
            "total_lead_time_days": total_days,
            "expected_demand": round(expected_demand, 2),
            "expected_shortage_units": round(
                max(0, expected_demand - stock), 2
            ),
        })

    return {"delay_scenarios": results}


def simulate_warehouse_capacity(
    current_units: int,
    incoming_units: int,
    outgoing_units: int,
    capacity_units: int,
) -> dict[str, Any]:
    """Check projected warehouse occupancy."""
    values = {}
    for name, value in {
        "current_units": current_units,
        "incoming_units": incoming_units,
        "outgoing_units": outgoing_units,
        "capacity_units": capacity_units,
    }.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SimulationError(f"{name} must be a nonnegative integer.")
        values[name] = value

    if outgoing_units > current_units + incoming_units:
        raise SimulationError("Outgoing units exceed available units.")

    projected = current_units + incoming_units - outgoing_units
    capacity = capacity_units

    return {
        "projected_units": projected,
        "capacity_units": capacity,
        "occupancy_percent": (
            round(projected / capacity * 100, 2)
            if capacity > 0 else None
        ),
        "overflow_units": max(0, projected - capacity),
        "capacity_exceeded": projected > capacity,
    }


def recommend_reorder_quantity(
    current_stock: int,
    average_daily_demand: float,
    lead_time_days: int,
    safety_stock: int = 0,
    review_period_days: int = 7,
) -> dict[str, Any]:
    """Calculate a simple order-up-to recommendation."""
    for name, value in {
        "current_stock": current_stock,
        "lead_time_days": lead_time_days,
        "safety_stock": safety_stock,
        "review_period_days": review_period_days,
    }.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise SimulationError(f"{name} must be a nonnegative integer.")

    demand = number(average_daily_demand, "average_daily_demand")
    target = math.ceil(
        demand * (lead_time_days + review_period_days) + safety_stock
    )

    return {
        "target_stock": target,
        "recommended_order_quantity": max(0, target - current_stock),
        "requires_approval": True,
        "method": "order_up_to_baseline",
    }


if __name__ == "__main__":
    scenario = InventoryScenario(
        product_id="SKU-1001",
        initial_stock=150,
        daily_demand=12,
        lead_time_days=5,
        reorder_point=60,
        reorder_quantity=100,
        unit_cost=45,
        holding_cost_per_unit_day=0.05,
        stockout_penalty_per_unit=10,
    )

    print(simulate_inventory(scenario, days=30))
    print(simulate_demand_scenarios(scenario))
    print(monte_carlo_stockout(150, 12, 3, days=10))
