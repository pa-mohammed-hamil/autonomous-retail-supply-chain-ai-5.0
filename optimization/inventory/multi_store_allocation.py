"""Planned module: multi store allocation. Implementation pending."""

"""
ai/optimization/multi_store_allocation.py

Multi-store inventory allocation.

Features:
- Multiple stores and SKUs
- Demand-based replenishment targets
- Priority and shortage scoring
- Warehouse inventory constraints
- Per-store shipment capacity
- Deterministic allocation
- Unfulfilled-demand reporting

Recommendations only: no inventory mutations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class StoreDemand:
    store_id: str
    sku: str
    forecast_demand: int
    current_stock: int
    inbound_stock: int = 0
    safety_stock: int = 0
    priority: float = 1.0

    def __post_init__(self):
        if not self.store_id or not self.sku:
            raise ValueError("Store and SKU required")

        quantities = (
            self.forecast_demand,
            self.current_stock,
            self.inbound_stock,
            self.safety_stock,
        )

        if any(
            not isinstance(q, int)
            or isinstance(q, bool)
            or q < 0
            for q in quantities
        ):
            raise ValueError(
                "Quantities must be nonnegative integers"
            )

        if not 0 < self.priority <= 10:
            raise ValueError(
                "Priority must be between 0 and 10"
            )


@dataclass
class AllocationResult:
    allocations: list[dict[str, Any]]
    warehouse_remaining: dict[str, int]
    total_allocated: int
    total_unfulfilled: int
    status: str = "recommendation_only"
    requires_approval: bool = True


class MultiStoreAllocator:

    @staticmethod
    def _validate_inventory(
        warehouse_inventory: dict[str, int],
    ) -> None:
        for sku, quantity in warehouse_inventory.items():
            if (
                not sku
                or not isinstance(quantity, int)
                or isinstance(quantity, bool)
                or quantity < 0
            ):
                raise ValueError(
                    "Invalid warehouse inventory"
                )

    def allocate(
        self,
        demands: list[StoreDemand],
        warehouse_inventory: dict[str, int],
        store_capacity: dict[str, int] | None = None,
    ) -> AllocationResult:

        self._validate_inventory(
            warehouse_inventory
        )

        remaining = dict(warehouse_inventory)
        capacities = dict(store_capacity or {})

        for store_id, capacity in capacities.items():
            if (
                not store_id
                or not isinstance(capacity, int)
                or isinstance(capacity, bool)
                or capacity < 0
            ):
                raise ValueError(
                    "Invalid store shipment capacity"
                )

        # Capacity is shared across SKUs.
        capacity_used: dict[str, int] = {}

        seen = set()
        candidates = []

        for demand in demands:
            key = (demand.store_id, demand.sku)

            if key in seen:
                raise ValueError(
                    f"Duplicate store/SKU request: {key}"
                )

            seen.add(key)

            target_stock = (
                demand.forecast_demand
                + demand.safety_stock
            )

            effective_stock = (
                demand.current_stock
                + demand.inbound_stock
            )

            requested = max(
                0,
                target_stock - effective_stock,
            )

            shortage_ratio = (
                requested / max(target_stock, 1)
            )

            score = (
                demand.priority
                * shortage_ratio
            )

            candidates.append({
                "store_id": demand.store_id,
                "sku": demand.sku,
                "target_stock": target_stock,
                "effective_stock": effective_stock,
                "requested_quantity": requested,
                "priority": demand.priority,
                "shortage_ratio": shortage_ratio,
                "score": score,
            })

        # Highest relative shortage and priority first.
        # Tie-breakers make results reproducible.
        candidates.sort(
            key=lambda row: (
                -row["score"],
                -row["shortage_ratio"],
                row["store_id"],
                row["sku"],
            )
        )

        allocations = []
        total_allocated = 0
        total_unfulfilled = 0

        for candidate in candidates:
            sku = candidate["sku"]
            store_id = candidate["store_id"]
            requested = candidate[
                "requested_quantity"
            ]

            available = remaining.get(sku, 0)

            capacity = capacities.get(store_id)

            if capacity is None:
                capacity_left = requested
            else:
                capacity_left = max(
                    0,
                    capacity - capacity_used.get(
                        store_id, 0
                    ),
                )

            allocated = min(
                requested,
                available,
                capacity_left,
            )

            unfulfilled = requested - allocated

            remaining[sku] = available - allocated

            capacity_used[store_id] = (
                capacity_used.get(store_id, 0)
                + allocated
            )

            total_allocated += allocated
            total_unfulfilled += unfulfilled

            allocations.append({
                **candidate,
                "allocated_quantity": allocated,
                "unfulfilled_quantity": unfulfilled,
                "projected_stock": (
                    candidate["effective_stock"]
                    + allocated
                ),
                "requires_approval": True,
            })

        return AllocationResult(
            allocations=allocations,
            warehouse_remaining=remaining,
            total_allocated=total_allocated,
            total_unfulfilled=total_unfulfilled,
        )
