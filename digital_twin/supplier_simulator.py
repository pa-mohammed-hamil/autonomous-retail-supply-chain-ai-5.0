"""Planned module: supplier simulator. Implementation pending."""

"""
ai/simulation/supplier_simulator.py

Autonomous Retail Supply Chain AI 5.0

Multi-supplier purchase order simulator.

Python 3.10+ | Standard library only.

Features:
- Supplier registration
- Purchase order simulation
- Daily production capacity
- Supplier lead times
- Partial fulfillment
- Defect quantities
- Shipment receipts
- Supplier KPI reporting

All purchase orders are simulated.
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
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        raise ValueError(
            f"{name} must be a nonnegative integer"
        )
    return value


def decimal_value(
    value: Any,
    name: str,
) -> Decimal:

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


def money(value: Decimal) -> str:
    return str(
        value.quantize(
            CENT, rounding=ROUND_HALF_UP
        )
    )


@dataclass(frozen=True)
class SupplierProfile:
    supplier_id: str
    product_id: str
    daily_capacity_units: int
    lead_time_days: int
    unit_cost: str
    defect_rate_percent: str = "0"


class SupplierSimulator:

    def __init__(
        self,
        tenant_id: str,
        currency: str = "INR",
    ):
        if (
            not isinstance(tenant_id, str)
            or not tenant_id.strip()
        ):
            raise ValueError("tenant_id is required")

        if (
            not isinstance(currency, str)
            or not currency.strip()
        ):
            raise ValueError("currency is required")

        self.tenant_id = tenant_id.strip()
        self.currency = currency.strip().upper()

        self.current_day = 0
        self.suppliers: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        self.deliveries: list[dict] = []

        self._order_counter = 0

    def register_supplier(
        self,
        profile: SupplierProfile,
    ) -> None:

        if not isinstance(profile, SupplierProfile):
            raise TypeError(
                "profile must be SupplierProfile"
            )

        supplier_id = profile.supplier_id.strip()

        if not supplier_id or not profile.product_id.strip():
            raise ValueError(
                "Supplier and product IDs required"
            )

        if supplier_id in self.suppliers:
            raise ValueError(
                f"Duplicate supplier: {supplier_id}"
            )

        capacity = units(
            profile.daily_capacity_units,
            "daily_capacity_units",
        )

        if capacity <= 0:
            raise ValueError(
                "Supplier capacity must be positive"
            )

        lead_time = units(
            profile.lead_time_days,
            "lead_time_days",
        )

        unit_cost = decimal_value(
            profile.unit_cost,
            "unit_cost",
        )

        defect_rate = decimal_value(
            profile.defect_rate_percent,
            "defect_rate_percent",
        )

        if defect_rate > 100:
            raise ValueError(
                "defect_rate_percent cannot exceed 100"
            )

        self.suppliers[supplier_id] = {
            "profile": profile,
            "unit_cost": unit_cost,
            "defect_rate": (
                defect_rate / Decimal("100")
            ),
            "ordered_units": 0,
            "produced_units": 0,
            "delivered_units": 0,
            "defective_units": 0,
        }

    def place_order(
        self,
        supplier_id: str,
        quantity: int,
    ) -> dict:

        if supplier_id not in self.suppliers:
            raise ValueError(
                f"Unknown supplier: {supplier_id}"
            )

        amount = units(quantity, "quantity")

        if amount == 0:
            raise ValueError(
                "Order quantity must be positive"
            )

        self._order_counter += 1

        order_id = f"SIM-PO-{self._order_counter:06d}"

        supplier = self.suppliers[supplier_id]

        order = {
            "order_id": order_id,
            "supplier_id": supplier_id,
            "product_id": (
                supplier["profile"].product_id
            ),
            "ordered_units": amount,
            "remaining_units": amount,
            "produced_units": 0,
            "delivered_units": 0,
            "status": "pending",
            "created_day": self.current_day,
            "estimated_order_cost": money(
                Decimal(amount)
                * supplier["unit_cost"]
            ),
        }

        self.orders[order_id] = order

        supplier["ordered_units"] += amount

        return copy.deepcopy(order)

    def simulate_day(self) -> dict:

        self.current_day += 1
        day = self.current_day

        produced_today = 0
        delivered_today = 0
        defective_today = 0

        # Receive shipments scheduled for today.
        arrivals = [
            shipment
            for shipment in self.deliveries
            if shipment["arrival_day"] == day
        ]

        self.deliveries = [
            shipment
            for shipment in self.deliveries
            if shipment["arrival_day"] != day
        ]

        for shipment in arrivals:
            order = self.orders[
                shipment["order_id"]
            ]
            supplier = self.suppliers[
                shipment["supplier_id"]
            ]

            order["delivered_units"] += (
                shipment["good_units"]
            )

            supplier["delivered_units"] += (
                shipment["good_units"]
            )

            supplier["defective_units"] += (
                shipment["defective_units"]
            )

            delivered_today += shipment["good_units"]
            defective_today += (
                shipment["defective_units"]
            )

        # Production allocation: FIFO by order ID.
        for supplier_id, supplier in (
            self.suppliers.items()
        ):
            capacity_remaining = (
                supplier["profile"].daily_capacity_units
            )

            for order in self.orders.values():
                if order["supplier_id"] != supplier_id:
                    continue

                if order["remaining_units"] <= 0:
                    continue

                if capacity_remaining <= 0:
                    break

                production = min(
                    capacity_remaining,
                    order["remaining_units"],
                )

                order["remaining_units"] -= production
                order["produced_units"] += production

                supplier["produced_units"] += production

                capacity_remaining -= production
                produced_today += production

                expected_defects = (
                    Decimal(production)
                    * supplier["defect_rate"]
                )

                defects = int(
                    expected_defects.to_integral_value(
                        rounding=ROUND_HALF_UP
                    )
                )

                defects = min(
                    defects, production
                )

                good_units = production - defects

                arrival_day = (
                    day
                    + supplier[
                        "profile"
                    ].lead_time_days
                )

                # Lead-time zero shipments are
                # received during today's processing.
                if arrival_day == day:
                    order["delivered_units"] += (
                        good_units
                    )

                    supplier["delivered_units"] += (
                        good_units
                    )
                    supplier["defective_units"] += (
                        defects
                    )

                    delivered_today += good_units
                    defective_today += defects

                else:
                    self.deliveries.append({
                        "order_id": order["order_id"],
                        "supplier_id": supplier_id,
                        "arrival_day": arrival_day,
                        "good_units": good_units,
                        "defective_units": defects,
                    })

        for order in self.orders.values():
            if (
                order["remaining_units"] == 0
                and not any(
                    shipment["order_id"]
                    == order["order_id"]
                    for shipment in self.deliveries
                )
            ):
                order["status"] = "completed"
            elif order["produced_units"] > 0:
                order["status"] = "in_progress"

        return {
            "day": day,
            "produced_units": produced_today,
            "delivered_good_units": delivered_today,
            "defective_units": defective_today,
            "pending_shipments": len(
                self.deliveries
            ),
            "simulation_only": True,
        }

    def run(self, days: int) -> dict:

        if (
            isinstance(days, bool)
            or not isinstance(days, int)
            or not 1 <= days <= 365
        ):
            raise ValueError(
                "days must be between 1 and 365"
            )

        history = [
            self.simulate_day()
            for _ in range(days)
        ]

        return {
            "tenant_id": self.tenant_id,
            "currency": self.currency,
            "days_simulated": days,
            "daily_history": history,
            "summary": self.summary(),
        }

    def summary(self) -> dict:

        supplier_results = {}

        for supplier_id, supplier in (
            self.suppliers.items()
        ):
            produced = supplier["produced_units"]
            delivered = supplier["delivered_units"]
            defective = supplier["defective_units"]

            inspected = delivered + defective

            defect_rate = (
                Decimal(defective)
                / Decimal(inspected)
                * 100
                if inspected > 0
                else None
            )

            supplier_results[supplier_id] = {
                "product_id": (
                    supplier["profile"].product_id
                ),
                "ordered_units": (
                    supplier["ordered_units"]
                ),
                "produced_units": produced,
                "delivered_good_units": delivered,
                "defective_units": defective,
                "observed_defect_rate_percent": (
                    money(defect_rate)
                    if defect_rate is not None
                    else None
                ),
            }

        return {
            "tenant_id": self.tenant_id,
            "currency": self.currency,
            "current_day": self.current_day,
            "supplier_performance": (
                supplier_results
            ),
            "orders": copy.deepcopy(
                list(self.orders.values())
            ),
            "pending_shipments": copy.deepcopy(
                self.deliveries
            ),
            "simulation_only": True,
        }
