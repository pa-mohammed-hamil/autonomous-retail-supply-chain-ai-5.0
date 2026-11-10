from __future__ import annotations

"""Planned module: refund. Implementation pending."""

"""
backend/models/refund.py

Autonomous Retail Supply Chain AI 5.0
Enterprise Refund Management Model

Features:
- Multi-tenant refund management
- Full and partial refunds
- Customer, order and product references
- Return and quality issue tracking
- Multiple refund reasons and methods
- Human approval workflows
- AI fraud and refund risk assessment
- Payment gateway and transaction references
- Refund processing, settlement and failure
- Idempotency and retry tracking
- Financial reconciliation
- Audit history and soft deletion
- Optimistic concurrency control

IMPORTANT:
This model records refund state only.

Actual payment gateway operations, refunds,
authorization, ledger posting and reconciliation
must be performed by application services.

Never store raw payment card information.
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

MONEY_QUANTUM = Decimal("0.0001")
MONEY_MAX = Decimal("100000000000000")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_refund_number() -> str:
    return f"REF-{uuid.uuid4().hex[:16].upper()}"


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


def require_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def nonnegative_decimal(
    value: Decimal | str | int | float,
    field: str,
    *,
    allow_zero: bool = True,
) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")

    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(
            f"{field} must be numeric"
        ) from None

    if not result.is_finite():
        raise ValueError(f"{field} must be finite")

    if result < 0 or (not allow_zero and result == 0):
        raise ValueError(
            f"{field} must be nonnegative"
            if allow_zero
            else f"{field} must be positive"
        )

    if result >= MONEY_MAX:
        raise ValueError(
            f"{field} exceeds supported precision"
        )

    if result != result.quantize(MONEY_QUANTUM):
        raise ValueError(
            f"{field} supports at most 4 decimal places"
        )

    return result


def score_decimal(
    value: Decimal | str | int | float,
    field: str,
) -> Decimal:
    result = nonnegative_decimal(value, field)

    if result > 1:
        raise ValueError(
            f"{field} must be between 0 and 1"
        )

    return result


def aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError(
            "Timezone-aware datetime required"
        )
    return value.astimezone(timezone.utc)


def enum_value(value: enum.Enum | None):
    return value.value if value is not None else None


def iso(value: datetime | None):
    return value.isoformat() if value else None


def decimal_string(value: Decimal | None):
    return str(value) if value is not None else None


# ============================================================
# ENUMS
# ============================================================

class RefundStatus(str, enum.Enum):
    DRAFT = "draft"
    REQUESTED = "requested"
    UNDER_REVIEW = "under_review"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROCESSING = "processing"
    PENDING_SETTLEMENT = "pending_settlement"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class RefundType(str, enum.Enum):
    FULL = "full"
    PARTIAL = "partial"
    ITEM_LEVEL = "item_level"
    SHIPPING_ONLY = "shipping_only"
    TAX_ADJUSTMENT = "tax_adjustment"
    PRICE_ADJUSTMENT = "price_adjustment"
    GOODWILL = "goodwill"


class RefundReason(str, enum.Enum):
    CUSTOMER_RETURN = "customer_return"
    DAMAGED_PRODUCT = "damaged_product"
    DEFECTIVE_PRODUCT = "defective_product"
    WRONG_PRODUCT = "wrong_product"
    MISSING_PRODUCT = "missing_product"
    DELIVERY_FAILURE = "delivery_failure"
    DELIVERY_DELAY = "delivery_delay"
    ORDER_CANCELLED = "order_cancelled"
    DUPLICATE_PAYMENT = "duplicate_payment"
    OVERCHARGED = "overcharged"
    PRODUCT_RECALL = "product_recall"
    QUALITY_ISSUE = "quality_issue"
    CUSTOMER_DISSATISFACTION = "customer_dissatisfaction"
    POLICY_EXCEPTION = "policy_exception"
    OTHER = "other"


class RefundMethod(str, enum.Enum):
    ORIGINAL_PAYMENT = "original_payment"
    BANK_TRANSFER = "bank_transfer"
    UPI = "upi"
    WALLET = "wallet"
    STORE_CREDIT = "store_credit"
    GIFT_CARD = "gift_card"
    MANUAL = "manual"
    OTHER = "other"


class RefundSource(str, enum.Enum):
    CUSTOMER = "customer"
    SUPPORT_AGENT = "support_agent"
    ADMIN = "admin"
    ORDER_SERVICE = "order_service"
    RETURN_SERVICE = "return_service"
    PAYMENT_GATEWAY = "payment_gateway"
    RULE_ENGINE = "rule_engine"
    AI_AGENT = "ai_agent"
    API = "api"


class RefundApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RefundRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class RefundReconciliationStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    PENDING = "pending"
    MATCHED = "matched"
    MISMATCHED = "mismatched"
    FAILED = "failed"


class RefundPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"


# ============================================================
# REFUND MODEL
# ============================================================

class Refund(Base):
    __tablename__ = "refunds"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "refund_number",
            name="uq_refund_org_number",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_refund_org_idempotency",
        ),
        CheckConstraint(
            "requested_amount > 0",
            name="refund_requested_positive",
        ),
        CheckConstraint(
            "approved_amount >= 0",
            name="refund_approved_nonnegative",
        ),
        CheckConstraint(
            "refunded_amount >= 0",
            name="refund_paid_nonnegative",
        ),
        CheckConstraint(
            "refunded_amount <= approved_amount",
            name="refund_paid_not_excess",
        ),
        CheckConstraint(
            "approved_amount <= requested_amount",
            name="refund_approved_not_excess",
        ),
        CheckConstraint(
            "tax_refund_amount >= 0",
            name="refund_tax_nonnegative",
        ),
        CheckConstraint(
            "shipping_refund_amount >= 0",
            name="refund_shipping_nonnegative",
        ),
        CheckConstraint(
            "processing_fee >= 0",
            name="refund_fee_nonnegative",
        ),
        CheckConstraint(
            "retry_count >= 0",
            name="refund_retry_nonnegative",
        ),
        CheckConstraint(
            "max_retries >= 0",
            name="refund_max_retries_nonnegative",
        ),
        CheckConstraint(
            "ai_risk_score IS NULL OR "
            "(ai_risk_score >= 0 AND ai_risk_score <= 1)",
            name="refund_ai_risk_range",
        ),
        CheckConstraint(
            "ai_confidence IS NULL OR "
            "(ai_confidence >= 0 AND ai_confidence <= 1)",
            name="refund_ai_confidence_range",
        ),
        CheckConstraint(
            "version >= 1",
            name="refund_version_positive",
        ),
        Index(
            "ix_refund_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_refund_org_customer",
            "organization_id",
            "customer_id",
        ),
        Index(
            "ix_refund_org_order",
            "organization_id",
            "order_id",
        ),
        Index(
            "ix_refund_org_payment",
            "organization_id",
            "payment_transaction_id",
        ),
        Index(
            "ix_refund_org_created",
            "organization_id",
            "created_at",
        ),
    )

    # --------------------------------------------------------
    # IDENTITY
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

    refund_number: Mapped[str] = mapped_column(
        String(50),
        default=generate_refund_number,
        nullable=False,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # --------------------------------------------------------
    # REFUND DETAILS
    # --------------------------------------------------------

    status: Mapped[RefundStatus] = mapped_column(
        enum_column(
            RefundStatus,
            "refund_status",
        ),
        default=RefundStatus.DRAFT,
        nullable=False,
    )

    refund_type: Mapped[RefundType] = mapped_column(
        enum_column(
            RefundType,
            "refund_type",
        ),
        default=RefundType.PARTIAL,
        nullable=False,
    )

    reason: Mapped[RefundReason] = mapped_column(
        enum_column(
            RefundReason,
            "refund_reason",
        ),
        nullable=False,
    )

    source: Mapped[RefundSource] = mapped_column(
        enum_column(
            RefundSource,
            "refund_source",
        ),
        default=RefundSource.CUSTOMER,
        nullable=False,
    )

    priority: Mapped[RefundPriority] = mapped_column(
        enum_column(
            RefundPriority,
            "refund_priority",
        ),
        default=RefundPriority.NORMAL,
        nullable=False,
    )

    reason_description: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    customer_notes: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    internal_notes: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # CUSTOMER / ORDER REFERENCES
    # --------------------------------------------------------

    customer_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    order_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    fulfillment_order_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    delivery_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    return_request_id: Mapped[
        str | None
    ] = mapped_column(
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

    # --------------------------------------------------------
    # REFUNDED PRODUCTS
    # --------------------------------------------------------

    refund_items: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    requires_return: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    return_received: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    return_verified_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # FINANCIALS
    # --------------------------------------------------------

    currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    requested_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        nullable=False,
    )

    approved_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    refunded_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    tax_refund_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    shipping_refund_amount: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    processing_fee: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=Decimal("0"),
        nullable=False,
    )

    # --------------------------------------------------------
    # PAYMENT
    # --------------------------------------------------------

    refund_method: Mapped[
        RefundMethod
    ] = mapped_column(
        enum_column(
            RefundMethod,
            "refund_method",
        ),
        default=RefundMethod.ORIGINAL_PAYMENT,
        nullable=False,
    )

    payment_transaction_id: Mapped[
        str | None
    ] = mapped_column(
        String(150),
        nullable=True,
    )

    payment_gateway: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    gateway_refund_id: Mapped[
        str | None
    ] = mapped_column(
        String(200),
        nullable=True,
    )

    gateway_status: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    gateway_response: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # AI FRAUD / RISK INTELLIGENCE
    # --------------------------------------------------------

    ai_model_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    ai_agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    ai_risk_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    ai_confidence: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    ai_risk_level: Mapped[
        RefundRiskLevel
    ] = mapped_column(
        enum_column(
            RefundRiskLevel,
            "refund_risk_level",
        ),
        default=RefundRiskLevel.UNKNOWN,
        nullable=False,
    )

    ai_recommendation: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    ai_explanation: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    ai_risk_factors: Mapped[
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

    # --------------------------------------------------------
    # APPROVAL
    # --------------------------------------------------------

    requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    approval_status: Mapped[
        RefundApprovalStatus
    ] = mapped_column(
        enum_column(
            RefundApprovalStatus,
            "refund_approval_status",
        ),
        default=RefundApprovalStatus.NOT_REQUIRED,
        nullable=False,
    )

    approval_request_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    requested_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    reviewed_by: Mapped[str | None] = mapped_column(
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

    rejected_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    rejected_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    rejection_reason: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # PROCESSING / RETRIES
    # --------------------------------------------------------

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

    refunded_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
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

    next_retry_at: Mapped[
        datetime | None
    ] = mapped_column(
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

    # --------------------------------------------------------
    # RECONCILIATION
    # --------------------------------------------------------

    reconciliation_status: Mapped[
        RefundReconciliationStatus
    ] = mapped_column(
        enum_column(
            RefundReconciliationStatus,
            "refund_reconciliation_status",
        ),
        default=RefundReconciliationStatus.NOT_STARTED,
        nullable=False,
    )

    reconciliation_reference: Mapped[
        str | None
    ] = mapped_column(
        String(200),
        nullable=True,
    )

    reconciled_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    reconciled_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # CANCELLATION / EXPIRATION
    # --------------------------------------------------------

    expires_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    cancelled_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    cancelled_by: Mapped[str | None] = mapped_column(
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
    # AUDIT / METADATA
    # --------------------------------------------------------

    refund_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    refund_history: Mapped[
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
    def remaining_amount(self) -> Decimal:
        return (
            self.approved_amount
            - self.refunded_amount
        )

    @property
    def is_fully_refunded(self) -> bool:
        return (
            self.approved_amount > 0
            and self.refunded_amount
            >= self.approved_amount
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            RefundStatus.REFUNDED,
            RefundStatus.REJECTED,
            RefundStatus.CANCELLED,
            RefundStatus.EXPIRED,
        }

    @property
    def is_approved(self) -> bool:
        return (
            self.approval_status
            == RefundApprovalStatus.APPROVED
            and self.approved_amount > 0
        )

    @property
    def is_expired(self) -> bool:
        return (
            self.expires_at is not None
            and utc_now() >= aware_datetime(
                self.expires_at
            )
        )

    @property
    def can_retry(self) -> bool:
        return (
            not self.is_deleted
            and self.status == RefundStatus.FAILED
            and self.retry_count < self.max_retries
            and not self.is_expired
        )

    @property
    def can_process(self) -> bool:
        return (
            not self.is_deleted
            and self.status == RefundStatus.APPROVED
            and self.is_approved
            and self.remaining_amount > 0
            and (
                not self.requires_return
                or self.return_received
            )
            and not self.is_expired
        )

    # ========================================================
    # INTERNAL METHODS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_not_deleted(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Refund has been deleted"
            )

    def _record_event(
        self,
        event: str,
        *,
        actor_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        history = list(self.refund_history or [])

        history.append({
            "event_id": str(uuid.uuid4()),
            "event": event,
            "actor_id": actor_id,
            "timestamp": utc_now().isoformat(),
            "details": details or {},
        })

        self.refund_history = history
        self._touch()

    # ========================================================
    # ADD REFUND ITEM
    # ========================================================

    def add_refund_item(
        self,
        *,
        product_id: str,
        sku: str,
        quantity: Decimal | str | int | float,
        amount: Decimal | str | int | float,
        actor_id: str,
        reason: str | None = None,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != RefundStatus.DRAFT:
            raise ValueError(
                "Refund items can only be edited in draft"
            )

        quantity = nonnegative_decimal(
            quantity,
            "quantity",
            allow_zero=False,
        )
        amount = nonnegative_decimal(
            amount,
            "amount",
            allow_zero=False,
        )

        items = list(self.refund_items or [])

        items.append({
            "item_id": str(uuid.uuid4()),
            "product_id": require_text(
                product_id,
                "Product ID",
            ),
            "sku": require_text(sku, "SKU"),
            "quantity": str(quantity),
            "amount": str(amount),
            "reason": reason,
        })

        self.refund_items = items

        self._record_event(
            "refund_item_added",
            actor_id=actor_id,
            details={
                "product_id": product_id,
                "amount": str(amount),
            },
        )

    # ========================================================
    # SUBMIT REFUND REQUEST
    # ========================================================

    def submit(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != RefundStatus.DRAFT:
            raise ValueError(
                "Only draft refunds can be submitted"
            )

        if self.is_expired:
            raise ValueError(
                "Refund request has expired"
            )

        if self.requested_amount <= 0:
            raise ValueError(
                "Refund amount must be positive"
            )

        self.requested_by = require_text(
            actor_id,
            "Actor ID",
        )
        self.status = RefundStatus.REQUESTED

        self._record_event(
            "refund_requested",
            actor_id=actor_id,
        )

    # ========================================================
    # START REVIEW
    # ========================================================

    def start_review(
        self,
        *,
        reviewer_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != RefundStatus.REQUESTED:
            raise ValueError(
                "Refund is not awaiting review"
            )

        self.status = RefundStatus.UNDER_REVIEW
        self.reviewed_by = require_text(
            reviewer_id,
            "Reviewer ID",
        )

        self._record_event(
            "refund_review_started",
            actor_id=reviewer_id,
        )

    # ========================================================
    # UPDATE AI RISK ASSESSMENT
    # ========================================================

    def update_ai_risk(
        self,
        *,
        model_id: str,
        risk_score: Decimal | str | int | float,
        confidence: Decimal | str | int | float,
        risk_level: RefundRiskLevel,
        recommendation: str,
        explanation: str,
        risk_factors: list[dict[str, Any]],
        agent_run_id: str | None = None,
    ) -> None:
        self._ensure_not_deleted()

        if self.status not in {
            RefundStatus.DRAFT,
            RefundStatus.REQUESTED,
            RefundStatus.UNDER_REVIEW,
            RefundStatus.PENDING_APPROVAL,
        }:
            raise ValueError(
                "Risk assessment cannot be updated"
            )

        self.ai_model_id = require_text(
            model_id,
            "Model ID",
        )
        self.ai_agent_run_id = agent_run_id
        self.ai_risk_score = score_decimal(
            risk_score,
            "risk_score",
        )
        self.ai_confidence = score_decimal(
            confidence,
            "confidence",
        )
        self.ai_risk_level = risk_level
        self.ai_recommendation = require_text(
            recommendation,
            "Recommendation",
        )
        self.ai_explanation = require_text(
            explanation,
            "Explanation",
        )
        self.ai_risk_factors = [
            dict(item) for item in risk_factors
        ]
        self.ai_analyzed_at = utc_now()

        self._record_event(
            "refund_ai_risk_updated",
            details={
                "model_id": model_id,
                "risk_level": risk_level.value,
            },
        )

    # ========================================================
    # VERIFY RETURN
    # ========================================================

    def verify_return(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if not self.requires_return:
            raise ValueError(
                "Refund does not require a return"
            )

        if self.status not in {
            RefundStatus.REQUESTED,
            RefundStatus.UNDER_REVIEW,
            RefundStatus.PENDING_APPROVAL,
            RefundStatus.APPROVED,
        }:
            raise ValueError(
                "Return cannot be verified in current state"
            )

        # Receiving service must verify the
        # physical return and quality inspection.

        self.return_received = True
        self.return_verified_at = utc_now()

        self._record_event(
            "refund_return_verified",
            actor_id=actor_id,
        )

    # ========================================================
    # REQUEST APPROVAL
    # ========================================================

    def request_approval(
        self,
        *,
        actor_id: str,
        approval_request_id: str | None = None,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != RefundStatus.UNDER_REVIEW:
            raise ValueError(
                "Refund must be under review"
            )

        if self.requires_approval:
            self.approval_request_id = require_text(
                approval_request_id,
                "Approval request ID",
            )
            self.approval_status = (
                RefundApprovalStatus.PENDING
            )
            self.status = RefundStatus.PENDING_APPROVAL
        else:
            self.approval_status = (
                RefundApprovalStatus.APPROVED
            )
            self.approved_amount = (
                self.requested_amount
            )
            self.approved_by = actor_id
            self.approved_at = utc_now()
            self.status = RefundStatus.APPROVED

        self._record_event(
            "refund_approval_requested",
            actor_id=actor_id,
        )

    # ========================================================
    # APPROVE REFUND
    # ========================================================

    def approve(
        self,
        *,
        approver_id: str,
        approved_amount: Decimal | str | int | float,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != RefundStatus.PENDING_APPROVAL:
            raise ValueError(
                "Refund is not pending approval"
            )

        amount = nonnegative_decimal(
            approved_amount,
            "approved_amount",
            allow_zero=False,
        )

        if amount > self.requested_amount:
            raise ValueError(
                "Approved amount exceeds requested amount"
            )

        # Service must validate payment eligibility,
        # remaining refundable order balance,
        # approver authority and linked approval.

        self.approved_amount = amount
        self.approval_status = (
            RefundApprovalStatus.APPROVED
        )
        self.approved_by = require_text(
            approver_id,
            "Approver ID",
        )
        self.approved_at = utc_now()
        self.status = RefundStatus.APPROVED

        self._record_event(
            "refund_approved",
            actor_id=approver_id,
            details={
                "approved_amount": str(amount),
            },
        )

    # ========================================================
    # REJECT REFUND
    # ========================================================

    def reject(
        self,
        *,
        reviewer_id: str,
        reason: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status not in {
            RefundStatus.REQUESTED,
            RefundStatus.UNDER_REVIEW,
            RefundStatus.PENDING_APPROVAL,
        }:
            raise ValueError(
                "Refund cannot be rejected"
            )

        self.approval_status = (
            RefundApprovalStatus.REJECTED
        )
        self.status = RefundStatus.REJECTED
        self.rejected_by = require_text(
            reviewer_id,
            "Reviewer ID",
        )
        self.rejected_at = utc_now()
        self.rejection_reason = require_text(
            reason,
            "Rejection reason",
        )

        self._record_event(
            "refund_rejected",
            actor_id=reviewer_id,
            details={"reason": reason},
        )

    # ========================================================
    # START PROCESSING
    # ========================================================

    def start_processing(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if not self.can_process:
            raise ValueError(
                "Refund is not eligible for processing"
            )

        self.status = RefundStatus.PROCESSING
        self.processing_started_at = utc_now()
        self.processed_by = require_text(
            actor_id,
            "Actor ID",
        )

        self._record_event(
            "refund_processing_started",
            actor_id=actor_id,
        )

    # ========================================================
    # MARK PENDING SETTLEMENT
    # ========================================================

    def mark_pending_settlement(
        self,
        *,
        gateway_refund_id: str,
        actor_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != RefundStatus.PROCESSING:
            raise ValueError(
                "Refund is not processing"
            )

        self.gateway_refund_id = require_text(
            gateway_refund_id,
            "Gateway refund ID",
        )
        self.status = RefundStatus.PENDING_SETTLEMENT

        self._record_event(
            "refund_pending_settlement",
            actor_id=actor_id,
        )

    # ========================================================
    # RECORD REFUND SETTLEMENT
    # ========================================================

    def record_settlement(
        self,
        *,
        amount: Decimal | str | int | float,
        gateway_refund_id: str,
        actor_id: str,
        settlement_reference: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status not in {
            RefundStatus.PROCESSING,
            RefundStatus.PENDING_SETTLEMENT,
            RefundStatus.PARTIALLY_REFUNDED,
        }:
            raise ValueError(
                "Refund is not awaiting settlement"
            )

        amount = nonnegative_decimal(
            amount,
            "amount",
            allow_zero=False,
        )

        if amount > self.remaining_amount:
            raise ValueError(
                "Settlement exceeds remaining refund"
            )

        # The payment service must verify the gateway
        # settlement and deduplicate its transaction
        # reference before invoking this method.

        self.refunded_amount += amount
        self.gateway_refund_id = require_text(
            gateway_refund_id,
            "Gateway refund ID",
        )

        if self.is_fully_refunded:
            self.status = RefundStatus.REFUNDED
            self.refunded_at = utc_now()
        else:
            self.status = RefundStatus.PARTIALLY_REFUNDED

        self.reconciliation_status = (
            RefundReconciliationStatus.PENDING
        )

        self._record_event(
            "refund_settlement_recorded",
            actor_id=actor_id,
            details={
                "amount": str(amount),
                "settlement_reference": require_text(
                    settlement_reference,
                    "Settlement reference",
                ),
            },
        )

    # ========================================================
    # RECORD FAILURE
    # ========================================================

    def mark_failed(
        self,
        *,
        failure_code: str,
        reason: str,
        actor_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status not in {
            RefundStatus.PROCESSING,
            RefundStatus.PENDING_SETTLEMENT,
        }:
            raise ValueError(
                "Refund is not being processed"
            )

        self.status = RefundStatus.FAILED
        self.failure_code = require_text(
            failure_code,
            "Failure code",
        )
        self.failure_reason = require_text(
            reason,
            "Failure reason",
        )

        self._record_event(
            "refund_processing_failed",
            actor_id=actor_id,
            details={
                "failure_code": failure_code,
                "reason": reason,
            },
        )

    # ========================================================
    # RETRY REFUND
    # ========================================================

    def retry(
        self,
        *,
        actor_id: str,
    ) -> None:
        if not self.can_retry:
            raise ValueError(
                "Refund is not eligible for retry"
            )

        # Gateway status must be reconciled before
        # retrying to prevent duplicate refunds.

        self.retry_count += 1
        self.status = RefundStatus.PROCESSING
        self.processing_started_at = utc_now()
        self.failure_code = None
        self.failure_reason = None
        self.next_retry_at = None

        self._record_event(
            "refund_retry_started",
            actor_id=actor_id,
            details={
                "retry_count": self.retry_count,
            },
        )

    # ========================================================
    # RECONCILE
    # ========================================================

    def reconcile(
        self,
        *,
        actor_id: str,
        matched: bool,
        reference: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status not in {
            RefundStatus.REFUNDED,
            RefundStatus.PARTIALLY_REFUNDED,
        }:
            raise ValueError(
                "Refund must have a recorded settlement"
            )

        self.reconciliation_status = (
            RefundReconciliationStatus.MATCHED
            if matched
            else RefundReconciliationStatus.MISMATCHED
        )
        self.reconciliation_reference = require_text(
            reference,
            "Reconciliation reference",
        )
        self.reconciled_at = utc_now()
        self.reconciled_by = require_text(
            actor_id,
            "Actor ID",
        )

        self._record_event(
            "refund_reconciled",
            actor_id=actor_id,
            details={
                "matched": matched,
                "reference": reference,
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
        self._ensure_not_deleted()

        if self.status not in {
            RefundStatus.DRAFT,
            RefundStatus.REQUESTED,
            RefundStatus.UNDER_REVIEW,
            RefundStatus.PENDING_APPROVAL,
            RefundStatus.APPROVED,
        }:
            raise ValueError(
                "Refund cannot be cancelled after processing"
            )

        self.status = RefundStatus.CANCELLED
        self.cancelled_at = utc_now()
        self.cancelled_by = require_text(
            actor_id,
            "Actor ID",
        )
        self.cancellation_reason = require_text(
            reason,
            "Cancellation reason",
        )

        self._record_event(
            "refund_cancelled",
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # EXPIRE
    # ========================================================

    def expire(
        self,
        *,
        actor_id: str | None = None,
    ) -> None:
        self._ensure_not_deleted()

        if not self.is_expired:
            raise ValueError(
                "Refund has not reached expiration"
            )

        if self.status not in {
            RefundStatus.DRAFT,
            RefundStatus.REQUESTED,
            RefundStatus.UNDER_REVIEW,
            RefundStatus.PENDING_APPROVAL,
            RefundStatus.APPROVED,
        }:
            raise ValueError(
                "Refund cannot expire in current state"
            )

        self.status = RefundStatus.EXPIRED

        self._record_event(
            "refund_expired",
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
        self._ensure_not_deleted()

        if self.status not in {
            RefundStatus.DRAFT,
            RefundStatus.REJECTED,
            RefundStatus.CANCELLED,
            RefundStatus.EXPIRED,
        }:
            raise ValueError(
                "Refund cannot be deleted in current state"
            )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = require_text(
            actor_id,
            "Actor ID",
        )

        self._record_event(
            "refund_soft_deleted",
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
        result = {
            "id": self.id,
            "organization_id": self.organization_id,
            "refund_number": self.refund_number,
            "status": enum_value(self.status),
            "refund_type": enum_value(
                self.refund_type
            ),
            "reason": enum_value(self.reason),
            "source": enum_value(self.source),
            "priority": enum_value(self.priority),
            "reason_description": (
                self.reason_description
            ),
            "customer_notes": self.customer_notes,

            "customer_id": self.customer_id,
            "order_id": self.order_id,
            "fulfillment_order_id": (
                self.fulfillment_order_id
            ),
            "delivery_id": self.delivery_id,
            "return_request_id": (
                self.return_request_id
            ),
            "product_quality_issue_id": (
                self.product_quality_issue_id
            ),
            "incident_id": self.incident_id,

            "refund_items": self.refund_items,
            "requires_return": self.requires_return,
            "return_received": self.return_received,
            "return_verified_at": iso(
                self.return_verified_at
            ),

            "currency": self.currency,
            "requested_amount": decimal_string(
                self.requested_amount
            ),
            "approved_amount": decimal_string(
                self.approved_amount
            ),
            "refunded_amount": decimal_string(
                self.refunded_amount
            ),
            "remaining_amount": decimal_string(
                self.remaining_amount
            ),
            "tax_refund_amount": decimal_string(
                self.tax_refund_amount
            ),
            "shipping_refund_amount": decimal_string(
                self.shipping_refund_amount
            ),
            "processing_fee": decimal_string(
                self.processing_fee
            ),

            "refund_method": enum_value(
                self.refund_method
            ),
            "payment_gateway": self.payment_gateway,
            "gateway_status": self.gateway_status,

            "requires_approval": self.requires_approval,
            "approval_status": enum_value(
                self.approval_status
            ),
            "approval_request_id": (
                self.approval_request_id
            ),
            "requested_by": self.requested_by,
            "reviewed_by": self.reviewed_by,
            "approved_by": self.approved_by,
            "approved_at": iso(self.approved_at),
            "rejected_at": iso(self.rejected_at),
            "rejection_reason": self.rejection_reason,

            "processing_started_at": iso(
                self.processing_started_at
            ),
            "refunded_at": iso(self.refunded_at),
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,

            "reconciliation_status": enum_value(
                self.reconciliation_status
            ),
            "reconciled_at": iso(self.reconciled_at),

            "expires_at": iso(self.expires_at),
            "cancelled_at": iso(self.cancelled_at),
            "cancellation_reason": (
                self.cancellation_reason
            ),

            "is_fully_refunded": (
                self.is_fully_refunded
            ),
            "is_approved": self.is_approved,
            "is_terminal": self.is_terminal,
            "is_expired": self.is_expired,
            "can_retry": self.can_retry,
            "can_process": self.can_process,

            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "is_deleted": self.is_deleted,
            "version": self.version,
        }

        if include_internal:
            result.update({
                "internal_notes": self.internal_notes,
                "payment_transaction_id": (
                    self.payment_transaction_id
                ),
                "gateway_refund_id": (
                    self.gateway_refund_id
                ),
                "gateway_response": (
                    self.gateway_response
                ),
                "ai_model_id": self.ai_model_id,
                "ai_agent_run_id": (
                    self.ai_agent_run_id
                ),
                "ai_risk_score": decimal_string(
                    self.ai_risk_score
                ),
                "ai_confidence": decimal_string(
                    self.ai_confidence
                ),
                "ai_risk_level": enum_value(
                    self.ai_risk_level
                ),
                "ai_recommendation": (
                    self.ai_recommendation
                ),
                "ai_explanation": self.ai_explanation,
                "ai_risk_factors": (
                    self.ai_risk_factors
                ),
                "ai_analyzed_at": iso(
                    self.ai_analyzed_at
                ),
                "failure_code": self.failure_code,
                "failure_reason": self.failure_reason,
                "next_retry_at": iso(
                    self.next_retry_at
                ),
                "reconciliation_reference": (
                    self.reconciliation_reference
                ),
                "refund_metadata": self.refund_metadata,
                "trace_id": self.trace_id,
                "correlation_id": self.correlation_id,
                "created_by": self.created_by,
                "updated_by": self.updated_by,
                "deleted_at": iso(self.deleted_at),
                "deleted_by": self.deleted_by,
            })

        if include_history:
            result["refund_history"] = (
                self.refund_history
            )

        return result

    def __repr__(self) -> str:
        return (
            f"<Refund("
            f"id={self.id}, "
            f"refund_number={self.refund_number}, "
            f"status={enum_value(self.status)}, "
            f"requested_amount={self.requested_amount}"
            f")>"
        )
