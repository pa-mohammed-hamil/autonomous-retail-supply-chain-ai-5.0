from __future__ import annotations

# backend/models/warehouse_bin.py


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


def generate_bin_code() -> str:
    return f"BIN-{uuid.uuid4().hex[:10].upper()}"


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
        raise ValueError("Expected a string")

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
    if value is None or isinstance(value, (str, int, bool)):
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
        f"Unsupported JSON type: {type(value).__name__}"
    )


# ============================================================
# ENUMS
# ============================================================

class WarehouseBinStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    AVAILABLE = "available"
    RESERVED = "reserved"
    OCCUPIED = "occupied"
    FULL = "full"
    BLOCKED = "blocked"
    QUARANTINED = "quarantined"
    INSPECTION_REQUIRED = "inspection_required"
    MAINTENANCE = "maintenance"
    INACTIVE = "inactive"
    DECOMMISSIONED = "decommissioned"
    ARCHIVED = "archived"


class WarehouseBinType(str, enum.Enum):
    STANDARD = "standard"
    PALLET = "pallet"
    SHELF = "shelf"
    RACK = "rack"
    FLOOR = "floor"
    BULK = "bulk"
    PICKING = "picking"
    PUTAWAY = "putaway"
    RECEIVING = "receiving"
    SHIPPING = "shipping"
    STAGING = "staging"
    RETURNS = "returns"
    QUARANTINE = "quarantine"
    DAMAGED_GOODS = "damaged_goods"
    COLD_STORAGE = "cold_storage"
    FREEZER = "freezer"
    HAZARDOUS = "hazardous"
    HIGH_VALUE = "high_value"
    AUTOMATED = "automated"
    ROBOTIC = "robotic"
    OTHER = "other"


class WarehouseBinZoneType(str, enum.Enum):
    GENERAL = "general"
    RECEIVING = "receiving"
    STORAGE = "storage"
    PICKING = "picking"
    PACKING = "packing"
    SHIPPING = "shipping"
    COLD_CHAIN = "cold_chain"
    HAZARDOUS = "hazardous"
    HIGH_SECURITY = "high_security"
    RETURNS = "returns"
    QUALITY_CONTROL = "quality_control"
    QUARANTINE = "quarantine"
    AUTOMATED = "automated"
    OTHER = "other"


class WarehouseBinPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"


class WarehouseBinCondition(str, enum.Enum):
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    DAMAGED = "damaged"
    UNKNOWN = "unknown"


class WarehouseBinRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class WarehouseBinTemperatureMode(str, enum.Enum):
    AMBIENT = "ambient"
    CHILLED = "chilled"
    FROZEN = "frozen"
    CONTROLLED = "controlled"
    HEATED = "heated"
    OTHER = "other"


class WarehouseBinAutomationType(str, enum.Enum):
    MANUAL = "manual"
    SEMI_AUTOMATED = "semi_automated"
    ASRS = "asrs"
    ROBOTIC = "robotic"
    CONVEYOR = "conveyor"
    SHUTTLE = "shuttle"
    AUTONOMOUS_MOBILE_ROBOT = "autonomous_mobile_robot"
    OTHER = "other"


class WarehouseBinEventType(str, enum.Enum):
    CREATED = "created"
    UPDATED = "updated"
    ACTIVATED = "activated"
    CAPACITY_UPDATED = "capacity_updated"
    INVENTORY_ADDED = "inventory_added"
    INVENTORY_REMOVED = "inventory_removed"
    INVENTORY_RESERVED = "inventory_reserved"
    RESERVATION_RELEASED = "reservation_released"
    STOCK_ADJUSTED = "stock_adjusted"
    LOCATION_UPDATED = "location_updated"
    SENSOR_UPDATED = "sensor_updated"
    TEMPERATURE_ALERT = "temperature_alert"
    HUMIDITY_ALERT = "humidity_alert"
    BLOCKED = "blocked"
    UNBLOCKED = "unblocked"
    QUARANTINED = "quarantined"
    QUARANTINE_RELEASED = "quarantine_released"
    INSPECTION_REQUESTED = "inspection_requested"
    INSPECTION_COMPLETED = "inspection_completed"
    MAINTENANCE_STARTED = "maintenance_started"
    MAINTENANCE_COMPLETED = "maintenance_completed"
    RISK_UPDATED = "risk_updated"
    AI_RECOMMENDATION_ADDED = "ai_recommendation_added"
    DEACTIVATED = "deactivated"
    DECOMMISSIONED = "decommissioned"
    ARCHIVED = "archived"
    SOFT_DELETED = "soft_deleted"


# ============================================================
# WAREHOUSE BIN MODEL
# ============================================================

class WarehouseBin(Base):
    __tablename__ = "warehouse_bins"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "warehouse_id",
            "bin_code",
            name="uq_warehouse_bin_org_warehouse_code",
        ),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_warehouse_bin_org_id",
        ),
        CheckConstraint(
            "capacity_units >= 0",
            name="ck_warehouse_bin_capacity_units",
        ),
        CheckConstraint(
            "occupied_units >= 0",
            name="ck_warehouse_bin_occupied_units",
        ),
        CheckConstraint(
            "reserved_units >= 0",
            name="ck_warehouse_bin_reserved_units",
        ),
        CheckConstraint(
            "occupied_units + reserved_units <= capacity_units",
            name="ck_warehouse_bin_units_capacity",
        ),
        CheckConstraint(
            "capacity_weight_kg >= 0",
            name="ck_warehouse_bin_weight_capacity",
        ),
        CheckConstraint(
            "occupied_weight_kg >= 0",
            name="ck_warehouse_bin_occupied_weight",
        ),
        CheckConstraint(
            "occupied_weight_kg <= capacity_weight_kg",
            name="ck_warehouse_bin_weight_limit",
        ),
        CheckConstraint(
            "capacity_volume_m3 >= 0",
            name="ck_warehouse_bin_volume_capacity",
        ),
        CheckConstraint(
            "occupied_volume_m3 >= 0",
            name="ck_warehouse_bin_occupied_volume",
        ),
        CheckConstraint(
            "occupied_volume_m3 <= capacity_volume_m3",
            name="ck_warehouse_bin_volume_limit",
        ),
        CheckConstraint(
            "max_pallets >= 0",
            name="ck_warehouse_bin_max_pallets",
        ),
        CheckConstraint(
            "occupied_pallets >= 0",
            name="ck_warehouse_bin_occupied_pallets",
        ),
        CheckConstraint(
            "occupied_pallets <= max_pallets",
            name="ck_warehouse_bin_pallet_limit",
        ),
        CheckConstraint(
            "risk_score IS NULL OR "
            "(risk_score >= 0 AND risk_score <= 1)",
            name="ck_warehouse_bin_risk_score",
        ),
        CheckConstraint(
            "health_score IS NULL OR "
            "(health_score >= 0 AND health_score <= 1)",
            name="ck_warehouse_bin_health_score",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_warehouse_bin_version",
        ),
        Index(
            "ix_warehouse_bin_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_warehouse_bin_warehouse_status",
            "warehouse_id",
            "status",
        ),
        Index(
            "ix_warehouse_bin_zone",
            "organization_id",
            "warehouse_id",
            "zone_code",
        ),
        Index(
            "ix_warehouse_bin_type",
            "organization_id",
            "bin_type",
        ),
        Index(
            "ix_warehouse_bin_risk",
            "organization_id",
            "risk_level",
        ),
        Index(
            "ix_warehouse_bin_product",
            "organization_id",
            "primary_product_id",
        ),
        Index(
            "ix_warehouse_bin_last_count",
            "organization_id",
            "last_cycle_count_at",
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

    warehouse_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    bin_code: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default=generate_bin_code,
    )

    bin_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    barcode: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    qr_code: Mapped[str | None] = mapped_column(
        String(250),
        nullable=True,
    )

    # ========================================================
    # CLASSIFICATION
    # ========================================================

    status: Mapped[WarehouseBinStatus] = mapped_column(
        enum_column(
            WarehouseBinStatus,
            "warehouse_bin_status",
        ),
        default=WarehouseBinStatus.DRAFT,
        nullable=False,
    )

    bin_type: Mapped[WarehouseBinType] = mapped_column(
        enum_column(
            WarehouseBinType,
            "warehouse_bin_type",
        ),
        default=WarehouseBinType.STANDARD,
        nullable=False,
    )

    zone_type: Mapped[WarehouseBinZoneType] = mapped_column(
        enum_column(
            WarehouseBinZoneType,
            "warehouse_bin_zone_type",
        ),
        default=WarehouseBinZoneType.GENERAL,
        nullable=False,
    )

    priority: Mapped[WarehouseBinPriority] = mapped_column(
        enum_column(
            WarehouseBinPriority,
            "warehouse_bin_priority",
        ),
        default=WarehouseBinPriority.NORMAL,
        nullable=False,
    )

    condition: Mapped[WarehouseBinCondition] = mapped_column(
        enum_column(
            WarehouseBinCondition,
            "warehouse_bin_condition",
        ),
        default=WarehouseBinCondition.UNKNOWN,
        nullable=False,
    )

    # ========================================================
    # PHYSICAL LOCATION
    # ========================================================

    zone_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    zone_code: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )

    aisle: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )

    rack: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )

    shelf: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )

    level: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )

    position: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )

    floor_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    location_label: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
    )

    coordinate_x: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 4),
        nullable=True,
    )

    coordinate_y: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 4),
        nullable=True,
    )

    coordinate_z: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 4),
        nullable=True,
    )

    # ========================================================
    # CAPACITY
    # ========================================================

    capacity_units: Mapped[Decimal] = mapped_column(
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

    capacity_weight_kg: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    occupied_weight_kg: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    capacity_volume_m3: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    occupied_volume_m3: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    max_pallets: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    occupied_pallets: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    max_distinct_skus: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # ========================================================
    # INVENTORY REFERENCES
    # ========================================================

    primary_product_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    primary_sku: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    product_category_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    inventory_ids: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    allowed_product_ids: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    restricted_product_ids: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    stock_snapshot: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # ========================================================
    # STORAGE CONDITIONS
    # ========================================================

    temperature_mode: Mapped[
        WarehouseBinTemperatureMode
    ] = mapped_column(
        enum_column(
            WarehouseBinTemperatureMode,
            "warehouse_bin_temperature_mode",
        ),
        default=WarehouseBinTemperatureMode.AMBIENT,
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

    # ========================================================
    # SAFETY AND SECURITY
    # ========================================================

    hazardous_material_allowed: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    food_grade_storage: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    pharmaceutical_storage: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    restricted_access: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    requires_supervisor_approval: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    access_role_ids: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    security_level: Mapped[str | None] = mapped_column(
        String(60),
        nullable=True,
    )

    # ========================================================
    # AUTOMATION AND ROBOTICS
    # ========================================================

    automation_type: Mapped[
        WarehouseBinAutomationType
    ] = mapped_column(
        enum_column(
            WarehouseBinAutomationType,
            "warehouse_bin_automation_type",
        ),
        default=WarehouseBinAutomationType.MANUAL,
        nullable=False,
    )

    automation_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    robot_accessible: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    assigned_robot_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    automation_controller_id: Mapped[
        str | None
    ] = mapped_column(
        String(150),
        nullable=True,
    )

    sensor_ids: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # ========================================================
    # INSPECTION AND MAINTENANCE
    # ========================================================

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

    # ========================================================
    # CYCLE COUNTING
    # ========================================================

    last_cycle_count_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    next_cycle_count_due_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_cycle_count_by: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    cycle_count_frequency_days: Mapped[
        int | None
    ] = mapped_column(
        Integer,
        nullable=True,
    )

    cycle_count_variance_units: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(20, 4),
        nullable=True,
    )

    # ========================================================
    # AI INTELLIGENCE
    # ========================================================

    ai_optimization_enabled: Mapped[
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

    risk_level: Mapped[WarehouseBinRiskLevel] = mapped_column(
        enum_column(
            WarehouseBinRiskLevel,
            "warehouse_bin_risk_level",
        ),
        default=WarehouseBinRiskLevel.UNKNOWN,
        nullable=False,
    )

    risk_score: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4),
        nullable=True,
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

    ai_last_analyzed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # OPERATIONS
    # ========================================================

    last_putaway_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_pick_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    total_putaway_operations: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    total_pick_operations: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    blocked_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    quarantine_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    reserved_for_order_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # ========================================================
    # LIFECYCLE
    # ========================================================

    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
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

    decommission_reason: Mapped[
        str | None
    ] = mapped_column(
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

    bin_metadata: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    sensor_data: Mapped[dict[str, Any]] = mapped_column(
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
            "bin_code": generate_bin_code,
            "status": lambda: WarehouseBinStatus.DRAFT,
            "bin_type": lambda: WarehouseBinType.STANDARD,
            "zone_type": lambda: WarehouseBinZoneType.GENERAL,
            "priority": lambda: WarehouseBinPriority.NORMAL,
            "condition": lambda: WarehouseBinCondition.UNKNOWN,
            "risk_level": lambda: WarehouseBinRiskLevel.UNKNOWN,
            "temperature_mode": (
                lambda: WarehouseBinTemperatureMode.AMBIENT
            ),
            "automation_type": (
                lambda: WarehouseBinAutomationType.MANUAL
            ),
            "capacity_units": lambda: Decimal("0"),
            "occupied_units": lambda: Decimal("0"),
            "reserved_units": lambda: Decimal("0"),
            "capacity_weight_kg": lambda: Decimal("0"),
            "occupied_weight_kg": lambda: Decimal("0"),
            "capacity_volume_m3": lambda: Decimal("0"),
            "occupied_volume_m3": lambda: Decimal("0"),
            "max_pallets": lambda: 0,
            "occupied_pallets": lambda: 0,
            "hazardous_material_allowed": lambda: False,
            "food_grade_storage": lambda: False,
            "pharmaceutical_storage": lambda: False,
            "restricted_access": lambda: False,
            "requires_supervisor_approval": lambda: False,
            "automation_enabled": lambda: False,
            "robot_accessible": lambda: False,
            "temperature_alert_active": lambda: False,
            "humidity_alert_active": lambda: False,
            "ai_optimization_enabled": lambda: False,
            "total_putaway_operations": lambda: 0,
            "total_pick_operations": lambda: 0,
            "is_deleted": lambda: False,
            "version": lambda: 1,
        }

        for field, factory in defaults.items():
            if getattr(self, field, None) is None:
                setattr(self, field, factory())

        for field in (
            "stock_snapshot",
            "bin_metadata",
            "sensor_data",
        ):
            if getattr(self, field, None) is None:
                setattr(self, field, {})

        for field in (
            "inventory_ids",
            "allowed_product_ids",
            "restricted_product_ids",
            "access_role_ids",
            "sensor_ids",
            "ai_recommendations",
            "risk_factors",
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
    def available_units(self) -> Decimal:
        return max(
            Decimal("0"),
            self.capacity_units
            - self.occupied_units
            - self.reserved_units,
        )

    @property
    def available_weight_kg(self) -> Decimal:
        return max(
            Decimal("0"),
            self.capacity_weight_kg
            - self.occupied_weight_kg,
        )

    @property
    def available_volume_m3(self) -> Decimal:
        return max(
            Decimal("0"),
            self.capacity_volume_m3
            - self.occupied_volume_m3,
        )

    @property
    def available_pallets(self) -> int:
        return max(
            0,
            self.max_pallets - self.occupied_pallets,
        )

    @property
    def utilization_percent(self) -> Decimal:
        if self.capacity_units <= 0:
            return Decimal("0")

        return (
            self.occupied_units
            / self.capacity_units
            * Decimal("100")
        ).quantize(Decimal("0.01"))

    @property
    def committed_utilization_percent(self) -> Decimal:
        if self.capacity_units <= 0:
            return Decimal("0")

        return (
            (self.occupied_units + self.reserved_units)
            / self.capacity_units
            * Decimal("100")
        ).quantize(Decimal("0.01"))

    @property
    def is_full(self) -> bool:
        return (
            self.capacity_units > 0
            and self.available_units == 0
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
    def is_high_risk(self) -> bool:
        return self.risk_level in {
            WarehouseBinRiskLevel.HIGH,
            WarehouseBinRiskLevel.CRITICAL,
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
    def is_operational(self) -> bool:
        return (
            self.status in {
                WarehouseBinStatus.ACTIVE,
                WarehouseBinStatus.AVAILABLE,
                WarehouseBinStatus.OCCUPIED,
                WarehouseBinStatus.FULL,
                WarehouseBinStatus.RESERVED,
            }
            and not self.is_deleted
        )

    @property
    def can_receive_stock(self) -> bool:
        return (
            self.is_operational
            and not self.is_full
            and not self.is_high_risk
            and self.is_temperature_compliant
            and self.is_humidity_compliant
            and self.condition not in {
                WarehouseBinCondition.POOR,
                WarehouseBinCondition.DAMAGED,
            }
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _ensure_editable(self) -> None:
        if self.is_deleted:
            raise ValueError("Warehouse bin is deleted")

        if self.status in {
            WarehouseBinStatus.DECOMMISSIONED,
            WarehouseBinStatus.ARCHIVED,
        }:
            raise ValueError(
                "Decommissioned or archived bin cannot be modified"
            )

    def _record_event(
        self,
        event_type: WarehouseBinEventType,
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
        *statuses: WarehouseBinStatus,
    ) -> None:
        if self.status not in statuses:
            raise ValueError(
                f"Invalid bin status: {enum_value(self.status)}"
            )

    def _refresh_occupancy_status(self) -> None:
        if self.status in {
            WarehouseBinStatus.BLOCKED,
            WarehouseBinStatus.QUARANTINED,
            WarehouseBinStatus.MAINTENANCE,
            WarehouseBinStatus.INSPECTION_REQUIRED,
            WarehouseBinStatus.INACTIVE,
            WarehouseBinStatus.DECOMMISSIONED,
            WarehouseBinStatus.ARCHIVED,
            WarehouseBinStatus.DRAFT,
        }:
            return

        if self.is_full:
            self.status = WarehouseBinStatus.FULL
        elif self.occupied_units > 0:
            self.status = WarehouseBinStatus.OCCUPIED
        elif self.reserved_units > 0:
            self.status = WarehouseBinStatus.RESERVED
        else:
            self.status = WarehouseBinStatus.AVAILABLE

    def _validate_capacity(self) -> None:
        if (
            self.occupied_units + self.reserved_units
            > self.capacity_units
        ):
            raise ValueError(
                "Occupied and reserved units exceed capacity"
            )

        if self.occupied_weight_kg > self.capacity_weight_kg:
            raise ValueError(
                "Occupied weight exceeds capacity"
            )

        if self.occupied_volume_m3 > self.capacity_volume_m3:
            raise ValueError(
                "Occupied volume exceeds capacity"
            )

        if self.occupied_pallets > self.max_pallets:
            raise ValueError(
                "Occupied pallets exceed capacity"
            )

    # ========================================================
    # VALIDATION
    # ========================================================

    def validate_bin(self) -> None:
        required_text(
            self.organization_id,
            "Organization ID",
        )

        required_text(
            self.warehouse_id,
            "Warehouse ID",
        )

        required_text(
            self.bin_code,
            "Bin code",
        )

        required_text(
            self.bin_name,
            "Bin name",
        )

        self._validate_capacity()

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

            if value is not None and not (
                Decimal("0") <= value <= Decimal("100")
            ):
                raise ValueError(
                    f"{field} must be between 0 and 100"
                )

    # ========================================================
    # ACTIVATE
    # ========================================================

    def activate(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        self._require_status(
            WarehouseBinStatus.DRAFT,
            WarehouseBinStatus.INACTIVE,
            WarehouseBinStatus.INSPECTION_REQUIRED,
        )

        self.validate_bin()

        if self.condition == WarehouseBinCondition.DAMAGED:
            raise ValueError(
                "Damaged bin cannot be activated"
            )

        self.status = WarehouseBinStatus.ACTIVE
        self.activated_at = utc_now()

        self._refresh_occupancy_status()

        self._record_event(
            WarehouseBinEventType.ACTIVATED,
            actor_id=actor_id,
        )

    # ========================================================
    # UPDATE PROFILE
    # ========================================================

    def update_profile(
        self,
        *,
        actor_id: str,
        bin_name: str | None = None,
        description: str | None = None,
        barcode: str | None = None,
        qr_code: str | None = None,
        priority: WarehouseBinPriority | None = None,
    ) -> None:
        self._ensure_editable()

        if bin_name is not None:
            self.bin_name = required_text(
                bin_name,
                "Bin name",
            )

        if description is not None:
            self.description = optional_text(description)

        if barcode is not None:
            self.barcode = optional_text(barcode)

        if qr_code is not None:
            self.qr_code = optional_text(qr_code)

        if priority is not None:
            if not isinstance(priority, WarehouseBinPriority):
                raise ValueError("Invalid priority")

            self.priority = priority

        self._record_event(
            WarehouseBinEventType.UPDATED,
            actor_id=actor_id,
            details={"section": "profile"},
        )

    # ========================================================
    # UPDATE LOCATION
    # ========================================================

    def update_location(
        self,
        *,
        actor_id: str,
        zone_code: str | None = None,
        aisle: str | None = None,
        rack: str | None = None,
        shelf: str | None = None,
        level: str | None = None,
        position: str | None = None,
    ) -> None:
        self._ensure_editable()

        if not self.is_empty:
            raise ValueError(
                "Bin must be empty before physical relocation"
            )

        updates = {
            "zone_code": zone_code,
            "aisle": aisle,
            "rack": rack,
            "shelf": shelf,
            "level": level,
            "position": position,
        }

        for field, value in updates.items():
            if value is not None:
                setattr(self, field, optional_text(value))

        self.location_label = "-".join(
            str(value)
            for value in (
                self.zone_code,
                self.aisle,
                self.rack,
                self.shelf,
                self.level,
                self.position,
            )
            if value
        ) or None

        self._record_event(
            WarehouseBinEventType.LOCATION_UPDATED,
            actor_id=actor_id,
            details={"location_label": self.location_label},
        )

    # ========================================================
    # CONFIGURE CAPACITY
    # ========================================================

    def configure_capacity(
        self,
        *,
        actor_id: str,
        capacity_units: Any,
        capacity_weight_kg: Any,
        capacity_volume_m3: Any,
        max_pallets: int,
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

        if max_pallets < 0:
            raise ValueError(
                "Maximum pallets cannot be negative"
            )

        if units < self.occupied_units + self.reserved_units:
            raise ValueError(
                "New capacity below committed units"
            )

        if weight < self.occupied_weight_kg:
            raise ValueError(
                "New weight capacity below occupied weight"
            )

        if volume < self.occupied_volume_m3:
            raise ValueError(
                "New volume capacity below occupied volume"
            )

        if max_pallets < self.occupied_pallets:
            raise ValueError(
                "New pallet capacity below occupied pallets"
            )

        self.capacity_units = units
        self.capacity_weight_kg = weight
        self.capacity_volume_m3 = volume
        self.max_pallets = max_pallets

        self._refresh_occupancy_status()

        self._record_event(
            WarehouseBinEventType.CAPACITY_UPDATED,
            actor_id=actor_id,
            details={
                "capacity_units": str(units),
                "capacity_weight_kg": str(weight),
                "capacity_volume_m3": str(volume),
                "max_pallets": max_pallets,
            },
        )

    # ========================================================
    # ADD INVENTORY
    # ========================================================

    def add_inventory(
        self,
        *,
        actor_id: str,
        inventory_id: str,
        quantity: Any,
        weight_kg: Any = 0,
        volume_m3: Any = 0,
        pallets: int = 0,
        product_id: str | None = None,
    ) -> None:
        self._ensure_editable()

        if not self.can_receive_stock:
            raise ValueError(
                "Bin cannot receive stock"
            )

        qty = decimal_value(
            quantity,
            "Quantity",
            minimum=Decimal("0.0001"),
        )

        weight = decimal_value(
            weight_kg,
            "Weight",
        )

        volume = decimal_value(
            volume_m3,
            "Volume",
        )

        if pallets < 0:
            raise ValueError(
                "Pallets cannot be negative"
            )

        if qty > self.available_units:
            raise ValueError(
                "Insufficient unit capacity"
            )

        if weight > self.available_weight_kg:
            raise ValueError(
                "Insufficient weight capacity"
            )

        if volume > self.available_volume_m3:
            raise ValueError(
                "Insufficient volume capacity"
            )

        if pallets > self.available_pallets:
            raise ValueError(
                "Insufficient pallet capacity"
            )

        if product_id is not None:
            product_id = required_text(
                product_id,
                "Product ID",
            )

            if (
                self.allowed_product_ids
                and product_id not in self.allowed_product_ids
            ):
                raise ValueError(
                    "Product not allowed in this bin"
                )

            if product_id in self.restricted_product_ids:
                raise ValueError(
                    "Product restricted from this bin"
                )

        inventory_id = required_text(
            inventory_id,
            "Inventory ID",
        )

        inventory_ids = list(self.inventory_ids or [])

        if inventory_id not in inventory_ids:
            inventory_ids.append(inventory_id)

        self.inventory_ids = inventory_ids

        self.occupied_units += qty
        self.occupied_weight_kg += weight
        self.occupied_volume_m3 += volume
        self.occupied_pallets += pallets

        self.total_putaway_operations += 1
        self.last_putaway_at = utc_now()

        self._refresh_occupancy_status()

        self._record_event(
            WarehouseBinEventType.INVENTORY_ADDED,
            actor_id=actor_id,
            details={
                "inventory_id": inventory_id,
                "product_id": product_id,
                "quantity": str(qty),
                "weight_kg": str(weight),
                "volume_m3": str(volume),
                "pallets": pallets,
            },
        )

        # The inventory ledger and stock movement must be
        # updated by the same transactional service.
        # This method only updates the bin's aggregate snapshot.

    # ========================================================
    # REMOVE INVENTORY
    # ========================================================

    def remove_inventory(
        self,
        *,
        actor_id: str,
        inventory_id: str,
        quantity: Any,
        weight_kg: Any = 0,
        volume_m3: Any = 0,
        pallets: int = 0,
    ) -> None:
        self._ensure_editable()

        if not self.is_operational:
            raise ValueError(
                "Bin is not operational"
            )

        qty = decimal_value(
            quantity,
            "Quantity",
            minimum=Decimal("0.0001"),
        )

        weight = decimal_value(
            weight_kg,
            "Weight",
        )

        volume = decimal_value(
            volume_m3,
            "Volume",
        )

        if pallets < 0:
            raise ValueError(
                "Pallet count cannot be negative"
            )

        if qty > self.occupied_units:
            raise ValueError(
                "Insufficient occupied units"
            )

        if weight > self.occupied_weight_kg:
            raise ValueError(
                "Insufficient occupied weight"
            )

        if volume > self.occupied_volume_m3:
            raise ValueError(
                "Insufficient occupied volume"
            )

        if pallets > self.occupied_pallets:
            raise ValueError(
                "Insufficient occupied pallets"
            )

        if (
            self.occupied_units - qty
            < self.reserved_units
        ):
            raise ValueError(
                "Cannot remove units committed to reservations"
            )

        self.occupied_units -= qty
        self.occupied_weight_kg -= weight
        self.occupied_volume_m3 -= volume
        self.occupied_pallets -= pallets

        self.total_pick_operations += 1
        self.last_pick_at = utc_now()

        self._refresh_occupancy_status()

        self._record_event(
            WarehouseBinEventType.INVENTORY_REMOVED,
            actor_id=actor_id,
            details={
                "inventory_id": inventory_id,
                "quantity": str(qty),
                "weight_kg": str(weight),
                "volume_m3": str(volume),
                "pallets": pallets,
            },
        )

    # ========================================================
    # RESERVE CAPACITY
    # ========================================================

    def reserve_capacity(
        self,
        *,
        actor_id: str,
        quantity: Any,
        order_id: str | None = None,
    ) -> None:
        self._ensure_editable()

        if not self.is_operational:
            raise ValueError(
                "Bin is not operational"
            )

        qty = decimal_value(
            quantity,
            "Reservation quantity",
            minimum=Decimal("0.0001"),
        )

        if qty > self.available_units:
            raise ValueError(
                "Insufficient free capacity"
            )

        self.reserved_units += qty

        if order_id is not None:
            self.reserved_for_order_id = required_text(
                order_id,
                "Order ID",
            )

        self._refresh_occupancy_status()

        self._record_event(
            WarehouseBinEventType.INVENTORY_RESERVED,
            actor_id=actor_id,
            details={
                "quantity": str(qty),
                "order_id": order_id,
            },
        )

    # ========================================================
    # RELEASE RESERVED CAPACITY
    # ========================================================

    def release_reservation(
        self,
        *,
        actor_id: str,
        quantity: Any,
    ) -> None:
        self._ensure_editable()

        qty = decimal_value(
            quantity,
            "Release quantity",
            minimum=Decimal("0.0001"),
        )

        if qty > self.reserved_units:
            raise ValueError(
                "Release exceeds reserved quantity"
            )

        self.reserved_units -= qty

        if self.reserved_units == 0:
            self.reserved_for_order_id = None

        self._refresh_occupancy_status()

        self._record_event(
            WarehouseBinEventType.RESERVATION_RELEASED,
            actor_id=actor_id,
            details={"quantity": str(qty)},
        )

    # ========================================================
    # UPDATE SENSOR DATA
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

        self.sensor_data = json_safe(sensor_data)

        if temperature_c is not None:
            self.current_temperature_c = decimal_value(
                temperature_c,
                "Temperature",
                minimum=None,
            )

        if humidity_percent is not None:
            humidity = decimal_value(
                humidity_percent,
                "Humidity",
            )

            if humidity > 100:
                raise ValueError(
                    "Humidity cannot exceed 100%"
                )

            self.current_humidity_percent = humidity

        self.temperature_alert_active = (
            not self.is_temperature_compliant
        )

        self.humidity_alert_active = (
            not self.is_humidity_compliant
        )

        self._record_event(
            WarehouseBinEventType.SENSOR_UPDATED,
            actor_id=actor_id,
            details={
                "temperature_alert": (
                    self.temperature_alert_active
                ),
                "humidity_alert": (
                    self.humidity_alert_active
                ),
            },
        )

        if self.temperature_alert_active:
            self._record_event(
                WarehouseBinEventType.TEMPERATURE_ALERT,
                actor_id=actor_id,
            )

        if self.humidity_alert_active:
            self._record_event(
                WarehouseBinEventType.HUMIDITY_ALERT,
                actor_id=actor_id,
            )

    # ========================================================
    # BLOCK BIN
    # ========================================================

    def block(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_editable()

        if self.status == WarehouseBinStatus.BLOCKED:
            raise ValueError("Bin is already blocked")

        self.blocked_reason = required_text(
            reason,
            "Block reason",
        )

        self.status = WarehouseBinStatus.BLOCKED

        self._record_event(
            WarehouseBinEventType.BLOCKED,
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # UNBLOCK BIN
    # ========================================================

    def unblock(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        self._require_status(
            WarehouseBinStatus.BLOCKED
        )

        if self.condition == WarehouseBinCondition.DAMAGED:
            raise ValueError(
                "Damaged bin cannot be unblocked"
            )

        self.blocked_reason = None
        self.status = WarehouseBinStatus.ACTIVE
        self._refresh_occupancy_status()

        self._record_event(
            WarehouseBinEventType.UNBLOCKED,
            actor_id=actor_id,
        )

    # ========================================================
    # QUARANTINE
    # ========================================================

    def quarantine(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_editable()

        self.quarantine_reason = required_text(
            reason,
            "Quarantine reason",
        )

        self.status = WarehouseBinStatus.QUARANTINED

        self._record_event(
            WarehouseBinEventType.QUARANTINED,
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # RELEASE QUARANTINE
    # ========================================================

    def release_quarantine(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        self._require_status(
            WarehouseBinStatus.QUARANTINED
        )

        if self.condition == WarehouseBinCondition.DAMAGED:
            raise ValueError(
                "Damaged bin cannot leave quarantine"
            )

        self.quarantine_reason = None
        self.status = WarehouseBinStatus.ACTIVE
        self._refresh_occupancy_status()

        self._record_event(
            WarehouseBinEventType.QUARANTINE_RELEASED,
            actor_id=actor_id,
        )

    # ========================================================
    # RECORD CYCLE COUNT
    # ========================================================

    def record_cycle_count(
        self,
        *,
        actor_id: str,
        counted_units: Any,
        next_due_at: datetime | None = None,
    ) -> None:
        self._ensure_editable()

        count = decimal_value(
            counted_units,
            "Counted units",
        )

        variance = count - self.occupied_units

        self.cycle_count_variance_units = variance
        self.last_cycle_count_at = utc_now()
        self.last_cycle_count_by = required_text(
            actor_id,
            "Counter ID",
        )
        self.next_cycle_count_due_at = next_due_at

        self._record_event(
            WarehouseBinEventType.STOCK_ADJUSTED,
            actor_id=actor_id,
            details={
                "record_type": "cycle_count",
                "system_units": str(self.occupied_units),
                "counted_units": str(count),
                "variance_units": str(variance),
                "stock_adjustment_applied": False,
            },
        )

        # A separate approved stock-adjustment transaction
        # must reconcile the inventory ledger and bin balance.

    # ========================================================
    # START MAINTENANCE
    # ========================================================

    def start_maintenance(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_editable()

        if not self.is_empty:
            raise ValueError(
                "Bin must be empty before maintenance"
            )

        self.maintenance_reason = required_text(
            reason,
            "Maintenance reason",
        )

        self.status = WarehouseBinStatus.MAINTENANCE

        self._record_event(
            WarehouseBinEventType.MAINTENANCE_STARTED,
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # COMPLETE MAINTENANCE
    # ========================================================

    def complete_maintenance(
        self,
        *,
        actor_id: str,
        condition: WarehouseBinCondition,
        next_due_at: datetime | None = None,
    ) -> None:
        self._ensure_editable()

        self._require_status(
            WarehouseBinStatus.MAINTENANCE
        )

        if not isinstance(condition, WarehouseBinCondition):
            raise ValueError("Invalid bin condition")

        self.condition = condition
        self.last_maintenance_at = utc_now()
        self.next_maintenance_due_at = next_due_at
        self.maintenance_reason = None

        self.status = (
            WarehouseBinStatus.INSPECTION_REQUIRED
        )

        self._record_event(
            WarehouseBinEventType.MAINTENANCE_COMPLETED,
            actor_id=actor_id,
            details={"condition": condition.value},
        )

    # ========================================================
    # UPDATE AI RISK
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

        score = score_value(
            risk_score,
            "Risk score",
        )

        self.risk_score = score

        if score >= Decimal("0.85"):
            self.risk_level = WarehouseBinRiskLevel.CRITICAL
        elif score >= Decimal("0.65"):
            self.risk_level = WarehouseBinRiskLevel.HIGH
        elif score >= Decimal("0.35"):
            self.risk_level = WarehouseBinRiskLevel.MEDIUM
        else:
            self.risk_level = WarehouseBinRiskLevel.LOW

        if health_score is not None:
            self.health_score = score_value(
                health_score,
                "Health score",
            )

        if factors is not None:
            if not isinstance(factors, list):
                raise ValueError("Factors must be a list")
            self.risk_factors = json_safe(factors)

        if recommendations is not None:
            if not isinstance(recommendations, list):
                raise ValueError(
                    "Recommendations must be a list"
                )
            self.ai_recommendations = json_safe(
                recommendations
            )

        self.ai_optimization_enabled = True
        self.ai_last_analyzed_at = utc_now()

        self._record_event(
            WarehouseBinEventType.RISK_UPDATED,
            actor_id=actor_id,
            details={
                "risk_score": str(score),
                "risk_level": self.risk_level.value,
            },
        )

    # ========================================================
    # DEACTIVATE
    # ========================================================

    def deactivate(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        if not self.is_empty:
            raise ValueError(
                "Bin must be empty before deactivation"
            )

        self.status = WarehouseBinStatus.INACTIVE
        self.deactivated_at = utc_now()

        self._record_event(
            WarehouseBinEventType.DEACTIVATED,
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

        self._require_status(
            WarehouseBinStatus.INACTIVE
        )

        if not self.is_empty:
            raise ValueError(
                "Bin must be empty before decommissioning"
            )

        self.decommission_reason = required_text(
            reason,
            "Decommission reason",
        )

        self.status = WarehouseBinStatus.DECOMMISSIONED
        self.decommissioned_at = utc_now()

        self._record_event(
            WarehouseBinEventType.DECOMMISSIONED,
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
            raise ValueError("Bin is deleted")

        self._require_status(
            WarehouseBinStatus.DECOMMISSIONED
        )

        self.status = WarehouseBinStatus.ARCHIVED
        self.archived_at = utc_now()

        self._record_event(
            WarehouseBinEventType.ARCHIVED,
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
            raise ValueError("Bin already deleted")

        self._require_status(
            WarehouseBinStatus.DRAFT,
            WarehouseBinStatus.ARCHIVED,
        )

        if not self.is_empty:
            raise ValueError(
                "Cannot delete bin containing stock or reservations"
            )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = required_text(
            actor_id,
            "Actor ID",
        )

        self._record_event(
            WarehouseBinEventType.SOFT_DELETED,
            actor_id=actor_id,
        )

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(
        self,
        *,
        include_inventory: bool = False,
        include_sensors: bool = False,
        include_ai: bool = False,
        include_history: bool = False,
    ) -> dict[str, Any]:

        data = {
            "id": self.id,
            "organization_id": self.organization_id,
            "warehouse_id": self.warehouse_id,
            "bin_code": self.bin_code,
            "bin_name": self.bin_name,
            "description": self.description,
            "barcode": self.barcode,
            "qr_code": self.qr_code,
            "status": enum_value(self.status),
            "bin_type": enum_value(self.bin_type),
            "zone_type": enum_value(self.zone_type),
            "priority": enum_value(self.priority),
            "condition": enum_value(self.condition),
            "zone_id": self.zone_id,
            "zone_code": self.zone_code,
            "aisle": self.aisle,
            "rack": self.rack,
            "shelf": self.shelf,
            "level": self.level,
            "position": self.position,
            "floor_number": self.floor_number,
            "location_label": self.location_label,
            "capacity_units": str(self.capacity_units),
            "occupied_units": str(self.occupied_units),
            "reserved_units": str(self.reserved_units),
            "available_units": str(self.available_units),
            "capacity_weight_kg": str(
                self.capacity_weight_kg
            ),
            "occupied_weight_kg": str(
                self.occupied_weight_kg
            ),
            "available_weight_kg": str(
                self.available_weight_kg
            ),
            "capacity_volume_m3": str(
                self.capacity_volume_m3
            ),
            "occupied_volume_m3": str(
                self.occupied_volume_m3
            ),
            "available_volume_m3": str(
                self.available_volume_m3
            ),
            "max_pallets": self.max_pallets,
            "occupied_pallets": self.occupied_pallets,
            "available_pallets": self.available_pallets,
            "utilization_percent": str(
                self.utilization_percent
            ),
            "committed_utilization_percent": str(
                self.committed_utilization_percent
            ),
            "is_full": self.is_full,
            "is_empty": self.is_empty,
            "is_operational": self.is_operational,
            "can_receive_stock": self.can_receive_stock,
            "temperature_mode": enum_value(
                self.temperature_mode
            ),
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
            "is_temperature_compliant": (
                self.is_temperature_compliant
            ),
            "is_humidity_compliant": (
                self.is_humidity_compliant
            ),
            "hazardous_material_allowed": (
                self.hazardous_material_allowed
            ),
            "food_grade_storage": self.food_grade_storage,
            "pharmaceutical_storage": (
                self.pharmaceutical_storage
            ),
            "restricted_access": self.restricted_access,
            "requires_supervisor_approval": (
                self.requires_supervisor_approval
            ),
            "automation_type": enum_value(
                self.automation_type
            ),
            "automation_enabled": self.automation_enabled,
            "robot_accessible": self.robot_accessible,
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
            "last_cycle_count_at": iso(
                self.last_cycle_count_at
            ),
            "next_cycle_count_due_at": iso(
                self.next_cycle_count_due_at
            ),
            "total_putaway_operations": (
                self.total_putaway_operations
            ),
            "total_pick_operations": (
                self.total_pick_operations
            ),
            "last_putaway_at": iso(self.last_putaway_at),
            "last_pick_at": iso(self.last_pick_at),
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
            "tags": self.tags,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "version": self.version,
        }

        if include_inventory:
            data.update({
                "primary_product_id": (
                    self.primary_product_id
                ),
                "primary_sku": self.primary_sku,
                "product_category_id": (
                    self.product_category_id
                ),
                "inventory_ids": self.inventory_ids,
                "allowed_product_ids": (
                    self.allowed_product_ids
                ),
                "restricted_product_ids": (
                    self.restricted_product_ids
                ),
                "stock_snapshot": self.stock_snapshot,
                "reserved_for_order_id": (
                    self.reserved_for_order_id
                ),
                "cycle_count_variance_units": (
                    str(self.cycle_count_variance_units)
                    if self.cycle_count_variance_units is not None
                    else None
                ),
            })

        if include_sensors:
            data.update({
                "current_temperature_c": (
                    str(self.current_temperature_c)
                    if self.current_temperature_c is not None
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
                "assigned_robot_id": self.assigned_robot_id,
                "automation_controller_id": (
                    self.automation_controller_id
                ),
            })

        if include_ai:
            data.update({
                "ai_optimization_enabled": (
                    self.ai_optimization_enabled
                ),
                "ai_recommendations": (
                    self.ai_recommendations
                ),
                "risk_factors": self.risk_factors,
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
                "ai_last_analyzed_at": iso(
                    self.ai_last_analyzed_at
                ),
            })

        if include_history:
            data.update({
                "event_history": self.event_history,
                "bin_metadata": self.bin_metadata,
                "blocked_reason": self.blocked_reason,
                "quarantine_reason": self.quarantine_reason,
                "maintenance_reason": self.maintenance_reason,
                "decommission_reason": (
                    self.decommission_reason
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
            f"<WarehouseBin("
            f"id={self.id!r}, "
            f"code={self.bin_code!r}, "
            f"warehouse_id={self.warehouse_id!r}, "
            f"status={enum_value(self.status)!r}"
            f")>"
        )