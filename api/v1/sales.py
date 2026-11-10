from __future__ import annotations

"""Planned module: sales. Implementation pending."""

"""
backend/sales.py

Autonomous Retail Supply Chain AI 5.0
Enterprise Sales Order Management API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Sales order creation
    - Multi-product sales orders
    - Customer references
    - Order confirmation
    - Inventory reservation references
    - Fulfillment status tracking
    - Payment recording
    - Cancellation
    - Refund tracking
    - Sales analytics
    - Tenant and warehouse isolation
    - Optimistic concurrency
    - Idempotent creation

IMPORTANT:
    This is an in-memory prototype.

    Payment recording does not charge customers.
    Inventory reservation does not reserve stock.
    Fulfillment does not ship products.
    Refund recording does not transfer money.

    Production requires authoritative inventory,
    payment, fulfillment, tax, and audit services.
"""


import asyncio
import hashlib
import json
import secrets

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
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


API_PREFIX = "/api/v1/sales"

MAX_ORDERS_PER_TENANT = 100000
MAX_ITEMS_PER_ORDER = 200
MAX_EVENTS_PER_ORDER = 1000
MAX_PAYMENTS_PER_ORDER = 100
MAX_REFUNDS_PER_ORDER = 100
MAX_IDEMPOTENCY_KEYS = 200000
MAX_LIST_LIMIT = 200

MONEY_QUANTUM = Decimal("0.01")


# ============================================================
# ENUMS
# ============================================================

class SalesOrderStatus(str, Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    RESERVED = "reserved"
    FULFILLMENT_PENDING = "fulfillment_pending"
    PICKING = "picking"
    PACKING = "packing"
    READY_FOR_DISPATCH = "ready_for_dispatch"
    DISPATCHED = "dispatched"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class PaymentStatus(str, Enum):
    UNPAID = "unpaid"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"


class PaymentMethod(str, Enum):
    UPI = "upi"
    CARD = "card"
    BANK_TRANSFER = "bank_transfer"
    CASH = "cash"
    WALLET = "wallet"
    OTHER = "other"


class SalesChannel(str, Enum):
    ONLINE = "online"
    RETAIL_STORE = "retail_store"
    WHOLESALE = "wholesale"
    MARKETPLACE = "marketplace"
    B2B = "b2b"


class SalesPriority(str, Enum):
    STANDARD = "standard"
    EXPRESS = "express"
    CRITICAL = "critical"


class SalesEventType(str, Enum):
    CREATED = "created"
    CONFIRMED = "confirmed"
    INVENTORY_RESERVED = "inventory_reserved"
    FULFILLMENT_STARTED = "fulfillment_started"
    PICKING_STARTED = "picking_started"
    PACKING_STARTED = "packing_started"
    READY_FOR_DISPATCH = "ready_for_dispatch"
    DISPATCHED = "dispatched"
    DELIVERED = "delivered"
    PAYMENT_RECORDED = "payment_recorded"
    REFUND_RECORDED = "refund_recorded"
    CANCELLED = "cancelled"


# ============================================================
# REQUEST SCHEMAS
# ============================================================

class SalesOrderItemCreate(BaseModel):
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
        le=1000000,
    )

    unit_price: Decimal = Field(
        ge=0,
        max_digits=16,
        decimal_places=2,
    )

    discount_amount: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=16,
        decimal_places=2,
    )

    @model_validator(mode="after")
    def validate_discount(self):

        subtotal = (
            Decimal(self.quantity)
            * self.unit_price
        )

        if self.discount_amount > subtotal:
            raise ValueError(
                "Discount cannot exceed line subtotal"
            )

        return self


class SalesOrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    customer_id: str = Field(
        min_length=1,
        max_length=128,
    )

    currency: str = Field(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    )

    channel: SalesChannel = SalesChannel.ONLINE

    priority: SalesPriority = SalesPriority.STANDARD

    items: list[SalesOrderItemCreate] = Field(
        min_length=1,
        max_length=MAX_ITEMS_PER_ORDER,
    )

    shipping_amount: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=16,
        decimal_places=2,
    )

    tax_amount: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=16,
        decimal_places=2,
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
    def validate_products(self):

        product_ids = [
            item.product_id
            for item in self.items
        ]

        if len(set(product_ids)) != len(product_ids):
            raise ValueError(
                "Duplicate product IDs are not allowed"
            )

        return self


class SalesVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class SalesReservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    reservation_reference: str = Field(
        min_length=1,
        max_length=200,
    )


class SalesFulfillmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    fulfillment_reference: str = Field(
        min_length=1,
        max_length=200,
    )


class SalesDispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    shipment_reference: str = Field(
        min_length=1,
        max_length=200,
    )


class SalesDeliveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    delivery_reference: str = Field(
        min_length=1,
        max_length=200,
    )


class SalesPaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    payment_reference: str = Field(
        min_length=1,
        max_length=200,
    )

    method: PaymentMethod

    amount: Decimal = Field(
        gt=0,
        max_digits=16,
        decimal_places=2,
    )


class SalesRefundCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    refund_reference: str = Field(
        min_length=1,
        max_length=200,
    )

    amount: Decimal = Field(
        gt=0,
        max_digits=16,
        decimal_places=2,
    )

    reason: str = Field(
        min_length=5,
        max_length=500,
    )


class SalesCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    reason: str = Field(
        min_length=5,
        max_length=500,
    )


# ============================================================
# RESPONSE SCHEMAS
# ============================================================

class SalesOrderItemResponse(BaseModel):
    product_id: str
    sku: str
    quantity: int
    unit_price: Decimal
    discount_amount: Decimal
    line_total: Decimal


class SalesPaymentResponse(BaseModel):
    payment_id: str
    payment_reference: str
    method: PaymentMethod
    amount: Decimal
    recorded_by: str
    created_at: datetime


class SalesRefundResponse(BaseModel):
    refund_id: str
    refund_reference: str
    amount: Decimal
    reason: str
    recorded_by: str
    created_at: datetime


class SalesEventResponse(BaseModel):
    event_id: str
    event_type: SalesEventType
    actor_id: str
    details: str | None
    created_at: datetime


class SalesOrderResponse(BaseModel):
    sales_order_id: str
    warehouse_id: str
    customer_id: str

    currency: str
    channel: SalesChannel
    priority: SalesPriority

    status: SalesOrderStatus
    payment_status: PaymentStatus

    subtotal: Decimal
    discount_total: Decimal
    tax_amount: Decimal
    shipping_amount: Decimal
    grand_total: Decimal

    paid_amount: Decimal
    refunded_amount: Decimal
    outstanding_amount: Decimal

    item_count: int
    total_units: int

    reservation_reference: str | None
    fulfillment_reference: str | None
    shipment_reference: str | None
    delivery_reference: str | None

    version: int
    created_at: datetime
    updated_at: datetime


class SalesOrderDetailResponse(SalesOrderResponse):
    items: list[SalesOrderItemResponse]
    payments: list[SalesPaymentResponse]
    refunds: list[SalesRefundResponse]
    events: list[SalesEventResponse]
    notes: str


class SalesAnalyticsResponse(BaseModel):
    total_orders: int
    confirmed_orders: int
    delivered_orders: int
    cancelled_orders: int

    gross_order_value: Decimal
    delivered_order_value: Decimal
    recorded_payments: Decimal
    recorded_refunds: Decimal

    total_units_ordered: int
    average_order_value: Decimal | None


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass
class SalesItemRecord:
    product_id: str
    sku: str
    quantity: int
    unit_price: Decimal
    discount_amount: Decimal

    @property
    def subtotal(self) -> Decimal:
        return money(
            Decimal(self.quantity) * self.unit_price
        )

    @property
    def line_total(self) -> Decimal:
        return money(
            self.subtotal - self.discount_amount
        )


@dataclass
class SalesOrderRecord:
    sales_order_id: str
    tenant_id: str
    warehouse_id: str
    customer_id: str

    currency: str
    channel: SalesChannel
    priority: SalesPriority

    items: dict[str, SalesItemRecord]

    tax_amount: Decimal
    shipping_amount: Decimal

    notes: str
    created_by: str

    status: SalesOrderStatus = SalesOrderStatus.DRAFT

    reservation_reference: str | None = None
    fulfillment_reference: str | None = None
    shipment_reference: str | None = None
    delivery_reference: str | None = None

    payments: list[SalesPaymentResponse] = field(
        default_factory=list
    )

    refunds: list[SalesRefundResponse] = field(
        default_factory=list
    )

    events: list[SalesEventResponse] = field(
        default_factory=list
    )

    version: int = 1

    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def money(value: Decimal) -> Decimal:
    return value.quantize(
        MONEY_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def fingerprint(payload: SalesOrderCreate) -> str:

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


def require_sales_access(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool,
) -> None:

    # Replace placeholder permissions with:
    # SALES_READ, SALES_WRITE, SALES_REFUND,
    # SALES_PAYMENT_RECORD.

    permission = (
        Permission.INVENTORY_WRITE
        if write
        else Permission.ANALYTICS_READ
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
            detail="Sales access denied",
        )


def calculate_totals(
    record: SalesOrderRecord,
) -> dict[str, Decimal]:

    items = list(record.items.values())

    subtotal = money(
        sum(
            (item.subtotal for item in items),
            Decimal("0"),
        )
    )

    discount_total = money(
        sum(
            (item.discount_amount for item in items),
            Decimal("0"),
        )
    )

    grand_total = money(
        subtotal
        - discount_total
        + record.tax_amount
        + record.shipping_amount
    )

    paid = money(
        sum(
            (payment.amount for payment in record.payments),
            Decimal("0"),
        )
    )

    refunded = money(
        sum(
            (refund.amount for refund in record.refunds),
            Decimal("0"),
        )
    )

    outstanding = money(
        max(
            grand_total - paid,
            Decimal("0"),
        )
    )

    return {
        "subtotal": subtotal,
        "discount_total": discount_total,
        "grand_total": grand_total,
        "paid": paid,
        "refunded": refunded,
        "outstanding": outstanding,
    }


def get_payment_status(
    record: SalesOrderRecord,
) -> PaymentStatus:

    totals = calculate_totals(record)

    paid = totals["paid"]
    refunded = totals["refunded"]
    total = totals["grand_total"]

    if paid == 0:
        return PaymentStatus.UNPAID

    if refunded > 0:
        if refunded >= paid:
            return PaymentStatus.REFUNDED
        return PaymentStatus.PARTIALLY_REFUNDED

    if paid >= total:
        return PaymentStatus.PAID

    return PaymentStatus.PARTIALLY_PAID


def to_response(
    record: SalesOrderRecord,
) -> SalesOrderResponse:

    totals = calculate_totals(record)

    return SalesOrderResponse(
        sales_order_id=record.sales_order_id,
        warehouse_id=record.warehouse_id,
        customer_id=record.customer_id,
        currency=record.currency,
        channel=record.channel,
        priority=record.priority,
        status=record.status,
        payment_status=get_payment_status(record),
        subtotal=totals["subtotal"],
        discount_total=totals["discount_total"],
        tax_amount=record.tax_amount,
        shipping_amount=record.shipping_amount,
        grand_total=totals["grand_total"],
        paid_amount=totals["paid"],
        refunded_amount=totals["refunded"],
        outstanding_amount=totals["outstanding"],
        item_count=len(record.items),
        total_units=sum(
            item.quantity
            for item in record.items.values()
        ),
        reservation_reference=record.reservation_reference,
        fulfillment_reference=record.fulfillment_reference,
        shipment_reference=record.shipment_reference,
        delivery_reference=record.delivery_reference,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def to_detail(
    record: SalesOrderRecord,
) -> SalesOrderDetailResponse:

    return SalesOrderDetailResponse(
        **to_response(record).model_dump(),
        items=[
            SalesOrderItemResponse(
                product_id=item.product_id,
                sku=item.sku,
                quantity=item.quantity,
                unit_price=item.unit_price,
                discount_amount=item.discount_amount,
                line_total=item.line_total,
            )
            for item in record.items.values()
        ],
        payments=list(record.payments),
        refunds=list(record.refunds),
        events=list(record.events),
        notes=record.notes,
    )


# ============================================================
# SALES STORE
# ============================================================

class SalesStore:

    def __init__(self):

        self.orders: dict[str, SalesOrderRecord] = {}

        self.idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self.lock = asyncio.Lock()

    def _get(
        self,
        principal: Principal,
        order_id: str,
        *,
        write: bool,
    ) -> SalesOrderRecord:

        record = self.orders.get(order_id)

        if (
            record is None
            or record.tenant_id != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Sales order not found",
            )

        require_sales_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    @staticmethod
    def _check_version(
        record: SalesOrderRecord,
        expected_version: int,
    ) -> None:

        if record.version != expected_version:
            raise HTTPException(
                status_code=409,
                detail="Sales order version conflict",
            )

    @staticmethod
    def _require_status(
        record: SalesOrderRecord,
        allowed: set[SalesOrderStatus],
    ) -> None:

        if record.status not in allowed:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Invalid sales order state: "
                    f"{record.status.value}"
                ),
            )

    @staticmethod
    def _add_event(
        record: SalesOrderRecord,
        event_type: SalesEventType,
        actor_id: str,
        details: str | None = None,
    ) -> None:

        if len(record.events) >= MAX_EVENTS_PER_ORDER:
            raise HTTPException(
                status_code=503,
                detail="Sales event capacity reached",
            )

        record.events.append(
            SalesEventResponse(
                event_id=secrets.token_urlsafe(16),
                event_type=event_type,
                actor_id=actor_id,
                details=details,
                created_at=utc_now(),
            )
        )

    @staticmethod
    def _touch(
        record: SalesOrderRecord,
    ) -> None:

        record.version += 1
        record.updated_at = utc_now()

    async def create(
        self,
        principal: Principal,
        payload: SalesOrderCreate,
    ) -> SalesOrderResponse:

        require_sales_access(
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

        async with self.lock:

            previous = self.idempotency.get(key)

            if previous:

                old_hash, order_id = previous

                if old_hash != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return to_response(
                    self._get(
                        principal,
                        order_id,
                        write=False,
                    )
                )

            tenant_count = sum(
                record.tenant_id == principal.tenant_id
                for record in self.orders.values()
            )

            if (
                tenant_count >= MAX_ORDERS_PER_TENANT
                or len(self.idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Sales storage capacity reached",
                )

            record = SalesOrderRecord(
                sales_order_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                customer_id=payload.customer_id,
                currency=payload.currency,
                channel=payload.channel,
                priority=payload.priority,
                items={
                    item.product_id: SalesItemRecord(
                        product_id=item.product_id,
                        sku=item.sku,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        discount_amount=item.discount_amount,
                    )
                    for item in payload.items
                },
                tax_amount=payload.tax_amount,
                shipping_amount=payload.shipping_amount,
                notes=payload.notes,
                created_by=principal.principal_id,
            )

            self._add_event(
                record,
                SalesEventType.CREATED,
                principal.principal_id,
            )

            self.orders[record.sales_order_id] = record

            self.idempotency[key] = (
                request_hash,
                record.sales_order_id,
            )

            return to_response(record)

    async def get(
        self,
        principal: Principal,
        order_id: str,
    ) -> SalesOrderDetailResponse:

        async with self.lock:

            return to_detail(
                self._get(
                    principal,
                    order_id,
                    write=False,
                )
            )

    async def list_orders(
        self,
        principal: Principal,
        warehouse_id: str | None,
        status: SalesOrderStatus | None,
        limit: int,
    ) -> list[SalesOrderResponse]:

        async with self.lock:

            records = [
                record
                for record in self.orders.values()
                if (
                    record.tenant_id == principal.tenant_id
                    and (
                        warehouse_id is None
                        or record.warehouse_id == warehouse_id
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
                    require_sales_access(
                        principal,
                        record.warehouse_id,
                        write=False,
                    )
                except HTTPException:
                    continue

                results.append(to_response(record))

                if len(results) >= limit:
                    break

            return results

    async def transition(
        self,
        principal: Principal,
        order_id: str,
        expected_version: int,
        allowed: set[SalesOrderStatus],
        new_status: SalesOrderStatus,
        event_type: SalesEventType,
        reference_field: str | None = None,
        reference_value: str | None = None,
    ) -> SalesOrderResponse:

        async with self.lock:

            record = self._get(
                principal,
                order_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            self._require_status(
                record,
                allowed,
            )

            self._add_event(
                record,
                event_type,
                principal.principal_id,
                reference_value,
            )

            record.status = new_status

            if reference_field:
                setattr(
                    record,
                    reference_field,
                    reference_value,
                )

            self._touch(record)

            return to_response(record)

    async def record_payment(
        self,
        principal: Principal,
        order_id: str,
        payload: SalesPaymentCreate,
    ) -> SalesOrderDetailResponse:

        async with self.lock:

            record = self._get(
                principal,
                order_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status == SalesOrderStatus.CANCELLED:
                raise HTTPException(
                    status_code=409,
                    detail="Cannot record payment on cancelled order",
                )

            if len(record.payments) >= MAX_PAYMENTS_PER_ORDER:
                raise HTTPException(
                    status_code=503,
                    detail="Payment record capacity reached",
                )

            if any(
                payment.payment_reference
                == payload.payment_reference
                for payment in record.payments
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Payment reference already exists",
                )

            totals = calculate_totals(record)

            if payload.amount > totals["outstanding"]:
                raise HTTPException(
                    status_code=409,
                    detail="Payment exceeds outstanding balance",
                )

            self._add_event(
                record,
                SalesEventType.PAYMENT_RECORDED,
                principal.principal_id,
                payload.payment_reference,
            )

            record.payments.append(
                SalesPaymentResponse(
                    payment_id=secrets.token_urlsafe(20),
                    payment_reference=payload.payment_reference,
                    method=payload.method,
                    amount=payload.amount,
                    recorded_by=principal.principal_id,
                    created_at=utc_now(),
                )
            )

            self._touch(record)

            return to_detail(record)

    async def record_refund(
        self,
        principal: Principal,
        order_id: str,
        payload: SalesRefundCreate,
    ) -> SalesOrderDetailResponse:

        async with self.lock:

            record = self._get(
                principal,
                order_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if len(record.refunds) >= MAX_REFUNDS_PER_ORDER:
                raise HTTPException(
                    status_code=503,
                    detail="Refund record capacity reached",
                )

            if any(
                refund.refund_reference
                == payload.refund_reference
                for refund in record.refunds
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Refund reference already exists",
                )

            totals = calculate_totals(record)

            refundable = (
                totals["paid"] - totals["refunded"]
            )

            if payload.amount > refundable:
                raise HTTPException(
                    status_code=409,
                    detail="Refund exceeds refundable balance",
                )

            self._add_event(
                record,
                SalesEventType.REFUND_RECORDED,
                principal.principal_id,
                payload.refund_reference,
            )

            record.refunds.append(
                SalesRefundResponse(
                    refund_id=secrets.token_urlsafe(20),
                    refund_reference=payload.refund_reference,
                    amount=payload.amount,
                    reason=payload.reason,
                    recorded_by=principal.principal_id,
                    created_at=utc_now(),
                )
            )

            self._touch(record)

            return to_detail(record)

    async def cancel(
        self,
        principal: Principal,
        order_id: str,
        payload: SalesCancelRequest,
    ) -> SalesOrderResponse:

        async with self.lock:

            record = self._get(
                principal,
                order_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status in {
                SalesOrderStatus.DISPATCHED,
                SalesOrderStatus.DELIVERED,
                SalesOrderStatus.CANCELLED,
            }:
                raise HTTPException(
                    status_code=409,
                    detail="Order cannot be cancelled",
                )

            if record.payments:
                raise HTTPException(
                    status_code=409,
                    detail="Paid orders require refund workflow before cancellation",
                )

            self._add_event(
                record,
                SalesEventType.CANCELLED,
                principal.principal_id,
                payload.reason,
            )

            record.status = SalesOrderStatus.CANCELLED

            self._touch(record)

            return to_response(record)

    async def analytics(
        self,
        principal: Principal,
        warehouse_id: str,
    ) -> SalesAnalyticsResponse:

        require_sales_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self.lock:

            records = [
                record
                for record in self.orders.values()
                if (
                    record.tenant_id == principal.tenant_id
                    and record.warehouse_id == warehouse_id
                )
            ]

            total_value = sum(
                (
                    calculate_totals(record)["grand_total"]
                    for record in records
                ),
                Decimal("0"),
            )

            delivered_value = sum(
                (
                    calculate_totals(record)["grand_total"]
                    for record in records
                    if record.status
                    == SalesOrderStatus.DELIVERED
                ),
                Decimal("0"),
            )

            paid = sum(
                (
                    calculate_totals(record)["paid"]
                    for record in records
                ),
                Decimal("0"),
            )

            refunded = sum(
                (
                    calculate_totals(record)["refunded"]
                    for record in records
                ),
                Decimal("0"),
            )

            return SalesAnalyticsResponse(
                total_orders=len(records),
                confirmed_orders=sum(
                    record.status
                    == SalesOrderStatus.CONFIRMED
                    for record in records
                ),
                delivered_orders=sum(
                    record.status
                    == SalesOrderStatus.DELIVERED
                    for record in records
                ),
                cancelled_orders=sum(
                    record.status
                    == SalesOrderStatus.CANCELLED
                    for record in records
                ),
                gross_order_value=money(total_value),
                delivered_order_value=money(
                    delivered_value
                ),
                recorded_payments=money(paid),
                recorded_refunds=money(refunded),
                total_units_ordered=sum(
                    item.quantity
                    for record in records
                    for item in record.items.values()
                ),
                average_order_value=(
                    money(
                        total_value / Decimal(len(records))
                    )
                    if records
                    else None
                ),
            )


sales_store = SalesStore()


# ============================================================
# SALES SERVICE
# ============================================================

class SalesService:

    def __init__(self, store: SalesStore):
        self.store = store

    async def create(
        self,
        principal: Principal,
        payload: SalesOrderCreate,
    ) -> SalesOrderResponse:

        return await self.store.create(
            principal,
            payload,
        )


sales_service = SalesService(sales_store)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Sales Management"],
)


@router.post(
    "",
    response_model=SalesOrderResponse,
    status_code=201,
)
async def create_sales_order(
    payload: SalesOrderCreate,
    principal: CurrentPrincipal,
):
    return await sales_service.create(
        principal,
        payload,
    )


@router.get(
    "",
    response_model=list[SalesOrderResponse],
)
async def list_sales_orders(
    principal: CurrentPrincipal,
    warehouse_id: str | None = None,
    status: SalesOrderStatus | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await sales_store.list_orders(
        principal,
        warehouse_id,
        status,
        limit,
    )


@router.get(
    "/analytics/{warehouse_id}",
    response_model=SalesAnalyticsResponse,
)
async def sales_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
):
    return await sales_store.analytics(
        principal,
        warehouse_id,
    )


@router.get(
    "/{order_id}",
    response_model=SalesOrderDetailResponse,
)
async def get_sales_order(
    order_id: str,
    principal: CurrentPrincipal,
):
    return await sales_store.get(
        principal,
        order_id,
    )


@router.post(
    "/{order_id}/confirm",
    response_model=SalesOrderResponse,
)
async def confirm_sales_order(
    order_id: str,
    payload: SalesVersionRequest,
    principal: CurrentPrincipal,
):
    return await sales_store.transition(
        principal,
        order_id,
        payload.expected_version,
        {SalesOrderStatus.DRAFT},
        SalesOrderStatus.CONFIRMED,
        SalesEventType.CONFIRMED,
    )


@router.post(
    "/{order_id}/reserve",
    response_model=SalesOrderResponse,
)
async def reserve_sales_inventory(
    order_id: str,
    payload: SalesReservationRequest,
    principal: CurrentPrincipal,
):
    return await sales_store.transition(
        principal,
        order_id,
        payload.expected_version,
        {SalesOrderStatus.CONFIRMED},
        SalesOrderStatus.RESERVED,
        SalesEventType.INVENTORY_RESERVED,
        "reservation_reference",
        payload.reservation_reference,
    )


@router.post(
    "/{order_id}/fulfillment",
    response_model=SalesOrderResponse,
)
async def start_sales_fulfillment(
    order_id: str,
    payload: SalesFulfillmentRequest,
    principal: CurrentPrincipal,
):
    return await sales_store.transition(
        principal,
        order_id,
        payload.expected_version,
        {SalesOrderStatus.RESERVED},
        SalesOrderStatus.FULFILLMENT_PENDING,
        SalesEventType.FULFILLMENT_STARTED,
        "fulfillment_reference",
        payload.fulfillment_reference,
    )


@router.post(
    "/{order_id}/picking",
    response_model=SalesOrderResponse,
)
async def start_sales_picking(
    order_id: str,
    payload: SalesVersionRequest,
    principal: CurrentPrincipal,
):
    return await sales_store.transition(
        principal,
        order_id,
        payload.expected_version,
        {SalesOrderStatus.FULFILLMENT_PENDING},
        SalesOrderStatus.PICKING,
        SalesEventType.PICKING_STARTED,
    )


@router.post(
    "/{order_id}/packing",
    response_model=SalesOrderResponse,
)
async def start_sales_packing(
    order_id: str,
    payload: SalesVersionRequest,
    principal: CurrentPrincipal,
):
    return await sales_store.transition(
        principal,
        order_id,
        payload.expected_version,
        {SalesOrderStatus.PICKING},
        SalesOrderStatus.PACKING,
        SalesEventType.PACKING_STARTED,
    )


@router.post(
    "/{order_id}/ready",
    response_model=SalesOrderResponse,
)
async def mark_sales_ready(
    order_id: str,
    payload: SalesVersionRequest,
    principal: CurrentPrincipal,
):
    return await sales_store.transition(
        principal,
        order_id,
        payload.expected_version,
        {SalesOrderStatus.PACKING},
        SalesOrderStatus.READY_FOR_DISPATCH,
        SalesEventType.READY_FOR_DISPATCH,
    )


@router.post(
    "/{order_id}/dispatch",
    response_model=SalesOrderResponse,
)
async def dispatch_sales_order(
    order_id: str,
    payload: SalesDispatchRequest,
    principal: CurrentPrincipal,
):
    return await sales_store.transition(
        principal,
        order_id,
        payload.expected_version,
        {SalesOrderStatus.READY_FOR_DISPATCH},
        SalesOrderStatus.DISPATCHED,
        SalesEventType.DISPATCHED,
        "shipment_reference",
        payload.shipment_reference,
    )


@router.post(
    "/{order_id}/deliver",
    response_model=SalesOrderResponse,
)
async def deliver_sales_order(
    order_id: str,
    payload: SalesDeliveryRequest,
    principal: CurrentPrincipal,
):
    return await sales_store.transition(
        principal,
        order_id,
        payload.expected_version,
        {SalesOrderStatus.DISPATCHED},
        SalesOrderStatus.DELIVERED,
        SalesEventType.DELIVERED,
        "delivery_reference",
        payload.delivery_reference,
    )


@router.post(
    "/{order_id}/payments",
    response_model=SalesOrderDetailResponse,
)
async def record_sales_payment(
    order_id: str,
    payload: SalesPaymentCreate,
    principal: CurrentPrincipal,
):
    return await sales_store.record_payment(
        principal,
        order_id,
        payload,
    )


@router.post(
    "/{order_id}/refunds",
    response_model=SalesOrderDetailResponse,
)
async def record_sales_refund(
    order_id: str,
    payload: SalesRefundCreate,
    principal: CurrentPrincipal,
):
    return await sales_store.record_refund(
        principal,
        order_id,
        payload,
    )


@router.post(
    "/{order_id}/cancel",
    response_model=SalesOrderResponse,
)
async def cancel_sales_order(
    order_id: str,
    payload: SalesCancelRequest,
    principal: CurrentPrincipal,
):
    return await sales_store.cancel(
        principal,
        order_id,
        payload,
    )


__all__ = [
    "SalesOrderStatus",
    "PaymentStatus",
    "PaymentMethod",
    "SalesChannel",
    "SalesPriority",
    "SalesEventType",
    "SalesOrderItemCreate",
    "SalesOrderCreate",
    "SalesVersionRequest",
    "SalesReservationRequest",
    "SalesFulfillmentRequest",
    "SalesDispatchRequest",
    "SalesDeliveryRequest",
    "SalesPaymentCreate",
    "SalesRefundCreate",
    "SalesCancelRequest",
    "SalesOrderItemResponse",
    "SalesPaymentResponse",
    "SalesRefundResponse",
    "SalesEventResponse",
    "SalesOrderResponse",
    "SalesOrderDetailResponse",
    "SalesAnalyticsResponse",
    "SalesStore",
    "SalesService",
    "sales_store",
    "sales_service",
    "router",
]
