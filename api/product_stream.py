from __future__ import annotations

"""Planned module: product stream. Implementation pending."""

"""
backend/product_stream.py

Autonomous Retail Supply Chain AI 5.0

Product catalog monitoring and event projections.

Python 3.10+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Product creation and updates
    - Product lifecycle monitoring
    - Price change detection
    - Availability changes
    - Quality holds and recalls
    - Product status alerts
    - Tenant-isolated event processing
    - Warehouse-scoped authorization
    - Idempotent event ingestion
    - Optimistic version validation
    - Bounded event history
    - Read-only product stream API

Architecture:
    ProductService + PostgreSQL
                |
        Committed outbox event
                |
          ProductStream
                |
       Product projections
                |
        Authorized API

Important:
    This is not the authoritative
    product database.

    Only trusted internal services may
    submit committed product events.

    Resource-specific WebSocket delivery
    remains disabled until secure
    per-recipient routing is available.
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
from typing import Any

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


# ============================================================
# CONFIGURATION
# ============================================================

MAX_HISTORY_PER_PRODUCT = 500

MAX_PRODUCTS_PER_TENANT = 10000

MAX_IDEMPOTENCY_RECORDS = 20000

MAX_PRICE = Decimal("999999999.99")

PRICE_CHANGE_ALERT_RATIO = Decimal("0.20")


# ============================================================
# ENUMS
# ============================================================

class ProductEventType(str, Enum):

    CREATED = "product_created"
    UPDATED = "product_updated"

    PRICE_UPDATED = "price_updated"

    AVAILABILITY_UPDATED = (
        "availability_updated"
    )

    QUALITY_HOLD = "quality_hold"

    QUALITY_RELEASED = (
        "quality_released"
    )

    RECALLED = "product_recalled"

    DISCONTINUED = (
        "product_discontinued"
    )

    REACTIVATED = "product_reactivated"


class ProductStatus(str, Enum):

    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"
    DISCONTINUED = "discontinued"
    RECALLED = "recalled"


class ProductAvailability(str, Enum):

    AVAILABLE = "available"
    LIMITED = "limited"
    UNAVAILABLE = "unavailable"


class ProductAlertType(str, Enum):

    LARGE_PRICE_CHANGE = (
        "large_price_change"
    )

    PRODUCT_UNAVAILABLE = (
        "product_unavailable"
    )

    QUALITY_HOLD = "quality_hold"

    PRODUCT_RECALL = "product_recall"

    PRODUCT_DISCONTINUED = (
        "product_discontinued"
    )


class ProductAlertSeverity(str, Enum):

    INFO = "info"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ============================================================
# STATUS TRANSITIONS
# ============================================================

ALLOWED_STATUS_TRANSITIONS = {

    ProductStatus.DRAFT: {
        ProductStatus.ACTIVE,
        ProductStatus.INACTIVE,
        ProductStatus.DISCONTINUED,
        ProductStatus.RECALLED,
    },

    ProductStatus.ACTIVE: {
        ProductStatus.INACTIVE,
        ProductStatus.DISCONTINUED,
        ProductStatus.RECALLED,
    },

    ProductStatus.INACTIVE: {
        ProductStatus.ACTIVE,
        ProductStatus.DISCONTINUED,
        ProductStatus.RECALLED,
    },

    ProductStatus.DISCONTINUED: set(),

    ProductStatus.RECALLED: set(),
}


# ============================================================
# EVENT SCHEMA
# ============================================================

class ProductEventCreate(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    warehouse_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    event_type: ProductEventType

    product_version: int = Field(
        ge=1,
    )

    source_event_id: str = Field(
        min_length=8,
        max_length=128,
    )

    name: str = Field(
        min_length=1,
        max_length=200,
    )

    sku: str = Field(
        min_length=1,
        max_length=100,
    )

    category: str = Field(
        min_length=1,
        max_length=100,
    )

    status: ProductStatus

    availability: ProductAvailability

    price: Decimal = Field(
        ge=0,
        le=MAX_PRICE,
        max_digits=11,
        decimal_places=2,
    )

    currency: str = Field(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    )

    quality_hold: bool = False

    occurred_at: datetime

    @model_validator(mode="after")
    def validate_event(self):

        if self.occurred_at.tzinfo is None:
            raise ValueError(
                "occurred_at must include timezone"
            )

        if (
            self.status == ProductStatus.RECALLED
            and self.availability
            != ProductAvailability.UNAVAILABLE
        ):
            raise ValueError(
                "Recalled products must be "
                "unavailable"
            )

        if (
            self.quality_hold
            and self.availability
            != ProductAvailability.UNAVAILABLE
        ):
            raise ValueError(
                "Products on quality hold "
                "must be unavailable"
            )

        if (
            self.status in {
                ProductStatus.INACTIVE,
                ProductStatus.DISCONTINUED,
            }
            and self.availability
            != ProductAvailability.UNAVAILABLE
        ):
            raise ValueError(
                "Inactive or discontinued "
                "products must be unavailable"
            )

        return self


# ============================================================
# RESPONSE SCHEMAS
# ============================================================

class ProductEventResponse(BaseModel):

    event_id: str

    product_id: str
    warehouse_id: str | None

    event_type: ProductEventType
    product_version: int

    status: ProductStatus
    availability: ProductAvailability

    price: Decimal
    currency: str

    occurred_at: datetime
    received_at: datetime


class ProductSnapshot(BaseModel):

    product_id: str
    warehouse_id: str | None

    name: str
    sku: str
    category: str

    status: ProductStatus
    availability: ProductAvailability

    price: Decimal
    currency: str

    quality_hold: bool

    product_version: int

    last_updated: datetime


class ProductAlert(BaseModel):

    alert_id: str

    product_id: str
    warehouse_id: str | None

    alert_type: ProductAlertType
    severity: ProductAlertSeverity

    message: str

    product_version: int

    created_at: datetime


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass(frozen=True)
class ProductEventRecord:

    event_id: str
    tenant_id: str

    product_id: str
    warehouse_id: str | None

    event_type: ProductEventType

    product_version: int

    source_event_id: str
    payload_fingerprint: str

    name: str
    sku: str
    category: str

    status: ProductStatus
    availability: ProductAvailability

    price: Decimal
    currency: str

    quality_hold: bool

    occurred_at: datetime
    received_at: datetime


@dataclass(frozen=True)
class ProductState:

    tenant_id: str

    product_id: str
    warehouse_id: str | None

    name: str
    sku: str
    category: str

    status: ProductStatus
    availability: ProductAvailability

    price: Decimal
    currency: str

    quality_hold: bool

    product_version: int

    last_updated: datetime


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:

    return datetime.now(timezone.utc)


def product_key(
    tenant_id: str,
    product_id: str,
    warehouse_id: str | None,
) -> tuple[str, str, str | None]:

    return (
        tenant_id,
        product_id,
        warehouse_id,
    )


def fingerprint_event(
    payload: ProductEventCreate,
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


def to_snapshot(
    state: ProductState,
) -> ProductSnapshot:

    return ProductSnapshot(
        product_id=state.product_id,
        warehouse_id=state.warehouse_id,
        name=state.name,
        sku=state.sku,
        category=state.category,
        status=state.status,
        availability=state.availability,
        price=state.price,
        currency=state.currency,
        quality_hold=state.quality_hold,
        product_version=state.product_version,
        last_updated=state.last_updated,
    )


def to_event_response(
    record: ProductEventRecord,
) -> ProductEventResponse:

    return ProductEventResponse(
        event_id=record.event_id,
        product_id=record.product_id,
        warehouse_id=record.warehouse_id,
        event_type=record.event_type,
        product_version=record.product_version,
        status=record.status,
        availability=record.availability,
        price=record.price,
        currency=record.currency,
        occurred_at=record.occurred_at,
        received_at=record.received_at,
    )


# ============================================================
# AUTHORIZATION
# ============================================================

def require_product_access(
    principal: Principal,
    warehouse_id: str | None,
) -> None:

    resource = ResourceContext(
        tenant_id=principal.tenant_id,
        warehouse_id=warehouse_id,
    )

    decision = permission_engine.evaluate(
        principal,
        Permission.PRODUCT_READ,
        resource,
    )

    if not decision.allowed:

        raise HTTPException(
            status_code=403,
            detail="Product access denied",
        )

    allowed = principal.allowed_warehouse_ids

    if (
        warehouse_id is not None
        and allowed is not None
        and warehouse_id not in allowed
    ):

        raise HTTPException(
            status_code=403,
            detail="Warehouse access denied",
        )


# ============================================================
# ALERT DETECTION
# ============================================================

def detect_product_alerts(
    previous: ProductState | None,
    current: ProductState,
    event_type: ProductEventType,
) -> list[ProductAlert]:

    alerts: list[ProductAlert] = []

    def add_alert(
        alert_type: ProductAlertType,
        severity: ProductAlertSeverity,
        message: str,
    ) -> None:

        alerts.append(
            ProductAlert(
                alert_id=secrets.token_urlsafe(16),
                product_id=current.product_id,
                warehouse_id=current.warehouse_id,
                alert_type=alert_type,
                severity=severity,
                message=message,
                product_version=(
                    current.product_version
                ),
                created_at=utc_now(),
            )
        )

    if previous is not None:

        if previous.price > 0:

            change_ratio = (
                abs(
                    current.price
                    - previous.price
                )
                / previous.price
            )

            if (
                change_ratio
                >= PRICE_CHANGE_ALERT_RATIO
            ):

                add_alert(
                    ProductAlertType.LARGE_PRICE_CHANGE,
                    ProductAlertSeverity.MEDIUM,
                    "A significant product "
                    "price change was detected.",
                )

        if (
            previous.availability
            != ProductAvailability.UNAVAILABLE
            and current.availability
            == ProductAvailability.UNAVAILABLE
        ):

            add_alert(
                ProductAlertType.PRODUCT_UNAVAILABLE,
                ProductAlertSeverity.HIGH,
                "Product became unavailable.",
            )

        if (
            not previous.quality_hold
            and current.quality_hold
        ):

            add_alert(
                ProductAlertType.QUALITY_HOLD,
                ProductAlertSeverity.HIGH,
                "Product was placed "
                "on quality hold.",
            )

    if (
        current.status == ProductStatus.RECALLED
        and (
            previous is None
            or previous.status
            != ProductStatus.RECALLED
        )
    ):

        add_alert(
            ProductAlertType.PRODUCT_RECALL,
            ProductAlertSeverity.CRITICAL,
            "Product recall was recorded.",
        )

    if (
        current.status == ProductStatus.DISCONTINUED
        and (
            previous is None
            or previous.status
            != ProductStatus.DISCONTINUED
        )
    ):

        add_alert(
            ProductAlertType.PRODUCT_DISCONTINUED,
            ProductAlertSeverity.MEDIUM,
            "Product was discontinued.",
        )

    return alerts


# ============================================================
# PRODUCT STREAM STORE
# ============================================================

class ProductStreamStore:

    def __init__(self):

        self._states: dict[
            tuple[str, str, str | None],
            ProductState,
        ] = {}

        self._history: dict[
            tuple[str, str, str | None],
            deque[ProductEventRecord],
        ] = defaultdict(
            lambda: deque(
                maxlen=MAX_HISTORY_PER_PRODUCT
            )
        )

        self._idempotency: dict[
            tuple[str, str],
            tuple[
                tuple[str, str, str | None],
                str,
                str,
            ],
        ] = {}

        self._lock = asyncio.Lock()

    async def apply_committed_event(
        self,
        *,
        tenant_id: str,
        payload: ProductEventCreate,
    ) -> tuple[
        ProductEventRecord,
        ProductState,
        ProductState | None,
        bool,
    ]:

        key = product_key(
            tenant_id,
            payload.product_id,
            payload.warehouse_id,
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
                    existing_key,
                    existing_id,
                    existing_fingerprint,
                ) = existing

                if (
                    existing_fingerprint
                    != fingerprint
                ):

                    raise ValueError(
                        "Idempotency conflict"
                    )

                for record in self._history.get(
                    existing_key,
                    (),
                ):

                    if record.event_id == existing_id:

                        return (
                            record,
                            self._states[existing_key],
                            None,
                            False,
                        )

                raise ValueError(
                    "Previously processed event "
                    "is no longer retained"
                )

            previous = self._states.get(
                key
            )

            if previous is not None:

                if (
                    payload.product_version
                    != previous.product_version + 1
                ):

                    raise ValueError(
                        "Product version gap"
                    )

                if (
                    payload.status
                    != previous.status
                ):

                    allowed = (
                        ALLOWED_STATUS_TRANSITIONS.get(
                            previous.status,
                            set(),
                        )
                    )

                    if payload.status not in allowed:

                        raise ValueError(
                            "Invalid product "
                            "status transition"
                        )

            elif (
                len(
                    [
                        state
                        for state in self._states.values()
                        if state.tenant_id == tenant_id
                    ]
                )
                >= MAX_PRODUCTS_PER_TENANT
            ):

                raise ValueError(
                    "Product stream capacity reached"
                )

            received_at = utc_now()

            record = ProductEventRecord(
                event_id=secrets.token_urlsafe(20),
                tenant_id=tenant_id,
                product_id=payload.product_id,
                warehouse_id=payload.warehouse_id,
                event_type=payload.event_type,
                product_version=(
                    payload.product_version
                ),
                source_event_id=(
                    payload.source_event_id
                ),
                payload_fingerprint=fingerprint,
                name=payload.name,
                sku=payload.sku,
                category=payload.category,
                status=payload.status,
                availability=payload.availability,
                price=payload.price,
                currency=payload.currency,
                quality_hold=payload.quality_hold,
                occurred_at=payload.occurred_at,
                received_at=received_at,
            )

            state = ProductState(
                tenant_id=tenant_id,
                product_id=payload.product_id,
                warehouse_id=payload.warehouse_id,
                name=payload.name,
                sku=payload.sku,
                category=payload.category,
                status=payload.status,
                availability=payload.availability,
                price=payload.price,
                currency=payload.currency,
                quality_hold=payload.quality_hold,
                product_version=(
                    payload.product_version
                ),
                last_updated=received_at,
            )

            self._states[key] = state

            self._history[key].append(
                record
            )

            if (
                len(self._idempotency)
                >= MAX_IDEMPOTENCY_RECORDS
            ):

                oldest_key = next(
                    iter(self._idempotency)
                )

                self._idempotency.pop(
                    oldest_key,
                    None,
                )

            self._idempotency[
                idempotency_key
            ] = (
                key,
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
        product_id: str,
        warehouse_id: str | None = None,
    ) -> ProductState | None:

        key = product_key(
            tenant_id,
            product_id,
            warehouse_id,
        )

        async with self._lock:

            return self._states.get(
                key
            )

    async def get_history(
        self,
        *,
        tenant_id: str,
        product_id: str,
        warehouse_id: str | None = None,
        limit: int = 50,
    ) -> list[ProductEventRecord]:

        key = product_key(
            tenant_id,
            product_id,
            warehouse_id,
        )

        async with self._lock:

            records = list(
                self._history.get(
                    key,
                    (),
                )
            )

        return list(
            reversed(
                records[-limit:]
            )
        )


product_store = ProductStreamStore()


# ============================================================
# REALTIME DELIVERY
# ============================================================

async def publish_product_event(
    record: ProductEventRecord,
) -> int:
    """
    Secure WebSocket delivery is disabled
    until per-recipient product and warehouse
    authorization is implemented.

    Returns zero delivered connections.
    """

    return 0


async def publish_product_alerts(
    state: ProductState,
    alerts: list[ProductAlert],
) -> int:

    return 0


# ============================================================
# SERVICE
# ============================================================

class ProductStreamService:

    def __init__(
        self,
        store: ProductStreamStore,
    ):

        self.store = store

    async def consume_committed_event(
        self,
        *,
        tenant_id: str,
        payload: ProductEventCreate,
    ) -> tuple[
        ProductEventRecord,
        list[ProductAlert],
    ]:
        """
        Internal-only committed event
        consumption.

        Call after product_service commits
        the authoritative transaction.
        """

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

        alerts = detect_product_alerts(
            previous,
            current,
            payload.event_type,
        )

        await publish_product_event(
            record
        )

        await publish_product_alerts(
            current,
            alerts,
        )

        return record, alerts


product_stream = ProductStreamService(
    product_store
)


# ============================================================
# API ROUTER
# ============================================================

router = APIRouter(
    prefix="/api/v1/product-stream",
    tags=["Product Stream"],
)


@router.get(
    "/snapshot/{product_id}",
    response_model=ProductSnapshot,
)
async def get_product_snapshot(
    product_id: str,
    principal: CurrentPrincipal,
    warehouse_id: str | None = None,
):

    require_product_access(
        principal,
        warehouse_id,
    )

    state = await product_store.get_snapshot(
        tenant_id=principal.tenant_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
    )

    if state is None:

        raise HTTPException(
            status_code=404,
            detail="Product snapshot not found",
        )

    return to_snapshot(
        state
    )


@router.get(
    "/history/{product_id}",
    response_model=list[
        ProductEventResponse
    ],
)
async def get_product_history(
    product_id: str,
    principal: CurrentPrincipal,
    warehouse_id: str | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
    ),
):

    require_product_access(
        principal,
        warehouse_id,
    )

    records = await product_store.get_history(
        tenant_id=principal.tenant_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
        limit=limit,
    )

    return [
        to_event_response(record)
        for record in records
    ]


@router.get(
    "/alerts/{product_id}",
    response_model=list[ProductAlert],
)
async def get_product_alerts(
    product_id: str,
    principal: CurrentPrincipal,
    warehouse_id: str | None = None,
):

    require_product_access(
        principal,
        warehouse_id,
    )

    state = await product_store.get_snapshot(
        tenant_id=principal.tenant_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
    )

    if state is None:

        raise HTTPException(
            status_code=404,
            detail="Product snapshot not found",
        )

    # Current-state alerts only.
    # Historical alerts should be stored
    # separately in a durable alert service.

    return detect_product_alerts(
        None,
        state,
        ProductEventType.UPDATED,
    )
