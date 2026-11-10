from __future__ import annotations

"""Planned module: routes. Implementation pending."""

"""
backend/routes.py

Autonomous Retail Supply Chain AI 5.0
Delivery Route Management API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Multi-tenant delivery route management
    - Warehouse-scoped authorization
    - Route creation with delivery stops
    - Driver and vehicle assignments
    - Heuristic route optimization
    - Distance and ETA estimation
    - Route dispatch and completion
    - Stop arrival and delivery tracking
    - Route cancellation
    - Optimistic concurrency
    - Idempotent route creation
    - Route analytics

Important:
    Distance calculations use the Haversine formula.
    ETA assumes straight-line distance and fixed speed.
    Optimization uses nearest-neighbor heuristics.

    This is not a live road-network routing engine.
"""


import asyncio
import hashlib
import json
import math
import secrets

from dataclasses import dataclass, field
from datetime import datetime, timezone
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


API_PREFIX = "/api/v1/routes"

MAX_ROUTES_PER_TENANT = 50000
MAX_STOPS_PER_ROUTE = 100
MAX_EVENTS_PER_ROUTE = 500
MAX_IDEMPOTENCY_KEYS = 100000
MAX_LIST_LIMIT = 200

EARTH_RADIUS_KM = 6371.0088
DEFAULT_SPEED_KMH = 35.0
DEFAULT_STOP_SERVICE_MINUTES = 10


# ============================================================
# ENUMS
# ============================================================

class RouteStatus(str, Enum):
    DRAFT = "draft"
    OPTIMIZED = "optimized"
    ASSIGNED = "assigned"
    DISPATCHED = "dispatched"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class RoutePriority(str, Enum):
    STANDARD = "standard"
    EXPRESS = "express"
    CRITICAL = "critical"


class StopStatus(str, Enum):
    PENDING = "pending"
    ARRIVED = "arrived"
    DELIVERED = "delivered"
    FAILED = "failed"
    SKIPPED = "skipped"


class RouteEventType(str, Enum):
    CREATED = "created"
    OPTIMIZED = "optimized"
    ASSIGNED = "assigned"
    DISPATCHED = "dispatched"
    STARTED = "started"
    STOP_ARRIVED = "stop_arrived"
    STOP_DELIVERED = "stop_delivered"
    STOP_FAILED = "stop_failed"
    STOP_SKIPPED = "stop_skipped"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# ============================================================
# REQUEST MODELS
# ============================================================

class GeoPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class RouteStopCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery_id: str = Field(
        min_length=1,
        max_length=128,
    )

    customer_reference: str = Field(
        min_length=1,
        max_length=128,
    )

    location: GeoPoint

    service_minutes: int = Field(
        default=DEFAULT_STOP_SERVICE_MINUTES,
        ge=0,
        le=240,
    )

    priority: RoutePriority = RoutePriority.STANDARD


class RouteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    route_name: str = Field(
        min_length=3,
        max_length=200,
    )

    origin: GeoPoint

    stops: list[RouteStopCreate] = Field(
        min_length=1,
        max_length=MAX_STOPS_PER_ROUTE,
    )

    planned_speed_kmh: float = Field(
        default=DEFAULT_SPEED_KMH,
        gt=0,
        le=130,
    )

    priority: RoutePriority = RoutePriority.STANDARD

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_stops(self):

        delivery_ids = [
            stop.delivery_id
            for stop in self.stops
        ]

        if len(delivery_ids) != len(set(delivery_ids)):
            raise ValueError(
                "Duplicate delivery IDs are not allowed"
            )

        return self


class RouteVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class RouteAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    vehicle_id: str = Field(
        min_length=1,
        max_length=128,
    )

    driver_id: str = Field(
        min_length=1,
        max_length=128,
    )


class RouteStopAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    notes: str = Field(
        default="",
        max_length=500,
    )


class RouteCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    reason: str = Field(
        min_length=5,
        max_length=500,
    )


# ============================================================
# RESPONSE MODELS
# ============================================================

class RouteStopResponse(BaseModel):
    stop_id: str
    delivery_id: str
    customer_reference: str
    location: GeoPoint

    sequence: int
    priority: RoutePriority
    status: StopStatus

    service_minutes: int

    estimated_arrival_minutes: float | None

    arrived_at: datetime | None
    completed_at: datetime | None


class RouteEventResponse(BaseModel):
    event_id: str
    event_type: RouteEventType
    actor_id: str
    details: str | None
    created_at: datetime


class RouteResponse(BaseModel):
    route_id: str
    warehouse_id: str
    route_name: str

    status: RouteStatus
    priority: RoutePriority

    vehicle_id: str | None
    driver_id: str | None

    total_stops: int
    completed_stops: int
    failed_stops: int

    estimated_distance_km: float
    estimated_duration_minutes: float

    version: int

    created_at: datetime
    updated_at: datetime
    dispatched_at: datetime | None
    completed_at: datetime | None


class RouteDetailResponse(RouteResponse):
    origin: GeoPoint
    planned_speed_kmh: float
    stops: list[RouteStopResponse]
    events: list[RouteEventResponse]


class RouteAnalyticsResponse(BaseModel):
    total_routes: int
    draft: int
    optimized: int
    assigned: int
    dispatched: int
    in_progress: int
    completed: int
    cancelled: int

    total_delivery_stops: int
    delivered_stops: int
    failed_stops: int

    total_estimated_distance_km: float
    average_estimated_duration_minutes: float | None


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass
class RouteStopRecord:
    stop_id: str
    delivery_id: str
    customer_reference: str
    location: GeoPoint
    sequence: int
    priority: RoutePriority
    service_minutes: int

    status: StopStatus = StopStatus.PENDING

    estimated_arrival_minutes: float | None = None

    arrived_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class RouteRecord:
    route_id: str
    tenant_id: str
    warehouse_id: str
    route_name: str

    origin: GeoPoint
    stops: list[RouteStopRecord]

    planned_speed_kmh: float
    priority: RoutePriority

    created_by: str

    status: RouteStatus = RouteStatus.DRAFT

    vehicle_id: str | None = None
    driver_id: str | None = None

    estimated_distance_km: float = 0.0
    estimated_duration_minutes: float = 0.0

    events: list[RouteEventResponse] = field(
        default_factory=list
    )

    version: int = 1

    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    dispatched_at: datetime | None = None
    completed_at: datetime | None = None


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def request_fingerprint(
    payload: RouteCreate,
) -> str:

    canonical = json.dumps(
        payload.model_dump(
            mode="json",
            exclude={"source_request_id"},
        ),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def require_route_access(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool,
) -> None:

    # Add LOGISTICS_WRITE to backend.permissions
    # for production write operations.
    #
    # INVENTORY_WRITE is a temporary placeholder.

    permission = (
        Permission.INVENTORY_WRITE
        if write
        else Permission.LOGISTICS_READ
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
            detail="Route access denied",
        )


def haversine_km(
    point_a: GeoPoint,
    point_b: GeoPoint,
) -> float:

    lat1 = math.radians(point_a.latitude)
    lon1 = math.radians(point_a.longitude)

    lat2 = math.radians(point_b.latitude)
    lon2 = math.radians(point_b.longitude)

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    value = min(1.0, max(0.0, value))

    return (
        2
        * EARTH_RADIUS_KM
        * math.asin(math.sqrt(value))
    )


def optimize_stops(
    origin: GeoPoint,
    stops: list[RouteStopRecord],
) -> list[RouteStopRecord]:

    """
    Nearest-neighbor route heuristic.

    This is a simple approximation and does not
    account for traffic, roads, time windows,
    vehicle capacity, or driver shifts.
    """

    remaining = list(stops)
    ordered = []

    current = origin

    while remaining:

        next_stop = min(
            remaining,
            key=lambda stop: haversine_km(
                current,
                stop.location,
            ),
        )

        ordered.append(next_stop)
        remaining.remove(next_stop)

        current = next_stop.location

    for index, stop in enumerate(
        ordered,
        start=1,
    ):
        stop.sequence = index

    return ordered


def estimate_route(
    origin: GeoPoint,
    stops: list[RouteStopRecord],
    speed_kmh: float,
) -> tuple[float, float]:

    total_distance = 0.0
    total_minutes = 0.0

    current = origin

    for stop in stops:

        distance = haversine_km(
            current,
            stop.location,
        )

        travel_minutes = (
            distance / speed_kmh
        ) * 60

        total_distance += distance
        total_minutes += travel_minutes

        stop.estimated_arrival_minutes = round(
            total_minutes,
            2,
        )

        total_minutes += stop.service_minutes

        current = stop.location

    return (
        round(total_distance, 2),
        round(total_minutes, 2),
    )


def to_stop(
    record: RouteStopRecord,
) -> RouteStopResponse:

    return RouteStopResponse(
        stop_id=record.stop_id,
        delivery_id=record.delivery_id,
        customer_reference=record.customer_reference,
        location=record.location,
        sequence=record.sequence,
        priority=record.priority,
        status=record.status,
        service_minutes=record.service_minutes,
        estimated_arrival_minutes=(
            record.estimated_arrival_minutes
        ),
        arrived_at=record.arrived_at,
        completed_at=record.completed_at,
    )


def to_response(
    record: RouteRecord,
) -> RouteResponse:

    return RouteResponse(
        route_id=record.route_id,
        warehouse_id=record.warehouse_id,
        route_name=record.route_name,
        status=record.status,
        priority=record.priority,
        vehicle_id=record.vehicle_id,
        driver_id=record.driver_id,
        total_stops=len(record.stops),
        completed_stops=sum(
            stop.status == StopStatus.DELIVERED
            for stop in record.stops
        ),
        failed_stops=sum(
            stop.status == StopStatus.FAILED
            for stop in record.stops
        ),
        estimated_distance_km=(
            record.estimated_distance_km
        ),
        estimated_duration_minutes=(
            record.estimated_duration_minutes
        ),
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        dispatched_at=record.dispatched_at,
        completed_at=record.completed_at,
    )


def to_detail(
    record: RouteRecord,
) -> RouteDetailResponse:

    return RouteDetailResponse(
        **to_response(record).model_dump(),
        origin=record.origin,
        planned_speed_kmh=record.planned_speed_kmh,
        stops=[
            to_stop(stop)
            for stop in sorted(
                record.stops,
                key=lambda item: item.sequence,
            )
        ],
        events=list(record.events),
    )


# ============================================================
# ROUTE STORE
# ============================================================

class RouteStore:

    def __init__(self):

        self._routes: dict[
            str,
            RouteRecord,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    def _get(
        self,
        principal: Principal,
        route_id: str,
        *,
        write: bool,
    ) -> RouteRecord:

        record = self._routes.get(route_id)

        if (
            record is None
            or record.tenant_id != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Route not found",
            )

        require_route_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    @staticmethod
    def _check_version(
        record: RouteRecord,
        expected_version: int,
    ) -> None:

        if record.version != expected_version:
            raise HTTPException(
                status_code=409,
                detail="Route version conflict",
            )

    @staticmethod
    def _require_status(
        record: RouteRecord,
        allowed: set[RouteStatus],
    ) -> None:

        if record.status not in allowed:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Invalid route status for operation: "
                    f"{record.status.value}"
                ),
            )

    @staticmethod
    def _add_event(
        record: RouteRecord,
        event_type: RouteEventType,
        actor_id: str,
        details: str | None = None,
    ) -> None:

        if len(record.events) >= MAX_EVENTS_PER_ROUTE:
            raise HTTPException(
                status_code=503,
                detail="Route event capacity reached",
            )

        record.events.append(
            RouteEventResponse(
                event_id=secrets.token_urlsafe(16),
                event_type=event_type,
                actor_id=actor_id,
                details=details,
                created_at=utc_now(),
            )
        )

    @staticmethod
    def _touch(record: RouteRecord) -> None:

        record.version += 1
        record.updated_at = utc_now()

    async def create(
        self,
        *,
        principal: Principal,
        payload: RouteCreate,
    ) -> RouteResponse:

        require_route_access(
            principal,
            payload.warehouse_id,
            write=True,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        fingerprint = request_fingerprint(payload)

        async with self._lock:

            previous = self._idempotency.get(key)

            if previous is not None:

                previous_hash, route_id = previous

                if previous_hash != fingerprint:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return to_response(
                    self._get(
                        principal,
                        route_id,
                        write=False,
                    )
                )

            tenant_count = sum(
                record.tenant_id == principal.tenant_id
                for record in self._routes.values()
            )

            if (
                tenant_count >= MAX_ROUTES_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Route capacity reached",
                )

            stops = [
                RouteStopRecord(
                    stop_id=secrets.token_urlsafe(16),
                    delivery_id=item.delivery_id,
                    customer_reference=item.customer_reference,
                    location=item.location,
                    sequence=index,
                    priority=item.priority,
                    service_minutes=item.service_minutes,
                )
                for index, item in enumerate(
                    payload.stops,
                    start=1,
                )
            ]

            distance, duration = estimate_route(
                payload.origin,
                stops,
                payload.planned_speed_kmh,
            )

            record = RouteRecord(
                route_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                route_name=payload.route_name,
                origin=payload.origin,
                stops=stops,
                planned_speed_kmh=payload.planned_speed_kmh,
                priority=payload.priority,
                created_by=principal.principal_id,
                estimated_distance_km=distance,
                estimated_duration_minutes=duration,
            )

            self._add_event(
                record,
                RouteEventType.CREATED,
                principal.principal_id,
            )

            self._routes[record.route_id] = record

            self._idempotency[key] = (
                fingerprint,
                record.route_id,
            )

            return to_response(record)

    async def get(
        self,
        *,
        principal: Principal,
        route_id: str,
    ) -> RouteDetailResponse:

        async with self._lock:

            return to_detail(
                self._get(
                    principal,
                    route_id,
                    write=False,
                )
            )

    async def list_routes(
        self,
        *,
        principal: Principal,
        warehouse_id: str | None,
        status: RouteStatus | None,
        limit: int,
    ) -> list[RouteResponse]:

        if warehouse_id is not None:
            require_route_access(
                principal,
                warehouse_id,
                write=False,
            )

        async with self._lock:

            records = [
                record
                for record in self._routes.values()
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
                    require_route_access(
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

    async def optimize(
        self,
        *,
        principal: Principal,
        route_id: str,
        expected_version: int,
    ) -> RouteDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                route_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            self._require_status(
                record,
                {
                    RouteStatus.DRAFT,
                    RouteStatus.OPTIMIZED,
                },
            )

            record.stops = optimize_stops(
                record.origin,
                record.stops,
            )

            distance, duration = estimate_route(
                record.origin,
                record.stops,
                record.planned_speed_kmh,
            )

            self._add_event(
                record,
                RouteEventType.OPTIMIZED,
                principal.principal_id,
                "Nearest-neighbor optimization",
            )

            record.estimated_distance_km = distance
            record.estimated_duration_minutes = duration

            record.status = RouteStatus.OPTIMIZED

            self._touch(record)

            return to_detail(record)

    async def assign(
        self,
        *,
        principal: Principal,
        route_id: str,
        payload: RouteAssignmentRequest,
    ) -> RouteResponse:

        async with self._lock:

            record = self._get(
                principal,
                route_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {
                    RouteStatus.DRAFT,
                    RouteStatus.OPTIMIZED,
                    RouteStatus.ASSIGNED,
                },
            )

            self._add_event(
                record,
                RouteEventType.ASSIGNED,
                principal.principal_id,
                (
                    f"Vehicle: {payload.vehicle_id}; "
                    f"Driver: {payload.driver_id}"
                ),
            )

            record.vehicle_id = payload.vehicle_id
            record.driver_id = payload.driver_id

            record.status = RouteStatus.ASSIGNED

            self._touch(record)

            return to_response(record)

    async def dispatch(
        self,
        *,
        principal: Principal,
        route_id: str,
        expected_version: int,
    ) -> RouteResponse:

        async with self._lock:

            record = self._get(
                principal,
                route_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            self._require_status(
                record,
                {RouteStatus.ASSIGNED},
            )

            if not record.vehicle_id or not record.driver_id:
                raise HTTPException(
                    status_code=409,
                    detail="Vehicle and driver are required",
                )

            self._add_event(
                record,
                RouteEventType.DISPATCHED,
                principal.principal_id,
            )

            record.status = RouteStatus.DISPATCHED
            record.dispatched_at = utc_now()

            self._touch(record)

            return to_response(record)

    async def start(
        self,
        *,
        principal: Principal,
        route_id: str,
        expected_version: int,
    ) -> RouteResponse:

        async with self._lock:

            record = self._get(
                principal,
                route_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            self._require_status(
                record,
                {RouteStatus.DISPATCHED},
            )

            self._add_event(
                record,
                RouteEventType.STARTED,
                principal.principal_id,
            )

            record.status = RouteStatus.IN_PROGRESS

            self._touch(record)

            return to_response(record)

    async def update_stop(
        self,
        *,
        principal: Principal,
        route_id: str,
        stop_id: str,
        payload: RouteStopAction,
        action: str,
    ) -> RouteDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                route_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {RouteStatus.IN_PROGRESS},
            )

            stop = next(
                (
                    item
                    for item in record.stops
                    if item.stop_id == stop_id
                ),
                None,
            )

            if stop is None:
                raise HTTPException(
                    status_code=404,
                    detail="Route stop not found",
                )

            transitions = {
                "arrive": (
                    {StopStatus.PENDING},
                    StopStatus.ARRIVED,
                    RouteEventType.STOP_ARRIVED,
                ),
                "deliver": (
                    {StopStatus.ARRIVED},
                    StopStatus.DELIVERED,
                    RouteEventType.STOP_DELIVERED,
                ),
                "fail": (
                    {
                        StopStatus.PENDING,
                        StopStatus.ARRIVED,
                    },
                    StopStatus.FAILED,
                    RouteEventType.STOP_FAILED,
                ),
                "skip": (
                    {StopStatus.PENDING},
                    StopStatus.SKIPPED,
                    RouteEventType.STOP_SKIPPED,
                ),
            }

            if action not in transitions:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid stop action",
                )

            allowed, new_status, event_type = (
                transitions[action]
            )

            if stop.status not in allowed:
                raise HTTPException(
                    status_code=409,
                    detail="Invalid stop status transition",
                )

            self._add_event(
                record,
                event_type,
                principal.principal_id,
                (
                    f"Stop: {stop_id}; "
                    f"Notes: {payload.notes}"
                ),
            )

            stop.status = new_status

            if new_status == StopStatus.ARRIVED:
                stop.arrived_at = utc_now()

            if new_status in {
                StopStatus.DELIVERED,
                StopStatus.FAILED,
                StopStatus.SKIPPED,
            }:
                stop.completed_at = utc_now()

            self._touch(record)

            return to_detail(record)

    async def complete(
        self,
        *,
        principal: Principal,
        route_id: str,
        expected_version: int,
    ) -> RouteResponse:

        async with self._lock:

            record = self._get(
                principal,
                route_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            self._require_status(
                record,
                {RouteStatus.IN_PROGRESS},
            )

            unfinished = [
                stop
                for stop in record.stops
                if stop.status in {
                    StopStatus.PENDING,
                    StopStatus.ARRIVED,
                }
            ]

            if unfinished:
                raise HTTPException(
                    status_code=409,
                    detail="All stops must be finalized",
                )

            self._add_event(
                record,
                RouteEventType.COMPLETED,
                principal.principal_id,
            )

            record.status = RouteStatus.COMPLETED
            record.completed_at = utc_now()

            self._touch(record)

            return to_response(record)

    async def cancel(
        self,
        *,
        principal: Principal,
        route_id: str,
        payload: RouteCancelRequest,
    ) -> RouteResponse:

        async with self._lock:

            record = self._get(
                principal,
                route_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status in {
                RouteStatus.COMPLETED,
                RouteStatus.CANCELLED,
            }:
                raise HTTPException(
                    status_code=409,
                    detail="Route cannot be cancelled",
                )

            if any(
                stop.status == StopStatus.DELIVERED
                for stop in record.stops
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Route with delivered stops requires closure workflow",
                )

            self._add_event(
                record,
                RouteEventType.CANCELLED,
                principal.principal_id,
                payload.reason,
            )

            record.status = RouteStatus.CANCELLED

            self._touch(record)

            return to_response(record)

    async def analytics(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
    ) -> RouteAnalyticsResponse:

        require_route_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._routes.values()
                if (
                    record.tenant_id == principal.tenant_id
                    and record.warehouse_id == warehouse_id
                )
            ]

            statuses = [
                record.status
                for record in records
            ]

            stops = [
                stop
                for record in records
                for stop in record.stops
            ]

            total_duration = sum(
                record.estimated_duration_minutes
                for record in records
            )

            return RouteAnalyticsResponse(
                total_routes=len(records),
                draft=statuses.count(
                    RouteStatus.DRAFT
                ),
                optimized=statuses.count(
                    RouteStatus.OPTIMIZED
                ),
                assigned=statuses.count(
                    RouteStatus.ASSIGNED
                ),
                dispatched=statuses.count(
                    RouteStatus.DISPATCHED
                ),
                in_progress=statuses.count(
                    RouteStatus.IN_PROGRESS
                ),
                completed=statuses.count(
                    RouteStatus.COMPLETED
                ),
                cancelled=statuses.count(
                    RouteStatus.CANCELLED
                ),
                total_delivery_stops=len(stops),
                delivered_stops=sum(
                    stop.status == StopStatus.DELIVERED
                    for stop in stops
                ),
                failed_stops=sum(
                    stop.status == StopStatus.FAILED
                    for stop in stops
                ),
                total_estimated_distance_km=round(
                    sum(
                        record.estimated_distance_km
                        for record in records
                    ),
                    2,
                ),
                average_estimated_duration_minutes=(
                    round(
                        total_duration / len(records),
                        2,
                    )
                    if records
                    else None
                ),
            )


route_store = RouteStore()


# ============================================================
# SERVICE
# ============================================================

class RouteService:

    def __init__(
        self,
        store: RouteStore,
    ):
        self.store = store

    async def create(
        self,
        principal: Principal,
        payload: RouteCreate,
    ) -> RouteResponse:

        return await self.store.create(
            principal=principal,
            payload=payload,
        )


route_service = RouteService(route_store)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Delivery Routes"],
)


@router.post(
    "",
    response_model=RouteResponse,
    status_code=201,
)
async def create_route(
    payload: RouteCreate,
    principal: CurrentPrincipal,
):
    return await route_service.create(
        principal,
        payload,
    )


@router.get(
    "",
    response_model=list[RouteResponse],
)
async def list_routes(
    principal: CurrentPrincipal,
    warehouse_id: str | None = None,
    status: RouteStatus | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await route_store.list_routes(
        principal=principal,
        warehouse_id=warehouse_id,
        status=status,
        limit=limit,
    )


@router.get(
    "/analytics/{warehouse_id}",
    response_model=RouteAnalyticsResponse,
)
async def route_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
):
    return await route_store.analytics(
        principal=principal,
        warehouse_id=warehouse_id,
    )


@router.get(
    "/{route_id}",
    response_model=RouteDetailResponse,
)
async def get_route(
    route_id: str,
    principal: CurrentPrincipal,
):
    return await route_store.get(
        principal=principal,
        route_id=route_id,
    )


@router.post(
    "/{route_id}/optimize",
    response_model=RouteDetailResponse,
)
async def optimize_route(
    route_id: str,
    payload: RouteVersionRequest,
    principal: CurrentPrincipal,
):
    return await route_store.optimize(
        principal=principal,
        route_id=route_id,
        expected_version=payload.expected_version,
    )


@router.post(
    "/{route_id}/assign",
    response_model=RouteResponse,
)
async def assign_route(
    route_id: str,
    payload: RouteAssignmentRequest,
    principal: CurrentPrincipal,
):
    return await route_store.assign(
        principal=principal,
        route_id=route_id,
        payload=payload,
    )


@router.post(
    "/{route_id}/dispatch",
    response_model=RouteResponse,
)
async def dispatch_route(
    route_id: str,
    payload: RouteVersionRequest,
    principal: CurrentPrincipal,
):
    return await route_store.dispatch(
        principal=principal,
        route_id=route_id,
        expected_version=payload.expected_version,
    )


@router.post(
    "/{route_id}/start",
    response_model=RouteResponse,
)
async def start_route(
    route_id: str,
    payload: RouteVersionRequest,
    principal: CurrentPrincipal,
):
    return await route_store.start(
        principal=principal,
        route_id=route_id,
        expected_version=payload.expected_version,
    )


@router.post(
    "/{route_id}/stops/{stop_id}/arrive",
    response_model=RouteDetailResponse,
)
async def arrive_at_stop(
    route_id: str,
    stop_id: str,
    payload: RouteStopAction,
    principal: CurrentPrincipal,
):
    return await route_store.update_stop(
        principal=principal,
        route_id=route_id,
        stop_id=stop_id,
        payload=payload,
        action="arrive",
    )


@router.post(
    "/{route_id}/stops/{stop_id}/deliver",
    response_model=RouteDetailResponse,
)
async def deliver_stop(
    route_id: str,
    stop_id: str,
    payload: RouteStopAction,
    principal: CurrentPrincipal,
):
    return await route_store.update_stop(
        principal=principal,
        route_id=route_id,
        stop_id=stop_id,
        payload=payload,
        action="deliver",
    )


@router.post(
    "/{route_id}/stops/{stop_id}/fail",
    response_model=RouteDetailResponse,
)
async def fail_stop(
    route_id: str,
    stop_id: str,
    payload: RouteStopAction,
    principal: CurrentPrincipal,
):
    return await route_store.update_stop(
        principal=principal,
        route_id=route_id,
        stop_id=stop_id,
        payload=payload,
        action="fail",
    )


@router.post(
    "/{route_id}/stops/{stop_id}/skip",
    response_model=RouteDetailResponse,
)
async def skip_stop(
    route_id: str,
    stop_id: str,
    payload: RouteStopAction,
    principal: CurrentPrincipal,
):
    return await route_store.update_stop(
        principal=principal,
        route_id=route_id,
        stop_id=stop_id,
        payload=payload,
        action="skip",
    )


@router.post(
    "/{route_id}/complete",
    response_model=RouteResponse,
)
async def complete_route(
    route_id: str,
    payload: RouteVersionRequest,
    principal: CurrentPrincipal,
):
    return await route_store.complete(
        principal=principal,
        route_id=route_id,
        expected_version=payload.expected_version,
    )


@router.post(
    "/{route_id}/cancel",
    response_model=RouteResponse,
)
async def cancel_route(
    route_id: str,
    payload: RouteCancelRequest,
    principal: CurrentPrincipal,
):
    return await route_store.cancel(
        principal=principal,
        route_id=route_id,
        payload=payload,
    )


__all__ = [
    "RouteStatus",
    "RoutePriority",
    "StopStatus",
    "RouteEventType",
    "GeoPoint",
    "RouteStopCreate",
    "RouteCreate",
    "RouteVersionRequest",
    "RouteAssignmentRequest",
    "RouteStopAction",
    "RouteCancelRequest",
    "RouteStopResponse",
    "RouteEventResponse",
    "RouteResponse",
    "RouteDetailResponse",
    "RouteAnalyticsResponse",
    "RouteStore",
    "RouteService",
    "route_store",
    "route_service",
    "router",
]
