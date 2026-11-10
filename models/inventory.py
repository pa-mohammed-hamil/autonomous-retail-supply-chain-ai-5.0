from __future__ import annotations

"""Planned module: inventory. Implementation pending."""

"""
backend/models/inventory.py

Autonomous Retail Supply Chain AI 5.0
Enterprise Inventory Management ORM

Features:
- Multi-tenant, multi-warehouse inventory
- Product and warehouse references
- On-hand, reserved, damaged and quarantine stock
- Available-to-promise calculations
- Inventory receipts, issues and adjustments
- Reservation and release operations
- Reorder points and safety stock
- Stockout and overstock detection
- Expiry and lot tracking
- Cost and inventory valuation
- AI demand forecasting references
- Replenishment recommendations
- Optimistic concurrency control
- Audit metadata and soft deletion

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
    Float,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


# ============================================================
# UTILITIES
# ============================================================

QUANTITY_PRECISION = Decimal("0.0001")
MONEY_PRECISION = Decimal("0.0001")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_inventory_code() -> str:
    return f"INV-{uuid.uuid4().hex[:16].upper()}"


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


def to_decimal(
    value: Any,
    *,
    allow_zero: bool = True,
    allow_negative: bool = False,
) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Invalid numeric value") from None

    if not result.is_finite():
        raise ValueError("Value must be finite")

    if not allow_negative and result < 0:
        raise ValueError("Value cannot be negative")

    if not allow_zero and result == 0:
        raise ValueError("Value must be greater than zero")

    if result.as_tuple().exponent < -4:
        raise ValueError(
            "Maximum supported decimal precision is 4 places"
        )

    return result


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def decimal_string(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def datetime_string(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


# ============================================================
# ENUMS
# ============================================================

class InventoryStatus(str, enum.Enum):
    ACTIVE = "active"
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"
    OVERSTOCK = "overstock"
    QUARANTINED = "quarantined"
    INACTIVE = "inactive"
    DISCONTINUED = "discontinued"


class InventoryCondition(str, enum.Enum):
    GOOD = "good"
    DAMAGED = "damaged"
    EXPIRED = "expired"
    DEFECTIVE = "defective"
    UNDER_INSPECTION = "under_inspection"


class InventoryValuationMethod(str, enum.Enum):
    FIFO = "fifo"
    LIFO = "lifo"
    WEIGHTED_AVERAGE = "weighted_average"
    STANDARD_COST = "standard_cost"
    SPECIFIC_IDENTIFICATION = "specific_identification"


class InventoryRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class InventorySource(str, enum.Enum):
    MANUAL = "manual"
    ERP = "erp"
    WMS = "wms"
    POS = "pos"
    SUPPLIER = "supplier"
    PURCHASE_ORDER = "purchase_order"
    STOCK_TRANSFER = "stock_transfer"
    AI_AGENT = "ai_agent"
    SYSTEM = "system"


# ============================================================
# INVENTORY MODEL
# ============================================================

class Inventory(Base):
    __tablename__ = "inventory"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "inventory_code",
            name="uq_inventory_org_code",
        ),
        UniqueConstraint(
            "organization_id",
            "product_id",
            "warehouse_id",
            "location_key",
            "lot_key",
            name="uq_inventory_stock_identity",
        ),
        CheckConstraint(
            "quantity_on_hand >= 0",
            name="inventory_on_hand_nonnegative",
        ),
        CheckConstraint(
            "quantity_reserved >= 0",
            name="inventory_reserved_nonnegative",
        ),
        CheckConstraint(
            "quantity_damaged >= 0",
            name="inventory_damaged_nonnegative",
        ),
        CheckConstraint(
            "quantity_quarantined >= 0",
            name="inventory_quarantined_nonnegative",
        ),
        CheckConstraint(
            "quantity_in_transit >= 0",
            name="inventory_transit_nonnegative",
        ),
        CheckConstraint(
            "quantity_on_order >= 0",
            name="inventory_on_order_nonnegative",
        ),
        CheckConstraint(
            "quantity_reserved + quantity_damaged + "
            "quantity_quarantined <= quantity_on_hand",
            name="inventory_unavailable_limit",
        ),
        CheckConstraint(
            "reorder_point >= 0",
            name="inventory_reorder_nonnegative",
        ),
        CheckConstraint(
            "safety_stock >= 0",
            name="inventory_safety_nonnegative",
        ),
        CheckConstraint(
            "maximum_stock IS NULL OR maximum_stock >= 0",
            name="inventory_maximum_nonnegative",
        ),
        CheckConstraint(
            "minimum_order_quantity >= 0",
            name="inventory_moq_nonnegative",
        ),
        CheckConstraint(
            "lead_time_days >= 0",
            name="inventory_lead_time_nonnegative",
        ),
        CheckConstraint(
            "unit_cost >= 0",
            name="inventory_cost_nonnegative",
        ),
        CheckConstraint(
            "forecast_demand >= 0",
            name="inventory_forecast_nonnegative",
        ),
        CheckConstraint(
            "recommended_reorder_quantity >= 0",
            name="inventory_recommendation_nonnegative",
        ),
        CheckConstraint(
            "stockout_probability IS NULL OR "
            "(stockout_probability >= 0 "
            "AND stockout_probability <= 1)",
            name="inventory_stockout_probability_range",
        ),
        CheckConstraint(
            "anomaly_score IS NULL OR "
            "(anomaly_score >= 0 AND anomaly_score <= 1)",
            name="inventory_anomaly_score_range",
        ),
        Index(
            "ix_inventory_org_product",
            "organization_id",
            "product_id",
        ),
        Index(
            "ix_inventory_org_warehouse",
            "organization_id",
            "warehouse_id",
        ),
        Index(
            "ix_inventory_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_inventory_org_supplier",
            "organization_id",
            "supplier_id",
        ),
        Index(
            "ix_inventory_org_expiry",
            "organization_id",
            "expiry_date",
        ),
        Index(
            "ix_inventory_org_risk",
            "organization_id",
            "risk_level",
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

    inventory_code: Mapped[str] = mapped_column(
        String(40),
        default=generate_inventory_code,
        nullable=False,
    )

    product_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    warehouse_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    supplier_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # STOCK LOCATION
    # --------------------------------------------------------

    bin_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    zone_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # Non-null normalized identity key prevents duplicate
    # inventory rows when the bin/location is unspecified.
    location_key: Mapped[str] = mapped_column(
        String(150),
        default="DEFAULT",
        nullable=False,
    )

    lot_number: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    lot_key: Mapped[str] = mapped_column(
        String(150),
        default="DEFAULT",
        nullable=False,
    )

    serial_number: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    sku: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    # --------------------------------------------------------
    # INVENTORY CLASSIFICATION
    # --------------------------------------------------------

    status: Mapped[InventoryStatus] = mapped_column(
        enum_column(
            InventoryStatus,
            "inventory_status",
        ),
        default=InventoryStatus.ACTIVE,
        nullable=False,
    )

    condition: Mapped[InventoryCondition] = mapped_column(
        enum_column(
            InventoryCondition,
            "inventory_condition",
        ),
        default=InventoryCondition.GOOD,
        nullable=False,
    )

    source: Mapped[InventorySource] = mapped_column(
        enum_column(
            InventorySource,
            "inventory_source",
        ),
        default=InventorySource.SYSTEM,
        nullable=False,
    )

    unit_of_measure: Mapped[str] = mapped_column(
        String(30),
        default="unit",
        nullable=False,
    )

    # --------------------------------------------------------
    # STOCK QUANTITIES
    # --------------------------------------------------------

    quantity_on_hand: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    quantity_reserved: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    quantity_damaged: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    quantity_quarantined: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    quantity_in_transit: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    quantity_on_order: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    # --------------------------------------------------------
    # REPLENISHMENT CONFIGURATION
    # --------------------------------------------------------

    reorder_point: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    safety_stock: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    maximum_stock: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    minimum_order_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("1"),
        nullable=False,
    )

    lead_time_days: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    auto_replenishment_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # --------------------------------------------------------
    # VALUATION
    # --------------------------------------------------------

    currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    valuation_method: Mapped[
        InventoryValuationMethod
    ] = mapped_column(
        enum_column(
            InventoryValuationMethod,
            "inventory_valuation_method",
        ),
        default=InventoryValuationMethod.WEIGHTED_AVERAGE,
        nullable=False,
    )

    # --------------------------------------------------------
    # LOT / EXPIRY
    # --------------------------------------------------------

    manufactured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    expiry_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_stock_count_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_movement_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # AI / ML INVENTORY INTELLIGENCE
    # --------------------------------------------------------

    demand_forecast_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    forecast_demand: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    recommended_reorder_quantity: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    stockout_probability: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    anomaly_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    risk_level: Mapped[InventoryRiskLevel] = mapped_column(
        enum_column(
            InventoryRiskLevel,
            "inventory_risk_level",
        ),
        default=InventoryRiskLevel.UNKNOWN,
        nullable=False,
    )

    ai_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    ai_recommendation: Mapped[str | None] = mapped_column(
        Text,
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

    agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    agent_action_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    requires_human_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    approval_request_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # EXTERNAL INTEGRATION
    # --------------------------------------------------------

    external_inventory_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    integration_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # METADATA
    # --------------------------------------------------------

    inventory_metadata: Mapped[
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
    def available_quantity(self) -> Decimal:
        """
        Available-to-promise quantity.

        Excludes reserved, damaged and quarantined stock.
        """
        return max(
            Decimal("0"),
            self.quantity_on_hand
            - self.quantity_reserved
            - self.quantity_damaged
            - self.quantity_quarantined,
        )

    @property
    def unavailable_quantity(self) -> Decimal:
        return (
            self.quantity_reserved
            + self.quantity_damaged
            + self.quantity_quarantined
        )

    @property
    def inventory_value(self) -> Decimal:
        return self.quantity_on_hand * self.unit_cost

    @property
    def available_inventory_value(self) -> Decimal:
        return self.available_quantity * self.unit_cost

    @property
    def is_stockout(self) -> bool:
        return self.available_quantity <= 0

    @property
    def is_low_stock(self) -> bool:
        return self.available_quantity <= self.reorder_point

    @property
    def is_overstock(self) -> bool:
        return (
            self.maximum_stock is not None
            and self.quantity_on_hand > self.maximum_stock
        )

    @property
    def is_expired(self) -> bool:
        return (
            self.expiry_date is not None
            and as_utc(self.expiry_date) <= utc_now()
        )

    @property
    def needs_replenishment(self) -> bool:
        return (
            not self.is_deleted
            and self.status != InventoryStatus.DISCONTINUED
            and self.available_quantity <= self.reorder_point
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_active(self) -> None:
        if self.is_deleted:
            raise ValueError("Inventory record is deleted")

        if self.status in {
            InventoryStatus.INACTIVE,
            InventoryStatus.DISCONTINUED,
        }:
            raise ValueError(
                "Inventory record is inactive"
            )

    def _validate_stock(self) -> None:
        quantities = (
            self.quantity_on_hand,
            self.quantity_reserved,
            self.quantity_damaged,
            self.quantity_quarantined,
            self.quantity_in_transit,
            self.quantity_on_order,
        )

        if any(quantity < 0 for quantity in quantities):
            raise ValueError(
                "Inventory quantities cannot be negative"
            )

        if self.unavailable_quantity > self.quantity_on_hand:
            raise ValueError(
                "Reserved, damaged and quarantined stock "
                "cannot exceed on-hand stock"
            )

    def _refresh_stock_status(self) -> None:
        if self.status in {
            InventoryStatus.INACTIVE,
            InventoryStatus.DISCONTINUED,
        }:
            return

        if self.is_expired:
            self.status = InventoryStatus.QUARANTINED
        elif self.quantity_quarantined == self.quantity_on_hand \
                and self.quantity_on_hand > 0:
            self.status = InventoryStatus.QUARANTINED
        elif self.is_stockout:
            self.status = InventoryStatus.OUT_OF_STOCK
        elif self.is_overstock:
            self.status = InventoryStatus.OVERSTOCK
        elif self.is_low_stock:
            self.status = InventoryStatus.LOW_STOCK
        else:
            self.status = InventoryStatus.ACTIVE

    def _record_movement(self) -> None:
        self.last_movement_at = utc_now()
        self._refresh_stock_status()
        self._touch()

    # ========================================================
    # RECEIVE STOCK
    # ========================================================

    def receive_stock(
        self,
        quantity: Decimal | int | float,
        *,
        unit_cost: Decimal | int | float | None = None,
    ) -> None:
        self._ensure_active()

        quantity = to_decimal(
            quantity,
            allow_zero=False,
        )

        if unit_cost is not None:
            new_cost = to_decimal(unit_cost)

            if self.valuation_method == (
                InventoryValuationMethod.WEIGHTED_AVERAGE
            ):
                old_value = (
                    self.quantity_on_hand * self.unit_cost
                )
                incoming_value = quantity * new_cost
                new_total = self.quantity_on_hand + quantity

                self.unit_cost = (
                    (old_value + incoming_value) / new_total
                ).quantize(MONEY_PRECISION)
            else:
                self.unit_cost = new_cost

        self.quantity_on_hand += quantity
        self.received_at = utc_now()

        self._validate_stock()
        self._record_movement()

    # ========================================================
    # RESERVE STOCK
    # ========================================================

    def reserve_stock(
        self,
        quantity: Decimal | int | float,
    ) -> None:
        self._ensure_active()

        if self.is_expired:
            raise ValueError(
                "Expired inventory cannot be reserved"
            )

        quantity = to_decimal(
            quantity,
            allow_zero=False,
        )

        if quantity > self.available_quantity:
            raise ValueError(
                "Insufficient available inventory"
            )

        self.quantity_reserved += quantity

        self._validate_stock()
        self._record_movement()

    # ========================================================
    # RELEASE RESERVED STOCK
    # ========================================================

    def release_reservation(
        self,
        quantity: Decimal | int | float,
    ) -> None:
        self._ensure_active()

        quantity = to_decimal(
            quantity,
            allow_zero=False,
        )

        if quantity > self.quantity_reserved:
            raise ValueError(
                "Release exceeds reserved quantity"
            )

        self.quantity_reserved -= quantity

        self._validate_stock()
        self._record_movement()

    # ========================================================
    # FULFILL RESERVED STOCK
    # ========================================================

    def fulfill_reserved_stock(
        self,
        quantity: Decimal | int | float,
    ) -> None:
        self._ensure_active()

        quantity = to_decimal(
            quantity,
            allow_zero=False,
        )

        if quantity > self.quantity_reserved:
            raise ValueError(
                "Insufficient reserved stock"
            )

        self.quantity_reserved -= quantity
        self.quantity_on_hand -= quantity

        self._validate_stock()
        self._record_movement()

    # ========================================================
    # ISSUE UNRESERVED STOCK
    # ========================================================

    def issue_stock(
        self,
        quantity: Decimal | int | float,
    ) -> None:
        self._ensure_active()

        if self.is_expired:
            raise ValueError(
                "Expired inventory cannot be issued"
            )

        quantity = to_decimal(
            quantity,
            allow_zero=False,
        )

        if quantity > self.available_quantity:
            raise ValueError(
                "Insufficient available inventory"
            )

        self.quantity_on_hand -= quantity

        self._validate_stock()
        self._record_movement()

    # ========================================================
    # MARK DAMAGED
    # ========================================================

    def mark_damaged(
        self,
        quantity: Decimal | int | float,
    ) -> None:
        self._ensure_active()

        quantity = to_decimal(
            quantity,
            allow_zero=False,
        )

        if quantity > self.available_quantity:
            raise ValueError(
                "Insufficient available stock"
            )

        self.quantity_damaged += quantity
        self._validate_stock()
        self._record_movement()

    # ========================================================
    # QUARANTINE STOCK
    # ========================================================

    def quarantine_stock(
        self,
        quantity: Decimal | int | float,
    ) -> None:
        self._ensure_active()

        quantity = to_decimal(
            quantity,
            allow_zero=False,
        )

        if quantity > self.available_quantity:
            raise ValueError(
                "Insufficient available stock"
            )

        self.quantity_quarantined += quantity

        self._validate_stock()
        self._record_movement()

    # ========================================================
    # RELEASE QUARANTINE
    # ========================================================

    def release_quarantine(
        self,
        quantity: Decimal | int | float,
    ) -> None:
        self._ensure_active()

        if self.is_expired:
            raise ValueError(
                "Expired inventory cannot be released"
            )

        quantity = to_decimal(
            quantity,
            allow_zero=False,
        )

        if quantity > self.quantity_quarantined:
            raise ValueError(
                "Release exceeds quarantined stock"
            )

        self.quantity_quarantined -= quantity

        self._validate_stock()
        self._record_movement()

    # ========================================================
    # REMOVE DAMAGED STOCK
    # ========================================================

    def write_off_damaged(
        self,
        quantity: Decimal | int | float,
    ) -> None:
        self._ensure_active()

        quantity = to_decimal(
            quantity,
            allow_zero=False,
        )

        if quantity > self.quantity_damaged:
            raise ValueError(
                "Write-off exceeds damaged quantity"
            )

        self.quantity_damaged -= quantity
        self.quantity_on_hand -= quantity

        self._validate_stock()
        self._record_movement()

    # ========================================================
    # PHYSICAL STOCK COUNT
    # ========================================================

    def reconcile_stock_count(
        self,
        *,
        counted_quantity: Decimal | int | float,
        user_id: str,
        reason: str,
    ) -> Decimal:
        self._ensure_active()

        if not user_id or not reason.strip():
            raise ValueError(
                "User ID and adjustment reason required"
            )

        counted = to_decimal(counted_quantity)

        if counted < self.unavailable_quantity:
            raise ValueError(
                "Physical count is below tracked unavailable "
                "stock; reconcile reservations and holds first"
            )

        difference = counted - self.quantity_on_hand

        self.quantity_on_hand = counted
        self.last_stock_count_at = utc_now()
        self.updated_by = user_id

        metadata = dict(self.inventory_metadata or {})
        metadata["last_stock_adjustment"] = {
            "difference": str(difference),
            "reason": reason,
            "user_id": user_id,
            "recorded_at": utc_now().isoformat(),
        }
        self.inventory_metadata = metadata

        self._validate_stock()
        self._record_movement()

        return difference

    # ========================================================
    # REPLENISHMENT CONFIGURATION
    # ========================================================

    def configure_replenishment(
        self,
        *,
        reorder_point: Decimal | int | float,
        safety_stock: Decimal | int | float,
        minimum_order_quantity: Decimal | int | float,
        lead_time_days: int,
        maximum_stock: Decimal | int | float | None = None,
    ) -> None:
        self._ensure_active()

        if isinstance(lead_time_days, bool) or (
            not isinstance(lead_time_days, int)
            or lead_time_days < 0
        ):
            raise ValueError(
                "Lead time must be a nonnegative integer"
            )

        new_reorder = to_decimal(reorder_point)
        new_safety = to_decimal(safety_stock)
        new_moq = to_decimal(
            minimum_order_quantity,
            allow_zero=False,
        )
        new_maximum = (
            to_decimal(maximum_stock)
            if maximum_stock is not None
            else None
        )

        if (
            new_maximum is not None
            and new_maximum < new_safety
        ):
            raise ValueError(
                "Maximum stock cannot be below safety stock"
            )

        self.reorder_point = new_reorder
        self.safety_stock = new_safety
        self.minimum_order_quantity = new_moq
        self.lead_time_days = lead_time_days
        self.maximum_stock = new_maximum

        self._refresh_stock_status()
        self._touch()

    # ========================================================
    # AI FORECAST UPDATE
    # ========================================================

    def update_ai_forecast(
        self,
        *,
        forecast_quantity: Decimal | int | float,
        reorder_quantity: Decimal | int | float,
        stockout_probability: float,
        anomaly_score: float,
        risk_level: InventoryRiskLevel,
        model_name: str,
        summary: str,
        recommendation: str,
        demand_forecast_id: str | None = None,
    ) -> None:
        self._ensure_active()

        probability = float(stockout_probability)
        anomaly = float(anomaly_score)

        if (
            not math.isfinite(probability)
            or not 0 <= probability <= 1
        ):
            raise ValueError(
                "Stockout probability must be between 0 and 1"
            )

        if (
            not math.isfinite(anomaly)
            or not 0 <= anomaly <= 1
        ):
            raise ValueError(
                "Anomaly score must be between 0 and 1"
            )

        if not model_name.strip():
            raise ValueError(
                "Model name is required"
            )

        self.forecast_demand = to_decimal(
            forecast_quantity
        )
        self.recommended_reorder_quantity = to_decimal(
            reorder_quantity
        )
        self.stockout_probability = probability
        self.anomaly_score = anomaly
        self.risk_level = risk_level
        self.model_name = model_name
        self.ai_summary = summary
        self.ai_recommendation = recommendation
        self.demand_forecast_id = demand_forecast_id

        self._touch()

    # ========================================================
    # CALCULATE REORDER QUANTITY
    # ========================================================

    def calculate_reorder_quantity(self) -> Decimal:
        """
        Simple order-up-to policy.

        Includes confirmed incoming stock, but does not
        independently validate purchase orders or transfers.
        """
        if not self.needs_replenishment:
            return Decimal("0")

        target = max(
            self.reorder_point,
            self.safety_stock + self.forecast_demand,
        )

        effective_stock = (
            self.available_quantity
            + self.quantity_on_order
            + self.quantity_in_transit
        )

        required = max(
            Decimal("0"),
            target - effective_stock,
        )

        if required == 0:
            return Decimal("0")

        return max(
            required,
            self.minimum_order_quantity,
        )

    # ========================================================
    # SOFT DELETE
    # ========================================================

    def soft_delete(self, user_id: str) -> None:
        if self.is_deleted:
            raise ValueError(
                "Inventory record already deleted"
            )

        if not user_id:
            raise ValueError(
                "Deleting user ID is required"
            )

        if any(
            quantity > 0
            for quantity in (
                self.quantity_on_hand,
                self.quantity_reserved,
                self.quantity_in_transit,
                self.quantity_on_order,
            )
        ):
            raise ValueError(
                "Inventory with outstanding stock or "
                "incoming quantities cannot be deleted"
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
            "inventory_code": self.inventory_code,
            "product_id": self.product_id,
            "warehouse_id": self.warehouse_id,
            "supplier_id": self.supplier_id,
            "bin_id": self.bin_id,
            "zone_id": self.zone_id,
            "location_key": self.location_key,
            "lot_number": self.lot_number,
            "serial_number": self.serial_number,
            "sku": self.sku,
            "status": self.status.value,
            "condition": self.condition.value,
            "source": self.source.value,
            "unit_of_measure": self.unit_of_measure,
            "quantity_on_hand": decimal_string(
                self.quantity_on_hand
            ),
            "quantity_reserved": decimal_string(
                self.quantity_reserved
            ),
            "quantity_damaged": decimal_string(
                self.quantity_damaged
            ),
            "quantity_quarantined": decimal_string(
                self.quantity_quarantined
            ),
            "quantity_in_transit": decimal_string(
                self.quantity_in_transit
            ),
            "quantity_on_order": decimal_string(
                self.quantity_on_order
            ),
            "available_quantity": decimal_string(
                self.available_quantity
            ),
            "unavailable_quantity": decimal_string(
                self.unavailable_quantity
            ),
            "reorder_point": decimal_string(
                self.reorder_point
            ),
            "safety_stock": decimal_string(
                self.safety_stock
            ),
            "maximum_stock": decimal_string(
                self.maximum_stock
            ),
            "minimum_order_quantity": decimal_string(
                self.minimum_order_quantity
            ),
            "lead_time_days": self.lead_time_days,
            "auto_replenishment_enabled": (
                self.auto_replenishment_enabled
            ),
            "currency": self.currency,
            "unit_cost": decimal_string(self.unit_cost),
            "valuation_method": self.valuation_method.value,
            "inventory_value": decimal_string(
                self.inventory_value
            ),
            "available_inventory_value": decimal_string(
                self.available_inventory_value
            ),
            "manufactured_at": datetime_string(
                self.manufactured_at
            ),
            "received_at": datetime_string(
                self.received_at
            ),
            "expiry_date": datetime_string(
                self.expiry_date
            ),
            "last_stock_count_at": datetime_string(
                self.last_stock_count_at
            ),
            "last_movement_at": datetime_string(
                self.last_movement_at
            ),
            "is_stockout": self.is_stockout,
            "is_low_stock": self.is_low_stock,
            "is_overstock": self.is_overstock,
            "is_expired": self.is_expired,
            "needs_replenishment": self.needs_replenishment,
            "demand_forecast_id": self.demand_forecast_id,
            "forecast_demand": decimal_string(
                self.forecast_demand
            ),
            "recommended_reorder_quantity": decimal_string(
                self.recommended_reorder_quantity
            ),
            "stockout_probability": self.stockout_probability,
            "anomaly_score": self.anomaly_score,
            "risk_level": self.risk_level.value,
            "ai_summary": self.ai_summary,
            "ai_recommendation": self.ai_recommendation,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "agent_run_id": self.agent_run_id,
            "agent_action_id": self.agent_action_id,
            "requires_human_approval": (
                self.requires_human_approval
            ),
            "approval_request_id": self.approval_request_id,
            "external_inventory_id": self.external_inventory_id,
            "integration_id": self.integration_id,
            "last_synced_at": datetime_string(
                self.last_synced_at
            ),
            "inventory_metadata": self.inventory_metadata,
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
            f"<Inventory("
            f"id={self.id}, "
            f"product_id={self.product_id}, "
            f"warehouse_id={self.warehouse_id}, "
            f"on_hand={self.quantity_on_hand}, "
            f"reserved={self.quantity_reserved}"
            f")>"
        )
