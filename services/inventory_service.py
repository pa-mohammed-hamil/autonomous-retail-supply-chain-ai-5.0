from __future__ import annotations

"""Planned module: inventory service. Implementation pending."""

"""
backend/services/inventory_service.py

Autonomous Retail Supply Chain AI 5.0

Inventory Management Service
Python 3.10+ | Standard library only

Features:
- Tenant-aware stock management
- Warehouse and SKU balances
- Available, reserved and on-hand stock
- Idempotent inventory receipts
- Order reservation and release
- Fulfillment stock consumption
- Warehouse-to-warehouse transfers
- Stock adjustment with approval reference
- Low-stock and reorder calculations
- Immutable movement audit records
- JSON export

Reference implementation only.
Uses in-memory storage and trusted
authenticated actor objects.

Production requires PostgreSQL,
transactional inventory locking,
durable audit logs and authorization.
"""


import copy
import json
import math
import threading
import uuid

from dataclasses import (
    asdict,
    dataclass,
)
from datetime import (
    datetime,
    timezone,
)
from enum import Enum
from pathlib import Path
from typing import Any


def now_utc() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def nonnegative_int(
    value: int,
    name: str,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        raise ValueError(
            f"{name} must be a nonnegative integer"
        )

    return value


def positive_int(
    value: int,
    name: str,
) -> int:
    nonnegative_int(value, name)

    if value == 0:
        raise ValueError(
            f"{name} must be positive"
        )

    return value


def identifier(
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


class InventoryMovementType(str, Enum):
    RECEIPT = "receipt"
    RESERVATION = "reservation"
    RELEASE = "release"
    FULFILLMENT = "fulfillment"
    TRANSFER_OUT = "transfer_out"
    TRANSFER_IN = "transfer_in"
    ADJUSTMENT = "adjustment"


@dataclass(frozen=True)
class InventoryActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str] = frozenset()
    is_active: bool = True


@dataclass
class InventoryBalance:
    tenant_id: str
    warehouse_id: str
    sku: str
    on_hand: int = 0
    reserved: int = 0
    reorder_point: int = 0
    safety_stock: int = 0
    version: int = 0

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved


@dataclass(frozen=True)
class InventoryMovement:
    movement_id: str
    tenant_id: str
    warehouse_id: str
    sku: str
    movement_type: InventoryMovementType
    quantity: int
    reference_id: str
    actor_id: str
    timestamp: str
    on_hand_after: int
    reserved_after: int


@dataclass(frozen=True)
class InventoryReservation:
    reservation_id: str
    tenant_id: str
    warehouse_id: str
    sku: str
    quantity: int
    reference_id: str
    status: str
    created_at: str


@dataclass(frozen=True)
class InventoryTransfer:
    transfer_id: str
    tenant_id: str
    source_warehouse: str
    destination_warehouse: str
    sku: str
    quantity: int
    reference_id: str
    created_at: str


class RetailInventoryService:
    MANAGER_ROLES = frozenset({
        "inventory_manager",
        "warehouse_manager",
        "corporate_admin",
    })

    WORKER_ROLES = frozenset({
        "inventory_worker",
        "warehouse_staff",
        "warehouse_manager",
        "corporate_admin",
    })

    READER_ROLES = (
        MANAGER_ROLES
        | WORKER_ROLES
        | frozenset({
            "inventory_analyst",
        })
    )

    def __init__(
        self,
        tenant_id: str,
    ):
        self.tenant_id = identifier(
            tenant_id,
            "tenant_id",
        )

        self._lock = threading.RLock()

        self._balances: dict[
            tuple[str, str],
            InventoryBalance,
        ] = {}

        self._movements: list[
            InventoryMovement
        ] = []

        self._reservations: dict[
            str, InventoryReservation
        ] = {}

        self._reservation_refs: dict[
            tuple[str, str, str],
            str,
        ] = {}

        self._operation_refs: dict[
            tuple[str, str],
            tuple[Any, ...],
        ] = {}

        self._transfers: dict[
            str, InventoryTransfer
        ] = {}

    def _authorize(
        self,
        actor: InventoryActor,
        roles: frozenset[str],
        warehouses: tuple[str, ...],
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id
            != self.tenant_id
            or not actor.user_id.strip()
            or not (actor.roles & roles)
        ):
            raise PermissionError(
                "Inventory access denied"
            )

        if "corporate_admin" in actor.roles:
            return

        for warehouse in warehouses:
            if warehouse not in (
                actor.warehouse_ids
            ):
                raise PermissionError(
                    "Warehouse access denied"
                )

    def _balance(
        self,
        warehouse_id: str,
        sku: str,
    ) -> InventoryBalance:
        balance = self._balances.get(
            (warehouse_id, sku)
        )

        if balance is None:
            raise KeyError(
                "Inventory balance not found"
            )

        return balance

    def _movement(
        self,
        actor: InventoryActor,
        balance: InventoryBalance,
        kind: InventoryMovementType,
        quantity: int,
        reference_id: str,
    ) -> None:
        self._movements.append(
            InventoryMovement(
                movement_id=str(uuid.uuid4()),
                tenant_id=self.tenant_id,
                warehouse_id=balance.warehouse_id,
                sku=balance.sku,
                movement_type=kind,
                quantity=quantity,
                reference_id=reference_id,
                actor_id=actor.user_id,
                timestamp=now_utc(),
                on_hand_after=balance.on_hand,
                reserved_after=balance.reserved,
            )
        )

    def _check_operation(
        self,
        kind: str,
        reference_id: str,
        signature: tuple[Any, ...],
    ) -> bool:
        key = (kind, reference_id)

        existing = self._operation_refs.get(
            key
        )

        if existing is not None:
            if existing != signature:
                raise ValueError(
                    "Idempotency reference conflict"
                )

            return True

        return False

    def create_balance(
        self,
        actor: InventoryActor,
        warehouse_id: str,
        sku: str,
        initial_stock: int = 0,
        reorder_point: int = 0,
        safety_stock: int = 0,
    ) -> InventoryBalance:
        warehouse_id = identifier(
            warehouse_id,
            "warehouse_id",
        )

        sku = identifier(sku, "sku")

        self._authorize(
            actor,
            self.MANAGER_ROLES,
            (warehouse_id,),
        )

        nonnegative_int(
            initial_stock,
            "initial_stock",
        )

        nonnegative_int(
            reorder_point,
            "reorder_point",
        )

        nonnegative_int(
            safety_stock,
            "safety_stock",
        )

        with self._lock:
            key = (warehouse_id, sku)

            if key in self._balances:
                raise ValueError(
                    "Balance already exists"
                )

            balance = InventoryBalance(
                tenant_id=self.tenant_id,
                warehouse_id=warehouse_id,
                sku=sku,
                on_hand=initial_stock,
                reorder_point=reorder_point,
                safety_stock=safety_stock,
                version=1,
            )

            self._balances[key] = balance

            if initial_stock:
                self._movement(
                    actor,
                    balance,
                    InventoryMovementType.RECEIPT,
                    initial_stock,
                    f"opening:{warehouse_id}:{sku}",
                )

            return copy.deepcopy(
                balance
            )

    def get_balance(
        self,
        actor: InventoryActor,
        warehouse_id: str,
        sku: str,
    ) -> InventoryBalance:
        self._authorize(
            actor,
            self.READER_ROLES,
            (warehouse_id,),
        )

        with self._lock:
            return copy.deepcopy(
                self._balance(
                    warehouse_id,
                    sku,
                )
            )

    def receive_stock(
        self,
        actor: InventoryActor,
        warehouse_id: str,
        sku: str,
        quantity: int,
        reference_id: str,
    ) -> InventoryBalance:
        self._authorize(
            actor,
            self.WORKER_ROLES,
            (warehouse_id,),
        )

        positive_int(
            quantity,
            "quantity",
        )

        reference_id = identifier(
            reference_id,
            "reference_id",
        )

        signature = (
            warehouse_id,
            sku,
            quantity,
        )

        with self._lock:
            balance = self._balance(
                warehouse_id,
                sku,
            )

            if self._check_operation(
                "receipt",
                reference_id,
                signature,
            ):
                return copy.deepcopy(
                    balance
                )

            balance.on_hand += quantity
            balance.version += 1

            self._operation_refs[
                ("receipt", reference_id)
            ] = signature

            self._movement(
                actor,
                balance,
                InventoryMovementType.RECEIPT,
                quantity,
                reference_id,
            )

            return copy.deepcopy(
                balance
            )

    def reserve(
        self,
        actor: InventoryActor,
        warehouse_id: str,
        sku: str,
        quantity: int,
        reference_id: str,
    ) -> InventoryReservation:
        self._authorize(
            actor,
            self.WORKER_ROLES,
            (warehouse_id,),
        )

        positive_int(
            quantity,
            "quantity",
        )

        reference_id = identifier(
            reference_id,
            "reference_id",
        )

        key = (
            warehouse_id,
            sku,
            reference_id,
        )

        with self._lock:
            existing_id = (
                self._reservation_refs.get(
                    key
                )
            )

            if existing_id:
                existing = (
                    self._reservations[
                        existing_id
                    ]
                )

                if existing.quantity != quantity:
                    raise ValueError(
                        "Reservation reference conflict"
                    )

                return existing

            balance = self._balance(
                warehouse_id,
                sku,
            )

            if balance.available < quantity:
                raise ValueError(
                    "Insufficient available stock"
                )

            balance.reserved += quantity
            balance.version += 1

            reservation = (
                InventoryReservation(
                    reservation_id=str(
                        uuid.uuid4()
                    ),
                    tenant_id=self.tenant_id,
                    warehouse_id=warehouse_id,
                    sku=sku,
                    quantity=quantity,
                    reference_id=reference_id,
                    status="active",
                    created_at=now_utc(),
                )
            )

            self._reservations[
                reservation.reservation_id
            ] = reservation

            self._reservation_refs[
                key
            ] = reservation.reservation_id

            self._movement(
                actor,
                balance,
                InventoryMovementType.RESERVATION,
                quantity,
                reference_id,
            )

            return reservation

    def release_reservation(
        self,
        actor: InventoryActor,
        reservation_id: str,
    ) -> InventoryReservation:
        with self._lock:
            reservation = (
                self._reservations.get(
                    reservation_id
                )
            )

            if reservation is None:
                raise KeyError(
                    "Reservation not found"
                )

            self._authorize(
                actor,
                self.WORKER_ROLES,
                (reservation.warehouse_id,),
            )

            if reservation.status == "released":
                return reservation

            if reservation.status != "active":
                raise ValueError(
                    "Reservation cannot be released"
                )

            balance = self._balance(
                reservation.warehouse_id,
                reservation.sku,
            )

            if balance.reserved < (
                reservation.quantity
            ):
                raise RuntimeError(
                    "Reservation invariant violated"
                )

            balance.reserved -= (
                reservation.quantity
            )

            balance.version += 1

            updated = InventoryReservation(
                **{
                    **asdict(reservation),
                    "status": "released",
                }
            )

            self._reservations[
                reservation_id
            ] = updated

            self._movement(
                actor,
                balance,
                InventoryMovementType.RELEASE,
                reservation.quantity,
                reservation.reference_id,
            )

            return updated

    def fulfill_reservation(
        self,
        actor: InventoryActor,
        reservation_id: str,
    ) -> InventoryReservation:
        with self._lock:
            reservation = (
                self._reservations.get(
                    reservation_id
                )
            )

            if reservation is None:
                raise KeyError(
                    "Reservation not found"
                )

            self._authorize(
                actor,
                self.WORKER_ROLES,
                (reservation.warehouse_id,),
            )

            if reservation.status == "fulfilled":
                return reservation

            if reservation.status != "active":
                raise ValueError(
                    "Reservation cannot be fulfilled"
                )

            balance = self._balance(
                reservation.warehouse_id,
                reservation.sku,
            )

            if (
                balance.reserved
                < reservation.quantity
                or balance.on_hand
                < reservation.quantity
            ):
                raise RuntimeError(
                    "Inventory invariant violated"
                )

            balance.reserved -= (
                reservation.quantity
            )

            balance.on_hand -= (
                reservation.quantity
            )

            balance.version += 1

            updated = InventoryReservation(
                **{
                    **asdict(reservation),
                    "status": "fulfilled",
                }
            )

            self._reservations[
                reservation_id
            ] = updated

            self._movement(
                actor,
                balance,
                InventoryMovementType.FULFILLMENT,
                reservation.quantity,
                reservation.reference_id,
            )

            return updated

    def transfer_stock(
        self,
        actor: InventoryActor,
        source_warehouse: str,
        destination_warehouse: str,
        sku: str,
        quantity: int,
        reference_id: str,
        approval_reference: str,
    ) -> InventoryTransfer:
        if (
            source_warehouse
            == destination_warehouse
        ):
            raise ValueError(
                "Source and destination must differ"
            )

        self._authorize(
            actor,
            self.MANAGER_ROLES,
            (
                source_warehouse,
                destination_warehouse,
            ),
        )

        positive_int(
            quantity,
            "quantity",
        )

        reference_id = identifier(
            reference_id,
            "reference_id",
        )

        approval_reference = identifier(
            approval_reference,
            "approval_reference",
        )

        signature = (
            source_warehouse,
            destination_warehouse,
            sku,
            quantity,
            approval_reference,
        )

        with self._lock:
            if self._check_operation(
                "transfer",
                reference_id,
                signature,
            ):
                for transfer in (
                    self._transfers.values()
                ):
                    if transfer.reference_id == (
                        reference_id
                    ):
                        return transfer

                raise RuntimeError(
                    "Transfer reference missing"
                )

            source = self._balance(
                source_warehouse,
                sku,
            )

            destination = self._balance(
                destination_warehouse,
                sku,
            )

            if source.available < quantity:
                raise ValueError(
                    "Insufficient transferable stock"
                )

            # Prototype: instantaneous
            # movement between warehouses.
            source.on_hand -= quantity
            destination.on_hand += quantity

            source.version += 1
            destination.version += 1

            transfer = InventoryTransfer(
                transfer_id=str(uuid.uuid4()),
                tenant_id=self.tenant_id,
                source_warehouse=(
                    source_warehouse
                ),
                destination_warehouse=(
                    destination_warehouse
                ),
                sku=sku,
                quantity=quantity,
                reference_id=reference_id,
                created_at=now_utc(),
            )

            self._transfers[
                transfer.transfer_id
            ] = transfer

            self._operation_refs[
                ("transfer", reference_id)
            ] = signature

            self._movement(
                actor,
                source,
                InventoryMovementType.TRANSFER_OUT,
                quantity,
                reference_id,
            )

            self._movement(
                actor,
                destination,
                InventoryMovementType.TRANSFER_IN,
                quantity,
                reference_id,
            )

            return transfer

    def adjust_stock(
        self,
        actor: InventoryActor,
        warehouse_id: str,
        sku: str,
        delta: int,
        reference_id: str,
        approval_reference: str,
    ) -> InventoryBalance:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
            (warehouse_id,),
        )

        if (
            isinstance(delta, bool)
            or not isinstance(delta, int)
            or delta == 0
        ):
            raise ValueError(
                "Delta must be nonzero integer"
            )

        reference_id = identifier(
            reference_id,
            "reference_id",
        )

        approval_reference = identifier(
            approval_reference,
            "approval_reference",
        )

        signature = (
            warehouse_id,
            sku,
            delta,
            approval_reference,
        )

        with self._lock:
            balance = self._balance(
                warehouse_id,
                sku,
            )

            if self._check_operation(
                "adjustment",
                reference_id,
                signature,
            ):
                return copy.deepcopy(
                    balance
                )

            new_stock = (
                balance.on_hand + delta
            )

            if new_stock < balance.reserved:
                raise ValueError(
                    "Adjustment would violate "
                    "active reservations"
                )

            balance.on_hand = new_stock
            balance.version += 1

            self._operation_refs[
                ("adjustment", reference_id)
            ] = signature

            self._movement(
                actor,
                balance,
                InventoryMovementType.ADJUSTMENT,
                delta,
                reference_id,
            )

            return copy.deepcopy(
                balance
            )

    def low_stock(
        self,
        actor: InventoryActor,
    ) -> list[dict[str, Any]]:
        self._authorize(
            actor,
            self.READER_ROLES,
            tuple(),
        )

        with self._lock:
            results = []

            for balance in (
                self._balances.values()
            ):
                if (
                    "corporate_admin"
                    not in actor.roles
                    and balance.warehouse_id
                    not in actor.warehouse_ids
                ):
                    continue

                if balance.available <= (
                    balance.reorder_point
                ):
                    results.append({
                        "warehouse_id": (
                            balance.warehouse_id
                        ),
                        "sku": balance.sku,
                        "available": (
                            balance.available
                        ),
                        "reorder_point": (
                            balance.reorder_point
                        ),
                        "safety_stock": (
                            balance.safety_stock
                        ),
                    })

            return results

    def recommend_reorder(
        self,
        actor: InventoryActor,
        warehouse_id: str,
        sku: str,
        daily_demand: float,
        lead_time_days: int,
    ) -> dict[str, Any]:
        balance = self.get_balance(
            actor,
            warehouse_id,
            sku,
        )

        if (
            not math.isfinite(
                daily_demand
            )
            or daily_demand < 0
        ):
            raise ValueError(
                "Invalid daily demand"
            )

        nonnegative_int(
            lead_time_days,
            "lead_time_days",
        )

        expected_demand = math.ceil(
            daily_demand
            * lead_time_days
        )

        target = (
            expected_demand
            + balance.safety_stock
        )

        quantity = max(
            0,
            target - balance.available,
        )

        return {
            "tenant_id": self.tenant_id,
            "warehouse_id": warehouse_id,
            "sku": sku,
            "available": balance.available,
            "expected_lead_time_demand": (
                expected_demand
            ),
            "safety_stock": (
                balance.safety_stock
            ),
            "target_stock": target,
            "suggested_order_quantity": (
                quantity
            ),
            "requires_approval": (
                quantity > 0
            ),
        }

    def movement_history(
        self,
        actor: InventoryActor,
        warehouse_id: str,
        sku: str | None = None,
    ) -> list[InventoryMovement]:
        self._authorize(
            actor,
            self.READER_ROLES,
            (warehouse_id,),
        )

        with self._lock:
            return [
                movement
                for movement in self._movements
                if (
                    movement.warehouse_id
                    == warehouse_id
                    and (
                        sku is None
                        or movement.sku == sku
                    )
                )
            ]

    def export_json(
        self,
        actor: InventoryActor,
        output_path: str | Path,
    ) -> Path:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
            tuple(),
        )

        with self._lock:
            balances = [
                asdict(balance)
                for balance in (
                    self._balances.values()
                )
                if (
                    "corporate_admin"
                    in actor.roles
                    or balance.warehouse_id
                    in actor.warehouse_ids
                )
            ]

            payload = {
                "tenant_id": self.tenant_id,
                "balances": balances,
            }

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
            ),
            encoding="utf-8",
        )

        return output


if __name__ == "__main__":
    service = RetailInventoryService(
        tenant_id="demo"
    )

    manager = InventoryActor(
        user_id="manager-001",
        tenant_id="demo",
        roles=frozenset({
            "warehouse_manager",
        }),
        warehouse_ids=frozenset({
            "WH001",
            "WH002",
        }),
    )

    service.create_balance(
        manager,
        warehouse_id="WH001",
        sku="SKU001",
        initial_stock=100,
        reorder_point=25,
        safety_stock=15,
    )

    service.create_balance(
        manager,
        warehouse_id="WH002",
        sku="SKU001",
        initial_stock=50,
        reorder_point=20,
        safety_stock=10,
    )

    service.receive_stock(
        manager,
        warehouse_id="WH001",
        sku="SKU001",
        quantity=20,
        reference_id="PO001",
    )

    reservation = service.reserve(
        manager,
        warehouse_id="WH001",
        sku="SKU001",
        quantity=10,
        reference_id="ORD001",
    )

    service.fulfill_reservation(
        manager,
        reservation.reservation_id,
    )

    print(
        service.get_balance(
            manager,
            "WH001",
            "SKU001",
        )
    )

    print(
        service.recommend_reorder(
            manager,
            warehouse_id="WH001",
            sku="SKU001",
            daily_demand=12,
            lead_time_days=7,
        )
    )
