from __future__ import annotations

"""Planned module: return request. Implementation pending."""
"""
backend/models/return_request.py

Enterprise Return Merchandise Authorization (RMA) Model.

Features:
- Multi-tenant customer returns
- Full and partial returns
- Multiple products per request
- Return eligibility and policy tracking
- Human approval workflows
- AI-assisted risk assessment
- Pickup and reverse logistics tracking
- Warehouse receiving and inspection
- Refund, replacement and store-credit resolutions
- Idempotent receipt and inspection references
- State transition validation
- Optimistic locking and audit history
- Soft deletion

IMPORTANT:
This model records business state. Services must enforce
tenant authorization, return eligibility, inventory ledger
updates, payment operations, external logistics actions,
approval permissions, and transactional idempotency.
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
# UTILITIES
# ============================================================

ZERO = Decimal("0.0000")
QUANTUM = Decimal("0.0001")
MAX_VALUE = Decimal("100000000000000")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_rma_number() -> str:
    return f"RMA-{uuid.uuid4().hex[:16].upper()}"


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


def to_decimal(
    value: Decimal | str | int | float,
    field: str,
    *,
    positive: bool = False,
) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")

    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(
            f"{field} must be numeric"
        ) from None

    if not result.is_finite():
        raise ValueError(f"{field} must be finite")

    if result < 0 or (positive and result == 0):
        raise ValueError(
            f"{field} must be positive"
            if positive
            else f"{field} must be nonnegative"
        )

    if result >= MAX_VALUE:
        raise ValueError(f"{field} exceeds precision")

    if result != result.quantize(QUANTUM):
        raise ValueError(
            f"{field} supports at most 4 decimal places"
        )

    return result


def score_decimal(value, field: str) -> Decimal:
    result = to_decimal(value, field)

    if result > 1:
        raise ValueError(
            f"{field} must be between 0 and 1"
        )

    return result


def enum_value(value):
    return value.value if isinstance(value, enum.Enum) else value


def iso(value: datetime | None):
    return value.isoformat() if value else None


def decimal_string(value):
    return str(value) if value is not None else None


# ============================================================
# ENUMERATIONS
# ============================================================

class ReturnRequestStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    AWAITING_SHIPMENT = "awaiting_shipment"
    IN_TRANSIT = "in_transit"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    INSPECTION_PENDING = "inspection_pending"
    INSPECTING = "inspecting"
    INSPECTED = "inspected"
    RESOLUTION_PENDING = "resolution_pending"
    RESOLUTION_PROCESSING = "resolution_processing"
    COMPLETED = "completed"
    ON_HOLD = "on_hold"
    FAILED = "failed"
    CANCELLED = "cancelled"
    CLOSED = "closed"


class ReturnRequestType(str, enum.Enum):
    FULL_ORDER = "full_order"
    PARTIAL_ORDER = "partial_order"
    SINGLE_ITEM = "single_item"
    EXCHANGE = "exchange"
    WARRANTY = "warranty"
    RECALL = "recall"


class ReturnReason(str, enum.Enum):
    DAMAGED = "damaged"
    DEFECTIVE = "defective"
    WRONG_ITEM = "wrong_item"
    MISSING_PARTS = "missing_parts"
    NOT_AS_DESCRIBED = "not_as_described"
    SIZE_MISMATCH = "size_mismatch"
    QUALITY_ISSUE = "quality_issue"
    EXPIRED = "expired"
    LATE_DELIVERY = "late_delivery"
    CUSTOMER_CHANGED_MIND = "customer_changed_mind"
    DUPLICATE_ORDER = "duplicate_order"
    PRODUCT_RECALL = "product_recall"
    WARRANTY_CLAIM = "warranty_claim"
    OTHER = "other"


class ReturnResolutionType(str, enum.Enum):
    REFUND = "refund"
    REPLACEMENT = "replacement"
    EXCHANGE = "exchange"
    STORE_CREDIT = "store_credit"
    REPAIR = "repair"
    NO_COMPENSATION = "no_compensation"


class ReturnItemCondition(str, enum.Enum):
    UNKNOWN = "unknown"
    NEW = "new"
    OPEN_BOX = "open_box"
    USED = "used"
    DAMAGED = "damaged"
    DEFECTIVE = "defective"
    UNSAFE = "unsafe"
    EXPIRED = "expired"


class ReturnInspectionResult(str, enum.Enum):
    PENDING = "pending"
    PASSED = "passed"
    PARTIAL = "partial"
    FAILED = "failed"
    REQUIRES_REVIEW = "requires_review"


class ReturnDisposition(str, enum.Enum):
    UNDECIDED = "undecided"
    RESTOCK = "restock"
    REFURBISH = "refurbish"
    REPAIR = "repair"
    QUARANTINE = "quarantine"
    RECYCLE = "recycle"
    DISPOSE = "dispose"
    RETURN_TO_SUPPLIER = "return_to_supplier"


class ReturnApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReturnRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class ReturnPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"


class ReturnSource(str, enum.Enum):
    CUSTOMER = "customer"
    SUPPORT = "support"
    ADMIN = "admin"
    API = "api"
    ERP = "erp"
    RULE_ENGINE = "rule_engine"
    AI_AGENT = "ai_agent"


# ============================================================
# RETURN REQUEST
# ============================================================

class ReturnRequest(Base):
    __tablename__ = "return_requests"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "rma_number",
            name="uq_return_org_rma",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_return_org_idempotency",
        ),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_return_org_id",
        ),
        CheckConstraint(
            "estimated_refund_amount >= 0",
            name="return_estimated_refund_nonnegative",
        ),
        CheckConstraint(
            "approved_refund_amount >= 0",
            name="return_approved_refund_nonnegative",
        ),
        CheckConstraint(
            "approved_refund_amount <= estimated_refund_amount",
            name="return_approved_refund_limit",
        ),
        CheckConstraint(
            "restocking_fee >= 0",
            name="return_restocking_fee_nonnegative",
        ),
        CheckConstraint(
            "shipping_fee >= 0",
            name="return_shipping_fee_nonnegative",
        ),
        CheckConstraint(
            "ai_risk_score IS NULL OR "
            "(ai_risk_score >= 0 AND ai_risk_score <= 1)",
            name="return_ai_risk_range",
        ),
        CheckConstraint(
            "ai_confidence IS NULL OR "
            "(ai_confidence >= 0 AND ai_confidence <= 1)",
            name="return_ai_confidence_range",
        ),
        CheckConstraint(
            "version >= 1",
            name="return_version_positive",
        ),
        Index(
            "ix_return_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_return_org_customer",
            "organization_id",
            "customer_id",
        ),
        Index(
            "ix_return_org_order",
            "organization_id",
            "order_id",
        ),
        Index(
            "ix_return_org_warehouse",
            "organization_id",
            "warehouse_id",
        ),
        Index(
            "ix_return_org_created",
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

    rma_number: Mapped[str] = mapped_column(
        String(50),
        default=generate_rma_number,
        nullable=False,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # --------------------------------------------------------
    # RETURN DETAILS
    # --------------------------------------------------------

    status: Mapped[ReturnRequestStatus] = mapped_column(
        enum_column(
            ReturnRequestStatus,
            "return_request_status",
        ),
        default=ReturnRequestStatus.DRAFT,
        nullable=False,
    )

    return_type: Mapped[ReturnRequestType] = mapped_column(
        enum_column(
            ReturnRequestType,
            "return_request_type",
        ),
        default=ReturnRequestType.PARTIAL_ORDER,
        nullable=False,
    )

    reason: Mapped[ReturnReason] = mapped_column(
        enum_column(
            ReturnReason,
            "return_request_reason",
        ),
        nullable=False,
    )

    source: Mapped[ReturnSource] = mapped_column(
        enum_column(
            ReturnSource,
            "return_request_source",
        ),
        default=ReturnSource.CUSTOMER,
        nullable=False,
    )

    priority: Mapped[ReturnPriority] = mapped_column(
        enum_column(
            ReturnPriority,
            "return_request_priority",
        ),
        default=ReturnPriority.NORMAL,
        nullable=False,
    )

    reason_description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    customer_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    internal_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # REFERENCES
    # --------------------------------------------------------

    customer_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    order_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    fulfillment_order_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    delivery_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    warehouse_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    logistics_route_id: Mapped[str | None] = mapped_column(
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
    # POLICY / ELIGIBILITY
    # --------------------------------------------------------

    policy_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    policy_version: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    eligibility_checked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    is_eligible: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    eligibility_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    eligibility_checked_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    return_window_expires_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # REVERSE LOGISTICS
    # --------------------------------------------------------

    carrier_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    tracking_number: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    pickup_reference: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    pickup_scheduled_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    shipped_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    first_received_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    received_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # INSPECTION
    # --------------------------------------------------------

    inspection_result: Mapped[
        ReturnInspectionResult
    ] = mapped_column(
        enum_column(
            ReturnInspectionResult,
            "return_inspection_result",
        ),
        default=ReturnInspectionResult.PENDING,
        nullable=False,
    )

    inspection_started_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    inspected_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    inspected_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    inspection_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    inspection_checklist: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # --------------------------------------------------------
    # RESOLUTION
    # --------------------------------------------------------

    resolution_type: Mapped[
        ReturnResolutionType | None
    ] = mapped_column(
        enum_column(
            ReturnResolutionType,
            "return_resolution_type",
        ),
        nullable=True,
    )

    resolution_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    refund_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    replacement_order_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    store_credit_reference: Mapped[
        str | None
    ] = mapped_column(
        String(200),
        nullable=True,
    )

    repair_reference: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    resolution_started_at: Mapped[
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

    # --------------------------------------------------------
    # FINANCIALS
    # --------------------------------------------------------

    currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    estimated_refund_amount: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    approved_refund_amount: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    restocking_fee: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    shipping_fee: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    # --------------------------------------------------------
    # AI RISK ASSESSMENT
    # --------------------------------------------------------

    ai_model_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    ai_agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    ai_risk_score: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    ai_confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    ai_risk_level: Mapped[ReturnRiskLevel] = mapped_column(
        enum_column(
            ReturnRiskLevel,
            "return_request_risk_level",
        ),
        default=ReturnRiskLevel.UNKNOWN,
        nullable=False,
    )

    ai_recommendation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    ai_explanation: Mapped[str | None] = mapped_column(
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
        ReturnApprovalStatus
    ] = mapped_column(
        enum_column(
            ReturnApprovalStatus,
            "return_request_approval_status",
        ),
        default=ReturnApprovalStatus.NOT_REQUIRED,
        nullable=False,
    )

    approval_request_id: Mapped[str | None] = mapped_column(
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

    rejection_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # HOLD / FAILURE / CANCELLATION
    # --------------------------------------------------------

    previous_status: Mapped[
        ReturnRequestStatus | None
    ] = mapped_column(
        enum_column(
            ReturnRequestStatus,
            "return_request_previous_status",
        ),
        nullable=True,
    )

    hold_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    held_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    failure_reason: Mapped[str | None] = mapped_column(
        Text,
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

    cancellation_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    closed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # AUDIT
    # --------------------------------------------------------

    request_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    request_history: Mapped[
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

    # --------------------------------------------------------
    # RELATIONSHIPS
    # --------------------------------------------------------

    items: Mapped[list["ReturnRequestItem"]] = relationship(
        "ReturnRequestItem",
        back_populates="return_request",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ReturnRequestItem.line_number",
    )

    # ========================================================
    # PROPERTIES
    # ========================================================

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            ReturnRequestStatus.COMPLETED,
            ReturnRequestStatus.REJECTED,
            ReturnRequestStatus.CANCELLED,
            ReturnRequestStatus.CLOSED,
        }

    @property
    def is_approved(self) -> bool:
        return (
            self.approval_status
            == ReturnApprovalStatus.APPROVED
            or (
                not self.requires_approval
                and self.status not in {
                    ReturnRequestStatus.DRAFT,
                    ReturnRequestStatus.SUBMITTED,
                    ReturnRequestStatus.UNDER_REVIEW,
                }
            )
        )

    @property
    def total_requested_quantity(self) -> Decimal:
        return sum(
            (item.requested_quantity for item in self.items),
            ZERO,
        )

    @property
    def total_received_quantity(self) -> Decimal:
        return sum(
            (item.received_quantity for item in self.items),
            ZERO,
        )

    @property
    def total_accepted_quantity(self) -> Decimal:
        return sum(
            (item.accepted_quantity for item in self.items),
            ZERO,
        )

    @property
    def is_fully_received(self) -> bool:
        return bool(self.items) and all(
            item.received_quantity == item.requested_quantity
            for item in self.items
        )

    @property
    def is_fully_inspected(self) -> bool:
        return bool(self.items) and all(
            item.inspected_quantity == item.received_quantity
            for item in self.items
        )

    @property
    def receipt_progress(self) -> Decimal:
        total = self.total_requested_quantity

        if total <= 0:
            return ZERO

        return min(
            Decimal("100"),
            (
                self.total_received_quantity
                / total
                * Decimal("100")
            ).quantize(QUANTUM),
        )

    # ========================================================
    # INTERNAL METHODS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_active(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Return request has been deleted"
            )

    def _ensure_status(
        self,
        *statuses: ReturnRequestStatus,
    ) -> None:
        self._ensure_active()

        if self.status not in statuses:
            raise ValueError(
                f"Invalid return state: {self.status.value}"
            )

    def _record_event(
        self,
        event: str,
        *,
        actor_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        history = list(self.request_history or [])

        history.append({
            "event_id": generate_uuid(),
            "event": event,
            "actor_id": actor_id,
            "timestamp": utc_now().isoformat(),
            "details": details or {},
        })

        self.request_history = history
        self._touch()

    def _get_item(self, item_id: str) -> "ReturnRequestItem":
        for item in self.items:
            if item.id == item_id:
                return item

        raise ValueError("Return item not found")

    def _recalculate_estimated_refund(self) -> None:
        self.estimated_refund_amount = sum(
            (
                item.requested_quantity * item.unit_price
                for item in self.items
            ),
            ZERO,
        ).quantize(QUANTUM)

        self._touch()

    # ========================================================
    # ADD ITEM
    # ========================================================

    def add_item(
        self,
        *,
        product_id: str,
        sku: str,
        product_name: str,
        requested_quantity: Decimal | str | int | float,
        unit_price: Decimal | str | int | float,
        actor_id: str,
        order_item_id: str | None = None,
        reason: ReturnReason | None = None,
        condition: ReturnItemCondition = (
            ReturnItemCondition.UNKNOWN
        ),
    ) -> "ReturnRequestItem":
        self._ensure_status(ReturnRequestStatus.DRAFT)

        if any(
            item.product_id == product_id
            and item.order_item_id == order_item_id
            for item in self.items
        ):
            raise ValueError(
                "Product/order line already exists"
            )

        item = ReturnRequestItem(
            organization_id=self.organization_id,
            line_number=max(
                (line.line_number for line in self.items),
                default=0,
            ) + 1,
            product_id=require_text(
                product_id, "Product ID"
            ),
            order_item_id=order_item_id,
            sku=require_text(sku, "SKU"),
            product_name=require_text(
                product_name, "Product name"
            ),
            requested_quantity=to_decimal(
                requested_quantity,
                "requested_quantity",
                positive=True,
            ),
            unit_price=to_decimal(
                unit_price, "unit_price"
            ),
            reason=reason or self.reason,
            declared_condition=condition,
        )

        self.items.append(item)
        self._recalculate_estimated_refund()

        self._record_event(
            "return_item_added",
            actor_id=actor_id,
            details={
                "product_id": product_id,
                "quantity": str(item.requested_quantity),
            },
        )

        return item

    # ========================================================
    # ELIGIBILITY
    # ========================================================

    def record_eligibility(
        self,
        *,
        eligible: bool,
        reason: str,
        actor_id: str,
        policy_id: str | None = None,
        policy_version: str | None = None,
    ) -> None:
        self._ensure_status(
            ReturnRequestStatus.DRAFT,
            ReturnRequestStatus.SUBMITTED,
            ReturnRequestStatus.UNDER_REVIEW,
        )

        self.eligibility_checked = True
        self.is_eligible = bool(eligible)
        self.eligibility_reason = require_text(
            reason, "Eligibility reason"
        )
        self.eligibility_checked_at = utc_now()
        self.policy_id = policy_id
        self.policy_version = policy_version

        self._record_event(
            "return_eligibility_checked",
            actor_id=actor_id,
            details={"eligible": eligible},
        )

    # ========================================================
    # SUBMIT
    # ========================================================

    def submit(self, *, actor_id: str) -> None:
        self._ensure_status(ReturnRequestStatus.DRAFT)

        if not self.items:
            raise ValueError(
                "Return request requires at least one item"
            )

        self.requested_by = require_text(
            actor_id, "Actor ID"
        )
        self.status = ReturnRequestStatus.SUBMITTED

        self._record_event(
            "return_submitted",
            actor_id=actor_id,
        )

    # ========================================================
    # REVIEW
    # ========================================================

    def start_review(
        self,
        *,
        reviewer_id: str,
    ) -> None:
        self._ensure_status(ReturnRequestStatus.SUBMITTED)

        self.status = ReturnRequestStatus.UNDER_REVIEW
        self.reviewed_by = require_text(
            reviewer_id, "Reviewer ID"
        )

        self._record_event(
            "return_review_started",
            actor_id=reviewer_id,
        )

    # ========================================================
    # AI RISK ASSESSMENT
    # ========================================================

    def update_ai_risk(
        self,
        *,
        model_id: str,
        risk_score: Decimal | str | int | float,
        confidence: Decimal | str | int | float,
        risk_level: ReturnRiskLevel,
        recommendation: str,
        explanation: str,
        risk_factors: list[dict[str, Any]],
        agent_run_id: str | None = None,
    ) -> None:
        self._ensure_status(
            ReturnRequestStatus.SUBMITTED,
            ReturnRequestStatus.UNDER_REVIEW,
            ReturnRequestStatus.PENDING_APPROVAL,
        )

        self.ai_model_id = require_text(
            model_id, "Model ID"
        )
        self.ai_agent_run_id = agent_run_id
        self.ai_risk_score = score_decimal(
            risk_score, "risk_score"
        )
        self.ai_confidence = score_decimal(
            confidence, "confidence"
        )
        self.ai_risk_level = risk_level
        self.ai_recommendation = require_text(
            recommendation, "Recommendation"
        )
        self.ai_explanation = require_text(
            explanation, "Explanation"
        )
        self.ai_risk_factors = [
            dict(factor) for factor in risk_factors
        ]
        self.ai_analyzed_at = utc_now()

        self._record_event(
            "return_ai_risk_updated",
            details={
                "model_id": model_id,
                "risk_level": risk_level.value,
            },
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
        self._ensure_status(
            ReturnRequestStatus.UNDER_REVIEW
        )

        if not self.eligibility_checked:
            raise ValueError(
                "Return eligibility has not been checked"
            )

        if not self.is_eligible:
            raise ValueError(
                "Return is not eligible for approval"
            )

        if self.requires_approval:
            self.approval_request_id = require_text(
                approval_request_id,
                "Approval request ID",
            )
            self.approval_status = (
                ReturnApprovalStatus.PENDING
            )
            self.status = (
                ReturnRequestStatus.PENDING_APPROVAL
            )
        else:
            self.approval_status = (
                ReturnApprovalStatus.NOT_REQUIRED
            )
            self.status = ReturnRequestStatus.APPROVED
            self.approved_at = utc_now()

        self._record_event(
            "return_approval_requested",
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
        self._ensure_status(
            ReturnRequestStatus.PENDING_APPROVAL
        )

        if not self.is_eligible:
            raise ValueError(
                "Ineligible return cannot be approved"
            )

        # Approval service must verify the linked
        # approval request and approver permissions.

        self.approval_status = (
            ReturnApprovalStatus.APPROVED
        )
        self.approved_by = require_text(
            approver_id, "Approver ID"
        )
        self.approved_at = utc_now()
        self.status = ReturnRequestStatus.APPROVED

        self._record_event(
            "return_approved",
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
        self._ensure_status(
            ReturnRequestStatus.SUBMITTED,
            ReturnRequestStatus.UNDER_REVIEW,
            ReturnRequestStatus.PENDING_APPROVAL,
        )

        self.approval_status = (
            ReturnApprovalStatus.REJECTED
        )
        self.rejected_by = require_text(
            reviewer_id, "Reviewer ID"
        )
        self.rejected_at = utc_now()
        self.rejection_reason = require_text(
            reason, "Rejection reason"
        )
        self.status = ReturnRequestStatus.REJECTED

        self._record_event(
            "return_rejected",
            actor_id=reviewer_id,
            details={"reason": reason},
        )

    # ========================================================
    # REVERSE LOGISTICS
    # ========================================================

    def schedule_return(
        self,
        *,
        actor_id: str,
        carrier_name: str,
        pickup_reference: str,
        pickup_scheduled_at: datetime,
    ) -> None:
        self._ensure_status(ReturnRequestStatus.APPROVED)

        if pickup_scheduled_at.tzinfo is None:
            raise ValueError(
                "Pickup datetime must be timezone-aware"
            )

        self.carrier_name = require_text(
            carrier_name, "Carrier name"
        )
        self.pickup_reference = require_text(
            pickup_reference, "Pickup reference"
        )
        self.pickup_scheduled_at = (
            pickup_scheduled_at.astimezone(timezone.utc)
        )
        self.status = ReturnRequestStatus.AWAITING_SHIPMENT

        self._record_event(
            "return_pickup_scheduled",
            actor_id=actor_id,
        )

    def mark_in_transit(
        self,
        *,
        actor_id: str,
        tracking_number: str,
    ) -> None:
        self._ensure_status(
            ReturnRequestStatus.APPROVED,
            ReturnRequestStatus.AWAITING_SHIPMENT,
        )

        self.tracking_number = require_text(
            tracking_number, "Tracking number"
        )
        self.shipped_at = utc_now()
        self.status = ReturnRequestStatus.IN_TRANSIT

        self._record_event(
            "return_in_transit",
            actor_id=actor_id,
        )

    # ========================================================
    # RECEIVE RETURN ITEM
    # ========================================================

    def record_item_receipt(
        self,
        *,
        item_id: str,
        quantity: Decimal | str | int | float,
        receipt_reference: str,
        actor_id: str,
    ) -> None:
        self._ensure_status(
            ReturnRequestStatus.APPROVED,
            ReturnRequestStatus.AWAITING_SHIPMENT,
            ReturnRequestStatus.IN_TRANSIT,
            ReturnRequestStatus.PARTIALLY_RECEIVED,
        )

        reference = require_text(
            receipt_reference, "Receipt reference"
        )

        item = self._get_item(item_id)

        # Duplicate references are rejected at model level.
        # A service must additionally enforce database-level
        # idempotency under concurrent requests.
        if reference in item.receipt_references:
            raise ValueError(
                "Receipt reference already processed"
            )

        item.record_received(quantity, reference)

        if self.first_received_at is None:
            self.first_received_at = utc_now()

        self.received_by = require_text(
            actor_id, "Actor ID"
        )

        self.status = (
            ReturnRequestStatus.RECEIVED
            if self.is_fully_received
            else ReturnRequestStatus.PARTIALLY_RECEIVED
        )

        self._record_event(
            "return_item_received",
            actor_id=actor_id,
            details={
                "item_id": item_id,
                "quantity": str(quantity),
                "receipt_reference": reference,
            },
        )

    # ========================================================
    # INSPECTION
    # ========================================================

    def start_inspection(
        self,
        *,
        inspector_id: str,
    ) -> None:
        self._ensure_status(
            ReturnRequestStatus.RECEIVED
        )

        self.status = ReturnRequestStatus.INSPECTING
        self.inspection_started_at = utc_now()
        self.inspected_by = require_text(
            inspector_id, "Inspector ID"
        )

        self._record_event(
            "return_inspection_started",
            actor_id=inspector_id,
        )

    def inspect_item(
        self,
        *,
        item_id: str,
        accepted_quantity: Decimal | str | int | float,
        condition: ReturnItemCondition,
        disposition: ReturnDisposition,
        inspection_reference: str,
        actor_id: str,
        notes: str | None = None,
    ) -> None:
        self._ensure_status(
            ReturnRequestStatus.INSPECTING
        )

        item = self._get_item(item_id)

        item.record_inspection(
            accepted_quantity=accepted_quantity,
            condition=condition,
            disposition=disposition,
            inspection_reference=inspection_reference,
            notes=notes,
        )

        self._record_event(
            "return_item_inspected",
            actor_id=actor_id,
            details={
                "item_id": item_id,
                "accepted_quantity": str(
                    accepted_quantity
                ),
            },
        )

    def complete_inspection(
        self,
        *,
        inspector_id: str,
        notes: str | None = None,
    ) -> None:
        self._ensure_status(
            ReturnRequestStatus.INSPECTING
        )

        if not self.is_fully_inspected:
            raise ValueError(
                "All received quantities must be inspected"
            )

        accepted = self.total_accepted_quantity
        received = self.total_received_quantity

        if accepted == received:
            result = ReturnInspectionResult.PASSED
        elif accepted > 0:
            result = ReturnInspectionResult.PARTIAL
        else:
            result = ReturnInspectionResult.FAILED

        self.inspection_result = result
        self.inspected_by = require_text(
            inspector_id, "Inspector ID"
        )
        self.inspected_at = utc_now()
        self.inspection_notes = notes
        self.status = ReturnRequestStatus.INSPECTED

        self._record_event(
            "return_inspection_completed",
            actor_id=inspector_id,
            details={"result": result.value},
        )

    # ========================================================
    # RESOLUTION
    # ========================================================

    def select_resolution(
        self,
        *,
        resolution_type: ReturnResolutionType,
        actor_id: str,
        notes: str | None = None,
        approved_refund_amount: (
            Decimal | str | int | float
        ) = ZERO,
    ) -> None:
        self._ensure_status(
            ReturnRequestStatus.INSPECTED
        )

        if (
            self.total_accepted_quantity <= 0
            and resolution_type
            != ReturnResolutionType.NO_COMPENSATION
        ):
            raise ValueError(
                "No accepted items for compensation"
            )

        amount = to_decimal(
            approved_refund_amount,
            "approved_refund_amount",
        )

        if amount > self.estimated_refund_amount:
            raise ValueError(
                "Approved refund exceeds estimated amount"
            )

        if (
            resolution_type == ReturnResolutionType.REFUND
            and amount <= 0
        ):
            raise ValueError(
                "Refund resolution requires positive amount"
            )

        if (
            resolution_type != ReturnResolutionType.REFUND
            and amount != 0
        ):
            raise ValueError(
                "Refund amount is only valid for refund resolution"
            )

        # Finance service must validate accepted-item
        # value, applicable taxes, fees and refund policy.

        self.resolution_type = resolution_type
        self.approved_refund_amount = amount
        self.resolution_notes = notes
        self.status = ReturnRequestStatus.RESOLUTION_PENDING

        self._record_event(
            "return_resolution_selected",
            actor_id=actor_id,
            details={
                "resolution_type": resolution_type.value,
                "approved_refund_amount": str(amount),
            },
        )

    def start_resolution(
        self,
        *,
        actor_id: str,
        reference: str | None = None,
    ) -> None:
        self._ensure_status(
            ReturnRequestStatus.RESOLUTION_PENDING
        )

        if self.resolution_type is None:
            raise ValueError(
                "Resolution type has not been selected"
            )

        if self.resolution_type == ReturnResolutionType.REFUND:
            self.refund_id = require_text(
                reference, "Refund ID"
            )

        elif self.resolution_type in {
            ReturnResolutionType.REPLACEMENT,
            ReturnResolutionType.EXCHANGE,
        }:
            self.replacement_order_id = require_text(
                reference, "Replacement order ID"
            )

        elif self.resolution_type == (
            ReturnResolutionType.STORE_CREDIT
        ):
            self.store_credit_reference = require_text(
                reference, "Store credit reference"
            )

        elif self.resolution_type == (
            ReturnResolutionType.REPAIR
        ):
            self.repair_reference = require_text(
                reference, "Repair reference"
            )

        self.resolution_started_at = utc_now()
        self.status = (
            ReturnRequestStatus.RESOLUTION_PROCESSING
        )

        self._record_event(
            "return_resolution_started",
            actor_id=actor_id,
        )

    def complete_resolution(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_status(
            ReturnRequestStatus.RESOLUTION_PROCESSING
        )

        # Service must verify the external refund,
        # replacement, repair or store-credit result.

        self.resolved_at = utc_now()
        self.status = ReturnRequestStatus.COMPLETED

        self._record_event(
            "return_resolution_completed",
            actor_id=actor_id,
        )

    # ========================================================
    # HOLD / RELEASE
    # ========================================================

    def place_on_hold(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_active()

        if self.is_terminal or self.status in {
            ReturnRequestStatus.ON_HOLD,
            ReturnRequestStatus.FAILED,
        }:
            raise ValueError(
                "Return cannot be placed on hold"
            )

        self.previous_status = self.status
        self.status = ReturnRequestStatus.ON_HOLD
        self.hold_reason = require_text(
            reason, "Hold reason"
        )
        self.held_at = utc_now()

        self._record_event(
            "return_placed_on_hold",
            actor_id=actor_id,
            details={"reason": reason},
        )

    def release_hold(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_status(ReturnRequestStatus.ON_HOLD)

        if self.previous_status is None:
            raise ValueError(
                "Previous status unavailable"
            )

        self.status = self.previous_status
        self.previous_status = None
        self.hold_reason = None
        self.held_at = None

        self._record_event(
            "return_hold_released",
            actor_id=actor_id,
        )

    # ========================================================
    # FAILURE / CANCELLATION
    # ========================================================

    def mark_failed(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_active()

        if self.is_terminal:
            raise ValueError(
                "Terminal return cannot fail"
            )

        self.status = ReturnRequestStatus.FAILED
        self.failure_reason = require_text(
            reason, "Failure reason"
        )

        self._record_event(
            "return_failed",
            actor_id=actor_id,
            details={"reason": reason},
        )

    def cancel(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_status(
            ReturnRequestStatus.DRAFT,
            ReturnRequestStatus.SUBMITTED,
            ReturnRequestStatus.UNDER_REVIEW,
            ReturnRequestStatus.PENDING_APPROVAL,
            ReturnRequestStatus.APPROVED,
            ReturnRequestStatus.AWAITING_SHIPMENT,
        )

        if self.total_received_quantity > 0:
            raise ValueError(
                "Received return cannot be cancelled"
            )

        self.status = ReturnRequestStatus.CANCELLED
        self.cancelled_at = utc_now()
        self.cancelled_by = require_text(
            actor_id, "Actor ID"
        )
        self.cancellation_reason = require_text(
            reason, "Cancellation reason"
        )

        self._record_event(
            "return_cancelled",
            actor_id=actor_id,
            details={"reason": reason},
        )

    def close(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_status(
            ReturnRequestStatus.COMPLETED,
            ReturnRequestStatus.REJECTED,
            ReturnRequestStatus.CANCELLED,
        )

        self.status = ReturnRequestStatus.CLOSED
        self.closed_at = utc_now()

        self._record_event(
            "return_closed",
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
        self._ensure_active()

        if self.status not in {
            ReturnRequestStatus.DRAFT,
            ReturnRequestStatus.REJECTED,
            ReturnRequestStatus.CANCELLED,
            ReturnRequestStatus.CLOSED,
        }:
            raise ValueError(
                "Return cannot be deleted in current state"
            )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = require_text(
            actor_id, "Actor ID"
        )

        self._record_event(
            "return_soft_deleted",
            actor_id=actor_id,
        )

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(
        self,
        *,
        include_items: bool = True,
        include_internal: bool = False,
        include_history: bool = False,
    ) -> dict[str, Any]:
        result = {
            "id": self.id,
            "organization_id": self.organization_id,
            "rma_number": self.rma_number,
            "status": enum_value(self.status),
            "return_type": enum_value(self.return_type),
            "reason": enum_value(self.reason),
            "source": enum_value(self.source),
            "priority": enum_value(self.priority),
            "reason_description": self.reason_description,
            "customer_notes": self.customer_notes,
            "customer_id": self.customer_id,
            "order_id": self.order_id,
            "fulfillment_order_id": self.fulfillment_order_id,
            "delivery_id": self.delivery_id,
            "warehouse_id": self.warehouse_id,
            "logistics_route_id": self.logistics_route_id,
            "product_quality_issue_id": (
                self.product_quality_issue_id
            ),
            "eligibility_checked": self.eligibility_checked,
            "is_eligible": self.is_eligible,
            "eligibility_reason": self.eligibility_reason,
            "return_window_expires_at": iso(
                self.return_window_expires_at
            ),
            "carrier_name": self.carrier_name,
            "tracking_number": self.tracking_number,
            "pickup_scheduled_at": iso(
                self.pickup_scheduled_at
            ),
            "shipped_at": iso(self.shipped_at),
            "first_received_at": iso(self.first_received_at),
            "inspection_result": enum_value(
                self.inspection_result
            ),
            "inspected_at": iso(self.inspected_at),
            "resolution_type": enum_value(
                self.resolution_type
            ),
            "refund_id": self.refund_id,
            "replacement_order_id": (
                self.replacement_order_id
            ),
            "store_credit_reference": (
                self.store_credit_reference
            ),
            "repair_reference": self.repair_reference,
            "resolved_at": iso(self.resolved_at),
            "currency": self.currency,
            "estimated_refund_amount": decimal_string(
                self.estimated_refund_amount
            ),
            "approved_refund_amount": decimal_string(
                self.approved_refund_amount
            ),
            "restocking_fee": decimal_string(
                self.restocking_fee
            ),
            "shipping_fee": decimal_string(
                self.shipping_fee
            ),
            "requires_approval": self.requires_approval,
            "approval_status": enum_value(
                self.approval_status
            ),
            "approved_at": iso(self.approved_at),
            "rejection_reason": self.rejection_reason,
            "total_requested_quantity": decimal_string(
                self.total_requested_quantity
            ),
            "total_received_quantity": decimal_string(
                self.total_received_quantity
            ),
            "total_accepted_quantity": decimal_string(
                self.total_accepted_quantity
            ),
            "receipt_progress": decimal_string(
                self.receipt_progress
            ),
            "is_fully_received": self.is_fully_received,
            "is_fully_inspected": self.is_fully_inspected,
            "is_terminal": self.is_terminal,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "is_deleted": self.is_deleted,
            "version": self.version,
        }

        if include_items:
            result["items"] = [
                item.to_dict() for item in self.items
            ]

        if include_internal:
            result.update({
                "internal_notes": self.internal_notes,
                "policy_id": self.policy_id,
                "policy_version": self.policy_version,
                "approval_request_id": (
                    self.approval_request_id
                ),
                "ai_model_id": self.ai_model_id,
                "ai_agent_run_id": self.ai_agent_run_id,
                "ai_risk_score": decimal_string(
                    self.ai_risk_score
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
                "inspection_notes": self.inspection_notes,
                "inspection_checklist": (
                    self.inspection_checklist
                ),
                "request_metadata": self.request_metadata,
                "trace_id": self.trace_id,
                "correlation_id": self.correlation_id,
            })

        if include_history:
            result["request_history"] = (
                self.request_history
            )

        return result

    def __repr__(self) -> str:
        return (
            f"<ReturnRequest("
            f"id={self.id}, "
            f"rma_number={self.rma_number}, "
            f"status={enum_value(self.status)}"
            f")>"
        )


# ============================================================
# RETURN REQUEST ITEM
# ============================================================

class ReturnRequestItem(Base):
    __tablename__ = "return_request_items"

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "return_request_id"],
            [
                "return_requests.organization_id",
                "return_requests.id",
            ],
            name="fk_return_item_same_tenant_request",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "return_request_id",
            "line_number",
            name="uq_return_item_line_number",
        ),
        CheckConstraint(
            "requested_quantity > 0",
            name="return_item_requested_positive",
        ),
        CheckConstraint(
            "received_quantity >= 0",
            name="return_item_received_nonnegative",
        ),
        CheckConstraint(
            "inspected_quantity >= 0",
            name="return_item_inspected_nonnegative",
        ),
        CheckConstraint(
            "accepted_quantity >= 0",
            name="return_item_accepted_nonnegative",
        ),
        CheckConstraint(
            "received_quantity <= requested_quantity",
            name="return_item_received_limit",
        ),
        CheckConstraint(
            "inspected_quantity <= received_quantity",
            name="return_item_inspected_limit",
        ),
        CheckConstraint(
            "accepted_quantity <= inspected_quantity",
            name="return_item_accepted_limit",
        ),
        CheckConstraint(
            "unit_price >= 0",
            name="return_item_price_nonnegative",
        ),
        Index(
            "ix_return_item_org_product",
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

    return_request_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    line_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    product_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    order_item_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    sku: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    product_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    reason: Mapped[ReturnReason] = mapped_column(
        enum_column(
            ReturnReason,
            "return_item_reason",
        ),
        nullable=False,
    )

    requested_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
    )

    received_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    inspected_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    accepted_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    declared_condition: Mapped[
        ReturnItemCondition
    ] = mapped_column(
        enum_column(
            ReturnItemCondition,
            "return_item_declared_condition",
        ),
        default=ReturnItemCondition.UNKNOWN,
        nullable=False,
    )

    inspected_condition: Mapped[
        ReturnItemCondition
    ] = mapped_column(
        enum_column(
            ReturnItemCondition,
            "return_item_inspected_condition",
        ),
        default=ReturnItemCondition.UNKNOWN,
        nullable=False,
    )

    disposition: Mapped[
        ReturnDisposition
    ] = mapped_column(
        enum_column(
            ReturnDisposition,
            "return_item_disposition",
        ),
        default=ReturnDisposition.UNDECIDED,
        nullable=False,
    )

    inspection_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    receipt_references: Mapped[
        list[str]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    inspection_reference: Mapped[
        str | None
    ] = mapped_column(
        String(200),
        nullable=True,
    )

    item_metadata: Mapped[
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

    return_request: Mapped["ReturnRequest"] = relationship(
        "ReturnRequest",
        back_populates="items",
    )

    # ========================================================
    # PROPERTIES
    # ========================================================

    @property
    def remaining_to_receive(self) -> Decimal:
        return (
            self.requested_quantity
            - self.received_quantity
        )

    @property
    def remaining_to_inspect(self) -> Decimal:
        return (
            self.received_quantity
            - self.inspected_quantity
        )

    @property
    def rejected_quantity(self) -> Decimal:
        return (
            self.inspected_quantity
            - self.accepted_quantity
        )

    @property
    def estimated_refund_amount(self) -> Decimal:
        return (
            self.requested_quantity * self.unit_price
        ).quantize(QUANTUM)

    @property
    def accepted_refund_amount(self) -> Decimal:
        return (
            self.accepted_quantity * self.unit_price
        ).quantize(QUANTUM)

    # ========================================================
    # RECEIVE
    # ========================================================

    def record_received(
        self,
        quantity: Decimal | str | int | float,
        receipt_reference: str,
    ) -> None:
        quantity = to_decimal(
            quantity,
            "quantity",
            positive=True,
        )

        reference = require_text(
            receipt_reference, "Receipt reference"
        )

        if reference in self.receipt_references:
            raise ValueError(
                "Receipt already recorded"
            )

        if quantity > self.remaining_to_receive:
            raise ValueError(
                "Received quantity exceeds requested quantity"
            )

        self.received_quantity += quantity

        references = list(self.receipt_references or [])
        references.append(reference)
        self.receipt_references = references

        self.updated_at = utc_now()

    # ========================================================
    # INSPECT
    # ========================================================

    def record_inspection(
        self,
        *,
        accepted_quantity: Decimal | str | int | float,
        condition: ReturnItemCondition,
        disposition: ReturnDisposition,
        inspection_reference: str,
        notes: str | None = None,
    ) -> None:
        if self.inspection_reference is not None:
            raise ValueError(
                "Item inspection already completed"
            )

        if self.received_quantity <= 0:
            raise ValueError(
                "Item has not been received"
            )

        accepted = to_decimal(
            accepted_quantity,
            "accepted_quantity",
        )

        if accepted > self.received_quantity:
            raise ValueError(
                "Accepted quantity exceeds received quantity"
            )

        self.inspected_quantity = self.received_quantity
        self.accepted_quantity = accepted
        self.inspected_condition = condition
        self.disposition = disposition
        self.inspection_reference = require_text(
            inspection_reference,
            "Inspection reference",
        )
        self.inspection_notes = notes
        self.updated_at = utc_now()

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "return_request_id": self.return_request_id,
            "line_number": self.line_number,
            "product_id": self.product_id,
            "order_item_id": self.order_item_id,
            "sku": self.sku,
            "product_name": self.product_name,
            "reason": enum_value(self.reason),
            "requested_quantity": decimal_string(
                self.requested_quantity
            ),
            "received_quantity": decimal_string(
                self.received_quantity
            ),
            "inspected_quantity": decimal_string(
                self.inspected_quantity
            ),
            "accepted_quantity": decimal_string(
                self.accepted_quantity
            ),
            "rejected_quantity": decimal_string(
                self.rejected_quantity
            ),
            "remaining_to_receive": decimal_string(
                self.remaining_to_receive
            ),
            "remaining_to_inspect": decimal_string(
                self.remaining_to_inspect
            ),
            "unit_price": decimal_string(self.unit_price),
            "estimated_refund_amount": decimal_string(
                self.estimated_refund_amount
            ),
            "accepted_refund_amount": decimal_string(
                self.accepted_refund_amount
            ),
            "declared_condition": enum_value(
                self.declared_condition
            ),
            "inspected_condition": enum_value(
                self.inspected_condition
            ),
            "disposition": enum_value(self.disposition),
            "inspection_notes": self.inspection_notes,
            "inspection_reference": (
                self.inspection_reference
            ),
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
        }

    def __repr__(self) -> str:
        return (
            f"<ReturnRequestItem("
            f"id={self.id}, "
            f"product_id={self.product_id}, "
            f"requested={self.requested_quantity}, "
            f"received={self.received_quantity}"
            f")>"
        )