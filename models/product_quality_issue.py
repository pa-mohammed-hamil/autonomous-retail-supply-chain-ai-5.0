from __future__ import annotations

"""Planned module: product quality issue. Implementation pending."""

"""
backend/models/product_quality_issue.py

Autonomous Retail Supply Chain AI 5.0

Product Quality Issue Management

Features:
- Multi-tenant product quality issues
- Product, supplier, warehouse, inventory references
- Defect and damage tracking
- Batch and lot traceability
- Computer vision inspection references
- AI risk scoring and recommendations
- Customer complaint references
- Quarantine and recall coordination
- Corrective and preventive actions (CAPA)
- Root-cause analysis
- Human approval
- Quality inspection results
- SLA monitoring
- Issue escalation
- Immutable-event-friendly audit history
- Soft deletion
- Optimistic locking

Important:
    ORM methods only update database state.

    Physical stock quarantine, recalls, supplier
    notifications, refunds and regulatory reporting
    must be performed by authorized services.
"""


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


def generate_issue_number() -> str:
    return f"PQI-{uuid.uuid4().hex[:16].upper()}"


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


def decimal_value(
    value: Decimal | int | float | str,
    *,
    field_name: str,
    allow_zero: bool = True,
) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(
            f"{field_name} must be numeric"
        )

    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(
            f"{field_name} must be numeric"
        ) from None

    if not result.is_finite():
        raise ValueError(
            f"{field_name} must be finite"
        )

    if result < 0 or (
        not allow_zero and result == 0
    ):
        raise ValueError(
            f"{field_name} must be positive"
            if not allow_zero
            else f"{field_name} cannot be negative"
        )

    if result != result.quantize(Decimal("0.0001")):
        raise ValueError(
            f"{field_name} supports at most "
            "four decimal places"
        )

    if result >= Decimal("100000000000000"):
        raise ValueError(
            f"{field_name} exceeds numeric precision"
        )

    return result


def probability_value(
    value: Decimal | int | float | str,
    *,
    field_name: str,
) -> Decimal:
    result = decimal_value(
        value,
        field_name=field_name,
    )

    if result > 1:
        raise ValueError(
            f"{field_name} must be between 0 and 1"
        )

    return result


def require_text(
    value: str,
    field_name: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{field_name} is required"
        )

    return value.strip()


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError(
            "Timezone-aware datetime required"
        )

    return value.astimezone(timezone.utc)


def iso_datetime(
    value: datetime | None,
) -> str | None:
    return value.isoformat() if value else None


def enum_value(
    value: enum.Enum | None,
) -> str | None:
    return value.value if value is not None else None


def decimal_string(
    value: Decimal | None,
) -> str | None:
    return str(value) if value is not None else None


# ============================================================
# ENUMS
# ============================================================

class ProductQualityIssueStatus(str, enum.Enum):
    REPORTED = "reported"
    TRIAGED = "triaged"
    UNDER_INVESTIGATION = "under_investigation"
    CONTAINMENT_PENDING = "containment_pending"
    CONTAINED = "contained"
    CORRECTIVE_ACTION = "corrective_action"
    PENDING_VERIFICATION = "pending_verification"
    PENDING_APPROVAL = "pending_approval"
    RESOLVED = "resolved"
    CLOSED = "closed"
    REOPENED = "reopened"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ProductQualityIssueType(str, enum.Enum):
    MANUFACTURING_DEFECT = "manufacturing_defect"
    DAMAGED_PRODUCT = "damaged_product"
    EXPIRED_PRODUCT = "expired_product"
    COUNTERFEIT_SUSPECTED = "counterfeit_suspected"
    INCORRECT_LABEL = "incorrect_label"
    INCORRECT_PACKAGING = "incorrect_packaging"
    MISSING_COMPONENT = "missing_component"
    WRONG_PRODUCT = "wrong_product"
    CONTAMINATION = "contamination"
    SAFETY_HAZARD = "safety_hazard"
    QUALITY_STANDARD_FAILURE = "quality_standard_failure"
    TEMPERATURE_EXCURSION = "temperature_excursion"
    STORAGE_DAMAGE = "storage_damage"
    TRANSPORT_DAMAGE = "transport_damage"
    SUPPLIER_NONCONFORMANCE = "supplier_nonconformance"
    CUSTOMER_COMPLAINT = "customer_complaint"
    RECALL_CONCERN = "recall_concern"
    OTHER = "other"


class ProductQualitySeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ProductQualityPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    EMERGENCY = "emergency"


class ProductQualitySource(str, enum.Enum):
    MANUAL = "manual"
    WAREHOUSE_INSPECTION = "warehouse_inspection"
    SUPPLIER_INSPECTION = "supplier_inspection"
    CUSTOMER_FEEDBACK = "customer_feedback"
    RETURN_INSPECTION = "return_inspection"
    DELIVERY_INSPECTION = "delivery_inspection"
    COMPUTER_VISION = "computer_vision"
    IOT_SENSOR = "iot_sensor"
    ERP = "erp"
    WMS = "wms"
    AI_AGENT = "ai_agent"
    SYSTEM = "system"


class ProductQualityRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class ProductQualityDisposition(str, enum.Enum):
    UNDECIDED = "undecided"
    RELEASE = "release"
    REWORK = "rework"
    REPAIR = "repair"
    RETURN_TO_SUPPLIER = "return_to_supplier"
    REPLACE = "replace"
    SCRAP = "scrap"
    DESTROY = "destroy"
    RECALL = "recall"


class ProductQualityApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class QualityInspectionResult(str, enum.Enum):
    NOT_INSPECTED = "not_inspected"
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


class CorrectiveActionStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    VERIFIED = "verified"
    CANCELLED = "cancelled"


# ============================================================
# PRODUCT QUALITY ISSUE MODEL
# ============================================================

class ProductQualityIssue(Base):
    __tablename__ = "product_quality_issues"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "issue_number",
            name="uq_product_quality_org_number",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_product_quality_org_idempotency",
        ),
        CheckConstraint(
            "affected_quantity >= 0",
            name="pqi_affected_nonnegative",
        ),
        CheckConstraint(
            "inspected_quantity >= 0",
            name="pqi_inspected_nonnegative",
        ),
        CheckConstraint(
            "defective_quantity >= 0",
            name="pqi_defective_nonnegative",
        ),
        CheckConstraint(
            "quarantined_quantity >= 0",
            name="pqi_quarantined_nonnegative",
        ),
        CheckConstraint(
            "estimated_loss >= 0",
            name="pqi_loss_nonnegative",
        ),
        CheckConstraint(
            "actual_loss >= 0",
            name="pqi_actual_loss_nonnegative",
        ),
        CheckConstraint(
            "risk_score IS NULL OR "
            "(risk_score >= 0 AND risk_score <= 1)",
            name="pqi_risk_score_range",
        ),
        CheckConstraint(
            "ai_confidence IS NULL OR "
            "(ai_confidence >= 0 AND ai_confidence <= 1)",
            name="pqi_confidence_range",
        ),
        CheckConstraint(
            "version >= 1",
            name="pqi_version_positive",
        ),
        Index(
            "ix_pqi_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_pqi_org_product",
            "organization_id",
            "product_id",
        ),
        Index(
            "ix_pqi_org_supplier",
            "organization_id",
            "supplier_id",
        ),
        Index(
            "ix_pqi_org_warehouse",
            "organization_id",
            "warehouse_id",
        ),
        Index(
            "ix_pqi_org_severity",
            "organization_id",
            "severity",
        ),
        Index(
            "ix_pqi_org_batch",
            "organization_id",
            "batch_number",
        ),
        Index(
            "ix_pqi_org_assignee",
            "organization_id",
            "assigned_to",
        ),
        Index(
            "ix_pqi_org_due",
            "organization_id",
            "resolution_due_at",
        ),
    )

    # --------------------------------------------------------
    # IDENTIFIERS
    # --------------------------------------------------------

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

    issue_number: Mapped[str] = mapped_column(
        String(50),
        default=generate_issue_number,
        nullable=False,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # --------------------------------------------------------
    # ISSUE DETAILS
    # --------------------------------------------------------

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    status: Mapped[
        ProductQualityIssueStatus
    ] = mapped_column(
        enum_column(
            ProductQualityIssueStatus,
            "product_quality_issue_status",
        ),
        default=ProductQualityIssueStatus.REPORTED,
        nullable=False,
    )

    issue_type: Mapped[
        ProductQualityIssueType
    ] = mapped_column(
        enum_column(
            ProductQualityIssueType,
            "product_quality_issue_type",
        ),
        nullable=False,
    )

    severity: Mapped[
        ProductQualitySeverity
    ] = mapped_column(
        enum_column(
            ProductQualitySeverity,
            "product_quality_severity",
        ),
        default=ProductQualitySeverity.MEDIUM,
        nullable=False,
    )

    priority: Mapped[
        ProductQualityPriority
    ] = mapped_column(
        enum_column(
            ProductQualityPriority,
            "product_quality_priority",
        ),
        default=ProductQualityPriority.NORMAL,
        nullable=False,
    )

    source: Mapped[
        ProductQualitySource
    ] = mapped_column(
        enum_column(
            ProductQualitySource,
            "product_quality_source",
        ),
        default=ProductQualitySource.MANUAL,
        nullable=False,
    )

    # --------------------------------------------------------
    # PRODUCT REFERENCES
    # --------------------------------------------------------

    product_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    sku: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    category_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    supplier_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    warehouse_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    inventory_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    bin_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    purchase_order_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    delivery_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    fulfillment_order_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    customer_feedback_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    incident_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # BATCH / LOT TRACEABILITY
    # --------------------------------------------------------

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

    manufacturing_date: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    expiry_date: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # QUANTITY TRACKING
    # --------------------------------------------------------

    affected_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    inspected_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    defective_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    quarantined_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    quantity_unit: Mapped[str] = mapped_column(
        String(30),
        default="units",
        nullable=False,
    )

    # --------------------------------------------------------
    # FINANCIAL IMPACT
    # --------------------------------------------------------

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

    actual_loss: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    cost_breakdown: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # INVESTIGATION
    # --------------------------------------------------------

    assigned_to: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    assigned_team_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    assigned_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    assigned_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    investigation_started_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    root_cause: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    root_cause_category: Mapped[
        str | None
    ] = mapped_column(
        String(100),
        nullable=True,
    )

    investigation_findings: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # INSPECTION
    # --------------------------------------------------------

    inspection_result: Mapped[
        QualityInspectionResult
    ] = mapped_column(
        enum_column(
            QualityInspectionResult,
            "product_quality_inspection_result",
        ),
        default=QualityInspectionResult.NOT_INSPECTED,
        nullable=False,
    )

    inspected_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    inspected_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    inspection_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    inspection_checklist: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # EVIDENCE
    # --------------------------------------------------------

    evidence_files: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    image_references: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    video_references: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # --------------------------------------------------------
    # AI / COMPUTER VISION
    # --------------------------------------------------------

    ai_detected: Mapped[bool] = mapped_column(
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

    risk_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    risk_level: Mapped[
        ProductQualityRiskLevel
    ] = mapped_column(
        enum_column(
            ProductQualityRiskLevel,
            "product_quality_risk_level",
        ),
        default=ProductQualityRiskLevel.UNKNOWN,
        nullable=False,
    )

    ai_summary: Mapped[str | None] = mapped_column(
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

    computer_vision_results: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    ai_analyzed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # CONTAINMENT / QUARANTINE
    # --------------------------------------------------------

    containment_required: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    containment_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    containment_reference: Mapped[
        str | None
    ] = mapped_column(
        String(150),
        nullable=True,
    )

    containment_verified_by: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    contained_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    quarantine_required: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    quarantine_reference: Mapped[
        str | None
    ] = mapped_column(
        String(150),
        nullable=True,
    )

    # --------------------------------------------------------
    # RECALL
    # --------------------------------------------------------

    recall_recommended: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    recall_reference: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    recall_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # DISPOSITION
    # --------------------------------------------------------

    disposition: Mapped[
        ProductQualityDisposition
    ] = mapped_column(
        enum_column(
            ProductQualityDisposition,
            "product_quality_disposition",
        ),
        default=ProductQualityDisposition.UNDECIDED,
        nullable=False,
    )

    disposition_reason: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    disposition_reference: Mapped[
        str | None
    ] = mapped_column(
        String(150),
        nullable=True,
    )

    disposition_completed: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    disposition_completed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # CORRECTIVE / PREVENTIVE ACTIONS
    # --------------------------------------------------------

    corrective_actions: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    preventive_actions: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # --------------------------------------------------------
    # HUMAN APPROVAL
    # --------------------------------------------------------

    requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    approval_status: Mapped[
        ProductQualityApprovalStatus
    ] = mapped_column(
        enum_column(
            ProductQualityApprovalStatus,
            "product_quality_approval_status",
        ),
        default=ProductQualityApprovalStatus.NOT_REQUIRED,
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

    approved_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # SLA
    # --------------------------------------------------------

    reported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    resolution_due_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    resolved_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    closed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    sla_breached: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    sla_breach_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # --------------------------------------------------------
    # ESCALATION
    # --------------------------------------------------------

    escalation_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    escalated_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # RESOLUTION
    # --------------------------------------------------------

    resolution_summary: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    resolved_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    closed_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    cancellation_reason: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # HISTORY
    # --------------------------------------------------------

    issue_history: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # --------------------------------------------------------
    # METADATA
    # --------------------------------------------------------

    issue_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # AUDIT
    # --------------------------------------------------------

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

    correlation_id: Mapped[
        str | None
    ] = mapped_column(
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

    # --------------------------------------------------------
    # SOFT DELETE
    # --------------------------------------------------------

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    deleted_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    deleted_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # OPTIMISTIC LOCKING
    # --------------------------------------------------------

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
            ProductQualityIssueStatus.CLOSED,
            ProductQualityIssueStatus.CANCELLED,
            ProductQualityIssueStatus.REJECTED,
        }

    @property
    def is_overdue(self) -> bool:
        return (
            self.resolution_due_at is not None
            and utc_now() > ensure_aware(
                self.resolution_due_at
            )
            and self.status not in {
                ProductQualityIssueStatus.RESOLVED,
                ProductQualityIssueStatus.CLOSED,
                ProductQualityIssueStatus.CANCELLED,
                ProductQualityIssueStatus.REJECTED,
            }
        )

    @property
    def defect_rate(self) -> Decimal:
        if self.inspected_quantity <= 0:
            return Decimal("0")

        return (
            self.defective_quantity
            / self.inspected_quantity
            * Decimal("100")
        ).quantize(Decimal("0.01"))

    @property
    def is_approved(self) -> bool:
        return (
            not self.requires_approval
            or self.approval_status
            == ProductQualityApprovalStatus.APPROVED
        )

    @property
    def all_corrective_actions_verified(self) -> bool:
        actions = self.corrective_actions or []

        return all(
            action.get("status")
            == CorrectiveActionStatus.VERIFIED.value
            for action in actions
        )

    @property
    def all_preventive_actions_verified(self) -> bool:
        actions = self.preventive_actions or []

        return all(
            action.get("status")
            == CorrectiveActionStatus.VERIFIED.value
            for action in actions
        )

    @property
    def can_resolve(self) -> bool:
        if self.is_deleted or self.is_terminal:
            return False

        return (
            self.status in {
                ProductQualityIssueStatus.CORRECTIVE_ACTION,
                ProductQualityIssueStatus.PENDING_VERIFICATION,
                ProductQualityIssueStatus.PENDING_APPROVAL,
            }
            and bool(self.root_cause)
            and self.all_corrective_actions_verified
            and self.all_preventive_actions_verified
            and (
                not self.containment_required
                or self.containment_verified
            )
            and self.disposition_completed
            and self.is_approved
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_active(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Quality issue has been deleted"
            )

        if self.is_terminal:
            raise ValueError(
                "Quality issue is in a terminal state"
            )

    def _record_event(
        self,
        event: str,
        *,
        actor_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        history = list(self.issue_history or [])

        history.append({
            "event_id": generate_uuid(),
            "event": event,
            "actor_id": actor_id,
            "timestamp": utc_now().isoformat(),
            "details": details or {},
        })

        self.issue_history = history
        self._touch()

    def _invalidate_approval(self) -> None:
        if self.requires_approval:
            self.approval_status = (
                ProductQualityApprovalStatus.NOT_REQUIRED
            )
            self.approval_request_id = None
            self.approved_by = None
            self.approved_at = None

    def _get_action(
        self,
        action_id: str,
        *,
        preventive: bool,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        source = (
            self.preventive_actions
            if preventive
            else self.corrective_actions
        )

        actions = [
            dict(item)
            for item in (source or [])
        ]

        action = next(
            (
                item for item in actions
                if item["action_id"] == action_id
            ),
            None,
        )

        if action is None:
            raise ValueError(
                "Quality action not found"
            )

        return actions, action

    # ========================================================
    # TRIAGE
    # ========================================================

    def triage(
        self,
        *,
        severity: ProductQualitySeverity,
        priority: ProductQualityPriority,
        actor_id: str,
        containment_required: bool = False,
        quarantine_required: bool = False,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            ProductQualityIssueStatus.REPORTED,
            ProductQualityIssueStatus.REOPENED,
        }:
            raise ValueError(
                "Issue cannot be triaged now"
            )

        self.severity = severity
        self.priority = priority
        self.containment_required = containment_required
        self.quarantine_required = quarantine_required
        self.status = ProductQualityIssueStatus.TRIAGED

        self._record_event(
            "issue_triaged",
            actor_id=actor_id,
            details={
                "severity": severity.value,
                "priority": priority.value,
            },
        )

    # ========================================================
    # ASSIGN INVESTIGATOR
    # ========================================================

    def assign(
        self,
        *,
        employee_id: str,
        assigned_by: str,
        team_id: str | None = None,
    ) -> None:
        self._ensure_active()

        self.assigned_to = require_text(
            employee_id,
            "Employee ID",
        )
        self.assigned_by = require_text(
            assigned_by,
            "Assigned by",
        )
        self.assigned_team_id = team_id
        self.assigned_at = utc_now()

        self._record_event(
            "investigator_assigned",
            actor_id=assigned_by,
            details={
                "employee_id": employee_id,
                "team_id": team_id,
            },
        )

    # ========================================================
    # START INVESTIGATION
    # ========================================================

    def start_investigation(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_active()

        if self.status != ProductQualityIssueStatus.TRIAGED:
            raise ValueError(
                "Issue must be triaged first"
            )

        if not self.assigned_to:
            raise ValueError(
                "Investigator must be assigned"
            )

        self.status = (
            ProductQualityIssueStatus.UNDER_INVESTIGATION
        )
        self.investigation_started_at = utc_now()

        self._record_event(
            "investigation_started",
            actor_id=actor_id,
        )

    # ========================================================
    # RECORD INSPECTION
    # ========================================================

    def record_inspection(
        self,
        *,
        inspected_quantity: Decimal | int | float | str,
        defective_quantity: Decimal | int | float | str,
        result: QualityInspectionResult,
        inspector_id: str,
        notes: str | None = None,
        checklist: dict[str, Any] | None = None,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            ProductQualityIssueStatus.UNDER_INVESTIGATION,
            ProductQualityIssueStatus.CONTAINED,
            ProductQualityIssueStatus.CORRECTIVE_ACTION,
            ProductQualityIssueStatus.PENDING_VERIFICATION,
        }:
            raise ValueError(
                "Inspection not allowed in current state"
            )

        inspected = decimal_value(
            inspected_quantity,
            field_name="inspected_quantity",
        )

        defective = decimal_value(
            defective_quantity,
            field_name="defective_quantity",
        )

        if defective > inspected:
            raise ValueError(
                "Defective quantity exceeds inspected quantity"
            )

        if (
            self.affected_quantity > 0
            and inspected > self.affected_quantity
        ):
            raise ValueError(
                "Inspected quantity exceeds affected quantity"
            )

        if result in {
            QualityInspectionResult.NOT_INSPECTED,
            QualityInspectionResult.PENDING,
        }:
            raise ValueError(
                "A completed inspection result is required"
            )

        self.inspected_quantity = inspected
        self.defective_quantity = defective
        self.inspection_result = result
        self.inspected_by = require_text(
            inspector_id,
            "Inspector ID",
        )
        self.inspected_at = utc_now()
        self.inspection_notes = notes
        self.inspection_checklist = dict(
            checklist or {}
        )

        self._record_event(
            "inspection_recorded",
            actor_id=inspector_id,
            details={
                "result": result.value,
                "inspected_quantity": str(inspected),
                "defective_quantity": str(defective),
            },
        )

    # ========================================================
    # RECORD ROOT CAUSE
    # ========================================================

    def record_root_cause(
        self,
        *,
        root_cause: str,
        actor_id: str,
        category: str | None = None,
        findings: dict[str, Any] | None = None,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            ProductQualityIssueStatus.UNDER_INVESTIGATION,
            ProductQualityIssueStatus.CONTAINED,
            ProductQualityIssueStatus.CORRECTIVE_ACTION,
        }:
            raise ValueError(
                "Root cause cannot be recorded now"
            )

        self.root_cause = require_text(
            root_cause,
            "Root cause",
        )
        self.root_cause_category = category
        self.investigation_findings = dict(
            findings or {}
        )

        self._invalidate_approval()

        self._record_event(
            "root_cause_recorded",
            actor_id=actor_id,
            details={"category": category},
        )

    # ========================================================
    # UPDATE AI ANALYSIS
    # ========================================================

    def update_ai_analysis(
        self,
        *,
        model_id: str,
        confidence: Decimal | int | float | str,
        risk_score: Decimal | int | float | str,
        risk_level: ProductQualityRiskLevel,
        summary: str,
        recommendations: list[dict[str, Any]],
        agent_run_id: str | None = None,
        computer_vision_results: dict[str, Any] | None = None,
    ) -> None:
        self._ensure_active()

        self.ai_model_id = require_text(
            model_id,
            "Model ID",
        )
        self.ai_agent_run_id = agent_run_id
        self.ai_confidence = probability_value(
            confidence,
            field_name="confidence",
        )
        self.risk_score = probability_value(
            risk_score,
            field_name="risk_score",
        )
        self.risk_level = risk_level
        self.ai_summary = require_text(
            summary,
            "AI summary",
        )
        self.ai_recommendations = [
            dict(item)
            for item in recommendations
        ]
        self.computer_vision_results = dict(
            computer_vision_results or {}
        )
        self.ai_detected = True
        self.ai_analyzed_at = utc_now()

        self._record_event(
            "ai_analysis_updated",
            details={
                "model_id": model_id,
                "risk_level": risk_level.value,
                "confidence": str(self.ai_confidence),
            },
        )

    # ========================================================
    # ADD EVIDENCE
    # ========================================================

    def add_evidence(
        self,
        *,
        file_id: str,
        file_type: str,
        uploaded_by: str,
        description: str | None = None,
        checksum_sha256: str | None = None,
    ) -> None:
        self._ensure_active()

        evidence = list(self.evidence_files or [])

        evidence.append({
            "evidence_id": generate_uuid(),
            "file_id": require_text(
                file_id,
                "File ID",
            ),
            "file_type": require_text(
                file_type,
                "File type",
            ),
            "description": description,
            "checksum_sha256": checksum_sha256,
            "uploaded_by": require_text(
                uploaded_by,
                "Uploaded by",
            ),
            "uploaded_at": utc_now().isoformat(),
        })

        self.evidence_files = evidence

        self._record_event(
            "evidence_added",
            actor_id=uploaded_by,
            details={"file_id": file_id},
        )

    # ========================================================
    # REQUEST CONTAINMENT
    # ========================================================

    def request_containment(
        self,
        *,
        actor_id: str,
        quarantine_required: bool = True,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            ProductQualityIssueStatus.TRIAGED,
            ProductQualityIssueStatus.UNDER_INVESTIGATION,
        }:
            raise ValueError(
                "Containment cannot be requested now"
            )

        self.containment_required = True
        self.quarantine_required = quarantine_required
        self.containment_verified = False
        self.status = (
            ProductQualityIssueStatus.CONTAINMENT_PENDING
        )

        self._record_event(
            "containment_requested",
            actor_id=actor_id,
        )

    # ========================================================
    # VERIFY CONTAINMENT
    # ========================================================

    def verify_containment(
        self,
        *,
        actor_id: str,
        containment_reference: str,
        quarantined_quantity: Decimal | int | float | str = 0,
        quarantine_reference: str | None = None,
    ) -> None:
        self._ensure_active()

        if self.status != (
            ProductQualityIssueStatus.CONTAINMENT_PENDING
        ):
            raise ValueError(
                "Containment is not pending"
            )

        quantity = decimal_value(
            quarantined_quantity,
            field_name="quarantined_quantity",
        )

        if (
            self.affected_quantity > 0
            and quantity > self.affected_quantity
        ):
            raise ValueError(
                "Quarantine quantity exceeds affected quantity"
            )

        if self.quarantine_required:
            if not quarantine_reference:
                raise ValueError(
                    "Quarantine reference required"
                )

            if quantity <= 0:
                raise ValueError(
                    "Quarantined quantity must be positive"
                )

        # The calling service must verify actual
        # containment and inventory ledger records.

        self.containment_reference = require_text(
            containment_reference,
            "Containment reference",
        )
        self.quarantine_reference = quarantine_reference
        self.quarantined_quantity = quantity
        self.containment_verified = True
        self.containment_verified_by = require_text(
            actor_id,
            "Actor ID",
        )
        self.contained_at = utc_now()
        self.status = ProductQualityIssueStatus.CONTAINED

        self._record_event(
            "containment_verified",
            actor_id=actor_id,
            details={
                "containment_reference": containment_reference,
                "quarantined_quantity": str(quantity),
            },
        )

    # ========================================================
    # ADD CORRECTIVE ACTION
    # ========================================================

    def add_corrective_action(
        self,
        *,
        title: str,
        description: str,
        assigned_to: str,
        actor_id: str,
        due_at: datetime | None = None,
    ) -> str:
        self._ensure_active()

        if self.status not in {
            ProductQualityIssueStatus.UNDER_INVESTIGATION,
            ProductQualityIssueStatus.CONTAINED,
            ProductQualityIssueStatus.CORRECTIVE_ACTION,
        }:
            raise ValueError(
                "Corrective actions cannot be added now"
            )

        action_id = generate_uuid()

        actions = list(self.corrective_actions or [])

        actions.append({
            "action_id": action_id,
            "title": require_text(title, "Title"),
            "description": require_text(
                description,
                "Description",
            ),
            "assigned_to": require_text(
                assigned_to,
                "Assigned to",
            ),
            "status": CorrectiveActionStatus.OPEN.value,
            "created_at": utc_now().isoformat(),
            "due_at": (
                ensure_aware(due_at).isoformat()
                if due_at
                else None
            ),
            "completed_at": None,
            "verified_at": None,
            "verified_by": None,
        })

        self.corrective_actions = actions
        self._invalidate_approval()

        self.status = (
            ProductQualityIssueStatus.CORRECTIVE_ACTION
        )

        self._record_event(
            "corrective_action_added",
            actor_id=actor_id,
            details={"action_id": action_id},
        )

        return action_id

    # ========================================================
    # ADD PREVENTIVE ACTION
    # ========================================================

    def add_preventive_action(
        self,
        *,
        title: str,
        description: str,
        assigned_to: str,
        actor_id: str,
        due_at: datetime | None = None,
    ) -> str:
        self._ensure_active()

        if self.status not in {
            ProductQualityIssueStatus.UNDER_INVESTIGATION,
            ProductQualityIssueStatus.CONTAINED,
            ProductQualityIssueStatus.CORRECTIVE_ACTION,
        }:
            raise ValueError(
                "Preventive actions cannot be added now"
            )

        action_id = generate_uuid()
        actions = list(self.preventive_actions or [])

        actions.append({
            "action_id": action_id,
            "title": require_text(title, "Title"),
            "description": require_text(
                description,
                "Description",
            ),
            "assigned_to": require_text(
                assigned_to,
                "Assigned to",
            ),
            "status": CorrectiveActionStatus.OPEN.value,
            "created_at": utc_now().isoformat(),
            "due_at": (
                ensure_aware(due_at).isoformat()
                if due_at
                else None
            ),
            "completed_at": None,
            "verified_at": None,
            "verified_by": None,
        })

        self.preventive_actions = actions
        self._invalidate_approval()
        self.status = (
            ProductQualityIssueStatus.CORRECTIVE_ACTION
        )

        self._record_event(
            "preventive_action_added",
            actor_id=actor_id,
            details={"action_id": action_id},
        )

        return action_id

    # ========================================================
    # COMPLETE QUALITY ACTION
    # ========================================================

    def complete_action(
        self,
        *,
        action_id: str,
        actor_id: str,
        preventive: bool = False,
    ) -> None:
        self._ensure_active()

        if self.status != (
            ProductQualityIssueStatus.CORRECTIVE_ACTION
        ):
            raise ValueError(
                "Issue is not in corrective action phase"
            )

        actions, action = self._get_action(
            action_id,
            preventive=preventive,
        )

        if action["status"] not in {
            CorrectiveActionStatus.OPEN.value,
            CorrectiveActionStatus.IN_PROGRESS.value,
        }:
            raise ValueError(
                "Action cannot be completed"
            )

        action["status"] = (
            CorrectiveActionStatus.COMPLETED.value
        )
        action["completed_at"] = utc_now().isoformat()
        action["completed_by"] = actor_id

        if preventive:
            self.preventive_actions = actions
        else:
            self.corrective_actions = actions

        self._record_event(
            "quality_action_completed",
            actor_id=actor_id,
            details={
                "action_id": action_id,
                "preventive": preventive,
            },
        )

    # ========================================================
    # VERIFY QUALITY ACTION
    # ========================================================

    def verify_action(
        self,
        *,
        action_id: str,
        verifier_id: str,
        preventive: bool = False,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            ProductQualityIssueStatus.CORRECTIVE_ACTION,
            ProductQualityIssueStatus.PENDING_VERIFICATION,
        }:
            raise ValueError(
                "Issue is not ready for action verification"
            )

        actions, action = self._get_action(
            action_id,
            preventive=preventive,
        )

        if action["status"] != (
            CorrectiveActionStatus.COMPLETED.value
        ):
            raise ValueError(
                "Action must be completed first"
            )

        action["status"] = (
            CorrectiveActionStatus.VERIFIED.value
        )
        action["verified_at"] = utc_now().isoformat()
        action["verified_by"] = require_text(
            verifier_id,
            "Verifier ID",
        )

        if preventive:
            self.preventive_actions = actions
        else:
            self.corrective_actions = actions

        self._record_event(
            "quality_action_verified",
            actor_id=verifier_id,
            details={
                "action_id": action_id,
                "preventive": preventive,
            },
        )

    # ========================================================
    # SELECT DISPOSITION
    # ========================================================

    def select_disposition(
        self,
        *,
        disposition: ProductQualityDisposition,
        reason: str,
        actor_id: str,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            ProductQualityIssueStatus.UNDER_INVESTIGATION,
            ProductQualityIssueStatus.CONTAINED,
            ProductQualityIssueStatus.CORRECTIVE_ACTION,
        }:
            raise ValueError(
                "Disposition cannot be selected now"
            )

        if disposition == (
            ProductQualityDisposition.UNDECIDED
        ):
            raise ValueError(
                "A final disposition must be selected"
            )

        self.disposition = disposition
        self.disposition_reason = require_text(
            reason,
            "Disposition reason",
        )
        self.disposition_completed = False
        self.disposition_reference = None
        self.disposition_completed_at = None

        self._invalidate_approval()

        self._record_event(
            "disposition_selected",
            actor_id=actor_id,
            details={
                "disposition": disposition.value,
            },
        )

    # ========================================================
    # RECORD COMPLETED DISPOSITION
    # ========================================================

    def record_disposition_completion(
        self,
        *,
        disposition_reference: str,
        actor_id: str,
    ) -> None:
        self._ensure_active()

        if self.disposition == (
            ProductQualityDisposition.UNDECIDED
        ):
            raise ValueError(
                "Disposition must be selected first"
            )

        if self.disposition_completed:
            raise ValueError(
                "Disposition is already completed"
            )

        # The service must verify the referenced
        # inventory, return, repair, recall or disposal
        # transaction before recording completion.

        self.disposition_reference = require_text(
            disposition_reference,
            "Disposition reference",
        )
        self.disposition_completed = True
        self.disposition_completed_at = utc_now()

        self._record_event(
            "disposition_completed",
            actor_id=actor_id,
            details={
                "disposition": self.disposition.value,
                "reference": disposition_reference,
            },
        )

    # ========================================================
    # RECOMMEND RECALL
    # ========================================================

    def recommend_recall(
        self,
        *,
        reason: str,
        actor_id: str,
    ) -> None:
        self._ensure_active()

        self.recall_recommended = True
        self.recall_notes = require_text(
            reason,
            "Recall reason",
        )

        self._record_event(
            "recall_recommended",
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # REQUEST APPROVAL
    # ========================================================

    def request_approval(
        self,
        *,
        approval_request_id: str,
        actor_id: str,
    ) -> None:
        self._ensure_active()

        if not self.requires_approval:
            raise ValueError(
                "Approval is not required"
            )

        if self.status not in {
            ProductQualityIssueStatus.CORRECTIVE_ACTION,
            ProductQualityIssueStatus.PENDING_VERIFICATION,
        }:
            raise ValueError(
                "Issue is not ready for approval"
            )

        if not self.root_cause:
            raise ValueError(
                "Root cause is required"
            )

        if not self.all_corrective_actions_verified:
            raise ValueError(
                "Corrective actions are not verified"
            )

        if not self.all_preventive_actions_verified:
            raise ValueError(
                "Preventive actions are not verified"
            )

        if (
            self.containment_required
            and not self.containment_verified
        ):
            raise ValueError(
                "Containment must be verified"
            )

        if not self.disposition_completed:
            raise ValueError(
                "Disposition must be completed"
            )

        self.approval_request_id = require_text(
            approval_request_id,
            "Approval request ID",
        )
        self.approval_status = (
            ProductQualityApprovalStatus.PENDING
        )
        self.approved_by = None
        self.approved_at = None
        self.status = (
            ProductQualityIssueStatus.PENDING_APPROVAL
        )

        self._record_event(
            "approval_requested",
            actor_id=actor_id,
        )

    # ========================================================
    # APPROVE RESOLUTION
    # ========================================================

    def approve_resolution(
        self,
        *,
        approver_id: str,
    ) -> None:
        self._ensure_active()

        if self.status != (
            ProductQualityIssueStatus.PENDING_APPROVAL
        ):
            raise ValueError(
                "Issue is not pending approval"
            )

        if self.approval_status != (
            ProductQualityApprovalStatus.PENDING
        ):
            raise ValueError(
                "Approval request is not pending"
            )

        # Verify linked ApprovalRequest and approver
        # permissions in the service layer.

        self.approval_status = (
            ProductQualityApprovalStatus.APPROVED
        )
        self.approved_by = require_text(
            approver_id,
            "Approver ID",
        )
        self.approved_at = utc_now()

        self._record_event(
            "resolution_approved",
            actor_id=approver_id,
        )

    # ========================================================
    # RESOLVE ISSUE
    # ========================================================

    def resolve(
        self,
        *,
        resolution_summary: str,
        resolved_by: str,
    ) -> None:
        self._ensure_active()

        if not self.can_resolve:
            raise ValueError(
                "Issue does not meet resolution requirements"
            )

        self.resolution_summary = require_text(
            resolution_summary,
            "Resolution summary",
        )
        self.resolved_by = require_text(
            resolved_by,
            "Resolved by",
        )
        self.resolved_at = utc_now()
        self.status = ProductQualityIssueStatus.RESOLVED

        self._record_event(
            "issue_resolved",
            actor_id=resolved_by,
        )

    # ========================================================
    # CLOSE ISSUE
    # ========================================================

    def close(
        self,
        *,
        closed_by: str,
    ) -> None:
        self._ensure_active()

        if self.status != (
            ProductQualityIssueStatus.RESOLVED
        ):
            raise ValueError(
                "Issue must be resolved first"
            )

        self.closed_by = require_text(
            closed_by,
            "Closed by",
        )
        self.closed_at = utc_now()
        self.status = ProductQualityIssueStatus.CLOSED

        self._record_event(
            "issue_closed",
            actor_id=closed_by,
        )

    # ========================================================
    # REOPEN ISSUE
    # ========================================================

    def reopen(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        if self.is_deleted:
            raise ValueError(
                "Deleted issue cannot be reopened"
            )

        if self.status not in {
            ProductQualityIssueStatus.RESOLVED,
            ProductQualityIssueStatus.CLOSED,
        }:
            raise ValueError(
                "Only resolved or closed issues can reopen"
            )

        reason = require_text(
            reason,
            "Reopen reason",
        )

        self.status = ProductQualityIssueStatus.REOPENED
        self.resolved_at = None
        self.resolved_by = None
        self.closed_at = None
        self.closed_by = None
        self.resolution_summary = None

        self._invalidate_approval()

        self._record_event(
            "issue_reopened",
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # ESCALATE ISSUE
    # ========================================================

    def escalate(
        self,
        *,
        escalation_id: str,
        actor_id: str,
    ) -> None:
        self._ensure_active()

        self.escalation_id = require_text(
            escalation_id,
            "Escalation ID",
        )
        self.escalated_at = utc_now()

        self._record_event(
            "issue_escalated",
            actor_id=actor_id,
            details={
                "escalation_id": escalation_id,
            },
        )

    # ========================================================
    # RECORD SLA BREACH
    # ========================================================

    def record_sla_breach(self) -> None:
        self._ensure_active()

        if not self.is_overdue:
            raise ValueError(
                "Resolution SLA has not been breached"
            )

        if self.sla_breached:
            raise ValueError(
                "SLA breach already recorded"
            )

        self.sla_breached = True
        self.sla_breach_count += 1

        self._record_event("sla_breached")

    # ========================================================
    # CANCEL ISSUE
    # ========================================================

    def cancel(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            ProductQualityIssueStatus.REPORTED,
            ProductQualityIssueStatus.TRIAGED,
        }:
            raise ValueError(
                "Investigated issues cannot be cancelled"
            )

        self.cancellation_reason = require_text(
            reason,
            "Cancellation reason",
        )
        self.status = ProductQualityIssueStatus.CANCELLED

        self._record_event(
            "issue_cancelled",
            actor_id=actor_id,
            details={"reason": reason},
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
            raise ValueError(
                "Issue is already deleted"
            )

        if self.status not in {
            ProductQualityIssueStatus.CANCELLED,
            ProductQualityIssueStatus.REJECTED,
        }:
            raise ValueError(
                "Only cancelled or rejected issues "
                "can be soft deleted"
            )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = require_text(
            actor_id,
            "Actor ID",
        )

        self._record_event(
            "issue_soft_deleted",
            actor_id=actor_id,
        )

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "issue_number": self.issue_number,
            "idempotency_key": self.idempotency_key,
            "title": self.title,
            "description": self.description,
            "status": enum_value(self.status),
            "issue_type": enum_value(self.issue_type),
            "severity": enum_value(self.severity),
            "priority": enum_value(self.priority),
            "source": enum_value(self.source),

            "product_id": self.product_id,
            "sku": self.sku,
            "category_id": self.category_id,
            "supplier_id": self.supplier_id,
            "warehouse_id": self.warehouse_id,
            "inventory_id": self.inventory_id,
            "bin_id": self.bin_id,
            "purchase_order_id": self.purchase_order_id,
            "delivery_id": self.delivery_id,
            "fulfillment_order_id": (
                self.fulfillment_order_id
            ),
            "customer_feedback_id": (
                self.customer_feedback_id
            ),
            "incident_id": self.incident_id,

            "batch_number": self.batch_number,
            "lot_number": self.lot_number,
            "serial_number": self.serial_number,
            "manufacturing_date": iso_datetime(
                self.manufacturing_date
            ),
            "expiry_date": iso_datetime(
                self.expiry_date
            ),

            "affected_quantity": str(
                self.affected_quantity
            ),
            "inspected_quantity": str(
                self.inspected_quantity
            ),
            "defective_quantity": str(
                self.defective_quantity
            ),
            "quarantined_quantity": str(
                self.quarantined_quantity
            ),
            "quantity_unit": self.quantity_unit,
            "defect_rate": str(self.defect_rate),

            "currency": self.currency,
            "estimated_loss": str(
                self.estimated_loss
            ),
            "actual_loss": str(self.actual_loss),
            "cost_breakdown": self.cost_breakdown,

            "assigned_to": self.assigned_to,
            "assigned_team_id": self.assigned_team_id,
            "assigned_by": self.assigned_by,
            "assigned_at": iso_datetime(
                self.assigned_at
            ),
            "investigation_started_at": iso_datetime(
                self.investigation_started_at
            ),
            "root_cause": self.root_cause,
            "root_cause_category": (
                self.root_cause_category
            ),
            "investigation_findings": (
                self.investigation_findings
            ),

            "inspection_result": enum_value(
                self.inspection_result
            ),
            "inspected_by": self.inspected_by,
            "inspected_at": iso_datetime(
                self.inspected_at
            ),
            "inspection_notes": self.inspection_notes,
            "inspection_checklist": (
                self.inspection_checklist
            ),

            "evidence_files": self.evidence_files,
            "image_references": self.image_references,
            "video_references": self.video_references,

            "ai_detected": self.ai_detected,
            "ai_model_id": self.ai_model_id,
            "ai_agent_run_id": self.ai_agent_run_id,
            "ai_confidence": decimal_string(
                self.ai_confidence
            ),
            "risk_score": decimal_string(
                self.risk_score
            ),
            "risk_level": enum_value(
                self.risk_level
            ),
            "ai_summary": self.ai_summary,
            "ai_recommendations": (
                self.ai_recommendations
            ),
            "computer_vision_results": (
                self.computer_vision_results
            ),
            "ai_analyzed_at": iso_datetime(
                self.ai_analyzed_at
            ),

            "containment_required": (
                self.containment_required
            ),
            "containment_verified": (
                self.containment_verified
            ),
            "containment_reference": (
                self.containment_reference
            ),
            "containment_verified_by": (
                self.containment_verified_by
            ),
            "contained_at": iso_datetime(
                self.contained_at
            ),
            "quarantine_required": (
                self.quarantine_required
            ),
            "quarantine_reference": (
                self.quarantine_reference
            ),

            "recall_recommended": (
                self.recall_recommended
            ),
            "recall_reference": self.recall_reference,
            "recall_notes": self.recall_notes,

            "disposition": enum_value(
                self.disposition
            ),
            "disposition_reason": (
                self.disposition_reason
            ),
            "disposition_reference": (
                self.disposition_reference
            ),
            "disposition_completed": (
                self.disposition_completed
            ),
            "disposition_completed_at": iso_datetime(
                self.disposition_completed_at
            ),

            "corrective_actions": (
                self.corrective_actions
            ),
            "preventive_actions": (
                self.preventive_actions
            ),
            "all_corrective_actions_verified": (
                self.all_corrective_actions_verified
            ),
            "all_preventive_actions_verified": (
                self.all_preventive_actions_verified
            ),

            "requires_approval": (
                self.requires_approval
            ),
            "approval_status": enum_value(
                self.approval_status
            ),
            "approval_request_id": (
                self.approval_request_id
            ),
            "approved_by": self.approved_by,
            "approved_at": iso_datetime(
                self.approved_at
            ),
            "is_approved": self.is_approved,

            "reported_at": iso_datetime(
                self.reported_at
            ),
            "resolution_due_at": iso_datetime(
                self.resolution_due_at
            ),
            "resolved_at": iso_datetime(
                self.resolved_at
            ),
            "closed_at": iso_datetime(
                self.closed_at
            ),
            "sla_breached": self.sla_breached,
            "sla_breach_count": self.sla_breach_count,
            "is_overdue": self.is_overdue,

            "escalation_id": self.escalation_id,
            "escalated_at": iso_datetime(
                self.escalated_at
            ),

            "resolution_summary": (
                self.resolution_summary
            ),
            "resolved_by": self.resolved_by,
            "closed_by": self.closed_by,
            "cancellation_reason": (
                self.cancellation_reason
            ),

            "issue_history": self.issue_history,
            "issue_metadata": self.issue_metadata,

            "is_terminal": self.is_terminal,
            "can_resolve": self.can_resolve,

            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "trace_id": self.trace_id,
            "correlation_id": self.correlation_id,
            "created_at": iso_datetime(
                self.created_at
            ),
            "updated_at": iso_datetime(
                self.updated_at
            ),

            "is_deleted": self.is_deleted,
            "deleted_at": iso_datetime(
                self.deleted_at
            ),
            "deleted_by": self.deleted_by,
            "version": self.version,
        }

    def __repr__(self) -> str:
        return (
            f"<ProductQualityIssue("
            f"id={self.id}, "
            f"issue_number={self.issue_number}, "
            f"product_id={self.product_id}, "
            f"status={enum_value(self.status)}, "
            f"severity={enum_value(self.severity)}"
            f")>"
        )
