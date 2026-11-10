from __future__ import annotations

"""Planned module: inventory. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
backend/services/inventory_service.py

Standard-library reference implementation.

Features:
- Tenant and warehouse RBAC
- Stock balance registration
- Receiving stock
- Inventory reservation
- Reservation release / fulfillment
- Interwarehouse transfers
- Approved stock adjustments
- Idempotent inventory operations
- Low-stock detection
- Replenishment recommendations
- Movement history and audit
- JSON export

Not connected to a database or live services.
"""


import copy
import json
import math
import threading
import uuid

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid {name}")
    if len(value) > 200:
        raise ValueError(f"{name} too long")
    return value.strip()


def quantity(value: int, positive: bool = True) -> int:
    if type(value) is not int:
        raise ValueError("Quantity must be an integer")
    if value < (1 if positive else 0):
        raise ValueError("Invalid quantity")
    return value


class ReservationStatus(str, Enum):
    ACTIVE = "active"
    RELEASED = "released"
    FULFILLED = "fulfilled"


class MovementType(str, Enum):
    RECEIVE = "receive"
    RESERVE = "reserve"
    RELEASE = "release"
    FULFILL = "fulfill"
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
    version: int = 1

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved


@dataclass
class InventoryReservation:
    reservation_id: str
    tenant_id: str
    warehouse_id: str
    sku: str
    quantity: int
    reference_id: str
    status: ReservationStatus
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class InventoryMovement:
    movement_id: str
    tenant_id: str
    warehouse_id: str
    sku: str
    movement_type: MovementType
    quantity: int
    reference_id: str
    actor_id: str
    created_at: str


@dataclass(frozen=True)
class InventoryAuditEvent:
    event_id: str
    tenant_id: str
    actor_id: str
    action: str
    warehouse_id: str
    sku: str
    timestamp: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReorderRecommendation:
    warehouse_id: str
    sku: str
    available: int
    reorder_point: int
    target_stock: int
    suggested_quantity: int
    requires_approval: bool


ApprovalVerifier = Callable[[str, str], bool]


class RetailInventoryService:
    WRITER_ROLES = frozenset({
        "inventory_manager",
        "warehouse_manager",
        "operations_manager",
        "corporate_admin",
    })

    READER_ROLES = WRITER_ROLES | frozenset({
        "inventory_analyst",
        "procurement_manager",
        "demand_planner",
        "business_analyst",
    })

    def __init__(
        self,
        tenant_id: str,
        approval_verifier: ApprovalVerifier | None = None,
    ):
        self.tenant_id = required(tenant_id, "tenant_id")
        self.approval_verifier = approval_verifier
        self._lock = threading.RLock()

        self._balances: dict[
            tuple[str, str], InventoryBalance
        ] = {}
        self._reservations: dict[
            str, InventoryReservation
        ] = {}
        self._operations: dict[
            tuple[str, str], Any
        ] = {}
        self._movements: list[InventoryMovement] = []
        self._audit: list[InventoryAuditEvent] = []

    def _authorize(
        self,
        actor: InventoryActor,
        roles: frozenset[str],
        warehouse_id: str,
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.user_id
            or not actor.roles.intersection(roles)
        ):
            raise PermissionError("Inventory access denied")

        if (
            "corporate_admin" not in actor.roles
            and warehouse_id not in actor.warehouse_ids
        ):
            raise PermissionError("Warehouse access denied")

    def _balance(
        self, warehouse_id: str, sku: str
    ) -> InventoryBalance:
        key = (warehouse_id, sku)
        if key not in self._balances:
            raise KeyError("Inventory balance not found")
        return self._balances[key]

    def _audit_event(
        self,
        actor: InventoryActor,
        action: str,
        warehouse_id: str,
        sku: str,
        details: dict | None = None,
    ) -> None:
        self._audit.append(InventoryAuditEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            actor_id=actor.user_id,
            action=action,
            warehouse_id=warehouse_id,
            sku=sku,
            timestamp=now(),
            details=copy.deepcopy(details or {}),
        ))

    def _movement(
        self,
        actor: InventoryActor,
        warehouse_id: str,
        sku: str,
        movement_type: MovementType,
        amount: int,
        reference_id: str,
    ) -> InventoryMovement:
        event = InventoryMovement(
            movement_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            warehouse_id=warehouse_id,
            sku=sku,
            movement_type=movement_type,
            quantity=amount,
            reference_id=reference_id,
            actor_id=actor.user_id,
            created_at=now(),
        )
        self._movements.append(event)
        return event

    def _check_approval(
        self,
        action: str,
        approval_reference: str,
    ) -> None:
        required(approval_reference, "approval_reference")

        if self.approval_verifier is None:
            raise PermissionError(
                "Approval verifier is not configured"
            )

        if not self.approval_verifier(
            action, approval_reference
        ):
            raise PermissionError("Approval not verified")

    def create_balance(
        self,
        actor: InventoryActor,
        warehouse_id: str,
        sku: str,
        initial_stock: int = 0,
        reorder_point: int = 0,
        safety_stock: int = 0,
    ) -> InventoryBalance:
        self._authorize(actor, self.WRITER_ROLES, warehouse_id)

        for value in (
            initial_stock, reorder_point, safety_stock
        ):
            quantity(value, positive=False)

        key = (
            required(warehouse_id, "warehouse_id"),
            required(sku, "sku"),
        )

        with self._lock:
            if key in self._balances:
                raise ValueError("Balance already exists")

            balance = InventoryBalance(
                tenant_id=self.tenant_id,
                warehouse_id=warehouse_id,
                sku=sku,
                on_hand=initial_stock,
                reorder_point=reorder_point,
                safety_stock=safety_stock,
            )
            self._balances[key] = balance
            self._audit_event(
                actor, "balance_created", warehouse_id, sku,
                {"initial_stock": initial_stock},
            )
            return copy.deepcopy(balance)

    def get_balance(
        self,
        actor: InventoryActor,
        warehouse_id: str,
        sku: str,
    ) -> InventoryBalance:
        self._authorize(actor, self.READER_ROLES, warehouse_id)
        with self._lock:
            return copy.deepcopy(self._balance(warehouse_id, sku))

    def receive_stock(
        self,
        actor: InventoryActor,
        warehouse_id: str,
        sku: str,
        amount: int,
        reference_id: str,
    ) -> InventoryBalance:
        self._authorize(actor, self.WRITER_ROLES, warehouse_id)
        quantity(amount)
        required(reference_id, "reference_id")
        key = ("receive", reference_id)

        with self._lock:
            if key in self._operations:
                previous = self._operations[key]
                if previous != (warehouse_id, sku, amount):
                    raise ValueError("Conflicting reference")
                return copy.deepcopy(self._balance(warehouse_id, sku))

            balance = self._balance(warehouse_id, sku)
            balance.on_hand += amount
            balance.version += 1
            self._operations[key] = (warehouse_id, sku, amount)

            self._movement(
                actor, warehouse_id, sku,
                MovementType.RECEIVE, amount, reference_id,
            )
            self._audit_event(
                actor, "stock_received", warehouse_id, sku,
                {"quantity": amount},
            )
            return copy.deepcopy(balance)

    def reserve(
        self,
        actor: InventoryActor,
        warehouse_id: str,
        sku: str,
        amount: int,
        reference_id: str,
    ) -> InventoryReservation:
        self._authorize(actor, self.WRITER_ROLES, warehouse_id)
        quantity(amount)
        required(reference_id, "reference_id")
        key = ("reserve", reference_id)

        with self._lock:
            if key in self._operations:
                reservation_id = self._operations[key]
                existing = self._reservations[reservation_id]
                if (
                    existing.warehouse_id != warehouse_id
                    or existing.sku != sku
                    or existing.quantity != amount
                ):
                    raise ValueError("Conflicting reservation reference")
                return copy.deepcopy(existing)

            balance = self._balance(warehouse_id, sku)
            if balance.available < amount:
                raise ValueError("Insufficient available stock")

            balance.reserved += amount
            balance.version += 1
            current = now()

            reservation = InventoryReservation(
                reservation_id=str(uuid.uuid4()),
                tenant_id=self.tenant_id,
                warehouse_id=warehouse_id,
                sku=sku,
                quantity=amount,
                reference_id=reference_id,
                status=ReservationStatus.ACTIVE,
                created_at=current,
                updated_at=current,
            )

            self._reservations[reservation.reservation_id] = reservation
            self._operations[key] = reservation.reservation_id

            self._movement(
                actor, warehouse_id, sku,
                MovementType.RESERVE, amount, reference_id,
            )
            self._audit_event(
                actor, "stock_reserved", warehouse_id, sku,
                {"reservation_id": reservation.reservation_id},
            )
            return copy.deepcopy(reservation)

    def _change_reservation(
        self,
        actor: InventoryActor,
        reservation_id: str,
        new_status: ReservationStatus,
    ) -> InventoryReservation:
        with self._lock:
            reservation = self._reservations.get(reservation_id)
            if reservation is None:
                raise KeyError("Reservation not found")

            self._authorize(
                actor, self.WRITER_ROLES, reservation.warehouse_id
            )

            if reservation.status == new_status:
                return copy.deepcopy(reservation)

            if reservation.status != ReservationStatus.ACTIVE:
                raise ValueError("Reservation already finalized")

            balance = self._balance(
                reservation.warehouse_id, reservation.sku
            )

            if new_status == ReservationStatus.RELEASED:
                balance.reserved -= reservation.quantity
                movement_type = MovementType.RELEASE
            elif new_status == ReservationStatus.FULFILLED:
                balance.reserved -= reservation.quantity
                balance.on_hand -= reservation.quantity
                movement_type = MovementType.FULFILL
            else:
                raise ValueError("Unsupported reservation transition")

            balance.version += 1
            reservation.status = new_status
            reservation.updated_at = now()

            self._movement(
                actor, reservation.warehouse_id, reservation.sku,
                movement_type, reservation.quantity,
                reservation.reference_id,
            )
            self._audit_event(
                actor, f"reservation_{new_status.value}",
                reservation.warehouse_id, reservation.sku,
                {"reservation_id": reservation_id},
            )
            return copy.deepcopy(reservation)

    def release_reservation(
        self, actor: InventoryActor, reservation_id: str
    ) -> InventoryReservation:
        return self._change_reservation(
            actor, reservation_id, ReservationStatus.RELEASED
        )

    def fulfill_reservation(
        self, actor: InventoryActor, reservation_id: str
    ) -> InventoryReservation:
        return self._change_reservation(
            actor, reservation_id, ReservationStatus.FULFILLED
        )

    def transfer_stock(
        self,
        actor: InventoryActor,
        source_warehouse: str,
        destination_warehouse: str,
        sku: str,
        amount: int,
        reference_id: str,
        approval_reference: str,
    ) -> tuple[InventoryBalance, InventoryBalance]:
        self._authorize(actor, self.WRITER_ROLES, source_warehouse)
        self._authorize(actor, self.WRITER_ROLES, destination_warehouse)
        quantity(amount)

        if source_warehouse == destination_warehouse:
            raise ValueError("Source and destination must differ")

        required(reference_id, "reference_id")
        key = ("transfer", reference_id)

        with self._lock:
            if key in self._operations:
                previous = self._operations[key]
                if previous != (
                    source_warehouse, destination_warehouse, sku, amount
                ):
                    raise ValueError("Conflicting transfer reference")
                return (
                    copy.deepcopy(self._balance(source_warehouse, sku)),
                    copy.deepcopy(self._balance(destination_warehouse, sku)),
                )

            self._check_approval("stock_transfer", approval_reference)

            source = self._balance(source_warehouse, sku)
            destination = self._balance(destination_warehouse, sku)

            if source.available < amount:
                raise ValueError("Insufficient transferable stock")

            source.on_hand -= amount
            destination.on_hand += amount
            source.version += 1
            destination.version += 1

            self._operations[key] = (
                source_warehouse, destination_warehouse, sku, amount
            )

            self._movement(
                actor, source_warehouse, sku,
                MovementType.TRANSFER_OUT, amount, reference_id,
            )
            self._movement(
                actor, destination_warehouse, sku,
                MovementType.TRANSFER_IN, amount, reference_id,
            )
            self._audit_event(
                actor, "stock_transferred", source_warehouse, sku,
                {
                    "destination_warehouse": destination_warehouse,
                    "quantity": amount,
                    "approval_reference": approval_reference,
                },
            )

            return copy.deepcopy(source), copy.deepcopy(destination)

    def adjust_stock(
        self,
        actor: InventoryActor,
        warehouse_id: str,
        sku: str,
        delta: int,
        reference_id: str,
        approval_reference: str,
    ) -> InventoryBalance:
        self._authorize(actor, self.WRITER_ROLES, warehouse_id)

        if type(delta) is not int or delta == 0:
            raise ValueError("Delta must be a nonzero integer")

        required(reference_id, "reference_id")
        key = ("adjust", reference_id)

        with self._lock:
            if key in self._operations:
                if self._operations[key] != (warehouse_id, sku, delta):
                    raise ValueError("Conflicting adjustment reference")
                return copy.deepcopy(self._balance(warehouse_id, sku))

            self._check_approval(
                "inventory_adjustment", approval_reference
            )

            balance = self._balance(warehouse_id, sku)
            if balance.on_hand + delta < balance.reserved:
                raise ValueError("Adjustment violates reserved stock")

            balance.on_hand += delta
            balance.version += 1
            self._operations[key] = (warehouse_id, sku, delta)

            self._movement(
                actor, warehouse_id, sku,
                MovementType.ADJUSTMENT, delta, reference_id,
            )
            self._audit_event(
                actor, "stock_adjusted", warehouse_id, sku,
                {"delta": delta, "approval_reference": approval_reference},
            )
            return copy.deepcopy(balance)

    def low_stock(
        self,
        actor: InventoryActor,
    ) -> list[InventoryBalance]:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.roles.intersection(self.READER_ROLES)
        ):
            raise PermissionError("Inventory access denied")

        with self._lock:
            return [
                copy.deepcopy(balance)
                for balance in self._balances.values()
                if (
                    balance.available <= balance.reorder_point
                    and (
                        "corporate_admin" in actor.roles
                        or balance.warehouse_id in actor.warehouse_ids
                    )
                )
            ]

    def recommend_reorder(
        self,
        actor: InventoryActor,
        warehouse_id: str,
        sku: str,
        daily_demand: float,
        lead_time_days: int,
    ) -> ReorderRecommendation:
        balance = self.get_balance(actor, warehouse_id, sku)

        if (
            isinstance(daily_demand, bool)
            or not isinstance(daily_demand, (int, float))
            or not math.isfinite(daily_demand)
            or daily_demand < 0
        ):
            raise ValueError("Invalid daily demand")

        quantity(lead_time_days, positive=False)

        reorder_point = math.ceil(
            daily_demand * lead_time_days + balance.safety_stock
        )

        target_stock = math.ceil(
            daily_demand * (lead_time_days + 7)
            + balance.safety_stock
        )

        suggested = (
            max(0, target_stock - balance.available)
            if balance.available <= reorder_point
            else 0
        )

        return ReorderRecommendation(
            warehouse_id=warehouse_id,
            sku=sku,
            available=balance.available,
            reorder_point=reorder_point,
            target_stock=target_stock,
            suggested_quantity=suggested,
            requires_approval=suggested > 0,
        )

    def movement_history(
        self,
        actor: InventoryActor,
        warehouse_id: str,
        sku: str | None = None,
    ) -> list[InventoryMovement]:
        self._authorize(actor, self.READER_ROLES, warehouse_id)

        with self._lock:
            return [
                copy.deepcopy(m)
                for m in self._movements
                if m.warehouse_id == warehouse_id
                and (sku is None or m.sku == sku)
            ]

    def audit_events(
        self,
        actor: InventoryActor,
        warehouse_id: str,
    ) -> list[InventoryAuditEvent]:
        self._authorize(actor, self.READER_ROLES, warehouse_id)

        with self._lock:
            return [
                copy.deepcopy(event)
                for event in self._audit
                if event.warehouse_id == warehouse_id
            ]

    def export_json(
        self,
        actor: InventoryActor,
        output_path: str | Path,
    ) -> Path:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.roles.intersection(self.READER_ROLES)
        ):
            raise PermissionError("Inventory access denied")

        with self._lock:
            balances = [
                asdict(b)
                for b in self._balances.values()
                if (
                    "corporate_admin" in actor.roles
                    or b.warehouse_id in actor.warehouse_ids
                )
            ]

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(balances, indent=2),
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    service = RetailInventoryService("demo")

    admin = InventoryActor(
        user_id="admin001",
        tenant_id="demo",
        roles=frozenset({"corporate_admin"}),
    )

    service.create_balance(
        admin, "WH001", "SKU001",
        initial_stock=100,
        reorder_point=30,
        safety_stock=20,
    )

    service.receive_stock(
        admin, "WH001", "SKU001",
        amount=50,
        reference_id="RECEIPT001",
    )

    reservation = service.reserve(
        admin, "WH001", "SKU001",
        amount=25,
        reference_id="ORDER001",
    )

    print(
        "After reservation:",
        service.get_balance(admin, "WH001", "SKU001"),
    )

    service.fulfill_reservation(
        admin, reservation.reservation_id
    )

    print(
        "After fulfillment:",
        service.get_balance(admin, "WH001", "SKU001"),
    )

    recommendation = service.recommend_reorder(
        admin, "WH001", "SKU001",
        daily_demand=15,
        lead_time_days=7,
    )

    print("Reorder:", recommendation.suggested_quantity)
