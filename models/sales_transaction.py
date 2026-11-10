from __future__ import annotations

"""Planned module: sales transaction. Implementation pending."""
"""
backend/models/sales_transaction.py

Autonomous Retail Supply Chain AI 5.0
Enterprise Sales Financial Transaction Model

Features:
- Multi-tenant transaction isolation
- Sale and customer references
- Payment, refund, reversal and chargeback records
- Payment authorization and capture
- Settlement and reconciliation
- Multiple payment channels and methods
- Provider and gateway references
- AI fraud detection and risk analysis
- Human review and approval
- Immutable transaction amount after submission
- Idempotency and duplicate-reference protection
- Financial audit trail
- Soft deletion for draft records
- Optimistic concurrency control

SECURITY:
- Never store card numbers, CVVs, PINs or payment tokens
  that expose payment credentials.
- Never store gateway API secrets.
- Verify provider webhooks cryptographically.
- Do not trust client-submitted payment success flags.
- Perform all financial operations through payment services.
- Use database transactions for ledger and sale updates.
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
# CONSTANTS
# ============================================================

ZERO = Decimal("0.0000")
QUANTUM = Decimal("0.0001")
MAX_AMOUNT = Decimal("100000000000000")


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_transaction_number() -> str:
    return f"TXN-{uuid.uuid4().hex[:20].upper()}"


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


def required_text(
    value: str,
    field: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")

    return value.strip()


def decimal_value(
    value: Decimal | str | int | float,
    field: str,
    *,
    positive: bool = False,
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
        raise ValueError(
            f"{field} must be finite"
        )

    if result < 0:
        raise ValueError(
            f"{field} cannot be negative"
        )

    if positive and result == 0:
        raise ValueError(
            f"{field} must be positive"
        )

    if result >= MAX_AMOUNT:
        raise ValueError(
            f"{field} exceeds supported precision"
        )

    if result != result.quantize(QUANTUM):
        raise ValueError(
            f"{field} supports at most 4 decimal places"
        )

    return result


def score_value(
    value: Decimal | str | int | float,
    field: str,
) -> Decimal:
    result = decimal_value(value, field)

    if result > 1:
        raise ValueError(
            f"{field} must be between 0 and 1"
        )

    return result


def enum_value(value):
    if isinstance(value, enum.Enum):
        return value.value

    return value


def iso(value: datetime | None):
    return value.isoformat() if value else None


def decimal_string(value):
    return str(value) if value is not None else None


def validate_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("Expected datetime")

    if value.tzinfo is None:
        raise ValueError(
            "Timezone-aware datetime required"
        )

    return value.astimezone(timezone.utc)


# ============================================================
# ENUMS
# ============================================================

class SalesTransactionType(str, enum.Enum):
    PAYMENT = "payment"
    AUTHORIZATION = "authorization"
    CAPTURE = "capture"
    REFUND = "refund"
    PARTIAL_REFUND = "partial_refund"
    REVERSAL = "reversal"
    VOID = "void"
    CHARGEBACK = "chargeback"
    CHARGEBACK_REVERSAL = "chargeback_reversal"
    ADJUSTMENT = "adjustment"


class SalesTransactionStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    INITIATED = "initiated"
    PENDING = "pending"
    AUTHORIZED = "authorized"
    PROCESSING = "processing"
    CAPTURED = "captured"
    SETTLED = "settled"
    COMPLETED = "completed"
    FAILED = "failed"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REVERSED = "reversed"
    DISPUTED = "disputed"
    ON_HOLD = "on_hold"


class SalesPaymentMethod(str, enum.Enum):
    CASH = "cash"
    UPI = "upi"
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    NET_BANKING = "net_banking"
    BANK_TRANSFER = "bank_transfer"
    WALLET = "wallet"
    GIFT_CARD = "gift_card"
    STORE_CREDIT = "store_credit"
    COD = "cash_on_delivery"
    OTHER = "other"


class SalesTransactionChannel(str, enum.Enum):
    POS = "pos"
    ECOMMERCE = "ecommerce"
    MOBILE_APP = "mobile_app"
    MARKETPLACE = "marketplace"
    B2B = "b2b"
    API = "api"
    MANUAL = "manual"


class SalesTransactionSource(str, enum.Enum):
    CUSTOMER = "customer"
    POS = "pos"
    ECOMMERCE = "ecommerce"
    ERP = "erp"
    PAYMENT_GATEWAY = "payment_gateway"
    BANK = "bank"
    WEBHOOK = "webhook"
    ADMIN = "admin"
    AI_AGENT = "ai_agent"
    SYSTEM = "system"


class SalesTransactionRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class SalesTransactionApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SalesReconciliationStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    PENDING = "pending"
    MATCHED = "matched"
    MISMATCHED = "mismatched"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"


class SalesFraudReviewStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    UNDER_REVIEW = "under_review"
    CLEARED = "cleared"
    BLOCKED = "blocked"


# ============================================================
# SALES TRANSACTION
# ============================================================

class SalesTransaction(Base):
    __tablename__ = "sales_transactions"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "transaction_number",
            name="uq_sales_txn_org_number",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_sales_txn_org_idempotency",
        ),
        UniqueConstraint(
            "organization_id",
            "provider_name",
            "provider_transaction_id",
            name="uq_sales_txn_provider_reference",
        ),
        CheckConstraint(
            "amount > 0",
            name="sales_txn_amount_positive",
        ),
        CheckConstraint(
            "authorized_amount >= 0",
            name="sales_txn_authorized_nonnegative",
        ),
        CheckConstraint(
            "captured_amount >= 0",
            name="sales_txn_captured_nonnegative",
        ),
        CheckConstraint(
            "settled_amount >= 0",
            name="sales_txn_settled_nonnegative",
        ),
        CheckConstraint(
            "refunded_amount >= 0",
            name="sales_txn_refunded_nonnegative",
        ),
        CheckConstraint(
            "processing_fee >= 0",
            name="sales_txn_fee_nonnegative",
        ),
        CheckConstraint(
            "tax_amount >= 0",
            name="sales_txn_tax_nonnegative",
        ),
        CheckConstraint(
            "captured_amount <= amount",
            name="sales_txn_capture_limit",
        ),
        CheckConstraint(
            "settled_amount <= captured_amount",
            name="sales_txn_settlement_limit",
        ),
        CheckConstraint(
            "refunded_amount <= captured_amount",
            name="sales_txn_refund_limit",
        ),
        CheckConstraint(
            "ai_fraud_score IS NULL OR "
            "(ai_fraud_score >= 0 AND ai_fraud_score <= 1)",
            name="sales_txn_fraud_score_range",
        ),
        CheckConstraint(
            "ai_confidence IS NULL OR "
            "(ai_confidence >= 0 AND ai_confidence <= 1)",
            name="sales_txn_ai_confidence_range",
        ),
        CheckConstraint(
            "version >= 1",
            name="sales_txn_version_positive",
        ),
        Index(
            "ix_sales_txn_org_sale",
            "organization_id",
            "sale_id",
        ),
        Index(
            "ix_sales_txn_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_sales_txn_org_customer",
            "organization_id",
            "customer_id",
        ),
        Index(
            "ix_sales_txn_org_created",
            "organization_id",
            "created_at",
        ),
        Index(
            "ix_sales_txn_org_reconciliation",
            "organization_id",
            "reconciliation_status",
        ),
    )

    # --------------------------------------------------------
    # IDENTITY
    # --------------------------------------------------------

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_uuid,
    )

    organization_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    transaction_number: Mapped[str] = mapped_column(
        String(60),
        default=new_transaction_number,
        nullable=False,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # --------------------------------------------------------
    # TRANSACTION DETAILS
    # --------------------------------------------------------

    transaction_type: Mapped[
        SalesTransactionType
    ] = mapped_column(
        enum_column(
            SalesTransactionType,
            "sales_transaction_type",
        ),
        default=SalesTransactionType.PAYMENT,
        nullable=False,
    )

    status: Mapped[
        SalesTransactionStatus
    ] = mapped_column(
        enum_column(
            SalesTransactionStatus,
            "sales_transaction_status",
        ),
        default=SalesTransactionStatus.DRAFT,
        nullable=False,
    )

    payment_method: Mapped[
        SalesPaymentMethod
    ] = mapped_column(
        enum_column(
            SalesPaymentMethod,
            "sales_transaction_payment_method",
        ),
        nullable=False,
    )

    channel: Mapped[
        SalesTransactionChannel
    ] = mapped_column(
        enum_column(
            SalesTransactionChannel,
            "sales_transaction_channel",
        ),
        default=SalesTransactionChannel.ECOMMERCE,
        nullable=False,
    )

    source: Mapped[
        SalesTransactionSource
    ] = mapped_column(
        enum_column(
            SalesTransactionSource,
            "sales_transaction_source",
        ),
        default=SalesTransactionSource.SYSTEM,
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # REFERENCES
    # --------------------------------------------------------

    sale_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    customer_id: Mapped[str | None] = mapped_column(
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

    refund_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    return_request_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    original_transaction_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    integration_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # AMOUNTS
    # --------------------------------------------------------

    currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        nullable=False,
    )

    authorized_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    captured_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    settled_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    refunded_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    processing_fee: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    # --------------------------------------------------------
    # PAYMENT PROVIDER
    # --------------------------------------------------------

    provider_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    provider_transaction_id: Mapped[
        str | None
    ] = mapped_column(
        String(200),
        nullable=True,
    )

    provider_payment_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    provider_order_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    provider_reference: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    payment_gateway_status: Mapped[
        str | None
    ] = mapped_column(
        String(100),
        nullable=True,
    )

    provider_response_code: Mapped[
        str | None
    ] = mapped_column(
        String(100),
        nullable=True,
    )

    provider_response_message: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # PAYMENT DETAILS
    # --------------------------------------------------------

    payment_instrument_label: Mapped[
        str | None
    ] = mapped_column(
        String(100),
        nullable=True,
    )

    payment_last_four: Mapped[
        str | None
    ] = mapped_column(
        String(4),
        nullable=True,
    )

    payment_network: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    bank_reference: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    upi_transaction_reference: Mapped[
        str | None
    ] = mapped_column(
        String(150),
        nullable=True,
    )

    # --------------------------------------------------------
    # AUTHORIZATION / CAPTURE / SETTLEMENT
    # --------------------------------------------------------

    initiated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    authorized_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    captured_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    settled_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    expires_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # RECONCILIATION
    # --------------------------------------------------------

    reconciliation_status: Mapped[
        SalesReconciliationStatus
    ] = mapped_column(
        enum_column(
            SalesReconciliationStatus,
            "sales_transaction_reconciliation_status",
        ),
        default=SalesReconciliationStatus.NOT_STARTED,
        nullable=False,
    )

    reconciliation_reference: Mapped[
        str | None
    ] = mapped_column(
        String(200),
        nullable=True,
    )

    reconciled_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    reconciled_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    reconciliation_notes: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # AI FRAUD DETECTION
    # --------------------------------------------------------

    ai_model_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    ai_agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    ai_fraud_score: Mapped[
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
        SalesTransactionRiskLevel
    ] = mapped_column(
        enum_column(
            SalesTransactionRiskLevel,
            "sales_transaction_risk_level",
        ),
        default=SalesTransactionRiskLevel.UNKNOWN,
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

    fraud_review_status: Mapped[
        SalesFraudReviewStatus
    ] = mapped_column(
        enum_column(
            SalesFraudReviewStatus,
            "sales_transaction_fraud_review_status",
        ),
        default=SalesFraudReviewStatus.NOT_REQUIRED,
        nullable=False,
    )

    fraud_reviewed_by: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    fraud_reviewed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    fraud_review_notes: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # APPROVAL
    # --------------------------------------------------------

    requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    approval_status: Mapped[
        SalesTransactionApprovalStatus
    ] = mapped_column(
        enum_column(
            SalesTransactionApprovalStatus,
            "sales_transaction_approval_status",
        ),
        default=SalesTransactionApprovalStatus.NOT_REQUIRED,
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

    rejection_reason: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # FAILURE / REVERSAL / DISPUTE
    # --------------------------------------------------------

    failure_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    failed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    reversal_reference: Mapped[
        str | None
    ] = mapped_column(
        String(200),
        nullable=True,
    )

    reversed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    dispute_reference: Mapped[
        str | None
    ] = mapped_column(
        String(200),
        nullable=True,
    )

    disputed_at: Mapped[
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

    previous_status: Mapped[
        SalesTransactionStatus | None
    ] = mapped_column(
        enum_column(
            SalesTransactionStatus,
            "sales_transaction_previous_status",
        ),
        nullable=True,
    )

    hold_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # AUDIT / METADATA
    # --------------------------------------------------------

    transaction_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    transaction_history: Mapped[
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
    # COMPUTED PROPERTIES
    # ========================================================

    @property
    def remaining_to_capture(self) -> Decimal:
        return max(
            ZERO,
            self.authorized_amount - self.captured_amount,
        )

    @property
    def remaining_to_settle(self) -> Decimal:
        return max(
            ZERO,
            self.captured_amount - self.settled_amount,
        )

    @property
    def refundable_balance(self) -> Decimal:
        return max(
            ZERO,
            self.captured_amount - self.refunded_amount,
        )

    @property
    def net_settlement(self) -> Decimal:
        return max(
            ZERO,
            self.settled_amount - self.processing_fee,
        )

    @property
    def is_fully_captured(self) -> bool:
        return (
            self.captured_amount > ZERO
            and self.captured_amount == self.amount
        )

    @property
    def is_fully_settled(self) -> bool:
        return (
            self.captured_amount > ZERO
            and self.settled_amount
            == self.captured_amount
        )

    @property
    def is_fully_refunded(self) -> bool:
        return (
            self.captured_amount > ZERO
            and self.refunded_amount
            == self.captured_amount
        )

    @property
    def is_approved(self) -> bool:
        return (
            not self.requires_approval
            or self.approval_status
            == SalesTransactionApprovalStatus.APPROVED
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            SalesTransactionStatus.COMPLETED,
            SalesTransactionStatus.FAILED,
            SalesTransactionStatus.DECLINED,
            SalesTransactionStatus.CANCELLED,
            SalesTransactionStatus.EXPIRED,
            SalesTransactionStatus.REVERSED,
        }

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_active(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Sales transaction has been deleted"
            )

    def _require_status(
        self,
        *statuses: SalesTransactionStatus,
    ) -> None:
        self._ensure_active()

        if self.status not in statuses:
            raise ValueError(
                f"Invalid transaction status: "
                f"{enum_value(self.status)}"
            )

    def _record_event(
        self,
        event: str,
        *,
        actor_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        history = list(self.transaction_history or [])

        history.append({
            "event_id": new_uuid(),
            "event": event,
            "actor_id": actor_id,
            "timestamp": utc_now().isoformat(),
            "details": details or {},
        })

        self.transaction_history = history
        self._touch()

    def _ensure_fraud_clearance(self) -> None:
        if self.fraud_review_status in {
            SalesFraudReviewStatus.PENDING,
            SalesFraudReviewStatus.UNDER_REVIEW,
            SalesFraudReviewStatus.BLOCKED,
        }:
            raise ValueError(
                "Fraud review has not cleared"
            )

    def _ensure_payment_transaction(self) -> None:
        if self.transaction_type not in {
            SalesTransactionType.PAYMENT,
            SalesTransactionType.AUTHORIZATION,
            SalesTransactionType.CAPTURE,
        }:
            raise ValueError(
                "Operation requires a payment transaction"
            )

    # ========================================================
    # INITIATE
    # ========================================================

    def initiate(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            SalesTransactionStatus.DRAFT,
            SalesTransactionStatus.APPROVED,
        )

        if self.requires_approval and not self.is_approved:
            raise ValueError(
                "Transaction approval required"
            )

        self._ensure_fraud_clearance()

        self.status = SalesTransactionStatus.INITIATED
        self.initiated_at = utc_now()

        self._record_event(
            "sales_transaction_initiated",
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
            SalesTransactionStatus.DRAFT
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
            SalesTransactionApprovalStatus.PENDING
        )
        self.status = (
            SalesTransactionStatus.PENDING_APPROVAL
        )

        self._record_event(
            "sales_transaction_approval_requested",
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
            SalesTransactionStatus.PENDING_APPROVAL
        )

        # Approval service must verify authority
        # and the linked approval request.

        self.approval_status = (
            SalesTransactionApprovalStatus.APPROVED
        )
        self.approved_by = required_text(
            approver_id,
            "Approver ID",
        )
        self.approved_at = utc_now()
        self.status = SalesTransactionStatus.APPROVED

        self._record_event(
            "sales_transaction_approved",
            actor_id=approver_id,
        )

    # ========================================================
    # AUTHORIZE
    # ========================================================

    def authorize(
        self,
        *,
        authorized_amount: Decimal | str | int | float,
        provider_transaction_id: str,
        provider_name: str,
        actor_id: str,
    ) -> None:
        self._require_status(
            SalesTransactionStatus.INITIATED,
            SalesTransactionStatus.PENDING,
        )

        self._ensure_payment_transaction()
        self._ensure_fraud_clearance()

        amount = decimal_value(
            authorized_amount,
            "authorized_amount",
            positive=True,
        )

        if amount > self.amount:
            raise ValueError(
                "Authorization exceeds transaction amount"
            )

        self.authorized_amount = amount
        self.provider_name = required_text(
            provider_name,
            "Provider name",
        )
        self.provider_transaction_id = required_text(
            provider_transaction_id,
            "Provider transaction ID",
        )

        self.authorized_at = utc_now()
        self.status = SalesTransactionStatus.AUTHORIZED

        self._record_event(
            "sales_transaction_authorized",
            actor_id=actor_id,
            details={
                "amount": str(amount),
            },
        )

    # ========================================================
    # CAPTURE
    # ========================================================

    def capture(
        self,
        *,
        amount: Decimal | str | int | float,
        actor_id: str,
    ) -> None:
        self._require_status(
            SalesTransactionStatus.AUTHORIZED,
            SalesTransactionStatus.CAPTURED,
        )

        self._ensure_payment_transaction()
        self._ensure_fraud_clearance()

        amount = decimal_value(
            amount,
            "amount",
            positive=True,
        )

        if amount > self.remaining_to_capture:
            raise ValueError(
                "Capture exceeds authorized balance"
            )

        # Payment service must verify provider capture
        # and enforce operation-level idempotency.

        self.captured_amount += amount
        self.captured_at = utc_now()
        self.status = SalesTransactionStatus.CAPTURED

        self._record_event(
            "sales_transaction_captured",
            actor_id=actor_id,
            details={
                "amount": str(amount),
                "captured_total": str(
                    self.captured_amount
                ),
            },
        )

    # ========================================================
    # SETTLE
    # ========================================================

    def settle(
        self,
        *,
        amount: Decimal | str | int | float,
        processing_fee: Decimal | str | int | float,
        actor_id: str,
        settlement_reference: str,
    ) -> None:
        self._require_status(
            SalesTransactionStatus.CAPTURED,
            SalesTransactionStatus.SETTLED,
        )

        amount = decimal_value(
            amount,
            "amount",
            positive=True,
        )
        fee = decimal_value(
            processing_fee,
            "processing_fee",
        )

        if amount > self.remaining_to_settle:
            raise ValueError(
                "Settlement exceeds captured balance"
            )

        if fee > amount:
            raise ValueError(
                "Processing fee exceeds settlement amount"
            )

        # Provider settlement confirmation and unique
        # settlement references belong in the service ledger.

        self.settled_amount += amount
        self.processing_fee += fee
        self.settled_at = utc_now()
        self.status = SalesTransactionStatus.SETTLED

        self._record_event(
            "sales_transaction_settled",
            actor_id=actor_id,
            details={
                "amount": str(amount),
                "processing_fee": str(fee),
                "settlement_reference": required_text(
                    settlement_reference,
                    "Settlement reference",
                ),
            },
        )

    # ========================================================
    # COMPLETE
    # ========================================================

    def complete(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            SalesTransactionStatus.SETTLED
        )

        if not self.is_fully_settled:
            raise ValueError(
                "Transaction is not fully settled"
            )

        self.status = SalesTransactionStatus.COMPLETED
        self.completed_at = utc_now()

        self._record_event(
            "sales_transaction_completed",
            actor_id=actor_id,
        )

    # ========================================================
    # RECORD REFUND
    # ========================================================

    def record_refund(
        self,
        *,
        amount: Decimal | str | int | float,
        refund_reference: str,
        actor_id: str,
    ) -> None:
        self._require_status(
            SalesTransactionStatus.CAPTURED,
            SalesTransactionStatus.SETTLED,
            SalesTransactionStatus.COMPLETED,
        )

        amount = decimal_value(
            amount,
            "amount",
            positive=True,
        )

        if amount > self.refundable_balance:
            raise ValueError(
                "Refund exceeds refundable balance"
            )

        reference = required_text(
            refund_reference,
            "Refund reference",
        )

        # Refund service must verify provider success,
        # uniqueness and ledger reconciliation.

        self.refunded_amount += amount

        self._record_event(
            "sales_transaction_refund_recorded",
            actor_id=actor_id,
            details={
                "amount": str(amount),
                "refund_reference": reference,
            },
        )

    # ========================================================
    # AI FRAUD ANALYSIS
    # ========================================================

    def update_ai_fraud_analysis(
        self,
        *,
        model_id: str,
        fraud_score: Decimal | str | int | float,
        confidence: Decimal | str | int | float,
        risk_level: SalesTransactionRiskLevel,
        recommendation: str,
        explanation: str,
        risk_factors: list[dict[str, Any]],
        agent_run_id: str | None = None,
    ) -> None:
        self._ensure_active()

        if self.is_terminal:
            raise ValueError(
                "Cannot analyze terminal transaction"
            )

        score = score_value(
            fraud_score,
            "fraud_score",
        )
        confidence_value = score_value(
            confidence,
            "confidence",
        )

        self.ai_model_id = required_text(
            model_id,
            "Model ID",
        )
        self.ai_agent_run_id = agent_run_id
        self.ai_fraud_score = score
        self.ai_confidence = confidence_value
        self.ai_risk_level = risk_level
        self.ai_recommendation = required_text(
            recommendation,
            "Recommendation",
        )
        self.ai_explanation = required_text(
            explanation,
            "Explanation",
        )
        self.ai_risk_factors = [
            dict(factor) for factor in risk_factors
        ]
        self.ai_analyzed_at = utc_now()

        if risk_level in {
            SalesTransactionRiskLevel.HIGH,
            SalesTransactionRiskLevel.CRITICAL,
        }:
            self.fraud_review_status = (
                SalesFraudReviewStatus.PENDING
            )

        self._record_event(
            "sales_transaction_ai_fraud_analyzed",
            details={
                "model_id": model_id,
                "risk_level": risk_level.value,
                "fraud_score": str(score),
            },
        )

    # ========================================================
    # FRAUD REVIEW
    # ========================================================

    def review_fraud(
        self,
        *,
        reviewer_id: str,
        cleared: bool,
        notes: str,
    ) -> None:
        self._ensure_active()

        if self.fraud_review_status not in {
            SalesFraudReviewStatus.PENDING,
            SalesFraudReviewStatus.UNDER_REVIEW,
        }:
            raise ValueError(
                "Fraud review is not pending"
            )

        # Fraud service must enforce reviewer permissions.

        self.fraud_review_status = (
            SalesFraudReviewStatus.CLEARED
            if cleared
            else SalesFraudReviewStatus.BLOCKED
        )

        self.fraud_reviewed_by = required_text(
            reviewer_id,
            "Reviewer ID",
        )
        self.fraud_reviewed_at = utc_now()
        self.fraud_review_notes = required_text(
            notes,
            "Review notes",
        )

        self._record_event(
            "sales_transaction_fraud_reviewed",
            actor_id=reviewer_id,
            details={
                "cleared": cleared,
            },
        )

    # ========================================================
    # RECONCILIATION
    # ========================================================

    def reconcile(
        self,
        *,
        matched: bool,
        reconciliation_reference: str,
        actor_id: str,
        notes: str | None = None,
    ) -> None:
        self._require_status(
            SalesTransactionStatus.SETTLED,
            SalesTransactionStatus.COMPLETED,
        )

        self.reconciliation_status = (
            SalesReconciliationStatus.MATCHED
            if matched
            else SalesReconciliationStatus.MISMATCHED
        )

        self.reconciliation_reference = required_text(
            reconciliation_reference,
            "Reconciliation reference",
        )
        self.reconciled_by = required_text(
            actor_id,
            "Actor ID",
        )
        self.reconciled_at = utc_now()
        self.reconciliation_notes = notes

        self._record_event(
            "sales_transaction_reconciled",
            actor_id=actor_id,
            details={
                "matched": matched,
            },
        )

    # ========================================================
    # MARK FAILED
    # ========================================================

    def mark_failed(
        self,
        *,
        actor_id: str,
        failure_code: str,
        reason: str,
    ) -> None:
        self._ensure_active()

        if self.is_terminal:
            raise ValueError(
                "Terminal transaction cannot fail"
            )

        if self.captured_amount > ZERO:
            raise ValueError(
                "Captured transaction requires reversal "
                "or financial reconciliation"
            )

        self.failure_code = required_text(
            failure_code,
            "Failure code",
        )
        self.failure_reason = required_text(
            reason,
            "Failure reason",
        )
        self.failed_at = utc_now()
        self.status = SalesTransactionStatus.FAILED

        self._record_event(
            "sales_transaction_failed",
            actor_id=actor_id,
            details={
                "failure_code": failure_code,
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
        self._require_status(
            SalesTransactionStatus.DRAFT,
            SalesTransactionStatus.PENDING_APPROVAL,
            SalesTransactionStatus.APPROVED,
            SalesTransactionStatus.INITIATED,
            SalesTransactionStatus.PENDING,
        )

        if self.authorized_amount > ZERO:
            raise ValueError(
                "Authorized funds require provider void"
            )

        self.status = SalesTransactionStatus.CANCELLED
        self.cancelled_by = required_text(
            actor_id,
            "Actor ID",
        )
        self.cancelled_at = utc_now()
        self.cancellation_reason = required_text(
            reason,
            "Cancellation reason",
        )

        self._record_event(
            "sales_transaction_cancelled",
            actor_id=actor_id,
        )

    # ========================================================
    # HOLD
    # ========================================================

    def place_on_hold(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_active()

        if self.is_terminal or self.status == (
            SalesTransactionStatus.ON_HOLD
        ):
            raise ValueError(
                "Transaction cannot be placed on hold"
            )

        self.previous_status = self.status
        self.status = SalesTransactionStatus.ON_HOLD
        self.hold_reason = required_text(
            reason,
            "Hold reason",
        )

        self._record_event(
            "sales_transaction_on_hold",
            actor_id=actor_id,
        )

    def release_hold(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            SalesTransactionStatus.ON_HOLD
        )

        if self.previous_status is None:
            raise ValueError(
                "Previous status is unavailable"
            )

        self._ensure_fraud_clearance()

        self.status = self.previous_status
        self.previous_status = None
        self.hold_reason = None

        self._record_event(
            "sales_transaction_hold_released",
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
            SalesTransactionStatus.DRAFT,
            SalesTransactionStatus.CANCELLED,
        )

        if (
            self.authorized_amount > ZERO
            or self.captured_amount > ZERO
            or self.settled_amount > ZERO
        ):
            raise ValueError(
                "Financially active transaction "
                "cannot be deleted"
            )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = required_text(
            actor_id,
            "Actor ID",
        )

        self._record_event(
            "sales_transaction_soft_deleted",
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
            "transaction_number": self.transaction_number,
            "transaction_type": enum_value(
                self.transaction_type
            ),
            "status": enum_value(self.status),
            "payment_method": enum_value(
                self.payment_method
            ),
            "channel": enum_value(self.channel),
            "source": enum_value(self.source),
            "sale_id": self.sale_id,
            "customer_id": self.customer_id,
            "warehouse_id": self.warehouse_id,
            "store_id": self.store_id,
            "refund_id": self.refund_id,
            "return_request_id": self.return_request_id,
            "original_transaction_id": (
                self.original_transaction_id
            ),
            "currency": self.currency,
            "amount": decimal_string(self.amount),
            "authorized_amount": decimal_string(
                self.authorized_amount
            ),
            "captured_amount": decimal_string(
                self.captured_amount
            ),
            "settled_amount": decimal_string(
                self.settled_amount
            ),
            "refunded_amount": decimal_string(
                self.refunded_amount
            ),
            "processing_fee": decimal_string(
                self.processing_fee
            ),
            "tax_amount": decimal_string(
                self.tax_amount
            ),
            "remaining_to_capture": decimal_string(
                self.remaining_to_capture
            ),
            "remaining_to_settle": decimal_string(
                self.remaining_to_settle
            ),
            "refundable_balance": decimal_string(
                self.refundable_balance
            ),
            "net_settlement": decimal_string(
                self.net_settlement
            ),
            "is_fully_captured": self.is_fully_captured,
            "is_fully_settled": self.is_fully_settled,
            "is_fully_refunded": self.is_fully_refunded,
            "provider_name": self.provider_name,
            "provider_transaction_id": (
                self.provider_transaction_id
            ),
            "payment_gateway_status": (
                self.payment_gateway_status
            ),
            "reconciliation_status": enum_value(
                self.reconciliation_status
            ),
            "fraud_review_status": enum_value(
                self.fraud_review_status
            ),
            "initiated_at": iso(self.initiated_at),
            "authorized_at": iso(self.authorized_at),
            "captured_at": iso(self.captured_at),
            "settled_at": iso(self.settled_at),
            "completed_at": iso(self.completed_at),
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "is_deleted": self.is_deleted,
            "version": self.version,
        }

        if include_internal:
            result.update({
                "ai_model_id": self.ai_model_id,
                "ai_agent_run_id": self.ai_agent_run_id,
                "ai_fraud_score": decimal_string(
                    self.ai_fraud_score
                ),
                "ai_confidence": decimal_string(
                    self.ai_confidence
                ),
                "ai_risk_level": enum_value(
                    self.ai_risk_level
                ),
                "ai_recommendation": self.ai_recommendation,
                "ai_explanation": self.ai_explanation,
                "ai_risk_factors": self.ai_risk_factors,
                "approval_status": enum_value(
                    self.approval_status
                ),
                "approval_request_id": (
                    self.approval_request_id
                ),
                "reconciliation_reference": (
                    self.reconciliation_reference
                ),
                "reconciliation_notes": (
                    self.reconciliation_notes
                ),
                "transaction_metadata": (
                    self.transaction_metadata
                ),
                "trace_id": self.trace_id,
                "correlation_id": self.correlation_id,
                "failure_code": self.failure_code,
                "failure_reason": self.failure_reason,
            })

        if include_history:
            result["transaction_history"] = (
                self.transaction_history
            )

        return result

    def __repr__(self) -> str:
        return (
            f"<SalesTransaction("
            f"id={self.id}, "
            f"transaction_number={self.transaction_number}, "
            f"status={enum_value(self.status)}, "
            f"amount={self.amount}"
            f")>"
        )