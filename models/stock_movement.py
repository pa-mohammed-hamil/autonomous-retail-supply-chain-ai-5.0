from __future__ import annotations

"""Planned module: stock movement. Implementation pending."""
# backend/models/stock_movement.py


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

ZERO = Decimal("0.0000")
QUANTITY_LIMIT = Decimal("99999999999999.9999")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_movement_number() -> str:
    return f"MOV-{uuid.uuid4().hex[:18].upper()}"


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
        raise ValueError("Expected string or None")

    return value.strip() or None


def validate_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("Expected datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timezone-aware datetime required")

    return value.astimezone(timezone.utc)


def decimal_value(
    value: Decimal | str | int | float,
    field: str,
    *,
    minimum: Decimal = ZERO,
    maximum: Decimal = QUANTITY_LIMIT,
) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")

    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} must be numeric") from None

    if not result.is_finite():
        raise ValueError(f"{field} must be finite")

    if result < minimum or result > maximum:
        raise ValueError(
            f"{field} must be between {minimum} and {maximum}"
        )

    if result != result.quantize(Decimal("0.0001")):
        raise ValueError(
            f"{field} supports at most 4 decimal places"
        )

    return result


def positive_decimal(
    value: Decimal | str | int | float,
    field: str,
) -> Decimal:
    result = decimal_value(value, field)

    if result <= ZERO:
        raise ValueError(f"{field} must be greater than zero")

    return result


def enum_value(value: Any) -> Any:
    return value.value if isinstance(value, enum.Enum) else value


def serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def serialize_decimal(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        return str(
            decimal_value(
                value,
                "JSON numeric value",
                minimum=-QUANTITY_LIMIT,
            )
        )

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

class StockMovementStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_VALIDATION = "pending_validation"
    VALIDATED = "validated"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    RESERVED = "reserved"
    PROCESSING = "processing"
    IN_TRANSIT = "in_transit"
    PARTIALLY_COMPLETED = "partially_completed"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REVERSED = "reversed"
    ARCHIVED = "archived"


class StockMovementType(str, enum.Enum):
    PURCHASE_RECEIPT = "purchase_receipt"
    SALES_ISSUE = "sales_issue"
    CUSTOMER_RETURN = "customer_return"
    SUPPLIER_RETURN = "supplier_return"
    WAREHOUSE_TRANSFER = "warehouse_transfer"
    BIN_TRANSFER = "bin_transfer"
    STOCK_ADJUSTMENT_IN = "stock_adjustment_in"
    STOCK_ADJUSTMENT_OUT = "stock_adjustment_out"
    INVENTORY_RECONCILIATION = "inventory_reconciliation"
    REPLENISHMENT_RECEIPT = "replenishment_receipt"
    PRODUCTION_CONSUMPTION = "production_consumption"
    PRODUCTION_OUTPUT = "production_output"
    DAMAGED_STOCK = "damaged_stock"
    EXPIRED_STOCK = "expired_stock"
    QUARANTINE_IN = "quarantine_in"
    QUARANTINE_OUT = "quarantine_out"
    RESERVATION = "reservation"
    RESERVATION_RELEASE = "reservation_release"
    STOCK_WRITE_OFF = "stock_write_off"
    STOCK_RECOVERY = "stock_recovery"
    CYCLE_COUNT_ADJUSTMENT = "cycle_count_adjustment"
    PRODUCT_RECALL = "product_recall"
    SAMPLE_ISSUE = "sample_issue"
    DONATION = "donation"
    MANUAL = "manual"
    OTHER = "other"


class StockMovementDirection(str, enum.Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    TRANSFER = "transfer"
    ADJUSTMENT = "adjustment"
    RESERVATION = "reservation"
    RELEASE = "release"


class StockMovementSource(str, enum.Enum):
    MANUAL = "manual"
    API = "api"
    ERP = "erp"
    WMS = "wms"
    POS = "pos"
    PURCHASE_ORDER = "purchase_order"
    SALES_ORDER = "sales_order"
    FULFILLMENT = "fulfillment"
    RETURN_SERVICE = "return_service"
    REPLENISHMENT_ENGINE = "replenishment_engine"
    INVENTORY_SERVICE = "inventory_service"
    AI_AGENT = "ai_agent"
    SCHEDULER = "scheduler"
    SYSTEM = "system"


class StockMovementPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"


class StockMovementReason(str, enum.Enum):
    PURCHASE = "purchase"
    SALE = "sale"
    RETURN = "return"
    REPLENISHMENT = "replenishment"
    STOCK_TRANSFER = "stock_transfer"
    STOCK_COUNT_CORRECTION = "stock_count_correction"
    DAMAGED_GOODS = "damaged_goods"
    EXPIRED_GOODS = "expired_goods"
    QUALITY_FAILURE = "quality_failure"
    PRODUCT_RECALL = "product_recall"
    SUPPLIER_ERROR = "supplier_error"
    CUSTOMER_CANCELLATION = "customer_cancellation"
    ORDER_FULFILLMENT = "order_fulfillment"
    INVENTORY_OPTIMIZATION = "inventory_optimization"
    WAREHOUSE_REBALANCING = "warehouse_rebalancing"
    FORECAST_RECOMMENDATION = "forecast_recommendation"
    MANUAL_CORRECTION = "manual_correction"
    OTHER = "other"


class StockMovementApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class StockMovementQualityStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING_INSPECTION = "pending_inspection"
    PASSED = "passed"
    FAILED = "failed"
    QUARANTINED = "quarantined"


class StockMovementRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class StockMovementReconciliationStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    MATCHED = "matched"
    MISMATCHED = "mismatched"
    RESOLVED = "resolved"


# ============================================================
# STOCK MOVEMENT MODEL
# ============================================================

class StockMovement(Base):
    __tablename__ = "stock_movements"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "movement_number",
            name="uq_stock_movement_org_number",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_stock_movement_org_idempotency",
        ),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_stock_movement_org_id",
        ),
        CheckConstraint(
            "requested_quantity > 0",
            name="ck_stock_movement_requested_qty",
        ),
        CheckConstraint(
            "processed_quantity >= 0",
            name="ck_stock_movement_processed_qty",
        ),
        CheckConstraint(
            "processed_quantity <= requested_quantity",
            name="ck_stock_movement_processed_limit",
        ),
        CheckConstraint(
            "rejected_quantity >= 0",
            name="ck_stock_movement_rejected_qty",
        ),
        CheckConstraint(
            "processed_quantity + rejected_quantity "
            "<= requested_quantity",
            name="ck_stock_movement_total_limit",
        ),
        CheckConstraint(
            "reserved_quantity >= 0",
            name="ck_stock_movement_reserved_qty",
        ),
        CheckConstraint(
            "reserved_quantity <= requested_quantity",
            name="ck_stock_movement_reserved_limit",
        ),
        CheckConstraint(
            "source_quantity_before IS NULL OR "
            "source_quantity_before >= 0",
            name="ck_stock_movement_source_before",
        ),
        CheckConstraint(
            "source_quantity_after IS NULL OR "
            "source_quantity_after >= 0",
            name="ck_stock_movement_source_after",
        ),
        CheckConstraint(
            "destination_quantity_before IS NULL OR "
            "destination_quantity_before >= 0",
            name="ck_stock_movement_dest_before",
        ),
        CheckConstraint(
            "destination_quantity_after IS NULL OR "
            "destination_quantity_after >= 0",
            name="ck_stock_movement_dest_after",
        ),
        CheckConstraint(
            "unit_cost >= 0",
            name="ck_stock_movement_unit_cost",
        ),
        CheckConstraint(
            "total_cost >= 0",
            name="ck_stock_movement_total_cost",
        ),
        CheckConstraint(
            "transportation_cost >= 0",
            name="ck_stock_movement_transport_cost",
        ),
        CheckConstraint(
            "handling_cost >= 0",
            name="ck_stock_movement_handling_cost",
        ),
        CheckConstraint(
            "risk_score IS NULL OR "
            "(risk_score >= 0 AND risk_score <= 1)",
            name="ck_stock_movement_risk_score",
        ),
        CheckConstraint(
            "ai_confidence IS NULL OR "
            "(ai_confidence >= 0 AND ai_confidence <= 1)",
            name="ck_stock_movement_ai_confidence",
        ),
        CheckConstraint(
            "retry_count >= 0",
            name="ck_stock_movement_retry_count",
        ),
        CheckConstraint(
            "max_retries >= 0",
            name="ck_stock_movement_max_retries",
        ),
        CheckConstraint(
            "retry_count <= max_retries",
            name="ck_stock_movement_retry_limit",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_stock_movement_version",
        ),
        Index(
            "ix_stock_movement_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_stock_movement_org_type",
            "organization_id",
            "movement_type",
        ),
        Index(
            "ix_stock_movement_org_product",
            "organization_id",
            "product_id",
        ),
        Index(
            "ix_stock_movement_org_source_warehouse",
            "organization_id",
            "source_warehouse_id",
        ),
        Index(
            "ix_stock_movement_org_dest_warehouse",
            "organization_id",
            "destination_warehouse_id",
        ),
        Index(
            "ix_stock_movement_org_created",
            "organization_id",
            "created_at",
        ),
        Index(
            "ix_stock_movement_org_completed",
            "organization_id",
            "completed_at",
        ),
        Index(
            "ix_stock_movement_org_reference",
            "organization_id",
            "reference_type",
            "reference_id",
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

    movement_number: Mapped[str] = mapped_column(
        String(60),
        default=generate_movement_number,
        nullable=False,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # ========================================================
    # MOVEMENT DETAILS
    # ========================================================

    movement_type: Mapped[StockMovementType] = mapped_column(
        enum_column(
            StockMovementType,
            "stock_movement_type",
        ),
        nullable=False,
    )

    direction: Mapped[StockMovementDirection] = mapped_column(
        enum_column(
            StockMovementDirection,
            "stock_movement_direction",
        ),
        nullable=False,
    )

    status: Mapped[StockMovementStatus] = mapped_column(
        enum_column(
            StockMovementStatus,
            "stock_movement_status",
        ),
        default=StockMovementStatus.DRAFT,
        nullable=False,
    )

    source: Mapped[StockMovementSource] = mapped_column(
        enum_column(
            StockMovementSource,
            "stock_movement_source",
        ),
        default=StockMovementSource.INVENTORY_SERVICE,
        nullable=False,
    )

    priority: Mapped[StockMovementPriority] = mapped_column(
        enum_column(
            StockMovementPriority,
            "stock_movement_priority",
        ),
        default=StockMovementPriority.NORMAL,
        nullable=False,
    )

    reason: Mapped[StockMovementReason] = mapped_column(
        enum_column(
            StockMovementReason,
            "stock_movement_reason",
        ),
        default=StockMovementReason.OTHER,
        nullable=False,
    )

    reason_description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ========================================================
    # PRODUCT REFERENCES
    # ========================================================

    product_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    category_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    supplier_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    sku: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    barcode: Mapped[str | None] = mapped_column(
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

    serial_number: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    unit_of_measure: Mapped[str] = mapped_column(
        String(30),
        default="unit",
        nullable=False,
    )

    # ========================================================
    # SOURCE LOCATION
    # ========================================================

    source_warehouse_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    source_inventory_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    source_bin_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    source_bin_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # ========================================================
    # DESTINATION LOCATION
    # ========================================================

    destination_warehouse_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    destination_inventory_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    destination_bin_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    destination_bin_code: Mapped[
        str | None
    ] = mapped_column(
        String(100),
        nullable=True,
    )

    # ========================================================
    # QUANTITIES
    # ========================================================

    requested_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
    )

    processed_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    rejected_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    reserved_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    # ========================================================
    # STOCK BALANCES
    # ========================================================

    source_quantity_before: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    source_quantity_after: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    destination_quantity_before: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    destination_quantity_after: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    # ========================================================
    # FINANCIAL DETAILS
    # ========================================================

    currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    transportation_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    handling_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    cost_center_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # ========================================================
    # BUSINESS REFERENCES
    # ========================================================

    reference_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    reference_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    purchase_order_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    fulfillment_order_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    sales_transaction_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    return_request_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    replenishment_plan_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    demand_forecast_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    pick_task_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    pack_task_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    delivery_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    logistics_route_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    stock_alert_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    product_quality_issue_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    incident_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    simulation_run_id: Mapped[str | None] = mapped_column(
        String(36),
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
        StockMovementApprovalStatus
    ] = mapped_column(
        enum_column(
            StockMovementApprovalStatus,
            "stock_movement_approval_status",
        ),
        default=StockMovementApprovalStatus.NOT_REQUIRED,
        nullable=False,
    )

    approval_request_id: Mapped[
        str | None
    ] = mapped_column(
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
    # QUALITY CONTROL
    # ========================================================

    quality_status: Mapped[
        StockMovementQualityStatus
    ] = mapped_column(
        enum_column(
            StockMovementQualityStatus,
            "stock_movement_quality_status",
        ),
        default=StockMovementQualityStatus.NOT_REQUIRED,
        nullable=False,
    )

    quality_inspection_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    quality_checked_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    quality_checked_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    quality_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ========================================================
    # AI INTELLIGENCE
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

    ai_agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    ai_confidence: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    ai_recommendation: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    ai_explanation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    risk_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    risk_level: Mapped[
        StockMovementRiskLevel
    ] = mapped_column(
        enum_column(
            StockMovementRiskLevel,
            "stock_movement_risk_level",
        ),
        default=StockMovementRiskLevel.UNKNOWN,
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
    # EXECUTION
    # ========================================================

    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    validated_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    reserved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    processing_started_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    processed_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    failure_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    max_retries: Mapped[int] = mapped_column(
        Integer,
        default=3,
        nullable=False,
    )

    # ========================================================
    # RECONCILIATION
    # ========================================================

    reconciliation_status: Mapped[
        StockMovementReconciliationStatus
    ] = mapped_column(
        enum_column(
            StockMovementReconciliationStatus,
            "stock_movement_reconciliation_status",
        ),
        default=StockMovementReconciliationStatus.NOT_REQUIRED,
        nullable=False,
    )

    reconciliation_reference: Mapped[
        str | None
    ] = mapped_column(
        String(150),
        nullable=True,
    )

    reconciled_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    reconciled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    reconciliation_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ========================================================
    # REVERSAL
    # ========================================================

    reversal_of_movement_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    reversal_movement_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    reversed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    reversed_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    reversal_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ========================================================
    # CANCELLATION / ARCHIVE
    # ========================================================

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

    movement_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    movement_history: Mapped[
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
    # COMPUTED PROPERTIES
    # ========================================================

    @property
    def remaining_quantity(self) -> Decimal:
        return max(
            ZERO,
            (self.requested_quantity or ZERO)
            - (self.processed_quantity or ZERO)
            - (self.rejected_quantity or ZERO),
        )

    @property
    def completion_percentage(self) -> Decimal:
        requested = self.requested_quantity or ZERO

        if requested <= ZERO:
            return ZERO

        return (
            (self.processed_quantity or ZERO)
            / requested
            * Decimal("100")
        ).quantize(Decimal("0.0001"))

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            StockMovementStatus.COMPLETED,
            StockMovementStatus.REJECTED,
            StockMovementStatus.CANCELLED,
            StockMovementStatus.REVERSED,
            StockMovementStatus.ARCHIVED,
        }

    @property
    def is_approved(self) -> bool:
        return (
            not self.requires_approval
            or self.approval_status
            == StockMovementApprovalStatus.APPROVED
        )

    @property
    def can_retry(self) -> bool:
        return (
            not self.is_deleted
            and self.status == StockMovementStatus.FAILED
            and (self.retry_count or 0)
            < (
                self.max_retries
                if self.max_retries is not None
                else 3
            )
        )

    @property
    def requires_source_location(self) -> bool:
        return self.direction in {
            StockMovementDirection.OUTBOUND,
            StockMovementDirection.TRANSFER,
            StockMovementDirection.RESERVATION,
            StockMovementDirection.RELEASE,
        }

    @property
    def requires_destination_location(self) -> bool:
        return self.direction in {
            StockMovementDirection.INBOUND,
            StockMovementDirection.TRANSFER,
        }

    # ========================================================
    # INTERNAL METHODS
    # ========================================================

    def _touch(self, actor_id: str | None = None) -> None:
        self.updated_at = utc_now()

        if actor_id is not None:
            self.updated_by = actor_id

    def _ensure_active(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Stock movement has been deleted"
            )

    def _require_status(
        self,
        *statuses: StockMovementStatus,
    ) -> None:
        self._ensure_active()

        if self.status not in statuses:
            raise ValueError(
                "Invalid stock movement status: "
                f"{enum_value(self.status)}"
            )

    def _record_event(
        self,
        event: str,
        *,
        actor_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        history = list(self.movement_history or [])

        history.append({
            "event_id": generate_uuid(),
            "event": required_text(event, "Event"),
            "actor_id": actor_id,
            "timestamp": utc_now().isoformat(),
            "details": json_safe(details or {}),
        })

        self.movement_history = history
        self._touch(actor_id)

    def _validate_locations(self) -> None:
        if self.requires_source_location:
            if not self.source_warehouse_id:
                raise ValueError(
                    "Source warehouse is required"
                )

        if self.requires_destination_location:
            if not self.destination_warehouse_id:
                raise ValueError(
                    "Destination warehouse is required"
                )

        if self.direction == StockMovementDirection.TRANSFER:
            if (
                self.source_warehouse_id
                == self.destination_warehouse_id
                and (
                    self.source_bin_id
                    == self.destination_bin_id
                )
            ):
                raise ValueError(
                    "Transfer source and destination "
                    "cannot be identical"
                )

    def _validate_movement(self) -> None:
        required_text(
            self.organization_id,
            "Organization ID",
        )
        required_text(self.product_id, "Product ID")

        if not isinstance(
            self.movement_type,
            StockMovementType,
        ):
            raise ValueError("Invalid movement type")

        if not isinstance(
            self.direction,
            StockMovementDirection,
        ):
            raise ValueError("Invalid movement direction")

        positive_decimal(
            self.requested_quantity,
            "requested_quantity",
        )

        self._validate_locations()

    # ========================================================
    # UPDATE QUANTITY
    # ========================================================

    def update_requested_quantity(
        self,
        *,
        quantity: Decimal | str | float,
        actor_id: str,
    ) -> None:
        self._require_status(
            StockMovementStatus.DRAFT
        )

        new_quantity = positive_decimal(
            quantity,
            "quantity",
        )

        if (
            (self.processed_quantity or ZERO) > new_quantity
            or (self.rejected_quantity or ZERO) > new_quantity
            or (self.reserved_quantity or ZERO) > new_quantity
        ):
            raise ValueError(
                "New quantity is below existing allocations"
            )

        self.requested_quantity = new_quantity

        self._record_event(
            "stock_movement_quantity_updated",
            actor_id=actor_id,
            details={"quantity": str(new_quantity)},
        )

    # ========================================================
    # CONFIGURE LOCATIONS
    # ========================================================

    def configure_locations(
        self,
        *,
        actor_id: str,
        source_warehouse_id: str | None = None,
        source_inventory_id: str | None = None,
        source_bin_id: str | None = None,
        destination_warehouse_id: str | None = None,
        destination_inventory_id: str | None = None,
        destination_bin_id: str | None = None,
    ) -> None:
        self._require_status(
            StockMovementStatus.DRAFT
        )

        new_source = optional_text(source_warehouse_id)
        new_destination = optional_text(
            destination_warehouse_id
        )
        new_source_bin = optional_text(source_bin_id)
        new_destination_bin = optional_text(
            destination_bin_id
        )

        if self.requires_source_location and not new_source:
            raise ValueError("Source warehouse is required")

        if (
            self.requires_destination_location
            and not new_destination
        ):
            raise ValueError(
                "Destination warehouse is required"
            )

        if (
            self.direction == StockMovementDirection.TRANSFER
            and new_source == new_destination
            and new_source_bin == new_destination_bin
        ):
            raise ValueError(
                "Source and destination must differ"
            )

        self.source_warehouse_id = new_source
        self.source_inventory_id = optional_text(
            source_inventory_id
        )
        self.source_bin_id = new_source_bin
        self.destination_warehouse_id = new_destination
        self.destination_inventory_id = optional_text(
            destination_inventory_id
        )
        self.destination_bin_id = new_destination_bin

        self._record_event(
            "stock_movement_locations_configured",
            actor_id=actor_id,
            details={
                "source_warehouse_id": new_source,
                "destination_warehouse_id": new_destination,
            },
        )

    # ========================================================
    # UPDATE COST
    # ========================================================

    def update_cost(
        self,
        *,
        unit_cost: Decimal | str | float,
        actor_id: str,
        transportation_cost: Decimal | str | float = ZERO,
        handling_cost: Decimal | str | float = ZERO,
    ) -> None:
        self._require_status(
            StockMovementStatus.DRAFT,
            StockMovementStatus.PENDING_VALIDATION,
        )

        unit = decimal_value(unit_cost, "unit_cost")
        transport = decimal_value(
            transportation_cost,
            "transportation_cost",
        )
        handling = decimal_value(
            handling_cost,
            "handling_cost",
        )

        total = (
            unit * (self.requested_quantity or ZERO)
            + transport
            + handling
        )

        total = total.quantize(Decimal("0.0001"))

        if total > QUANTITY_LIMIT:
            raise ValueError("Total cost exceeds supported range")

        self.unit_cost = unit
        self.transportation_cost = transport
        self.handling_cost = handling
        self.total_cost = total

        self._record_event(
            "stock_movement_cost_updated",
            actor_id=actor_id,
            details={
                "unit_cost": str(unit),
                "total_cost": str(total),
            },
        )

    # ========================================================
    # SUBMIT FOR VALIDATION
    # ========================================================

    def submit_for_validation(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            StockMovementStatus.DRAFT
        )

        self._validate_movement()

        self.status = (
            StockMovementStatus.PENDING_VALIDATION
        )

        self._record_event(
            "stock_movement_validation_requested",
            actor_id=actor_id,
        )

    # ========================================================
    # VALIDATE
    # ========================================================

    def validate(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            StockMovementStatus.PENDING_VALIDATION
        )

        self._validate_movement()

        # Inventory availability, ownership, tenant isolation,
        # product status and warehouse rules must be checked
        # by the inventory service before this method is called.

        self.validated_by = required_text(
            actor_id,
            "Actor ID",
        )
        self.validated_at = utc_now()
        self.status = StockMovementStatus.VALIDATED

        self._record_event(
            "stock_movement_validated",
            actor_id=actor_id,
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
            StockMovementStatus.VALIDATED
        )

        if not self.requires_approval:
            raise ValueError(
                "Approval is not required"
            )

        self.approval_request_id = required_text(
            approval_request_id,
            "Approval request ID",
        )
        self.approval_status = (
            StockMovementApprovalStatus.PENDING
        )
        self.status = (
            StockMovementStatus.PENDING_APPROVAL
        )

        self._record_event(
            "stock_movement_approval_requested",
            actor_id=actor_id,
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
            StockMovementStatus.PENDING_APPROVAL
        )

        approver_id = required_text(
            approver_id,
            "Approver ID",
        )

        self.approval_status = (
            StockMovementApprovalStatus.APPROVED
        )
        self.approved_by = approver_id
        self.approved_at = utc_now()
        self.status = StockMovementStatus.APPROVED

        self._record_event(
            "stock_movement_approved",
            actor_id=approver_id,
        )

    # ========================================================
    # REJECT
    # ========================================================

    def reject(
        self,
        *,
        approver_id: str,
        reason: str,
    ) -> None:
        self._require_status(
            StockMovementStatus.PENDING_APPROVAL
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
            StockMovementApprovalStatus.REJECTED
        )
        self.rejected_by = approver_id
        self.rejected_at = utc_now()
        self.rejection_reason = reason
        self.status = StockMovementStatus.REJECTED

        self._record_event(
            "stock_movement_rejected",
            actor_id=approver_id,
            details={"reason": reason},
        )

    # ========================================================
    # RESERVE
    # ========================================================

    def reserve(
        self,
        *,
        quantity: Decimal | str | float,
        actor_id: str,
        reservation_reference: str,
    ) -> None:
        self._require_status(
            StockMovementStatus.VALIDATED,
            StockMovementStatus.APPROVED,
        )

        if not self.is_approved:
            raise ValueError(
                "Movement requires approval"
            )

        quantity_value = positive_decimal(
            quantity,
            "quantity",
        )

        if quantity_value > (
            self.requested_quantity or ZERO
        ):
            raise ValueError(
                "Reserved quantity exceeds requested quantity"
            )

        reference = required_text(
            reservation_reference,
            "Reservation reference",
        )

        # Stock must be reserved atomically by the inventory
        # service. This method only records the reservation.

        self.reserved_quantity = quantity_value
        self.reserved_at = utc_now()
        self.status = StockMovementStatus.RESERVED

        metadata = dict(self.movement_metadata or {})
        metadata["reservation_reference"] = reference
        self.movement_metadata = metadata

        self._record_event(
            "stock_movement_reserved",
            actor_id=actor_id,
            details={
                "quantity": str(quantity_value),
                "reservation_reference": reference,
            },
        )

    # ========================================================
    # START PROCESSING
    # ========================================================

    def start_processing(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            StockMovementStatus.VALIDATED,
            StockMovementStatus.APPROVED,
            StockMovementStatus.RESERVED,
        )

        if not self.is_approved:
            raise ValueError(
                "Movement requires approval"
            )

        if self.quality_status in {
            StockMovementQualityStatus.FAILED,
            StockMovementQualityStatus.QUARANTINED,
        }:
            raise ValueError(
                "Quality status blocks processing"
            )

        self.status = StockMovementStatus.PROCESSING
        self.processing_started_at = utc_now()
        self.processed_by = required_text(
            actor_id,
            "Actor ID",
        )

        self._record_event(
            "stock_movement_processing_started",
            actor_id=actor_id,
        )

    # ========================================================
    # RECORD STOCK POSTING
    # ========================================================

    def record_stock_posting(
        self,
        *,
        quantity: Decimal | str | float,
        actor_id: str,
        ledger_reference: str,
        source_quantity_before: Decimal | str | float | None = None,
        source_quantity_after: Decimal | str | float | None = None,
        destination_quantity_before: Decimal | str | float | None = None,
        destination_quantity_after: Decimal | str | float | None = None,
    ) -> None:
        self._require_status(
            StockMovementStatus.PROCESSING,
            StockMovementStatus.PARTIALLY_COMPLETED,
            StockMovementStatus.IN_TRANSIT,
        )

        quantity_value = positive_decimal(
            quantity,
            "quantity",
        )

        reference = required_text(
            ledger_reference,
            "Ledger reference",
        )

        existing_postings = list(
            (self.movement_metadata or {}).get(
                "ledger_postings",
                [],
            )
        )

        if any(
            item.get("ledger_reference") == reference
            for item in existing_postings
        ):
            raise ValueError(
                "Ledger reference already recorded"
            )

        current_processed = self.processed_quantity or ZERO
        current_rejected = self.rejected_quantity or ZERO

        if (
            current_processed
            + current_rejected
            + quantity_value
            > self.requested_quantity
        ):
            raise ValueError(
                "Posting exceeds requested quantity"
            )

        source_before = (
            decimal_value(
                source_quantity_before,
                "source_quantity_before",
            )
            if source_quantity_before is not None
            else None
        )

        source_after = (
            decimal_value(
                source_quantity_after,
                "source_quantity_after",
            )
            if source_quantity_after is not None
            else None
        )

        destination_before = (
            decimal_value(
                destination_quantity_before,
                "destination_quantity_before",
            )
            if destination_quantity_before is not None
            else None
        )

        destination_after = (
            decimal_value(
                destination_quantity_after,
                "destination_quantity_after",
            )
            if destination_quantity_after is not None
            else None
        )

        if (source_before is None) != (source_after is None):
            raise ValueError(
                "Both source balances must be provided together"
            )

        if (
            (destination_before is None)
            != (destination_after is None)
        ):
            raise ValueError(
                "Both destination balances must be "
                "provided together"
            )

        # Inventory service responsibilities:
        # 1. Lock affected inventory rows.
        # 2. Verify available stock and tenant ownership.
        # 3. Write immutable stock ledger entries.
        # 4. Update inventory balances in one transaction.
        # 5. Enforce unique ledger_reference at DB level.
        # 6. Call this method within the same transaction.
        #
        # This ORM method does not modify inventory balances.

        new_processed = current_processed + quantity_value

        posting = {
            "posting_id": generate_uuid(),
            "ledger_reference": reference,
            "quantity": str(quantity_value),
            "source_quantity_before": serialize_decimal(
                source_before
            ),
            "source_quantity_after": serialize_decimal(
                source_after
            ),
            "destination_quantity_before": serialize_decimal(
                destination_before
            ),
            "destination_quantity_after": serialize_decimal(
                destination_after
            ),
            "posted_by": actor_id,
            "posted_at": utc_now().isoformat(),
        }

        existing_postings.append(posting)

        metadata = dict(self.movement_metadata or {})
        metadata["ledger_postings"] = existing_postings

        self.movement_metadata = metadata
        self.processed_quantity = new_processed

        if source_before is not None:
            self.source_quantity_before = (
                self.source_quantity_before
                if self.source_quantity_before is not None
                else source_before
            )
            self.source_quantity_after = source_after

        if destination_before is not None:
            self.destination_quantity_before = (
                self.destination_quantity_before
                if self.destination_quantity_before is not None
                else destination_before
            )
            self.destination_quantity_after = destination_after

        self.status = (
            StockMovementStatus.PARTIALLY_COMPLETED
        )

        self._record_event(
            "stock_movement_stock_posted",
            actor_id=actor_id,
            details={
                "quantity": str(quantity_value),
                "processed_quantity": str(new_processed),
                "ledger_reference": reference,
            },
        )

    # ========================================================
    # RECORD REJECTED QUANTITY
    # ========================================================

    def record_rejected_quantity(
        self,
        *,
        quantity: Decimal | str | float,
        actor_id: str,
        reason: str,
    ) -> None:
        self._require_status(
            StockMovementStatus.PROCESSING,
            StockMovementStatus.PARTIALLY_COMPLETED,
        )

        quantity_value = positive_decimal(
            quantity,
            "quantity",
        )
        reason = required_text(
            reason,
            "Rejection reason",
        )

        if quantity_value > self.remaining_quantity:
            raise ValueError(
                "Rejected quantity exceeds remaining quantity"
            )

        self.rejected_quantity = (
            (self.rejected_quantity or ZERO)
            + quantity_value
        )

        self._record_event(
            "stock_movement_quantity_rejected",
            actor_id=actor_id,
            details={
                "quantity": str(quantity_value),
                "reason": reason,
            },
        )

    # ========================================================
    # DISPATCH TRANSFER
    # ========================================================

    def dispatch_transfer(
        self,
        *,
        actor_id: str,
        dispatch_reference: str,
    ) -> None:
        self._require_status(
            StockMovementStatus.PROCESSING
        )

        if self.direction != StockMovementDirection.TRANSFER:
            raise ValueError(
                "Only transfers can be dispatched"
            )

        reference = required_text(
            dispatch_reference,
            "Dispatch reference",
        )

        metadata = dict(self.movement_metadata or {})
        metadata["dispatch_reference"] = reference
        self.movement_metadata = metadata

        self.dispatched_at = utc_now()
        self.status = StockMovementStatus.IN_TRANSIT

        self._record_event(
            "stock_movement_transfer_dispatched",
            actor_id=actor_id,
            details={
                "dispatch_reference": reference,
            },
        )

    # ========================================================
    # RECORD TRANSFER RECEIPT
    # ========================================================

    def record_transfer_receipt(
        self,
        *,
        actor_id: str,
        receipt_reference: str,
    ) -> None:
        self._require_status(
            StockMovementStatus.IN_TRANSIT
        )

        reference = required_text(
            receipt_reference,
            "Receipt reference",
        )

        metadata = dict(self.movement_metadata or {})
        metadata["receipt_reference"] = reference
        self.movement_metadata = metadata

        self.received_at = utc_now()
        self.status = StockMovementStatus.PROCESSING

        self._record_event(
            "stock_movement_transfer_received",
            actor_id=actor_id,
            details={"receipt_reference": reference},
        )

    # ========================================================
    # UPDATE QUALITY
    # ========================================================

    def update_quality_status(
        self,
        *,
        quality_status: StockMovementQualityStatus,
        actor_id: str,
        inspection_id: str | None = None,
        notes: str | None = None,
    ) -> None:
        self._ensure_active()

        if self.is_terminal:
            raise ValueError(
                "Cannot update terminal movement"
            )

        if not isinstance(
            quality_status,
            StockMovementQualityStatus,
        ):
            raise ValueError(
                "Invalid quality status"
            )

        self.quality_status = quality_status
        self.quality_inspection_id = optional_text(
            inspection_id
        )
        self.quality_checked_by = required_text(
            actor_id,
            "Actor ID",
        )
        self.quality_checked_at = utc_now()
        self.quality_notes = optional_text(notes)

        self._record_event(
            "stock_movement_quality_updated",
            actor_id=actor_id,
            details={
                "quality_status": quality_status.value,
                "inspection_id": inspection_id,
            },
        )

    # ========================================================
    # AI RISK ANALYSIS
    # ========================================================

    def update_ai_analysis(
        self,
        *,
        model_id: str,
        confidence: Decimal | str | float,
        risk_score: Decimal | str | float,
        risk_level: StockMovementRiskLevel,
        recommendation: str,
        explanation: str,
        actor_id: str,
        agent_run_id: str | None = None,
        risk_factors: list[dict[str, Any]] | None = None,
    ) -> None:
        self._ensure_active()

        if self.is_terminal:
            raise ValueError(
                "Cannot analyze terminal movement"
            )

        if not isinstance(
            risk_level,
            StockMovementRiskLevel,
        ):
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

        factors = risk_factors or []

        if not isinstance(factors, list) or any(
            not isinstance(item, dict)
            for item in factors
        ):
            raise ValueError(
                "Risk factors must be a list of dictionaries"
            )

        safe_factors = json_safe(factors)

        self.ai_model_id = required_text(
            model_id,
            "Model ID",
        )
        self.ai_agent_run_id = optional_text(
            agent_run_id
        )
        self.ai_confidence = confidence_value
        self.risk_score = risk_value
        self.risk_level = risk_level
        self.ai_recommendation = required_text(
            recommendation,
            "Recommendation",
        )
        self.ai_explanation = required_text(
            explanation,
            "Explanation",
        )
        self.risk_factors = safe_factors
        self.ai_generated = True
        self.analyzed_at = utc_now()

        self._record_event(
            "stock_movement_ai_analysis_updated",
            actor_id=actor_id,
            details={
                "risk_score": str(risk_value),
                "risk_level": risk_level.value,
                "confidence": str(confidence_value),
            },
        )

    # ========================================================
    # COMPLETE MOVEMENT
    # ========================================================

    def complete(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            StockMovementStatus.PROCESSING,
            StockMovementStatus.PARTIALLY_COMPLETED,
        )

        if not self.is_approved:
            raise ValueError(
                "Movement requires approval"
            )

        if self.quality_status in {
            StockMovementQualityStatus.PENDING_INSPECTION,
            StockMovementQualityStatus.FAILED,
            StockMovementQualityStatus.QUARANTINED,
        }:
            raise ValueError(
                "Quality inspection blocks completion"
            )

        if self.remaining_quantity != ZERO:
            raise ValueError(
                "All requested quantity must be "
                "processed or rejected"
            )

        if (self.processed_quantity or ZERO) <= ZERO:
            raise ValueError(
                "Movement has no successfully posted quantity"
            )

        if (
            self.direction == StockMovementDirection.TRANSFER
            and self.received_at is None
        ):
            raise ValueError(
                "Transfer receipt must be recorded"
            )

        self.status = StockMovementStatus.COMPLETED
        self.completed_at = utc_now()

        self._record_event(
            "stock_movement_completed",
            actor_id=actor_id,
            details={
                "processed_quantity": str(
                    self.processed_quantity
                ),
                "rejected_quantity": str(
                    self.rejected_quantity
                ),
            },
        )

    # ========================================================
    # FAIL
    # ========================================================

    def fail(
        self,
        *,
        actor_id: str,
        failure_code: str,
        failure_reason: str,
    ) -> None:
        self._require_status(
            StockMovementStatus.RESERVED,
            StockMovementStatus.PROCESSING,
            StockMovementStatus.IN_TRANSIT,
            StockMovementStatus.PARTIALLY_COMPLETED,
        )

        self.failure_code = required_text(
            failure_code,
            "Failure code",
        )
        self.failure_reason = required_text(
            failure_reason,
            "Failure reason",
        )
        self.failed_at = utc_now()
        self.status = StockMovementStatus.FAILED

        self._record_event(
            "stock_movement_failed",
            actor_id=actor_id,
            details={
                "failure_code": self.failure_code,
            },
        )

    # ========================================================
    # RETRY
    # ========================================================

    def retry(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_active()

        if not self.can_retry:
            raise ValueError(
                "Movement cannot be retried"
            )

        # Existing ledger postings must never be replayed.
        # Retry services must resume from verified balances
        # and unprocessed quantities.

        self.retry_count = (
            self.retry_count or 0
        ) + 1

        self.status = StockMovementStatus.VALIDATED
        self.failure_code = None
        self.failure_reason = None
        self.failed_at = None

        self._record_event(
            "stock_movement_retry_requested",
            actor_id=actor_id,
            details={
                "retry_count": self.retry_count,
                "remaining_quantity": str(
                    self.remaining_quantity
                ),
            },
        )

    # ========================================================
    # RECONCILIATION
    # ========================================================

    def reconcile(
        self,
        *,
        actor_id: str,
        reference: str,
        matched: bool,
        notes: str | None = None,
    ) -> None:
        self._require_status(
            StockMovementStatus.COMPLETED,
            StockMovementStatus.REVERSED,
        )

        reference = required_text(
            reference,
            "Reconciliation reference",
        )

        self.reconciliation_status = (
            StockMovementReconciliationStatus.MATCHED
            if matched
            else StockMovementReconciliationStatus.MISMATCHED
        )

        self.reconciliation_reference = reference
        self.reconciled_by = required_text(
            actor_id,
            "Actor ID",
        )
        self.reconciled_at = utc_now()
        self.reconciliation_notes = optional_text(notes)

        self._record_event(
            "stock_movement_reconciled",
            actor_id=actor_id,
            details={
                "reference": reference,
                "matched": matched,
            },
        )

    # ========================================================
    # RECORD REVERSAL
    # ========================================================

    def record_reversal(
        self,
        *,
        actor_id: str,
        reversal_movement_id: str,
        reason: str,
    ) -> None:
        self._require_status(
            StockMovementStatus.COMPLETED
        )

        if self.reversal_movement_id:
            raise ValueError(
                "Movement has already been reversed"
            )

        reversal_id = required_text(
            reversal_movement_id,
            "Reversal movement ID",
        )

        if reversal_id == self.id:
            raise ValueError(
                "Movement cannot reverse itself"
            )

        reason = required_text(
            reason,
            "Reversal reason",
        )

        # The inventory service must verify that a separate,
        # opposite-direction stock movement has been posted
        # successfully before marking this record reversed.

        self.reversal_movement_id = reversal_id
        self.reversal_reason = reason
        self.reversed_by = required_text(
            actor_id,
            "Actor ID",
        )
        self.reversed_at = utc_now()
        self.status = StockMovementStatus.REVERSED

        self._record_event(
            "stock_movement_reversed",
            actor_id=actor_id,
            details={
                "reversal_movement_id": reversal_id,
                "reason": reason,
            },
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
                "Terminal movement cannot be cancelled"
            )

        if (self.processed_quantity or ZERO) > ZERO:
            raise ValueError(
                "Posted stock cannot be cancelled; "
                "create a compensating movement"
            )

        if self.status in {
            StockMovementStatus.IN_TRANSIT,
            StockMovementStatus.PARTIALLY_COMPLETED,
        }:
            raise ValueError(
                "Movement requires operational reconciliation"
            )

        # Any active inventory reservation must be released
        # by the inventory service before cancellation.

        self.cancellation_reason = required_text(
            reason,
            "Cancellation reason",
        )
        self.cancelled_by = required_text(
            actor_id,
            "Actor ID",
        )
        self.cancelled_at = utc_now()
        self.status = StockMovementStatus.CANCELLED

        self._record_event(
            "stock_movement_cancelled",
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
            StockMovementStatus.COMPLETED,
            StockMovementStatus.REJECTED,
            StockMovementStatus.CANCELLED,
            StockMovementStatus.REVERSED,
        )

        self.status = StockMovementStatus.ARCHIVED
        self.archived_at = utc_now()

        self._record_event(
            "stock_movement_archived",
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
            StockMovementStatus.DRAFT,
            StockMovementStatus.CANCELLED,
        )

        if (self.processed_quantity or ZERO) > ZERO:
            raise ValueError(
                "Posted movements cannot be deleted"
            )

        if (self.reserved_quantity or ZERO) > ZERO:
            raise ValueError(
                "Release reservations before deletion"
            )

        actor_id = required_text(
            actor_id,
            "Actor ID",
        )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = actor_id

        self._record_event(
            "stock_movement_soft_deleted",
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
            "movement_number": self.movement_number,
            "movement_type": enum_value(self.movement_type),
            "direction": enum_value(self.direction),
            "status": enum_value(self.status),
            "source": enum_value(self.source),
            "priority": enum_value(self.priority),
            "reason": enum_value(self.reason),
            "reason_description": self.reason_description,
            "product_id": self.product_id,
            "category_id": self.category_id,
            "supplier_id": self.supplier_id,
            "sku": self.sku,
            "barcode": self.barcode,
            "batch_number": self.batch_number,
            "lot_number": self.lot_number,
            "serial_number": self.serial_number,
            "unit_of_measure": self.unit_of_measure,
            "source_warehouse_id": self.source_warehouse_id,
            "source_inventory_id": self.source_inventory_id,
            "source_bin_id": self.source_bin_id,
            "destination_warehouse_id": (
                self.destination_warehouse_id
            ),
            "destination_inventory_id": (
                self.destination_inventory_id
            ),
            "destination_bin_id": self.destination_bin_id,
            "requested_quantity": serialize_decimal(
                self.requested_quantity
            ),
            "processed_quantity": serialize_decimal(
                self.processed_quantity
            ),
            "rejected_quantity": serialize_decimal(
                self.rejected_quantity
            ),
            "reserved_quantity": serialize_decimal(
                self.reserved_quantity
            ),
            "remaining_quantity": serialize_decimal(
                self.remaining_quantity
            ),
            "completion_percentage": serialize_decimal(
                self.completion_percentage
            ),
            "source_quantity_before": serialize_decimal(
                self.source_quantity_before
            ),
            "source_quantity_after": serialize_decimal(
                self.source_quantity_after
            ),
            "destination_quantity_before": serialize_decimal(
                self.destination_quantity_before
            ),
            "destination_quantity_after": serialize_decimal(
                self.destination_quantity_after
            ),
            "currency": self.currency,
            "unit_cost": serialize_decimal(self.unit_cost),
            "total_cost": serialize_decimal(self.total_cost),
            "transportation_cost": serialize_decimal(
                self.transportation_cost
            ),
            "handling_cost": serialize_decimal(
                self.handling_cost
            ),
            "reference_type": self.reference_type,
            "reference_id": self.reference_id,
            "purchase_order_id": self.purchase_order_id,
            "fulfillment_order_id": self.fulfillment_order_id,
            "sales_transaction_id": self.sales_transaction_id,
            "return_request_id": self.return_request_id,
            "replenishment_plan_id": (
                self.replenishment_plan_id
            ),
            "demand_forecast_id": self.demand_forecast_id,
            "pick_task_id": self.pick_task_id,
            "pack_task_id": self.pack_task_id,
            "delivery_id": self.delivery_id,
            "logistics_route_id": self.logistics_route_id,
            "stock_alert_id": self.stock_alert_id,
            "product_quality_issue_id": (
                self.product_quality_issue_id
            ),
            "incident_id": self.incident_id,
            "simulation_run_id": self.simulation_run_id,
            "requires_approval": self.requires_approval,
            "approval_status": enum_value(
                self.approval_status
            ),
            "quality_status": enum_value(
                self.quality_status
            ),
            "ai_generated": self.ai_generated,
            "ai_confidence": serialize_decimal(
                self.ai_confidence
            ),
            "risk_score": serialize_decimal(
                self.risk_score
            ),
            "risk_level": enum_value(self.risk_level),
            "scheduled_at": serialize_datetime(
                self.scheduled_at
            ),
            "validated_at": serialize_datetime(
                self.validated_at
            ),
            "processing_started_at": serialize_datetime(
                self.processing_started_at
            ),
            "dispatched_at": serialize_datetime(
                self.dispatched_at
            ),
            "received_at": serialize_datetime(
                self.received_at
            ),
            "completed_at": serialize_datetime(
                self.completed_at
            ),
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "reconciliation_status": enum_value(
                self.reconciliation_status
            ),
            "reversal_of_movement_id": (
                self.reversal_of_movement_id
            ),
            "reversal_movement_id": (
                self.reversal_movement_id
            ),
            "is_terminal": self.is_terminal,
            "is_approved": self.is_approved,
            "can_retry": self.can_retry,
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
                "notes": self.notes,
                "source_bin_code": self.source_bin_code,
                "destination_bin_code": (
                    self.destination_bin_code
                ),
                "cost_center_id": self.cost_center_id,
                "approval_request_id": (
                    self.approval_request_id
                ),
                "approved_by": self.approved_by,
                "approved_at": serialize_datetime(
                    self.approved_at
                ),
                "rejected_by": self.rejected_by,
                "rejected_at": serialize_datetime(
                    self.rejected_at
                ),
                "rejection_reason": self.rejection_reason,
                "quality_inspection_id": (
                    self.quality_inspection_id
                ),
                "quality_checked_by": (
                    self.quality_checked_by
                ),
                "quality_checked_at": serialize_datetime(
                    self.quality_checked_at
                ),
                "quality_notes": self.quality_notes,
                "ai_model_id": self.ai_model_id,
                "ai_agent_run_id": self.ai_agent_run_id,
                "ai_recommendation": self.ai_recommendation,
                "ai_explanation": self.ai_explanation,
                "risk_factors": self.risk_factors,
                "failure_code": self.failure_code,
                "failure_reason": self.failure_reason,
                "reconciliation_reference": (
                    self.reconciliation_reference
                ),
                "reconciled_by": self.reconciled_by,
                "reconciled_at": serialize_datetime(
                    self.reconciled_at
                ),
                "reconciliation_notes": (
                    self.reconciliation_notes
                ),
                "reversal_reason": self.reversal_reason,
                "reversed_by": self.reversed_by,
                "reversed_at": serialize_datetime(
                    self.reversed_at
                ),
                "cancellation_reason": (
                    self.cancellation_reason
                ),
                "movement_metadata": self.movement_metadata,
                "trace_id": self.trace_id,
                "correlation_id": self.correlation_id,
            })

        if include_history:
            data["movement_history"] = self.movement_history

        return data

    def __repr__(self) -> str:
        return (
            f"<StockMovement("
            f"id={self.id!r}, "
            f"movement_number={self.movement_number!r}, "
            f"type={enum_value(self.movement_type)!r}, "
            f"direction={enum_value(self.direction)!r}, "
            f"status={enum_value(self.status)!r}"
            f")>"
        )