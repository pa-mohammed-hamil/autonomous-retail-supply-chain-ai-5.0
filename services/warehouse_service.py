from __future__ import annotations

"""Planned module: warehouse service. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
backend/services/warehouse_service.py

Python 3.10+ | Standard library only.

Reference implementation.

Features:
- Tenant-isolated warehouse registry
- Warehouse lifecycle management
- Storage bin registration
- Capacity and occupancy control
- SKU-level bin inventory
- Idempotent inbound receiving
- Bin-to-bin stock transfers
- Idempotent outbound picking
- Warehouse inventory summaries
- Role and warehouse-scope checks
- Audit events and JSON export

Limitations:
- In-memory persistence
- Capacity is measured in unit slots
- No lot/serial/expiry tracking
- No physical barcode integration
- No external inventory ledger updates
"""


import copy
import json
import threading
import uuid

from dataclasses import (
    asdict,
    dataclass,
    field,
)
from datetime import (
    datetime,
    timezone,
)
from enum import Enum
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def required_text(
    value: str,
    name: str,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 200
    ):
        raise ValueError(
            f"Invalid {name}"
        )

    return value.strip()


def positive_int(
    value: int,
    name: str,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        raise ValueError(
            f"{name} must be a positive integer"
        )

    return value


class WarehouseStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class WarehouseMovementType(str, Enum):
    RECEIVE = "receive"
    TRANSFER = "transfer"
    PICK = "pick"


@dataclass(frozen=True)
class WarehouseActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str] = (
        frozenset()
    )
    is_active: bool = True


@dataclass
class RetailWarehouse:
    warehouse_id: str
    tenant_id: str
    name: str
    location: str
    capacity_units: int
    status: WarehouseStatus
    created_by: str
    created_at: str
    updated_at: str
    version: int = 1


@dataclass
class WarehouseBin:
    bin_id: str
    tenant_id: str
    warehouse_id: str
    zone: str
    capacity_units: int
    stock: dict[str, int] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class WarehouseMovement:
    movement_id: str
    tenant_id: str
    warehouse_id: str
    movement_type: WarehouseMovementType
    sku: str
    quantity: int
    source_bin_id: str | None
    destination_bin_id: str | None
    reference_id: str
    actor_id: str
    created_at: str


@dataclass(frozen=True)
class WarehouseAuditEvent:
    event_id: str
    tenant_id: str
    warehouse_id: str
    actor_id: str
    action: str
    timestamp: str
    details: dict[str, Any] = field(
        default_factory=dict
    )


class RetailWarehouseService:
    ADMIN_ROLES = frozenset({
        "warehouse_admin",
        "operations_manager",
        "corporate_admin",
    })

    OPERATOR_ROLES = (
        ADMIN_ROLES
        | frozenset({
            "warehouse_manager",
            "warehouse_operator",
        })
    )

    READER_ROLES = (
        OPERATOR_ROLES
        | frozenset({
            "inventory_analyst",
            "logistics_manager",
            "procurement_manager",
        })
    )

    def __init__(
        self,
        tenant_id: str,
    ):
        self.tenant_id = required_text(
            tenant_id,
            "tenant_id",
        )

        self._lock = (
            threading.RLock()
        )

        self._warehouses: dict[
            str, RetailWarehouse
        ] = {}

        self._bins: dict[
            tuple[str, str],
            WarehouseBin,
        ] = {}

        self._movements: dict[
            str, WarehouseMovement
        ] = {}

        self._reference_index: dict[
            tuple[str, str],
            str,
        ] = {}

        self._audit: list[
            WarehouseAuditEvent
        ] = []

    def _authorize(
        self,
        actor: WarehouseActor,
        roles: frozenset[str],
        warehouse_id: str | None = None,
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id
            != self.tenant_id
            or not actor.user_id.strip()
            or not (actor.roles & roles)
        ):
            raise PermissionError(
                "Warehouse access denied"
            )

        if (
            warehouse_id is not None
            and "corporate_admin"
            not in actor.roles
            and warehouse_id
            not in actor.warehouse_ids
        ):
            raise PermissionError(
                "Warehouse scope denied"
            )

    def _warehouse(
        self,
        warehouse_id: str,
    ) -> RetailWarehouse:
        warehouse = (
            self._warehouses.get(
                warehouse_id
            )
        )

        if warehouse is None:
            raise KeyError(
                "Warehouse not found"
            )

        return warehouse

    def _bin(
        self,
        warehouse_id: str,
        bin_id: str,
    ) -> WarehouseBin:
        item = self._bins.get(
            (
                warehouse_id,
                bin_id,
            )
        )

        if item is None:
            raise KeyError(
                "Storage bin not found"
            )

        return item

    @staticmethod
    def _occupied(
        storage_bin: WarehouseBin,
    ) -> int:
        return sum(
            storage_bin.stock.values()
        )

    def _warehouse_occupied(
        self,
        warehouse_id: str,
    ) -> int:
        return sum(
            self._occupied(
                storage_bin
            )
            for (
                wid,
                _,
            ), storage_bin in (
                self._bins.items()
            )
            if wid == warehouse_id
        )

    def _audit_event(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
        action: str,
        details: dict | None = None,
    ) -> None:
        self._audit.append(
            WarehouseAuditEvent(
                event_id=str(
                    uuid.uuid4()
                ),
                tenant_id=self.tenant_id,
                warehouse_id=warehouse_id,
                actor_id=actor.user_id,
                action=action,
                timestamp=utc_now(),
                details=copy.deepcopy(
                    details or {}
                ),
            )
        )

    def register_warehouse(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
        name: str,
        location: str,
        capacity_units: int,
    ) -> RetailWarehouse:
        self._authorize(
            actor,
            self.ADMIN_ROLES,
            warehouse_id,
        )

        warehouse_id = required_text(
            warehouse_id,
            "warehouse_id",
        )

        name = required_text(
            name,
            "name",
        )

        location = required_text(
            location,
            "location",
        )

        capacity_units = positive_int(
            capacity_units,
            "capacity_units",
        )

        with self._lock:
            if warehouse_id in (
                self._warehouses
            ):
                raise ValueError(
                    "Warehouse already exists"
                )

            timestamp = utc_now()

            warehouse = RetailWarehouse(
                warehouse_id=warehouse_id,
                tenant_id=self.tenant_id,
                name=name,
                location=location,
                capacity_units=(
                    capacity_units
                ),
                status=(
                    WarehouseStatus.ACTIVE
                ),
                created_by=actor.user_id,
                created_at=timestamp,
                updated_at=timestamp,
            )

            self._warehouses[
                warehouse_id
            ] = warehouse

            self._audit_event(
                actor,
                warehouse_id,
                "warehouse_registered",
            )

            return copy.deepcopy(
                warehouse
            )

    def register_bin(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
        bin_id: str,
        zone: str,
        capacity_units: int,
    ) -> WarehouseBin:
        self._authorize(
            actor,
            self.ADMIN_ROLES,
            warehouse_id,
        )

        bin_id = required_text(
            bin_id,
            "bin_id",
        )

        zone = required_text(
            zone,
            "zone",
        )

        capacity_units = positive_int(
            capacity_units,
            "capacity_units",
        )

        with self._lock:
            warehouse = self._warehouse(
                warehouse_id
            )

            if warehouse.status != (
                WarehouseStatus.ACTIVE
            ):
                raise ValueError(
                    "Warehouse is inactive"
                )

            key = (
                warehouse_id,
                bin_id,
            )

            if key in self._bins:
                raise ValueError(
                    "Bin already exists"
                )

            allocated_capacity = sum(
                item.capacity_units
                for (
                    wid,
                    _,
                ), item in (
                    self._bins.items()
                )
                if wid == warehouse_id
            )

            if (
                allocated_capacity
                + capacity_units
                > warehouse.capacity_units
            ):
                raise ValueError(
                    "Warehouse capacity allocation exceeded"
                )

            storage_bin = WarehouseBin(
                bin_id=bin_id,
                tenant_id=self.tenant_id,
                warehouse_id=warehouse_id,
                zone=zone,
                capacity_units=(
                    capacity_units
                ),
            )

            self._bins[
                key
            ] = storage_bin

            self._audit_event(
                actor,
                warehouse_id,
                "bin_registered",
                {
                    "bin_id": bin_id,
                    "capacity_units": (
                        capacity_units
                    ),
                },
            )

            return copy.deepcopy(
                storage_bin
            )

    def _record_movement(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
        movement_type: (
            WarehouseMovementType
        ),
        sku: str,
        quantity: int,
        source_bin_id: str | None,
        destination_bin_id: str | None,
        reference_id: str,
    ) -> WarehouseMovement:
        movement = WarehouseMovement(
            movement_id=str(
                uuid.uuid4()
            ),
            tenant_id=self.tenant_id,
            warehouse_id=warehouse_id,
            movement_type=movement_type,
            sku=sku,
            quantity=quantity,
            source_bin_id=(
                source_bin_id
            ),
            destination_bin_id=(
                destination_bin_id
            ),
            reference_id=reference_id,
            actor_id=actor.user_id,
            created_at=utc_now(),
        )

        self._movements[
            movement.movement_id
        ] = movement

        self._reference_index[
            (
                warehouse_id,
                reference_id,
            )
        ] = movement.movement_id

        self._audit_event(
            actor,
            warehouse_id,
            f"stock_{movement_type.value}",
            {
                "sku": sku,
                "quantity": quantity,
                "reference_id": (
                    reference_id
                ),
            },
        )

        return movement

    def _existing_reference(
        self,
        warehouse_id: str,
        reference_id: str,
        movement_type: (
            WarehouseMovementType
        ),
        sku: str,
        quantity: int,
        source_bin_id: str | None,
        destination_bin_id: str | None,
    ) -> WarehouseMovement | None:
        movement_id = (
            self._reference_index.get(
                (
                    warehouse_id,
                    reference_id,
                )
            )
        )

        if movement_id is None:
            return None

        existing = (
            self._movements[
                movement_id
            ]
        )

        if (
            existing.movement_type
            != movement_type
            or existing.sku != sku
            or existing.quantity
            != quantity
            or existing.source_bin_id
            != source_bin_id
            or existing.destination_bin_id
            != destination_bin_id
        ):
            raise ValueError(
                "Movement reference conflict"
            )

        return copy.deepcopy(
            existing
        )

    def receive_stock(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
        bin_id: str,
        sku: str,
        quantity: int,
        reference_id: str,
    ) -> WarehouseMovement:
        self._authorize(
            actor,
            self.OPERATOR_ROLES,
            warehouse_id,
        )

        sku = required_text(
            sku,
            "sku",
        )

        reference_id = required_text(
            reference_id,
            "reference_id",
        )

        positive_int(
            quantity,
            "quantity",
        )

        with self._lock:
            existing = (
                self._existing_reference(
                    warehouse_id,
                    reference_id,
                    WarehouseMovementType.RECEIVE,
                    sku,
                    quantity,
                    None,
                    bin_id,
                )
            )

            if existing:
                return existing

            warehouse = self._warehouse(
                warehouse_id
            )

            if warehouse.status != (
                WarehouseStatus.ACTIVE
            ):
                raise ValueError(
                    "Warehouse is inactive"
                )

            storage_bin = self._bin(
                warehouse_id,
                bin_id,
            )

            if (
                self._occupied(
                    storage_bin
                )
                + quantity
                > storage_bin.capacity_units
            ):
                raise ValueError(
                    "Bin capacity exceeded"
                )

            storage_bin.stock[
                sku
            ] = (
                storage_bin.stock.get(
                    sku,
                    0,
                )
                + quantity
            )

            movement = (
                self._record_movement(
                    actor,
                    warehouse_id,
                    WarehouseMovementType.RECEIVE,
                    sku,
                    quantity,
                    None,
                    bin_id,
                    reference_id,
                )
            )

            return copy.deepcopy(
                movement
            )

    def transfer_stock(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
        source_bin_id: str,
        destination_bin_id: str,
        sku: str,
        quantity: int,
        reference_id: str,
    ) -> WarehouseMovement:
        self._authorize(
            actor,
            self.OPERATOR_ROLES,
            warehouse_id,
        )

        sku = required_text(
            sku,
            "sku",
        )

        reference_id = required_text(
            reference_id,
            "reference_id",
        )

        positive_int(
            quantity,
            "quantity",
        )

        if source_bin_id == (
            destination_bin_id
        ):
            raise ValueError(
                "Source and destination must differ"
            )

        with self._lock:
            existing = (
                self._existing_reference(
                    warehouse_id,
                    reference_id,
                    WarehouseMovementType.TRANSFER,
                    sku,
                    quantity,
                    source_bin_id,
                    destination_bin_id,
                )
            )

            if existing:
                return existing

            warehouse = self._warehouse(
                warehouse_id
            )

            if warehouse.status != (
                WarehouseStatus.ACTIVE
            ):
                raise ValueError(
                    "Warehouse is inactive"
                )

            source = self._bin(
                warehouse_id,
                source_bin_id,
            )

            destination = self._bin(
                warehouse_id,
                destination_bin_id,
            )

            if source.stock.get(
                sku,
                0,
            ) < quantity:
                raise ValueError(
                    "Insufficient source stock"
                )

            if (
                self._occupied(
                    destination
                )
                + quantity
                > destination.capacity_units
            ):
                raise ValueError(
                    "Destination bin full"
                )

            source.stock[
                sku
            ] -= quantity

            if source.stock[
                sku
            ] == 0:
                del source.stock[
                    sku
                ]

            destination.stock[
                sku
            ] = (
                destination.stock.get(
                    sku,
                    0,
                )
                + quantity
            )

            movement = (
                self._record_movement(
                    actor,
                    warehouse_id,
                    WarehouseMovementType.TRANSFER,
                    sku,
                    quantity,
                    source_bin_id,
                    destination_bin_id,
                    reference_id,
                )
            )

            return copy.deepcopy(
                movement
            )

    def pick_stock(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
        bin_id: str,
        sku: str,
        quantity: int,
        reference_id: str,
    ) -> WarehouseMovement:
        self._authorize(
            actor,
            self.OPERATOR_ROLES,
            warehouse_id,
        )

        sku = required_text(
            sku,
            "sku",
        )

        reference_id = required_text(
            reference_id,
            "reference_id",
        )

        positive_int(
            quantity,
            "quantity",
        )

        with self._lock:
            existing = (
                self._existing_reference(
                    warehouse_id,
                    reference_id,
                    WarehouseMovementType.PICK,
                    sku,
                    quantity,
                    bin_id,
                    None,
                )
            )

            if existing:
                return existing

            warehouse = self._warehouse(
                warehouse_id
            )

            if warehouse.status != (
                WarehouseStatus.ACTIVE
            ):
                raise ValueError(
                    "Warehouse is inactive"
                )

            storage_bin = self._bin(
                warehouse_id,
                bin_id,
            )

            if storage_bin.stock.get(
                sku,
                0,
            ) < quantity:
                raise ValueError(
                    "Insufficient stock"
                )

            storage_bin.stock[
                sku
            ] -= quantity

            if storage_bin.stock[
                sku
            ] == 0:
                del storage_bin.stock[
                    sku
                ]

            movement = (
                self._record_movement(
                    actor,
                    warehouse_id,
                    WarehouseMovementType.PICK,
                    sku,
                    quantity,
                    bin_id,
                    None,
                    reference_id,
                )
            )

            return copy.deepcopy(
                movement
            )

    def get_warehouse(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
    ) -> RetailWarehouse:
        self._authorize(
            actor,
            self.READER_ROLES,
            warehouse_id,
        )

        with self._lock:
            return copy.deepcopy(
                self._warehouse(
                    warehouse_id
                )
            )

    def list_warehouses(
        self,
        actor: WarehouseActor,
    ) -> list[RetailWarehouse]:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        with self._lock:
            return [
                copy.deepcopy(
                    warehouse
                )
                for warehouse in (
                    self._warehouses.values()
                )
                if (
                    "corporate_admin"
                    in actor.roles
                    or warehouse.warehouse_id
                    in actor.warehouse_ids
                )
            ]

    def bin_inventory(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
    ) -> list[WarehouseBin]:
        self._authorize(
            actor,
            self.READER_ROLES,
            warehouse_id,
        )

        with self._lock:
            self._warehouse(
                warehouse_id
            )

            return [
                copy.deepcopy(
                    storage_bin
                )
                for (
                    wid,
                    _,
                ), storage_bin in (
                    self._bins.items()
                )
                if wid == warehouse_id
            ]

    def warehouse_metrics(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
    ) -> dict:
        self._authorize(
            actor,
            self.READER_ROLES,
            warehouse_id,
        )

        with self._lock:
            warehouse = self._warehouse(
                warehouse_id
            )

            bins = [
                storage_bin
                for (
                    wid,
                    _,
                ), storage_bin in (
                    self._bins.items()
                )
                if wid == warehouse_id
            ]

            occupied = sum(
                self._occupied(
                    storage_bin
                )
                for storage_bin in bins
            )

            inventory: dict[
                str, int
            ] = {}

            for storage_bin in bins:
                for sku, quantity in (
                    storage_bin.stock.items()
                ):
                    inventory[
                        sku
                    ] = (
                        inventory.get(
                            sku,
                            0,
                        )
                        + quantity
                    )

            return {
                "tenant_id": self.tenant_id,
                "warehouse_id": (
                    warehouse_id
                ),
                "warehouse_name": (
                    warehouse.name
                ),
                "status": (
                    warehouse.status.value
                ),
                "capacity_units": (
                    warehouse.capacity_units
                ),
                "occupied_units": (
                    occupied
                ),
                "available_units": (
                    warehouse.capacity_units
                    - occupied
                ),
                "utilization_pct": round(
                    occupied
                    / warehouse.capacity_units
                    * 100,
                    2,
                ),
                "bin_count": len(
                    bins
                ),
                "sku_count": len(
                    inventory
                ),
                "inventory": inventory,
            }

    def movement_history(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
    ) -> list[WarehouseMovement]:
        self._authorize(
            actor,
            self.READER_ROLES,
            warehouse_id,
        )

        with self._lock:
            return [
                copy.deepcopy(
                    movement
                )
                for movement in (
                    self._movements.values()
                )
                if movement.warehouse_id == (
                    warehouse_id
                )
            ]

    def audit_events(
        self,
        actor: WarehouseActor,
        warehouse_id: str,
    ) -> list[WarehouseAuditEvent]:
        self._authorize(
            actor,
            self.READER_ROLES,
            warehouse_id,
        )

        with self._lock:
            return [
                copy.deepcopy(
                    event
                )
                for event in (
                    self._audit
                )
                if event.warehouse_id == (
                    warehouse_id
                )
            ]

    def export_json(
        self,
        actor: WarehouseActor,
        output_path: str | Path,
    ) -> Path:
        warehouses = (
            self.list_warehouses(
                actor
            )
        )

        payload = []

        for warehouse in warehouses:
            payload.append({
                "warehouse": asdict(
                    warehouse
                ),
                "metrics": (
                    self.warehouse_metrics(
                        actor,
                        warehouse.warehouse_id,
                    )
                ),
                "bins": [
                    asdict(
                        storage_bin
                    )
                    for storage_bin in (
                        self.bin_inventory(
                            actor,
                            warehouse.warehouse_id,
                        )
                    )
                ],
            })

        output = Path(
            output_path
        )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            json.dumps(
                payload,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        return output


if __name__ == "__main__":
    service = RetailWarehouseService(
        tenant_id="demo"
    )

    admin = WarehouseActor(
        user_id="warehouse-admin",
        tenant_id="demo",
        roles=frozenset({
            "warehouse_admin",
        }),
        warehouse_ids=frozenset({
            "WH001",
        }),
    )

    service.register_warehouse(
        actor=admin,
        warehouse_id="WH001",
        name="Kochi Distribution Center",
        location="Kochi, Kerala",
        capacity_units=1000,
    )

    service.register_bin(
        actor=admin,
        warehouse_id="WH001",
        bin_id="BIN-A1",
        zone="A",
        capacity_units=300,
    )

    service.register_bin(
        actor=admin,
        warehouse_id="WH001",
        bin_id="BIN-B1",
        zone="B",
        capacity_units=300,
    )

    service.receive_stock(
        actor=admin,
        warehouse_id="WH001",
        bin_id="BIN-A1",
        sku="SKU001",
        quantity=120,
        reference_id="GRN001",
    )

    service.transfer_stock(
        actor=admin,
        warehouse_id="WH001",
        source_bin_id="BIN-A1",
        destination_bin_id="BIN-B1",
        sku="SKU001",
        quantity=40,
        reference_id="MOVE001",
    )

    service.pick_stock(
        actor=admin,
        warehouse_id="WH001",
        bin_id="BIN-B1",
        sku="SKU001",
        quantity=15,
        reference_id="PICK001",
    )

    print(
        json.dumps(
            service.warehouse_metrics(
                admin,
                "WH001",
            ),
            indent=2,
        )
    )
