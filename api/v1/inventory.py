from __future__ import annotations

"""Planned module: inventory. Implementation pending."""

"""
backend/inventory.py

Autonomous Retail Supply Chain AI 5.0
Inventory Management API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Prototype capabilities:
    - Warehouse inventory balances
    - Stock receipts and adjustments
    - Order reservations and releases
    - Reservation consumption
    - Warehouse stock transfers
    - Low-stock monitoring
    - Movement history
    - Inventory analytics
    - Tenant isolation
    - Permission enforcement
    - Idempotent stock operations
    - Optimistic concurrency

Production requirements:
    - PostgreSQL transactions and row locks
    - Durable movement ledger and audit outbox
    - Product/warehouse ownership verification
    - Authoritative order verification
    - Bin/lot/expiry tracking
    - Warehouse transfer reconciliation
    - Role-specific adjustment approvals
    - Stock valuation and currency handling

This implementation is in-memory and single-process.
"""


import asyncio
import hashlib
import json
import secrets

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from backend.permissions import (
    CurrentPrincipal,
    Permission,
    Principal,
    ResourceContext,
    permission_engine,
)


API_PREFIX = "/api/v1/inventory"

MAX_SKUS_PER_TENANT = 100_000
MAX_MOVEMENTS_PER_TENANT = 200_000
MAX_RESERVATIONS_PER_TENANT = 100_000
MAX_IDEMPOTENCY_KEYS = 200_000
MAX_LIST_LIMIT = 200


# ============================================================
# ENUMS
# ============================================================

class InventoryMovementType(str, Enum):
    RECEIPT = "receipt"
    ADJUSTMENT_IN = "adjustment_in"
    ADJUSTMENT_OUT = "adjustment_out"
    RESERVATION = "reservation"
    RELEASE = "release"
    CONSUMPTION = "consumption"
    TRANSFER_OUT = "transfer_out"
    TRANSFER_IN = "transfer_in"


class InventoryRiskLevel(str, Enum):
    NORMAL = "normal"
    LOW_STOCK = "low_stock"
    STOCKOUT = "stockout"


class ReservationStatus(str, Enum):
    ACTIVE = "active"
    RELEASED = "released"
    CONSUMED = "consumed"


# ============================================================
# REQUEST MODELS
# ============================================================

class InventoryInitialize(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    opening_stock: int = Field(
        default=0,
        ge=0,
        le=100_000_000,
    )

    reorder_point: int = Field(
        default=10,
        ge=0,
        le=100_000_000,
    )

    safety_stock: int = Field(
        default=5,
        ge=0,
        le=100_000_000,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )


class InventoryQuantityOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: int = Field(
        ge=1,
        le=10_000_000,
    )

    expected_version: int = Field(ge=1)

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    reference_id: str | None = Field(
        default=None,
        max_length=128,
    )


class InventoryThresholdUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reorder_point: int = Field(
        ge=0,
        le=100_000_000,
    )

    safety_stock: int = Field(
        ge=0,
        le=100_000_000,
    )

    expected_version: int = Field(ge=1)


class InventoryReservationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    order_id: str = Field(
        min_length=1,
        max_length=128,
    )

    quantity: int = Field(
        ge=1,
        le=10_000_000,
    )

    expected_version: int = Field(ge=1)

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )


class ReservationAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_inventory_version: int = Field(
        ge=1
    )

    expected_reservation_version: int = Field(
        ge=1
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )


class InventoryTransferCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    destination_warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    quantity: int = Field(
        ge=1,
        le=10_000_000,
    )

    expected_source_version: int = Field(
        ge=1
    )

    expected_destination_version: int = Field(
        ge=1
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_warehouses(self):

        if (
            self.source_warehouse_id
            == self.destination_warehouse_id
        ):
            raise ValueError(
                "Source and destination must differ"
            )

        return self


# ============================================================
# RESPONSE MODELS
# ============================================================

class InventoryBalanceResponse(BaseModel):
    inventory_id: str
    warehouse_id: str
    product_id: str

    on_hand: int
    reserved: int
    available: int

    reorder_point: int
    safety_stock: int

    risk_level: InventoryRiskLevel

    version: int
    created_at: datetime
    updated_at: datetime


class InventoryMovementResponse(BaseModel):
    movement_id: str

    warehouse_id: str
    product_id: str

    movement_type: InventoryMovementType
    quantity: int

    reference_id: str | None
    actor_id: str

    inventory_version: int
    timestamp: datetime


class InventoryReservationResponse(BaseModel):
    reservation_id: str

    warehouse_id: str
    product_id: str
    order_id: str

    quantity: int
    status: ReservationStatus

    version: int
    created_at: datetime
    updated_at: datetime


class InventoryTransferResponse(BaseModel):
    transfer_id: str
    product_id: str

    source_warehouse_id: str
    destination_warehouse_id: str

    quantity: int

    source_inventory_version: int
    destination_inventory_version: int

    created_at: datetime


class InventoryAnalyticsResponse(BaseModel):
    warehouse_id: str

    total_skus: int
    total_on_hand: int
    total_reserved: int
    total_available: int

    low_stock_skus: int
    stockout_skus: int

    inventory_utilization_percent: float


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass
class InventoryRecord:
    inventory_id: str
    tenant_id: str

    warehouse_id: str
    product_id: str

    on_hand: int
    reserved: int

    reorder_point: int
    safety_stock: int

    version: int = 1

    created_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )


@dataclass
class ReservationRecord:
    reservation_id: str
    tenant_id: str

    warehouse_id: str
    product_id: str
    order_id: str

    quantity: int

    status: ReservationStatus = (
        ReservationStatus.ACTIVE
    )

    version: int = 1

    created_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def request_fingerprint(
    operation: str,
    payload: BaseModel,
    *,
    resource_id: str | None = None,
) -> str:

    canonical = json.dumps(
        {
            "operation": operation,
            "resource_id": resource_id,
            "payload": payload.model_dump(
                mode="json",
                exclude={"source_request_id"},
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def require_inventory_access(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool,
) -> None:

    permission = (
        Permission.INVENTORY_WRITE
        if write
        else Permission.INVENTORY_READ
    )

    allowed = principal.allowed_warehouse_ids

    if (
        allowed is not None
        and warehouse_id not in allowed
    ):
        raise HTTPException(
            status_code=403,
            detail="Warehouse access denied",
        )

    decision = permission_engine.evaluate(
        principal,
        permission,
        ResourceContext(
            tenant_id=principal.tenant_id,
            warehouse_id=warehouse_id,
        ),
    )

    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail="Inventory access denied",
        )


def available_stock(
    record: InventoryRecord,
) -> int:

    return record.on_hand - record.reserved


def inventory_risk(
    record: InventoryRecord,
) -> InventoryRiskLevel:

    available = available_stock(record)

    if available == 0:
        return InventoryRiskLevel.STOCKOUT

    if available <= record.reorder_point:
        return InventoryRiskLevel.LOW_STOCK

    return InventoryRiskLevel.NORMAL


def to_balance(
    record: InventoryRecord,
) -> InventoryBalanceResponse:

    return InventoryBalanceResponse(
        inventory_id=record.inventory_id,
        warehouse_id=record.warehouse_id,
        product_id=record.product_id,
        on_hand=record.on_hand,
        reserved=record.reserved,
        available=available_stock(record),
        reorder_point=record.reorder_point,
        safety_stock=record.safety_stock,
        risk_level=inventory_risk(record),
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def to_reservation(
    record: ReservationRecord,
) -> InventoryReservationResponse:

    return InventoryReservationResponse(
        reservation_id=record.reservation_id,
        warehouse_id=record.warehouse_id,
        product_id=record.product_id,
        order_id=record.order_id,
        quantity=record.quantity,
        status=record.status,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


# ============================================================
# INVENTORY STORE
# ============================================================

class InventoryStore:

    def __init__(self):

        self._inventory: dict[
            tuple[str, str, str],
            InventoryRecord,
        ] = {}

        self._reservations: dict[
            str,
            ReservationRecord,
        ] = {}

        self._movements: list[
            tuple[str, InventoryMovementResponse]
        ] = []

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    @staticmethod
    def _key(
        tenant_id: str,
        warehouse_id: str,
        product_id: str,
    ) -> tuple[str, str, str]:

        return (
            tenant_id,
            warehouse_id,
            product_id,
        )

    def _get(
        self,
        principal: Principal,
        warehouse_id: str,
        product_id: str,
        *,
        write: bool,
    ) -> InventoryRecord:

        require_inventory_access(
            principal,
            warehouse_id,
            write=write,
        )

        record = self._inventory.get(
            self._key(
                principal.tenant_id,
                warehouse_id,
                product_id,
            )
        )

        if record is None:
            raise HTTPException(
                status_code=404,
                detail="Inventory record not found",
            )

        return record

    def _get_reservation(
        self,
        principal: Principal,
        reservation_id: str,
        *,
        write: bool,
    ) -> ReservationRecord:

        record = self._reservations.get(
            reservation_id
        )

        if (
            record is None
            or record.tenant_id
            != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Reservation not found",
            )

        require_inventory_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    @staticmethod
    def _check_version(
        actual: int,
        expected: int,
    ) -> None:

        if actual != expected:
            raise HTTPException(
                status_code=409,
                detail="Inventory version conflict",
            )

    def _check_idempotency(
        self,
        key: tuple[str, str, str],
        request_hash: str,
    ) -> str | None:

        previous = self._idempotency.get(
            key
        )

        if previous is None:
            return None

        old_hash, result_id = previous

        if old_hash != request_hash:
            raise HTTPException(
                status_code=409,
                detail="Idempotency conflict",
            )

        return result_id

    def _require_capacity(
        self,
        *,
        movements: int = 0,
        reservations: int = 0,
    ) -> None:

        if (
            len(self._movements) + movements
            > MAX_MOVEMENTS_PER_TENANT
        ):
            raise HTTPException(
                status_code=503,
                detail="Movement capacity reached",
            )

        if (
            len(self._reservations) + reservations
            > MAX_RESERVATIONS_PER_TENANT
        ):
            raise HTTPException(
                status_code=503,
                detail="Reservation capacity reached",
            )

        if (
            len(self._idempotency)
            >= MAX_IDEMPOTENCY_KEYS
        ):
            raise HTTPException(
                status_code=503,
                detail="Idempotency capacity reached",
            )

    def _append_movement(
        self,
        *,
        record: InventoryRecord,
        movement_type: InventoryMovementType,
        quantity: int,
        actor_id: str,
        reference_id: str | None = None,
    ) -> InventoryMovementResponse:

        movement = InventoryMovementResponse(
            movement_id=secrets.token_urlsafe(18),
            warehouse_id=record.warehouse_id,
            product_id=record.product_id,
            movement_type=movement_type,
            quantity=quantity,
            reference_id=reference_id,
            actor_id=actor_id,
            inventory_version=record.version,
            timestamp=utc_now(),
        )

        self._movements.append(
            (
                record.tenant_id,
                movement,
            )
        )

        return movement

    async def initialize(
        self,
        *,
        principal: Principal,
        payload: InventoryInitialize,
    ) -> InventoryBalanceResponse:

        require_inventory_access(
            principal,
            payload.warehouse_id,
            write=True,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = request_fingerprint(
            "initialize",
            payload,
        )

        inventory_key = self._key(
            principal.tenant_id,
            payload.warehouse_id,
            payload.product_id,
        )

        async with self._lock:

            previous = self._check_idempotency(
                key,
                request_hash,
            )

            if previous is not None:
                return to_balance(
                    self._get(
                        principal,
                        payload.warehouse_id,
                        payload.product_id,
                        write=False,
                    )
                )

            if inventory_key in self._inventory:
                raise HTTPException(
                    status_code=409,
                    detail="Inventory already initialized",
                )

            tenant_count = sum(
                key[0] == principal.tenant_id
                for key in self._inventory
            )

            if tenant_count >= MAX_SKUS_PER_TENANT:
                raise HTTPException(
                    status_code=503,
                    detail="Inventory capacity reached",
                )

            self._require_capacity(
                movements=(
                    1 if payload.opening_stock else 0
                )
            )

            record = InventoryRecord(
                inventory_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                product_id=payload.product_id,
                on_hand=payload.opening_stock,
                reserved=0,
                reorder_point=payload.reorder_point,
                safety_stock=payload.safety_stock,
            )

            self._inventory[
                inventory_key
            ] = record

            if payload.opening_stock:
                self._append_movement(
                    record=record,
                    movement_type=(
                        InventoryMovementType.RECEIPT
                    ),
                    quantity=payload.opening_stock,
                    actor_id=principal.principal_id,
                    reference_id="opening-stock",
                )

            self._idempotency[key] = (
                request_hash,
                record.inventory_id,
            )

            return to_balance(record)

    async def get(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
        product_id: str,
    ) -> InventoryBalanceResponse:

        async with self._lock:

            return to_balance(
                self._get(
                    principal,
                    warehouse_id,
                    product_id,
                    write=False,
                )
            )

    async def list_inventory(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
        risk: InventoryRiskLevel | None,
        limit: int,
    ) -> list[InventoryBalanceResponse]:

        require_inventory_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._inventory.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and record.warehouse_id
                    == warehouse_id
                    and (
                        risk is None
                        or inventory_risk(record)
                        == risk
                    )
                )
            ]

            records.sort(
                key=lambda item: item.product_id
            )

            return [
                to_balance(record)
                for record in records[:limit]
            ]

    async def adjust_stock(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
        product_id: str,
        payload: InventoryQuantityOperation,
        increase: bool,
    ) -> InventoryBalanceResponse:

        operation = (
            "receive"
            if increase
            else "adjust_out"
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = request_fingerprint(
            operation,
            payload,
            resource_id=(
                f"{warehouse_id}:{product_id}"
            ),
        )

        async with self._lock:

            record = self._get(
                principal,
                warehouse_id,
                product_id,
                write=True,
            )

            previous = self._check_idempotency(
                key,
                request_hash,
            )

            if previous is not None:
                return to_balance(record)

            self._check_version(
                record.version,
                payload.expected_version,
            )

            if not increase:
                if (
                    payload.quantity
                    > available_stock(record)
                ):
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Cannot remove reserved stock"
                        ),
                    )

            self._require_capacity(
                movements=1
            )

            if increase:
                record.on_hand += payload.quantity
                movement_type = (
                    InventoryMovementType.RECEIPT
                )
            else:
                record.on_hand -= payload.quantity
                movement_type = (
                    InventoryMovementType.ADJUSTMENT_OUT
                )

            record.version += 1
            record.updated_at = utc_now()

            self._append_movement(
                record=record,
                movement_type=movement_type,
                quantity=payload.quantity,
                actor_id=principal.principal_id,
                reference_id=payload.reference_id,
            )

            self._idempotency[key] = (
                request_hash,
                record.inventory_id,
            )

            return to_balance(record)

    async def update_thresholds(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
        product_id: str,
        payload: InventoryThresholdUpdate,
    ) -> InventoryBalanceResponse:

        async with self._lock:

            record = self._get(
                principal,
                warehouse_id,
                product_id,
                write=True,
            )

            self._check_version(
                record.version,
                payload.expected_version,
            )

            record.reorder_point = (
                payload.reorder_point
            )

            record.safety_stock = (
                payload.safety_stock
            )

            record.version += 1
            record.updated_at = utc_now()

            return to_balance(record)

    async def reserve(
        self,
        *,
        principal: Principal,
        payload: InventoryReservationCreate,
    ) -> InventoryReservationResponse:

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = request_fingerprint(
            "reserve",
            payload,
        )

        async with self._lock:

            record = self._get(
                principal,
                payload.warehouse_id,
                payload.product_id,
                write=True,
            )

            previous = self._check_idempotency(
                key,
                request_hash,
            )

            if previous is not None:
                return to_reservation(
                    self._get_reservation(
                        principal,
                        previous,
                        write=False,
                    )
                )

            self._check_version(
                record.version,
                payload.expected_version,
            )

            if (
                payload.quantity
                > available_stock(record)
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Insufficient available stock",
                )

            self._require_capacity(
                movements=1,
                reservations=1,
            )

            reservation = ReservationRecord(
                reservation_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                product_id=payload.product_id,
                order_id=payload.order_id,
                quantity=payload.quantity,
            )

            record.reserved += payload.quantity
            record.version += 1
            record.updated_at = utc_now()

            self._reservations[
                reservation.reservation_id
            ] = reservation

            self._append_movement(
                record=record,
                movement_type=(
                    InventoryMovementType.RESERVATION
                ),
                quantity=payload.quantity,
                actor_id=principal.principal_id,
                reference_id=reservation.reservation_id,
            )

            self._idempotency[key] = (
                request_hash,
                reservation.reservation_id,
            )

            return to_reservation(reservation)

    async def reservation_action(
        self,
        *,
        principal: Principal,
        reservation_id: str,
        payload: ReservationAction,
        consume: bool,
    ) -> InventoryReservationResponse:

        operation = (
            "consume_reservation"
            if consume
            else "release_reservation"
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = request_fingerprint(
            operation,
            payload,
            resource_id=reservation_id,
        )

        async with self._lock:

            reservation = self._get_reservation(
                principal,
                reservation_id,
                write=True,
            )

            record = self._get(
                principal,
                reservation.warehouse_id,
                reservation.product_id,
                write=True,
            )

            previous = self._check_idempotency(
                key,
                request_hash,
            )

            if previous is not None:
                return to_reservation(reservation)

            self._check_version(
                record.version,
                payload.expected_inventory_version,
            )

            self._check_version(
                reservation.version,
                payload.expected_reservation_version,
            )

            if (
                reservation.status
                != ReservationStatus.ACTIVE
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Reservation is not active",
                )

            if record.reserved < reservation.quantity:
                raise HTTPException(
                    status_code=409,
                    detail="Reservation balance inconsistency",
                )

            self._require_capacity(
                movements=1
            )

            record.reserved -= reservation.quantity

            if consume:
                if record.on_hand < reservation.quantity:
                    raise HTTPException(
                        status_code=409,
                        detail="Insufficient on-hand stock",
                    )

                record.on_hand -= reservation.quantity

                reservation.status = (
                    ReservationStatus.CONSUMED
                )

                movement_type = (
                    InventoryMovementType.CONSUMPTION
                )

            else:
                reservation.status = (
                    ReservationStatus.RELEASED
                )

                movement_type = (
                    InventoryMovementType.RELEASE
                )

            record.version += 1
            record.updated_at = utc_now()

            reservation.version += 1
            reservation.updated_at = utc_now()

            self._append_movement(
                record=record,
                movement_type=movement_type,
                quantity=reservation.quantity,
                actor_id=principal.principal_id,
                reference_id=reservation_id,
            )

            self._idempotency[key] = (
                request_hash,
                reservation_id,
            )

            return to_reservation(reservation)

    async def transfer(
        self,
        *,
        principal: Principal,
        payload: InventoryTransferCreate,
    ) -> InventoryTransferResponse:

        require_inventory_access(
            principal,
            payload.source_warehouse_id,
            write=True,
        )

        require_inventory_access(
            principal,
            payload.destination_warehouse_id,
            write=True,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = request_fingerprint(
            "transfer",
            payload,
        )

        async with self._lock:

            source = self._get(
                principal,
                payload.source_warehouse_id,
                payload.product_id,
                write=True,
            )

            destination = self._get(
                principal,
                payload.destination_warehouse_id,
                payload.product_id,
                write=True,
            )

            previous = self._check_idempotency(
                key,
                request_hash,
            )

            if previous is not None:
                # A real implementation should store
                # and return the original immutable
                # transfer result.
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Transfer already processed; "
                        "retrieve the original ledger record"
                    ),
                )

            self._check_version(
                source.version,
                payload.expected_source_version,
            )

            self._check_version(
                destination.version,
                payload.expected_destination_version,
            )

            if (
                payload.quantity
                > available_stock(source)
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Insufficient source stock",
                )

            self._require_capacity(
                movements=2
            )

            transfer_id = secrets.token_urlsafe(20)

            source.on_hand -= payload.quantity
            destination.on_hand += payload.quantity

            source.version += 1
            destination.version += 1

            timestamp = utc_now()

            source.updated_at = timestamp
            destination.updated_at = timestamp

            self._append_movement(
                record=source,
                movement_type=(
                    InventoryMovementType.TRANSFER_OUT
                ),
                quantity=payload.quantity,
                actor_id=principal.principal_id,
                reference_id=transfer_id,
            )

            self._append_movement(
                record=destination,
                movement_type=(
                    InventoryMovementType.TRANSFER_IN
                ),
                quantity=payload.quantity,
                actor_id=principal.principal_id,
                reference_id=transfer_id,
            )

            self._idempotency[key] = (
                request_hash,
                transfer_id,
            )

            return InventoryTransferResponse(
                transfer_id=transfer_id,
                product_id=payload.product_id,
                source_warehouse_id=(
                    payload.source_warehouse_id
                ),
                destination_warehouse_id=(
                    payload.destination_warehouse_id
                ),
                quantity=payload.quantity,
                source_inventory_version=(
                    source.version
                ),
                destination_inventory_version=(
                    destination.version
                ),
                created_at=timestamp,
            )

    async def movements(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
        product_id: str | None,
        limit: int,
    ) -> list[InventoryMovementResponse]:

        require_inventory_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            results = [
                movement
                for tenant_id, movement
                in self._movements
                if (
                    tenant_id == principal.tenant_id
                    and movement.warehouse_id
                    == warehouse_id
                    and (
                        product_id is None
                        or movement.product_id
                        == product_id
                    )
                )
            ]

            return [
                item.model_copy(deep=True)
                for item in results[-limit:][::-1]
            ]

    async def analytics(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
    ) -> InventoryAnalyticsResponse:

        require_inventory_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._inventory.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and record.warehouse_id
                    == warehouse_id
                )
            ]

            total_on_hand = sum(
                record.on_hand
                for record in records
            )

            total_reserved = sum(
                record.reserved
                for record in records
            )

            total_available = (
                total_on_hand - total_reserved
            )

            low_stock = sum(
                inventory_risk(record)
                == InventoryRiskLevel.LOW_STOCK
                for record in records
            )

            stockout = sum(
                inventory_risk(record)
                == InventoryRiskLevel.STOCKOUT
                for record in records
            )

            utilization = (
                round(
                    total_reserved
                    / total_on_hand * 100,
                    2,
                )
                if total_on_hand
                else 0.0
            )

            return InventoryAnalyticsResponse(
                warehouse_id=warehouse_id,
                total_skus=len(records),
                total_on_hand=total_on_hand,
                total_reserved=total_reserved,
                total_available=total_available,
                low_stock_skus=low_stock,
                stockout_skus=stockout,
                inventory_utilization_percent=(
                    utilization
                ),
            )


inventory_store = InventoryStore()


# ============================================================
# SERVICE
# ============================================================

class InventoryService:

    def __init__(
        self,
        store: InventoryStore,
    ):
        self.store = store

    async def initialize(
        self,
        principal: Principal,
        payload: InventoryInitialize,
    ) -> InventoryBalanceResponse:

        return await self.store.initialize(
            principal=principal,
            payload=payload,
        )

    async def reserve(
        self,
        principal: Principal,
        payload: InventoryReservationCreate,
    ) -> InventoryReservationResponse:

        return await self.store.reserve(
            principal=principal,
            payload=payload,
        )

    async def transfer(
        self,
        principal: Principal,
        payload: InventoryTransferCreate,
    ) -> InventoryTransferResponse:

        return await self.store.transfer(
            principal=principal,
            payload=payload,
        )


inventory_service = InventoryService(
    inventory_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Inventory Management"],
)


@router.post(
    "",
    response_model=InventoryBalanceResponse,
    status_code=201,
)
async def initialize_inventory(
    payload: InventoryInitialize,
    principal: CurrentPrincipal,
):
    return await inventory_service.initialize(
        principal,
        payload,
    )


@router.get(
    "",
    response_model=list[InventoryBalanceResponse],
)
async def list_inventory(
    principal: CurrentPrincipal,
    warehouse_id: str,
    risk: InventoryRiskLevel | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await inventory_store.list_inventory(
        principal=principal,
        warehouse_id=warehouse_id,
        risk=risk,
        limit=limit,
    )


@router.get(
    "/analytics/{warehouse_id}",
    response_model=InventoryAnalyticsResponse,
)
async def inventory_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
):
    return await inventory_store.analytics(
        principal=principal,
        warehouse_id=warehouse_id,
    )


@router.get(
    "/movements/{warehouse_id}",
    response_model=list[InventoryMovementResponse],
)
async def inventory_movements(
    warehouse_id: str,
    principal: CurrentPrincipal,
    product_id: str | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await inventory_store.movements(
        principal=principal,
        warehouse_id=warehouse_id,
        product_id=product_id,
        limit=limit,
    )


@router.get(
    "/{warehouse_id}/{product_id}",
    response_model=InventoryBalanceResponse,
)
async def get_inventory(
    warehouse_id: str,
    product_id: str,
    principal: CurrentPrincipal,
):
    return await inventory_store.get(
        principal=principal,
        warehouse_id=warehouse_id,
        product_id=product_id,
    )


@router.post(
    "/{warehouse_id}/{product_id}/receive",
    response_model=InventoryBalanceResponse,
)
async def receive_inventory(
    warehouse_id: str,
    product_id: str,
    payload: InventoryQuantityOperation,
    principal: CurrentPrincipal,
):
    return await inventory_store.adjust_stock(
        principal=principal,
        warehouse_id=warehouse_id,
        product_id=product_id,
        payload=payload,
        increase=True,
    )


@router.post(
    "/{warehouse_id}/{product_id}/adjust-out",
    response_model=InventoryBalanceResponse,
)
async def adjust_inventory_out(
    warehouse_id: str,
    product_id: str,
    payload: InventoryQuantityOperation,
    principal: CurrentPrincipal,
):
    return await inventory_store.adjust_stock(
        principal=principal,
        warehouse_id=warehouse_id,
        product_id=product_id,
        payload=payload,
        increase=False,
    )


@router.patch(
    "/{warehouse_id}/{product_id}/thresholds",
    response_model=InventoryBalanceResponse,
)
async def update_inventory_thresholds(
    warehouse_id: str,
    product_id: str,
    payload: InventoryThresholdUpdate,
    principal: CurrentPrincipal,
):
    return await inventory_store.update_thresholds(
        principal=principal,
        warehouse_id=warehouse_id,
        product_id=product_id,
        payload=payload,
    )


@router.post(
    "/reservations",
    response_model=InventoryReservationResponse,
    status_code=201,
)
async def create_inventory_reservation(
    payload: InventoryReservationCreate,
    principal: CurrentPrincipal,
):
    return await inventory_service.reserve(
        principal,
        payload,
    )


@router.post(
    "/reservations/{reservation_id}/release",
    response_model=InventoryReservationResponse,
)
async def release_inventory_reservation(
    reservation_id: str,
    payload: ReservationAction,
    principal: CurrentPrincipal,
):
    return await inventory_store.reservation_action(
        principal=principal,
        reservation_id=reservation_id,
        payload=payload,
        consume=False,
    )


@router.post(
    "/reservations/{reservation_id}/consume",
    response_model=InventoryReservationResponse,
)
async def consume_inventory_reservation(
    reservation_id: str,
    payload: ReservationAction,
    principal: CurrentPrincipal,
):
    return await inventory_store.reservation_action(
        principal=principal,
        reservation_id=reservation_id,
        payload=payload,
        consume=True,
    )


@router.post(
    "/transfers",
    response_model=InventoryTransferResponse,
    status_code=201,
)
async def transfer_inventory(
    payload: InventoryTransferCreate,
    principal: CurrentPrincipal,
):
    return await inventory_service.transfer(
        principal,
        payload,
    )


__all__ = [
    "InventoryMovementType",
    "InventoryRiskLevel",
    "ReservationStatus",
    "InventoryInitialize",
    "InventoryQuantityOperation",
    "InventoryThresholdUpdate",
    "InventoryReservationCreate",
    "ReservationAction",
    "InventoryTransferCreate",
    "InventoryBalanceResponse",
    "InventoryMovementResponse",
    "InventoryReservationResponse",
    "InventoryTransferResponse",
    "InventoryAnalyticsResponse",
    "InventoryStore",
    "InventoryService",
    "inventory_store",
    "inventory_service",
    "router",
]
    