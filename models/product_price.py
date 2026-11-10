from __future__ import annotations

"""Planned module: product price. Implementation pending."""

"""
backend/models/product_price.py

Autonomous Retail Supply Chain AI 5.0
Product Pricing and AI Price Intelligence Model

SQLAlchemy 2.0 compatible.

Pricing calculations:
- Decimal-based monetary arithmetic
- Percentage and fixed-amount discounts
- Tax-exclusive and tax-inclusive totals
- Gross margin and markup
- Competitor price comparisons
- AI-assisted pricing recommendations

Lifecycle:
    DRAFT -> PENDING_APPROVAL -> APPROVED
    DRAFT -> APPROVED (when approval is not required)
    APPROVED -> ACTIVE -> EXPIRED
    APPROVED/ACTIVE -> SUSPENDED
    DRAFT/PENDING_APPROVAL -> CANCELLED

External authorization, tax rules, inventory synchronization,
and checkout price locking belong in service-layer transactions.
"""


import enum
import uuid

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
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

MONEY_QUANT = Decimal("0.0001")
PERCENT_QUANT = Decimal("0.0001")
MAX_NUMERIC = Decimal("100000000000000")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_price_code() -> str:
    return f"PRICE-{uuid.uuid4().hex[:16].upper()}"


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


def decimal_value(
    value: Decimal | int | float | str,
    *,
    field_name: str,
    allow_zero: bool = True,
) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(
            f"{field_name} must be numeric"
        )

    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(
            f"{field_name} must be numeric"
        ) from None

    if not result.is_finite():
        raise ValueError(
            f"{field_name} must be finite"
        )

    if result < 0 or (
        not allow_zero and result == 0
    ):
        raise ValueError(
            f"{field_name} must be positive"
            if not allow_zero
            else f"{field_name} cannot be negative"
        )

    if result >= MAX_NUMERIC:
        raise ValueError(
            f"{field_name} exceeds numeric precision"
        )

    if result != result.quantize(MONEY_QUANT):
        raise ValueError(
            f"{field_name} supports at most "
            "four decimal places"
        )

    return result


def money(value: Decimal) -> Decimal:
    return value.quantize(
        MONEY_QUANT,
        rounding=ROUND_HALF_UP,
    )


def percentage(
    value: Decimal | int | float | str,
    field_name: str,
) -> Decimal:
    result = decimal_value(
        value,
        field_name=field_name,
    )

    if result > 100:
        raise ValueError(
            f"{field_name} cannot exceed 100%"
        )

    return result


def require_text(
    value: str,
    field_name: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{field_name} is required"
        )

    return value.strip()


def aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(
            "Expected datetime"
        )

    if value.tzinfo is None:
        raise ValueError(
            "Timezone-aware datetime required"
        )

    return value.astimezone(timezone.utc)


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def enum_value(value: enum.Enum | None):
    return value.value if value is not None else None


def decimal_string(value: Decimal | None):
    return str(value) if value is not None else None


# ============================================================
# ENUMS
# ============================================================

class ProductPriceStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class ProductPriceType(str, enum.Enum):
    REGULAR = "regular"
    SALE = "sale"
    PROMOTIONAL = "promotional"
    WHOLESALE = "wholesale"
    RETAIL = "retail"
    CONTRACT = "contract"
    DYNAMIC = "dynamic"
    CLEARANCE = "clearance"
    SEASONAL = "seasonal"
    BUNDLE = "bundle"
    CUSTOM = "custom"


class ProductPriceSource(str, enum.Enum):
    MANUAL = "manual"
    ERP = "erp"
    POS = "pos"
    ECOMMERCE = "ecommerce"
    SUPPLIER = "supplier"
    MARKET_DATA = "market_data"
    RULE_ENGINE = "rule_engine"
    AI_AGENT = "ai_agent"
    OPTIMIZATION_ENGINE = "optimization_engine"
    SYSTEM = "system"


class DiscountType(str, enum.Enum):
    NONE = "none"
    PERCENTAGE = "percentage"
    FIXED_AMOUNT = "fixed_amount"


class TaxMode(str, enum.Enum):
    EXCLUSIVE = "exclusive"
    INCLUSIVE = "inclusive"
    EXEMPT = "exempt"


class PriceRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class PriceApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PriceChangeReason(str, enum.Enum):
    COST_CHANGE = "cost_change"
    COMPETITOR_CHANGE = "competitor_change"
    DEMAND_CHANGE = "demand_change"
    INVENTORY_CHANGE = "inventory_change"
    PROMOTION = "promotion"
    SEASONAL = "seasonal"
    MANUAL_ADJUSTMENT = "manual_adjustment"
    AI_RECOMMENDATION = "ai_recommendation"
    CORRECTION = "correction"
    OTHER = "other"


# ============================================================
# PRODUCT PRICE MODEL
# ============================================================

class ProductPrice(Base):
    __tablename__ = "product_prices"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "price_code",
            name="uq_product_price_org_code",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_product_price_org_idempotency",
        ),
        CheckConstraint(
            "base_price >= 0",
            name="product_price_base_nonnegative",
        ),
        CheckConstraint(
            "cost_price >= 0",
            name="product_price_cost_nonnegative",
        ),
        CheckConstraint(
            "discount_value >= 0",
            name="product_price_discount_nonnegative",
        ),
        CheckConstraint(
            "tax_rate >= 0 AND tax_rate <= 100",
            name="product_price_tax_valid",
        ),
        CheckConstraint(
            "min_price IS NULL OR min_price >= 0",
            name="product_price_min_valid",
        ),
        CheckConstraint(
            "max_price IS NULL OR max_price >= 0",
            name="product_price_max_valid",
        ),
        CheckConstraint(
            "min_price IS NULL OR max_price IS NULL "
            "OR min_price <= max_price",
            name="product_price_bounds_valid",
        ),
        CheckConstraint(
            "competitor_price IS NULL "
            "OR competitor_price >= 0",
            name="product_price_competitor_valid",
        ),
        CheckConstraint(
            "version >= 1",
            name="product_price_version_positive",
        ),
        Index(
            "ix_product_price_org_product",
            "organization_id",
            "product_id",
        ),
        Index(
            "ix_product_price_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_product_price_org_type",
            "organization_id",
            "price_type",
        ),
        Index(
            "ix_product_price_org_warehouse",
            "organization_id",
            "warehouse_id",
        ),
        Index(
            "ix_product_price_org_channel",
            "organization_id",
            "sales_channel",
        ),
        Index(
            "ix_product_price_org_effective",
            "organization_id",
            "effective_from",
            "effective_until",
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

    price_code: Mapped[str] = mapped_column(
        String(50),
        default=generate_price_code,
        nullable=False,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # --------------------------------------------------------
    # PRODUCT REFERENCES
    # --------------------------------------------------------

    product_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    sku: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    category_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    supplier_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    warehouse_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    customer_segment_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    sales_channel: Mapped[str] = mapped_column(
        String(50),
        default="all",
        nullable=False,
    )

    region_code: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    # --------------------------------------------------------
    # PRICE IDENTITY
    # --------------------------------------------------------

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    status: Mapped[ProductPriceStatus] = mapped_column(
        enum_column(
            ProductPriceStatus,
            "product_price_status",
        ),
        default=ProductPriceStatus.DRAFT,
        nullable=False,
    )

    price_type: Mapped[ProductPriceType] = mapped_column(
        enum_column(
            ProductPriceType,
            "product_price_type",
        ),
        default=ProductPriceType.REGULAR,
        nullable=False,
    )

    source: Mapped[ProductPriceSource] = mapped_column(
        enum_column(
            ProductPriceSource,
            "product_price_source",
        ),
        default=ProductPriceSource.MANUAL,
        nullable=False,
    )

    # --------------------------------------------------------
    # CURRENCY AND BASE PRICE
    # --------------------------------------------------------

    currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    base_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    cost_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    list_price: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    min_price: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    max_price: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    # --------------------------------------------------------
    # DISCOUNT
    # --------------------------------------------------------

    discount_type: Mapped[DiscountType] = mapped_column(
        enum_column(
            DiscountType,
            "product_price_discount_type",
        ),
        default=DiscountType.NONE,
        nullable=False,
    )

    discount_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    promotion_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    coupon_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # --------------------------------------------------------
    # TAX
    # --------------------------------------------------------

    tax_mode: Mapped[TaxMode] = mapped_column(
        enum_column(
            TaxMode,
            "product_price_tax_mode",
        ),
        default=TaxMode.EXCLUSIVE,
        nullable=False,
    )

    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(8, 4),
        default=Decimal("0"),
        nullable=False,
    )

    tax_code: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    # --------------------------------------------------------
    # EFFECTIVE PERIOD
    # --------------------------------------------------------

    effective_from: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    effective_until: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    activated_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    expired_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # COMPETITOR INTELLIGENCE
    # --------------------------------------------------------

    competitor_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    competitor_price: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    competitor_currency: Mapped[
        str | None
    ] = mapped_column(
        String(3),
        nullable=True,
    )

    competitor_observed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    competitor_source_url: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    competitor_prices: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # --------------------------------------------------------
    # AI PRICE INTELLIGENCE
    # --------------------------------------------------------

    ai_recommended_price: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    ai_confidence_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    ai_risk_level: Mapped[
        PriceRiskLevel
    ] = mapped_column(
        enum_column(
            PriceRiskLevel,
            "product_price_risk_level",
        ),
        default=PriceRiskLevel.UNKNOWN,
        nullable=False,
    )

    ai_explanation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    ai_model_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    ai_agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    ai_features: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    ai_recommended_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # PRICING RULES
    # --------------------------------------------------------

    pricing_rules: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    dynamic_pricing_enabled: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    automatic_activation_enabled: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # --------------------------------------------------------
    # HUMAN APPROVAL
    # --------------------------------------------------------

    requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    approval_status: Mapped[
        PriceApprovalStatus
    ] = mapped_column(
        enum_column(
            PriceApprovalStatus,
            "product_price_approval_status",
        ),
        default=PriceApprovalStatus.NOT_REQUIRED,
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

    rejection_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # CHANGE TRACKING
    # --------------------------------------------------------

    change_reason: Mapped[
        PriceChangeReason | None
    ] = mapped_column(
        enum_column(
            PriceChangeReason,
            "product_price_change_reason",
        ),
        nullable=True,
    )

    price_history: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # --------------------------------------------------------
    # EXTERNAL INTEGRATIONS
    # --------------------------------------------------------

    external_price_id: Mapped[
        str | None
    ] = mapped_column(
        String(150),
        nullable=True,
    )

    integration_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    last_synced_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # METADATA
    # --------------------------------------------------------

    price_metadata: Mapped[
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

    # --------------------------------------------------------
    # SOFT DELETE
    # --------------------------------------------------------

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
    def discount_amount(self) -> Decimal:
        base = self.base_price or Decimal("0")
        value = self.discount_value or Decimal("0")

        if self.discount_type == DiscountType.NONE:
            return Decimal("0")

        if self.discount_type == DiscountType.PERCENTAGE:
            return money(
                base * value / Decimal("100")
            )

        return min(base, value)

    @property
    def net_price(self) -> Decimal:
        return money(
            max(
                Decimal("0"),
                self.base_price - self.discount_amount,
            )
        )

    @property
    def tax_amount(self) -> Decimal:
        if self.tax_mode == TaxMode.EXEMPT:
            return Decimal("0")

        rate = self.tax_rate or Decimal("0")
        net = self.net_price

        if self.tax_mode == TaxMode.INCLUSIVE:
            if rate == 0:
                return Decimal("0")

            return money(
                net * rate
                / (Decimal("100") + rate)
            )

        return money(
            net * rate / Decimal("100")
        )

    @property
    def final_price(self) -> Decimal:
        if self.tax_mode == TaxMode.EXCLUSIVE:
            return money(
                self.net_price + self.tax_amount
            )

        return self.net_price

    @property
    def revenue_excluding_tax(self) -> Decimal:
        if self.tax_mode == TaxMode.INCLUSIVE:
            return money(
                self.net_price - self.tax_amount
            )

        return self.net_price

    @property
    def gross_profit(self) -> Decimal:
        return money(
            self.revenue_excluding_tax
            - self.cost_price
        )

    @property
    def gross_margin_percent(self) -> Decimal:
        revenue = self.revenue_excluding_tax

        if revenue <= 0:
            return Decimal("0")

        return money(
            self.gross_profit
            / revenue
            * Decimal("100")
        )

    @property
    def markup_percent(self) -> Decimal:
        if self.cost_price <= 0:
            return Decimal("0")

        return money(
            self.gross_profit
            / self.cost_price
            * Decimal("100")
        )

    @property
    def competitor_price_difference(self) -> Decimal | None:
        if self.competitor_price is None:
            return None

        if (
            self.competitor_currency
            and self.competitor_currency != self.currency
        ):
            return None

        return money(
            self.final_price - self.competitor_price
        )

    @property
    def is_currently_effective(self) -> bool:
        now = utc_now()

        if self.status != ProductPriceStatus.ACTIVE:
            return False

        if self.is_deleted:
            return False

        if (
            self.effective_from is not None
            and now < aware_utc(self.effective_from)
        ):
            return False

        if (
            self.effective_until is not None
            and now >= aware_utc(self.effective_until)
        ):
            return False

        return True

    @property
    def can_activate(self) -> bool:
        if self.is_deleted:
            return False

        if self.status != ProductPriceStatus.APPROVED:
            return False

        if (
            self.requires_approval
            and self.approval_status
            != PriceApprovalStatus.APPROVED
        ):
            return False

        if (
            self.effective_until is not None
            and utc_now() >= aware_utc(self.effective_until)
        ):
            return False

        return True

    # ========================================================
    # INTERNAL METHODS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_editable(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Product price is deleted"
            )

        if self.status != ProductPriceStatus.DRAFT:
            raise ValueError(
                "Pricing terms can only be edited in draft. "
                "Create a new price version instead."
            )

    def _ensure_not_deleted(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Product price is deleted"
            )

    def _record_event(
        self,
        event: str,
        *,
        actor_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        history = list(self.price_history or [])

        history.append({
            "event_id": generate_uuid(),
            "event": event,
            "actor_id": actor_id,
            "timestamp": utc_now().isoformat(),
            "details": details or {},
        })

        self.price_history = history
        self._touch()

    def _validate_price_bounds(
        self,
        candidate: Decimal,
    ) -> None:
        if (
            self.min_price is not None
            and candidate < self.min_price
        ):
            raise ValueError(
                "Price is below configured minimum"
            )

        if (
            self.max_price is not None
            and candidate > self.max_price
        ):
            raise ValueError(
                "Price exceeds configured maximum"
            )

    def _validate_configuration(self) -> None:
        if self.base_price < 0:
            raise ValueError(
                "Base price cannot be negative"
            )

        if self.cost_price < 0:
            raise ValueError(
                "Cost price cannot be negative"
            )

        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError(
                "Minimum price exceeds maximum price"
            )

        if self.discount_type == DiscountType.PERCENTAGE:
            percentage(
                self.discount_value,
                "discount_value",
            )

        if self.discount_type == DiscountType.FIXED_AMOUNT:
            if self.discount_value > self.base_price:
                raise ValueError(
                    "Fixed discount exceeds base price"
                )

        percentage(
            self.tax_rate,
            "tax_rate",
        )

        self._validate_price_bounds(self.net_price)

        if (
            self.effective_from is not None
            and self.effective_until is not None
            and aware_utc(self.effective_from)
            >= aware_utc(self.effective_until)
        ):
            raise ValueError(
                "Effective end must follow start"
            )

        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValueError(
                "Currency must be a three-letter ISO code"
            )

    # ========================================================
    # UPDATE BASE PRICE
    # ========================================================

    def update_base_price(
        self,
        *,
        new_price: Decimal | int | float | str,
        actor_id: str,
        reason: PriceChangeReason,
    ) -> None:
        self._ensure_editable()

        value = decimal_value(
            new_price,
            field_name="new_price",
        )

        old_price = self.base_price
        self.base_price = value

        try:
            self._validate_configuration()
        except ValueError:
            self.base_price = old_price
            raise

        self.change_reason = reason

        self._record_event(
            "base_price_updated",
            actor_id=actor_id,
            details={
                "old_price": str(old_price),
                "new_price": str(value),
                "reason": reason.value,
            },
        )

    # ========================================================
    # UPDATE COST PRICE
    # ========================================================

    def update_cost_price(
        self,
        *,
        new_cost: Decimal | int | float | str,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        value = decimal_value(
            new_cost,
            field_name="new_cost",
        )

        old_cost = self.cost_price
        self.cost_price = value

        self.change_reason = (
            PriceChangeReason.COST_CHANGE
        )

        self._record_event(
            "cost_price_updated",
            actor_id=actor_id,
            details={
                "old_cost": str(old_cost),
                "new_cost": str(value),
            },
        )

    # ========================================================
    # CONFIGURE DISCOUNT
    # ========================================================

    def configure_discount(
        self,
        *,
        discount_type: DiscountType,
        discount_value: Decimal | int | float | str,
        actor_id: str,
        promotion_id: str | None = None,
    ) -> None:
        self._ensure_editable()

        value = decimal_value(
            discount_value,
            field_name="discount_value",
        )

        if discount_type == DiscountType.NONE:
            if value != 0:
                raise ValueError(
                    "NONE discount requires zero value"
                )

        elif discount_type == DiscountType.PERCENTAGE:
            percentage(value, "discount_value")

        elif discount_type == DiscountType.FIXED_AMOUNT:
            if value > self.base_price:
                raise ValueError(
                    "Discount exceeds base price"
                )

        else:
            raise ValueError(
                "Unsupported discount type"
            )

        old_type = self.discount_type
        old_value = self.discount_value
        old_promotion = self.promotion_id

        self.discount_type = discount_type
        self.discount_value = value
        self.promotion_id = promotion_id

        try:
            self._validate_configuration()
        except ValueError:
            self.discount_type = old_type
            self.discount_value = old_value
            self.promotion_id = old_promotion
            raise

        self._record_event(
            "discount_configured",
            actor_id=actor_id,
            details={
                "type": discount_type.value,
                "value": str(value),
                "promotion_id": promotion_id,
            },
        )

    # ========================================================
    # CONFIGURE TAX
    # ========================================================

    def configure_tax(
        self,
        *,
        tax_mode: TaxMode,
        tax_rate: Decimal | int | float | str,
        actor_id: str,
        tax_code: str | None = None,
    ) -> None:
        self._ensure_editable()

        rate = percentage(
            tax_rate,
            "tax_rate",
        )

        old_mode = self.tax_mode
        old_rate = self.tax_rate
        old_code = self.tax_code

        self.tax_mode = tax_mode
        self.tax_rate = rate
        self.tax_code = tax_code

        try:
            self._validate_configuration()
        except ValueError:
            self.tax_mode = old_mode
            self.tax_rate = old_rate
            self.tax_code = old_code
            raise

        self._record_event(
            "tax_configured",
            actor_id=actor_id,
            details={
                "tax_mode": tax_mode.value,
                "tax_rate": str(rate),
                "tax_code": tax_code,
            },
        )

    # ========================================================
    # CONFIGURE PRICE LIMITS
    # ========================================================

    def configure_price_limits(
        self,
        *,
        min_price: Decimal | int | float | str | None,
        max_price: Decimal | int | float | str | None,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        minimum = (
            decimal_value(
                min_price,
                field_name="min_price",
            )
            if min_price is not None
            else None
        )

        maximum = (
            decimal_value(
                max_price,
                field_name="max_price",
            )
            if max_price is not None
            else None
        )

        old_min = self.min_price
        old_max = self.max_price

        self.min_price = minimum
        self.max_price = maximum

        try:
            self._validate_configuration()
        except ValueError:
            self.min_price = old_min
            self.max_price = old_max
            raise

        self._record_event(
            "price_limits_configured",
            actor_id=actor_id,
            details={
                "min_price": decimal_string(minimum),
                "max_price": decimal_string(maximum),
            },
        )

    # ========================================================
    # CONFIGURE EFFECTIVE PERIOD
    # ========================================================

    def configure_effective_period(
        self,
        *,
        effective_from: datetime | None,
        effective_until: datetime | None,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        start = (
            aware_utc(effective_from)
            if effective_from is not None
            else None
        )

        end = (
            aware_utc(effective_until)
            if effective_until is not None
            else None
        )

        if start and end and start >= end:
            raise ValueError(
                "Effective end must follow start"
            )

        self.effective_from = start
        self.effective_until = end

        self._record_event(
            "effective_period_configured",
            actor_id=actor_id,
            details={
                "effective_from": iso(start),
                "effective_until": iso(end),
            },
        )

    # ========================================================
    # RECORD COMPETITOR PRICE
    # ========================================================

    def record_competitor_price(
        self,
        *,
        competitor_name: str,
        competitor_price: Decimal | int | float | str,
        competitor_currency: str,
        observed_at: datetime,
        source_url: str | None = None,
        actor_id: str | None = None,
    ) -> None:
        self._ensure_not_deleted()

        name = require_text(
            competitor_name,
            "Competitor name",
        )

        value = decimal_value(
            competitor_price,
            field_name="competitor_price",
        )

        currency = require_text(
            competitor_currency,
            "Competitor currency",
        ).upper()

        if len(currency) != 3 or not currency.isalpha():
            raise ValueError(
                "Invalid competitor currency"
            )

        observed = aware_utc(observed_at)

        if observed > utc_now():
            raise ValueError(
                "Observation time cannot be in the future"
            )

        records = list(self.competitor_prices or [])

        records.append({
            "id": generate_uuid(),
            "competitor_name": name,
            "price": str(value),
            "currency": currency,
            "observed_at": observed.isoformat(),
            "source_url": source_url,
        })

        self.competitor_prices = records

        if (
            self.competitor_observed_at is None
            or observed >= aware_utc(
                self.competitor_observed_at
            )
        ):
            self.competitor_name = name
            self.competitor_price = value
            self.competitor_currency = currency
            self.competitor_observed_at = observed
            self.competitor_source_url = source_url

        self._record_event(
            "competitor_price_recorded",
            actor_id=actor_id,
            details={
                "competitor": name,
                "price": str(value),
                "currency": currency,
            },
        )

    # ========================================================
    # AI PRICING RECOMMENDATION
    # ========================================================

    def update_ai_recommendation(
        self,
        *,
        recommended_price: Decimal | int | float | str,
        confidence_score: Decimal | int | float | str,
        explanation: str,
        model_id: str,
        agent_run_id: str | None = None,
        risk_level: PriceRiskLevel = (
            PriceRiskLevel.UNKNOWN
        ),
        features: dict[str, Any] | None = None,
    ) -> None:
        self._ensure_not_deleted()

        if self.status in {
            ProductPriceStatus.CANCELLED,
            ProductPriceStatus.ARCHIVED,
            ProductPriceStatus.EXPIRED,
            ProductPriceStatus.REJECTED,
        }:
            raise ValueError(
                "AI recommendations are not accepted "
                "for this price status"
            )

        recommendation = decimal_value(
            recommended_price,
            field_name="recommended_price",
        )

        confidence = decimal_value(
            confidence_score,
            field_name="confidence_score",
        )

        if confidence > 1:
            raise ValueError(
                "Confidence score must be between 0 and 1"
            )

        self._validate_price_bounds(recommendation)

        self.ai_recommended_price = recommendation
        self.ai_confidence_score = confidence
        self.ai_explanation = require_text(
            explanation,
            "Explanation",
        )
        self.ai_model_id = require_text(
            model_id,
            "Model ID",
        )
        self.ai_agent_run_id = agent_run_id
        self.ai_risk_level = risk_level
        self.ai_features = dict(features or {})
        self.ai_recommended_at = utc_now()

        self._record_event(
            "ai_price_recommended",
            details={
                "recommended_price": str(recommendation),
                "confidence": str(confidence),
                "risk_level": risk_level.value,
                "model_id": model_id,
            },
        )

    # ========================================================
    # APPLY AI RECOMMENDATION TO DRAFT
    # ========================================================

    def apply_ai_recommendation(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        if self.ai_recommended_price is None:
            raise ValueError(
                "No AI recommendation available"
            )

        # Human/service authorization must be checked
        # before this method is invoked.

        self.update_base_price(
            new_price=self.ai_recommended_price,
            actor_id=actor_id,
            reason=PriceChangeReason.AI_RECOMMENDATION,
        )

    # ========================================================
    # SUBMIT FOR APPROVAL
    # ========================================================

    def submit_for_approval(
        self,
        *,
        approval_request_id: str | None = None,
        actor_id: str,
    ) -> None:
        self._ensure_editable()
        self._validate_configuration()

        if self.requires_approval:
            if not approval_request_id:
                raise ValueError(
                    "Approval request ID is required"
                )

            self.approval_request_id = approval_request_id
            self.approval_status = (
                PriceApprovalStatus.PENDING
            )
            self.status = (
                ProductPriceStatus.PENDING_APPROVAL
            )
        else:
            self.approval_status = (
                PriceApprovalStatus.NOT_REQUIRED
            )
            self.status = ProductPriceStatus.APPROVED

        self._record_event(
            "submitted_for_approval",
            actor_id=actor_id,
            details={
                "approval_request_id": approval_request_id,
                "approval_required": self.requires_approval,
            },
        )

    # ========================================================
    # APPROVE PRICE
    # ========================================================

    def approve(
        self,
        *,
        approver_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != (
            ProductPriceStatus.PENDING_APPROVAL
        ):
            raise ValueError(
                "Price is not pending approval"
            )

        if self.approval_status != (
            PriceApprovalStatus.PENDING
        ):
            raise ValueError(
                "Approval request is not pending"
            )

        # Service must validate approver permissions
        # and the linked ApprovalRequest state.

        self.approval_status = (
            PriceApprovalStatus.APPROVED
        )
        self.approved_by = require_text(
            approver_id,
            "Approver ID",
        )
        self.approved_at = utc_now()
        self.status = ProductPriceStatus.APPROVED

        self._record_event(
            "price_approved",
            actor_id=approver_id,
        )

    # ========================================================
    # REJECT PRICE
    # ========================================================

    def reject(
        self,
        *,
        approver_id: str,
        reason: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != (
            ProductPriceStatus.PENDING_APPROVAL
        ):
            raise ValueError(
                "Price is not pending approval"
            )

        self.approval_status = (
            PriceApprovalStatus.REJECTED
        )
        self.rejection_reason = require_text(
            reason,
            "Rejection reason",
        )
        self.status = ProductPriceStatus.REJECTED

        self._record_event(
            "price_rejected",
            actor_id=approver_id,
            details={"reason": reason},
        )

    # ========================================================
    # ACTIVATE PRICE
    # ========================================================

    def activate(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if not self.can_activate:
            raise ValueError(
                "Price is not eligible for activation"
            )

        self._validate_configuration()

        now = utc_now()

        if (
            self.effective_from is not None
            and now < aware_utc(self.effective_from)
        ):
            raise ValueError(
                "Effective start time has not arrived"
            )

        # The service must enforce that only one
        # applicable price wins for a given product,
        # channel, region, customer segment and time.

        self.status = ProductPriceStatus.ACTIVE
        self.activated_at = now

        self._record_event(
            "price_activated",
            actor_id=actor_id,
            details={
                "final_price": str(self.final_price),
                "currency": self.currency,
            },
        )

    # ========================================================
    # SUSPEND PRICE
    # ========================================================

    def suspend(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status not in {
            ProductPriceStatus.ACTIVE,
            ProductPriceStatus.APPROVED,
        }:
            raise ValueError(
                "Price cannot be suspended"
            )

        self.status = ProductPriceStatus.SUSPENDED

        self._record_event(
            "price_suspended",
            actor_id=actor_id,
            details={
                "reason": require_text(
                    reason,
                    "Reason",
                ),
            },
        )

    # ========================================================
    # RESUME SUSPENDED PRICE
    # ========================================================

    def resume(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != ProductPriceStatus.SUSPENDED:
            raise ValueError(
                "Price is not suspended"
            )

        if (
            self.requires_approval
            and self.approval_status
            != PriceApprovalStatus.APPROVED
        ):
            raise ValueError(
                "Approved pricing required"
            )

        if (
            self.effective_until is not None
            and utc_now() >= aware_utc(self.effective_until)
        ):
            raise ValueError(
                "Price has already expired"
            )

        self.status = ProductPriceStatus.APPROVED

        self._record_event(
            "price_resumed_to_approved",
            actor_id=actor_id,
        )

        # Call activate() separately when the
        # effective period begins.

    # ========================================================
    # EXPIRE PRICE
    # ========================================================

    def expire(
        self,
        *,
        actor_id: str | None = None,
    ) -> None:
        self._ensure_not_deleted()

        if self.status not in {
            ProductPriceStatus.ACTIVE,
            ProductPriceStatus.APPROVED,
            ProductPriceStatus.SUSPENDED,
        }:
            raise ValueError(
                "Price cannot be expired from this state"
            )

        if self.effective_until is None:
            raise ValueError(
                "No expiry date is configured"
            )

        if utc_now() < aware_utc(self.effective_until):
            raise ValueError(
                "Expiry date has not arrived"
            )

        self.status = ProductPriceStatus.EXPIRED
        self.expired_at = utc_now()

        self._record_event(
            "price_expired",
            actor_id=actor_id,
        )

    # ========================================================
    # CANCEL PRICE
    # ========================================================

    def cancel(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status not in {
            ProductPriceStatus.DRAFT,
            ProductPriceStatus.PENDING_APPROVAL,
        }:
            raise ValueError(
                "Only draft or pending prices "
                "can be cancelled"
            )

        self.status = ProductPriceStatus.CANCELLED

        self._record_event(
            "price_cancelled",
            actor_id=actor_id,
            details={
                "reason": require_text(
                    reason,
                    "Reason",
                ),
            },
        )

    # ========================================================
    # ARCHIVE PRICE
    # ========================================================

    def archive(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status not in {
            ProductPriceStatus.EXPIRED,
            ProductPriceStatus.CANCELLED,
            ProductPriceStatus.REJECTED,
        }:
            raise ValueError(
                "Only terminal prices can be archived"
            )

        self.status = ProductPriceStatus.ARCHIVED

        self._record_event(
            "price_archived",
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
            ProductPriceStatus.DRAFT,
            ProductPriceStatus.CANCELLED,
            ProductPriceStatus.REJECTED,
            ProductPriceStatus.ARCHIVED,
        }:
            raise ValueError(
                "Price cannot be deleted in this state"
            )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = require_text(
            actor_id,
            "Actor ID",
        )

        self._record_event(
            "price_soft_deleted",
            actor_id=actor_id,
        )

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "price_code": self.price_code,
            "idempotency_key": self.idempotency_key,
            "product_id": self.product_id,
            "sku": self.sku,
            "category_id": self.category_id,
            "supplier_id": self.supplier_id,
            "warehouse_id": self.warehouse_id,
            "customer_segment_id": (
                self.customer_segment_id
            ),
            "sales_channel": self.sales_channel,
            "region_code": self.region_code,
            "name": self.name,
            "description": self.description,
            "status": enum_value(self.status),
            "price_type": enum_value(self.price_type),
            "source": enum_value(self.source),
            "currency": self.currency,
            "base_price": str(self.base_price),
            "cost_price": str(self.cost_price),
            "list_price": decimal_string(
                self.list_price
            ),
            "min_price": decimal_string(
                self.min_price
            ),
            "max_price": decimal_string(
                self.max_price
            ),
            "discount_type": enum_value(
                self.discount_type
            ),
            "discount_value": str(
                self.discount_value
            ),
            "discount_amount": str(
                self.discount_amount
            ),
            "promotion_id": self.promotion_id,
            "coupon_code": self.coupon_code,
            "tax_mode": enum_value(self.tax_mode),
            "tax_rate": str(self.tax_rate),
            "tax_code": self.tax_code,
            "net_price": str(self.net_price),
            "tax_amount": str(self.tax_amount),
            "final_price": str(self.final_price),
            "revenue_excluding_tax": str(
                self.revenue_excluding_tax
            ),
            "gross_profit": str(
                self.gross_profit
            ),
            "gross_margin_percent": str(
                self.gross_margin_percent
            ),
            "markup_percent": str(
                self.markup_percent
            ),
            "effective_from": iso(
                self.effective_from
            ),
            "effective_until": iso(
                self.effective_until
            ),
            "activated_at": iso(
                self.activated_at
            ),
            "expired_at": iso(self.expired_at),
            "is_currently_effective": (
                self.is_currently_effective
            ),
            "competitor_name": (
                self.competitor_name
            ),
            "competitor_price": decimal_string(
                self.competitor_price
            ),
            "competitor_currency": (
                self.competitor_currency
            ),
            "competitor_observed_at": iso(
                self.competitor_observed_at
            ),
            "competitor_source_url": (
                self.competitor_source_url
            ),
            "competitor_prices": (
                self.competitor_prices
            ),
            "competitor_price_difference": (
                decimal_string(
                    self.competitor_price_difference
                )
            ),
            "ai_recommended_price": decimal_string(
                self.ai_recommended_price
            ),
            "ai_confidence_score": decimal_string(
                self.ai_confidence_score
            ),
            "ai_risk_level": enum_value(
                self.ai_risk_level
            ),
            "ai_explanation": (
                self.ai_explanation
            ),
            "ai_model_id": self.ai_model_id,
            "ai_agent_run_id": (
                self.ai_agent_run_id
            ),
            "ai_features": self.ai_features,
            "ai_recommended_at": iso(
                self.ai_recommended_at
            ),
            "pricing_rules": self.pricing_rules,
            "dynamic_pricing_enabled": (
                self.dynamic_pricing_enabled
            ),
            "automatic_activation_enabled": (
                self.automatic_activation_enabled
            ),
            "requires_approval": (
                self.requires_approval
            ),
            "approval_status": enum_value(
                self.approval_status
            ),
            "approval_request_id": (
                self.approval_request_id
            ),
            "approved_by": self.approved_by,
            "approved_at": iso(self.approved_at),
            "rejection_reason": (
                self.rejection_reason
            ),
            "change_reason": enum_value(
                self.change_reason
            ),
            "price_history": self.price_history,
            "external_price_id": (
                self.external_price_id
            ),
            "integration_id": self.integration_id,
            "last_synced_at": iso(
                self.last_synced_at
            ),
            "price_metadata": (
                self.price_metadata
            ),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "trace_id": self.trace_id,
            "correlation_id": (
                self.correlation_id
            ),
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "is_deleted": self.is_deleted,
            "deleted_at": iso(self.deleted_at),
            "deleted_by": self.deleted_by,
            "version": self.version,
        }

    def __repr__(self) -> str:
        return (
            f"<ProductPrice("
            f"id={self.id}, "
            f"product_id={self.product_id}, "
            f"status={enum_value(self.status)}, "
            f"base_price={self.base_price}, "
            f"currency={self.currency}"
            f")>"
        )
