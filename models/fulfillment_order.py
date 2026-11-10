from __future__ import annotations


"""
backend/models/fulfillment_order.py

Autonomous Retail Supply Chain AI 5.0
Fulfillment Order ORM Model

Features:
- Multi-tenant fulfillment orders
- Warehouse and customer references
- Order lifecycle management
- Inventory reservation
- Picking and packing
- Partial fulfillment
- Shipment and delivery integration
- SLA and priority management
- AI fulfillment recommendations
- Human approval references
- Exception handling
- Audit and optimistic locking
- Soft deletion

Requirements:
    Python >= 3.10
    SQLAlchemy >= 2.0

Shared ORM:
    backend.models.base.Base
"""


import enum
import math
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
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


# ============================================================
# UTILITIES
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_fulfillment_number() -> str:
    return f"FUL-{uuid.uuid4().hex[:16].upper()}"


def enum_column(enum_class, name: str):
    return SQLEnum(
        enum_class,
        name=name,
        native_enum=False,
        values_callable=lambda cls: [
            member.value for member in cls
        ],
        validate_strings=True,
        length=60,
    )


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Invalid numeric value") from None

    if not result.is_finite():
        raise ValueError("Numeric value must be finite")

    return result


def decimal_string(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def datetime_string(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


# ============================================================
# ENUMS
# ============================================================

class FulfillmentStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    ALLOCATING = "allocating"
    ALLOCATED = "allocated"
    PARTIALLY_ALLOCATED = "partially_allocated"
    PICKING = "picking"
    PICKED = "picked"
    PACKING = "packing"
    PACKED = "packed"
    READY_TO_SHIP = "ready_to_ship"
    PARTIALLY_SHIPPED = "partially_shipped"
    SHIPPED = "shipped"
    PARTIALLY_DELIVERED = "partially_delivered"
    DELIVERED = "delivered"
    COMPLETED = "completed"
    ON_HOLD = "on_hold"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FulfillmentPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"


class FulfillmentType(str, enum.Enum):
    CUSTOMER_ORDER = "customer_order"
    STORE_REPLENISHMENT = "store_replenishment"
    WAREHOUSE_TRANSFER = "warehouse_transfer"
    BACKORDER = "backorder"
    PREORDER = "preorder"
    RETURN_REPLACEMENT = "return_replacement"
    INTERNAL_REQUEST = "internal_request"


class FulfillmentChannel(str, enum.Enum):
    ECOMMERCE = "ecommerce"
    RETAIL_STORE = "retail_store"
    MARKETPLACE = "marketplace"
    WHOLESALE = "wholesale"
    B2B = "b2b"
    INTERNAL = "internal"
    API = "api"


class FulfillmentAllocationStatus(str, enum.Enum):
    NOT_ALLOCATED = "not_allocated"
    PARTIALLY_ALLOCATED = "partially_allocated"
    ALLOCATED = "allocated"
    RELEASED = "released"


class FulfillmentRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class FulfillmentExceptionType(str, enum.Enum):
    NONE = "none"
    STOCKOUT = "stockout"
    INVENTORY_MISMATCH = "inventory_mismatch"
    PICKING_FAILURE = "picking_failure"
    PACKING_FAILURE = "packing_failure"
    ADDRESS_ERROR = "address_error"
    CARRIER_DELAY = "carrier_delay"
    QUALITY_HOLD = "quality_hold"
    PAYMENT_HOLD = "payment_hold"
    SYSTEM_ERROR = "system_error"
    OTHER = "other"


# ============================================================
# FULFILLMENT ORDER
# ============================================================

class FulfillmentOrder(Base):
    __tablename__ = "fulfillment_orders"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "fulfillment_number",
            name="uq_fulfillment_org_number",
        ),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_fulfillment_org_id",
        ),
        CheckConstraint(
            "total_quantity >= 0",
            name="fulfillment_total_qty_nonnegative",
        ),
        CheckConstraint(
            "allocated_quantity >= 0",
            name="fulfillment_allocated_qty_nonnegative",
        ),
        CheckConstraint(
            "picked_quantity >= 0",
            name="fulfillment_picked_qty_nonnegative",
        ),
        CheckConstraint(
            "packed_quantity >= 0",
            name="fulfillment_packed_qty_nonnegative",
        ),
        CheckConstraint(
            "shipped_quantity >= 0",
            name="fulfillment_shipped_qty_nonnegative",
        ),
        CheckConstraint(
            "delivered_quantity >= 0",
            name="fulfillment_delivered_qty_nonnegative",
        ),
        CheckConstraint(
            "allocated_quantity <= total_quantity",
            name="fulfillment_allocated_limit",
        ),
        CheckConstraint(
            "picked_quantity <= allocated_quantity",
            name="fulfillment_picked_limit",
        ),
        CheckConstraint(
            "packed_quantity <= picked_quantity",
            name="fulfillment_packed_limit",
        ),
        CheckConstraint(
            "shipped_quantity <= packed_quantity",
            name="fulfillment_shipped_limit",
        ),
        CheckConstraint(
            "delivered_quantity <= shipped_quantity",
            name="fulfillment_delivered_limit",
        ),
        CheckConstraint(
            "total_amount >= 0",
            name="fulfillment_amount_nonnegative",
        ),
        CheckConstraint(
            "shipping_cost >= 0",
            name="fulfillment_shipping_cost_nonnegative",
        ),
        CheckConstraint(
            "delay_probability IS NULL OR "
            "(delay_probability >= 0 "
            "AND delay_probability <= 1)",
            name="fulfillment_delay_probability_range",
        ),
        CheckConstraint(
            "optimization_score IS NULL OR "
            "(optimization_score >= 0 "
            "AND optimization_score <= 1)",
            name="fulfillment_optimization_score_range",
        ),
        Index(
            "ix_fulfillment_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_fulfillment_org_warehouse",
            "organization_id",
            "warehouse_id",
        ),
        Index(
            "ix_fulfillment_org_customer",
            "organization_id",
            "customer_id",
        ),
        Index(
            "ix_fulfillment_org_order",
            "organization_id",
            "order_id",
        ),
        Index(
            "ix_fulfillment_org_priority",
            "organization_id",
            "priority",
        ),
        Index(
            "ix_fulfillment_org_due",
            "organization_id",
            "due_at",
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

    fulfillment_number: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=generate_fulfillment_number,
    )

    order_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    external_order_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    # --------------------------------------------------------
    # BUSINESS REFERENCES
    # --------------------------------------------------------

    customer_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    warehouse_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    destination_warehouse_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    delivery_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    shipment_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    picking_batch_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    packing_batch_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # FULFILLMENT DETAILS
    # --------------------------------------------------------

    fulfillment_type: Mapped[FulfillmentType] = mapped_column(
        enum_column(
            FulfillmentType,
            "fulfillment_order_type",
        ),
        default=FulfillmentType.CUSTOMER_ORDER,
        nullable=False,
    )

    channel: Mapped[FulfillmentChannel] = mapped_column(
        enum_column(
            FulfillmentChannel,
            "fulfillment_order_channel",
        ),
        default=FulfillmentChannel.ECOMMERCE,
        nullable=False,
    )

    status: Mapped[FulfillmentStatus] = mapped_column(
        enum_column(
            FulfillmentStatus,
            "fulfillment_order_status",
        ),
        default=FulfillmentStatus.DRAFT,
        nullable=False,
    )

    priority: Mapped[FulfillmentPriority] = mapped_column(
        enum_column(
            FulfillmentPriority,
            "fulfillment_order_priority",
        ),
        default=FulfillmentPriority.NORMAL,
        nullable=False,
    )

    allocation_status: Mapped[
        FulfillmentAllocationStatus
    ] = mapped_column(
        enum_column(
            FulfillmentAllocationStatus,
            "fulfillment_allocation_status",
        ),
        default=FulfillmentAllocationStatus.NOT_ALLOCATED,
        nullable=False,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # QUANTITY TRACKING
    # --------------------------------------------------------

    total_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    allocated_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    picked_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    packed_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    shipped_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    delivered_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    # --------------------------------------------------------
    # FINANCIALS
    # --------------------------------------------------------

    currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0"),
        nullable=False,
    )

    shipping_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0"),
        nullable=False,
    )

    # --------------------------------------------------------
    # CUSTOMER DELIVERY
    # --------------------------------------------------------

    recipient_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    recipient_phone: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )

    shipping_address: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # SLA AND TIMELINE
    # --------------------------------------------------------

    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    allocated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    picking_started_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    picked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    packing_started_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    packed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    shipped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # AI OPTIMIZATION
    # --------------------------------------------------------

    agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    agent_action_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    model_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    model_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    delay_probability: Mapped[float | None] = mapped_column(
        nullable=True,
    )

    optimization_score: Mapped[float | None] = mapped_column(
        nullable=True,
    )

    risk_level: Mapped[FulfillmentRiskLevel] = mapped_column(
        enum_column(
            FulfillmentRiskLevel,
            "fulfillment_order_risk_level",
        ),
        default=FulfillmentRiskLevel.UNKNOWN,
        nullable=False,
    )

    ai_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    recommended_action: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    requires_human_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    approval_request_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # EXCEPTION HANDLING
    # --------------------------------------------------------

    exception_type: Mapped[
        FulfillmentExceptionType
    ] = mapped_column(
        enum_column(
            FulfillmentExceptionType,
            "fulfillment_exception_type",
        ),
        default=FulfillmentExceptionType.NONE,
        nullable=False,
    )

    exception_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    exception_detected_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # HOLD / CANCEL
    # --------------------------------------------------------

    hold_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(
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

    # --------------------------------------------------------
    # METADATA
    # --------------------------------------------------------

    fulfillment_metadata: Mapped[
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
            FulfillmentStatus.COMPLETED,
            FulfillmentStatus.FAILED,
            FulfillmentStatus.CANCELLED,
        }

    @property
    def is_overdue(self) -> bool:
        if self.due_at is None or self.is_terminal:
            return False

        return as_utc(self.due_at) < utc_now()

    @property
    def remaining_quantity(self) -> Decimal:
        return max(
            Decimal("0"),
            self.total_quantity - self.shipped_quantity,
        )

    @property
    def allocation_remaining(self) -> Decimal:
        return max(
            Decimal("0"),
            self.total_quantity - self.allocated_quantity,
        )

    @property
    def is_fully_delivered(self) -> bool:
        return (
            self.total_quantity > 0
            and self.delivered_quantity == self.total_quantity
        )

    @property
    def fulfillment_rate(self) -> float:
        if self.total_quantity == 0:
            return 0.0

        return float(
            self.shipped_quantity / self.total_quantity
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_active(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Fulfillment order has been deleted"
            )

        if self.is_terminal:
            raise ValueError(
                "Fulfillment order is terminal"
            )

    def _ensure_not_on_hold(self) -> None:
        if self.status == FulfillmentStatus.ON_HOLD:
            raise ValueError(
                "Fulfillment order is on hold"
            )

    def _validate_quantities(self) -> None:
        quantities = (
            self.total_quantity,
            self.allocated_quantity,
            self.picked_quantity,
            self.packed_quantity,
            self.shipped_quantity,
            self.delivered_quantity,
        )

        if any(value < 0 for value in quantities):
            raise ValueError(
                "Quantities cannot be negative"
            )

        if not (
            self.delivered_quantity
            <= self.shipped_quantity
            <= self.packed_quantity
            <= self.picked_quantity
            <= self.allocated_quantity
            <= self.total_quantity
        ):
            raise ValueError(
                "Invalid fulfillment quantity progression"
            )

    # ========================================================
    # CONFIRM ORDER
    # ========================================================

    def confirm(self) -> None:
        self._ensure_active()

        if self.status not in {
            FulfillmentStatus.DRAFT,
            FulfillmentStatus.PENDING,
        }:
            raise ValueError(
                "Only draft or pending orders can be confirmed"
            )

        if self.total_quantity <= 0:
            raise ValueError(
                "Total quantity must be positive"
            )

        self.status = FulfillmentStatus.CONFIRMED
        self.confirmed_at = utc_now()
        self._touch()

    # ========================================================
    # START ALLOCATION
    # ========================================================

    def start_allocation(self) -> None:
        self._ensure_active()
        self._ensure_not_on_hold()

        if self.status != FulfillmentStatus.CONFIRMED:
            raise ValueError(
                "Order must be confirmed before allocation"
            )

        self.status = FulfillmentStatus.ALLOCATING
        self._touch()

    # ========================================================
    # ALLOCATE INVENTORY
    # ========================================================

    def allocate_inventory(
        self,
        quantity: Decimal | int | float,
    ) -> None:
        self._ensure_active()
        self._ensure_not_on_hold()

        if self.status not in {
            FulfillmentStatus.ALLOCATING,
            FulfillmentStatus.PARTIALLY_ALLOCATED,
        }:
            raise ValueError(
                "Order is not in allocation stage"
            )

        quantity = to_decimal(quantity)

        if quantity <= 0:
            raise ValueError(
                "Allocation quantity must be positive"
            )

        if (
            self.allocated_quantity + quantity
            > self.total_quantity
        ):
            raise ValueError(
                "Allocation exceeds order quantity"
            )

        self.allocated_quantity += quantity

        if self.allocated_quantity == self.total_quantity:
            self.allocation_status = (
                FulfillmentAllocationStatus.ALLOCATED
            )
            self.status = FulfillmentStatus.ALLOCATED
            self.allocated_at = utc_now()
        else:
            self.allocation_status = (
                FulfillmentAllocationStatus.PARTIALLY_ALLOCATED
            )
            self.status = FulfillmentStatus.PARTIALLY_ALLOCATED

        self._validate_quantities()
        self._touch()

    # ========================================================
    # START PICKING
    # ========================================================

    def start_picking(self) -> None:
        self._ensure_active()
        self._ensure_not_on_hold()

        if self.status not in {
            FulfillmentStatus.ALLOCATED,
            FulfillmentStatus.PARTIALLY_ALLOCATED,
        }:
            raise ValueError(
                "Inventory must be allocated first"
            )

        if self.allocated_quantity <= self.picked_quantity:
            raise ValueError(
                "No allocated inventory available for picking"
            )

        self.status = FulfillmentStatus.PICKING
        self.picking_started_at = utc_now()
        self._touch()

    # ========================================================
    # RECORD PICKING
    # ========================================================

    def record_picking(
        self,
        quantity: Decimal | int | float,
    ) -> None:
        self._ensure_active()
        self._ensure_not_on_hold()

        if self.status != FulfillmentStatus.PICKING:
            raise ValueError(
                "Order is not in picking stage"
            )

        quantity = to_decimal(quantity)

        if quantity <= 0:
            raise ValueError(
                "Picking quantity must be positive"
            )

        if (
            self.picked_quantity + quantity
            > self.allocated_quantity
        ):
            raise ValueError(
                "Picked quantity exceeds allocated quantity"
            )

        self.picked_quantity += quantity

        if self.picked_quantity == self.allocated_quantity:
            self.status = FulfillmentStatus.PICKED
            self.picked_at = utc_now()

        self._validate_quantities()
        self._touch()

    # ========================================================
    # START PACKING
    # ========================================================

    def start_packing(self) -> None:
        self._ensure_active()
        self._ensure_not_on_hold()

        if self.status != FulfillmentStatus.PICKED:
            raise ValueError(
                "Order must be picked before packing"
            )

        self.status = FulfillmentStatus.PACKING
        self.packing_started_at = utc_now()
        self._touch()

    # ========================================================
    # RECORD PACKING
    # ========================================================

    def record_packing(
        self,
        quantity: Decimal | int | float,
    ) -> None:
        self._ensure_active()
        self._ensure_not_on_hold()

        if self.status != FulfillmentStatus.PACKING:
            raise ValueError(
                "Order is not in packing stage"
            )

        quantity = to_decimal(quantity)

        if quantity <= 0:
            raise ValueError(
                "Packing quantity must be positive"
            )

        if (
            self.packed_quantity + quantity
            > self.picked_quantity
        ):
            raise ValueError(
                "Packed quantity exceeds picked quantity"
            )

        self.packed_quantity += quantity

        if self.packed_quantity == self.picked_quantity:
            self.status = FulfillmentStatus.PACKED
            self.packed_at = utc_now()

        self._validate_quantities()
        self._touch()

    # ========================================================
    # READY TO SHIP
    # ========================================================

    def mark_ready_to_ship(self) -> None:
        self._ensure_active()
        self._ensure_not_on_hold()

        if self.status != FulfillmentStatus.PACKED:
            raise ValueError(
                "Order must be packed before shipping"
            )

        self.status = FulfillmentStatus.READY_TO_SHIP
        self._touch()

    # ========================================================
    # RECORD SHIPMENT
    # ========================================================

    def record_shipment(
        self,
        quantity: Decimal | int | float,
        *,
        shipment_id: str | None = None,
    ) -> None:
        self._ensure_active()
        self._ensure_not_on_hold()

        if self.status not in {
            FulfillmentStatus.READY_TO_SHIP,
            FulfillmentStatus.PARTIALLY_SHIPPED,
        }:
            raise ValueError(
                "Order is not ready for shipment"
            )

        quantity = to_decimal(quantity)

        if quantity <= 0:
            raise ValueError(
                "Shipment quantity must be positive"
            )

        if (
            self.shipped_quantity + quantity
            > self.packed_quantity
        ):
            raise ValueError(
                "Shipment exceeds packed quantity"
            )

        self.shipped_quantity += quantity

        if shipment_id:
            self.shipment_id = shipment_id

        self.shipped_at = utc_now()

        if self.shipped_quantity == self.total_quantity:
            self.status = FulfillmentStatus.SHIPPED
        else:
            self.status = FulfillmentStatus.PARTIALLY_SHIPPED

        self._validate_quantities()
        self._touch()

    # ========================================================
    # RECORD DELIVERY
    # ========================================================

    def record_delivery(
        self,
        quantity: Decimal | int | float,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            FulfillmentStatus.SHIPPED,
            FulfillmentStatus.PARTIALLY_SHIPPED,
            FulfillmentStatus.PARTIALLY_DELIVERED,
        }:
            raise ValueError(
                "Order must be shipped before delivery"
            )

        quantity = to_decimal(quantity)

        if quantity <= 0:
            raise ValueError(
                "Delivered quantity must be positive"
            )

        if (
            self.delivered_quantity + quantity
            > self.shipped_quantity
        ):
            raise ValueError(
                "Delivered quantity exceeds shipped quantity"
            )

        self.delivered_quantity += quantity

        if self.is_fully_delivered:
            self.status = FulfillmentStatus.DELIVERED
            self.delivered_at = utc_now()
        else:
            self.status = FulfillmentStatus.PARTIALLY_DELIVERED

        self._validate_quantities()
        self._touch()

    # ========================================================
    # COMPLETE FULFILLMENT
    # ========================================================

    def complete(self) -> None:
        self._ensure_active()

        if self.status != FulfillmentStatus.DELIVERED:
            raise ValueError(
                "Order must be fully delivered"
            )

        if not self.is_fully_delivered:
            raise ValueError(
                "Delivered quantity does not match total"
            )

        self.status = FulfillmentStatus.COMPLETED
        self.completed_at = utc_now()
        self._touch()

    # ========================================================
    # HOLD ORDER
    # ========================================================

    def place_on_hold(self, reason: str) -> None:
        self._ensure_active()

        if not reason.strip():
            raise ValueError(
                "Hold reason is required"
            )

        if self.status == FulfillmentStatus.ON_HOLD:
            raise ValueError(
                "Order already on hold"
            )

        metadata = dict(self.fulfillment_metadata or {})
        metadata["status_before_hold"] = self.status.value
        self.fulfillment_metadata = metadata

        self.hold_reason = reason
        self.status = FulfillmentStatus.ON_HOLD
        self._touch()

    def release_hold(self) -> None:
        self._ensure_active()

        if self.status != FulfillmentStatus.ON_HOLD:
            raise ValueError(
                "Order is not on hold"
            )

        metadata = dict(self.fulfillment_metadata or {})
        previous = metadata.pop(
            "status_before_hold",
            FulfillmentStatus.CONFIRMED.value,
        )

        self.status = FulfillmentStatus(previous)
        self.fulfillment_metadata = metadata
        self.hold_reason = None
        self._touch()

    # ========================================================
    # RECORD EXCEPTION
    # ========================================================

    def record_exception(
        self,
        *,
        exception_type: FulfillmentExceptionType,
        reason: str,
    ) -> None:
        self._ensure_active()

        if not reason.strip():
            raise ValueError(
                "Exception reason is required"
            )

        self.exception_type = exception_type
        self.exception_reason = reason
        self.exception_detected_at = utc_now()
        self._touch()

    # ========================================================
    # AI RISK PREDICTION
    # ========================================================

    def update_ai_prediction(
        self,
        *,
        model_name: str,
        delay_probability: float,
        optimization_score: float,
        risk_level: FulfillmentRiskLevel,
        summary: str,
        recommended_action: str,
    ) -> None:
        self._ensure_active()

        if not model_name.strip():
            raise ValueError(
                "Model name is required"
            )

        for name, value in {
            "delay_probability": delay_probability,
            "optimization_score": optimization_score,
        }.items():
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(
                    f"{name} must be between 0 and 1"
                )

        self.model_name = model_name
        self.delay_probability = delay_probability
        self.optimization_score = optimization_score
        self.risk_level = risk_level
        self.ai_summary = summary
        self.recommended_action = recommended_action
        self._touch()

    # ========================================================
    # CANCEL ORDER
    # ========================================================

    def cancel(
        self,
        *,
        user_id: str,
        reason: str,
    ) -> None:
        self._ensure_active()

        if not user_id or not reason.strip():
            raise ValueError(
                "Cancelling user and reason are required"
            )

        if self.shipped_quantity > 0:
            raise ValueError(
                "Shipped orders require a return or "
                "shipment exception workflow"
            )

        if self.allocated_quantity > 0:
            raise ValueError(
                "Inventory reservations must be released "
                "before cancellation"
            )

        self.status = FulfillmentStatus.CANCELLED
        self.cancelled_by = user_id
        self.cancelled_at = utc_now()
        self.cancellation_reason = reason
        self._touch()

    # ========================================================
    # SOFT DELETE
    # ========================================================

    def soft_delete(self, user_id: str) -> None:
        if self.is_deleted:
            raise ValueError(
                "Fulfillment order already deleted"
            )

        if not user_id:
            raise ValueError(
                "Deleting user is required"
            )

        if self.status not in {
            FulfillmentStatus.DRAFT,
            FulfillmentStatus.CANCELLED,
            FulfillmentStatus.FAILED,
        }:
            raise ValueError(
                "Active fulfillment orders cannot be deleted"
            )

        self.is_deleted = True
        self.deleted_by = user_id
        self.deleted_at = utc_now()
        self._touch()

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "fulfillment_number": self.fulfillment_number,
            "order_id": self.order_id,
            "external_order_id": self.external_order_id,
            "customer_id": self.customer_id,
            "warehouse_id": self.warehouse_id,
            "destination_warehouse_id": (
                self.destination_warehouse_id
            ),
            "delivery_id": self.delivery_id,
            "shipment_id": self.shipment_id,
            "picking_batch_id": self.picking_batch_id,
            "packing_batch_id": self.packing_batch_id,
            "fulfillment_type": self.fulfillment_type.value,
            "channel": self.channel.value,
            "status": self.status.value,
            "priority": self.priority.value,
            "allocation_status": self.allocation_status.value,
            "notes": self.notes,
            "total_quantity": decimal_string(
                self.total_quantity
            ),
            "allocated_quantity": decimal_string(
                self.allocated_quantity
            ),
            "picked_quantity": decimal_string(
                self.picked_quantity
            ),
            "packed_quantity": decimal_string(
                self.packed_quantity
            ),
            "shipped_quantity": decimal_string(
                self.shipped_quantity
            ),
            "delivered_quantity": decimal_string(
                self.delivered_quantity
            ),
            "remaining_quantity": decimal_string(
                self.remaining_quantity
            ),
            "fulfillment_rate": self.fulfillment_rate,
            "currency": self.currency,
            "total_amount": decimal_string(
                self.total_amount
            ),
            "shipping_cost": decimal_string(
                self.shipping_cost
            ),
            "recipient_name": self.recipient_name,
            "shipping_address": self.shipping_address,
            "confirmed_at": datetime_string(
                self.confirmed_at
            ),
            "allocated_at": datetime_string(
                self.allocated_at
            ),
            "picking_started_at": datetime_string(
                self.picking_started_at
            ),
            "picked_at": datetime_string(self.picked_at),
            "packing_started_at": datetime_string(
                self.packing_started_at
            ),
            "packed_at": datetime_string(self.packed_at),
            "shipped_at": datetime_string(self.shipped_at),
            "delivered_at": datetime_string(
                self.delivered_at
            ),
            "completed_at": datetime_string(
                self.completed_at
            ),
            "due_at": datetime_string(self.due_at),
            "is_overdue": self.is_overdue,
            "is_fully_delivered": self.is_fully_delivered,
            "agent_run_id": self.agent_run_id,
            "agent_action_id": self.agent_action_id,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "delay_probability": self.delay_probability,
            "optimization_score": self.optimization_score,
            "risk_level": self.risk_level.value,
            "ai_summary": self.ai_summary,
            "recommended_action": self.recommended_action,
            "requires_human_approval": (
                self.requires_human_approval
            ),
            "approval_request_id": self.approval_request_id,
            "exception_type": self.exception_type.value,
            "exception_reason": self.exception_reason,
            "exception_detected_at": datetime_string(
                self.exception_detected_at
            ),
            "hold_reason": self.hold_reason,
            "cancelled_at": datetime_string(
                self.cancelled_at
            ),
            "cancelled_by": self.cancelled_by,
            "cancellation_reason": self.cancellation_reason,
            "fulfillment_metadata": self.fulfillment_metadata,
            "is_deleted": self.is_deleted,
            "version": self.version,
            "created_at": datetime_string(
                self.created_at
            ),
            "updated_at": datetime_string(
                self.updated_at
            ),
        }

    def __repr__(self) -> str:
        return (
            f"<FulfillmentOrder("
            f"id={self.id}, "
            f"number={self.fulfillment_number}, "
            f"status={self.status.value}, "
            f"quantity={self.total_quantity}"
            f")>"
        )
