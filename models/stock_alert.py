from __future__ import annotations

"""Planned module: stock alert. Implementation pending."""
# backend/models/stock_alert.py


import enum
import uuid

from datetime import datetime, timedelta, timezone
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
# UTILITIES
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_alert_number() -> str:
    return f"STK-{uuid.uuid4().hex[:18].upper()}"


def enum_column(enum_class, name: str):
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


def validate_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Timezone-aware datetime required")

    return value.astimezone(timezone.utc)


def decimal_value(
    value: Decimal | str | int | float,
    field: str,
    *,
    minimum: Decimal = Decimal("0"),
    maximum: Decimal | None = None,
) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")

    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be numeric") from None

    if not result.is_finite():
        raise ValueError(f"{field} must be finite")

    if result < minimum:
        raise ValueError(
            f"{field} must be at least {minimum}"
        )

    if maximum is not None and result > maximum:
        raise ValueError(
            f"{field} must not exceed {maximum}"
        )

    if result != result.quantize(Decimal("0.0001")):
        raise ValueError(
            f"{field} supports at most 4 decimal places"
        )

    return result


def enum_value(value):
    return value.value if isinstance(value, enum.Enum) else value


def serialize_datetime(value):
    return value.isoformat() if value else None


def serialize_decimal(value):
    return str(value) if value is not None else None


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        return str(decimal_value(
            value,
            "JSON number",
            minimum=Decimal("-999999999999999999"),
        ))

    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite decimal")
        return str(value)

    if isinstance(value, enum.Enum):
        return value.value

    if isinstance(value, datetime):
        return validate_datetime(value).isoformat()

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

class StockAlertStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    TRIGGERED = "triggered"
    ACKNOWLEDGED = "acknowledged"
    INVESTIGATING = "investigating"
    ACTION_REQUIRED = "action_required"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
    ESCALATED = "escalated"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class StockAlertType(str, enum.Enum):
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"
    CRITICAL_STOCK = "critical_stock"
    OVERSTOCK = "overstock"
    EXCESS_INVENTORY = "excess_inventory"
    REORDER_POINT = "reorder_point"
    SAFETY_STOCK_BREACH = "safety_stock_breach"
    NEGATIVE_STOCK = "negative_stock"
    STOCK_DISCREPANCY = "stock_discrepancy"
    STOCK_EXPIRING = "stock_expiring"
    EXPIRED_STOCK = "expired_stock"
    SLOW_MOVING_STOCK = "slow_moving_stock"
    DEAD_STOCK = "dead_stock"
    HIGH_DEMAND = "high_demand"
    DEMAND_SPIKE = "demand_spike"
    DEMAND_DROP = "demand_drop"
    STOCKOUT_RISK = "stockout_risk"
    REPLENISHMENT_DELAY = "replenishment_delay"
    SUPPLIER_DELAY = "supplier_delay"
    WAREHOUSE_CAPACITY = "warehouse_capacity"
    DAMAGED_STOCK = "damaged_stock"
    QUARANTINED_STOCK = "quarantined_stock"
    RESERVED_STOCK_EXCESS = "reserved_stock_excess"
    INVENTORY_ANOMALY = "inventory_anomaly"
    PRODUCT_RECALL = "product_recall"
    CUSTOM = "custom"


class StockAlertSeverity(str, enum.Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class StockAlertPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"


class StockAlertSource(str, enum.Enum):
    INVENTORY_SERVICE = "inventory_service"
    REPLENISHMENT_ENGINE = "replenishment_engine"
    DEMAND_FORECAST = "demand_forecast"
    WAREHOUSE_SYSTEM = "warehouse_system"
    ERP = "erp"
    POS = "pos"
    SUPPLIER_API = "supplier_api"
    AI_AGENT = "ai_agent"
    ANOMALY_DETECTION = "anomaly_detection"
    SCHEDULER = "scheduler"
    MANUAL = "manual"
    API = "api"
    SYSTEM = "system"


class StockAlertRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class StockAlertApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class StockAlertNotificationStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    QUEUED = "queued"
    SENT = "sent"
    PARTIALLY_SENT = "partially_sent"
    FAILED = "failed"


class StockAlertResolutionType(str, enum.Enum):
    REPLENISHED = "replenished"
    STOCK_TRANSFERRED = "stock_transferred"
    PURCHASE_ORDER_CREATED = "purchase_order_created"
    INVENTORY_ADJUSTED = "inventory_adjusted"
    SUPPLIER_CONFIRMED = "supplier_confirmed"
    DEMAND_NORMALIZED = "demand_normalized"
    ISSUE_CORRECTED = "issue_corrected"
    FALSE_POSITIVE = "false_positive"
    MANUAL_OVERRIDE = "manual_override"
    NO_ACTION_REQUIRED = "no_action_required"
    OTHER = "other"


class StockAlertActionType(str, enum.Enum):
    CREATE_REPLENISHMENT_PLAN = "create_replenishment_plan"
    CREATE_PURCHASE_ORDER = "create_purchase_order"
    TRANSFER_STOCK = "transfer_stock"
    ADJUST_INVENTORY = "adjust_inventory"
    CONTACT_SUPPLIER = "contact_supplier"
    INVESTIGATE_DISCREPANCY = "investigate_discrepancy"
    QUARANTINE_STOCK = "quarantine_stock"
    INITIATE_RECALL = "initiate_recall"
    REVIEW_FORECAST = "review_forecast"
    OPTIMIZE_SAFETY_STOCK = "optimize_safety_stock"
    NOTIFY_WAREHOUSE = "notify_warehouse"
    ESCALATE_INCIDENT = "escalate_incident"
    MANUAL_REVIEW = "manual_review"
    OTHER = "other"


# ============================================================
# STOCK ALERT ORM
# ============================================================

class StockAlert(Base):
    __tablename__ = "stock_alerts"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "alert_number",
            name="uq_stock_alert_org_number",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_stock_alert_org_idempotency",
        ),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_stock_alert_org_id",
        ),
        CheckConstraint(
            "current_quantity >= 0",
            name="ck_stock_alert_current_qty",
        ),
        CheckConstraint(
            "available_quantity >= 0",
            name="ck_stock_alert_available_qty",
        ),
        CheckConstraint(
            "reserved_quantity >= 0",
            name="ck_stock_alert_reserved_qty",
        ),
        CheckConstraint(
            "reorder_point >= 0",
            name="ck_stock_alert_reorder_point",
        ),
        CheckConstraint(
            "safety_stock >= 0",
            name="ck_stock_alert_safety_stock",
        ),
        CheckConstraint(
            "minimum_stock >= 0",
            name="ck_stock_alert_minimum_stock",
        ),
        CheckConstraint(
            "maximum_stock >= 0",
            name="ck_stock_alert_maximum_stock",
        ),
        CheckConstraint(
            "recommended_order_quantity >= 0",
            name="ck_stock_alert_recommended_qty",
        ),
        CheckConstraint(
            "forecast_demand >= 0",
            name="ck_stock_alert_forecast_demand",
        ),
        CheckConstraint(
            "estimated_stockout_days IS NULL OR "
            "estimated_stockout_days >= 0",
            name="ck_stock_alert_stockout_days",
        ),
        CheckConstraint(
            "risk_score IS NULL OR "
            "(risk_score >= 0 AND risk_score <= 1)",
            name="ck_stock_alert_risk_score",
        ),
        CheckConstraint(
            "ai_confidence IS NULL OR "
            "(ai_confidence >= 0 AND ai_confidence <= 1)",
            name="ck_stock_alert_ai_confidence",
        ),
        CheckConstraint(
            "estimated_loss >= 0",
            name="ck_stock_alert_estimated_loss",
        ),
        CheckConstraint(
            "estimated_replenishment_cost >= 0",
            name="ck_stock_alert_replenishment_cost",
        ),
        CheckConstraint(
            "notification_attempts >= 0",
            name="ck_stock_alert_notification_attempts",
        ),
        CheckConstraint(
            "escalation_level >= 0",
            name="ck_stock_alert_escalation_level",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_stock_alert_version",
        ),
        Index(
            "ix_stock_alert_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_stock_alert_org_type",
            "organization_id",
            "alert_type",
        ),
        Index(
            "ix_stock_alert_org_severity",
            "organization_id",
            "severity",
        ),
        Index(
            "ix_stock_alert_org_product",
            "organization_id",
            "product_id",
        ),
        Index(
            "ix_stock_alert_org_warehouse",
            "organization_id",
            "warehouse_id",
        ),
        Index(
            "ix_stock_alert_org_inventory",
            "organization_id",
            "inventory_id",
        ),
        Index(
            "ix_stock_alert_org_created",
            "organization_id",
            "created_at",
        ),
        Index(
            "ix_stock_alert_org_triggered",
            "organization_id",
            "triggered_at",
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

    alert_number: Mapped[str] = mapped_column(
        String(60),
        default=generate_alert_number,
        nullable=False,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # ========================================================
    # ALERT DETAILS
    # ========================================================

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    alert_type: Mapped[StockAlertType] = mapped_column(
        enum_column(
            StockAlertType,
            "stock_alert_type",
        ),
        nullable=False,
    )

    status: Mapped[StockAlertStatus] = mapped_column(
        enum_column(
            StockAlertStatus,
            "stock_alert_status",
        ),
        default=StockAlertStatus.DRAFT,
        nullable=False,
    )

    severity: Mapped[StockAlertSeverity] = mapped_column(
        enum_column(
            StockAlertSeverity,
            "stock_alert_severity",
        ),
        default=StockAlertSeverity.MEDIUM,
        nullable=False,
    )

    priority: Mapped[StockAlertPriority] = mapped_column(
        enum_column(
            StockAlertPriority,
            "stock_alert_priority",
        ),
        default=StockAlertPriority.NORMAL,
        nullable=False,
    )

    source: Mapped[StockAlertSource] = mapped_column(
        enum_column(
            StockAlertSource,
            "stock_alert_source",
        ),
        default=StockAlertSource.INVENTORY_SERVICE,
        nullable=False,
    )

    source_reference_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # ========================================================
    # BUSINESS REFERENCES
    # ========================================================

    product_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    inventory_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    warehouse_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    supplier_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    category_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    demand_forecast_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    replenishment_plan_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    purchase_order_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    simulation_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    incident_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    escalation_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # ========================================================
    # PRODUCT / STOCK IDENTIFIERS
    # ========================================================

    sku: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    batch_number: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    lot_number: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    bin_location: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    unit_of_measure: Mapped[str] = mapped_column(
        String(30),
        default="unit",
        nullable=False,
    )

    # ========================================================
    # INVENTORY SNAPSHOT
    # ========================================================

    current_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    available_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    reserved_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    incoming_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    reorder_point: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    safety_stock: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    minimum_stock: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    maximum_stock: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    stock_snapshot_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # FORECAST / REPLENISHMENT
    # ========================================================

    forecast_demand: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    recommended_order_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    estimated_stockout_days: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    expected_replenishment_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    forecast_horizon_days: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    supplier_lead_time_days: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # ========================================================
    # THRESHOLD / RULE
    # ========================================================

    rule_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    threshold_value: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    observed_value: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    trigger_condition: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    rule_configuration: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    trigger_evidence: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # ========================================================
    # AI RISK INTELLIGENCE
    # ========================================================

    ai_generated: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    ai_model_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    ai_model_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    ai_agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    ai_confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    risk_score: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    risk_level: Mapped[StockAlertRiskLevel] = mapped_column(
        enum_column(
            StockAlertRiskLevel,
            "stock_alert_risk_level",
        ),
        default=StockAlertRiskLevel.UNKNOWN,
        nullable=False,
    )

    ai_explanation: Mapped[str | None] = mapped_column(
        Text,
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

    analyzed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # FINANCIAL IMPACT
    # ========================================================

    currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    estimated_loss: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    estimated_replenishment_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    estimated_lost_sales: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    financial_impact_details: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # ========================================================
    # ACTIONS
    # ========================================================

    recommended_action: Mapped[
        StockAlertActionType | None
    ] = mapped_column(
        enum_column(
            StockAlertActionType,
            "stock_alert_action_type",
        ),
        nullable=True,
    )

    recommended_action_details: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    action_items: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    assigned_to: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    action_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # APPROVAL
    # ========================================================

    requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    approval_status: Mapped[
        StockAlertApprovalStatus
    ] = mapped_column(
        enum_column(
            StockAlertApprovalStatus,
            "stock_alert_approval_status",
        ),
        default=StockAlertApprovalStatus.NOT_REQUIRED,
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
    # NOTIFICATION
    # ========================================================

    notification_status: Mapped[
        StockAlertNotificationStatus
    ] = mapped_column(
        enum_column(
            StockAlertNotificationStatus,
            "stock_alert_notification_status",
        ),
        default=StockAlertNotificationStatus.NOT_REQUIRED,
        nullable=False,
    )

    notification_ids: Mapped[
        list[str]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    notification_channels: Mapped[
        list[str]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    notification_attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    last_notification_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    notification_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ========================================================
    # ESCALATION / SLA
    # ========================================================

    escalation_level: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    escalation_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    escalated_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    sla_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    sla_breached: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    sla_breached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # LIFECYCLE
    # ========================================================

    triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    acknowledged_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    investigation_started_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    resolved_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    resolution_type: Mapped[
        StockAlertResolutionType | None
    ] = mapped_column(
        enum_column(
            StockAlertResolutionType,
            "stock_alert_resolution_type",
        ),
        nullable=True,
    )

    resolution_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    dismissed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    dismissed_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    dismissal_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    expired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    cancelled_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    cancellation_reason: Mapped[str | None] = mapped_column(
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

    alert_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    alert_history: Mapped[
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

    trace_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    correlation_id: Mapped[str | None] = mapped_column(
        String(100),
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
    # PROPERTIES
    # ========================================================

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            StockAlertStatus.RESOLVED,
            StockAlertStatus.DISMISSED,
            StockAlertStatus.EXPIRED,
            StockAlertStatus.CANCELLED,
            StockAlertStatus.ARCHIVED,
        }

    @property
    def is_open(self) -> bool:
        return not self.is_deleted and self.status in {
            StockAlertStatus.ACTIVE,
            StockAlertStatus.TRIGGERED,
            StockAlertStatus.ACKNOWLEDGED,
            StockAlertStatus.INVESTIGATING,
            StockAlertStatus.ACTION_REQUIRED,
            StockAlertStatus.PENDING_APPROVAL,
            StockAlertStatus.APPROVED,
            StockAlertStatus.ESCALATED,
        }

    @property
    def is_critical(self) -> bool:
        return self.severity in {
            StockAlertSeverity.CRITICAL,
            StockAlertSeverity.EMERGENCY,
        }

    @property
    def is_approved(self) -> bool:
        return (
            not self.requires_approval
            or self.approval_status
            == StockAlertApprovalStatus.APPROVED
        )

    @property
    def stock_gap(self) -> Decimal:
        return max(
            Decimal("0"),
            (self.reorder_point or Decimal("0"))
            - (self.available_quantity or Decimal("0")),
        )

    @property
    def safety_stock_gap(self) -> Decimal:
        return max(
            Decimal("0"),
            (self.safety_stock or Decimal("0"))
            - (self.available_quantity or Decimal("0")),
        )

    @property
    def projected_available_quantity(self) -> Decimal:
        return (
            (self.available_quantity or Decimal("0"))
            + (self.incoming_quantity or Decimal("0"))
            - (self.forecast_demand or Decimal("0"))
        )

    @property
    def is_sla_overdue(self) -> bool:
        return (
            self.is_open
            and self.sla_due_at is not None
            and validate_datetime(self.sla_due_at) < utc_now()
        )

    @property
    def is_expired(self) -> bool:
        return (
            self.expires_at is not None
            and validate_datetime(self.expires_at) <= utc_now()
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _touch(self, actor_id: str | None = None) -> None:
        self.updated_at = utc_now()

        if actor_id is not None:
            self.updated_by = actor_id

    def _ensure_active(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Stock alert has been deleted"
            )

    def _require_status(
        self,
        *statuses: StockAlertStatus,
    ) -> None:
        self._ensure_active()

        if self.status not in statuses:
            raise ValueError(
                f"Invalid stock alert status: "
                f"{enum_value(self.status)}"
            )

    def _record_event(
        self,
        event: str,
        *,
        actor_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        history = list(self.alert_history or [])

        history.append({
            "event_id": generate_uuid(),
            "event": event,
            "actor_id": actor_id,
            "timestamp": utc_now().isoformat(),
            "details": json_safe(details or {}),
        })

        self.alert_history = history
        self._touch(actor_id)

    # ========================================================
    # ACTIVATE
    # ========================================================

    def activate(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            StockAlertStatus.DRAFT
        )

        required_text(self.title, "Title")
        required_text(self.product_id, "Product ID")
        required_text(self.warehouse_id, "Warehouse ID")

        self.status = StockAlertStatus.ACTIVE

        self._record_event(
            "stock_alert_activated",
            actor_id=actor_id,
        )

    # ========================================================
    # UPDATE STOCK SNAPSHOT
    # ========================================================

    def update_stock_snapshot(
        self,
        *,
        current_quantity: Decimal | str | float,
        available_quantity: Decimal | str | float,
        reserved_quantity: Decimal | str | float,
        incoming_quantity: Decimal | str | float,
        actor_id: str,
        reorder_point: Decimal | str | float | None = None,
        safety_stock: Decimal | str | float | None = None,
        minimum_stock: Decimal | str | float | None = None,
        maximum_stock: Decimal | str | float | None = None,
    ) -> None:
        self._require_status(
            StockAlertStatus.DRAFT,
            StockAlertStatus.ACTIVE,
            StockAlertStatus.TRIGGERED,
            StockAlertStatus.ACKNOWLEDGED,
            StockAlertStatus.INVESTIGATING,
            StockAlertStatus.ACTION_REQUIRED,
            StockAlertStatus.ESCALATED,
        )

        current = decimal_value(
            current_quantity, "current_quantity"
        )
        available = decimal_value(
            available_quantity, "available_quantity"
        )
        reserved = decimal_value(
            reserved_quantity, "reserved_quantity"
        )
        incoming = decimal_value(
            incoming_quantity, "incoming_quantity"
        )

        if available + reserved > current:
            raise ValueError(
                "Available plus reserved stock cannot "
                "exceed current stock"
            )

        new_reorder = (
            decimal_value(reorder_point, "reorder_point")
            if reorder_point is not None
            else self.reorder_point or Decimal("0")
        )

        new_safety = (
            decimal_value(safety_stock, "safety_stock")
            if safety_stock is not None
            else self.safety_stock or Decimal("0")
        )

        new_minimum = (
            decimal_value(minimum_stock, "minimum_stock")
            if minimum_stock is not None
            else self.minimum_stock or Decimal("0")
        )

        new_maximum = (
            decimal_value(maximum_stock, "maximum_stock")
            if maximum_stock is not None
            else self.maximum_stock or Decimal("0")
        )

        if new_maximum > 0 and new_minimum > new_maximum:
            raise ValueError(
                "Minimum stock cannot exceed maximum stock"
            )

        self.current_quantity = current
        self.available_quantity = available
        self.reserved_quantity = reserved
        self.incoming_quantity = incoming
        self.reorder_point = new_reorder
        self.safety_stock = new_safety
        self.minimum_stock = new_minimum
        self.maximum_stock = new_maximum
        self.stock_snapshot_at = utc_now()

        self._record_event(
            "stock_snapshot_updated",
            actor_id=actor_id,
            details={
                "current_quantity": str(current),
                "available_quantity": str(available),
                "reserved_quantity": str(reserved),
                "incoming_quantity": str(incoming),
            },
        )

    # ========================================================
    # UPDATE FORECAST
    # ========================================================

    def update_forecast(
        self,
        *,
        forecast_demand: Decimal | str | float,
        recommended_order_quantity: Decimal | str | float,
        actor_id: str,
        estimated_stockout_days: Decimal | str | float | None = None,
        forecast_horizon_days: int | None = None,
        supplier_lead_time_days: int | None = None,
        expected_replenishment_at: datetime | None = None,
    ) -> None:
        self._ensure_active()

        if self.is_terminal:
            raise ValueError(
                "Cannot update a terminal stock alert"
            )

        demand = decimal_value(
            forecast_demand,
            "forecast_demand",
        )
        quantity = decimal_value(
            recommended_order_quantity,
            "recommended_order_quantity",
        )

        stockout_days = (
            decimal_value(
                estimated_stockout_days,
                "estimated_stockout_days",
            )
            if estimated_stockout_days is not None
            else None
        )

        for name, value in (
            ("forecast_horizon_days", forecast_horizon_days),
            ("supplier_lead_time_days", supplier_lead_time_days),
        ):
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ValueError(
                    f"{name} must be a nonnegative integer"
                )

        replenishment_at = (
            validate_datetime(expected_replenishment_at)
            if expected_replenishment_at is not None
            else None
        )

        self.forecast_demand = demand
        self.recommended_order_quantity = quantity
        self.estimated_stockout_days = stockout_days
        self.forecast_horizon_days = forecast_horizon_days
        self.supplier_lead_time_days = supplier_lead_time_days
        self.expected_replenishment_at = replenishment_at

        self._record_event(
            "stock_alert_forecast_updated",
            actor_id=actor_id,
            details={
                "forecast_demand": str(demand),
                "recommended_order_quantity": str(quantity),
            },
        )

    # ========================================================
    # TRIGGER
    # ========================================================

    def trigger(
        self,
        *,
        actor_id: str,
        observed_value: Decimal | str | float,
        threshold_value: Decimal | str | float,
        condition: str,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        self._require_status(
            StockAlertStatus.ACTIVE
        )

        observed = decimal_value(
            observed_value,
            "observed_value",
            minimum=Decimal("-99999999999999"),
        )
        threshold = decimal_value(
            threshold_value,
            "threshold_value",
            minimum=Decimal("-99999999999999"),
        )
        condition = required_text(
            condition,
            "Trigger condition",
        )
        safe_evidence = json_safe(evidence or {})

        self.observed_value = observed
        self.threshold_value = threshold
        self.trigger_condition = condition
        self.trigger_evidence = safe_evidence
        self.triggered_at = utc_now()
        self.status = StockAlertStatus.TRIGGERED

        self._record_event(
            "stock_alert_triggered",
            actor_id=actor_id,
            details={
                "observed_value": str(observed),
                "threshold_value": str(threshold),
                "condition": condition,
            },
        )

    # ========================================================
    # UPDATE AI ANALYSIS
    # ========================================================

    def update_ai_analysis(
        self,
        *,
        model_id: str,
        confidence: Decimal | str | float,
        risk_score: Decimal | str | float,
        risk_level: StockAlertRiskLevel,
        explanation: str,
        recommendations: list[dict[str, Any]],
        actor_id: str,
        risk_factors: list[dict[str, Any]] | None = None,
        model_version: str | None = None,
        agent_run_id: str | None = None,
    ) -> None:
        self._ensure_active()

        if self.is_terminal:
            raise ValueError(
                "Cannot analyze terminal stock alert"
            )

        if not isinstance(risk_level, StockAlertRiskLevel):
            raise ValueError("Invalid risk level")

        confidence_value = decimal_value(
            confidence,
            "confidence",
            maximum=Decimal("1"),
        )
        risk_value = decimal_value(
            risk_score,
            "risk_score",
            maximum=Decimal("1"),
        )

        if not isinstance(recommendations, list) or any(
            not isinstance(item, dict)
            for item in recommendations
        ):
            raise ValueError(
                "Recommendations must contain dictionaries"
            )

        factors = risk_factors or []

        if not isinstance(factors, list) or any(
            not isinstance(item, dict)
            for item in factors
        ):
            raise ValueError(
                "Risk factors must contain dictionaries"
            )

        safe_recommendations = json_safe(recommendations)
        safe_factors = json_safe(factors)

        self.ai_generated = True
        self.ai_model_id = required_text(
            model_id,
            "Model ID",
        )
        self.ai_model_version = optional_text(model_version)
        self.ai_agent_run_id = optional_text(agent_run_id)
        self.ai_confidence = confidence_value
        self.risk_score = risk_value
        self.risk_level = risk_level
        self.ai_explanation = required_text(
            explanation,
            "Explanation",
        )
        self.ai_recommendations = safe_recommendations
        self.risk_factors = safe_factors
        self.analyzed_at = utc_now()

        self._record_event(
            "stock_alert_ai_analysis_updated",
            actor_id=actor_id,
            details={
                "risk_level": risk_level.value,
                "risk_score": str(risk_value),
                "confidence": str(confidence_value),
            },
        )

    # ========================================================
    # FINANCIAL IMPACT
    # ========================================================

    def update_financial_impact(
        self,
        *,
        estimated_loss: Decimal | str | float,
        estimated_replenishment_cost: Decimal | str | float,
        estimated_lost_sales: Decimal | str | float,
        actor_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._ensure_active()

        if self.is_terminal:
            raise ValueError(
                "Cannot update terminal stock alert"
            )

        loss = decimal_value(
            estimated_loss,
            "estimated_loss",
        )
        replenishment_cost = decimal_value(
            estimated_replenishment_cost,
            "estimated_replenishment_cost",
        )
        lost_sales = decimal_value(
            estimated_lost_sales,
            "estimated_lost_sales",
        )
        safe_details = json_safe(details or {})

        self.estimated_loss = loss
        self.estimated_replenishment_cost = replenishment_cost
        self.estimated_lost_sales = lost_sales
        self.financial_impact_details = safe_details

        self._record_event(
            "stock_alert_financial_impact_updated",
            actor_id=actor_id,
            details={
                "estimated_loss": str(loss),
                "estimated_replenishment_cost": str(
                    replenishment_cost
                ),
                "estimated_lost_sales": str(lost_sales),
            },
        )

    # ========================================================
    # ACKNOWLEDGE
    # ========================================================

    def acknowledge(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            StockAlertStatus.TRIGGERED,
            StockAlertStatus.ESCALATED,
        )

        actor_id = required_text(
            actor_id,
            "Actor ID",
        )

        self.status = StockAlertStatus.ACKNOWLEDGED
        self.acknowledged_by = actor_id
        self.acknowledged_at = utc_now()

        self._record_event(
            "stock_alert_acknowledged",
            actor_id=actor_id,
        )

    # ========================================================
    # ASSIGN
    # ========================================================

    def assign(
        self,
        *,
        assigned_to: str,
        actor_id: str,
        due_at: datetime | None = None,
    ) -> None:
        self._ensure_active()

        if not self.is_open:
            raise ValueError(
                "Only open alerts can be assigned"
            )

        assignee = required_text(
            assigned_to,
            "Assignee",
        )
        due = (
            validate_datetime(due_at)
            if due_at is not None
            else None
        )

        self.assigned_to = assignee
        self.assigned_at = utc_now()
        self.action_due_at = due

        self._record_event(
            "stock_alert_assigned",
            actor_id=actor_id,
            details={"assigned_to": assignee},
        )

    # ========================================================
    # START INVESTIGATION
    # ========================================================

    def start_investigation(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            StockAlertStatus.ACKNOWLEDGED,
            StockAlertStatus.ESCALATED,
        )

        self.status = StockAlertStatus.INVESTIGATING
        self.investigation_started_at = utc_now()

        self._record_event(
            "stock_alert_investigation_started",
            actor_id=actor_id,
        )

    # ========================================================
    # ADD ACTION
    # ========================================================

    def add_action(
        self,
        *,
        action_type: StockAlertActionType,
        description: str,
        actor_id: str,
        assigned_to: str | None = None,
        due_at: datetime | None = None,
    ) -> str:
        self._require_status(
            StockAlertStatus.ACKNOWLEDGED,
            StockAlertStatus.INVESTIGATING,
            StockAlertStatus.ACTION_REQUIRED,
            StockAlertStatus.ESCALATED,
        )

        if not isinstance(action_type, StockAlertActionType):
            raise ValueError("Invalid action type")

        description = required_text(
            description,
            "Action description",
        )
        due = (
            validate_datetime(due_at)
            if due_at is not None
            else None
        )

        action_id = generate_uuid()
        actions = list(self.action_items or [])

        actions.append({
            "action_id": action_id,
            "action_type": action_type.value,
            "description": description,
            "assigned_to": optional_text(assigned_to),
            "due_at": serialize_datetime(due),
            "status": "pending",
            "created_at": utc_now().isoformat(),
            "completed_at": None,
            "completion_reference": None,
        })

        self.action_items = actions
        self.status = StockAlertStatus.ACTION_REQUIRED

        self._record_event(
            "stock_alert_action_added",
            actor_id=actor_id,
            details={
                "action_id": action_id,
                "action_type": action_type.value,
            },
        )

        return action_id

    # ========================================================
    # COMPLETE ACTION
    # ========================================================

    def complete_action(
        self,
        *,
        action_id: str,
        actor_id: str,
        completion_reference: str,
    ) -> None:
        self._require_status(
            StockAlertStatus.ACTION_REQUIRED,
            StockAlertStatus.APPROVED,
            StockAlertStatus.ESCALATED,
        )

        action_id = required_text(
            action_id,
            "Action ID",
        )
        reference = required_text(
            completion_reference,
            "Completion reference",
        )

        actions = [
            dict(item)
            for item in (self.action_items or [])
        ]

        action = next(
            (
                item for item in actions
                if item.get("action_id") == action_id
            ),
            None,
        )

        if action is None:
            raise ValueError("Action not found")

        if action.get("status") == "completed":
            raise ValueError("Action already completed")

        # External services must verify that the referenced
        # action actually succeeded before recording it.

        action["status"] = "completed"
        action["completed_at"] = utc_now().isoformat()
        action["completed_by"] = required_text(
            actor_id,
            "Actor ID",
        )
        action["completion_reference"] = reference

        self.action_items = actions

        self._record_event(
            "stock_alert_action_completed",
            actor_id=actor_id,
            details={
                "action_id": action_id,
                "completion_reference": reference,
            },
        )

    # ========================================================
    # REQUEST APPROVAL
    # ========================================================

    def request_approval(
        self,
        *,
        actor_id: str,
        approval_request_id: str,
    ) -> None:
        self._require_status(
            StockAlertStatus.ACTION_REQUIRED,
            StockAlertStatus.INVESTIGATING,
        )

        if not self.requires_approval:
            raise ValueError(
                "Approval is not required"
            )

        request_id = required_text(
            approval_request_id,
            "Approval request ID",
        )

        self.approval_request_id = request_id
        self.approval_status = (
            StockAlertApprovalStatus.PENDING
        )
        self.status = StockAlertStatus.PENDING_APPROVAL

        self._record_event(
            "stock_alert_approval_requested",
            actor_id=actor_id,
            details={
                "approval_request_id": request_id,
            },
        )

    # ========================================================
    # APPROVE
    # ========================================================

    def approve(
        self,
        *,
        approver_id: str,
    ) -> None:
        self._require_status(
            StockAlertStatus.PENDING_APPROVAL
        )

        approver_id = required_text(
            approver_id,
            "Approver ID",
        )

        # The approval service must verify permissions
        # and the linked approval request.

        self.approval_status = (
            StockAlertApprovalStatus.APPROVED
        )
        self.approved_by = approver_id
        self.approved_at = utc_now()
        self.status = StockAlertStatus.APPROVED

        self._record_event(
            "stock_alert_approved",
            actor_id=approver_id,
        )

    # ========================================================
    # REJECT APPROVAL
    # ========================================================

    def reject_approval(
        self,
        *,
        approver_id: str,
        reason: str,
    ) -> None:
        self._require_status(
            StockAlertStatus.PENDING_APPROVAL
        )

        approver_id = required_text(
            approver_id,
            "Approver ID",
        )
        reason = required_text(
            reason,
            "Rejection reason",
        )

        self.approval_status = (
            StockAlertApprovalStatus.REJECTED
        )
        self.rejection_reason = reason
        self.status = StockAlertStatus.ACTION_REQUIRED

        self._record_event(
            "stock_alert_approval_rejected",
            actor_id=approver_id,
            details={"reason": reason},
        )

    # ========================================================
    # RECORD NOTIFICATION
    # ========================================================

    def record_notification(
        self,
        *,
        notification_id: str,
        channel: str,
        actor_id: str,
        delivered: bool,
        error: str | None = None,
    ) -> None:
        self._ensure_active()

        notification_id = required_text(
            notification_id,
            "Notification ID",
        )
        channel = required_text(
            channel,
            "Notification channel",
        )

        ids = list(self.notification_ids or [])

        if notification_id in ids:
            raise ValueError(
                "Notification already recorded"
            )

        channels = list(self.notification_channels or [])

        ids.append(notification_id)

        if channel not in channels:
            channels.append(channel)

        self.notification_ids = ids
        self.notification_channels = channels
        self.notification_attempts = (
            self.notification_attempts or 0
        ) + 1
        self.last_notification_at = utc_now()

        if delivered:
            self.notification_status = (
                StockAlertNotificationStatus.SENT
            )
            self.notification_error = None
        else:
            self.notification_status = (
                StockAlertNotificationStatus.FAILED
            )
            self.notification_error = optional_text(error)

        self._record_event(
            "stock_alert_notification_recorded",
            actor_id=actor_id,
            details={
                "notification_id": notification_id,
                "channel": channel,
                "delivered": delivered,
            },
        )

    # ========================================================
    # ESCALATE
    # ========================================================

    def escalate(
        self,
        *,
        actor_id: str,
        reason: str,
        escalation_id: str | None = None,
    ) -> None:
        self._ensure_active()

        if not self.is_open:
            raise ValueError(
                "Only open alerts can be escalated"
            )

        reason = required_text(
            reason,
            "Escalation reason",
        )

        self.escalation_level = (
            self.escalation_level or 0
        ) + 1
        self.escalation_reason = reason
        self.escalation_id = optional_text(escalation_id)
        self.escalated_at = utc_now()
        self.escalated_by = required_text(
            actor_id,
            "Actor ID",
        )
        self.status = StockAlertStatus.ESCALATED

        self._record_event(
            "stock_alert_escalated",
            actor_id=actor_id,
            details={
                "escalation_level": self.escalation_level,
                "reason": reason,
                "escalation_id": self.escalation_id,
            },
        )

    # ========================================================
    # RECORD SLA BREACH
    # ========================================================

    def record_sla_breach(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_active()

        if not self.is_sla_overdue:
            raise ValueError(
                "SLA is not overdue"
            )

        if self.sla_breached:
            raise ValueError(
                "SLA breach already recorded"
            )

        self.sla_breached = True
        self.sla_breached_at = utc_now()

        self._record_event(
            "stock_alert_sla_breached",
            actor_id=actor_id,
        )

    # ========================================================
    # LINK REPLENISHMENT PLAN
    # ========================================================

    def link_replenishment_plan(
        self,
        *,
        replenishment_plan_id: str,
        actor_id: str,
    ) -> None:
        self._ensure_active()

        if not self.is_open:
            raise ValueError(
                "Only open alerts can be linked"
            )

        self.replenishment_plan_id = required_text(
            replenishment_plan_id,
            "Replenishment plan ID",
        )

        self._record_event(
            "stock_alert_replenishment_linked",
            actor_id=actor_id,
            details={
                "replenishment_plan_id": (
                    self.replenishment_plan_id
                ),
            },
        )

    # ========================================================
    # LINK PURCHASE ORDER
    # ========================================================

    def link_purchase_order(
        self,
        *,
        purchase_order_id: str,
        actor_id: str,
    ) -> None:
        self._ensure_active()

        if not self.is_open:
            raise ValueError(
                "Only open alerts can be linked"
            )

        self.purchase_order_id = required_text(
            purchase_order_id,
            "Purchase order ID",
        )

        self._record_event(
            "stock_alert_purchase_order_linked",
            actor_id=actor_id,
            details={
                "purchase_order_id": self.purchase_order_id,
            },
        )

    # ========================================================
    # RESOLVE
    # ========================================================

    def resolve(
        self,
        *,
        actor_id: str,
        resolution_type: StockAlertResolutionType,
        notes: str,
    ) -> None:
        self._ensure_active()

        if not self.is_open:
            raise ValueError(
                "Only open alerts can be resolved"
            )

        if not isinstance(
            resolution_type,
            StockAlertResolutionType,
        ):
            raise ValueError("Invalid resolution type")

        if self.requires_approval and not self.is_approved:
            raise ValueError(
                "Approval required before resolution"
            )

        incomplete_actions = [
            item for item in (self.action_items or [])
            if item.get("status") != "completed"
        ]

        if incomplete_actions:
            raise ValueError(
                "All required actions must be completed"
            )

        self.resolution_type = resolution_type
        self.resolution_notes = required_text(
            notes,
            "Resolution notes",
        )
        self.resolved_by = required_text(
            actor_id,
            "Actor ID",
        )
        self.resolved_at = utc_now()
        self.status = StockAlertStatus.RESOLVED

        self._record_event(
            "stock_alert_resolved",
            actor_id=actor_id,
            details={
                "resolution_type": resolution_type.value,
            },
        )

    # ========================================================
    # DISMISS
    # ========================================================

    def dismiss(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_active()

        if not self.is_open:
            raise ValueError(
                "Only open alerts can be dismissed"
            )

        self.dismissal_reason = required_text(
            reason,
            "Dismissal reason",
        )
        self.dismissed_by = required_text(
            actor_id,
            "Actor ID",
        )
        self.dismissed_at = utc_now()
        self.status = StockAlertStatus.DISMISSED

        self._record_event(
            "stock_alert_dismissed",
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # EXPIRE
    # ========================================================

    def expire(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_active()

        if not self.is_open:
            raise ValueError(
                "Only open alerts can expire"
            )

        if not self.is_expired:
            raise ValueError(
                "Alert expiration time not reached"
            )

        self.status = StockAlertStatus.EXPIRED
        self.expired_at = utc_now()

        self._record_event(
            "stock_alert_expired",
            actor_id=actor_id,
        )

    # ========================================================
    # CANCEL
    # ========================================================

    def cancel(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_active()

        if self.is_terminal:
            raise ValueError(
                "Terminal alert cannot be cancelled"
            )

        self.cancellation_reason = required_text(
            reason,
            "Cancellation reason",
        )
        self.cancelled_by = required_text(
            actor_id,
            "Actor ID",
        )
        self.cancelled_at = utc_now()
        self.status = StockAlertStatus.CANCELLED

        self._record_event(
            "stock_alert_cancelled",
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
        self._require_status(
            StockAlertStatus.RESOLVED,
            StockAlertStatus.DISMISSED,
            StockAlertStatus.EXPIRED,
            StockAlertStatus.CANCELLED,
        )

        self.status = StockAlertStatus.ARCHIVED
        self.archived_at = utc_now()

        self._record_event(
            "stock_alert_archived",
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
        self._require_status(
            StockAlertStatus.DRAFT,
            StockAlertStatus.CANCELLED,
            StockAlertStatus.ARCHIVED,
        )

        actor_id = required_text(
            actor_id,
            "Actor ID",
        )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = actor_id

        self._record_event(
            "stock_alert_soft_deleted",
            actor_id=actor_id,
        )

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(
        self,
        *,
        include_internal: bool = False,
        include_history: bool = False,
    ) -> dict[str, Any]:

        data = {
            "id": self.id,
            "organization_id": self.organization_id,
            "alert_number": self.alert_number,
            "title": self.title,
            "description": self.description,
            "alert_type": enum_value(self.alert_type),
            "status": enum_value(self.status),
            "severity": enum_value(self.severity),
            "priority": enum_value(self.priority),
            "source": enum_value(self.source),
            "product_id": self.product_id,
            "inventory_id": self.inventory_id,
            "warehouse_id": self.warehouse_id,
            "supplier_id": self.supplier_id,
            "category_id": self.category_id,
            "demand_forecast_id": self.demand_forecast_id,
            "replenishment_plan_id": (
                self.replenishment_plan_id
            ),
            "purchase_order_id": self.purchase_order_id,
            "simulation_run_id": self.simulation_run_id,
            "incident_id": self.incident_id,
            "escalation_id": self.escalation_id,
            "sku": self.sku,
            "batch_number": self.batch_number,
            "lot_number": self.lot_number,
            "bin_location": self.bin_location,
            "unit_of_measure": self.unit_of_measure,
            "current_quantity": serialize_decimal(
                self.current_quantity
            ),
            "available_quantity": serialize_decimal(
                self.available_quantity
            ),
            "reserved_quantity": serialize_decimal(
                self.reserved_quantity
            ),
            "incoming_quantity": serialize_decimal(
                self.incoming_quantity
            ),
            "reorder_point": serialize_decimal(
                self.reorder_point
            ),
            "safety_stock": serialize_decimal(
                self.safety_stock
            ),
            "minimum_stock": serialize_decimal(
                self.minimum_stock
            ),
            "maximum_stock": serialize_decimal(
                self.maximum_stock
            ),
            "stock_gap": serialize_decimal(
                self.stock_gap
            ),
            "safety_stock_gap": serialize_decimal(
                self.safety_stock_gap
            ),
            "projected_available_quantity": serialize_decimal(
                self.projected_available_quantity
            ),
            "forecast_demand": serialize_decimal(
                self.forecast_demand
            ),
            "recommended_order_quantity": serialize_decimal(
                self.recommended_order_quantity
            ),
            "estimated_stockout_days": serialize_decimal(
                self.estimated_stockout_days
            ),
            "expected_replenishment_at": serialize_datetime(
                self.expected_replenishment_at
            ),
            "risk_score": serialize_decimal(
                self.risk_score
            ),
            "risk_level": enum_value(self.risk_level),
            "ai_generated": self.ai_generated,
            "ai_confidence": serialize_decimal(
                self.ai_confidence
            ),
            "ai_recommendations": self.ai_recommendations,
            "currency": self.currency,
            "estimated_loss": serialize_decimal(
                self.estimated_loss
            ),
            "estimated_replenishment_cost": serialize_decimal(
                self.estimated_replenishment_cost
            ),
            "estimated_lost_sales": serialize_decimal(
                self.estimated_lost_sales
            ),
            "recommended_action": enum_value(
                self.recommended_action
            ),
            "action_items": self.action_items,
            "assigned_to": self.assigned_to,
            "assigned_at": serialize_datetime(
                self.assigned_at
            ),
            "action_due_at": serialize_datetime(
                self.action_due_at
            ),
            "requires_approval": self.requires_approval,
            "approval_status": enum_value(
                self.approval_status
            ),
            "notification_status": enum_value(
                self.notification_status
            ),
            "escalation_level": self.escalation_level,
            "sla_due_at": serialize_datetime(
                self.sla_due_at
            ),
            "sla_breached": self.sla_breached,
            "triggered_at": serialize_datetime(
                self.triggered_at
            ),
            "acknowledged_at": serialize_datetime(
                self.acknowledged_at
            ),
            "resolved_at": serialize_datetime(
                self.resolved_at
            ),
            "resolution_type": enum_value(
                self.resolution_type
            ),
            "resolution_notes": self.resolution_notes,
            "expires_at": serialize_datetime(
                self.expires_at
            ),
            "is_open": self.is_open,
            "is_terminal": self.is_terminal,
            "is_critical": self.is_critical,
            "is_sla_overdue": self.is_sla_overdue,
            "is_expired": self.is_expired,
            "created_at": serialize_datetime(
                self.created_at
            ),
            "updated_at": serialize_datetime(
                self.updated_at
            ),
            "is_deleted": self.is_deleted,
            "version": self.version,
        }

        if include_internal:
            data.update({
                "idempotency_key": self.idempotency_key,
                "source_reference_id": (
                    self.source_reference_id
                ),
                "rule_id": self.rule_id,
                "threshold_value": serialize_decimal(
                    self.threshold_value
                ),
                "observed_value": serialize_decimal(
                    self.observed_value
                ),
                "trigger_condition": (
                    self.trigger_condition
                ),
                "rule_configuration": (
                    self.rule_configuration
                ),
                "trigger_evidence": self.trigger_evidence,
                "ai_model_id": self.ai_model_id,
                "ai_model_version": (
                    self.ai_model_version
                ),
                "ai_agent_run_id": self.ai_agent_run_id,
                "ai_explanation": self.ai_explanation,
                "risk_factors": self.risk_factors,
                "financial_impact_details": (
                    self.financial_impact_details
                ),
                "recommended_action_details": (
                    self.recommended_action_details
                ),
                "approval_request_id": (
                    self.approval_request_id
                ),
                "approved_by": self.approved_by,
                "approved_at": serialize_datetime(
                    self.approved_at
                ),
                "rejection_reason": self.rejection_reason,
                "notification_ids": self.notification_ids,
                "notification_channels": (
                    self.notification_channels
                ),
                "notification_attempts": (
                    self.notification_attempts
                ),
                "notification_error": (
                    self.notification_error
                ),
                "escalation_reason": (
                    self.escalation_reason
                ),
                "escalated_at": serialize_datetime(
                    self.escalated_at
                ),
                "escalated_by": self.escalated_by,
                "acknowledged_by": self.acknowledged_by,
                "resolved_by": self.resolved_by,
                "dismissal_reason": (
                    self.dismissal_reason
                ),
                "cancellation_reason": (
                    self.cancellation_reason
                ),
                "alert_metadata": self.alert_metadata,
                "trace_id": self.trace_id,
                "correlation_id": self.correlation_id,
            })

        if include_history:
            data["alert_history"] = self.alert_history

        return data

    def __repr__(self) -> str:
        return (
            f"<StockAlert("
            f"id={self.id!r}, "
            f"alert_number={self.alert_number!r}, "
            f"type={enum_value(self.alert_type)!r}, "
            f"severity={enum_value(self.severity)!r}, "
            f"status={enum_value(self.status)!r}"
            f")>"
        )