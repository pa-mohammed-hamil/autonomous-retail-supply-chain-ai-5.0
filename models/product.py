from __future__ import annotations

"""Planned module: product. Implementation pending."""

"""
backend/models/product.py

Autonomous Retail Supply Chain AI 5.0
Enterprise Product Master Model

Features:
- Multi-tenant product catalog
- SKU, barcode, GTIN, brand, category
- Supplier and warehouse references
- Product variants and attributes
- Inventory and replenishment settings
- Product pricing references
- AI demand and product intelligence
- Product quality and recall controls
- Approval and publication workflow
- Product lifecycle management
- Audit events and soft deletion
- Optimistic concurrency control

External actions such as publishing products,
updating stock, blocking sales, synchronizing
ERP systems, and recalling products must be
handled by authorized application services.
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

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_product_code() -> str:
    return f"PRD-{uuid.uuid4().hex[:16].upper()}"


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


def positive_decimal(
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
            else f"{field} must be greater than zero"
        )

    if result >= Decimal("100000000000000"):
        raise ValueError(
            f"{field} exceeds supported precision"
        )

    if result != result.quantize(Decimal("0.0001")):
        raise ValueError(
            f"{field} supports at most 4 decimal places"
        )

    return result


def probability(
    value: Decimal | str | int | float,
    field: str,
) -> Decimal:
    result = positive_decimal(value, field)

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

class ProductStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    DISCONTINUED = "discontinued"
    ARCHIVED = "archived"
    REJECTED = "rejected"


class ProductType(str, enum.Enum):
    PHYSICAL = "physical"
    DIGITAL = "digital"
    SERVICE = "service"
    BUNDLE = "bundle"
    KIT = "kit"
    RAW_MATERIAL = "raw_material"
    COMPONENT = "component"
    FINISHED_GOOD = "finished_good"
    CONSUMABLE = "consumable"
    OTHER = "other"


class ProductSource(str, enum.Enum):
    MANUAL = "manual"
    ERP = "erp"
    WMS = "wms"
    POS = "pos"
    ECOMMERCE = "ecommerce"
    SUPPLIER_API = "supplier_api"
    MARKETPLACE = "marketplace"
    AI_AGENT = "ai_agent"
    IMPORT = "import"
    SYSTEM = "system"


class ProductRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class ProductQualityStatus(str, enum.Enum):
    NOT_INSPECTED = "not_inspected"
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    QUARANTINED = "quarantined"
    RECALLED = "recalled"


class ProductApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ProductTrackingType(str, enum.Enum):
    NONE = "none"
    LOT = "lot"
    SERIAL = "serial"
    LOT_AND_SERIAL = "lot_and_serial"


class ProductStorageType(str, enum.Enum):
    AMBIENT = "ambient"
    REFRIGERATED = "refrigerated"
    FROZEN = "frozen"
    HAZARDOUS = "hazardous"
    SECURE = "secure"
    CUSTOM = "custom"


class ProductDemandTrend(str, enum.Enum):
    STRONG_INCREASE = "strong_increase"
    INCREASE = "increase"
    STABLE = "stable"
    DECREASE = "decrease"
    STRONG_DECREASE = "strong_decrease"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"


# ============================================================
# PRODUCT MODEL
# ============================================================

class Product(Base):
    __tablename__ = "products"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "product_code",
            name="uq_product_org_code",
        ),
        UniqueConstraint(
            "organization_id",
            "sku",
            name="uq_product_org_sku",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_product_org_idempotency",
        ),
        CheckConstraint(
            "unit_weight IS NULL OR unit_weight >= 0",
            name="product_weight_nonnegative",
        ),
        CheckConstraint(
            "unit_length IS NULL OR unit_length >= 0",
            name="product_length_nonnegative",
        ),
        CheckConstraint(
            "unit_width IS NULL OR unit_width >= 0",
            name="product_width_nonnegative",
        ),
        CheckConstraint(
            "unit_height IS NULL OR unit_height >= 0",
            name="product_height_nonnegative",
        ),
        CheckConstraint(
            "reorder_point >= 0",
            name="product_reorder_point_nonnegative",
        ),
        CheckConstraint(
            "reorder_quantity >= 0",
            name="product_reorder_quantity_nonnegative",
        ),
        CheckConstraint(
            "safety_stock >= 0",
            name="product_safety_stock_nonnegative",
        ),
        CheckConstraint(
            "min_stock_level >= 0",
            name="product_min_stock_nonnegative",
        ),
        CheckConstraint(
            "max_stock_level IS NULL "
            "OR max_stock_level >= 0",
            name="product_max_stock_nonnegative",
        ),
        CheckConstraint(
            "lead_time_days >= 0",
            name="product_lead_time_nonnegative",
        ),
        CheckConstraint(
            "shelf_life_days IS NULL "
            "OR shelf_life_days >= 0",
            name="product_shelf_life_nonnegative",
        ),
        CheckConstraint(
            "ai_confidence IS NULL OR "
            "(ai_confidence >= 0 AND ai_confidence <= 1)",
            name="product_ai_confidence_range",
        ),
        CheckConstraint(
            "ai_risk_score IS NULL OR "
            "(ai_risk_score >= 0 AND ai_risk_score <= 1)",
            name="product_ai_risk_range",
        ),
        CheckConstraint(
            "version >= 1",
            name="product_version_positive",
        ),
        Index(
            "ix_product_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_product_org_category",
            "organization_id",
            "category_id",
        ),
        Index(
            "ix_product_org_supplier",
            "organization_id",
            "primary_supplier_id",
        ),
        Index(
            "ix_product_org_brand",
            "organization_id",
            "brand",
        ),
        Index(
            "ix_product_org_barcode",
            "organization_id",
            "barcode",
        ),
        Index(
            "ix_product_org_name",
            "organization_id",
            "name",
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

    product_code: Mapped[str] = mapped_column(
        String(50),
        default=generate_product_code,
        nullable=False,
    )

    sku: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # --------------------------------------------------------
    # PRODUCT DETAILS
    # --------------------------------------------------------

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    short_description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    product_type: Mapped[ProductType] = mapped_column(
        enum_column(
            ProductType,
            "product_type",
        ),
        default=ProductType.PHYSICAL,
        nullable=False,
    )

    status: Mapped[ProductStatus] = mapped_column(
        enum_column(
            ProductStatus,
            "product_status",
        ),
        default=ProductStatus.DRAFT,
        nullable=False,
    )

    source: Mapped[ProductSource] = mapped_column(
        enum_column(
            ProductSource,
            "product_source",
        ),
        default=ProductSource.MANUAL,
        nullable=False,
    )

    brand: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    manufacturer: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    model_number: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    barcode: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    gtin: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    hsn_code: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    country_of_origin: Mapped[str | None] = mapped_column(
        String(2),
        nullable=True,
    )

    # --------------------------------------------------------
    # CATEGORY / SUPPLIER
    # --------------------------------------------------------

    category_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    subcategory_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    primary_supplier_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    supplier_product_code: Mapped[
        str | None
    ] = mapped_column(
        String(100),
        nullable=True,
    )

    alternative_supplier_ids: Mapped[
        list[str]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # --------------------------------------------------------
    # VARIANTS / ATTRIBUTES
    # --------------------------------------------------------

    parent_product_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    is_variant: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    attributes: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    variant_options: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    tags: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # --------------------------------------------------------
    # PRODUCT MEDIA
    # --------------------------------------------------------

    image_urls: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    video_urls: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    document_references: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # --------------------------------------------------------
    # UNIT / DIMENSIONS
    # --------------------------------------------------------

    unit_of_measure: Mapped[str] = mapped_column(
        String(30),
        default="units",
        nullable=False,
    )

    unit_weight: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    weight_unit: Mapped[str] = mapped_column(
        String(20),
        default="kg",
        nullable=False,
    )

    unit_length: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    unit_width: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    unit_height: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    dimension_unit: Mapped[str] = mapped_column(
        String(20),
        default="cm",
        nullable=False,
    )

    # --------------------------------------------------------
    # INVENTORY SETTINGS
    # --------------------------------------------------------

    track_inventory: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    tracking_type: Mapped[
        ProductTrackingType
    ] = mapped_column(
        enum_column(
            ProductTrackingType,
            "product_tracking_type",
        ),
        default=ProductTrackingType.NONE,
        nullable=False,
    )

    reorder_point: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    reorder_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    safety_stock: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    min_stock_level: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    max_stock_level: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    lead_time_days: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    preferred_warehouse_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # STORAGE / EXPIRY
    # --------------------------------------------------------

    storage_type: Mapped[
        ProductStorageType
    ] = mapped_column(
        enum_column(
            ProductStorageType,
            "product_storage_type",
        ),
        default=ProductStorageType.AMBIENT,
        nullable=False,
    )

    shelf_life_days: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    is_perishable: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    is_hazardous: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    storage_requirements: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # PRICING REFERENCES
    # --------------------------------------------------------

    currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    default_price_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    pricing_strategy: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    dynamic_pricing_enabled: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # --------------------------------------------------------
    # AI / DEMAND INTELLIGENCE
    # --------------------------------------------------------

    ai_demand_forecast_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
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

    ai_confidence: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    ai_risk_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    ai_risk_level: Mapped[
        ProductRiskLevel
    ] = mapped_column(
        enum_column(
            ProductRiskLevel,
            "product_risk_level",
        ),
        default=ProductRiskLevel.UNKNOWN,
        nullable=False,
    )

    ai_demand_trend: Mapped[
        ProductDemandTrend
    ] = mapped_column(
        enum_column(
            ProductDemandTrend,
            "product_demand_trend",
        ),
        default=ProductDemandTrend.UNKNOWN,
        nullable=False,
    )

    ai_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    ai_recommendations: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
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
    # QUALITY / SAFETY
    # --------------------------------------------------------

    quality_status: Mapped[
        ProductQualityStatus
    ] = mapped_column(
        enum_column(
            ProductQualityStatus,
            "product_quality_status",
        ),
        default=ProductQualityStatus.NOT_INSPECTED,
        nullable=False,
    )

    latest_quality_issue_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    quality_inspection_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    recall_reference: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    sales_blocked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    sales_block_reason: Mapped[
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
        default=True,
        nullable=False,
    )

    approval_status: Mapped[
        ProductApprovalStatus
    ] = mapped_column(
        enum_column(
            ProductApprovalStatus,
            "product_approval_status",
        ),
        default=ProductApprovalStatus.NOT_REQUIRED,
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
    # PUBLICATION
    # --------------------------------------------------------

    published_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    published_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    discontinued_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # EXTERNAL SYSTEMS
    # --------------------------------------------------------

    external_product_id: Mapped[
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
    # HISTORY
    # --------------------------------------------------------

    product_history: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    product_metadata: Mapped[
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
    def is_active(self) -> bool:
        return (
            self.status == ProductStatus.ACTIVE
            and not self.is_deleted
        )

    @property
    def is_sellable(self) -> bool:
        return (
            self.is_active
            and not self.sales_blocked
            and self.quality_status not in {
                ProductQualityStatus.FAILED,
                ProductQualityStatus.QUARANTINED,
                ProductQualityStatus.RECALLED,
            }
        )

    @property
    def is_approved(self) -> bool:
        return (
            not self.requires_approval
            or self.approval_status
            == ProductApprovalStatus.APPROVED
        )

    @property
    def is_discontinued(self) -> bool:
        return self.status == ProductStatus.DISCONTINUED

    @property
    def volume(self) -> Decimal | None:
        dimensions = (
            self.unit_length,
            self.unit_width,
            self.unit_height,
        )

        if any(value is None for value in dimensions):
            return None

        return (
            self.unit_length
            * self.unit_width
            * self.unit_height
        )

    # ========================================================
    # INTERNAL METHODS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_not_deleted(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Product has been deleted"
            )

    def _ensure_draft(self) -> None:
        self._ensure_not_deleted()

        if self.status != ProductStatus.DRAFT:
            raise ValueError(
                "Product must be in draft state"
            )

    def _record_event(
        self,
        event: str,
        *,
        actor_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        history = list(self.product_history or [])

        history.append({
            "event_id": generate_uuid(),
            "event": event,
            "actor_id": actor_id,
            "timestamp": utc_now().isoformat(),
            "details": details or {},
        })

        self.product_history = history
        self._touch()

    # ========================================================
    # UPDATE PRODUCT DETAILS
    # ========================================================

    def update_details(
        self,
        *,
        actor_id: str,
        name: str | None = None,
        description: str | None = None,
        brand: str | None = None,
        manufacturer: str | None = None,
        model_number: str | None = None,
        category_id: str | None = None,
    ) -> None:
        self._ensure_draft()

        if name is not None:
            self.name = require_text(name, "Name")

        if description is not None:
            self.description = description

        if brand is not None:
            self.brand = brand

        if manufacturer is not None:
            self.manufacturer = manufacturer

        if model_number is not None:
            self.model_number = model_number

        if category_id is not None:
            self.category_id = category_id

        self.updated_by = actor_id

        self._record_event(
            "product_details_updated",
            actor_id=actor_id,
        )

    # ========================================================
    # UPDATE INVENTORY SETTINGS
    # ========================================================

    def configure_inventory(
        self,
        *,
        reorder_point: Decimal | str | int | float,
        reorder_quantity: Decimal | str | int | float,
        safety_stock: Decimal | str | int | float,
        min_stock_level: Decimal | str | int | float,
        actor_id: str,
        max_stock_level: (
            Decimal | str | int | float | None
        ) = None,
        lead_time_days: int = 0,
    ) -> None:
        self._ensure_not_deleted()

        if self.status in {
            ProductStatus.DISCONTINUED,
            ProductStatus.ARCHIVED,
            ProductStatus.REJECTED,
        }:
            raise ValueError(
                "Inventory settings cannot be updated"
            )

        reorder = positive_decimal(
            reorder_point,
            "reorder_point",
        )
        quantity = positive_decimal(
            reorder_quantity,
            "reorder_quantity",
        )
        safety = positive_decimal(
            safety_stock,
            "safety_stock",
        )
        minimum = positive_decimal(
            min_stock_level,
            "min_stock_level",
        )

        maximum = (
            positive_decimal(
                max_stock_level,
                "max_stock_level",
            )
            if max_stock_level is not None
            else None
        )

        if maximum is not None:
            if minimum > maximum:
                raise ValueError(
                    "Minimum stock exceeds maximum stock"
                )

            if safety > maximum or reorder > maximum:
                raise ValueError(
                    "Stock thresholds exceed maximum stock"
                )

        if (
            isinstance(lead_time_days, bool)
            or not isinstance(lead_time_days, int)
            or lead_time_days < 0
        ):
            raise ValueError(
                "Lead time must be a nonnegative integer"
            )

        self.reorder_point = reorder
        self.reorder_quantity = quantity
        self.safety_stock = safety
        self.min_stock_level = minimum
        self.max_stock_level = maximum
        self.lead_time_days = lead_time_days
        self.updated_by = actor_id

        self._record_event(
            "inventory_settings_updated",
            actor_id=actor_id,
        )

    # ========================================================
    # UPDATE SUPPLIER
    # ========================================================

    def set_primary_supplier(
        self,
        *,
        supplier_id: str,
        actor_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status in {
            ProductStatus.DISCONTINUED,
            ProductStatus.ARCHIVED,
        }:
            raise ValueError(
                "Supplier cannot be updated"
            )

        self.primary_supplier_id = require_text(
            supplier_id,
            "Supplier ID",
        )

        self.updated_by = actor_id

        self._record_event(
            "primary_supplier_updated",
            actor_id=actor_id,
            details={"supplier_id": supplier_id},
        )

    # ========================================================
    # ADD ALTERNATIVE SUPPLIER
    # ========================================================

    def add_alternative_supplier(
        self,
        *,
        supplier_id: str,
        actor_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status in {
            ProductStatus.DISCONTINUED,
            ProductStatus.ARCHIVED,
        }:
            raise ValueError(
                "Alternative suppliers cannot be updated"
            )

        supplier_id = require_text(
            supplier_id,
            "Supplier ID",
        )

        if supplier_id == self.primary_supplier_id:
            raise ValueError(
                "Supplier is already primary"
            )

        suppliers = list(
            self.alternative_supplier_ids or []
        )

        if supplier_id in suppliers:
            raise ValueError(
                "Supplier already exists"
            )

        suppliers.append(supplier_id)
        self.alternative_supplier_ids = suppliers

        self._record_event(
            "alternative_supplier_added",
            actor_id=actor_id,
            details={"supplier_id": supplier_id},
        )

    # ========================================================
    # UPDATE AI INTELLIGENCE
    # ========================================================

    def update_ai_intelligence(
        self,
        *,
        model_id: str,
        confidence: Decimal | str | int | float,
        risk_score: Decimal | str | int | float,
        risk_level: ProductRiskLevel,
        demand_trend: ProductDemandTrend,
        summary: str,
        recommendations: list[dict[str, Any]],
        agent_run_id: str | None = None,
        features: dict[str, Any] | None = None,
    ) -> None:
        self._ensure_not_deleted()

        self.ai_model_id = require_text(
            model_id,
            "Model ID",
        )
        self.ai_agent_run_id = agent_run_id

        self.ai_confidence = probability(
            confidence,
            "confidence",
        )
        self.ai_risk_score = probability(
            risk_score,
            "risk_score",
        )
        self.ai_risk_level = risk_level
        self.ai_demand_trend = demand_trend
        self.ai_summary = require_text(
            summary,
            "AI summary",
        )
        self.ai_recommendations = [
            dict(item) for item in recommendations
        ]
        self.ai_features = dict(features or {})
        self.ai_analyzed_at = utc_now()

        self._record_event(
            "ai_intelligence_updated",
            details={
                "model_id": model_id,
                "risk_level": risk_level.value,
                "demand_trend": demand_trend.value,
            },
        )

    # ========================================================
    # UPDATE QUALITY STATUS
    # ========================================================

    def update_quality_status(
        self,
        *,
        quality_status: ProductQualityStatus,
        actor_id: str,
        quality_issue_id: str | None = None,
        inspection_id: str | None = None,
    ) -> None:
        self._ensure_not_deleted()

        self.quality_status = quality_status

        if quality_issue_id is not None:
            self.latest_quality_issue_id = quality_issue_id

        if inspection_id is not None:
            self.quality_inspection_id = inspection_id

        if quality_status in {
            ProductQualityStatus.FAILED,
            ProductQualityStatus.QUARANTINED,
            ProductQualityStatus.RECALLED,
        }:
            self.sales_blocked = True
            self.sales_block_reason = (
                f"Quality status: {quality_status.value}"
            )

        self._record_event(
            "quality_status_updated",
            actor_id=actor_id,
            details={
                "quality_status": quality_status.value,
                "quality_issue_id": quality_issue_id,
            },
        )

    # ========================================================
    # BLOCK SALES
    # ========================================================

    def block_sales(
        self,
        *,
        reason: str,
        actor_id: str,
    ) -> None:
        self._ensure_not_deleted()

        self.sales_blocked = True
        self.sales_block_reason = require_text(
            reason,
            "Sales block reason",
        )

        self._record_event(
            "sales_blocked",
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # UNBLOCK SALES
    # ========================================================

    def unblock_sales(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.quality_status in {
            ProductQualityStatus.FAILED,
            ProductQualityStatus.QUARANTINED,
            ProductQualityStatus.RECALLED,
        }:
            raise ValueError(
                "Product quality status prevents sales"
            )

        if self.status != ProductStatus.ACTIVE:
            raise ValueError(
                "Only active products can be unblocked"
            )

        # The service must check all outstanding
        # recalls, incidents and quality holds.

        self.sales_blocked = False
        self.sales_block_reason = None

        self._record_event(
            "sales_unblocked",
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
        self._ensure_draft()

        require_text(self.name, "Product name")
        require_text(self.sku, "SKU")

        if self.requires_approval:
            self.approval_request_id = require_text(
                approval_request_id,
                "Approval request ID",
            )
            self.approval_status = (
                ProductApprovalStatus.PENDING
            )
            self.status = (
                ProductStatus.PENDING_APPROVAL
            )
        else:
            self.approval_status = (
                ProductApprovalStatus.NOT_REQUIRED
            )
            self.status = ProductStatus.APPROVED

        self._record_event(
            "product_approval_requested",
            actor_id=actor_id,
        )

    # ========================================================
    # APPROVE PRODUCT
    # ========================================================

    def approve(
        self,
        *,
        approver_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != (
            ProductStatus.PENDING_APPROVAL
        ):
            raise ValueError(
                "Product is not pending approval"
            )

        if self.approval_status != (
            ProductApprovalStatus.PENDING
        ):
            raise ValueError(
                "Approval is not pending"
            )

        # The service must verify approval authority
        # and the linked ApprovalRequest state.

        self.approval_status = (
            ProductApprovalStatus.APPROVED
        )
        self.approved_by = require_text(
            approver_id,
            "Approver ID",
        )
        self.approved_at = utc_now()
        self.status = ProductStatus.APPROVED

        self._record_event(
            "product_approved",
            actor_id=approver_id,
        )

    # ========================================================
    # REJECT PRODUCT
    # ========================================================

    def reject(
        self,
        *,
        approver_id: str,
        reason: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != (
            ProductStatus.PENDING_APPROVAL
        ):
            raise ValueError(
                "Product is not pending approval"
            )

        self.approval_status = (
            ProductApprovalStatus.REJECTED
        )
        self.rejection_reason = require_text(
            reason,
            "Rejection reason",
        )
        self.status = ProductStatus.REJECTED

        self._record_event(
            "product_rejected",
            actor_id=approver_id,
            details={"reason": reason},
        )

    # ========================================================
    # ACTIVATE PRODUCT
    # ========================================================

    def activate(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status not in {
            ProductStatus.APPROVED,
            ProductStatus.INACTIVE,
        }:
            raise ValueError(
                "Product cannot be activated"
            )

        if not self.is_approved:
            raise ValueError(
                "Product requires approval"
            )

        if self.quality_status in {
            ProductQualityStatus.FAILED,
            ProductQualityStatus.QUARANTINED,
            ProductQualityStatus.RECALLED,
        }:
            raise ValueError(
                "Quality hold prevents activation"
            )

        self.status = ProductStatus.ACTIVE
        self.published_at = utc_now()
        self.published_by = actor_id

        self._record_event(
            "product_activated",
            actor_id=actor_id,
        )

    # ========================================================
    # DEACTIVATE PRODUCT
    # ========================================================

    def deactivate(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != ProductStatus.ACTIVE:
            raise ValueError(
                "Product is not active"
            )

        self.status = ProductStatus.INACTIVE

        self._record_event(
            "product_deactivated",
            actor_id=actor_id,
            details={
                "reason": require_text(
                    reason,
                    "Reason",
                ),
            },
        )

    # ========================================================
    # SUSPEND PRODUCT
    # ========================================================

    def suspend(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status not in {
            ProductStatus.ACTIVE,
            ProductStatus.INACTIVE,
        }:
            raise ValueError(
                "Product cannot be suspended"
            )

        self.status = ProductStatus.SUSPENDED
        self.sales_blocked = True
        self.sales_block_reason = require_text(
            reason,
            "Suspension reason",
        )

        self._record_event(
            "product_suspended",
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # DISCONTINUE PRODUCT
    # ========================================================

    def discontinue(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status in {
            ProductStatus.ARCHIVED,
            ProductStatus.DISCONTINUED,
        }:
            raise ValueError(
                "Product is already terminal"
            )

        self.status = ProductStatus.DISCONTINUED
        self.discontinued_at = utc_now()
        self.sales_blocked = True
        self.sales_block_reason = (
            f"Discontinued: "
            f"{require_text(reason, 'Reason')}"
        )

        self._record_event(
            "product_discontinued",
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # ARCHIVE PRODUCT
    # ========================================================

    def archive(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status not in {
            ProductStatus.DISCONTINUED,
            ProductStatus.REJECTED,
        }:
            raise ValueError(
                "Product must be discontinued or rejected"
            )

        self.status = ProductStatus.ARCHIVED

        self._record_event(
            "product_archived",
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
            ProductStatus.DRAFT,
            ProductStatus.REJECTED,
            ProductStatus.ARCHIVED,
        }:
            raise ValueError(
                "Product cannot be deleted in current state"
            )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = require_text(
            actor_id,
            "Actor ID",
        )

        self._record_event(
            "product_soft_deleted",
            actor_id=actor_id,
        )

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "product_code": self.product_code,
            "sku": self.sku,
            "idempotency_key": self.idempotency_key,

            "name": self.name,
            "description": self.description,
            "short_description": self.short_description,
            "product_type": enum_value(
                self.product_type
            ),
            "status": enum_value(self.status),
            "source": enum_value(self.source),
            "brand": self.brand,
            "manufacturer": self.manufacturer,
            "model_number": self.model_number,
            "barcode": self.barcode,
            "gtin": self.gtin,
            "hsn_code": self.hsn_code,
            "country_of_origin": self.country_of_origin,

            "category_id": self.category_id,
            "subcategory_id": self.subcategory_id,
            "primary_supplier_id": (
                self.primary_supplier_id
            ),
            "supplier_product_code": (
                self.supplier_product_code
            ),
            "alternative_supplier_ids": (
                self.alternative_supplier_ids
            ),

            "parent_product_id": self.parent_product_id,
            "is_variant": self.is_variant,
            "attributes": self.attributes,
            "variant_options": self.variant_options,
            "tags": self.tags,

            "image_urls": self.image_urls,
            "video_urls": self.video_urls,
            "document_references": (
                self.document_references
            ),

            "unit_of_measure": self.unit_of_measure,
            "unit_weight": decimal_string(
                self.unit_weight
            ),
            "weight_unit": self.weight_unit,
            "unit_length": decimal_string(
                self.unit_length
            ),
            "unit_width": decimal_string(
                self.unit_width
            ),
            "unit_height": decimal_string(
                self.unit_height
            ),
            "dimension_unit": self.dimension_unit,
            "volume": decimal_string(self.volume),

            "track_inventory": self.track_inventory,
            "tracking_type": enum_value(
                self.tracking_type
            ),
            "reorder_point": str(self.reorder_point),
            "reorder_quantity": str(
                self.reorder_quantity
            ),
            "safety_stock": str(self.safety_stock),
            "min_stock_level": str(
                self.min_stock_level
            ),
            "max_stock_level": decimal_string(
                self.max_stock_level
            ),
            "lead_time_days": self.lead_time_days,
            "preferred_warehouse_id": (
                self.preferred_warehouse_id
            ),

            "storage_type": enum_value(
                self.storage_type
            ),
            "shelf_life_days": self.shelf_life_days,
            "is_perishable": self.is_perishable,
            "is_hazardous": self.is_hazardous,
            "storage_requirements": (
                self.storage_requirements
            ),

            "currency": self.currency,
            "default_price_id": self.default_price_id,
            "pricing_strategy": self.pricing_strategy,
            "dynamic_pricing_enabled": (
                self.dynamic_pricing_enabled
            ),

            "ai_demand_forecast_id": (
                self.ai_demand_forecast_id
            ),
            "ai_model_id": self.ai_model_id,
            "ai_agent_run_id": self.ai_agent_run_id,
            "ai_confidence": decimal_string(
                self.ai_confidence
            ),
            "ai_risk_score": decimal_string(
                self.ai_risk_score
            ),
            "ai_risk_level": enum_value(
                self.ai_risk_level
            ),
            "ai_demand_trend": enum_value(
                self.ai_demand_trend
            ),
            "ai_summary": self.ai_summary,
            "ai_recommendations": (
                self.ai_recommendations
            ),
            "ai_features": self.ai_features,
            "ai_analyzed_at": iso(
                self.ai_analyzed_at
            ),

            "quality_status": enum_value(
                self.quality_status
            ),
            "latest_quality_issue_id": (
                self.latest_quality_issue_id
            ),
            "quality_inspection_id": (
                self.quality_inspection_id
            ),
            "recall_reference": self.recall_reference,
            "sales_blocked": self.sales_blocked,
            "sales_block_reason": (
                self.sales_block_reason
            ),

            "requires_approval": self.requires_approval,
            "approval_status": enum_value(
                self.approval_status
            ),
            "approval_request_id": (
                self.approval_request_id
            ),
            "approved_by": self.approved_by,
            "approved_at": iso(self.approved_at),
            "rejection_reason": self.rejection_reason,

            "published_at": iso(self.published_at),
            "published_by": self.published_by,
            "discontinued_at": iso(
                self.discontinued_at
            ),

            "external_product_id": (
                self.external_product_id
            ),
            "integration_id": self.integration_id,
            "last_synced_at": iso(
                self.last_synced_at
            ),

            "product_history": self.product_history,
            "product_metadata": self.product_metadata,

            "is_active": self.is_active,
            "is_sellable": self.is_sellable,
            "is_approved": self.is_approved,
            "is_discontinued": self.is_discontinued,

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

    def __repr__(self) -> str:
        return (
            f"<Product("
            f"id={self.id}, "
            f"sku={self.sku}, "
            f"name={self.name}, "
            f"status={enum_value(self.status)}"
            f")>"
        )
