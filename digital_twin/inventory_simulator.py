"""Planned module: inventory simulator. Implementation pending."""

"""
ai/simulation/inventory_simulator.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+ | Standard library only

Features:
- Daily SKU demand
- Inventory depletion
- Stockout and lost-sales tracking
- Supplier lead-time simulation
- Automatic simulated replenishment
- Reorder point and order quantity
- Inventory holding cost
- Service-level metrics
- Daily history

Simulation only: never submits real orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import (
    Decimal,
    InvalidOperation,
    ROUND_HALF_UP,
)
from typing import Any

from .environment import SimulationEnvironment


CENT = Decimal("0.01")


def quantity(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"Invalid {name}")

    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.isdecimal():
        result = int(value)
    else:
        raise ValueError(
            f"{name} must be a nonnegative integer"
        )

    if result < 0:
        raise ValueError(f"Invalid {name}")

    return result


def decimal_value(value: Any, name: str) -> Decimal:
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


def money(value: Decimal) -> str:
    return str(
        value.quantize(
            CENT,
            rounding=ROUND_HALF_UP,
        )
    )


@dataclass(frozen=True)
class InventoryPolicy:
    product_id: str
    initial_stock: int
    reorder_point: int
    reorder_quantity: int
    lead_time_days: int
    daily_holding_cost_per_unit: str = "0"
    lost_contribution_per_unit: str = "0"


class InventorySimulator:

    def __init__(
        self,
        environment: SimulationEnvironment,
        policy: InventoryPolicy,
    ):
        if not isinstance(
            environment, SimulationEnvironment
        ):
            raise TypeError(
                "environment must be SimulationEnvironment"
            )

        if not isinstance(policy, InventoryPolicy):
            raise TypeError(
                "policy must be InventoryPolicy"
            )

        if not policy.product_id.strip():
            raise ValueError("product_id is required")

        for field_name in (
            "initial_stock",
            "reorder_point",
            "reorder_quantity",
            "lead_time_days",
        ):
            quantity(
                getattr(policy, field_name),
                field_name,
            )

        if policy.reorder_quantity <= 0:
            raise ValueError(
                "reorder_quantity must be positive"
            )

        self.env = environment
        self.policy = policy

        self.holding_rate = decimal_value(
            policy.daily_holding_cost_per_unit,
            "daily_holding_cost_per_unit",
        )
        self.lost_margin = decimal_value(
            policy.lost_contribution_per_unit,
            "lost_contribution_per_unit",
        )

        self.stock = policy.initial_stock
        self.pending_orders: list[dict] = []

        self.total_demand = 0
        self.total_fulfilled = 0
        self.total_lost_sales = 0
        self.total_holding_cost = Decimal("0")
        self.total_lost_contribution = Decimal("0")
        self.total_orders_placed = 0

        self.daily_history: list[dict] = []

        # Each simulator requires its own environment
        # or unique event names for multi-SKU runs.
        self._daily_event = (
            f"inventory_daily:{policy.product_id}"
        )
        self._receipt_event = (
            f"inventory_receipt:{policy.product_id}"
        )

        self.env.register_handler(
            self._daily_event,
            self._on_daily_demand,
        )
        self.env.register_handler(
            self._receipt_event,
            self._on_receipt,
        )

    def _inventory_position(self) -> int:
        outstanding = sum(
            order["quantity"]
            for order in self.pending_orders
        )
        return self.stock + outstanding

    def _place_order(self, day: int) -> None:
        if (
            self._inventory_position()
            > self.policy.reorder_point
        ):
            return

        amount = self.policy.reorder_quantity

        # Same-day receipt is allowed for lead time 0,
        # but happens after today's demand event.
        receipt_day = (
            day + self.policy.lead_time_days
        )

        order = {
            "order_id": (
                f"{self.policy.product_id}-"
                f"PO-{self.total_orders_placed + 1}"
            ),
            "quantity": amount,
            "receipt_day": receipt_day,
        }

        self.pending_orders.append(order)
        self.total_orders_placed += 1

        self.env.schedule(
            event_type=self._receipt_event,
            scheduled_day=receipt_day,
            payload={
                "order_id": order["order_id"]
            },
            priority=200,
        )

    def _on_receipt(
        self,
        env: SimulationEnvironment,
        payload: dict,
    ) -> None:
        order_id = payload["order_id"]

        match = next(
            (
                order
                for order in self.pending_orders
                if order["order_id"] == order_id
            ),
            None,
        )

        if match is None:
            raise ValueError(
                f"Unknown simulated order: {order_id}"
            )

        self.stock += match["quantity"]
        self.pending_orders.remove(match)

    def _on_daily_demand(
        self,
        env: SimulationEnvironment,
        payload: dict,
    ) -> None:

        day = env.current_day
        demand = quantity(
            payload["demand"],
            "daily demand",
        )

        opening_stock = self.stock

        fulfilled = min(self.stock, demand)
        lost_sales = demand - fulfilled

        self.stock -= fulfilled

        self.total_demand += demand
        self.total_fulfilled += fulfilled
        self.total_lost_sales += lost_sales

        lost_contribution = (
            Decimal(lost_sales) * self.lost_margin
        )

        holding_cost = (
            Decimal(self.stock) * self.holding_rate
        )

        self.total_lost_contribution += (
            lost_contribution
        )
        self.total_holding_cost += holding_cost

        self._place_order(day)

        self.daily_history.append({
            "day": day,
            "opening_stock": opening_stock,
            "demand": demand,
            "fulfilled": fulfilled,
            "lost_sales": lost_sales,
            "closing_stock": self.stock,
            "inventory_position": (
                self._inventory_position()
            ),
            "holding_cost": money(holding_cost),
            "lost_contribution": money(
                lost_contribution
            ),
        })

    def schedule_demand(
        self,
        daily_demands: list[int],
        start_day: int = 1,
    ) -> None:

        if not isinstance(daily_demands, list):
            raise ValueError(
                "daily_demands must be a list"
            )

        if (
            isinstance(start_day, bool)
            or not isinstance(start_day, int)
            or start_day < self.env.current_day
        ):
            raise ValueError("Invalid start_day")

        for offset, demand in enumerate(
            daily_demands
        ):
            demand = quantity(
                demand, "daily demand"
            )

            self.env.schedule(
                event_type=self._daily_event,
                scheduled_day=start_day + offset,
                payload={"demand": demand},
                priority=100,
            )

    def summary(self) -> dict:
        fill_rate = (
            self.total_fulfilled
            / self.total_demand * 100
            if self.total_demand else 100.0
        )

        stockout_days = sum(
            day["lost_sales"] > 0
            for day in self.daily_history
        )

        return {
            "product_id": self.policy.product_id,
            "tenant_id": self.env.tenant_id,
            "simulation_id": self.env.simulation_id,
            "current_day": self.env.current_day,
            "closing_stock": self.stock,
            "inventory_position": (
                self._inventory_position()
            ),
            "total_demand_units": self.total_demand,
            "fulfilled_units": self.total_fulfilled,
            "lost_sales_units": self.total_lost_sales,
            "unit_fill_rate_percent": round(
                fill_rate, 2
            ),
            "stockout_days": stockout_days,
            "simulated_orders_placed": (
                self.total_orders_placed
            ),
            "pending_orders": list(
                self.pending_orders
            ),
            "total_holding_cost": money(
                self.total_holding_cost
            ),
            "total_lost_contribution": money(
                self.total_lost_contribution
            ),
            "simulation_only": True,
        }

    def history(self, limit: int = 100) -> list[dict]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit < 0
        ):
            raise ValueError("Invalid limit")

        return [
            dict(row)
            for row in self.daily_history[-limit:]
        ]
