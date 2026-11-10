from __future__ import annotations

"""Planned module: supplier risk. Implementation pending."""
# backend/models/supplier_risk.py


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
SCORE_SCALE = Decimal("0.0001")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_assessment_number() -> str:
    return f"SR-{uuid.uuid4().hex[:16].upper()}"


def enum_type(enum_class: type[enum.Enum], name: str):
    return SQLEnum(
        enum_class,
        name=name,
        native_enum=False,
        values_callable=lambda values: [
            member.value for member in values
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
    value: Decimal | str | int | float,
    field: str,
    *,
    minimum: Decimal = ZERO,
    maximum: Decimal = ONE,
) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")

    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{field} must be numeric") from None

    if not result.is_finite():
        raise ValueError(f"{field} must be finite")

    if result < minimum or result > maximum:
        raise ValueError(
            f"{field} must be between {minimum} and {maximum}"
        )

    if result != result.quantize(SCORE_SCALE):
        raise ValueError(
            f"{field} supports at most four decimal places"
        )

    return result


def score_value(
    value: Decimal | str | int | float,
    field: str,
) -> Decimal:
    return decimal_value(value, field)


def nonnegative_int(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")

    if value < 0:
        raise ValueError(f"{field} cannot be negative")

    return value


def aware_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("Expected datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timezone-aware datetime required")

    return value.astimezone(timezone.utc)


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value

    if isinstance(value, (Decimal, float)):
        result = Decimal(str(value))

        if not result.is_finite():
            raise ValueError("Non-finite JSON number")

        return str(result)

    if isinstance(value, enum.Enum):
        return value.value

    if isinstance(value, datetime):
        return aware_datetime(value).isoformat()

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


def enum_value(value: Any) -> Any:
    return value.value if isinstance(value, enum.Enum) else value


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def decimal_string(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


# ============================================================
# ENUMS
# ============================================================

class SupplierRiskStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    COLLECTING_DATA = "collecting_data"
    ANALYZING = "analyzing"
    PENDING_REVIEW = "pending_review"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"
    MONITORING = "monitoring"
    MITIGATING = "mitigating"
    RESOLVED = "resolved"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    FAILED = "failed"
    ARCHIVED = "archived"


class SupplierRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class SupplierRiskCategory(str, enum.Enum):
    FINANCIAL = "financial"
    OPERATIONAL = "operational"
    DELIVERY = "delivery"
    QUALITY = "quality"
    CAPACITY = "capacity"
    INVENTORY = "inventory"
    LOGISTICS = "logistics"
    GEOPOLITICAL = "geopolitical"
    ENVIRONMENTAL = "environmental"
    CLIMATE = "climate"
    NATURAL_DISASTER = "natural_disaster"
    CYBERSECURITY = "cybersecurity"
    COMPLIANCE = "compliance"
    LEGAL = "legal"
    REPUTATIONAL = "reputational"
    ESG = "esg"
    MARKET = "market"
    FRAUD = "fraud"
    CONTRACTUAL = "contractual"
    CONCENTRATION = "concentration"
    BUSINESS_CONTINUITY = "business_continuity"
    MULTI_FACTOR = "multi_factor"
    OTHER = "other"


class SupplierRiskSource(str, enum.Enum):
    MANUAL = "manual"
    API = "api"
    SCHEDULER = "scheduler"
    AI_AGENT = "ai_agent"
    ML_MODEL = "ml_model"
    SUPPLIER_PORTAL = "supplier_portal"
    ERP = "erp"
    WMS = "wms"
    MARKET_DATA = "market_data"
    NEWS_INTELLIGENCE = "news_intelligence"
    CONTRACT_ANALYSIS = "contract_analysis"
    DELIVERY_ANALYTICS = "delivery_analytics"
    QUALITY_ANALYTICS = "quality_analytics"
    SYSTEM = "system"


class SupplierRiskAssessmentType(str, enum.Enum):
    INITIAL = "initial"
    PERIODIC = "periodic"
    CONTINUOUS = "continuous"
    EVENT_TRIGGERED = "event_triggered"
    PRE_CONTRACT = "pre_contract"
    POST_INCIDENT = "post_incident"
    SUPPLIER_ONBOARDING = "supplier_onboarding"
    RENEWAL = "renewal"
    EMERGENCY = "emergency"


class SupplierRiskPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"


class SupplierRiskTrend(str, enum.Enum):
    IMPROVING = "improving"
    STABLE = "stable"
    DETERIORATING = "deteriorating"
    UNKNOWN = "unknown"


class SupplierRiskReviewStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SupplierRiskMitigationStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PROPOSED = "proposed"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SupplierRiskRecommendationType(str, enum.Enum):
    MONITOR = "monitor"
    REQUEST_DOCUMENTS = "request_documents"
    SUPPLIER_AUDIT = "supplier_audit"
    QUALITY_INSPECTION = "quality_inspection"
    REDUCE_EXPOSURE = "reduce_exposure"
    DIVERSIFY_SUPPLIERS = "diversify_suppliers"
    ALTERNATIVE_SUPPLIER = "alternative_supplier"
    SAFETY_STOCK = "safety_stock"
    EARLY_REPLENISHMENT = "early_replenishment"
    ADJUST_LEAD_TIME = "adjust_lead_time"
    CONTRACT_REVIEW = "contract_review"
    PAYMENT_REVIEW = "payment_review"
    SECURITY_REVIEW = "security_review"
    BUSINESS_CONTINUITY = "business_continuity"
    ESCALATE = "escalate"
    SUSPEND_SUPPLIER = "suspend_supplier"
    OTHER = "other"


class SupplierRiskEventType(str, enum.Enum):
    CREATED = "created"
    DATA_COLLECTION_STARTED = "data_collection_started"
    DATA_UPDATED = "data_updated"
    ANALYSIS_STARTED = "analysis_started"
    ANALYSIS_COMPLETED = "analysis_completed"
    RISK_SCORE_UPDATED = "risk_score_updated"
    FACTOR_ADDED = "factor_added"
    FACTOR_UPDATED = "factor_updated"
    REVIEW_REQUESTED = "review_requested"
    REVIEW_APPROVED = "review_approved"
    REVIEW_REJECTED = "review_rejected"
    MONITORING_STARTED = "monitoring_started"
    MITIGATION_PROPOSED = "mitigation_proposed"
    MITIGATION_APPROVED = "mitigation_approved"
    MITIGATION_STARTED = "mitigation_started"
    MITIGATION_COMPLETED = "mitigation_completed"
    MITIGATION_FAILED = "mitigation_failed"
    ALERT_RECORDED = "alert_recorded"
    RESOLVED = "resolved"
    EXPIRED = "expired"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"
    SOFT_DELETED = "soft_deleted"


# ============================================================
# SUPPLIER RISK ASSESSMENT
# ============================================================

class SupplierRisk(Base):
    __tablename__ = "supplier_risks"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_supplier_risk_org_id",
        ),
        UniqueConstraint(
            "organization_id",
            "assessment_number",
            name="uq_supplier_risk_org_number",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_supplier_risk_org_idempotency",
        ),
        CheckConstraint(
            "overall_risk_score IS NULL OR "
            "(overall_risk_score >= 0 AND overall_risk_score <= 1)",
            name="ck_supplier_risk_overall_score",
        ),
        CheckConstraint(
            "financial_risk_score IS NULL OR "
            "(financial_risk_score >= 0 AND financial_risk_score <= 1)",
            name="ck_supplier_risk_financial_score",
        ),
        CheckConstraint(
            "operational_risk_score IS NULL OR "
            "(operational_risk_score >= 0 AND operational_risk_score <= 1)",
            name="ck_supplier_risk_operational_score",
        ),
        CheckConstraint(
            "delivery_risk_score IS NULL OR "
            "(delivery_risk_score >= 0 AND delivery_risk_score <= 1)",
            name="ck_supplier_risk_delivery_score",
        ),
        CheckConstraint(
            "quality_risk_score IS NULL OR "
            "(quality_risk_score >= 0 AND quality_risk_score <= 1)",
            name="ck_supplier_risk_quality_score",
        ),
        CheckConstraint(
            "compliance_risk_score IS NULL OR "
            "(compliance_risk_score >= 0 AND compliance_risk_score <= 1)",
            name="ck_supplier_risk_compliance_score",
        ),
        CheckConstraint(
            "cybersecurity_risk_score IS NULL OR "
            "(cybersecurity_risk_score >= 0 AND cybersecurity_risk_score <= 1)",
            name="ck_supplier_risk_cyber_score",
        ),
        CheckConstraint(
            "environmental_risk_score IS NULL OR "
            "(environmental_risk_score >= 0 AND environmental_risk_score <= 1)",
            name="ck_supplier_risk_environmental_score",
        ),
        CheckConstraint(
            "concentration_risk_score IS NULL OR "
            "(concentration_risk_score >= 0 AND concentration_risk_score <= 1)",
            name="ck_supplier_risk_concentration_score",
        ),
        CheckConstraint(
            "predicted_disruption_probability IS NULL OR "
            "(predicted_disruption_probability >= 0 AND "
            "predicted_disruption_probability <= 1)",
            name="ck_supplier_risk_disruption_probability",
        ),
        CheckConstraint(
            "model_confidence IS NULL OR "
            "(model_confidence >= 0 AND model_confidence <= 1)",
            name="ck_supplier_risk_model_confidence",
        ),
        CheckConstraint(
            "supplier_reliability_score IS NULL OR "
            "(supplier_reliability_score >= 0 AND "
            "supplier_reliability_score <= 1)",
            name="ck_supplier_risk_reliability",
        ),
        CheckConstraint(
            "on_time_delivery_rate IS NULL OR "
            "(on_time_delivery_rate >= 0 AND "
            "on_time_delivery_rate <= 1)",
            name="ck_supplier_risk_delivery_rate",
        ),
        CheckConstraint(
            "defect_rate IS NULL OR "
            "(defect_rate >= 0 AND defect_rate <= 1)",
            name="ck_supplier_risk_defect_rate",
        ),
        CheckConstraint(
            "lead_time_variability_days IS NULL OR "
            "lead_time_variability_days >= 0",
            name="ck_supplier_risk_lead_time_variability",
        ),
        CheckConstraint(
            "expected_financial_impact >= 0",
            name="ck_supplier_risk_financial_impact",
        ),
        CheckConstraint(
            "estimated_mitigation_cost >= 0",
            name="ck_supplier_risk_mitigation_cost",
        ),
        CheckConstraint(
            "monitoring_interval_hours >= 1",
            name="ck_supplier_risk_monitor_interval",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_supplier_risk_version",
        ),
        Index(
            "ix_supplier_risk_org_supplier",
            "organization_id",
            "supplier_id",
        ),
        Index(
            "ix_supplier_risk_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_supplier_risk_org_level",
            "organization_id",
            "risk_level",
        ),
        Index(
            "ix_supplier_risk_org_priority",
            "organization_id",
            "priority",
        ),
        Index(
            "ix_supplier_risk_org_category",
            "organization_id",
            "primary_risk_category",
        ),
        Index(
            "ix_supplier_risk_org_assessed",
            "organization_id",
            "assessed_at",
        ),
        Index(
            "ix_supplier_risk_org_monitor",
            "organization_id",
            "next_monitoring_at",
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

    assessment_number: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default=generate_assessment_number,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ========================================================
    # REFERENCES
    # ========================================================

    supplier_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    supplier_contract_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    purchase_order_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    replenishment_plan_id: Mapped[str | None] = mapped_column(
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

    product_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    category_id: Mapped[str | None] = mapped_column(
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

    approval_request_id: Mapped[str | None] = mapped_column(
        String(36),
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

    previous_assessment_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # ========================================================
    # CLASSIFICATION
    # ========================================================

    status: Mapped[SupplierRiskStatus] = mapped_column(
        enum_type(
            SupplierRiskStatus,
            "supplier_risk_status",
        ),
        default=SupplierRiskStatus.DRAFT,
        nullable=False,
    )

    assessment_type: Mapped[
        SupplierRiskAssessmentType
    ] = mapped_column(
        enum_type(
            SupplierRiskAssessmentType,
            "supplier_risk_assessment_type",
        ),
        default=SupplierRiskAssessmentType.PERIODIC,
        nullable=False,
    )

    source: Mapped[SupplierRiskSource] = mapped_column(
        enum_type(
            SupplierRiskSource,
            "supplier_risk_source",
        ),
        default=SupplierRiskSource.MANUAL,
        nullable=False,
    )

    priority: Mapped[SupplierRiskPriority] = mapped_column(
        enum_type(
            SupplierRiskPriority,
            "supplier_risk_priority",
        ),
        default=SupplierRiskPriority.NORMAL,
        nullable=False,
    )

    primary_risk_category: Mapped[
        SupplierRiskCategory
    ] = mapped_column(
        enum_type(
            SupplierRiskCategory,
            "supplier_risk_primary_category",
        ),
        default=SupplierRiskCategory.MULTI_FACTOR,
        nullable=False,
    )

    risk_level: Mapped[SupplierRiskLevel] = mapped_column(
        enum_type(
            SupplierRiskLevel,
            "supplier_risk_level",
        ),
        default=SupplierRiskLevel.UNKNOWN,
        nullable=False,
    )

    risk_trend: Mapped[SupplierRiskTrend] = mapped_column(
        enum_type(
            SupplierRiskTrend,
            "supplier_risk_trend",
        ),
        default=SupplierRiskTrend.UNKNOWN,
        nullable=False,
    )

    # ========================================================
    # RISK SCORES
    # ========================================================

    overall_risk_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    financial_risk_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    operational_risk_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    delivery_risk_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    quality_risk_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    compliance_risk_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    cybersecurity_risk_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    environmental_risk_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    concentration_risk_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    risk_weights: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    risk_score_breakdown: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # ========================================================
    # SUPPLIER PERFORMANCE
    # ========================================================

    supplier_reliability_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    on_time_delivery_rate: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    defect_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    lead_time_variability_days: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    supplier_performance_metrics: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # ========================================================
    # AI PREDICTIONS
    # ========================================================

    predicted_disruption_probability: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    predicted_disruption_date: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    predicted_disruption_type: Mapped[
        str | None
    ] = mapped_column(
        String(120),
        nullable=True,
    )

    model_confidence: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    model_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    model_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    ai_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
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

    ai_evidence: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    ai_analyzed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # FINANCIAL EXPOSURE
    # ========================================================

    currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    expected_financial_impact: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    estimated_mitigation_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    financial_exposure_details: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # ========================================================
    # RISK SIGNALS
    # ========================================================

    external_risk_signals: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    market_signals: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    news_signals: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    geographic_risk_details: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    risk_indicators: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # ========================================================
    # REVIEW
    # ========================================================

    review_status: Mapped[
        SupplierRiskReviewStatus
    ] = mapped_column(
        enum_type(
            SupplierRiskReviewStatus,
            "supplier_risk_review_status",
        ),
        default=SupplierRiskReviewStatus.NOT_REQUIRED,
        nullable=False,
    )

    requires_human_review: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    review_requested_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    reviewed_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    review_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    rejection_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ========================================================
    # MITIGATION
    # ========================================================

    mitigation_status: Mapped[
        SupplierRiskMitigationStatus
    ] = mapped_column(
        enum_type(
            SupplierRiskMitigationStatus,
            "supplier_risk_mitigation_status",
        ),
        default=SupplierRiskMitigationStatus.NOT_REQUIRED,
        nullable=False,
    )

    mitigation_plan: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    mitigation_owner_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    mitigation_approved_by: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    mitigation_approved_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    mitigation_started_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    mitigation_completed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    mitigation_outcome: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    mitigation_effectiveness_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    # ========================================================
    # MONITORING
    # ========================================================

    continuous_monitoring_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    monitoring_interval_hours: Mapped[int] = mapped_column(
        Integer,
        default=24,
        nullable=False,
    )

    last_monitored_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    next_monitoring_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    alert_required: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    alert_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    latest_alert_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    escalation_required: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # ========================================================
    # ASSESSMENT LIFECYCLE
    # ========================================================

    assessment_started_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    assessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    assessment_valid_until: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    resolution_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
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

    assessment_metadata: Mapped[
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
    # RELATIONSHIPS
    # ========================================================

    factors: Mapped[list["SupplierRiskFactor"]] = relationship(
        "SupplierRiskFactor",
        back_populates="assessment",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    recommendations: Mapped[
        list["SupplierRiskRecommendation"]
    ] = relationship(
        "SupplierRiskRecommendation",
        back_populates="assessment",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    events: Mapped[list["SupplierRiskEvent"]] = relationship(
        "SupplierRiskEvent",
        back_populates="assessment",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="SupplierRiskEvent.created_at",
    )

    # ========================================================
    # INITIALIZATION
    # ========================================================

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        defaults = {
            "id": generate_uuid,
            "assessment_number": generate_assessment_number,
            "status": lambda: SupplierRiskStatus.DRAFT,
            "risk_level": lambda: SupplierRiskLevel.UNKNOWN,
            "risk_trend": lambda: SupplierRiskTrend.UNKNOWN,
            "priority": lambda: SupplierRiskPriority.NORMAL,
            "source": lambda: SupplierRiskSource.MANUAL,
            "assessment_type": (
                lambda: SupplierRiskAssessmentType.PERIODIC
            ),
            "primary_risk_category": (
                lambda: SupplierRiskCategory.MULTI_FACTOR
            ),
            "review_status": (
                lambda: SupplierRiskReviewStatus.NOT_REQUIRED
            ),
            "mitigation_status": (
                lambda: SupplierRiskMitigationStatus.NOT_REQUIRED
            ),
            "requires_human_review": lambda: True,
            "continuous_monitoring_enabled": lambda: False,
            "monitoring_interval_hours": lambda: 24,
            "alert_required": lambda: False,
            "alert_count": lambda: 0,
            "escalation_required": lambda: False,
            "expected_financial_impact": lambda: ZERO,
            "estimated_mitigation_cost": lambda: ZERO,
            "currency": lambda: "INR",
            "is_deleted": lambda: False,
            "version": lambda: 1,
        }

        for field, factory in defaults.items():
            if getattr(self, field, None) is None:
                setattr(self, field, factory())

        for field in (
            "risk_weights",
            "risk_score_breakdown",
            "supplier_performance_metrics",
            "financial_exposure_details",
            "geographic_risk_details",
            "mitigation_plan",
            "assessment_metadata",
        ):
            if getattr(self, field, None) is None:
                setattr(self, field, {})

        for field in (
            "ai_recommendations",
            "ai_evidence",
            "external_risk_signals",
            "market_signals",
            "news_signals",
            "risk_indicators",
            "tags",
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
    def is_terminal(self) -> bool:
        return self.status in {
            SupplierRiskStatus.RESOLVED,
            SupplierRiskStatus.EXPIRED,
            SupplierRiskStatus.CANCELLED,
            SupplierRiskStatus.FAILED,
            SupplierRiskStatus.ARCHIVED,
        }

    @property
    def is_high_risk(self) -> bool:
        return self.risk_level in {
            SupplierRiskLevel.HIGH,
            SupplierRiskLevel.CRITICAL,
        }

    @property
    def is_critical(self) -> bool:
        return self.risk_level == SupplierRiskLevel.CRITICAL

    @property
    def is_reviewed(self) -> bool:
        return self.review_status == (
            SupplierRiskReviewStatus.APPROVED
        )

    @property
    def is_assessment_expired(self) -> bool:
        return (
            self.assessment_valid_until is not None
            and aware_datetime(
                self.assessment_valid_until
            ) <= utc_now()
        )

    @property
    def requires_attention(self) -> bool:
        return (
            self.is_high_risk
            or bool(self.alert_required)
            or bool(self.escalation_required)
        )

    @property
    def is_monitoring_due(self) -> bool:
        return (
            bool(self.continuous_monitoring_enabled)
            and self.next_monitoring_at is not None
            and aware_datetime(
                self.next_monitoring_at
            ) <= utc_now()
        )

    @property
    def active_recommendation_count(self) -> int:
        return sum(
            1
            for item in self.recommendations
            if item.status not in {
                SupplierRiskMitigationStatus.COMPLETED,
                SupplierRiskMitigationStatus.CANCELLED,
                SupplierRiskMitigationStatus.FAILED,
            }
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _ensure_editable(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Supplier risk assessment has been deleted"
            )

        if self.is_terminal:
            raise ValueError(
                "Terminal risk assessment cannot be modified"
            )

    def _require_status(
        self,
        *statuses: SupplierRiskStatus,
    ) -> None:
        self._ensure_editable()

        if self.status not in statuses:
            raise ValueError(
                f"Invalid status: {enum_value(self.status)}"
            )

    def _record_event(
        self,
        event_type: SupplierRiskEventType,
        *,
        actor_id: str | None = None,
        description: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.events.append(
            SupplierRiskEvent(
                id=generate_uuid(),
                organization_id=required_text(
                    self.organization_id,
                    "Organization ID",
                ),
                event_type=event_type,
                description=optional_text(description),
                details=json_safe(details or {}),
                actor_id=actor_id,
                created_at=utc_now(),
            )
        )

        self.updated_at = utc_now()

        if actor_id is not None:
            self.updated_by = actor_id

    def _set_risk_level(
        self,
        score: Decimal,
    ) -> None:
        if score >= Decimal("0.8500"):
            self.risk_level = SupplierRiskLevel.CRITICAL
        elif score >= Decimal("0.6500"):
            self.risk_level = SupplierRiskLevel.HIGH
        elif score >= Decimal("0.3500"):
            self.risk_level = SupplierRiskLevel.MEDIUM
        else:
            self.risk_level = SupplierRiskLevel.LOW

    def validate_assessment(self) -> None:
        required_text(
            self.organization_id,
            "Organization ID",
        )
        required_text(self.supplier_id, "Supplier ID")
        required_text(self.title, "Assessment title")

        if self.assessment_valid_until is not None:
            aware_datetime(self.assessment_valid_until)

        if self.currency:
            if (
                not isinstance(self.currency, str)
                or len(self.currency) != 3
                or not self.currency.isalpha()
                or self.currency != self.currency.upper()
            ):
                raise ValueError(
                    "Currency must use uppercase ISO alpha-3"
                )

    # ========================================================
    # START DATA COLLECTION
    # ========================================================

    def start_data_collection(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            SupplierRiskStatus.DRAFT,
            SupplierRiskStatus.PENDING,
        )

        self.validate_assessment()

        self.status = SupplierRiskStatus.COLLECTING_DATA
        self.assessment_started_at = utc_now()

        self._record_event(
            SupplierRiskEventType.DATA_COLLECTION_STARTED,
            actor_id=actor_id,
        )

    # ========================================================
    # UPDATE SUPPLIER PERFORMANCE
    # ========================================================

    def update_supplier_performance(
        self,
        *,
        actor_id: str,
        reliability_score: Decimal | str | float | None = None,
        on_time_delivery_rate: Decimal | str | float | None = None,
        defect_rate: Decimal | str | float | None = None,
        lead_time_variability_days: (
            Decimal | str | float | None
        ) = None,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        self._ensure_editable()

        if reliability_score is not None:
            self.supplier_reliability_score = score_value(
                reliability_score,
                "Supplier reliability score",
            )

        if on_time_delivery_rate is not None:
            self.on_time_delivery_rate = score_value(
                on_time_delivery_rate,
                "On-time delivery rate",
            )

        if defect_rate is not None:
            self.defect_rate = score_value(
                defect_rate,
                "Defect rate",
            )

        if lead_time_variability_days is not None:
            self.lead_time_variability_days = decimal_value(
                lead_time_variability_days,
                "Lead time variability",
                maximum=Decimal("99999999.9999"),
            )

        if metrics is not None:
            if not isinstance(metrics, dict):
                raise ValueError("Metrics must be a dictionary")

            self.supplier_performance_metrics = json_safe(
                metrics
            )

        self._record_event(
            SupplierRiskEventType.DATA_UPDATED,
            actor_id=actor_id,
            details={
                "source": "supplier_performance",
            },
        )

    # ========================================================
    # UPDATE RISK SCORES
    # ========================================================

    def update_risk_scores(
        self,
        *,
        actor_id: str,
        financial: Decimal | str | float | None = None,
        operational: Decimal | str | float | None = None,
        delivery: Decimal | str | float | None = None,
        quality: Decimal | str | float | None = None,
        compliance: Decimal | str | float | None = None,
        cybersecurity: Decimal | str | float | None = None,
        environmental: Decimal | str | float | None = None,
        concentration: Decimal | str | float | None = None,
        weights: dict[str, Decimal | str | float] | None = None,
    ) -> None:
        self._ensure_editable()

        incoming = {
            "financial": financial,
            "operational": operational,
            "delivery": delivery,
            "quality": quality,
            "compliance": compliance,
            "cybersecurity": cybersecurity,
            "environmental": environmental,
            "concentration": concentration,
        }

        fields = {
            "financial": "financial_risk_score",
            "operational": "operational_risk_score",
            "delivery": "delivery_risk_score",
            "quality": "quality_risk_score",
            "compliance": "compliance_risk_score",
            "cybersecurity": "cybersecurity_risk_score",
            "environmental": "environmental_risk_score",
            "concentration": "concentration_risk_score",
        }

        for name, value in incoming.items():
            if value is not None:
                setattr(
                    self,
                    fields[name],
                    score_value(value, f"{name} risk score"),
                )

        available_scores = {
            name: getattr(self, field)
            for name, field in fields.items()
            if getattr(self, field) is not None
        }

        if not available_scores:
            raise ValueError(
                "At least one risk score is required"
            )

        if weights is None:
            validated_weights = {
                name: ONE
                for name in available_scores
            }
        else:
            if not isinstance(weights, dict):
                raise ValueError("Weights must be a dictionary")

            unknown = set(weights) - set(fields)
            if unknown:
                raise ValueError(
                    f"Unknown risk weight categories: {unknown}"
                )

            validated_weights = {
                name: decimal_value(
                    weights.get(name, ZERO),
                    f"{name} weight",
                )
                for name in available_scores
            }

        total_weight = sum(
            validated_weights.values(),
            ZERO,
        )

        if total_weight <= ZERO:
            raise ValueError(
                "Total risk weight must be positive"
            )

        weighted_score = sum(
            available_scores[name] * validated_weights[name]
            for name in available_scores
        ) / total_weight

        self.overall_risk_score = weighted_score.quantize(
            SCORE_SCALE
        )

        self.risk_weights = {
            name: str(weight)
            for name, weight in validated_weights.items()
        }

        self.risk_score_breakdown = {
            name: str(value)
            for name, value in available_scores.items()
        }

        self._set_risk_level(self.overall_risk_score)

        self.alert_required = self.is_high_risk
        self.escalation_required = self.is_critical

        self._record_event(
            SupplierRiskEventType.RISK_SCORE_UPDATED,
            actor_id=actor_id,
            details={
                "overall_risk_score": str(
                    self.overall_risk_score
                ),
                "risk_level": self.risk_level.value,
                "risk_weights": self.risk_weights,
            },
        )

    # ========================================================
    # ADD RISK FACTOR
    # ========================================================

    def add_risk_factor(
        self,
        *,
        actor_id: str,
        title: str,
        category: SupplierRiskCategory,
        severity: SupplierRiskLevel,
        likelihood: Decimal | str | float,
        impact: Decimal | str | float,
        description: str | None = None,
        evidence: list[dict[str, Any]] | None = None,
    ) -> "SupplierRiskFactor":
        self._ensure_editable()

        if not isinstance(category, SupplierRiskCategory):
            raise ValueError("Invalid risk category")

        if not isinstance(severity, SupplierRiskLevel):
            raise ValueError("Invalid risk severity")

        likelihood_value = score_value(
            likelihood,
            "Likelihood",
        )
        impact_value = score_value(
            impact,
            "Impact",
        )

        factor = SupplierRiskFactor(
            id=generate_uuid(),
            organization_id=self.organization_id,
            title=required_text(title, "Factor title"),
            description=optional_text(description),
            category=category,
            severity=severity,
            likelihood=likelihood_value,
            impact=impact_value,
            factor_score=(
                likelihood_value * impact_value
            ).quantize(SCORE_SCALE),
            evidence=json_safe(evidence or []),
            is_active=True,
        )

        self.factors.append(factor)

        self._record_event(
            SupplierRiskEventType.FACTOR_ADDED,
            actor_id=actor_id,
            details={
                "factor_id": factor.id,
                "category": category.value,
                "factor_score": str(factor.factor_score),
            },
        )

        return factor

    # ========================================================
    # START AI ANALYSIS
    # ========================================================

    def start_analysis(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            SupplierRiskStatus.COLLECTING_DATA,
            SupplierRiskStatus.PENDING,
        )

        self.status = SupplierRiskStatus.ANALYZING

        self._record_event(
            SupplierRiskEventType.ANALYSIS_STARTED,
            actor_id=actor_id,
        )

    # ========================================================
    # RECORD AI ANALYSIS
    # ========================================================

    def record_ai_analysis(
        self,
        *,
        actor_id: str,
        disruption_probability: Decimal | str | float,
        model_confidence: Decimal | str | float,
        summary: str,
        explanation: str | None = None,
        predicted_disruption_date: datetime | None = None,
        predicted_disruption_type: str | None = None,
        recommendations: list[dict[str, Any]] | None = None,
        evidence: list[dict[str, Any]] | None = None,
        model_name: str | None = None,
        model_version: str | None = None,
        assessment_valid_until: datetime | None = None,
    ) -> None:
        self._require_status(
            SupplierRiskStatus.ANALYZING
        )

        if self.overall_risk_score is None:
            raise ValueError(
                "Calculate risk scores before completing analysis"
            )

        self.predicted_disruption_probability = score_value(
            disruption_probability,
            "Disruption probability",
        )

        self.model_confidence = score_value(
            model_confidence,
            "Model confidence",
        )

        self.ai_summary = required_text(
            summary,
            "AI summary",
        )

        self.ai_explanation = optional_text(explanation)
        self.predicted_disruption_type = optional_text(
            predicted_disruption_type
        )

        if predicted_disruption_date is not None:
            self.predicted_disruption_date = aware_datetime(
                predicted_disruption_date
            )

        if assessment_valid_until is not None:
            valid_until = aware_datetime(
                assessment_valid_until
            )

            if valid_until <= utc_now():
                raise ValueError(
                    "Assessment validity must be in the future"
                )

            self.assessment_valid_until = valid_until

        self.ai_recommendations = json_safe(
            recommendations or []
        )

        self.ai_evidence = json_safe(evidence or [])
        self.model_name = optional_text(model_name)
        self.model_version = optional_text(model_version)

        self.ai_analyzed_at = utc_now()
        self.assessed_at = utc_now()

        self.status = (
            SupplierRiskStatus.PENDING_REVIEW
            if self.requires_human_review
            else SupplierRiskStatus.REVIEWED
        )

        self.review_status = (
            SupplierRiskReviewStatus.PENDING
            if self.requires_human_review
            else SupplierRiskReviewStatus.NOT_REQUIRED
        )

        self._record_event(
            SupplierRiskEventType.ANALYSIS_COMPLETED,
            actor_id=actor_id,
            details={
                "risk_level": self.risk_level.value,
                "risk_score": str(self.overall_risk_score),
                "disruption_probability": str(
                    self.predicted_disruption_probability
                ),
                "model_confidence": str(
                    self.model_confidence
                ),
            },
        )

    # ========================================================
    # REQUEST REVIEW
    # ========================================================

    def request_review(
        self,
        *,
        actor_id: str,
        approval_request_id: str | None = None,
    ) -> None:
        self._require_status(
            SupplierRiskStatus.REVIEWED,
            SupplierRiskStatus.PENDING_REVIEW,
        )

        self.status = SupplierRiskStatus.PENDING_REVIEW
        self.review_status = SupplierRiskReviewStatus.PENDING
        self.review_requested_at = utc_now()

        if approval_request_id is not None:
            self.approval_request_id = required_text(
                approval_request_id,
                "Approval request ID",
            )

        self._record_event(
            SupplierRiskEventType.REVIEW_REQUESTED,
            actor_id=actor_id,
        )

    # ========================================================
    # APPROVE REVIEW
    # ========================================================

    def approve_review(
        self,
        *,
        reviewer_id: str,
        notes: str | None = None,
    ) -> None:
        self._require_status(
            SupplierRiskStatus.PENDING_REVIEW
        )

        self.reviewed_by = required_text(
            reviewer_id,
            "Reviewer ID",
        )

        self.reviewed_at = utc_now()
        self.review_notes = optional_text(notes)
        self.review_status = SupplierRiskReviewStatus.APPROVED
        self.status = SupplierRiskStatus.APPROVED

        self._record_event(
            SupplierRiskEventType.REVIEW_APPROVED,
            actor_id=reviewer_id,
        )

    # ========================================================
    # REJECT REVIEW
    # ========================================================

    def reject_review(
        self,
        *,
        reviewer_id: str,
        reason: str,
    ) -> None:
        self._require_status(
            SupplierRiskStatus.PENDING_REVIEW
        )

        self.reviewed_by = required_text(
            reviewer_id,
            "Reviewer ID",
        )
        self.reviewed_at = utc_now()
        self.rejection_reason = required_text(
            reason,
            "Rejection reason",
        )

        self.review_status = SupplierRiskReviewStatus.REJECTED
        self.status = SupplierRiskStatus.REJECTED

        self._record_event(
            SupplierRiskEventType.REVIEW_REJECTED,
            actor_id=reviewer_id,
            details={"reason": self.rejection_reason},
        )

    # ========================================================
    # START MONITORING
    # ========================================================

    def start_monitoring(
        self,
        *,
        actor_id: str,
        interval_hours: int = 24,
    ) -> None:
        self._require_status(
            SupplierRiskStatus.APPROVED,
            SupplierRiskStatus.REVIEWED,
        )

        if (
            self.requires_human_review
            and self.review_status
            != SupplierRiskReviewStatus.APPROVED
        ):
            raise ValueError(
                "Human review must be approved"
            )

        interval = nonnegative_int(
            interval_hours,
            "Monitoring interval",
        )

        if interval < 1:
            raise ValueError(
                "Monitoring interval must be at least one hour"
            )

        self.monitoring_interval_hours = interval
        self.continuous_monitoring_enabled = True
        self.status = SupplierRiskStatus.MONITORING
        self.last_monitored_at = utc_now()

        from datetime import timedelta

        self.next_monitoring_at = (
            self.last_monitored_at
            + timedelta(hours=interval)
        )

        self._record_event(
            SupplierRiskEventType.MONITORING_STARTED,
            actor_id=actor_id,
            details={"interval_hours": interval},
        )

    # ========================================================
    # ADD MITIGATION RECOMMENDATION
    # ========================================================

    def add_recommendation(
        self,
        *,
        actor_id: str,
        title: str,
        recommendation_type: SupplierRiskRecommendationType,
        description: str,
        priority: SupplierRiskPriority = (
            SupplierRiskPriority.NORMAL
        ),
        estimated_cost: Decimal | str | float = ZERO,
        expected_risk_reduction: (
            Decimal | str | float | None
        ) = None,
        requires_approval: bool = True,
    ) -> "SupplierRiskRecommendation":
        self._ensure_editable()

        if not isinstance(
            recommendation_type,
            SupplierRiskRecommendationType,
        ):
            raise ValueError("Invalid recommendation type")

        if not isinstance(priority, SupplierRiskPriority):
            raise ValueError("Invalid priority")

        cost = decimal_value(
            estimated_cost,
            "Estimated cost",
            maximum=Decimal("9999999999999999.9999"),
        )

        reduction = (
            score_value(
                expected_risk_reduction,
                "Expected risk reduction",
            )
            if expected_risk_reduction is not None
            else None
        )

        recommendation = SupplierRiskRecommendation(
            id=generate_uuid(),
            organization_id=self.organization_id,
            title=required_text(
                title,
                "Recommendation title",
            ),
            description=required_text(
                description,
                "Recommendation description",
            ),
            recommendation_type=recommendation_type,
            priority=priority,
            status=SupplierRiskMitigationStatus.PROPOSED,
            estimated_cost=cost,
            expected_risk_reduction=reduction,
            requires_approval=requires_approval,
        )

        self.recommendations.append(recommendation)

        if self.mitigation_status == (
            SupplierRiskMitigationStatus.NOT_REQUIRED
        ):
            self.mitigation_status = (
                SupplierRiskMitigationStatus.PROPOSED
            )

        self._record_event(
            SupplierRiskEventType.MITIGATION_PROPOSED,
            actor_id=actor_id,
            details={
                "recommendation_id": recommendation.id,
                "type": recommendation_type.value,
            },
        )

        return recommendation

    # ========================================================
    # APPROVE MITIGATION
    # ========================================================

    def approve_mitigation(
        self,
        *,
        approver_id: str,
        owner_id: str,
        plan: dict[str, Any],
    ) -> None:
        self._require_status(
            SupplierRiskStatus.APPROVED,
            SupplierRiskStatus.MONITORING,
        )

        if not isinstance(plan, dict) or not plan:
            raise ValueError(
                "Mitigation plan must be a nonempty dictionary"
            )

        self.mitigation_owner_id = required_text(
            owner_id,
            "Mitigation owner ID",
        )
        self.mitigation_approved_by = required_text(
            approver_id,
            "Approver ID",
        )

        self.mitigation_plan = json_safe(plan)
        self.mitigation_approved_at = utc_now()
        self.mitigation_status = (
            SupplierRiskMitigationStatus.APPROVED
        )

        self._record_event(
            SupplierRiskEventType.MITIGATION_APPROVED,
            actor_id=approver_id,
        )

    # ========================================================
    # START MITIGATION
    # ========================================================

    def start_mitigation(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            SupplierRiskStatus.APPROVED,
            SupplierRiskStatus.MONITORING,
        )

        if self.mitigation_status != (
            SupplierRiskMitigationStatus.APPROVED
        ):
            raise ValueError(
                "Mitigation must be approved before execution"
            )

        self.mitigation_status = (
            SupplierRiskMitigationStatus.IN_PROGRESS
        )
        self.mitigation_started_at = utc_now()
        self.status = SupplierRiskStatus.MITIGATING

        self._record_event(
            SupplierRiskEventType.MITIGATION_STARTED,
            actor_id=actor_id,
        )

    # ========================================================
    # COMPLETE MITIGATION
    # ========================================================

    def complete_mitigation(
        self,
        *,
        actor_id: str,
        outcome: str,
        effectiveness_score: Decimal | str | float,
    ) -> None:
        self._require_status(
            SupplierRiskStatus.MITIGATING
        )

        if self.mitigation_status != (
            SupplierRiskMitigationStatus.IN_PROGRESS
        ):
            raise ValueError(
                "Mitigation is not in progress"
            )

        self.mitigation_outcome = required_text(
            outcome,
            "Mitigation outcome",
        )

        self.mitigation_effectiveness_score = score_value(
            effectiveness_score,
            "Mitigation effectiveness score",
        )

        self.mitigation_completed_at = utc_now()
        self.mitigation_status = (
            SupplierRiskMitigationStatus.COMPLETED
        )
        self.status = SupplierRiskStatus.MONITORING

        self._record_event(
            SupplierRiskEventType.MITIGATION_COMPLETED,
            actor_id=actor_id,
            details={
                "effectiveness_score": str(
                    self.mitigation_effectiveness_score
                ),
            },
        )

    # ========================================================
    # RECORD ALERT
    # ========================================================

    def record_alert(
        self,
        *,
        actor_id: str,
        alert_id: str,
        requires_escalation: bool = False,
    ) -> None:
        self._ensure_editable()

        self.latest_alert_id = required_text(
            alert_id,
            "Alert ID",
        )

        self.alert_count = (self.alert_count or 0) + 1
        self.alert_required = True

        if requires_escalation:
            self.escalation_required = True

        self._record_event(
            SupplierRiskEventType.ALERT_RECORDED,
            actor_id=actor_id,
            details={
                "alert_id": self.latest_alert_id,
                "requires_escalation": requires_escalation,
            },
        )

    # ========================================================
    # RESOLVE
    # ========================================================

    def resolve(
        self,
        *,
        actor_id: str,
        notes: str,
    ) -> None:
        self._require_status(
            SupplierRiskStatus.APPROVED,
            SupplierRiskStatus.REVIEWED,
            SupplierRiskStatus.MONITORING,
            SupplierRiskStatus.MITIGATING,
        )

        if self.mitigation_status == (
            SupplierRiskMitigationStatus.IN_PROGRESS
        ):
            raise ValueError(
                "Complete or cancel mitigation before resolving"
            )

        self.resolution_notes = required_text(
            notes,
            "Resolution notes",
        )
        self.resolved_at = utc_now()
        self.status = SupplierRiskStatus.RESOLVED

        self.continuous_monitoring_enabled = False
        self.next_monitoring_at = None
        self.alert_required = False
        self.escalation_required = False

        self._record_event(
            SupplierRiskEventType.RESOLVED,
            actor_id=actor_id,
        )

    # ========================================================
    # EXPIRE ASSESSMENT
    # ========================================================

    def expire(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        if not self.is_assessment_expired:
            raise ValueError(
                "Assessment validity has not expired"
            )

        self.status = SupplierRiskStatus.EXPIRED
        self.continuous_monitoring_enabled = False
        self.next_monitoring_at = None

        self._record_event(
            SupplierRiskEventType.EXPIRED,
            actor_id=actor_id,
        )

    # ========================================================
    # MARK FAILED
    # ========================================================

    def mark_failed(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_editable()

        self.failure_reason = required_text(
            reason,
            "Failure reason",
        )
        self.failed_at = utc_now()
        self.status = SupplierRiskStatus.FAILED

        self.continuous_monitoring_enabled = False
        self.next_monitoring_at = None

        self._record_event(
            SupplierRiskEventType.FAILED,
            actor_id=actor_id,
            details={"reason": self.failure_reason},
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
        self._ensure_editable()

        self.cancellation_reason = required_text(
            reason,
            "Cancellation reason",
        )
        self.cancelled_at = utc_now()
        self.status = SupplierRiskStatus.CANCELLED

        self.continuous_monitoring_enabled = False
        self.next_monitoring_at = None

        self._record_event(
            SupplierRiskEventType.CANCELLED,
            actor_id=actor_id,
            details={"reason": self.cancellation_reason},
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
            raise ValueError("Assessment has been deleted")

        if self.status not in {
            SupplierRiskStatus.RESOLVED,
            SupplierRiskStatus.EXPIRED,
            SupplierRiskStatus.CANCELLED,
            SupplierRiskStatus.FAILED,
            SupplierRiskStatus.REJECTED,
        }:
            raise ValueError(
                "Assessment must be closed before archiving"
            )

        self.status = SupplierRiskStatus.ARCHIVED
        self.archived_at = utc_now()

        self._record_event(
            SupplierRiskEventType.ARCHIVED,
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
            raise ValueError("Assessment already deleted")

        if self.status not in {
            SupplierRiskStatus.DRAFT,
            SupplierRiskStatus.ARCHIVED,
        }:
            raise ValueError(
                "Only draft or archived assessments "
                "can be soft-deleted"
            )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = required_text(
            actor_id,
            "Actor ID",
        )

        self._record_event(
            SupplierRiskEventType.SOFT_DELETED,
            actor_id=actor_id,
        )

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(
        self,
        *,
        include_internal: bool = False,
        include_factors: bool = True,
        include_recommendations: bool = True,
        include_events: bool = False,
    ) -> dict[str, Any]:

        data = {
            "id": self.id,
            "organization_id": self.organization_id,
            "assessment_number": self.assessment_number,
            "title": self.title,
            "description": self.description,
            "supplier_id": self.supplier_id,
            "supplier_contract_id": self.supplier_contract_id,
            "warehouse_id": self.warehouse_id,
            "store_id": self.store_id,
            "product_id": self.product_id,
            "category_id": self.category_id,
            "status": enum_value(self.status),
            "assessment_type": enum_value(
                self.assessment_type
            ),
            "source": enum_value(self.source),
            "priority": enum_value(self.priority),
            "primary_risk_category": enum_value(
                self.primary_risk_category
            ),
            "risk_level": enum_value(self.risk_level),
            "risk_trend": enum_value(self.risk_trend),
            "overall_risk_score": decimal_string(
                self.overall_risk_score
            ),
            "financial_risk_score": decimal_string(
                self.financial_risk_score
            ),
            "operational_risk_score": decimal_string(
                self.operational_risk_score
            ),
            "delivery_risk_score": decimal_string(
                self.delivery_risk_score
            ),
            "quality_risk_score": decimal_string(
                self.quality_risk_score
            ),
            "compliance_risk_score": decimal_string(
                self.compliance_risk_score
            ),
            "cybersecurity_risk_score": decimal_string(
                self.cybersecurity_risk_score
            ),
            "environmental_risk_score": decimal_string(
                self.environmental_risk_score
            ),
            "concentration_risk_score": decimal_string(
                self.concentration_risk_score
            ),
            "supplier_reliability_score": decimal_string(
                self.supplier_reliability_score
            ),
            "on_time_delivery_rate": decimal_string(
                self.on_time_delivery_rate
            ),
            "defect_rate": decimal_string(self.defect_rate),
            "predicted_disruption_probability": decimal_string(
                self.predicted_disruption_probability
            ),
            "predicted_disruption_date": iso(
                self.predicted_disruption_date
            ),
            "predicted_disruption_type": (
                self.predicted_disruption_type
            ),
            "model_confidence": decimal_string(
                self.model_confidence
            ),
            "ai_summary": self.ai_summary,
            "ai_explanation": self.ai_explanation,
            "ai_recommendations": self.ai_recommendations,
            "currency": self.currency,
            "expected_financial_impact": decimal_string(
                self.expected_financial_impact
            ),
            "estimated_mitigation_cost": decimal_string(
                self.estimated_mitigation_cost
            ),
            "review_status": enum_value(self.review_status),
            "requires_human_review": (
                self.requires_human_review
            ),
            "mitigation_status": enum_value(
                self.mitigation_status
            ),
            "continuous_monitoring_enabled": (
                self.continuous_monitoring_enabled
            ),
            "monitoring_interval_hours": (
                self.monitoring_interval_hours
            ),
            "last_monitored_at": iso(
                self.last_monitored_at
            ),
            "next_monitoring_at": iso(
                self.next_monitoring_at
            ),
            "alert_required": self.alert_required,
            "alert_count": self.alert_count,
            "escalation_required": self.escalation_required,
            "assessment_started_at": iso(
                self.assessment_started_at
            ),
            "assessed_at": iso(self.assessed_at),
            "assessment_valid_until": iso(
                self.assessment_valid_until
            ),
            "resolved_at": iso(self.resolved_at),
            "is_high_risk": self.is_high_risk,
            "is_critical": self.is_critical,
            "is_assessment_expired": (
                self.is_assessment_expired
            ),
            "requires_attention": self.requires_attention,
            "is_monitoring_due": self.is_monitoring_due,
            "active_recommendation_count": (
                self.active_recommendation_count
            ),
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "is_deleted": self.is_deleted,
            "version": self.version,
        }

        if include_factors:
            data["factors"] = [
                factor.to_dict()
                for factor in self.factors
            ]

        if include_recommendations:
            data["recommendations"] = [
                recommendation.to_dict()
                for recommendation in self.recommendations
            ]

        if include_events:
            data["events"] = [
                event.to_dict()
                for event in self.events
            ]

        if include_internal:
            data.update({
                "idempotency_key": self.idempotency_key,
                "purchase_order_id": self.purchase_order_id,
                "replenishment_plan_id": (
                    self.replenishment_plan_id
                ),
                "incident_id": self.incident_id,
                "escalation_id": self.escalation_id,
                "approval_request_id": (
                    self.approval_request_id
                ),
                "model_registry_id": self.model_registry_id,
                "agent_run_id": self.agent_run_id,
                "previous_assessment_id": (
                    self.previous_assessment_id
                ),
                "risk_weights": self.risk_weights,
                "risk_score_breakdown": (
                    self.risk_score_breakdown
                ),
                "supplier_performance_metrics": (
                    self.supplier_performance_metrics
                ),
                "financial_exposure_details": (
                    self.financial_exposure_details
                ),
                "external_risk_signals": (
                    self.external_risk_signals
                ),
                "market_signals": self.market_signals,
                "news_signals": self.news_signals,
                "geographic_risk_details": (
                    self.geographic_risk_details
                ),
                "risk_indicators": self.risk_indicators,
                "ai_evidence": self.ai_evidence,
                "mitigation_plan": self.mitigation_plan,
                "mitigation_owner_id": self.mitigation_owner_id,
                "mitigation_approved_by": (
                    self.mitigation_approved_by
                ),
                "mitigation_approved_at": iso(
                    self.mitigation_approved_at
                ),
                "mitigation_outcome": self.mitigation_outcome,
                "mitigation_effectiveness_score": decimal_string(
                    self.mitigation_effectiveness_score
                ),
                "reviewed_by": self.reviewed_by,
                "reviewed_at": iso(self.reviewed_at),
                "review_notes": self.review_notes,
                "rejection_reason": self.rejection_reason,
                "failure_reason": self.failure_reason,
                "cancellation_reason": self.cancellation_reason,
                "resolution_notes": self.resolution_notes,
                "assessment_metadata": self.assessment_metadata,
                "tags": self.tags,
                "created_by": self.created_by,
                "updated_by": self.updated_by,
                "trace_id": self.trace_id,
                "correlation_id": self.correlation_id,
                "deleted_at": iso(self.deleted_at),
                "deleted_by": self.deleted_by,
            })

        return data

    def __repr__(self) -> str:
        return (
            f"<SupplierRisk("
            f"id={self.id!r}, "
            f"supplier_id={self.supplier_id!r}, "
            f"risk_level={enum_value(self.risk_level)!r}, "
            f"status={enum_value(self.status)!r}"
            f")>"
        )


# ============================================================
# SUPPLIER RISK FACTOR
# ============================================================

class SupplierRiskFactor(Base):
    __tablename__ = "supplier_risk_factors"

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "assessment_id"],
            [
                "supplier_risks.organization_id",
                "supplier_risks.id",
            ],
            name="fk_supplier_risk_factor_assessment",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "likelihood >= 0 AND likelihood <= 1",
            name="ck_supplier_risk_factor_likelihood",
        ),
        CheckConstraint(
            "impact >= 0 AND impact <= 1",
            name="ck_supplier_risk_factor_impact",
        ),
        CheckConstraint(
            "factor_score >= 0 AND factor_score <= 1",
            name="ck_supplier_risk_factor_score",
        ),
        Index(
            "ix_supplier_risk_factor_category",
            "organization_id",
            "category",
        ),
        Index(
            "ix_supplier_risk_factor_assessment",
            "assessment_id",
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

    assessment_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    category: Mapped[SupplierRiskCategory] = mapped_column(
        enum_type(
            SupplierRiskCategory,
            "supplier_risk_factor_category",
        ),
        nullable=False,
    )

    severity: Mapped[SupplierRiskLevel] = mapped_column(
        enum_type(
            SupplierRiskLevel,
            "supplier_risk_factor_severity",
        ),
        nullable=False,
    )

    likelihood: Mapped[Decimal] = mapped_column(
        Numeric(6, 4),
        nullable=False,
    )

    impact: Mapped[Decimal] = mapped_column(
        Numeric(6, 4),
        nullable=False,
    )

    factor_score: Mapped[Decimal] = mapped_column(
        Numeric(6, 4),
        nullable=False,
    )

    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    mitigation_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
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

    assessment: Mapped[SupplierRisk] = relationship(
        "SupplierRisk",
        back_populates="factors",
    )

    def update_score(
        self,
        *,
        likelihood: Decimal | str | float,
        impact: Decimal | str | float,
    ) -> None:
        if not self.is_active:
            raise ValueError(
                "Resolved risk factor cannot be updated"
            )

        self.likelihood = score_value(
            likelihood,
            "Likelihood",
        )
        self.impact = score_value(
            impact,
            "Impact",
        )

        self.factor_score = (
            self.likelihood * self.impact
        ).quantize(SCORE_SCALE)

        self.updated_at = utc_now()

    def resolve(
        self,
        *,
        notes: str,
    ) -> None:
        if not self.is_active:
            raise ValueError("Risk factor already resolved")

        self.mitigation_notes = required_text(
            notes,
            "Mitigation notes",
        )

        self.is_active = False
        self.resolved_at = utc_now()
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "assessment_id": self.assessment_id,
            "title": self.title,
            "description": self.description,
            "category": enum_value(self.category),
            "severity": enum_value(self.severity),
            "likelihood": decimal_string(self.likelihood),
            "impact": decimal_string(self.impact),
            "factor_score": decimal_string(
                self.factor_score
            ),
            "evidence": self.evidence,
            "mitigation_notes": self.mitigation_notes,
            "is_active": self.is_active,
            "detected_at": iso(self.detected_at),
            "resolved_at": iso(self.resolved_at),
            "created_at": iso(self.created_at),
        }


# ============================================================
# SUPPLIER RISK RECOMMENDATION
# ============================================================

class SupplierRiskRecommendation(Base):
    __tablename__ = "supplier_risk_recommendations"

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "assessment_id"],
            [
                "supplier_risks.organization_id",
                "supplier_risks.id",
            ],
            name="fk_supplier_risk_recommendation_assessment",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "estimated_cost >= 0",
            name="ck_supplier_risk_recommendation_cost",
        ),
        CheckConstraint(
            "expected_risk_reduction IS NULL OR "
            "(expected_risk_reduction >= 0 AND "
            "expected_risk_reduction <= 1)",
            name="ck_supplier_risk_recommendation_reduction",
        ),
        Index(
            "ix_supplier_risk_recommendation_status",
            "organization_id",
            "status",
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

    assessment_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    recommendation_type: Mapped[
        SupplierRiskRecommendationType
    ] = mapped_column(
        enum_type(
            SupplierRiskRecommendationType,
            "supplier_risk_recommendation_type",
        ),
        nullable=False,
    )

    priority: Mapped[SupplierRiskPriority] = mapped_column(
        enum_type(
            SupplierRiskPriority,
            "supplier_risk_recommendation_priority",
        ),
        default=SupplierRiskPriority.NORMAL,
        nullable=False,
    )

    status: Mapped[
        SupplierRiskMitigationStatus
    ] = mapped_column(
        enum_type(
            SupplierRiskMitigationStatus,
            "supplier_risk_recommendation_status",
        ),
        default=SupplierRiskMitigationStatus.PROPOSED,
        nullable=False,
    )

    estimated_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    expected_risk_reduction: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    assigned_to: Mapped[str | None] = mapped_column(
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

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    outcome: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    recommendation_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
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

    assessment: Mapped[SupplierRisk] = relationship(
        "SupplierRisk",
        back_populates="recommendations",
    )

    def approve(
        self,
        *,
        approver_id: str,
    ) -> None:
        if self.status not in {
            SupplierRiskMitigationStatus.PROPOSED,
            SupplierRiskMitigationStatus.PENDING_APPROVAL,
        }:
            raise ValueError(
                "Recommendation cannot be approved"
            )

        self.approved_by = required_text(
            approver_id,
            "Approver ID",
        )
        self.approved_at = utc_now()
        self.status = SupplierRiskMitigationStatus.APPROVED
        self.updated_at = utc_now()

    def start(
        self,
        *,
        actor_id: str,
    ) -> None:
        required_text(actor_id, "Actor ID")

        if self.status != SupplierRiskMitigationStatus.APPROVED:
            raise ValueError(
                "Recommendation must be approved"
            )

        self.status = (
            SupplierRiskMitigationStatus.IN_PROGRESS
        )
        self.started_at = utc_now()
        self.updated_at = utc_now()

    def complete(
        self,
        *,
        actor_id: str,
        outcome: str,
    ) -> None:
        required_text(actor_id, "Actor ID")

        if self.status != (
            SupplierRiskMitigationStatus.IN_PROGRESS
        ):
            raise ValueError(
                "Recommendation is not in progress"
            )

        self.outcome = required_text(
            outcome,
            "Outcome",
        )
        self.completed_at = utc_now()
        self.updated_at = utc_now()
        self.status = SupplierRiskMitigationStatus.COMPLETED

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "assessment_id": self.assessment_id,
            "title": self.title,
            "description": self.description,
            "recommendation_type": enum_value(
                self.recommendation_type
            ),
            "priority": enum_value(self.priority),
            "status": enum_value(self.status),
            "estimated_cost": decimal_string(
                self.estimated_cost
            ),
            "expected_risk_reduction": decimal_string(
                self.expected_risk_reduction
            ),
            "requires_approval": self.requires_approval,
            "assigned_to": self.assigned_to,
            "approved_at": iso(self.approved_at),
            "started_at": iso(self.started_at),
            "completed_at": iso(self.completed_at),
            "outcome": self.outcome,
            "created_at": iso(self.created_at),
        }


# ============================================================
# SUPPLIER RISK EVENT
# ============================================================

class SupplierRiskEvent(Base):
    __tablename__ = "supplier_risk_events"

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "assessment_id"],
            [
                "supplier_risks.organization_id",
                "supplier_risks.id",
            ],
            name="fk_supplier_risk_event_assessment",
            ondelete="CASCADE",
        ),
        Index(
            "ix_supplier_risk_event_assessment_created",
            "assessment_id",
            "created_at",
        ),
        Index(
            "ix_supplier_risk_event_org_type",
            "organization_id",
            "event_type",
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

    assessment_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    event_type: Mapped[SupplierRiskEventType] = mapped_column(
        enum_type(
            SupplierRiskEventType,
            "supplier_risk_event_type",
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

    assessment: Mapped[SupplierRisk] = relationship(
        "SupplierRisk",
        back_populates="events",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "assessment_id": self.assessment_id,
            "event_type": enum_value(self.event_type),
            "description": self.description,
            "details": self.details,
            "actor_id": self.actor_id,
            "created_at": iso(self.created_at),
        }

    def __repr__(self) -> str:
        return (
            f"<SupplierRiskEvent("
            f"id={self.id!r}, "
            f"assessment_id={self.assessment_id!r}, "
            f"event_type={enum_value(self.event_type)!r}"
            f")>"
        )