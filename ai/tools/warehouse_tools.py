"""Planned module: warehouse tools. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
File: ai/tools/warehouse_tools.py

Warehouse inventory and operations toolkit.

Features:
- Warehouse registration
- Warehouse capacity monitoring
- Stock receiving and picking
- Inventory transfers
- Stock movement history
- Warehouse utilization analytics
- Low-stock and overflow alerts
- Structured operational outputs

Python 3.10+ | Standard library only
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


class WarehouseError(ValueError):
    """Invalid warehouse operation."""


def _quantity(value: Any, name: str, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WarehouseError(f"{name} must be an integer.")

    minimum = 0 if allow_zero else 1
    if value < minimum:
        raise WarehouseError(f"{name} must be >= {minimum}.")

    return value


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WarehouseError(f"{name} must be a nonempty string.")
    return value.strip()


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Warehouse:
    warehouse_id: str
    name: str
    location: str
    capacity_units: int
    active: bool = True


@dataclass
class StockMovement:
    movement_id: str
    warehouse_id: str
    product_id: str
    movement_type: str
    quantity: int
    reference_id: str
    created_at: str


class WarehouseManager:
    """
    In-memory warehouse operations manager.

    Uses a reentrant lock to keep local stock updates
    consistent across threads within one Python process.
    """

    def __init__(self) -> None:
        self._warehouses: dict[str, Warehouse] = {}
        self._stock: dict[tuple[str, str], int] = {}
        self._movements: list[StockMovement] = []
        self._lock = threading.RLock()

    def register_warehouse(
        self,
        name: str,
        location: str,
        capacity_units: int,
    ) -> dict[str, Any]:
        name = _identifier(name, "name")
        location = _identifier(location, "location")
        capacity = _quantity(capacity_units, "capacity_units")

        warehouse = Warehouse(
            warehouse_id=str(uuid4()),
            name=name,
            location=location,
            capacity_units=capacity,
        )

        with self._lock:
            self._warehouses[warehouse.warehouse_id] = warehouse

        return {
            "success": True,
            "warehouse": asdict(warehouse),
        }

    def _get_warehouse(self, warehouse_id: str) -> Warehouse:
        warehouse = self._warehouses.get(warehouse_id)

        if warehouse is None:
            raise WarehouseError("Warehouse not found.")

        if not warehouse.active:
            raise WarehouseError("Warehouse is inactive.")

        return warehouse

    def _occupied_units(self, warehouse_id: str) -> int:
        return sum(
            quantity
            for (wid, _), quantity in self._stock.items()
            if wid == warehouse_id
        )

    def get_stock(
        self,
        warehouse_id: str,
        product_id: str,
    ) -> int:
        with self._lock:
            self._get_warehouse(warehouse_id)
            return self._stock.get((warehouse_id, product_id), 0)

    def receive_stock(
        self,
        warehouse_id: str,
        product_id: str,
        quantity: int,
        reference_id: str,
    ) -> dict[str, Any]:
        product_id = _identifier(product_id, "product_id")
        reference_id = _identifier(reference_id, "reference_id")
        quantity = _quantity(quantity, "quantity")

        with self._lock:
            warehouse = self._get_warehouse(warehouse_id)
            occupied = self._occupied_units(warehouse_id)

            if occupied + quantity > warehouse.capacity_units:
                raise WarehouseError(
                    "Receiving would exceed warehouse capacity."
                )

            key = (warehouse_id, product_id)
            self._stock[key] = self._stock.get(key, 0) + quantity

            movement = StockMovement(
                movement_id=str(uuid4()),
                warehouse_id=warehouse_id,
                product_id=product_id,
                movement_type="receive",
                quantity=quantity,
                reference_id=reference_id,
                created_at=_timestamp(),
            )

            self._movements.append(movement)

            return {
                "success": True,
                "movement": asdict(movement),
                "new_stock": self._stock[key],
            }

    def pick_stock(
        self,
        warehouse_id: str,
        product_id: str,
        quantity: int,
        reference_id: str,
    ) -> dict[str, Any]:
        product_id = _identifier(product_id, "product_id")
        reference_id = _identifier(reference_id, "reference_id")
        quantity = _quantity(quantity, "quantity")

        with self._lock:
            self._get_warehouse(warehouse_id)
            key = (warehouse_id, product_id)
            available = self._stock.get(key, 0)

            if available < quantity:
                raise WarehouseError(
                    f"Insufficient stock: available={available}, "
                    f"requested={quantity}."
                )

            self._stock[key] = available - quantity

            movement = StockMovement(
                movement_id=str(uuid4()),
                warehouse_id=warehouse_id,
                product_id=product_id,
                movement_type="pick",
                quantity=quantity,
                reference_id=reference_id,
                created_at=_timestamp(),
            )

            self._movements.append(movement)

            return {
                "success": True,
                "movement": asdict(movement),
                "remaining_stock": self._stock[key],
            }

    def transfer_stock(
        self,
        source_warehouse_id: str,
        destination_warehouse_id: str,
        product_id: str,
        quantity: int,
        reference_id: str,
    ) -> dict[str, Any]:
        if source_warehouse_id == destination_warehouse_id:
            raise WarehouseError(
                "Source and destination must differ."
            )

        product_id = _identifier(product_id, "product_id")
        reference_id = _identifier(reference_id, "reference_id")
        quantity = _quantity(quantity, "quantity")

        with self._lock:
            self._get_warehouse(source_warehouse_id)
            destination = self._get_warehouse(destination_warehouse_id)

            source_key = (source_warehouse_id, product_id)
            destination_key = (destination_warehouse_id, product_id)

            available = self._stock.get(source_key, 0)
            if available < quantity:
                raise WarehouseError("Insufficient source stock.")

            destination_occupied = self._occupied_units(
                destination_warehouse_id
            )

            if destination_occupied + quantity > destination.capacity_units:
                raise WarehouseError(
                    "Destination warehouse capacity exceeded."
                )

            # Both stock changes occur under one process-level lock.
            self._stock[source_key] = available - quantity
            self._stock[destination_key] = (
                self._stock.get(destination_key, 0) + quantity
            )

            movement_out = StockMovement(
                movement_id=str(uuid4()),
                warehouse_id=source_warehouse_id,
                product_id=product_id,
                movement_type="transfer_out",
                quantity=quantity,
                reference_id=reference_id,
                created_at=_timestamp(),
            )

            movement_in = StockMovement(
                movement_id=str(uuid4()),
                warehouse_id=destination_warehouse_id,
                product_id=product_id,
                movement_type="transfer_in",
                quantity=quantity,
                reference_id=reference_id,
                created_at=_timestamp(),
            )

            self._movements.extend([movement_out, movement_in])

            return {
                "success": True,
                "source_stock": self._stock[source_key],
                "destination_stock": self._stock[destination_key],
                "movements": [
                    asdict(movement_out),
                    asdict(movement_in),
                ],
            }

    def warehouse_utilization(
        self,
        warehouse_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            warehouse = self._get_warehouse(warehouse_id)
            occupied = self._occupied_units(warehouse_id)
            capacity = warehouse.capacity_units
            utilization = occupied / capacity * 100

            if utilization >= 95:
                status = "critical"
            elif utilization >= 85:
                status = "high"
            else:
                status = "normal"

            return {
                "warehouse_id": warehouse_id,
                "capacity_units": capacity,
                "occupied_units": occupied,
                "available_capacity_units": capacity - occupied,
                "utilization_percent": round(utilization, 2),
                "status": status,
            }

    def inventory_report(
        self,
        warehouse_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            self._get_warehouse(warehouse_id)

            products = [
                {
                    "product_id": product_id,
                    "quantity": quantity,
                }
                for (wid, product_id), quantity in self._stock.items()
                if wid == warehouse_id
            ]

            return {
                "warehouse_id": warehouse_id,
                "products": sorted(
                    products,
                    key=lambda item: item["product_id"],
                ),
                "total_units": sum(
                    item["quantity"] for item in products
                ),
            }

    def movement_history(
        self,
        warehouse_id: str | None = None,
        product_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        _quantity(limit, "limit")

        with self._lock:
            records = [
                movement
                for movement in self._movements
                if (
                    warehouse_id is None
                    or movement.warehouse_id == warehouse_id
                )
                and (
                    product_id is None
                    or movement.product_id == product_id
                )
            ]

            return [
                asdict(item)
                for item in records[-limit:]
            ]

    def generate_warehouse_alerts(
        self,
        warehouse_id: str,
        reorder_points: dict[str, int] | None = None,
    ) -> list[dict[str, Any]]:
        """Generate capacity and low-stock alerts."""
        with self._lock:
            utilization = self.warehouse_utilization(
                warehouse_id
            )
            alerts = []

            if utilization["status"] in {"high", "critical"}:
                alerts.append({
                    "alert_type": "warehouse_capacity",
                    "severity": utilization["status"],
                    "warehouse_id": warehouse_id,
                    "utilization_percent": utilization[
                        "utilization_percent"
                    ],
                    "requires_review": True,
                })

            for product_id, reorder_point in (
                reorder_points or {}
            ).items():
                _quantity(
                    reorder_point,
                    "reorder_point",
                    allow_zero=True,
                )

                stock = self._stock.get(
                    (warehouse_id, product_id), 0
                )

                if stock <= reorder_point:
                    alerts.append({
                        "alert_type": "low_stock",
                        "severity": "high" if stock == 0 else "medium",
                        "warehouse_id": warehouse_id,
                        "product_id": product_id,
                        "available_stock": stock,
                        "reorder_point": reorder_point,
                        "requires_review": True,
                    })

            return alerts


if __name__ == "__main__":
    manager = WarehouseManager()

    warehouse_a = manager.register_warehouse(
        name="Kochi Distribution Center",
        location="Kochi, Kerala",
        capacity_units=10000,
    )["warehouse"]["warehouse_id"]

    warehouse_b = manager.register_warehouse(
        name="Thrissur Warehouse",
        location="Thrissur, Kerala",
        capacity_units=5000,
    )["warehouse"]["warehouse_id"]

    print(
        manager.receive_stock(
            warehouse_id=warehouse_a,
            product_id="SKU-1001",
            quantity=500,
            reference_id="PO-001",
        )
    )

    print(
        manager.transfer_stock(
            source_warehouse_id=warehouse_a,
            destination_warehouse_id=warehouse_b,
            product_id="SKU-1001",
            quantity=100,
            reference_id="TR-001",
        )
    )

    print(manager.warehouse_utilization(warehouse_a))
    print(manager.inventory_report(warehouse_b))
    print(
        manager.generate_warehouse_alerts(
            warehouse_a,
            reorder_points={"SKU-1001": 450},
        )
    )
