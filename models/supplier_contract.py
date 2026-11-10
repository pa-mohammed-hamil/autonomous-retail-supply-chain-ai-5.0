from __future__ import annotations

"""Planned module: supplier contract. Implementation pending."""
# backend/models/supplier_contract.py


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
# CONSTANTS
# ============================================================

ZERO = Decimal("0.0000")
ONE = Decimal("1.0000")
MAX_MONEY = Decimal("9999999999999999.9999")
MAX_QUANTITY = Decimal("99999999999999.9999")


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_contract_number() -> str:
    return f"SC-{uuid.uuid4().hex[:16].upper()}"


def generate_amendment_number() -> str:
    return f"AMD-{uuid.uuid4().hex[:14].upper()}"


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


def money(
    value: Decimal | str | int | float,
    field: str,
) -> Decimal:
    return nonnegative_decimal(
        value,
        field,
        maximum=MAX_MONEY,
    )


def nonnegative_decimal(
    value: Decimal | str | int | float,
    field: str,
    *,
    maximum: Decimal = MAX_QUANTITY,
) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")

    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{field} must be numeric") from None

    if not result.is_finite():
        raise ValueError(f"{field} must be finite")

    if result < ZERO or result > maximum:
        raise ValueError(
            f"{field} must be between 0 and {maximum}"
        )

    if result != result.quantize(Decimal("0.0001")):
        raise ValueError(
            f"{field} supports at most four decimal places"
        )

    return result


def percentage(
    value: Decimal | str | int | float,
    field: str,
) -> Decimal:
    return nonnegative_decimal(
        value,
        field,
        maximum=ONE,
    )


def ensure_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("Expected datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            "Timezone-aware datetime is required"
        )

    return value.astimezone(timezone.utc)


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value

    if isinstance(value, (float, Decimal)):
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError("Non-finite JSON numeric value")
        return str(result)

    if isinstance(value, datetime):
        return ensure_datetime(value).isoformat()

    if isinstance(value, enum.Enum):
        return value.value

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

class SupplierContractStatus(str, enum.Enum):
    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    PENDING_SIGNATURE = "pending_signature"
    SIGNED = "signed"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    RENEWAL_PENDING = "renewal_pending"
    EXPIRED = "expired"
    TERMINATED = "terminated"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class SupplierContractType(str, enum.Enum):
    MASTER_SUPPLY_AGREEMENT = "master_supply_agreement"
    PURCHASE_AGREEMENT = "purchase_agreement"
    FRAMEWORK_AGREEMENT = "framework_agreement"
    SERVICE_LEVEL_AGREEMENT = "service_level_agreement"
    DISTRIBUTION_AGREEMENT = "distribution_agreement"
    LOGISTICS_AGREEMENT = "logistics_agreement"
    PROCUREMENT_AGREEMENT = "procurement_agreement"
    EXCLUSIVE_SUPPLY = "exclusive_supply"
    NON_EXCLUSIVE_SUPPLY = "non_exclusive_supply"
    CONSIGNMENT = "consignment"
    RATE_CONTRACT = "rate_contract"
    QUALITY_AGREEMENT = "quality_agreement"
    MAINTENANCE_AGREEMENT = "maintenance_agreement"
    OTHER = "other"


class SupplierContractPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"


class SupplierContractRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class SupplierContractApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SupplierContractSignatureStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    PENDING = "pending"
    PARTIALLY_SIGNED = "partially_signed"
    COMPLETED = "completed"
    DECLINED = "declined"
    EXPIRED = "expired"
    FAILED = "failed"


class SupplierContractPaymentTerms(str, enum.Enum):
    ADVANCE = "advance"
    PREPAID = "prepaid"
    CASH_ON_DELIVERY = "cash_on_delivery"
    NET_7 = "net_7"
    NET_15 = "net_15"
    NET_30 = "net_30"
    NET_45 = "net_45"
    NET_60 = "net_60"
    NET_90 = "net_90"
    MILESTONE = "milestone"
    CUSTOM = "custom"


class SupplierContractPricingType(str, enum.Enum):
    FIXED = "fixed"
    VARIABLE = "variable"
    TIERED = "tiered"
    VOLUME_BASED = "volume_based"
    INDEX_LINKED = "index_linked"
    COST_PLUS = "cost_plus"
    DYNAMIC = "dynamic"
    CUSTOM = "custom"


class SupplierContractRenewalType(str, enum.Enum):
    MANUAL = "manual"
    AUTOMATIC = "automatic"
    NON_RENEWABLE = "non_renewable"


class SupplierContractComplianceStatus(str, enum.Enum):
    NOT_EVALUATED = "not_evaluated"
    COMPLIANT = "compliant"
    PARTIALLY_COMPLIANT = "partially_compliant"
    NON_COMPLIANT = "non_compliant"
    REVIEW_REQUIRED = "review_required"


class SupplierContractAmendmentStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SIGNED = "signed"
    EFFECTIVE = "effective"
    CANCELLED = "cancelled"


class SupplierContractObligationStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    OVERDUE = "overdue"
    WAIVED = "waived"
    CANCELLED = "cancelled"


class SupplierContractObligationType(str, enum.Enum):
    DELIVERY = "delivery"
    PAYMENT = "payment"
    QUALITY = "quality"
    COMPLIANCE = "compliance"
    DOCUMENTATION = "documentation"
    INSPECTION = "inspection"
    REPORTING = "reporting"
    INSURANCE = "insurance"
    SECURITY = "security"
    CONFIDENTIALITY = "confidentiality"
    OTHER = "other"


class SupplierContractEventType(str, enum.Enum):
    CREATED = "created"
    UPDATED = "updated"
    REVIEW_REQUESTED = "review_requested"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    SIGNATURE_REQUESTED = "signature_requested"
    SIGNED = "signed"
    ACTIVATED = "activated"
    SUSPENDED = "suspended"
    RESUMED = "resumed"
    RENEWAL_REQUESTED = "renewal_requested"
    RENEWED = "renewed"
    EXPIRED = "expired"
    TERMINATED = "terminated"
    CANCELLED = "cancelled"
    RISK_UPDATED = "risk_updated"
    COMPLIANCE_UPDATED = "compliance_updated"
    OBLIGATION_ADDED = "obligation_added"
    AMENDMENT_ADDED = "amendment_added"
    AMENDMENT_APPLIED = "amendment_applied"
    ARCHIVED = "archived"
    SOFT_DELETED = "soft_deleted"


# ============================================================
# SUPPLIER CONTRACT
# ============================================================

class SupplierContract(Base):
    __tablename__ = "supplier_contracts"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "contract_number",
            name="uq_supplier_contract_org_number",
        ),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_supplier_contract_org_id",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_supplier_contract_org_idempotency",
        ),
        CheckConstraint(
            "contract_value >= 0",
            name="ck_supplier_contract_value",
        ),
        CheckConstraint(
            "minimum_order_value >= 0",
            name="ck_supplier_contract_min_order_value",
        ),
        CheckConstraint(
            "maximum_order_value IS NULL OR "
            "maximum_order_value >= minimum_order_value",
            name="ck_supplier_contract_max_order_value",
        ),
        CheckConstraint(
            "annual_commitment_value >= 0",
            name="ck_supplier_contract_annual_commitment",
        ),
        CheckConstraint(
            "minimum_order_quantity >= 0",
            name="ck_supplier_contract_min_order_qty",
        ),
        CheckConstraint(
            "maximum_order_quantity IS NULL OR "
            "maximum_order_quantity >= minimum_order_quantity",
            name="ck_supplier_contract_max_order_qty",
        ),
        CheckConstraint(
            "lead_time_days >= 0",
            name="ck_supplier_contract_lead_time",
        ),
        CheckConstraint(
            "payment_due_days >= 0",
            name="ck_supplier_contract_payment_due",
        ),
        CheckConstraint(
            "renewal_notice_days >= 0",
            name="ck_supplier_contract_renewal_notice",
        ),
        CheckConstraint(
            "termination_notice_days >= 0",
            name="ck_supplier_contract_termination_notice",
        ),
        CheckConstraint(
            "penalty_rate >= 0 AND penalty_rate <= 1",
            name="ck_supplier_contract_penalty_rate",
        ),
        CheckConstraint(
            "discount_rate >= 0 AND discount_rate <= 1",
            name="ck_supplier_contract_discount_rate",
        ),
        CheckConstraint(
            "tax_rate >= 0 AND tax_rate <= 1",
            name="ck_supplier_contract_tax_rate",
        ),
        CheckConstraint(
            "risk_score IS NULL OR "
            "(risk_score >= 0 AND risk_score <= 1)",
            name="ck_supplier_contract_risk_score",
        ),
        CheckConstraint(
            "compliance_score IS NULL OR "
            "(compliance_score >= 0 AND compliance_score <= 1)",
            name="ck_supplier_contract_compliance_score",
        ),
        CheckConstraint(
            "on_time_delivery_target IS NULL OR "
            "(on_time_delivery_target >= 0 AND "
            "on_time_delivery_target <= 1)",
            name="ck_supplier_contract_delivery_target",
        ),
        CheckConstraint(
            "quality_acceptance_target IS NULL OR "
            "(quality_acceptance_target >= 0 AND "
            "quality_acceptance_target <= 1)",
            name="ck_supplier_contract_quality_target",
        ),
        CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR "
            "end_date > start_date",
            name="ck_supplier_contract_date_range",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_supplier_contract_version",
        ),
        Index(
            "ix_supplier_contract_org_supplier",
            "organization_id",
            "supplier_id",
        ),
        Index(
            "ix_supplier_contract_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_supplier_contract_org_type",
            "organization_id",
            "contract_type",
        ),
        Index(
            "ix_supplier_contract_org_end_date",
            "organization_id",
            "end_date",
        ),
        Index(
            "ix_supplier_contract_org_risk",
            "organization_id",
            "risk_level",
        ),
        Index(
            "ix_supplier_contract_org_renewal",
            "organization_id",
            "next_renewal_at",
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

    contract_number: Mapped[str] = mapped_column(
        String(60),
        default=generate_contract_number,
        nullable=False,
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
    # CLASSIFICATION
    # ========================================================

    contract_type: Mapped[SupplierContractType] = mapped_column(
        enum_type(
            SupplierContractType,
            "supplier_contract_type",
        ),
        default=SupplierContractType.PURCHASE_AGREEMENT,
        nullable=False,
    )

    status: Mapped[SupplierContractStatus] = mapped_column(
        enum_type(
            SupplierContractStatus,
            "supplier_contract_status",
        ),
        default=SupplierContractStatus.DRAFT,
        nullable=False,
    )

    priority: Mapped[SupplierContractPriority] = mapped_column(
        enum_type(
            SupplierContractPriority,
            "supplier_contract_priority",
        ),
        default=SupplierContractPriority.NORMAL,
        nullable=False,
    )

    # ========================================================
    # BUSINESS REFERENCES
    # ========================================================

    supplier_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    warehouse_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    store_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    category_id: Mapped[str | None] = mapped_column(
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

    supplier_risk_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    document_id: Mapped[str | None] = mapped_column(
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

    parent_contract_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    external_contract_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    # ========================================================
    # CONTRACT PARTIES
    # ========================================================

    buyer_legal_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    supplier_legal_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    buyer_contact_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    supplier_contact_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    contract_owner_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    procurement_manager_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    legal_reviewer_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # ========================================================
    # CONTRACT DATES
    # ========================================================

    start_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    end_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    effective_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    signed_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    next_renewal_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    renewal_notice_days: Mapped[int] = mapped_column(
        Integer,
        default=30,
        nullable=False,
    )

    termination_notice_days: Mapped[int] = mapped_column(
        Integer,
        default=30,
        nullable=False,
    )

    renewal_type: Mapped[SupplierContractRenewalType] = (
        mapped_column(
            enum_type(
                SupplierContractRenewalType,
                "supplier_contract_renewal_type",
            ),
            default=SupplierContractRenewalType.MANUAL,
            nullable=False,
        )
    )

    auto_renewal_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    renewal_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # ========================================================
    # FINANCIAL TERMS
    # ========================================================

    currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    contract_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    annual_commitment_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    minimum_order_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    maximum_order_value: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 4),
        nullable=True,
    )

    minimum_order_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    maximum_order_quantity: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    pricing_type: Mapped[SupplierContractPricingType] = (
        mapped_column(
            enum_type(
                SupplierContractPricingType,
                "supplier_contract_pricing_type",
            ),
            default=SupplierContractPricingType.FIXED,
            nullable=False,
        )
    )

    payment_terms: Mapped[SupplierContractPaymentTerms] = (
        mapped_column(
            enum_type(
                SupplierContractPaymentTerms,
                "supplier_contract_payment_terms",
            ),
            default=SupplierContractPaymentTerms.NET_30,
            nullable=False,
        )
    )

    payment_due_days: Mapped[int] = mapped_column(
        Integer,
        default=30,
        nullable=False,
    )

    discount_rate: Mapped[Decimal] = mapped_column(
        Numeric(6, 4),
        default=ZERO,
        nullable=False,
    )

    penalty_rate: Mapped[Decimal] = mapped_column(
        Numeric(6, 4),
        default=ZERO,
        nullable=False,
    )

    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(6, 4),
        default=ZERO,
        nullable=False,
    )

    pricing_details: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    payment_details: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    penalty_details: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # ========================================================
    # DELIVERY / SUPPLY TERMS
    # ========================================================

    lead_time_days: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    delivery_frequency: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    delivery_location: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    incoterms: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    shipping_terms: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    return_terms: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    warranty_terms: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    on_time_delivery_target: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    quality_acceptance_target: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    service_level_details: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # ========================================================
    # LEGAL TERMS
    # ========================================================

    governing_law: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    jurisdiction: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    confidentiality_clause: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    termination_clause: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    liability_clause: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    force_majeure_clause: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    dispute_resolution_clause: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    legal_terms: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # ========================================================
    # AI CONTRACT INTELLIGENCE
    # ========================================================

    risk_level: Mapped[SupplierContractRiskLevel] = (
        mapped_column(
            enum_type(
                SupplierContractRiskLevel,
                "supplier_contract_risk_level",
            ),
            default=SupplierContractRiskLevel.UNKNOWN,
            nullable=False,
        )
    )

    risk_score: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    ai_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    ai_risk_explanation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    ai_extracted_clauses: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    ai_risk_factors: Mapped[
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

    ai_model_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    ai_model_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    ai_analyzed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    requires_human_review: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # ========================================================
    # COMPLIANCE
    # ========================================================

    compliance_status: Mapped[
        SupplierContractComplianceStatus
    ] = mapped_column(
        enum_type(
            SupplierContractComplianceStatus,
            "supplier_contract_compliance_status",
        ),
        default=SupplierContractComplianceStatus.NOT_EVALUATED,
        nullable=False,
    )

    compliance_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    compliance_findings: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    compliance_checked_by: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    compliance_checked_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # APPROVAL
    # ========================================================

    approval_status: Mapped[
        SupplierContractApprovalStatus
    ] = mapped_column(
        enum_type(
            SupplierContractApprovalStatus,
            "supplier_contract_approval_status",
        ),
        default=SupplierContractApprovalStatus.NOT_REQUIRED,
        nullable=False,
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
    # SIGNATURE
    # ========================================================

    signature_status: Mapped[
        SupplierContractSignatureStatus
    ] = mapped_column(
        enum_type(
            SupplierContractSignatureStatus,
            "supplier_contract_signature_status",
        ),
        default=SupplierContractSignatureStatus.NOT_STARTED,
        nullable=False,
    )

    signature_provider: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    signature_envelope_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    signature_requested_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    buyer_signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    supplier_signed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    signed_document_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    signature_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # ========================================================
    # LIFECYCLE
    # ========================================================

    submitted_for_review_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
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

    suspension_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    renewal_requested_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    renewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    expired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    terminated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    terminated_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    termination_reason: Mapped[str | None] = mapped_column(
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

    contract_metadata: Mapped[
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

    items: Mapped[list["SupplierContractItem"]] = relationship(
        "SupplierContractItem",
        back_populates="contract",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    obligations: Mapped[
        list["SupplierContractObligation"]
    ] = relationship(
        "SupplierContractObligation",
        back_populates="contract",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    amendments: Mapped[
        list["SupplierContractAmendment"]
    ] = relationship(
        "SupplierContractAmendment",
        back_populates="contract",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    events: Mapped[list["SupplierContractEvent"]] = relationship(
        "SupplierContractEvent",
        back_populates="contract",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="SupplierContractEvent.created_at",
    )

    # ========================================================
    # COMPUTED PROPERTIES
    # ========================================================

    @property
    def is_active(self) -> bool:
        return (
            self.status == SupplierContractStatus.ACTIVE
            and not bool(self.is_deleted)
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            SupplierContractStatus.EXPIRED,
            SupplierContractStatus.TERMINATED,
            SupplierContractStatus.CANCELLED,
            SupplierContractStatus.ARCHIVED,
        }

    @property
    def is_signed(self) -> bool:
        return (
            self.signature_status
            == SupplierContractSignatureStatus.COMPLETED
        )

    @property
    def is_expired(self) -> bool:
        return (
            self.end_date is not None
            and ensure_datetime(self.end_date) <= utc_now()
        )

    @property
    def is_high_risk(self) -> bool:
        return self.risk_level in {
            SupplierContractRiskLevel.HIGH,
            SupplierContractRiskLevel.CRITICAL,
        }

    @property
    def requires_renewal(self) -> bool:
        if self.end_date is None:
            return False

        if self.renewal_type == (
            SupplierContractRenewalType.NON_RENEWABLE
        ):
            return False

        remaining = (
            ensure_datetime(self.end_date) - utc_now()
        ).total_seconds()

        return remaining <= (
            (self.renewal_notice_days or 0) * 86400
        )

    @property
    def total_item_value(self) -> Decimal:
        return sum(
            (item.total_value for item in self.items),
            ZERO,
        )

    @property
    def open_obligation_count(self) -> int:
        return sum(
            1
            for obligation in self.obligations
            if obligation.status in {
                SupplierContractObligationStatus.OPEN,
                SupplierContractObligationStatus.IN_PROGRESS,
                SupplierContractObligationStatus.OVERDUE,
            }
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _ensure_editable(self) -> None:
        if self.is_deleted:
            raise ValueError("Contract has been deleted")

        if self.is_terminal:
            raise ValueError(
                "Terminal contract cannot be modified"
            )

    def _require_status(
        self,
        *statuses: SupplierContractStatus,
    ) -> None:
        self._ensure_editable()

        if self.status not in statuses:
            raise ValueError(
                "Invalid contract status: "
                f"{enum_value(self.status)}"
            )

    def _record_event(
        self,
        event_type: SupplierContractEventType,
        *,
        actor_id: str | None = None,
        details: dict[str, Any] | None = None,
        description: str | None = None,
    ) -> None:
        self.events.append(
            SupplierContractEvent(
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

    def validate_contract(self) -> None:
        required_string(
            self.organization_id,
            "Organization ID",
        )
        required_string(self.supplier_id, "Supplier ID")
        required_string(self.title, "Contract title")

        if self.start_date is None:
            raise ValueError("Contract start date required")

        if self.end_date is None:
            raise ValueError("Contract end date required")

        start = ensure_datetime(self.start_date)
        end = ensure_datetime(self.end_date)

        if end <= start:
            raise ValueError(
                "Contract end date must follow start date"
            )

        if self.maximum_order_value is not None:
            if (
                self.maximum_order_value
                < (self.minimum_order_value or ZERO)
            ):
                raise ValueError(
                    "Maximum order value is below minimum"
                )

        if self.maximum_order_quantity is not None:
            if (
                self.maximum_order_quantity
                < (self.minimum_order_quantity or ZERO)
            ):
                raise ValueError(
                    "Maximum order quantity is below minimum"
                )

    # ========================================================
    # ADD CONTRACT ITEM
    # ========================================================

    def add_item(
        self,
        *,
        actor_id: str,
        product_id: str,
        quantity: Decimal | str | float,
        unit_price: Decimal | str | float,
        product_name: str | None = None,
        sku: str | None = None,
        unit_of_measure: str = "unit",
        discount_rate: Decimal | str | float = ZERO,
        tax_rate: Decimal | str | float = ZERO,
    ) -> "SupplierContractItem":
        self._require_status(
            SupplierContractStatus.DRAFT
        )

        product_id = required_string(
            product_id,
            "Product ID",
        )
        quantity_value = nonnegative_decimal(
            quantity,
            "Quantity",
        )
        price_value = money(unit_price)
        discount_value = percentage(
            discount_rate,
            "Discount rate",
        )
        tax_value = percentage(
            tax_rate,
            "Tax rate",
        )

        if quantity_value <= ZERO:
            raise ValueError("Quantity must be positive")

        if any(
            item.product_id == product_id
            for item in self.items
        ):
            raise ValueError(
                "Product already exists in contract"
            )

        item = SupplierContractItem(
            id=generate_uuid(),
            organization_id=self.organization_id,
            product_id=product_id,
            product_name=optional_string(product_name),
            sku=optional_string(sku),
            quantity=quantity_value,
            unit_price=price_value,
            unit_of_measure=required_string(
                unit_of_measure,
                "Unit of measure",
            ),
            discount_rate=discount_value,
            tax_rate=tax_value,
        )

        self.items.append(item)

        self._record_event(
            SupplierContractEventType.UPDATED,
            actor_id=actor_id,
            details={
                "action": "item_added",
                "product_id": product_id,
                "quantity": str(quantity_value),
            },
        )

        return item

    # ========================================================
    # ADD OBLIGATION
    # ========================================================

    def add_obligation(
        self,
        *,
        actor_id: str,
        title: str,
        obligation_type: SupplierContractObligationType,
        due_at: datetime,
        description: str | None = None,
        assigned_to: str | None = None,
        requires_evidence: bool = False,
    ) -> "SupplierContractObligation":
        self._ensure_editable()

        if not isinstance(
            obligation_type,
            SupplierContractObligationType,
        ):
            raise ValueError("Invalid obligation type")

        obligation = SupplierContractObligation(
            id=generate_uuid(),
            organization_id=self.organization_id,
            title=required_string(
                title,
                "Obligation title",
            ),
            obligation_type=obligation_type,
            description=optional_string(description),
            due_at=ensure_datetime(due_at),
            assigned_to=assigned_to,
            requires_evidence=requires_evidence,
            status=SupplierContractObligationStatus.OPEN,
        )

        self.obligations.append(obligation)

        self._record_event(
            SupplierContractEventType.OBLIGATION_ADDED,
            actor_id=actor_id,
            details={
                "obligation_id": obligation.id,
                "title": obligation.title,
            },
        )

        return obligation

    # ========================================================
    # SUBMIT FOR REVIEW
    # ========================================================

    def submit_for_review(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            SupplierContractStatus.DRAFT
        )

        self.validate_contract()

        if not self.items:
            raise ValueError(
                "Contract must contain at least one item"
            )

        self.status = SupplierContractStatus.UNDER_REVIEW
        self.submitted_for_review_at = utc_now()

        self._record_event(
            SupplierContractEventType.REVIEW_REQUESTED,
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
            SupplierContractStatus.UNDER_REVIEW
        )

        self.approval_request_id = required_string(
            approval_request_id,
            "Approval request ID",
        )

        self.approval_status = (
            SupplierContractApprovalStatus.PENDING
        )
        self.status = SupplierContractStatus.PENDING_APPROVAL

        self._record_event(
            SupplierContractEventType.APPROVAL_REQUESTED,
            actor_id=actor_id,
            details={
                "approval_request_id": (
                    self.approval_request_id
                ),
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
            SupplierContractStatus.PENDING_APPROVAL
        )

        approver_id = required_string(
            approver_id,
            "Approver ID",
        )

        # Verify approval permissions and external approval
        # request state in the service layer.

        self.approval_status = (
            SupplierContractApprovalStatus.APPROVED
        )
        self.approved_by = approver_id
        self.approved_at = utc_now()
        self.status = SupplierContractStatus.APPROVED

        self._record_event(
            SupplierContractEventType.APPROVED,
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
            SupplierContractStatus.PENDING_APPROVAL
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
        self.approval_status = (
            SupplierContractApprovalStatus.REJECTED
        )
        self.status = SupplierContractStatus.REJECTED

        self._record_event(
            SupplierContractEventType.REJECTED,
            actor_id=approver_id,
            details={"reason": self.rejection_reason},
        )

    # ========================================================
    # REQUEST SIGNATURE
    # ========================================================

    def request_signature(
        self,
        *,
        actor_id: str,
        signature_provider: str,
        signature_envelope_id: str,
    ) -> None:
        self._require_status(
            SupplierContractStatus.APPROVED
        )

        self.signature_provider = required_string(
            signature_provider,
            "Signature provider",
        )
        self.signature_envelope_id = required_string(
            signature_envelope_id,
            "Signature envelope ID",
        )
        self.signature_status = (
            SupplierContractSignatureStatus.PENDING
        )
        self.signature_requested_at = utc_now()
        self.status = SupplierContractStatus.PENDING_SIGNATURE

        self._record_event(
            SupplierContractEventType.SIGNATURE_REQUESTED,
            actor_id=actor_id,
            details={
                "signature_provider": (
                    self.signature_provider
                ),
                "signature_envelope_id": (
                    self.signature_envelope_id
                ),
            },
        )

    # ========================================================
    # RECORD VERIFIED SIGNATURE
    # ========================================================

    def record_signature(
        self,
        *,
        actor_id: str,
        buyer_signed_at: datetime,
        supplier_signed_at: datetime,
        signed_document_id: str,
        verification_metadata: dict[str, Any] | None = None,
    ) -> None:
        self._require_status(
            SupplierContractStatus.PENDING_SIGNATURE
        )

        buyer_at = ensure_datetime(buyer_signed_at)
        supplier_at = ensure_datetime(supplier_signed_at)
        document_id = required_string(
            signed_document_id,
            "Signed document ID",
        )

        # Only call after signature provider verification.
        # The ORM does not independently verify signatures.

        self.buyer_signed_at = buyer_at
        self.supplier_signed_at = supplier_at
        self.signed_date = max(buyer_at, supplier_at)
        self.signed_document_id = document_id
        self.signature_metadata = json_safe(
            verification_metadata or {}
        )
        self.signature_status = (
            SupplierContractSignatureStatus.COMPLETED
        )
        self.status = SupplierContractStatus.SIGNED

        self._record_event(
            SupplierContractEventType.SIGNED,
            actor_id=actor_id,
            details={
                "signed_document_id": document_id,
            },
        )

    # ========================================================
    # ACTIVATE
    # ========================================================

    def activate(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            SupplierContractStatus.SIGNED
        )

        self.validate_contract()

        if not self.is_signed:
            raise ValueError(
                "Contract must be signed before activation"
            )

        if self.is_expired:
            raise ValueError(
                "Expired contract cannot be activated"
            )

        if (
            self.effective_date is not None
            and ensure_datetime(self.effective_date) > utc_now()
        ):
            raise ValueError(
                "Contract effective date has not arrived"
            )

        self.status = SupplierContractStatus.ACTIVE
        self.activated_at = utc_now()

        self._record_event(
            SupplierContractEventType.ACTIVATED,
            actor_id=actor_id,
        )

    # ========================================================
    # UPDATE AI RISK
    # ========================================================

    def update_ai_risk(
        self,
        *,
        actor_id: str,
        risk_level: SupplierContractRiskLevel,
        risk_score: Decimal | str | float,
        summary: str | None = None,
        explanation: str | None = None,
        extracted_clauses: list[dict[str, Any]] | None = None,
        risk_factors: list[dict[str, Any]] | None = None,
        recommendations: list[dict[str, Any]] | None = None,
        model_name: str | None = None,
        model_version: str | None = None,
        requires_human_review: bool = False,
    ) -> None:
        self._ensure_editable()

        if not isinstance(
            risk_level,
            SupplierContractRiskLevel,
        ):
            raise ValueError("Invalid risk level")

        self.risk_level = risk_level
        self.risk_score = percentage(
            risk_score,
            "Risk score",
        )
        self.ai_summary = optional_string(summary)
        self.ai_risk_explanation = optional_string(explanation)
        self.ai_extracted_clauses = json_safe(
            extracted_clauses or []
        )
        self.ai_risk_factors = json_safe(
            risk_factors or []
        )
        self.ai_recommendations = json_safe(
            recommendations or []
        )
        self.ai_model_name = optional_string(model_name)
        self.ai_model_version = optional_string(model_version)
        self.requires_human_review = requires_human_review
        self.ai_analyzed_at = utc_now()

        self._record_event(
            SupplierContractEventType.RISK_UPDATED,
            actor_id=actor_id,
            details={
                "risk_level": risk_level.value,
                "risk_score": str(self.risk_score),
            },
        )

    # ========================================================
    # UPDATE COMPLIANCE
    # ========================================================

    def update_compliance(
        self,
        *,
        actor_id: str,
        compliance_status: SupplierContractComplianceStatus,
        compliance_score: Decimal | str | float,
        findings: list[dict[str, Any]] | None = None,
    ) -> None:
        self._ensure_editable()

        if not isinstance(
            compliance_status,
            SupplierContractComplianceStatus,
        ):
            raise ValueError("Invalid compliance status")

        self.compliance_status = compliance_status
        self.compliance_score = percentage(
            compliance_score,
            "Compliance score",
        )
        self.compliance_findings = json_safe(findings or [])
        self.compliance_checked_by = required_string(
            actor_id,
            "Actor ID",
        )
        self.compliance_checked_at = utc_now()

        self._record_event(
            SupplierContractEventType.COMPLIANCE_UPDATED,
            actor_id=actor_id,
            details={
                "compliance_status": compliance_status.value,
                "compliance_score": str(
                    self.compliance_score
                ),
            },
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
        self._require_status(
            SupplierContractStatus.ACTIVE
        )

        self.suspension_reason = required_string(
            reason,
            "Suspension reason",
        )
        self.suspended_at = utc_now()
        self.status = SupplierContractStatus.SUSPENDED

        self._record_event(
            SupplierContractEventType.SUSPENDED,
            actor_id=actor_id,
            details={"reason": self.suspension_reason},
        )

    # ========================================================
    # RESUME
    # ========================================================

    def resume(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            SupplierContractStatus.SUSPENDED
        )

        if self.is_expired:
            raise ValueError(
                "Expired contract cannot be resumed"
            )

        self.status = SupplierContractStatus.ACTIVE
        self.suspension_reason = None
        self.suspended_at = None

        self._record_event(
            SupplierContractEventType.RESUMED,
            actor_id=actor_id,
        )

    # ========================================================
    # REQUEST RENEWAL
    # ========================================================

    def request_renewal(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            SupplierContractStatus.ACTIVE
        )

        if self.renewal_type == (
            SupplierContractRenewalType.NON_RENEWABLE
        ):
            raise ValueError(
                "Contract is not renewable"
            )

        if not self.requires_renewal:
            raise ValueError(
                "Renewal notice window has not started"
            )

        self.status = SupplierContractStatus.RENEWAL_PENDING
        self.renewal_requested_at = utc_now()

        self._record_event(
            SupplierContractEventType.RENEWAL_REQUESTED,
            actor_id=actor_id,
        )

    # ========================================================
    # COMPLETE VERIFIED RENEWAL
    # ========================================================

    def complete_renewal(
        self,
        *,
        actor_id: str,
        new_end_date: datetime,
        renewal_document_id: str,
    ) -> None:
        self._require_status(
            SupplierContractStatus.RENEWAL_PENDING
        )

        new_end = ensure_datetime(new_end_date)

        if self.end_date is None:
            raise ValueError(
                "Current contract end date missing"
            )

        if new_end <= ensure_datetime(self.end_date):
            raise ValueError(
                "New end date must extend the contract"
            )

        renewal_document_id = required_string(
            renewal_document_id,
            "Renewal document ID",
        )

        # A service must verify signed renewal terms,
        # approval and the renewal document before calling.

        previous_end = self.end_date
        self.end_date = new_end
        self.renewal_count = (self.renewal_count or 0) + 1
        self.renewed_at = utc_now()
        self.status = SupplierContractStatus.ACTIVE

        self._record_event(
            SupplierContractEventType.RENEWED,
            actor_id=actor_id,
            details={
                "previous_end_date": iso(previous_end),
                "new_end_date": iso(new_end),
                "renewal_document_id": renewal_document_id,
            },
        )

    # ========================================================
    # EXPIRE
    # ========================================================

    def expire(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        if not self.is_expired:
            raise ValueError(
                "Contract expiration date not reached"
            )

        self.status = SupplierContractStatus.EXPIRED
        self.expired_at = utc_now()

        self._record_event(
            SupplierContractEventType.EXPIRED,
            actor_id=actor_id,
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
        self._require_status(
            SupplierContractStatus.ACTIVE,
            SupplierContractStatus.SUSPENDED,
            SupplierContractStatus.RENEWAL_PENDING,
        )

        # Verify termination authority, contractual notice,
        # outstanding obligations and supplier notifications
        # in the application service.

        self.termination_reason = required_string(
            reason,
            "Termination reason",
        )
        self.terminated_by = required_string(
            actor_id,
            "Actor ID",
        )
        self.terminated_at = utc_now()
        self.status = SupplierContractStatus.TERMINATED

        self._record_event(
            SupplierContractEventType.TERMINATED,
            actor_id=actor_id,
            details={"reason": self.termination_reason},
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
        self._require_status(
            SupplierContractStatus.DRAFT,
            SupplierContractStatus.UNDER_REVIEW,
            SupplierContractStatus.PENDING_APPROVAL,
            SupplierContractStatus.APPROVED,
            SupplierContractStatus.REJECTED,
        )

        self.cancellation_reason = required_string(
            reason,
            "Cancellation reason",
        )
        self.cancelled_at = utc_now()
        self.status = SupplierContractStatus.CANCELLED

        self._record_event(
            SupplierContractEventType.CANCELLED,
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
            raise ValueError("Contract has been deleted")

        if self.status not in {
            SupplierContractStatus.EXPIRED,
            SupplierContractStatus.TERMINATED,
            SupplierContractStatus.CANCELLED,
            SupplierContractStatus.REJECTED,
        }:
            raise ValueError(
                "Only terminal contracts can be archived"
            )

        self.status = SupplierContractStatus.ARCHIVED
        self.archived_at = utc_now()

        self._record_event(
            SupplierContractEventType.ARCHIVED,
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
            raise ValueError("Contract already deleted")

        if self.status not in {
            SupplierContractStatus.DRAFT,
            SupplierContractStatus.ARCHIVED,
        }:
            raise ValueError(
                "Only draft or archived contracts "
                "can be soft-deleted"
            )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = required_string(
            actor_id,
            "Actor ID",
        )

        self._record_event(
            SupplierContractEventType.SOFT_DELETED,
            actor_id=actor_id,
        )

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(
        self,
        *,
        include_internal: bool = False,
        include_items: bool = True,
        include_obligations: bool = False,
        include_amendments: bool = False,
        include_events: bool = False,
    ) -> dict[str, Any]:
        data = {
            "id": self.id,
            "organization_id": self.organization_id,
            "contract_number": self.contract_number,
            "title": self.title,
            "description": self.description,
            "contract_type": enum_value(self.contract_type),
            "status": enum_value(self.status),
            "priority": enum_value(self.priority),
            "supplier_id": self.supplier_id,
            "warehouse_id": self.warehouse_id,
            "store_id": self.store_id,
            "category_id": self.category_id,
            "document_id": self.document_id,
            "buyer_legal_name": self.buyer_legal_name,
            "supplier_legal_name": self.supplier_legal_name,
            "start_date": iso(self.start_date),
            "end_date": iso(self.end_date),
            "effective_date": iso(self.effective_date),
            "signed_date": iso(self.signed_date),
            "next_renewal_at": iso(self.next_renewal_at),
            "renewal_type": enum_value(self.renewal_type),
            "auto_renewal_enabled": self.auto_renewal_enabled,
            "renewal_notice_days": self.renewal_notice_days,
            "renewal_count": self.renewal_count,
            "currency": self.currency,
            "contract_value": decimal_string(
                self.contract_value
            ),
            "annual_commitment_value": decimal_string(
                self.annual_commitment_value
            ),
            "minimum_order_value": decimal_string(
                self.minimum_order_value
            ),
            "maximum_order_value": decimal_string(
                self.maximum_order_value
            ),
            "minimum_order_quantity": decimal_string(
                self.minimum_order_quantity
            ),
            "maximum_order_quantity": decimal_string(
                self.maximum_order_quantity
            ),
            "pricing_type": enum_value(self.pricing_type),
            "payment_terms": enum_value(self.payment_terms),
            "payment_due_days": self.payment_due_days,
            "discount_rate": decimal_string(
                self.discount_rate
            ),
            "penalty_rate": decimal_string(
                self.penalty_rate
            ),
            "tax_rate": decimal_string(self.tax_rate),
            "lead_time_days": self.lead_time_days,
            "delivery_frequency": self.delivery_frequency,
            "delivery_location": self.delivery_location,
            "incoterms": self.incoterms,
            "on_time_delivery_target": decimal_string(
                self.on_time_delivery_target
            ),
            "quality_acceptance_target": decimal_string(
                self.quality_acceptance_target
            ),
            "risk_level": enum_value(self.risk_level),
            "risk_score": decimal_string(self.risk_score),
            "ai_summary": self.ai_summary,
            "ai_recommendations": self.ai_recommendations,
            "compliance_status": enum_value(
                self.compliance_status
            ),
            "compliance_score": decimal_string(
                self.compliance_score
            ),
            "approval_status": enum_value(
                self.approval_status
            ),
            "signature_status": enum_value(
                self.signature_status
            ),
            "is_active": self.is_active,
            "is_signed": self.is_signed,
            "is_expired": self.is_expired,
            "is_high_risk": self.is_high_risk,
            "requires_renewal": self.requires_renewal,
            "total_item_value": decimal_string(
                self.total_item_value
            ),
            "open_obligation_count": (
                self.open_obligation_count
            ),
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "is_deleted": self.is_deleted,
            "version": self.version,
        }

        if include_items:
            data["items"] = [
                item.to_dict()
                for item in self.items
            ]

        if include_obligations:
            data["obligations"] = [
                obligation.to_dict()
                for obligation in self.obligations
            ]

        if include_amendments:
            data["amendments"] = [
                amendment.to_dict()
                for amendment in self.amendments
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
                "supplier_risk_id": self.supplier_risk_id,
                "approval_request_id": (
                    self.approval_request_id
                ),
                "model_registry_id": self.model_registry_id,
                "agent_run_id": self.agent_run_id,
                "parent_contract_id": self.parent_contract_id,
                "external_contract_id": (
                    self.external_contract_id
                ),
                "contract_owner_id": self.contract_owner_id,
                "procurement_manager_id": (
                    self.procurement_manager_id
                ),
                "legal_reviewer_id": self.legal_reviewer_id,
                "pricing_details": self.pricing_details,
                "payment_details": self.payment_details,
                "penalty_details": self.penalty_details,
                "shipping_terms": self.shipping_terms,
                "return_terms": self.return_terms,
                "warranty_terms": self.warranty_terms,
                "service_level_details": (
                    self.service_level_details
                ),
                "governing_law": self.governing_law,
                "jurisdiction": self.jurisdiction,
                "legal_terms": self.legal_terms,
                "ai_extracted_clauses": (
                    self.ai_extracted_clauses
                ),
                "ai_risk_factors": self.ai_risk_factors,
                "ai_risk_explanation": (
                    self.ai_risk_explanation
                ),
                "compliance_findings": (
                    self.compliance_findings
                ),
                "signature_provider": self.signature_provider,
                "signature_envelope_id": (
                    self.signature_envelope_id
                ),
                "signed_document_id": (
                    self.signed_document_id
                ),
                "signature_metadata": (
                    self.signature_metadata
                ),
                "approved_by": self.approved_by,
                "approved_at": iso(self.approved_at),
                "rejected_by": self.rejected_by,
                "rejected_at": iso(self.rejected_at),
                "rejection_reason": self.rejection_reason,
                "termination_reason": (
                    self.termination_reason
                ),
                "suspension_reason": self.suspension_reason,
                "contract_metadata": self.contract_metadata,
                "tags": self.tags,
                "created_by": self.created_by,
                "updated_by": self.updated_by,
                "trace_id": self.trace_id,
                "correlation_id": self.correlation_id,
            })

        return data

    def __repr__(self) -> str:
        return (
            f"<SupplierContract("
            f"id={self.id!r}, "
            f"contract_number={self.contract_number!r}, "
            f"supplier_id={self.supplier_id!r}, "
            f"status={enum_value(self.status)!r}"
            f")>"
        )


# ============================================================
# SUPPLIER CONTRACT ITEM
# ============================================================

class SupplierContractItem(Base):
    __tablename__ = "supplier_contract_items"

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "contract_id"],
            [
                "supplier_contracts.organization_id",
                "supplier_contracts.id",
            ],
            name="fk_supplier_contract_item_contract",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "organization_id",
            "contract_id",
            "product_id",
            name="uq_supplier_contract_item_product",
        ),
        CheckConstraint(
            "quantity > 0",
            name="ck_supplier_contract_item_quantity",
        ),
        CheckConstraint(
            "unit_price >= 0",
            name="ck_supplier_contract_item_unit_price",
        ),
        CheckConstraint(
            "discount_rate >= 0 AND discount_rate <= 1",
            name="ck_supplier_contract_item_discount",
        ),
        CheckConstraint(
            "tax_rate >= 0 AND tax_rate <= 1",
            name="ck_supplier_contract_item_tax",
        ),
        Index(
            "ix_supplier_contract_item_product",
            "organization_id",
            "product_id",
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

    contract_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    product_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    product_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    sku: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
    )

    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        nullable=False,
    )

    unit_of_measure: Mapped[str] = mapped_column(
        String(30),
        default="unit",
        nullable=False,
    )

    discount_rate: Mapped[Decimal] = mapped_column(
        Numeric(6, 4),
        default=ZERO,
        nullable=False,
    )

    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(6, 4),
        default=ZERO,
        nullable=False,
    )

    specifications: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    delivery_schedule: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
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

    contract: Mapped[SupplierContract] = relationship(
        "SupplierContract",
        back_populates="items",
    )

    @property
    def subtotal(self) -> Decimal:
        return (
            (self.quantity or ZERO)
            * (self.unit_price or ZERO)
        ).quantize(Decimal("0.0001"))

    @property
    def discount_amount(self) -> Decimal:
        return (
            self.subtotal
            * (self.discount_rate or ZERO)
        ).quantize(Decimal("0.0001"))

    @property
    def taxable_amount(self) -> Decimal:
        return self.subtotal - self.discount_amount

    @property
    def tax_amount(self) -> Decimal:
        return (
            self.taxable_amount
            * (self.tax_rate or ZERO)
        ).quantize(Decimal("0.0001"))

    @property
    def total_value(self) -> Decimal:
        return self.taxable_amount + self.tax_amount

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "contract_id": self.contract_id,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "sku": self.sku,
            "quantity": decimal_string(self.quantity),
            "unit_price": decimal_string(self.unit_price),
            "unit_of_measure": self.unit_of_measure,
            "discount_rate": decimal_string(
                self.discount_rate
            ),
            "tax_rate": decimal_string(self.tax_rate),
            "subtotal": decimal_string(self.subtotal),
            "discount_amount": decimal_string(
                self.discount_amount
            ),
            "tax_amount": decimal_string(self.tax_amount),
            "total_value": decimal_string(self.total_value),
            "specifications": self.specifications,
            "delivery_schedule": self.delivery_schedule,
            "created_at": iso(self.created_at),
        }


# ============================================================
# SUPPLIER CONTRACT OBLIGATION
# ============================================================

class SupplierContractObligation(Base):
    __tablename__ = "supplier_contract_obligations"

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "contract_id"],
            [
                "supplier_contracts.organization_id",
                "supplier_contracts.id",
            ],
            name="fk_supplier_contract_obligation_contract",
            ondelete="CASCADE",
        ),
        Index(
            "ix_supplier_contract_obligation_due",
            "organization_id",
            "due_at",
        ),
        Index(
            "ix_supplier_contract_obligation_status",
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

    contract_id: Mapped[str] = mapped_column(
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

    obligation_type: Mapped[
        SupplierContractObligationType
    ] = mapped_column(
        enum_type(
            SupplierContractObligationType,
            "supplier_contract_obligation_type",
        ),
        nullable=False,
    )

    status: Mapped[
        SupplierContractObligationStatus
    ] = mapped_column(
        enum_type(
            SupplierContractObligationStatus,
            "supplier_contract_obligation_status",
        ),
        default=SupplierContractObligationStatus.OPEN,
        nullable=False,
    )

    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    assigned_to: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    requires_evidence: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    evidence_document_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    completion_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    obligation_metadata: Mapped[
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

    contract: Mapped[SupplierContract] = relationship(
        "SupplierContract",
        back_populates="obligations",
    )

    @property
    def is_overdue(self) -> bool:
        return (
            self.status in {
                SupplierContractObligationStatus.OPEN,
                SupplierContractObligationStatus.IN_PROGRESS,
                SupplierContractObligationStatus.OVERDUE,
            }
            and ensure_datetime(self.due_at) < utc_now()
        )

    def start(self) -> None:
        if self.status != SupplierContractObligationStatus.OPEN:
            raise ValueError(
                "Only open obligations can be started"
            )

        self.status = (
            SupplierContractObligationStatus.IN_PROGRESS
        )
        self.updated_at = utc_now()

    def complete(
        self,
        *,
        actor_id: str,
        notes: str | None = None,
        evidence_document_id: str | None = None,
    ) -> None:
        if self.status not in {
            SupplierContractObligationStatus.OPEN,
            SupplierContractObligationStatus.IN_PROGRESS,
            SupplierContractObligationStatus.OVERDUE,
        }:
            raise ValueError(
                "Obligation cannot be completed"
            )

        if self.requires_evidence and not (
            evidence_document_id or self.evidence_document_id
        ):
            raise ValueError(
                "Evidence document is required"
            )

        if evidence_document_id is not None:
            self.evidence_document_id = required_string(
                evidence_document_id,
                "Evidence document ID",
            )

        self.completed_by = required_string(
            actor_id,
            "Actor ID",
        )
        self.completion_notes = optional_string(notes)
        self.completed_at = utc_now()
        self.updated_at = utc_now()
        self.status = (
            SupplierContractObligationStatus.COMPLETED
        )

    def mark_overdue(self) -> None:
        if not self.is_overdue:
            raise ValueError(
                "Obligation is not overdue"
            )

        self.status = (
            SupplierContractObligationStatus.OVERDUE
        )
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "contract_id": self.contract_id,
            "title": self.title,
            "description": self.description,
            "obligation_type": enum_value(
                self.obligation_type
            ),
            "status": enum_value(self.status),
            "due_at": iso(self.due_at),
            "assigned_to": self.assigned_to,
            "requires_evidence": self.requires_evidence,
            "evidence_document_id": (
                self.evidence_document_id
            ),
            "completed_at": iso(self.completed_at),
            "completed_by": self.completed_by,
            "completion_notes": self.completion_notes,
            "is_overdue": self.is_overdue,
            "created_at": iso(self.created_at),
        }


# ============================================================
# SUPPLIER CONTRACT AMENDMENT
# ============================================================

class SupplierContractAmendment(Base):
    __tablename__ = "supplier_contract_amendments"

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "contract_id"],
            [
                "supplier_contracts.organization_id",
                "supplier_contracts.id",
            ],
            name="fk_supplier_contract_amendment_contract",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "organization_id",
            "amendment_number",
            name="uq_supplier_contract_amendment_number",
        ),
        Index(
            "ix_supplier_contract_amendment_status",
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

    contract_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    amendment_number: Mapped[str] = mapped_column(
        String(60),
        default=generate_amendment_number,
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

    status: Mapped[
        SupplierContractAmendmentStatus
    ] = mapped_column(
        enum_type(
            SupplierContractAmendmentStatus,
            "supplier_contract_amendment_status",
        ),
        default=SupplierContractAmendmentStatus.DRAFT,
        nullable=False,
    )

    change_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    proposed_changes: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    previous_values: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    effective_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    amendment_document_id: Mapped[
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

    signed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_by: Mapped[str | None] = mapped_column(
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

    contract: Mapped[SupplierContract] = relationship(
        "SupplierContract",
        back_populates="amendments",
    )

    def request_approval(self) -> None:
        if self.status != SupplierContractAmendmentStatus.DRAFT:
            raise ValueError(
                "Only draft amendments can request approval"
            )

        if not self.proposed_changes:
            raise ValueError(
                "Proposed changes are required"
            )

        self.status = (
            SupplierContractAmendmentStatus.PENDING_APPROVAL
        )
        self.updated_at = utc_now()

    def approve(self, *, approver_id: str) -> None:
        if self.status != (
            SupplierContractAmendmentStatus.PENDING_APPROVAL
        ):
            raise ValueError(
                "Amendment is not pending approval"
            )

        self.approved_by = required_string(
            approver_id,
            "Approver ID",
        )
        self.approved_at = utc_now()
        self.updated_at = utc_now()
        self.status = (
            SupplierContractAmendmentStatus.APPROVED
        )

    def record_signature(
        self,
        *,
        signed_at: datetime,
        document_id: str,
    ) -> None:
        if self.status != SupplierContractAmendmentStatus.APPROVED:
            raise ValueError(
                "Amendment must be approved before signing"
            )

        # External signature verification is mandatory.

        self.signed_at = ensure_datetime(signed_at)
        self.amendment_document_id = required_string(
            document_id,
            "Amendment document ID",
        )
        self.updated_at = utc_now()
        self.status = SupplierContractAmendmentStatus.SIGNED

    def mark_effective(self) -> None:
        if self.status != SupplierContractAmendmentStatus.SIGNED:
            raise ValueError(
                "Amendment must be signed"
            )

        if (
            self.effective_at is not None
            and ensure_datetime(self.effective_at) > utc_now()
        ):
            raise ValueError(
                "Amendment effective date has not arrived"
            )

        # Changes to the parent contract must be applied
        # transactionally by an authorized service.
        # This method only records successful application.

        self.applied_at = utc_now()
        self.updated_at = utc_now()
        self.status = SupplierContractAmendmentStatus.EFFECTIVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "contract_id": self.contract_id,
            "amendment_number": self.amendment_number,
            "title": self.title,
            "description": self.description,
            "status": enum_value(self.status),
            "change_summary": self.change_summary,
            "proposed_changes": self.proposed_changes,
            "effective_at": iso(self.effective_at),
            "amendment_document_id": (
                self.amendment_document_id
            ),
            "approved_at": iso(self.approved_at),
            "signed_at": iso(self.signed_at),
            "applied_at": iso(self.applied_at),
            "created_at": iso(self.created_at),
        }


# ============================================================
# SUPPLIER CONTRACT EVENT
# ============================================================

class SupplierContractEvent(Base):
    __tablename__ = "supplier_contract_events"

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "contract_id"],
            [
                "supplier_contracts.organization_id",
                "supplier_contracts.id",
            ],
            name="fk_supplier_contract_event_contract",
            ondelete="CASCADE",
        ),
        Index(
            "ix_supplier_contract_event_created",
            "contract_id",
            "created_at",
        ),
        Index(
            "ix_supplier_contract_event_type",
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

    contract_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    event_type: Mapped[
        SupplierContractEventType
    ] = mapped_column(
        enum_type(
            SupplierContractEventType,
            "supplier_contract_event_type",
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

    contract: Mapped[SupplierContract] = relationship(
        "SupplierContract",
        back_populates="events",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "contract_id": self.contract_id,
            "event_type": enum_value(self.event_type),
            "description": self.description,
            "details": self.details,
            "actor_id": self.actor_id,
            "created_at": iso(self.created_at),
        }

    def __repr__(self) -> str:
        return (
            f"<SupplierContractEvent("
            f"id={self.id!r}, "
            f"contract_id={self.contract_id!r}, "
            f"event_type={enum_value(self.event_type)!r}"
            f")>"
        )