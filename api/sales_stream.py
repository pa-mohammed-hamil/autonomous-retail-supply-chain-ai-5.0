from __future__ import annotations

"""Planned module: sales stream. Implementation pending."""

"""
backend/sales_stream.py

Autonomous Retail Supply Chain AI 5.0
Sales Event Monitoring and Analytics

Python 3.10+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Tenant-isolated sales monitoring
    - Warehouse-scoped authorization
    - Order creation and payment updates
    - Sales and refund tracking
    - Revenue calculations
    - Daily sales summaries
    - Product-level sales analytics
    - Sales trend detection
    - Duplicate event protection
    - Order version validation
    - Read-only sales monitoring endpoints

Security:
    - No public event mutation endpoint
    - Committed events only
    - No customer payment credentials
    - No cardholder data
    - Warehouse-level authorization
    - No unsafe tenant-wide WebSocket broadcasts

Production:
    Replace memory storage with PostgreSQL.
    Use a transactional outbox and durable
    message consumer.
"""


import asyncio
import hashlib
import json
import secrets

from collections import defaultdict, deque
from dataclasses import dataclass
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


# ============================================================
# CONFIGURATION
# ============================================================

MAX_HISTORY_PER_ORDER = 200
MAX_ORDERS_PER_TENANT = 10000
MAX_EVENT_RECORDS = 50000

MAX_QUANTITY = 1_000_000
MAX_MONEY = Decimal("999999999999.99")

DEFAULT_TREND_WINDOW = 7
SALES_SPIKE_RATIO = Decimal("1.50")
SALES_DROP_RATIO = Decimal("0.60")


# ============================================================
# ENUMS
# ============================================================

class SalesEventType(str, Enum):

    ORDER_CREATED = "order_created"
    PAYMENT_CONFIRMED = "payment_confirmed"
    ORDER_FULFILLED = "order_fulfilled"
    ORDER_CANCELLED = "order_cancelled"
    REFUND_ISSUED = "refund_issued"
    RETURN_COMPLETED = "return_completed"


class SalesOrderStatus(str, Enum):

    CREATED = "created"
    PAID = "paid"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"


class SalesChannel(str, Enum):

    POS = "pos"
    ECOMMERCE = "ecommerce"
    MARKETPLACE = "marketplace"
    WHOLESALE = "wholesale"


class SalesTrend(str, Enum):

    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"
    INSUFFICIENT_DATA = "insufficient_data"


class SalesAlertType(str, Enum):

    SALES_SPIKE = "sales_spike"
    SALES_DROP = "sales_drop"
    LARGE_REFUND = "large_refund"
    ORDER_CANCELLED = "order_cancelled"


class SalesSeverity(str, Enum):

    INFO = "info"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ============================================================
# STATUS TRANSITIONS
# ============================================================

ALLOWED_TRANSITIONS = {

    SalesOrderStatus.CREATED: {
        SalesOrderStatus.PAID,
        SalesOrderStatus.CANCELLED,
    },

    SalesOrderStatus.PAID: {
        SalesOrderStatus.FULFILLED,
        SalesOrderStatus.CANCELLED,
        SalesOrderStatus.PARTIALLY_REFUNDED,
        SalesOrderStatus.REFUNDED,
    },

    SalesOrderStatus.FULFILLED: {
        SalesOrderStatus.PARTIALLY_REFUNDED,
        SalesOrderStatus.REFUNDED,
    },

    SalesOrderStatus.PARTIALLY_REFUNDED: {
        SalesOrderStatus.REFUNDED,
    },

    SalesOrderStatus.REFUNDED: set(),

    SalesOrderStatus.CANCELLED: set(),
}


# ============================================================
# REQUEST MODELS
# ============================================================

class SalesLine(BaseModel):

    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    quantity: int = Field(
        gt=0,
        le=MAX_QUANTITY,
    )

    unit_price: Decimal = Field(
        ge=0,
        le=MAX_MONEY,
        max_digits=14,
        decimal_places=2,
    )

    @property
    def total(self) -> Decimal:
        return self.quantity * self.unit_price


class SalesEventCreate(BaseModel):

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(
        min_length=1,
        max_length=128,
    )

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    event_type: SalesEventType

    status: SalesOrderStatus

    sales_channel: SalesChannel

    order_version: int = Field(ge=1)

    source_event_id: str = Field(
        min_length=8,
        max_length=128,
    )

    currency: str = Field(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    )

    lines: list[SalesLine] = Field(
        min_length=1,
        max_length=500,
    )

    refund_total: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        le=MAX_MONEY,
    )

    occurred_at: datetime

    @model_validator(mode="after")
    def validate_event(self):

        if self.occurred_at.tzinfo is None:
            raise ValueError(
                "occurred_at must include timezone"
            )

        gross_total = sum(
            (line.total for line in self.lines),
            Decimal("0"),
        )

        if gross_total > MAX_MONEY:
            raise ValueError(
                "Order total exceeds supported limit"
            )

        if self.refund_total > gross_total:
            raise ValueError(
                "Refund total exceeds order total"
            )

        if (
            self.status == SalesOrderStatus.REFUNDED
            and self.refund_total != gross_total
        ):
            raise ValueError(
                "Fully refunded orders require "
                "refund_total equal to gross total"
            )

        if (
            self.status == SalesOrderStatus.PARTIALLY_REFUNDED
            and not (
                Decimal("0")
                < self.refund_total
                < gross_total
            )
        ):
            raise ValueError(
                "Partial refund must be greater "
                "than zero and below gross total"
            )

        return self


# ============================================================
# RESPONSE MODELS
# ============================================================

class SalesEventResponse(BaseModel):

    event_id: str
    order_id: str
    warehouse_id: str

    event_type: SalesEventType
    status: SalesOrderStatus

    order_version: int

    gross_total: Decimal
    refund_total: Decimal
    net_total: Decimal

    currency: str

    occurred_at: datetime
    received_at: datetime


class SalesOrderSnapshot(BaseModel):

    order_id: str
    warehouse_id: str

    sales_channel: SalesChannel
    status: SalesOrderStatus

    order_version: int

    gross_total: Decimal
    refund_total: Decimal
    net_total: Decimal

    currency: str

    last_updated: datetime


class SalesSummary(BaseModel):

    warehouse_id: str

    total_orders: int
    paid_orders: int
    fulfilled_orders: int
    cancelled_orders: int

    gross_sales: Decimal
    refunds: Decimal
    net_sales: Decimal

    currency: str


class ProductSalesSummary(BaseModel):

    product_id: str
    warehouse_id: str

    units_ordered: int

    gross_sales: Decimal

    currency: str


class SalesAlert(BaseModel):

    alert_id: str

    order_id: str
    warehouse_id: str

    alert_type: SalesAlertType
    severity: SalesSeverity

    message: str

    created_at: datetime


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass(frozen=True)
class SalesEventRecord:

    event_id: str
    tenant_id: str

    order_id: str
    warehouse_id: str

    event_type: SalesEventType
    status: SalesOrderStatus
    sales_channel: SalesChannel

    order_version: int

    source_event_id: str
    payload_fingerprint: str

    currency: str

    lines: tuple[SalesLine, ...]

    gross_total: Decimal
    refund_total: Decimal

    occurred_at: datetime
    received_at: datetime


@dataclass(frozen=True)
class SalesOrderState:

    tenant_id: str

    order_id: str
    warehouse_id: str

    sales_channel: SalesChannel
    status: SalesOrderStatus

    order_version: int

    currency: str

    lines: tuple[SalesLine, ...]

    gross_total: Decimal
    refund_total: Decimal

    last_updated: datetime


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def calculate_gross(
    lines: list[SalesLine] | tuple[SalesLine, ...],
) -> Decimal:

    return sum(
        (line.total for line in lines),
        Decimal("0"),
    )


def calculate_net(
    gross: Decimal,
    refunds: Decimal,
) -> Decimal:

    return gross - refunds


def fingerprint_event(
    payload: SalesEventCreate,
) -> str:

    canonical = json.dumps(
        payload.model_dump(
            mode="json",
            exclude={"source_event_id"},
        ),
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def to_event_response(
    record: SalesEventRecord,
) -> SalesEventResponse:

    return SalesEventResponse(
        event_id=record.event_id,
        order_id=record.order_id,
        warehouse_id=record.warehouse_id,
        event_type=record.event_type,
        status=record.status,
        order_version=record.order_version,
        gross_total=record.gross_total,
        refund_total=record.refund_total,
        net_total=calculate_net(
            record.gross_total,
            record.refund_total,
        ),
        currency=record.currency,
        occurred_at=record.occurred_at,
        received_at=record.received_at,
    )


def to_snapshot(
    state: SalesOrderState,
) -> SalesOrderSnapshot:

    return SalesOrderSnapshot(
        order_id=state.order_id,
        warehouse_id=state.warehouse_id,
        sales_channel=state.sales_channel,
        status=state.status,
        order_version=state.order_version,
        gross_total=state.gross_total,
        refund_total=state.refund_total,
        net_total=calculate_net(
            state.gross_total,
            state.refund_total,
        ),
        currency=state.currency,
        last_updated=state.last_updated,
    )


# ============================================================
# AUTHORIZATION
# ============================================================

def require_sales_access(
    principal: Principal,
    warehouse_id: str,
) -> None:

    resource = ResourceContext(
        tenant_id=principal.tenant_id,
        warehouse_id=warehouse_id,
    )

    decision = permission_engine.evaluate(
        principal,
        Permission.ANALYTICS_READ,
        resource,
    )

    if not decision.allowed:

        raise HTTPException(
            status_code=403,
            detail="Sales access denied",
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
# ALERT DETECTION
# ============================================================

def detect_sales_alerts(
    previous: SalesOrderState | None,
    current: SalesOrderState,
) -> list[SalesAlert]:

    alerts: list[SalesAlert] = []

    def add_alert(
        alert_type: SalesAlertType,
        severity: SalesSeverity,
        message: str,
    ) -> None:

        alerts.append(
            SalesAlert(
                alert_id=secrets.token_urlsafe(16),
                order_id=current.order_id,
                warehouse_id=current.warehouse_id,
                alert_type=alert_type,
                severity=severity,
                message=message,
                created_at=utc_now(),
            )
        )

    if (
        current.status == SalesOrderStatus.CANCELLED
        and (
            previous is None
            or previous.status != SalesOrderStatus.CANCELLED
        )
    ):
        add_alert(
            SalesAlertType.ORDER_CANCELLED,
            SalesSeverity.MEDIUM,
            "Sales order was cancelled.",
        )

    if previous is not None:

        refund_delta = (
            current.refund_total
            - previous.refund_total
        )

        if (
            refund_delta > 0
            and current.gross_total > 0
            and (
                refund_delta / current.gross_total
            ) >= Decimal("0.50")
        ):
            add_alert(
                SalesAlertType.LARGE_REFUND,
                SalesSeverity.HIGH,
                "A large refund was recorded.",
            )

    return alerts


# ============================================================
# SALES STREAM STORE
# ============================================================

class SalesStreamStore:

    def __init__(self):

        self._states: dict[
            tuple[str, str],
            SalesOrderState,
        ] = {}

        self._history: dict[
            tuple[str, str],
            deque[SalesEventRecord],
        ] = defaultdict(
            lambda: deque(
                maxlen=MAX_HISTORY_PER_ORDER
            )
        )

        self._idempotency: dict[
            tuple[str, str],
            tuple[str, str, str],
        ] = {}

        self._lock = asyncio.Lock()

    async def apply_committed_event(
        self,
        *,
        tenant_id: str,
        payload: SalesEventCreate,
    ) -> tuple[
        SalesEventRecord,
        SalesOrderState,
        SalesOrderState | None,
        bool,
    ]:

        key = (
            tenant_id,
            payload.order_id,
        )

        idempotency_key = (
            tenant_id,
            payload.source_event_id,
        )

        fingerprint = fingerprint_event(
            payload
        )

        async with self._lock:

            existing = self._idempotency.get(
                idempotency_key
            )

            if existing is not None:

                (
                    existing_order_id,
                    existing_event_id,
                    existing_fingerprint,
                ) = existing

                if (
                    existing_fingerprint
                    != fingerprint
                ):
                    raise ValueError(
                        "Idempotency conflict"
                    )

                history_key = (
                    tenant_id,
                    existing_order_id,
                )

                for record in self._history.get(
                    history_key,
                    (),
                ):
                    if record.event_id == existing_event_id:

                        return (
                            record,
                            self._states[history_key],
                            None,
                            False,
                        )

                raise ValueError(
                    "Previously processed event "
                    "is no longer retained"
                )

            previous = self._states.get(key)

            if previous is not None:

                if (
                    payload.order_version
                    != previous.order_version + 1
                ):
                    raise ValueError(
                        "Sales order version gap"
                    )

                if (
                    payload.warehouse_id
                    != previous.warehouse_id
                ):
                    raise ValueError(
                        "Warehouse change is not "
                        "supported by this projection"
                    )

                if (
                    payload.currency
                    != previous.currency
                ):
                    raise ValueError(
                        "Order currency cannot change"
                    )

                if (
                    payload.status
                    != previous.status
                ):

                    allowed = ALLOWED_TRANSITIONS.get(
                        previous.status,
                        set(),
                    )

                    if payload.status not in allowed:
                        raise ValueError(
                            "Invalid order status transition"
                        )

                if (
                    payload.refund_total
                    < previous.refund_total
                ):
                    raise ValueError(
                        "Cumulative refunds cannot decrease"
                    )

            else:

                tenant_order_count = sum(
                    1
                    for tenant, _ in self._states
                    if tenant == tenant_id
                )

                if (
                    tenant_order_count
                    >= MAX_ORDERS_PER_TENANT
                ):
                    raise ValueError(
                        "Sales stream capacity reached"
                    )

            gross_total = calculate_gross(
                payload.lines
            )

            received_at = utc_now()

            record = SalesEventRecord(
                event_id=secrets.token_urlsafe(20),
                tenant_id=tenant_id,
                order_id=payload.order_id,
                warehouse_id=payload.warehouse_id,
                event_type=payload.event_type,
                status=payload.status,
                sales_channel=payload.sales_channel,
                order_version=payload.order_version,
                source_event_id=payload.source_event_id,
                payload_fingerprint=fingerprint,
                currency=payload.currency,
                lines=tuple(payload.lines),
                gross_total=gross_total,
                refund_total=payload.refund_total,
                occurred_at=payload.occurred_at,
                received_at=received_at,
            )

            state = SalesOrderState(
                tenant_id=tenant_id,
                order_id=payload.order_id,
                warehouse_id=payload.warehouse_id,
                sales_channel=payload.sales_channel,
                status=payload.status,
                order_version=payload.order_version,
                currency=payload.currency,
                lines=tuple(payload.lines),
                gross_total=gross_total,
                refund_total=payload.refund_total,
                last_updated=received_at,
            )

            self._states[key] = state

            self._history[key].append(record)

            self._idempotency[
                idempotency_key
            ] = (
                payload.order_id,
                record.event_id,
                fingerprint,
            )

            return (
                record,
                state,
                previous,
                True,
            )

    async def get_snapshot(
        self,
        *,
        tenant_id: str,
        order_id: str,
    ) -> SalesOrderState | None:

        async with self._lock:

            return self._states.get(
                (tenant_id, order_id)
            )

    async def get_history(
        self,
        *,
        tenant_id: str,
        order_id: str,
        limit: int = 50,
    ) -> list[SalesEventRecord]:

        async with self._lock:

            records = list(
                self._history.get(
                    (tenant_id, order_id),
                    (),
                )
            )

        return list(
            reversed(records[-limit:])
        )

    async def list_orders(
        self,
        *,
        tenant_id: str,
        warehouse_id: str,
    ) -> list[SalesOrderState]:

        async with self._lock:

            return [
                state
                for state in self._states.values()
                if (
                    state.tenant_id == tenant_id
                    and state.warehouse_id == warehouse_id
                )
            ]


sales_store = SalesStreamStore()


# ============================================================
# SALES ANALYTICS
# ============================================================

def calculate_sales_summary(
    orders: list[SalesOrderState],
    warehouse_id: str,
    currency: str,
) -> SalesSummary:

    selected = [
        order
        for order in orders
        if order.currency == currency
    ]

    gross = sum(
        (
            order.gross_total
            for order in selected
            if order.status in {
                SalesOrderStatus.PAID,
                SalesOrderStatus.FULFILLED,
                SalesOrderStatus.PARTIALLY_REFUNDED,
                SalesOrderStatus.REFUNDED,
            }
        ),
        Decimal("0"),
    )

    refunds = sum(
        (
            order.refund_total
            for order in selected
        ),
        Decimal("0"),
    )

    return SalesSummary(
        warehouse_id=warehouse_id,
        total_orders=len(selected),
        paid_orders=sum(
            order.status == SalesOrderStatus.PAID
            for order in selected
        ),
        fulfilled_orders=sum(
            order.status == SalesOrderStatus.FULFILLED
            for order in selected
        ),
        cancelled_orders=sum(
            order.status == SalesOrderStatus.CANCELLED
            for order in selected
        ),
        gross_sales=gross,
        refunds=refunds,
        net_sales=gross - refunds,
        currency=currency,
    )


def calculate_product_sales(
    orders: list[SalesOrderState],
    *,
    warehouse_id: str,
    product_id: str,
    currency: str,
) -> ProductSalesSummary:

    units = 0
    gross = Decimal("0")

    for order in orders:

        if order.currency != currency:
            continue

        if order.status not in {
            SalesOrderStatus.PAID,
            SalesOrderStatus.FULFILLED,
            SalesOrderStatus.PARTIALLY_REFUNDED,
            SalesOrderStatus.REFUNDED,
        }:
            continue

        for line in order.lines:

            if line.product_id == product_id:
                units += line.quantity
                gross += line.total

    return ProductSalesSummary(
        product_id=product_id,
        warehouse_id=warehouse_id,
        units_ordered=units,
        gross_sales=gross,
        currency=currency,
    )


# ============================================================
# REALTIME DELIVERY
# ============================================================

async def publish_sales_event(
    record: SalesEventRecord,
) -> int:
    """
    Disabled until WebSocket delivery supports
    warehouse-scoped recipient authorization.

    Returns number of delivered connections.
    """
    return 0


async def publish_sales_alerts(
    alerts: list[SalesAlert],
) -> int:
    return 0


# ============================================================
# SERVICE
# ============================================================

class SalesStreamService:

    def __init__(
        self,
        store: SalesStreamStore,
    ):
        self.store = store

    async def consume_committed_event(
        self,
        *,
        tenant_id: str,
        payload: SalesEventCreate,
    ) -> tuple[
        SalesEventRecord,
        list[SalesAlert],
    ]:

        (
            record,
            current,
            previous,
            created,
        ) = await self.store.apply_committed_event(
            tenant_id=tenant_id,
            payload=payload,
        )

        if not created:
            return record, []

        alerts = detect_sales_alerts(
            previous,
            current,
        )

        await publish_sales_event(record)
        await publish_sales_alerts(alerts)

        return record, alerts


sales_stream = SalesStreamService(
    sales_store
)


# ============================================================
# API ROUTER
# ============================================================

router = APIRouter(
    prefix="/api/v1/sales-stream",
    tags=["Sales Stream"],
)


@router.get(
    "/orders/{order_id}",
    response_model=SalesOrderSnapshot,
)
async def get_sales_order(
    order_id: str,
    principal: CurrentPrincipal,
):

    state = await sales_store.get_snapshot(
        tenant_id=principal.tenant_id,
        order_id=order_id,
    )

    if state is None:
        raise HTTPException(
            status_code=404,
            detail="Sales order not found",
        )

    require_sales_access(
        principal,
        state.warehouse_id,
    )

    return to_snapshot(state)


@router.get(
    "/orders/{order_id}/history",
    response_model=list[SalesEventResponse],
)
async def get_sales_order_history(
    order_id: str,
    principal: CurrentPrincipal,
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
    ),
):

    state = await sales_store.get_snapshot(
        tenant_id=principal.tenant_id,
        order_id=order_id,
    )

    if state is None:
        raise HTTPException(
            status_code=404,
            detail="Sales order not found",
        )

    require_sales_access(
        principal,
        state.warehouse_id,
    )

    records = await sales_store.get_history(
        tenant_id=principal.tenant_id,
        order_id=order_id,
        limit=limit,
    )

    return [
        to_event_response(record)
        for record in records
    ]


@router.get(
    "/summary/{warehouse_id}",
    response_model=SalesSummary,
)
async def get_sales_summary(
    warehouse_id: str,
    principal: CurrentPrincipal,
    currency: str = Query(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    ),
):

    require_sales_access(
        principal,
        warehouse_id,
    )

    orders = await sales_store.list_orders(
        tenant_id=principal.tenant_id,
        warehouse_id=warehouse_id,
    )

    return calculate_sales_summary(
        orders,
        warehouse_id,
        currency,
    )


@router.get(
    "/products/{warehouse_id}/{product_id}",
    response_model=ProductSalesSummary,
)
async def get_product_sales_summary(
    warehouse_id: str,
    product_id: str,
    principal: CurrentPrincipal,
    currency: str = Query(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    ),
):

    require_sales_access(
        principal,
        warehouse_id,
    )

    orders = await sales_store.list_orders(
        tenant_id=principal.tenant_id,
        warehouse_id=warehouse_id,
    )

    return calculate_product_sales(
        orders,
        warehouse_id=warehouse_id,
        product_id=product_id,
        currency=currency,
    )
