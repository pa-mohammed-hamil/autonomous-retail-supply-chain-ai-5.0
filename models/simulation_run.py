from __future__ import annotations

"""Planned module: simulation run. Implementation pending."""
# backend/models/simulation_run.py


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


def generate_run_number() -> str:
    return f"SIM-{uuid.uuid4().hex[:18].upper()}"


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


def optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Expected string")
    return value.strip() or None


def decimal_value(
    value: Decimal | str | int | float,
    field: str,
    *,
    minimum: Decimal = Decimal("0"),
    maximum: Decimal | None = None,
) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")

    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{field} must be numeric") from None

    if not result.is_finite():
        raise ValueError(f"{field} must be finite")

    if result < minimum:
        raise ValueError(
            f"{field} must be at least {minimum}"
        )

    if maximum is not None and result > maximum:
        raise ValueError(
            f"{field} must not exceed {maximum}"
        )

    if result != result.quantize(Decimal("0.0001")):
        raise ValueError(
            f"{field} supports at most 4 decimal places"
        )

    return result


def validate_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Timezone-aware datetime required")
    return value.astimezone(timezone.utc)


def enum_value(value):
    return value.value if isinstance(value, enum.Enum) else value


def serialize_datetime(value):
    return value.isoformat() if value else None


def serialize_decimal(value):
    return str(value) if value is not None else None


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite JSON number")
        return value

    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite decimal")
        return str(value)

    if isinstance(value, enum.Enum):
        return value.value

    if isinstance(value, datetime):
        return validate_datetime(value).isoformat()

    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]

    raise ValueError(
        f"Unsupported JSON value: {type(value).__name__}"
    )


# ============================================================
# ENUMS
# ============================================================

class SimulationRunStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    QUEUED = "queued"
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    ARCHIVED = "archived"


class SimulationType(str, enum.Enum):
    DEMAND_FORECAST = "demand_forecast"
    INVENTORY_OPTIMIZATION = "inventory_optimization"
    REPLENISHMENT = "replenishment"
    SAFETY_STOCK = "safety_stock"
    SUPPLIER_RISK = "supplier_risk"
    SUPPLIER_DISRUPTION = "supplier_disruption"
    WAREHOUSE_CAPACITY = "warehouse_capacity"
    WAREHOUSE_OPERATIONS = "warehouse_operations"
    LOGISTICS_ROUTING = "logistics_routing"
    DELIVERY_DELAY = "delivery_delay"
    TRANSPORTATION_COST = "transportation_cost"
    PRICING = "pricing"
    PROMOTION = "promotion"
    SALES = "sales"
    CUSTOMER_DEMAND = "customer_demand"
    CASHFLOW = "cashflow"
    COST_OPTIMIZATION = "cost_optimization"
    DISASTER_RECOVERY = "disaster_recovery"
    DIGITAL_TWIN = "digital_twin"
    WHAT_IF = "what_if"
    MONTE_CARLO = "monte_carlo"
    MULTI_OBJECTIVE = "multi_objective"
    END_TO_END_SUPPLY_CHAIN = "end_to_end_supply_chain"
    CUSTOM = "custom"


class SimulationSource(str, enum.Enum):
    MANUAL = "manual"
    API = "api"
    SCHEDULER = "scheduler"
    AI_AGENT = "ai_agent"
    OPTIMIZATION_ENGINE = "optimization_engine"
    DIGITAL_TWIN = "digital_twin"
    FORECAST_ENGINE = "forecast_engine"
    ERP = "erp"
    WMS = "wms"
    SYSTEM = "system"


class SimulationPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"


class SimulationExecutionMode(str, enum.Enum):
    SYNCHRONOUS = "synchronous"
    ASYNCHRONOUS = "asynchronous"
    BATCH = "batch"
    DISTRIBUTED = "distributed"
    STREAMING = "streaming"


class SimulationAlgorithm(str, enum.Enum):
    RULE_BASED = "rule_based"
    HEURISTIC = "heuristic"
    LINEAR_PROGRAMMING = "linear_programming"
    MIXED_INTEGER_PROGRAMMING = "mixed_integer_programming"
    GENETIC_ALGORITHM = "genetic_algorithm"
    SIMULATED_ANNEALING = "simulated_annealing"
    MONTE_CARLO = "monte_carlo"
    DISCRETE_EVENT = "discrete_event"
    AGENT_BASED = "agent_based"
    REINFORCEMENT_LEARNING = "reinforcement_learning"
    MACHINE_LEARNING = "machine_learning"
    DEEP_LEARNING = "deep_learning"
    HYBRID_AI = "hybrid_ai"
    CUSTOM = "custom"


class SimulationRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class SimulationApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SimulationResultQuality(str, enum.Enum):
    NOT_EVALUATED = "not_evaluated"
    EXCELLENT = "excellent"
    GOOD = "good"
    ACCEPTABLE = "acceptable"
    POOR = "poor"
    INVALID = "invalid"


class SimulationRecommendationStatus(str, enum.Enum):
    NOT_GENERATED = "not_generated"
    PROPOSED = "proposed"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    IMPLEMENTED = "implemented"


# ============================================================
# SIMULATION RUN
# ============================================================

class SimulationRun(Base):
    __tablename__ = "simulation_runs"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "run_number",
            name="uq_simulation_org_run_number",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_simulation_org_idempotency",
        ),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_simulation_org_id",
        ),
        CheckConstraint(
            "progress_percentage >= 0 "
            "AND progress_percentage <= 100",
            name="ck_simulation_progress",
        ),
        CheckConstraint(
            "iteration_count >= 0",
            name="ck_simulation_iterations",
        ),
        CheckConstraint(
            "completed_iterations >= 0",
            name="ck_simulation_completed_iterations",
        ),
        CheckConstraint(
            "completed_iterations <= iteration_count",
            name="ck_simulation_iteration_limit",
        ),
        CheckConstraint(
            "retry_count >= 0",
            name="ck_simulation_retry_count",
        ),
        CheckConstraint(
            "max_retries >= 0",
            name="ck_simulation_max_retries",
        ),
        CheckConstraint(
            "retry_count <= max_retries",
            name="ck_simulation_retry_limit",
        ),
        CheckConstraint(
            "estimated_cost >= 0",
            name="ck_simulation_estimated_cost",
        ),
        CheckConstraint(
            "actual_cost >= 0",
            name="ck_simulation_actual_cost",
        ),
        CheckConstraint(
            "estimated_savings >= 0",
            name="ck_simulation_estimated_savings",
        ),
        CheckConstraint(
            "estimated_roi_percent IS NULL OR "
            "estimated_roi_percent >= -100",
            name="ck_simulation_roi",
        ),
        CheckConstraint(
            "ai_confidence IS NULL OR "
            "(ai_confidence >= 0 AND ai_confidence <= 1)",
            name="ck_simulation_ai_confidence",
        ),
        CheckConstraint(
            "risk_score IS NULL OR "
            "(risk_score >= 0 AND risk_score <= 1)",
            name="ck_simulation_risk_score",
        ),
        CheckConstraint(
            "execution_time_seconds >= 0",
            name="ck_simulation_execution_time",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_simulation_version",
        ),
        Index(
            "ix_simulation_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_simulation_org_type",
            "organization_id",
            "simulation_type",
        ),
        Index(
            "ix_simulation_org_created",
            "organization_id",
            "created_at",
        ),
        Index(
            "ix_simulation_org_warehouse",
            "organization_id",
            "warehouse_id",
        ),
        Index(
            "ix_simulation_org_product",
            "organization_id",
            "product_id",
        ),
        Index(
            "ix_simulation_org_agent",
            "organization_id",
            "ai_agent_run_id",
        ),
        Index(
            "ix_simulation_org_scenario",
            "organization_id",
            "scenario_id",
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

    run_number: Mapped[str] = mapped_column(
        String(60),
        default=generate_run_number,
        nullable=False,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # --------------------------------------------------------
    # GENERAL DETAILS
    # --------------------------------------------------------

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    simulation_type: Mapped[SimulationType] = mapped_column(
        enum_column(
            SimulationType,
            "simulation_run_type",
        ),
        nullable=False,
    )

    status: Mapped[SimulationRunStatus] = mapped_column(
        enum_column(
            SimulationRunStatus,
            "simulation_run_status",
        ),
        default=SimulationRunStatus.DRAFT,
        nullable=False,
    )

    source: Mapped[SimulationSource] = mapped_column(
        enum_column(
            SimulationSource,
            "simulation_run_source",
        ),
        default=SimulationSource.MANUAL,
        nullable=False,
    )

    priority: Mapped[SimulationPriority] = mapped_column(
        enum_column(
            SimulationPriority,
            "simulation_run_priority",
        ),
        default=SimulationPriority.NORMAL,
        nullable=False,
    )

    execution_mode: Mapped[
        SimulationExecutionMode
    ] = mapped_column(
        enum_column(
            SimulationExecutionMode,
            "simulation_run_execution_mode",
        ),
        default=SimulationExecutionMode.ASYNCHRONOUS,
        nullable=False,
    )

    algorithm: Mapped[SimulationAlgorithm] = mapped_column(
        enum_column(
            SimulationAlgorithm,
            "simulation_run_algorithm",
        ),
        default=SimulationAlgorithm.HYBRID_AI,
        nullable=False,
    )

    # --------------------------------------------------------
    # BUSINESS REFERENCES
    # --------------------------------------------------------

    scenario_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    baseline_simulation_id: Mapped[
        str | None
    ] = mapped_column(
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

    supplier_risk_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    warehouse_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    supplier_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    product_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    category_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    logistics_route_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    inventory_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    integration_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # SCENARIO CONFIGURATION
    # --------------------------------------------------------

    scenario_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    scenario_description: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    scenario_parameters: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    baseline_parameters: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    constraints: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    objective_weights: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    assumptions: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    input_data_references: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    random_seed: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    iteration_count: Mapped[int] = mapped_column(
        Integer,
        default=100,
        nullable=False,
    )

    completed_iterations: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    progress_percentage: Mapped[Decimal] = mapped_column(
        Numeric(7, 4),
        default=Decimal("0.0000"),
        nullable=False,
    )

    # --------------------------------------------------------
    # SIMULATION TIME HORIZON
    # --------------------------------------------------------

    simulation_start_date: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    simulation_end_date: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    time_step_minutes: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # --------------------------------------------------------
    # EXECUTION
    # --------------------------------------------------------

    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    queued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    resumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    execution_time_seconds: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0.0000"),
        nullable=False,
    )

    timeout_seconds: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    max_retries: Mapped[int] = mapped_column(
        Integer,
        default=3,
        nullable=False,
    )

    worker_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    job_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    execution_environment: Mapped[
        str | None
    ] = mapped_column(
        String(100),
        nullable=True,
    )

    execution_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # SIMULATION RESULTS
    # --------------------------------------------------------

    result_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    result_data: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    baseline_results: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    comparison_results: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    kpi_results: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    sensitivity_analysis: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    uncertainty_analysis: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    result_quality: Mapped[
        SimulationResultQuality
    ] = mapped_column(
        enum_column(
            SimulationResultQuality,
            "simulation_result_quality",
        ),
        default=SimulationResultQuality.NOT_EVALUATED,
        nullable=False,
    )

    result_artifact_uri: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    result_checksum: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    # --------------------------------------------------------
    # FINANCIAL ANALYSIS
    # --------------------------------------------------------

    currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    estimated_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0.0000"),
        nullable=False,
    )

    actual_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0.0000"),
        nullable=False,
    )

    estimated_savings: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0.0000"),
        nullable=False,
    )

    estimated_roi_percent: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    cost_breakdown: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # AI INTELLIGENCE
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

    ai_model_version: Mapped[str | None] = mapped_column(
        String(100),
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

    ai_analysis: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # RISK
    # --------------------------------------------------------

    risk_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    risk_level: Mapped[
        SimulationRiskLevel
    ] = mapped_column(
        enum_column(
            SimulationRiskLevel,
            "simulation_run_risk_level",
        ),
        default=SimulationRiskLevel.UNKNOWN,
        nullable=False,
    )

    risk_factors: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
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
        SimulationApprovalStatus
    ] = mapped_column(
        enum_column(
            SimulationApprovalStatus,
            "simulation_run_approval_status",
        ),
        default=SimulationApprovalStatus.NOT_REQUIRED,
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

    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    rejection_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # RECOMMENDATION IMPLEMENTATION
    # --------------------------------------------------------

    recommendation_status: Mapped[
        SimulationRecommendationStatus
    ] = mapped_column(
        enum_column(
            SimulationRecommendationStatus,
            "simulation_recommendation_status",
        ),
        default=SimulationRecommendationStatus.NOT_GENERATED,
        nullable=False,
    )

    recommendation_approval_request_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    recommendation_approved_by: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    recommendation_approved_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    implementation_reference: Mapped[
        str | None
    ] = mapped_column(
        String(150),
        nullable=True,
    )

    implemented_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # FAILURE / CANCELLATION
    # --------------------------------------------------------

    error_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    cancellation_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    cancelled_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # AUDIT / METADATA
    # --------------------------------------------------------

    simulation_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    run_history: Mapped[
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
    # COMPUTED PROPERTIES
    # ========================================================

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            SimulationRunStatus.COMPLETED,
            SimulationRunStatus.PARTIALLY_COMPLETED,
            SimulationRunStatus.FAILED,
            SimulationRunStatus.CANCELLED,
            SimulationRunStatus.TIMED_OUT,
            SimulationRunStatus.ARCHIVED,
        }

    @property
    def is_running(self) -> bool:
        return self.status == SimulationRunStatus.RUNNING

    @property
    def is_successful(self) -> bool:
        return self.status == SimulationRunStatus.COMPLETED

    @property
    def is_approved(self) -> bool:
        return (
            not self.requires_approval
            or self.approval_status
            == SimulationApprovalStatus.APPROVED
        )

    @property
    def can_retry(self) -> bool:
        return (
            self.status in {
                SimulationRunStatus.FAILED,
                SimulationRunStatus.TIMED_OUT,
            }
            and (self.retry_count or 0)
            < (self.max_retries if self.max_retries is not None else 3)
        )

    @property
    def remaining_iterations(self) -> int:
        return max(
            0,
            (self.iteration_count or 0)
            - (self.completed_iterations or 0),
        )

    @property
    def cost_variance(self) -> Decimal:
        return (
            (self.actual_cost or Decimal("0"))
            - (self.estimated_cost or Decimal("0"))
        )

    @property
    def net_estimated_benefit(self) -> Decimal:
        return (
            (self.estimated_savings or Decimal("0"))
            - (self.estimated_cost or Decimal("0"))
        )

    # ========================================================
    # INTERNAL METHODS
    # ========================================================

    def _touch(self, actor_id: str | None = None) -> None:
        self.updated_at = utc_now()
        if actor_id is not None:
            self.updated_by = actor_id

    def _ensure_active(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Simulation run has been deleted"
            )

    def _require_status(
        self,
        *statuses: SimulationRunStatus,
    ) -> None:
        self._ensure_active()

        if self.status not in statuses:
            raise ValueError(
                f"Invalid simulation status: "
                f"{enum_value(self.status)}"
            )

    def _record_event(
        self,
        event: str,
        *,
        actor_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        history = list(self.run_history or [])

        history.append({
            "event_id": generate_uuid(),
            "event": required_text(event, "Event"),
            "actor_id": actor_id,
            "timestamp": utc_now().isoformat(),
            "details": json_safe(details or {}),
        })

        self.run_history = history
        self._touch(actor_id)

    def _validate_configuration(self) -> None:
        required_text(self.name, "Name")
        required_text(self.organization_id, "Organization ID")

        if not isinstance(self.simulation_type, SimulationType):
            raise ValueError("Invalid simulation type")

        if not isinstance(self.algorithm, SimulationAlgorithm):
            raise ValueError("Invalid simulation algorithm")

        iterations = (
            self.iteration_count
            if self.iteration_count is not None
            else 100
        )

        if not isinstance(iterations, int) or iterations <= 0:
            raise ValueError(
                "iteration_count must be a positive integer"
            )

        if (
            self.completed_iterations is not None
            and self.completed_iterations > iterations
        ):
            raise ValueError(
                "Completed iterations exceed total iterations"
            )

        if (
            self.simulation_start_date is not None
            and self.simulation_end_date is not None
        ):
            start = validate_datetime(
                self.simulation_start_date
            )
            end = validate_datetime(
                self.simulation_end_date
            )

            if end <= start:
                raise ValueError(
                    "Simulation end must be after start"
                )

        if (
            self.time_step_minutes is not None
            and self.time_step_minutes <= 0
        ):
            raise ValueError(
                "time_step_minutes must be positive"
            )

        if (
            self.timeout_seconds is not None
            and self.timeout_seconds <= 0
        ):
            raise ValueError(
                "timeout_seconds must be positive"
            )

    # ========================================================
    # CONFIGURE SCENARIO
    # ========================================================

    def configure_scenario(
        self,
        *,
        parameters: dict[str, Any],
        actor_id: str,
        baseline_parameters: dict[str, Any] | None = None,
        constraints: dict[str, Any] | None = None,
        objective_weights: dict[str, Any] | None = None,
        assumptions: list[dict[str, Any]] | None = None,
        scenario_name: str | None = None,
        scenario_description: str | None = None,
        random_seed: int | None = None,
        iteration_count: int | None = None,
    ) -> None:
        self._require_status(
            SimulationRunStatus.DRAFT
        )

        if not isinstance(parameters, dict):
            raise ValueError("parameters must be a dictionary")

        if iteration_count is not None:
            if (
                isinstance(iteration_count, bool)
                or not isinstance(iteration_count, int)
                or iteration_count <= 0
            ):
                raise ValueError(
                    "iteration_count must be positive"
                )

        if random_seed is not None:
            if (
                isinstance(random_seed, bool)
                or not isinstance(random_seed, int)
                or random_seed < 0
                or random_seed > 2147483647
            ):
                raise ValueError(
                    "random_seed must be between 0 and 2147483647"
                )

        new_parameters = json_safe(parameters)
        new_baseline = json_safe(baseline_parameters or {})
        new_constraints = json_safe(constraints or {})
        new_weights = json_safe(objective_weights or {})
        new_assumptions = json_safe(assumptions or [])

        if not isinstance(new_assumptions, list) or any(
            not isinstance(item, dict)
            for item in new_assumptions
        ):
            raise ValueError(
                "assumptions must contain dictionaries"
            )

        self.scenario_parameters = new_parameters
        self.baseline_parameters = new_baseline
        self.constraints = new_constraints
        self.objective_weights = new_weights
        self.assumptions = new_assumptions
        self.scenario_name = optional_text(scenario_name)
        self.scenario_description = optional_text(
            scenario_description
        )

        if random_seed is not None:
            self.random_seed = random_seed

        if iteration_count is not None:
            self.iteration_count = iteration_count

        self._record_event(
            "simulation_scenario_configured",
            actor_id=actor_id,
            details={
                "scenario_name": self.scenario_name,
                "iteration_count": self.iteration_count,
            },
        )

    # ========================================================
    # ADD INPUT DATA REFERENCE
    # ========================================================

    def add_input_reference(
        self,
        *,
        reference_type: str,
        reference_id: str,
        actor_id: str,
        version: str | None = None,
        checksum: str | None = None,
    ) -> None:
        self._require_status(
            SimulationRunStatus.DRAFT
        )

        reference_type = required_text(
            reference_type,
            "Reference type",
        )
        reference_id = required_text(
            reference_id,
            "Reference ID",
        )

        references = list(self.input_data_references or [])

        if any(
            item.get("reference_type") == reference_type
            and item.get("reference_id") == reference_id
            for item in references
        ):
            raise ValueError(
                "Input reference already exists"
            )

        references.append({
            "reference_type": reference_type,
            "reference_id": reference_id,
            "version": version,
            "checksum": checksum,
            "added_at": utc_now().isoformat(),
        })

        self.input_data_references = references

        self._record_event(
            "simulation_input_reference_added",
            actor_id=actor_id,
            details={
                "reference_type": reference_type,
                "reference_id": reference_id,
            },
        )

    # ========================================================
    # APPROVAL
    # ========================================================

    def request_approval(
        self,
        *,
        actor_id: str,
        approval_request_id: str,
    ) -> None:
        self._require_status(
            SimulationRunStatus.DRAFT
        )

        if not self.requires_approval:
            raise ValueError(
                "Approval is not required"
            )

        self._validate_configuration()

        self.approval_request_id = required_text(
            approval_request_id,
            "Approval request ID",
        )

        self.approval_status = (
            SimulationApprovalStatus.PENDING
        )
        self.status = (
            SimulationRunStatus.PENDING_APPROVAL
        )

        self._record_event(
            "simulation_approval_requested",
            actor_id=actor_id,
        )

    def approve(
        self,
        *,
        approver_id: str,
    ) -> None:
        self._require_status(
            SimulationRunStatus.PENDING_APPROVAL
        )

        approver_id = required_text(
            approver_id,
            "Approver ID",
        )

        self._validate_configuration()

        # The approval service must verify approver authority
        # and the linked approval request before calling this.

        self.approval_status = (
            SimulationApprovalStatus.APPROVED
        )
        self.approved_by = approver_id
        self.approved_at = utc_now()
        self.status = SimulationRunStatus.APPROVED

        self._record_event(
            "simulation_approved",
            actor_id=approver_id,
        )

    def reject(
        self,
        *,
        approver_id: str,
        reason: str,
    ) -> None:
        self._require_status(
            SimulationRunStatus.PENDING_APPROVAL
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
            SimulationApprovalStatus.REJECTED
        )
        self.rejection_reason = reason
        self.status = SimulationRunStatus.DRAFT

        self._record_event(
            "simulation_approval_rejected",
            actor_id=approver_id,
            details={"reason": reason},
        )

    # ========================================================
    # QUEUE SIMULATION
    # ========================================================

    def queue(
        self,
        *,
        actor_id: str,
        scheduled_at: datetime | None = None,
        job_id: str | None = None,
    ) -> None:
        self._require_status(
            SimulationRunStatus.DRAFT,
            SimulationRunStatus.APPROVED,
        )

        self._validate_configuration()

        if self.requires_approval and not self.is_approved:
            raise ValueError(
                "Simulation approval required"
            )

        schedule = (
            validate_datetime(scheduled_at)
            if scheduled_at is not None
            else None
        )

        self.status = SimulationRunStatus.QUEUED
        self.queued_at = utc_now()
        self.scheduled_at = schedule
        self.job_id = optional_text(job_id)

        self._record_event(
            "simulation_queued",
            actor_id=actor_id,
            details={
                "job_id": self.job_id,
                "scheduled_at": serialize_datetime(schedule),
            },
        )

    # ========================================================
    # INITIALIZE
    # ========================================================

    def initialize(
        self,
        *,
        actor_id: str,
        worker_id: str,
        execution_environment: str | None = None,
    ) -> None:
        self._require_status(
            SimulationRunStatus.QUEUED
        )

        worker_id = required_text(
            worker_id,
            "Worker ID",
        )

        self.worker_id = worker_id
        self.execution_environment = optional_text(
            execution_environment
        )
        self.status = SimulationRunStatus.INITIALIZING

        self._record_event(
            "simulation_initializing",
            actor_id=actor_id,
            details={"worker_id": worker_id},
        )

    # ========================================================
    # START SIMULATION
    # ========================================================

    def start(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            SimulationRunStatus.INITIALIZING
        )

        self._validate_configuration()

        self.status = SimulationRunStatus.RUNNING
        self.started_at = utc_now()
        self.paused_at = None

        self._record_event(
            "simulation_started",
            actor_id=actor_id,
        )

    # ========================================================
    # UPDATE PROGRESS
    # ========================================================

    def update_progress(
        self,
        *,
        completed_iterations: int,
        actor_id: str,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        self._require_status(
            SimulationRunStatus.RUNNING
        )

        if (
            isinstance(completed_iterations, bool)
            or not isinstance(completed_iterations, int)
        ):
            raise ValueError(
                "completed_iterations must be an integer"
            )

        total = (
            self.iteration_count
            if self.iteration_count is not None
            else 100
        )
        current = self.completed_iterations or 0

        if completed_iterations < current:
            raise ValueError(
                "Progress cannot decrease"
            )

        if completed_iterations > total:
            raise ValueError(
                "Completed iterations exceed total"
            )

        safe_metrics = (
            json_safe(metrics)
            if metrics is not None
            else None
        )

        if safe_metrics is not None and not isinstance(
            safe_metrics, dict
        ):
            raise ValueError(
                "metrics must be a dictionary"
            )

        progress = (
            Decimal(completed_iterations)
            / Decimal(total)
            * Decimal("100")
        ).quantize(Decimal("0.0001"))

        self.completed_iterations = completed_iterations
        self.progress_percentage = progress

        if safe_metrics is not None:
            current_kpis = dict(self.kpi_results or {})
            current_kpis.update(safe_metrics)
            self.kpi_results = current_kpis

        self._record_event(
            "simulation_progress_updated",
            actor_id=actor_id,
            details={
                "completed_iterations": completed_iterations,
                "progress_percentage": str(progress),
            },
        )

    # ========================================================
    # PAUSE
    # ========================================================

    def pause(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._require_status(
            SimulationRunStatus.RUNNING
        )

        reason = required_text(
            reason,
            "Pause reason",
        )

        self.status = SimulationRunStatus.PAUSED
        self.paused_at = utc_now()

        self._record_event(
            "simulation_paused",
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # RESUME
    # ========================================================

    def resume(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            SimulationRunStatus.PAUSED
        )

        self.status = SimulationRunStatus.RUNNING
        self.resumed_at = utc_now()
        self.paused_at = None

        self._record_event(
            "simulation_resumed",
            actor_id=actor_id,
        )

    # ========================================================
    # RECORD RESULTS
    # ========================================================

    def record_results(
        self,
        *,
        results: dict[str, Any],
        summary: str,
        actor_id: str,
        kpis: dict[str, Any] | None = None,
        baseline_results: dict[str, Any] | None = None,
        comparison_results: dict[str, Any] | None = None,
        sensitivity_analysis: dict[str, Any] | None = None,
        uncertainty_analysis: dict[str, Any] | None = None,
        artifact_uri: str | None = None,
        artifact_checksum: str | None = None,
    ) -> None:
        self._require_status(
            SimulationRunStatus.RUNNING,
            SimulationRunStatus.PAUSED,
        )

        if not isinstance(results, dict):
            raise ValueError(
                "results must be a dictionary"
            )

        safe_results = json_safe(results)
        safe_kpis = json_safe(kpis or {})
        safe_baseline = json_safe(baseline_results or {})
        safe_comparison = json_safe(
            comparison_results or {}
        )
        safe_sensitivity = json_safe(
            sensitivity_analysis or {}
        )
        safe_uncertainty = json_safe(
            uncertainty_analysis or {}
        )
        summary = required_text(summary, "Result summary")

        self.result_data = safe_results
        self.result_summary = summary
        self.kpi_results = safe_kpis
        self.baseline_results = safe_baseline
        self.comparison_results = safe_comparison
        self.sensitivity_analysis = safe_sensitivity
        self.uncertainty_analysis = safe_uncertainty
        self.result_artifact_uri = optional_text(artifact_uri)
        self.result_checksum = optional_text(
            artifact_checksum
        )

        self._record_event(
            "simulation_results_recorded",
            actor_id=actor_id,
            details={
                "result_keys": list(safe_results.keys()),
                "artifact_uri": self.result_artifact_uri,
            },
        )

    # ========================================================
    # FINANCIAL ANALYSIS
    # ========================================================

    def update_financial_analysis(
        self,
        *,
        estimated_cost: Decimal | str | float,
        actual_cost: Decimal | str | float,
        estimated_savings: Decimal | str | float,
        actor_id: str,
        estimated_roi_percent: Decimal | str | float | None = None,
        cost_breakdown: dict[str, Any] | None = None,
    ) -> None:
        self._require_status(
            SimulationRunStatus.RUNNING,
            SimulationRunStatus.PAUSED,
        )

        cost_estimate = decimal_value(
            estimated_cost,
            "estimated_cost",
        )
        cost_actual = decimal_value(
            actual_cost,
            "actual_cost",
        )
        savings = decimal_value(
            estimated_savings,
            "estimated_savings",
        )

        roi = None
        if estimated_roi_percent is not None:
            roi = decimal_value(
                estimated_roi_percent,
                "estimated_roi_percent",
                minimum=Decimal("-100"),
            )

        safe_breakdown = json_safe(
            cost_breakdown or {}
        )

        self.estimated_cost = cost_estimate
        self.actual_cost = cost_actual
        self.estimated_savings = savings
        self.estimated_roi_percent = roi
        self.cost_breakdown = safe_breakdown

        self._record_event(
            "simulation_financial_analysis_updated",
            actor_id=actor_id,
            details={
                "estimated_cost": str(cost_estimate),
                "actual_cost": str(cost_actual),
                "estimated_savings": str(savings),
            },
        )

    # ========================================================
    # AI ANALYSIS
    # ========================================================

    def update_ai_analysis(
        self,
        *,
        model_id: str,
        confidence: Decimal | str | float,
        explanation: str,
        recommendations: list[dict[str, Any]],
        actor_id: str,
        agent_run_id: str | None = None,
        model_version: str | None = None,
        analysis: dict[str, Any] | None = None,
    ) -> None:
        self._require_status(
            SimulationRunStatus.RUNNING,
            SimulationRunStatus.PAUSED,
        )

        confidence_value = decimal_value(
            confidence,
            "confidence",
            maximum=Decimal("1"),
        )

        if not isinstance(recommendations, list) or any(
            not isinstance(item, dict)
            for item in recommendations
        ):
            raise ValueError(
                "recommendations must be a list of dictionaries"
            )

        safe_recommendations = json_safe(
            recommendations
        )
        safe_analysis = json_safe(analysis or {})

        self.ai_generated = True
        self.ai_model_id = required_text(
            model_id,
            "Model ID",
        )
        self.ai_model_version = optional_text(
            model_version
        )
        self.ai_agent_run_id = optional_text(
            agent_run_id
        )
        self.ai_confidence = confidence_value
        self.ai_explanation = required_text(
            explanation,
            "Explanation",
        )
        self.ai_recommendations = safe_recommendations
        self.ai_analysis = safe_analysis

        if safe_recommendations:
            self.recommendation_status = (
                SimulationRecommendationStatus.PROPOSED
            )

        self._record_event(
            "simulation_ai_analysis_updated",
            actor_id=actor_id,
            details={
                "model_id": model_id,
                "confidence": str(confidence_value),
                "recommendation_count": len(
                    safe_recommendations
                ),
            },
        )

    # ========================================================
    # RISK ANALYSIS
    # ========================================================

    def update_risk_analysis(
        self,
        *,
        risk_score: Decimal | str | float,
        risk_level: SimulationRiskLevel,
        risk_factors: list[dict[str, Any]],
        actor_id: str,
    ) -> None:
        self._require_status(
            SimulationRunStatus.RUNNING,
            SimulationRunStatus.PAUSED,
        )

        score = decimal_value(
            risk_score,
            "risk_score",
            maximum=Decimal("1"),
        )

        if not isinstance(risk_level, SimulationRiskLevel):
            raise ValueError("Invalid risk level")

        if not isinstance(risk_factors, list) or any(
            not isinstance(item, dict)
            for item in risk_factors
        ):
            raise ValueError(
                "risk_factors must be a list of dictionaries"
            )

        safe_factors = json_safe(risk_factors)

        self.risk_score = score
        self.risk_level = risk_level
        self.risk_factors = safe_factors

        self._record_event(
            "simulation_risk_updated",
            actor_id=actor_id,
            details={
                "risk_score": str(score),
                "risk_level": risk_level.value,
            },
        )

    # ========================================================
    # EVALUATE RESULT QUALITY
    # ========================================================

    def evaluate_quality(
        self,
        *,
        quality: SimulationResultQuality,
        actor_id: str,
        evaluation_metrics: dict[str, Any] | None = None,
    ) -> None:
        self._require_status(
            SimulationRunStatus.RUNNING,
            SimulationRunStatus.PAUSED,
            SimulationRunStatus.COMPLETED,
            SimulationRunStatus.PARTIALLY_COMPLETED,
        )

        if not isinstance(quality, SimulationResultQuality):
            raise ValueError("Invalid result quality")

        safe_metrics = json_safe(
            evaluation_metrics or {}
        )

        self.result_quality = quality

        metadata = dict(self.simulation_metadata or {})
        metadata["evaluation_metrics"] = safe_metrics
        self.simulation_metadata = metadata

        self._record_event(
            "simulation_quality_evaluated",
            actor_id=actor_id,
            details={"quality": quality.value},
        )

    # ========================================================
    # COMPLETE
    # ========================================================

    def complete(
        self,
        *,
        actor_id: str,
        execution_time_seconds: Decimal | str | float,
        partial: bool = False,
    ) -> None:
        self._require_status(
            SimulationRunStatus.RUNNING,
            SimulationRunStatus.PAUSED,
        )

        duration = decimal_value(
            execution_time_seconds,
            "execution_time_seconds",
        )

        if not self.result_summary:
            raise ValueError(
                "Simulation results must be recorded"
            )

        total = (
            self.iteration_count
            if self.iteration_count is not None
            else 100
        )
        completed = self.completed_iterations or 0

        if not partial and completed != total:
            raise ValueError(
                "All iterations must finish before completion"
            )

        if partial and completed >= total:
            raise ValueError(
                "Use full completion for all iterations"
            )

        if partial and completed == 0:
            raise ValueError(
                "Partial completion requires completed work"
            )

        self.status = (
            SimulationRunStatus.PARTIALLY_COMPLETED
            if partial
            else SimulationRunStatus.COMPLETED
        )

        self.completed_at = utc_now()
        self.execution_time_seconds = duration

        if not partial:
            self.progress_percentage = Decimal("100.0000")

        self._record_event(
            "simulation_completed",
            actor_id=actor_id,
            details={
                "partial": partial,
                "execution_time_seconds": str(duration),
            },
        )

    # ========================================================
    # FAIL
    # ========================================================

    def fail(
        self,
        *,
        error_code: str,
        error_message: str,
        actor_id: str,
    ) -> None:
        self._require_status(
            SimulationRunStatus.INITIALIZING,
            SimulationRunStatus.RUNNING,
            SimulationRunStatus.PAUSED,
        )

        code = required_text(
            error_code,
            "Error code",
        )
        message = required_text(
            error_message,
            "Error message",
        )

        self.error_code = code
        self.error_message = message
        self.failed_at = utc_now()
        self.status = SimulationRunStatus.FAILED

        self._record_event(
            "simulation_failed",
            actor_id=actor_id,
            details={"error_code": code},
        )

    # ========================================================
    # TIMEOUT
    # ========================================================

    def mark_timed_out(
        self,
        *,
        actor_id: str,
        reason: str = "Simulation execution timed out",
    ) -> None:
        self._require_status(
            SimulationRunStatus.INITIALIZING,
            SimulationRunStatus.RUNNING,
            SimulationRunStatus.PAUSED,
        )

        self.error_code = "SIMULATION_TIMEOUT"
        self.error_message = required_text(
            reason,
            "Timeout reason",
        )
        self.failed_at = utc_now()
        self.status = SimulationRunStatus.TIMED_OUT

        self._record_event(
            "simulation_timed_out",
            actor_id=actor_id,
        )

    # ========================================================
    # RETRY
    # ========================================================

    def retry(
        self,
        *,
        actor_id: str,
        new_job_id: str | None = None,
    ) -> None:
        self._ensure_active()

        if not self.can_retry:
            raise ValueError(
                "Simulation cannot be retried"
            )

        self.retry_count = (self.retry_count or 0) + 1
        self.status = SimulationRunStatus.QUEUED
        self.queued_at = utc_now()
        self.job_id = optional_text(new_job_id)

        self.started_at = None
        self.paused_at = None
        self.resumed_at = None
        self.completed_at = None
        self.failed_at = None
        self.worker_id = None

        self.completed_iterations = 0
        self.progress_percentage = Decimal("0.0000")
        self.execution_time_seconds = Decimal("0.0000")

        self.result_summary = None
        self.result_data = {}
        self.baseline_results = {}
        self.comparison_results = {}
        self.kpi_results = {}
        self.sensitivity_analysis = {}
        self.uncertainty_analysis = {}
        self.result_quality = (
            SimulationResultQuality.NOT_EVALUATED
        )
        self.result_artifact_uri = None
        self.result_checksum = None

        self.ai_generated = False
        self.ai_model_id = None
        self.ai_model_version = None
        self.ai_agent_run_id = None
        self.ai_confidence = None
        self.ai_explanation = None
        self.ai_recommendations = []
        self.ai_analysis = {}

        self.risk_score = None
        self.risk_level = SimulationRiskLevel.UNKNOWN
        self.risk_factors = []

        self.recommendation_status = (
            SimulationRecommendationStatus.NOT_GENERATED
        )
        self.recommendation_approval_request_id = None
        self.recommendation_approved_by = None
        self.recommendation_approved_at = None
        self.implementation_reference = None
        self.implemented_at = None

        self.error_code = None
        self.error_message = None

        self._record_event(
            "simulation_retry_queued",
            actor_id=actor_id,
            details={
                "retry_count": self.retry_count,
                "job_id": self.job_id,
            },
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
                "Terminal simulation cannot be cancelled"
            )

        reason = required_text(
            reason,
            "Cancellation reason",
        )

        self.status = SimulationRunStatus.CANCELLED
        self.cancelled_at = utc_now()
        self.cancelled_by = required_text(
            actor_id,
            "Actor ID",
        )
        self.cancellation_reason = reason

        self._record_event(
            "simulation_cancelled",
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # REQUEST RECOMMENDATION APPROVAL
    # ========================================================

    def request_recommendation_approval(
        self,
        *,
        actor_id: str,
        approval_request_id: str,
    ) -> None:
        self._require_status(
            SimulationRunStatus.COMPLETED,
            SimulationRunStatus.PARTIALLY_COMPLETED,
        )

        if self.recommendation_status != (
            SimulationRecommendationStatus.PROPOSED
        ):
            raise ValueError(
                "No proposed recommendations available"
            )

        request_id = required_text(
            approval_request_id,
            "Approval request ID",
        )

        self.recommendation_approval_request_id = request_id
        self.recommendation_status = (
            SimulationRecommendationStatus.PENDING_APPROVAL
        )

        self._record_event(
            "simulation_recommendation_approval_requested",
            actor_id=actor_id,
            details={"approval_request_id": request_id},
        )

    # ========================================================
    # APPROVE RECOMMENDATIONS
    # ========================================================

    def approve_recommendations(
        self,
        *,
        approver_id: str,
    ) -> None:
        self._require_status(
            SimulationRunStatus.COMPLETED,
            SimulationRunStatus.PARTIALLY_COMPLETED,
        )

        if self.recommendation_status != (
            SimulationRecommendationStatus.PENDING_APPROVAL
        ):
            raise ValueError(
                "Recommendation approval is not pending"
            )

        approver_id = required_text(
            approver_id,
            "Approver ID",
        )

        # Service layer must verify the linked approval
        # request and the approver's permissions.

        self.recommendation_status = (
            SimulationRecommendationStatus.APPROVED
        )
        self.recommendation_approved_by = approver_id
        self.recommendation_approved_at = utc_now()

        self._record_event(
            "simulation_recommendations_approved",
            actor_id=approver_id,
        )

    # ========================================================
    # REJECT RECOMMENDATIONS
    # ========================================================

    def reject_recommendations(
        self,
        *,
        approver_id: str,
        reason: str,
    ) -> None:
        self._require_status(
            SimulationRunStatus.COMPLETED,
            SimulationRunStatus.PARTIALLY_COMPLETED,
        )

        if self.recommendation_status != (
            SimulationRecommendationStatus.PENDING_APPROVAL
        ):
            raise ValueError(
                "Recommendation approval is not pending"
            )

        approver_id = required_text(
            approver_id,
            "Approver ID",
        )
        reason = required_text(
            reason,
            "Rejection reason",
        )

        self.recommendation_status = (
            SimulationRecommendationStatus.REJECTED
        )

        self._record_event(
            "simulation_recommendations_rejected",
            actor_id=approver_id,
            details={"reason": reason},
        )

    # ========================================================
    # RECORD IMPLEMENTATION
    # ========================================================

    def record_implementation(
        self,
        *,
        actor_id: str,
        implementation_reference: str,
    ) -> None:
        self._require_status(
            SimulationRunStatus.COMPLETED,
            SimulationRunStatus.PARTIALLY_COMPLETED,
        )

        if self.recommendation_status != (
            SimulationRecommendationStatus.APPROVED
        ):
            raise ValueError(
                "Recommendations require approval"
            )

        reference = required_text(
            implementation_reference,
            "Implementation reference",
        )

        # External execution must already be verified.
        # This method only records the completed action.

        self.implementation_reference = reference
        self.implemented_at = utc_now()
        self.recommendation_status = (
            SimulationRecommendationStatus.IMPLEMENTED
        )

        self._record_event(
            "simulation_recommendations_implemented",
            actor_id=actor_id,
            details={
                "implementation_reference": reference,
            },
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
            SimulationRunStatus.COMPLETED,
            SimulationRunStatus.PARTIALLY_COMPLETED,
            SimulationRunStatus.FAILED,
            SimulationRunStatus.CANCELLED,
            SimulationRunStatus.TIMED_OUT,
        )

        self.status = SimulationRunStatus.ARCHIVED

        self._record_event(
            "simulation_archived",
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
            SimulationRunStatus.DRAFT,
            SimulationRunStatus.CANCELLED,
            SimulationRunStatus.ARCHIVED,
        )

        actor_id = required_text(
            actor_id,
            "Actor ID",
        )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = actor_id

        self._record_event(
            "simulation_soft_deleted",
            actor_id=actor_id,
        )

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(
        self,
        *,
        include_results: bool = True,
        include_internal: bool = False,
        include_history: bool = False,
    ) -> dict[str, Any]:
        data = {
            "id": self.id,
            "organization_id": self.organization_id,
            "run_number": self.run_number,
            "name": self.name,
            "description": self.description,
            "simulation_type": enum_value(
                self.simulation_type
            ),
            "status": enum_value(self.status),
            "source": enum_value(self.source),
            "priority": enum_value(self.priority),
            "execution_mode": enum_value(
                self.execution_mode
            ),
            "algorithm": enum_value(self.algorithm),
            "scenario_id": self.scenario_id,
            "scenario_name": self.scenario_name,
            "baseline_simulation_id": (
                self.baseline_simulation_id
            ),
            "demand_forecast_id": self.demand_forecast_id,
            "replenishment_plan_id": (
                self.replenishment_plan_id
            ),
            "supplier_risk_id": self.supplier_risk_id,
            "warehouse_id": self.warehouse_id,
            "supplier_id": self.supplier_id,
            "product_id": self.product_id,
            "category_id": self.category_id,
            "logistics_route_id": self.logistics_route_id,
            "inventory_id": self.inventory_id,
            "iteration_count": self.iteration_count,
            "completed_iterations": (
                self.completed_iterations
            ),
            "remaining_iterations": (
                self.remaining_iterations
            ),
            "progress_percentage": serialize_decimal(
                self.progress_percentage
            ),
            "simulation_start_date": serialize_datetime(
                self.simulation_start_date
            ),
            "simulation_end_date": serialize_datetime(
                self.simulation_end_date
            ),
            "scheduled_at": serialize_datetime(
                self.scheduled_at
            ),
            "queued_at": serialize_datetime(
                self.queued_at
            ),
            "started_at": serialize_datetime(
                self.started_at
            ),
            "paused_at": serialize_datetime(
                self.paused_at
            ),
            "completed_at": serialize_datetime(
                self.completed_at
            ),
            "execution_time_seconds": serialize_decimal(
                self.execution_time_seconds
            ),
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "currency": self.currency,
            "estimated_cost": serialize_decimal(
                self.estimated_cost
            ),
            "actual_cost": serialize_decimal(
                self.actual_cost
            ),
            "estimated_savings": serialize_decimal(
                self.estimated_savings
            ),
            "estimated_roi_percent": serialize_decimal(
                self.estimated_roi_percent
            ),
            "cost_variance": serialize_decimal(
                self.cost_variance
            ),
            "net_estimated_benefit": serialize_decimal(
                self.net_estimated_benefit
            ),
            "ai_generated": self.ai_generated,
            "ai_confidence": serialize_decimal(
                self.ai_confidence
            ),
            "risk_score": serialize_decimal(
                self.risk_score
            ),
            "risk_level": enum_value(self.risk_level),
            "result_quality": enum_value(
                self.result_quality
            ),
            "requires_approval": self.requires_approval,
            "approval_status": enum_value(
                self.approval_status
            ),
            "recommendation_status": enum_value(
                self.recommendation_status
            ),
            "is_running": self.is_running,
            "is_successful": self.is_successful,
            "is_terminal": self.is_terminal,
            "can_retry": self.can_retry,
            "created_at": serialize_datetime(
                self.created_at
            ),
            "updated_at": serialize_datetime(
                self.updated_at
            ),
            "is_deleted": self.is_deleted,
            "version": self.version,
        }

        if include_results:
            data.update({
                "result_summary": self.result_summary,
                "result_data": self.result_data,
                "baseline_results": self.baseline_results,
                "comparison_results": self.comparison_results,
                "kpi_results": self.kpi_results,
                "sensitivity_analysis": (
                    self.sensitivity_analysis
                ),
                "uncertainty_analysis": (
                    self.uncertainty_analysis
                ),
                "ai_recommendations": (
                    self.ai_recommendations
                ),
            })

        if include_internal:
            data.update({
                "idempotency_key": self.idempotency_key,
                "scenario_parameters": (
                    self.scenario_parameters
                ),
                "baseline_parameters": (
                    self.baseline_parameters
                ),
                "constraints": self.constraints,
                "objective_weights": (
                    self.objective_weights
                ),
                "assumptions": self.assumptions,
                "input_data_references": (
                    self.input_data_references
                ),
                "random_seed": self.random_seed,
                "time_step_minutes": (
                    self.time_step_minutes
                ),
                "timeout_seconds": self.timeout_seconds,
                "worker_id": self.worker_id,
                "job_id": self.job_id,
                "execution_environment": (
                    self.execution_environment
                ),
                "execution_metadata": (
                    self.execution_metadata
                ),
                "cost_breakdown": self.cost_breakdown,
                "ai_model_id": self.ai_model_id,
                "ai_model_version": (
                    self.ai_model_version
                ),
                "ai_agent_run_id": self.ai_agent_run_id,
                "ai_explanation": self.ai_explanation,
                "ai_analysis": self.ai_analysis,
                "risk_factors": self.risk_factors,
                "approval_request_id": (
                    self.approval_request_id
                ),
                "approved_by": self.approved_by,
                "approved_at": serialize_datetime(
                    self.approved_at
                ),
                "rejection_reason": (
                    self.rejection_reason
                ),
                "recommendation_approval_request_id": (
                    self.recommendation_approval_request_id
                ),
                "recommendation_approved_by": (
                    self.recommendation_approved_by
                ),
                "recommendation_approved_at": (
                    serialize_datetime(
                        self.recommendation_approved_at
                    )
                ),
                "implementation_reference": (
                    self.implementation_reference
                ),
                "implemented_at": serialize_datetime(
                    self.implemented_at
                ),
                "result_artifact_uri": (
                    self.result_artifact_uri
                ),
                "result_checksum": self.result_checksum,
                "error_code": self.error_code,
                "error_message": self.error_message,
                "cancellation_reason": (
                    self.cancellation_reason
                ),
                "simulation_metadata": (
                    self.simulation_metadata
                ),
                "trace_id": self.trace_id,
                "correlation_id": self.correlation_id,
            })

        if include_history:
            data["run_history"] = self.run_history

        return data

    def __repr__(self) -> str:
        return (
            f"<SimulationRun("
            f"id={self.id!r}, "
            f"run_number={self.run_number!r}, "
            f"type={enum_value(self.simulation_type)!r}, "
            f"status={enum_value(self.status)!r}, "
            f"progress={self.progress_percentage}"
            f")>"
        )