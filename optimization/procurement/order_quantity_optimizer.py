"""Planned module: order quantity optimizer. Implementation pending."""

"""
ai/optimization/order_quantity_optimizer.py

Constrained economic order quantity planning.

Features:
- EOQ
- Minimum order quantity
- Pack-size multiples
- Inventory target
- Warehouse capacity
- Purchase budget
- Candidate cost comparison

Planning assumptions:
- Constant average annual demand.
- Fixed ordering and holding costs.
- No quantity discounts or perishability.
- One SKU per optimization request.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class OrderQuantityInput:
    sku: str
    annual_demand: float
    unit_cost: float
    ordering_cost: float
    annual_holding_cost_per_unit: float
    current_stock: int
    inbound_stock: int = 0
    backorders: int = 0
    target_inventory_position: int = 0
    minimum_order_quantity: int = 1
    pack_size: int = 1
    warehouse_capacity_units: int | None = None
    available_budget: float | None = None

    def __post_init__(self):
        if not self.sku:
            raise ValueError("SKU required")

        for name in (
            "annual_demand",
            "unit_cost",
            "ordering_cost",
            "annual_holding_cost_per_unit",
        ):
            value = getattr(self, name)

            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"Invalid {name}")

        if self.annual_holding_cost_per_unit <= 0:
            raise ValueError(
                "Holding cost must be positive"
            )

        for name in (
            "current_stock",
            "inbound_stock",
            "backorders",
            "target_inventory_position",
        ):
            value = getattr(self, name)

            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ValueError(f"Invalid {name}")

        for name in (
            "minimum_order_quantity",
            "pack_size",
        ):
            value = getattr(self, name)

            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                raise ValueError(f"Invalid {name}")

        if self.warehouse_capacity_units is not None:
            if (
                isinstance(
                    self.warehouse_capacity_units, bool
                )
                or not isinstance(
                    self.warehouse_capacity_units, int
                )
                or self.warehouse_capacity_units < 0
            ):
                raise ValueError(
                    "Invalid warehouse capacity"
                )

        if self.available_budget is not None:
            if (
                isinstance(self.available_budget, bool)
                or not isinstance(
                    self.available_budget, (int, float)
                )
                or not math.isfinite(
                    self.available_budget
                )
                or self.available_budget < 0
            ):
                raise ValueError("Invalid budget")


class OrderQuantityOptimizer:

    @staticmethod
    def round_up_pack(
        quantity: float,
        pack_size: int,
    ) -> int:
        return (
            math.ceil(quantity / pack_size)
            * pack_size
        )

    @staticmethod
    def annual_variable_cost(
        quantity: int,
        annual_demand: float,
        ordering_cost: float,
        holding_cost: float,
    ) -> float:
        if quantity <= 0:
            return 0.0

        return (
            annual_demand / quantity
            * ordering_cost
            + quantity / 2
            * holding_cost
        )

    def optimize(
        self,
        item: OrderQuantityInput,
    ) -> dict:

        inventory_position = (
            item.current_stock
            + item.inbound_stock
            - item.backorders
        )

        shortage = max(
            0,
            item.target_inventory_position
            - inventory_position,
        )

        eoq = (
            math.sqrt(
                2
                * item.annual_demand
                * item.ordering_cost
                / item.annual_holding_cost_per_unit
            )
            if item.annual_demand > 0
            and item.ordering_cost > 0
            else 0.0
        )

        if shortage == 0:
            return {
                "sku": item.sku,
                "inventory_position": inventory_position,
                "eoq_units": round(eoq, 2),
                "recommended_order_units": 0,
                "reason": "Inventory target already met",
                "feasible": True,
                "requires_approval": True,
            }

        minimum_quantity = self.round_up_pack(
            max(
                shortage,
                item.minimum_order_quantity,
            ),
            item.pack_size,
        )

        maximum_quantity = math.inf

        if item.warehouse_capacity_units is not None:
            # Conservative assumption: inbound orders
            # remain in the warehouse when this PO arrives.
            free_space = max(
                0,
                item.warehouse_capacity_units
                - item.current_stock
                - item.inbound_stock,
            )

            maximum_quantity = min(
                maximum_quantity,
                free_space,
            )

        if item.available_budget is not None:
            if item.unit_cost > 0:
                affordable_units = math.floor(
                    item.available_budget
                    / item.unit_cost
                )

                maximum_quantity = min(
                    maximum_quantity,
                    affordable_units,
                )

        if maximum_quantity < minimum_quantity:
            return {
                "sku": item.sku,
                "inventory_position": inventory_position,
                "eoq_units": round(eoq, 2),
                "minimum_required_units": (
                    minimum_quantity
                ),
                "recommended_order_units": None,
                "feasible": False,
                "reason": (
                    "Budget or warehouse capacity "
                    "cannot meet minimum required order"
                ),
                "requires_approval": True,
            }

        # Candidate pack multiples around EOQ
        # and the minimum required quantity.
        candidates = {minimum_quantity}

        for raw in (
            eoq,
            math.floor(eoq / item.pack_size)
            * item.pack_size,
            math.ceil(eoq / item.pack_size)
            * item.pack_size,
        ):
            q = self.round_up_pack(
                max(raw, minimum_quantity),
                item.pack_size,
            )

            if q <= maximum_quantity:
                candidates.add(q)

        if math.isfinite(maximum_quantity):
            upper = (
                math.floor(
                    maximum_quantity / item.pack_size
                )
                * item.pack_size
            )

            if upper >= minimum_quantity:
                candidates.add(upper)

        evaluated = []

        for quantity in sorted(candidates):
            if quantity > maximum_quantity:
                continue

            purchase_cost = (
                quantity * item.unit_cost
            )

            variable_cost = self.annual_variable_cost(
                quantity,
                item.annual_demand,
                item.ordering_cost,
                item.annual_holding_cost_per_unit,
            )

            evaluated.append({
                "quantity": quantity,
                "purchase_cost": round(
                    purchase_cost, 2
                ),
                "annual_ordering_and_holding_cost": (
                    round(variable_cost, 2)
                ),
            })

        best = min(
            evaluated,
            key=lambda row: (
                row["annual_ordering_and_holding_cost"],
                row["quantity"],
            ),
        )

        return {
            "sku": item.sku,
            "inventory_position": inventory_position,
            "shortage_units": shortage,
            "eoq_units": round(eoq, 2),
            "recommended_order_units": best["quantity"],
            "estimated_purchase_cost": (
                best["purchase_cost"]
            ),
            "estimated_annual_variable_cost": (
                best["annual_ordering_and_holding_cost"]
            ),
            "alternatives": evaluated,
            "feasible": True,
            "requires_approval": True,
            "purchase_order_created": False,
        }
