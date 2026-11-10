from __future__ import annotations

"""Planned module: warehouse. Implementation pending."""
# backend/models/warehouse.py


import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SQLEnum,
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


def generate_warehouse_code() -> str:
    return f"WH-{uuid.uuid4().hex[:10].upper()}"


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
    minimum: Decimal | None = Decimal("0"),
) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc

    if not result.is_finite():
        raise ValueError(f"{field} must be finite")

    if minimum is not None and result < minimum:
        raise ValueError(f"{field} must be at least {minimum}")

    return result


def score_value(value: Any, field: str) -> Decimal:
    result = decimal_value(value, field)
    if result > Decimal("1"):
        raise ValueError(f"{field} must be between 0 and 1")
    return result


def percentage_value(value: Any, field: str) -> Decimal:
    result = decimal_value(value, field)
    if result > Decimal("100"):
        raise ValueError(f"{field} must be between 0 and 100")
    return result


def enum_value(value: Any) -> Any:
    return value.value if isinstance(value, enum.Enum) else value


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, enum.Enum):
        return value.value

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

class WarehouseStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SETUP = "setup"
    INSPECTION_REQUIRED = "inspection_required"
    ACTIVE = "active"
    LIMITED_OPERATIONS = "limited_operations"
    AT_CAPACITY = "at_capacity"
    MAINTENANCE = "maintenance"
    TEMPORARILY_CLOSED = "temporarily_closed"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"
    DECOMMISSIONED = "decommissioned"
    ARCHIVED = "archived"


class WarehouseType(str, enum.Enum):
    CENTRAL = "central"
    REGIONAL = "regional"
    DISTRIBUTION_CENTER = "distribution_center"
    FULFILLMENT_CENTER = "fulfillment_center"
    MICRO_FULFILLMENT = "micro_fulfillment"
    RETAIL_BACKROOM = "retail_backroom"
    CROSS_DOCK = "cross_dock"
    TRANSIT_HUB = "transit_hub"
    COLD_STORAGE = "cold_storage"
    FREEZER = "freezer"
    BONDED = "bonded"
    HAZARDOUS = "hazardous"
    AUTOMATED = "automated"
    DARK_STORE = "dark_store"
    RETURNS_CENTER = "returns_center"
    MANUFACTURING = "manufacturing"
    THIRD_PARTY = "third_party"
    OTHER = "other"


class WarehouseOwnershipType(str, enum.Enum):
    OWNED = "owned"
    LEASED = "leased"
    RENTED = "rented"
    THIRD_PARTY = "third_party"
    PARTNER = "partner"
    FRANCHISE = "franchise"


class WarehousePriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"


class WarehouseCondition(str, enum.Enum):
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class WarehouseRiskLevel(str, enum.Enum):
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class WarehouseAutomationLevel(str, enum.Enum):
    MANUAL = "manual"
    BASIC = "basic"
    SEMI_AUTOMATED = "semi_automated"
    HIGHLY_AUTOMATED = "highly_automated"
    FULLY_AUTOMATED = "fully_automated"
    ROBOTIC = "robotic"


class WarehouseApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class WarehouseInspectionStatus(str, enum.Enum):
    NOT_INSPECTED = "not_inspected"
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    EXPIRED = "expired"


class WarehouseMaintenanceStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    SCHEDULED = "scheduled"
    DUE = "due"
    OVERDUE = "overdue"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class WarehouseEventType(str, enum.Enum):
    CREATED = "created"
    UPDATED = "updated"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    SETUP_STARTED = "setup_started"
    INSPECTION_REQUESTED = "inspection_requested"
    INSPECTION_PASSED = "inspection_passed"
    INSPECTION_FAILED = "inspection_failed"
    ACTIVATED = "activated"
    CAPACITY_UPDATED = "capacity_updated"
    INVENTORY_SNAPSHOT_UPDATED = "inventory_snapshot_updated"
    WORKFORCE_UPDATED = "workforce_updated"
    EQUIPMENT_UPDATED = "equipment_updated"
    SENSOR_UPDATED = "sensor_updated"
    TEMPERATURE_ALERT = "temperature_alert"
    HUMIDITY_ALERT = "humidity_alert"
    RISK_UPDATED = "risk_updated"
    AI_INSIGHT_ADDED = "ai_insight_added"
    MAINTENANCE_SCHEDULED = "maintenance_scheduled"
    MAINTENANCE_STARTED = "maintenance_started"
    MAINTENANCE_COMPLETED = "maintenance_completed"
    LIMITED_OPERATIONS = "limited_operations"
    OPERATIONS_RESTORED = "operations_restored"
    TEMPORARILY_CLOSED = "temporarily_closed"
    SUSPENDED = "suspended"
    REOPEN_REQUESTED = "reopen_requested"
    DEACTIVATED = "deactivated"
    DECOMMISSIONED = "decommissioned"
    ARCHIVED = "archived"
    SOFT_DELETED = "soft_deleted"


# ============================================================
# WAREHOUSE MODEL
# ============================================================

class Warehouse(Base):
    __tablename__ = "warehouses"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "warehouse_code",
            name="uq_warehouse_org_code",
        ),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_warehouse_org_id",
        ),
        CheckConstraint(
            "total_capacity_units >= 0",
            name="ck_warehouse_capacity_units",
        ),
        CheckConstraint(
            "occupied_units >= 0",
            name="ck_warehouse_occupied_units",
        ),
        CheckConstraint(
            "reserved_units >= 0",
            name="ck_warehouse_reserved_units",
        ),
        CheckConstraint(
            "occupied_units + reserved_units <= total_capacity_units",
            name="ck_warehouse_committed_units",
        ),
        CheckConstraint(
            "total_capacity_weight_kg >= 0",
            name="ck_warehouse_weight_capacity",
        ),
        CheckConstraint(
            "occupied_weight_kg >= 0",
            name="ck_warehouse_occupied_weight",
        ),
        CheckConstraint(
            "occupied_weight_kg <= total_capacity_weight_kg",
            name="ck_warehouse_weight_limit",
        ),
        CheckConstraint(
            "total_capacity_volume_m3 >= 0",
            name="ck_warehouse_volume_capacity",
        ),
        CheckConstraint(
            "occupied_volume_m3 >= 0",
            name="ck_warehouse_occupied_volume",
        ),
        CheckConstraint(
            "occupied_volume_m3 <= total_capacity_volume_m3",
            name="ck_warehouse_volume_limit",
        ),
        CheckConstraint(
            "total_pallet_capacity >= 0",
            name="ck_warehouse_pallet_capacity",
        ),
        CheckConstraint(
            "occupied_pallets >= 0",
            name="ck_warehouse_occupied_pallets",
        ),
        CheckConstraint(
            "occupied_pallets <= total_pallet_capacity",
            name="ck_warehouse_pallet_limit",
        ),
        CheckConstraint(
            "total_bins >= 0 AND active_bins >= 0",
            name="ck_warehouse_bin_counts",
        ),
        CheckConstraint(
            "active_bins <= total_bins",
            name="ck_warehouse_active_bin_limit",
        ),
        CheckConstraint(
            "risk_score IS NULL OR "
            "(risk_score >= 0 AND risk_score <= 1)",
            name="ck_warehouse_risk_score",
        ),
        CheckConstraint(
            "health_score IS NULL OR "
            "(health_score >= 0 AND health_score <= 1)",
            name="ck_warehouse_health_score",
        ),
        CheckConstraint(
            "latitude IS NULL OR "
            "(latitude >= -90 AND latitude <= 90)",
            name="ck_warehouse_latitude",
        ),
        CheckConstraint(
            "longitude IS NULL OR "
            "(longitude >= -180 AND longitude <= 180)",
            name="ck_warehouse_longitude",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_warehouse_version",
        ),
        Index(
            "ix_warehouse_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_warehouse_org_type",
            "organization_id",
            "warehouse_type",
        ),
        Index(
            "ix_warehouse_org_city",
            "organization_id",
            "city",
        ),
        Index(
            "ix_warehouse_org_state",
            "organization_id",
            "state",
        ),
        Index(
            "ix_warehouse_org_manager",
            "organization_id",
            "manager_user_id",
        ),
        Index(
            "ix_warehouse_org_risk",
            "organization_id",
            "risk_level",
        ),
        Index(
            "ix_warehouse_org_region",
            "organization_id",
            "region_id",
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

    warehouse_code: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default=generate_warehouse_code,
    )

    warehouse_name: Mapped[str] = mapped_column(
        String(250),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ========================================================
    # CLASSIFICATION
    # ========================================================

    status: Mapped[WarehouseStatus] = mapped_column(
        enum_column(
            WarehouseStatus,
            "warehouse_status",
        ),
        default=WarehouseStatus.DRAFT,
        nullable=False,
    )

    warehouse_type: Mapped[WarehouseType] = mapped_column(
        enum_column(
            WarehouseType,
            "warehouse_type",
        ),
        default=WarehouseType.DISTRIBUTION_CENTER,
        nullable=False,
    )

    ownership_type: Mapped[
        WarehouseOwnershipType
    ] = mapped_column(
        enum_column(
            WarehouseOwnershipType,
            "warehouse_ownership_type",
        ),
        default=WarehouseOwnershipType.OWNED,
        nullable=False,
    )

    priority: Mapped[WarehousePriority] = mapped_column(
        enum_column(
            WarehousePriority,
            "warehouse_priority",
        ),
        default=WarehousePriority.NORMAL,
        nullable=False,
    )

    condition: Mapped[WarehouseCondition] = mapped_column(
        enum_column(
            WarehouseCondition,
            "warehouse_condition",
        ),
        default=WarehouseCondition.UNKNOWN,
        nullable=False,
    )

    # ========================================================
    # ORGANIZATION AND MANAGEMENT
    # ========================================================

    region_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    parent_warehouse_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    logistics_provider_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    supplier_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    manager_user_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    supervisor_user_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    contact_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    contact_email: Mapped[str | None] = mapped_column(
        String(254),
        nullable=True,
    )

    contact_phone: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    # ========================================================
    # ADDRESS AND GEOLOCATION
    # ========================================================

    address_line_1: Mapped[str | None] = mapped_column(
        String(250),
        nullable=True,
    )

    address_line_2: Mapped[str | None] = mapped_column(
        String(250),
        nullable=True,
    )

    city: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    district: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    state: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    country: Mapped[str] = mapped_column(
        String(120),
        default="India",
        nullable=False,
    )

    country_code: Mapped[str] = mapped_column(
        String(2),
        default="IN",
        nullable=False,
    )

    postal_code: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    latitude: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 7),
        nullable=True,
    )

    longitude: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 7),
        nullable=True,
    )

    timezone_name: Mapped[str] = mapped_column(
        String(100),
        default="Asia/Kolkata",
        nullable=False,
    )

    geofence_radius_meters: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(14, 4),
        nullable=True,
    )

    # ========================================================
    # BUILDING AND FACILITY
    # ========================================================

    facility_area_sq_m: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(20, 4),
        nullable=True,
    )

    storage_area_sq_m: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(20, 4),
        nullable=True,
    )

    number_of_floors: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    loading_docks: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    unloading_docks: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    parking_capacity: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    total_zones: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    total_bins: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    active_bins: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # ========================================================
    # CAPACITY
    # ========================================================

    total_capacity_units: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    occupied_units: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    reserved_units: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    total_capacity_weight_kg: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    occupied_weight_kg: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    total_capacity_volume_m3: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    occupied_volume_m3: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    total_pallet_capacity: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    occupied_pallets: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    maximum_distinct_skus: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    current_distinct_skus: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # ========================================================
    # INVENTORY SNAPSHOT
    # ========================================================

    total_inventory_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    available_inventory_units: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    damaged_inventory_units: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    quarantined_inventory_units: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    incoming_inventory_units: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    outgoing_inventory_units: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    inventory_snapshot_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    inventory_snapshot_source: Mapped[
        str | None
    ] = mapped_column(
        String(100),
        nullable=True,
    )

    # ========================================================
    # OPERATIONS AND THROUGHPUT
    # ========================================================

    daily_receiving_capacity_units: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    daily_shipping_capacity_units: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    daily_picking_capacity_units: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    daily_packing_capacity_units: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    average_order_processing_minutes: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(14, 4),
        nullable=True,
    )

    average_pick_time_minutes: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(14, 4),
        nullable=True,
    )

    average_dispatch_time_minutes: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(14, 4),
        nullable=True,
    )

    operating_24x7: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    operating_schedule: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # ========================================================
    # WORKFORCE
    # ========================================================

    total_employees: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    active_employees: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    warehouse_operators: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    pickers: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    packers: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    forklift_operators: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    security_staff: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    maintenance_staff: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    workforce_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # ========================================================
    # AUTOMATION AND ROBOTICS
    # ========================================================

    automation_level: Mapped[
        WarehouseAutomationLevel
    ] = mapped_column(
        enum_column(
            WarehouseAutomationLevel,
            "warehouse_automation_level",
        ),
        default=WarehouseAutomationLevel.MANUAL,
        nullable=False,
    )

    wms_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    erp_integrated: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    robotics_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    automated_sorting_enabled: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    automated_storage_enabled: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    autonomous_mobile_robots_enabled: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    total_robots: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    active_robots: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    robot_ids: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    equipment_ids: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    automation_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # ========================================================
    # ENVIRONMENT
    # ========================================================

    cold_storage_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    freezer_storage_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    temperature_control_enabled: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    humidity_control_enabled: Mapped[bool] = mapped_column(
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

    current_temperature_c: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(8, 2),
        nullable=True,
    )

    humidity_min_percent: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 2),
        nullable=True,
    )

    humidity_max_percent: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 2),
        nullable=True,
    )

    current_humidity_percent: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 2),
        nullable=True,
    )

    temperature_alert_active: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    humidity_alert_active: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    sensor_ids: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    sensor_data: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    sensor_updated_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # SAFETY AND SECURITY
    # ========================================================

    fire_safety_certified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    hazardous_material_certified: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    food_safety_certified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    pharmaceutical_storage_certified: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    cctv_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    access_control_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    intrusion_detection_enabled: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    emergency_response_enabled: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    security_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # ========================================================
    # INSPECTION
    # ========================================================

    inspection_status: Mapped[
        WarehouseInspectionStatus
    ] = mapped_column(
        enum_column(
            WarehouseInspectionStatus,
            "warehouse_inspection_status",
        ),
        default=WarehouseInspectionStatus.NOT_INSPECTED,
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
        WarehouseMaintenanceStatus
    ] = mapped_column(
        enum_column(
            WarehouseMaintenanceStatus,
            "warehouse_maintenance_status",
        ),
        default=WarehouseMaintenanceStatus.NOT_REQUIRED,
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
    # AI AND PREDICTIVE INTELLIGENCE
    # ========================================================

    ai_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    predictive_analytics_enabled: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    digital_twin_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    health_score: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    risk_level: Mapped[WarehouseRiskLevel] = mapped_column(
        enum_column(
            WarehouseRiskLevel,
            "warehouse_risk_level",
        ),
        default=WarehouseRiskLevel.UNKNOWN,
        nullable=False,
    )

    risk_score: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    predicted_utilization_percent: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 2),
        nullable=True,
    )

    predicted_congestion_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    predicted_capacity_shortage_units: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(20, 4),
        nullable=True,
    )

    predicted_capacity_shortage_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    ai_model_id: Mapped[str | None] = mapped_column(
        String(36),
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

    risk_factors: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    ai_last_analyzed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # PERFORMANCE METRICS
    # ========================================================

    total_orders_processed: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    total_shipments_dispatched: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    total_receipts_processed: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    order_accuracy_percent: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 2),
        nullable=True,
    )

    on_time_dispatch_percent: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 2),
        nullable=True,
    )

    inventory_accuracy_percent: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 2),
        nullable=True,
    )

    warehouse_efficiency_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    performance_updated_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # FINANCIALS
    # ========================================================

    monthly_rent_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    monthly_utilities_cost: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    monthly_labor_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    monthly_maintenance_cost: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    monthly_operating_cost: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    estimated_storage_cost_per_unit: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    estimated_fulfillment_cost_per_order: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    # ========================================================
    # APPROVAL
    # ========================================================

    approval_status: Mapped[
        WarehouseApprovalStatus
    ] = mapped_column(
        enum_column(
            WarehouseApprovalStatus,
            "warehouse_approval_status",
        ),
        default=WarehouseApprovalStatus.NOT_REQUIRED,
        nullable=False,
    )

    approval_request_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    approved_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    rejection_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ========================================================
    # LIFECYCLE
    # ========================================================

    setup_started_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    temporarily_closed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    closure_reason: Mapped[str | None] = mapped_column(
        Text,
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

    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    decommissioned_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    decommission_reason: Mapped[str | None] = mapped_column(
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

    warehouse_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    integrations_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    compliance_documents: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
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
            "warehouse_code": generate_warehouse_code,
            "status": lambda: WarehouseStatus.DRAFT,
            "warehouse_type": (
                lambda: WarehouseType.DISTRIBUTION_CENTER
            ),
            "ownership_type": (
                lambda: WarehouseOwnershipType.OWNED
            ),
            "priority": lambda: WarehousePriority.NORMAL,
            "condition": lambda: WarehouseCondition.UNKNOWN,
            "risk_level": lambda: WarehouseRiskLevel.UNKNOWN,
            "approval_status": (
                lambda: WarehouseApprovalStatus.NOT_REQUIRED
            ),
            "inspection_status": (
                lambda: WarehouseInspectionStatus.NOT_INSPECTED
            ),
            "maintenance_status": (
                lambda: WarehouseMaintenanceStatus.NOT_REQUIRED
            ),
            "automation_level": (
                lambda: WarehouseAutomationLevel.MANUAL
            ),
            "country": lambda: "India",
            "country_code": lambda: "IN",
            "timezone_name": lambda: "Asia/Kolkata",
            "currency": lambda: "INR",
            "number_of_floors": lambda: 1,
            "version": lambda: 1,
            "is_deleted": lambda: False,
        }

        numeric_defaults = (
            "total_capacity_units",
            "occupied_units",
            "reserved_units",
            "total_capacity_weight_kg",
            "occupied_weight_kg",
            "total_capacity_volume_m3",
            "occupied_volume_m3",
            "total_inventory_value",
            "available_inventory_units",
            "damaged_inventory_units",
            "quarantined_inventory_units",
            "incoming_inventory_units",
            "outgoing_inventory_units",
            "daily_receiving_capacity_units",
            "daily_shipping_capacity_units",
            "daily_picking_capacity_units",
            "daily_packing_capacity_units",
            "monthly_rent_cost",
            "monthly_utilities_cost",
            "monthly_labor_cost",
            "monthly_maintenance_cost",
            "monthly_operating_cost",
        )

        integer_defaults = (
            "loading_docks",
            "unloading_docks",
            "parking_capacity",
            "total_zones",
            "total_bins",
            "active_bins",
            "total_pallet_capacity",
            "occupied_pallets",
            "current_distinct_skus",
            "total_employees",
            "active_employees",
            "warehouse_operators",
            "pickers",
            "packers",
            "forklift_operators",
            "security_staff",
            "maintenance_staff",
            "total_robots",
            "active_robots",
            "total_orders_processed",
            "total_shipments_dispatched",
            "total_receipts_processed",
        )

        boolean_defaults = (
            "operating_24x7",
            "wms_enabled",
            "erp_integrated",
            "robotics_enabled",
            "automated_sorting_enabled",
            "automated_storage_enabled",
            "autonomous_mobile_robots_enabled",
            "cold_storage_enabled",
            "freezer_storage_enabled",
            "temperature_control_enabled",
            "humidity_control_enabled",
            "temperature_alert_active",
            "humidity_alert_active",
            "fire_safety_certified",
            "hazardous_material_certified",
            "food_safety_certified",
            "pharmaceutical_storage_certified",
            "cctv_enabled",
            "access_control_enabled",
            "intrusion_detection_enabled",
            "emergency_response_enabled",
            "ai_enabled",
            "predictive_analytics_enabled",
            "digital_twin_enabled",
        )

        for field, factory in defaults.items():
            if getattr(self, field, None) is None:
                setattr(self, field, factory())

        for field in numeric_defaults:
            if getattr(self, field, None) is None:
                setattr(self, field, Decimal("0"))

        for field in integer_defaults:
            if getattr(self, field, None) is None:
                setattr(self, field, 0)

        for field in boolean_defaults:
            if getattr(self, field, None) is None:
                setattr(self, field, False)

        for field in (
            "operating_schedule",
            "workforce_metadata",
            "automation_metadata",
            "sensor_data",
            "security_metadata",
            "warehouse_metadata",
            "integrations_metadata",
        ):
            if getattr(self, field, None) is None:
                setattr(self, field, {})

        for field in (
            "robot_ids",
            "equipment_ids",
            "sensor_ids",
            "maintenance_history",
            "ai_insights",
            "ai_recommendations",
            "risk_factors",
            "compliance_documents",
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
    # COMPUTED PROPERTIES
    # ========================================================

    @property
    def available_capacity_units(self) -> Decimal:
        return max(
            Decimal("0"),
            self.total_capacity_units
            - self.occupied_units
            - self.reserved_units,
        )

    @property
    def available_weight_kg(self) -> Decimal:
        return max(
            Decimal("0"),
            self.total_capacity_weight_kg
            - self.occupied_weight_kg,
        )

    @property
    def available_volume_m3(self) -> Decimal:
        return max(
            Decimal("0"),
            self.total_capacity_volume_m3
            - self.occupied_volume_m3,
        )

    @property
    def available_pallets(self) -> int:
        return max(
            0,
            self.total_pallet_capacity - self.occupied_pallets,
        )

    @property
    def utilization_percent(self) -> Decimal:
        if self.total_capacity_units <= 0:
            return Decimal("0")

        return (
            self.occupied_units
            / self.total_capacity_units
            * Decimal("100")
        ).quantize(Decimal("0.01"))

    @property
    def committed_utilization_percent(self) -> Decimal:
        if self.total_capacity_units <= 0:
            return Decimal("0")

        return (
            (self.occupied_units + self.reserved_units)
            / self.total_capacity_units
            * Decimal("100")
        ).quantize(Decimal("0.01"))

    @property
    def is_at_capacity(self) -> bool:
        return (
            self.total_capacity_units > 0
            and self.available_capacity_units == 0
        )

    @property
    def is_empty(self) -> bool:
        return (
            self.occupied_units == 0
            and self.reserved_units == 0
            and self.occupied_weight_kg == 0
            and self.occupied_volume_m3 == 0
            and self.occupied_pallets == 0
        )

    @property
    def is_operational(self) -> bool:
        return (
            self.status in {
                WarehouseStatus.ACTIVE,
                WarehouseStatus.LIMITED_OPERATIONS,
                WarehouseStatus.AT_CAPACITY,
            }
            and not self.is_deleted
        )

    @property
    def is_high_risk(self) -> bool:
        return self.risk_level in {
            WarehouseRiskLevel.HIGH,
            WarehouseRiskLevel.CRITICAL,
        }

    @property
    def is_temperature_compliant(self) -> bool:
        if self.current_temperature_c is None:
            return True

        if (
            self.temperature_min_c is not None
            and self.current_temperature_c
            < self.temperature_min_c
        ):
            return False

        if (
            self.temperature_max_c is not None
            and self.current_temperature_c
            > self.temperature_max_c
        ):
            return False

        return True

    @property
    def is_humidity_compliant(self) -> bool:
        if self.current_humidity_percent is None:
            return True

        if (
            self.humidity_min_percent is not None
            and self.current_humidity_percent
            < self.humidity_min_percent
        ):
            return False

        if (
            self.humidity_max_percent is not None
            and self.current_humidity_percent
            > self.humidity_max_percent
        ):
            return False

        return True

    @property
    def is_maintenance_due(self) -> bool:
        if self.maintenance_status in {
            WarehouseMaintenanceStatus.DUE,
            WarehouseMaintenanceStatus.OVERDUE,
            WarehouseMaintenanceStatus.IN_PROGRESS,
            WarehouseMaintenanceStatus.FAILED,
        }:
            return True

        if self.next_maintenance_due_at is not None:
            due = self.next_maintenance_due_at
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            return due <= utc_now()

        return False

    @property
    def can_receive_inventory(self) -> bool:
        return (
            self.is_operational
            and self.available_capacity_units > 0
            and not self.is_high_risk
            and not self.is_maintenance_due
            and self.is_temperature_compliant
            and self.is_humidity_compliant
            and self.condition not in {
                WarehouseCondition.POOR,
                WarehouseCondition.CRITICAL,
            }
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _ensure_editable(self) -> None:
        if self.is_deleted:
            raise ValueError("Warehouse is deleted")

        if self.status in {
            WarehouseStatus.DECOMMISSIONED,
            WarehouseStatus.ARCHIVED,
        }:
            raise ValueError(
                "Decommissioned or archived warehouse "
                "cannot be modified"
            )

    def _require_status(
        self,
        *statuses: WarehouseStatus,
    ) -> None:
        if self.status not in statuses:
            raise ValueError(
                f"Invalid warehouse status: "
                f"{enum_value(self.status)}"
            )

    def _record_event(
        self,
        event_type: WarehouseEventType,
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

    def _refresh_capacity_status(self) -> None:
        if self.status not in {
            WarehouseStatus.ACTIVE,
            WarehouseStatus.AT_CAPACITY,
        }:
            return

        self.status = (
            WarehouseStatus.AT_CAPACITY
            if self.is_at_capacity
            else WarehouseStatus.ACTIVE
        )

    # ========================================================
    # VALIDATION
    # ========================================================

    def validate_warehouse(self) -> None:
        required_text(self.organization_id, "Organization ID")
        required_text(self.warehouse_code, "Warehouse code")
        required_text(self.warehouse_name, "Warehouse name")

        if self.total_capacity_units < (
            self.occupied_units + self.reserved_units
        ):
            raise ValueError(
                "Committed units exceed warehouse capacity"
            )

        if self.occupied_weight_kg > self.total_capacity_weight_kg:
            raise ValueError("Occupied weight exceeds capacity")

        if self.occupied_volume_m3 > self.total_capacity_volume_m3:
            raise ValueError("Occupied volume exceeds capacity")

        if self.occupied_pallets > self.total_pallet_capacity:
            raise ValueError("Occupied pallets exceed capacity")

        if self.active_bins > self.total_bins:
            raise ValueError(
                "Active bin count exceeds total bin count"
            )

        if self.active_employees > self.total_employees:
            raise ValueError(
                "Active employees exceed total employees"
            )

        if self.active_robots > self.total_robots:
            raise ValueError(
                "Active robots exceed total robots"
            )

        if (
            self.temperature_min_c is not None
            and self.temperature_max_c is not None
            and self.temperature_min_c > self.temperature_max_c
        ):
            raise ValueError(
                "Minimum temperature exceeds maximum"
            )

        if (
            self.humidity_min_percent is not None
            and self.humidity_max_percent is not None
            and self.humidity_min_percent
            > self.humidity_max_percent
        ):
            raise ValueError(
                "Minimum humidity exceeds maximum"
            )

        for field in (
            "humidity_min_percent",
            "humidity_max_percent",
            "current_humidity_percent",
        ):
            value = getattr(self, field)
            if value is not None:
                percentage_value(value, field)

    # ========================================================
    # UPDATE PROFILE
    # ========================================================

    def update_profile(
        self,
        *,
        actor_id: str,
        warehouse_name: str | None = None,
        description: str | None = None,
        manager_user_id: str | None = None,
        contact_email: str | None = None,
        contact_phone: str | None = None,
    ) -> None:
        self._ensure_editable()

        if warehouse_name is not None:
            self.warehouse_name = required_text(
                warehouse_name,
                "Warehouse name",
            )

        if description is not None:
            self.description = optional_text(description)

        if manager_user_id is not None:
            self.manager_user_id = optional_text(
                manager_user_id
            )

        if contact_email is not None:
            self.contact_email = optional_text(contact_email)

        if contact_phone is not None:
            self.contact_phone = optional_text(contact_phone)

        self._record_event(
            WarehouseEventType.UPDATED,
            actor_id=actor_id,
            details={"section": "profile"},
        )

    # ========================================================
    # APPROVAL WORKFLOW
    # ========================================================

    def request_approval(
        self,
        *,
        actor_id: str,
        approval_request_id: str,
    ) -> None:
        self._ensure_editable()
        self._require_status(WarehouseStatus.DRAFT)

        self.validate_warehouse()

        self.approval_request_id = required_text(
            approval_request_id,
            "Approval request ID",
        )
        self.approval_status = WarehouseApprovalStatus.PENDING
        self.status = WarehouseStatus.PENDING_APPROVAL

        self._record_event(
            WarehouseEventType.APPROVAL_REQUESTED,
            actor_id=actor_id,
            details={
                "approval_request_id": approval_request_id,
            },
        )

    def approve(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()
        self._require_status(
            WarehouseStatus.PENDING_APPROVAL
        )

        if self.approval_status != WarehouseApprovalStatus.PENDING:
            raise ValueError("Approval is not pending")

        self.approval_status = WarehouseApprovalStatus.APPROVED
        self.approved_by = required_text(
            actor_id,
            "Approver ID",
        )
        self.approved_at = utc_now()
        self.rejection_reason = None
        self.status = WarehouseStatus.APPROVED

        self._record_event(
            WarehouseEventType.APPROVED,
            actor_id=actor_id,
        )

    def reject(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_editable()
        self._require_status(
            WarehouseStatus.PENDING_APPROVAL
        )

        self.approval_status = WarehouseApprovalStatus.REJECTED
        self.rejection_reason = required_text(
            reason,
            "Rejection reason",
        )
        self.status = WarehouseStatus.DRAFT

        self._record_event(
            WarehouseEventType.REJECTED,
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # SETUP
    # ========================================================

    def start_setup(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()
        self._require_status(WarehouseStatus.APPROVED)

        self.status = WarehouseStatus.SETUP
        self.setup_started_at = utc_now()

        self._record_event(
            WarehouseEventType.SETUP_STARTED,
            actor_id=actor_id,
        )

    def request_inspection(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        self._require_status(
            WarehouseStatus.SETUP,
            WarehouseStatus.INACTIVE,
            WarehouseStatus.INSPECTION_REQUIRED,
        )

        self.status = WarehouseStatus.INSPECTION_REQUIRED
        self.inspection_status = WarehouseInspectionStatus.PENDING

        self._record_event(
            WarehouseEventType.INSPECTION_REQUESTED,
            actor_id=actor_id,
        )

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
            WarehouseStatus.INSPECTION_REQUIRED
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
                WarehouseInspectionStatus.PASSED
            )
            self.status = WarehouseStatus.ACTIVE
            self.activated_at = utc_now()
            self._refresh_capacity_status()
            event = WarehouseEventType.INSPECTION_PASSED
        else:
            self.inspection_status = (
                WarehouseInspectionStatus.FAILED
            )
            self.status = WarehouseStatus.INACTIVE
            event = WarehouseEventType.INSPECTION_FAILED

        self._record_event(
            event,
            actor_id=inspector_id,
            details={"passed": passed},
        )

    # ========================================================
    # CAPACITY MANAGEMENT
    # ========================================================

    def configure_capacity(
        self,
        *,
        actor_id: str,
        capacity_units: Any,
        capacity_weight_kg: Any,
        capacity_volume_m3: Any,
        pallet_capacity: int,
    ) -> None:
        self._ensure_editable()

        units = decimal_value(
            capacity_units,
            "Capacity units",
        )
        weight = decimal_value(
            capacity_weight_kg,
            "Capacity weight",
        )
        volume = decimal_value(
            capacity_volume_m3,
            "Capacity volume",
        )

        if pallet_capacity < 0:
            raise ValueError(
                "Pallet capacity cannot be negative"
            )

        if units < self.occupied_units + self.reserved_units:
            raise ValueError(
                "Capacity below committed inventory"
            )

        if weight < self.occupied_weight_kg:
            raise ValueError(
                "Weight capacity below occupied weight"
            )

        if volume < self.occupied_volume_m3:
            raise ValueError(
                "Volume capacity below occupied volume"
            )

        if pallet_capacity < self.occupied_pallets:
            raise ValueError(
                "Pallet capacity below occupied pallets"
            )

        self.total_capacity_units = units
        self.total_capacity_weight_kg = weight
        self.total_capacity_volume_m3 = volume
        self.total_pallet_capacity = pallet_capacity

        self._refresh_capacity_status()

        self._record_event(
            WarehouseEventType.CAPACITY_UPDATED,
            actor_id=actor_id,
            details={
                "capacity_units": str(units),
                "capacity_weight_kg": str(weight),
                "capacity_volume_m3": str(volume),
                "pallet_capacity": pallet_capacity,
            },
        )

    # ========================================================
    # INVENTORY SNAPSHOT
    # ========================================================

    def update_inventory_snapshot(
        self,
        *,
        actor_id: str,
        occupied_units: Any,
        reserved_units: Any,
        occupied_weight_kg: Any,
        occupied_volume_m3: Any,
        occupied_pallets: int,
        inventory_value: Any,
        available_inventory_units: Any | None = None,
        distinct_skus: int | None = None,
        source: str = "inventory_service",
    ) -> None:
        self._ensure_editable()

        units = decimal_value(
            occupied_units,
            "Occupied units",
        )
        reserved = decimal_value(
            reserved_units,
            "Reserved units",
        )
        weight = decimal_value(
            occupied_weight_kg,
            "Occupied weight",
        )
        volume = decimal_value(
            occupied_volume_m3,
            "Occupied volume",
        )
        value = decimal_value(
            inventory_value,
            "Inventory value",
        )

        if occupied_pallets < 0:
            raise ValueError(
                "Occupied pallets cannot be negative"
            )

        if units + reserved > self.total_capacity_units:
            raise ValueError(
                "Inventory exceeds warehouse capacity"
            )

        if weight > self.total_capacity_weight_kg:
            raise ValueError(
                "Inventory exceeds weight capacity"
            )

        if volume > self.total_capacity_volume_m3:
            raise ValueError(
                "Inventory exceeds volume capacity"
            )

        if occupied_pallets > self.total_pallet_capacity:
            raise ValueError(
                "Inventory exceeds pallet capacity"
            )

        if distinct_skus is not None:
            if distinct_skus < 0:
                raise ValueError(
                    "Distinct SKU count cannot be negative"
                )
            if (
                self.maximum_distinct_skus is not None
                and distinct_skus > self.maximum_distinct_skus
            ):
                raise ValueError(
                    "Distinct SKU limit exceeded"
                )

        available = None
        if available_inventory_units is not None:
            available = decimal_value(
                available_inventory_units,
                "Available inventory units",
            )
            if available > units:
                raise ValueError(
                    "Available inventory cannot exceed occupied units"
                )

        self.occupied_units = units
        self.reserved_units = reserved
        self.occupied_weight_kg = weight
        self.occupied_volume_m3 = volume
        self.occupied_pallets = occupied_pallets
        self.total_inventory_value = value

        if available is not None:
            self.available_inventory_units = available

        if distinct_skus is not None:
            self.current_distinct_skus = distinct_skus

        self.inventory_snapshot_at = utc_now()
        self.inventory_snapshot_source = required_text(
            source,
            "Snapshot source",
        )

        self._refresh_capacity_status()

        self._record_event(
            WarehouseEventType.INVENTORY_SNAPSHOT_UPDATED,
            actor_id=actor_id,
            details={
                "occupied_units": str(units),
                "reserved_units": str(reserved),
                "inventory_value": str(value),
                "source": source,
            },
        )

        # Snapshot must be derived from committed inventory
        # transactions. This method does not post stock movements.

    # ========================================================
    # UPDATE BIN COUNTS
    # ========================================================

    def update_bin_counts(
        self,
        *,
        actor_id: str,
        total_bins: int,
        active_bins: int,
        total_zones: int | None = None,
    ) -> None:
        self._ensure_editable()

        if total_bins < 0 or active_bins < 0:
            raise ValueError("Bin counts cannot be negative")

        if active_bins > total_bins:
            raise ValueError(
                "Active bins exceed total bins"
            )

        self.total_bins = total_bins
        self.active_bins = active_bins

        if total_zones is not None:
            if total_zones < 0:
                raise ValueError(
                    "Zone count cannot be negative"
                )
            self.total_zones = total_zones

        self._record_event(
            WarehouseEventType.UPDATED,
            actor_id=actor_id,
            details={
                "section": "bin_counts",
                "total_bins": total_bins,
                "active_bins": active_bins,
            },
        )

    # ========================================================
    # WORKFORCE
    # ========================================================

    def update_workforce(
        self,
        *,
        actor_id: str,
        total_employees: int,
        active_employees: int,
        role_counts: dict[str, int] | None = None,
    ) -> None:
        self._ensure_editable()

        if total_employees < 0 or active_employees < 0:
            raise ValueError(
                "Employee counts cannot be negative"
            )

        if active_employees > total_employees:
            raise ValueError(
                "Active employees exceed total employees"
            )

        allowed_roles = {
            "warehouse_operators",
            "pickers",
            "packers",
            "forklift_operators",
            "security_staff",
            "maintenance_staff",
        }

        if role_counts is not None:
            for role, count in role_counts.items():
                if role not in allowed_roles:
                    raise ValueError(
                        f"Unsupported workforce role: {role}"
                    )
                if (
                    not isinstance(count, int)
                    or isinstance(count, bool)
                    or count < 0
                ):
                    raise ValueError(
                        f"Invalid count for {role}"
                    )

        self.total_employees = total_employees
        self.active_employees = active_employees

        for role, count in (role_counts or {}).items():
            setattr(self, role, count)

        self._record_event(
            WarehouseEventType.WORKFORCE_UPDATED,
            actor_id=actor_id,
            details={
                "total_employees": total_employees,
                "active_employees": active_employees,
                "role_counts": role_counts or {},
            },
        )

    # ========================================================
    # ROBOTICS
    # ========================================================

    def update_robotics(
        self,
        *,
        actor_id: str,
        total_robots: int,
        active_robots: int,
        robot_ids: list[str] | None = None,
    ) -> None:
        self._ensure_editable()

        if total_robots < 0 or active_robots < 0:
            raise ValueError(
                "Robot counts cannot be negative"
            )

        if active_robots > total_robots:
            raise ValueError(
                "Active robots exceed total robots"
            )

        if robot_ids is not None:
            normalized = [
                required_text(robot_id, "Robot ID")
                for robot_id in robot_ids
            ]
            if len(set(normalized)) != len(normalized):
                raise ValueError("Duplicate robot IDs")
            if len(normalized) > total_robots:
                raise ValueError(
                    "Robot IDs exceed total robots"
                )
            self.robot_ids = normalized

        self.total_robots = total_robots
        self.active_robots = active_robots
        self.robotics_enabled = total_robots > 0

        self._record_event(
            WarehouseEventType.EQUIPMENT_UPDATED,
            actor_id=actor_id,
            details={
                "total_robots": total_robots,
                "active_robots": active_robots,
            },
        )

    # ========================================================
    # SENSOR MONITORING
    # ========================================================

    def update_sensor_data(
        self,
        *,
        sensor_data: dict[str, Any],
        temperature_c: Any | None = None,
        humidity_percent: Any | None = None,
        actor_id: str | None = None,
    ) -> None:
        self._ensure_editable()

        if not isinstance(sensor_data, dict):
            raise ValueError(
                "Sensor data must be a dictionary"
            )

        temperature = self.current_temperature_c
        humidity = self.current_humidity_percent

        if temperature_c is not None:
            temperature = decimal_value(
                temperature_c,
                "Temperature",
                minimum=None,
            )

        if humidity_percent is not None:
            humidity = percentage_value(
                humidity_percent,
                "Humidity",
            )

        self.sensor_data = json_safe(sensor_data)
        self.current_temperature_c = temperature
        self.current_humidity_percent = humidity
        self.sensor_updated_at = utc_now()

        self.temperature_alert_active = (
            not self.is_temperature_compliant
        )
        self.humidity_alert_active = (
            not self.is_humidity_compliant
        )

        self._record_event(
            WarehouseEventType.SENSOR_UPDATED,
            actor_id=actor_id,
            details={
                "temperature_alert": self.temperature_alert_active,
                "humidity_alert": self.humidity_alert_active,
            },
        )

        if self.temperature_alert_active:
            self._record_event(
                WarehouseEventType.TEMPERATURE_ALERT,
                actor_id=actor_id,
            )

        if self.humidity_alert_active:
            self._record_event(
                WarehouseEventType.HUMIDITY_ALERT,
                actor_id=actor_id,
            )

        # Alert delivery and incident creation belong to
        # the notification/incident orchestration service.

    # ========================================================
    # AI RISK ASSESSMENT
    # ========================================================

    def update_ai_risk(
        self,
        *,
        actor_id: str,
        risk_score: Any,
        health_score: Any | None = None,
        factors: list[dict[str, Any]] | None = None,
        recommendations: list[dict[str, Any]] | None = None,
    ) -> None:
        self._ensure_editable()

        score = score_value(risk_score, "Risk score")

        if score >= Decimal("0.85"):
            level = WarehouseRiskLevel.CRITICAL
        elif score >= Decimal("0.65"):
            level = WarehouseRiskLevel.HIGH
        elif score >= Decimal("0.35"):
            level = WarehouseRiskLevel.MEDIUM
        else:
            level = WarehouseRiskLevel.LOW

        if factors is not None and not isinstance(factors, list):
            raise ValueError("Risk factors must be a list")

        if (
            recommendations is not None
            and not isinstance(recommendations, list)
        ):
            raise ValueError(
                "Recommendations must be a list"
            )

        health = (
            score_value(health_score, "Health score")
            if health_score is not None
            else self.health_score
        )

        self.risk_score = score
        self.risk_level = level
        self.health_score = health

        if factors is not None:
            self.risk_factors = json_safe(factors)

        if recommendations is not None:
            self.ai_recommendations = json_safe(
                recommendations
            )

        self.ai_enabled = True
        self.ai_last_analyzed_at = utc_now()

        self._record_event(
            WarehouseEventType.RISK_UPDATED,
            actor_id=actor_id,
            details={
                "risk_score": str(score),
                "risk_level": level.value,
            },
        )

    # ========================================================
    # PERFORMANCE METRICS
    # ========================================================

    def update_performance(
        self,
        *,
        actor_id: str,
        order_accuracy_percent: Any | None = None,
        on_time_dispatch_percent: Any | None = None,
        inventory_accuracy_percent: Any | None = None,
        efficiency_score: Any | None = None,
    ) -> None:
        self._ensure_editable()

        updates = {
            "order_accuracy_percent": order_accuracy_percent,
            "on_time_dispatch_percent": on_time_dispatch_percent,
            "inventory_accuracy_percent": inventory_accuracy_percent,
        }

        validated: dict[str, Decimal] = {}

        for field, value in updates.items():
            if value is not None:
                validated[field] = percentage_value(
                    value,
                    field,
                )

        if efficiency_score is not None:
            validated["warehouse_efficiency_score"] = (
                score_value(
                    efficiency_score,
                    "Efficiency score",
                )
            )

        for field, value in validated.items():
            setattr(self, field, value)

        self.performance_updated_at = utc_now()

        self._record_event(
            WarehouseEventType.UPDATED,
            actor_id=actor_id,
            details={
                "section": "performance",
                "metrics": json_safe(validated),
            },
        )

    # ========================================================
    # MAINTENANCE
    # ========================================================

    def schedule_maintenance(
        self,
        *,
        actor_id: str,
        reason: str,
        due_at: datetime | None = None,
    ) -> None:
        self._ensure_editable()

        self.maintenance_reason = required_text(
            reason,
            "Maintenance reason",
        )
        self.maintenance_status = (
            WarehouseMaintenanceStatus.SCHEDULED
        )
        self.next_maintenance_due_at = due_at

        self._record_event(
            WarehouseEventType.MAINTENANCE_SCHEDULED,
            actor_id=actor_id,
            details={"reason": reason},
        )

    def start_maintenance(
        self,
        *,
        actor_id: str,
        reason: str | None = None,
    ) -> None:
        self._ensure_editable()

        self._require_status(
            WarehouseStatus.ACTIVE,
            WarehouseStatus.AT_CAPACITY,
            WarehouseStatus.LIMITED_OPERATIONS,
            WarehouseStatus.TEMPORARILY_CLOSED,
            WarehouseStatus.INACTIVE,
        )

        if not self.is_empty:
            raise ValueError(
                "Full-facility maintenance requires "
                "inventory relocation or a separate "
                "approved operational safety plan"
            )

        if reason is not None:
            self.maintenance_reason = required_text(
                reason,
                "Maintenance reason",
            )

        self.status = WarehouseStatus.MAINTENANCE
        self.maintenance_status = (
            WarehouseMaintenanceStatus.IN_PROGRESS
        )

        self._record_event(
            WarehouseEventType.MAINTENANCE_STARTED,
            actor_id=actor_id,
        )

    def complete_maintenance(
        self,
        *,
        actor_id: str,
        description: str,
        cost: Any = 0,
        next_due_at: datetime | None = None,
    ) -> None:
        self._ensure_editable()
        self._require_status(WarehouseStatus.MAINTENANCE)

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
        }

        history = list(self.maintenance_history or [])
        history.append(record)

        self.maintenance_history = history
        self.last_maintenance_at = utc_now()
        self.next_maintenance_due_at = next_due_at
        self.maintenance_reason = None
        self.maintenance_status = (
            WarehouseMaintenanceStatus.COMPLETED
        )

        self.status = WarehouseStatus.INSPECTION_REQUIRED
        self.inspection_status = WarehouseInspectionStatus.PENDING

        self._record_event(
            WarehouseEventType.MAINTENANCE_COMPLETED,
            actor_id=actor_id,
            details=record,
        )

    # ========================================================
    # LIMITED OPERATIONS
    # ========================================================

    def limit_operations(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_editable()

        self._require_status(
            WarehouseStatus.ACTIVE,
            WarehouseStatus.AT_CAPACITY,
        )

        self.status = WarehouseStatus.LIMITED_OPERATIONS
        self.closure_reason = required_text(
            reason,
            "Restriction reason",
        )

        self._record_event(
            WarehouseEventType.LIMITED_OPERATIONS,
            actor_id=actor_id,
            details={"reason": reason},
        )

    def restore_operations(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        self._require_status(
            WarehouseStatus.LIMITED_OPERATIONS
        )

        if (
            self.inspection_status
            != WarehouseInspectionStatus.PASSED
        ):
            raise ValueError(
                "Valid inspection required"
            )

        if self.is_maintenance_due or self.is_high_risk:
            raise ValueError(
                "Maintenance or high-risk condition "
                "prevents restoration"
            )

        self.status = WarehouseStatus.ACTIVE
        self.closure_reason = None
        self._refresh_capacity_status()

        self._record_event(
            WarehouseEventType.OPERATIONS_RESTORED,
            actor_id=actor_id,
        )

    # ========================================================
    # TEMPORARY CLOSURE
    # ========================================================

    def temporarily_close(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_editable()

        self._require_status(
            WarehouseStatus.ACTIVE,
            WarehouseStatus.AT_CAPACITY,
            WarehouseStatus.LIMITED_OPERATIONS,
        )

        self.closure_reason = required_text(
            reason,
            "Closure reason",
        )
        self.temporarily_closed_at = utc_now()
        self.status = WarehouseStatus.TEMPORARILY_CLOSED

        self._record_event(
            WarehouseEventType.TEMPORARILY_CLOSED,
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # SUSPENSION
    # ========================================================

    def suspend(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_editable()

        self.suspension_reason = required_text(
            reason,
            "Suspension reason",
        )
        self.suspended_at = utc_now()
        self.status = WarehouseStatus.SUSPENDED

        self._record_event(
            WarehouseEventType.SUSPENDED,
            actor_id=actor_id,
            details={"reason": reason},
        )

    def request_reopening(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        self._require_status(
            WarehouseStatus.TEMPORARILY_CLOSED,
            WarehouseStatus.SUSPENDED,
        )

        self.status = WarehouseStatus.INSPECTION_REQUIRED
        self.inspection_status = WarehouseInspectionStatus.PENDING

        self._record_event(
            WarehouseEventType.REOPEN_REQUESTED,
            actor_id=actor_id,
        )

    # ========================================================
    # DEACTIVATION
    # ========================================================

    def deactivate(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        self._require_status(
            WarehouseStatus.ACTIVE,
            WarehouseStatus.AT_CAPACITY,
            WarehouseStatus.TEMPORARILY_CLOSED,
            WarehouseStatus.SUSPENDED,
        )

        if not self.is_empty:
            raise ValueError(
                "Warehouse must have no inventory "
                "or reservations before deactivation"
            )

        self.status = WarehouseStatus.INACTIVE
        self.deactivated_at = utc_now()

        self._record_event(
            WarehouseEventType.DEACTIVATED,
            actor_id=actor_id,
        )

    # ========================================================
    # DECOMMISSION
    # ========================================================

    def decommission(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_editable()
        self._require_status(WarehouseStatus.INACTIVE)

        if not self.is_empty:
            raise ValueError(
                "Warehouse must be empty before decommissioning"
            )

        self.decommission_reason = required_text(
            reason,
            "Decommission reason",
        )
        self.decommissioned_at = utc_now()
        self.status = WarehouseStatus.DECOMMISSIONED

        self._record_event(
            WarehouseEventType.DECOMMISSIONED,
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
            raise ValueError("Warehouse is deleted")

        self._require_status(
            WarehouseStatus.DECOMMISSIONED
        )

        self.status = WarehouseStatus.ARCHIVED
        self.archived_at = utc_now()

        self._record_event(
            WarehouseEventType.ARCHIVED,
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
            raise ValueError("Warehouse already deleted")

        self._require_status(
            WarehouseStatus.DRAFT,
            WarehouseStatus.ARCHIVED,
        )

        if not self.is_empty:
            raise ValueError(
                "Cannot delete warehouse containing inventory"
            )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = required_text(
            actor_id,
            "Actor ID",
        )

        self._record_event(
            WarehouseEventType.SOFT_DELETED,
            actor_id=actor_id,
        )

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(
        self,
        *,
        include_inventory: bool = False,
        include_operations: bool = False,
        include_financials: bool = False,
        include_ai: bool = False,
        include_sensors: bool = False,
        include_history: bool = False,
        include_sensitive: bool = False,
    ) -> dict[str, Any]:

        data = {
            "id": self.id,
            "organization_id": self.organization_id,
            "warehouse_code": self.warehouse_code,
            "warehouse_name": self.warehouse_name,
            "description": self.description,
            "status": enum_value(self.status),
            "warehouse_type": enum_value(self.warehouse_type),
            "ownership_type": enum_value(self.ownership_type),
            "priority": enum_value(self.priority),
            "condition": enum_value(self.condition),
            "region_id": self.region_id,
            "parent_warehouse_id": self.parent_warehouse_id,
            "manager_user_id": self.manager_user_id,
            "city": self.city,
            "district": self.district,
            "state": self.state,
            "country": self.country,
            "country_code": self.country_code,
            "postal_code": self.postal_code,
            "timezone_name": self.timezone_name,
            "facility_area_sq_m": (
                str(self.facility_area_sq_m)
                if self.facility_area_sq_m is not None
                else None
            ),
            "storage_area_sq_m": (
                str(self.storage_area_sq_m)
                if self.storage_area_sq_m is not None
                else None
            ),
            "number_of_floors": self.number_of_floors,
            "loading_docks": self.loading_docks,
            "unloading_docks": self.unloading_docks,
            "total_zones": self.total_zones,
            "total_bins": self.total_bins,
            "active_bins": self.active_bins,
            "total_capacity_units": str(
                self.total_capacity_units
            ),
            "occupied_units": str(self.occupied_units),
            "reserved_units": str(self.reserved_units),
            "available_capacity_units": str(
                self.available_capacity_units
            ),
            "total_capacity_weight_kg": str(
                self.total_capacity_weight_kg
            ),
            "occupied_weight_kg": str(
                self.occupied_weight_kg
            ),
            "available_weight_kg": str(
                self.available_weight_kg
            ),
            "total_capacity_volume_m3": str(
                self.total_capacity_volume_m3
            ),
            "occupied_volume_m3": str(
                self.occupied_volume_m3
            ),
            "available_volume_m3": str(
                self.available_volume_m3
            ),
            "total_pallet_capacity": self.total_pallet_capacity,
            "occupied_pallets": self.occupied_pallets,
            "available_pallets": self.available_pallets,
            "utilization_percent": str(
                self.utilization_percent
            ),
            "committed_utilization_percent": str(
                self.committed_utilization_percent
            ),
            "is_at_capacity": self.is_at_capacity,
            "is_empty": self.is_empty,
            "is_operational": self.is_operational,
            "can_receive_inventory": self.can_receive_inventory,
            "automation_level": enum_value(
                self.automation_level
            ),
            "wms_enabled": self.wms_enabled,
            "erp_integrated": self.erp_integrated,
            "robotics_enabled": self.robotics_enabled,
            "total_robots": self.total_robots,
            "active_robots": self.active_robots,
            "total_employees": self.total_employees,
            "active_employees": self.active_employees,
            "cold_storage_enabled": self.cold_storage_enabled,
            "freezer_storage_enabled": self.freezer_storage_enabled,
            "temperature_control_enabled": (
                self.temperature_control_enabled
            ),
            "humidity_control_enabled": (
                self.humidity_control_enabled
            ),
            "inspection_status": enum_value(
                self.inspection_status
            ),
            "maintenance_status": enum_value(
                self.maintenance_status
            ),
            "last_inspection_at": iso(self.last_inspection_at),
            "next_inspection_due_at": iso(
                self.next_inspection_due_at
            ),
            "last_maintenance_at": iso(
                self.last_maintenance_at
            ),
            "next_maintenance_due_at": iso(
                self.next_maintenance_due_at
            ),
            "risk_level": enum_value(self.risk_level),
            "risk_score": (
                str(self.risk_score)
                if self.risk_score is not None
                else None
            ),
            "health_score": (
                str(self.health_score)
                if self.health_score is not None
                else None
            ),
            "is_high_risk": self.is_high_risk,
            "is_maintenance_due": self.is_maintenance_due,
            "approval_status": enum_value(
                self.approval_status
            ),
            "ai_enabled": self.ai_enabled,
            "digital_twin_enabled": self.digital_twin_enabled,
            "tags": self.tags,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "version": self.version,
        }

        if include_inventory:
            data.update({
                "total_inventory_value": str(
                    self.total_inventory_value
                ),
                "available_inventory_units": str(
                    self.available_inventory_units
                ),
                "damaged_inventory_units": str(
                    self.damaged_inventory_units
                ),
                "quarantined_inventory_units": str(
                    self.quarantined_inventory_units
                ),
                "incoming_inventory_units": str(
                    self.incoming_inventory_units
                ),
                "outgoing_inventory_units": str(
                    self.outgoing_inventory_units
                ),
                "current_distinct_skus": (
                    self.current_distinct_skus
                ),
                "maximum_distinct_skus": (
                    self.maximum_distinct_skus
                ),
                "inventory_snapshot_at": iso(
                    self.inventory_snapshot_at
                ),
                "inventory_snapshot_source": (
                    self.inventory_snapshot_source
                ),
            })

        if include_operations:
            data.update({
                "daily_receiving_capacity_units": str(
                    self.daily_receiving_capacity_units
                ),
                "daily_shipping_capacity_units": str(
                    self.daily_shipping_capacity_units
                ),
                "daily_picking_capacity_units": str(
                    self.daily_picking_capacity_units
                ),
                "daily_packing_capacity_units": str(
                    self.daily_packing_capacity_units
                ),
                "operating_24x7": self.operating_24x7,
                "operating_schedule": self.operating_schedule,
                "total_orders_processed": (
                    self.total_orders_processed
                ),
                "total_shipments_dispatched": (
                    self.total_shipments_dispatched
                ),
                "total_receipts_processed": (
                    self.total_receipts_processed
                ),
                "order_accuracy_percent": (
                    str(self.order_accuracy_percent)
                    if self.order_accuracy_percent is not None
                    else None
                ),
                "on_time_dispatch_percent": (
                    str(self.on_time_dispatch_percent)
                    if self.on_time_dispatch_percent is not None
                    else None
                ),
                "inventory_accuracy_percent": (
                    str(self.inventory_accuracy_percent)
                    if self.inventory_accuracy_percent is not None
                    else None
                ),
                "warehouse_efficiency_score": (
                    str(self.warehouse_efficiency_score)
                    if self.warehouse_efficiency_score is not None
                    else None
                ),
                "performance_updated_at": iso(
                    self.performance_updated_at
                ),
            })

        if include_financials:
            data.update({
                "currency": self.currency,
                "monthly_rent_cost": str(
                    self.monthly_rent_cost
                ),
                "monthly_utilities_cost": str(
                    self.monthly_utilities_cost
                ),
                "monthly_labor_cost": str(
                    self.monthly_labor_cost
                ),
                "monthly_maintenance_cost": str(
                    self.monthly_maintenance_cost
                ),
                "monthly_operating_cost": str(
                    self.monthly_operating_cost
                ),
                "estimated_storage_cost_per_unit": (
                    str(self.estimated_storage_cost_per_unit)
                    if self.estimated_storage_cost_per_unit
                    is not None
                    else None
                ),
                "estimated_fulfillment_cost_per_order": (
                    str(self.estimated_fulfillment_cost_per_order)
                    if self.estimated_fulfillment_cost_per_order
                    is not None
                    else None
                ),
            })

        if include_ai:
            data.update({
                "predictive_analytics_enabled": (
                    self.predictive_analytics_enabled
                ),
                "predicted_utilization_percent": (
                    str(self.predicted_utilization_percent)
                    if self.predicted_utilization_percent
                    is not None
                    else None
                ),
                "predicted_congestion_score": (
                    str(self.predicted_congestion_score)
                    if self.predicted_congestion_score
                    is not None
                    else None
                ),
                "predicted_capacity_shortage_units": (
                    str(self.predicted_capacity_shortage_units)
                    if self.predicted_capacity_shortage_units
                    is not None
                    else None
                ),
                "predicted_capacity_shortage_at": iso(
                    self.predicted_capacity_shortage_at
                ),
                "ai_model_id": self.ai_model_id,
                "ai_model_version": self.ai_model_version,
                "ai_insights": self.ai_insights,
                "ai_recommendations": self.ai_recommendations,
                "risk_factors": self.risk_factors,
                "ai_last_analyzed_at": iso(
                    self.ai_last_analyzed_at
                ),
            })

        if include_sensors:
            data.update({
                "temperature_min_c": (
                    str(self.temperature_min_c)
                    if self.temperature_min_c is not None
                    else None
                ),
                "temperature_max_c": (
                    str(self.temperature_max_c)
                    if self.temperature_max_c is not None
                    else None
                ),
                "current_temperature_c": (
                    str(self.current_temperature_c)
                    if self.current_temperature_c is not None
                    else None
                ),
                "humidity_min_percent": (
                    str(self.humidity_min_percent)
                    if self.humidity_min_percent is not None
                    else None
                ),
                "humidity_max_percent": (
                    str(self.humidity_max_percent)
                    if self.humidity_max_percent is not None
                    else None
                ),
                "current_humidity_percent": (
                    str(self.current_humidity_percent)
                    if self.current_humidity_percent is not None
                    else None
                ),
                "temperature_alert_active": (
                    self.temperature_alert_active
                ),
                "humidity_alert_active": (
                    self.humidity_alert_active
                ),
                "sensor_ids": self.sensor_ids,
                "sensor_data": self.sensor_data,
                "sensor_updated_at": iso(
                    self.sensor_updated_at
                ),
            })

        if include_history:
            data.update({
                "event_history": self.event_history,
                "maintenance_history": self.maintenance_history,
                "warehouse_metadata": self.warehouse_metadata,
                "automation_metadata": self.automation_metadata,
                "workforce_metadata": self.workforce_metadata,
                "security_metadata": self.security_metadata,
                "integrations_metadata": (
                    self.integrations_metadata
                ),
                "closure_reason": self.closure_reason,
                "suspension_reason": self.suspension_reason,
                "decommission_reason": (
                    self.decommission_reason
                ),
            })

        if include_sensitive:
            data.update({
                "address_line_1": self.address_line_1,
                "address_line_2": self.address_line_2,
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
                "contact_name": self.contact_name,
                "contact_email": self.contact_email,
                "contact_phone": self.contact_phone,
                "supervisor_user_id": self.supervisor_user_id,
                "logistics_provider_id": (
                    self.logistics_provider_id
                ),
                "supplier_id": self.supplier_id,
                "approval_request_id": (
                    self.approval_request_id
                ),
                "approved_by": self.approved_by,
                "approved_at": iso(self.approved_at),
                "rejection_reason": self.rejection_reason,
                "compliance_documents": (
                    self.compliance_documents
                ),
                "created_by": self.created_by,
                "updated_by": self.updated_by,
                "is_deleted": self.is_deleted,
                "deleted_at": iso(self.deleted_at),
                "deleted_by": self.deleted_by,
            })

        return data

    def __repr__(self) -> str:
        return (
            f"<Warehouse("
            f"id={self.id!r}, "
            f"code={self.warehouse_code!r}, "
            f"name={self.warehouse_name!r}, "
            f"status={enum_value(self.status)!r}"
            f")>"
        )