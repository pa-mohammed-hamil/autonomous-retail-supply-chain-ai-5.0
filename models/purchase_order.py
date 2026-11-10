from __future__ import annotations

"""Planned module: purchase order. Implementation pending."""

"""
backend/models/purchase_order.py

Autonomous Retail Supply Chain AI 5.0
Enterprise Purchase Order Management

Features:
- Multi-tenant purchase orders
- Multiple purchase order line items
- Supplier and warehouse references
- AI-driven replenishment recommendations
- Supplier risk and lead-time intelligence
- Draft, approval, dispatch, receipt workflows
- Partial deliveries and receiving
- Tax, discounts, shipping and total calculations
- Purchase order amendments
- Cancellation and closure
- Idempotency and optimistic locking
- Audit history and soft deletion

Important:
    Model methods only update ORM state.

    Actual supplier communication, inventory receipt,
    accounting entries, invoice matching, approvals
    and external integrations belong in services.
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
# HELPERS
# ============================================================

MONEY_ZERO = Decimal("0.0000")
MONEY_QUANTUM = Decimal("0.0001")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_po_number() -> str:
    return f"PO-{uuid.uuid4().hex[:16].upper()}"


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
    value: Decimal | int | float | str,
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

    if result >= Decimal("100000000000000"):
        raise ValueError(
            f"{field} exceeds supported precision"
        )

    if result != result.quantize(MONEY_QUANTUM):
        raise ValueError(
            f"{field} supports at most 4 decimal places"
        )

    return result


def score_decimal(
    value: Decimal | int | float | str,
    field: str,
) -> Decimal:
    result = nonnegative_decimal(value, field)

    if result > 1:
        raise ValueError(
            f"{field} must be between 0 and 1"
        )

    return result


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError(
            "Timezone-aware datetime required"
        )
    return value.astimezone(timezone.utc)


def enum_value(value: enum.Enum | None):
    return value.value if value is not None else None


def iso(value: datetime | None):
    return value.isoformat() if value else None


def money(value: Decimal | None):
    return str(value) if value is not None else None


# ============================================================
# ENUMS
# ============================================================

class PurchaseOrderStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class PurchaseOrderType(str, enum.Enum):
    STANDARD = "standard"
    REPLENISHMENT = "replenishment"
    EMERGENCY = "emergency"
    BLANKET = "blanket"
    DROP_SHIPPING = "drop_shipping"
    INTERCOMPANY = "intercompany"
    RETURN_REPLACEMENT = "return_replacement"


class PurchaseOrderPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    EMERGENCY = "emergency"


class PurchaseOrderSource(str, enum.Enum):
    MANUAL = "manual"
    REORDER_RULE = "reorder_rule"
    DEMAND_FORECAST = "demand_forecast"
    AI_AGENT = "ai_agent"
    ERP = "erp"
    WMS = "wms"
    API = "api"
    SCHEDULER = "scheduler"


class PurchaseOrderApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PurchaseOrderPaymentStatus(str, enum.Enum):
    UNPAID = "unpaid"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    REFUNDED = "refunded"


class PurchaseOrderLineStatus(str, enum.Enum):
    OPEN = "open"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class SupplierRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


# ============================================================
# PURCHASE ORDER
# ============================================================

class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "po_number",
            name="uq_po_org_number",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_po_org_idempotency",
        ),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_po_org_id",
        ),
        CheckConstraint(
            "subtotal >= 0",
            name="po_subtotal_nonnegative",
        ),
        CheckConstraint(
            "tax_amount >= 0",
            name="po_tax_nonnegative",
        ),
        CheckConstraint(
            "discount_amount >= 0",
            name="po_discount_nonnegative",
        ),
        CheckConstraint(
            "shipping_cost >= 0",
            name="po_shipping_nonnegative",
        ),
        CheckConstraint(
            "other_charges >= 0",
            name="po_other_charges_nonnegative",
        ),
        CheckConstraint(
            "total_amount >= 0",
            name="po_total_nonnegative",
        ),
        CheckConstraint(
            "supplier_risk_score IS NULL OR "
            "(supplier_risk_score >= 0 "
            "AND supplier_risk_score <= 1)",
            name="po_supplier_risk_range",
        ),
        CheckConstraint(
            "ai_confidence IS NULL OR "
            "(ai_confidence >= 0 AND ai_confidence <= 1)",
            name="po_ai_confidence_range",
        ),
        CheckConstraint(
            "version >= 1",
            name="po_version_positive",
        ),
        Index(
            "ix_po_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_po_org_supplier",
            "organization_id",
            "supplier_id",
        ),
        Index(
            "ix_po_org_warehouse",
            "organization_id",
            "warehouse_id",
        ),
        Index(
            "ix_po_org_expected_delivery",
            "organization_id",
            "expected_delivery_at",
        ),
        Index(
            "ix_po_org_created",
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

    po_number: Mapped[str] = mapped_column(
        String(50),
        default=generate_po_number,
        nullable=False,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # --------------------------------------------------------
    # ORDER DETAILS
    # --------------------------------------------------------

    status: Mapped[
        PurchaseOrderStatus
    ] = mapped_column(
        enum_column(
            PurchaseOrderStatus,
            "purchase_order_status",
        ),
        default=PurchaseOrderStatus.DRAFT,
        nullable=False,
    )

    order_type: Mapped[
        PurchaseOrderType
    ] = mapped_column(
        enum_column(
            PurchaseOrderType,
            "purchase_order_type",
        ),
        default=PurchaseOrderType.STANDARD,
        nullable=False,
    )

    priority: Mapped[
        PurchaseOrderPriority
    ] = mapped_column(
        enum_column(
            PurchaseOrderPriority,
            "purchase_order_priority",
        ),
        default=PurchaseOrderPriority.NORMAL,
        nullable=False,
    )

    source: Mapped[
        PurchaseOrderSource
    ] = mapped_column(
        enum_column(
            PurchaseOrderSource,
            "purchase_order_source",
        ),
        default=PurchaseOrderSource.MANUAL,
        nullable=False,
    )

    title: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # SUPPLIER / WAREHOUSE
    # --------------------------------------------------------

    supplier_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    warehouse_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    supplier_reference: Mapped[
        str | None
    ] = mapped_column(
        String(150),
        nullable=True,
    )

    supplier_contact_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    delivery_address: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    billing_address: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # REFERENCES
    # --------------------------------------------------------

    demand_forecast_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    supplier_risk_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    inventory_replenishment_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    integration_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    external_order_id: Mapped[
        str | None
    ] = mapped_column(
        String(150),
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
        default=MONEY_ZERO,
        nullable=False,
    )

    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=MONEY_ZERO,
        nullable=False,
    )

    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=MONEY_ZERO,
        nullable=False,
    )

    shipping_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=MONEY_ZERO,
        nullable=False,
    )

    other_charges: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=MONEY_ZERO,
        nullable=False,
    )

    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=MONEY_ZERO,
        nullable=False,
    )

    payment_terms: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    payment_status: Mapped[
        PurchaseOrderPaymentStatus
    ] = mapped_column(
        enum_column(
            PurchaseOrderPaymentStatus,
            "purchase_order_payment_status",
        ),
        default=PurchaseOrderPaymentStatus.UNPAID,
        nullable=False,
    )

    # --------------------------------------------------------
    # DELIVERY
    # --------------------------------------------------------

    order_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    expected_delivery_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    actual_delivery_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    shipping_method: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    tracking_number: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    latest_delivery_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # AI / SUPPLIER INTELLIGENCE
    # --------------------------------------------------------

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

    ai_explanation: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    ai_analysis: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    supplier_risk_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    supplier_risk_level: Mapped[
        SupplierRiskLevel
    ] = mapped_column(
        enum_column(
            SupplierRiskLevel,
            "po_supplier_risk_level",
        ),
        default=SupplierRiskLevel.UNKNOWN,
        nullable=False,
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
        PurchaseOrderApprovalStatus
    ] = mapped_column(
        enum_column(
            PurchaseOrderApprovalStatus,
            "purchase_order_approval_status",
        ),
        default=PurchaseOrderApprovalStatus.NOT_REQUIRED,
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
    # LIFECYCLE
    # --------------------------------------------------------

    sent_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    acknowledged_at: Mapped[
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

    closed_by: Mapped[str | None] = mapped_column(
        String(36),
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
    # METADATA / AUDIT
    # --------------------------------------------------------

    po_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    order_history: Mapped[
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

    # --------------------------------------------------------
    # LINE ITEMS
    # --------------------------------------------------------

    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        "PurchaseOrderItem",
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="PurchaseOrderItem.line_number",
    )

    # ========================================================
    # PROPERTIES
    # ========================================================

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            PurchaseOrderStatus.CLOSED,
            PurchaseOrderStatus.CANCELLED,
            PurchaseOrderStatus.REJECTED,
        }

    @property
    def is_approved(self) -> bool:
        return (
            not self.requires_approval
            or self.approval_status
            == PurchaseOrderApprovalStatus.APPROVED
        )

    @property
    def is_fully_received(self) -> bool:
        active_items = [
            item for item in self.items
            if item.status != PurchaseOrderLineStatus.CANCELLED
        ]

        return bool(active_items) and all(
            item.quantity_received >= item.quantity_ordered
            for item in active_items
        )

    @property
    def total_ordered_quantity(self) -> Decimal:
        return sum(
            (
                item.quantity_ordered
                for item in self.items
                if item.status
                != PurchaseOrderLineStatus.CANCELLED
            ),
            MONEY_ZERO,
        )

    @property
    def total_received_quantity(self) -> Decimal:
        return sum(
            (
                item.quantity_received
                for item in self.items
                if item.status
                != PurchaseOrderLineStatus.CANCELLED
            ),
            MONEY_ZERO,
        )

    @property
    def is_overdue(self) -> bool:
        return (
            self.expected_delivery_at is not None
            and utc_now() > ensure_aware(
                self.expected_delivery_at
            )
            and self.status in {
                PurchaseOrderStatus.SENT,
                PurchaseOrderStatus.ACKNOWLEDGED,
                PurchaseOrderStatus.PARTIALLY_RECEIVED,
            }
        )

    # ========================================================
    # INTERNAL METHODS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_editable(self) -> None:
        if self.is_deleted:
            raise ValueError("Purchase order is deleted")

        if self.status != PurchaseOrderStatus.DRAFT:
            raise ValueError(
                "Only draft purchase orders are editable"
            )

    def _ensure_active(self) -> None:
        if self.is_deleted or self.is_terminal:
            raise ValueError(
                "Purchase order is not active"
            )

    def _record_event(
        self,
        event: str,
        *,
        actor_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        history = list(self.order_history or [])

        history.append({
            "event_id": generate_uuid(),
            "event": event,
            "actor_id": actor_id,
            "timestamp": utc_now().isoformat(),
            "details": details or {},
        })

        self.order_history = history
        self._touch()

    # ========================================================
    # ADD LINE ITEM
    # ========================================================

    def add_item(
        self,
        *,
        product_id: str,
        sku: str,
        product_name: str,
        quantity: Decimal | int | float | str,
        unit_price: Decimal | int | float | str,
        actor_id: str,
        tax_rate: Decimal | int | float | str = 0,
        discount_amount: Decimal | int | float | str = 0,
        unit_of_measure: str = "units",
    ) -> "PurchaseOrderItem":
        self._ensure_editable()

        quantity = nonnegative_decimal(
            quantity,
            "quantity",
            allow_zero=False,
        )
        unit_price = nonnegative_decimal(
            unit_price,
            "unit_price",
        )
        tax_rate = nonnegative_decimal(
            tax_rate,
            "tax_rate",
        )
        discount_amount = nonnegative_decimal(
            discount_amount,
            "discount_amount",
        )

        if tax_rate > 100:
            raise ValueError(
                "Tax rate cannot exceed 100%"
            )

        line_number = max(
            (item.line_number for item in self.items),
            default=0,
        ) + 1

        item = PurchaseOrderItem(
            organization_id=self.organization_id,
            line_number=line_number,
            product_id=require_text(
                product_id,
                "Product ID",
            ),
            sku=require_text(sku, "SKU"),
            product_name=require_text(
                product_name,
                "Product name",
            ),
            quantity_ordered=quantity,
            unit_price=unit_price,
            tax_rate=tax_rate,
            discount_amount=discount_amount,
            unit_of_measure=require_text(
                unit_of_measure,
                "Unit of measure",
            ),
        )

        item.recalculate()
        self.items.append(item)
        self.recalculate_totals()

        self._record_event(
            "purchase_order_item_added",
            actor_id=actor_id,
            details={
                "product_id": product_id,
                "quantity": str(quantity),
            },
        )

        return item

    # ========================================================
    # REMOVE LINE ITEM
    # ========================================================

    def remove_item(
        self,
        *,
        item_id: str,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        item = next(
            (
                item for item in self.items
                if item.id == item_id
            ),
            None,
        )

        if item is None:
            raise ValueError("Purchase order item not found")

        self.items.remove(item)
        self.recalculate_totals()

        self._record_event(
            "purchase_order_item_removed",
            actor_id=actor_id,
            details={"item_id": item_id},
        )

    # ========================================================
    # RECALCULATE TOTALS
    # ========================================================

    def recalculate_totals(self) -> None:
        self._ensure_editable()

        for item in self.items:
            item.recalculate()

        subtotal = sum(
            (
                item.line_subtotal
                for item in self.items
            ),
            MONEY_ZERO,
        )

        line_discounts = sum(
            (
                item.discount_amount
                for item in self.items
            ),
            MONEY_ZERO,
        )

        tax_total = sum(
            (
                item.tax_amount
                for item in self.items
            ),
            MONEY_ZERO,
        )

        # Header discount_amount represents the
        # order-level discount only. Line discounts
        # are already applied to line taxable totals.

        total = (
            subtotal
            - line_discounts
            - self.discount_amount
            + tax_total
            + self.shipping_cost
            + self.other_charges
        )

        if total < 0:
            raise ValueError(
                "Discounts exceed purchase order total"
            )

        self.subtotal = subtotal
        self.tax_amount = tax_total
        self.total_amount = total.quantize(
            MONEY_QUANTUM
        )

        self._touch()

    # ========================================================
    # UPDATE ORDER CHARGES
    # ========================================================

    def update_charges(
        self,
        *,
        actor_id: str,
        discount_amount: Decimal | int | float | str = 0,
        shipping_cost: Decimal | int | float | str = 0,
        other_charges: Decimal | int | float | str = 0,
    ) -> None:
        self._ensure_editable()

        old_values = (
            self.discount_amount,
            self.shipping_cost,
            self.other_charges,
        )

        self.discount_amount = nonnegative_decimal(
            discount_amount,
            "discount_amount",
        )
        self.shipping_cost = nonnegative_decimal(
            shipping_cost,
            "shipping_cost",
        )
        self.other_charges = nonnegative_decimal(
            other_charges,
            "other_charges",
        )

        try:
            self.recalculate_totals()
        except ValueError:
            (
                self.discount_amount,
                self.shipping_cost,
                self.other_charges,
            ) = old_values
            raise

        self._record_event(
            "purchase_order_charges_updated",
            actor_id=actor_id,
        )

    # ========================================================
    # RECORD AI RECOMMENDATION
    # ========================================================

    def update_ai_recommendation(
        self,
        *,
        model_id: str,
        confidence: Decimal | int | float | str,
        recommendation: str,
        explanation: str,
        analysis: dict[str, Any],
        agent_run_id: str | None = None,
    ) -> None:
        self._ensure_editable()

        self.ai_generated = True
        self.ai_model_id = require_text(
            model_id,
            "Model ID",
        )
        self.ai_agent_run_id = agent_run_id
        self.ai_confidence = score_decimal(
            confidence,
            "confidence",
        )
        self.ai_recommendation = require_text(
            recommendation,
            "Recommendation",
        )
        self.ai_explanation = require_text(
            explanation,
            "Explanation",
        )
        self.ai_analysis = dict(analysis)

        self._record_event(
            "ai_recommendation_updated",
            details={"model_id": model_id},
        )

    # ========================================================
    # UPDATE SUPPLIER RISK
    # ========================================================

    def update_supplier_risk(
        self,
        *,
        risk_score: Decimal | int | float | str,
        risk_level: SupplierRiskLevel,
        supplier_risk_id: str | None = None,
    ) -> None:
        self._ensure_active()

        self.supplier_risk_score = score_decimal(
            risk_score,
            "risk_score",
        )
        self.supplier_risk_level = risk_level

        if supplier_risk_id is not None:
            self.supplier_risk_id = supplier_risk_id

        self._record_event(
            "supplier_risk_updated",
            details={
                "risk_level": risk_level.value,
            },
        )

    # ========================================================
    # REQUEST APPROVAL
    # ========================================================

    def request_approval(
        self,
        *,
        requested_by: str,
        approval_request_id: str | None = None,
    ) -> None:
        self._ensure_editable()

        if not self.items:
            raise ValueError(
                "Purchase order requires at least one item"
            )

        self.recalculate_totals()
        self.requested_by = require_text(
            requested_by,
            "Requested by",
        )

        if self.requires_approval:
            self.approval_request_id = require_text(
                approval_request_id,
                "Approval request ID",
            )
            self.approval_status = (
                PurchaseOrderApprovalStatus.PENDING
            )
            self.status = (
                PurchaseOrderStatus.PENDING_APPROVAL
            )
        else:
            self.approval_status = (
                PurchaseOrderApprovalStatus.NOT_REQUIRED
            )
            self.status = PurchaseOrderStatus.APPROVED

        self._record_event(
            "purchase_order_approval_requested",
            actor_id=requested_by,
        )

    # ========================================================
    # APPROVE
    # ========================================================

    def approve(
        self,
        *,
        approver_id: str,
    ) -> None:
        self._ensure_active()

        if self.status != (
            PurchaseOrderStatus.PENDING_APPROVAL
        ):
            raise ValueError(
                "Purchase order is not pending approval"
            )

        if self.approval_status != (
            PurchaseOrderApprovalStatus.PENDING
        ):
            raise ValueError(
                "Approval request is not pending"
            )

        # Service layer must validate the approver
        # and linked ApprovalRequest record.

        self.approval_status = (
            PurchaseOrderApprovalStatus.APPROVED
        )
        self.approved_by = require_text(
            approver_id,
            "Approver ID",
        )
        self.approved_at = utc_now()
        self.status = PurchaseOrderStatus.APPROVED

        self._record_event(
            "purchase_order_approved",
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
        self._ensure_active()

        if self.status != (
            PurchaseOrderStatus.PENDING_APPROVAL
        ):
            raise ValueError(
                "Purchase order is not pending approval"
            )

        self.approval_status = (
            PurchaseOrderApprovalStatus.REJECTED
        )
        self.rejection_reason = require_text(
            reason,
            "Rejection reason",
        )
        self.status = PurchaseOrderStatus.REJECTED

        self._record_event(
            "purchase_order_rejected",
            actor_id=approver_id,
            details={"reason": reason},
        )

    # ========================================================
    # MARK SENT
    # ========================================================

    def mark_sent(
        self,
        *,
        actor_id: str,
        supplier_reference: str | None = None,
    ) -> None:
        self._ensure_active()

        if self.status != PurchaseOrderStatus.APPROVED:
            raise ValueError(
                "Purchase order must be approved"
            )

        if not self.is_approved:
            raise ValueError(
                "Purchase order approval is incomplete"
            )

        # Call only after supplier delivery has been
        # confirmed by the integration service.

        self.status = PurchaseOrderStatus.SENT
        self.sent_at = utc_now()

        if supplier_reference is not None:
            self.supplier_reference = supplier_reference

        self._record_event(
            "purchase_order_sent",
            actor_id=actor_id,
        )

    # ========================================================
    # SUPPLIER ACKNOWLEDGMENT
    # ========================================================

    def acknowledge(
        self,
        *,
        supplier_reference: str,
        actor_id: str,
    ) -> None:
        self._ensure_active()

        if self.status != PurchaseOrderStatus.SENT:
            raise ValueError(
                "Purchase order has not been sent"
            )

        self.supplier_reference = require_text(
            supplier_reference,
            "Supplier reference",
        )
        self.acknowledged_at = utc_now()
        self.status = PurchaseOrderStatus.ACKNOWLEDGED

        self._record_event(
            "supplier_acknowledged",
            actor_id=actor_id,
        )

    # ========================================================
    # RECEIVE ITEM
    # ========================================================

    def receive_item(
        self,
        *,
        item_id: str,
        quantity: Decimal | int | float | str,
        actor_id: str,
        receipt_reference: str,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            PurchaseOrderStatus.SENT,
            PurchaseOrderStatus.ACKNOWLEDGED,
            PurchaseOrderStatus.PARTIALLY_RECEIVED,
        }:
            raise ValueError(
                "Purchase order cannot receive items"
            )

        item = next(
            (
                item for item in self.items
                if item.id == item_id
            ),
            None,
        )

        if item is None:
            raise ValueError(
                "Purchase order item not found"
            )

        quantity = nonnegative_decimal(
            quantity,
            "quantity",
            allow_zero=False,
        )

        # The receiving service must first verify
        # the warehouse receipt, quantity, quality,
        # tenant ownership and idempotency key.

        item.receive(quantity)

        if self.is_fully_received:
            self.status = PurchaseOrderStatus.RECEIVED
            self.actual_delivery_at = utc_now()
        else:
            self.status = (
                PurchaseOrderStatus.PARTIALLY_RECEIVED
            )

        self._record_event(
            "purchase_order_item_received",
            actor_id=actor_id,
            details={
                "item_id": item_id,
                "quantity": str(quantity),
                "receipt_reference": require_text(
                    receipt_reference,
                    "Receipt reference",
                ),
            },
        )

    # ========================================================
    # CLOSE PURCHASE ORDER
    # ========================================================

    def close(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_active()

        if self.status != PurchaseOrderStatus.RECEIVED:
            raise ValueError(
                "Purchase order must be fully received"
            )

        self.status = PurchaseOrderStatus.CLOSED
        self.closed_at = utc_now()
        self.closed_by = require_text(
            actor_id,
            "Actor ID",
        )

        self._record_event(
            "purchase_order_closed",
            actor_id=actor_id,
        )

    # ========================================================
    # CANCEL PURCHASE ORDER
    # ========================================================

    def cancel(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            PurchaseOrderStatus.DRAFT,
            PurchaseOrderStatus.PENDING_APPROVAL,
            PurchaseOrderStatus.APPROVED,
        }:
            raise ValueError(
                "Dispatched or received orders require "
                "a supplier cancellation/return workflow"
            )

        self.status = PurchaseOrderStatus.CANCELLED
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
            "purchase_order_cancelled",
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
                "Purchase order already deleted"
            )

        if self.status not in {
            PurchaseOrderStatus.DRAFT,
            PurchaseOrderStatus.REJECTED,
            PurchaseOrderStatus.CANCELLED,
        }:
            raise ValueError(
                "Purchase order cannot be deleted"
            )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = require_text(
            actor_id,
            "Actor ID",
        )

        self._record_event(
            "purchase_order_soft_deleted",
            actor_id=actor_id,
        )

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(
        self,
        *,
        include_items: bool = True,
    ) -> dict[str, Any]:
        result = {
            "id": self.id,
            "organization_id": self.organization_id,
            "po_number": self.po_number,
            "idempotency_key": self.idempotency_key,

            "status": enum_value(self.status),
            "order_type": enum_value(self.order_type),
            "priority": enum_value(self.priority),
            "source": enum_value(self.source),
            "title": self.title,
            "description": self.description,

            "supplier_id": self.supplier_id,
            "warehouse_id": self.warehouse_id,
            "supplier_reference": self.supplier_reference,
            "supplier_contact_id": self.supplier_contact_id,
            "delivery_address": self.delivery_address,
            "billing_address": self.billing_address,

            "demand_forecast_id": self.demand_forecast_id,
            "supplier_risk_id": self.supplier_risk_id,
            "inventory_replenishment_id": (
                self.inventory_replenishment_id
            ),
            "integration_id": self.integration_id,
            "external_order_id": self.external_order_id,

            "currency": self.currency,
            "subtotal": money(self.subtotal),
            "tax_amount": money(self.tax_amount),
            "discount_amount": money(
                self.discount_amount
            ),
            "shipping_cost": money(self.shipping_cost),
            "other_charges": money(self.other_charges),
            "total_amount": money(self.total_amount),
            "payment_terms": self.payment_terms,
            "payment_status": enum_value(
                self.payment_status
            ),

            "order_date": iso(self.order_date),
            "expected_delivery_at": iso(
                self.expected_delivery_at
            ),
            "actual_delivery_at": iso(
                self.actual_delivery_at
            ),
            "shipping_method": self.shipping_method,
            "tracking_number": self.tracking_number,
            "latest_delivery_id": self.latest_delivery_id,

            "ai_generated": self.ai_generated,
            "ai_model_id": self.ai_model_id,
            "ai_agent_run_id": self.ai_agent_run_id,
            "ai_confidence": money(
                self.ai_confidence
            ),
            "ai_recommendation": (
                self.ai_recommendation
            ),
            "ai_explanation": self.ai_explanation,
            "ai_analysis": self.ai_analysis,
            "supplier_risk_score": money(
                self.supplier_risk_score
            ),
            "supplier_risk_level": enum_value(
                self.supplier_risk_level
            ),

            "requires_approval": self.requires_approval,
            "approval_status": enum_value(
                self.approval_status
            ),
            "approval_request_id": (
                self.approval_request_id
            ),
            "requested_by": self.requested_by,
            "approved_by": self.approved_by,
            "approved_at": iso(self.approved_at),
            "rejection_reason": self.rejection_reason,

            "sent_at": iso(self.sent_at),
            "acknowledged_at": iso(
                self.acknowledged_at
            ),
            "closed_at": iso(self.closed_at),
            "closed_by": self.closed_by,
            "cancelled_at": iso(self.cancelled_at),
            "cancelled_by": self.cancelled_by,
            "cancellation_reason": (
                self.cancellation_reason
            ),

            "total_ordered_quantity": str(
                self.total_ordered_quantity
            ),
            "total_received_quantity": str(
                self.total_received_quantity
            ),
            "is_fully_received": self.is_fully_received,
            "is_overdue": self.is_overdue,
            "is_approved": self.is_approved,
            "is_terminal": self.is_terminal,

            "po_metadata": self.po_metadata,
            "order_history": self.order_history,

            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "trace_id": self.trace_id,
            "correlation_id": self.correlation_id,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),

            "is_deleted": self.is_deleted,
            "deleted_at": iso(self.deleted_at),
            "deleted_by": self.deleted_by,
            "version": self.version,
        }

        if include_items:
            result["items"] = [
                item.to_dict() for item in self.items
            ]

        return result

    def __repr__(self) -> str:
        return (
            f"<PurchaseOrder("
            f"id={self.id}, "
            f"po_number={self.po_number}, "
            f"status={enum_value(self.status)}, "
            f"total={self.total_amount}"
            f")>"
        )


# ============================================================
# PURCHASE ORDER ITEM
# ============================================================

class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "purchase_order_id"],
            [
                "purchase_orders.organization_id",
                "purchase_orders.id",
            ],
            name="fk_po_item_same_tenant_order",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "purchase_order_id",
            "line_number",
            name="uq_po_item_line",
        ),
        CheckConstraint(
            "quantity_ordered > 0",
            name="po_item_quantity_positive",
        ),
        CheckConstraint(
            "quantity_received >= 0",
            name="po_item_received_nonnegative",
        ),
        CheckConstraint(
            "quantity_received <= quantity_ordered",
            name="po_item_received_not_excess",
        ),
        CheckConstraint(
            "unit_price >= 0",
            name="po_item_price_nonnegative",
        ),
        CheckConstraint(
            "tax_rate >= 0 AND tax_rate <= 100",
            name="po_item_tax_rate_range",
        ),
        CheckConstraint(
            "discount_amount >= 0",
            name="po_item_discount_nonnegative",
        ),
        CheckConstraint(
            "line_total >= 0",
            name="po_item_total_nonnegative",
        ),
        Index(
            "ix_po_item_org_product",
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

    purchase_order_id: Mapped[str] = mapped_column(
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

    unit_of_measure: Mapped[str] = mapped_column(
        String(30),
        default="units",
        nullable=False,
    )

    quantity_ordered: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
    )

    quantity_received: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=MONEY_ZERO,
        nullable=False,
    )

    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=MONEY_ZERO,
        nullable=False,
    )

    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(7, 4),
        default=MONEY_ZERO,
        nullable=False,
    )

    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=MONEY_ZERO,
        nullable=False,
    )

    line_subtotal: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=MONEY_ZERO,
        nullable=False,
    )

    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=MONEY_ZERO,
        nullable=False,
    )

    line_total: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=MONEY_ZERO,
        nullable=False,
    )

    status: Mapped[
        PurchaseOrderLineStatus
    ] = mapped_column(
        enum_column(
            PurchaseOrderLineStatus,
            "purchase_order_line_status",
        ),
        default=PurchaseOrderLineStatus.OPEN,
        nullable=False,
    )

    product_metadata: Mapped[
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

    purchase_order: Mapped["PurchaseOrder"] = relationship(
        "PurchaseOrder",
        back_populates="items",
    )

    # ========================================================
    # PROPERTIES
    # ========================================================

    @property
    def remaining_quantity(self) -> Decimal:
        return (
            self.quantity_ordered
            - self.quantity_received
        )

    @property
    def is_fully_received(self) -> bool:
        return (
            self.quantity_received
            >= self.quantity_ordered
        )

    # ========================================================
    # RECALCULATE
    # ========================================================

    def recalculate(self) -> None:
        subtotal = (
            self.quantity_ordered * self.unit_price
        ).quantize(MONEY_QUANTUM)

        if self.discount_amount > subtotal:
            raise ValueError(
                "Line discount exceeds line subtotal"
            )

        taxable_amount = (
            subtotal - self.discount_amount
        )

        tax_amount = (
            taxable_amount
            * self.tax_rate
            / Decimal("100")
        ).quantize(MONEY_QUANTUM)

        self.line_subtotal = subtotal
        self.tax_amount = tax_amount
        self.line_total = (
            taxable_amount + tax_amount
        ).quantize(MONEY_QUANTUM)

        self.updated_at = utc_now()

    # ========================================================
    # RECEIVE QUANTITY
    # ========================================================

    def receive(
        self,
        quantity: Decimal | int | float | str,
    ) -> None:
        if self.status == PurchaseOrderLineStatus.CANCELLED:
            raise ValueError(
                "Cancelled line cannot receive stock"
            )

        quantity = nonnegative_decimal(
            quantity,
            "quantity",
            allow_zero=False,
        )

        if quantity > self.remaining_quantity:
            raise ValueError(
                "Received quantity exceeds outstanding quantity"
            )

        self.quantity_received += quantity

        if self.is_fully_received:
            self.status = PurchaseOrderLineStatus.RECEIVED
        else:
            self.status = (
                PurchaseOrderLineStatus.PARTIALLY_RECEIVED
            )

        self.updated_at = utc_now()

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "purchase_order_id": self.purchase_order_id,
            "line_number": self.line_number,
            "product_id": self.product_id,
            "sku": self.sku,
            "product_name": self.product_name,
            "unit_of_measure": self.unit_of_measure,
            "quantity_ordered": str(
                self.quantity_ordered
            ),
            "quantity_received": str(
                self.quantity_received
            ),
            "remaining_quantity": str(
                self.remaining_quantity
            ),
            "unit_price": money(self.unit_price),
            "tax_rate": money(self.tax_rate),
            "discount_amount": money(
                self.discount_amount
            ),
            "line_subtotal": money(
                self.line_subtotal
            ),
            "tax_amount": money(self.tax_amount),
            "line_total": money(self.line_total),
            "status": enum_value(self.status),
            "is_fully_received": self.is_fully_received,
            "product_metadata": self.product_metadata,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
        }

    def __repr__(self) -> str:
        return (
            f"<PurchaseOrderItem("
            f"id={self.id}, "
            f"product_id={self.product_id}, "
            f"ordered={self.quantity_ordered}, "
            f"received={self.quantity_received}"
            f")>"
        )
