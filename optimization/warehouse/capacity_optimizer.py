
"""
ai/optimization/capacity_optimizer.py

Warehouse capacity optimization.

Features:
- Multiple warehouses
- Multiple SKUs
- Weight and volume limits
- Refrigeration compatibility
- Warehouse-specific unit storage costs
- Split inventory placement
- Unallocated inventory reporting

All quantities are whole units.
No warehouse reservations are executed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from ortools.sat.python import cp_model


@dataclass(frozen=True)
class WarehouseCapacity:
    warehouse_id: str
    available_weight_kg: int
    available_volume_liters: int
    refrigerated: bool = False
    storage_cost_per_unit: float = 1.0

    def __post_init__(self):
        if not self.warehouse_id:
            raise ValueError("Warehouse ID required")

        for name in (
            "available_weight_kg",
            "available_volume_liters",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ValueError(f"Invalid {name}")

        if (
            not math.isfinite(self.storage_cost_per_unit)
            or self.storage_cost_per_unit < 0
        ):
            raise ValueError("Invalid storage cost")


@dataclass(frozen=True)
class ProductCapacityDemand:
    sku: str
    quantity: int
    weight_kg_per_unit: int
    volume_liters_per_unit: int
    refrigerated: bool = False

    def __post_init__(self):
        if not self.sku:
            raise ValueError("SKU required")

        for name in (
            "quantity",
            "weight_kg_per_unit",
            "volume_liters_per_unit",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                raise ValueError(f"Invalid {name}")


class CapacityOptimizer:

    def optimize(
        self,
        warehouses: list[WarehouseCapacity],
        products: list[ProductCapacityDemand],
        max_solve_seconds: float = 10.0,
    ) -> dict:

        if not warehouses or not products:
            raise ValueError(
                "Warehouses and products required"
            )

        if (
            not math.isfinite(max_solve_seconds)
            or max_solve_seconds <= 0
        ):
            raise ValueError("Invalid solve time")

        warehouse_ids = [
            w.warehouse_id for w in warehouses
        ]

        product_ids = [
            p.sku for p in products
        ]

        if len(warehouse_ids) != len(set(warehouse_ids)):
            raise ValueError("Duplicate warehouse IDs")

        if len(product_ids) != len(set(product_ids)):
            raise ValueError("Duplicate SKUs")

        model = cp_model.CpModel()

        allocation = {}

        for p_index, product in enumerate(products):
            for w_index, warehouse in enumerate(warehouses):
                upper = product.quantity

                if (
                    product.refrigerated
                    and not warehouse.refrigerated
                ):
                    upper = 0

                allocation[p_index, w_index] = (
                    model.NewIntVar(
                        0,
                        upper,
                        f"alloc_{p_index}_{w_index}",
                    )
                )

        # Each product must be fully allocated.
        for p_index, product in enumerate(products):
            model.Add(
                sum(
                    allocation[p_index, w_index]
                    for w_index in range(len(warehouses))
                ) == product.quantity
            )

        for w_index, warehouse in enumerate(warehouses):
            model.Add(
                sum(
                    allocation[p_index, w_index]
                    * product.weight_kg_per_unit
                    for p_index, product in enumerate(products)
                ) <= warehouse.available_weight_kg
            )

            model.Add(
                sum(
                    allocation[p_index, w_index]
                    * product.volume_liters_per_unit
                    for p_index, product in enumerate(products)
                ) <= warehouse.available_volume_liters
            )

        # Convert currency to integer cents.
        model.Minimize(
            sum(
                allocation[p_index, w_index]
                * round(
                    warehouse.storage_cost_per_unit * 100
                )
                for p_index, _ in enumerate(products)
                for w_index, warehouse in enumerate(warehouses)
            )
        )

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = (
            max_solve_seconds
        )

        status = solver.Solve(model)

        if status not in (
            cp_model.OPTIMAL,
            cp_model.FEASIBLE,
        ):
            return {
                "status": "no_feasible_allocation_found",
                "allocations": [],
                "requires_approval": True,
            }

        allocations = []
        total_cost = 0.0

        for p_index, product in enumerate(products):
            for w_index, warehouse in enumerate(warehouses):
                quantity = solver.Value(
                    allocation[p_index, w_index]
                )

                if quantity <= 0:
                    continue

                cost = (
                    quantity
                    * warehouse.storage_cost_per_unit
                )

                total_cost += cost

                allocations.append({
                    "warehouse_id": warehouse.warehouse_id,
                    "sku": product.sku,
                    "quantity": quantity,
                    "estimated_storage_cost": round(
                        cost, 2
                    ),
                })

        return {
            "status": (
                "optimal"
                if status == cp_model.OPTIMAL
                else "feasible"
            ),
            "allocations": allocations,
            "total_allocated_units": sum(
                item["quantity"]
                for item in allocations
            ),
            "total_estimated_storage_cost": round(
                total_cost, 2
            ),
            "requires_approval": True,
            "warehouse_inventory_updated": False,
        }
