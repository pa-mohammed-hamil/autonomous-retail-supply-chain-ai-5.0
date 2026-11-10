"""Planned module: supplier selection. Implementation pending."""

"""
ai/optimization/supplier_selection.py

Multi-criteria supplier selection.

Features:
- Price competitiveness
- On-time delivery reliability
- Quality acceptance rate
- Supplier risk
- Lead-time requirements
- Supplier capacity
- Minimum order quantities
- Budget constraints
- Split-order recommendations

Scores are heuristic and require calibration.
"""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Supplier:
    supplier_id: str
    sku: str
    unit_price: float
    available_capacity: int
    lead_time_days: float
    on_time_rate: float
    quality_rate: float
    risk_score: float
    minimum_order_quantity: int = 1

    def __post_init__(self):
        if not self.supplier_id or not self.sku:
            raise ValueError("Supplier ID and SKU required")

        for name in (
            "unit_price",
            "lead_time_days",
            "on_time_rate",
            "quality_rate",
            "risk_score",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"Invalid {name}")

        if self.unit_price < 0 or self.lead_time_days < 0:
            raise ValueError("Negative price or lead time")

        for name in (
            "on_time_rate",
            "quality_rate",
            "risk_score",
        ):
            if not 0 <= getattr(self, name) <= 1:
                raise ValueError(f"{name} must be 0-1")

        for name in (
            "available_capacity",
            "minimum_order_quantity",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < (1 if name == "minimum_order_quantity" else 0)
            ):
                raise ValueError(f"Invalid {name}")


class SupplierSelectionOptimizer:

    def select(
        self,
        suppliers: list[Supplier],
        sku: str,
        required_quantity: int,
        max_lead_time_days: float,
        budget: float | None = None,
    ) -> dict:

        if (
            isinstance(required_quantity, bool)
            or not isinstance(required_quantity, int)
            or required_quantity <= 0
        ):
            raise ValueError("Quantity must be positive")

        if (
            not math.isfinite(max_lead_time_days)
            or max_lead_time_days < 0
        ):
            raise ValueError("Invalid lead time limit")

        if budget is not None and (
            not math.isfinite(budget) or budget < 0
        ):
            raise ValueError("Invalid budget")

        ids = [s.supplier_id for s in suppliers]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate supplier IDs")

        eligible = [
            s for s in suppliers
            if s.sku == sku
            and s.lead_time_days <= max_lead_time_days
            and s.available_capacity >= s.minimum_order_quantity
        ]

        if not eligible:
            return {
                "status": "no_eligible_supplier",
                "allocations": [],
                "unfulfilled_quantity": required_quantity,
                "requires_approval": True,
            }

        prices = [s.unit_price for s in eligible]
        minimum_price = min(prices)
        maximum_price = max(prices)

        def score(s: Supplier) -> float:
            if maximum_price == minimum_price:
                price_score = 1.0
            else:
                price_score = (
                    maximum_price - s.unit_price
                ) / (maximum_price - minimum_price)

            lead_score = (
                1.0
                if max_lead_time_days == 0
                else max(
                    0.0,
                    1 - s.lead_time_days / max_lead_time_days
                )
            )

            return (
                0.30 * price_score
                + 0.25 * s.on_time_rate
                + 0.20 * s.quality_rate
                + 0.15 * lead_score
                + 0.10 * (1 - s.risk_score)
            )

        ranked = sorted(
            eligible,
            key=lambda s: (
                -score(s),
                s.unit_price,
                s.supplier_id,
            ),
        )

        remaining = required_quantity
        remaining_budget = (
            budget if budget is not None else math.inf
        )

        allocations = []

        for supplier in ranked:
            if remaining <= 0:
                break

            affordable = (
                remaining
                if supplier.unit_price == 0
                else math.floor(
                    remaining_budget / supplier.unit_price
                )
            )

            quantity = min(
                remaining,
                supplier.available_capacity,
                affordable,
            )

            if quantity < supplier.minimum_order_quantity:
                continue

            cost = quantity * supplier.unit_price

            allocations.append({
                "supplier_id": supplier.supplier_id,
                "sku": sku,
                "quantity": quantity,
                "unit_price": supplier.unit_price,
                "estimated_cost": round(cost, 2),
                "supplier_score": round(score(supplier), 4),
                "lead_time_days": supplier.lead_time_days,
            })

            remaining -= quantity
            remaining_budget -= cost

        return {
            "status": (
                "fully_allocated"
                if remaining == 0
                else "partially_allocated"
            ),
            "sku": sku,
            "allocations": allocations,
            "allocated_quantity": (
                required_quantity - remaining
            ),
            "unfulfilled_quantity": remaining,
            "total_estimated_cost": round(
                sum(a["estimated_cost"] for a in allocations),
                2,
            ),
            "requires_approval": True,
            "purchase_orders_created": False,
        }
    