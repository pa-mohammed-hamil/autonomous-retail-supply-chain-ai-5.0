from __future__ import annotations

"""Planned module: stockout prediction. Implementation pending."""
# backend/models/stockout_prediction.py


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
# CONSTANTS
# ============================================================

ZERO = Decimal("0.0000")
ONE = Decimal("1.0000")
MAX_QUANTITY = Decimal("99999999999999.9999")
MAX_MONEY = Decimal("9999999999999999.9999")


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_prediction_number() -> str:
    return f"SOP-{uuid.uuid4().hex[:18].upper()}"


def enum_column(enum_class: type[enum.Enum], name: str):
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


def optional_text(value: str | None) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise ValueError("Expected a string")

    return value.strip() or None


def ensure_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("Expected datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timezone-aware datetime required")

    return value.astimezone(timezone.utc)


def decimal_value(
    value: Decimal | str | int | float,
    field: str,
    *,
    minimum: Decimal = ZERO,
    maximum: Decimal = MAX_QUANTITY,
) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")

    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(
            f"{field} must be a valid decimal"
        ) from None

    if not result.is_finite():
        raise ValueError(f"{field} must be finite")

    if result < minimum or result > maximum:
        raise ValueError(
            f"{field} must be between {minimum} and {maximum}"
        )

    if result != result.quantize(Decimal("0.0001")):
        raise ValueError(
            f"{field} supports at most four decimal places"
        )

    return result


def probability_value(
    value: Decimal | str | int | float,
    field: str,
) -> Decimal:
    return decimal_value(
        value,
        field,
        minimum=ZERO,
        maximum=ONE,
    )


def enum_value(value: Any) -> Any:
    return value.value if isinstance(value, enum.Enum) else value


def serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def serialize_decimal(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite Decimal")
        return str(value)

    if isinstance(value, float):
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError("Non-finite float")
        return str(result)

    if isinstance(value, datetime):
        return ensure_datetime(value).isoformat()

    if isinstance(value, enum.Enum):
        return value.value

    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]

    raise ValueError(
        f"Unsupported JSON type: {type(value).__name__}"
    )


# ============================================================
# ENUMS
# ============================================================

class StockoutPredictionStatus(str, enum.Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    REVIEW_REQUIRED = "review_required"
    REVIEWED = "reviewed"
    ACTION_REQUIRED = "action_required"
    ACTION_PENDING_APPROVAL = "action_pending_approval"
    ACTION_APPROVED = "action_approved"
    ACTION_REJECTED = "action_rejected"
    MITIGATION_IN_PROGRESS = "mitigation_in_progress"
    MITIGATED = "mitigated"
    MONITORING = "monitoring"
    EXPIRED = "expired"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class StockoutRiskLevel(str, enum.Enum):
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class StockoutPredictionSource(str, enum.Enum):
    DEMAND_FORECAST = "demand_forecast"
    INVENTORY_MONITOR = "inventory_monitor"
    REPLENISHMENT_ENGINE = "replenishment_engine"
    ML_MODEL = "ml_model"
    AI_AGENT = "ai_agent"
    SIMULATION = "simulation"
    ERP = "erp"
    WMS = "wms"
    API = "api"
    SCHEDULER = "scheduler"
    MANUAL = "manual"


class StockoutPredictionMethod(str, enum.Enum):
    RULE_BASED = "rule_based"
    MOVING_AVERAGE = "moving_average"
    EXPONENTIAL_SMOOTHING = "exponential_smoothing"
    ARIMA = "arima"
    SARIMA = "sarima"
    PROPHET = "prophet"
    XGBOOST = "xgboost"
    LIGHTGBM = "lightgbm"
    RANDOM_FOREST = "random_forest"
    LSTM = "lstm"
    GRU = "gru"
    TRANSFORMER = "transformer"
    DEEP_LEARNING = "deep_learning"
    ENSEMBLE = "ensemble"
    MONTE_CARLO = "monte_carlo"
    HYBRID = "hybrid"
    OTHER = "other"


class StockoutPredictionPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"


class StockoutPredictionHorizon(str, enum.Enum):
    INTRADAY = "intraday"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"


class StockoutPredictionApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class StockoutPredictionAction(str, enum.Enum):
    NONE = "none"
    CREATE_REPLENISHMENT_PLAN = "create_replenishment_plan"
    CREATE_PURCHASE_ORDER = "create_purchase_order"
    EMERGENCY_REPLENISHMENT = "emergency_replenishment"
    TRANSFER_INVENTORY = "transfer_inventory"
    INCREASE_SAFETY_STOCK = "increase_safety_stock"
    ADJUST_REORDER_POINT = "adjust_reorder_point"
    EXPEDITE_SUPPLIER = "expedite_supplier"
    CHANGE_SUPPLIER = "change_supplier"
    REALLOCATE_STOCK = "reallocate_stock"
    LIMIT_PROMOTIONS = "limit_promotions"
    REVIEW_DEMAND_FORECAST = "review_demand_forecast"
    INVESTIGATE_INVENTORY = "investigate_inventory"
    NOTIFY_WAREHOUSE = "notify_warehouse"
    ESCALATE_TO_MANAGER = "escalate_to_manager"
    MANUAL_REVIEW = "manual_review"
    OTHER = "other"


class StockoutPredictionOutcome(str, enum.Enum):
    UNKNOWN = "unknown"
    STOCKOUT_OCCURRED = "stockout_occurred"
    STOCKOUT_PREVENTED = "stockout_prevented"
    NO_STOCKOUT = "no_stockout"
    PARTIAL_STOCKOUT = "partial_stockout"
    INCONCLUSIVE = "inconclusive"


class StockoutPredictionValidationStatus(str, enum.Enum):
    NOT_EVALUATED = "not_evaluated"
    PENDING = "pending"
    EVALUATED = "evaluated"
    FAILED = "failed"


class StockoutFactorCategory(str, enum.Enum):
    DEMAND = "demand"
    INVENTORY = "inventory"
    SUPPLIER = "supplier"
    LOGISTICS = "logistics"
    SEASONALITY = "seasonality"
    PROMOTION = "promotion"
    PRICING = "pricing"
    LEAD_TIME = "lead_time"
    WAREHOUSE = "warehouse"
    EXTERNAL_EVENT = "external_event"
    MODEL_UNCERTAINTY = "model_uncertainty"
    OTHER = "other"


# ============================================================
# STOCKOUT PREDICTION MODEL
# ============================================================

class StockoutPrediction(Base):
    __tablename__ = "stockout_predictions"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "prediction_number",
            name="uq_stockout_prediction_org_number",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_stockout_prediction_org_idempotency",
        ),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_stockout_prediction_org_id",
        ),
        CheckConstraint(
            "current_stock >= 0",
            name="ck_stockout_current_stock",
        ),
        CheckConstraint(
            "available_stock >= 0",
            name="ck_stockout_available_stock",
        ),
        CheckConstraint(
            "reserved_stock >= 0",
            name="ck_stockout_reserved_stock",
        ),
        CheckConstraint(
            "incoming_stock >= 0",
            name="ck_stockout_incoming_stock",
        ),
        CheckConstraint(
            "safety_stock >= 0",
            name="ck_stockout_safety_stock",
        ),
        CheckConstraint(
            "reorder_point >= 0",
            name="ck_stockout_reorder_point",
        ),
        CheckConstraint(
            "forecast_demand >= 0",
            name="ck_stockout_forecast_demand",
        ),
        CheckConstraint(
            "average_daily_demand >= 0",
            name="ck_stockout_avg_daily_demand",
        ),
        CheckConstraint(
            "predicted_remaining_stock IS NULL OR "
            "predicted_remaining_stock >= 0",
            name="ck_stockout_predicted_remaining",
        ),
        CheckConstraint(
            "predicted_shortage_quantity >= 0",
            name="ck_stockout_shortage_quantity",
        ),
        CheckConstraint(
            "recommended_reorder_quantity >= 0",
            name="ck_stockout_reorder_quantity",
        ),
        CheckConstraint(
            "stockout_probability IS NULL OR "
            "(stockout_probability >= 0 AND "
            "stockout_probability <= 1)",
            name="ck_stockout_probability",
        ),
        CheckConstraint(
            "confidence_score IS NULL OR "
            "(confidence_score >= 0 AND "
            "confidence_score <= 1)",
            name="ck_stockout_confidence",
        ),
        CheckConstraint(
            "risk_score IS NULL OR "
            "(risk_score >= 0 AND risk_score <= 1)",
            name="ck_stockout_risk_score",
        ),
        CheckConstraint(
            "days_until_stockout IS NULL OR "
            "days_until_stockout >= 0",
            name="ck_stockout_days_until",
        ),
        CheckConstraint(
            "forecast_horizon_days > 0",
            name="ck_stockout_horizon_days",
        ),
        CheckConstraint(
            "supplier_lead_time_days IS NULL OR "
            "supplier_lead_time_days >= 0",
            name="ck_stockout_lead_time",
        ),
        CheckConstraint(
            "estimated_lost_sales >= 0",
            name="ck_stockout_lost_sales",
        ),
        CheckConstraint(
            "estimated_revenue_loss >= 0",
            name="ck_stockout_revenue_loss",
        ),
        CheckConstraint(
            "estimated_profit_loss >= 0",
            name="ck_stockout_profit_loss",
        ),
        CheckConstraint(
            "estimated_replenishment_cost >= 0",
            name="ck_stockout_replenishment_cost",
        ),
        CheckConstraint(
            "actual_shortage_quantity >= 0",
            name="ck_stockout_actual_shortage",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_stockout_version",
        ),
        Index(
            "ix_stockout_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_stockout_org_product",
            "organization_id",
            "product_id",
        ),
        Index(
            "ix_stockout_org_warehouse",
            "organization_id",
            "warehouse_id",
        ),
        Index(
            "ix_stockout_org_risk",
            "organization_id",
            "risk_level",
        ),
        Index(
            "ix_stockout_org_predicted_date",
            "organization_id",
            "predicted_stockout_at",
        ),
        Index(
            "ix_stockout_org_created",
            "organization_id",
            "created_at",
        ),
        Index(
            "ix_stockout_org_model",
            "organization_id",
            "model_registry_id",
        ),
    )

    # ========================================================
    # IDENTITY
    # ========================================================

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

    prediction_number: Mapped[str] = mapped_column(
        String(60),
        default=generate_prediction_number,
        nullable=False,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # ========================================================
    # PREDICTION DETAILS
    # ========================================================

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    status: Mapped[StockoutPredictionStatus] = mapped_column(
        enum_column(
            StockoutPredictionStatus,
            "stockout_prediction_status",
        ),
        default=StockoutPredictionStatus.DRAFT,
        nullable=False,
    )

    risk_level: Mapped[StockoutRiskLevel] = mapped_column(
        enum_column(
            StockoutRiskLevel,
            "stockout_prediction_risk_level",
        ),
        default=StockoutRiskLevel.UNKNOWN,
        nullable=False,
    )

    priority: Mapped[
        StockoutPredictionPriority
    ] = mapped_column(
        enum_column(
            StockoutPredictionPriority,
            "stockout_prediction_priority",
        ),
        default=StockoutPredictionPriority.NORMAL,
        nullable=False,
    )

    source: Mapped[StockoutPredictionSource] = mapped_column(
        enum_column(
            StockoutPredictionSource,
            "stockout_prediction_source",
        ),
        default=StockoutPredictionSource.ML_MODEL,
        nullable=False,
    )

    prediction_method: Mapped[
        StockoutPredictionMethod
    ] = mapped_column(
        enum_column(
            StockoutPredictionMethod,
            "stockout_prediction_method",
        ),
        default=StockoutPredictionMethod.HYBRID,
        nullable=False,
    )

    prediction_horizon: Mapped[
        StockoutPredictionHorizon
    ] = mapped_column(
        enum_column(
            StockoutPredictionHorizon,
            "stockout_prediction_horizon",
        ),
        default=StockoutPredictionHorizon.WEEKLY,
        nullable=False,
    )

    # ========================================================
    # BUSINESS REFERENCES
    # ========================================================

    product_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    warehouse_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    inventory_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    supplier_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    category_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    demand_forecast_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    replenishment_plan_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    stock_alert_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    supplier_risk_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    simulation_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    model_registry_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    evaluation_result_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    approval_request_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    purchase_order_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # ========================================================
    # PRODUCT DETAILS
    # ========================================================

    sku: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    product_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    unit_of_measure: Mapped[str] = mapped_column(
        String(30),
        default="unit",
        nullable=False,
    )

    # ========================================================
    # INVENTORY SNAPSHOT
    # ========================================================

    current_stock: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    available_stock: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    reserved_stock: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    incoming_stock: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    safety_stock: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    reorder_point: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    inventory_snapshot_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # DEMAND INFORMATION
    # ========================================================

    forecast_demand: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    average_daily_demand: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    demand_variability: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    demand_growth_rate: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    seasonality_factor: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    promotional_demand_factor: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    forecast_horizon_days: Mapped[int] = mapped_column(
        Integer,
        default=7,
        nullable=False,
    )

    supplier_lead_time_days: Mapped[
        int | None
    ] = mapped_column(
        Integer,
        nullable=True,
    )

    # ========================================================
    # PREDICTION RESULTS
    # ========================================================

    stockout_probability: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    confidence_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    risk_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    predicted_stockout_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    days_until_stockout: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    predicted_remaining_stock: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    predicted_shortage_quantity: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    recommended_reorder_quantity: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    recommended_reorder_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    expected_replenishment_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    prediction_window_start: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    prediction_window_end: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # FINANCIAL IMPACT
    # ========================================================

    currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    estimated_lost_sales: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    estimated_revenue_loss: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    estimated_profit_loss: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    estimated_replenishment_cost: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    financial_impact_details: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # ========================================================
    # AI / ML METADATA
    # ========================================================

    model_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    model_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    model_provider: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    model_parameters: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    feature_values: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    feature_importance: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    prediction_intervals: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    ai_explanation: Mapped[str | None] = mapped_column(
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

    uncertainty_factors: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # ========================================================
    # MITIGATION
    # ========================================================

    recommended_action: Mapped[
        StockoutPredictionAction
    ] = mapped_column(
        enum_column(
            StockoutPredictionAction,
            "stockout_prediction_action",
        ),
        default=StockoutPredictionAction.NONE,
        nullable=False,
    )

    action_details: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    action_reference_id: Mapped[
        str | None
    ] = mapped_column(
        String(100),
        nullable=True,
    )

    assigned_to: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    action_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    action_started_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    mitigated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    mitigation_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ========================================================
    # APPROVAL
    # ========================================================

    requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    approval_status: Mapped[
        StockoutPredictionApprovalStatus
    ] = mapped_column(
        enum_column(
            StockoutPredictionApprovalStatus,
            "stockout_prediction_approval_status",
        ),
        default=StockoutPredictionApprovalStatus.NOT_REQUIRED,
        nullable=False,
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

    # ========================================================
    # VALIDATION / OUTCOME
    # ========================================================

    validation_status: Mapped[
        StockoutPredictionValidationStatus
    ] = mapped_column(
        enum_column(
            StockoutPredictionValidationStatus,
            "stockout_prediction_validation_status",
        ),
        default=StockoutPredictionValidationStatus.NOT_EVALUATED,
        nullable=False,
    )

    actual_outcome: Mapped[
        StockoutPredictionOutcome
    ] = mapped_column(
        enum_column(
            StockoutPredictionOutcome,
            "stockout_prediction_outcome",
        ),
        default=StockoutPredictionOutcome.UNKNOWN,
        nullable=False,
    )

    actual_stockout_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    actual_shortage_quantity: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    prediction_error_days: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )

    validation_metrics: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    evaluated_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # LIFECYCLE
    # ========================================================

    queued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    processing_started_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    predicted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    reviewed_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    review_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    expired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    failure_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    failure_reason: Mapped[str | None] = mapped_column(
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

    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # AUDIT
    # ========================================================

    prediction_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    prediction_history: Mapped[
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

    deleted_at: Mapped[datetime | None] = mapped_column(
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
    # RELATIONSHIPS
    # ========================================================

    risk_factors: Mapped[list["StockoutPredictionFactor"]] = (
        relationship(
            "StockoutPredictionFactor",
            back_populates="prediction",
            cascade="all, delete-orphan",
            passive_deletes=False,
            lazy="selectin",
        )
    )

    # ========================================================
    # COMPUTED PROPERTIES
    # ========================================================

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            StockoutPredictionStatus.EXPIRED,
            StockoutPredictionStatus.CANCELLED,
            StockoutPredictionStatus.ARCHIVED,
        }

    @property
    def is_high_risk(self) -> bool:
        return self.risk_level in {
            StockoutRiskLevel.HIGH,
            StockoutRiskLevel.CRITICAL,
        }

    @property
    def is_approved(self) -> bool:
        return (
            not self.requires_approval
            or self.approval_status
            == StockoutPredictionApprovalStatus.APPROVED
        )

    @property
    def is_expired(self) -> bool:
        return (
            self.expires_at is not None
            and ensure_datetime(self.expires_at) <= utc_now()
        )

    @property
    def available_stock_gap(self) -> Decimal:
        return max(
            ZERO,
            (self.reorder_point or ZERO)
            - (self.available_stock or ZERO),
        )

    @property
    def safety_stock_gap(self) -> Decimal:
        return max(
            ZERO,
            (self.safety_stock or ZERO)
            - (self.available_stock or ZERO),
        )

    @property
    def projected_stock_balance(self) -> Decimal:
        return (
            (self.available_stock or ZERO)
            + (self.incoming_stock or ZERO)
            - (self.forecast_demand or ZERO)
        )

    @property
    def calculated_shortage(self) -> Decimal:
        return max(
            ZERO,
            -self.projected_stock_balance,
        )

    @property
    def needs_replenishment(self) -> bool:
        return (
            self.available_stock_gap > ZERO
            or self.calculated_shortage > ZERO
            or self.is_high_risk
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _touch(self, actor_id: str | None = None) -> None:
        self.updated_at = utc_now()

        if actor_id is not None:
            self.updated_by = actor_id

    def _ensure_active(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Prediction has been deleted"
            )

    def _require_status(
        self,
        *statuses: StockoutPredictionStatus,
    ) -> None:
        self._ensure_active()

        if self.status not in statuses:
            raise ValueError(
                "Invalid prediction status: "
                f"{enum_value(self.status)}"
            )

    def _record_event(
        self,
        event: str,
        *,
        actor_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        history = list(self.prediction_history or [])

        history.append({
            "event_id": generate_uuid(),
            "event": required_text(event, "Event"),
            "actor_id": actor_id,
            "timestamp": utc_now().isoformat(),
            "details": json_safe(details or {}),
        })

        self.prediction_history = history
        self._touch(actor_id)

    # ========================================================
    # UPDATE INVENTORY SNAPSHOT
    # ========================================================

    def update_inventory_snapshot(
        self,
        *,
        current_stock: Decimal | str | float,
        available_stock: Decimal | str | float,
        reserved_stock: Decimal | str | float,
        incoming_stock: Decimal | str | float,
        safety_stock: Decimal | str | float,
        reorder_point: Decimal | str | float,
        actor_id: str,
    ) -> None:
        self._require_status(
            StockoutPredictionStatus.DRAFT,
            StockoutPredictionStatus.QUEUED,
        )

        current = decimal_value(
            current_stock,
            "current_stock",
        )
        available = decimal_value(
            available_stock,
            "available_stock",
        )
        reserved = decimal_value(
            reserved_stock,
            "reserved_stock",
        )
        incoming = decimal_value(
            incoming_stock,
            "incoming_stock",
        )
        safety = decimal_value(
            safety_stock,
            "safety_stock",
        )
        reorder = decimal_value(
            reorder_point,
            "reorder_point",
        )

        if available + reserved > current:
            raise ValueError(
                "Available plus reserved stock cannot "
                "exceed current stock"
            )

        self.current_stock = current
        self.available_stock = available
        self.reserved_stock = reserved
        self.incoming_stock = incoming
        self.safety_stock = safety
        self.reorder_point = reorder
        self.inventory_snapshot_at = utc_now()

        self._record_event(
            "stockout_inventory_snapshot_updated",
            actor_id=actor_id,
            details={
                "current_stock": str(current),
                "available_stock": str(available),
                "incoming_stock": str(incoming),
            },
        )

    # ========================================================
    # UPDATE DEMAND FEATURES
    # ========================================================

    def update_demand_features(
        self,
        *,
        forecast_demand: Decimal | str | float,
        average_daily_demand: Decimal | str | float,
        actor_id: str,
        demand_variability: Decimal | str | float | None = None,
        supplier_lead_time_days: int | None = None,
        feature_values: dict[str, Any] | None = None,
    ) -> None:
        self._require_status(
            StockoutPredictionStatus.DRAFT,
            StockoutPredictionStatus.QUEUED,
        )

        demand = decimal_value(
            forecast_demand,
            "forecast_demand",
        )
        daily = decimal_value(
            average_daily_demand,
            "average_daily_demand",
        )

        variability = (
            decimal_value(
                demand_variability,
                "demand_variability",
            )
            if demand_variability is not None
            else None
        )

        if supplier_lead_time_days is not None:
            if (
                isinstance(supplier_lead_time_days, bool)
                or not isinstance(supplier_lead_time_days, int)
                or supplier_lead_time_days < 0
            ):
                raise ValueError(
                    "Supplier lead time must be "
                    "a nonnegative integer"
                )

        safe_features = json_safe(feature_values or {})

        self.forecast_demand = demand
        self.average_daily_demand = daily
        self.demand_variability = variability
        self.supplier_lead_time_days = supplier_lead_time_days
        self.feature_values = safe_features

        self._record_event(
            "stockout_demand_features_updated",
            actor_id=actor_id,
            details={
                "forecast_demand": str(demand),
                "average_daily_demand": str(daily),
            },
        )

    # ========================================================
    # QUEUE PREDICTION
    # ========================================================

    def queue(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            StockoutPredictionStatus.DRAFT
        )

        required_text(
            self.organization_id,
            "Organization ID",
        )
        required_text(self.product_id, "Product ID")
        required_text(self.warehouse_id, "Warehouse ID")

        if (
            isinstance(self.forecast_horizon_days, bool)
            or not isinstance(self.forecast_horizon_days, int)
            or self.forecast_horizon_days <= 0
        ):
            raise ValueError(
                "Forecast horizon must be a positive integer"
            )

        self.status = StockoutPredictionStatus.QUEUED
        self.queued_at = utc_now()

        self._record_event(
            "stockout_prediction_queued",
            actor_id=actor_id,
        )

    # ========================================================
    # START PREDICTION
    # ========================================================

    def start_processing(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            StockoutPredictionStatus.QUEUED
        )

        self.status = StockoutPredictionStatus.PROCESSING
        self.processing_started_at = utc_now()

        self._record_event(
            "stockout_prediction_processing_started",
            actor_id=actor_id,
        )

    # ========================================================
    # SAVE PREDICTION RESULTS
    # ========================================================

    def record_prediction(
        self,
        *,
        actor_id: str,
        stockout_probability: Decimal | str | float,
        confidence_score: Decimal | str | float,
        risk_score: Decimal | str | float,
        risk_level: StockoutRiskLevel,
        predicted_shortage_quantity: Decimal | str | float,
        recommended_reorder_quantity: Decimal | str | float,
        predicted_stockout_at: datetime | None = None,
        days_until_stockout: Decimal | str | float | None = None,
        predicted_remaining_stock: Decimal | str | float | None = None,
        recommended_reorder_at: datetime | None = None,
        expected_replenishment_at: datetime | None = None,
        model_name: str | None = None,
        model_version: str | None = None,
        explanation: str | None = None,
        recommendations: list[dict[str, Any]] | None = None,
        feature_importance: dict[str, Any] | None = None,
        prediction_intervals: dict[str, Any] | None = None,
        review_required: bool = False,
    ) -> None:
        self._require_status(
            StockoutPredictionStatus.PROCESSING
        )

        if not isinstance(risk_level, StockoutRiskLevel):
            raise ValueError("Invalid risk level")

        probability = probability_value(
            stockout_probability,
            "stockout_probability",
        )
        confidence = probability_value(
            confidence_score,
            "confidence_score",
        )
        risk = probability_value(
            risk_score,
            "risk_score",
        )
        shortage = decimal_value(
            predicted_shortage_quantity,
            "predicted_shortage_quantity",
        )
        reorder_quantity = decimal_value(
            recommended_reorder_quantity,
            "recommended_reorder_quantity",
        )

        days = (
            decimal_value(
                days_until_stockout,
                "days_until_stockout",
            )
            if days_until_stockout is not None
            else None
        )

        remaining = (
            decimal_value(
                predicted_remaining_stock,
                "predicted_remaining_stock",
            )
            if predicted_remaining_stock is not None
            else None
        )

        stockout_at = (
            ensure_datetime(predicted_stockout_at)
            if predicted_stockout_at is not None
            else None
        )

        reorder_at = (
            ensure_datetime(recommended_reorder_at)
            if recommended_reorder_at is not None
            else None
        )

        replenishment_at = (
            ensure_datetime(expected_replenishment_at)
            if expected_replenishment_at is not None
            else None
        )

        if stockout_at is not None and days is not None:
            # The service should ensure consistency between
            # the predicted timestamp and days-to-stockout.
            pass

        safe_recommendations = json_safe(
            recommendations or []
        )
        safe_importance = json_safe(
            feature_importance or {}
        )
        safe_intervals = json_safe(
            prediction_intervals or {}
        )

        if not isinstance(safe_recommendations, list):
            raise ValueError(
                "Recommendations must be a list"
            )

        if any(
            not isinstance(item, dict)
            for item in safe_recommendations
        ):
            raise ValueError(
                "Recommendations must contain dictionaries"
            )

        self.stockout_probability = probability
        self.confidence_score = confidence
        self.risk_score = risk
        self.risk_level = risk_level
        self.predicted_shortage_quantity = shortage
        self.recommended_reorder_quantity = reorder_quantity
        self.predicted_stockout_at = stockout_at
        self.days_until_stockout = days
        self.predicted_remaining_stock = remaining
        self.recommended_reorder_at = reorder_at
        self.expected_replenishment_at = replenishment_at
        self.model_name = optional_text(model_name)
        self.model_version = optional_text(model_version)
        self.ai_explanation = optional_text(explanation)
        self.ai_recommendations = safe_recommendations
        self.feature_importance = safe_importance
        self.prediction_intervals = safe_intervals
        self.predicted_at = utc_now()
        self.completed_at = utc_now()

        self.status = (
            StockoutPredictionStatus.REVIEW_REQUIRED
            if review_required
            else StockoutPredictionStatus.COMPLETED
        )

        self._record_event(
            "stockout_prediction_completed",
            actor_id=actor_id,
            details={
                "stockout_probability": str(probability),
                "confidence_score": str(confidence),
                "risk_score": str(risk),
                "risk_level": risk_level.value,
                "recommended_reorder_quantity": str(
                    reorder_quantity
                ),
                "review_required": review_required,
            },
        )

    # ========================================================
    # ADD RISK FACTOR
    # ========================================================

    def add_risk_factor(
        self,
        *,
        category: StockoutFactorCategory,
        name: str,
        impact_score: Decimal | str | float,
        actor_id: str,
        description: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> "StockoutPredictionFactor":
        self._ensure_active()

        if self.is_terminal:
            raise ValueError(
                "Cannot modify terminal prediction"
            )

        if not isinstance(category, StockoutFactorCategory):
            raise ValueError("Invalid factor category")

        factor = StockoutPredictionFactor(
            id=generate_uuid(),
            organization_id=required_text(
                self.organization_id,
                "Organization ID",
            ),
            category=category,
            name=required_text(name, "Factor name"),
            description=optional_text(description),
            impact_score=probability_value(
                impact_score,
                "impact_score",
            ),
            evidence=json_safe(evidence or {}),
            created_by=required_text(
                actor_id,
                "Actor ID",
            ),
        )

        self.risk_factors.append(factor)

        self._record_event(
            "stockout_risk_factor_added",
            actor_id=actor_id,
            details={
                "factor_id": factor.id,
                "category": category.value,
                "name": factor.name,
            },
        )

        return factor

    # ========================================================
    # UPDATE FINANCIAL IMPACT
    # ========================================================

    def update_financial_impact(
        self,
        *,
        actor_id: str,
        estimated_lost_sales: Decimal | str | float,
        estimated_revenue_loss: Decimal | str | float,
        estimated_profit_loss: Decimal | str | float,
        estimated_replenishment_cost: Decimal | str | float,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._ensure_active()

        if self.is_terminal:
            raise ValueError(
                "Cannot update terminal prediction"
            )

        lost_sales = decimal_value(
            estimated_lost_sales,
            "estimated_lost_sales",
        )
        revenue_loss = decimal_value(
            estimated_revenue_loss,
            "estimated_revenue_loss",
            maximum=MAX_MONEY,
        )
        profit_loss = decimal_value(
            estimated_profit_loss,
            "estimated_profit_loss",
            maximum=MAX_MONEY,
        )
        replenishment_cost = decimal_value(
            estimated_replenishment_cost,
            "estimated_replenishment_cost",
            maximum=MAX_MONEY,
        )
        safe_details = json_safe(details or {})

        self.estimated_lost_sales = lost_sales
        self.estimated_revenue_loss = revenue_loss
        self.estimated_profit_loss = profit_loss
        self.estimated_replenishment_cost = replenishment_cost
        self.financial_impact_details = safe_details

        self._record_event(
            "stockout_financial_impact_updated",
            actor_id=actor_id,
            details={
                "estimated_revenue_loss": str(revenue_loss),
                "estimated_profit_loss": str(profit_loss),
                "estimated_replenishment_cost": str(
                    replenishment_cost
                ),
            },
        )

    # ========================================================
    # REVIEW PREDICTION
    # ========================================================

    def review(
        self,
        *,
        actor_id: str,
        notes: str,
        action_required: bool = False,
    ) -> None:
        self._require_status(
            StockoutPredictionStatus.COMPLETED,
            StockoutPredictionStatus.REVIEW_REQUIRED,
        )

        self.reviewed_by = required_text(
            actor_id,
            "Actor ID",
        )
        self.reviewed_at = utc_now()
        self.review_notes = required_text(
            notes,
            "Review notes",
        )

        self.status = (
            StockoutPredictionStatus.ACTION_REQUIRED
            if action_required
            else StockoutPredictionStatus.REVIEWED
        )

        self._record_event(
            "stockout_prediction_reviewed",
            actor_id=actor_id,
            details={
                "action_required": action_required,
            },
        )

    # ========================================================
    # ASSIGN ACTION
    # ========================================================

    def assign_action(
        self,
        *,
        actor_id: str,
        action: StockoutPredictionAction,
        assigned_to: str,
        details: dict[str, Any] | None = None,
        due_at: datetime | None = None,
    ) -> None:
        self._require_status(
            StockoutPredictionStatus.COMPLETED,
            StockoutPredictionStatus.REVIEWED,
            StockoutPredictionStatus.ACTION_REQUIRED,
            StockoutPredictionStatus.ACTION_REJECTED,
        )

        if not isinstance(action, StockoutPredictionAction):
            raise ValueError("Invalid action")

        if action == StockoutPredictionAction.NONE:
            raise ValueError(
                "A mitigation action must be selected"
            )

        assignee = required_text(
            assigned_to,
            "Assignee",
        )
        safe_details = json_safe(details or {})
        due = (
            ensure_datetime(due_at)
            if due_at is not None
            else None
        )

        self.recommended_action = action
        self.action_details = safe_details
        self.assigned_to = assignee
        self.assigned_at = utc_now()
        self.action_due_at = due
        self.action_reference_id = None
        self.approved_by = None
        self.approved_at = None
        self.rejected_by = None
        self.rejected_at = None
        self.rejection_reason = None
        self.approval_status = (
            StockoutPredictionApprovalStatus.NOT_REQUIRED
        )
        self.status = StockoutPredictionStatus.ACTION_REQUIRED

        self._record_event(
            "stockout_mitigation_action_assigned",
            actor_id=actor_id,
            details={
                "action": action.value,
                "assigned_to": assignee,
            },
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
            StockoutPredictionStatus.ACTION_REQUIRED
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
            StockoutPredictionApprovalStatus.PENDING
        )
        self.status = (
            StockoutPredictionStatus.ACTION_PENDING_APPROVAL
        )

        self._record_event(
            "stockout_mitigation_approval_requested",
            actor_id=actor_id,
            details={
                "approval_request_id": (
                    self.approval_request_id
                ),
            },
        )

    # ========================================================
    # APPROVE ACTION
    # ========================================================

    def approve_action(
        self,
        *,
        approver_id: str,
    ) -> None:
        self._require_status(
            StockoutPredictionStatus.ACTION_PENDING_APPROVAL
        )

        approver_id = required_text(
            approver_id,
            "Approver ID",
        )

        # The approval service must verify permissions,
        # approval request state, and segregation of duties.

        self.approval_status = (
            StockoutPredictionApprovalStatus.APPROVED
        )
        self.approved_by = approver_id
        self.approved_at = utc_now()
        self.status = (
            StockoutPredictionStatus.ACTION_APPROVED
        )

        self._record_event(
            "stockout_mitigation_action_approved",
            actor_id=approver_id,
        )

    # ========================================================
    # REJECT ACTION
    # ========================================================

    def reject_action(
        self,
        *,
        approver_id: str,
        reason: str,
    ) -> None:
        self._require_status(
            StockoutPredictionStatus.ACTION_PENDING_APPROVAL
        )

        approver_id = required_text(
            approver_id,
            "Approver ID",
        )
        reason = required_text(
            reason,
            "Rejection reason",
        )

        self.approval_status = (
            StockoutPredictionApprovalStatus.REJECTED
        )
        self.rejected_by = approver_id
        self.rejected_at = utc_now()
        self.rejection_reason = reason
        self.status = (
            StockoutPredictionStatus.ACTION_REJECTED
        )

        self._record_event(
            "stockout_mitigation_action_rejected",
            actor_id=approver_id,
            details={"reason": reason},
        )

    # ========================================================
    # START MITIGATION
    # ========================================================

    def start_mitigation(
        self,
        *,
        actor_id: str,
        action_reference_id: str,
    ) -> None:
        self._require_status(
            StockoutPredictionStatus.ACTION_REQUIRED,
            StockoutPredictionStatus.ACTION_APPROVED,
        )

        if not self.is_approved:
            raise ValueError(
                "Mitigation requires approval"
            )

        if self.recommended_action == StockoutPredictionAction.NONE:
            raise ValueError(
                "No mitigation action selected"
            )

        reference = required_text(
            action_reference_id,
            "Action reference ID",
        )

        # Services must create and verify the real action
        # before linking it here. This method does not
        # purchase inventory or execute warehouse transfers.

        self.action_reference_id = reference
        self.action_started_at = utc_now()
        self.status = (
            StockoutPredictionStatus.MITIGATION_IN_PROGRESS
        )

        self._record_event(
            "stockout_mitigation_started",
            actor_id=actor_id,
            details={
                "action_reference_id": reference,
                "action": self.recommended_action.value,
            },
        )

    # ========================================================
    # COMPLETE MITIGATION
    # ========================================================

    def complete_mitigation(
        self,
        *,
        actor_id: str,
        notes: str,
    ) -> None:
        self._require_status(
            StockoutPredictionStatus.MITIGATION_IN_PROGRESS
        )

        self.mitigation_notes = required_text(
            notes,
            "Mitigation notes",
        )
        self.mitigated_at = utc_now()
        self.status = StockoutPredictionStatus.MITIGATED

        self._record_event(
            "stockout_mitigation_completed",
            actor_id=actor_id,
        )

    # ========================================================
    # START MONITORING
    # ========================================================

    def start_monitoring(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            StockoutPredictionStatus.COMPLETED,
            StockoutPredictionStatus.REVIEWED,
            StockoutPredictionStatus.MITIGATED,
        )

        self.status = StockoutPredictionStatus.MONITORING

        self._record_event(
            "stockout_prediction_monitoring_started",
            actor_id=actor_id,
        )

    # ========================================================
    # RECORD ACTUAL OUTCOME
    # ========================================================

    def record_actual_outcome(
        self,
        *,
        actor_id: str,
        outcome: StockoutPredictionOutcome,
        actual_shortage_quantity: Decimal | str | float,
        actual_stockout_at: datetime | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        self._require_status(
            StockoutPredictionStatus.COMPLETED,
            StockoutPredictionStatus.REVIEWED,
            StockoutPredictionStatus.MITIGATED,
            StockoutPredictionStatus.MONITORING,
        )

        if not isinstance(outcome, StockoutPredictionOutcome):
            raise ValueError("Invalid outcome")

        if outcome == StockoutPredictionOutcome.UNKNOWN:
            raise ValueError(
                "Actual outcome must be determined"
            )

        shortage = decimal_value(
            actual_shortage_quantity,
            "actual_shortage_quantity",
        )

        actual_at = (
            ensure_datetime(actual_stockout_at)
            if actual_stockout_at is not None
            else None
        )

        if outcome in {
            StockoutPredictionOutcome.STOCKOUT_OCCURRED,
            StockoutPredictionOutcome.PARTIAL_STOCKOUT,
        } and actual_at is None:
            raise ValueError(
                "Actual stockout timestamp is required"
            )

        if outcome in {
            StockoutPredictionOutcome.NO_STOCKOUT,
            StockoutPredictionOutcome.STOCKOUT_PREVENTED,
        } and shortage > ZERO:
            raise ValueError(
                "No-stockout outcomes cannot have "
                "positive shortage quantity"
            )

        safe_metrics = json_safe(metrics or {})

        error_days = None

        if (
            actual_at is not None
            and self.predicted_stockout_at is not None
        ):
            delta = (
                actual_at
                - ensure_datetime(self.predicted_stockout_at)
            )

            error_days = (
                Decimal(str(delta.total_seconds()))
                / Decimal("86400")
            ).quantize(Decimal("0.0001"))

        self.actual_outcome = outcome
        self.actual_shortage_quantity = shortage
        self.actual_stockout_at = actual_at
        self.prediction_error_days = error_days
        self.validation_metrics = safe_metrics
        self.validation_status = (
            StockoutPredictionValidationStatus.EVALUATED
        )
        self.evaluated_by = required_text(
            actor_id,
            "Actor ID",
        )
        self.evaluated_at = utc_now()

        self._record_event(
            "stockout_prediction_outcome_recorded",
            actor_id=actor_id,
            details={
                "outcome": outcome.value,
                "actual_shortage_quantity": str(shortage),
                "prediction_error_days": (
                    str(error_days)
                    if error_days is not None
                    else None
                ),
            },
        )

    # ========================================================
    # FAIL PREDICTION
    # ========================================================

    def fail(
        self,
        *,
        actor_id: str,
        failure_code: str,
        failure_reason: str,
    ) -> None:
        self._require_status(
            StockoutPredictionStatus.QUEUED,
            StockoutPredictionStatus.PROCESSING,
        )

        self.failure_code = required_text(
            failure_code,
            "Failure code",
        )
        self.failure_reason = required_text(
            failure_reason,
            "Failure reason",
        )
        self.failed_at = utc_now()
        self.status = StockoutPredictionStatus.FAILED

        self._record_event(
            "stockout_prediction_failed",
            actor_id=actor_id,
            details={
                "failure_code": self.failure_code,
            },
        )

    # ========================================================
    # RETRY PREDICTION
    # ========================================================

    def retry(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            StockoutPredictionStatus.FAILED
        )

        self.failure_code = None
        self.failure_reason = None
        self.failed_at = None
        self.queued_at = utc_now()
        self.status = StockoutPredictionStatus.QUEUED

        self._record_event(
            "stockout_prediction_retried",
            actor_id=actor_id,
        )

    # ========================================================
    # EXPIRE PREDICTION
    # ========================================================

    def expire(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_active()

        if self.is_terminal:
            raise ValueError(
                "Prediction is already terminal"
            )

        if not self.is_expired:
            raise ValueError(
                "Prediction expiration time not reached"
            )

        if self.status == (
            StockoutPredictionStatus.MITIGATION_IN_PROGRESS
        ):
            raise ValueError(
                "Cannot expire active mitigation"
            )

        self.status = StockoutPredictionStatus.EXPIRED
        self.expired_at = utc_now()

        self._record_event(
            "stockout_prediction_expired",
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
    ) -> None:
        self._ensure_active()

        if self.is_terminal:
            raise ValueError(
                "Terminal prediction cannot be cancelled"
            )

        if self.status == (
            StockoutPredictionStatus.MITIGATION_IN_PROGRESS
        ):
            raise ValueError(
                "Active mitigation must be reconciled first"
            )

        self.cancellation_reason = required_text(
            reason,
            "Cancellation reason",
        )
        self.cancelled_by = required_text(
            actor_id,
            "Actor ID",
        )
        self.cancelled_at = utc_now()
        self.status = StockoutPredictionStatus.CANCELLED

        self._record_event(
            "stockout_prediction_cancelled",
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # ARCHIVE
    # ========================================================

    def archive(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            StockoutPredictionStatus.EXPIRED,
            StockoutPredictionStatus.CANCELLED,
            StockoutPredictionStatus.FAILED,
            StockoutPredictionStatus.MITIGATED,
            StockoutPredictionStatus.REVIEWED,
            StockoutPredictionStatus.COMPLETED,
        )

        self.status = StockoutPredictionStatus.ARCHIVED
        self.archived_at = utc_now()

        self._record_event(
            "stockout_prediction_archived",
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
            StockoutPredictionStatus.DRAFT,
            StockoutPredictionStatus.CANCELLED,
            StockoutPredictionStatus.ARCHIVED,
        )

        actor_id = required_text(
            actor_id,
            "Actor ID",
        )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = actor_id

        self._record_event(
            "stockout_prediction_soft_deleted",
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
        include_factors: bool = True,
    ) -> dict[str, Any]:

        data = {
            "id": self.id,
            "organization_id": self.organization_id,
            "prediction_number": self.prediction_number,
            "title": self.title,
            "description": self.description,
            "status": enum_value(self.status),
            "risk_level": enum_value(self.risk_level),
            "priority": enum_value(self.priority),
            "source": enum_value(self.source),
            "prediction_method": enum_value(
                self.prediction_method
            ),
            "prediction_horizon": enum_value(
                self.prediction_horizon
            ),
            "product_id": self.product_id,
            "warehouse_id": self.warehouse_id,
            "inventory_id": self.inventory_id,
            "supplier_id": self.supplier_id,
            "category_id": self.category_id,
            "demand_forecast_id": self.demand_forecast_id,
            "replenishment_plan_id": (
                self.replenishment_plan_id
            ),
            "stock_alert_id": self.stock_alert_id,
            "supplier_risk_id": self.supplier_risk_id,
            "simulation_run_id": self.simulation_run_id,
            "model_registry_id": self.model_registry_id,
            "sku": self.sku,
            "product_name": self.product_name,
            "unit_of_measure": self.unit_of_measure,
            "current_stock": serialize_decimal(
                self.current_stock
            ),
            "available_stock": serialize_decimal(
                self.available_stock
            ),
            "reserved_stock": serialize_decimal(
                self.reserved_stock
            ),
            "incoming_stock": serialize_decimal(
                self.incoming_stock
            ),
            "safety_stock": serialize_decimal(
                self.safety_stock
            ),
            "reorder_point": serialize_decimal(
                self.reorder_point
            ),
            "forecast_demand": serialize_decimal(
                self.forecast_demand
            ),
            "average_daily_demand": serialize_decimal(
                self.average_daily_demand
            ),
            "forecast_horizon_days": (
                self.forecast_horizon_days
            ),
            "supplier_lead_time_days": (
                self.supplier_lead_time_days
            ),
            "stockout_probability": serialize_decimal(
                self.stockout_probability
            ),
            "confidence_score": serialize_decimal(
                self.confidence_score
            ),
            "risk_score": serialize_decimal(
                self.risk_score
            ),
            "predicted_stockout_at": serialize_datetime(
                self.predicted_stockout_at
            ),
            "days_until_stockout": serialize_decimal(
                self.days_until_stockout
            ),
            "predicted_remaining_stock": serialize_decimal(
                self.predicted_remaining_stock
            ),
            "predicted_shortage_quantity": serialize_decimal(
                self.predicted_shortage_quantity
            ),
            "recommended_reorder_quantity": serialize_decimal(
                self.recommended_reorder_quantity
            ),
            "recommended_reorder_at": serialize_datetime(
                self.recommended_reorder_at
            ),
            "expected_replenishment_at": serialize_datetime(
                self.expected_replenishment_at
            ),
            "available_stock_gap": serialize_decimal(
                self.available_stock_gap
            ),
            "safety_stock_gap": serialize_decimal(
                self.safety_stock_gap
            ),
            "projected_stock_balance": serialize_decimal(
                self.projected_stock_balance
            ),
            "calculated_shortage": serialize_decimal(
                self.calculated_shortage
            ),
            "needs_replenishment": self.needs_replenishment,
            "currency": self.currency,
            "estimated_lost_sales": serialize_decimal(
                self.estimated_lost_sales
            ),
            "estimated_revenue_loss": serialize_decimal(
                self.estimated_revenue_loss
            ),
            "estimated_profit_loss": serialize_decimal(
                self.estimated_profit_loss
            ),
            "estimated_replenishment_cost": serialize_decimal(
                self.estimated_replenishment_cost
            ),
            "model_name": self.model_name,
            "model_version": self.model_version,
            "ai_explanation": self.ai_explanation,
            "ai_recommendations": self.ai_recommendations,
            "recommended_action": enum_value(
                self.recommended_action
            ),
            "assigned_to": self.assigned_to,
            "action_reference_id": self.action_reference_id,
            "action_due_at": serialize_datetime(
                self.action_due_at
            ),
            "requires_approval": self.requires_approval,
            "approval_status": enum_value(
                self.approval_status
            ),
            "validation_status": enum_value(
                self.validation_status
            ),
            "actual_outcome": enum_value(
                self.actual_outcome
            ),
            "actual_stockout_at": serialize_datetime(
                self.actual_stockout_at
            ),
            "actual_shortage_quantity": serialize_decimal(
                self.actual_shortage_quantity
            ),
            "prediction_error_days": serialize_decimal(
                self.prediction_error_days
            ),
            "predicted_at": serialize_datetime(
                self.predicted_at
            ),
            "completed_at": serialize_datetime(
                self.completed_at
            ),
            "reviewed_at": serialize_datetime(
                self.reviewed_at
            ),
            "mitigated_at": serialize_datetime(
                self.mitigated_at
            ),
            "expires_at": serialize_datetime(
                self.expires_at
            ),
            "is_high_risk": self.is_high_risk,
            "is_terminal": self.is_terminal,
            "is_expired": self.is_expired,
            "is_approved": self.is_approved,
            "created_at": serialize_datetime(
                self.created_at
            ),
            "updated_at": serialize_datetime(
                self.updated_at
            ),
            "is_deleted": self.is_deleted,
            "version": self.version,
        }

        if include_factors:
            data["risk_factors"] = [
                factor.to_dict()
                for factor in self.risk_factors
            ]

        if include_internal:
            data.update({
                "idempotency_key": self.idempotency_key,
                "evaluation_result_id": (
                    self.evaluation_result_id
                ),
                "agent_run_id": self.agent_run_id,
                "approval_request_id": (
                    self.approval_request_id
                ),
                "purchase_order_id": self.purchase_order_id,
                "demand_variability": serialize_decimal(
                    self.demand_variability
                ),
                "demand_growth_rate": serialize_decimal(
                    self.demand_growth_rate
                ),
                "seasonality_factor": serialize_decimal(
                    self.seasonality_factor
                ),
                "promotional_demand_factor": serialize_decimal(
                    self.promotional_demand_factor
                ),
                "model_provider": self.model_provider,
                "model_parameters": self.model_parameters,
                "feature_values": self.feature_values,
                "feature_importance": self.feature_importance,
                "prediction_intervals": (
                    self.prediction_intervals
                ),
                "uncertainty_factors": (
                    self.uncertainty_factors
                ),
                "financial_impact_details": (
                    self.financial_impact_details
                ),
                "action_details": self.action_details,
                "approved_by": self.approved_by,
                "approved_at": serialize_datetime(
                    self.approved_at
                ),
                "rejected_by": self.rejected_by,
                "rejected_at": serialize_datetime(
                    self.rejected_at
                ),
                "rejection_reason": self.rejection_reason,
                "review_notes": self.review_notes,
                "mitigation_notes": self.mitigation_notes,
                "validation_metrics": self.validation_metrics,
                "evaluated_by": self.evaluated_by,
                "evaluated_at": serialize_datetime(
                    self.evaluated_at
                ),
                "failure_code": self.failure_code,
                "failure_reason": self.failure_reason,
                "cancellation_reason": (
                    self.cancellation_reason
                ),
                "prediction_metadata": (
                    self.prediction_metadata
                ),
                "trace_id": self.trace_id,
                "correlation_id": self.correlation_id,
            })

        if include_history:
            data["prediction_history"] = (
                self.prediction_history
            )

        return data

    def __repr__(self) -> str:
        return (
            f"<StockoutPrediction("
            f"id={self.id!r}, "
            f"prediction_number={self.prediction_number!r}, "
            f"product_id={self.product_id!r}, "
            f"risk_level={enum_value(self.risk_level)!r}, "
            f"status={enum_value(self.status)!r}"
            f")>"
        )


# ============================================================
# STOCKOUT PREDICTION FACTOR
# ============================================================

class StockoutPredictionFactor(Base):
    __tablename__ = "stockout_prediction_factors"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "prediction_id",
            "name",
            name="uq_stockout_factor_prediction_name",
        ),
        ForeignKeyConstraint(
            ["organization_id", "prediction_id"],
            [
                "stockout_predictions.organization_id",
                "stockout_predictions.id",
            ],
            name="fk_stockout_factor_prediction_org",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "impact_score >= 0 AND impact_score <= 1",
            name="ck_stockout_factor_impact",
        ),
        CheckConstraint(
            "contribution_score IS NULL OR "
            "(contribution_score >= -1 AND "
            "contribution_score <= 1)",
            name="ck_stockout_factor_contribution",
        ),
        Index(
            "ix_stockout_factor_org_category",
            "organization_id",
            "category",
        ),
        Index(
            "ix_stockout_factor_prediction",
            "prediction_id",
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

    prediction_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    category: Mapped[
        StockoutFactorCategory
    ] = mapped_column(
        enum_column(
            StockoutFactorCategory,
            "stockout_factor_category",
        ),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    impact_score: Mapped[Decimal] = mapped_column(
        Numeric(6, 4),
        default=ZERO,
        nullable=False,
    )

    contribution_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    feature_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    feature_value: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    evidence: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    recommendation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_by: Mapped[str | None] = mapped_column(
        String(36),
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

    prediction: Mapped[StockoutPrediction] = relationship(
        "StockoutPrediction",
        back_populates="risk_factors",
    )

    # ========================================================
    # UPDATE FACTOR
    # ========================================================

    def update_analysis(
        self,
        *,
        impact_score: Decimal | str | float,
        contribution_score: Decimal | str | float | None = None,
        recommendation: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        self.impact_score = probability_value(
            impact_score,
            "impact_score",
        )

        if contribution_score is not None:
            self.contribution_score = decimal_value(
                contribution_score,
                "contribution_score",
                minimum=Decimal("-1"),
                maximum=ONE,
            )

        if recommendation is not None:
            self.recommendation = optional_text(
                recommendation
            )

        if evidence is not None:
            self.evidence = json_safe(evidence)

        self.updated_at = utc_now()

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "prediction_id": self.prediction_id,
            "category": enum_value(self.category),
            "name": self.name,
            "description": self.description,
            "impact_score": serialize_decimal(
                self.impact_score
            ),
            "contribution_score": serialize_decimal(
                self.contribution_score
            ),
            "feature_name": self.feature_name,
            "feature_value": self.feature_value,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
            "created_by": self.created_by,
            "created_at": serialize_datetime(
                self.created_at
            ),
            "updated_at": serialize_datetime(
                self.updated_at
            ),
        }

    def __repr__(self) -> str:
        return (
            f"<StockoutPredictionFactor("
            f"id={self.id!r}, "
            f"name={self.name!r}, "
            f"category={enum_value(self.category)!r}, "
            f"impact_score={self.impact_score!r}"
            f")>"
        )