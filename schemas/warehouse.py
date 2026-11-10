from __future__ import annotations

"""Planned module: warehouse. Implementation pending."""

"""
backend/services/warehouse_service.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+ | Standard library only

Reference warehouse management service.

Features:
- Multi-tenant warehouse registry
- Warehouse-scoped RBAC
- Bin registration and capacity
- SKU stock receiving
- Bin-to-bin / warehouse transfers
- Stock picking
- Movement idempotency
- Capacity and utilization analytics
- Audit events
- JSON export

Not connected to a live database or WMS.
"""


import copy
import json
import threading
import uuid

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def text(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 255
    ):
        raise ValueError(f"Invalid {name}")
    return value.strip()


def positive_int(value: int, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


class WarehouseStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class MovementType(str, Enum):
    RECEIVE = "receive"
    TRANSFER_OUT = "transfer_out"
    TRANSFER_IN = "transfer_in"
    PICK = "pick"


@dataclass(frozen=True)
class WarehouseActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str] = frozenset()
    is_active: bool = True


@dataclass
class Warehouse:
    warehouse_id: str
    tenant_id: str
    name: str
    location: str
    status: WarehouseStatus
    created_at: str


@dataclass
class StorageBin:
    bin_id: str
    warehouse_id: str
    capacity_units: int
    stock: dict[str, int] = field(default_factory=dict)

    @property
    def occupied_units(self) -> int:
        return sum(self.stock.values())

    @property
    def available_capacity(self) -> int:
        return self.capacity_units - self.occupied_units


@dataclass(frozen=True)
class WarehouseMovement:
    movement_id: str
    tenant_id: str
    warehouse_id: str
    bin_id: str
    sku: str
    movement_type: MovementType
    quantity: int
    reference_id: str
    actor_id: str
    timestamp: str


@dataclass(frozen=True)
class WarehouseAuditEvent:
    event_id: str
    tenant_id: str
    actor_id: str
    action: str
    warehouse_id: str
    timestamp: str
    details: dict[str, Any] = field(default_factory=dict)


class RetailWarehouseService:
    ADMIN_ROLES = frozenset({
        "corporate_admin",
        "operations_manager",
    })

    WRITER_ROLES = ADMIN_ROLES | frozenset({
        "warehouse_manager",
        "inventory_manager",
        "warehouse_operator",
    })

    READER_ROLES = WRITER_ROLES | frozenset({
        "inventory_analyst",
        "logistics_manager",
        "business_analyst",
    })

    def __init__(self, tenant_id: str):
        self.tenant_id = text(tenant_id, "tenant_id")
        self._lock = threading.RLock()
        self._warehouses: dict[str, Warehouse] = {}
        self._bins: dict[tuple[str, str], StorageBin] = {}
        self._movements: list[WarehouseMovement] = []
        self._reference_index: dict[
            str, tuple[Any, ...]
        ] = {}
        self._audit: list[WarehouseAuditEvent] = []

    def _authorize(
        self,
        actor: WarehouseActor,
        roles: frozenset[str],
        warehouse_id: str | None = None,
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.user_id.strip()
            or not actor.roles.intersection(roles)
        ):
            raise PermissionError("Warehouse access denied")

        if warehouse_id is not None:
            if (
                "corporate_admin" not in actor.roles
                and warehouse_id not in actor.warehouse_ids
            ):
                raise PermissionError("Warehouse scope denied")

    def _get_warehouse(self, warehouse_id: str) -> Warehouse:
        warehouse = self._warehouses.get(warehouse_id)
        if warehouse is None:
            raise KeyError("Warehouse not found")
        return warehouse

    def _get_bin(
        self, warehouse_id: str, bin_id: str
    ) -> StorageBin:
        bin_record = self._bins.get((warehouse_id, bin_id))
        if bin_record is None:
            raise KeyError("Storage bin not found")
        return bin_record

    def _ensure_active(self, warehouse_id: str) -> None:
        if (
            self._get_warehouse(warehouse_id).status
            != WarehouseStatus.ACTIVE
        ):
            raise ValueError("Warehouse is inactive")

    def _audit_event(
        self,
        actor: WarehouseActor,
        action: str,
        warehouse_id: str,
        details: dict | None = None,
    ) -> None:
        self._audit.append(WarehouseAuditEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            actor_id=actor.user_id,
            action=action,
            warehouse_id=warehouse_id,
            timestamp=now_utc(),
            details=copy.deepcopy(details or {}),
        ))

    def _movement(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
        bin_id: str,
        sku: str,
        kind: MovementType,
        quantity: int,
        reference_id: str,
    ) -> None:
        self._movements.append(WarehouseMovement(
            movement_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            warehouse_id=warehouse_id,
            bin_id=bin_id,
            sku=sku,
            movement_type=kind,
            quantity=quantity,
            reference_id=reference_id,
            actor_id=actor.user_id,
            timestamp=now_utc(),
        ))

    def register_warehouse(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
        name: str,
        location: str,
    ) -> Warehouse:
        self._authorize(actor, self.ADMIN_ROLES)

        warehouse_id = text(warehouse_id, "warehouse_id")
        name = text(name, "name")
        location = text(location, "location")

        with self._lock:
            if warehouse_id in self._warehouses:
                raise ValueError("Warehouse already exists")

            warehouse = Warehouse(
                warehouse_id=warehouse_id,
                tenant_id=self.tenant_id,
                name=name,
                location=location,
                status=WarehouseStatus.ACTIVE,
                created_at=now_utc(),
            )

            self._warehouses[warehouse_id] = warehouse
            self._audit_event(
                actor, "warehouse_registered", warehouse_id
            )
            return copy.deepcopy(warehouse)

    def register_bin(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
        bin_id: str,
        capacity_units: int,
    ) -> StorageBin:
        self._authorize(
            actor, self.WRITER_ROLES, warehouse_id
        )
        bin_id = text(bin_id, "bin_id")
        positive_int(capacity_units, "capacity_units")

        with self._lock:
            self._ensure_active(warehouse_id)
            key = (warehouse_id, bin_id)

            if key in self._bins:
                raise ValueError("Bin already exists")

            bin_record = StorageBin(
                bin_id=bin_id,
                warehouse_id=warehouse_id,
                capacity_units=capacity_units,
            )

            self._bins[key] = bin_record
            self._audit_event(
                actor,
                "bin_registered",
                warehouse_id,
                {"bin_id": bin_id},
            )
            return copy.deepcopy(bin_record)

    def receive_stock(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
        bin_id: str,
        sku: str,
        quantity: int,
        reference_id: str,
    ) -> StorageBin:
        self._authorize(
            actor, self.WRITER_ROLES, warehouse_id
        )

        sku = text(sku, "sku")
        reference_id = text(reference_id, "reference_id")
        positive_int(quantity, "quantity")

        signature = (
            "receive", warehouse_id, bin_id, sku, quantity
        )

        with self._lock:
            if reference_id in self._reference_index:
                if self._reference_index[reference_id] != signature:
                    raise ValueError("Conflicting reference")
                return copy.deepcopy(
                    self._get_bin(warehouse_id, bin_id)
                )

            self._ensure_active(warehouse_id)
            bin_record = self._get_bin(
                warehouse_id, bin_id
            )

            if quantity > bin_record.available_capacity:
                raise ValueError("Insufficient bin capacity")

            bin_record.stock[sku] = (
                bin_record.stock.get(sku, 0) + quantity
            )

            self._reference_index[reference_id] = signature
            self._movement(
                actor, warehouse_id, bin_id, sku,
                MovementType.RECEIVE, quantity, reference_id,
            )
            self._audit_event(
                actor,
                "stock_received",
                warehouse_id,
                {"sku": sku, "quantity": quantity},
            )
            return copy.deepcopy(bin_record)

    def transfer_stock(
        self,
        actor: WarehouseActor,
        source_warehouse: str,
        source_bin: str,
        destination_warehouse: str,
        destination_bin: str,
        sku: str,
        quantity: int,
        reference_id: str,
    ) -> tuple[StorageBin, StorageBin]:
        self._authorize(
            actor, self.WRITER_ROLES, source_warehouse
        )
        self._authorize(
            actor, self.WRITER_ROLES, destination_warehouse
        )

        sku = text(sku, "sku")
        reference_id = text(reference_id, "reference_id")
        positive_int(quantity, "quantity")

        source_key = (source_warehouse, source_bin)
        destination_key = (
            destination_warehouse, destination_bin
        )

        if source_key == destination_key:
            raise ValueError("Source and destination identical")

        signature = (
            "transfer", source_key, destination_key,
            sku, quantity,
        )

        with self._lock:
            if reference_id in self._reference_index:
                if self._reference_index[reference_id] != signature:
                    raise ValueError("Conflicting reference")
                return (
                    copy.deepcopy(self._get_bin(*source_key)),
                    copy.deepcopy(self._get_bin(*destination_key)),
                )

            self._ensure_active(source_warehouse)
            self._ensure_active(destination_warehouse)

            source = self._get_bin(*source_key)
            destination = self._get_bin(*destination_key)

            if source.stock.get(sku, 0) < quantity:
                raise ValueError("Insufficient source stock")

            if destination.available_capacity < quantity:
                raise ValueError(
                    "Insufficient destination capacity"
                )

            source.stock[sku] -= quantity
            if source.stock[sku] == 0:
                del source.stock[sku]

            destination.stock[sku] = (
                destination.stock.get(sku, 0) + quantity
            )

            self._reference_index[reference_id] = signature

            self._movement(
                actor, source_warehouse, source_bin, sku,
                MovementType.TRANSFER_OUT,
                quantity, reference_id,
            )
            self._movement(
                actor, destination_warehouse, destination_bin,
                sku, MovementType.TRANSFER_IN,
                quantity, reference_id,
            )

            self._audit_event(
                actor, "stock_transferred",
                source_warehouse,
                {
                    "destination_warehouse": destination_warehouse,
                    "sku": sku,
                    "quantity": quantity,
                },
            )

            return (
                copy.deepcopy(source),
                copy.deepcopy(destination),
            )

    def pick_stock(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
        bin_id: str,
        sku: str,
        quantity: int,
        reference_id: str,
    ) -> StorageBin:
        self._authorize(
            actor, self.WRITER_ROLES, warehouse_id
        )

        sku = text(sku, "sku")
        reference_id = text(reference_id, "reference_id")
        positive_int(quantity, "quantity")

        signature = (
            "pick", warehouse_id, bin_id, sku, quantity
        )

        with self._lock:
            if reference_id in self._reference_index:
                if self._reference_index[reference_id] != signature:
                    raise ValueError("Conflicting reference")
                return copy.deepcopy(
                    self._get_bin(warehouse_id, bin_id)
                )

            self._ensure_active(warehouse_id)
            bin_record = self._get_bin(
                warehouse_id, bin_id
            )

            if bin_record.stock.get(sku, 0) < quantity:
                raise ValueError("Insufficient stock")

            bin_record.stock[sku] -= quantity
            if bin_record.stock[sku] == 0:
                del bin_record.stock[sku]

            self._reference_index[reference_id] = signature
            self._movement(
                actor, warehouse_id, bin_id, sku,
                MovementType.PICK, quantity, reference_id,
            )
            self._audit_event(
                actor,
                "stock_picked",
                warehouse_id,
                {"sku": sku, "quantity": quantity},
            )

            return copy.deepcopy(bin_record)

    def get_warehouse(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
    ) -> Warehouse:
        self._authorize(
            actor, self.READER_ROLES, warehouse_id
        )

        with self._lock:
            return copy.deepcopy(
                self._get_warehouse(warehouse_id)
            )

    def list_warehouses(
        self,
        actor: WarehouseActor,
    ) -> list[Warehouse]:
        self._authorize(actor, self.READER_ROLES)

        with self._lock:
            return [
                copy.deepcopy(warehouse)
                for warehouse in self._warehouses.values()
                if (
                    "corporate_admin" in actor.roles
                    or warehouse.warehouse_id in actor.warehouse_ids
                )
            ]

    def bin_inventory(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
    ) -> list[StorageBin]:
        self._authorize(
            actor, self.READER_ROLES, warehouse_id
        )

        with self._lock:
            self._get_warehouse(warehouse_id)

            return [
                copy.deepcopy(bin_record)
                for (wid, _), bin_record in self._bins.items()
                if wid == warehouse_id
            ]

    def warehouse_metrics(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
    ) -> dict[str, Any]:
        bins = self.bin_inventory(actor, warehouse_id)

        capacity = sum(
            bin_record.capacity_units
            for bin_record in bins
        )
        occupied = sum(
            bin_record.occupied_units
            for bin_record in bins
        )

        return {
            "warehouse_id": warehouse_id,
            "total_bins": len(bins),
            "capacity_units": capacity,
            "occupied_units": occupied,
            "available_units": capacity - occupied,
            "utilization_pct": (
                round(occupied / capacity * 100, 2)
                if capacity else 0.0
            ),
            "sku_count": len({
                sku
                for bin_record in bins
                for sku in bin_record.stock
            }),
        }

    def movement_history(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
        sku: str | None = None,
    ) -> list[WarehouseMovement]:
        self._authorize(
            actor, self.READER_ROLES, warehouse_id
        )

        with self._lock:
            return [
                copy.deepcopy(movement)
                for movement in self._movements
                if (
                    movement.warehouse_id == warehouse_id
                    and (sku is None or movement.sku == sku)
                )
            ]

    def audit_events(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
    ) -> list[WarehouseAuditEvent]:
        self._authorize(
            actor, self.READER_ROLES, warehouse_id
        )

        with self._lock:
            return [
                copy.deepcopy(event)
                for event in self._audit
                if event.warehouse_id == warehouse_id
            ]

    def export_json(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
        output_path: str | Path,
    ) -> Path:
        warehouse = self.get_warehouse(
            actor, warehouse_id
        )
        bins = self.bin_inventory(
            actor, warehouse_id
        )

        payload = {
            "warehouse": asdict(warehouse),
            "bins": [asdict(b) for b in bins],
            "metrics": self.warehouse_metrics(
                actor, warehouse_id
            ),
        }

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    service = RetailWarehouseService("demo")

    admin = WarehouseActor(
        user_id="ADMIN001",
        tenant_id="demo",
        roles=frozenset({"corporate_admin"}),
    )

    service.register_warehouse(
        admin, "WH001", "Central Warehouse", "Kochi"
    )

    service.register_warehouse(
        admin, "WH002", "North Warehouse", "Kozhikode"
    )

    service.register_bin(admin, "WH001", "A01", 500)
    service.register_bin(admin, "WH002", "B01", 400)

    service.receive_stock(
        admin, "WH001", "A01",
        "SKU001", 300, "GRN001"
    )

    service.transfer_stock(
        admin,
        "WH001", "A01",
        "WH002", "B01",
        "SKU001", 100, "TRANSFER001",
    )

    service.pick_stock(
        admin, "WH002", "B01",
        "SKU001", 20, "PICK001",
    )

    print(
        "WH001:",
        service.warehouse_metrics(admin, "WH001"),
    )

    print(
        "WH002:",
        service.warehouse_metrics(admin, "WH002"),
    )
