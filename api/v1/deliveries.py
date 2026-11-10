from __future__ import annotations

"""Planned module: deliveries. Implementation pending."""

"""
backend/deliveries.py

Autonomous Retail Supply Chain AI 5.0
Delivery Management and Tracking API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Create outbound delivery records
    - Assign delivery carrier and tracking number
    - Dispatch shipments
    - Track delivery status
    - Record delivery attempts
    - Proof-of-delivery references
    - Failed delivery management
    - Return-to-origin tracking
    - Delivery performance analytics
    - Tenant and warehouse isolation
    - Optimistic concurrency
    - Idempotent commands
    - Event history
    - In-memory prototype

SECURITY:
    - Authenticated API access
    - Warehouse-scoped authorization
    - No public unauthenticated tracking endpoint
    - No raw recipient personal data in responses
    - Proof-of-delivery files are not exposed
    - External carrier events require trusted ingestion

IMPORTANT:
    This module does not:
      - Book a real carrier shipment
      - Send notifications
      - Update inventory balances
      - Charge or refund customers
      - Execute return logistics automatically

    Integrate those operations through
    trusted services and transactional outbox.
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


# ============================================================
# CONFIGURATION
# ============================================================

API_PREFIX = "/api/v1/deliveries"

MAX_DELIVERIES_PER_TENANT = 20_000
MAX_EVENTS_PER_DELIVERY = 100
MAX_IDEMPOTENCY_KEYS = 100_000
MAX_LIST_LIMIT = 200


# ============================================================
# ENUMS
# ============================================================

class DeliveryStatus(str, Enum):
    CREATED = "created"
    ASSIGNED = "assigned"
    DISPATCHED = "dispatched"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETURNING = "returning"
    RETURNED = "returned"
    CANCELLED = "cancelled"


class DeliveryPriority(str, Enum):
    STANDARD = "standard"
    EXPRESS = "express"
    CRITICAL = "critical"


class DeliveryEventType(str, Enum):
    CREATED = "created"
    ASSIGNED = "assigned"
    DISPATCHED = "dispatched"
    STATUS_CHANGED = "status_changed"
    ATTEMPT_FAILED = "attempt_failed"
    DELIVERED = "delivered"
    RETURN_INITIATED = "return_initiated"
    RETURN_COMPLETED = "return_completed"
    CANCELLED = "cancelled"


# ============================================================
# STATE TRANSITIONS
# ============================================================

ALLOWED_TRANSITIONS = {
    DeliveryStatus.CREATED: {
        DeliveryStatus.ASSIGNED,
        DeliveryStatus.CANCELLED,
    },
    DeliveryStatus.ASSIGNED: {
        DeliveryStatus.DISPATCHED,
        DeliveryStatus.CANCELLED,
    },
    DeliveryStatus.DISPATCHED: {
        DeliveryStatus.IN_TRANSIT,
        DeliveryStatus.RETURNING,
    },
    DeliveryStatus.IN_TRANSIT: {
        DeliveryStatus.OUT_FOR_DELIVERY,
        DeliveryStatus.RETURNING,
    },
    DeliveryStatus.OUT_FOR_DELIVERY: {
        DeliveryStatus.DELIVERED,
        DeliveryStatus.FAILED,
        DeliveryStatus.RETURNING,
    },
    DeliveryStatus.FAILED: {
        DeliveryStatus.OUT_FOR_DELIVERY,
        DeliveryStatus.RETURNING,
    },
    DeliveryStatus.RETURNING: {
        DeliveryStatus.RETURNED,
    },
    DeliveryStatus.DELIVERED: set(),
    DeliveryStatus.RETURNED: set(),
    DeliveryStatus.CANCELLED: set(),
}


# ============================================================
# REQUEST MODELS
# ============================================================

class DeliveryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    order_id: str = Field(
        min_length=1,
        max_length=128,
    )

    destination_reference_id: str = Field(
        min_length=1,
        max_length=128,
    )

    priority: DeliveryPriority = (
        DeliveryPriority.STANDARD
    )

    expected_delivery_at: datetime | None = None

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )


class DeliveryAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    carrier_id: str = Field(
        min_length=1,
        max_length=128,
    )

    tracking_number: str = Field(
        min_length=1,
        max_length=128,
    )

    expected_version: int = Field(ge=1)

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )


class DeliveryStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: DeliveryStatus

    expected_version: int = Field(ge=1)

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    location_reference: str | None = Field(
        default=None,
        max_length=128,
    )

    reason_code: str | None = Field(
        default=None,
        max_length=100,
    )


class DeliveryProof(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    proof_reference_id: str = Field(
        min_length=1,
        max_length=128,
    )

    delivered_at: datetime

    @model_validator(mode="after")
    def validate_timestamp(self):

        if self.delivered_at.tzinfo is None:
            raise ValueError(
                "delivered_at must include a timezone"
            )

        return self


class DeliveryFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    reason_code: str = Field(
        min_length=1,
        max_length=100,
    )


# ============================================================
# RESPONSE MODELS
# ============================================================

class DeliveryEventResponse(BaseModel):
    event_id: str
    delivery_id: str

    event_type: DeliveryEventType
    status: DeliveryStatus

    actor_id: str

    location_reference: str | None
    reason_code: str | None

    timestamp: datetime
    version: int


class DeliveryResponse(BaseModel):
    delivery_id: str
    warehouse_id: str
    order_id: str

    destination_reference_id: str

    priority: DeliveryPriority
    status: DeliveryStatus

    carrier_id: str | None
    tracking_number: str | None

    expected_delivery_at: datetime | None
    dispatched_at: datetime | None
    delivered_at: datetime | None

    proof_reference_id: str | None

    failed_attempts: int

    version: int

    created_at: datetime
    updated_at: datetime


class DeliveryDetailResponse(DeliveryResponse):
    events: list[DeliveryEventResponse]


class DeliveryAnalyticsResponse(BaseModel):
    warehouse_id: str
    total_deliveries: int
    delivered: int
    in_transit: int
    failed: int
    returned: int
    cancelled: int
    on_time_deliveries: int
    late_deliveries: int
    on_time_delivery_rate: float | None


# ============================================================
# INTERNAL RECORD
# ============================================================

@dataclass
class DeliveryRecord:
    delivery_id: str

    tenant_id: str
    warehouse_id: str

    order_id: str
    destination_reference_id: str

    priority: DeliveryPriority

    expected_delivery_at: datetime | None

    status: DeliveryStatus = (
        DeliveryStatus.CREATED
    )

    carrier_id: str | None = None
    tracking_number: str | None = None

    dispatched_at: datetime | None = None
    delivered_at: datetime | None = None

    proof_reference_id: str | None = None

    failed_attempts: int = 0

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

    events: list[DeliveryEventResponse] = field(
        default_factory=list
    )


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


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


def to_response(
    record: DeliveryRecord,
) -> DeliveryResponse:

    return DeliveryResponse(
        delivery_id=record.delivery_id,
        warehouse_id=record.warehouse_id,
        order_id=record.order_id,
        destination_reference_id=(
            record.destination_reference_id
        ),
        priority=record.priority,
        status=record.status,
        carrier_id=record.carrier_id,
        tracking_number=record.tracking_number,
        expected_delivery_at=record.expected_delivery_at,
        dispatched_at=record.dispatched_at,
        delivered_at=record.delivered_at,
        proof_reference_id=record.proof_reference_id,
        failed_attempts=record.failed_attempts,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def to_detail(
    record: DeliveryRecord,
) -> DeliveryDetailResponse:

    return DeliveryDetailResponse(
        **to_response(record).model_dump(),
        events=[
            event.model_copy(deep=True)
            for event in record.events
        ],
    )


# ============================================================
# AUTHORIZATION
# ============================================================

def require_delivery_permission(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool,
) -> None:

    # Existing permissions.py defines
    # LOGISTICS_READ. Confirm LOGISTICS_WRITE
    # is also defined before integration.

    permission = (
        Permission.LOGISTICS_WRITE
        if write
        else Permission.LOGISTICS_READ
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
            detail="Delivery permission denied",
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
# DELIVERY STORE
# ============================================================

class DeliveryStore:

    def __init__(self):

        self._records: dict[
            str,
            DeliveryRecord,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, object],
        ] = {}

        self._lock = asyncio.Lock()

    def _get(
        self,
        tenant_id: str,
        delivery_id: str,
    ) -> DeliveryRecord:

        record = self._records.get(
            delivery_id
        )

        if (
            record is None
            or record.tenant_id != tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Delivery not found",
            )

        return record

    @staticmethod
    def _check_version(
        record: DeliveryRecord,
        expected_version: int,
    ) -> None:

        if record.version != expected_version:
            raise HTTPException(
                status_code=409,
                detail="Delivery version conflict",
            )

    def _check_idempotency(
        self,
        key: tuple[str, str, str],
        fingerprint: str,
    ) -> object | None:

        existing = self._idempotency.get(
            key
        )

        if existing is None:
            return None

        old_fingerprint, response = existing

        if old_fingerprint != fingerprint:
            raise HTTPException(
                status_code=409,
                detail="Idempotency conflict",
            )

        return response

    def _append_event(
        self,
        record: DeliveryRecord,
        *,
        event_type: DeliveryEventType,
        actor_id: str,
        location_reference: str | None = None,
        reason_code: str | None = None,
    ) -> None:

        if (
            len(record.events)
            >= MAX_EVENTS_PER_DELIVERY
        ):
            raise HTTPException(
                status_code=503,
                detail="Delivery event capacity reached",
            )

        record.events.append(
            DeliveryEventResponse(
                event_id=secrets.token_urlsafe(18),
                delivery_id=record.delivery_id,
                event_type=event_type,
                status=record.status,
                actor_id=actor_id,
                location_reference=location_reference,
                reason_code=reason_code,
                timestamp=utc_now(),
                version=record.version,
            )
        )

    def _transition(
        self,
        record: DeliveryRecord,
        target: DeliveryStatus,
    ) -> None:

        permitted = ALLOWED_TRANSITIONS.get(
            record.status,
            set(),
        )

        if target not in permitted:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Invalid delivery transition: "
                    f"{record.status.value} -> "
                    f"{target.value}"
                ),
            )

        record.status = target
        record.version += 1
        record.updated_at = utc_now()

    async def create(
        self,
        *,
        principal: Principal,
        payload: DeliveryCreate,
    ) -> DeliveryResponse:

        require_delivery_permission(
            principal,
            payload.warehouse_id,
            write=True,
        )

        fingerprint = request_fingerprint(
            "create",
            payload,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        async with self._lock:

            existing = self._check_idempotency(
                key,
                fingerprint,
            )

            if existing is not None:
                return existing.model_copy(
                    deep=True
                )

            tenant_count = sum(
                record.tenant_id
                == principal.tenant_id
                for record in self._records.values()
            )

            if tenant_count >= MAX_DELIVERIES_PER_TENANT:
                raise HTTPException(
                    status_code=503,
                    detail="Delivery capacity reached",
                )

            if (
                len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Idempotency capacity reached",
                )

            record = DeliveryRecord(
                delivery_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                order_id=payload.order_id,
                destination_reference_id=(
                    payload.destination_reference_id
                ),
                priority=payload.priority,
                expected_delivery_at=(
                    payload.expected_delivery_at
                ),
            )

            self._append_event(
                record,
                event_type=DeliveryEventType.CREATED,
                actor_id=principal.principal_id,
            )

            self._records[
                record.delivery_id
            ] = record

            result = to_response(record)

            self._idempotency[key] = (
                fingerprint,
                result.model_copy(deep=True),
            )

            return result

    async def get(
        self,
        *,
        principal: Principal,
        delivery_id: str,
    ) -> DeliveryDetailResponse:

        async with self._lock:

            record = self._get(
                principal.tenant_id,
                delivery_id,
            )

            require_delivery_permission(
                principal,
                record.warehouse_id,
                write=False,
            )

            return to_detail(record)

    async def list_records(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
        status: DeliveryStatus | None,
        limit: int,
    ) -> list[DeliveryResponse]:

        require_delivery_permission(
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
        delivery_id: str,
        payload: DeliveryAssignment,
    ) -> DeliveryResponse:

        fingerprint = request_fingerprint(
            f"assign:{delivery_id}",
            payload,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        async with self._lock:

            record = self._get(
                principal.tenant_id,
                delivery_id,
            )

            require_delivery_permission(
                principal,
                record.warehouse_id,
                write=True,
            )

            existing = self._check_idempotency(
                key,
                fingerprint,
            )

            if existing is not None:
                return existing.model_copy(deep=True)

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status != DeliveryStatus.CREATED:
                raise HTTPException(
                    status_code=409,
                    detail="Delivery cannot be assigned",
                )

            if (
                len(record.events)
                >= MAX_EVENTS_PER_DELIVERY
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Delivery event capacity reached",
                )

            record.carrier_id = payload.carrier_id
            record.tracking_number = (
                payload.tracking_number
            )

            self._transition(
                record,
                DeliveryStatus.ASSIGNED,
            )

            self._append_event(
                record,
                event_type=DeliveryEventType.ASSIGNED,
                actor_id=principal.principal_id,
            )

            result = to_response(record)

            self._idempotency[key] = (
                fingerprint,
                result.model_copy(deep=True),
            )

            return result

    async def update_status(
        self,
        *,
        principal: Principal,
        delivery_id: str,
        payload: DeliveryStatusUpdate,
    ) -> DeliveryResponse:

        fingerprint = request_fingerprint(
            f"status:{delivery_id}",
            payload,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        async with self._lock:

            record = self._get(
                principal.tenant_id,
                delivery_id,
            )

            require_delivery_permission(
                principal,
                record.warehouse_id,
                write=True,
            )

            existing = self._check_idempotency(
                key,
                fingerprint,
            )

            if existing is not None:
                return existing.model_copy(deep=True)

            self._check_version(
                record,
                payload.expected_version,
            )

            # Delivery completion must use
            # the proof-of-delivery endpoint.
            if payload.status == DeliveryStatus.DELIVERED:
                raise HTTPException(
                    status_code=409,
                    detail="Use proof-of-delivery endpoint",
                )

            # Failed attempts must use
            # the dedicated failure endpoint.
            if payload.status == DeliveryStatus.FAILED:
                raise HTTPException(
                    status_code=409,
                    detail="Use delivery failure endpoint",
                )

            if (
                len(record.events)
                >= MAX_EVENTS_PER_DELIVERY
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Delivery event capacity reached",
                )

            self._transition(
                record,
                payload.status,
            )

            if payload.status == DeliveryStatus.DISPATCHED:
                record.dispatched_at = utc_now()

            event_type = DeliveryEventType.STATUS_CHANGED

            if payload.status == DeliveryStatus.DISPATCHED:
                event_type = DeliveryEventType.DISPATCHED

            elif payload.status == DeliveryStatus.RETURNING:
                event_type = DeliveryEventType.RETURN_INITIATED

            elif payload.status == DeliveryStatus.RETURNED:
                event_type = DeliveryEventType.RETURN_COMPLETED

            elif payload.status == DeliveryStatus.CANCELLED:
                event_type = DeliveryEventType.CANCELLED

            self._append_event(
                record,
                event_type=event_type,
                actor_id=principal.principal_id,
                location_reference=(
                    payload.location_reference
                ),
                reason_code=payload.reason_code,
            )

            result = to_response(record)

            self._idempotency[key] = (
                fingerprint,
                result.model_copy(deep=True),
            )

            return result

    async def record_failure(
        self,
        *,
        principal: Principal,
        delivery_id: str,
        payload: DeliveryFailure,
    ) -> DeliveryResponse:

        fingerprint = request_fingerprint(
            f"failure:{delivery_id}",
            payload,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        async with self._lock:

            record = self._get(
                principal.tenant_id,
                delivery_id,
            )

            require_delivery_permission(
                principal,
                record.warehouse_id,
                write=True,
            )

            existing = self._check_idempotency(
                key,
                fingerprint,
            )

            if existing is not None:
                return existing.model_copy(deep=True)

            self._check_version(
                record,
                payload.expected_version,
            )

            if (
                len(record.events)
                >= MAX_EVENTS_PER_DELIVERY
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Delivery event capacity reached",
                )

            self._transition(
                record,
                DeliveryStatus.FAILED,
            )

            record.failed_attempts += 1

            self._append_event(
                record,
                event_type=DeliveryEventType.ATTEMPT_FAILED,
                actor_id=principal.principal_id,
                reason_code=payload.reason_code,
            )

            result = to_response(record)

            self._idempotency[key] = (
                fingerprint,
                result.model_copy(deep=True),
            )

            return result

    async def complete_delivery(
        self,
        *,
        principal: Principal,
        delivery_id: str,
        payload: DeliveryProof,
    ) -> DeliveryResponse:

        fingerprint = request_fingerprint(
            f"complete:{delivery_id}",
            payload,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        async with self._lock:

            record = self._get(
                principal.tenant_id,
                delivery_id,
            )

            require_delivery_permission(
                principal,
                record.warehouse_id,
                write=True,
            )

            existing = self._check_idempotency(
                key,
                fingerprint,
            )

            if existing is not None:
                return existing.model_copy(deep=True)

            self._check_version(
                record,
                payload.expected_version,
            )

            if (
                payload.delivered_at > utc_now()
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Delivery time cannot be in future",
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

            if (
                len(record.events)
                >= MAX_EVENTS_PER_DELIVERY
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Delivery event capacity reached",
                )

            self._transition(
                record,
                DeliveryStatus.DELIVERED,
            )

            record.delivered_at = (
                payload.delivered_at
            )

            record.proof_reference_id = (
                payload.proof_reference_id
            )

            self._append_event(
                record,
                event_type=DeliveryEventType.DELIVERED,
                actor_id=principal.principal_id,
            )

            result = to_response(record)

            self._idempotency[key] = (
                fingerprint,
                result.model_copy(deep=True),
            )

            return result

    async def analytics(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
    ) -> DeliveryAnalyticsResponse:

        require_delivery_permission(
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

            delivered = [
                record
                for record in records
                if record.status
                == DeliveryStatus.DELIVERED
            ]

            eligible = [
                record
                for record in delivered
                if (
                    record.expected_delivery_at
                    is not None
                    and record.delivered_at
                    is not None
                )
            ]

            on_time = sum(
                record.delivered_at
                <= record.expected_delivery_at
                for record in eligible
            )

            late = len(eligible) - on_time

            return DeliveryAnalyticsResponse(
                warehouse_id=warehouse_id,
                total_deliveries=len(records),
                delivered=len(delivered),
                in_transit=sum(
                    record.status in {
                        DeliveryStatus.DISPATCHED,
                        DeliveryStatus.IN_TRANSIT,
                        DeliveryStatus.OUT_FOR_DELIVERY,
                    }
                    for record in records
                ),
                failed=sum(
                    record.status == DeliveryStatus.FAILED
                    for record in records
                ),
                returned=sum(
                    record.status == DeliveryStatus.RETURNED
                    for record in records
                ),
                cancelled=sum(
                    record.status == DeliveryStatus.CANCELLED
                    for record in records
                ),
                on_time_deliveries=on_time,
                late_deliveries=late,
                on_time_delivery_rate=(
                    round(
                        on_time / len(eligible) * 100,
                        2,
                    )
                    if eligible
                    else None
                ),
            )


delivery_store = DeliveryStore()


# ============================================================
# DELIVERY SERVICE
# ============================================================

class DeliveryService:

    def __init__(
        self,
        store: DeliveryStore,
    ):
        self.store = store

    async def create(
        self,
        principal: Principal,
        payload: DeliveryCreate,
    ) -> DeliveryResponse:

        return await self.store.create(
            principal=principal,
            payload=payload,
        )

    async def assign(
        self,
        principal: Principal,
        delivery_id: str,
        payload: DeliveryAssignment,
    ) -> DeliveryResponse:

        return await self.store.assign(
            principal=principal,
            delivery_id=delivery_id,
            payload=payload,
        )

    async def complete(
        self,
        principal: Principal,
        delivery_id: str,
        payload: DeliveryProof,
    ) -> DeliveryResponse:

        return await self.store.complete_delivery(
            principal=principal,
            delivery_id=delivery_id,
            payload=payload,
        )


delivery_service = DeliveryService(
    delivery_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Delivery Management"],
)


@router.post(
    "",
    response_model=DeliveryResponse,
    status_code=201,
)
async def create_delivery(
    payload: DeliveryCreate,
    principal: CurrentPrincipal,
):
    return await delivery_service.create(
        principal,
        payload,
    )


@router.get(
    "",
    response_model=list[DeliveryResponse],
)
async def list_deliveries(
    principal: CurrentPrincipal,
    warehouse_id: str,
    status: DeliveryStatus | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await delivery_store.list_records(
        principal=principal,
        warehouse_id=warehouse_id,
        status=status,
        limit=limit,
    )


@router.get(
    "/analytics/{warehouse_id}",
    response_model=DeliveryAnalyticsResponse,
)
async def delivery_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
):
    return await delivery_store.analytics(
        principal=principal,
        warehouse_id=warehouse_id,
    )


@router.get(
    "/{delivery_id}",
    response_model=DeliveryDetailResponse,
)
async def get_delivery(
    delivery_id: str,
    principal: CurrentPrincipal,
):
    return await delivery_store.get(
        principal=principal,
        delivery_id=delivery_id,
    )


@router.post(
    "/{delivery_id}/assign",
    response_model=DeliveryResponse,
)
async def assign_delivery(
    delivery_id: str,
    payload: DeliveryAssignment,
    principal: CurrentPrincipal,
):
    return await delivery_service.assign(
        principal,
        delivery_id,
        payload,
    )


@router.post(
    "/{delivery_id}/status",
    response_model=DeliveryResponse,
)
async def update_delivery_status(
    delivery_id: str,
    payload: DeliveryStatusUpdate,
    principal: CurrentPrincipal,
):
    return await delivery_store.update_status(
        principal=principal,
        delivery_id=delivery_id,
        payload=payload,
    )


@router.post(
    "/{delivery_id}/failure",
    response_model=DeliveryResponse,
)
async def record_delivery_failure(
    delivery_id: str,
    payload: DeliveryFailure,
    principal: CurrentPrincipal,
):
    return await delivery_store.record_failure(
        principal=principal,
        delivery_id=delivery_id,
        payload=payload,
    )


@router.post(
    "/{delivery_id}/complete",
    response_model=DeliveryResponse,
)
async def complete_delivery(
    delivery_id: str,
    payload: DeliveryProof,
    principal: CurrentPrincipal,
):
    return await delivery_service.complete(
        principal,
        delivery_id,
        payload,
    )


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "DeliveryStatus",
    "DeliveryPriority",
    "DeliveryEventType",
    "DeliveryCreate",
    "DeliveryAssignment",
    "DeliveryStatusUpdate",
    "DeliveryProof",
    "DeliveryFailure",
    "DeliveryEventResponse",
    "DeliveryResponse",
    "DeliveryDetailResponse",
    "DeliveryAnalyticsResponse",
    "DeliveryRecord",
    "DeliveryStore",
    "DeliveryService",
    "delivery_store",
    "delivery_service",
    "router",
]
