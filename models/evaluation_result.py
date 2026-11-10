from __future__ import annotations

"""Planned module: evaluation result. Implementation pending."""

"""
backend/models/evaluation_result.py

Autonomous Retail Supply Chain AI 5.0
AI / ML / RAG / Agent Evaluation Result Model

Features:
- Multi-tenant evaluation results
- ML forecasting and classification evaluation
- Demand forecasting metrics
- RAG retrieval and answer quality
- Agent execution and tool-call evaluation
- Model drift and data quality evaluations
- Benchmark and dataset references
- Quality gates and threshold checks
- Human review and approval
- Evaluation artifacts and metadata
- Optimistic concurrency
- Soft deletion and audit timestamps

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


def generate_evaluation_code() -> str:
    return f"EVAL-{uuid.uuid4().hex[:16].upper()}"


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


def ensure_finite(
    value: float,
    field_name: str,
) -> float:
    numeric = float(value)

    if not math.isfinite(numeric):
        raise ValueError(
            f"{field_name} must be finite"
        )

    return numeric


def validate_unit_score(
    value: float,
    field_name: str,
) -> float:
    numeric = ensure_finite(value, field_name)

    if not 0 <= numeric <= 1:
        raise ValueError(
            f"{field_name} must be between 0 and 1"
        )

    return numeric


# ============================================================
# ENUMS
# ============================================================

class EvaluationType(str, enum.Enum):
    DEMAND_FORECAST = "demand_forecast"
    SALES_FORECAST = "sales_forecast"
    INVENTORY_FORECAST = "inventory_forecast"
    SUPPLIER_RISK = "supplier_risk"
    ANOMALY_DETECTION = "anomaly_detection"
    CLASSIFICATION = "classification"
    REGRESSION = "regression"
    RECOMMENDATION = "recommendation"
    OPTIMIZATION = "optimization"

    RAG_RETRIEVAL = "rag_retrieval"
    RAG_GENERATION = "rag_generation"
    RAG_END_TO_END = "rag_end_to_end"

    AGENT_EXECUTION = "agent_execution"
    AGENT_TOOL_CALLING = "agent_tool_calling"
    AGENT_PLANNING = "agent_planning"
    AGENT_SAFETY = "agent_safety"

    MODEL_DRIFT = "model_drift"
    DATA_DRIFT = "data_drift"
    DATA_QUALITY = "data_quality"

    LATENCY = "latency"
    COST = "cost"
    SECURITY = "security"
    BENCHMARK = "benchmark"
    CUSTOM = "custom"


class EvaluationStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EvaluationOutcome(str, enum.Enum):
    NOT_EVALUATED = "not_evaluated"
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    INCONCLUSIVE = "inconclusive"


class EvaluationSource(str, enum.Enum):
    ML_PIPELINE = "ml_pipeline"
    LLMOPS_PIPELINE = "llmops_pipeline"
    EVALUATION_ENGINE = "evaluation_engine"
    AI_AGENT = "ai_agent"
    BENCHMARK_RUNNER = "benchmark_runner"
    HUMAN_REVIEW = "human_review"
    CI_CD = "ci_cd"
    API = "api"
    MANUAL = "manual"


class EvaluationReviewStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class EvaluationSeverity(str, enum.Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ============================================================
# EVALUATION RESULT MODEL
# ============================================================

class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "evaluation_code",
            name="uq_evaluation_result_org_code",
        ),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_evaluation_result_org_id",
        ),
        CheckConstraint(
            "sample_count >= 0",
            name="evaluation_sample_count_nonnegative",
        ),
        CheckConstraint(
            "passed_count >= 0",
            name="evaluation_passed_count_nonnegative",
        ),
        CheckConstraint(
            "failed_count >= 0",
            name="evaluation_failed_count_nonnegative",
        ),
        CheckConstraint(
            "passed_count + failed_count <= sample_count",
            name="evaluation_sample_counts_valid",
        ),
        CheckConstraint(
            "overall_score IS NULL OR "
            "(overall_score >= 0 AND overall_score <= 1)",
            name="evaluation_overall_score_range",
        ),
        CheckConstraint(
            "confidence_score IS NULL OR "
            "(confidence_score >= 0 "
            "AND confidence_score <= 1)",
            name="evaluation_confidence_range",
        ),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="evaluation_latency_nonnegative",
        ),
        CheckConstraint(
            "cost_usd IS NULL OR cost_usd >= 0",
            name="evaluation_cost_nonnegative",
        ),
        Index(
            "ix_evaluation_org_type",
            "organization_id",
            "evaluation_type",
        ),
        Index(
            "ix_evaluation_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_evaluation_org_outcome",
            "organization_id",
            "outcome",
        ),
        Index(
            "ix_evaluation_org_model",
            "organization_id",
            "model_name",
        ),
        Index(
            "ix_evaluation_org_agent_run",
            "organization_id",
            "agent_run_id",
        ),
        Index(
            "ix_evaluation_org_created",
            "organization_id",
            "created_at",
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

    evaluation_code: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=generate_evaluation_code,
    )

    evaluation_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )

    # --------------------------------------------------------
    # EVALUATION INFORMATION
    # --------------------------------------------------------

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    evaluation_type: Mapped[EvaluationType] = mapped_column(
        enum_column(
            EvaluationType,
            "evaluation_result_type",
        ),
        nullable=False,
    )

    status: Mapped[EvaluationStatus] = mapped_column(
        enum_column(
            EvaluationStatus,
            "evaluation_result_status",
        ),
        default=EvaluationStatus.PENDING,
        nullable=False,
    )

    outcome: Mapped[EvaluationOutcome] = mapped_column(
        enum_column(
            EvaluationOutcome,
            "evaluation_result_outcome",
        ),
        default=EvaluationOutcome.NOT_EVALUATED,
        nullable=False,
    )

    source: Mapped[EvaluationSource] = mapped_column(
        enum_column(
            EvaluationSource,
            "evaluation_result_source",
        ),
        default=EvaluationSource.EVALUATION_ENGINE,
        nullable=False,
    )

    severity: Mapped[EvaluationSeverity] = mapped_column(
        enum_column(
            EvaluationSeverity,
            "evaluation_result_severity",
        ),
        default=EvaluationSeverity.INFO,
        nullable=False,
    )

    # --------------------------------------------------------
    # MODEL AND PIPELINE REFERENCES
    # --------------------------------------------------------

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

    pipeline_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    pipeline_run_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    # --------------------------------------------------------
    # BUSINESS REFERENCES
    # --------------------------------------------------------

    product_id: Mapped[str | None] = mapped_column(
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

    demand_forecast_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    demand_event_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    document_id: Mapped[str | None] = mapped_column(
        String(36),
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

    # --------------------------------------------------------
    # DATASET AND BENCHMARK
    # --------------------------------------------------------

    dataset_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    dataset_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    dataset_hash: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    benchmark_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    benchmark_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # --------------------------------------------------------
    # GENERAL SCORES
    # --------------------------------------------------------

    overall_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    confidence_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    sample_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    passed_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    failed_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # --------------------------------------------------------
    # CLASSIFICATION METRICS
    # --------------------------------------------------------

    accuracy: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    precision: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    recall: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    f1_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    roc_auc: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    # --------------------------------------------------------
    # REGRESSION AND FORECASTING METRICS
    # --------------------------------------------------------

    mae: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    mse: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    rmse: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    mape: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    smape: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    wape: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    r2_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    # --------------------------------------------------------
    # RAG METRICS
    # --------------------------------------------------------

    retrieval_precision: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    retrieval_recall: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    mrr: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    ndcg: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    faithfulness: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    answer_relevance: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    context_relevance: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    hallucination_rate: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    # --------------------------------------------------------
    # AGENT METRICS
    # --------------------------------------------------------

    task_success_rate: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    tool_call_accuracy: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    planning_score: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    safety_score: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    # --------------------------------------------------------
    # PERFORMANCE METRICS
    # --------------------------------------------------------

    latency_ms: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    cost_usd: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    input_tokens: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    output_tokens: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # --------------------------------------------------------
    # CUSTOM METRICS AND THRESHOLDS
    # --------------------------------------------------------

    metrics: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    thresholds: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    threshold_results: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    quality_gate_passed: Mapped[
        bool | None
    ] = mapped_column(
        Boolean,
        nullable=True,
    )

    # --------------------------------------------------------
    # FAILURE AND EXPLANATION
    # --------------------------------------------------------

    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    findings: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    recommendations: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    error_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # --------------------------------------------------------
    # EVALUATION ARTIFACTS
    # --------------------------------------------------------

    artifact_references: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    evaluation_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # HUMAN REVIEW
    # --------------------------------------------------------

    review_status: Mapped[
        EvaluationReviewStatus
    ] = mapped_column(
        enum_column(
            EvaluationReviewStatus,
            "evaluation_review_status",
        ),
        default=EvaluationReviewStatus.NOT_REQUIRED,
        nullable=False,
    )

    reviewed_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    review_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # EXECUTION TIMESTAMPS
    # --------------------------------------------------------

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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
    def is_complete(self) -> bool:
        return self.status == EvaluationStatus.COMPLETED

    @property
    def is_passed(self) -> bool:
        return (
            self.is_complete
            and self.outcome == EvaluationOutcome.PASSED
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            EvaluationStatus.COMPLETED,
            EvaluationStatus.FAILED,
            EvaluationStatus.CANCELLED,
        }

    @property
    def pass_rate(self) -> float | None:
        if self.sample_count == 0:
            return None

        return self.passed_count / self.sample_count

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_active(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Evaluation result has been deleted"
            )

    # ========================================================
    # START EVALUATION
    # ========================================================

    def start(self) -> None:
        self._ensure_active()

        if self.status != EvaluationStatus.PENDING:
            raise ValueError(
                "Only pending evaluations can start"
            )

        self.status = EvaluationStatus.RUNNING
        self.started_at = utc_now()
        self._touch()

    # ========================================================
    # UPDATE CLASSIFICATION METRICS
    # ========================================================

    def update_classification_metrics(
        self,
        *,
        accuracy: float | None = None,
        precision: float | None = None,
        recall: float | None = None,
        f1_score: float | None = None,
        roc_auc: float | None = None,
    ) -> None:
        self._ensure_active()

        if self.status != EvaluationStatus.RUNNING:
            raise ValueError(
                "Evaluation must be running"
            )

        values = {
            "accuracy": accuracy,
            "precision": precision,
            "recall": recall,
            "f1_score": f1_score,
            "roc_auc": roc_auc,
        }

        for field, value in values.items():
            if value is not None:
                setattr(
                    self,
                    field,
                    validate_unit_score(value, field),
                )

        self._touch()

    # ========================================================
    # UPDATE FORECAST METRICS
    # ========================================================

    def update_forecast_metrics(
        self,
        *,
        mae: float | None = None,
        mse: float | None = None,
        rmse: float | None = None,
        mape: float | None = None,
        smape: float | None = None,
        wape: float | None = None,
        r2_score: float | None = None,
    ) -> None:
        self._ensure_active()

        if self.status != EvaluationStatus.RUNNING:
            raise ValueError(
                "Evaluation must be running"
            )

        values = {
            "mae": mae,
            "mse": mse,
            "rmse": rmse,
            "mape": mape,
            "smape": smape,
            "wape": wape,
            "r2_score": r2_score,
        }

        for field, value in values.items():
            if value is None:
                continue

            numeric = ensure_finite(value, field)

            if field != "r2_score" and numeric < 0:
                raise ValueError(
                    f"{field} cannot be negative"
                )

            if field == "r2_score" and numeric > 1:
                raise ValueError(
                    "R2 score cannot exceed 1"
                )

            setattr(self, field, numeric)

        self._touch()

    # ========================================================
    # UPDATE RAG METRICS
    # ========================================================

    def update_rag_metrics(
        self,
        *,
        retrieval_precision: float | None = None,
        retrieval_recall: float | None = None,
        mrr: float | None = None,
        ndcg: float | None = None,
        faithfulness: float | None = None,
        answer_relevance: float | None = None,
        context_relevance: float | None = None,
        hallucination_rate: float | None = None,
    ) -> None:
        self._ensure_active()

        if self.status != EvaluationStatus.RUNNING:
            raise ValueError(
                "Evaluation must be running"
            )

        values = {
            "retrieval_precision": retrieval_precision,
            "retrieval_recall": retrieval_recall,
            "mrr": mrr,
            "ndcg": ndcg,
            "faithfulness": faithfulness,
            "answer_relevance": answer_relevance,
            "context_relevance": context_relevance,
            "hallucination_rate": hallucination_rate,
        }

        for field, value in values.items():
            if value is not None:
                setattr(
                    self,
                    field,
                    validate_unit_score(value, field),
                )

        self._touch()

    # ========================================================
    # UPDATE AGENT METRICS
    # ========================================================

    def update_agent_metrics(
        self,
        *,
        task_success_rate: float | None = None,
        tool_call_accuracy: float | None = None,
        planning_score: float | None = None,
        safety_score: float | None = None,
    ) -> None:
        self._ensure_active()

        if self.status != EvaluationStatus.RUNNING:
            raise ValueError(
                "Evaluation must be running"
            )

        values = {
            "task_success_rate": task_success_rate,
            "tool_call_accuracy": tool_call_accuracy,
            "planning_score": planning_score,
            "safety_score": safety_score,
        }

        for field, value in values.items():
            if value is not None:
                setattr(
                    self,
                    field,
                    validate_unit_score(value, field),
                )

        self._touch()

    # ========================================================
    # UPDATE PERFORMANCE METRICS
    # ========================================================

    def update_performance(
        self,
        *,
        latency_ms: float | None = None,
        cost_usd: float | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        self._ensure_active()

        if self.status != EvaluationStatus.RUNNING:
            raise ValueError(
                "Evaluation must be running"
            )

        if latency_ms is not None:
            value = ensure_finite(
                latency_ms,
                "latency_ms",
            )

            if value < 0:
                raise ValueError(
                    "Latency cannot be negative"
                )

            self.latency_ms = value

        if cost_usd is not None:
            value = ensure_finite(
                cost_usd,
                "cost_usd",
            )

            if value < 0:
                raise ValueError(
                    "Cost cannot be negative"
                )

            self.cost_usd = value

        if input_tokens is not None:
            if input_tokens < 0:
                raise ValueError(
                    "Input tokens cannot be negative"
                )

            self.input_tokens = input_tokens

        if output_tokens is not None:
            if output_tokens < 0:
                raise ValueError(
                    "Output tokens cannot be negative"
                )

            self.output_tokens = output_tokens

        self._touch()

    # ========================================================
    # UPDATE SAMPLE COUNTS
    # ========================================================

    def update_sample_counts(
        self,
        *,
        total: int,
        passed: int,
        failed: int,
    ) -> None:
        self._ensure_active()

        if self.status != EvaluationStatus.RUNNING:
            raise ValueError(
                "Evaluation must be running"
            )

        if min(total, passed, failed) < 0:
            raise ValueError(
                "Sample counts cannot be negative"
            )

        if passed + failed > total:
            raise ValueError(
                "Passed + failed exceeds total samples"
            )

        self.sample_count = total
        self.passed_count = passed
        self.failed_count = failed
        self._touch()

    # ========================================================
    # QUALITY GATE
    # ========================================================

    def evaluate_quality_gate(
        self,
        thresholds: dict[str, Any],
    ) -> bool:
        self._ensure_active()

        if self.status != EvaluationStatus.RUNNING:
            raise ValueError(
                "Evaluation must be running"
            )

        if not thresholds:
            raise ValueError(
                "At least one threshold is required"
            )

        results: dict[str, Any] = {}
        passed = True

        for metric_name, rule in thresholds.items():
            if not isinstance(rule, dict):
                raise ValueError(
                    f"Invalid threshold rule: {metric_name}"
                )

            if metric_name not in self.__mapper__.attrs:
                raise ValueError(
                    f"Unknown metric: {metric_name}"
                )

            # Only allow numeric mapped columns.
            allowed_metrics = {
                "accuracy", "precision", "recall",
                "f1_score", "roc_auc",
                "mae", "mse", "rmse", "mape",
                "smape", "wape", "r2_score",
                "retrieval_precision", "retrieval_recall",
                "mrr", "ndcg", "faithfulness",
                "answer_relevance", "context_relevance",
                "hallucination_rate",
                "task_success_rate", "tool_call_accuracy",
                "planning_score", "safety_score",
                "latency_ms", "cost_usd", "overall_score",
                "confidence_score",
            }

            if metric_name not in allowed_metrics:
                raise ValueError(
                    f"Metric is not allowed: {metric_name}"
                )

            actual = getattr(self, metric_name)

            if actual is None:
                metric_passed = False
            else:
                metric_passed = True

                if "min" in rule:
                    minimum = ensure_finite(
                        rule["min"],
                        f"{metric_name}.min",
                    )
                    metric_passed = (
                        metric_passed
                        and actual >= minimum
                    )

                if "max" in rule:
                    maximum = ensure_finite(
                        rule["max"],
                        f"{metric_name}.max",
                    )
                    metric_passed = (
                        metric_passed
                        and actual <= maximum
                    )

                if "min" not in rule and "max" not in rule:
                    raise ValueError(
                        f"No bounds for {metric_name}"
                    )

            results[metric_name] = {
                "actual": actual,
                "passed": metric_passed,
                "rule": rule,
            }

            if not metric_passed:
                passed = False

        self.thresholds = dict(thresholds)
        self.threshold_results = results
        self.quality_gate_passed = passed
        self._touch()

        return passed

    # ========================================================
    # COMPLETE EVALUATION
    # ========================================================

    def complete(
        self,
        *,
        overall_score: float | None = None,
        summary: str | None = None,
    ) -> None:
        self._ensure_active()

        if self.status != EvaluationStatus.RUNNING:
            raise ValueError(
                "Evaluation must be running"
            )

        if overall_score is not None:
            self.overall_score = validate_unit_score(
                overall_score,
                "overall_score",
            )

        self.summary = summary

        if self.quality_gate_passed is True:
            self.outcome = EvaluationOutcome.PASSED

        elif self.quality_gate_passed is False:
            self.outcome = EvaluationOutcome.FAILED

        else:
            self.outcome = EvaluationOutcome.INCONCLUSIVE

        self.status = EvaluationStatus.COMPLETED
        self.completed_at = utc_now()
        self._touch()

    # ========================================================
    # FAIL EVALUATION EXECUTION
    # ========================================================

    def fail(
        self,
        *,
        reason: str,
        error_code: str | None = None,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            EvaluationStatus.PENDING,
            EvaluationStatus.RUNNING,
        }:
            raise ValueError(
                "Evaluation cannot fail in current state"
            )

        if not reason.strip():
            raise ValueError(
                "Failure reason is required"
            )

        self.status = EvaluationStatus.FAILED
        self.outcome = EvaluationOutcome.INCONCLUSIVE
        self.failure_reason = reason
        self.error_code = error_code
        self.completed_at = utc_now()
        self._touch()

    # ========================================================
    # CANCEL EVALUATION
    # ========================================================

    def cancel(self, reason: str) -> None:
        self._ensure_active()

        if self.status not in {
            EvaluationStatus.PENDING,
            EvaluationStatus.RUNNING,
        }:
            raise ValueError(
                "Evaluation cannot be cancelled"
            )

        if not reason.strip():
            raise ValueError(
                "Cancellation reason is required"
            )

        self.status = EvaluationStatus.CANCELLED
        self.outcome = EvaluationOutcome.INCONCLUSIVE
        self.failure_reason = reason
        self.completed_at = utc_now()
        self._touch()

    # ========================================================
    # HUMAN REVIEW
    # ========================================================

    def request_review(self) -> None:
        self._ensure_active()

        if self.status != EvaluationStatus.COMPLETED:
            raise ValueError(
                "Evaluation must be completed"
            )

        self.review_status = EvaluationReviewStatus.PENDING
        self._touch()

    def approve_review(
        self,
        *,
        user_id: str,
        note: str | None = None,
    ) -> None:
        self._ensure_active()

        if self.review_status != EvaluationReviewStatus.PENDING:
            raise ValueError(
                "Evaluation is not pending review"
            )

        if not user_id:
            raise ValueError(
                "Reviewer ID is required"
            )

        self.review_status = EvaluationReviewStatus.APPROVED
        self.reviewed_by = user_id
        self.reviewed_at = utc_now()
        self.review_note = note
        self._touch()

    def reject_review(
        self,
        *,
        user_id: str,
        reason: str,
    ) -> None:
        self._ensure_active()

        if self.review_status != EvaluationReviewStatus.PENDING:
            raise ValueError(
                "Evaluation is not pending review"
            )

        if not user_id or not reason.strip():
            raise ValueError(
                "Reviewer and rejection reason required"
            )

        self.review_status = EvaluationReviewStatus.REJECTED
        self.reviewed_by = user_id
        self.reviewed_at = utc_now()
        self.review_note = reason
        self._touch()

    # ========================================================
    # ADD EVALUATION ARTIFACT
    # ========================================================

    def add_artifact(
        self,
        *,
        artifact_type: str,
        storage_key: str,
        description: str | None = None,
    ) -> None:
        self._ensure_active()

        if not artifact_type.strip() or not storage_key.strip():
            raise ValueError(
                "Artifact type and storage key are required"
            )

        artifacts = list(self.artifact_references or [])

        artifacts.append(
            {
                "type": artifact_type,
                "storage_key": storage_key,
                "description": description,
                "created_at": utc_now().isoformat(),
            }
        )

        self.artifact_references = artifacts
        self._touch()

    # ========================================================
    # SOFT DELETE
    # ========================================================

    def soft_delete(self, user_id: str) -> None:
        if self.is_deleted:
            raise ValueError(
                "Evaluation already deleted"
            )

        if not user_id:
            raise ValueError(
                "Deleting user is required"
            )

        if self.status == EvaluationStatus.RUNNING:
            raise ValueError(
                "Running evaluations cannot be deleted"
            )

        self.is_deleted = True
        self.deleted_by = user_id
        self.deleted_at = utc_now()
        self._touch()

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(self) -> dict[str, Any]:
        def dt(value: datetime | None) -> str | None:
            return value.isoformat() if value else None

        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "evaluation_code": self.evaluation_code,
            "evaluation_run_id": self.evaluation_run_id,
            "name": self.name,
            "description": self.description,
            "evaluation_type": self.evaluation_type.value,
            "status": self.status.value,
            "outcome": self.outcome.value,
            "source": self.source.value,
            "severity": self.severity.value,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "model_registry_id": self.model_registry_id,
            "pipeline_name": self.pipeline_name,
            "pipeline_run_id": self.pipeline_run_id,
            "product_id": self.product_id,
            "warehouse_id": self.warehouse_id,
            "supplier_id": self.supplier_id,
            "demand_forecast_id": self.demand_forecast_id,
            "demand_event_id": self.demand_event_id,
            "document_id": self.document_id,
            "agent_run_id": self.agent_run_id,
            "agent_action_id": self.agent_action_id,
            "dataset_name": self.dataset_name,
            "dataset_version": self.dataset_version,
            "dataset_hash": self.dataset_hash,
            "benchmark_name": self.benchmark_name,
            "benchmark_version": self.benchmark_version,
            "overall_score": self.overall_score,
            "confidence_score": self.confidence_score,
            "sample_count": self.sample_count,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "pass_rate": self.pass_rate,
            "accuracy": self.accuracy,
            "precision": self.precision,
            "recall": self.recall,
            "f1_score": self.f1_score,
            "roc_auc": self.roc_auc,
            "mae": self.mae,
            "mse": self.mse,
            "rmse": self.rmse,
            "mape": self.mape,
            "smape": self.smape,
            "wape": self.wape,
            "r2_score": self.r2_score,
            "retrieval_precision": self.retrieval_precision,
            "retrieval_recall": self.retrieval_recall,
            "mrr": self.mrr,
            "ndcg": self.ndcg,
            "faithfulness": self.faithfulness,
            "answer_relevance": self.answer_relevance,
            "context_relevance": self.context_relevance,
            "hallucination_rate": self.hallucination_rate,
            "task_success_rate": self.task_success_rate,
            "tool_call_accuracy": self.tool_call_accuracy,
            "planning_score": self.planning_score,
            "safety_score": self.safety_score,
            "latency_ms": self.latency_ms,
            "cost_usd": self.cost_usd,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "metrics": self.metrics,
            "thresholds": self.thresholds,
            "threshold_results": self.threshold_results,
            "quality_gate_passed": self.quality_gate_passed,
            "summary": self.summary,
            "findings": self.findings,
            "recommendations": self.recommendations,
            "failure_reason": self.failure_reason,
            "error_code": self.error_code,
            "artifact_references": self.artifact_references,
            "evaluation_metadata": self.evaluation_metadata,
            "review_status": self.review_status.value,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": dt(self.reviewed_at),
            "review_note": self.review_note,
            "started_at": dt(self.started_at),
            "completed_at": dt(self.completed_at),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "trace_id": self.trace_id,
            "correlation_id": self.correlation_id,
            "is_deleted": self.is_deleted,
            "version": self.version,
            "created_at": dt(self.created_at),
            "updated_at": dt(self.updated_at),
        }

    def __repr__(self) -> str:
        return (
            f"<EvaluationResult("
            f"id={self.id}, "
            f"type={self.evaluation_type.value}, "
            f"status={self.status.value}, "
            f"outcome={self.outcome.value}"
            f")>"
        )
