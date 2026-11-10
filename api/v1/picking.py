from __future__ import annotations

"""Planned module: picking. Implementation pending."""

"""
backend/picking.py

Autonomous Retail Supply Chain AI 5.0
Warehouse Picking Management API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Pick list creation
    - Warehouse picker assignment
    - Bin and SKU verification
    - Partial picking and short picks
    - Pick quantity tracking
    - Picking verification
    - Packing handoff readiness
    - Cancellation
    - Warehouse picking analytics
    - Tenant and warehouse authorization
    - Optimistic concurrency
    - Idempotent pick list creation

Prototype limitations:
    - In-memory state only
    - No real inventory reservations
    - No scanner hardware integration
    - No actual inventory decrement
    - No automatic packing job creation
    - No durable audit storage
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


API_PREFIX = "/api/v1/picking"

MAX_PICK_LISTS_PER_TENANT = 50000
MAX_ITEMS_PER_PICK_LIST = 200
MAX_EVENTS_PER_PICK_LIST = 500
MAX_IDEMPOTENCY_KEYS = 100000
MAX_LIST_LIMIT = 200


# ============================================================
# ENUMS
# ============================================================

class PickingStatus(str, Enum):
    CREATED = "created"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    VERIFICATION_PENDING = "verification_pending"
    VERIFIED = "verified"
    READY_FOR_PACKING = "ready_for_packing"
    CANCELLED = "cancelled"


class PickingPriority(str, Enum):
    STANDARD = "standard"
    EXPRESS = "express"
    CRITICAL = "critical"


class PickingStrategy(str, Enum):
    SINGLE_ORDER = "single_order"
    BATCH = "batch"
    ZONE = "zone"
    WAVE = "wave"


class PickItemStatus(str, Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    PICKED = "picked"
    SHORT_PICKED = "short_picked"


class PickingEventType(str, Enum):
    CREATED = "created"
    ASSIGNED = "assigned"
    STARTED = "started"
    ITEM_PICKED = "item_picked"
    SHORT_PICK_RECORDED = "short_pick_recorded"
    VERIFICATION_STARTED = "verification_started"
    VERIFIED = "verified"
    READY_FOR_PACKING = "ready_for_packing"
    CANCELLED = "cancelled"


# ============================================================
# REQUEST MODELS
# ============================================================

class PickItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    sku: str = Field(
        min_length=1,
        max_length=100,
    )

    bin_id: str = Field(
        min_length=1,
        max_length=128,
    )

    required_quantity: int = Field(
        gt=0,
        le=100000,
    )


class PickListCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    fulfillment_id: str = Field(
        min_length=1,
        max_length=128,
    )

    order_id: str = Field(
        min_length=1,
        max_length=128,
    )

    priority: PickingPriority = (
        PickingPriority.STANDARD
    )

    strategy: PickingStrategy = (
        PickingStrategy.SINGLE_ORDER
    )

    items: list[PickItemCreate] = Field(
        min_length=1,
        max_length=MAX_ITEMS_PER_PICK_LIST,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_items(self):

        keys = [
            (item.product_id, item.bin_id)
            for item in self.items
        ]

        if len(set(keys)) != len(keys):
            raise ValueError(
                "Duplicate product/bin combinations"
            )

        sku_by_product = {}

        for item in self.items:

            existing = sku_by_product.get(
                item.product_id
            )

            if (
                existing is not None
                and existing != item.sku
            ):
                raise ValueError(
                    "A product cannot have conflicting SKUs"
                )

            sku_by_product[
                item.product_id
            ] = item.sku

        return self


class PickerAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    picker_id: str = Field(
        min_length=1,
        max_length=128,
    )

    expected_version: int = Field(ge=1)


class PickingVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class PickItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    scanned_sku: str = Field(
        min_length=1,
        max_length=100,
    )

    scanned_bin_id: str = Field(
        min_length=1,
        max_length=128,
    )

    quantity: int = Field(
        gt=0,
        le=100000,
    )

    expected_version: int = Field(ge=1)


class ShortPickRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    bin_id: str = Field(
        min_length=1,
        max_length=128,
    )

    short_quantity: int = Field(
        gt=0,
        le=100000,
    )

    reason: str = Field(
        min_length=3,
        max_length=500,
    )

    expected_version: int = Field(ge=1)


class PickingVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    verification_reference: str = Field(
        min_length=1,
        max_length=200,
    )

    accept_short_picks: bool = False


class PickingCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    reason: str = Field(
        min_length=3,
        max_length=500,
    )


# ============================================================
# RESPONSE MODELS
# ============================================================

class PickItemResponse(BaseModel):
    product_id: str
    sku: str
    bin_id: str

    required_quantity: int
    picked_quantity: int
    short_quantity: int
    remaining_quantity: int

    status: PickItemStatus


class PickingEventResponse(BaseModel):
    event_id: str
    event_type: PickingEventType

    actor_id: str
    details: str | None

    created_at: datetime


class PickListResponse(BaseModel):
    pick_list_id: str

    warehouse_id: str
    fulfillment_id: str
    order_id: str

    priority: PickingPriority
    strategy: PickingStrategy
    status: PickingStatus

    picker_id: str | None

    total_required_quantity: int
    total_picked_quantity: int
    total_short_quantity: int

    item_count: int

    version: int

    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class PickListDetailResponse(PickListResponse):
    items: list[PickItemResponse]
    events: list[PickingEventResponse]
    verification_reference: str | None


class PickingAnalyticsResponse(BaseModel):
    total_pick_lists: int

    created: int
    assigned: int
    in_progress: int
    verification_pending: int
    verified: int
    ready_for_packing: int
    cancelled: int

    total_required_units: int
    total_picked_units: int
    total_short_units: int

    average_completion_minutes: float | None


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass
class PickItemRecord:
    product_id: str
    sku: str
    bin_id: str

    required_quantity: int

    picked_quantity: int = 0
    short_quantity: int = 0

    @property
    def remaining_quantity(self) -> int:

        return (
            self.required_quantity
            - self.picked_quantity
            - self.short_quantity
        )

    @property
    def status(self) -> PickItemStatus:

        if self.remaining_quantity == 0:

            if self.short_quantity > 0:
                return PickItemStatus.SHORT_PICKED

            return PickItemStatus.PICKED

        if (
            self.picked_quantity > 0
            or self.short_quantity > 0
        ):
            return PickItemStatus.PARTIAL

        return PickItemStatus.PENDING


@dataclass
class PickListRecord:
    pick_list_id: str
    tenant_id: str

    warehouse_id: str
    fulfillment_id: str
    order_id: str

    priority: PickingPriority
    strategy: PickingStrategy

    items: dict[
        tuple[str, str],
        PickItemRecord,
    ]

    created_by: str

    status: PickingStatus = (
        PickingStatus.CREATED
    )

    picker_id: str | None = None

    verification_reference: str | None = None

    events: list[
        PickingEventResponse
    ] = field(default_factory=list)

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

    completed_at: datetime | None = None


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def request_fingerprint(
    payload: PickListCreate,
) -> str:

    canonical = json.dumps(
        payload.model_dump(
            mode="json",
            exclude={"source_request_id"},
        ),
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def require_picking_access(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool,
) -> None:

    # Temporary mapping to existing permissions.
    #
    # Production:
    # PICKING_READ
    # PICKING_WRITE
    # PICKING_VERIFY

    permission = (
        Permission.INVENTORY_WRITE
        if write
        else Permission.INVENTORY_READ
    )

    if (
        principal.allowed_warehouse_ids is not None
        and warehouse_id
        not in principal.allowed_warehouse_ids
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
            detail="Picking access denied",
        )


def to_item_response(
    item: PickItemRecord,
) -> PickItemResponse:

    return PickItemResponse(
        product_id=item.product_id,
        sku=item.sku,
        bin_id=item.bin_id,
        required_quantity=item.required_quantity,
        picked_quantity=item.picked_quantity,
        short_quantity=item.short_quantity,
        remaining_quantity=item.remaining_quantity,
        status=item.status,
    )


def to_response(
    record: PickListRecord,
) -> PickListResponse:

    items = list(
        record.items.values()
    )

    return PickListResponse(
        pick_list_id=record.pick_list_id,
        warehouse_id=record.warehouse_id,
        fulfillment_id=record.fulfillment_id,
        order_id=record.order_id,
        priority=record.priority,
        strategy=record.strategy,
        status=record.status,
        picker_id=record.picker_id,
        total_required_quantity=sum(
            item.required_quantity
            for item in items
        ),
        total_picked_quantity=sum(
            item.picked_quantity
            for item in items
        ),
        total_short_quantity=sum(
            item.short_quantity
            for item in items
        ),
        item_count=len(items),
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
    )


def to_detail(
    record: PickListRecord,
) -> PickListDetailResponse:

    return PickListDetailResponse(
        **to_response(record).model_dump(),
        items=[
            to_item_response(item)
            for item in record.items.values()
        ],
        events=list(record.events),
        verification_reference=(
            record.verification_reference
        ),
    )


# ============================================================
# PICKING STORE
# ============================================================

class PickingStore:

    def __init__(self):

        self._pick_lists: dict[
            str,
            PickListRecord,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    def _get(
        self,
        principal: Principal,
        pick_list_id: str,
        *,
        write: bool,
    ) -> PickListRecord:

        record = self._pick_lists.get(
            pick_list_id
        )

        if (
            record is None
            or record.tenant_id
            != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Pick list not found",
            )

        require_picking_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    @staticmethod
    def _check_version(
        record: PickListRecord,
        expected_version: int,
    ) -> None:

        if record.version != expected_version:
            raise HTTPException(
                status_code=409,
                detail="Pick list version conflict",
            )

    @staticmethod
    def _require_status(
        record: PickListRecord,
        allowed: set[PickingStatus],
    ) -> None:

        if record.status not in allowed:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Picking operation is not allowed "
                    f"in status {record.status.value}"
                ),
            )

    @staticmethod
    def _add_event(
        record: PickListRecord,
        event_type: PickingEventType,
        actor_id: str,
        details: str | None = None,
    ) -> None:

        if (
            len(record.events)
            >= MAX_EVENTS_PER_PICK_LIST
        ):
            raise HTTPException(
                status_code=503,
                detail="Picking event capacity reached",
            )

        record.events.append(
            PickingEventResponse(
                event_id=secrets.token_urlsafe(16),
                event_type=event_type,
                actor_id=actor_id,
                details=details,
                created_at=utc_now(),
            )
        )

    @staticmethod
    def _touch(
        record: PickListRecord,
    ) -> None:

        record.version += 1
        record.updated_at = utc_now()

    async def create(
        self,
        *,
        principal: Principal,
        payload: PickListCreate,
    ) -> PickListResponse:

        require_picking_access(
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
            payload
        )

        async with self._lock:

            previous = self._idempotency.get(
                key
            )

            if previous is not None:

                old_hash, pick_list_id = previous

                if old_hash != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return to_response(
                    self._get(
                        principal,
                        pick_list_id,
                        write=False,
                    )
                )

            tenant_count = sum(
                record.tenant_id
                == principal.tenant_id
                for record in self._pick_lists.values()
            )

            if (
                tenant_count
                >= MAX_PICK_LISTS_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Picking capacity reached",
                )

            record = PickListRecord(
                pick_list_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                fulfillment_id=payload.fulfillment_id,
                order_id=payload.order_id,
                priority=payload.priority,
                strategy=payload.strategy,
                items={
                    (
                        item.product_id,
                        item.bin_id,
                    ): PickItemRecord(
                        product_id=item.product_id,
                        sku=item.sku,
                        bin_id=item.bin_id,
                        required_quantity=(
                            item.required_quantity
                        ),
                    )
                    for item in payload.items
                },
                created_by=principal.principal_id,
            )

            self._add_event(
                record,
                PickingEventType.CREATED,
                principal.principal_id,
            )

            self._pick_lists[
                record.pick_list_id
            ] = record

            self._idempotency[key] = (
                request_hash,
                record.pick_list_id,
            )

            return to_response(record)

    async def get(
        self,
        *,
        principal: Principal,
        pick_list_id: str,
    ) -> PickListDetailResponse:

        async with self._lock:

            return to_detail(
                self._get(
                    principal,
                    pick_list_id,
                    write=False,
                )
            )

    async def list_pick_lists(
        self,
        *,
        principal: Principal,
        warehouse_id: str | None,
        status: PickingStatus | None,
        limit: int,
    ) -> list[PickListResponse]:

        if warehouse_id is not None:
            require_picking_access(
                principal,
                warehouse_id,
                write=False,
            )

        async with self._lock:

            records = [
                record
                for record in self._pick_lists.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and (
                        warehouse_id is None
                        or record.warehouse_id
                        == warehouse_id
                    )
                    and (
                        status is None
                        or record.status == status
                    )
                )
            ]

            records.sort(
                key=lambda item: item.created_at,
                reverse=True,
            )

            results = []

            for record in records:

                try:
                    require_picking_access(
                        principal,
                        record.warehouse_id,
                        write=False,
                    )

                except HTTPException:
                    continue

                results.append(
                    to_response(record)
                )

                if len(results) >= limit:
                    break

            return results

    async def assign(
        self,
        *,
        principal: Principal,
        pick_list_id: str,
        payload: PickerAssignment,
    ) -> PickListResponse:

        async with self._lock:

            record = self._get(
                principal,
                pick_list_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {PickingStatus.CREATED},
            )

            record.picker_id = payload.picker_id
            record.status = PickingStatus.ASSIGNED

            self._add_event(
                record,
                PickingEventType.ASSIGNED,
                principal.principal_id,
                payload.picker_id,
            )

            self._touch(record)

            return to_response(record)

    async def start(
        self,
        *,
        principal: Principal,
        pick_list_id: str,
        expected_version: int,
    ) -> PickListResponse:

        async with self._lock:

            record = self._get(
                principal,
                pick_list_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            self._require_status(
                record,
                {PickingStatus.ASSIGNED},
            )

            record.status = PickingStatus.IN_PROGRESS

            self._add_event(
                record,
                PickingEventType.STARTED,
                principal.principal_id,
            )

            self._touch(record)

            return to_response(record)

    async def pick_item(
        self,
        *,
        principal: Principal,
        pick_list_id: str,
        payload: PickItemRequest,
    ) -> PickListDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                pick_list_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {PickingStatus.IN_PROGRESS},
            )

            key = (
                payload.product_id,
                payload.scanned_bin_id,
            )

            item = record.items.get(
                key
            )

            if item is None:
                raise HTTPException(
                    status_code=404,
                    detail="Product/bin not found in pick list",
                )

            if item.sku != payload.scanned_sku:
                raise HTTPException(
                    status_code=422,
                    detail="Scanned SKU mismatch",
                )

            if payload.quantity > item.remaining_quantity:
                raise HTTPException(
                    status_code=409,
                    detail="Quantity exceeds remaining requirement",
                )

            self._add_event(
                record,
                PickingEventType.ITEM_PICKED,
                principal.principal_id,
                (
                    f"{payload.product_id}: "
                    f"{payload.quantity}"
                ),
            )

            item.picked_quantity += payload.quantity

            self._touch(record)

            return to_detail(record)

    async def short_pick(
        self,
        *,
        principal: Principal,
        pick_list_id: str,
        payload: ShortPickRequest,
    ) -> PickListDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                pick_list_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {PickingStatus.IN_PROGRESS},
            )

            item = record.items.get(
                (
                    payload.product_id,
                    payload.bin_id,
                )
            )

            if item is None:
                raise HTTPException(
                    status_code=404,
                    detail="Pick item not found",
                )

            if (
                payload.short_quantity
                > item.remaining_quantity
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Short quantity exceeds remaining units",
                )

            self._add_event(
                record,
                PickingEventType.SHORT_PICK_RECORDED,
                principal.principal_id,
                payload.reason,
            )

            item.short_quantity += (
                payload.short_quantity
            )

            self._touch(record)

            return to_detail(record)

    async def start_verification(
        self,
        *,
        principal: Principal,
        pick_list_id: str,
        expected_version: int,
    ) -> PickListResponse:

        async with self._lock:

            record = self._get(
                principal,
                pick_list_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            self._require_status(
                record,
                {PickingStatus.IN_PROGRESS},
            )

            if any(
                item.remaining_quantity > 0
                for item in record.items.values()
            ):
                raise HTTPException(
                    status_code=409,
                    detail="All pick lines must be resolved",
                )

            record.status = (
                PickingStatus.VERIFICATION_PENDING
            )

            self._add_event(
                record,
                PickingEventType.VERIFICATION_STARTED,
                principal.principal_id,
            )

            self._touch(record)

            return to_response(record)

    async def verify(
        self,
        *,
        principal: Principal,
        pick_list_id: str,
        payload: PickingVerificationRequest,
    ) -> PickListResponse:

        async with self._lock:

            record = self._get(
                principal,
                pick_list_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {PickingStatus.VERIFICATION_PENDING},
            )

            has_short_picks = any(
                item.short_quantity > 0
                for item in record.items.values()
            )

            if (
                has_short_picks
                and not payload.accept_short_picks
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Short picks require explicit acceptance",
                )

            record.verification_reference = (
                payload.verification_reference
            )

            record.status = PickingStatus.VERIFIED
            record.completed_at = utc_now()

            self._add_event(
                record,
                PickingEventType.VERIFIED,
                principal.principal_id,
                payload.verification_reference,
            )

            self._touch(record)

            return to_response(record)

    async def ready_for_packing(
        self,
        *,
        principal: Principal,
        pick_list_id: str,
        expected_version: int,
    ) -> PickListResponse:

        async with self._lock:

            record = self._get(
                principal,
                pick_list_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            self._require_status(
                record,
                {PickingStatus.VERIFIED},
            )

            record.status = (
                PickingStatus.READY_FOR_PACKING
            )

            self._add_event(
                record,
                PickingEventType.READY_FOR_PACKING,
                principal.principal_id,
            )

            self._touch(record)

            return to_response(record)

    async def cancel(
        self,
        *,
        principal: Principal,
        pick_list_id: str,
        payload: PickingCancelRequest,
    ) -> PickListResponse:

        async with self._lock:

            record = self._get(
                principal,
                pick_list_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status in {
                PickingStatus.VERIFIED,
                PickingStatus.READY_FOR_PACKING,
                PickingStatus.CANCELLED,
            }:
                raise HTTPException(
                    status_code=409,
                    detail="Pick list cannot be cancelled",
                )

            self._add_event(
                record,
                PickingEventType.CANCELLED,
                principal.principal_id,
                payload.reason,
            )

            record.status = PickingStatus.CANCELLED

            self._touch(record)

            return to_response(record)

    async def analytics(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
    ) -> PickingAnalyticsResponse:

        require_picking_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._pick_lists.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and record.warehouse_id
                    == warehouse_id
                )
            ]

            statuses = [
                record.status
                for record in records
            ]

            items = [
                item
                for record in records
                for item in record.items.values()
            ]

            durations = [
                (
                    record.completed_at
                    - record.created_at
                ).total_seconds() / 60
                for record in records
                if record.completed_at is not None
            ]

            return PickingAnalyticsResponse(
                total_pick_lists=len(records),
                created=statuses.count(
                    PickingStatus.CREATED
                ),
                assigned=statuses.count(
                    PickingStatus.ASSIGNED
                ),
                in_progress=statuses.count(
                    PickingStatus.IN_PROGRESS
                ),
                verification_pending=statuses.count(
                    PickingStatus.VERIFICATION_PENDING
                ),
                verified=statuses.count(
                    PickingStatus.VERIFIED
                ),
                ready_for_packing=statuses.count(
                    PickingStatus.READY_FOR_PACKING
                ),
                cancelled=statuses.count(
                    PickingStatus.CANCELLED
                ),
                total_required_units=sum(
                    item.required_quantity
                    for item in items
                ),
                total_picked_units=sum(
                    item.picked_quantity
                    for item in items
                ),
                total_short_units=sum(
                    item.short_quantity
                    for item in items
                ),
                average_completion_minutes=(
                    round(
                        sum(durations) / len(durations),
                        2,
                    )
                    if durations
                    else None
                ),
            )


picking_store = PickingStore()


# ============================================================
# SERVICE
# ============================================================

class PickingService:

    def __init__(
        self,
        store: PickingStore,
    ):
        self.store = store

    async def create(
        self,
        principal: Principal,
        payload: PickListCreate,
    ) -> PickListResponse:

        return await self.store.create(
            principal=principal,
            payload=payload,
        )


picking_service = PickingService(
    picking_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Warehouse Picking"],
)


@router.post(
    "",
    response_model=PickListResponse,
    status_code=201,
)
async def create_pick_list(
    payload: PickListCreate,
    principal: CurrentPrincipal,
):
    return await picking_service.create(
        principal,
        payload,
    )


@router.get(
    "",
    response_model=list[PickListResponse],
)
async def list_pick_lists(
    principal: CurrentPrincipal,
    warehouse_id: str | None = None,
    status: PickingStatus | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await picking_store.list_pick_lists(
        principal=principal,
        warehouse_id=warehouse_id,
        status=status,
        limit=limit,
    )


@router.get(
    "/analytics/{warehouse_id}",
    response_model=PickingAnalyticsResponse,
)
async def picking_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
):
    return await picking_store.analytics(
        principal=principal,
        warehouse_id=warehouse_id,
    )


@router.get(
    "/{pick_list_id}",
    response_model=PickListDetailResponse,
)
async def get_pick_list(
    pick_list_id: str,
    principal: CurrentPrincipal,
):
    return await picking_store.get(
        principal=principal,
        pick_list_id=pick_list_id,
    )


@router.post(
    "/{pick_list_id}/assign",
    response_model=PickListResponse,
)
async def assign_pick_list(
    pick_list_id: str,
    payload: PickerAssignment,
    principal: CurrentPrincipal,
):
    return await picking_store.assign(
        principal=principal,
        pick_list_id=pick_list_id,
        payload=payload,
    )


@router.post(
    "/{pick_list_id}/start",
    response_model=PickListResponse,
)
async def start_pick_list(
    pick_list_id: str,
    payload: PickingVersionRequest,
    principal: CurrentPrincipal,
):
    return await picking_store.start(
        principal=principal,
        pick_list_id=pick_list_id,
        expected_version=payload.expected_version,
    )


@router.post(
    "/{pick_list_id}/pick-item",
    response_model=PickListDetailResponse,
)
async def pick_item(
    pick_list_id: str,
    payload: PickItemRequest,
    principal: CurrentPrincipal,
):
    return await picking_store.pick_item(
        principal=principal,
        pick_list_id=pick_list_id,
        payload=payload,
    )


@router.post(
    "/{pick_list_id}/short-pick",
    response_model=PickListDetailResponse,
)
async def record_short_pick(
    pick_list_id: str,
    payload: ShortPickRequest,
    principal: CurrentPrincipal,
):
    return await picking_store.short_pick(
        principal=principal,
        pick_list_id=pick_list_id,
        payload=payload,
    )


@router.post(
    "/{pick_list_id}/verify-start",
    response_model=PickListResponse,
)
async def start_pick_verification(
    pick_list_id: str,
    payload: PickingVersionRequest,
    principal: CurrentPrincipal,
):
    return await picking_store.start_verification(
        principal=principal,
        pick_list_id=pick_list_id,
        expected_version=payload.expected_version,
    )


@router.post(
    "/{pick_list_id}/verify",
    response_model=PickListResponse,
)
async def verify_pick_list(
    pick_list_id: str,
    payload: PickingVerificationRequest,
    principal: CurrentPrincipal,
):
    return await picking_store.verify(
        principal=principal,
        pick_list_id=pick_list_id,
        payload=payload,
    )


@router.post(
    "/{pick_list_id}/ready-for-packing",
    response_model=PickListResponse,
)
async def ready_for_packing(
    pick_list_id: str,
    payload: PickingVersionRequest,
    principal: CurrentPrincipal,
):
    return await picking_store.ready_for_packing(
        principal=principal,
        pick_list_id=pick_list_id,
        expected_version=payload.expected_version,
    )


@router.post(
    "/{pick_list_id}/cancel",
    response_model=PickListResponse,
)
async def cancel_pick_list(
    pick_list_id: str,
    payload: PickingCancelRequest,
    principal: CurrentPrincipal,
):
    return await picking_store.cancel(
        principal=principal,
        pick_list_id=pick_list_id,
        payload=payload,
    )


__all__ = [
    "PickingStatus",
    "PickingPriority",
    "PickingStrategy",
    "PickItemStatus",
    "PickingEventType",
    "PickItemCreate",
    "PickListCreate",
    "PickerAssignment",
    "PickingVersionRequest",
    "PickItemRequest",
    "ShortPickRequest",
    "PickingVerificationRequest",
    "PickingCancelRequest",
    "PickItemResponse",
    "PickingEventResponse",
    "PickListResponse",
    "PickListDetailResponse",
    "PickingAnalyticsResponse",
    "PickingStore",
    "PickingService",
    "picking_store",
    "picking_service",
    "router",
]
