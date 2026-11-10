from __future__ import annotations

"""Planned module: organization. Implementation pending."""

"""
backend/models/organization.py

Autonomous Retail Supply Chain AI 5.0
Organization / Multi-Tenant Management Model

Features:
- Multi-tenant organization identity
- Business and legal profiles
- Organization types and industries
- Subscription and billing metadata
- Enterprise resource limits
- Warehouse and supplier configuration
- AI / ML / GenAI feature settings
- Agentic AI governance
- RBAC, MFA and security policies
- Data retention and privacy settings
- Integration and notification preferences
- Organization lifecycle management
- Onboarding and verification
- Suspension and reactivation
- Audit metadata and soft deletion
- Optimistic concurrency control

Requirements:
    Python >= 3.10
    SQLAlchemy >= 2.0

Shared ORM Base:
    backend.models.base.Base

Security:
    Never store passwords, access tokens,
    payment card data, or API secrets here.
"""


import enum
import re
import uuid

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SQLEnum,
    Index,
    Integer,
    JSON,
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


def generate_organization_code() -> str:
    return f"ORG-{uuid.uuid4().hex[:16].upper()}"


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


def datetime_string(
    value: datetime | None,
) -> str | None:
    return value.isoformat() if value else None


def enum_value(
    value: enum.Enum | None,
) -> str | None:
    return value.value if value is not None else None


def require_text(
    value: str,
    field_name: str,
    *,
    max_length: int | None = None,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")

    result = value.strip()

    if not result:
        raise ValueError(f"{field_name} is required")

    if max_length is not None and len(result) > max_length:
        raise ValueError(
            f"{field_name} exceeds {max_length} characters"
        )

    return result


def normalize_slug(value: str) -> str:
    slug = re.sub(
        r"[^a-z0-9]+",
        "-",
        value.strip().lower(),
    ).strip("-")

    if not slug or len(slug) > 100:
        raise ValueError("Invalid organization slug")

    return slug


def validate_timezone_datetime(
    value: datetime,
) -> datetime:
    if value.tzinfo is None:
        raise ValueError(
            "Timezone-aware datetime required"
        )

    return value.astimezone(timezone.utc)


# ============================================================
# ENUMS
# ============================================================

class OrganizationType(str, enum.Enum):
    ENTERPRISE = "enterprise"
    CORPORATION = "corporation"
    SMALL_BUSINESS = "small_business"
    STARTUP = "startup"
    RETAILER = "retailer"
    WHOLESALER = "wholesaler"
    DISTRIBUTOR = "distributor"
    MANUFACTURER = "manufacturer"
    LOGISTICS_PROVIDER = "logistics_provider"
    SUPPLIER = "supplier"
    NON_PROFIT = "non_profit"
    GOVERNMENT = "government"
    EDUCATIONAL = "educational"
    OTHER = "other"


class OrganizationIndustry(str, enum.Enum):
    RETAIL = "retail"
    ECOMMERCE = "ecommerce"
    FMCG = "fmcg"
    GROCERY = "grocery"
    FASHION = "fashion"
    ELECTRONICS = "electronics"
    PHARMACEUTICALS = "pharmaceuticals"
    HEALTHCARE = "healthcare"
    AUTOMOTIVE = "automotive"
    MANUFACTURING = "manufacturing"
    LOGISTICS = "logistics"
    FOOD_BEVERAGE = "food_beverage"
    AGRICULTURE = "agriculture"
    TECHNOLOGY = "technology"
    GENERAL = "general"
    OTHER = "other"


class OrganizationStatus(str, enum.Enum):
    DRAFT = "draft"
    ONBOARDING = "onboarding"
    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"
    CLOSING = "closing"
    CLOSED = "closed"


class OrganizationVerificationStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    EXPIRED = "expired"


class OrganizationPlan(str, enum.Enum):
    FREE = "free"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    BUSINESS = "business"
    ENTERPRISE = "enterprise"
    CUSTOM = "custom"


class OrganizationBillingStatus(str, enum.Enum):
    NOT_CONFIGURED = "not_configured"
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


class OrganizationSize(str, enum.Enum):
    SOLO = "solo"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    ENTERPRISE = "enterprise"


class OrganizationRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


# ============================================================
# ORGANIZATION MODEL
# ============================================================

class Organization(Base):
    __tablename__ = "organizations"

    __table_args__ = (
        UniqueConstraint(
            "organization_code",
            name="uq_organization_code",
        ),
        UniqueConstraint(
            "slug",
            name="uq_organization_slug",
        ),
        CheckConstraint(
            "max_users >= 0",
            name="organization_max_users_nonnegative",
        ),
        CheckConstraint(
            "max_warehouses >= 0",
            name="organization_max_warehouses_nonnegative",
        ),
        CheckConstraint(
            "max_suppliers >= 0",
            name="organization_max_suppliers_nonnegative",
        ),
        CheckConstraint(
            "max_integrations >= 0",
            name="organization_max_integrations_nonnegative",
        ),
        CheckConstraint(
            "max_ai_agents >= 0",
            name="organization_max_agents_nonnegative",
        ),
        CheckConstraint(
            "monthly_ai_request_limit >= 0",
            name="organization_ai_limit_nonnegative",
        ),
        CheckConstraint(
            "storage_limit_gb >= 0",
            name="organization_storage_limit_nonnegative",
        ),
        CheckConstraint(
            "data_retention_days >= 0",
            name="organization_retention_nonnegative",
        ),
        CheckConstraint(
            "version >= 1",
            name="organization_version_positive",
        ),
        Index(
            "ix_organization_status",
            "status",
        ),
        Index(
            "ix_organization_plan",
            "plan",
        ),
        Index(
            "ix_organization_industry",
            "industry",
        ),
        Index(
            "ix_organization_country",
            "country_code",
        ),
        Index(
            "ix_organization_created",
            "created_at",
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

    organization_code: Mapped[str] = mapped_column(
        String(40),
        default=generate_organization_code,
        nullable=False,
    )

    slug: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    # --------------------------------------------------------
    # BUSINESS IDENTITY
    # --------------------------------------------------------

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    legal_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    display_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    organization_type: Mapped[
        OrganizationType
    ] = mapped_column(
        enum_column(
            OrganizationType,
            "organization_type",
        ),
        default=OrganizationType.RETAILER,
        nullable=False,
    )

    industry: Mapped[
        OrganizationIndustry
    ] = mapped_column(
        enum_column(
            OrganizationIndustry,
            "organization_industry",
        ),
        default=OrganizationIndustry.RETAIL,
        nullable=False,
    )

    organization_size: Mapped[
        OrganizationSize
    ] = mapped_column(
        enum_column(
            OrganizationSize,
            "organization_size",
        ),
        default=OrganizationSize.SMALL,
        nullable=False,
    )

    # --------------------------------------------------------
    # LIFECYCLE
    # --------------------------------------------------------

    status: Mapped[
        OrganizationStatus
    ] = mapped_column(
        enum_column(
            OrganizationStatus,
            "organization_status",
        ),
        default=OrganizationStatus.DRAFT,
        nullable=False,
    )

    verification_status: Mapped[
        OrganizationVerificationStatus
    ] = mapped_column(
        enum_column(
            OrganizationVerificationStatus,
            "organization_verification_status",
        ),
        default=OrganizationVerificationStatus.NOT_STARTED,
        nullable=False,
    )

    # --------------------------------------------------------
    # CONTACT
    # --------------------------------------------------------

    primary_email: Mapped[str] = mapped_column(
        String(320),
        nullable=False,
    )

    support_email: Mapped[str | None] = mapped_column(
        String(320),
        nullable=True,
    )

    billing_email: Mapped[str | None] = mapped_column(
        String(320),
        nullable=True,
    )

    phone_number: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    website_url: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )

    logo_url: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )

    # --------------------------------------------------------
    # LOCATION
    # --------------------------------------------------------

    address_line_1: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    address_line_2: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    city: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    state: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    postal_code: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    country_code: Mapped[str] = mapped_column(
        String(2),
        default="IN",
        nullable=False,
    )

    timezone_name: Mapped[str] = mapped_column(
        String(100),
        default="Asia/Kolkata",
        nullable=False,
    )

    default_currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    default_locale: Mapped[str] = mapped_column(
        String(20),
        default="en-IN",
        nullable=False,
    )

    # --------------------------------------------------------
    # LEGAL AND TAX PROFILE
    # --------------------------------------------------------

    registration_number: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    tax_registration_reference: Mapped[
        str | None
    ] = mapped_column(
        String(150),
        nullable=True,
    )

    legal_entity_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    incorporation_date: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # OWNER AND ADMINISTRATORS
    # --------------------------------------------------------

    owner_user_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    primary_admin_user_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # SUBSCRIPTION
    # --------------------------------------------------------

    plan: Mapped[OrganizationPlan] = mapped_column(
        enum_column(
            OrganizationPlan,
            "organization_plan",
        ),
        default=OrganizationPlan.FREE,
        nullable=False,
    )

    billing_status: Mapped[
        OrganizationBillingStatus
    ] = mapped_column(
        enum_column(
            OrganizationBillingStatus,
            "organization_billing_status",
        ),
        default=OrganizationBillingStatus.NOT_CONFIGURED,
        nullable=False,
    )

    billing_customer_reference: Mapped[
        str | None
    ] = mapped_column(
        String(200),
        nullable=True,
    )

    subscription_reference: Mapped[
        str | None
    ] = mapped_column(
        String(200),
        nullable=True,
    )

    trial_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    subscription_started_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    subscription_ends_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # RESOURCE LIMITS
    # --------------------------------------------------------

    max_users: Mapped[int] = mapped_column(
        Integer,
        default=10,
        nullable=False,
    )

    max_warehouses: Mapped[int] = mapped_column(
        Integer,
        default=5,
        nullable=False,
    )

    max_suppliers: Mapped[int] = mapped_column(
        Integer,
        default=100,
        nullable=False,
    )

    max_integrations: Mapped[int] = mapped_column(
        Integer,
        default=5,
        nullable=False,
    )

    max_ai_agents: Mapped[int] = mapped_column(
        Integer,
        default=3,
        nullable=False,
    )

    monthly_ai_request_limit: Mapped[int] = mapped_column(
        Integer,
        default=10000,
        nullable=False,
    )

    storage_limit_gb: Mapped[int] = mapped_column(
        Integer,
        default=10,
        nullable=False,
    )

    # --------------------------------------------------------
    # FEATURE FLAGS
    # --------------------------------------------------------

    ai_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    ml_forecasting_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    agentic_ai_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    rag_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    advanced_analytics_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    automation_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    integrations_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    notifications_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # --------------------------------------------------------
    # SECURITY AND GOVERNANCE
    # --------------------------------------------------------

    mfa_required: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    sso_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    require_human_approval_for_ai: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    allow_autonomous_actions: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    risk_level: Mapped[
        OrganizationRiskLevel
    ] = mapped_column(
        enum_column(
            OrganizationRiskLevel,
            "organization_risk_level",
        ),
        default=OrganizationRiskLevel.UNKNOWN,
        nullable=False,
    )

    data_retention_days: Mapped[int] = mapped_column(
        Integer,
        default=365,
        nullable=False,
    )

    security_policy: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    privacy_settings: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    ai_governance_settings: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # BUSINESS CONFIGURATION
    # --------------------------------------------------------

    inventory_settings: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    demand_forecasting_settings: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    supplier_management_settings: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    logistics_settings: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    notification_settings: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    integration_settings: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # UI AND BRANDING
    # --------------------------------------------------------

    branding_settings: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    dashboard_settings: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # ONBOARDING AND VERIFICATION
    # --------------------------------------------------------

    onboarding_completed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    verification_requested_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    verified_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    verification_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # SUSPENSION
    # --------------------------------------------------------

    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    suspended_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    suspension_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # CLOSURE
    # --------------------------------------------------------

    closure_requested_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    closure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # TAGS AND METADATA
    # --------------------------------------------------------

    tags: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    organization_metadata: Mapped[
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

    # --------------------------------------------------------
    # SOFT DELETE
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # OPTIMISTIC CONCURRENCY
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
    def is_active(self) -> bool:
        return (
            self.status == OrganizationStatus.ACTIVE
            and not self.is_deleted
        )

    @property
    def is_verified(self) -> bool:
        return (
            self.verification_status
            == OrganizationVerificationStatus.VERIFIED
        )

    @property
    def is_suspended(self) -> bool:
        return (
            self.status == OrganizationStatus.SUSPENDED
        )

    @property
    def is_closed(self) -> bool:
        return (
            self.status == OrganizationStatus.CLOSED
        )

    @property
    def is_enterprise(self) -> bool:
        return self.plan in {
            OrganizationPlan.ENTERPRISE,
            OrganizationPlan.CUSTOM,
        }

    @property
    def is_trial_active(self) -> bool:
        return (
            self.billing_status
            == OrganizationBillingStatus.TRIALING
            and self.trial_ends_at is not None
            and validate_timezone_datetime(
                self.trial_ends_at
            ) > utc_now()
        )

    @property
    def can_use_ai(self) -> bool:
        return (
            self.is_active
            and self.ai_enabled
        )

    @property
    def can_use_agents(self) -> bool:
        return (
            self.can_use_ai
            and self.agentic_ai_enabled
        )

    @property
    def can_run_autonomous_actions(self) -> bool:
        return (
            self.can_use_agents
            and self.automation_enabled
            and self.allow_autonomous_actions
            and not self.require_human_approval_for_ai
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_not_deleted(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Organization has been deleted"
            )

    def _ensure_mutable(self) -> None:
        self._ensure_not_deleted()

        if self.status in {
            OrganizationStatus.CLOSING,
            OrganizationStatus.CLOSED,
        }:
            raise ValueError(
                "Organization cannot be modified"
            )

    # ========================================================
    # START ONBOARDING
    # ========================================================

    def start_onboarding(self) -> None:
        self._ensure_not_deleted()

        if self.status != OrganizationStatus.DRAFT:
            raise ValueError(
                "Only draft organizations can start onboarding"
            )

        self.name = require_text(
            self.name,
            "Organization name",
            max_length=255,
        )

        self.primary_email = require_text(
            self.primary_email,
            "Primary email",
            max_length=320,
        )

        self.slug = normalize_slug(self.slug)

        self.status = OrganizationStatus.ONBOARDING
        self._touch()

    # ========================================================
    # COMPLETE ONBOARDING
    # ========================================================

    def complete_onboarding(self) -> None:
        self._ensure_not_deleted()

        if self.status != OrganizationStatus.ONBOARDING:
            raise ValueError(
                "Organization is not onboarding"
            )

        if not self.owner_user_id:
            raise ValueError(
                "Organization owner is required"
            )

        if not self.primary_admin_user_id:
            raise ValueError(
                "Primary administrator is required"
            )

        self.onboarding_completed_at = utc_now()
        self._touch()

    # ========================================================
    # REQUEST VERIFICATION
    # ========================================================

    def request_verification(self) -> None:
        self._ensure_not_deleted()

        if self.status != OrganizationStatus.ONBOARDING:
            raise ValueError(
                "Organization must be onboarding"
            )

        if self.onboarding_completed_at is None:
            raise ValueError(
                "Complete onboarding first"
            )

        if self.verification_status not in {
            OrganizationVerificationStatus.NOT_STARTED,
            OrganizationVerificationStatus.REJECTED,
            OrganizationVerificationStatus.EXPIRED,
        }:
            raise ValueError(
                "Verification request is already active "
                "or completed"
            )

        self.verification_status = (
            OrganizationVerificationStatus.PENDING
        )
        self.verification_requested_at = utc_now()
        self.status = OrganizationStatus.PENDING_VERIFICATION

        self._touch()

    # ========================================================
    # VERIFY ORGANIZATION
    # ========================================================

    def verify(
        self,
        *,
        verified_by: str,
        notes: str | None = None,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != (
            OrganizationStatus.PENDING_VERIFICATION
        ):
            raise ValueError(
                "Organization is not pending verification"
            )

        if self.verification_status != (
            OrganizationVerificationStatus.PENDING
        ):
            raise ValueError(
                "Verification is not pending"
            )

        if not verified_by:
            raise ValueError(
                "Verifier ID is required"
            )

        # Verify business documents and reviewer
        # permissions in the service layer.
        self.verification_status = (
            OrganizationVerificationStatus.VERIFIED
        )
        self.verified_by = verified_by
        self.verified_at = utc_now()
        self.verification_notes = notes

        self._touch()

    # ========================================================
    # ACTIVATE ORGANIZATION
    # ========================================================

    def activate(self) -> None:
        self._ensure_not_deleted()

        if self.status not in {
            OrganizationStatus.PENDING_VERIFICATION,
            OrganizationStatus.INACTIVE,
        }:
            raise ValueError(
                "Organization cannot be activated now"
            )

        if not self.is_verified:
            raise ValueError(
                "Organization must be verified first"
            )

        if self.onboarding_completed_at is None:
            raise ValueError(
                "Onboarding must be completed"
            )

        self.status = OrganizationStatus.ACTIVE
        self.suspended_at = None
        self.suspended_by = None
        self.suspension_reason = None

        self._touch()

    # ========================================================
    # SUSPEND ORGANIZATION
    # ========================================================

    def suspend(
        self,
        *,
        user_id: str,
        reason: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != OrganizationStatus.ACTIVE:
            raise ValueError(
                "Only active organizations can be suspended"
            )

        if not user_id or not reason.strip():
            raise ValueError(
                "User ID and suspension reason required"
            )

        self.status = OrganizationStatus.SUSPENDED
        self.suspended_by = user_id
        self.suspended_at = utc_now()
        self.suspension_reason = reason

        self._touch()

    # ========================================================
    # REACTIVATE ORGANIZATION
    # ========================================================

    def reactivate(self) -> None:
        self._ensure_not_deleted()

        if self.status != OrganizationStatus.SUSPENDED:
            raise ValueError(
                "Organization is not suspended"
            )

        if not self.is_verified:
            raise ValueError(
                "Organization verification required"
            )

        # Resolve billing, security and compliance
        # restrictions in the service layer.
        self.status = OrganizationStatus.ACTIVE
        self.suspended_at = None
        self.suspended_by = None
        self.suspension_reason = None

        self._touch()

    # ========================================================
    # UPDATE BUSINESS PROFILE
    # ========================================================

    def update_profile(
        self,
        *,
        name: str | None = None,
        display_name: str | None = None,
        description: str | None = None,
        website_url: str | None = None,
        phone_number: str | None = None,
    ) -> None:
        self._ensure_mutable()

        if name is not None:
            self.name = require_text(
                name,
                "Organization name",
                max_length=255,
            )

        if display_name is not None:
            self.display_name = require_text(
                display_name,
                "Display name",
                max_length=255,
            )

        if description is not None:
            self.description = description

        if website_url is not None:
            self.website_url = website_url

        if phone_number is not None:
            self.phone_number = phone_number

        self._touch()

    # ========================================================
    # UPDATE SUBSCRIPTION
    # ========================================================

    def update_subscription(
        self,
        *,
        plan: OrganizationPlan,
        billing_status: OrganizationBillingStatus,
        subscription_reference: str | None = None,
        subscription_ends_at: datetime | None = None,
    ) -> None:
        self._ensure_mutable()

        # Billing provider events and entitlements
        # must be verified by the service layer.
        self.plan = plan
        self.billing_status = billing_status
        self.subscription_reference = subscription_reference

        if subscription_ends_at is not None:
            self.subscription_ends_at = (
                validate_timezone_datetime(
                    subscription_ends_at
                )
            )

        self._touch()

    # ========================================================
    # UPDATE RESOURCE LIMITS
    # ========================================================

    def update_resource_limits(
        self,
        *,
        max_users: int | None = None,
        max_warehouses: int | None = None,
        max_suppliers: int | None = None,
        max_integrations: int | None = None,
        max_ai_agents: int | None = None,
        monthly_ai_request_limit: int | None = None,
        storage_limit_gb: int | None = None,
    ) -> None:
        self._ensure_mutable()

        limits = {
            "max_users": max_users,
            "max_warehouses": max_warehouses,
            "max_suppliers": max_suppliers,
            "max_integrations": max_integrations,
            "max_ai_agents": max_ai_agents,
            "monthly_ai_request_limit": (
                monthly_ai_request_limit
            ),
            "storage_limit_gb": storage_limit_gb,
        }

        for field_name, value in limits.items():
            if value is None:
                continue

            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(
                    f"{field_name} must be a "
                    "non-negative integer"
                )

            setattr(self, field_name, value)

        self._touch()

    # ========================================================
    # CONFIGURE AI FEATURES
    # ========================================================

    def configure_ai_features(
        self,
        *,
        ai_enabled: bool | None = None,
        ml_forecasting_enabled: bool | None = None,
        agentic_ai_enabled: bool | None = None,
        rag_enabled: bool | None = None,
        automation_enabled: bool | None = None,
    ) -> None:
        self._ensure_mutable()

        settings = {
            "ai_enabled": ai_enabled,
            "ml_forecasting_enabled": (
                ml_forecasting_enabled
            ),
            "agentic_ai_enabled": agentic_ai_enabled,
            "rag_enabled": rag_enabled,
            "automation_enabled": automation_enabled,
        }

        for field_name, value in settings.items():
            if value is not None:
                if not isinstance(value, bool):
                    raise ValueError(
                        f"{field_name} must be boolean"
                    )

                setattr(self, field_name, value)

        if not self.ai_enabled:
            self.agentic_ai_enabled = False
            self.automation_enabled = False
            self.allow_autonomous_actions = False

        if not self.agentic_ai_enabled:
            self.allow_autonomous_actions = False

        self._touch()

    # ========================================================
    # CONFIGURE AI GOVERNANCE
    # ========================================================

    def configure_ai_governance(
        self,
        *,
        require_human_approval: bool,
        allow_autonomous_actions: bool,
        settings: dict[str, Any] | None = None,
    ) -> None:
        self._ensure_mutable()

        if allow_autonomous_actions:
            if not self.ai_enabled:
                raise ValueError(
                    "AI must be enabled"
                )

            if not self.agentic_ai_enabled:
                raise ValueError(
                    "Agentic AI must be enabled"
                )

            if not self.automation_enabled:
                raise ValueError(
                    "Automation must be enabled"
                )

            if require_human_approval:
                raise ValueError(
                    "Unapproved autonomous actions conflict "
                    "with mandatory human approval"
                )

        self.require_human_approval_for_ai = (
            require_human_approval
        )
        self.allow_autonomous_actions = (
            allow_autonomous_actions
        )

        if settings is not None:
            self.ai_governance_settings = dict(settings)

        self._touch()

    # ========================================================
    # CONFIGURE SECURITY
    # ========================================================

    def configure_security(
        self,
        *,
        mfa_required: bool | None = None,
        sso_enabled: bool | None = None,
        security_policy: dict[str, Any] | None = None,
        privacy_settings: dict[str, Any] | None = None,
    ) -> None:
        self._ensure_mutable()

        if mfa_required is not None:
            if not isinstance(mfa_required, bool):
                raise ValueError(
                    "mfa_required must be boolean"
                )
            self.mfa_required = mfa_required

        if sso_enabled is not None:
            if not isinstance(sso_enabled, bool):
                raise ValueError(
                    "sso_enabled must be boolean"
                )
            self.sso_enabled = sso_enabled

        if security_policy is not None:
            self.security_policy = dict(security_policy)

        if privacy_settings is not None:
            self.privacy_settings = dict(privacy_settings)

        self._touch()

    # ========================================================
    # UPDATE BUSINESS SETTINGS
    # ========================================================

    def update_business_settings(
        self,
        *,
        inventory: dict[str, Any] | None = None,
        forecasting: dict[str, Any] | None = None,
        suppliers: dict[str, Any] | None = None,
        logistics: dict[str, Any] | None = None,
        notifications: dict[str, Any] | None = None,
        integrations: dict[str, Any] | None = None,
    ) -> None:
        self._ensure_mutable()

        if inventory is not None:
            self.inventory_settings = dict(inventory)

        if forecasting is not None:
            self.demand_forecasting_settings = dict(
                forecasting
            )

        if suppliers is not None:
            self.supplier_management_settings = dict(
                suppliers
            )

        if logistics is not None:
            self.logistics_settings = dict(logistics)

        if notifications is not None:
            self.notification_settings = dict(
                notifications
            )

        if integrations is not None:
            self.integration_settings = dict(
                integrations
            )

        self._touch()

    # ========================================================
    # REQUEST CLOSURE
    # ========================================================

    def request_closure(self, reason: str) -> None:
        self._ensure_not_deleted()

        if self.status not in {
            OrganizationStatus.ACTIVE,
            OrganizationStatus.SUSPENDED,
            OrganizationStatus.INACTIVE,
        }:
            raise ValueError(
                "Organization cannot request closure now"
            )

        if not reason.strip():
            raise ValueError(
                "Closure reason required"
            )

        self.status = OrganizationStatus.CLOSING
        self.closure_reason = reason
        self.closure_requested_at = utc_now()

        self._touch()

    # ========================================================
    # COMPLETE CLOSURE
    # ========================================================

    def complete_closure(self) -> None:
        self._ensure_not_deleted()

        if self.status != OrganizationStatus.CLOSING:
            raise ValueError(
                "Organization is not closing"
            )

        # Verify exports, outstanding obligations,
        # data retention, active subscriptions,
        # running jobs and integration shutdown
        # before invoking this method.
        self.status = OrganizationStatus.CLOSED
        self.closed_at = utc_now()

        self.ai_enabled = False
        self.agentic_ai_enabled = False
        self.automation_enabled = False
        self.allow_autonomous_actions = False
        self.integrations_enabled = False

        self._touch()

    # ========================================================
    # SOFT DELETE
    # ========================================================

    def soft_delete(self, user_id: str) -> None:
        self._ensure_not_deleted()

        if self.status != OrganizationStatus.CLOSED:
            raise ValueError(
                "Organization must be closed first"
            )

        if not user_id:
            raise ValueError(
                "Deleting user ID required"
            )

        self.is_deleted = True
        self.deleted_by = user_id
        self.deleted_at = utc_now()

        self._touch()

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(
        self,
        *,
        include_sensitive: bool = False,
    ) -> dict[str, Any]:
        result = {
            "id": self.id,
            "organization_code": self.organization_code,
            "slug": self.slug,
            "name": self.name,
            "legal_name": self.legal_name,
            "display_name": self.display_name,
            "description": self.description,
            "organization_type": enum_value(
                self.organization_type
            ),
            "industry": enum_value(self.industry),
            "organization_size": enum_value(
                self.organization_size
            ),
            "status": enum_value(self.status),
            "verification_status": enum_value(
                self.verification_status
            ),
            "primary_email": self.primary_email,
            "support_email": self.support_email,
            "phone_number": self.phone_number,
            "website_url": self.website_url,
            "logo_url": self.logo_url,
            "city": self.city,
            "state": self.state,
            "country_code": self.country_code,
            "timezone_name": self.timezone_name,
            "default_currency": self.default_currency,
            "default_locale": self.default_locale,
            "plan": enum_value(self.plan),
            "billing_status": enum_value(
                self.billing_status
            ),
            "max_users": self.max_users,
            "max_warehouses": self.max_warehouses,
            "max_suppliers": self.max_suppliers,
            "max_integrations": self.max_integrations,
            "max_ai_agents": self.max_ai_agents,
            "monthly_ai_request_limit": (
                self.monthly_ai_request_limit
            ),
            "storage_limit_gb": self.storage_limit_gb,
            "ai_enabled": self.ai_enabled,
            "ml_forecasting_enabled": (
                self.ml_forecasting_enabled
            ),
            "agentic_ai_enabled": self.agentic_ai_enabled,
            "rag_enabled": self.rag_enabled,
            "advanced_analytics_enabled": (
                self.advanced_analytics_enabled
            ),
            "automation_enabled": self.automation_enabled,
            "integrations_enabled": (
                self.integrations_enabled
            ),
            "notifications_enabled": (
                self.notifications_enabled
            ),
            "mfa_required": self.mfa_required,
            "sso_enabled": self.sso_enabled,
            "require_human_approval_for_ai": (
                self.require_human_approval_for_ai
            ),
            "allow_autonomous_actions": (
                self.allow_autonomous_actions
            ),
            "risk_level": enum_value(self.risk_level),
            "data_retention_days": self.data_retention_days,
            "is_active": self.is_active,
            "is_verified": self.is_verified,
            "is_suspended": self.is_suspended,
            "is_closed": self.is_closed,
            "is_enterprise": self.is_enterprise,
            "is_trial_active": self.is_trial_active,
            "can_use_ai": self.can_use_ai,
            "can_use_agents": self.can_use_agents,
            "can_run_autonomous_actions": (
                self.can_run_autonomous_actions
            ),
            "tags": self.tags,
            "is_deleted": self.is_deleted,
            "version": self.version,
            "created_at": datetime_string(self.created_at),
            "updated_at": datetime_string(self.updated_at),
        }

        if include_sensitive:
            result.update({
                "billing_email": self.billing_email,
                "address_line_1": self.address_line_1,
                "address_line_2": self.address_line_2,
                "postal_code": self.postal_code,
                "registration_number": self.registration_number,
                "tax_registration_reference": (
                    self.tax_registration_reference
                ),
                "legal_entity_type": self.legal_entity_type,
                "owner_user_id": self.owner_user_id,
                "primary_admin_user_id": (
                    self.primary_admin_user_id
                ),
                "billing_customer_reference": (
                    self.billing_customer_reference
                ),
                "subscription_reference": (
                    self.subscription_reference
                ),
                "security_policy": self.security_policy,
                "privacy_settings": self.privacy_settings,
                "ai_governance_settings": (
                    self.ai_governance_settings
                ),
                "inventory_settings": self.inventory_settings,
                "demand_forecasting_settings": (
                    self.demand_forecasting_settings
                ),
                "supplier_management_settings": (
                    self.supplier_management_settings
                ),
                "logistics_settings": self.logistics_settings,
                "notification_settings": (
                    self.notification_settings
                ),
                "integration_settings": (
                    self.integration_settings
                ),
                "branding_settings": self.branding_settings,
                "dashboard_settings": self.dashboard_settings,
                "organization_metadata": (
                    self.organization_metadata
                ),
                "verification_notes": self.verification_notes,
                "suspension_reason": self.suspension_reason,
                "closure_reason": self.closure_reason,
            })

        return result

    def __repr__(self) -> str:
        return (
            f"<Organization("
            f"id={self.id}, "
            f"slug={self.slug}, "
            f"name={self.name}, "
            f"status={enum_value(self.status)}, "
            f"plan={enum_value(self.plan)}"
            f")>"
        )
