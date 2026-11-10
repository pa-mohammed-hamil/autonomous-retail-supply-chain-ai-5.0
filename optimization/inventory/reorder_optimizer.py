"""Planned module: reorder optimizer. Implementation pending."""

"""
ai/optimization/reorder_optimizer.py

Inventory reorder recommendations.

Features:
- Reorder point calculation
- Safety stock using demand uncertainty
- Inventory position
- Economic order quantity (EOQ)
- Minimum order quantity
- Supplier pack-size rounding
- Optional budget constraint

No purchase order is created automatically.
"""

from __future__ import annotations

import math

from dataclasses import dataclass
from statistics import NormalDist


@dataclass(frozen=True)
class ReorderInput:
    sku: str
    average_daily_demand: float
    daily_demand_std: float
    lead_time_days: float
    current_stock: int
    inbound_stock: int
    backorders: int
    unit_cost: float
    ordering_cost: float
    annual_holding_cost_per_unit: float
    service_level: float = 0.95
    minimum_order_quantity: int = 1
    pack_size: int = 1

    def __post_init__(self):
        if not self.sku:
            raise ValueError("SKU required")

        nonnegative = (
            self.average_daily_demand,
            self.daily_demand_std,
            self.lead_time_days,
            self.unit_cost,
            self.ordering_cost,
        )

        if any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or v < 0
            for v in nonnegative
        ):
            raise ValueError(
                "Invalid nonnegative input"
            )

        if (
            not math.isfinite(
                self.annual_holding_cost_per_unit
            )
            or self.annual_holding_cost_per_unit <= 0
        ):
            raise ValueError(
                "Holding cost must be positive"
            )

        for quantity in (
            self.current_stock,
            self.inbound_stock,
            self.backorders,
        ):
            if (
                not isinstance(quantity, int)
                or isinstance(quantity, bool)
                or quantity < 0
            ):
                raise ValueError(
                    "Stock values must be nonnegative integers"
                )

        if not 0 < self.service_level < 1:
            raise ValueError(
                "Service level must be between 0 and 1"
            )

        if (
            not isinstance(self.minimum_order_quantity, int)
            or isinstance(self.minimum_order_quantity, bool)
            or self.minimum_order_quantity < 1
        ):
            raise ValueError("Invalid minimum order quantity")

        if (
            not isinstance(self.pack_size, int)
            or isinstance(self.pack_size, bool)
            or self.pack_size < 1
        ):
            raise ValueError("Invalid pack size")


class ReorderOptimizer:

    @staticmethod
    def _round_to_pack(
        quantity: float,
        pack_size: int,
    ) -> int:
        if quantity <= 0:
            return 0

        return (
            math.ceil(quantity / pack_size)
            * pack_size
        )

    def recommend(
        self,
        item: ReorderInput,
        budget: float | None = None,
    ) -> dict:

        if budget is not None:
            if (
                not math.isfinite(budget)
                or budget < 0
            ):
                raise ValueError("Invalid budget")

        z_score = NormalDist().inv_cdf(
            item.service_level
        )

        expected_lead_time_demand = (
            item.average_daily_demand
            * item.lead_time_days
        )

        # Assumes independent daily demand and
        # deterministic supplier lead time.
        safety_stock = (
            z_score
            * item.daily_demand_std
            * math.sqrt(item.lead_time_days)
        )

        reorder_point = math.ceil(
            expected_lead_time_demand
            + safety_stock
        )

        inventory_position = (
            item.current_stock
            + item.inbound_stock
            - item.backorders
        )

        annual_demand = (
            item.average_daily_demand * 365
        )

        eoq = math.sqrt(
            (
                2
                * annual_demand
                * item.ordering_cost
            )
            / item.annual_holding_cost_per_unit
        )

        reorder_needed = (
            inventory_position <= reorder_point
            and annual_demand > 0
        )

        if reorder_needed:
            # Order enough to restore inventory
            # position above the reorder point,
            # while considering EOQ.
            shortage = (
                reorder_point
                - inventory_position
                + 1
            )

            raw_quantity = max(
                shortage,
                eoq,
                item.minimum_order_quantity,
            )

            suggested_quantity = (
                self._round_to_pack(
                    raw_quantity,
                    item.pack_size,
                )
            )
        else:
            suggested_quantity = 0

        estimated_cost = (
            suggested_quantity * item.unit_cost
        )

        budget_feasible = (
            budget is None
            or estimated_cost <= budget
        )

        return {
            "sku": item.sku,
            "service_level": item.service_level,
            "expected_lead_time_demand": round(
                expected_lead_time_demand, 2
            ),
            "safety_stock": math.ceil(safety_stock),
            "reorder_point": reorder_point,
            "inventory_position": inventory_position,
            "economic_order_quantity": round(
                eoq, 2
            ),
            "reorder_needed": reorder_needed,
            "suggested_quantity": suggested_quantity,
            "estimated_purchase_cost": round(
                estimated_cost, 2
            ),
            "budget_feasible": budget_feasible,
            "recommendation_status": (
                "within_budget"
                if budget_feasible
                else "budget_review_required"
            ),
            "requires_approval": True,
            "purchase_order_created": False,
        }
