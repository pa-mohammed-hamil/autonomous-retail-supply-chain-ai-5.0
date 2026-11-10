from __future__ import annotations

"""Planned module: sale. Implementation pending."""
"""
backend/models/sale.py

Enterprise Sales Transaction ORM Model.

Features:
- Multi-tenant sales
- POS, e-commerce, marketplace and B2B channels
- Multiple sale line items
- Decimal-based pricing, discounts and taxes
- Partial and full payment tracking
- Inventory and fulfillment references
- Refund and return tracking
- AI fraud and anomaly detection
- Human approval workflow
- Sales lifecycle management
- Immutable pricing snapshots after confirmation
- Audit history
- Soft deletion
- Optimistic concurrency control

IMPORTANT:
This model stores sale state only.

Payment capture, refunds, stock deduction, tax calculation,
customer authorization and fulfillment must be performed
by transactional services.

Never store card numbers, CVVs, payment secrets or other
sensitive payment credentials in this model.
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
MAX_DECIMAL = Decimal("100000000000000")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_sale_number() -> str:
    return f"SALE-{uuid.uuid4().hex[:16].upper()}"


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


def money(
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
        raise ValueError(f"{field} must be finite")

    if result < 0 or (positive and result == 0):
        raise ValueError(
            f"{field} must be positive"
            if positive
            else f"{field} must be nonnegative"
        )

    if result >= MAX_DECIMAL:
        raise ValueError(
            f"{field} exceeds supported precision"
        )

    if result != result.quantize(QUANTUM):
        raise ValueError(
            f"{field} supports at most 4 decimal places"
        )

    return result


def ratio(value, field: str) -> Decimal:
    result = money(value, field)

    if result > 1:
        raise ValueError(
            f"{field} must be between 0 and 1"
        )

    return result


def enum_value(value):
    return value.value if isinstance(value, enum.Enum) else value


def iso(value):
    return value.isoformat() if value else None


def decimal_string(value):
    return str(value) if value is not None else None


# ============================================================
# ENUMS
# ============================================================

class SaleStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    CONFIRMED = "confirmed"
    PAYMENT_PENDING = "payment_pending"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    FULFILLING = "fulfilling"
    PARTIALLY_FULFILLED = "partially_fulfilled"
    FULFILLED = "fulfilled"
    COMPLETED = "completed"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"
    ON_HOLD = "on_hold"
    FAILED = "failed"


class SaleChannel(str, enum.Enum):
    POS = "pos"
    ECOMMERCE = "ecommerce"
    MARKETPLACE = "marketplace"
    MOBILE_APP = "mobile_app"
    SOCIAL_COMMERCE = "social_commerce"
    B2B = "b2b"
    WHOLESALE = "wholesale"
    DIRECT = "direct"
    API = "api"


class SaleType(str, enum.Enum):
    RETAIL = "retail"
    WHOLESALE = "wholesale"
    B2B = "b2b"
    SUBSCRIPTION = "subscription"
    SERVICE = "service"
    DIGITAL = "digital"
    OTHER = "other"


class SaleSource(str, enum.Enum):
    MANUAL = "manual"
    POS = "pos"
    ECOMMERCE = "ecommerce"
    MARKETPLACE = "marketplace"
    ERP = "erp"
    API = "api"
    AI_AGENT = "ai_agent"
    IMPORT = "import"
    SYSTEM = "system"


class SalePaymentStatus(str, enum.Enum):
    UNPAID = "unpaid"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"
    FAILED = "failed"


class SaleFulfillmentStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    PENDING = "pending"
    PARTIALLY_FULFILLED = "partially_fulfilled"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"


class SaleApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SaleRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class SalePriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class SaleDiscountType(str, enum.Enum):
    NONE = "none"
    PERCENTAGE = "percentage"
    FIXED = "fixed"


# ============================================================
# SALE
# ============================================================

class Sale(Base):
    __tablename__ = "sales"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "sale_number",
            name="uq_sale_org_number",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_sale_org_idempotency",
        ),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_sale_org_id",
        ),
        CheckConstraint(
            "subtotal >= 0",
            name="sale_subtotal_nonnegative",
        ),
        CheckConstraint(
            "discount_amount >= 0",
            name="sale_discount_nonnegative",
        ),
        CheckConstraint(
            "tax_amount >= 0",
            name="sale_tax_nonnegative",
        ),
        CheckConstraint(
            "shipping_amount >= 0",
            name="sale_shipping_nonnegative",
        ),
        CheckConstraint(
            "total_amount >= 0",
            name="sale_total_nonnegative",
        ),
        CheckConstraint(
            "paid_amount >= 0",
            name="sale_paid_nonnegative",
        ),
        CheckConstraint(
            "refunded_amount >= 0",
            name="sale_refunded_nonnegative",
        ),
        CheckConstraint(
            "refunded_amount <= paid_amount",
            name="sale_refunded_limit",
        ),
        CheckConstraint(
            "ai_risk_score IS NULL OR "
            "(ai_risk_score >= 0 AND ai_risk_score <= 1)",
            name="sale_ai_risk_range",
        ),
        CheckConstraint(
            "ai_confidence IS NULL OR "
            "(ai_confidence >= 0 AND ai_confidence <= 1)",
            name="sale_ai_confidence_range",
        ),
        CheckConstraint(
            "version >= 1",
            name="sale_version_positive",
        ),
        Index(
            "ix_sale_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_sale_org_customer",
            "organization_id",
            "customer_id",
        ),
        Index(
            "ix_sale_org_warehouse",
            "organization_id",
            "warehouse_id",
        ),
        Index(
            "ix_sale_org_channel",
            "organization_id",
            "channel",
        ),
        Index(
            "ix_sale_org_created",
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
        default=new_uuid,
    )

    organization_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    sale_number: Mapped[str] = mapped_column(
        String(60),
        default=new_sale_number,
        nullable=False,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # --------------------------------------------------------
    # SALE DETAILS
    # --------------------------------------------------------

    status: Mapped[SaleStatus] = mapped_column(
        enum_column(SaleStatus, "sale_status"),
        default=SaleStatus.DRAFT,
        nullable=False,
    )

    sale_type: Mapped[SaleType] = mapped_column(
        enum_column(SaleType, "sale_type"),
        default=SaleType.RETAIL,
        nullable=False,
    )

    channel: Mapped[SaleChannel] = mapped_column(
        enum_column(SaleChannel, "sale_channel"),
        default=SaleChannel.ECOMMERCE,
        nullable=False,
    )

    source: Mapped[SaleSource] = mapped_column(
        enum_column(SaleSource, "sale_source"),
        default=SaleSource.MANUAL,
        nullable=False,
    )

    priority: Mapped[SalePriority] = mapped_column(
        enum_column(SalePriority, "sale_priority"),
        default=SalePriority.NORMAL,
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # REFERENCES
    # --------------------------------------------------------

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

    sales_agent_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    fulfillment_order_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    delivery_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    external_order_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    integration_id: Mapped[str | None] = mapped_column(
        String(36),
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

    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    shipping_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    refunded_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    discount_type: Mapped[SaleDiscountType] = mapped_column(
        enum_column(
            SaleDiscountType,
            "sale_discount_type",
        ),
        default=SaleDiscountType.NONE,
        nullable=False,
    )

    discount_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    coupon_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # --------------------------------------------------------
    # PAYMENT
    # --------------------------------------------------------

    payment_status: Mapped[
        SalePaymentStatus
    ] = mapped_column(
        enum_column(
            SalePaymentStatus,
            "sale_payment_status",
        ),
        default=SalePaymentStatus.UNPAID,
        nullable=False,
    )

    payment_method: Mapped[str | None] = mapped_column(
        String(60),
        nullable=True,
    )

    payment_reference: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    payment_references: Mapped[
        list[str]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    refund_references: Mapped[
        list[str]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # --------------------------------------------------------
    # FULFILLMENT
    # --------------------------------------------------------

    fulfillment_status: Mapped[
        SaleFulfillmentStatus
    ] = mapped_column(
        enum_column(
            SaleFulfillmentStatus,
            "sale_fulfillment_status",
        ),
        default=SaleFulfillmentStatus.NOT_STARTED,
        nullable=False,
    )

    # --------------------------------------------------------
    # RETURNS
    # --------------------------------------------------------

    return_request_ids: Mapped[
        list[str]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    refund_ids: Mapped[
        list[str]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # --------------------------------------------------------
    # AI ANALYTICS
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

    ai_risk_level: Mapped[SaleRiskLevel] = mapped_column(
        enum_column(
            SaleRiskLevel,
            "sale_risk_level",
        ),
        default=SaleRiskLevel.UNKNOWN,
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

    ai_features: Mapped[
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
    # APPROVAL
    # --------------------------------------------------------

    requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    approval_status: Mapped[
        SaleApprovalStatus
    ] = mapped_column(
        enum_column(
            SaleApprovalStatus,
            "sale_approval_status",
        ),
        default=SaleApprovalStatus.NOT_REQUIRED,
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

    approved_at: Mapped[
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
    # LIFECYCLE
    # --------------------------------------------------------

    confirmed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    paid_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    fulfilled_at: Mapped[
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

    previous_status: Mapped[
        SaleStatus | None
    ] = mapped_column(
        enum_column(
            SaleStatus,
            "sale_previous_status",
        ),
        nullable=True,
    )

    hold_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # AUDIT
    # --------------------------------------------------------

    sale_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    sale_history: Mapped[
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

    items: Mapped[list["SaleItem"]] = relationship(
        "SaleItem",
        back_populates="sale",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="SaleItem.line_number",
    )

    # ========================================================
    # PROPERTIES
    # ========================================================

    @property
    def balance_due(self) -> Decimal:
        return max(
            ZERO,
            self.total_amount - self.paid_amount,
        )

    @property
    def net_collected(self) -> Decimal:
        return self.paid_amount - self.refunded_amount

    @property
    def is_fully_paid(self) -> bool:
        return (
            self.total_amount > ZERO
            and self.paid_amount >= self.total_amount
        )

    @property
    def is_approved(self) -> bool:
        return (
            not self.requires_approval
            or self.approval_status
            == SaleApprovalStatus.APPROVED
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            SaleStatus.REFUNDED,
            SaleStatus.CANCELLED,
            SaleStatus.FAILED,
        }

    @property
    def total_quantity(self) -> Decimal:
        return sum(
            (item.quantity for item in self.items),
            ZERO,
        )

    @property
    def total_fulfilled_quantity(self) -> Decimal:
        return sum(
            (item.fulfilled_quantity for item in self.items),
            ZERO,
        )

    @property
    def is_fully_fulfilled(self) -> bool:
        return bool(self.items) and all(
            item.fulfilled_quantity == item.quantity
            for item in self.items
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _touch(self):
        self.updated_at = utc_now()

    def _ensure_active(self):
        if self.is_deleted:
            raise ValueError("Sale has been deleted")

    def _require_status(self, *allowed):
        self._ensure_active()

        if self.status not in allowed:
            raise ValueError(
                f"Invalid sale status: {self.status.value}"
            )

    def _record_event(
        self,
        event: str,
        *,
        actor_id: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        history = list(self.sale_history or [])

        history.append({
            "event_id": new_uuid(),
            "event": event,
            "actor_id": actor_id,
            "timestamp": utc_now().isoformat(),
            "details": details or {},
        })

        self.sale_history = history
        self._touch()

    def _get_item(self, item_id: str) -> "SaleItem":
        for item in self.items:
            if item.id == item_id:
                return item

        raise ValueError("Sale item not found")

    # ========================================================
    # ADD SALE ITEM
    # ========================================================

    def add_item(
        self,
        *,
        product_id: str,
        sku: str,
        product_name: str,
        quantity: Decimal | str | int | float,
        unit_price: Decimal | str | int | float,
        actor_id: str,
        unit_cost: Decimal | str | int | float = ZERO,
        tax_rate: Decimal | str | int | float = ZERO,
        discount_amount: Decimal | str | int | float = ZERO,
    ) -> "SaleItem":
        self._require_status(SaleStatus.DRAFT)

        if any(
            item.product_id == product_id
            for item in self.items
        ):
            raise ValueError(
                "Product already exists in this sale"
            )

        item = SaleItem(
            organization_id=self.organization_id,
            line_number=max(
                (line.line_number for line in self.items),
                default=0,
            ) + 1,
            product_id=required_text(
                product_id, "Product ID"
            ),
            sku=required_text(sku, "SKU"),
            product_name=required_text(
                product_name, "Product name"
            ),
            quantity=money(
                quantity, "quantity", positive=True
            ),
            unit_price=money(
                unit_price, "unit_price"
            ),
            unit_cost=money(
                unit_cost, "unit_cost"
            ),
            tax_rate=ratio(tax_rate, "tax_rate"),
            discount_amount=money(
                discount_amount, "discount_amount"
            ),
        )

        item.recalculate()

        self.items.append(item)
        self.recalculate_totals()

        self._record_event(
            "sale_item_added",
            actor_id=actor_id,
            details={
                "product_id": product_id,
                "quantity": str(item.quantity),
            },
        )

        return item

    # ========================================================
    # CALCULATE TOTALS
    # ========================================================

    def recalculate_totals(self):
        self._require_status(SaleStatus.DRAFT)

        for item in self.items:
            item.recalculate()

        self.subtotal = sum(
            (item.subtotal for item in self.items),
            ZERO,
        ).quantize(QUANTUM)

        line_discounts = sum(
            (item.discount_amount for item in self.items),
            ZERO,
        )

        if self.discount_type == SaleDiscountType.NONE:
            order_discount = ZERO

        elif self.discount_type == (
            SaleDiscountType.PERCENTAGE
        ):
            if self.discount_value > 100:
                raise ValueError(
                    "Percentage discount cannot exceed 100"
                )

            order_discount = (
                (self.subtotal - line_discounts)
                * self.discount_value
                / Decimal("100")
            ).quantize(QUANTUM)

        else:
            order_discount = self.discount_value

        if order_discount > self.subtotal - line_discounts:
            raise ValueError(
                "Discount exceeds sale subtotal"
            )

        # Line taxes are calculated before order-level
        # discount. Production tax services must allocate
        # order-level discounts and recompute taxable bases.
        self.discount_amount = (
            line_discounts + order_discount
        ).quantize(QUANTUM)

        self.tax_amount = sum(
            (item.tax_amount for item in self.items),
            ZERO,
        ).quantize(QUANTUM)

        self.total_amount = (
            self.subtotal
            - self.discount_amount
            + self.tax_amount
            + self.shipping_amount
        ).quantize(QUANTUM)

        self._touch()

    # ========================================================
    # CONFIGURE DISCOUNT
    # ========================================================

    def configure_discount(
        self,
        *,
        discount_type: SaleDiscountType,
        discount_value: Decimal | str | int | float,
        actor_id: str,
        coupon_code: str | None = None,
    ):
        self._require_status(SaleStatus.DRAFT)

        value = money(
            discount_value, "discount_value"
        )

        if (
            discount_type == SaleDiscountType.PERCENTAGE
            and value > 100
        ):
            raise ValueError(
                "Percentage discount cannot exceed 100"
            )

        if (
            discount_type == SaleDiscountType.NONE
            and value != ZERO
        ):
            raise ValueError(
                "NONE discount must have zero value"
            )

        old_type = self.discount_type
        old_value = self.discount_value
        old_coupon = self.coupon_code

        self.discount_type = discount_type
        self.discount_value = value
        self.coupon_code = coupon_code

        try:
            self.recalculate_totals()
        except Exception:
            self.discount_type = old_type
            self.discount_value = old_value
            self.coupon_code = old_coupon
            self.recalculate_totals()
            raise

        self._record_event(
            "sale_discount_configured",
            actor_id=actor_id,
        )

    # ========================================================
    # AI RISK
    # ========================================================

    def update_ai_risk(
        self,
        *,
        model_id: str,
        risk_score: Decimal | str | int | float,
        confidence: Decimal | str | int | float,
        risk_level: SaleRiskLevel,
        recommendation: str,
        explanation: str,
        features: dict[str, Any],
        agent_run_id: str | None = None,
    ):
        self._ensure_active()

        if self.is_terminal:
            raise ValueError(
                "Cannot update terminal sale"
            )

        self.ai_model_id = required_text(
            model_id, "Model ID"
        )
        self.ai_agent_run_id = agent_run_id
        self.ai_risk_score = ratio(
            risk_score, "risk_score"
        )
        self.ai_confidence = ratio(
            confidence, "confidence"
        )
        self.ai_risk_level = risk_level
        self.ai_recommendation = required_text(
            recommendation, "Recommendation"
        )
        self.ai_explanation = required_text(
            explanation, "Explanation"
        )
        self.ai_features = dict(features)
        self.ai_analyzed_at = utc_now()

        self._record_event(
            "sale_ai_risk_updated",
            details={
                "risk_level": risk_level.value,
                "model_id": model_id,
            },
        )

    # ========================================================
    # APPROVAL
    # ========================================================

    def request_approval(
        self,
        *,
        actor_id: str,
        approval_request_id: str | None = None,
    ):
        self._require_status(SaleStatus.DRAFT)

        if not self.items:
            raise ValueError("Sale has no items")

        self.recalculate_totals()

        if self.requires_approval:
            self.approval_request_id = required_text(
                approval_request_id,
                "Approval request ID",
            )
            self.approval_status = (
                SaleApprovalStatus.PENDING
            )
            self.status = SaleStatus.PENDING_APPROVAL
        else:
            self.approval_status = (
                SaleApprovalStatus.NOT_REQUIRED
            )
            self.status = SaleStatus.APPROVED

        self._record_event(
            "sale_approval_requested",
            actor_id=actor_id,
        )

    def approve(self, *, approver_id: str):
        self._require_status(
            SaleStatus.PENDING_APPROVAL
        )

        # Authorization and linked approval must be
        # verified by the approval service.

        self.approval_status = (
            SaleApprovalStatus.APPROVED
        )
        self.approved_by = required_text(
            approver_id, "Approver ID"
        )
        self.approved_at = utc_now()
        self.status = SaleStatus.APPROVED

        self._record_event(
            "sale_approved",
            actor_id=approver_id,
        )

    # ========================================================
    # CONFIRM
    # ========================================================

    def confirm(self, *, actor_id: str):
        self._require_status(SaleStatus.APPROVED)

        if not self.is_approved:
            raise ValueError("Sale approval incomplete")

        if not self.items:
            raise ValueError("Sale has no items")

        if self.total_amount <= ZERO:
            raise ValueError(
                "Sale total must be positive"
            )

        self.status = SaleStatus.CONFIRMED
        self.confirmed_at = utc_now()

        self._record_event(
            "sale_confirmed",
            actor_id=actor_id,
        )

    # ========================================================
    # RECORD PAYMENT
    # ========================================================

    def record_payment(
        self,
        *,
        amount: Decimal | str | int | float,
        payment_reference: str,
        payment_method: str,
        actor_id: str,
    ):
        self._require_status(
            SaleStatus.CONFIRMED,
            SaleStatus.PAYMENT_PENDING,
            SaleStatus.PARTIALLY_PAID,
        )

        amount = money(
            amount, "amount", positive=True
        )

        reference = required_text(
            payment_reference, "Payment reference"
        )

        if reference in self.payment_references:
            raise ValueError(
                "Payment reference already recorded"
            )

        if amount > self.balance_due:
            raise ValueError(
                "Payment exceeds outstanding balance"
            )

        # Payment service must verify actual settlement
        # before recording the amount.

        self.paid_amount += amount

        references = list(self.payment_references or [])
        references.append(reference)
        self.payment_references = references

        self.payment_reference = reference
        self.payment_method = required_text(
            payment_method, "Payment method"
        )

        if self.is_fully_paid:
            self.payment_status = SalePaymentStatus.PAID
            self.status = SaleStatus.PAID
            self.paid_at = utc_now()
        else:
            self.payment_status = (
                SalePaymentStatus.PARTIALLY_PAID
            )
            self.status = SaleStatus.PARTIALLY_PAID

        self._record_event(
            "sale_payment_recorded",
            actor_id=actor_id,
            details={
                "amount": str(amount),
                "reference": reference,
            },
        )

    # ========================================================
    # START FULFILLMENT
    # ========================================================

    def start_fulfillment(
        self,
        *,
        actor_id: str,
        fulfillment_order_id: str,
    ):
        self._require_status(SaleStatus.PAID)

        self.fulfillment_order_id = required_text(
            fulfillment_order_id,
            "Fulfillment order ID",
        )

        self.fulfillment_status = (
            SaleFulfillmentStatus.PENDING
        )
        self.status = SaleStatus.FULFILLING

        self._record_event(
            "sale_fulfillment_started",
            actor_id=actor_id,
        )

    # ========================================================
    # RECORD FULFILLMENT
    # ========================================================

    def record_fulfillment(
        self,
        *,
        item_id: str,
        quantity: Decimal | str | int | float,
        actor_id: str,
        fulfillment_reference: str,
    ):
        self._require_status(
            SaleStatus.FULFILLING,
            SaleStatus.PARTIALLY_FULFILLED,
        )

        item = self._get_item(item_id)

        item.record_fulfilled(
            quantity=quantity,
            reference=fulfillment_reference,
        )

        if self.is_fully_fulfilled:
            self.fulfillment_status = (
                SaleFulfillmentStatus.FULFILLED
            )
            self.status = SaleStatus.FULFILLED
            self.fulfilled_at = utc_now()
        else:
            self.fulfillment_status = (
                SaleFulfillmentStatus.PARTIALLY_FULFILLED
            )
            self.status = SaleStatus.PARTIALLY_FULFILLED

        self._record_event(
            "sale_item_fulfilled",
            actor_id=actor_id,
            details={
                "item_id": item_id,
                "quantity": str(quantity),
            },
        )

    # ========================================================
    # COMPLETE
    # ========================================================

    def complete(self, *, actor_id: str):
        self._require_status(SaleStatus.FULFILLED)

        if not self.is_fully_paid:
            raise ValueError("Sale not fully paid")

        if not self.is_fully_fulfilled:
            raise ValueError(
                "Sale not fully fulfilled"
            )

        self.status = SaleStatus.COMPLETED
        self.completed_at = utc_now()

        self._record_event(
            "sale_completed",
            actor_id=actor_id,
        )

    # ========================================================
    # RECORD REFUND
    # ========================================================

    def record_refund(
        self,
        *,
        refund_id: str,
        refund_reference: str,
        amount: Decimal | str | int | float,
        actor_id: str,
    ):
        self._require_status(
            SaleStatus.PAID,
            SaleStatus.FULFILLING,
            SaleStatus.PARTIALLY_FULFILLED,
            SaleStatus.FULFILLED,
            SaleStatus.COMPLETED,
            SaleStatus.PARTIALLY_REFUNDED,
        )

        amount = money(
            amount, "amount", positive=True
        )

        reference = required_text(
            refund_reference, "Refund reference"
        )
        refund_id = required_text(
            refund_id, "Refund ID"
        )

        if reference in self.refund_references:
            raise ValueError(
                "Refund reference already recorded"
            )

        if refund_id in self.refund_ids:
            raise ValueError(
                "Refund ID already recorded"
            )

        if amount > self.paid_amount - self.refunded_amount:
            raise ValueError(
                "Refund exceeds available paid amount"
            )

        # Payment service must verify successful refund
        # and return eligibility before this call.

        self.refunded_amount += amount

        self.refund_ids = [
            *(self.refund_ids or []),
            refund_id,
        ]
        self.refund_references = [
            *(self.refund_references or []),
            reference,
        ]

        if self.refunded_amount == self.paid_amount:
            self.payment_status = (
                SalePaymentStatus.REFUNDED
            )
            self.status = SaleStatus.REFUNDED
        else:
            self.payment_status = (
                SalePaymentStatus.PARTIALLY_REFUNDED
            )
            self.status = SaleStatus.PARTIALLY_REFUNDED

        self._record_event(
            "sale_refund_recorded",
            actor_id=actor_id,
            details={
                "refund_id": refund_id,
                "amount": str(amount),
            },
        )

    # ========================================================
    # LINK RETURN REQUEST
    # ========================================================

    def link_return_request(
        self,
        *,
        return_request_id: str,
        actor_id: str,
    ):
        self._ensure_active()

        if self.status in {
            SaleStatus.DRAFT,
            SaleStatus.CANCELLED,
            SaleStatus.FAILED,
        }:
            raise ValueError(
                "Sale is not eligible for a return link"
            )

        reference = required_text(
            return_request_id, "Return request ID"
        )

        if reference in self.return_request_ids:
            return

        self.return_request_ids = [
            *(self.return_request_ids or []),
            reference,
        ]

        self._record_event(
            "sale_return_request_linked",
            actor_id=actor_id,
            details={"return_request_id": reference},
        )

    # ========================================================
    # HOLD / RELEASE
    # ========================================================

    def place_on_hold(
        self,
        *,
        actor_id: str,
        reason: str,
    ):
        self._ensure_active()

        if self.is_terminal or self.status == SaleStatus.ON_HOLD:
            raise ValueError(
                "Sale cannot be placed on hold"
            )

        self.previous_status = self.status
        self.status = SaleStatus.ON_HOLD
        self.hold_reason = required_text(
            reason, "Hold reason"
        )

        self._record_event(
            "sale_on_hold",
            actor_id=actor_id,
            details={"reason": reason},
        )

    def release_hold(self, *, actor_id: str):
        self._require_status(SaleStatus.ON_HOLD)

        if self.previous_status is None:
            raise ValueError(
                "Previous sale status missing"
            )

        self.status = self.previous_status
        self.previous_status = None
        self.hold_reason = None

        self._record_event(
            "sale_hold_released",
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
    ):
        self._require_status(
            SaleStatus.DRAFT,
            SaleStatus.PENDING_APPROVAL,
            SaleStatus.APPROVED,
            SaleStatus.CONFIRMED,
            SaleStatus.PAYMENT_PENDING,
        )

        if self.paid_amount > ZERO:
            raise ValueError(
                "Paid sale requires refund or reversal"
            )

        if self.total_fulfilled_quantity > ZERO:
            raise ValueError(
                "Fulfilled sale cannot be directly cancelled"
            )

        self.status = SaleStatus.CANCELLED
        self.cancelled_by = required_text(
            actor_id, "Actor ID"
        )
        self.cancelled_at = utc_now()
        self.cancellation_reason = required_text(
            reason, "Cancellation reason"
        )

        self._record_event(
            "sale_cancelled",
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # FAIL
    # ========================================================

    def mark_failed(
        self,
        *,
        actor_id: str,
        reason: str,
    ):
        self._ensure_active()

        if self.is_terminal:
            raise ValueError(
                "Terminal sale cannot fail"
            )

        if self.paid_amount > ZERO:
            raise ValueError(
                "Paid sale requires payment reconciliation"
            )

        self.status = SaleStatus.FAILED
        self.failure_reason = required_text(
            reason, "Failure reason"
        )

        self._record_event(
            "sale_failed",
            actor_id=actor_id,
        )

    # ========================================================
    # SOFT DELETE
    # ========================================================

    def soft_delete(self, *, actor_id: str):
        self._require_status(
            SaleStatus.DRAFT,
            SaleStatus.CANCELLED,
            SaleStatus.FAILED,
        )

        if self.paid_amount > ZERO:
            raise ValueError(
                "Financially active sale cannot be deleted"
            )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = required_text(
            actor_id, "Actor ID"
        )

        self._record_event(
            "sale_soft_deleted",
            actor_id=actor_id,
        )

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(
        self,
        *,
        include_items: bool = True,
        include_history: bool = False,
        include_internal: bool = False,
    ) -> dict[str, Any]:
        result = {
            "id": self.id,
            "organization_id": self.organization_id,
            "sale_number": self.sale_number,
            "status": enum_value(self.status),
            "sale_type": enum_value(self.sale_type),
            "channel": enum_value(self.channel),
            "source": enum_value(self.source),
            "priority": enum_value(self.priority),
            "customer_id": self.customer_id,
            "warehouse_id": self.warehouse_id,
            "store_id": self.store_id,
            "fulfillment_order_id": self.fulfillment_order_id,
            "delivery_id": self.delivery_id,
            "external_order_id": self.external_order_id,
            "currency": self.currency,
            "subtotal": decimal_string(self.subtotal),
            "discount_amount": decimal_string(
                self.discount_amount
            ),
            "tax_amount": decimal_string(
                self.tax_amount
            ),
            "shipping_amount": decimal_string(
                self.shipping_amount
            ),
            "total_amount": decimal_string(
                self.total_amount
            ),
            "paid_amount": decimal_string(
                self.paid_amount
            ),
            "refunded_amount": decimal_string(
                self.refunded_amount
            ),
            "balance_due": decimal_string(
                self.balance_due
            ),
            "net_collected": decimal_string(
                self.net_collected
            ),
            "payment_status": enum_value(
                self.payment_status
            ),
            "fulfillment_status": enum_value(
                self.fulfillment_status
            ),
            "discount_type": enum_value(
                self.discount_type
            ),
            "discount_value": decimal_string(
                self.discount_value
            ),
            "coupon_code": self.coupon_code,
            "total_quantity": decimal_string(
                self.total_quantity
            ),
            "total_fulfilled_quantity": decimal_string(
                self.total_fulfilled_quantity
            ),
            "is_fully_paid": self.is_fully_paid,
            "is_fully_fulfilled": self.is_fully_fulfilled,
            "return_request_ids": self.return_request_ids,
            "refund_ids": self.refund_ids,
            "confirmed_at": iso(self.confirmed_at),
            "paid_at": iso(self.paid_at),
            "fulfilled_at": iso(self.fulfilled_at),
            "completed_at": iso(self.completed_at),
            "cancelled_at": iso(self.cancelled_at),
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
                "ai_features": self.ai_features,
                "approval_status": enum_value(
                    self.approval_status
                ),
                "approval_request_id": (
                    self.approval_request_id
                ),
                "sale_metadata": self.sale_metadata,
                "trace_id": self.trace_id,
                "correlation_id": self.correlation_id,
            })

        if include_history:
            result["sale_history"] = self.sale_history

        return result

    def __repr__(self):
        return (
            f"<Sale("
            f"id={self.id}, "
            f"sale_number={self.sale_number}, "
            f"status={enum_value(self.status)}"
            f")>"
        )


# ============================================================
# SALE ITEM
# ============================================================

class SaleItem(Base):
    __tablename__ = "sale_items"

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "sale_id"],
            ["sales.organization_id", "sales.id"],
            name="fk_sale_item_same_tenant",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "sale_id",
            "line_number",
            name="uq_sale_item_line",
        ),
        CheckConstraint(
            "quantity > 0",
            name="sale_item_quantity_positive",
        ),
        CheckConstraint(
            "fulfilled_quantity >= 0",
            name="sale_item_fulfilled_nonnegative",
        ),
        CheckConstraint(
            "fulfilled_quantity <= quantity",
            name="sale_item_fulfilled_limit",
        ),
        CheckConstraint(
            "unit_price >= 0",
            name="sale_item_price_nonnegative",
        ),
        CheckConstraint(
            "unit_cost >= 0",
            name="sale_item_cost_nonnegative",
        ),
        CheckConstraint(
            "discount_amount >= 0",
            name="sale_item_discount_nonnegative",
        ),
        CheckConstraint(
            "tax_rate >= 0 AND tax_rate <= 1",
            name="sale_item_tax_rate_range",
        ),
        Index(
            "ix_sale_item_org_product",
            "organization_id",
            "product_id",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_uuid,
    )

    organization_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    sale_id: Mapped[str] = mapped_column(
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

    sku: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    product_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
    )

    fulfilled_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        nullable=False,
    )

    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(6, 4),
        default=ZERO,
        nullable=False,
    )

    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    fulfillment_references: Mapped[
        list[str]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
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

    sale: Mapped["Sale"] = relationship(
        "Sale",
        back_populates="items",
    )

    # ========================================================
    # PROPERTIES
    # ========================================================

    @property
    def remaining_to_fulfill(self) -> Decimal:
        return self.quantity - self.fulfilled_quantity

    @property
    def gross_profit(self) -> Decimal:
        return (
            self.total_amount
            - self.tax_amount
            - self.quantity * self.unit_cost
        ).quantize(QUANTUM)

    # ========================================================
    # RECALCULATE
    # ========================================================

    def recalculate(self):
        subtotal = (
            self.quantity * self.unit_price
        ).quantize(QUANTUM)

        if self.discount_amount > subtotal:
            raise ValueError(
                "Line discount exceeds subtotal"
            )

        taxable = subtotal - self.discount_amount

        tax = (
            taxable * self.tax_rate
        ).quantize(QUANTUM)

        self.subtotal = subtotal
        self.tax_amount = tax
        self.total_amount = (
            taxable + tax
        ).quantize(QUANTUM)

        self.updated_at = utc_now()

    # ========================================================
    # FULFILL
    # ========================================================

    def record_fulfilled(
        self,
        *,
        quantity: Decimal | str | int | float,
        reference: str,
    ):
        quantity = money(
            quantity, "quantity", positive=True
        )
        reference = required_text(
            reference, "Fulfillment reference"
        )

        if reference in self.fulfillment_references:
            raise ValueError(
                "Fulfillment reference already recorded"
            )

        if quantity > self.remaining_to_fulfill:
            raise ValueError(
                "Fulfilled quantity exceeds ordered quantity"
            )

        self.fulfilled_quantity += quantity

        self.fulfillment_references = [
            *(self.fulfillment_references or []),
            reference,
        ]

        self.updated_at = utc_now()

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(self):
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "sale_id": self.sale_id,
            "line_number": self.line_number,
            "product_id": self.product_id,
            "sku": self.sku,
            "product_name": self.product_name,
            "quantity": decimal_string(self.quantity),
            "fulfilled_quantity": decimal_string(
                self.fulfilled_quantity
            ),
            "remaining_to_fulfill": decimal_string(
                self.remaining_to_fulfill
            ),
            "unit_price": decimal_string(
                self.unit_price
            ),
            "unit_cost": decimal_string(
                self.unit_cost
            ),
            "discount_amount": decimal_string(
                self.discount_amount
            ),
            "tax_rate": decimal_string(
                self.tax_rate
            ),
            "subtotal": decimal_string(
                self.subtotal
            ),
            "tax_amount": decimal_string(
                self.tax_amount
            ),
            "total_amount": decimal_string(
                self.total_amount
            ),
            "gross_profit": decimal_string(
                self.gross_profit
            ),
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
        }

    def __repr__(self):
        return (
            f"<SaleItem("
            f"id={self.id}, "
            f"product_id={self.product_id}, "
            f"quantity={self.quantity}"
            f")>"
        )