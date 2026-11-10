"""Planned module: store simulator. Implementation pending."""

"""
ai/simulation/store_simulator.py

Autonomous Retail Supply Chain AI 5.0

Multi-SKU retail store simulator.
Python 3.10+ | Standard library only.

Features:
- Daily store demand
- Multi-product inventory
- Incoming stock receipts
- Sales and lost-sales tracking
- Revenue and contribution estimates
- Reorder recommendations
- Store-level performance metrics

No real inventory or orders are changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import (
    Decimal,
    InvalidOperation,
    ROUND_HALF_UP,
)
from typing import Any
import copy


CENT = Decimal("0.01")


def units(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(
        value, int
    ) or value < 0:
        raise ValueError(
            f"{name} must be a nonnegative integer"
        )
    return value


def price(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(
        value, (str, int, Decimal)
    ):
        raise ValueError(f"Invalid {name}")

    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid {name}") from exc

    if not result.is_finite() or result < 0:
        raise ValueError(f"Invalid {name}")

    return result


def cash(value: Decimal) -> str:
    return str(
        value.quantize(
            CENT, rounding=ROUND_HALF_UP
        )
    )


@dataclass(frozen=True)
class StoreProduct:
    product_id: str
    initial_stock: int
    selling_price: str
    variable_cost: str
    reorder_point: int = 0
    reorder_quantity: int = 0


class StoreSimulator:

    def __init__(
        self,
        tenant_id: str,
        store_id: str,
        products: list[StoreProduct],
        currency: str = "INR",
    ):
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("tenant_id is required")

        if not isinstance(store_id, str) or not store_id.strip():
            raise ValueError("store_id is required")

        if not isinstance(products, list) or not products:
            raise ValueError(
                "At least one product is required"
            )

        if not isinstance(currency, str) or not currency.strip():
            raise ValueError("currency is required")

        self.tenant_id = tenant_id.strip()
        self.store_id = store_id.strip()
        self.currency = currency.strip().upper()
        self.current_day = 0

        self.products: dict[str, dict] = {}

        for product in products:
            if not isinstance(product, StoreProduct):
                raise ValueError(
                    "Products must be StoreProduct objects"
                )

            product_id = product.product_id.strip()

            if not product_id:
                raise ValueError(
                    "product_id is required"
                )

            if product_id in self.products:
                raise ValueError(
                    f"Duplicate product: {product_id}"
                )

            initial = units(
                product.initial_stock,
                "initial_stock",
            )
            reorder_point = units(
                product.reorder_point,
                "reorder_point",
            )
            reorder_quantity = units(
                product.reorder_quantity,
                "reorder_quantity",
            )

            selling = price(
                product.selling_price,
                "selling_price",
            )
            variable = price(
                product.variable_cost,
                "variable_cost",
            )

            if variable > selling:
                raise ValueError(
                    "Variable cost exceeds selling price"
                )

            self.products[product_id] = {
                "stock": initial,
                "selling_price": selling,
                "variable_cost": variable,
                "reorder_point": reorder_point,
                "reorder_quantity": reorder_quantity,
                "demand": 0,
                "sold": 0,
                "lost_sales": 0,
                "revenue": Decimal("0"),
                "contribution": Decimal("0"),
            }

        self._deliveries: list[dict] = []
        self._history: list[dict] = []

    def schedule_delivery(
        self,
        product_id: str,
        quantity: int,
        arrival_day: int,
    ) -> None:

        if product_id not in self.products:
            raise ValueError(
                f"Unknown product: {product_id}"
            )

        qty = units(quantity, "quantity")
        day = units(arrival_day, "arrival_day")

        if day <= self.current_day:
            raise ValueError(
                "Arrival must be in the future"
            )

        self._deliveries.append({
            "product_id": product_id,
            "quantity": qty,
            "arrival_day": day,
        })

    def simulate_day(
        self,
        demand_by_product: dict[str, int],
    ) -> dict:

        if not isinstance(demand_by_product, dict):
            raise ValueError(
                "Demand must be a dictionary"
            )

        unknown = (
            set(demand_by_product)
            - set(self.products)
        )

        if unknown:
            raise ValueError(
                f"Unknown products: {sorted(unknown)}"
            )

        validated_demand = {
            product_id: units(
                demand_by_product.get(product_id, 0),
                f"demand for {product_id}",
            )
            for product_id in self.products
        }

        self.current_day += 1

        arrivals = [
            delivery
            for delivery in self._deliveries
            if delivery["arrival_day"]
            == self.current_day
        ]

        self._deliveries = [
            delivery
            for delivery in self._deliveries
            if delivery["arrival_day"]
            != self.current_day
        ]

        for delivery in arrivals:
            self.products[
                delivery["product_id"]
            ]["stock"] += delivery["quantity"]

        daily_revenue = Decimal("0")
        daily_contribution = Decimal("0")
        daily_demand = 0
        daily_sold = 0
        daily_lost = 0

        sku_results = {}

        for product_id, requested in (
            validated_demand.items()
        ):
            item = self.products[product_id]

            opening_stock = item["stock"]

            sold = min(
                requested,
                opening_stock,
            )

            lost = requested - sold
            item["stock"] -= sold

            revenue = (
                Decimal(sold)
                * item["selling_price"]
            )

            contribution = (
                Decimal(sold)
                * (
                    item["selling_price"]
                    - item["variable_cost"]
                )
            )

            item["demand"] += requested
            item["sold"] += sold
            item["lost_sales"] += lost
            item["revenue"] += revenue
            item["contribution"] += contribution

            daily_revenue += revenue
            daily_contribution += contribution
            daily_demand += requested
            daily_sold += sold
            daily_lost += lost

            reorder_recommended = (
                item["reorder_quantity"] > 0
                and item["stock"]
                <= item["reorder_point"]
            )

            sku_results[product_id] = {
                "opening_stock_after_receipts": (
                    opening_stock
                ),
                "demand": requested,
                "sold": sold,
                "lost_sales": lost,
                "closing_stock": item["stock"],
                "reorder_recommended": (
                    reorder_recommended
                ),
                "suggested_order_quantity": (
                    item["reorder_quantity"]
                    if reorder_recommended else 0
                ),
                "revenue": cash(revenue),
                "contribution": cash(contribution),
            }

        report = {
            "day": self.current_day,
            "store_id": self.store_id,
            "demand_units": daily_demand,
            "sold_units": daily_sold,
            "lost_sales_units": daily_lost,
            "revenue": cash(daily_revenue),
            "contribution": cash(
                daily_contribution
            ),
            "products": sku_results,
            "simulation_only": True,
        }

        self._history.append(
            copy.deepcopy(report)
        )

        return report

    def run(
        self,
        daily_demands: list[dict[str, int]],
    ) -> dict:

        if not isinstance(daily_demands, list):
            raise ValueError(
                "daily_demands must be a list"
            )

        results = [
            self.simulate_day(day)
            for day in daily_demands
        ]

        return {
            "tenant_id": self.tenant_id,
            "store_id": self.store_id,
            "days_simulated": len(results),
            "daily_results": results,
            "summary": self.summary(),
        }

    def summary(self) -> dict:
        demand = sum(
            item["demand"]
            for item in self.products.values()
        )

        sold = sum(
            item["sold"]
            for item in self.products.values()
        )

        lost = sum(
            item["lost_sales"]
            for item in self.products.values()
        )

        revenue = sum(
            (
                item["revenue"]
                for item in self.products.values()
            ),
            Decimal("0"),
        )

        contribution = sum(
            (
                item["contribution"]
                for item in self.products.values()
            ),
            Decimal("0"),
        )

        return {
            "tenant_id": self.tenant_id,
            "store_id": self.store_id,
            "currency": self.currency,
            "days_simulated": self.current_day,
            "total_demand_units": demand,
            "total_sold_units": sold,
            "total_lost_sales_units": lost,
            "unit_fill_rate_percent": (
                round(sold / demand * 100, 2)
                if demand else 100.0
            ),
            "total_revenue": cash(revenue),
            "total_contribution": cash(
                contribution
            ),
            "closing_inventory": {
                product_id: item["stock"]
                for product_id, item
                in self.products.items()
            },
            "pending_deliveries": copy.deepcopy(
                self._deliveries
            ),
            "simulation_only": True,
        }

    def history(
        self,
        limit: int = 100,
    ) -> list[dict]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit < 0
        ):
            raise ValueError("Invalid limit")

        return copy.deepcopy(
            self._history[-limit:]
        )
