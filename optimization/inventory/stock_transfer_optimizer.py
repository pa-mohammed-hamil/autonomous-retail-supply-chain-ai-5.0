k"""Planned module: stock transfer optimizer. Implementation pending."""

"""
Stock Transfer Optimizer

Inter-store inventory balancing.

Features:
- Multiple SKUs
- Surplus and shortage identification
- Minimum protected donor stock
- Transportation costs
- Route eligibility and capacities
- Greedy cost-aware transfer recommendations
- No automatic inventory mutation

For globally optimal solutions, use a
min-cost flow or mixed-integer optimizer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class StoreInventory:
    store_id: str
    sku: str
    current_stock: int
    forecast_demand: int
    safety_stock: int
    inbound_stock: int = 0

    def __post_init__(self):
        if not self.store_id or not self.sku:
            raise ValueError(
                "Store ID and SKU are required"
            )

        values = (
            self.current_stock,
            self.forecast_demand,
            self.safety_stock,
            self.inbound_stock,
        )

        if any(
            isinstance(v, bool)
            or not isinstance(v, int)
            or v < 0
            for v in values
        ):
            raise ValueError(
                "Stock quantities must be nonnegative integers"
            )


@dataclass(frozen=True)
class TransferLane:
    from_store: str
    to_store: str
    cost_per_unit: float
    max_units: int
    distance_km: float = 0.0

    def __post_init__(self):
        if (
            not self.from_store
            or not self.to_store
            or self.from_store == self.to_store
        ):
            raise ValueError("Invalid transfer lane")

        if any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or v < 0
            for v in (
                self.cost_per_unit,
                self.distance_km,
            )
        ):
            raise ValueError("Invalid transfer cost/distance")

        if (
            isinstance(self.max_units, bool)
            or not isinstance(self.max_units, int)
            or self.max_units < 0
        ):
            raise ValueError("Invalid lane capacity")


class StockTransferOptimizer:

    def optimize(
        self,
        inventory: list[StoreInventory],
        lanes: list[TransferLane],
        max_distance_km: float | None = None,
    ) -> dict:

        if max_distance_km is not None:
            if (
                not math.isfinite(max_distance_km)
                or max_distance_km < 0
            ):
                raise ValueError(
                    "Invalid maximum distance"
                )

        records = {}

        for item in inventory:
            key = (item.store_id, item.sku)

            if key in records:
                raise ValueError(
                    f"Duplicate inventory record: {key}"
                )

            records[key] = item

        surplus = {}
        shortage = {}

        for key, item in records.items():
            available = (
                item.current_stock
                + item.inbound_stock
            )

            target = (
                item.forecast_demand
                + item.safety_stock
            )

            surplus[key] = max(
                0,
                available - target,
            )

            shortage[key] = max(
                0,
                target - available,
            )

        # Lowest unit transportation cost first.
        eligible_lanes = sorted(
            lanes,
            key=lambda lane: (
                lane.cost_per_unit,
                lane.distance_km,
                lane.from_store,
                lane.to_store,
            ),
        )

        transfers = []
        total_cost = 0.0

        # Shared capacity per physical lane
        # across all SKUs.
        lane_usage: dict[tuple[str, str], int] = {}

        for lane in eligible_lanes:
            if (
                max_distance_km is not None
                and lane.distance_km > max_distance_km
            ):
                continue

            lane_key = (
                lane.from_store,
                lane.to_store,
            )

            used = lane_usage.get(
                lane_key, 0
            )

            capacity_left = max(
                0,
                lane.max_units - used,
            )

            if capacity_left == 0:
                continue

            # Process SKUs in a deterministic order.
            skus = sorted({
                sku
                for store, sku in records
                if store in {
                    lane.from_store,
                    lane.to_store,
                }
            })

            for sku in skus:
                if capacity_left == 0:
                    break

                donor_key = (
                    lane.from_store,
                    sku,
                )

                receiver_key = (
                    lane.to_store,
                    sku,
                )

                quantity = min(
                    surplus.get(donor_key, 0),
                    shortage.get(receiver_key, 0),
                    capacity_left,
                )

                if quantity <= 0:
                    continue

                cost = (
                    quantity * lane.cost_per_unit
                )

                transfers.append({
                    "from_store": lane.from_store,
                    "to_store": lane.to_store,
                    "sku": sku,
                    "quantity": quantity,
                    "distance_km": lane.distance_km,
                    "estimated_cost": round(cost, 2),
                    "requires_approval": True,
                })

                surplus[donor_key] -= quantity
                shortage[receiver_key] -= quantity

                capacity_left -= quantity
                used += quantity
                total_cost += cost

            lane_usage[lane_key] = used

        remaining_shortages = [
            {
                "store_id": store_id,
                "sku": sku,
                "unfulfilled_quantity": quantity,
            }
            for (store_id, sku), quantity in sorted(
                shortage.items()
            )
            if quantity > 0
        ]

        return {
            "transfers": transfers,
            "total_transferred_units": sum(
                row["quantity"]
                for row in transfers
            ),
            "total_estimated_cost": round(
                total_cost, 2
            ),
            "remaining_shortages": remaining_shortages,
            "remaining_surplus": [
                {
                    "store_id": store_id,
                    "sku": sku,
                    "quantity": quantity,
                }
                for (store_id, sku), quantity in sorted(
                    surplus.items()
                )
                if quantity > 0
            ],
            "recommendation_only": True,
            "inventory_updated": False,
            "requires_approval": True,
        }
