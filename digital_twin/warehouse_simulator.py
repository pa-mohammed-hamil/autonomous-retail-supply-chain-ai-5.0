"""Planned module: warehouse simulator. Implementation pending."""

"""
ai/simulation/warehouse_simulator.py

Autonomous Retail Supply Chain AI 5.0

Multi-SKU warehouse digital twin.
Python 3.10+ | Standard library only.

Simulation only: no real inventory changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
import copy


def integer(value: Any, name: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        raise ValueError(
            f"{name} must be a nonnegative integer"
        )
    return value


def decimal_value(value: Any, name: str) -> Decimal:
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


def money(value: Decimal) -> str:
    return str(
        value.quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
    )


@dataclass(frozen=True)
class WarehouseProduct:
    product_id: str
    initial_stock: int
    unit_volume: str = "1"
    holding_cost_per_unit_day: str = "0"


class WarehouseSimulator:

    def __init__(
        self,
        tenant_id: str,
        warehouse_id: str,
        capacity_volume: Any,
        products: list[WarehouseProduct],
        receiving_capacity_units_day: int = 10000,
        dispatch_capacity_units_day: int = 10000,
        handling_cost_per_unit: Any = "0",
        fixed_cost_per_day: Any = "0",
        currency: str = "INR",
    ):
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id required")
        if not isinstance(warehouse_id, str) or not warehouse_id.strip():
            raise ValueError("warehouse_id required")
        if not isinstance(currency, str) or not currency.strip():
            raise ValueError("currency required")

        self.tenant_id = tenant_id.strip()
        self.warehouse_id = warehouse_id.strip()
        self.currency = currency.strip().upper()
        self.capacity = decimal_value(
            capacity_volume, "capacity_volume"
        )

        if self.capacity <= 0:
            raise ValueError("Capacity must be positive")

        self.receiving_capacity = integer(
            receiving_capacity_units_day,
            "receiving_capacity_units_day",
        )
        self.dispatch_capacity = integer(
            dispatch_capacity_units_day,
            "dispatch_capacity_units_day",
        )
        self.handling_cost = decimal_value(
            handling_cost_per_unit,
            "handling_cost_per_unit",
        )
        self.fixed_cost = decimal_value(
            fixed_cost_per_day, "fixed_cost_per_day"
        )

        if not isinstance(products, list) or not products:
            raise ValueError("At least one product required")

        self.products = {}

        for product in products:
            if not isinstance(product, WarehouseProduct):
                raise TypeError("Invalid product profile")

            pid = product.product_id.strip()
            if not pid or pid in self.products:
                raise ValueError("Duplicate or empty product ID")

            stock = integer(product.initial_stock, "initial_stock")
            volume = decimal_value(
                product.unit_volume, "unit_volume"
            )
            holding = decimal_value(
                product.holding_cost_per_unit_day,
                "holding_cost_per_unit_day",
            )

            if volume <= 0:
                raise ValueError("unit_volume must be positive")

            self.products[pid] = {
                "stock": stock,
                "unit_volume": volume,
                "holding_cost": holding,
                "demand": 0,
                "fulfilled": 0,
                "unfulfilled": 0,
            }

        if self._occupied_volume() > self.capacity:
            raise ValueError(
                "Initial inventory exceeds warehouse capacity"
            )

        self.current_day = 0
        self._inbound: list[dict] = []
        self._history: list[dict] = []
        self._total_cost = Decimal("0")
        self._total_received = 0
        self._total_dispatched = 0

    def _occupied_volume(self) -> Decimal:
        return sum(
            (
                Decimal(item["stock"]) * item["unit_volume"]
                for item in self.products.values()
            ),
            Decimal("0"),
        )

    def schedule_inbound(
        self,
        product_id: str,
        quantity: int,
        arrival_day: int,
    ) -> None:
        if product_id not in self.products:
            raise ValueError("Unknown product")

        qty = integer(quantity, "quantity")
        day = integer(arrival_day, "arrival_day")

        if day <= self.current_day:
            raise ValueError("Arrival must be in the future")

        self._inbound.append({
            "product_id": product_id,
            "remaining_units": qty,
            "arrival_day": day,
        })

    def simulate_day(
        self,
        outbound_demand: dict[str, int],
    ) -> dict:
        if not isinstance(outbound_demand, dict):
            raise ValueError("Demand must be a dictionary")

        if set(outbound_demand) - set(self.products):
            raise ValueError("Unknown demand product")

        demand = {
            pid: integer(
                outbound_demand.get(pid, 0),
                f"demand[{pid}]",
            )
            for pid in self.products
        }

        day = self.current_day + 1

        # Inbound queues remain eligible after their
        # original arrival day if capacity is unavailable.
        receiving_remaining = self.receiving_capacity
        received = {pid: 0 for pid in self.products}

        for shipment in self._inbound:
            if shipment["arrival_day"] > day:
                continue
            if receiving_remaining == 0:
                break

            pid = shipment["product_id"]
            item = self.products[pid]

            free_volume = (
                self.capacity - self._occupied_volume()
            )

            capacity_units = int(
                free_volume // item["unit_volume"]
            )

            accepted = min(
                shipment["remaining_units"],
                receiving_remaining,
                capacity_units,
            )

            item["stock"] += accepted
            shipment["remaining_units"] -= accepted
            received[pid] += accepted
            receiving_remaining -= accepted

        self._inbound = [
            shipment
            for shipment in self._inbound
            if shipment["remaining_units"] > 0
        ]

        # Outbound capacity is shared across SKUs.
        # Product insertion order determines priority.
        dispatch_remaining = self.dispatch_capacity
        dispatched = {}
        unfulfilled = {}

        for pid, requested in demand.items():
            item = self.products[pid]

            shipped = min(
                requested,
                item["stock"],
                dispatch_remaining,
            )

            missed = requested - shipped

            item["stock"] -= shipped
            item["demand"] += requested
            item["fulfilled"] += shipped
            item["unfulfilled"] += missed

            dispatch_remaining -= shipped

            dispatched[pid] = shipped
            unfulfilled[pid] = missed

        received_total = sum(received.values())
        dispatched_total = sum(dispatched.values())

        holding_cost = sum(
            (
                Decimal(item["stock"])
                * item["holding_cost"]
                for item in self.products.values()
            ),
            Decimal("0"),
        )

        handling_cost = (
            Decimal(received_total + dispatched_total)
            * self.handling_cost
        )

        daily_cost = (
            holding_cost
            + handling_cost
            + self.fixed_cost
        )

        self._total_cost += daily_cost
        self._total_received += received_total
        self._total_dispatched += dispatched_total
        self.current_day = day

        occupied = self._occupied_volume()

        result = {
            "day": day,
            "received_units": received,
            "dispatched_units": dispatched,
            "unfulfilled_units": unfulfilled,
            "closing_stock": {
                pid: item["stock"]
                for pid, item in self.products.items()
            },
            "occupied_volume": str(occupied),
            "capacity_utilization_percent": money(
                occupied / self.capacity * 100
            ),
            "holding_cost": money(holding_cost),
            "handling_cost": money(handling_cost),
            "fixed_cost": money(self.fixed_cost),
            "daily_cost": money(daily_cost),
            "simulation_only": True,
        }

        self._history.append(copy.deepcopy(result))
        return result

    def run(
        self,
        daily_outbound_demands: list[dict[str, int]],
    ) -> dict:
        if not isinstance(daily_outbound_demands, list):
            raise ValueError("Expected a list of daily demands")

        results = [
            self.simulate_day(day)
            for day in daily_outbound_demands
        ]

        return {
            "tenant_id": self.tenant_id,
            "warehouse_id": self.warehouse_id,
            "daily_results": results,
            "summary": self.summary(),
        }

    def summary(self) -> dict:
        demand = sum(
            p["demand"] for p in self.products.values()
        )
        fulfilled = sum(
            p["fulfilled"] for p in self.products.values()
        )

        return {
            "tenant_id": self.tenant_id,
            "warehouse_id": self.warehouse_id,
            "currency": self.currency,
            "days_simulated": self.current_day,
            "demand_units": demand,
            "fulfilled_units": fulfilled,
            "unfulfilled_units": demand - fulfilled,
            "unit_fill_rate_percent": money(
                Decimal(fulfilled) / Decimal(demand) * 100
                if demand else Decimal("100")
            ),
            "received_units": self._total_received,
            "dispatched_units": self._total_dispatched,
            "operating_cost": money(self._total_cost),
            "capacity_utilization_percent": money(
                self._occupied_volume() / self.capacity * 100
            ),
            "closing_stock": {
                pid: p["stock"]
                for pid, p in self.products.items()
            },
            "pending_inbound": copy.deepcopy(self._inbound),
            "simulation_only": True,
        }

    def history(self, limit: int = 100) -> list[dict]:
        integer(limit, "limit")
        return copy.deepcopy(
            self._history[-limit:] if limit else []
        )
