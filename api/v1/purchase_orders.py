from __future__ import annotations

"""Planned module: purchase orders. Implementation pending."""

"""
backend/purchase_orders.py

Autonomous Retail Supply Chain AI 5.0
Purchase Order Management API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Purchase order creation
    - Supplier and warehouse references
    - Multi-item purchase orders
    - Decimal-based cost calculations
    - Draft submission
    - Human approval and rejection
    - Purchase order issuance
    - Partial and full goods receipt
    - Order cancellation
    - Idempotent order creation
    - Optimistic concurrency
    - Tenant and warehouse authorization
    - Purchase order analytics

Prototype limitations:
    - In-memory storage only
    - No actual inventory stock updates
    - No supplier API or email dispatch
    - No durable approvals or audit trail
    - No tax or foreign exchange calculation
    - No payment or invoice settlement
"""


import asyncio
import hashlib
import json
import secrets

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
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


API_PREFIX = "/api/v1/purchase-orders"

MAX_ORDERS_PER_TENANT = 50000
MAX_ITEMS_PER_ORDER = 200
MAX_RECEIPTS_PER_ORDER = 500
MAX_EVENTS_PER_ORDER = 1000
MAX_IDEMPOTENCY_KEYS = 100000
MAX_LIST_LIMIT = 200

MONEY_QUANTUM = Decimal("0.01")


# ============================================================
# ENUMS
# ============================================================

class PurchaseOrderStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    ISSUED = "issued"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class PurchaseOrderPriority(str, Enum):
    STANDARD = "standard"
    HIGH = "high"
    CRITICAL = "critical"


class PurchaseOrderEventType(str, Enum):
    CREATED = "created"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    ISSUED = "issued"
    GOODS_RECEIVED = "goods_received"
    PARTIALLY_RECEIVED = "partially_received"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# ============================================================
# REQUEST MODELS
# ============================================================

class PurchaseOrderItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    sku: str = Field(
        min_length=1,
        max_length=100,
    )

    quantity: int = Field(
        gt=0,
        le=10000000,
    )

    unit_cost: Decimal = Field(
        ge=0,
        max_digits=16,
        decimal_places=2,
    )


class PurchaseOrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    supplier_id: str = Field(
        min_length=1,
        max_length=128,
    )

    currency: str = Field(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    )

    priority: PurchaseOrderPriority = (
        PurchaseOrderPriority.STANDARD
    )

    expected_delivery_date: datetime | None = None

    items: list[
        PurchaseOrderItemCreate
    ] = Field(
        min_length=1,
        max_length=MAX_ITEMS_PER_ORDER,
    )

    notes: str = Field(
        default="",
        max_length=2000,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_order(self):

        product_ids = [
            item.product_id
            for item in self.items
        ]

        if len(set(product_ids)) != len(product_ids):
            raise ValueError(
                "Duplicate product IDs are not allowed"
            )

        if self.expected_delivery_date is not None:

            if self.expected_delivery_date.tzinfo is None:
                raise ValueError(
                    "Delivery date must include timezone"
                )

            if (
                self.expected_delivery_date
                <= datetime.now(timezone.utc)
            ):
                raise ValueError(
                    "Delivery date must be in the future"
                )

        return self


class PurchaseOrderVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class PurchaseOrderDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    notes: str = Field(
        min_length=3,
        max_length=1000,
    )


class PurchaseOrderIssueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    supplier_reference: str = Field(
        min_length=1,
        max_length=200,
    )


class GoodsReceiptItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    received_quantity: int = Field(
        gt=0,
        le=10000000,
    )


class GoodsReceiptCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    receipt_reference: str = Field(
        min_length=1,
        max_length=200,
    )

    items: list[GoodsReceiptItem] = Field(
        min_length=1,
        max_length=MAX_ITEMS_PER_ORDER,
    )

    notes: str = Field(
        default="",
        max_length=1000,
    )

    @model_validator(mode="after")
    def validate_items(self):

        ids = [
            item.product_id
            for item in self.items
        ]

        if len(set(ids)) != len(ids):
            raise ValueError(
                "Duplicate receipt product IDs"
            )

        return self


class PurchaseOrderCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    reason: str = Field(
        min_length=5,
        max_length=500,
    )


# ============================================================
# RESPONSE MODELS
# ============================================================

class PurchaseOrderItemResponse(BaseModel):
    product_id: str
    sku: str

    ordered_quantity: int
    received_quantity: int
    remaining_quantity: int

    unit_cost: Decimal
    line_total: Decimal


class GoodsReceiptResponse(BaseModel):
    receipt_id: str
    receipt_reference: str

    items: list[GoodsReceiptItem]

    recorded_by: str
    created_at: datetime


class PurchaseOrderEventResponse(BaseModel):
    event_id: str

    event_type: PurchaseOrderEventType

    actor_id: str
    details: str | None

    created_at: datetime


class PurchaseOrderResponse(BaseModel):
    purchase_order_id: str

    warehouse_id: str
    supplier_id: str

    currency: str
    priority: PurchaseOrderPriority
    status: PurchaseOrderStatus

    total_amount: Decimal

    total_ordered_quantity: int
    total_received_quantity: int

    item_count: int

    expected_delivery_date: datetime | None
    supplier_reference: str | None

    version: int

    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class PurchaseOrderDetailResponse(
    PurchaseOrderResponse
):
    items: list[PurchaseOrderItemResponse]
    receipts: list[GoodsReceiptResponse]
    events: list[PurchaseOrderEventResponse]

    notes: str
    approval_notes: str | None


class PurchaseOrderAnalyticsResponse(BaseModel):
    total_orders: int

    draft: int
    pending_approval: int
    approved: int
    rejected: int
    issued: int
    partially_received: int
    received: int
    cancelled: int

    total_order_value: Decimal

    total_ordered_units: int
    total_received_units: int
    total_pending_units: int

    average_order_value: Decimal | None


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass
class PurchaseOrderItemRecord:
    product_id: str
    sku: str

    ordered_quantity: int
    unit_cost: Decimal

    received_quantity: int = 0

    @property
    def remaining_quantity(self) -> int:

        return (
            self.ordered_quantity
            - self.received_quantity
        )

    @property
    def line_total(self) -> Decimal:

        return money(
            Decimal(self.ordered_quantity)
            * self.unit_cost
        )


@dataclass
class PurchaseOrderRecord:
    purchase_order_id: str
    tenant_id: str

    warehouse_id: str
    supplier_id: str

    currency: str
    priority: PurchaseOrderPriority

    items: dict[
        str,
        PurchaseOrderItemRecord,
    ]

    created_by: str

    expected_delivery_date: datetime | None
    notes: str

    status: PurchaseOrderStatus = (
        PurchaseOrderStatus.DRAFT
    )

    supplier_reference: str | None = None
    approval_notes: str | None = None

    receipts: list[
        GoodsReceiptResponse
    ] = field(default_factory=list)

    events: list[
        PurchaseOrderEventResponse
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


def money(
    value: Decimal,
) -> Decimal:

    return value.quantize(
        MONEY_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def request_fingerprint(
    payload: PurchaseOrderCreate,
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


def require_purchase_order_access(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool,
) -> None:

    # Existing permissions are used temporarily.
    #
    # Production should define:
    # PURCHASE_ORDER_READ
    # PURCHASE_ORDER_WRITE
    # PURCHASE_ORDER_APPROVE
    # PURCHASE_ORDER_RECEIVE

    permission = (
        Permission.INVENTORY_WRITE
        if write
        else Permission.PROCUREMENT_READ
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
            detail="Purchase order access denied",
        )


def to_item(
    record: PurchaseOrderItemRecord,
) -> PurchaseOrderItemResponse:

    return PurchaseOrderItemResponse(
        product_id=record.product_id,
        sku=record.sku,
        ordered_quantity=record.ordered_quantity,
        received_quantity=record.received_quantity,
        remaining_quantity=record.remaining_quantity,
        unit_cost=record.unit_cost,
        line_total=record.line_total,
    )


def to_response(
    record: PurchaseOrderRecord,
) -> PurchaseOrderResponse:

    items = list(
        record.items.values()
    )

    return PurchaseOrderResponse(
        purchase_order_id=record.purchase_order_id,
        warehouse_id=record.warehouse_id,
        supplier_id=record.supplier_id,
        currency=record.currency,
        priority=record.priority,
        status=record.status,
        total_amount=money(
            sum(
                (
                    item.line_total
                    for item in items
                ),
                Decimal("0"),
            )
        ),
        total_ordered_quantity=sum(
            item.ordered_quantity
            for item in items
        ),
        total_received_quantity=sum(
            item.received_quantity
            for item in items
        ),
        item_count=len(items),
        expected_delivery_date=(
            record.expected_delivery_date
        ),
        supplier_reference=record.supplier_reference,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
    )


def to_detail(
    record: PurchaseOrderRecord,
) -> PurchaseOrderDetailResponse:

    return PurchaseOrderDetailResponse(
        **to_response(record).model_dump(),
        items=[
            to_item(item)
            for item in record.items.values()
        ],
        receipts=list(record.receipts),
        events=list(record.events),
        notes=record.notes,
        approval_notes=record.approval_notes,
    )


# ============================================================
# PURCHASE ORDER STORE
# ============================================================

class PurchaseOrderStore:

    def __init__(self):

        self._orders: dict[
            str,
            PurchaseOrderRecord,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    def _get(
        self,
        principal: Principal,
        purchase_order_id: str,
        *,
        write: bool,
    ) -> PurchaseOrderRecord:

        record = self._orders.get(
            purchase_order_id
        )

        if (
            record is None
            or record.tenant_id
            != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Purchase order not found",
            )

        require_purchase_order_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    @staticmethod
    def _check_version(
        record: PurchaseOrderRecord,
        expected_version: int,
    ) -> None:

        if record.version != expected_version:
            raise HTTPException(
                status_code=409,
                detail="Purchase order version conflict",
            )

    @staticmethod
    def _require_status(
        record: PurchaseOrderRecord,
        allowed: set[PurchaseOrderStatus],
    ) -> None:

        if record.status not in allowed:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Operation not allowed "
                    f"in status {record.status.value}"
                ),
            )

    @staticmethod
    def _add_event(
        record: PurchaseOrderRecord,
        event_type: PurchaseOrderEventType,
        actor_id: str,
        details: str | None = None,
    ) -> None:

        if (
            len(record.events)
            >= MAX_EVENTS_PER_ORDER
        ):
            raise HTTPException(
                status_code=503,
                detail="Purchase order event capacity reached",
            )

        record.events.append(
            PurchaseOrderEventResponse(
                event_id=secrets.token_urlsafe(16),
                event_type=event_type,
                actor_id=actor_id,
                details=details,
                created_at=utc_now(),
            )
        )

    @staticmethod
    def _touch(
        record: PurchaseOrderRecord,
    ) -> None:

        record.version += 1
        record.updated_at = utc_now()

    async def create(
        self,
        *,
        principal: Principal,
        payload: PurchaseOrderCreate,
    ) -> PurchaseOrderResponse:

        require_purchase_order_access(
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

                old_hash, purchase_order_id = previous

                if old_hash != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return to_response(
                    self._get(
                        principal,
                        purchase_order_id,
                        write=False,
                    )
                )

            tenant_count = sum(
                record.tenant_id
                == principal.tenant_id
                for record in self._orders.values()
            )

            if (
                tenant_count
                >= MAX_ORDERS_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Purchase order capacity reached",
                )

            record = PurchaseOrderRecord(
                purchase_order_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                supplier_id=payload.supplier_id,
                currency=payload.currency,
                priority=payload.priority,
                items={
                    item.product_id: PurchaseOrderItemRecord(
                        product_id=item.product_id,
                        sku=item.sku,
                        ordered_quantity=item.quantity,
                        unit_cost=item.unit_cost,
                    )
                    for item in payload.items
                },
                created_by=principal.principal_id,
                expected_delivery_date=(
                    payload.expected_delivery_date
                ),
                notes=payload.notes,
            )

            self._add_event(
                record,
                PurchaseOrderEventType.CREATED,
                principal.principal_id,
            )

            self._orders[
                record.purchase_order_id
            ] = record

            self._idempotency[key] = (
                request_hash,
                record.purchase_order_id,
            )

            return to_response(record)

    async def get(
        self,
        *,
        principal: Principal,
        purchase_order_id: str,
    ) -> PurchaseOrderDetailResponse:

        async with self._lock:

            return to_detail(
                self._get(
                    principal,
                    purchase_order_id,
                    write=False,
                )
            )

    async def list_orders(
        self,
        *,
        principal: Principal,
        warehouse_id: str | None,
        status: PurchaseOrderStatus | None,
        limit: int,
    ) -> list[PurchaseOrderResponse]:

        if warehouse_id is not None:
            require_purchase_order_access(
                principal,
                warehouse_id,
                write=False,
            )

        async with self._lock:

            records = [
                record
                for record in self._orders.values()
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
                    require_purchase_order_access(
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

    async def submit(
        self,
        *,
        principal: Principal,
        purchase_order_id: str,
        expected_version: int,
    ) -> PurchaseOrderResponse:

        async with self._lock:

            record = self._get(
                principal,
                purchase_order_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            self._require_status(
                record,
                {PurchaseOrderStatus.DRAFT},
            )

            record.status = (
                PurchaseOrderStatus.PENDING_APPROVAL
            )

            self._add_event(
                record,
                PurchaseOrderEventType.SUBMITTED,
                principal.principal_id,
            )

            self._touch(record)

            return to_response(record)

    async def decide(
        self,
        *,
        principal: Principal,
        purchase_order_id: str,
        payload: PurchaseOrderDecision,
        approve: bool,
    ) -> PurchaseOrderResponse:

        async with self._lock:

            record = self._get(
                principal,
                purchase_order_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {PurchaseOrderStatus.PENDING_APPROVAL},
            )

            if (
                record.created_by
                == principal.principal_id
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Creator cannot approve own purchase order",
                )

            # Production must enforce a dedicated
            # PURCHASE_ORDER_APPROVE permission.

            record.status = (
                PurchaseOrderStatus.APPROVED
                if approve
                else PurchaseOrderStatus.REJECTED
            )

            record.approval_notes = payload.notes

            self._add_event(
                record,
                (
                    PurchaseOrderEventType.APPROVED
                    if approve
                    else PurchaseOrderEventType.REJECTED
                ),
                principal.principal_id,
                payload.notes,
            )

            self._touch(record)

            return to_response(record)

    async def issue(
        self,
        *,
        principal: Principal,
        purchase_order_id: str,
        payload: PurchaseOrderIssueRequest,
    ) -> PurchaseOrderResponse:

        async with self._lock:

            record = self._get(
                principal,
                purchase_order_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {PurchaseOrderStatus.APPROVED},
            )

            record.supplier_reference = (
                payload.supplier_reference
            )

            record.status = (
                PurchaseOrderStatus.ISSUED
            )

            self._add_event(
                record,
                PurchaseOrderEventType.ISSUED,
                principal.principal_id,
                payload.supplier_reference,
            )

            self._touch(record)

            return to_response(record)

    async def receive(
        self,
        *,
        principal: Principal,
        purchase_order_id: str,
        payload: GoodsReceiptCreate,
    ) -> PurchaseOrderDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                purchase_order_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {
                    PurchaseOrderStatus.ISSUED,
                    PurchaseOrderStatus.PARTIALLY_RECEIVED,
                },
            )

            if (
                len(record.receipts)
                >= MAX_RECEIPTS_PER_ORDER
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Goods receipt capacity reached",
                )

            if any(
                receipt.receipt_reference
                == payload.receipt_reference
                for receipt in record.receipts
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Receipt reference already exists",
                )

            # Validate all lines before mutation.
            for receipt_item in payload.items:

                item = record.items.get(
                    receipt_item.product_id
                )

                if item is None:
                    raise HTTPException(
                        status_code=404,
                        detail=(
                            "Receipt product not found "
                            "in purchase order"
                        ),
                    )

                if (
                    receipt_item.received_quantity
                    > item.remaining_quantity
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Receipt exceeds outstanding quantity",
                    )

            self._add_event(
                record,
                PurchaseOrderEventType.GOODS_RECEIVED,
                principal.principal_id,
                payload.receipt_reference,
            )

            for receipt_item in payload.items:

                record.items[
                    receipt_item.product_id
                ].received_quantity += (
                    receipt_item.received_quantity
                )

            receipt = GoodsReceiptResponse(
                receipt_id=secrets.token_urlsafe(20),
                receipt_reference=payload.receipt_reference,
                items=list(payload.items),
                recorded_by=principal.principal_id,
                created_at=utc_now(),
            )

            record.receipts.append(
                receipt
            )

            all_received = all(
                item.remaining_quantity == 0
                for item in record.items.values()
            )

            if all_received:

                record.status = (
                    PurchaseOrderStatus.RECEIVED
                )

                record.completed_at = utc_now()

                self._add_event(
                    record,
                    PurchaseOrderEventType.COMPLETED,
                    principal.principal_id,
                )

            else:

                record.status = (
                    PurchaseOrderStatus.PARTIALLY_RECEIVED
                )

            self._touch(record)

            return to_detail(record)

    async def cancel(
        self,
        *,
        principal: Principal,
        purchase_order_id: str,
        payload: PurchaseOrderCancelRequest,
    ) -> PurchaseOrderResponse:

        async with self._lock:

            record = self._get(
                principal,
                purchase_order_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status in {
                PurchaseOrderStatus.RECEIVED,
                PurchaseOrderStatus.CANCELLED,
            }:
                raise HTTPException(
                    status_code=409,
                    detail="Purchase order cannot be cancelled",
                )

            if any(
                item.received_quantity > 0
                for item in record.items.values()
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Orders with receipts require a closure workflow",
                )

            self._add_event(
                record,
                PurchaseOrderEventType.CANCELLED,
                principal.principal_id,
                payload.reason,
            )

            record.status = (
                PurchaseOrderStatus.CANCELLED
            )

            self._touch(record)

            return to_response(record)

    async def analytics(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
    ) -> PurchaseOrderAnalyticsResponse:

        require_purchase_order_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._orders.values()
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

            total_value = sum(
                (
                    to_response(record).total_amount
                    for record in records
                ),
                Decimal("0"),
            )

            items = [
                item
                for record in records
                for item in record.items.values()
            ]

            return PurchaseOrderAnalyticsResponse(
                total_orders=len(records),
                draft=statuses.count(
                    PurchaseOrderStatus.DRAFT
                ),
                pending_approval=statuses.count(
                    PurchaseOrderStatus.PENDING_APPROVAL
                ),
                approved=statuses.count(
                    PurchaseOrderStatus.APPROVED
                ),
                rejected=statuses.count(
                    PurchaseOrderStatus.REJECTED
                ),
                issued=statuses.count(
                    PurchaseOrderStatus.ISSUED
                ),
                partially_received=statuses.count(
                    PurchaseOrderStatus.PARTIALLY_RECEIVED
                ),
                received=statuses.count(
                    PurchaseOrderStatus.RECEIVED
                ),
                cancelled=statuses.count(
                    PurchaseOrderStatus.CANCELLED
                ),
                total_order_value=money(total_value),
                total_ordered_units=sum(
                    item.ordered_quantity
                    for item in items
                ),
                total_received_units=sum(
                    item.received_quantity
                    for item in items
                ),
                total_pending_units=sum(
                    item.remaining_quantity
                    for item in items
                ),
                average_order_value=(
                    money(
                        total_value
                        / Decimal(len(records))
                    )
                    if records
                    else None
                ),
            )


purchase_order_store = PurchaseOrderStore()


# ============================================================
# SERVICE
# ============================================================

class PurchaseOrderService:

    def __init__(
        self,
        store: PurchaseOrderStore,
    ):
        self.store = store

    async def create(
        self,
        principal: Principal,
        payload: PurchaseOrderCreate,
    ) -> PurchaseOrderResponse:

        return await self.store.create(
            principal=principal,
            payload=payload,
        )


purchase_order_service = PurchaseOrderService(
    purchase_order_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Purchase Orders"],
)


@router.post(
    "",
    response_model=PurchaseOrderResponse,
    status_code=201,
)
async def create_purchase_order(
    payload: PurchaseOrderCreate,
    principal: CurrentPrincipal,
):
    return await purchase_order_service.create(
        principal,
        payload,
    )


@router.get(
    "",
    response_model=list[PurchaseOrderResponse],
)
async def list_purchase_orders(
    principal: CurrentPrincipal,
    warehouse_id: str | None = None,
    status: PurchaseOrderStatus | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await purchase_order_store.list_orders(
        principal=principal,
        warehouse_id=warehouse_id,
        status=status,
        limit=limit,
    )


@router.get(
    "/analytics/{warehouse_id}",
    response_model=PurchaseOrderAnalyticsResponse,
)
async def purchase_order_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
):
    return await purchase_order_store.analytics(
        principal=principal,
        warehouse_id=warehouse_id,
    )


@router.get(
    "/{purchase_order_id}",
    response_model=PurchaseOrderDetailResponse,
)
async def get_purchase_order(
    purchase_order_id: str,
    principal: CurrentPrincipal,
):
    return await purchase_order_store.get(
        principal=principal,
        purchase_order_id=purchase_order_id,
    )


@router.post(
    "/{purchase_order_id}/submit",
    response_model=PurchaseOrderResponse,
)
async def submit_purchase_order(
    purchase_order_id: str,
    payload: PurchaseOrderVersionRequest,
    principal: CurrentPrincipal,
):
    return await purchase_order_store.submit(
        principal=principal,
        purchase_order_id=purchase_order_id,
        expected_version=payload.expected_version,
    )


@router.post(
    "/{purchase_order_id}/approve",
    response_model=PurchaseOrderResponse,
)
async def approve_purchase_order(
    purchase_order_id: str,
    payload: PurchaseOrderDecision,
    principal: CurrentPrincipal,
):
    return await purchase_order_store.decide(
        principal=principal,
        purchase_order_id=purchase_order_id,
        payload=payload,
        approve=True,
    )


@router.post(
    "/{purchase_order_id}/reject",
    response_model=PurchaseOrderResponse,
)
async def reject_purchase_order(
    purchase_order_id: str,
    payload: PurchaseOrderDecision,
    principal: CurrentPrincipal,
):
    return await purchase_order_store.decide(
        principal=principal,
        purchase_order_id=purchase_order_id,
        payload=payload,
        approve=False,
    )


@router.post(
    "/{purchase_order_id}/issue",
    response_model=PurchaseOrderResponse,
)
async def issue_purchase_order(
    purchase_order_id: str,
    payload: PurchaseOrderIssueRequest,
    principal: CurrentPrincipal,
):
    return await purchase_order_store.issue(
        principal=principal,
        purchase_order_id=purchase_order_id,
        payload=payload,
    )


@router.post(
    "/{purchase_order_id}/receive",
    response_model=PurchaseOrderDetailResponse,
)
async def receive_purchase_order_goods(
    purchase_order_id: str,
    payload: GoodsReceiptCreate,
    principal: CurrentPrincipal,
):
    return await purchase_order_store.receive(
        principal=principal,
        purchase_order_id=purchase_order_id,
        payload=payload,
    )


@router.post(
    "/{purchase_order_id}/cancel",
    response_model=PurchaseOrderResponse,
)
async def cancel_purchase_order(
    purchase_order_id: str,
    payload: PurchaseOrderCancelRequest,
    principal: CurrentPrincipal,
):
    return await purchase_order_store.cancel(
        principal=principal,
        purchase_order_id=purchase_order_id,
        payload=payload,
    )


__all__ = [
    "PurchaseOrderStatus",
    "PurchaseOrderPriority",
    "PurchaseOrderEventType",
    "PurchaseOrderItemCreate",
    "PurchaseOrderCreate",
    "PurchaseOrderVersionRequest",
    "PurchaseOrderDecision",
    "PurchaseOrderIssueRequest",
    "GoodsReceiptItem",
    "GoodsReceiptCreate",
    "PurchaseOrderCancelRequest",
    "PurchaseOrderItemResponse",
    "GoodsReceiptResponse",
    "PurchaseOrderEventResponse",
    "PurchaseOrderResponse",
    "PurchaseOrderDetailResponse",
    "PurchaseOrderAnalyticsResponse",
    "PurchaseOrderStore",
    "PurchaseOrderService",
    "purchase_order_store",
    "purchase_order_service",
    "router",
]
