from __future__ import annotations

"""Planned module: store. Implementation pending."""
# backend/models/store.py


import enum
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SQLEnum,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


# ============================================================
# HELPERS
# ============================================================

ZERO = Decimal("0.0000")
ONE = Decimal("1.0000")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_store_code() -> str:
    return f"STR-{uuid.uuid4().hex[:12].upper()}"


def enum_type(enum_class: type[enum.Enum], name: str):
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


def required_string(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Expected string")
    return value.strip() or None


def nonnegative_decimal(
    value: Decimal | str | int | float,
    field: str,
    *,
    maximum: Decimal = Decimal("99999999999999.9999"),
) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")

    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{field} must be numeric") from None

    if not result.is_finite() or result < ZERO or result > maximum:
        raise ValueError(f"{field} must be a finite nonnegative value")

    if result != result.quantize(Decimal("0.0001")):
        raise ValueError(f"{field} supports four decimal places")

    return result


def probability(
    value: Decimal | str | int | float,
    field: str,
) -> Decimal:
    result = nonnegative_decimal(value, field, maximum=ONE)
    return result


def ensure_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("Expected datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timezone-aware datetime required")
    return value.astimezone(timezone.utc)


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value

    if isinstance(value, (float, Decimal)):
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError("Non-finite numeric JSON value")
        return str(number)

    if isinstance(value, enum.Enum):
        return value.value

    if isinstance(value, datetime):
        return ensure_datetime(value).isoformat()

    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]

    raise ValueError(f"Unsupported JSON type: {type(value).__name__}")


def enum_value(value: Any) -> Any:
    return value.value if isinstance(value, enum.Enum) else value


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def decimal_string(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


# ============================================================
# ENUMS
# ============================================================

class StoreStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    ACTIVE = "active"
    TEMPORARILY_CLOSED = "temporarily_closed"
    MAINTENANCE = "maintenance"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"
    PERMANENTLY_CLOSED = "permanently_closed"
    ARCHIVED = "archived"


class StoreType(str, enum.Enum):
    RETAIL = "retail"
    SUPERMARKET = "supermarket"
    HYPERMARKET = "hypermarket"
    CONVENIENCE = "convenience"
    GROCERY = "grocery"
    PHARMACY = "pharmacy"
    ELECTRONICS = "electronics"
    FASHION = "fashion"
    DEPARTMENT = "department"
    WHOLESALE = "wholesale"
    FRANCHISE = "franchise"
    OUTLET = "outlet"
    DARK_STORE = "dark_store"
    MICRO_FULFILLMENT = "micro_fulfillment"
    POPUP = "popup"
    SHOWROOM = "showroom"
    OTHER = "other"


class StoreOwnershipType(str, enum.Enum):
    COMPANY_OWNED = "company_owned"
    FRANCHISE = "franchise"
    PARTNER = "partner"
    THIRD_PARTY = "third_party"
    LEASED = "leased"
    OTHER = "other"


class StoreChannel(str, enum.Enum):
    OFFLINE = "offline"
    ONLINE = "online"
    OMNICHANNEL = "omnichannel"
    CLICK_AND_COLLECT = "click_and_collect"
    DARK_STORE = "dark_store"


class StorePriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class StoreRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class StoreApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class StoreHealthStatus(str, enum.Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class StoreOperatingDay(str, enum.Enum):
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


class StoreServiceType(str, enum.Enum):
    IN_STORE_SHOPPING = "in_store_shopping"
    HOME_DELIVERY = "home_delivery"
    CLICK_AND_COLLECT = "click_and_collect"
    CURBSIDE_PICKUP = "curbside_pickup"
    EXPRESS_DELIVERY = "express_delivery"
    SAME_DAY_DELIVERY = "same_day_delivery"
    RETURNS = "returns"
    EXCHANGES = "exchanges"
    CUSTOMER_SUPPORT = "customer_support"
    OTHER = "other"


class StoreEventType(str, enum.Enum):
    CREATED = "created"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVATED = "activated"
    TEMPORARILY_CLOSED = "temporarily_closed"
    REOPENED = "reopened"
    MAINTENANCE_STARTED = "maintenance_started"
    MAINTENANCE_COMPLETED = "maintenance_completed"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"
    PERMANENTLY_CLOSED = "permanently_closed"
    WAREHOUSE_ASSIGNED = "warehouse_assigned"
    MANAGER_ASSIGNED = "manager_assigned"
    OPERATING_HOURS_UPDATED = "operating_hours_updated"
    SERVICES_UPDATED = "services_updated"
    PERFORMANCE_UPDATED = "performance_updated"
    RISK_UPDATED = "risk_updated"
    HEALTH_UPDATED = "health_updated"
    INVENTORY_POLICY_UPDATED = "inventory_policy_updated"
    ARCHIVED = "archived"
    SOFT_DELETED = "soft_deleted"


# ============================================================
# STORE
# ============================================================

class Store(Base):
    __tablename__ = "stores"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "store_code",
            name="uq_store_org_code",
        ),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_store_org_id",
        ),
        CheckConstraint(
            "store_area_sqft IS NULL OR store_area_sqft >= 0",
            name="ck_store_area",
        ),
        CheckConstraint(
            "storage_capacity_units >= 0",
            name="ck_store_storage_capacity",
        ),
        CheckConstraint(
            "max_daily_orders >= 0",
            name="ck_store_max_daily_orders",
        ),
        CheckConstraint(
            "employee_count >= 0",
            name="ck_store_employee_count",
        ),
        CheckConstraint(
            "daily_sales_target >= 0",
            name="ck_store_daily_sales_target",
        ),
        CheckConstraint(
            "monthly_sales_target >= 0",
            name="ck_store_monthly_sales_target",
        ),
        CheckConstraint(
            "average_daily_sales >= 0",
            name="ck_store_average_daily_sales",
        ),
        CheckConstraint(
            "average_daily_orders >= 0",
            name="ck_store_average_daily_orders",
        ),
        CheckConstraint(
            "inventory_value >= 0",
            name="ck_store_inventory_value",
        ),
        CheckConstraint(
            "stockout_rate IS NULL OR "
            "(stockout_rate >= 0 AND stockout_rate <= 1)",
            name="ck_store_stockout_rate",
        ),
        CheckConstraint(
            "fulfillment_rate IS NULL OR "
            "(fulfillment_rate >= 0 AND fulfillment_rate <= 1)",
            name="ck_store_fulfillment_rate",
        ),
        CheckConstraint(
            "customer_satisfaction_score IS NULL OR "
            "(customer_satisfaction_score >= 0 AND "
            "customer_satisfaction_score <= 1)",
            name="ck_store_satisfaction_score",
        ),
        CheckConstraint(
            "risk_score IS NULL OR "
            "(risk_score >= 0 AND risk_score <= 1)",
            name="ck_store_risk_score",
        ),
        CheckConstraint(
            "health_score IS NULL OR "
            "(health_score >= 0 AND health_score <= 1)",
            name="ck_store_health_score",
        ),
        CheckConstraint(
            "latitude IS NULL OR "
            "(latitude >= -90 AND latitude <= 90)",
            name="ck_store_latitude",
        ),
        CheckConstraint(
            "longitude IS NULL OR "
            "(longitude >= -180 AND longitude <= 180)",
            name="ck_store_longitude",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_store_version",
        ),
        Index(
            "ix_store_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_store_org_type",
            "organization_id",
            "store_type",
        ),
        Index(
            "ix_store_org_city",
            "organization_id",
            "city",
        ),
        Index(
            "ix_store_org_state",
            "organization_id",
            "state",
        ),
        Index(
            "ix_store_org_warehouse",
            "organization_id",
            "primary_warehouse_id",
        ),
        Index(
            "ix_store_org_manager",
            "organization_id",
            "manager_id",
        ),
        Index(
            "ix_store_org_risk",
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

    store_code: Mapped[str] = mapped_column(
        String(60),
        default=generate_store_code,
        nullable=False,
    )

    store_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    display_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ========================================================
    # CLASSIFICATION
    # ========================================================

    store_type: Mapped[StoreType] = mapped_column(
        enum_type(StoreType, "store_type"),
        default=StoreType.RETAIL,
        nullable=False,
    )

    ownership_type: Mapped[StoreOwnershipType] = mapped_column(
        enum_type(
            StoreOwnershipType,
            "store_ownership_type",
        ),
        default=StoreOwnershipType.COMPANY_OWNED,
        nullable=False,
    )

    sales_channel: Mapped[StoreChannel] = mapped_column(
        enum_type(StoreChannel, "store_channel"),
        default=StoreChannel.OFFLINE,
        nullable=False,
    )

    status: Mapped[StoreStatus] = mapped_column(
        enum_type(StoreStatus, "store_status"),
        default=StoreStatus.DRAFT,
        nullable=False,
    )

    priority: Mapped[StorePriority] = mapped_column(
        enum_type(StorePriority, "store_priority"),
        default=StorePriority.NORMAL,
        nullable=False,
    )

    # ========================================================
    # ORGANIZATIONAL REFERENCES
    # ========================================================

    primary_warehouse_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    manager_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    regional_manager_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    region_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    franchise_partner_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    integration_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    external_store_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    pos_system_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    # ========================================================
    # CONTACT INFORMATION
    # ========================================================

    email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    phone: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    alternate_phone: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    website_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    # ========================================================
    # ADDRESS
    # ========================================================

    address_line1: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    address_line2: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    landmark: Mapped[str | None] = mapped_column(
        String(255),
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

    postal_code: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    country: Mapped[str] = mapped_column(
        String(100),
        default="India",
        nullable=False,
    )

    country_code: Mapped[str] = mapped_column(
        String(2),
        default="IN",
        nullable=False,
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

    # ========================================================
    # STORE OPERATIONS
    # ========================================================

    currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    store_area_sqft: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    storage_capacity_units: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    max_daily_orders: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    employee_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    supports_online_orders: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    supports_pickup: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    supports_delivery: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    supports_returns: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    supports_stock_transfers: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    operating_hours: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    holiday_schedule: Mapped[list[dict[str, Any]]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    enabled_services: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # ========================================================
    # INVENTORY POLICIES
    # ========================================================

    inventory_policy: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    replenishment_policy: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    stock_transfer_policy: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    safety_stock_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    auto_replenishment_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    ai_forecasting_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    agent_automation_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    human_approval_required: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # ========================================================
    # PERFORMANCE METRICS
    # ========================================================

    daily_sales_target: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    monthly_sales_target: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    average_daily_sales: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    average_daily_orders: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    inventory_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    stockout_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    fulfillment_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    customer_satisfaction_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    performance_metrics: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    performance_updated_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # AI RISK & HEALTH
    # ========================================================

    risk_level: Mapped[StoreRiskLevel] = mapped_column(
        enum_type(StoreRiskLevel, "store_risk_level"),
        default=StoreRiskLevel.UNKNOWN,
        nullable=False,
    )

    risk_score: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    health_status: Mapped[StoreHealthStatus] = mapped_column(
        enum_type(
            StoreHealthStatus,
            "store_health_status",
        ),
        default=StoreHealthStatus.UNKNOWN,
        nullable=False,
    )

    health_score: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    ai_risk_factors: Mapped[list[dict[str, Any]]] = mapped_column(
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

    ai_explanation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    model_registry_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    last_ai_analysis_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # APPROVAL
    # ========================================================

    approval_status: Mapped[
        StoreApprovalStatus
    ] = mapped_column(
        enum_type(
            StoreApprovalStatus,
            "store_approval_status",
        ),
        default=StoreApprovalStatus.NOT_REQUIRED,
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

    rejected_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    rejected_at: Mapped[datetime | None] = mapped_column(
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

    opening_date: Mapped[datetime | None] = mapped_column(
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

    expected_reopening_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    maintenance_started_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    permanently_closed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    closure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # AUDIT
    # ========================================================

    store_metadata: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    tags: Mapped[list[str]] = mapped_column(
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
    # RELATIONSHIPS
    # ========================================================

    events: Mapped[list["StoreEvent"]] = relationship(
        "StoreEvent",
        back_populates="store",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="StoreEvent.created_at",
    )

    # ========================================================
    # COMPUTED PROPERTIES
    # ========================================================

    @property
    def is_active(self) -> bool:
        return (
            self.status == StoreStatus.ACTIVE
            and not bool(self.is_deleted)
        )

    @property
    def is_operational(self) -> bool:
        return self.is_active

    @property
    def is_closed(self) -> bool:
        return self.status in {
            StoreStatus.TEMPORARILY_CLOSED,
            StoreStatus.PERMANENTLY_CLOSED,
        }

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            StoreStatus.PERMANENTLY_CLOSED,
            StoreStatus.ARCHIVED,
        }

    @property
    def is_high_risk(self) -> bool:
        return self.risk_level in {
            StoreRiskLevel.HIGH,
            StoreRiskLevel.CRITICAL,
        }

    @property
    def can_accept_orders(self) -> bool:
        return self.is_active

    @property
    def can_accept_online_orders(self) -> bool:
        return (
            self.is_active
            and bool(self.supports_online_orders)
        )

    @property
    def can_fulfill_delivery(self) -> bool:
        return (
            self.is_active
            and bool(self.supports_delivery)
        )

    @property
    def sales_target_achievement(self) -> Decimal | None:
        target = self.daily_sales_target or ZERO

        if target <= ZERO:
            return None

        actual = self.average_daily_sales or ZERO

        return (actual / target).quantize(
            Decimal("0.0001")
        )

    @property
    def full_address(self) -> str:
        parts = [
            self.address_line1,
            self.address_line2,
            self.landmark,
            self.city,
            self.district,
            self.state,
            self.postal_code,
            self.country,
        ]

        return ", ".join(
            str(part).strip()
            for part in parts
            if part and str(part).strip()
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _ensure_editable(self) -> None:
        if self.is_deleted:
            raise ValueError("Store has been deleted")

        if self.is_terminal:
            raise ValueError(
                "Terminal store cannot be modified"
            )

    def _require_status(
        self,
        *statuses: StoreStatus,
    ) -> None:
        self._ensure_editable()

        if self.status not in statuses:
            raise ValueError(
                f"Invalid store status: {enum_value(self.status)}"
            )

    def _record_event(
        self,
        event_type: StoreEventType,
        *,
        actor_id: str | None = None,
        description: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.events.append(
            StoreEvent(
                id=generate_uuid(),
                organization_id=required_string(
                    self.organization_id,
                    "Organization ID",
                ),
                event_type=event_type,
                description=description,
                details=json_safe(details or {}),
                actor_id=actor_id,
                created_at=utc_now(),
            )
        )

        self.updated_at = utc_now()

        if actor_id is not None:
            self.updated_by = actor_id

    # ========================================================
    # VALIDATION
    # ========================================================

    def validate_store(self) -> None:
        required_string(
            self.organization_id,
            "Organization ID",
        )
        required_string(self.store_name, "Store name")

        if self.email:
            if not re.fullmatch(
                r"[^@\s]+@[^@\s]+\.[^@\s]+",
                self.email,
            ):
                raise ValueError("Invalid store email")

        if self.country_code:
            if not re.fullmatch(
                r"[A-Z]{2}",
                self.country_code,
            ):
                raise ValueError(
                    "Country code must use ISO alpha-2 format"
                )

        if self.currency:
            if not re.fullmatch(
                r"[A-Z]{3}",
                self.currency,
            ):
                raise ValueError(
                    "Currency must use ISO alpha-3 format"
                )

        if self.latitude is not None:
            latitude = Decimal(str(self.latitude))
            if not Decimal("-90") <= latitude <= Decimal("90"):
                raise ValueError("Invalid latitude")

        if self.longitude is not None:
            longitude = Decimal(str(self.longitude))
            if not Decimal("-180") <= longitude <= Decimal("180"):
                raise ValueError("Invalid longitude")

    # ========================================================
    # REQUEST APPROVAL
    # ========================================================

    def request_approval(
        self,
        *,
        actor_id: str,
        approval_request_id: str,
    ) -> None:
        self._require_status(StoreStatus.DRAFT)

        self.validate_store()

        self.approval_request_id = required_string(
            approval_request_id,
            "Approval request ID",
        )

        self.approval_status = StoreApprovalStatus.PENDING
        self.status = StoreStatus.PENDING_APPROVAL

        self._record_event(
            StoreEventType.APPROVAL_REQUESTED,
            actor_id=actor_id,
            details={
                "approval_request_id": (
                    self.approval_request_id
                ),
            },
        )

    # ========================================================
    # APPROVE STORE
    # ========================================================

    def approve(
        self,
        *,
        approver_id: str,
    ) -> None:
        self._require_status(
            StoreStatus.PENDING_APPROVAL
        )

        approver_id = required_string(
            approver_id,
            "Approver ID",
        )

        # Authorization and approval-request verification
        # belong in the application service layer.

        self.approval_status = StoreApprovalStatus.APPROVED
        self.approved_by = approver_id
        self.approved_at = utc_now()
        self.status = StoreStatus.APPROVED

        self._record_event(
            StoreEventType.APPROVED,
            actor_id=approver_id,
        )

    # ========================================================
    # REJECT STORE
    # ========================================================

    def reject(
        self,
        *,
        approver_id: str,
        reason: str,
    ) -> None:
        self._require_status(
            StoreStatus.PENDING_APPROVAL
        )

        self.rejected_by = required_string(
            approver_id,
            "Approver ID",
        )
        self.rejection_reason = required_string(
            reason,
            "Rejection reason",
        )
        self.rejected_at = utc_now()

        self.approval_status = StoreApprovalStatus.REJECTED
        self.status = StoreStatus.DRAFT

        self._record_event(
            StoreEventType.REJECTED,
            actor_id=approver_id,
            details={"reason": self.rejection_reason},
        )

    # ========================================================
    # ACTIVATE STORE
    # ========================================================

    def activate(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            StoreStatus.DRAFT,
            StoreStatus.APPROVED,
            StoreStatus.INACTIVE,
        )

        self.validate_store()

        if (
            self.human_approval_required
            and self.approval_status
            != StoreApprovalStatus.APPROVED
        ):
            raise ValueError(
                "Store activation requires approval"
            )

        self.status = StoreStatus.ACTIVE
        self.activated_at = utc_now()

        if self.opening_date is None:
            self.opening_date = utc_now()

        self._record_event(
            StoreEventType.ACTIVATED,
            actor_id=actor_id,
        )

    # ========================================================
    # TEMPORARILY CLOSE STORE
    # ========================================================

    def temporarily_close(
        self,
        *,
        actor_id: str,
        reason: str,
        expected_reopening_at: datetime | None = None,
    ) -> None:
        self._require_status(StoreStatus.ACTIVE)

        reopening = (
            ensure_datetime(expected_reopening_at)
            if expected_reopening_at is not None
            else None
        )

        if reopening is not None and reopening <= utc_now():
            raise ValueError(
                "Reopening time must be in the future"
            )

        self.status = StoreStatus.TEMPORARILY_CLOSED
        self.temporarily_closed_at = utc_now()
        self.expected_reopening_at = reopening
        self.closure_reason = required_string(
            reason,
            "Closure reason",
        )

        self._record_event(
            StoreEventType.TEMPORARILY_CLOSED,
            actor_id=actor_id,
            details={
                "reason": self.closure_reason,
                "expected_reopening_at": iso(reopening),
            },
        )

    # ========================================================
    # REOPEN STORE
    # ========================================================

    def reopen(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            StoreStatus.TEMPORARILY_CLOSED
        )

        self.status = StoreStatus.ACTIVE
        self.temporarily_closed_at = None
        self.expected_reopening_at = None
        self.closure_reason = None

        self._record_event(
            StoreEventType.REOPENED,
            actor_id=actor_id,
        )

    # ========================================================
    # START MAINTENANCE
    # ========================================================

    def start_maintenance(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._require_status(StoreStatus.ACTIVE)

        self.status = StoreStatus.MAINTENANCE
        self.maintenance_started_at = utc_now()
        self.closure_reason = required_string(
            reason,
            "Maintenance reason",
        )

        self._record_event(
            StoreEventType.MAINTENANCE_STARTED,
            actor_id=actor_id,
            details={"reason": self.closure_reason},
        )

    # ========================================================
    # COMPLETE MAINTENANCE
    # ========================================================

    def complete_maintenance(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(StoreStatus.MAINTENANCE)

        self.status = StoreStatus.ACTIVE
        self.maintenance_started_at = None
        self.closure_reason = None

        self._record_event(
            StoreEventType.MAINTENANCE_COMPLETED,
            actor_id=actor_id,
        )

    # ========================================================
    # SUSPEND STORE
    # ========================================================

    def suspend(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._require_status(
            StoreStatus.ACTIVE,
            StoreStatus.TEMPORARILY_CLOSED,
            StoreStatus.MAINTENANCE,
        )

        self.status = StoreStatus.SUSPENDED
        self.suspended_at = utc_now()
        self.closure_reason = required_string(
            reason,
            "Suspension reason",
        )

        self._record_event(
            StoreEventType.SUSPENDED,
            actor_id=actor_id,
            details={"reason": self.closure_reason},
        )

    # ========================================================
    # DEACTIVATE STORE
    # ========================================================

    def deactivate(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._require_status(
            StoreStatus.ACTIVE,
            StoreStatus.TEMPORARILY_CLOSED,
            StoreStatus.MAINTENANCE,
            StoreStatus.SUSPENDED,
        )

        self.status = StoreStatus.INACTIVE
        self.deactivated_at = utc_now()
        self.closure_reason = required_string(
            reason,
            "Deactivation reason",
        )

        self._record_event(
            StoreEventType.DEACTIVATED,
            actor_id=actor_id,
            details={"reason": self.closure_reason},
        )

    # ========================================================
    # PERMANENTLY CLOSE
    # ========================================================

    def permanently_close(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._require_status(
            StoreStatus.INACTIVE,
            StoreStatus.SUSPENDED,
            StoreStatus.TEMPORARILY_CLOSED,
        )

        # The service must reconcile inventory, sales,
        # returns, refunds, transfers and outstanding
        # financial obligations before closure.

        self.status = StoreStatus.PERMANENTLY_CLOSED
        self.permanently_closed_at = utc_now()
        self.closure_reason = required_string(
            reason,
            "Closure reason",
        )

        self._record_event(
            StoreEventType.PERMANENTLY_CLOSED,
            actor_id=actor_id,
            details={"reason": self.closure_reason},
        )

    # ========================================================
    # ASSIGN WAREHOUSE
    # ========================================================

    def assign_warehouse(
        self,
        *,
        warehouse_id: str,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        warehouse_id = required_string(
            warehouse_id,
            "Warehouse ID",
        )

        previous_id = self.primary_warehouse_id
        self.primary_warehouse_id = warehouse_id

        self._record_event(
            StoreEventType.WAREHOUSE_ASSIGNED,
            actor_id=actor_id,
            details={
                "previous_warehouse_id": previous_id,
                "warehouse_id": warehouse_id,
            },
        )

    # ========================================================
    # ASSIGN MANAGER
    # ========================================================

    def assign_manager(
        self,
        *,
        manager_id: str,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        manager_id = required_string(
            manager_id,
            "Manager ID",
        )

        previous_id = self.manager_id
        self.manager_id = manager_id

        self._record_event(
            StoreEventType.MANAGER_ASSIGNED,
            actor_id=actor_id,
            details={
                "previous_manager_id": previous_id,
                "manager_id": manager_id,
            },
        )

    # ========================================================
    # UPDATE OPERATING HOURS
    # ========================================================

    def update_operating_hours(
        self,
        *,
        actor_id: str,
        hours: dict[str, Any],
    ) -> None:
        self._ensure_editable()

        if not isinstance(hours, dict):
            raise ValueError(
                "Operating hours must be a dictionary"
            )

        valid_days = {
            day.value for day in StoreOperatingDay
        }

        validated: dict[str, Any] = {}

        for day, schedule in hours.items():
            if day not in valid_days:
                raise ValueError(
                    f"Invalid operating day: {day}"
                )

            if not isinstance(schedule, dict):
                raise ValueError(
                    "Each day must contain a schedule dictionary"
                )

            closed = schedule.get("closed", False)

            if not isinstance(closed, bool):
                raise ValueError(
                    "closed must be boolean"
                )

            if closed:
                validated[day] = {
                    "closed": True,
                    "open": None,
                    "close": None,
                }
                continue

            opening = schedule.get("open")
            closing = schedule.get("close")

            pattern = r"(?:[01]\d|2[0-3]):[0-5]\d"

            if (
                not isinstance(opening, str)
                or not isinstance(closing, str)
                or not re.fullmatch(pattern, opening)
                or not re.fullmatch(pattern, closing)
            ):
                raise ValueError(
                    "Operating times must use HH:MM format"
                )

            validated[day] = {
                "closed": False,
                "open": opening,
                "close": closing,
                "overnight": closing <= opening,
            }

        self.operating_hours = validated

        self._record_event(
            StoreEventType.OPERATING_HOURS_UPDATED,
            actor_id=actor_id,
            details={"days_updated": list(validated.keys())},
        )

    # ========================================================
    # UPDATE SERVICES
    # ========================================================

    def update_services(
        self,
        *,
        actor_id: str,
        services: list[StoreServiceType],
    ) -> None:
        self._ensure_editable()

        if not isinstance(services, list):
            raise ValueError("Services must be a list")

        if not all(
            isinstance(service, StoreServiceType)
            for service in services
        ):
            raise ValueError("Invalid store service")

        values = sorted({
            service.value for service in services
        })

        self.enabled_services = values

        self.supports_online_orders = any(
            service in values
            for service in {
                StoreServiceType.HOME_DELIVERY.value,
                StoreServiceType.CLICK_AND_COLLECT.value,
                StoreServiceType.EXPRESS_DELIVERY.value,
                StoreServiceType.SAME_DAY_DELIVERY.value,
            }
        )

        self.supports_pickup = (
            StoreServiceType.CLICK_AND_COLLECT.value in values
            or StoreServiceType.CURBSIDE_PICKUP.value in values
        )

        self.supports_delivery = any(
            service in values
            for service in {
                StoreServiceType.HOME_DELIVERY.value,
                StoreServiceType.EXPRESS_DELIVERY.value,
                StoreServiceType.SAME_DAY_DELIVERY.value,
            }
        )

        self.supports_returns = (
            StoreServiceType.RETURNS.value in values
        )

        self._record_event(
            StoreEventType.SERVICES_UPDATED,
            actor_id=actor_id,
            details={"services": values},
        )

    # ========================================================
    # UPDATE INVENTORY POLICY
    # ========================================================

    def update_inventory_policy(
        self,
        *,
        actor_id: str,
        inventory_policy: dict[str, Any],
        replenishment_policy: dict[str, Any] | None = None,
        stock_transfer_policy: dict[str, Any] | None = None,
        safety_stock_enabled: bool | None = None,
        auto_replenishment_enabled: bool | None = None,
        ai_forecasting_enabled: bool | None = None,
        agent_automation_enabled: bool | None = None,
    ) -> None:
        self._ensure_editable()

        if not isinstance(inventory_policy, dict):
            raise ValueError(
                "Inventory policy must be a dictionary"
            )

        self.inventory_policy = json_safe(inventory_policy)

        if replenishment_policy is not None:
            if not isinstance(replenishment_policy, dict):
                raise ValueError(
                    "Replenishment policy must be a dictionary"
                )
            self.replenishment_policy = json_safe(
                replenishment_policy
            )

        if stock_transfer_policy is not None:
            if not isinstance(stock_transfer_policy, dict):
                raise ValueError(
                    "Stock transfer policy must be a dictionary"
                )
            self.stock_transfer_policy = json_safe(
                stock_transfer_policy
            )

        flags = {
            "safety_stock_enabled": safety_stock_enabled,
            "auto_replenishment_enabled": (
                auto_replenishment_enabled
            ),
            "ai_forecasting_enabled": ai_forecasting_enabled,
            "agent_automation_enabled": agent_automation_enabled,
        }

        for field, value in flags.items():
            if value is not None:
                if not isinstance(value, bool):
                    raise ValueError(
                        f"{field} must be boolean"
                    )
                setattr(self, field, value)

        self._record_event(
            StoreEventType.INVENTORY_POLICY_UPDATED,
            actor_id=actor_id,
            details={"updated_flags": {
                key: value
                for key, value in flags.items()
                if value is not None
            }},
        )

    # ========================================================
    # UPDATE PERFORMANCE
    # ========================================================

    def update_performance(
        self,
        *,
        actor_id: str,
        average_daily_sales: Decimal | str | float,
        average_daily_orders: Decimal | str | float,
        inventory_value: Decimal | str | float,
        stockout_rate: Decimal | str | float | None = None,
        fulfillment_rate: Decimal | str | float | None = None,
        customer_satisfaction_score: (
            Decimal | str | float | None
        ) = None,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        self._ensure_editable()

        self.average_daily_sales = nonnegative_decimal(
            average_daily_sales,
            "average_daily_sales",
            maximum=Decimal("9999999999999999.9999"),
        )

        self.average_daily_orders = nonnegative_decimal(
            average_daily_orders,
            "average_daily_orders",
        )

        self.inventory_value = nonnegative_decimal(
            inventory_value,
            "inventory_value",
            maximum=Decimal("9999999999999999.9999"),
        )

        if stockout_rate is not None:
            self.stockout_rate = probability(
                stockout_rate,
                "stockout_rate",
            )

        if fulfillment_rate is not None:
            self.fulfillment_rate = probability(
                fulfillment_rate,
                "fulfillment_rate",
            )

        if customer_satisfaction_score is not None:
            self.customer_satisfaction_score = probability(
                customer_satisfaction_score,
                "customer_satisfaction_score",
            )

        if metrics is not None:
            self.performance_metrics = json_safe(metrics)

        self.performance_updated_at = utc_now()

        self._record_event(
            StoreEventType.PERFORMANCE_UPDATED,
            actor_id=actor_id,
            details={
                "average_daily_sales": str(
                    self.average_daily_sales
                ),
                "average_daily_orders": str(
                    self.average_daily_orders
                ),
            },
        )

    # ========================================================
    # UPDATE AI RISK
    # ========================================================

    def update_ai_risk(
        self,
        *,
        actor_id: str,
        risk_level: StoreRiskLevel,
        risk_score: Decimal | str | float,
        factors: list[dict[str, Any]] | None = None,
        recommendations: list[dict[str, Any]] | None = None,
        explanation: str | None = None,
        model_registry_id: str | None = None,
        agent_run_id: str | None = None,
    ) -> None:
        self._ensure_editable()

        if not isinstance(risk_level, StoreRiskLevel):
            raise ValueError("Invalid risk level")

        self.risk_level = risk_level
        self.risk_score = probability(
            risk_score,
            "risk_score",
        )

        self.ai_risk_factors = json_safe(factors or [])
        self.ai_recommendations = json_safe(
            recommendations or []
        )
        self.ai_explanation = optional_string(explanation)
        self.model_registry_id = model_registry_id
        self.agent_run_id = agent_run_id
        self.last_ai_analysis_at = utc_now()

        self._record_event(
            StoreEventType.RISK_UPDATED,
            actor_id=actor_id,
            details={
                "risk_level": risk_level.value,
                "risk_score": str(self.risk_score),
            },
        )

    # ========================================================
    # UPDATE STORE HEALTH
    # ========================================================

    def update_health(
        self,
        *,
        actor_id: str,
        health_status: StoreHealthStatus,
        health_score: Decimal | str | float,
    ) -> None:
        self._ensure_editable()

        if not isinstance(
            health_status,
            StoreHealthStatus,
        ):
            raise ValueError("Invalid health status")

        self.health_status = health_status
        self.health_score = probability(
            health_score,
            "health_score",
        )

        self._record_event(
            StoreEventType.HEALTH_UPDATED,
            actor_id=actor_id,
            details={
                "health_status": health_status.value,
                "health_score": str(self.health_score),
            },
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
            raise ValueError("Store has been deleted")

        if self.status not in {
            StoreStatus.INACTIVE,
            StoreStatus.PERMANENTLY_CLOSED,
        }:
            raise ValueError(
                "Only inactive or permanently closed "
                "stores can be archived"
            )

        self.status = StoreStatus.ARCHIVED
        self.archived_at = utc_now()

        self._record_event(
            StoreEventType.ARCHIVED,
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
            raise ValueError("Store already deleted")

        if self.status not in {
            StoreStatus.DRAFT,
            StoreStatus.ARCHIVED,
        }:
            raise ValueError(
                "Only draft or archived stores "
                "can be soft-deleted"
            )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = required_string(
            actor_id,
            "Actor ID",
        )

        self._record_event(
            StoreEventType.SOFT_DELETED,
            actor_id=actor_id,
        )

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(
        self,
        *,
        include_internal: bool = False,
        include_events: bool = False,
    ) -> dict[str, Any]:

        data = {
            "id": self.id,
            "organization_id": self.organization_id,
            "store_code": self.store_code,
            "store_name": self.store_name,
            "display_name": self.display_name,
            "description": self.description,
            "store_type": enum_value(self.store_type),
            "ownership_type": enum_value(
                self.ownership_type
            ),
            "sales_channel": enum_value(
                self.sales_channel
            ),
            "status": enum_value(self.status),
            "priority": enum_value(self.priority),
            "primary_warehouse_id": (
                self.primary_warehouse_id
            ),
            "manager_id": self.manager_id,
            "region_id": self.region_id,
            "email": self.email,
            "phone": self.phone,
            "address_line1": self.address_line1,
            "address_line2": self.address_line2,
            "city": self.city,
            "district": self.district,
            "state": self.state,
            "postal_code": self.postal_code,
            "country": self.country,
            "country_code": self.country_code,
            "latitude": decimal_string(self.latitude),
            "longitude": decimal_string(self.longitude),
            "timezone_name": self.timezone_name,
            "full_address": self.full_address,
            "currency": self.currency,
            "store_area_sqft": decimal_string(
                self.store_area_sqft
            ),
            "storage_capacity_units": decimal_string(
                self.storage_capacity_units
            ),
            "max_daily_orders": self.max_daily_orders,
            "employee_count": self.employee_count,
            "supports_online_orders": (
                self.supports_online_orders
            ),
            "supports_pickup": self.supports_pickup,
            "supports_delivery": self.supports_delivery,
            "supports_returns": self.supports_returns,
            "supports_stock_transfers": (
                self.supports_stock_transfers
            ),
            "operating_hours": self.operating_hours,
            "enabled_services": self.enabled_services,
            "safety_stock_enabled": (
                self.safety_stock_enabled
            ),
            "auto_replenishment_enabled": (
                self.auto_replenishment_enabled
            ),
            "ai_forecasting_enabled": (
                self.ai_forecasting_enabled
            ),
            "agent_automation_enabled": (
                self.agent_automation_enabled
            ),
            "daily_sales_target": decimal_string(
                self.daily_sales_target
            ),
            "monthly_sales_target": decimal_string(
                self.monthly_sales_target
            ),
            "average_daily_sales": decimal_string(
                self.average_daily_sales
            ),
            "average_daily_orders": decimal_string(
                self.average_daily_orders
            ),
            "inventory_value": decimal_string(
                self.inventory_value
            ),
            "stockout_rate": decimal_string(
                self.stockout_rate
            ),
            "fulfillment_rate": decimal_string(
                self.fulfillment_rate
            ),
            "customer_satisfaction_score": decimal_string(
                self.customer_satisfaction_score
            ),
            "risk_level": enum_value(self.risk_level),
            "risk_score": decimal_string(self.risk_score),
            "health_status": enum_value(
                self.health_status
            ),
            "health_score": decimal_string(
                self.health_score
            ),
            "ai_recommendations": (
                self.ai_recommendations
            ),
            "approval_status": enum_value(
                self.approval_status
            ),
            "opening_date": iso(self.opening_date),
            "activated_at": iso(self.activated_at),
            "temporarily_closed_at": iso(
                self.temporarily_closed_at
            ),
            "expected_reopening_at": iso(
                self.expected_reopening_at
            ),
            "permanently_closed_at": iso(
                self.permanently_closed_at
            ),
            "is_active": self.is_active,
            "is_operational": self.is_operational,
            "is_closed": self.is_closed,
            "is_high_risk": self.is_high_risk,
            "can_accept_orders": self.can_accept_orders,
            "can_accept_online_orders": (
                self.can_accept_online_orders
            ),
            "sales_target_achievement": decimal_string(
                self.sales_target_achievement
            ),
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "is_deleted": self.is_deleted,
            "version": self.version,
        }

        if include_internal:
            data.update({
                "regional_manager_id": (
                    self.regional_manager_id
                ),
                "franchise_partner_id": (
                    self.franchise_partner_id
                ),
                "integration_id": self.integration_id,
                "external_store_id": self.external_store_id,
                "pos_system_id": self.pos_system_id,
                "alternate_phone": self.alternate_phone,
                "website_url": self.website_url,
                "landmark": self.landmark,
                "holiday_schedule": self.holiday_schedule,
                "inventory_policy": self.inventory_policy,
                "replenishment_policy": (
                    self.replenishment_policy
                ),
                "stock_transfer_policy": (
                    self.stock_transfer_policy
                ),
                "performance_metrics": (
                    self.performance_metrics
                ),
                "ai_risk_factors": self.ai_risk_factors,
                "ai_explanation": self.ai_explanation,
                "model_registry_id": self.model_registry_id,
                "agent_run_id": self.agent_run_id,
                "approval_request_id": (
                    self.approval_request_id
                ),
                "approved_by": self.approved_by,
                "approved_at": iso(self.approved_at),
                "rejected_by": self.rejected_by,
                "rejected_at": iso(self.rejected_at),
                "rejection_reason": self.rejection_reason,
                "closure_reason": self.closure_reason,
                "store_metadata": self.store_metadata,
                "tags": self.tags,
                "created_by": self.created_by,
                "updated_by": self.updated_by,
                "deleted_at": iso(self.deleted_at),
                "deleted_by": self.deleted_by,
            })

        if include_events:
            data["events"] = [
                event.to_dict()
                for event in self.events
            ]

        return data

    def __repr__(self) -> str:
        return (
            f"<Store("
            f"id={self.id!r}, "
            f"store_code={self.store_code!r}, "
            f"store_name={self.store_name!r}, "
            f"status={enum_value(self.status)!r}"
            f")>"
        )


# ============================================================
# STORE EVENT
# ============================================================

class StoreEvent(Base):
    __tablename__ = "store_events"

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "store_id"],
            ["stores.organization_id", "stores.id"],
            name="fk_store_event_store_org",
            ondelete="CASCADE",
        ),
        Index(
            "ix_store_event_org_type",
            "organization_id",
            "event_type",
        ),
        Index(
            "ix_store_event_store_created",
            "store_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    organization_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    store_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    event_type: Mapped[StoreEventType] = mapped_column(
        enum_type(
            StoreEventType,
            "store_event_type",
        ),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    details: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    actor_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    store: Mapped[Store] = relationship(
        "Store",
        back_populates="events",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "store_id": self.store_id,
            "event_type": enum_value(self.event_type),
            "description": self.description,
            "details": self.details,
            "actor_id": self.actor_id,
            "created_at": iso(self.created_at),
        }

    def __repr__(self) -> str:
        return (
            f"<StoreEvent("
            f"id={self.id!r}, "
            f"store_id={self.store_id!r}, "
            f"event_type={enum_value(self.event_type)!r}"
            f")>"
        )