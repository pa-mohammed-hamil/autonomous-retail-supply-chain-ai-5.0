from __future__ import annotations

"""Planned module: bins. Implementation pending."""

"""
backend/bins.py

Autonomous Retail Supply Chain AI 5.0
Warehouse Bin and Storage Location Management API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Warehouse bin registration
    - Zone, aisle, rack and shelf tracking
    - Bin capacity management
    - Product placement and removal
    - Inventory reservations
    - Reservation release
    - Bin-to-bin stock transfers
    - Bin blocking and activation
    - Stock movement history
    - Tenant and warehouse isolation
    - Optimistic concurrency
    - Idempotent stock operations
    - In-memory prototype storage

IMPORTANT:
    This module manages bin-level stock.

    It does not automatically update the
    warehouse-wide inventory ledger.

    Production transfers must update bin
    balances, inventory ledger and outbox
    events within one database transaction.
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
)

from backend.permissions import (
    CurrentPrincipal,
    Permission,
    Principal,
    ResourceContext,
    permission_engine,
)


# ============================================================
# CONFIGURATION
# ============================================================

MAX_BINS_PER_TENANT = 20_000
MAX_MOVEMENTS_PER_TENANT = 100_000
MAX_IDEMPOTENCY_KEYS = 100_000
MAX_LIST_LIMIT = 200

API_PREFIX = "/api/v1/bins"


# ============================================================
# ENUMS
# ============================================================

class BinStatus(str, Enum):
    ACTIVE = "active"
    BLOCKED = "blocked"
    MAINTENANCE = "maintenance"
    INACTIVE = "inactive"


class BinType(str, Enum):
    STANDARD = "standard"
    PALLET = "pallet"
    PICKING = "picking"
    BULK = "bulk"
    COLD_STORAGE = "cold_storage"
    HAZARDOUS = "hazardous"
    RETURNS = "returns"
    QUARANTINE = "quarantine"


class BinMovementType(str, Enum):
    PUTAWAY = "putaway"
    PICK = "pick"
    TRANSFER = "transfer"
    ADJUSTMENT = "adjustment"
    RESERVE = "reserve"
    RELEASE = "release"


# ============================================================
# REQUEST MODELS
# ============================================================

class BinCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    bin_code: str = Field(
        min_length=1,
        max_length=64,
    )

    zone: str = Field(
        min_length=1,
        max_length=64,
    )

    aisle: str = Field(
        min_length=1,
        max_length=64,
    )

    rack: str = Field(
        min_length=1,
        max_length=64,
    )

    shelf: str = Field(
        min_length=1,
        max_length=64,
    )

    bin_type: BinType = BinType.STANDARD

    capacity_units: int = Field(
        gt=0,
        le=1_000_000,
    )


class BinStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: BinStatus

    expected_version: int = Field(ge=1)


class BinStockOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    quantity: int = Field(
        gt=0,
        le=1_000_000,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    expected_version: int = Field(ge=1)


class BinTransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_bin_id: str
    destination_bin_id: str
    product_id: str

    quantity: int = Field(
        gt=0,
        le=1_000_000,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    expected_source_version: int = Field(
        ge=1
    )

    expected_destination_version: int = Field(
        ge=1
    )


# ============================================================
# RESPONSE MODELS
# ============================================================

class BinProductBalance(BaseModel):
    product_id: str
    quantity_on_hand: int
    quantity_reserved: int
    quantity_available: int


class BinResponse(BaseModel):
    bin_id: str
    warehouse_id: str
    bin_code: str

    zone: str
    aisle: str
    rack: str
    shelf: str

    bin_type: BinType
    status: BinStatus

    capacity_units: int
    occupied_units: int
    available_capacity_units: int
    utilization_percent: float

    products: list[BinProductBalance]

    version: int
    created_at: datetime
    updated_at: datetime


class BinMovementResponse(BaseModel):
    movement_id: str
    warehouse_id: str

    movement_type: BinMovementType

    source_bin_id: str | None
    destination_bin_id: str | None

    product_id: str
    quantity: int

    actor_id: str
    source_request_id: str

    timestamp: datetime


class BinTransferResponse(BaseModel):
    movement: BinMovementResponse
    source: BinResponse
    destination: BinResponse


class BinCapacitySummary(BaseModel):
    warehouse_id: str
    total_bins: int
    active_bins: int
    blocked_bins: int
    total_capacity_units: int
    occupied_units: int
    available_capacity_units: int
    utilization_percent: float


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass
class ProductBalance:
    on_hand: int = 0
    reserved: int = 0


@dataclass
class BinRecord:
    bin_id: str
    tenant_id: str
    warehouse_id: str
    bin_code: str

    zone: str
    aisle: str
    rack: str
    shelf: str

    bin_type: BinType
    capacity_units: int

    status: BinStatus = BinStatus.ACTIVE

    products: dict[str, ProductBalance] = field(
        default_factory=dict
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


def occupied_units(record: BinRecord) -> int:
    return sum(
        balance.on_hand
        for balance in record.products.values()
    )


def available_capacity(record: BinRecord) -> int:
    return max(
        0,
        record.capacity_units - occupied_units(record),
    )


def utilization_percent(
    occupied: int,
    capacity: int,
) -> float:

    if capacity <= 0:
        return 0.0

    return round(
        occupied / capacity * 100,
        2,
    )


def to_bin_response(
    record: BinRecord,
) -> BinResponse:

    occupied = occupied_units(record)

    products = [
        BinProductBalance(
            product_id=product_id,
            quantity_on_hand=balance.on_hand,
            quantity_reserved=balance.reserved,
            quantity_available=(
                balance.on_hand - balance.reserved
            ),
        )
        for product_id, balance
        in sorted(record.products.items())
    ]

    return BinResponse(
        bin_id=record.bin_id,
        warehouse_id=record.warehouse_id,
        bin_code=record.bin_code,
        zone=record.zone,
        aisle=record.aisle,
        rack=record.rack,
        shelf=record.shelf,
        bin_type=record.bin_type,
        status=record.status,
        capacity_units=record.capacity_units,
        occupied_units=occupied,
        available_capacity_units=available_capacity(
            record
        ),
        utilization_percent=utilization_percent(
            occupied,
            record.capacity_units,
        ),
        products=products,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def request_fingerprint(
    operation: str,
    payload: BaseModel,
) -> str:

    canonical = json.dumps(
        {
            "operation": operation,
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


# ============================================================
# AUTHORIZATION
# ============================================================

def require_bin_permission(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool = False,
) -> None:

    permission = (
        Permission.INVENTORY_WRITE
        if write
        else Permission.INVENTORY_READ
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
            detail="Bin access denied",
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


# ============================================================
# BIN STORE
# ============================================================

class BinStore:

    def __init__(self):

        self._bins: dict[
            str,
            BinRecord,
        ] = {}

        self._codes: dict[
            tuple[str, str, str],
            str,
        ] = {}

        self._movements: dict[
            str,
            list[BinMovementResponse],
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, object],
        ] = {}

        self._lock = asyncio.Lock()

    def _get_record(
        self,
        tenant_id: str,
        bin_id: str,
    ) -> BinRecord:

        record = self._bins.get(bin_id)

        if (
            record is None
            or record.tenant_id != tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Bin not found",
            )

        return record

    @staticmethod
    def _check_version(
        record: BinRecord,
        expected: int,
    ) -> None:

        if record.version != expected:
            raise HTTPException(
                status_code=409,
                detail="Bin version conflict",
            )

    @staticmethod
    def _require_active(
        record: BinRecord,
    ) -> None:

        if record.status != BinStatus.ACTIVE:
            raise HTTPException(
                status_code=409,
                detail="Bin is not active",
            )

    def _check_idempotency(
        self,
        key: tuple[str, str, str],
        fingerprint: str,
    ) -> object | None:

        existing = self._idempotency.get(key)

        if existing is None:
            return None

        old_fingerprint, result = existing

        if old_fingerprint != fingerprint:
            raise HTTPException(
                status_code=409,
                detail="Idempotency key conflict",
            )

        return result

    def _record_movement(
        self,
        *,
        tenant_id: str,
        warehouse_id: str,
        movement_type: BinMovementType,
        source_bin_id: str | None,
        destination_bin_id: str | None,
        product_id: str,
        quantity: int,
        actor_id: str,
        source_request_id: str,
    ) -> BinMovementResponse:

        history = self._movements.setdefault(
            tenant_id,
            [],
        )

        if len(history) >= MAX_MOVEMENTS_PER_TENANT:
            raise HTTPException(
                status_code=503,
                detail="Movement history capacity reached",
            )

        movement = BinMovementResponse(
            movement_id=secrets.token_urlsafe(18),
            warehouse_id=warehouse_id,
            movement_type=movement_type,
            source_bin_id=source_bin_id,
            destination_bin_id=destination_bin_id,
            product_id=product_id,
            quantity=quantity,
            actor_id=actor_id,
            source_request_id=source_request_id,
            timestamp=utc_now(),
        )

        history.append(movement)

        return movement

    async def create(
        self,
        *,
        principal: Principal,
        payload: BinCreate,
    ) -> BinResponse:

        require_bin_permission(
            principal,
            payload.warehouse_id,
            write=True,
        )

        async with self._lock:

            code_key = (
                principal.tenant_id,
                payload.warehouse_id,
                payload.bin_code.upper(),
            )

            if code_key in self._codes:
                raise HTTPException(
                    status_code=409,
                    detail="Bin code already exists",
                )

            count = sum(
                record.tenant_id == principal.tenant_id
                for record in self._bins.values()
            )

            if count >= MAX_BINS_PER_TENANT:
                raise HTTPException(
                    status_code=503,
                    detail="Bin capacity limit reached",
                )

            record = BinRecord(
                bin_id=secrets.token_urlsafe(18),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                bin_code=payload.bin_code.upper(),
                zone=payload.zone,
                aisle=payload.aisle,
                rack=payload.rack,
                shelf=payload.shelf,
                bin_type=payload.bin_type,
                capacity_units=payload.capacity_units,
            )

            self._bins[record.bin_id] = record
            self._codes[code_key] = record.bin_id

            return to_bin_response(record)

    async def get(
        self,
        *,
        principal: Principal,
        bin_id: str,
    ) -> BinResponse:

        async with self._lock:

            record = self._get_record(
                principal.tenant_id,
                bin_id,
            )

            require_bin_permission(
                principal,
                record.warehouse_id,
            )

            return to_bin_response(record)

    async def list_bins(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
        status: BinStatus | None,
        limit: int,
    ) -> list[BinResponse]:

        require_bin_permission(
            principal,
            warehouse_id,
        )

        async with self._lock:

            records = [
                record
                for record in self._bins.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and record.warehouse_id
                    == warehouse_id
                    and (
                        status is None
                        or record.status == status
                    )
                )
            ]

            records.sort(
                key=lambda item: item.bin_code
            )

            return [
                to_bin_response(record)
                for record in records[:limit]
            ]

    async def update_status(
        self,
        *,
        principal: Principal,
        bin_id: str,
        payload: BinStatusUpdate,
    ) -> BinResponse:

        async with self._lock:

            record = self._get_record(
                principal.tenant_id,
                bin_id,
            )

            require_bin_permission(
                principal,
                record.warehouse_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if (
                payload.status == BinStatus.INACTIVE
                and occupied_units(record) > 0
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Cannot deactivate a bin "
                        "containing inventory"
                    ),
                )

            record.status = payload.status
            record.version += 1
            record.updated_at = utc_now()

            return to_bin_response(record)

    async def stock_operation(
        self,
        *,
        principal: Principal,
        bin_id: str,
        payload: BinStockOperation,
        movement_type: BinMovementType,
    ) -> BinResponse:

        fingerprint = request_fingerprint(
            f"{movement_type.value}:{bin_id}",
            payload,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        async with self._lock:

            record = self._get_record(
                principal.tenant_id,
                bin_id,
            )

            require_bin_permission(
                principal,
                record.warehouse_id,
                write=True,
            )

            existing = self._check_idempotency(
                key,
                fingerprint,
            )

            if existing is not None:
                return existing.model_copy(
                    deep=True
                )

            self._require_active(record)

            self._check_version(
                record,
                payload.expected_version,
            )

            current = record.products.get(
                payload.product_id,
                ProductBalance(),
            )

            on_hand = current.on_hand
            reserved = current.reserved

            if movement_type == BinMovementType.PUTAWAY:

                if (
                    available_capacity(record)
                    < payload.quantity
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Insufficient bin capacity",
                    )

                on_hand += payload.quantity

            elif movement_type == BinMovementType.PICK:

                if (
                    on_hand - reserved
                    < payload.quantity
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Insufficient available stock",
                    )

                on_hand -= payload.quantity

            elif movement_type == BinMovementType.RESERVE:

                if (
                    on_hand - reserved
                    < payload.quantity
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Insufficient stock to reserve",
                    )

                reserved += payload.quantity

            elif movement_type == BinMovementType.RELEASE:

                if reserved < payload.quantity:
                    raise HTTPException(
                        status_code=409,
                        detail="Insufficient reserved stock",
                    )

                reserved -= payload.quantity

            else:
                raise HTTPException(
                    status_code=422,
                    detail="Unsupported stock operation",
                )

            # Check bounded history before mutation.
            history = self._movements.get(
                principal.tenant_id,
                [],
            )

            if len(history) >= MAX_MOVEMENTS_PER_TENANT:
                raise HTTPException(
                    status_code=503,
                    detail="Movement history capacity reached",
                )

            if len(self._idempotency) >= MAX_IDEMPOTENCY_KEYS:
                raise HTTPException(
                    status_code=503,
                    detail="Idempotency storage full",
                )

            record.products[payload.product_id] = (
                ProductBalance(
                    on_hand=on_hand,
                    reserved=reserved,
                )
            )

            record.version += 1
            record.updated_at = utc_now()

            self._record_movement(
                tenant_id=principal.tenant_id,
                warehouse_id=record.warehouse_id,
                movement_type=movement_type,
                source_bin_id=(
                    bin_id
                    if movement_type
                    == BinMovementType.PICK
                    else None
                ),
                destination_bin_id=(
                    bin_id
                    if movement_type
                    == BinMovementType.PUTAWAY
                    else None
                ),
                product_id=payload.product_id,
                quantity=payload.quantity,
                actor_id=principal.principal_id,
                source_request_id=payload.source_request_id,
            )

            result = to_bin_response(record)

            self._idempotency[key] = (
                fingerprint,
                result.model_copy(deep=True),
            )

            return result

    async def transfer(
        self,
        *,
        principal: Principal,
        payload: BinTransferRequest,
    ) -> BinTransferResponse:

        if (
            payload.source_bin_id
            == payload.destination_bin_id
        ):
            raise HTTPException(
                status_code=422,
                detail="Source and destination must differ",
            )

        fingerprint = request_fingerprint(
            "transfer",
            payload,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        async with self._lock:

            source = self._get_record(
                principal.tenant_id,
                payload.source_bin_id,
            )

            destination = self._get_record(
                principal.tenant_id,
                payload.destination_bin_id,
            )

            if (
                source.warehouse_id
                != destination.warehouse_id
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Cross-warehouse transfers require "
                        "the inventory transfer service"
                    ),
                )

            require_bin_permission(
                principal,
                source.warehouse_id,
                write=True,
            )

            existing = self._check_idempotency(
                key,
                fingerprint,
            )

            if existing is not None:
                return existing.model_copy(
                    deep=True
                )

            self._require_active(source)
            self._require_active(destination)

            self._check_version(
                source,
                payload.expected_source_version,
            )

            self._check_version(
                destination,
                payload.expected_destination_version,
            )

            source_balance = source.products.get(
                payload.product_id,
                ProductBalance(),
            )

            destination_balance = (
                destination.products.get(
                    payload.product_id,
                    ProductBalance(),
                )
            )

            if (
                source_balance.on_hand
                - source_balance.reserved
                < payload.quantity
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Insufficient transferable stock",
                )

            if (
                available_capacity(destination)
                < payload.quantity
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Destination capacity exceeded",
                )

            if (
                len(
                    self._movements.get(
                        principal.tenant_id,
                        [],
                    )
                )
                >= MAX_MOVEMENTS_PER_TENANT
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Movement history capacity reached",
                )

            if len(self._idempotency) >= MAX_IDEMPOTENCY_KEYS:
                raise HTTPException(
                    status_code=503,
                    detail="Idempotency storage full",
                )

            source_balance.on_hand -= payload.quantity
            destination_balance.on_hand += payload.quantity

            source.products[
                payload.product_id
            ] = source_balance

            destination.products[
                payload.product_id
            ] = destination_balance

            now = utc_now()

            source.version += 1
            destination.version += 1

            source.updated_at = now
            destination.updated_at = now

            movement = self._record_movement(
                tenant_id=principal.tenant_id,
                warehouse_id=source.warehouse_id,
                movement_type=BinMovementType.TRANSFER,
                source_bin_id=source.bin_id,
                destination_bin_id=destination.bin_id,
                product_id=payload.product_id,
                quantity=payload.quantity,
                actor_id=principal.principal_id,
                source_request_id=payload.source_request_id,
            )

            result = BinTransferResponse(
                movement=movement,
                source=to_bin_response(source),
                destination=to_bin_response(destination),
            )

            self._idempotency[key] = (
                fingerprint,
                result.model_copy(deep=True),
            )

            return result

    async def movements(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
        bin_id: str | None,
        limit: int,
    ) -> list[BinMovementResponse]:

        require_bin_permission(
            principal,
            warehouse_id,
        )

        async with self._lock:

            history = [
                item
                for item in self._movements.get(
                    principal.tenant_id,
                    [],
                )
                if (
                    item.warehouse_id == warehouse_id
                    and (
                        bin_id is None
                        or item.source_bin_id == bin_id
                        or item.destination_bin_id == bin_id
                    )
                )
            ]

            return [
                item.model_copy(deep=True)
                for item in reversed(history[-limit:])
            ]

    async def capacity_summary(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
    ) -> BinCapacitySummary:

        require_bin_permission(
            principal,
            warehouse_id,
        )

        async with self._lock:

            bins = [
                record
                for record in self._bins.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and record.warehouse_id
                    == warehouse_id
                )
            ]

            total_capacity = sum(
                record.capacity_units
                for record in bins
            )

            occupied = sum(
                occupied_units(record)
                for record in bins
            )

            return BinCapacitySummary(
                warehouse_id=warehouse_id,
                total_bins=len(bins),
                active_bins=sum(
                    record.status == BinStatus.ACTIVE
                    for record in bins
                ),
                blocked_bins=sum(
                    record.status == BinStatus.BLOCKED
                    for record in bins
                ),
                total_capacity_units=total_capacity,
                occupied_units=occupied,
                available_capacity_units=sum(
                    available_capacity(record)
                    for record in bins
                    if record.status == BinStatus.ACTIVE
                ),
                utilization_percent=utilization_percent(
                    occupied,
                    total_capacity,
                ),
            )


bin_store = BinStore()


# ============================================================
# BIN SERVICE
# ============================================================

class BinService:

    def __init__(
        self,
        store: BinStore,
    ):
        self.store = store

    async def putaway(
        self,
        principal: Principal,
        bin_id: str,
        payload: BinStockOperation,
    ) -> BinResponse:

        return await self.store.stock_operation(
            principal=principal,
            bin_id=bin_id,
            payload=payload,
            movement_type=BinMovementType.PUTAWAY,
        )

    async def pick(
        self,
        principal: Principal,
        bin_id: str,
        payload: BinStockOperation,
    ) -> BinResponse:

        return await self.store.stock_operation(
            principal=principal,
            bin_id=bin_id,
            payload=payload,
            movement_type=BinMovementType.PICK,
        )

    async def reserve(
        self,
        principal: Principal,
        bin_id: str,
        payload: BinStockOperation,
    ) -> BinResponse:

        return await self.store.stock_operation(
            principal=principal,
            bin_id=bin_id,
            payload=payload,
            movement_type=BinMovementType.RESERVE,
        )

    async def release(
        self,
        principal: Principal,
        bin_id: str,
        payload: BinStockOperation,
    ) -> BinResponse:

        return await self.store.stock_operation(
            principal=principal,
            bin_id=bin_id,
            payload=payload,
            movement_type=BinMovementType.RELEASE,
        )


bin_service = BinService(bin_store)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Warehouse Bins"],
)


@router.post(
    "",
    response_model=BinResponse,
    status_code=201,
)
async def create_bin(
    payload: BinCreate,
    principal: CurrentPrincipal,
):
    return await bin_store.create(
        principal=principal,
        payload=payload,
    )


@router.get(
    "",
    response_model=list[BinResponse],
)
async def list_bins(
    principal: CurrentPrincipal,
    warehouse_id: str,
    status: BinStatus | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await bin_store.list_bins(
        principal=principal,
        warehouse_id=warehouse_id,
        status=status,
        limit=limit,
    )


@router.get(
    "/capacity/{warehouse_id}",
    response_model=BinCapacitySummary,
)
async def get_capacity(
    warehouse_id: str,
    principal: CurrentPrincipal,
):
    return await bin_store.capacity_summary(
        principal=principal,
        warehouse_id=warehouse_id,
    )


@router.get(
    "/movements/{warehouse_id}",
    response_model=list[BinMovementResponse],
)
async def get_movements(
    warehouse_id: str,
    principal: CurrentPrincipal,
    bin_id: str | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await bin_store.movements(
        principal=principal,
        warehouse_id=warehouse_id,
        bin_id=bin_id,
        limit=limit,
    )


@router.post(
    "/transfer",
    response_model=BinTransferResponse,
)
async def transfer_stock(
    payload: BinTransferRequest,
    principal: CurrentPrincipal,
):
    return await bin_store.transfer(
        principal=principal,
        payload=payload,
    )


@router.get(
    "/{bin_id}",
    response_model=BinResponse,
)
async def get_bin(
    bin_id: str,
    principal: CurrentPrincipal,
):
    return await bin_store.get(
        principal=principal,
        bin_id=bin_id,
    )


@router.patch(
    "/{bin_id}/status",
    response_model=BinResponse,
)
async def update_bin_status(
    bin_id: str,
    payload: BinStatusUpdate,
    principal: CurrentPrincipal,
):
    return await bin_store.update_status(
        principal=principal,
        bin_id=bin_id,
        payload=payload,
    )


@router.post(
    "/{bin_id}/putaway",
    response_model=BinResponse,
)
async def putaway_stock(
    bin_id: str,
    payload: BinStockOperation,
    principal: CurrentPrincipal,
):
    return await bin_service.putaway(
        principal,
        bin_id,
        payload,
    )


@router.post(
    "/{bin_id}/pick",
    response_model=BinResponse,
)
async def pick_stock(
    bin_id: str,
    payload: BinStockOperation,
    principal: CurrentPrincipal,
):
    return await bin_service.pick(
        principal,
        bin_id,
        payload,
    )


@router.post(
    "/{bin_id}/reserve",
    response_model=BinResponse,
)
async def reserve_stock(
    bin_id: str,
    payload: BinStockOperation,
    principal: CurrentPrincipal,
):
    return await bin_service.reserve(
        principal,
        bin_id,
        payload,
    )


@router.post(
    "/{bin_id}/release",
    response_model=BinResponse,
)
async def release_stock(
    bin_id: str,
    payload: BinStockOperation,
    principal: CurrentPrincipal,
):
    return await bin_service.release(
        principal,
        bin_id,
        payload,
    )


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "BinStatus",
    "BinType",
    "BinMovementType",
    "BinCreate",
    "BinStatusUpdate",
    "BinStockOperation",
    "BinTransferRequest",
    "BinProductBalance",
    "BinResponse",
    "BinMovementResponse",
    "BinTransferResponse",
    "BinCapacitySummary",
    "BinStore",
    "BinService",
    "bin_store",
    "bin_service",
    "router",
]
