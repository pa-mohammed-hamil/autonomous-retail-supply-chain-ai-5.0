from __future__ import annotations

"""Planned module: returns. Implementation pending."""

"""
backend/returns.py

Autonomous Retail Supply Chain AI 5.0
Returns & Reverse Logistics Management API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
- Tenant and warehouse isolation
- Return merchandise authorization (RMA)
- Customer and order references
- Multi-item returns
- Return eligibility workflow
- Human approval / rejection
- Reverse logistics tracking
- Goods receipt and inspection
- Restock, quarantine, repair, disposal decisions
- Refund and replacement workflow
- Idempotent creation
- Optimistic concurrency
- Event history and analytics

Prototype:
- In-memory persistence
- No actual payment refunds
- No real inventory stock movements
- No external courier integrations
- No authoritative order eligibility checks
"""


import asyncio
import hashlib
import json
import secrets

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from fastapi import APIRouter, HTTPException, Query
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


API_PREFIX = "/api/v1/returns"

MAX_RETURNS_PER_TENANT = 50000
MAX_ITEMS_PER_RETURN = 100
MAX_EVENTS_PER_RETURN = 500
MAX_IDEMPOTENCY_KEYS = 100000
MAX_LIST_LIMIT = 200


# ============================================================
# ENUMS
# ============================================================

class ReturnStatus(str, Enum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    AWAITING_PICKUP = "awaiting_pickup"
    IN_TRANSIT = "in_transit"
    RECEIVED = "received"
    INSPECTION_PENDING = "inspection_pending"
    INSPECTED = "inspected"
    RESOLUTION_PENDING = "resolution_pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ReturnReason(str, Enum):
    DAMAGED = "damaged"
    DEFECTIVE = "defective"
    WRONG_ITEM = "wrong_item"
    MISSING_PARTS = "missing_parts"
    NOT_AS_DESCRIBED = "not_as_described"
    CUSTOMER_PREFERENCE = "customer_preference"
    LATE_DELIVERY = "late_delivery"
    OTHER = "other"


class ReturnResolution(str, Enum):
    REFUND = "refund"
    REPLACEMENT = "replacement"
    STORE_CREDIT = "store_credit"
    NO_COMPENSATION = "no_compensation"


class ItemCondition(str, Enum):
    NEW = "new"
    OPEN_BOX = "open_box"
    USED = "used"
    DAMAGED = "damaged"
    DEFECTIVE = "defective"


class Disposition(str, Enum):
    RESTOCK = "restock"
    QUARANTINE = "quarantine"
    REPAIR = "repair"
    RECYCLE = "recycle"
    DISPOSE = "dispose"


class ReturnEventType(str, Enum):
    CREATED = "created"
    APPROVED = "approved"
    REJECTED = "rejected"
    PICKUP_SCHEDULED = "pickup_scheduled"
    SHIPPED = "shipped"
    RECEIVED = "received"
    INSPECTED = "inspected"
    RESOLUTION_SELECTED = "resolution_selected"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# ============================================================
# REQUEST SCHEMAS
# ============================================================

class ReturnItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=128)
    sku: str = Field(min_length=1, max_length=100)

    quantity: int = Field(gt=0, le=100000)

    unit_price: Decimal = Field(
        ge=0,
        max_digits=16,
        decimal_places=2,
    )

    reason: ReturnReason


class ReturnCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(min_length=1, max_length=128)
    order_id: str = Field(min_length=1, max_length=128)
    customer_id: str = Field(min_length=1, max_length=128)

    currency: str = Field(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    )

    items: list[ReturnItemCreate] = Field(
        min_length=1,
        max_length=MAX_ITEMS_PER_RETURN,
    )

    description: str = Field(default="", max_length=2000)

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def unique_products(self):
        ids = [item.product_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate product IDs")
        return self


class ReturnVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class ReturnDecisionRequest(ReturnVersionRequest):
    notes: str = Field(min_length=3, max_length=1000)


class ReturnShipmentRequest(ReturnVersionRequest):
    carrier_id: str = Field(min_length=1, max_length=128)
    tracking_reference: str = Field(
        min_length=1,
        max_length=200,
    )


class ReturnInspectionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=128)
    condition: ItemCondition
    disposition: Disposition
    notes: str = Field(default="", max_length=1000)


class ReturnInspectionRequest(ReturnVersionRequest):
    inspection_reference: str = Field(
        min_length=1,
        max_length=200,
    )

    items: list[ReturnInspectionItem] = Field(
        min_length=1,
        max_length=MAX_ITEMS_PER_RETURN,
    )

    @model_validator(mode="after")
    def unique_items(self):
        ids = [item.product_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate inspection products")
        return self


class ReturnResolutionRequest(ReturnVersionRequest):
    resolution: ReturnResolution

    approved_amount: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        max_digits=16,
        decimal_places=2,
    )

    resolution_reference: str = Field(
        min_length=1,
        max_length=200,
    )

    notes: str = Field(default="", max_length=1000)


class ReturnCompletionRequest(ReturnVersionRequest):
    fulfillment_reference: str = Field(
        min_length=1,
        max_length=200,
    )


class ReturnCancelRequest(ReturnVersionRequest):
    reason: str = Field(min_length=5, max_length=500)


# ============================================================
# RESPONSE SCHEMAS
# ============================================================

class ReturnItemResponse(BaseModel):
    product_id: str
    sku: str
    quantity: int
    unit_price: Decimal
    reason: ReturnReason
    line_amount: Decimal
    condition: ItemCondition | None
    disposition: Disposition | None


class ReturnEventResponse(BaseModel):
    event_id: str
    event_type: ReturnEventType
    actor_id: str
    details: str | None
    created_at: datetime


class ReturnResponse(BaseModel):
    return_id: str
    rma_number: str

    warehouse_id: str
    order_id: str
    customer_id: str

    status: ReturnStatus
    currency: str

    total_return_value: Decimal
    approved_amount: Decimal

    resolution: ReturnResolution | None

    item_count: int
    total_units: int

    version: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class ReturnDetailResponse(ReturnResponse):
    items: list[ReturnItemResponse]
    description: str
    carrier_id: str | None
    tracking_reference: str | None
    inspection_reference: str | None
    resolution_reference: str | None
    fulfillment_reference: str | None
    events: list[ReturnEventResponse]


class ReturnAnalyticsResponse(BaseModel):
    total_returns: int
    requested: int
    approved: int
    rejected: int
    in_transit: int
    received: int
    completed: int
    cancelled: int

    total_return_value: Decimal
    total_approved_amount: Decimal

    total_returned_units: int

    refunds: int
    replacements: int
    store_credits: int


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass
class ReturnItemRecord:
    product_id: str
    sku: str
    quantity: int
    unit_price: Decimal
    reason: ReturnReason

    condition: ItemCondition | None = None
    disposition: Disposition | None = None

    @property
    def line_amount(self) -> Decimal:
        return self.unit_price * self.quantity


@dataclass
class ReturnRecord:
    return_id: str
    rma_number: str
    tenant_id: str

    warehouse_id: str
    order_id: str
    customer_id: str

    currency: str
    items: dict[str, ReturnItemRecord]

    description: str
    created_by: str

    status: ReturnStatus = ReturnStatus.REQUESTED

    resolution: ReturnResolution | None = None
    approved_amount: Decimal = Decimal("0")

    carrier_id: str | None = None
    tracking_reference: str | None = None

    inspection_reference: str | None = None
    resolution_reference: str | None = None
    fulfillment_reference: str | None = None

    events: list[ReturnEventResponse] = field(
        default_factory=list
    )

    version: int = 1

    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    completed_at: datetime | None = None


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint(payload: ReturnCreate) -> str:
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


def require_returns_access(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool,
) -> None:

    # Replace with RETURNS_READ/RETURNS_WRITE
    # and dedicated approval permissions in production.
    permission = (
        Permission.INVENTORY_WRITE
        if write
        else Permission.INVENTORY_READ
    )

    if (
        principal.allowed_warehouse_ids is not None
        and warehouse_id not in principal.allowed_warehouse_ids
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
            detail="Returns access denied",
        )


def to_response(record: ReturnRecord) -> ReturnResponse:
    items = list(record.items.values())

    return ReturnResponse(
        return_id=record.return_id,
        rma_number=record.rma_number,
        warehouse_id=record.warehouse_id,
        order_id=record.order_id,
        customer_id=record.customer_id,
        status=record.status,
        currency=record.currency,
        total_return_value=sum(
            (item.line_amount for item in items),
            Decimal("0"),
        ),
        approved_amount=record.approved_amount,
        resolution=record.resolution,
        item_count=len(items),
        total_units=sum(item.quantity for item in items),
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
    )


def to_detail(record: ReturnRecord) -> ReturnDetailResponse:
    return ReturnDetailResponse(
        **to_response(record).model_dump(),
        items=[
            ReturnItemResponse(
                product_id=item.product_id,
                sku=item.sku,
                quantity=item.quantity,
                unit_price=item.unit_price,
                reason=item.reason,
                line_amount=item.line_amount,
                condition=item.condition,
                disposition=item.disposition,
            )
            for item in record.items.values()
        ],
        description=record.description,
        carrier_id=record.carrier_id,
        tracking_reference=record.tracking_reference,
        inspection_reference=record.inspection_reference,
        resolution_reference=record.resolution_reference,
        fulfillment_reference=record.fulfillment_reference,
        events=list(record.events),
    )


# ============================================================
# RETURN STORE
# ============================================================

class ReturnStore:

    def __init__(self):
        self._returns: dict[str, ReturnRecord] = {}
        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}
        self._lock = asyncio.Lock()

    def _get(
        self,
        principal: Principal,
        return_id: str,
        *,
        write: bool,
    ) -> ReturnRecord:

        record = self._returns.get(return_id)

        if (
            record is None
            or record.tenant_id != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Return not found",
            )

        require_returns_access(
            principal,
            record.warehouse_id,
            write=write,
        )
        return record

    @staticmethod
    def _check_version(
        record: ReturnRecord,
        expected_version: int,
    ) -> None:
        if record.version != expected_version:
            raise HTTPException(
                status_code=409,
                detail="Return version conflict",
            )

    @staticmethod
    def _require_status(
        record: ReturnRecord,
        allowed: set[ReturnStatus],
    ) -> None:
        if record.status not in allowed:
            raise HTTPException(
                status_code=409,
                detail=f"Invalid state: {record.status.value}",
            )

    @staticmethod
    def _event(
        record: ReturnRecord,
        event_type: ReturnEventType,
        actor_id: str,
        details: str | None = None,
    ) -> None:

        if len(record.events) >= MAX_EVENTS_PER_RETURN:
            raise HTTPException(
                status_code=503,
                detail="Return event capacity reached",
            )

        record.events.append(
            ReturnEventResponse(
                event_id=secrets.token_urlsafe(16),
                event_type=event_type,
                actor_id=actor_id,
                details=details,
                created_at=utc_now(),
            )
        )

    @staticmethod
    def _touch(record: ReturnRecord) -> None:
        record.version += 1
        record.updated_at = utc_now()

    async def create(
        self,
        principal: Principal,
        payload: ReturnCreate,
    ) -> ReturnResponse:

        require_returns_access(
            principal,
            payload.warehouse_id,
            write=True,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )
        request_hash = fingerprint(payload)

        async with self._lock:

            previous = self._idempotency.get(key)

            if previous:
                old_hash, return_id = previous

                if old_hash != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return to_response(
                    self._get(principal, return_id, write=False)
                )

            tenant_count = sum(
                item.tenant_id == principal.tenant_id
                for item in self._returns.values()
            )

            if (
                tenant_count >= MAX_RETURNS_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Return capacity reached",
                )

            return_id = secrets.token_urlsafe(20)

            record = ReturnRecord(
                return_id=return_id,
                rma_number="RMA-" + secrets.token_hex(8).upper(),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                order_id=payload.order_id,
                customer_id=payload.customer_id,
                currency=payload.currency,
                items={
                    item.product_id: ReturnItemRecord(
                        product_id=item.product_id,
                        sku=item.sku,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        reason=item.reason,
                    )
                    for item in payload.items
                },
                description=payload.description,
                created_by=principal.principal_id,
            )

            self._event(
                record,
                ReturnEventType.CREATED,
                principal.principal_id,
            )

            self._returns[return_id] = record
            self._idempotency[key] = (request_hash, return_id)

            return to_response(record)

    async def get(
        self,
        principal: Principal,
        return_id: str,
    ) -> ReturnDetailResponse:

        async with self._lock:
            return to_detail(
                self._get(principal, return_id, write=False)
            )

    async def list_returns(
        self,
        principal: Principal,
        warehouse_id: str | None,
        status: ReturnStatus | None,
        limit: int,
    ) -> list[ReturnResponse]:

        async with self._lock:
            records = sorted(
                (
                    record
                    for record in self._returns.values()
                    if record.tenant_id == principal.tenant_id
                    and (
                        warehouse_id is None
                        or record.warehouse_id == warehouse_id
                    )
                    and (
                        status is None
                        or record.status == status
                    )
                ),
                key=lambda record: record.created_at,
                reverse=True,
            )

            result = []

            for record in records:
                try:
                    require_returns_access(
                        principal,
                        record.warehouse_id,
                        write=False,
                    )
                except HTTPException:
                    continue

                result.append(to_response(record))
                if len(result) >= limit:
                    break

            return result

    async def decide(
        self,
        principal: Principal,
        return_id: str,
        payload: ReturnDecisionRequest,
        approve: bool,
    ) -> ReturnResponse:

        async with self._lock:
            record = self._get(principal, return_id, write=True)

            self._check_version(record, payload.expected_version)
            self._require_status(
                record,
                {ReturnStatus.REQUESTED},
            )

            if record.created_by == principal.principal_id:
                raise HTTPException(
                    status_code=403,
                    detail="Requester cannot approve own return",
                )

            self._event(
                record,
                (
                    ReturnEventType.APPROVED
                    if approve
                    else ReturnEventType.REJECTED
                ),
                principal.principal_id,
                payload.notes,
            )

            record.status = (
                ReturnStatus.APPROVED
                if approve
                else ReturnStatus.REJECTED
            )
            self._touch(record)
            return to_response(record)

    async def schedule_pickup(
        self,
        principal: Principal,
        return_id: str,
        expected_version: int,
    ) -> ReturnResponse:

        async with self._lock:
            record = self._get(principal, return_id, write=True)
            self._check_version(record, expected_version)
            self._require_status(
                record,
                {ReturnStatus.APPROVED},
            )

            self._event(
                record,
                ReturnEventType.PICKUP_SCHEDULED,
                principal.principal_id,
            )

            record.status = ReturnStatus.AWAITING_PICKUP
            self._touch(record)
            return to_response(record)

    async def ship(
        self,
        principal: Principal,
        return_id: str,
        payload: ReturnShipmentRequest,
    ) -> ReturnResponse:

        async with self._lock:
            record = self._get(principal, return_id, write=True)
            self._check_version(record, payload.expected_version)
            self._require_status(
                record,
                {ReturnStatus.AWAITING_PICKUP},
            )

            self._event(
                record,
                ReturnEventType.SHIPPED,
                principal.principal_id,
                payload.tracking_reference,
            )

            record.carrier_id = payload.carrier_id
            record.tracking_reference = payload.tracking_reference
            record.status = ReturnStatus.IN_TRANSIT
            self._touch(record)
            return to_response(record)

    async def receive(
        self,
        principal: Principal,
        return_id: str,
        expected_version: int,
    ) -> ReturnResponse:

        async with self._lock:
            record = self._get(principal, return_id, write=True)
            self._check_version(record, expected_version)
            self._require_status(
                record,
                {
                    ReturnStatus.APPROVED,
                    ReturnStatus.AWAITING_PICKUP,
                    ReturnStatus.IN_TRANSIT,
                },
            )

            self._event(
                record,
                ReturnEventType.RECEIVED,
                principal.principal_id,
            )

            record.status = ReturnStatus.INSPECTION_PENDING
            self._touch(record)
            return to_response(record)

    async def inspect(
        self,
        principal: Principal,
        return_id: str,
        payload: ReturnInspectionRequest,
    ) -> ReturnDetailResponse:

        async with self._lock:
            record = self._get(principal, return_id, write=True)
            self._check_version(record, payload.expected_version)
            self._require_status(
                record,
                {ReturnStatus.INSPECTION_PENDING},
            )

            expected = set(record.items)
            provided = {
                item.product_id
                for item in payload.items
            }

            if expected != provided:
                raise HTTPException(
                    status_code=422,
                    detail="All returned products must be inspected",
                )

            self._event(
                record,
                ReturnEventType.INSPECTED,
                principal.principal_id,
                payload.inspection_reference,
            )

            for item in payload.items:
                existing = record.items[item.product_id]
                existing.condition = item.condition
                existing.disposition = item.disposition

            record.inspection_reference = (
                payload.inspection_reference
            )
            record.status = ReturnStatus.RESOLUTION_PENDING

            self._touch(record)
            return to_detail(record)

    async def resolve(
        self,
        principal: Principal,
        return_id: str,
        payload: ReturnResolutionRequest,
    ) -> ReturnDetailResponse:

        async with self._lock:
            record = self._get(principal, return_id, write=True)
            self._check_version(record, payload.expected_version)
            self._require_status(
                record,
                {ReturnStatus.RESOLUTION_PENDING},
            )

            maximum_amount = sum(
                (item.line_amount for item in record.items.values()),
                Decimal("0"),
            )

            if payload.approved_amount > maximum_amount:
                raise HTTPException(
                    status_code=422,
                    detail="Approved amount exceeds return value",
                )

            if (
                payload.resolution
                in {
                    ReturnResolution.REPLACEMENT,
                    ReturnResolution.NO_COMPENSATION,
                }
                and payload.approved_amount != 0
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Resolution requires zero monetary amount",
                )

            self._event(
                record,
                ReturnEventType.RESOLUTION_SELECTED,
                principal.principal_id,
                payload.notes,
            )

            record.resolution = payload.resolution
            record.approved_amount = payload.approved_amount
            record.resolution_reference = (
                payload.resolution_reference
            )

            self._touch(record)
            return to_detail(record)

    async def complete(
        self,
        principal: Principal,
        return_id: str,
        payload: ReturnCompletionRequest,
    ) -> ReturnResponse:

        async with self._lock:
            record = self._get(principal, return_id, write=True)
            self._check_version(record, payload.expected_version)
            self._require_status(
                record,
                {ReturnStatus.RESOLUTION_PENDING},
            )

            if record.resolution is None:
                raise HTTPException(
                    status_code=409,
                    detail="Return resolution not selected",
                )

            # This is only a recorded reference.
            # Verify real refund/replacement completion
            # against authoritative external services.

            self._event(
                record,
                ReturnEventType.COMPLETED,
                principal.principal_id,
                payload.fulfillment_reference,
            )

            record.fulfillment_reference = (
                payload.fulfillment_reference
            )
            record.status = ReturnStatus.COMPLETED
            record.completed_at = utc_now()

            self._touch(record)
            return to_response(record)

    async def cancel(
        self,
        principal: Principal,
        return_id: str,
        payload: ReturnCancelRequest,
    ) -> ReturnResponse:

        async with self._lock:
            record = self._get(principal, return_id, write=True)
            self._check_version(record, payload.expected_version)
            self._require_status(
                record,
                {
                    ReturnStatus.REQUESTED,
                    ReturnStatus.APPROVED,
                    ReturnStatus.AWAITING_PICKUP,
                },
            )

            self._event(
                record,
                ReturnEventType.CANCELLED,
                principal.principal_id,
                payload.reason,
            )

            record.status = ReturnStatus.CANCELLED
            self._touch(record)
            return to_response(record)

    async def analytics(
        self,
        principal: Principal,
        warehouse_id: str,
    ) -> ReturnAnalyticsResponse:

        require_returns_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:
            records = [
                record
                for record in self._returns.values()
                if record.tenant_id == principal.tenant_id
                and record.warehouse_id == warehouse_id
            ]

            statuses = [record.status for record in records]
            resolutions = [
                record.resolution for record in records
            ]

            return ReturnAnalyticsResponse(
                total_returns=len(records),
                requested=statuses.count(ReturnStatus.REQUESTED),
                approved=statuses.count(ReturnStatus.APPROVED),
                rejected=statuses.count(ReturnStatus.REJECTED),
                in_transit=statuses.count(ReturnStatus.IN_TRANSIT),
                received=sum(
                    status in {
                        ReturnStatus.RECEIVED,
                        ReturnStatus.INSPECTION_PENDING,
                        ReturnStatus.INSPECTED,
                        ReturnStatus.RESOLUTION_PENDING,
                    }
                    for status in statuses
                ),
                completed=statuses.count(ReturnStatus.COMPLETED),
                cancelled=statuses.count(ReturnStatus.CANCELLED),
                total_return_value=sum(
                    (
                        item.line_amount
                        for record in records
                        for item in record.items.values()
                    ),
                    Decimal("0"),
                ),
                total_approved_amount=sum(
                    (record.approved_amount for record in records),
                    Decimal("0"),
                ),
                total_returned_units=sum(
                    item.quantity
                    for record in records
                    for item in record.items.values()
                ),
                refunds=resolutions.count(ReturnResolution.REFUND),
                replacements=resolutions.count(
                    ReturnResolution.REPLACEMENT
                ),
                store_credits=resolutions.count(
                    ReturnResolution.STORE_CREDIT
                ),
            )


return_store = ReturnStore()


# ============================================================
# SERVICE
# ============================================================

class ReturnService:

    def __init__(self, store: ReturnStore):
        self.store = store

    async def create(
        self,
        principal: Principal,
        payload: ReturnCreate,
    ) -> ReturnResponse:
        return await self.store.create(principal, payload)


return_service = ReturnService(return_store)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Returns & Reverse Logistics"],
)


@router.post(
    "",
    response_model=ReturnResponse,
    status_code=201,
)
async def create_return(
    payload: ReturnCreate,
    principal: CurrentPrincipal,
):
    return await return_service.create(principal, payload)


@router.get(
    "",
    response_model=list[ReturnResponse],
)
async def list_returns(
    principal: CurrentPrincipal,
    warehouse_id: str | None = None,
    status: ReturnStatus | None = None,
    limit: int = Query(default=50, ge=1, le=MAX_LIST_LIMIT),
):
    return await return_store.list_returns(
        principal,
        warehouse_id,
        status,
        limit,
    )


@router.get(
    "/analytics/{warehouse_id}",
    response_model=ReturnAnalyticsResponse,
)
async def return_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
):
    return await return_store.analytics(
        principal,
        warehouse_id,
    )


@router.get(
    "/{return_id}",
    response_model=ReturnDetailResponse,
)
async def get_return(
    return_id: str,
    principal: CurrentPrincipal,
):
    return await return_store.get(principal, return_id)


@router.post(
    "/{return_id}/approve",
    response_model=ReturnResponse,
)
async def approve_return(
    return_id: str,
    payload: ReturnDecisionRequest,
    principal: CurrentPrincipal,
):
    return await return_store.decide(
        principal, return_id, payload, True
    )


@router.post(
    "/{return_id}/reject",
    response_model=ReturnResponse,
)
async def reject_return(
    return_id: str,
    payload: ReturnDecisionRequest,
    principal: CurrentPrincipal,
):
    return await return_store.decide(
        principal, return_id, payload, False
    )


@router.post(
    "/{return_id}/pickup",
    response_model=ReturnResponse,
)
async def schedule_return_pickup(
    return_id: str,
    payload: ReturnVersionRequest,
    principal: CurrentPrincipal,
):
    return await return_store.schedule_pickup(
        principal, return_id, payload.expected_version
    )


@router.post(
    "/{return_id}/ship",
    response_model=ReturnResponse,
)
async def ship_return(
    return_id: str,
    payload: ReturnShipmentRequest,
    principal: CurrentPrincipal,
):
    return await return_store.ship(
        principal, return_id, payload
    )


@router.post(
    "/{return_id}/receive",
    response_model=ReturnResponse,
)
async def receive_return(
    return_id: str,
    payload: ReturnVersionRequest,
    principal: CurrentPrincipal,
):
    return await return_store.receive(
        principal, return_id, payload.expected_version
    )


@router.post(
    "/{return_id}/inspect",
    response_model=ReturnDetailResponse,
)
async def inspect_return(
    return_id: str,
    payload: ReturnInspectionRequest,
    principal: CurrentPrincipal,
):
    return await return_store.inspect(
        principal, return_id, payload
    )


@router.post(
    "/{return_id}/resolve",
    response_model=ReturnDetailResponse,
)
async def resolve_return(
    return_id: str,
    payload: ReturnResolutionRequest,
    principal: CurrentPrincipal,
):
    return await return_store.resolve(
        principal, return_id, payload
    )


@router.post(
    "/{return_id}/complete",
    response_model=ReturnResponse,
)
async def complete_return(
    return_id: str,
    payload: ReturnCompletionRequest,
    principal: CurrentPrincipal,
):
    return await return_store.complete(
        principal, return_id, payload
    )


@router.post(
    "/{return_id}/cancel",
    response_model=ReturnResponse,
)
async def cancel_return(
    return_id: str,
    payload: ReturnCancelRequest,
    principal: CurrentPrincipal,
):
    return await return_store.cancel(
        principal, return_id, payload
    )


__all__ = [
    "ReturnStatus",
    "ReturnReason",
    "ReturnResolution",
    "ItemCondition",
    "Disposition",
    "ReturnCreate",
    "ReturnItemCreate",
    "ReturnVersionRequest",
    "ReturnDecisionRequest",
    "ReturnShipmentRequest",
    "ReturnInspectionRequest",
    "ReturnResolutionRequest",
    "ReturnCompletionRequest",
    "ReturnCancelRequest",
    "ReturnResponse",
    "ReturnDetailResponse",
    "ReturnAnalyticsResponse",
    "ReturnStore",
    "ReturnService",
    "return_store",
    "return_service",
    "router",
]
