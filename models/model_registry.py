from __future__ import annotations

"""Planned module: model registry. Implementation pending."""

"""
backend/models/model_registry.py

Autonomous Retail Supply Chain AI 5.0
ML / GenAI Model Registry ORM

Features:
- Multi-tenant ML model registration
- Model version and artifact tracking
- ML, DL, GenAI, RAG and agent model types
- Model lifecycle and deployment stages
- Training dataset and experiment references
- Evaluation and benchmark metrics
- Model quality gates
- Drift and monitoring metadata
- Security and governance checks
- Human approval workflows
- Deployment and rollback tracking
- Audit fields and optimistic concurrency
- Soft deletion

Python >= 3.10
SQLAlchemy >= 2.0

Shared Base:
    backend.models.base.Base

Important:
    This module stores registry metadata.
    Artifact storage, model serving, training,
    approval verification, and deployment
    must be implemented in separate services.
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
    ForeignKeyConstraint,
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


def generate_model_code() -> str:
    return f"MDL-{uuid.uuid4().hex[:16].upper()}"


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


def validate_metric(
    value: float,
    name: str,
) -> float:
    result = float(value)

    if not math.isfinite(result):
        raise ValueError(
            f"{name} must be finite"
        )

    return result


def datetime_string(
    value: datetime | None,
) -> str | None:
    return value.isoformat() if value else None


def enum_value(value: enum.Enum | None) -> str | None:
    return value.value if value is not None else None


# ============================================================
# ENUMS
# ============================================================

class ModelType(str, enum.Enum):
    CLASSIFICATION = "classification"
    REGRESSION = "regression"
    FORECASTING = "forecasting"
    ANOMALY_DETECTION = "anomaly_detection"
    RECOMMENDATION = "recommendation"
    OPTIMIZATION = "optimization"
    COMPUTER_VISION = "computer_vision"
    NLP = "nlp"
    EMBEDDING = "embedding"
    RERANKER = "reranker"
    LLM = "llm"
    GENERATIVE_AI = "generative_ai"
    RAG = "rag"
    AGENTIC_AI = "agentic_ai"
    REINFORCEMENT_LEARNING = "reinforcement_learning"
    MULTIMODAL = "multimodal"
    CUSTOM = "custom"


class ModelFramework(str, enum.Enum):
    SCIKIT_LEARN = "scikit_learn"
    PYTORCH = "pytorch"
    TENSORFLOW = "tensorflow"
    XGBOOST = "xgboost"
    LIGHTGBM = "lightgbm"
    CATBOOST = "catboost"
    HUGGING_FACE = "hugging_face"
    LANGCHAIN = "langchain"
    LANGGRAPH = "langgraph"
    ONNX = "onnx"
    PROPHET = "prophet"
    STATSMODELS = "statsmodels"
    CUSTOM = "custom"
    OTHER = "other"


class ModelRegistryStatus(str, enum.Enum):
    DRAFT = "draft"
    REGISTERED = "registered"
    VALIDATING = "validating"
    VALIDATED = "validated"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class ModelStage(str, enum.Enum):
    NONE = "none"
    DEVELOPMENT = "development"
    EXPERIMENTAL = "experimental"
    STAGING = "staging"
    PRODUCTION = "production"
    CANARY = "canary"
    SHADOW = "shadow"
    RETIRED = "retired"


class ModelSource(str, enum.Enum):
    TRAINING_PIPELINE = "training_pipeline"
    MLOPS_PIPELINE = "mlops_pipeline"
    LLMOPS_PIPELINE = "llmops_pipeline"
    EXPERIMENT_TRACKER = "experiment_tracker"
    EXTERNAL_PROVIDER = "external_provider"
    HUGGING_FACE = "hugging_face"
    MANUAL = "manual"
    IMPORTED = "imported"
    AI_AGENT = "ai_agent"


class ModelRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class ModelDeploymentStatus(str, enum.Enum):
    NOT_DEPLOYED = "not_deployed"
    DEPLOYING = "deploying"
    DEPLOYED = "deployed"
    DEGRADED = "degraded"
    FAILED = "failed"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    STOPPED = "stopped"


class ModelMonitoringStatus(str, enum.Enum):
    NOT_CONFIGURED = "not_configured"
    HEALTHY = "healthy"
    WARNING = "warning"
    DRIFT_DETECTED = "drift_detected"
    CRITICAL = "critical"
    PAUSED = "paused"


class ModelApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# ============================================================
# MODEL REGISTRY
# ============================================================

class ModelRegistry(Base):
    __tablename__ = "model_registry"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "model_code",
            name="uq_model_registry_org_code",
        ),
        UniqueConstraint(
            "organization_id",
            "model_name",
            "model_version",
            name="uq_model_registry_name_version",
        ),
        CheckConstraint(
            "training_samples >= 0",
            name="model_training_samples_nonnegative",
        ),
        CheckConstraint(
            "validation_samples >= 0",
            name="model_validation_samples_nonnegative",
        ),
        CheckConstraint(
            "test_samples >= 0",
            name="model_test_samples_nonnegative",
        ),
        CheckConstraint(
            "artifact_size_bytes IS NULL OR "
            "artifact_size_bytes >= 0",
            name="model_artifact_size_nonnegative",
        ),
        CheckConstraint(
            "quality_score IS NULL OR "
            "(quality_score >= 0 AND quality_score <= 1)",
            name="model_quality_score_range",
        ),
        CheckConstraint(
            "drift_score IS NULL OR "
            "(drift_score >= 0 AND drift_score <= 1)",
            name="model_drift_score_range",
        ),
        CheckConstraint(
            "security_score IS NULL OR "
            "(security_score >= 0 AND security_score <= 1)",
            name="model_security_score_range",
        ),
        CheckConstraint(
            "deployment_traffic_percentage >= 0 AND "
            "deployment_traffic_percentage <= 100",
            name="model_traffic_percentage_range",
        ),
        CheckConstraint(
            "deployment_count >= 0",
            name="model_deployment_count_nonnegative",
        ),
        CheckConstraint(
            "rollback_count >= 0",
            name="model_rollback_count_nonnegative",
        ),
        Index(
            "ix_model_registry_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_model_registry_org_stage",
            "organization_id",
            "stage",
        ),
        Index(
            "ix_model_registry_org_type",
            "organization_id",
            "model_type",
        ),
        Index(
            "ix_model_registry_org_deployment",
            "organization_id",
            "deployment_status",
        ),
        Index(
            "ix_model_registry_org_monitoring",
            "organization_id",
            "monitoring_status",
        ),
        Index(
            "ix_model_registry_org_created",
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

    model_code: Mapped[str] = mapped_column(
        String(40),
        default=generate_model_code,
        nullable=False,
    )

    # --------------------------------------------------------
    # MODEL IDENTITY
    # --------------------------------------------------------

    model_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    model_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    display_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    model_type: Mapped[ModelType] = mapped_column(
        enum_column(
            ModelType,
            "registry_model_type",
        ),
        nullable=False,
    )

    framework: Mapped[ModelFramework] = mapped_column(
        enum_column(
            ModelFramework,
            "registry_model_framework",
        ),
        default=ModelFramework.CUSTOM,
        nullable=False,
    )

    framework_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # --------------------------------------------------------
    # LIFECYCLE
    # --------------------------------------------------------

    status: Mapped[ModelRegistryStatus] = mapped_column(
        enum_column(
            ModelRegistryStatus,
            "registry_model_status",
        ),
        default=ModelRegistryStatus.DRAFT,
        nullable=False,
    )

    stage: Mapped[ModelStage] = mapped_column(
        enum_column(
            ModelStage,
            "registry_model_stage",
        ),
        default=ModelStage.DEVELOPMENT,
        nullable=False,
    )

    source: Mapped[ModelSource] = mapped_column(
        enum_column(
            ModelSource,
            "registry_model_source",
        ),
        default=ModelSource.TRAINING_PIPELINE,
        nullable=False,
    )

    # --------------------------------------------------------
    # OWNERSHIP
    # --------------------------------------------------------

    owner_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    team_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    project_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # BUSINESS USE CASE
    # --------------------------------------------------------

    use_case: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    business_domain: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    target_entity_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # --------------------------------------------------------
    # TRAINING AND EXPERIMENT TRACKING
    # --------------------------------------------------------

    experiment_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    experiment_run_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    training_pipeline_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    training_job_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    training_dataset_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    validation_dataset_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    test_dataset_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    training_samples: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    validation_samples: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    test_samples: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    trained_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # ARTIFACTS
    # --------------------------------------------------------

    artifact_uri: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )

    artifact_hash_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    artifact_size_bytes: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    artifact_format: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    container_image: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
    )

    source_commit_sha: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    artifact_references: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # --------------------------------------------------------
    # TRAINING CONFIGURATION
    # --------------------------------------------------------

    hyperparameters: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    training_configuration: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    feature_schema: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    input_schema: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    output_schema: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # EVALUATION
    # --------------------------------------------------------

    evaluation_result_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    evaluation_run_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    evaluation_metrics: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    quality_thresholds: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    quality_gate_passed: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    quality_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    validation_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # GOVERNANCE AND SECURITY
    # --------------------------------------------------------

    risk_level: Mapped[ModelRiskLevel] = mapped_column(
        enum_column(
            ModelRiskLevel,
            "registry_model_risk_level",
        ),
        default=ModelRiskLevel.UNKNOWN,
        nullable=False,
    )

    security_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    security_scan_passed: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    privacy_review_passed: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    bias_review_passed: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    license_verified: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
    )

    model_card_uri: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )

    governance_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # APPROVAL
    # --------------------------------------------------------

    requires_human_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    approval_status: Mapped[
        ModelApprovalStatus
    ] = mapped_column(
        enum_column(
            ModelApprovalStatus,
            "registry_model_approval_status",
        ),
        default=ModelApprovalStatus.NOT_REQUIRED,
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

    # --------------------------------------------------------
    # DEPLOYMENT
    # --------------------------------------------------------

    deployment_status: Mapped[
        ModelDeploymentStatus
    ] = mapped_column(
        enum_column(
            ModelDeploymentStatus,
            "registry_model_deployment_status",
        ),
        default=ModelDeploymentStatus.NOT_DEPLOYED,
        nullable=False,
    )

    deployment_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    deployment_environment: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    endpoint_reference: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    deployment_traffic_percentage: Mapped[
        float
    ] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
    )

    deployment_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    deployed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    deployed_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    deployment_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # ROLLBACK
    # --------------------------------------------------------

    previous_model_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    rollback_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    last_rollback_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_rollback_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # MONITORING AND DRIFT
    # --------------------------------------------------------

    monitoring_status: Mapped[
        ModelMonitoringStatus
    ] = mapped_column(
        enum_column(
            ModelMonitoringStatus,
            "registry_model_monitoring_status",
        ),
        default=ModelMonitoringStatus.NOT_CONFIGURED,
        nullable=False,
    )

    drift_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    drift_detected: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    last_monitored_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    monitoring_metrics: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    monitoring_configuration: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # AI AGENT AND INTEGRATION REFERENCES
    # --------------------------------------------------------

    agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    agent_action_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    integration_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # METADATA
    # --------------------------------------------------------

    tags: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    model_metadata: Mapped[
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
    def is_deployed(self) -> bool:
        return (
            self.deployment_status
            == ModelDeploymentStatus.DEPLOYED
            and not self.is_deleted
        )

    @property
    def is_production(self) -> bool:
        return (
            self.stage == ModelStage.PRODUCTION
            and self.is_deployed
        )

    @property
    def is_approved(self) -> bool:
        return (
            self.status == ModelRegistryStatus.APPROVED
            and self.approval_status
            == ModelApprovalStatus.APPROVED
        )

    @property
    def is_healthy(self) -> bool:
        return (
            self.is_deployed
            and self.monitoring_status
            == ModelMonitoringStatus.HEALTHY
            and not self.drift_detected
        )

    @property
    def can_promote(self) -> bool:
        return (
            not self.is_deleted
            and self.status in {
                ModelRegistryStatus.VALIDATED,
                ModelRegistryStatus.APPROVED,
            }
            and self.quality_gate_passed is True
            and self.security_scan_passed is True
            and (
                not self.requires_human_approval
                or self.is_approved
            )
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_active(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Model registry record is deleted"
            )

        if self.status in {
            ModelRegistryStatus.DEPRECATED,
            ModelRegistryStatus.ARCHIVED,
            ModelRegistryStatus.REJECTED,
        }:
            raise ValueError(
                "Model version is not active"
            )

    def _ensure_not_deployed(self) -> None:
        if self.deployment_status in {
            ModelDeploymentStatus.DEPLOYING,
            ModelDeploymentStatus.DEPLOYED,
            ModelDeploymentStatus.DEGRADED,
            ModelDeploymentStatus.ROLLING_BACK,
        }:
            raise ValueError(
                "Model is deployed or has an active "
                "deployment operation"
            )

    # ========================================================
    # REGISTER MODEL
    # ========================================================

    def register(
        self,
        *,
        artifact_uri: str,
        artifact_hash_sha256: str,
        artifact_format: str,
    ) -> None:
        self._ensure_active()

        if self.status != ModelRegistryStatus.DRAFT:
            raise ValueError(
                "Only draft models can be registered"
            )

        if not artifact_uri.strip():
            raise ValueError(
                "Artifact URI is required"
            )

        hash_value = artifact_hash_sha256.lower().strip()

        if (
            len(hash_value) != 64
            or any(
                char not in "0123456789abcdef"
                for char in hash_value
            )
        ):
            raise ValueError(
                "Valid SHA-256 artifact hash is required"
            )

        if not artifact_format.strip():
            raise ValueError(
                "Artifact format is required"
            )

        self.artifact_uri = artifact_uri
        self.artifact_hash_sha256 = hash_value
        self.artifact_format = artifact_format
        self.status = ModelRegistryStatus.REGISTERED
        self._touch()

    # ========================================================
    # START VALIDATION
    # ========================================================

    def start_validation(self) -> None:
        self._ensure_active()

        if self.status != ModelRegistryStatus.REGISTERED:
            raise ValueError(
                "Model must be registered before validation"
            )

        self.status = ModelRegistryStatus.VALIDATING
        self._touch()

    # ========================================================
    # RECORD EVALUATION
    # ========================================================

    def record_evaluation(
        self,
        *,
        evaluation_result_id: str,
        metrics: dict[str, float],
        quality_score: float,
        quality_thresholds: dict[str, Any] | None = None,
        summary: str | None = None,
    ) -> None:
        self._ensure_active()

        if self.status != ModelRegistryStatus.VALIDATING:
            raise ValueError(
                "Model must be validating"
            )

        if not evaluation_result_id:
            raise ValueError(
                "Evaluation result ID is required"
            )

        if not metrics:
            raise ValueError(
                "Evaluation metrics are required"
            )

        validated_metrics = {
            name: validate_metric(value, name)
            for name, value in metrics.items()
        }

        thresholds = dict(quality_thresholds or {})

        passed = True

        for metric_name, rule in thresholds.items():
            if metric_name not in validated_metrics:
                passed = False
                continue

            if not isinstance(rule, dict):
                raise ValueError(
                    "Threshold rule must be a dictionary"
                )

            if not rule or any(
                key not in {"min", "max"}
                for key in rule
            ):
                raise ValueError(
                    "Thresholds must use min and/or max"
                )

            value = validated_metrics[metric_name]

            if "min" in rule:
                minimum = validate_metric(
                    rule["min"],
                    f"{metric_name}.min",
                )
                if value < minimum:
                    passed = False

            if "max" in rule:
                maximum = validate_metric(
                    rule["max"],
                    f"{metric_name}.max",
                )
                if value > maximum:
                    passed = False

        self.evaluation_result_id = evaluation_result_id
        self.evaluation_metrics = validated_metrics
        self.quality_thresholds = thresholds
        self.quality_score = validate_score(
            quality_score,
            "quality_score",
        )
        self.quality_gate_passed = passed
        self.validation_summary = summary
        self.evaluated_at = utc_now()

        self._touch()

    # ========================================================
    # COMPLETE VALIDATION
    # ========================================================

    def complete_validation(self) -> None:
        self._ensure_active()

        if self.status != ModelRegistryStatus.VALIDATING:
            raise ValueError(
                "Model is not validating"
            )

        if self.quality_gate_passed is not True:
            raise ValueError(
                "Model has not passed quality gates"
            )

        if not self.evaluation_result_id:
            raise ValueError(
                "Evaluation result is required"
            )

        self.status = ModelRegistryStatus.VALIDATED
        self._touch()

    # ========================================================
    # RECORD SECURITY REVIEW
    # ========================================================

    def record_security_review(
        self,
        *,
        security_score: float,
        security_scan_passed: bool,
        privacy_review_passed: bool,
        bias_review_passed: bool,
        license_verified: bool,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            ModelRegistryStatus.REGISTERED,
            ModelRegistryStatus.VALIDATING,
            ModelRegistryStatus.VALIDATED,
        }:
            raise ValueError(
                "Security review cannot be changed now"
            )

        self.security_score = validate_score(
            security_score,
            "security_score",
        )
        self.security_scan_passed = bool(
            security_scan_passed
        )
        self.privacy_review_passed = bool(
            privacy_review_passed
        )
        self.bias_review_passed = bool(
            bias_review_passed
        )
        self.license_verified = bool(
            license_verified
        )

        self._touch()

    # ========================================================
    # REQUEST APPROVAL
    # ========================================================

    def request_approval(
        self,
        approval_request_id: str,
    ) -> None:
        self._ensure_active()

        if self.status != ModelRegistryStatus.VALIDATED:
            raise ValueError(
                "Model must be validated first"
            )

        if not approval_request_id:
            raise ValueError(
                "Approval request ID required"
            )

        if self.quality_gate_passed is not True:
            raise ValueError(
                "Model quality gate has not passed"
            )

        if self.security_scan_passed is not True:
            raise ValueError(
                "Security scan has not passed"
            )

        self.approval_request_id = approval_request_id
        self.approval_status = ModelApprovalStatus.PENDING
        self.approved_by = None
        self.approved_at = None
        self.status = ModelRegistryStatus.PENDING_APPROVAL

        self._touch()

    # ========================================================
    # APPROVE MODEL
    # ========================================================

    def approve(self, user_id: str) -> None:
        self._ensure_active()

        if self.status != (
            ModelRegistryStatus.PENDING_APPROVAL
        ):
            raise ValueError(
                "Model is not pending approval"
            )

        if not user_id:
            raise ValueError(
                "Approver ID is required"
            )

        # Verify approval request, tenant, permissions,
        # and model revision in the service layer.
        self.approval_status = ModelApprovalStatus.APPROVED
        self.approved_by = user_id
        self.approved_at = utc_now()
        self.status = ModelRegistryStatus.APPROVED

        self._touch()

    # ========================================================
    # REJECT MODEL
    # ========================================================

    def reject(
        self,
        *,
        user_id: str,
        reason: str,
    ) -> None:
        self._ensure_active()

        if self.status != (
            ModelRegistryStatus.PENDING_APPROVAL
        ):
            raise ValueError(
                "Model is not pending approval"
            )

        if not user_id or not reason.strip():
            raise ValueError(
                "User ID and reason required"
            )

        self.approval_status = ModelApprovalStatus.REJECTED
        self.rejected_by = user_id
        self.rejected_at = utc_now()
        self.rejection_reason = reason
        self.status = ModelRegistryStatus.REJECTED

        self._touch()

    # ========================================================
    # PROMOTE MODEL
    # ========================================================

    def promote(
        self,
        *,
        target_stage: ModelStage,
    ) -> None:
        self._ensure_active()

        if not self.can_promote:
            raise ValueError(
                "Model has not met promotion requirements"
            )

        if target_stage == ModelStage.NONE:
            raise ValueError(
                "Cannot promote to NONE stage"
            )

        if target_stage == ModelStage.PRODUCTION:
            if self.privacy_review_passed is not True:
                raise ValueError(
                    "Privacy review is required for production"
                )

            if self.license_verified is not True:
                raise ValueError(
                    "Model license must be verified"
                )

        self.stage = target_stage
        self._touch()

    # ========================================================
    # START DEPLOYMENT
    # ========================================================

    def start_deployment(
        self,
        *,
        deployment_id: str,
        environment: str,
        traffic_percentage: float,
    ) -> None:
        self._ensure_active()

        if not self.can_promote:
            raise ValueError(
                "Model is not eligible for deployment"
            )

        if self.deployment_status not in {
            ModelDeploymentStatus.NOT_DEPLOYED,
            ModelDeploymentStatus.STOPPED,
            ModelDeploymentStatus.FAILED,
            ModelDeploymentStatus.ROLLED_BACK,
        }:
            raise ValueError(
                "Deployment already exists or is active"
            )

        if not deployment_id or not environment.strip():
            raise ValueError(
                "Deployment ID and environment required"
            )

        traffic = float(traffic_percentage)

        if not math.isfinite(traffic) or not 0 <= traffic <= 100:
            raise ValueError(
                "Traffic percentage must be between 0 and 100"
            )

        self.deployment_id = deployment_id
        self.deployment_environment = environment
        self.deployment_traffic_percentage = traffic
        self.deployment_status = (
            ModelDeploymentStatus.DEPLOYING
        )

        self._touch()

    # ========================================================
    # MARK DEPLOYED
    # ========================================================

    def mark_deployed(
        self,
        *,
        endpoint_reference: str,
        deployed_by: str,
    ) -> None:
        self._ensure_active()

        if self.deployment_status != (
            ModelDeploymentStatus.DEPLOYING
        ):
            raise ValueError(
                "Model is not deploying"
            )

        if not endpoint_reference or not deployed_by:
            raise ValueError(
                "Endpoint reference and deployer required"
            )

        # Call after the serving platform confirms
        # deployment and health checks.
        self.endpoint_reference = endpoint_reference
        self.deployed_by = deployed_by
        self.deployed_at = utc_now()
        self.deployment_count += 1
        self.deployment_status = ModelDeploymentStatus.DEPLOYED

        self._touch()

    # ========================================================
    # DEPLOYMENT FAILURE
    # ========================================================

    def mark_deployment_failed(
        self,
        reason: str,
    ) -> None:
        self._ensure_active()

        if self.deployment_status != (
            ModelDeploymentStatus.DEPLOYING
        ):
            raise ValueError(
                "Model is not deploying"
            )

        if not reason.strip():
            raise ValueError(
                "Failure reason required"
            )

        metadata = dict(self.deployment_metadata or {})
        metadata["last_failure"] = {
            "reason": reason,
            "recorded_at": utc_now().isoformat(),
        }
        self.deployment_metadata = metadata

        self.deployment_status = ModelDeploymentStatus.FAILED
        self._touch()

    # ========================================================
    # RECORD MONITORING
    # ========================================================

    def record_monitoring(
        self,
        *,
        drift_score: float,
        drift_detected: bool,
        monitoring_status: ModelMonitoringStatus,
        metrics: dict[str, float] | None = None,
    ) -> None:
        self._ensure_active()

        if self.deployment_status not in {
            ModelDeploymentStatus.DEPLOYED,
            ModelDeploymentStatus.DEGRADED,
        }:
            raise ValueError(
                "Monitoring requires a deployed model"
            )

        if (
            drift_detected
            and monitoring_status
            == ModelMonitoringStatus.HEALTHY
        ):
            raise ValueError(
                "Drifted model cannot be marked healthy"
            )

        self.drift_score = validate_score(
            drift_score,
            "drift_score",
        )
        self.drift_detected = bool(drift_detected)
        self.monitoring_status = monitoring_status
        self.monitoring_metrics = {
            key: validate_metric(value, key)
            for key, value in (metrics or {}).items()
        }
        self.last_monitored_at = utc_now()

        if monitoring_status in {
            ModelMonitoringStatus.WARNING,
            ModelMonitoringStatus.DRIFT_DETECTED,
            ModelMonitoringStatus.CRITICAL,
        }:
            self.deployment_status = (
                ModelDeploymentStatus.DEGRADED
            )

        self._touch()

    # ========================================================
    # START ROLLBACK
    # ========================================================

    def start_rollback(
        self,
        *,
        previous_model_id: str,
        reason: str,
    ) -> None:
        self._ensure_active()

        if self.deployment_status not in {
            ModelDeploymentStatus.DEPLOYED,
            ModelDeploymentStatus.DEGRADED,
        }:
            raise ValueError(
                "Only deployed models can be rolled back"
            )

        if not previous_model_id or not reason.strip():
            raise ValueError(
                "Previous model ID and reason required"
            )

        if previous_model_id == self.id:
            raise ValueError(
                "Cannot roll back to the same model"
            )

        self.previous_model_id = previous_model_id
        self.last_rollback_reason = reason
        self.deployment_status = (
            ModelDeploymentStatus.ROLLING_BACK
        )

        self._touch()

    # ========================================================
    # COMPLETE ROLLBACK
    # ========================================================

    def complete_rollback(self) -> None:
        self._ensure_active()

        if self.deployment_status != (
            ModelDeploymentStatus.ROLLING_BACK
        ):
            raise ValueError(
                "Model is not rolling back"
            )

        # The deployment service must first confirm
        # traffic has moved to the previous version.
        self.rollback_count += 1
        self.last_rollback_at = utc_now()
        self.deployment_status = (
            ModelDeploymentStatus.ROLLED_BACK
        )
        self.deployment_traffic_percentage = 0.0
        self.stage = ModelStage.RETIRED

        self._touch()

    # ========================================================
    # STOP DEPLOYMENT
    # ========================================================

    def stop_deployment(self) -> None:
        self._ensure_active()

        if self.deployment_status not in {
            ModelDeploymentStatus.DEPLOYED,
            ModelDeploymentStatus.DEGRADED,
        }:
            raise ValueError(
                "Model is not deployed"
            )

        # Only call after the serving service has
        # confirmed shutdown or traffic removal.
        self.deployment_status = ModelDeploymentStatus.STOPPED
        self.deployment_traffic_percentage = 0.0
        self._touch()

    # ========================================================
    # DEPRECATE MODEL
    # ========================================================

    def deprecate(self) -> None:
        self._ensure_active()
        self._ensure_not_deployed()

        self.status = ModelRegistryStatus.DEPRECATED
        self.stage = ModelStage.RETIRED
        self._touch()

    # ========================================================
    # ARCHIVE MODEL
    # ========================================================

    def archive(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Model is deleted"
            )

        if self.status != ModelRegistryStatus.DEPRECATED:
            raise ValueError(
                "Model must be deprecated before archiving"
            )

        self._ensure_not_deployed()

        self.status = ModelRegistryStatus.ARCHIVED
        self._touch()

    # ========================================================
    # SOFT DELETE
    # ========================================================

    def soft_delete(self, user_id: str) -> None:
        if self.is_deleted:
            raise ValueError(
                "Model already deleted"
            )

        if not user_id:
            raise ValueError(
                "Deleting user ID required"
            )

        self._ensure_not_deployed()

        if self.status not in {
            ModelRegistryStatus.DRAFT,
            ModelRegistryStatus.REJECTED,
            ModelRegistryStatus.ARCHIVED,
        }:
            raise ValueError(
                "Only draft, rejected or archived models "
                "can be soft deleted"
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
            "model_code": self.model_code,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "display_name": self.display_name,
            "description": self.description,
            "model_type": enum_value(self.model_type),
            "framework": enum_value(self.framework),
            "framework_version": self.framework_version,
            "status": enum_value(self.status),
            "stage": enum_value(self.stage),
            "source": enum_value(self.source),
            "owner_id": self.owner_id,
            "team_id": self.team_id,
            "project_id": self.project_id,
            "use_case": self.use_case,
            "business_domain": self.business_domain,
            "target_entity_type": self.target_entity_type,
            "experiment_id": self.experiment_id,
            "experiment_run_id": self.experiment_run_id,
            "training_pipeline_id": self.training_pipeline_id,
            "training_job_id": self.training_job_id,
            "training_dataset_id": self.training_dataset_id,
            "validation_dataset_id": self.validation_dataset_id,
            "test_dataset_id": self.test_dataset_id,
            "training_samples": self.training_samples,
            "validation_samples": self.validation_samples,
            "test_samples": self.test_samples,
            "trained_at": datetime_string(self.trained_at),
            "artifact_uri": self.artifact_uri,
            "artifact_hash_sha256": self.artifact_hash_sha256,
            "artifact_size_bytes": self.artifact_size_bytes,
            "artifact_format": self.artifact_format,
            "container_image": self.container_image,
            "source_commit_sha": self.source_commit_sha,
            "artifact_references": self.artifact_references,
            "hyperparameters": self.hyperparameters,
            "training_configuration": self.training_configuration,
            "feature_schema": self.feature_schema,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "evaluation_result_id": self.evaluation_result_id,
            "evaluation_run_id": self.evaluation_run_id,
            "evaluation_metrics": self.evaluation_metrics,
            "quality_thresholds": self.quality_thresholds,
            "quality_gate_passed": self.quality_gate_passed,
            "quality_score": self.quality_score,
            "evaluated_at": datetime_string(self.evaluated_at),
            "validation_summary": self.validation_summary,
            "risk_level": enum_value(self.risk_level),
            "security_score": self.security_score,
            "security_scan_passed": self.security_scan_passed,
            "privacy_review_passed": self.privacy_review_passed,
            "bias_review_passed": self.bias_review_passed,
            "license_verified": self.license_verified,
            "model_card_uri": self.model_card_uri,
            "governance_metadata": self.governance_metadata,
            "requires_human_approval": (
                self.requires_human_approval
            ),
            "approval_status": enum_value(
                self.approval_status
            ),
            "approval_request_id": self.approval_request_id,
            "approved_by": self.approved_by,
            "approved_at": datetime_string(self.approved_at),
            "rejected_by": self.rejected_by,
            "rejected_at": datetime_string(self.rejected_at),
            "rejection_reason": self.rejection_reason,
            "deployment_status": enum_value(
                self.deployment_status
            ),
            "deployment_id": self.deployment_id,
            "deployment_environment": self.deployment_environment,
            "endpoint_reference": self.endpoint_reference,
            "deployment_traffic_percentage": (
                self.deployment_traffic_percentage
            ),
            "deployment_count": self.deployment_count,
            "deployed_at": datetime_string(self.deployed_at),
            "deployed_by": self.deployed_by,
            "deployment_metadata": self.deployment_metadata,
            "previous_model_id": self.previous_model_id,
            "rollback_count": self.rollback_count,
            "last_rollback_at": datetime_string(
                self.last_rollback_at
            ),
            "last_rollback_reason": self.last_rollback_reason,
            "monitoring_status": enum_value(
                self.monitoring_status
            ),
            "drift_score": self.drift_score,
            "drift_detected": self.drift_detected,
            "last_monitored_at": datetime_string(
                self.last_monitored_at
            ),
            "monitoring_metrics": self.monitoring_metrics,
            "monitoring_configuration": (
                self.monitoring_configuration
            ),
            "agent_run_id": self.agent_run_id,
            "agent_action_id": self.agent_action_id,
            "integration_id": self.integration_id,
            "tags": self.tags,
            "model_metadata": self.model_metadata,
            "is_deployed": self.is_deployed,
            "is_production": self.is_production,
            "is_approved": self.is_approved,
            "is_healthy": self.is_healthy,
            "can_promote": self.can_promote,
            "is_deleted": self.is_deleted,
            "version": self.version,
            "created_at": datetime_string(self.created_at),
            "updated_at": datetime_string(self.updated_at),
        }

    def __repr__(self) -> str:
        return (
            f"<ModelRegistry("
            f"id={self.id}, "
            f"name={self.model_name}, "
            f"version={self.model_version}, "
            f"stage={enum_value(self.stage)}, "
            f"status={enum_value(self.status)}"
            f")>"
        )
