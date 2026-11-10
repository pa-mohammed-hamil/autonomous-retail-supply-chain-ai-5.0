from __future__ import annotations

"""Planned module: logistics. Implementation pending."""

"""
backend/logistics.py

Autonomous Retail Supply Chain AI 5.0
Logistics & Shipment Management API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Shipment creation
    - Carrier and vehicle assignment
    - Shipment dispatch
    - In-transit tracking events
    - Delivery confirmation
    - Failed delivery reporting
    - Return-to-origin workflow
    - Shipment cancellation
    - ETA and delay monitoring
    - Tenant/warehouse authorization
    - Idempotent shipment creation
    - Optimistic concurrency
    - Logistics analytics

Limitations:
    - In-memory single-process prototype
    - No GPS tracking
    - No live carrier API calls
    - No automatic route optimization
    - No real-world dispatch
    - No authoritative delivery verification
    - No durable database or event outbox
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


API_PREFIX = "/api/v1/logistics"

MAX_SHIPMENTS_PER_TENANT = 100_000
MAX_EVENTS_PER_SHIPMENT = 200
MAX_IDEMPOTENCY_KEYS = 150_000
MAX_LIST_LIMIT = 200


# ============================================================
# ENUMS
# ============================================================

class ShipmentStatus(str, Enum):
    CREATED = "created"
    ASSIGNED = "assigned"
    DISPATCHED = "dispatched"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    DELIVERY_FAILED = "delivery_failed"
    RETURNING = "returning"
    RETURNED = "returned"
    CANCELLED = "cancelled"


class ShipmentPriority(str, Enum):
    STANDARD = "standard"
    EXPRESS = "express"
    CRITICAL = "critical"


class TransportMode(str, Enum):
    ROAD = "road"
    RAIL = "rail"
    AIR = "air"
    SEA = "sea"


class ShipmentEventType(str, Enum):
    CREATED = "created"
    ASSIGNED = "assigned"
    DISPATCHED = "dispatched"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    DELIVERY_FAILED = "delivery_failed"
    RETURNING = "returning"
    RETURNED = "returned"
    CANCELLED = "cancelled"
    LOCATION_UPDATED = "location_updated"
    ETA_UPDATED = "eta_updated"


ALLOWED_TRANSITIONS = {
    ShipmentStatus.CREATED: {
        ShipmentStatus.ASSIGNED,
        ShipmentStatus.CANCELLED,
    },
    ShipmentStatus.ASSIGNED: {
        ShipmentStatus.DISPATCHED,
        ShipmentStatus.CANCELLED,
    },
    ShipmentStatus.DISPATCHED: {
        ShipmentStatus.IN_TRANSIT,
        ShipmentStatus.RETURNING,
    },
    ShipmentStatus.IN_TRANSIT: {
        ShipmentStatus.OUT_FOR_DELIVERY,
        ShipmentStatus.RETURNING,
    },
    ShipmentStatus.OUT_FOR_DELIVERY: {
        ShipmentStatus.DELIVERED,
        ShipmentStatus.DELIVERY_FAILED,
        ShipmentStatus.RETURNING,
    },
    ShipmentStatus.DELIVERY_FAILED: {
        ShipmentStatus.OUT_FOR_DELIVERY,
        ShipmentStatus.RETURNING,
    },
    ShipmentStatus.RETURNING: {
        ShipmentStatus.RETURNED,
    },
    ShipmentStatus.DELIVERED: set(),
    ShipmentStatus.RETURNED: set(),
    ShipmentStatus.CANCELLED: set(),
}


# ============================================================
# REQUEST MODELS
# ============================================================

class ShipmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    order_id: str = Field(
        min_length=1,
        max_length=128,
    )

    destination_reference: str = Field(
        min_length=1,
        max_length=200,
    )

    priority: ShipmentPriority = (
        ShipmentPriority.STANDARD
    )

    transport_mode: TransportMode = (
        TransportMode.ROAD
    )

    weight_kg: float = Field(
        gt=0,
        le=100_000,
        allow_inf_nan=False,
    )

    expected_delivery_at: datetime | None = None

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_eta(self):

        if (
            self.expected_delivery_at is not None
            and self.expected_delivery_at.tzinfo is None
        ):
            raise ValueError(
                "Expected delivery timestamp must include timezone"
            )

        return self


class ShipmentAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    carrier_id: str = Field(
        min_length=1,
        max_length=128,
    )

    vehicle_id: str | None = Field(
        default=None,
        max_length=128,
    )

    tracking_number: str = Field(
        min_length=3,
        max_length=100,
    )

    expected_version: int = Field(ge=1)


class ShipmentVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class ShipmentLocationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    location_reference: str = Field(
        min_length=1,
        max_length=200,
    )


class ShipmentETAUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    expected_delivery_at: datetime

    @model_validator(mode="after")
    def validate_eta(self):

        if self.expected_delivery_at.tzinfo is None:
            raise ValueError(
                "ETA must include timezone"
            )

        return self


class ShipmentDeliveryProof(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    proof_reference_id: str = Field(
        min_length=1,
        max_length=200,
    )

    delivered_at: datetime

    @model_validator(mode="after")
    def validate_timestamp(self):

        if self.delivered_at.tzinfo is None:
            raise ValueError(
                "Delivery timestamp must include timezone"
            )

        return self


class ShipmentFailureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    reason_code: str = Field(
        min_length=3,
        max_length=100,
    )


# ============================================================
# RESPONSE MODELS
# ============================================================

class ShipmentEventResponse(BaseModel):
    event_id: str
    event_type: ShipmentEventType
    actor_id: str

    timestamp: datetime
    version: int

    detail: str | None = None


class ShipmentResponse(BaseModel):
    shipment_id: str
    warehouse_id: str
    order_id: str

    destination_reference: str

    priority: ShipmentPriority
    transport_mode: TransportMode

    weight_kg: float
    status: ShipmentStatus

    carrier_id: str | None
    vehicle_id: str | None
    tracking_number: str | None

    current_location_reference: str | None

    expected_delivery_at: datetime | None
    dispatched_at: datetime | None
    delivered_at: datetime | None

    proof_reference_id: str | None
    failure_reason_code: str | None

    version: int

    created_at: datetime
    updated_at: datetime


class ShipmentDetailResponse(ShipmentResponse):
    events: list[ShipmentEventResponse]


class LogisticsAnalyticsResponse(BaseModel):
    warehouse_id: str

    total_shipments: int
    created: int
    assigned: int
    dispatched: int
    in_transit: int
    out_for_delivery: int
    delivered: int
    delivery_failed: int
    returning: int
    returned: int
    cancelled: int

    delayed_open_shipments: int

    delivery_success_rate_percent: float
    on_time_delivery_rate_percent: float | None


# ============================================================
# INTERNAL RECORD
# ============================================================

@dataclass
class ShipmentRecord:
    shipment_id: str
    tenant_id: str
    warehouse_id: str

    order_id: str
    destination_reference: str

    priority: ShipmentPriority
    transport_mode: TransportMode
    weight_kg: float

    expected_delivery_at: datetime | None

    status: ShipmentStatus = (
        ShipmentStatus.CREATED
    )

    carrier_id: str | None = None
    vehicle_id: str | None = None
    tracking_number: str | None = None

    current_location_reference: str | None = None

    dispatched_at: datetime | None = None
    delivered_at: datetime | None = None

    proof_reference_id: str | None = None
    failure_reason_code: str | None = None

    version: int = 1

    events: list[
        ShipmentEventResponse
    ] = field(default_factory=list)

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
    payload: ShipmentCreate,
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


def require_logistics_access(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool,
) -> None:

    # LOGISTICS_WRITE must be defined
    # in backend.permissions.Permission.

    permission = (
        Permission.LOGISTICS_WRITE
        if write
        else Permission.LOGISTICS_READ
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
            detail="Logistics access denied",
        )


def to_response(
    record: ShipmentRecord,
) -> ShipmentResponse:

    return ShipmentResponse(
        shipment_id=record.shipment_id,
        warehouse_id=record.warehouse_id,
        order_id=record.order_id,
        destination_reference=record.destination_reference,
        priority=record.priority,
        transport_mode=record.transport_mode,
        weight_kg=record.weight_kg,
        status=record.status,
        carrier_id=record.carrier_id,
        vehicle_id=record.vehicle_id,
        tracking_number=record.tracking_number,
        current_location_reference=(
            record.current_location_reference
        ),
        expected_delivery_at=record.expected_delivery_at,
        dispatched_at=record.dispatched_at,
        delivered_at=record.delivered_at,
        proof_reference_id=record.proof_reference_id,
        failure_reason_code=record.failure_reason_code,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def to_detail(
    record: ShipmentRecord,
) -> ShipmentDetailResponse:

    return ShipmentDetailResponse(
        **to_response(record).model_dump(),
        events=[
            event.model_copy(deep=True)
            for event in record.events
        ],
    )


# ============================================================
# LOGISTICS STORE
# ============================================================

class LogisticsStore:

    def __init__(self):

        self._records: dict[
            str,
            ShipmentRecord,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    def _get(
        self,
        principal: Principal,
        shipment_id: str,
        *,
        write: bool,
    ) -> ShipmentRecord:

        record = self._records.get(
            shipment_id
        )

        if (
            record is None
            or record.tenant_id
            != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Shipment not found",
            )

        require_logistics_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    @staticmethod
    def _check_version(
        record: ShipmentRecord,
        expected_version: int,
    ) -> None:

        if record.version != expected_version:
            raise HTTPException(
                status_code=409,
                detail="Shipment version conflict",
            )

    @staticmethod
    def _ensure_event_capacity(
        record: ShipmentRecord,
    ) -> None:

        if len(record.events) >= MAX_EVENTS_PER_SHIPMENT:
            raise HTTPException(
                status_code=503,
                detail="Shipment event capacity reached",
            )

    @staticmethod
    def _append_event(
        record: ShipmentRecord,
        event_type: ShipmentEventType,
        actor_id: str,
        detail: str | None = None,
    ) -> None:

        record.events.append(
            ShipmentEventResponse(
                event_id=secrets.token_urlsafe(18),
                event_type=event_type,
                actor_id=actor_id,
                timestamp=utc_now(),
                version=record.version,
                detail=detail,
            )
        )

    @staticmethod
    def _transition(
        record: ShipmentRecord,
        new_status: ShipmentStatus,
        event_type: ShipmentEventType,
        actor_id: str,
        detail: str | None = None,
    ) -> None:

        if (
            new_status
            not in ALLOWED_TRANSITIONS[record.status]
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Invalid transition: "
                    f"{record.status.value} -> "
                    f"{new_status.value}"
                ),
            )

        LogisticsStore._ensure_event_capacity(
            record
        )

        record.status = new_status
        record.version += 1
        record.updated_at = utc_now()

        LogisticsStore._append_event(
            record,
            event_type,
            actor_id,
            detail,
        )

    async def create(
        self,
        *,
        principal: Principal,
        payload: ShipmentCreate,
    ) -> ShipmentResponse:

        require_logistics_access(
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

                old_hash, shipment_id = previous

                if old_hash != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return to_response(
                    self._get(
                        principal,
                        shipment_id,
                        write=False,
                    )
                )

            tenant_count = sum(
                record.tenant_id
                == principal.tenant_id
                for record in self._records.values()
            )

            if (
                tenant_count >= MAX_SHIPMENTS_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Shipment capacity reached",
                )

            record = ShipmentRecord(
                shipment_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                order_id=payload.order_id,
                destination_reference=(
                    payload.destination_reference
                ),
                priority=payload.priority,
                transport_mode=payload.transport_mode,
                weight_kg=payload.weight_kg,
                expected_delivery_at=(
                    payload.expected_delivery_at
                ),
            )

            self._append_event(
                record,
                ShipmentEventType.CREATED,
                principal.principal_id,
            )

            self._records[
                record.shipment_id
            ] = record

            self._idempotency[key] = (
                request_hash,
                record.shipment_id,
            )

            return to_response(record)

    async def get(
        self,
        *,
        principal: Principal,
        shipment_id: str,
    ) -> ShipmentDetailResponse:

        async with self._lock:

            return to_detail(
                self._get(
                    principal,
                    shipment_id,
                    write=False,
                )
            )

    async def list_records(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
        status: ShipmentStatus | None,
        limit: int,
    ) -> list[ShipmentResponse]:

        require_logistics_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._records.values()
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
                key=lambda item: item.created_at,
                reverse=True,
            )

            return [
                to_response(record)
                for record in records[:limit]
            ]

    async def assign(
        self,
        *,
        principal: Principal,
        shipment_id: str,
        payload: ShipmentAssignment,
    ) -> ShipmentDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                shipment_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status != ShipmentStatus.CREATED:
                raise HTTPException(
                    status_code=409,
                    detail="Shipment cannot be assigned",
                )

            self._ensure_event_capacity(record)

            # Carrier/vehicle ownership and capacity
            # must be verified by trusted services.

            record.carrier_id = payload.carrier_id
            record.vehicle_id = payload.vehicle_id
            record.tracking_number = (
                payload.tracking_number
            )

            self._transition(
                record,
                ShipmentStatus.ASSIGNED,
                ShipmentEventType.ASSIGNED,
                principal.principal_id,
            )

            return to_detail(record)

    async def update_status(
        self,
        *,
        principal: Principal,
        shipment_id: str,
        expected_version: int,
        new_status: ShipmentStatus,
    ) -> ShipmentDetailResponse:

        event_map = {
            ShipmentStatus.DISPATCHED:
                ShipmentEventType.DISPATCHED,
            ShipmentStatus.IN_TRANSIT:
                ShipmentEventType.IN_TRANSIT,
            ShipmentStatus.OUT_FOR_DELIVERY:
                ShipmentEventType.OUT_FOR_DELIVERY,
            ShipmentStatus.RETURNING:
                ShipmentEventType.RETURNING,
            ShipmentStatus.RETURNED:
                ShipmentEventType.RETURNED,
            ShipmentStatus.CANCELLED:
                ShipmentEventType.CANCELLED,
        }

        if new_status not in event_map:
            raise HTTPException(
                status_code=422,
                detail="Use dedicated endpoint for this status",
            )

        async with self._lock:

            record = self._get(
                principal,
                shipment_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            self._transition(
                record,
                new_status,
                event_map[new_status],
                principal.principal_id,
            )

            if new_status == ShipmentStatus.DISPATCHED:
                record.dispatched_at = utc_now()

            return to_detail(record)

    async def update_location(
        self,
        *,
        principal: Principal,
        shipment_id: str,
        payload: ShipmentLocationUpdate,
    ) -> ShipmentDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                shipment_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status not in {
                ShipmentStatus.DISPATCHED,
                ShipmentStatus.IN_TRANSIT,
                ShipmentStatus.OUT_FOR_DELIVERY,
                ShipmentStatus.RETURNING,
            }:
                raise HTTPException(
                    status_code=409,
                    detail="Shipment is not in transit",
                )

            self._ensure_event_capacity(record)

            record.current_location_reference = (
                payload.location_reference
            )

            record.version += 1
            record.updated_at = utc_now()

            self._append_event(
                record,
                ShipmentEventType.LOCATION_UPDATED,
                principal.principal_id,
                payload.location_reference,
            )

            return to_detail(record)

    async def update_eta(
        self,
        *,
        principal: Principal,
        shipment_id: str,
        payload: ShipmentETAUpdate,
    ) -> ShipmentDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                shipment_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status in {
                ShipmentStatus.DELIVERED,
                ShipmentStatus.RETURNED,
                ShipmentStatus.CANCELLED,
            }:
                raise HTTPException(
                    status_code=409,
                    detail="Terminal shipment cannot update ETA",
                )

            self._ensure_event_capacity(record)

            record.expected_delivery_at = (
                payload.expected_delivery_at
            )

            record.version += 1
            record.updated_at = utc_now()

            self._append_event(
                record,
                ShipmentEventType.ETA_UPDATED,
                principal.principal_id,
            )

            return to_detail(record)

    async def complete_delivery(
        self,
        *,
        principal: Principal,
        shipment_id: str,
        payload: ShipmentDeliveryProof,
    ) -> ShipmentDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                shipment_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if (
                record.status
                != ShipmentStatus.OUT_FOR_DELIVERY
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Shipment is not out for delivery",
                )

            if payload.delivered_at > utc_now():
                raise HTTPException(
                    status_code=422,
                    detail="Delivery timestamp is in the future",
                )

            if (
                record.dispatched_at is not None
                and payload.delivered_at
                < record.dispatched_at
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Delivery predates dispatch",
                )

            self._ensure_event_capacity(record)

            record.proof_reference_id = (
                payload.proof_reference_id
            )

            record.delivered_at = (
                payload.delivered_at
            )

            self._transition(
                record,
                ShipmentStatus.DELIVERED,
                ShipmentEventType.DELIVERED,
                principal.principal_id,
            )

            return to_detail(record)

    async def record_failure(
        self,
        *,
        principal: Principal,
        shipment_id: str,
        payload: ShipmentFailureRequest,
    ) -> ShipmentDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                shipment_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._ensure_event_capacity(record)

            if (
                ShipmentStatus.DELIVERY_FAILED
                not in ALLOWED_TRANSITIONS[record.status]
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Delivery failure not allowed",
                )

            record.failure_reason_code = (
                payload.reason_code
            )

            self._transition(
                record,
                ShipmentStatus.DELIVERY_FAILED,
                ShipmentEventType.DELIVERY_FAILED,
                principal.principal_id,
                payload.reason_code,
            )

            return to_detail(record)

    async def analytics(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
    ) -> LogisticsAnalyticsResponse:

        require_logistics_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._records.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and record.warehouse_id
                    == warehouse_id
                )
            ]

            counts = {
                status: sum(
                    record.status == status
                    for record in records
                )
                for status in ShipmentStatus
            }

            now = utc_now()

            delayed = sum(
                (
                    record.expected_delivery_at is not None
                    and record.expected_delivery_at < now
                    and record.status not in {
                        ShipmentStatus.DELIVERED,
                        ShipmentStatus.RETURNED,
                        ShipmentStatus.CANCELLED,
                    }
                )
                for record in records
            )

            delivered = [
                record
                for record in records
                if record.status == ShipmentStatus.DELIVERED
            ]

            on_time = [
                record
                for record in delivered
                if (
                    record.expected_delivery_at is not None
                    and record.delivered_at is not None
                    and record.delivered_at
                    <= record.expected_delivery_at
                )
            ]

            eligible = [
                record
                for record in delivered
                if record.expected_delivery_at is not None
            ]

            total = len(records)

            return LogisticsAnalyticsResponse(
                warehouse_id=warehouse_id,
                total_shipments=total,
                created=counts[ShipmentStatus.CREATED],
                assigned=counts[ShipmentStatus.ASSIGNED],
                dispatched=counts[ShipmentStatus.DISPATCHED],
                in_transit=counts[ShipmentStatus.IN_TRANSIT],
                out_for_delivery=counts[
                    ShipmentStatus.OUT_FOR_DELIVERY
                ],
                delivered=counts[ShipmentStatus.DELIVERED],
                delivery_failed=counts[
                    ShipmentStatus.DELIVERY_FAILED
                ],
                returning=counts[ShipmentStatus.RETURNING],
                returned=counts[ShipmentStatus.RETURNED],
                cancelled=counts[ShipmentStatus.CANCELLED],
                delayed_open_shipments=delayed,
                delivery_success_rate_percent=(
                    round(len(delivered) / total * 100, 2)
                    if total
                    else 0.0
                ),
                on_time_delivery_rate_percent=(
                    round(
                        len(on_time) / len(eligible) * 100,
                        2,
                    )
                    if eligible
                    else None
                ),
            )


logistics_store = LogisticsStore()


# ============================================================
# SERVICE
# ============================================================

class LogisticsService:

    def __init__(
        self,
        store: LogisticsStore,
    ):
        self.store = store

    async def create(
        self,
        principal: Principal,
        payload: ShipmentCreate,
    ) -> ShipmentResponse:

        return await self.store.create(
            principal=principal,
            payload=payload,
        )

    async def deliver(
        self,
        principal: Principal,
        shipment_id: str,
        payload: ShipmentDeliveryProof,
    ) -> ShipmentDetailResponse:

        return await self.store.complete_delivery(
            principal=principal,
            shipment_id=shipment_id,
            payload=payload,
        )


logistics_service = LogisticsService(
    logistics_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Logistics Management"],
)


@router.post(
    "",
    response_model=ShipmentResponse,
    status_code=201,
)
async def create_shipment(
    payload: ShipmentCreate,
    principal: CurrentPrincipal,
):
    return await logistics_service.create(
        principal,
        payload,
    )


@router.get(
    "",
    response_model=list[ShipmentResponse],
)
async def list_shipments(
    principal: CurrentPrincipal,
    warehouse_id: str,
    status: ShipmentStatus | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await logistics_store.list_records(
        principal=principal,
        warehouse_id=warehouse_id,
        status=status,
        limit=limit,
    )


@router.get(
    "/analytics/{warehouse_id}",
    response_model=LogisticsAnalyticsResponse,
)
async def logistics_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
):
    return await logistics_store.analytics(
        principal=principal,
        warehouse_id=warehouse_id,
    )


@router.get(
    "/{shipment_id}",
    response_model=ShipmentDetailResponse,
)
async def get_shipment(
    shipment_id: str,
    principal: CurrentPrincipal,
):
    return await logistics_store.get(
        principal=principal,
        shipment_id=shipment_id,
    )


@router.post(
    "/{shipment_id}/assign",
    response_model=ShipmentDetailResponse,
)
async def assign_shipment(
    shipment_id: str,
    payload: ShipmentAssignment,
    principal: CurrentPrincipal,
):
    return await logistics_store.assign(
        principal=principal,
        shipment_id=shipment_id,
        payload=payload,
    )


@router.post(
    "/{shipment_id}/dispatch",
    response_model=ShipmentDetailResponse,
)
async def dispatch_shipment(
    shipment_id: str,
    principal: CurrentPrincipal,
    expected_version: int = Query(ge=1),
):
    return await logistics_store.update_status(
        principal=principal,
        shipment_id=shipment_id,
        expected_version=expected_version,
        new_status=ShipmentStatus.DISPATCHED,
    )


@router.post(
    "/{shipment_id}/in-transit",
    response_model=ShipmentDetailResponse,
)
async def mark_shipment_in_transit(
    shipment_id: str,
    principal: CurrentPrincipal,
    expected_version: int = Query(ge=1),
):
    return await logistics_store.update_status(
        principal=principal,
        shipment_id=shipment_id,
        expected_version=expected_version,
        new_status=ShipmentStatus.IN_TRANSIT,
    )


@router.post(
    "/{shipment_id}/out-for-delivery",
    response_model=ShipmentDetailResponse,
)
async def mark_out_for_delivery(
    shipment_id: str,
    principal: CurrentPrincipal,
    expected_version: int = Query(ge=1),
):
    return await logistics_store.update_status(
        principal=principal,
        shipment_id=shipment_id,
        expected_version=expected_version,
        new_status=ShipmentStatus.OUT_FOR_DELIVERY,
    )


@router.post(
    "/{shipment_id}/deliver",
    response_model=ShipmentDetailResponse,
)
async def deliver_shipment(
    shipment_id: str,
    payload: ShipmentDeliveryProof,
    principal: CurrentPrincipal,
):
    return await logistics_service.deliver(
        principal,
        shipment_id,
        payload,
    )


@router.post(
    "/{shipment_id}/failure",
    response_model=ShipmentDetailResponse,
)
async def record_delivery_failure(
    shipment_id: str,
    payload: ShipmentFailureRequest,
    principal: CurrentPrincipal,
):
    return await logistics_store.record_failure(
        principal=principal,
        shipment_id=shipment_id,
        payload=payload,
    )


@router.post(
    "/{shipment_id}/return",
    response_model=ShipmentDetailResponse,
)
async def return_shipment(
    shipment_id: str,
    principal: CurrentPrincipal,
    expected_version: int = Query(ge=1),
):
    return await logistics_store.update_status(
        principal=principal,
        shipment_id=shipment_id,
        expected_version=expected_version,
        new_status=ShipmentStatus.RETURNING,
    )


@router.post(
    "/{shipment_id}/returned",
    response_model=ShipmentDetailResponse,
)
async def mark_shipment_returned(
    shipment_id: str,
    principal: CurrentPrincipal,
    expected_version: int = Query(ge=1),
):
    return await logistics_store.update_status(
        principal=principal,
        shipment_id=shipment_id,
        expected_version=expected_version,
        new_status=ShipmentStatus.RETURNED,
    )


@router.post(
    "/{shipment_id}/cancel",
    response_model=ShipmentDetailResponse,
)
async def cancel_shipment(
    shipment_id: str,
    principal: CurrentPrincipal,
    expected_version: int = Query(ge=1),
):
    return await logistics_store.update_status(
        principal=principal,
        shipment_id=shipment_id,
        expected_version=expected_version,
        new_status=ShipmentStatus.CANCELLED,
    )


@router.post(
    "/{shipment_id}/location",
    response_model=ShipmentDetailResponse,
)
async def update_shipment_location(
    shipment_id: str,
    payload: ShipmentLocationUpdate,
    principal: CurrentPrincipal,
):
    return await logistics_store.update_location(
        principal=principal,
        shipment_id=shipment_id,
        payload=payload,
    )


@router.post(
    "/{shipment_id}/eta",
    response_model=ShipmentDetailResponse,
)
async def update_shipment_eta(
    shipment_id: str,
    payload: ShipmentETAUpdate,
    principal: CurrentPrincipal,
):
    return await logistics_store.update_eta(
        principal=principal,
        shipment_id=shipment_id,
        payload=payload,
    )


__all__ = [
    "ShipmentStatus",
    "ShipmentPriority",
    "TransportMode",
    "ShipmentEventType",
    "ShipmentCreate",
    "ShipmentAssignment",
    "ShipmentVersionRequest",
    "ShipmentLocationUpdate",
    "ShipmentETAUpdate",
    "ShipmentDeliveryProof",
    "ShipmentFailureRequest",
    "ShipmentEventResponse",
    "ShipmentResponse",
    "ShipmentDetailResponse",
    "LogisticsAnalyticsResponse",
    "LogisticsStore",
    "LogisticsService",
    "logistics_store",
    "logistics_service",
    "router",
]
