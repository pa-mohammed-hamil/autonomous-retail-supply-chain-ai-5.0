from __future__ import annotations

"""Planned module: demand forecast. Implementation pending."""

"""
backend/models/demand_forecast.py

Autonomous Retail Supply Chain AI 5.0
Demand Forecast ORM Model

Features:
    - Product and warehouse demand forecasting
    - Daily, weekly and monthly forecasts
    - Multiple forecasting algorithms
    - Prediction confidence intervals
    - Actual vs predicted demand
    - Forecast evaluation metrics
    - Model version tracking
    - AI agent integration
    - Forecast approval workflow
    - Multi-tenant organization isolation
    - Optimistic concurrency control
    - Soft deletion
    - UTC audit timestamps

Dependencies:
    SQLAlchemy >= 2.0

Shared base:
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

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_forecast_code() -> str:
    return f"FCST-{uuid.uuid4().hex[:16].upper()}"


def enum_column(enum_class, name: str):
    return SQLEnum(
        enum_class,
        name=name,
        native_enum=False,
        values_callable=lambda values: [
            member.value for member in values
        ],
        validate_strings=True,
        length=60,
    )


def to_decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Invalid numeric value") from None

    if not result.is_finite():
        raise ValueError("Numeric value must be finite")

    return result


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def decimal_string(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def datetime_string(
    value: datetime | None,
) -> str | None:
    return value.isoformat() if value else None


# ============================================================
# ENUMS
# ============================================================

class ForecastHorizon(str, enum.Enum):
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
    CUSTOM = "custom"


class ForecastModelType(str, enum.Enum):
    MOVING_AVERAGE = "moving_average"
    EXPONENTIAL_SMOOTHING = "exponential_smoothing"
    ARIMA = "arima"
    SARIMA = "sarima"
    PROPHET = "prophet"
    XGBOOST = "xgboost"
    LIGHTGBM = "lightgbm"
    CATBOOST = "catboost"
    RANDOM_FOREST = "random_forest"
    LSTM = "lstm"
    GRU = "gru"
    TRANSFORMER = "transformer"
    TFT = "temporal_fusion_transformer"
    NBEATS = "nbeats"
    ENSEMBLE = "ensemble"
    OTHER = "other"


class ForecastStatus(str, enum.Enum):
    DRAFT = "draft"
    GENERATED = "generated"
    VALIDATED = "validated"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    FAILED = "failed"


class ForecastSource(str, enum.Enum):
    ML_PIPELINE = "ml_pipeline"
    AI_AGENT = "ai_agent"
    FORECAST_ENGINE = "forecast_engine"
    MANUAL = "manual"
    ERP = "erp"
    EXTERNAL_API = "external_api"


class ForecastRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


# ============================================================
# DEMAND FORECAST MODEL
# ============================================================

class DemandForecast(Base):
    __tablename__ = "demand_forecasts"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "forecast_code",
            name="uq_demand_forecast_org_code",
        ),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_demand_forecast_org_id",
        ),
        CheckConstraint(
            "forecast_quantity >= 0",
            name="demand_forecast_quantity_nonnegative",
        ),
        CheckConstraint(
            "lower_bound IS NULL OR lower_bound >= 0",
            name="demand_forecast_lower_nonnegative",
        ),
        CheckConstraint(
            "upper_bound IS NULL OR upper_bound >= 0",
            name="demand_forecast_upper_nonnegative",
        ),
        CheckConstraint(
            "lower_bound IS NULL OR "
            "lower_bound <= forecast_quantity",
            name="demand_forecast_lower_valid",
        ),
        CheckConstraint(
            "upper_bound IS NULL OR "
            "upper_bound >= forecast_quantity",
            name="demand_forecast_upper_valid",
        ),
        CheckConstraint(
            "actual_quantity IS NULL OR actual_quantity >= 0",
            name="demand_forecast_actual_nonnegative",
        ),
        CheckConstraint(
            "confidence_level IS NULL OR "
            "(confidence_level > 0 AND confidence_level < 1)",
            name="demand_forecast_confidence_range",
        ),
        CheckConstraint(
            "stockout_probability IS NULL OR "
            "(stockout_probability >= 0 "
            "AND stockout_probability <= 1)",
            name="demand_forecast_stockout_range",
        ),
        CheckConstraint(
            "forecast_end_at > forecast_start_at",
            name="demand_forecast_period_valid",
        ),
        CheckConstraint(
            "forecast_version >= 1",
            name="demand_forecast_version_positive",
        ),
        Index(
            "ix_demand_forecast_org_product",
            "organization_id",
            "product_id",
        ),
        Index(
            "ix_demand_forecast_org_warehouse",
            "organization_id",
            "warehouse_id",
        ),
        Index(
            "ix_demand_forecast_org_period",
            "organization_id",
            "forecast_start_at",
            "forecast_end_at",
        ),
        Index(
            "ix_demand_forecast_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_demand_forecast_org_model",
            "organization_id",
            "model_name",
        ),
        Index(
            "ix_demand_forecast_run",
            "organization_id",
            "forecast_run_id",
        ),
    )

    # --------------------------------------------------------
    # PRIMARY IDENTIFIERS
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

    forecast_code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=generate_forecast_code,
    )

    forecast_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # BUSINESS REFERENCES
    # --------------------------------------------------------

    product_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    category_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    warehouse_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    region_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    sales_channel: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # --------------------------------------------------------
    # FORECAST DETAILS
    # --------------------------------------------------------

    forecast_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    horizon: Mapped[ForecastHorizon] = mapped_column(
        enum_column(
            ForecastHorizon,
            "demand_forecast_horizon",
        ),
        default=ForecastHorizon.DAILY,
        nullable=False,
    )

    status: Mapped[ForecastStatus] = mapped_column(
        enum_column(
            ForecastStatus,
            "demand_forecast_status",
        ),
        default=ForecastStatus.DRAFT,
        nullable=False,
    )

    source: Mapped[ForecastSource] = mapped_column(
        enum_column(
            ForecastSource,
            "demand_forecast_source",
        ),
        default=ForecastSource.FORECAST_ENGINE,
        nullable=False,
    )

    # --------------------------------------------------------
    # FORECAST PERIOD
    # --------------------------------------------------------

    forecast_start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    forecast_end_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    training_data_end_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # FORECAST VALUES
    # --------------------------------------------------------

    forecast_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
    )

    lower_bound: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    upper_bound: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    confidence_level: Mapped[float | None] = mapped_column(
        nullable=True,
    )

    unit_of_measure: Mapped[str] = mapped_column(
        String(30),
        default="units",
        nullable=False,
    )

    # --------------------------------------------------------
    # ACTUAL DEMAND
    # --------------------------------------------------------

    actual_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    absolute_error: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    percentage_error: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 4),
        nullable=True,
    )

    actual_recorded_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # MODEL INFORMATION
    # --------------------------------------------------------

    model_type: Mapped[ForecastModelType] = mapped_column(
        enum_column(
            ForecastModelType,
            "demand_forecast_model_type",
        ),
        default=ForecastModelType.OTHER,
        nullable=False,
    )

    model_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    model_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    model_registry_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    # --------------------------------------------------------
    # MODEL EVALUATION METRICS
    # --------------------------------------------------------

    mae: Mapped[float | None] = mapped_column(
        nullable=True,
    )

    rmse: Mapped[float | None] = mapped_column(
        nullable=True,
    )

    mape: Mapped[float | None] = mapped_column(
        nullable=True,
    )

    smape: Mapped[float | None] = mapped_column(
        nullable=True,
    )

    wape: Mapped[float | None] = mapped_column(
        nullable=True,
    )

    model_metrics: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # RISK AND REPLENISHMENT
    # --------------------------------------------------------

    risk_level: Mapped[ForecastRiskLevel] = mapped_column(
        enum_column(
            ForecastRiskLevel,
            "demand_forecast_risk_level",
        ),
        default=ForecastRiskLevel.UNKNOWN,
        nullable=False,
    )

    stockout_probability: Mapped[float | None] = mapped_column(
        nullable=True,
    )

    recommended_reorder_quantity: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    recommended_safety_stock: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    recommended_action: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # AI AGENT INTEGRATION
    # --------------------------------------------------------

    agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    agent_action_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    ai_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    explanation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    feature_importance: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # HUMAN APPROVAL
    # --------------------------------------------------------

    requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
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
    # FORECAST VERSIONING
    # --------------------------------------------------------

    forecast_version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    supersedes_forecast_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # ADDITIONAL DATA
    # --------------------------------------------------------

    forecast_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    external_factors: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # AUDIT AND OBSERVABILITY
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
    def is_published(self) -> bool:
        return self.status == ForecastStatus.PUBLISHED

    @property
    def is_approved(self) -> bool:
        return self.status in {
            ForecastStatus.APPROVED,
            ForecastStatus.PUBLISHED,
        }

    @property
    def has_actuals(self) -> bool:
        return self.actual_quantity is not None

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            ForecastStatus.REJECTED,
            ForecastStatus.SUPERSEDED,
            ForecastStatus.FAILED,
        }

    @property
    def forecast_bias(self) -> Decimal | None:
        if self.actual_quantity is None:
            return None

        return self.forecast_quantity - self.actual_quantity

    # ========================================================
    # INTERNAL VALIDATION
    # ========================================================

    def _ensure_active(self) -> None:
        if self.is_deleted:
            raise ValueError("Forecast is deleted")

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def validate_period(self) -> None:
        if (
            normalize_datetime(self.forecast_end_at)
            <= normalize_datetime(self.forecast_start_at)
        ):
            raise ValueError(
                "Forecast end must be after forecast start"
            )

    def validate_intervals(self) -> None:
        if self.forecast_quantity < 0:
            raise ValueError(
                "Forecast quantity cannot be negative"
            )

        if (
            self.lower_bound is not None
            and self.lower_bound > self.forecast_quantity
        ):
            raise ValueError(
                "Lower bound exceeds forecast"
            )

        if (
            self.upper_bound is not None
            and self.upper_bound < self.forecast_quantity
        ):
            raise ValueError(
                "Upper bound is below forecast"
            )

        if (
            self.lower_bound is not None
            and self.upper_bound is not None
            and self.lower_bound > self.upper_bound
        ):
            raise ValueError(
                "Lower bound exceeds upper bound"
            )

    # ========================================================
    # UPDATE PREDICTION
    # ========================================================

    def update_prediction(
        self,
        *,
        quantity: Decimal | float | int,
        lower_bound: Decimal | float | int | None = None,
        upper_bound: Decimal | float | int | None = None,
        confidence_level: float | None = None,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            ForecastStatus.DRAFT,
            ForecastStatus.GENERATED,
        }:
            raise ValueError(
                "Cannot edit a validated or published forecast"
            )

        predicted = to_decimal(quantity)

        lower = (
            to_decimal(lower_bound)
            if lower_bound is not None
            else None
        )

        upper = (
            to_decimal(upper_bound)
            if upper_bound is not None
            else None
        )

        if predicted < 0:
            raise ValueError(
                "Forecast quantity must be nonnegative"
            )

        if lower is not None and lower < 0:
            raise ValueError(
                "Lower bound must be nonnegative"
            )

        if upper is not None and upper < 0:
            raise ValueError(
                "Upper bound must be nonnegative"
            )

        if lower is not None and lower > predicted:
            raise ValueError(
                "Lower bound exceeds prediction"
            )

        if upper is not None and upper < predicted:
            raise ValueError(
                "Upper bound is below prediction"
            )

        if (
            confidence_level is not None
            and (
                not math.isfinite(confidence_level)
                or not 0 < confidence_level < 1
            )
        ):
            raise ValueError(
                "Confidence level must be between 0 and 1"
            )

        self.forecast_quantity = predicted
        self.lower_bound = lower
        self.upper_bound = upper
        self.confidence_level = confidence_level
        self._touch()

    # ========================================================
    # MARK GENERATED
    # ========================================================

    def mark_generated(self) -> None:
        self._ensure_active()

        if self.status != ForecastStatus.DRAFT:
            raise ValueError(
                "Only draft forecasts can be generated"
            )

        self.validate_period()
        self.validate_intervals()

        self.status = ForecastStatus.GENERATED
        self.generated_at = utc_now()
        self._touch()

    # ========================================================
    # VALIDATE FORECAST
    # ========================================================

    def validate_forecast(self) -> None:
        self._ensure_active()

        if self.status != ForecastStatus.GENERATED:
            raise ValueError(
                "Only generated forecasts can be validated"
            )

        self.validate_period()
        self.validate_intervals()

        self.status = ForecastStatus.VALIDATED
        self._touch()

    # ========================================================
    # REQUEST APPROVAL
    # ========================================================

    def request_approval(
        self,
        approval_request_id: str,
    ) -> None:
        self._ensure_active()

        if self.status != ForecastStatus.VALIDATED:
            raise ValueError(
                "Forecast must be validated first"
            )

        if not approval_request_id:
            raise ValueError(
                "Approval request ID is required"
            )

        self.requires_approval = True
        self.approval_request_id = approval_request_id
        self.status = ForecastStatus.PENDING_APPROVAL
        self._touch()

    # ========================================================
    # APPROVE FORECAST
    # ========================================================

    def approve(
        self,
        user_id: str,
    ) -> None:
        self._ensure_active()

        allowed = (
            {ForecastStatus.PENDING_APPROVAL}
            if self.requires_approval
            else {ForecastStatus.VALIDATED}
        )

        if self.status not in allowed:
            raise ValueError(
                "Forecast cannot be approved in current state"
            )

        if not user_id:
            raise ValueError(
                "Approving user is required"
            )

        self.approved_by = user_id
        self.approved_at = utc_now()
        self.status = ForecastStatus.APPROVED
        self._touch()

    # ========================================================
    # REJECT FORECAST
    # ========================================================

    def reject(
        self,
        *,
        user_id: str,
        reason: str,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            ForecastStatus.VALIDATED,
            ForecastStatus.PENDING_APPROVAL,
        }:
            raise ValueError(
                "Forecast cannot be rejected"
            )

        if not user_id:
            raise ValueError(
                "Rejecting user is required"
            )

        if not reason.strip():
            raise ValueError(
                "Rejection reason is required"
            )

        self.rejected_by = user_id
        self.rejected_at = utc_now()
        self.rejection_reason = reason
        self.status = ForecastStatus.REJECTED
        self._touch()

    # ========================================================
    # PUBLISH FORECAST
    # ========================================================

    def publish(self) -> None:
        self._ensure_active()

        if self.status != ForecastStatus.APPROVED:
            raise ValueError(
                "Forecast must be approved before publication"
            )

        self.status = ForecastStatus.PUBLISHED
        self.published_at = utc_now()
        self._touch()

    # ========================================================
    # RECORD ACTUAL DEMAND
    # ========================================================

    def record_actual(
        self,
        actual_quantity: Decimal | float | int,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            ForecastStatus.APPROVED,
            ForecastStatus.PUBLISHED,
            ForecastStatus.SUPERSEDED,
        }:
            raise ValueError(
                "Forecast must be approved or published"
            )

        actual = to_decimal(actual_quantity)

        if actual < 0:
            raise ValueError(
                "Actual demand cannot be negative"
            )

        self.actual_quantity = actual

        self.absolute_error = abs(
            self.forecast_quantity - actual
        )

        if actual == 0:
            self.percentage_error = None
        else:
            self.percentage_error = (
                self.absolute_error
                / actual
                * Decimal("100")
            ).quantize(Decimal("0.0001"))

        self.actual_recorded_at = utc_now()
        self._touch()

    # ========================================================
    # UPDATE MODEL METRICS
    # ========================================================

    def update_model_metrics(
        self,
        *,
        mae: float | None = None,
        rmse: float | None = None,
        mape: float | None = None,
        smape: float | None = None,
        wape: float | None = None,
    ) -> None:
        self._ensure_active()

        metrics = {
            "mae": mae,
            "rmse": rmse,
            "mape": mape,
            "smape": smape,
            "wape": wape,
        }

        for name, value in metrics.items():
            if value is not None:
                if not math.isfinite(value) or value < 0:
                    raise ValueError(
                        f"{name} must be finite and nonnegative"
                    )

                setattr(self, name, value)

        self._touch()

    # ========================================================
    # REPLENISHMENT RECOMMENDATIONS
    # ========================================================

    def update_replenishment(
        self,
        *,
        reorder_quantity: Decimal | float | int,
        safety_stock: Decimal | float | int,
        stockout_probability: float | None = None,
        recommended_action: str | None = None,
    ) -> None:
        self._ensure_active()

        reorder = to_decimal(reorder_quantity)
        safety = to_decimal(safety_stock)

        if reorder < 0 or safety < 0:
            raise ValueError(
                "Replenishment values must be nonnegative"
            )

        if stockout_probability is not None:
            if (
                not math.isfinite(stockout_probability)
                or not 0 <= stockout_probability <= 1
            ):
                raise ValueError(
                    "Stockout probability must be between 0 and 1"
                )

        self.recommended_reorder_quantity = reorder
        self.recommended_safety_stock = safety
        self.stockout_probability = stockout_probability
        self.recommended_action = recommended_action
        self._touch()

    # ========================================================
    # SUPERSEDE FORECAST
    # ========================================================

    def mark_superseded(self) -> None:
        self._ensure_active()

        if self.status != ForecastStatus.PUBLISHED:
            raise ValueError(
                "Only published forecasts can be superseded"
            )

        self.status = ForecastStatus.SUPERSEDED
        self.superseded_at = utc_now()
        self._touch()

    # ========================================================
    # SOFT DELETE
    # ========================================================

    def soft_delete(self, user_id: str) -> None:
        if self.is_deleted:
            raise ValueError(
                "Forecast already deleted"
            )

        if not user_id:
            raise ValueError(
                "Deleting user is required"
            )

        if self.status == ForecastStatus.PUBLISHED:
            raise ValueError(
                "Published forecasts must be superseded "
                "rather than deleted"
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
            "forecast_code": self.forecast_code,
            "forecast_run_id": self.forecast_run_id,
            "product_id": self.product_id,
            "category_id": self.category_id,
            "warehouse_id": self.warehouse_id,
            "region_id": self.region_id,
            "sales_channel": self.sales_channel,
            "forecast_name": self.forecast_name,
            "description": self.description,
            "horizon": self.horizon.value,
            "status": self.status.value,
            "source": self.source.value,
            "forecast_start_at": datetime_string(
                self.forecast_start_at
            ),
            "forecast_end_at": datetime_string(
                self.forecast_end_at
            ),
            "generated_at": datetime_string(
                self.generated_at
            ),
            "training_data_end_at": datetime_string(
                self.training_data_end_at
            ),
            "forecast_quantity": decimal_string(
                self.forecast_quantity
            ),
            "lower_bound": decimal_string(
                self.lower_bound
            ),
            "upper_bound": decimal_string(
                self.upper_bound
            ),
            "confidence_level": self.confidence_level,
            "unit_of_measure": self.unit_of_measure,
            "actual_quantity": decimal_string(
                self.actual_quantity
            ),
            "absolute_error": decimal_string(
                self.absolute_error
            ),
            "percentage_error": decimal_string(
                self.percentage_error
            ),
            "model_type": self.model_type.value,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "model_registry_id": self.model_registry_id,
            "mae": self.mae,
            "rmse": self.rmse,
            "mape": self.mape,
            "smape": self.smape,
            "wape": self.wape,
            "model_metrics": self.model_metrics,
            "risk_level": self.risk_level.value,
            "stockout_probability": (
                self.stockout_probability
            ),
            "recommended_reorder_quantity": decimal_string(
                self.recommended_reorder_quantity
            ),
            "recommended_safety_stock": decimal_string(
                self.recommended_safety_stock
            ),
            "recommended_action": self.recommended_action,
            "agent_run_id": self.agent_run_id,
            "agent_action_id": self.agent_action_id,
            "ai_summary": self.ai_summary,
            "explanation": self.explanation,
            "feature_importance": self.feature_importance,
            "requires_approval": self.requires_approval,
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
            "forecast_version": self.forecast_version,
            "supersedes_forecast_id": (
                self.supersedes_forecast_id
            ),
            "superseded_at": datetime_string(
                self.superseded_at
            ),
            "forecast_metadata": self.forecast_metadata,
            "external_factors": self.external_factors,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "trace_id": self.trace_id,
            "correlation_id": self.correlation_id,
            "is_deleted": self.is_deleted,
            "deleted_at": datetime_string(
                self.deleted_at
            ),
            "deleted_by": self.deleted_by,
            "version": self.version,
            "forecast_bias": decimal_string(
                self.forecast_bias
            ),
            "is_published": self.is_published,
            "created_at": datetime_string(
                self.created_at
            ),
            "updated_at": datetime_string(
                self.updated_at
            ),
        }

    def __repr__(self) -> str:
        return (
            f"<DemandForecast("
            f"id={self.id}, "
            f"code={self.forecast_code}, "
            f"status={self.status.value}, "
            f"quantity={self.forecast_quantity}"
            f")>"
        )
