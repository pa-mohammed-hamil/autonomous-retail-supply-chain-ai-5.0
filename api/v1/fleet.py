from __future__ import annotations

"""Planned module: fleet. Implementation pending."""

"""
backend/fleet.py

Autonomous Retail Supply Chain AI 5.0
Fleet Management and Logistics Intelligence API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Vehicle registration
    - Vehicle status management
    - Driver assignment
    - Delivery trip lifecycle
    - Fleet maintenance records
    - Fuel expense tracking
    - Distance and utilization metrics
    - Warehouse-scoped fleet management
    - Tenant isolation
    - Optimistic concurrency
    - Idempotent trip creation
    - Bounded in-memory storage

This is a fleet planning and record-management
prototype. It does not dispatch physical vehicles,
track live GPS, or verify driving licences.
"""


import asyncio
import hashlib
import json
import secrets

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
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


API_PREFIX = "/api/v1/fleet"

MAX_VEHICLES_PER_TENANT = 10_000
MAX_TRIPS_PER_TENANT = 100_000
MAX_MAINTENANCE_RECORDS = 100_000
MAX_FUEL_RECORDS = 100_000
MAX_IDEMPOTENCY_KEYS = 150_000
MAX_LIST_LIMIT = 200


# ============================================================
# ENUMS
# ============================================================

class VehicleType(str, Enum):
    BIKE = "bike"
    VAN = "van"
    TRUCK = "truck"
    REFRIGERATED_TRUCK = "refrigerated_truck"
    ELECTRIC_VAN = "electric_van"
    ELECTRIC_TRUCK = "electric_truck"


class VehicleStatus(str, Enum):
    AVAILABLE = "available"
    ASSIGNED = "assigned"
    IN_TRANSIT = "in_transit"
    MAINTENANCE = "maintenance"
    OUT_OF_SERVICE = "out_of_service"


class TripStatus(str, Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MaintenanceType(str, Enum):
    PREVENTIVE = "preventive"
    CORRECTIVE = "corrective"
    INSPECTION = "inspection"
    TIRE = "tire"
    ENGINE = "engine"
    BRAKE = "brake"
    BATTERY = "battery"
    OTHER = "other"


class FuelType(str, Enum):
    DIESEL = "diesel"
    PETROL = "petrol"
    CNG = "cng"
    ELECTRIC = "electric"


# ============================================================
# REQUEST MODELS
# ============================================================

class VehicleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    registration_number: str = Field(
        min_length=4,
        max_length=30,
    )

    vehicle_type: VehicleType

    capacity_kg: float = Field(
        gt=0,
        le=100_000,
        allow_inf_nan=False,
    )

    fuel_type: FuelType

    odometer_km: float = Field(
        default=0,
        ge=0,
        le=10_000_000,
        allow_inf_nan=False,
    )

    model_name: str | None = Field(
        default=None,
        max_length=150,
    )


class VehicleStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: VehicleStatus
    expected_version: int = Field(ge=1)


class DriverAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    driver_id: str = Field(
        min_length=1,
        max_length=128,
    )

    expected_version: int = Field(ge=1)


class TripCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_id: str = Field(
        min_length=1,
        max_length=128,
    )

    delivery_id: str | None = Field(
        default=None,
        max_length=128,
    )

    origin_reference: str = Field(
        min_length=1,
        max_length=200,
    )

    destination_reference: str = Field(
        min_length=1,
        max_length=200,
    )

    planned_distance_km: float = Field(
        gt=0,
        le=100_000,
        allow_inf_nan=False,
    )

    load_kg: float = Field(
        ge=0,
        le=100_000,
        allow_inf_nan=False,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )


class TripComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    actual_distance_km: float = Field(
        ge=0,
        le=100_000,
        allow_inf_nan=False,
    )


class MaintenanceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_id: str

    maintenance_type: MaintenanceType

    description: str = Field(
        min_length=3,
        max_length=1000,
    )

    cost: Decimal = Field(
        ge=0,
        max_digits=14,
        decimal_places=2,
    )

    currency: str = Field(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    )

    expected_vehicle_version: int = Field(ge=1)


class FuelRecordCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_id: str

    quantity: float = Field(
        gt=0,
        le=100_000,
        allow_inf_nan=False,
    )

    cost: Decimal = Field(
        ge=0,
        max_digits=14,
        decimal_places=2,
    )

    currency: str = Field(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    )

    odometer_km: float = Field(
        ge=0,
        le=10_000_000,
        allow_inf_nan=False,
    )

    expected_vehicle_version: int = Field(ge=1)


# ============================================================
# RESPONSE MODELS
# ============================================================

class VehicleResponse(BaseModel):
    vehicle_id: str
    warehouse_id: str

    registration_number: str
    vehicle_type: VehicleType

    capacity_kg: float
    fuel_type: FuelType

    model_name: str | None
    odometer_km: float

    status: VehicleStatus
    assigned_driver_id: str | None

    version: int
    created_at: datetime
    updated_at: datetime


class TripResponse(BaseModel):
    trip_id: str
    warehouse_id: str
    vehicle_id: str
    driver_id: str

    delivery_id: str | None

    origin_reference: str
    destination_reference: str

    planned_distance_km: float
    actual_distance_km: float | None

    load_kg: float
    status: TripStatus

    version: int

    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class MaintenanceResponse(BaseModel):
    maintenance_id: str
    vehicle_id: str
    warehouse_id: str

    maintenance_type: MaintenanceType
    description: str

    cost: Decimal
    currency: str

    created_at: datetime


class FuelRecordResponse(BaseModel):
    fuel_record_id: str
    vehicle_id: str
    warehouse_id: str

    quantity: float
    cost: Decimal
    currency: str
    odometer_km: float

    created_at: datetime


class FleetAnalyticsResponse(BaseModel):
    warehouse_id: str

    total_vehicles: int
    available_vehicles: int
    assigned_vehicles: int
    in_transit_vehicles: int
    maintenance_vehicles: int
    out_of_service_vehicles: int

    total_trips: int
    completed_trips: int
    active_trips: int

    total_completed_distance_km: float

    maintenance_cost: Decimal
    fuel_cost: Decimal
    currency: str


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass
class VehicleRecord:
    vehicle_id: str
    tenant_id: str
    warehouse_id: str

    registration_number: str
    vehicle_type: VehicleType

    capacity_kg: float
    fuel_type: FuelType

    model_name: str | None
    odometer_km: float

    status: VehicleStatus = VehicleStatus.AVAILABLE

    assigned_driver_id: str | None = None

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


@dataclass
class TripRecord:
    trip_id: str
    tenant_id: str
    warehouse_id: str

    vehicle_id: str
    driver_id: str

    delivery_id: str | None

    origin_reference: str
    destination_reference: str

    planned_distance_km: float
    load_kg: float

    status: TripStatus = TripStatus.PLANNED

    actual_distance_km: float | None = None

    version: int = 1

    created_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    started_at: datetime | None = None
    completed_at: datetime | None = None


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def require_fleet_access(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool,
) -> None:

    # LOGISTICS_WRITE must be defined in
    # backend.permissions.Permission.
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
            detail="Fleet access denied",
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


def fingerprint_request(
    payload: TripCreate,
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


def to_vehicle_response(
    record: VehicleRecord,
) -> VehicleResponse:

    return VehicleResponse(
        vehicle_id=record.vehicle_id,
        warehouse_id=record.warehouse_id,
        registration_number=record.registration_number,
        vehicle_type=record.vehicle_type,
        capacity_kg=record.capacity_kg,
        fuel_type=record.fuel_type,
        model_name=record.model_name,
        odometer_km=record.odometer_km,
        status=record.status,
        assigned_driver_id=record.assigned_driver_id,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def to_trip_response(
    record: TripRecord,
) -> TripResponse:

    return TripResponse(
        trip_id=record.trip_id,
        warehouse_id=record.warehouse_id,
        vehicle_id=record.vehicle_id,
        driver_id=record.driver_id,
        delivery_id=record.delivery_id,
        origin_reference=record.origin_reference,
        destination_reference=record.destination_reference,
        planned_distance_km=record.planned_distance_km,
        actual_distance_km=record.actual_distance_km,
        load_kg=record.load_kg,
        status=record.status,
        version=record.version,
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
    )


# ============================================================
# FLEET STORE
# ============================================================

class FleetStore:

    def __init__(self):

        self._vehicles: dict[
            str,
            VehicleRecord,
        ] = {}

        self._trips: dict[
            str,
            TripRecord,
        ] = {}

        self._maintenance: dict[
            str,
            tuple[str, MaintenanceResponse],
        ] = {}

        self._fuel: dict[
            str,
            tuple[str, FuelRecordResponse],
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    def _get_vehicle(
        self,
        principal: Principal,
        vehicle_id: str,
        *,
        write: bool,
    ) -> VehicleRecord:

        record = self._vehicles.get(
            vehicle_id
        )

        if (
            record is None
            or record.tenant_id != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Vehicle not found",
            )

        require_fleet_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    def _get_trip(
        self,
        principal: Principal,
        trip_id: str,
        *,
        write: bool,
    ) -> TripRecord:

        record = self._trips.get(
            trip_id
        )

        if (
            record is None
            or record.tenant_id != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Trip not found",
            )

        require_fleet_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    @staticmethod
    def _check_version(
        actual: int,
        expected: int,
    ) -> None:

        if actual != expected:
            raise HTTPException(
                status_code=409,
                detail="Version conflict",
            )

    def _active_trip_exists(
        self,
        vehicle_id: str,
    ) -> bool:

        return any(
            trip.vehicle_id == vehicle_id
            and trip.status in {
                TripStatus.PLANNED,
                TripStatus.IN_PROGRESS,
            }
            for trip in self._trips.values()
        )

    async def create_vehicle(
        self,
        *,
        principal: Principal,
        payload: VehicleCreate,
    ) -> VehicleResponse:

        require_fleet_access(
            principal,
            payload.warehouse_id,
            write=True,
        )

        registration = (
            payload.registration_number
            .strip()
            .upper()
        )

        async with self._lock:

            for vehicle in self._vehicles.values():

                if (
                    vehicle.tenant_id
                    == principal.tenant_id
                    and vehicle.registration_number
                    == registration
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Vehicle registration already exists",
                    )

            tenant_count = sum(
                vehicle.tenant_id
                == principal.tenant_id
                for vehicle in self._vehicles.values()
            )

            if tenant_count >= MAX_VEHICLES_PER_TENANT:
                raise HTTPException(
                    status_code=503,
                    detail="Fleet capacity reached",
                )

            record = VehicleRecord(
                vehicle_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                registration_number=registration,
                vehicle_type=payload.vehicle_type,
                capacity_kg=payload.capacity_kg,
                fuel_type=payload.fuel_type,
                model_name=payload.model_name,
                odometer_km=payload.odometer_km,
            )

            self._vehicles[
                record.vehicle_id
            ] = record

            return to_vehicle_response(
                record
            )

    async def get_vehicle(
        self,
        *,
        principal: Principal,
        vehicle_id: str,
    ) -> VehicleResponse:

        async with self._lock:

            record = self._get_vehicle(
                principal,
                vehicle_id,
                write=False,
            )

            return to_vehicle_response(
                record
            )

    async def list_vehicles(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
        status: VehicleStatus | None,
        limit: int,
    ) -> list[VehicleResponse]:

        require_fleet_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._vehicles.values()
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
                to_vehicle_response(record)
                for record in records[:limit]
            ]

    async def assign_driver(
        self,
        *,
        principal: Principal,
        vehicle_id: str,
        payload: DriverAssignment,
    ) -> VehicleResponse:

        async with self._lock:

            record = self._get_vehicle(
                principal,
                vehicle_id,
                write=True,
            )

            self._check_version(
                record.version,
                payload.expected_version,
            )

            if record.status not in {
                VehicleStatus.AVAILABLE,
                VehicleStatus.ASSIGNED,
            }:
                raise HTTPException(
                    status_code=409,
                    detail="Vehicle unavailable for assignment",
                )

            if self._active_trip_exists(vehicle_id):
                raise HTTPException(
                    status_code=409,
                    detail="Vehicle has an active trip",
                )

            record.assigned_driver_id = (
                payload.driver_id
            )

            record.status = VehicleStatus.ASSIGNED
            record.version += 1
            record.updated_at = utc_now()

            return to_vehicle_response(
                record
            )

    async def update_vehicle_status(
        self,
        *,
        principal: Principal,
        vehicle_id: str,
        payload: VehicleStatusUpdate,
    ) -> VehicleResponse:

        async with self._lock:

            record = self._get_vehicle(
                principal,
                vehicle_id,
                write=True,
            )

            self._check_version(
                record.version,
                payload.expected_version,
            )

            if payload.status == VehicleStatus.IN_TRANSIT:
                raise HTTPException(
                    status_code=409,
                    detail="Start a trip to enter in_transit status",
                )

            if self._active_trip_exists(vehicle_id):
                raise HTTPException(
                    status_code=409,
                    detail="Vehicle has an active trip",
                )

            if (
                payload.status == VehicleStatus.ASSIGNED
                and not record.assigned_driver_id
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Driver assignment required",
                )

            record.status = payload.status

            if payload.status == VehicleStatus.AVAILABLE:
                record.assigned_driver_id = None

            record.version += 1
            record.updated_at = utc_now()

            return to_vehicle_response(
                record
            )

    async def create_trip(
        self,
        *,
        principal: Principal,
        payload: TripCreate,
    ) -> TripResponse:

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = fingerprint_request(
            payload
        )

        async with self._lock:

            vehicle = self._get_vehicle(
                principal,
                payload.vehicle_id,
                write=True,
            )

            previous = self._idempotency.get(
                key
            )

            if previous is not None:

                old_hash, trip_id = previous

                if old_hash != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return to_trip_response(
                    self._get_trip(
                        principal,
                        trip_id,
                        write=False,
                    )
                )

            if vehicle.status != VehicleStatus.ASSIGNED:
                raise HTTPException(
                    status_code=409,
                    detail="Vehicle must have an assigned driver",
                )

            if not vehicle.assigned_driver_id:
                raise HTTPException(
                    status_code=409,
                    detail="Driver is missing",
                )

            if payload.load_kg > vehicle.capacity_kg:
                raise HTTPException(
                    status_code=422,
                    detail="Trip load exceeds vehicle capacity",
                )

            if self._active_trip_exists(
                vehicle.vehicle_id
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Vehicle already has an active trip",
                )

            tenant_count = sum(
                trip.tenant_id == principal.tenant_id
                for trip in self._trips.values()
            )

            if (
                tenant_count >= MAX_TRIPS_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Trip capacity reached",
                )

            record = TripRecord(
                trip_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                warehouse_id=vehicle.warehouse_id,
                vehicle_id=vehicle.vehicle_id,
                driver_id=vehicle.assigned_driver_id,
                delivery_id=payload.delivery_id,
                origin_reference=payload.origin_reference,
                destination_reference=payload.destination_reference,
                planned_distance_km=payload.planned_distance_km,
                load_kg=payload.load_kg,
            )

            self._trips[
                record.trip_id
            ] = record

            self._idempotency[key] = (
                request_hash,
                record.trip_id,
            )

            return to_trip_response(
                record
            )

    async def start_trip(
        self,
        *,
        principal: Principal,
        trip_id: str,
        expected_version: int,
    ) -> TripResponse:

        async with self._lock:

            trip = self._get_trip(
                principal,
                trip_id,
                write=True,
            )

            self._check_version(
                trip.version,
                expected_version,
            )

            if trip.status != TripStatus.PLANNED:
                raise HTTPException(
                    status_code=409,
                    detail="Only planned trips can start",
                )

            vehicle = self._get_vehicle(
                principal,
                trip.vehicle_id,
                write=True,
            )

            if (
                vehicle.status != VehicleStatus.ASSIGNED
                or vehicle.assigned_driver_id
                != trip.driver_id
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Vehicle assignment changed",
                )

            trip.status = TripStatus.IN_PROGRESS
            trip.started_at = utc_now()
            trip.version += 1

            vehicle.status = VehicleStatus.IN_TRANSIT
            vehicle.version += 1
            vehicle.updated_at = utc_now()

            return to_trip_response(
                trip
            )

    async def complete_trip(
        self,
        *,
        principal: Principal,
        trip_id: str,
        payload: TripComplete,
    ) -> TripResponse:

        async with self._lock:

            trip = self._get_trip(
                principal,
                trip_id,
                write=True,
            )

            self._check_version(
                trip.version,
                payload.expected_version,
            )

            if trip.status != TripStatus.IN_PROGRESS:
                raise HTTPException(
                    status_code=409,
                    detail="Trip is not in progress",
                )

            vehicle = self._get_vehicle(
                principal,
                trip.vehicle_id,
                write=True,
            )

            if (
                vehicle.status
                != VehicleStatus.IN_TRANSIT
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Vehicle status conflict",
                )

            new_odometer = (
                vehicle.odometer_km
                + payload.actual_distance_km
            )

            if new_odometer > 10_000_000:
                raise HTTPException(
                    status_code=422,
                    detail="Odometer limit exceeded",
                )

            trip.actual_distance_km = (
                payload.actual_distance_km
            )

            trip.status = TripStatus.COMPLETED
            trip.completed_at = utc_now()
            trip.version += 1

            vehicle.odometer_km = new_odometer
            vehicle.status = VehicleStatus.ASSIGNED
            vehicle.version += 1
            vehicle.updated_at = utc_now()

            return to_trip_response(
                trip
            )

    async def cancel_trip(
        self,
        *,
        principal: Principal,
        trip_id: str,
        expected_version: int,
    ) -> TripResponse:

        async with self._lock:

            trip = self._get_trip(
                principal,
                trip_id,
                write=True,
            )

            self._check_version(
                trip.version,
                expected_version,
            )

            if trip.status != TripStatus.PLANNED:
                raise HTTPException(
                    status_code=409,
                    detail="Only planned trips can be cancelled",
                )

            trip.status = TripStatus.CANCELLED
            trip.version += 1

            return to_trip_response(
                trip
            )

    async def get_trip(
        self,
        *,
        principal: Principal,
        trip_id: str,
    ) -> TripResponse:

        async with self._lock:

            trip = self._get_trip(
                principal,
                trip_id,
                write=False,
            )

            return to_trip_response(
                trip
            )

    async def list_trips(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
        status: TripStatus | None,
        limit: int,
    ) -> list[TripResponse]:

        require_fleet_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = [
                trip
                for trip in self._trips.values()
                if (
                    trip.tenant_id
                    == principal.tenant_id
                    and trip.warehouse_id
                    == warehouse_id
                    and (
                        status is None
                        or trip.status == status
                    )
                )
            ]

            records.sort(
                key=lambda item: item.created_at,
                reverse=True,
            )

            return [
                to_trip_response(trip)
                for trip in records[:limit]
            ]

    async def record_maintenance(
        self,
        *,
        principal: Principal,
        payload: MaintenanceCreate,
    ) -> MaintenanceResponse:

        async with self._lock:

            vehicle = self._get_vehicle(
                principal,
                payload.vehicle_id,
                write=True,
            )

            self._check_version(
                vehicle.version,
                payload.expected_vehicle_version,
            )

            if self._active_trip_exists(
                vehicle.vehicle_id
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Cannot service vehicle with active trip",
                )

            if len(self._maintenance) >= MAX_MAINTENANCE_RECORDS:
                raise HTTPException(
                    status_code=503,
                    detail="Maintenance record capacity reached",
                )

            record = MaintenanceResponse(
                maintenance_id=secrets.token_urlsafe(20),
                vehicle_id=vehicle.vehicle_id,
                warehouse_id=vehicle.warehouse_id,
                maintenance_type=payload.maintenance_type,
                description=payload.description,
                cost=money(payload.cost),
                currency=payload.currency,
                created_at=utc_now(),
            )

            self._maintenance[
                record.maintenance_id
            ] = (
                principal.tenant_id,
                record,
            )

            vehicle.status = VehicleStatus.MAINTENANCE
            vehicle.version += 1
            vehicle.updated_at = utc_now()

            return record

    async def record_fuel(
        self,
        *,
        principal: Principal,
        payload: FuelRecordCreate,
    ) -> FuelRecordResponse:

        async with self._lock:

            vehicle = self._get_vehicle(
                principal,
                payload.vehicle_id,
                write=True,
            )

            self._check_version(
                vehicle.version,
                payload.expected_vehicle_version,
            )

            if payload.odometer_km < vehicle.odometer_km:
                raise HTTPException(
                    status_code=422,
                    detail="Odometer cannot decrease",
                )

            if len(self._fuel) >= MAX_FUEL_RECORDS:
                raise HTTPException(
                    status_code=503,
                    detail="Fuel record capacity reached",
                )

            record = FuelRecordResponse(
                fuel_record_id=secrets.token_urlsafe(20),
                vehicle_id=vehicle.vehicle_id,
                warehouse_id=vehicle.warehouse_id,
                quantity=payload.quantity,
                cost=money(payload.cost),
                currency=payload.currency,
                odometer_km=payload.odometer_km,
                created_at=utc_now(),
            )

            self._fuel[
                record.fuel_record_id
            ] = (
                principal.tenant_id,
                record,
            )

            vehicle.odometer_km = (
                payload.odometer_km
            )

            vehicle.version += 1
            vehicle.updated_at = utc_now()

            return record

    async def analytics(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
        currency: str,
    ) -> FleetAnalyticsResponse:

        require_fleet_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            vehicles = [
                vehicle
                for vehicle in self._vehicles.values()
                if (
                    vehicle.tenant_id
                    == principal.tenant_id
                    and vehicle.warehouse_id
                    == warehouse_id
                )
            ]

            trips = [
                trip
                for trip in self._trips.values()
                if (
                    trip.tenant_id
                    == principal.tenant_id
                    and trip.warehouse_id
                    == warehouse_id
                )
            ]

            maintenance_cost = sum(
                (
                    item.cost
                    for tenant_id, item
                    in self._maintenance.values()
                    if (
                        tenant_id == principal.tenant_id
                        and item.warehouse_id == warehouse_id
                        and item.currency == currency
                    )
                ),
                Decimal("0"),
            )

            fuel_cost = sum(
                (
                    item.cost
                    for tenant_id, item
                    in self._fuel.values()
                    if (
                        tenant_id == principal.tenant_id
                        and item.warehouse_id == warehouse_id
                        and item.currency == currency
                    )
                ),
                Decimal("0"),
            )

            return FleetAnalyticsResponse(
                warehouse_id=warehouse_id,
                total_vehicles=len(vehicles),
                available_vehicles=sum(
                    item.status == VehicleStatus.AVAILABLE
                    for item in vehicles
                ),
                assigned_vehicles=sum(
                    item.status == VehicleStatus.ASSIGNED
                    for item in vehicles
                ),
                in_transit_vehicles=sum(
                    item.status == VehicleStatus.IN_TRANSIT
                    for item in vehicles
                ),
                maintenance_vehicles=sum(
                    item.status == VehicleStatus.MAINTENANCE
                    for item in vehicles
                ),
                out_of_service_vehicles=sum(
                    item.status == VehicleStatus.OUT_OF_SERVICE
                    for item in vehicles
                ),
                total_trips=len(trips),
                completed_trips=sum(
                    item.status == TripStatus.COMPLETED
                    for item in trips
                ),
                active_trips=sum(
                    item.status == TripStatus.IN_PROGRESS
                    for item in trips
                ),
                total_completed_distance_km=round(
                    sum(
                        item.actual_distance_km or 0
                        for item in trips
                        if item.status == TripStatus.COMPLETED
                    ),
                    2,
                ),
                maintenance_cost=money(maintenance_cost),
                fuel_cost=money(fuel_cost),
                currency=currency,
            )


fleet_store = FleetStore()


# ============================================================
# SERVICE
# ============================================================

class FleetService:

    def __init__(
        self,
        store: FleetStore,
    ):
        self.store = store

    async def register_vehicle(
        self,
        principal: Principal,
        payload: VehicleCreate,
    ) -> VehicleResponse:

        return await self.store.create_vehicle(
            principal=principal,
            payload=payload,
        )

    async def create_trip(
        self,
        principal: Principal,
        payload: TripCreate,
    ) -> TripResponse:

        return await self.store.create_trip(
            principal=principal,
            payload=payload,
        )


fleet_service = FleetService(
    fleet_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Fleet Management"],
)


@router.post(
    "/vehicles",
    response_model=VehicleResponse,
    status_code=201,
)
async def register_vehicle(
    payload: VehicleCreate,
    principal: CurrentPrincipal,
):
    return await fleet_service.register_vehicle(
        principal,
        payload,
    )


@router.get(
    "/vehicles",
    response_model=list[VehicleResponse],
)
async def list_vehicles(
    principal: CurrentPrincipal,
    warehouse_id: str,
    status: VehicleStatus | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await fleet_store.list_vehicles(
        principal=principal,
        warehouse_id=warehouse_id,
        status=status,
        limit=limit,
    )


@router.get(
    "/vehicles/{vehicle_id}",
    response_model=VehicleResponse,
)
async def get_vehicle(
    vehicle_id: str,
    principal: CurrentPrincipal,
):
    return await fleet_store.get_vehicle(
        principal=principal,
        vehicle_id=vehicle_id,
    )


@router.post(
    "/vehicles/{vehicle_id}/assign-driver",
    response_model=VehicleResponse,
)
async def assign_vehicle_driver(
    vehicle_id: str,
    payload: DriverAssignment,
    principal: CurrentPrincipal,
):
    return await fleet_store.assign_driver(
        principal=principal,
        vehicle_id=vehicle_id,
        payload=payload,
    )


@router.patch(
    "/vehicles/{vehicle_id}/status",
    response_model=VehicleResponse,
)
async def update_vehicle_status(
    vehicle_id: str,
    payload: VehicleStatusUpdate,
    principal: CurrentPrincipal,
):
    return await fleet_store.update_vehicle_status(
        principal=principal,
        vehicle_id=vehicle_id,
        payload=payload,
    )


@router.post(
    "/trips",
    response_model=TripResponse,
    status_code=201,
)
async def create_trip(
    payload: TripCreate,
    principal: CurrentPrincipal,
):
    return await fleet_service.create_trip(
        principal,
        payload,
    )


@router.get(
    "/trips",
    response_model=list[TripResponse],
)
async def list_trips(
    principal: CurrentPrincipal,
    warehouse_id: str,
    status: TripStatus | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await fleet_store.list_trips(
        principal=principal,
        warehouse_id=warehouse_id,
        status=status,
        limit=limit,
    )


@router.get(
    "/trips/{trip_id}",
    response_model=TripResponse,
)
async def get_trip(
    trip_id: str,
    principal: CurrentPrincipal,
):
    return await fleet_store.get_trip(
        principal=principal,
        trip_id=trip_id,
    )


@router.post(
    "/trips/{trip_id}/start",
    response_model=TripResponse,
)
async def start_trip(
    trip_id: str,
    principal: CurrentPrincipal,
    expected_version: int = Query(ge=1),
):
    return await fleet_store.start_trip(
        principal=principal,
        trip_id=trip_id,
        expected_version=expected_version,
    )


@router.post(
    "/trips/{trip_id}/complete",
    response_model=TripResponse,
)
async def complete_trip(
    trip_id: str,
    payload: TripComplete,
    principal: CurrentPrincipal,
):
    return await fleet_store.complete_trip(
        principal=principal,
        trip_id=trip_id,
        payload=payload,
    )


@router.post(
    "/trips/{trip_id}/cancel",
    response_model=TripResponse,
)
async def cancel_trip(
    trip_id: str,
    principal: CurrentPrincipal,
    expected_version: int = Query(ge=1),
):
    return await fleet_store.cancel_trip(
        principal=principal,
        trip_id=trip_id,
        expected_version=expected_version,
    )


@router.post(
    "/maintenance",
    response_model=MaintenanceResponse,
    status_code=201,
)
async def record_maintenance(
    payload: MaintenanceCreate,
    principal: CurrentPrincipal,
):
    return await fleet_store.record_maintenance(
        principal=principal,
        payload=payload,
    )


@router.post(
    "/fuel",
    response_model=FuelRecordResponse,
    status_code=201,
)
async def record_fuel(
    payload: FuelRecordCreate,
    principal: CurrentPrincipal,
):
    return await fleet_store.record_fuel(
        principal=principal,
        payload=payload,
    )


@router.get(
    "/analytics/{warehouse_id}",
    response_model=FleetAnalyticsResponse,
)
async def fleet_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
    currency: str = Query(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    ),
):
    return await fleet_store.analytics(
        principal=principal,
        warehouse_id=warehouse_id,
        currency=currency,
    )


__all__ = [
    "VehicleType",
    "VehicleStatus",
    "TripStatus",
    "MaintenanceType",
    "FuelType",
    "VehicleCreate",
    "VehicleStatusUpdate",
    "DriverAssignment",
    "TripCreate",
    "TripComplete",
    "MaintenanceCreate",
    "FuelRecordCreate",
    "VehicleResponse",
    "TripResponse",
    "MaintenanceResponse",
    "FuelRecordResponse",
    "FleetAnalyticsResponse",
    "FleetStore",
    "FleetService",
    "fleet_store",
    "fleet_service",
    "router",
]
