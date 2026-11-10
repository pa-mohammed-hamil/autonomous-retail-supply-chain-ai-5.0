from __future__ import annotations

"""Planned module: supplier. Implementation pending."""
# backend/models/supplier.py


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


def generate_supplier_code() -> str:
    return f"SUP-{uuid.uuid4().hex[:12].upper()}"


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


def validate_score(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field} must be numeric") from exc

    if not result.is_finite() or not Decimal("0") <= result <= Decimal("1"):
        raise ValueError(f"{field} must be between 0 and 1")

    if result.as_tuple().exponent < -4:
        raise ValueError(f"{field} supports at most 4 decimal places")

    return result


def validate_nonnegative(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"{field} must be numeric") from exc

    if not result.is_finite() or result < 0:
        raise ValueError(f"{field} must be nonnegative")

    if result.as_tuple().exponent < -4:
        raise ValueError(f"{field} supports at most 4 decimal places")

    return result


def enum_value(value: Any) -> Any:
    return value.value if isinstance(value, enum.Enum) else value


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, (Decimal, float)):
        return str(value)

    if isinstance(value, enum.Enum):
        return value.value

    if isinstance(value, datetime):
        return value.isoformat()

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


def serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, enum.Enum):
        return value.value

    return value


# ============================================================
# ENUMS
# ============================================================

class SupplierStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_VERIFICATION = "pending_verification"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    SUSPENDED = "suspended"
    BLOCKED = "blocked"
    INACTIVE = "inactive"
    TERMINATED = "terminated"
    ARCHIVED = "archived"


class SupplierType(str, enum.Enum):
    MANUFACTURER = "manufacturer"
    DISTRIBUTOR = "distributor"
    WHOLESALER = "wholesaler"
    IMPORTER = "importer"
    EXPORTER = "exporter"
    LOGISTICS_PROVIDER = "logistics_provider"
    SERVICE_PROVIDER = "service_provider"
    RAW_MATERIAL = "raw_material"
    PACKAGING = "packaging"
    TECHNOLOGY = "technology"
    DROPSHIPPER = "dropshipper"
    THIRD_PARTY = "third_party"
    OTHER = "other"


class SupplierTier(str, enum.Enum):
    STRATEGIC = "strategic"
    PREFERRED = "preferred"
    STANDARD = "standard"
    CONDITIONAL = "conditional"
    PROBATIONARY = "probationary"


class SupplierRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class SupplierVerificationStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    VERIFIED = "verified"
    FAILED = "failed"
    EXPIRED = "expired"


class SupplierApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SupplierPaymentTerms(str, enum.Enum):
    PREPAID = "prepaid"
    CASH_ON_DELIVERY = "cash_on_delivery"
    NET_7 = "net_7"
    NET_15 = "net_15"
    NET_30 = "net_30"
    NET_45 = "net_45"
    NET_60 = "net_60"
    NET_90 = "net_90"
    CUSTOM = "custom"


class SupplierEventType(str, enum.Enum):
    CREATED = "created"
    UPDATED = "updated"
    VERIFICATION_REQUESTED = "verification_requested"
    VERIFIED = "verified"
    VERIFICATION_FAILED = "verification_failed"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVATED = "activated"
    PUT_ON_HOLD = "put_on_hold"
    SUSPENDED = "suspended"
    BLOCKED = "blocked"
    REACTIVATED = "reactivated"
    DEACTIVATED = "deactivated"
    TERMINATED = "terminated"
    ARCHIVED = "archived"
    PERFORMANCE_UPDATED = "performance_updated"
    RISK_UPDATED = "risk_updated"
    CONTRACT_LINKED = "contract_linked"
    DOCUMENT_ADDED = "document_added"
    CONTACT_ADDED = "contact_added"
    SOFT_DELETED = "soft_deleted"


# ============================================================
# SUPPLIER MODEL
# ============================================================

class Supplier(Base):
    __tablename__ = "suppliers"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "supplier_code",
            name="uq_supplier_org_code",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_supplier_org_idempotency",
        ),
        CheckConstraint(
            "risk_score IS NULL OR "
            "(risk_score >= 0 AND risk_score <= 1)",
            name="ck_supplier_risk_score",
        ),
        CheckConstraint(
            "reliability_score IS NULL OR "
            "(reliability_score >= 0 AND reliability_score <= 1)",
            name="ck_supplier_reliability",
        ),
        CheckConstraint(
            "quality_score IS NULL OR "
            "(quality_score >= 0 AND quality_score <= 1)",
            name="ck_supplier_quality",
        ),
        CheckConstraint(
            "delivery_score IS NULL OR "
            "(delivery_score >= 0 AND delivery_score <= 1)",
            name="ck_supplier_delivery",
        ),
        CheckConstraint(
            "on_time_delivery_rate IS NULL OR "
            "(on_time_delivery_rate >= 0 AND on_time_delivery_rate <= 1)",
            name="ck_supplier_on_time_rate",
        ),
        CheckConstraint(
            "defect_rate IS NULL OR "
            "(defect_rate >= 0 AND defect_rate <= 1)",
            name="ck_supplier_defect_rate",
        ),
        CheckConstraint(
            "average_lead_time_days >= 0",
            name="ck_supplier_lead_time",
        ),
        CheckConstraint(
            "minimum_order_value >= 0",
            name="ck_supplier_min_order_value",
        ),
        CheckConstraint(
            "credit_limit >= 0",
            name="ck_supplier_credit_limit",
        ),
        CheckConstraint(
            "total_purchase_value >= 0",
            name="ck_supplier_total_purchase",
        ),
        CheckConstraint(
            "total_orders >= 0",
            name="ck_supplier_total_orders",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_supplier_version",
        ),
        Index(
            "ix_supplier_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_supplier_org_type",
            "organization_id",
            "supplier_type",
        ),
        Index(
            "ix_supplier_org_tier",
            "organization_id",
            "tier",
        ),
        Index(
            "ix_supplier_org_risk",
            "organization_id",
            "risk_level",
        ),
        Index(
            "ix_supplier_org_name",
            "organization_id",
            "name",
        ),
        Index(
            "ix_supplier_org_country",
            "organization_id",
            "country",
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

    supplier_code: Mapped[str] = mapped_column(
        String(60),
        nullable=False,
        default=generate_supplier_code,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    legal_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    supplier_type: Mapped[SupplierType] = mapped_column(
        enum_column(
            SupplierType,
            "supplier_type",
        ),
        default=SupplierType.DISTRIBUTOR,
        nullable=False,
    )

    status: Mapped[SupplierStatus] = mapped_column(
        enum_column(
            SupplierStatus,
            "supplier_status",
        ),
        default=SupplierStatus.DRAFT,
        nullable=False,
    )

    tier: Mapped[SupplierTier] = mapped_column(
        enum_column(
            SupplierTier,
            "supplier_tier",
        ),
        default=SupplierTier.STANDARD,
        nullable=False,
    )

    # ========================================================
    # BUSINESS DETAILS
    # ========================================================

    registration_number: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    tax_identification_number: Mapped[
        str | None
    ] = mapped_column(
        String(120),
        nullable=True,
    )

    gst_number: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    pan_number: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    industry: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    business_category: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    website: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    year_established: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # ========================================================
    # CONTACT INFORMATION
    # ========================================================

    primary_contact_name: Mapped[
        str | None
    ] = mapped_column(
        String(150),
        nullable=True,
    )

    primary_contact_email: Mapped[
        str | None
    ] = mapped_column(
        String(255),
        nullable=True,
    )

    primary_contact_phone: Mapped[
        str | None
    ] = mapped_column(
        String(40),
        nullable=True,
    )

    support_email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    support_phone: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )

    alternate_phone: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )

    contacts: Mapped[list[dict[str, Any]]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # ========================================================
    # ADDRESS
    # ========================================================

    address_line_1: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    address_line_2: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    city: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    state: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    country: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
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

    service_regions: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # ========================================================
    # PROCUREMENT
    # ========================================================

    currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    payment_terms: Mapped[SupplierPaymentTerms] = mapped_column(
        enum_column(
            SupplierPaymentTerms,
            "supplier_payment_terms",
        ),
        default=SupplierPaymentTerms.NET_30,
        nullable=False,
    )

    custom_payment_terms: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    minimum_order_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    minimum_order_quantity: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    average_lead_time_days: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    lead_time_variability_days: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    credit_limit: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    delivery_terms: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    shipping_methods: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    supported_product_categories: Mapped[
        list[str]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # ========================================================
    # PERFORMANCE
    # ========================================================

    reliability_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    quality_score: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    delivery_score: Mapped[Decimal | None] = mapped_column(
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

    total_orders: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    completed_orders: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    cancelled_orders: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    late_deliveries: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    total_purchase_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    last_order_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_delivery_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    performance_metrics: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # ========================================================
    # RISK INTELLIGENCE
    # ========================================================

    risk_level: Mapped[SupplierRiskLevel] = mapped_column(
        enum_column(
            SupplierRiskLevel,
            "supplier_master_risk_level",
        ),
        default=SupplierRiskLevel.UNKNOWN,
        nullable=False,
    )

    risk_score: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    latest_risk_assessment_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    risk_assessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    risk_factors: Mapped[list[dict[str, Any]]] = mapped_column(
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

    requires_enhanced_monitoring: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # ========================================================
    # VERIFICATION AND APPROVAL
    # ========================================================

    verification_status: Mapped[
        SupplierVerificationStatus
    ] = mapped_column(
        enum_column(
            SupplierVerificationStatus,
            "supplier_verification_status",
        ),
        default=SupplierVerificationStatus.NOT_STARTED,
        nullable=False,
    )

    approval_status: Mapped[
        SupplierApprovalStatus
    ] = mapped_column(
        enum_column(
            SupplierApprovalStatus,
            "supplier_approval_status",
        ),
        default=SupplierApprovalStatus.NOT_REQUIRED,
        nullable=False,
    )

    approval_request_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    verified_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
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

    verification_notes: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    rejection_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ========================================================
    # CONTRACTS AND DOCUMENTS
    # ========================================================

    active_contract_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    contract_start_date: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    contract_end_date: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    certifications: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    document_references: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    compliance_details: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # ========================================================
    # AI AND AUTOMATION
    # ========================================================

    ai_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    ai_summary: Mapped[str | None] = mapped_column(
        Text,
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

    model_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    model_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    ai_last_analyzed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # OPERATIONAL CONTROLS
    # ========================================================

    purchasing_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    automatic_replenishment_enabled: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    requires_manual_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    hold_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    suspension_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    termination_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    terminated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # AUDIT AND METADATA
    # ========================================================

    supplier_metadata: Mapped[
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
            "supplier_code": generate_supplier_code,
            "status": lambda: SupplierStatus.DRAFT,
            "supplier_type": lambda: SupplierType.DISTRIBUTOR,
            "tier": lambda: SupplierTier.STANDARD,
            "risk_level": lambda: SupplierRiskLevel.UNKNOWN,
            "verification_status": (
                lambda: SupplierVerificationStatus.NOT_STARTED
            ),
            "approval_status": (
                lambda: SupplierApprovalStatus.NOT_REQUIRED
            ),
            "payment_terms": lambda: SupplierPaymentTerms.NET_30,
            "currency": lambda: "INR",
            "minimum_order_value": lambda: Decimal("0"),
            "credit_limit": lambda: Decimal("0"),
            "total_purchase_value": lambda: Decimal("0"),
            "average_lead_time_days": lambda: 0,
            "total_orders": lambda: 0,
            "completed_orders": lambda: 0,
            "cancelled_orders": lambda: 0,
            "late_deliveries": lambda: 0,
            "purchasing_enabled": lambda: False,
            "automatic_replenishment_enabled": lambda: False,
            "requires_manual_approval": lambda: True,
            "requires_enhanced_monitoring": lambda: False,
            "ai_enabled": lambda: False,
            "is_deleted": lambda: False,
            "version": lambda: 1,
        }

        for field, factory in defaults.items():
            if getattr(self, field, None) is None:
                setattr(self, field, factory())

        for field in (
            "performance_metrics",
            "compliance_details",
            "supplier_metadata",
        ):
            if getattr(self, field, None) is None:
                setattr(self, field, {})

        for field in (
            "contacts",
            "service_regions",
            "shipping_methods",
            "supported_product_categories",
            "risk_factors",
            "risk_recommendations",
            "certifications",
            "document_references",
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
    def is_active(self) -> bool:
        return (
            self.status == SupplierStatus.ACTIVE
            and not self.is_deleted
        )

    @property
    def can_receive_orders(self) -> bool:
        return (
            self.is_active
            and self.purchasing_enabled
            and self.verification_status
            == SupplierVerificationStatus.VERIFIED
            and self.approval_status
            == SupplierApprovalStatus.APPROVED
        )

    @property
    def is_high_risk(self) -> bool:
        return self.risk_level in {
            SupplierRiskLevel.HIGH,
            SupplierRiskLevel.CRITICAL,
        }

    @property
    def is_contract_expired(self) -> bool:
        if self.contract_end_date is None:
            return False

        end_date = self.contract_end_date

        if end_date.tzinfo is None:
            end_date = end_date.replace(
                tzinfo=timezone.utc
            )

        return end_date <= utc_now()

    @property
    def order_completion_rate(self) -> Decimal | None:
        if not self.total_orders:
            return None

        return (
            Decimal(self.completed_orders or 0)
            / Decimal(self.total_orders)
        ).quantize(Decimal("0.0001"))

    # ========================================================
    # INTERNAL METHODS
    # ========================================================

    def _ensure_editable(self) -> None:
        if self.is_deleted:
            raise ValueError("Supplier is deleted")

        if self.status in {
            SupplierStatus.TERMINATED,
            SupplierStatus.ARCHIVED,
        }:
            raise ValueError(
                "Terminated or archived supplier cannot be modified"
            )

    def _record_event(
        self,
        event_type: SupplierEventType,
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

    def validate_supplier(self) -> None:
        required_text(
            self.organization_id,
            "Organization ID",
        )
        required_text(self.name, "Supplier name")
        required_text(
            self.supplier_code,
            "Supplier code",
        )

        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValueError(
                "Currency must be a three-letter code"
            )

        if self.minimum_order_quantity is not None:
            validate_nonnegative(
                self.minimum_order_quantity,
                "Minimum order quantity",
            )

        if self.year_established is not None:
            if (
                self.year_established < 1800
                or self.year_established > utc_now().year
            ):
                raise ValueError(
                    "Invalid establishment year"
                )

    # ========================================================
    # UPDATE PROFILE
    # ========================================================

    def update_profile(
        self,
        *,
        actor_id: str,
        name: str | None = None,
        legal_name: str | None = None,
        description: str | None = None,
        website: str | None = None,
        industry: str | None = None,
    ) -> None:
        self._ensure_editable()

        if name is not None:
            self.name = required_text(name, "Supplier name")

        if legal_name is not None:
            self.legal_name = optional_text(legal_name)

        if description is not None:
            self.description = optional_text(description)

        if website is not None:
            self.website = optional_text(website)

        if industry is not None:
            self.industry = optional_text(industry)

        self._record_event(
            SupplierEventType.UPDATED,
            actor_id=actor_id,
            details={"section": "profile"},
        )

    # ========================================================
    # ADD CONTACT
    # ========================================================

    def add_contact(
        self,
        *,
        actor_id: str,
        name: str,
        email: str | None = None,
        phone: str | None = None,
        designation: str | None = None,
        is_primary: bool = False,
    ) -> str:
        self._ensure_editable()

        contact_id = generate_uuid()

        contact = {
            "id": contact_id,
            "name": required_text(name, "Contact name"),
            "email": optional_text(email),
            "phone": optional_text(phone),
            "designation": optional_text(designation),
            "is_primary": bool(is_primary),
            "created_at": utc_now().isoformat(),
        }

        contacts = list(self.contacts or [])

        if is_primary:
            for existing in contacts:
                existing["is_primary"] = False

            self.primary_contact_name = contact["name"]
            self.primary_contact_email = contact["email"]
            self.primary_contact_phone = contact["phone"]

        contacts.append(contact)
        self.contacts = contacts

        self._record_event(
            SupplierEventType.CONTACT_ADDED,
            actor_id=actor_id,
            details={"contact_id": contact_id},
        )

        return contact_id

    # ========================================================
    # REQUEST VERIFICATION
    # ========================================================

    def request_verification(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        if self.status not in {
            SupplierStatus.DRAFT,
            SupplierStatus.PENDING_VERIFICATION,
        }:
            raise ValueError(
                "Supplier cannot enter verification"
            )

        self.validate_supplier()

        self.verification_status = (
            SupplierVerificationStatus.PENDING
        )
        self.status = SupplierStatus.PENDING_VERIFICATION

        self._record_event(
            SupplierEventType.VERIFICATION_REQUESTED,
            actor_id=actor_id,
        )

    # ========================================================
    # VERIFY
    # ========================================================

    def verify(
        self,
        *,
        verifier_id: str,
        notes: str | None = None,
    ) -> None:
        self._ensure_editable()

        if self.status != SupplierStatus.PENDING_VERIFICATION:
            raise ValueError(
                "Supplier is not pending verification"
            )

        self.verified_by = required_text(
            verifier_id,
            "Verifier ID",
        )

        self.verified_at = utc_now()
        self.verification_notes = optional_text(notes)

        self.verification_status = (
            SupplierVerificationStatus.VERIFIED
        )

        self.status = SupplierStatus.PENDING_APPROVAL
        self.approval_status = SupplierApprovalStatus.PENDING

        self._record_event(
            SupplierEventType.VERIFIED,
            actor_id=verifier_id,
        )

    # ========================================================
    # FAIL VERIFICATION
    # ========================================================

    def fail_verification(
        self,
        *,
        verifier_id: str,
        reason: str,
    ) -> None:
        self._ensure_editable()

        if self.status != SupplierStatus.PENDING_VERIFICATION:
            raise ValueError(
                "Supplier is not pending verification"
            )

        self.verification_status = (
            SupplierVerificationStatus.FAILED
        )
        self.verification_notes = required_text(
            reason,
            "Failure reason",
        )
        self.status = SupplierStatus.DRAFT

        self._record_event(
            SupplierEventType.VERIFICATION_FAILED,
            actor_id=verifier_id,
            details={"reason": reason},
        )

    # ========================================================
    # APPROVE
    # ========================================================

    def approve(
        self,
        *,
        approver_id: str,
    ) -> None:
        self._ensure_editable()

        if self.status != SupplierStatus.PENDING_APPROVAL:
            raise ValueError(
                "Supplier is not pending approval"
            )

        if self.verification_status != (
            SupplierVerificationStatus.VERIFIED
        ):
            raise ValueError(
                "Supplier verification is required"
            )

        self.approved_by = required_text(
            approver_id,
            "Approver ID",
        )

        self.approved_at = utc_now()
        self.approval_status = SupplierApprovalStatus.APPROVED
        self.status = SupplierStatus.APPROVED

        self._record_event(
            SupplierEventType.APPROVED,
            actor_id=approver_id,
        )

    # ========================================================
    # REJECT
    # ========================================================

    def reject(
        self,
        *,
        reviewer_id: str,
        reason: str,
    ) -> None:
        self._ensure_editable()

        if self.status != SupplierStatus.PENDING_APPROVAL:
            raise ValueError(
                "Supplier is not pending approval"
            )

        self.rejection_reason = required_text(
            reason,
            "Rejection reason",
        )

        self.approval_status = SupplierApprovalStatus.REJECTED
        self.status = SupplierStatus.DRAFT

        self._record_event(
            SupplierEventType.REJECTED,
            actor_id=reviewer_id,
            details={"reason": reason},
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

        if self.status not in {
            SupplierStatus.APPROVED,
            SupplierStatus.INACTIVE,
        }:
            raise ValueError(
                "Supplier cannot be activated"
            )

        if self.verification_status != (
            SupplierVerificationStatus.VERIFIED
        ):
            raise ValueError(
                "Supplier must be verified"
            )

        if self.approval_status != (
            SupplierApprovalStatus.APPROVED
        ):
            raise ValueError(
                "Supplier must be approved"
            )

        self.status = SupplierStatus.ACTIVE
        self.activated_at = utc_now()
        self.purchasing_enabled = True

        self._record_event(
            SupplierEventType.ACTIVATED,
            actor_id=actor_id,
        )

    # ========================================================
    # PUT ON HOLD
    # ========================================================

    def put_on_hold(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_editable()

        if self.status != SupplierStatus.ACTIVE:
            raise ValueError(
                "Only active suppliers can be put on hold"
            )

        self.hold_reason = required_text(
            reason,
            "Hold reason",
        )

        self.status = SupplierStatus.ON_HOLD
        self.purchasing_enabled = False

        self._record_event(
            SupplierEventType.PUT_ON_HOLD,
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

        if self.status not in {
            SupplierStatus.ACTIVE,
            SupplierStatus.ON_HOLD,
        }:
            raise ValueError(
                "Supplier cannot be suspended"
            )

        self.suspension_reason = required_text(
            reason,
            "Suspension reason",
        )

        self.status = SupplierStatus.SUSPENDED
        self.suspended_at = utc_now()
        self.purchasing_enabled = False
        self.automatic_replenishment_enabled = False

        self._record_event(
            SupplierEventType.SUSPENDED,
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # BLOCK
    # ========================================================

    def block(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_editable()

        self.suspension_reason = required_text(
            reason,
            "Blocking reason",
        )

        self.status = SupplierStatus.BLOCKED
        self.purchasing_enabled = False
        self.automatic_replenishment_enabled = False

        self._record_event(
            SupplierEventType.BLOCKED,
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

        if self.status not in {
            SupplierStatus.ON_HOLD,
            SupplierStatus.SUSPENDED,
            SupplierStatus.BLOCKED,
            SupplierStatus.INACTIVE,
        }:
            raise ValueError(
                "Supplier cannot be reactivated"
            )

        if self.verification_status != (
            SupplierVerificationStatus.VERIFIED
        ):
            raise ValueError(
                "Supplier must be verified"
            )

        if self.approval_status != (
            SupplierApprovalStatus.APPROVED
        ):
            raise ValueError(
                "Supplier must be approved"
            )

        self.status = SupplierStatus.ACTIVE
        self.purchasing_enabled = True
        self.hold_reason = None
        self.suspension_reason = None
        self.activated_at = utc_now()

        self._record_event(
            SupplierEventType.REACTIVATED,
            actor_id=actor_id,
        )

    # ========================================================
    # UPDATE PERFORMANCE
    # ========================================================

    def update_performance(
        self,
        *,
        actor_id: str,
        reliability_score: Any = None,
        quality_score: Any = None,
        delivery_score: Any = None,
        on_time_delivery_rate: Any = None,
        defect_rate: Any = None,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        self._ensure_editable()

        values = {
            "reliability_score": reliability_score,
            "quality_score": quality_score,
            "delivery_score": delivery_score,
            "on_time_delivery_rate": on_time_delivery_rate,
            "defect_rate": defect_rate,
        }

        for field, value in values.items():
            if value is not None:
                setattr(
                    self,
                    field,
                    validate_score(value, field),
                )

        if metrics is not None:
            if not isinstance(metrics, dict):
                raise ValueError(
                    "Performance metrics must be a dictionary"
                )

            self.performance_metrics = json_safe(metrics)

        self._record_event(
            SupplierEventType.PERFORMANCE_UPDATED,
            actor_id=actor_id,
        )

    # ========================================================
    # UPDATE RISK
    # ========================================================

    def update_risk(
        self,
        *,
        actor_id: str,
        score: Any,
        assessment_id: str | None = None,
        factors: list[dict[str, Any]] | None = None,
        recommendations: list[dict[str, Any]] | None = None,
    ) -> None:
        self._ensure_editable()

        risk_score = validate_score(
            score,
            "Supplier risk score",
        )

        self.risk_score = risk_score

        if risk_score >= Decimal("0.8500"):
            self.risk_level = SupplierRiskLevel.CRITICAL
        elif risk_score >= Decimal("0.6500"):
            self.risk_level = SupplierRiskLevel.HIGH
        elif risk_score >= Decimal("0.3500"):
            self.risk_level = SupplierRiskLevel.MEDIUM
        else:
            self.risk_level = SupplierRiskLevel.LOW

        self.requires_enhanced_monitoring = self.is_high_risk

        if assessment_id is not None:
            self.latest_risk_assessment_id = required_text(
                assessment_id,
                "Assessment ID",
            )

        if factors is not None:
            self.risk_factors = json_safe(factors)

        if recommendations is not None:
            self.risk_recommendations = json_safe(
                recommendations
            )

        self.risk_assessed_at = utc_now()

        self._record_event(
            SupplierEventType.RISK_UPDATED,
            actor_id=actor_id,
            details={
                "risk_score": str(self.risk_score),
                "risk_level": self.risk_level.value,
            },
        )

    # ========================================================
    # LINK CONTRACT
    # ========================================================

    def link_contract(
        self,
        *,
        actor_id: str,
        contract_id: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> None:
        self._ensure_editable()

        if start_date is not None and end_date is not None:
            if end_date <= start_date:
                raise ValueError(
                    "Contract end date must be after start date"
                )

        self.active_contract_id = required_text(
            contract_id,
            "Contract ID",
        )

        self.contract_start_date = start_date
        self.contract_end_date = end_date

        self._record_event(
            SupplierEventType.CONTRACT_LINKED,
            actor_id=actor_id,
            details={"contract_id": contract_id},
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
        filename: str | None = None,
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
            "filename": optional_text(filename),
            "added_at": utc_now().isoformat(),
        }

        documents = list(self.document_references or [])
        documents.append(document)

        self.document_references = documents

        self._record_event(
            SupplierEventType.DOCUMENT_ADDED,
            actor_id=actor_id,
            details=document,
        )

    # ========================================================
    # DEACTIVATE
    # ========================================================

    def deactivate(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_editable()

        if self.status not in {
            SupplierStatus.ACTIVE,
            SupplierStatus.ON_HOLD,
            SupplierStatus.SUSPENDED,
            SupplierStatus.BLOCKED,
        }:
            raise ValueError(
                "Supplier cannot be deactivated"
            )

        self.status = SupplierStatus.INACTIVE
        self.purchasing_enabled = False
        self.automatic_replenishment_enabled = False

        self._record_event(
            SupplierEventType.DEACTIVATED,
            actor_id=actor_id,
            details={
                "reason": required_text(
                    reason,
                    "Deactivation reason",
                )
            },
        )

    # ========================================================
    # TERMINATE
    # ========================================================

    def terminate(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_editable()

        self.termination_reason = required_text(
            reason,
            "Termination reason",
        )

        self.status = SupplierStatus.TERMINATED
        self.terminated_at = utc_now()
        self.purchasing_enabled = False
        self.automatic_replenishment_enabled = False

        self._record_event(
            SupplierEventType.TERMINATED,
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
            raise ValueError("Supplier is deleted")

        if self.status not in {
            SupplierStatus.INACTIVE,
            SupplierStatus.TERMINATED,
        }:
            raise ValueError(
                "Supplier must be inactive or terminated"
            )

        self.status = SupplierStatus.ARCHIVED
        self.archived_at = utc_now()
        self.purchasing_enabled = False
        self.automatic_replenishment_enabled = False

        self._record_event(
            SupplierEventType.ARCHIVED,
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
            raise ValueError(
                "Supplier already deleted"
            )

        if self.status not in {
            SupplierStatus.DRAFT,
            SupplierStatus.ARCHIVED,
        }:
            raise ValueError(
                "Only draft or archived suppliers "
                "can be deleted"
            )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = required_text(
            actor_id,
            "Actor ID",
        )

        self._record_event(
            SupplierEventType.SOFT_DELETED,
            actor_id=actor_id,
        )

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(
        self,
        *,
        include_sensitive: bool = False,
        include_history: bool = False,
    ) -> dict[str, Any]:

        data = {
            "id": self.id,
            "organization_id": self.organization_id,
            "supplier_code": self.supplier_code,
            "name": self.name,
            "legal_name": self.legal_name,
            "description": self.description,
            "supplier_type": enum_value(
                self.supplier_type
            ),
            "status": enum_value(self.status),
            "tier": enum_value(self.tier),
            "industry": self.industry,
            "business_category": self.business_category,
            "website": self.website,
            "primary_contact_name": (
                self.primary_contact_name
            ),
            "primary_contact_email": (
                self.primary_contact_email
            ),
            "primary_contact_phone": (
                self.primary_contact_phone
            ),
            "city": self.city,
            "state": self.state,
            "country": self.country,
            "postal_code": self.postal_code,
            "service_regions": self.service_regions,
            "currency": self.currency,
            "payment_terms": enum_value(
                self.payment_terms
            ),
            "minimum_order_value": serialize(
                self.minimum_order_value
            ),
            "minimum_order_quantity": serialize(
                self.minimum_order_quantity
            ),
            "average_lead_time_days": (
                self.average_lead_time_days
            ),
            "credit_limit": serialize(self.credit_limit),
            "reliability_score": serialize(
                self.reliability_score
            ),
            "quality_score": serialize(self.quality_score),
            "delivery_score": serialize(
                self.delivery_score
            ),
            "on_time_delivery_rate": serialize(
                self.on_time_delivery_rate
            ),
            "defect_rate": serialize(self.defect_rate),
            "total_orders": self.total_orders,
            "completed_orders": self.completed_orders,
            "cancelled_orders": self.cancelled_orders,
            "total_purchase_value": serialize(
                self.total_purchase_value
            ),
            "risk_level": enum_value(self.risk_level),
            "risk_score": serialize(self.risk_score),
            "latest_risk_assessment_id": (
                self.latest_risk_assessment_id
            ),
            "verification_status": enum_value(
                self.verification_status
            ),
            "approval_status": enum_value(
                self.approval_status
            ),
            "active_contract_id": self.active_contract_id,
            "contract_start_date": serialize(
                self.contract_start_date
            ),
            "contract_end_date": serialize(
                self.contract_end_date
            ),
            "is_contract_expired": (
                self.is_contract_expired
            ),
            "purchasing_enabled": self.purchasing_enabled,
            "automatic_replenishment_enabled": (
                self.automatic_replenishment_enabled
            ),
            "requires_manual_approval": (
                self.requires_manual_approval
            ),
            "requires_enhanced_monitoring": (
                self.requires_enhanced_monitoring
            ),
            "is_active": self.is_active,
            "can_receive_orders": self.can_receive_orders,
            "is_high_risk": self.is_high_risk,
            "order_completion_rate": serialize(
                self.order_completion_rate
            ),
            "tags": self.tags,
            "created_at": serialize(self.created_at),
            "updated_at": serialize(self.updated_at),
            "version": self.version,
        }

        if include_sensitive:
            data.update({
                "registration_number": (
                    self.registration_number
                ),
                "tax_identification_number": (
                    self.tax_identification_number
                ),
                "gst_number": self.gst_number,
                "pan_number": self.pan_number,
                "address_line_1": self.address_line_1,
                "address_line_2": self.address_line_2,
                "contacts": self.contacts,
                "certifications": self.certifications,
                "document_references": (
                    self.document_references
                ),
                "compliance_details": self.compliance_details,
                "performance_metrics": (
                    self.performance_metrics
                ),
                "risk_factors": self.risk_factors,
                "risk_recommendations": (
                    self.risk_recommendations
                ),
                "supplier_metadata": self.supplier_metadata,
                "approval_request_id": (
                    self.approval_request_id
                ),
                "verified_by": self.verified_by,
                "approved_by": self.approved_by,
                "verification_notes": self.verification_notes,
                "rejection_reason": self.rejection_reason,
                "hold_reason": self.hold_reason,
                "suspension_reason": self.suspension_reason,
                "termination_reason": self.termination_reason,
                "created_by": self.created_by,
                "updated_by": self.updated_by,
                "is_deleted": self.is_deleted,
                "deleted_at": serialize(self.deleted_at),
                "deleted_by": self.deleted_by,
            })

        if include_history:
            data["event_history"] = self.event_history

        return data

    def __repr__(self) -> str:
        return (
            f"<Supplier("
            f"id={self.id!r}, "
            f"code={self.supplier_code!r}, "
            f"name={self.name!r}, "
            f"status={enum_value(self.status)!r}"
            f")>"
        )