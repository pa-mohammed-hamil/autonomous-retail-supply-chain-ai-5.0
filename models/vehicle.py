from __future__ import annotations

"""Planned module: vehicle. Implementation pending."""
# backend/models/vehicle.py


import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_vehicle_code() -> str:
    return f"VEH-{uuid.uuid4().hex[:12].upper()}"


def enum_column(enum_class: type[enum.Enum], name: str):
    return SQLEnum(
        enum_class,
        name=name,
        native_enum=False,
        values_callable=lambda members: [
            member.value for member in members
        ],
        validate_strings=True,
        length=60,
    )


def required_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def optional_text(value: str | None) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise ValueError("Expected string")

    return value.strip() or None


def decimal_value(
    value: Any,
    field: str,
    *,
    minimum: Decimal = Decimal("0"),
) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field} must be numeric") from exc

    if not result.is_finite() or result < minimum:
        raise ValueError(
            f"{field} must be at least {minimum}"
        )

    return result


def score_value(value: Any, field: str) -> Decimal:
    result = decimal_value(value, field)

    if result > Decimal("1"):
        raise ValueError(
            f"{field} must be between 0 and 1"
        )

    return result


def enum_value(value: Any) -> Any:
    return value.value if isinstance(value, enum.Enum) else value


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, enum.Enum):
        return value.value

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, float):
        import math

        if not math.isfinite(value):
            raise ValueError("Non-finite JSON number")

        return value

    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]

    raise ValueError(
        f"Unsupported JSON value: {type(value).__name__}"
    )


# ============================================================
# ENUMS
# ============================================================

class VehicleStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_INSPECTION = "pending_inspection"
    AVAILABLE = "available"
    RESERVED = "reserved"
    ASSIGNED = "assigned"
    LOADING = "loading"
    IN_TRANSIT = "in_transit"
    DELIVERING = "delivering"
    RETURNING = "returning"
    MAINTENANCE = "maintenance"
    OUT_OF_SERVICE = "out_of_service"
    SUSPENDED = "suspended"
    RETIRED = "retired"
    ARCHIVED = "archived"


class VehicleType(str, enum.Enum):
    MOTORCYCLE = "motorcycle"
    SCOOTER = "scooter"
    THREE_WHEELER = "three_wheeler"
    CAR = "car"
    VAN = "van"
    MINI_TRUCK = "mini_truck"
    LIGHT_TRUCK = "light_truck"
    MEDIUM_TRUCK = "medium_truck"
    HEAVY_TRUCK = "heavy_truck"
    CONTAINER_TRUCK = "container_truck"
    REFRIGERATED_TRUCK = "refrigerated_truck"
    TANKER = "tanker"
    TRAILER = "trailer"
    ELECTRIC_DELIVERY_VEHICLE = "electric_delivery_vehicle"
    AUTONOMOUS_DELIVERY_VEHICLE = "autonomous_delivery_vehicle"
    DRONE = "drone"
    FORKLIFT = "forklift"
    OTHER = "other"


class VehicleOwnershipType(str, enum.Enum):
    OWNED = "owned"
    LEASED = "leased"
    RENTED = "rented"
    THIRD_PARTY = "third_party"
    CONTRACTED = "contracted"


class VehicleFuelType(str, enum.Enum):
    PETROL = "petrol"
    DIESEL = "diesel"
    ELECTRIC = "electric"
    HYBRID = "hybrid"
    CNG = "cng"
    LNG = "lng"
    LPG = "lpg"
    HYDROGEN = "hydrogen"
    OTHER = "other"


class VehicleCondition(str, enum.Enum):
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class VehicleMaintenanceStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    SCHEDULED = "scheduled"
    DUE = "due"
    OVERDUE = "overdue"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class VehicleInspectionStatus(str, enum.Enum):
    NOT_INSPECTED = "not_inspected"
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    EXPIRED = "expired"


class VehicleRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class VehicleAvailability(str, enum.Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    RESERVED = "reserved"
    BUSY = "busy"
    MAINTENANCE = "maintenance"


class VehicleEventType(str, enum.Enum):
    CREATED = "created"
    UPDATED = "updated"
    INSPECTION_REQUESTED = "inspection_requested"
    INSPECTION_PASSED = "inspection_passed"
    INSPECTION_FAILED = "inspection_failed"
    ACTIVATED = "activated"
    RESERVED = "reserved"
    RESERVATION_RELEASED = "reservation_released"
    ASSIGNED = "assigned"
    LOADING_STARTED = "loading_started"
    DISPATCHED = "dispatched"
    DELIVERY_STARTED = "delivery_started"
    RETURN_STARTED = "return_started"
    TRIP_COMPLETED = "trip_completed"
    LOCATION_UPDATED = "location_updated"
    TELEMETRY_UPDATED = "telemetry_updated"
    MAINTENANCE_SCHEDULED = "maintenance_scheduled"
    MAINTENANCE_STARTED = "maintenance_started"
    MAINTENANCE_COMPLETED = "maintenance_completed"
    OUT_OF_SERVICE = "out_of_service"
    SUSPENDED = "suspended"
    REACTIVATED = "reactivated"
    RISK_UPDATED = "risk_updated"
    COST_UPDATED = "cost_updated"
    DOCUMENT_ADDED = "document_added"
    RETIRED = "retired"
    ARCHIVED = "archived"
    SOFT_DELETED = "soft_deleted"


# ============================================================
# VEHICLE MODEL
# ============================================================

class Vehicle(Base):
    __tablename__ = "vehicles"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "vehicle_code",
            name="uq_vehicle_org_code",
        ),
        UniqueConstraint(
            "organization_id",
            "registration_number",
            name="uq_vehicle_org_registration",
        ),
        UniqueConstraint(
            "organization_id",
            "vin",
            name="uq_vehicle_org_vin",
        ),
        CheckConstraint(
            "capacity_kg >= 0",
            name="ck_vehicle_capacity_kg",
        ),
        CheckConstraint(
            "capacity_volume_m3 >= 0",
            name="ck_vehicle_capacity_volume",
        ),
        CheckConstraint(
            "current_load_kg >= 0",
            name="ck_vehicle_current_load",
        ),
        CheckConstraint(
            "current_load_volume_m3 >= 0",
            name="ck_vehicle_current_volume",
        ),
        CheckConstraint(
            "current_load_kg <= capacity_kg",
            name="ck_vehicle_load_within_capacity",
        ),
        CheckConstraint(
            "current_load_volume_m3 <= capacity_volume_m3",
            name="ck_vehicle_volume_within_capacity",
        ),
        CheckConstraint(
            "odometer_km >= 0",
            name="ck_vehicle_odometer",
        ),
        CheckConstraint(
            "total_distance_km >= 0",
            name="ck_vehicle_total_distance",
        ),
        CheckConstraint(
            "fuel_level_percent IS NULL OR "
            "(fuel_level_percent >= 0 "
            "AND fuel_level_percent <= 100)",
            name="ck_vehicle_fuel_level",
        ),
        CheckConstraint(
            "battery_level_percent IS NULL OR "
            "(battery_level_percent >= 0 "
            "AND battery_level_percent <= 100)",
            name="ck_vehicle_battery_level",
        ),
        CheckConstraint(
            "health_score IS NULL OR "
            "(health_score >= 0 AND health_score <= 1)",
            name="ck_vehicle_health_score",
        ),
        CheckConstraint(
            "risk_score IS NULL OR "
            "(risk_score >= 0 AND risk_score <= 1)",
            name="ck_vehicle_risk_score",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_vehicle_version",
        ),
        Index(
            "ix_vehicle_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_vehicle_org_type",
            "organization_id",
            "vehicle_type",
        ),
        Index(
            "ix_vehicle_org_availability",
            "organization_id",
            "availability",
        ),
        Index(
            "ix_vehicle_org_warehouse",
            "organization_id",
            "warehouse_id",
        ),
        Index(
            "ix_vehicle_org_driver",
            "organization_id",
            "assigned_driver_id",
        ),
        Index(
            "ix_vehicle_org_route",
            "organization_id",
            "current_route_id",
        ),
        Index(
            "ix_vehicle_org_risk",
            "organization_id",
            "risk_level",
        ),
    )

    # ========================================================
    # IDENTITY
    # ========================================================

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    organization_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    vehicle_code: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default=generate_vehicle_code,
    )

    registration_number: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    vin: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    chassis_number: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    engine_number: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    vehicle_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ========================================================
    # CLASSIFICATION
    # ========================================================

    vehicle_type: Mapped[VehicleType] = mapped_column(
        enum_column(
            VehicleType,
            "vehicle_type",
        ),
        default=VehicleType.VAN,
        nullable=False,
    )

    status: Mapped[VehicleStatus] = mapped_column(
        enum_column(
            VehicleStatus,
            "vehicle_status",
        ),
        default=VehicleStatus.DRAFT,
        nullable=False,
    )

    availability: Mapped[VehicleAvailability] = mapped_column(
        enum_column(
            VehicleAvailability,
            "vehicle_availability",
        ),
        default=VehicleAvailability.UNAVAILABLE,
        nullable=False,
    )

    ownership_type: Mapped[VehicleOwnershipType] = mapped_column(
        enum_column(
            VehicleOwnershipType,
            "vehicle_ownership_type",
        ),
        default=VehicleOwnershipType.OWNED,
        nullable=False,
    )

    fuel_type: Mapped[VehicleFuelType] = mapped_column(
        enum_column(
            VehicleFuelType,
            "vehicle_fuel_type",
        ),
        default=VehicleFuelType.DIESEL,
        nullable=False,
    )

    condition: Mapped[VehicleCondition] = mapped_column(
        enum_column(
            VehicleCondition,
            "vehicle_condition",
        ),
        default=VehicleCondition.UNKNOWN,
        nullable=False,
    )

    # ========================================================
    # MANUFACTURER
    # ========================================================

    manufacturer: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    model: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    model_year: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    color: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )

    body_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # ========================================================
    # OWNERSHIP AND ASSIGNMENT
    # ========================================================

    fleet_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    warehouse_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    store_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    logistics_provider_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    owner_organization_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    assigned_driver_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    current_route_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    current_delivery_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    current_trip_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    reservation_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    reserved_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # CAPACITY
    # ========================================================

    capacity_kg: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    capacity_volume_m3: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    current_load_kg: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    current_load_volume_m3: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    max_pallets: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    current_pallets: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    refrigerated: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    hazardous_material_certified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    temperature_min_c: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2),
        nullable=True,
    )

    temperature_max_c: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2),
        nullable=True,
    )

    # ========================================================
    # FUEL, ENERGY AND DISTANCE
    # ========================================================

    fuel_tank_capacity_liters: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    fuel_level_percent: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2),
        nullable=True,
    )

    battery_capacity_kwh: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    battery_level_percent: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 2),
        nullable=True,
    )

    average_fuel_efficiency_kmpl: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    energy_consumption_kwh_per_km: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    estimated_range_km: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(14, 4),
        nullable=True,
    )

    odometer_km: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    total_distance_km: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    total_trips: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    completed_deliveries: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    failed_deliveries: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # ========================================================
    # LOCATION AND TRACKING
    # ========================================================

    latitude: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 7),
        nullable=True,
    )

    longitude: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 7),
        nullable=True,
    )

    altitude_meters: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    speed_kmph: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    heading_degrees: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 3),
        nullable=True,
    )

    location_updated_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    gps_device_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    tracking_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    geofencing_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # ========================================================
    # INSPECTION
    # ========================================================

    inspection_status: Mapped[
        VehicleInspectionStatus
    ] = mapped_column(
        enum_column(
            VehicleInspectionStatus,
            "vehicle_inspection_status",
        ),
        default=VehicleInspectionStatus.NOT_INSPECTED,
        nullable=False,
    )

    last_inspection_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    next_inspection_due_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    inspected_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    inspection_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ========================================================
    # MAINTENANCE
    # ========================================================

    maintenance_status: Mapped[
        VehicleMaintenanceStatus
    ] = mapped_column(
        enum_column(
            VehicleMaintenanceStatus,
            "vehicle_maintenance_status",
        ),
        default=VehicleMaintenanceStatus.NOT_REQUIRED,
        nullable=False,
    )

    last_maintenance_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    next_maintenance_due_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    next_maintenance_due_km: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    maintenance_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    maintenance_history: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # ========================================================
    # PREDICTIVE MAINTENANCE
    # ========================================================

    predictive_maintenance_enabled: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    health_score: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    failure_probability: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    predicted_remaining_useful_life_hours: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    predicted_failure_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    latest_prediction_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    # ========================================================
    # RISK INTELLIGENCE
    # ========================================================

    risk_level: Mapped[VehicleRiskLevel] = mapped_column(
        enum_column(
            VehicleRiskLevel,
            "vehicle_risk_level",
        ),
        default=VehicleRiskLevel.UNKNOWN,
        nullable=False,
    )

    risk_score: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    risk_factors: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    risk_recommendations: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    risk_assessed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # COMPLIANCE
    # ========================================================

    insurance_policy_number: Mapped[
        str | None
    ] = mapped_column(
        String(150),
        nullable=True,
    )

    insurance_expiry_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    registration_expiry_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    fitness_certificate_expiry_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    pollution_certificate_expiry_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    permit_expiry_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    documents: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    compliance_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # ========================================================
    # COST AND FINANCIALS
    # ========================================================

    currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    purchase_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 4),
        nullable=True,
    )

    lease_cost_per_month: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(20, 4),
        nullable=True,
    )

    estimated_cost_per_km: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    total_fuel_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    total_maintenance_cost: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    total_operating_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    # ========================================================
    # AI AND TELEMETRY
    # ========================================================

    ai_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    autonomous_mode_enabled: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    ai_model_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    ai_model_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    ai_insights: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    ai_recommendations: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    latest_telemetry: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    telemetry_updated_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # LIFECYCLE
    # ========================================================

    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_trip_completed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    suspension_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    out_of_service_reason: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    retirement_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # METADATA AND AUDIT
    # ========================================================

    vehicle_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    tags: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    event_history: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    created_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    updated_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    deleted_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    __mapper_args__ = {
        "version_id_col": version,
    }

    # ========================================================
    # INITIALIZATION
    # ========================================================

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        defaults = {
            "id": generate_uuid,
            "vehicle_code": generate_vehicle_code,
            "status": lambda: VehicleStatus.DRAFT,
            "vehicle_type": lambda: VehicleType.VAN,
            "availability": (
                lambda: VehicleAvailability.UNAVAILABLE
            ),
            "ownership_type": (
                lambda: VehicleOwnershipType.OWNED
            ),
            "fuel_type": lambda: VehicleFuelType.DIESEL,
            "condition": lambda: VehicleCondition.UNKNOWN,
            "inspection_status": (
                lambda: VehicleInspectionStatus.NOT_INSPECTED
            ),
            "maintenance_status": (
                lambda: VehicleMaintenanceStatus.NOT_REQUIRED
            ),
            "risk_level": lambda: VehicleRiskLevel.UNKNOWN,
            "capacity_kg": lambda: Decimal("0"),
            "capacity_volume_m3": lambda: Decimal("0"),
            "current_load_kg": lambda: Decimal("0"),
            "current_load_volume_m3": lambda: Decimal("0"),
            "current_pallets": lambda: 0,
            "odometer_km": lambda: Decimal("0"),
            "total_distance_km": lambda: Decimal("0"),
            "total_trips": lambda: 0,
            "completed_deliveries": lambda: 0,
            "failed_deliveries": lambda: 0,
            "total_fuel_cost": lambda: Decimal("0"),
            "total_maintenance_cost": lambda: Decimal("0"),
            "total_operating_cost": lambda: Decimal("0"),
            "currency": lambda: "INR",
            "refrigerated": lambda: False,
            "hazardous_material_certified": lambda: False,
            "tracking_enabled": lambda: False,
            "geofencing_enabled": lambda: False,
            "predictive_maintenance_enabled": lambda: False,
            "ai_enabled": lambda: False,
            "autonomous_mode_enabled": lambda: False,
            "is_deleted": lambda: False,
            "version": lambda: 1,
        }

        for field, factory in defaults.items():
            if getattr(self, field, None) is None:
                setattr(self, field, factory())

        for field in (
            "compliance_metadata",
            "latest_telemetry",
            "vehicle_metadata",
        ):
            if getattr(self, field, None) is None:
                setattr(self, field, {})

        for field in (
            "maintenance_history",
            "risk_factors",
            "risk_recommendations",
            "documents",
            "ai_insights",
            "ai_recommendations",
            "tags",
            "event_history",
        ):
            if getattr(self, field, None) is None:
                setattr(self, field, [])

        if self.created_at is None:
            self.created_at = utc_now()

        if self.updated_at is None:
            self.updated_at = utc_now()

    # ========================================================
    # PROPERTIES
    # ========================================================

    @property
    def is_available(self) -> bool:
        return (
            self.status == VehicleStatus.AVAILABLE
            and self.availability == VehicleAvailability.AVAILABLE
            and not self.is_deleted
        )

    @property
    def is_on_trip(self) -> bool:
        return self.status in {
            VehicleStatus.LOADING,
            VehicleStatus.IN_TRANSIT,
            VehicleStatus.DELIVERING,
            VehicleStatus.RETURNING,
        }

    @property
    def is_high_risk(self) -> bool:
        return self.risk_level in {
            VehicleRiskLevel.HIGH,
            VehicleRiskLevel.CRITICAL,
        }

    @property
    def remaining_capacity_kg(self) -> Decimal:
        return max(
            Decimal("0"),
            (self.capacity_kg or Decimal("0"))
            - (self.current_load_kg or Decimal("0")),
        )

    @property
    def load_utilization_percent(self) -> Decimal:
        if not self.capacity_kg:
            return Decimal("0")

        return (
            (self.current_load_kg or Decimal("0"))
            / self.capacity_kg
            * Decimal("100")
        ).quantize(Decimal("0.01"))

    @property
    def is_overloaded(self) -> bool:
        return (
            (self.current_load_kg or Decimal("0"))
            > (self.capacity_kg or Decimal("0"))
            or
            (self.current_load_volume_m3 or Decimal("0"))
            > (self.capacity_volume_m3 or Decimal("0"))
        )

    @property
    def is_maintenance_due(self) -> bool:
        if self.maintenance_status in {
            VehicleMaintenanceStatus.DUE,
            VehicleMaintenanceStatus.OVERDUE,
            VehicleMaintenanceStatus.IN_PROGRESS,
            VehicleMaintenanceStatus.FAILED,
        }:
            return True

        if self.next_maintenance_due_at is not None:
            due_at = self.next_maintenance_due_at

            if due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=timezone.utc)

            if due_at <= utc_now():
                return True

        if self.next_maintenance_due_km is not None:
            return (
                self.odometer_km
                >= self.next_maintenance_due_km
            )

        return False

    @property
    def has_expired_compliance(self) -> bool:
        fields = (
            self.insurance_expiry_at,
            self.registration_expiry_at,
            self.fitness_certificate_expiry_at,
            self.pollution_certificate_expiry_at,
            self.permit_expiry_at,
        )

        for expiry in fields:
            if expiry is None:
                continue

            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)

            if expiry <= utc_now():
                return True

        return False

    @property
    def can_dispatch(self) -> bool:
        return (
            self.status in {
                VehicleStatus.AVAILABLE,
                VehicleStatus.ASSIGNED,
                VehicleStatus.LOADING,
            }
            and not self.is_deleted
            and self.inspection_status
            == VehicleInspectionStatus.PASSED
            and not self.is_maintenance_due
            and not self.has_expired_compliance
            and not self.is_overloaded
            and not self.is_high_risk
        )

    # ========================================================
    # INTERNAL METHODS
    # ========================================================

    def _ensure_editable(self) -> None:
        if self.is_deleted:
            raise ValueError("Vehicle is deleted")

        if self.status in {
            VehicleStatus.RETIRED,
            VehicleStatus.ARCHIVED,
        }:
            raise ValueError(
                "Retired or archived vehicle cannot be modified"
            )

    def _record_event(
        self,
        event_type: VehicleEventType,
        *,
        actor_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        history = list(self.event_history or [])

        history.append({
            "event_id": generate_uuid(),
            "event_type": event_type.value,
            "actor_id": actor_id,
            "details": json_safe(details or {}),
            "timestamp": utc_now().isoformat(),
        })

        self.event_history = history
        self.updated_at = utc_now()

        if actor_id is not None:
            self.updated_by = actor_id

    def _require_status(
        self,
        *statuses: VehicleStatus,
    ) -> None:
        if self.status not in statuses:
            raise ValueError(
                f"Invalid vehicle status: {enum_value(self.status)}"
            )

    def _clear_assignment(self) -> None:
        self.assigned_driver_id = None
        self.current_route_id = None
        self.current_delivery_id = None
        self.current_trip_id = None
        self.reservation_id = None
        self.reserved_until = None

    def _check_capacity(
        self,
        weight_kg: Decimal,
        volume_m3: Decimal,
    ) -> None:
        if weight_kg > self.capacity_kg:
            raise ValueError(
                "Weight exceeds vehicle capacity"
            )

        if volume_m3 > self.capacity_volume_m3:
            raise ValueError(
                "Volume exceeds vehicle capacity"
            )

    # ========================================================
    # VALIDATION
    # ========================================================

    def validate_vehicle(self) -> None:
        required_text(
            self.organization_id,
            "Organization ID",
        )
        required_text(
            self.vehicle_name,
            "Vehicle name",
        )
        required_text(
            self.vehicle_code,
            "Vehicle code",
        )

        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValueError(
                "Currency must be a three-letter code"
            )

        self._check_capacity(
            self.current_load_kg,
            self.current_load_volume_m3,
        )

        if (
            self.temperature_min_c is not None
            and self.temperature_max_c is not None
            and self.temperature_min_c > self.temperature_max_c
        ):
            raise ValueError(
                "Minimum temperature exceeds maximum"
            )

        if self.model_year is not None:
            if not 1886 <= self.model_year <= utc_now().year + 1:
                raise ValueError("Invalid model year")

    # ========================================================
    # UPDATE PROFILE
    # ========================================================

    def update_profile(
        self,
        *,
        actor_id: str,
        vehicle_name: str | None = None,
        registration_number: str | None = None,
        manufacturer: str | None = None,
        model: str | None = None,
        description: str | None = None,
    ) -> None:
        self._ensure_editable()

        if vehicle_name is not None:
            self.vehicle_name = required_text(
                vehicle_name,
                "Vehicle name",
            )

        if registration_number is not None:
            self.registration_number = optional_text(
                registration_number
            )

        if manufacturer is not None:
            self.manufacturer = optional_text(manufacturer)

        if model is not None:
            self.model = optional_text(model)

        if description is not None:
            self.description = optional_text(description)

        self._record_event(
            VehicleEventType.UPDATED,
            actor_id=actor_id,
            details={"section": "profile"},
        )

    # ========================================================
    # CONFIGURE CAPACITY
    # ========================================================

    def configure_capacity(
        self,
        *,
        actor_id: str,
        capacity_kg: Any,
        capacity_volume_m3: Any,
        max_pallets: int | None = None,
    ) -> None:
        self._ensure_editable()

        if self.is_on_trip:
            raise ValueError(
                "Cannot change capacity during an active trip"
            )

        weight = decimal_value(
            capacity_kg,
            "Capacity kg",
        )

        volume = decimal_value(
            capacity_volume_m3,
            "Capacity volume",
        )

        self._check_capacity_values(
            weight,
            volume,
        )

        if max_pallets is not None:
            if max_pallets < 0:
                raise ValueError(
                    "Maximum pallets cannot be negative"
                )

            if max_pallets < self.current_pallets:
                raise ValueError(
                    "Maximum pallets below current load"
                )

            self.max_pallets = max_pallets

        self.capacity_kg = weight
        self.capacity_volume_m3 = volume

        self._record_event(
            VehicleEventType.UPDATED,
            actor_id=actor_id,
            details={"section": "capacity"},
        )

    def _check_capacity_values(
        self,
        weight: Decimal,
        volume: Decimal,
    ) -> None:
        if weight < self.current_load_kg:
            raise ValueError(
                "New weight capacity below current load"
            )

        if volume < self.current_load_volume_m3:
            raise ValueError(
                "New volume capacity below current load"
            )

    # ========================================================
    # REQUEST INSPECTION
    # ========================================================

    def request_inspection(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        self._require_status(
            VehicleStatus.DRAFT,
            VehicleStatus.OUT_OF_SERVICE,
            VehicleStatus.PENDING_INSPECTION,
        )

        self.status = VehicleStatus.PENDING_INSPECTION
        self.inspection_status = VehicleInspectionStatus.PENDING
        self.availability = VehicleAvailability.UNAVAILABLE

        self._record_event(
            VehicleEventType.INSPECTION_REQUESTED,
            actor_id=actor_id,
        )

    # ========================================================
    # COMPLETE INSPECTION
    # ========================================================

    def complete_inspection(
        self,
        *,
        inspector_id: str,
        passed: bool,
        notes: str | None = None,
        next_due_at: datetime | None = None,
    ) -> None:
        self._ensure_editable()

        self._require_status(
            VehicleStatus.PENDING_INSPECTION,
        )

        self.inspected_by = required_text(
            inspector_id,
            "Inspector ID",
        )

        self.last_inspection_at = utc_now()
        self.inspection_notes = optional_text(notes)
        self.next_inspection_due_at = next_due_at

        if passed:
            self.inspection_status = (
                VehicleInspectionStatus.PASSED
            )
            self.status = VehicleStatus.AVAILABLE
            self.availability = VehicleAvailability.AVAILABLE
            self.activated_at = utc_now()

            event = VehicleEventType.INSPECTION_PASSED
        else:
            self.inspection_status = (
                VehicleInspectionStatus.FAILED
            )
            self.status = VehicleStatus.OUT_OF_SERVICE
            self.availability = VehicleAvailability.UNAVAILABLE

            event = VehicleEventType.INSPECTION_FAILED

        self._record_event(
            event,
            actor_id=inspector_id,
            details={"passed": passed},
        )

    # ========================================================
    # RESERVE
    # ========================================================

    def reserve(
        self,
        *,
        actor_id: str,
        reservation_id: str,
        reserved_until: datetime | None = None,
    ) -> None:
        self._ensure_editable()

        if not self.is_available:
            raise ValueError("Vehicle is unavailable")

        if not self.can_dispatch:
            raise ValueError(
                "Vehicle does not meet dispatch requirements"
            )

        self.reservation_id = required_text(
            reservation_id,
            "Reservation ID",
        )

        self.reserved_until = reserved_until
        self.status = VehicleStatus.RESERVED
        self.availability = VehicleAvailability.RESERVED

        self._record_event(
            VehicleEventType.RESERVED,
            actor_id=actor_id,
            details={"reservation_id": reservation_id},
        )

    # ========================================================
    # RELEASE RESERVATION
    # ========================================================

    def release_reservation(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        self._require_status(VehicleStatus.RESERVED)

        self.reservation_id = None
        self.reserved_until = None
        self.status = VehicleStatus.AVAILABLE
        self.availability = VehicleAvailability.AVAILABLE

        self._record_event(
            VehicleEventType.RESERVATION_RELEASED,
            actor_id=actor_id,
        )

    # ========================================================
    # ASSIGN VEHICLE
    # ========================================================

    def assign(
        self,
        *,
        actor_id: str,
        driver_id: str,
        route_id: str,
        trip_id: str,
        delivery_id: str | None = None,
    ) -> None:
        self._ensure_editable()

        self._require_status(
            VehicleStatus.AVAILABLE,
            VehicleStatus.RESERVED,
        )

        if self.status == VehicleStatus.AVAILABLE:
            if not self.can_dispatch:
                raise ValueError(
                    "Vehicle is not dispatch-ready"
                )
        else:
            if (
                self.inspection_status
                != VehicleInspectionStatus.PASSED
                or self.is_maintenance_due
                or self.has_expired_compliance
                or self.is_overloaded
                or self.is_high_risk
            ):
                raise ValueError(
                    "Reserved vehicle is not dispatch-ready"
                )

        self.assigned_driver_id = required_text(
            driver_id,
            "Driver ID",
        )

        self.current_route_id = required_text(
            route_id,
            "Route ID",
        )

        self.current_trip_id = required_text(
            trip_id,
            "Trip ID",
        )

        self.current_delivery_id = optional_text(delivery_id)

        self.status = VehicleStatus.ASSIGNED
        self.availability = VehicleAvailability.BUSY

        self._record_event(
            VehicleEventType.ASSIGNED,
            actor_id=actor_id,
            details={
                "driver_id": driver_id,
                "route_id": route_id,
                "trip_id": trip_id,
            },
        )

    # ========================================================
    # START LOADING
    # ========================================================

    def start_loading(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        self._require_status(VehicleStatus.ASSIGNED)

        self.status = VehicleStatus.LOADING

        self._record_event(
            VehicleEventType.LOADING_STARTED,
            actor_id=actor_id,
        )

    # ========================================================
    # UPDATE LOAD
    # ========================================================

    def update_load(
        self,
        *,
        actor_id: str,
        weight_kg: Any,
        volume_m3: Any,
        pallets: int = 0,
    ) -> None:
        self._ensure_editable()

        self._require_status(
            VehicleStatus.ASSIGNED,
            VehicleStatus.LOADING,
        )

        weight = decimal_value(
            weight_kg,
            "Load weight",
        )

        volume = decimal_value(
            volume_m3,
            "Load volume",
        )

        self._check_capacity(weight, volume)

        if pallets < 0:
            raise ValueError(
                "Pallet count cannot be negative"
            )

        if (
            self.max_pallets is not None
            and pallets > self.max_pallets
        ):
            raise ValueError(
                "Pallet count exceeds capacity"
            )

        self.current_load_kg = weight
        self.current_load_volume_m3 = volume
        self.current_pallets = pallets

        self._record_event(
            VehicleEventType.UPDATED,
            actor_id=actor_id,
            details={
                "section": "load",
                "weight_kg": str(weight),
                "volume_m3": str(volume),
                "pallets": pallets,
            },
        )

    # ========================================================
    # DISPATCH
    # ========================================================

    def dispatch(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        self._require_status(
            VehicleStatus.ASSIGNED,
            VehicleStatus.LOADING,
        )

        if not self.can_dispatch:
            raise ValueError(
                "Vehicle is not dispatch-ready"
            )

        if not self.assigned_driver_id:
            raise ValueError(
                "Driver assignment is required"
            )

        if not self.current_route_id:
            raise ValueError(
                "Route assignment is required"
            )

        self.status = VehicleStatus.IN_TRANSIT
        self.availability = VehicleAvailability.BUSY
        self.dispatched_at = utc_now()

        self._record_event(
            VehicleEventType.DISPATCHED,
            actor_id=actor_id,
        )

    # ========================================================
    # START DELIVERY
    # ========================================================

    def start_delivery(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        self._require_status(VehicleStatus.IN_TRANSIT)

        self.status = VehicleStatus.DELIVERING

        self._record_event(
            VehicleEventType.DELIVERY_STARTED,
            actor_id=actor_id,
        )

    # ========================================================
    # START RETURN
    # ========================================================

    def start_return(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        self._require_status(
            VehicleStatus.IN_TRANSIT,
            VehicleStatus.DELIVERING,
        )

        self.status = VehicleStatus.RETURNING

        self._record_event(
            VehicleEventType.RETURN_STARTED,
            actor_id=actor_id,
        )

    # ========================================================
    # COMPLETE TRIP
    # ========================================================

    def complete_trip(
        self,
        *,
        actor_id: str,
        distance_km: Any,
        completed_deliveries: int = 0,
        failed_deliveries: int = 0,
        fuel_cost: Any = 0,
        operating_cost: Any = 0,
    ) -> None:
        self._ensure_editable()

        self._require_status(
            VehicleStatus.IN_TRANSIT,
            VehicleStatus.DELIVERING,
            VehicleStatus.RETURNING,
        )

        distance = decimal_value(
            distance_km,
            "Trip distance",
        )

        fuel = decimal_value(
            fuel_cost,
            "Fuel cost",
        )

        operating = decimal_value(
            operating_cost,
            "Operating cost",
        )

        if completed_deliveries < 0 or failed_deliveries < 0:
            raise ValueError(
                "Delivery counts cannot be negative"
            )

        self.odometer_km += distance
        self.total_distance_km += distance
        self.total_trips += 1

        self.completed_deliveries += completed_deliveries
        self.failed_deliveries += failed_deliveries

        self.total_fuel_cost += fuel
        self.total_operating_cost += operating

        self.current_load_kg = Decimal("0")
        self.current_load_volume_m3 = Decimal("0")
        self.current_pallets = 0

        self.last_trip_completed_at = utc_now()

        self._clear_assignment()

        if self.is_maintenance_due:
            self.status = VehicleStatus.MAINTENANCE
            self.availability = VehicleAvailability.MAINTENANCE
        else:
            self.status = VehicleStatus.AVAILABLE
            self.availability = VehicleAvailability.AVAILABLE

        self._record_event(
            VehicleEventType.TRIP_COMPLETED,
            actor_id=actor_id,
            details={
                "distance_km": str(distance),
                "completed_deliveries": completed_deliveries,
                "failed_deliveries": failed_deliveries,
                "fuel_cost": str(fuel),
                "operating_cost": str(operating),
            },
        )

    # ========================================================
    # UPDATE LOCATION
    # ========================================================

    def update_location(
        self,
        *,
        latitude: Any,
        longitude: Any,
        speed_kmph: Any | None = None,
        heading_degrees: Any | None = None,
        actor_id: str | None = None,
    ) -> None:
        self._ensure_editable()

        lat = Decimal(str(latitude))
        lon = Decimal(str(longitude))

        if not lat.is_finite() or not Decimal("-90") <= lat <= Decimal("90"):
            raise ValueError("Invalid latitude")

        if not lon.is_finite() or not Decimal("-180") <= lon <= Decimal("180"):
            raise ValueError("Invalid longitude")

        self.latitude = lat
        self.longitude = lon

        if speed_kmph is not None:
            self.speed_kmph = decimal_value(
                speed_kmph,
                "Speed",
            )

        if heading_degrees is not None:
            heading = decimal_value(
                heading_degrees,
                "Heading",
            )

            if heading >= Decimal("360"):
                raise ValueError(
                    "Heading must be below 360 degrees"
                )

            self.heading_degrees = heading

        self.location_updated_at = utc_now()

        self._record_event(
            VehicleEventType.LOCATION_UPDATED,
            actor_id=actor_id,
            details={
                "latitude": str(lat),
                "longitude": str(lon),
            },
        )

    # ========================================================
    # UPDATE TELEMETRY
    # ========================================================

    def update_telemetry(
        self,
        *,
        telemetry: dict[str, Any],
        fuel_level_percent: Any | None = None,
        battery_level_percent: Any | None = None,
        actor_id: str | None = None,
    ) -> None:
        self._ensure_editable()

        if not isinstance(telemetry, dict):
            raise ValueError(
                "Telemetry must be a dictionary"
            )

        if fuel_level_percent is not None:
            fuel = decimal_value(
                fuel_level_percent,
                "Fuel level",
            )

            if fuel > 100:
                raise ValueError(
                    "Fuel level cannot exceed 100%"
                )

            self.fuel_level_percent = fuel

        if battery_level_percent is not None:
            battery = decimal_value(
                battery_level_percent,
                "Battery level",
            )

            if battery > 100:
                raise ValueError(
                    "Battery level cannot exceed 100%"
                )

            self.battery_level_percent = battery

        self.latest_telemetry = json_safe(telemetry)
        self.telemetry_updated_at = utc_now()

        self._record_event(
            VehicleEventType.TELEMETRY_UPDATED,
            actor_id=actor_id,
        )

    # ========================================================
    # SCHEDULE MAINTENANCE
    # ========================================================

    def schedule_maintenance(
        self,
        *,
        actor_id: str,
        reason: str,
        due_at: datetime | None = None,
        due_odometer_km: Any | None = None,
    ) -> None:
        self._ensure_editable()

        self.maintenance_reason = required_text(
            reason,
            "Maintenance reason",
        )

        self.maintenance_status = (
            VehicleMaintenanceStatus.SCHEDULED
        )

        if due_at is not None:
            self.next_maintenance_due_at = due_at

        if due_odometer_km is not None:
            self.next_maintenance_due_km = decimal_value(
                due_odometer_km,
                "Maintenance odometer",
            )

        self._record_event(
            VehicleEventType.MAINTENANCE_SCHEDULED,
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # START MAINTENANCE
    # ========================================================

    def start_maintenance(
        self,
        *,
        actor_id: str,
        reason: str | None = None,
    ) -> None:
        self._ensure_editable()

        self._require_status(
            VehicleStatus.AVAILABLE,
            VehicleStatus.OUT_OF_SERVICE,
        )

        if reason is not None:
            self.maintenance_reason = required_text(
                reason,
                "Maintenance reason",
            )

        self.status = VehicleStatus.MAINTENANCE
        self.availability = VehicleAvailability.MAINTENANCE

        self.maintenance_status = (
            VehicleMaintenanceStatus.IN_PROGRESS
        )

        self._record_event(
            VehicleEventType.MAINTENANCE_STARTED,
            actor_id=actor_id,
        )

    # ========================================================
    # COMPLETE MAINTENANCE
    # ========================================================

    def complete_maintenance(
        self,
        *,
        actor_id: str,
        description: str,
        cost: Any = 0,
        next_due_at: datetime | None = None,
        next_due_km: Any | None = None,
    ) -> None:
        self._ensure_editable()

        self._require_status(VehicleStatus.MAINTENANCE)

        if self.maintenance_status != (
            VehicleMaintenanceStatus.IN_PROGRESS
        ):
            raise ValueError(
                "Maintenance is not in progress"
            )

        maintenance_cost = decimal_value(
            cost,
            "Maintenance cost",
        )

        record = {
            "maintenance_id": generate_uuid(),
            "description": required_text(
                description,
                "Maintenance description",
            ),
            "cost": str(maintenance_cost),
            "currency": self.currency,
            "completed_by": actor_id,
            "completed_at": utc_now().isoformat(),
            "odometer_km": str(self.odometer_km),
        }

        history = list(self.maintenance_history or [])
        history.append(record)

        self.maintenance_history = history
        self.total_maintenance_cost += maintenance_cost
        self.total_operating_cost += maintenance_cost

        self.maintenance_status = (
            VehicleMaintenanceStatus.COMPLETED
        )

        self.last_maintenance_at = utc_now()
        self.next_maintenance_due_at = next_due_at

        if next_due_km is not None:
            self.next_maintenance_due_km = decimal_value(
                next_due_km,
                "Next maintenance odometer",
            )
        else:
            self.next_maintenance_due_km = None

        self.maintenance_reason = None
        self.status = VehicleStatus.PENDING_INSPECTION
        self.availability = VehicleAvailability.UNAVAILABLE
        self.inspection_status = VehicleInspectionStatus.PENDING

        self._record_event(
            VehicleEventType.MAINTENANCE_COMPLETED,
            actor_id=actor_id,
            details=record,
        )

    # ========================================================
    # UPDATE RISK
    # ========================================================

    def update_risk(
        self,
        *,
        actor_id: str,
        risk_score: Any,
        factors: list[dict[str, Any]] | None = None,
        recommendations: list[dict[str, Any]] | None = None,
    ) -> None:
        self._ensure_editable()

        score = score_value(
            risk_score,
            "Vehicle risk score",
        )

        self.risk_score = score

        if score >= Decimal("0.85"):
            self.risk_level = VehicleRiskLevel.CRITICAL
        elif score >= Decimal("0.65"):
            self.risk_level = VehicleRiskLevel.HIGH
        elif score >= Decimal("0.35"):
            self.risk_level = VehicleRiskLevel.MEDIUM
        else:
            self.risk_level = VehicleRiskLevel.LOW

        if factors is not None:
            self.risk_factors = json_safe(factors)

        if recommendations is not None:
            self.risk_recommendations = json_safe(
                recommendations
            )

        self.risk_assessed_at = utc_now()

        self._record_event(
            VehicleEventType.RISK_UPDATED,
            actor_id=actor_id,
            details={
                "risk_score": str(score),
                "risk_level": self.risk_level.value,
            },
        )

    # ========================================================
    # UPDATE PREDICTIVE MAINTENANCE
    # ========================================================

    def update_predictive_maintenance(
        self,
        *,
        actor_id: str,
        health_score: Any,
        failure_probability: Any,
        remaining_useful_life_hours: Any | None = None,
        predicted_failure_at: datetime | None = None,
        prediction_id: str | None = None,
    ) -> None:
        self._ensure_editable()

        self.health_score = score_value(
            health_score,
            "Health score",
        )

        self.failure_probability = score_value(
            failure_probability,
            "Failure probability",
        )

        if remaining_useful_life_hours is not None:
            self.predicted_remaining_useful_life_hours = (
                decimal_value(
                    remaining_useful_life_hours,
                    "Remaining useful life",
                )
            )

        self.predicted_failure_at = predicted_failure_at
        self.latest_prediction_id = optional_text(prediction_id)

        self.predictive_maintenance_enabled = True

        self._record_event(
            VehicleEventType.UPDATED,
            actor_id=actor_id,
            details={
                "section": "predictive_maintenance",
                "health_score": str(self.health_score),
                "failure_probability": str(
                    self.failure_probability
                ),
            },
        )

    # ========================================================
    # ADD DOCUMENT
    # ========================================================

    def add_document(
        self,
        *,
        actor_id: str,
        document_id: str,
        document_type: str,
        expires_at: datetime | None = None,
    ) -> None:
        self._ensure_editable()

        document = {
            "document_id": required_text(
                document_id,
                "Document ID",
            ),
            "document_type": required_text(
                document_type,
                "Document type",
            ),
            "expires_at": iso(expires_at),
            "added_at": utc_now().isoformat(),
        }

        documents = list(self.documents or [])
        documents.append(document)

        self.documents = documents

        self._record_event(
            VehicleEventType.DOCUMENT_ADDED,
            actor_id=actor_id,
            details=document,
        )

    # ========================================================
    # MARK OUT OF SERVICE
    # ========================================================

    def mark_out_of_service(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_editable()

        if self.is_on_trip:
            raise ValueError(
                "Active trip requires incident handling "
                "and safe vehicle recovery first"
            )

        self.out_of_service_reason = required_text(
            reason,
            "Out-of-service reason",
        )

        self.status = VehicleStatus.OUT_OF_SERVICE
        self.availability = VehicleAvailability.UNAVAILABLE

        self._record_event(
            VehicleEventType.OUT_OF_SERVICE,
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # SUSPEND
    # ========================================================

    def suspend(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_editable()

        if self.is_on_trip:
            raise ValueError(
                "Cannot suspend vehicle during an active trip"
            )

        self.suspension_reason = required_text(
            reason,
            "Suspension reason",
        )

        self.status = VehicleStatus.SUSPENDED
        self.availability = VehicleAvailability.UNAVAILABLE
        self.suspended_at = utc_now()

        self._record_event(
            VehicleEventType.SUSPENDED,
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # REACTIVATE
    # ========================================================

    def reactivate(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        self._require_status(
            VehicleStatus.SUSPENDED,
            VehicleStatus.OUT_OF_SERVICE,
        )

        self.status = VehicleStatus.PENDING_INSPECTION
        self.availability = VehicleAvailability.UNAVAILABLE
        self.inspection_status = VehicleInspectionStatus.PENDING

        self.suspension_reason = None
        self.out_of_service_reason = None

        self._record_event(
            VehicleEventType.REACTIVATED,
            actor_id=actor_id,
        )

    # ========================================================
    # RETIRE
    # ========================================================

    def retire(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_editable()

        if self.is_on_trip:
            raise ValueError(
                "Cannot retire vehicle during an active trip"
            )

        self.retirement_reason = required_text(
            reason,
            "Retirement reason",
        )

        self.status = VehicleStatus.RETIRED
        self.availability = VehicleAvailability.UNAVAILABLE
        self.retired_at = utc_now()

        self._clear_assignment()

        self._record_event(
            VehicleEventType.RETIRED,
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # ARCHIVE
    # ========================================================

    def archive(
        self,
        *,
        actor_id: str,
    ) -> None:
        if self.is_deleted:
            raise ValueError("Vehicle is deleted")

        self._require_status(VehicleStatus.RETIRED)

        self.status = VehicleStatus.ARCHIVED
        self.archived_at = utc_now()

        self._record_event(
            VehicleEventType.ARCHIVED,
            actor_id=actor_id,
        )

    # ========================================================
    # SOFT DELETE
    # ========================================================

    def soft_delete(
        self,
        *,
        actor_id: str,
    ) -> None:
        if self.is_deleted:
            raise ValueError("Vehicle already deleted")

        self._require_status(
            VehicleStatus.DRAFT,
            VehicleStatus.ARCHIVED,
        )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = required_text(
            actor_id,
            "Actor ID",
        )

        self._record_event(
            VehicleEventType.SOFT_DELETED,
            actor_id=actor_id,
        )

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(
        self,
        *,
        include_telemetry: bool = False,
        include_financials: bool = False,
        include_history: bool = False,
        include_sensitive: bool = False,
    ) -> dict[str, Any]:

        data = {
            "id": self.id,
            "organization_id": self.organization_id,
            "vehicle_code": self.vehicle_code,
            "vehicle_name": self.vehicle_name,
            "description": self.description,
            "vehicle_type": enum_value(self.vehicle_type),
            "status": enum_value(self.status),
            "availability": enum_value(self.availability),
            "ownership_type": enum_value(
                self.ownership_type
            ),
            "fuel_type": enum_value(self.fuel_type),
            "condition": enum_value(self.condition),
            "manufacturer": self.manufacturer,
            "model": self.model,
            "model_year": self.model_year,
            "fleet_id": self.fleet_id,
            "warehouse_id": self.warehouse_id,
            "store_id": self.store_id,
            "logistics_provider_id": (
                self.logistics_provider_id
            ),
            "assigned_driver_id": self.assigned_driver_id,
            "current_route_id": self.current_route_id,
            "current_delivery_id": self.current_delivery_id,
            "current_trip_id": self.current_trip_id,
            "capacity_kg": str(self.capacity_kg),
            "capacity_volume_m3": str(
                self.capacity_volume_m3
            ),
            "current_load_kg": str(self.current_load_kg),
            "current_load_volume_m3": str(
                self.current_load_volume_m3
            ),
            "remaining_capacity_kg": str(
                self.remaining_capacity_kg
            ),
            "load_utilization_percent": str(
                self.load_utilization_percent
            ),
            "max_pallets": self.max_pallets,
            "current_pallets": self.current_pallets,
            "refrigerated": self.refrigerated,
            "hazardous_material_certified": (
                self.hazardous_material_certified
            ),
            "odometer_km": str(self.odometer_km),
            "total_distance_km": str(
                self.total_distance_km
            ),
            "total_trips": self.total_trips,
            "completed_deliveries": self.completed_deliveries,
            "failed_deliveries": self.failed_deliveries,
            "inspection_status": enum_value(
                self.inspection_status
            ),
            "maintenance_status": enum_value(
                self.maintenance_status
            ),
            "last_inspection_at": iso(
                self.last_inspection_at
            ),
            "next_inspection_due_at": iso(
                self.next_inspection_due_at
            ),
            "last_maintenance_at": iso(
                self.last_maintenance_at
            ),
            "next_maintenance_due_at": iso(
                self.next_maintenance_due_at
            ),
            "predictive_maintenance_enabled": (
                self.predictive_maintenance_enabled
            ),
            "health_score": (
                str(self.health_score)
                if self.health_score is not None
                else None
            ),
            "failure_probability": (
                str(self.failure_probability)
                if self.failure_probability is not None
                else None
            ),
            "predicted_remaining_useful_life_hours": (
                str(self.predicted_remaining_useful_life_hours)
                if self.predicted_remaining_useful_life_hours
                is not None
                else None
            ),
            "predicted_failure_at": iso(
                self.predicted_failure_at
            ),
            "risk_level": enum_value(self.risk_level),
            "risk_score": (
                str(self.risk_score)
                if self.risk_score is not None
                else None
            ),
            "risk_assessed_at": iso(self.risk_assessed_at),
            "tracking_enabled": self.tracking_enabled,
            "geofencing_enabled": self.geofencing_enabled,
            "ai_enabled": self.ai_enabled,
            "autonomous_mode_enabled": (
                self.autonomous_mode_enabled
            ),
            "is_available": self.is_available,
            "is_on_trip": self.is_on_trip,
            "is_high_risk": self.is_high_risk,
            "is_overloaded": self.is_overloaded,
            "is_maintenance_due": self.is_maintenance_due,
            "has_expired_compliance": (
                self.has_expired_compliance
            ),
            "can_dispatch": self.can_dispatch,
            "tags": self.tags,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "version": self.version,
        }

        if include_telemetry:
            data.update({
                "latitude": (
                    str(self.latitude)
                    if self.latitude is not None
                    else None
                ),
                "longitude": (
                    str(self.longitude)
                    if self.longitude is not None
                    else None
                ),
                "speed_kmph": (
                    str(self.speed_kmph)
                    if self.speed_kmph is not None
                    else None
                ),
                "heading_degrees": (
                    str(self.heading_degrees)
                    if self.heading_degrees is not None
                    else None
                ),
                "fuel_level_percent": (
                    str(self.fuel_level_percent)
                    if self.fuel_level_percent is not None
                    else None
                ),
                "battery_level_percent": (
                    str(self.battery_level_percent)
                    if self.battery_level_percent is not None
                    else None
                ),
                "latest_telemetry": self.latest_telemetry,
                "telemetry_updated_at": iso(
                    self.telemetry_updated_at
                ),
                "location_updated_at": iso(
                    self.location_updated_at
                ),
            })

        if include_financials:
            data.update({
                "currency": self.currency,
                "purchase_cost": (
                    str(self.purchase_cost)
                    if self.purchase_cost is not None
                    else None
                ),
                "lease_cost_per_month": (
                    str(self.lease_cost_per_month)
                    if self.lease_cost_per_month is not None
                    else None
                ),
                "estimated_cost_per_km": (
                    str(self.estimated_cost_per_km)
                    if self.estimated_cost_per_km is not None
                    else None
                ),
                "total_fuel_cost": str(
                    self.total_fuel_cost
                ),
                "total_maintenance_cost": str(
                    self.total_maintenance_cost
                ),
                "total_operating_cost": str(
                    self.total_operating_cost
                ),
            })

        if include_history:
            data.update({
                "maintenance_history": (
                    self.maintenance_history
                ),
                "event_history": self.event_history,
                "risk_factors": self.risk_factors,
                "risk_recommendations": (
                    self.risk_recommendations
                ),
                "ai_insights": self.ai_insights,
                "ai_recommendations": self.ai_recommendations,
            })

        if include_sensitive:
            data.update({
                "registration_number": (
                    self.registration_number
                ),
                "vin": self.vin,
                "chassis_number": self.chassis_number,
                "engine_number": self.engine_number,
                "gps_device_id": self.gps_device_id,
                "insurance_policy_number": (
                    self.insurance_policy_number
                ),
                "insurance_expiry_at": iso(
                    self.insurance_expiry_at
                ),
                "registration_expiry_at": iso(
                    self.registration_expiry_at
                ),
                "fitness_certificate_expiry_at": iso(
                    self.fitness_certificate_expiry_at
                ),
                "pollution_certificate_expiry_at": iso(
                    self.pollution_certificate_expiry_at
                ),
                "permit_expiry_at": iso(
                    self.permit_expiry_at
                ),
                "documents": self.documents,
                "compliance_metadata": (
                    self.compliance_metadata
                ),
                "vehicle_metadata": self.vehicle_metadata,
                "created_by": self.created_by,
                "updated_by": self.updated_by,
                "is_deleted": self.is_deleted,
                "deleted_at": iso(self.deleted_at),
                "deleted_by": self.deleted_by,
            })

        return data

    def __repr__(self) -> str:
        return (
            f"<Vehicle("
            f"id={self.id!r}, "
            f"code={self.vehicle_code!r}, "
            f"name={self.vehicle_name!r}, "
            f"status={enum_value(self.status)!r}"
            f")>"
        )