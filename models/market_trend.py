from __future__ import annotations


"""
backend/models/market_trend.py

Autonomous Retail Supply Chain AI 5.0
Market Trend Intelligence ORM Model

Features:
- Multi-tenant market trend records
- Product, category, supplier and region analysis
- Competitor pricing and market signals
- Demand, sales and seasonal trend detection
- Economic and consumer behavior indicators
- AI/ML trend predictions and confidence
- Market opportunities and risk assessment
- Replenishment and pricing recommendations
- Human approval for consequential actions
- Data freshness and source tracking
- Trend lifecycle management
- Audit metadata and soft deletion
- Optimistic concurrency control

Requirements:
    Python >= 3.10
    SQLAlchemy >= 2.0

Shared ORM:
    backend.models.base.Base

Important:
    This module stores market intelligence results.
    Actual data collection, model inference, pricing
    changes and procurement belong in services.
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


def generate_trend_code() -> str:
    return f"MKT-{uuid.uuid4().hex[:16].upper()}"


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
    allow_negative: bool = False,
) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Invalid decimal value") from None

    if not result.is_finite():
        raise ValueError("Decimal value must be finite")

    if not allow_negative and result < 0:
        raise ValueError("Decimal value cannot be negative")

    if result.as_tuple().exponent < -4:
        raise ValueError(
            "Maximum supported precision is 4 decimal places"
        )

    return result


def validate_score(
    value: float,
    name: str,
) -> float:
    result = float(value)

    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError(
            f"{name} must be between 0 and 1"
        )

    return result


def validate_finite(
    value: float,
    name: str,
) -> float:
    result = float(value)

    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")

    return result


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def datetime_string(
    value: datetime | None,
) -> str | None:
    return value.isoformat() if value else None


def decimal_string(
    value: Decimal | None,
) -> str | None:
    return str(value) if value is not None else None


# ============================================================
# ENUMS
# ============================================================

class MarketTrendType(str, enum.Enum):
    DEMAND = "demand"
    SALES = "sales"
    PRICING = "pricing"
    COMPETITOR_PRICING = "competitor_pricing"
    CONSUMER_BEHAVIOR = "consumer_behavior"
    SEASONALITY = "seasonality"
    PRODUCT_POPULARITY = "product_popularity"
    CATEGORY_GROWTH = "category_growth"
    SUPPLIER_MARKET = "supplier_market"
    ECONOMIC = "economic"
    INFLATION = "inflation"
    PROMOTION = "promotion"
    MARKET_SHARE = "market_share"
    INVENTORY = "inventory"
    SUPPLY_CHAIN = "supply_chain"
    LOGISTICS = "logistics"
    WEATHER_IMPACT = "weather_impact"
    SOCIAL_SENTIMENT = "social_sentiment"
    EMERGING_TREND = "emerging_trend"
    OTHER = "other"


class MarketTrendDirection(str, enum.Enum):
    STRONG_INCREASE = "strong_increase"
    INCREASE = "increase"
    STABLE = "stable"
    DECREASE = "decrease"
    STRONG_DECREASE = "strong_decrease"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"


class MarketTrendStatus(str, enum.Enum):
    DETECTED = "detected"
    ANALYZING = "analyzing"
    VALIDATED = "validated"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    PUBLISHED = "published"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class MarketTrendSource(str, enum.Enum):
    INTERNAL_SALES = "internal_sales"
    POS = "pos"
    ERP = "erp"
    WMS = "wms"
    MARKET_DATA_API = "market_data_api"
    COMPETITOR_API = "competitor_api"
    ECOMMERCE = "ecommerce"
    SUPPLIER_API = "supplier_api"
    SOCIAL_MEDIA = "social_media"
    SEARCH_TRENDS = "search_trends"
    WEATHER_API = "weather_api"
    ECONOMIC_DATA = "economic_data"
    CUSTOMER_FEEDBACK = "customer_feedback"
    AI_AGENT = "ai_agent"
    ML_MODEL = "ml_model"
    MANUAL = "manual"
    OTHER = "other"


class MarketTrendRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class MarketTrendImpact(str, enum.Enum):
    VERY_LOW = "very_low"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    VERY_HIGH = "very_high"
    UNKNOWN = "unknown"


class MarketTrendTimeHorizon(str, enum.Enum):
    REAL_TIME = "real_time"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
    CUSTOM = "custom"


class MarketTrendRecommendationType(str, enum.Enum):
    INCREASE_INVENTORY = "increase_inventory"
    REDUCE_INVENTORY = "reduce_inventory"
    REPLENISH_STOCK = "replenish_stock"
    ADJUST_PRICE = "adjust_price"
    LAUNCH_PROMOTION = "launch_promotion"
    REVIEW_SUPPLIER = "review_supplier"
    CHANGE_SUPPLIER = "change_supplier"
    OPTIMIZE_LOGISTICS = "optimize_logistics"
    EXPAND_MARKET = "expand_market"
    REDUCE_EXPOSURE = "reduce_exposure"
    MONITOR = "monitor"
    NO_ACTION = "no_action"


# ============================================================
# MARKET TREND MODEL
# ============================================================

class MarketTrend(Base):
    __tablename__ = "market_trends"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "trend_code",
            name="uq_market_trend_org_code",
        ),
        CheckConstraint(
            "current_value IS NULL OR current_value >= 0",
            name="market_trend_current_nonnegative",
        ),
        CheckConstraint(
            "previous_value IS NULL OR previous_value >= 0",
            name="market_trend_previous_nonnegative",
        ),
        CheckConstraint(
            "predicted_value IS NULL OR predicted_value >= 0",
            name="market_trend_predicted_nonnegative",
        ),
        CheckConstraint(
            "competitor_price IS NULL OR competitor_price >= 0",
            name="market_trend_competitor_price_nonnegative",
        ),
        CheckConstraint(
            "our_price IS NULL OR our_price >= 0",
            name="market_trend_our_price_nonnegative",
        ),
        CheckConstraint(
            "market_size IS NULL OR market_size >= 0",
            name="market_trend_market_size_nonnegative",
        ),
        CheckConstraint(
            "confidence_score IS NULL OR "
            "(confidence_score >= 0 AND confidence_score <= 1)",
            name="market_trend_confidence_range",
        ),
        CheckConstraint(
            "risk_score IS NULL OR "
            "(risk_score >= 0 AND risk_score <= 1)",
            name="market_trend_risk_range",
        ),
        CheckConstraint(
            "opportunity_score IS NULL OR "
            "(opportunity_score >= 0 AND opportunity_score <= 1)",
            name="market_trend_opportunity_range",
        ),
        CheckConstraint(
            "anomaly_score IS NULL OR "
            "(anomaly_score >= 0 AND anomaly_score <= 1)",
            name="market_trend_anomaly_range",
        ),
        CheckConstraint(
            "data_quality_score IS NULL OR "
            "(data_quality_score >= 0 AND data_quality_score <= 1)",
            name="market_trend_data_quality_range",
        ),
        CheckConstraint(
            "sample_size >= 0",
            name="market_trend_sample_size_nonnegative",
        ),
        CheckConstraint(
            "forecast_horizon_days >= 0",
            name="market_trend_horizon_nonnegative",
        ),
        CheckConstraint(
            "observation_end_at IS NULL OR "
            "observation_start_at IS NULL OR "
            "observation_end_at >= observation_start_at",
            name="market_trend_observation_range",
        ),
        Index(
            "ix_market_trend_org_type",
            "organization_id",
            "trend_type",
        ),
        Index(
            "ix_market_trend_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_market_trend_org_product",
            "organization_id",
            "product_id",
        ),
        Index(
            "ix_market_trend_org_category",
            "organization_id",
            "category_id",
        ),
        Index(
            "ix_market_trend_org_region",
            "organization_id",
            "region_code",
        ),
        Index(
            "ix_market_trend_org_observed",
            "organization_id",
            "observed_at",
        ),
        Index(
            "ix_market_trend_org_risk",
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

    trend_code: Mapped[str] = mapped_column(
        String(40),
        default=generate_trend_code,
        nullable=False,
    )

    # --------------------------------------------------------
    # GENERAL INFORMATION
    # --------------------------------------------------------

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    trend_type: Mapped[MarketTrendType] = mapped_column(
        enum_column(
            MarketTrendType,
            "market_trend_type",
        ),
        nullable=False,
    )

    direction: Mapped[
        MarketTrendDirection
    ] = mapped_column(
        enum_column(
            MarketTrendDirection,
            "market_trend_direction",
        ),
        default=MarketTrendDirection.UNKNOWN,
        nullable=False,
    )

    status: Mapped[MarketTrendStatus] = mapped_column(
        enum_column(
            MarketTrendStatus,
            "market_trend_status",
        ),
        default=MarketTrendStatus.DETECTED,
        nullable=False,
    )

    source: Mapped[MarketTrendSource] = mapped_column(
        enum_column(
            MarketTrendSource,
            "market_trend_source",
        ),
        default=MarketTrendSource.ML_MODEL,
        nullable=False,
    )

    # --------------------------------------------------------
    # BUSINESS ENTITY REFERENCES
    # --------------------------------------------------------

    product_id: Mapped[str | None] = mapped_column(
        String(36),
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

    competitor_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    competitor_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # --------------------------------------------------------
    # MARKET SEGMENT AND LOCATION
    # --------------------------------------------------------

    country_code: Mapped[str | None] = mapped_column(
        String(2),
        nullable=True,
    )

    region_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    city: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    market_segment: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    sales_channel: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # --------------------------------------------------------
    # TIME WINDOW
    # --------------------------------------------------------

    time_horizon: Mapped[
        MarketTrendTimeHorizon
    ] = mapped_column(
        enum_column(
            MarketTrendTimeHorizon,
            "market_trend_time_horizon",
        ),
        default=MarketTrendTimeHorizon.WEEKLY,
        nullable=False,
    )

    observation_start_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    observation_end_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    forecast_horizon_days: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # --------------------------------------------------------
    # MARKET METRICS
    # --------------------------------------------------------

    metric_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    metric_unit: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    current_value: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 4),
        nullable=True,
    )

    previous_value: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 4),
        nullable=True,
    )

    predicted_value: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 4),
        nullable=True,
    )

    change_percentage: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    growth_rate_percentage: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    market_share_percentage: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    market_size: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 4),
        nullable=True,
    )

    # --------------------------------------------------------
    # COMPETITOR PRICING
    # --------------------------------------------------------

    currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    our_price: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    competitor_price: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    competitor_price_change_percentage: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    # --------------------------------------------------------
    # SEASONALITY AND EXTERNAL INDICATORS
    # --------------------------------------------------------

    is_seasonal: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    seasonal_period: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    consumer_sentiment_score: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    inflation_rate_percentage: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    economic_indicators: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # AI / ML INTELLIGENCE
    # --------------------------------------------------------

    model_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    model_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    confidence_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    anomaly_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    opportunity_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    risk_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    risk_level: Mapped[
        MarketTrendRiskLevel
    ] = mapped_column(
        enum_column(
            MarketTrendRiskLevel,
            "market_trend_risk_level",
        ),
        default=MarketTrendRiskLevel.UNKNOWN,
        nullable=False,
    )

    impact_level: Mapped[MarketTrendImpact] = mapped_column(
        enum_column(
            MarketTrendImpact,
            "market_trend_impact",
        ),
        default=MarketTrendImpact.UNKNOWN,
        nullable=False,
    )

    ai_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    ai_explanation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    predicted_drivers: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # --------------------------------------------------------
    # BUSINESS RECOMMENDATIONS
    # --------------------------------------------------------

    recommendation_type: Mapped[
        MarketTrendRecommendationType | None
    ] = mapped_column(
        enum_column(
            MarketTrendRecommendationType,
            "market_trend_recommendation_type",
        ),
        nullable=True,
    )

    recommended_action: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    recommended_price: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    recommended_stock_quantity: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    expected_business_impact: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # DATA SOURCE AND QUALITY
    # --------------------------------------------------------

    integration_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    source_reference: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    source_url: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )

    sample_size: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    data_quality_score: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    last_data_refresh_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    data_expires_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # AI AGENT REFERENCES
    # --------------------------------------------------------

    agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    agent_action_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    demand_forecast_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # HUMAN APPROVAL
    # --------------------------------------------------------

    requires_human_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
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

    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    rejected_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    rejected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    rejection_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # METADATA
    # --------------------------------------------------------

    market_data: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    trend_metadata: Mapped[
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
    def is_terminal(self) -> bool:
        return self.status in {
            MarketTrendStatus.REJECTED,
            MarketTrendStatus.SUPERSEDED,
            MarketTrendStatus.ARCHIVED,
        }

    @property
    def is_published(self) -> bool:
        return (
            self.status == MarketTrendStatus.PUBLISHED
            and not self.is_deleted
        )

    @property
    def is_stale(self) -> bool:
        return (
            self.data_expires_at is not None
            and as_utc(self.data_expires_at) <= utc_now()
        )

    @property
    def is_high_risk(self) -> bool:
        return self.risk_level in {
            MarketTrendRiskLevel.HIGH,
            MarketTrendRiskLevel.CRITICAL,
        }

    @property
    def is_opportunity(self) -> bool:
        return (
            self.opportunity_score is not None
            and self.opportunity_score >= 0.7
        )

    @property
    def price_gap_percentage(self) -> float | None:
        if (
            self.our_price is None
            or self.competitor_price is None
            or self.competitor_price == 0
        ):
            return None

        return float(
            (
                self.our_price - self.competitor_price
            )
            / self.competitor_price
            * Decimal("100")
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_editable(self) -> None:
        if self.is_deleted:
            raise ValueError("Market trend is deleted")

        if self.status in {
            MarketTrendStatus.PUBLISHED,
            MarketTrendStatus.REJECTED,
            MarketTrendStatus.SUPERSEDED,
            MarketTrendStatus.ARCHIVED,
        }:
            raise ValueError(
                "Market trend is no longer editable"
            )

    def _invalidate_approval(self) -> None:
        self.approved_by = None
        self.approved_at = None
        self.approval_request_id = None

    # ========================================================
    # START ANALYSIS
    # ========================================================

    def start_analysis(self) -> None:
        self._ensure_editable()

        if self.status != MarketTrendStatus.DETECTED:
            raise ValueError(
                "Only detected trends can start analysis"
            )

        self.status = MarketTrendStatus.ANALYZING
        self._touch()

    # ========================================================
    # UPDATE OBSERVED METRICS
    # ========================================================

    def update_metrics(
        self,
        *,
        current_value: Decimal | int | float,
        previous_value: Decimal | int | float,
        metric_name: str,
        metric_unit: str,
    ) -> None:
        self._ensure_editable()

        if self.status not in {
            MarketTrendStatus.DETECTED,
            MarketTrendStatus.ANALYZING,
            MarketTrendStatus.VALIDATED,
        }:
            raise ValueError(
                "Metrics cannot be changed in current state"
            )

        if not metric_name.strip() or not metric_unit.strip():
            raise ValueError(
                "Metric name and unit are required"
            )

        current = to_decimal(current_value)
        previous = to_decimal(previous_value)

        self.current_value = current
        self.previous_value = previous
        self.metric_name = metric_name
        self.metric_unit = metric_unit

        if previous > 0:
            change = (
                (current - previous)
                / previous
                * Decimal("100")
            )
            self.change_percentage = float(change)
        else:
            # A zero baseline has no defined percentage change.
            self.change_percentage = None

        if current > previous:
            self.direction = MarketTrendDirection.INCREASE
        elif current < previous:
            self.direction = MarketTrendDirection.DECREASE
        else:
            self.direction = MarketTrendDirection.STABLE

        self._invalidate_approval()
        self.status = MarketTrendStatus.ANALYZING
        self._touch()

    # ========================================================
    # UPDATE COMPETITOR PRICING
    # ========================================================

    def update_competitor_pricing(
        self,
        *,
        our_price: Decimal | int | float,
        competitor_price: Decimal | int | float,
        competitor_name: str,
    ) -> None:
        self._ensure_editable()

        if self.status not in {
            MarketTrendStatus.DETECTED,
            MarketTrendStatus.ANALYZING,
            MarketTrendStatus.VALIDATED,
        }:
            raise ValueError(
                "Pricing cannot be changed in current state"
            )

        if not competitor_name.strip():
            raise ValueError(
                "Competitor name is required"
            )

        self.our_price = to_decimal(our_price)
        self.competitor_price = to_decimal(competitor_price)
        self.competitor_name = competitor_name

        self._invalidate_approval()
        self.status = MarketTrendStatus.ANALYZING
        self._touch()

    # ========================================================
    # UPDATE AI PREDICTION
    # ========================================================

    def update_ai_prediction(
        self,
        *,
        predicted_value: Decimal | int | float,
        confidence_score: float,
        anomaly_score: float,
        opportunity_score: float,
        risk_score: float,
        risk_level: MarketTrendRiskLevel,
        impact_level: MarketTrendImpact,
        model_name: str,
        summary: str,
        explanation: str,
        predicted_drivers: list[dict[str, Any]] | None = None,
    ) -> None:
        self._ensure_editable()

        if self.status not in {
            MarketTrendStatus.DETECTED,
            MarketTrendStatus.ANALYZING,
            MarketTrendStatus.VALIDATED,
        }:
            raise ValueError(
                "AI prediction cannot be changed now"
            )

        if not model_name.strip():
            raise ValueError("Model name is required")

        self.predicted_value = to_decimal(predicted_value)
        self.confidence_score = validate_score(
            confidence_score,
            "confidence_score",
        )
        self.anomaly_score = validate_score(
            anomaly_score,
            "anomaly_score",
        )
        self.opportunity_score = validate_score(
            opportunity_score,
            "opportunity_score",
        )
        self.risk_score = validate_score(
            risk_score,
            "risk_score",
        )

        self.risk_level = risk_level
        self.impact_level = impact_level
        self.model_name = model_name
        self.ai_summary = summary
        self.ai_explanation = explanation
        self.predicted_drivers = list(
            predicted_drivers or []
        )

        self._invalidate_approval()
        self.status = MarketTrendStatus.ANALYZING
        self._touch()

    # ========================================================
    # UPDATE RECOMMENDATION
    # ========================================================

    def update_recommendation(
        self,
        *,
        recommendation_type: MarketTrendRecommendationType,
        action: str,
        expected_impact: str | None = None,
        recommended_price: Decimal | int | float | None = None,
        recommended_stock_quantity: (
            Decimal | int | float | None
        ) = None,
    ) -> None:
        self._ensure_editable()

        if self.status not in {
            MarketTrendStatus.DETECTED,
            MarketTrendStatus.ANALYZING,
            MarketTrendStatus.VALIDATED,
        }:
            raise ValueError(
                "Recommendation cannot be changed now"
            )

        if not action.strip():
            raise ValueError(
                "Recommended action is required"
            )

        self.recommendation_type = recommendation_type
        self.recommended_action = action
        self.expected_business_impact = expected_impact

        self.recommended_price = (
            to_decimal(recommended_price)
            if recommended_price is not None
            else None
        )

        self.recommended_stock_quantity = (
            to_decimal(recommended_stock_quantity)
            if recommended_stock_quantity is not None
            else None
        )

        self._invalidate_approval()
        self.status = MarketTrendStatus.ANALYZING
        self._touch()

    # ========================================================
    # VALIDATE TREND
    # ========================================================

    def validate(self) -> None:
        self._ensure_editable()

        if self.status not in {
            MarketTrendStatus.ANALYZING,
            MarketTrendStatus.DETECTED,
        }:
            raise ValueError(
                "Trend cannot be validated in current state"
            )

        if self.current_value is None:
            raise ValueError(
                "Current market metric is required"
            )

        if not self.metric_name:
            raise ValueError(
                "Metric name is required"
            )

        if self.is_stale:
            raise ValueError(
                "Market data has expired"
            )

        self.status = MarketTrendStatus.VALIDATED
        self._touch()

    # ========================================================
    # REQUEST HUMAN APPROVAL
    # ========================================================

    def request_approval(
        self,
        approval_request_id: str,
    ) -> None:
        self._ensure_editable()

        if self.status != MarketTrendStatus.VALIDATED:
            raise ValueError(
                "Trend must be validated first"
            )

        if not approval_request_id:
            raise ValueError(
                "Approval request ID is required"
            )

        self.approval_request_id = approval_request_id
        self.approved_by = None
        self.approved_at = None
        self.status = MarketTrendStatus.PENDING_APPROVAL
        self._touch()

    # ========================================================
    # APPROVE TREND
    # ========================================================

    def approve(self, user_id: str) -> None:
        self._ensure_editable()

        if self.status != (
            MarketTrendStatus.PENDING_APPROVAL
        ):
            raise ValueError(
                "Trend is not pending approval"
            )

        if not user_id:
            raise ValueError(
                "Approver ID is required"
            )

        # Verify the linked approval request, tenant,
        # approver permissions and record version in
        # the service before calling this method.
        self.approved_by = user_id
        self.approved_at = utc_now()
        self.status = MarketTrendStatus.APPROVED
        self._touch()

    # ========================================================
    # REJECT TREND
    # ========================================================

    def reject(
        self,
        *,
        user_id: str,
        reason: str,
    ) -> None:
        self._ensure_editable()

        if self.status != (
            MarketTrendStatus.PENDING_APPROVAL
        ):
            raise ValueError(
                "Trend is not pending approval"
            )

        if not user_id or not reason.strip():
            raise ValueError(
                "User ID and rejection reason required"
            )

        self.rejected_by = user_id
        self.rejected_at = utc_now()
        self.rejection_reason = reason
        self.status = MarketTrendStatus.REJECTED
        self._touch()

    # ========================================================
    # PUBLISH TREND
    # ========================================================

    def publish(self) -> None:
        self._ensure_editable()

        if self.requires_human_approval:
            if self.status != MarketTrendStatus.APPROVED:
                raise ValueError(
                    "Verified approval is required"
                )
        elif self.status not in {
            MarketTrendStatus.VALIDATED,
            MarketTrendStatus.APPROVED,
        }:
            raise ValueError(
                "Trend must be validated before publishing"
            )

        if self.is_stale:
            raise ValueError(
                "Cannot publish expired market data"
            )

        self.status = MarketTrendStatus.PUBLISHED
        self.published_at = utc_now()
        self._touch()

    # ========================================================
    # MARK SUPERSEDED
    # ========================================================

    def mark_superseded(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Trend is deleted"
            )

        if self.status != MarketTrendStatus.PUBLISHED:
            raise ValueError(
                "Only published trends can be superseded"
            )

        self.status = MarketTrendStatus.SUPERSEDED
        self._touch()

    # ========================================================
    # ARCHIVE
    # ========================================================

    def archive(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Trend is deleted"
            )

        if self.status not in {
            MarketTrendStatus.REJECTED,
            MarketTrendStatus.SUPERSEDED,
            MarketTrendStatus.PUBLISHED,
        }:
            raise ValueError(
                "Trend cannot be archived in current state"
            )

        self.status = MarketTrendStatus.ARCHIVED
        self._touch()

    # ========================================================
    # SOFT DELETE
    # ========================================================

    def soft_delete(self, user_id: str) -> None:
        if self.is_deleted:
            raise ValueError(
                "Trend already deleted"
            )

        if not user_id:
            raise ValueError(
                "Deleting user ID required"
            )

        if self.status not in {
            MarketTrendStatus.DETECTED,
            MarketTrendStatus.REJECTED,
            MarketTrendStatus.ARCHIVED,
        }:
            raise ValueError(
                "Only detected, rejected or archived "
                "trends can be deleted"
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
            "trend_code": self.trend_code,
            "title": self.title,
            "description": self.description,
            "trend_type": self.trend_type.value,
            "direction": self.direction.value,
            "status": self.status.value,
            "source": self.source.value,
            "product_id": self.product_id,
            "category_id": self.category_id,
            "supplier_id": self.supplier_id,
            "warehouse_id": self.warehouse_id,
            "competitor_id": self.competitor_id,
            "competitor_name": self.competitor_name,
            "country_code": self.country_code,
            "region_code": self.region_code,
            "city": self.city,
            "market_segment": self.market_segment,
            "sales_channel": self.sales_channel,
            "time_horizon": self.time_horizon.value,
            "observation_start_at": datetime_string(
                self.observation_start_at
            ),
            "observation_end_at": datetime_string(
                self.observation_end_at
            ),
            "observed_at": datetime_string(
                self.observed_at
            ),
            "forecast_horizon_days": (
                self.forecast_horizon_days
            ),
            "metric_name": self.metric_name,
            "metric_unit": self.metric_unit,
            "current_value": decimal_string(
                self.current_value
            ),
            "previous_value": decimal_string(
                self.previous_value
            ),
            "predicted_value": decimal_string(
                self.predicted_value
            ),
            "change_percentage": self.change_percentage,
            "growth_rate_percentage": (
                self.growth_rate_percentage
            ),
            "market_share_percentage": (
                self.market_share_percentage
            ),
            "market_size": decimal_string(
                self.market_size
            ),
            "currency": self.currency,
            "our_price": decimal_string(
                self.our_price
            ),
            "competitor_price": decimal_string(
                self.competitor_price
            ),
            "price_gap_percentage": (
                self.price_gap_percentage
            ),
            "competitor_price_change_percentage": (
                self.competitor_price_change_percentage
            ),
            "is_seasonal": self.is_seasonal,
            "seasonal_period": self.seasonal_period,
            "consumer_sentiment_score": (
                self.consumer_sentiment_score
            ),
            "inflation_rate_percentage": (
                self.inflation_rate_percentage
            ),
            "economic_indicators": self.economic_indicators,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "confidence_score": self.confidence_score,
            "anomaly_score": self.anomaly_score,
            "opportunity_score": self.opportunity_score,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level.value,
            "impact_level": self.impact_level.value,
            "ai_summary": self.ai_summary,
            "ai_explanation": self.ai_explanation,
            "predicted_drivers": self.predicted_drivers,
            "recommendation_type": (
                self.recommendation_type.value
                if self.recommendation_type
                else None
            ),
            "recommended_action": self.recommended_action,
            "recommended_price": decimal_string(
                self.recommended_price
            ),
            "recommended_stock_quantity": decimal_string(
                self.recommended_stock_quantity
            ),
            "expected_business_impact": (
                self.expected_business_impact
            ),
            "integration_id": self.integration_id,
            "source_reference": self.source_reference,
            "source_url": self.source_url,
            "sample_size": self.sample_size,
            "data_quality_score": self.data_quality_score,
            "last_data_refresh_at": datetime_string(
                self.last_data_refresh_at
            ),
            "data_expires_at": datetime_string(
                self.data_expires_at
            ),
            "is_stale": self.is_stale,
            "is_high_risk": self.is_high_risk,
            "is_opportunity": self.is_opportunity,
            "is_published": self.is_published,
            "agent_run_id": self.agent_run_id,
            "agent_action_id": self.agent_action_id,
            "demand_forecast_id": self.demand_forecast_id,
            "requires_human_approval": (
                self.requires_human_approval
            ),
            "approval_request_id": self.approval_request_id,
            "approved_by": self.approved_by,
            "approved_at": datetime_string(
                self.approved_at
            ),
            "rejected_by": self.rejected_by,
            "rejected_at": datetime_string(
                self.rejected_at
            ),
            "rejection_reason": self.rejection_reason,
            "published_at": datetime_string(
                self.published_at
            ),
            "market_data": self.market_data,
            "trend_metadata": self.trend_metadata,
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
            f"<MarketTrend("
            f"id={self.id}, "
            f"code={self.trend_code}, "
            f"type={self.trend_type.value}, "
            f"status={self.status.value}"
            f")>"
        )
