from __future__ import annotations


"""
backend/mlops.py

Autonomous Retail Supply Chain AI 5.0
MLOps Management API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - ML model registry
    - Model version management
    - Experiment tracking
    - Evaluation metric records
    - Model deployment approval workflow
    - Deployment state tracking
    - Monitoring metric ingestion
    - Drift detection using reported metrics
    - Tenant isolation
    - Warehouse access control
    - Idempotency
    - Optimistic concurrency

IMPORTANT:
    This module stores metadata and reported metrics.
    It does not train models, calculate drift from raw
    datasets, or deploy models to infrastructure.

    Deployment approval and deployment execution are
    separate operations. Deployment is not performed
    automatically.
"""


import asyncio
import hashlib
import json
import secrets

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from backend.permissions import (
    CurrentPrincipal,
    Permission,
    Principal,
    ResourceContext,
    permission_engine,
)


API_PREFIX = "/api/v1/mlops"

MAX_MODELS_PER_TENANT = 5000
MAX_VERSIONS_PER_MODEL = 100
MAX_EXPERIMENTS_PER_TENANT = 20000
MAX_MONITORING_RECORDS_PER_TENANT = 100000
MAX_IDEMPOTENCY_KEYS = 150000
MAX_LIST_LIMIT = 200


# ============================================================
# ENUMS
# ============================================================

class MLTaskType(str, Enum):
    FORECASTING = "forecasting"
    CLASSIFICATION = "classification"
    REGRESSION = "regression"
    ANOMALY_DETECTION = "anomaly_detection"
    RANKING = "ranking"
    CLUSTERING = "clustering"


class MLFramework(str, Enum):
    SCIKIT_LEARN = "scikit_learn"
    PYTORCH = "pytorch"
    TENSORFLOW = "tensorflow"
    XGBOOST = "xgboost"
    LIGHTGBM = "lightgbm"
    HUGGING_FACE = "hugging_face"
    CUSTOM = "custom"


class ModelVersionStatus(str, Enum):
    REGISTERED = "registered"
    VALIDATED = "validated"
    APPROVED = "approved"
    DEPLOYED = "deployed"
    ARCHIVED = "archived"


class ExperimentStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeploymentEnvironment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class DeploymentStatus(str, Enum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEPLOYED = "deployed"


class DriftStatus(str, Enum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


# ============================================================
# REQUEST MODELS
# ============================================================

class MLModelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=3,
        max_length=120,
    )

    description: str = Field(
        default="",
        max_length=2000,
    )

    task_type: MLTaskType
    framework: MLFramework

    warehouse_id: str | None = Field(
        default=None,
        max_length=128,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )


class MLModelVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_name: str = Field(
        min_length=1,
        max_length=80,
    )

    artifact_reference: str = Field(
        min_length=3,
        max_length=500,
    )

    artifact_sha256: str = Field(
        pattern=r"^[a-fA-F0-9]{64}$",
    )

    dataset_reference: str = Field(
        min_length=3,
        max_length=300,
    )

    parameters: dict[str, Any] = Field(
        default_factory=dict,
    )

    metrics: dict[str, float] = Field(
        default_factory=dict,
    )

    expected_model_version: int = Field(
        ge=1
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_metadata(self):

        if len(self.parameters) > 50:
            raise ValueError(
                "Too many model parameters"
            )

        if len(self.metrics) > 50:
            raise ValueError(
                "Too many evaluation metrics"
            )

        for name, value in self.metrics.items():
            if not name or len(name) > 100:
                raise ValueError(
                    "Invalid metric name"
                )

            if not isinstance(value, (int, float)):
                raise ValueError(
                    "Metric must be numeric"
                )

            import math

            if not math.isfinite(float(value)):
                raise ValueError(
                    "Metric must be finite"
                )

        if len(
            json.dumps(
                self.parameters,
                default=str,
            )
        ) > 16000:
            raise ValueError(
                "Model parameters are too large"
            )

        return self


class ExperimentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(
        min_length=1,
        max_length=128,
    )

    name: str = Field(
        min_length=3,
        max_length=150,
    )

    dataset_reference: str = Field(
        min_length=3,
        max_length=300,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )


class ExperimentFinish(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    status: ExperimentStatus

    metrics: dict[str, float] = Field(
        default_factory=dict,
    )

    notes: str | None = Field(
        default=None,
        max_length=2000,
    )

    @model_validator(mode="after")
    def validate_status(self):

        if self.status == ExperimentStatus.RUNNING:
            raise ValueError(
                "Finish status cannot be running"
            )

        if len(self.metrics) > 50:
            raise ValueError(
                "Too many experiment metrics"
            )

        import math

        for value in self.metrics.values():
            if not math.isfinite(float(value)):
                raise ValueError(
                    "Metrics must be finite"
                )

        return self


class ModelValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    evaluation_id: str = Field(
        min_length=1,
        max_length=128,
    )


class DeploymentRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_version_id: str = Field(
        min_length=1,
        max_length=128,
    )

    environment: DeploymentEnvironment

    reason: str = Field(
        min_length=10,
        max_length=1000,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )


class DeploymentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    approve: bool

    decision_note: str = Field(
        min_length=3,
        max_length=1000,
    )


class DeploymentConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    deployment_reference: str = Field(
        min_length=3,
        max_length=300,
    )


class MonitoringRecordCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_version_id: str = Field(
        min_length=1,
        max_length=128,
    )

    metric_name: str = Field(
        min_length=1,
        max_length=100,
    )

    metric_value: float = Field(
        allow_inf_nan=False,
    )

    warning_threshold: float = Field(
        ge=0,
        allow_inf_nan=False,
    )

    critical_threshold: float = Field(
        ge=0,
        allow_inf_nan=False,
    )

    observed_at: datetime

    source_reference: str = Field(
        min_length=3,
        max_length=300,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_thresholds(self):

        if (
            self.critical_threshold
            < self.warning_threshold
        ):
            raise ValueError(
                "Critical threshold must be >= warning"
            )

        if self.observed_at.tzinfo is None:
            raise ValueError(
                "Observation timestamp must include timezone"
            )

        if self.observed_at > datetime.now(
            timezone.utc
        ):
            raise ValueError(
                "Future monitoring timestamp is invalid"
            )

        return self


# ============================================================
# RESPONSE MODELS
# ============================================================

class MLModelResponse(BaseModel):
    model_id: str
    name: str
    description: str

    task_type: MLTaskType
    framework: MLFramework

    warehouse_id: str | None

    version: int
    version_count: int

    created_by: str
    created_at: datetime
    updated_at: datetime


class MLModelVersionResponse(BaseModel):
    model_version_id: str
    model_id: str

    version_name: str
    artifact_reference: str
    artifact_sha256: str

    dataset_reference: str

    parameters: dict[str, Any]
    metrics: dict[str, float]

    status: ModelVersionStatus
    evaluation_id: str | None

    version: int
    created_at: datetime
    updated_at: datetime


class ExperimentResponse(BaseModel):
    experiment_id: str
    model_id: str

    name: str
    dataset_reference: str

    status: ExperimentStatus
    metrics: dict[str, float]

    notes: str | None

    version: int
    started_at: datetime
    finished_at: datetime | None


class DeploymentResponse(BaseModel):
    deployment_id: str
    model_id: str
    model_version_id: str

    environment: DeploymentEnvironment
    status: DeploymentStatus

    reason: str

    requested_by: str
    approved_by: str | None

    decision_note: str | None
    deployment_reference: str | None

    version: int
    created_at: datetime
    updated_at: datetime


class MonitoringRecordResponse(BaseModel):
    monitoring_id: str

    model_id: str
    model_version_id: str

    metric_name: str
    metric_value: float

    warning_threshold: float
    critical_threshold: float

    drift_status: DriftStatus

    source_reference: str
    observed_at: datetime
    created_at: datetime


class MLOpsSummaryResponse(BaseModel):
    total_models: int
    total_model_versions: int
    total_experiments: int

    running_experiments: int
    completed_experiments: int

    deployment_requests: int
    deployed_records: int

    monitoring_records: int
    warning_records: int
    critical_records: int


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass
class MLModelRecord:
    model_id: str
    tenant_id: str

    name: str
    description: str

    task_type: MLTaskType
    framework: MLFramework

    warehouse_id: str | None
    created_by: str

    version: int = 1

    version_ids: list[str] = field(
        default_factory=list
    )

    created_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )


@dataclass
class MLModelVersionRecord:
    model_version_id: str
    tenant_id: str
    model_id: str

    version_name: str
    artifact_reference: str
    artifact_sha256: str
    dataset_reference: str

    parameters: dict[str, Any]
    metrics: dict[str, float]

    status: ModelVersionStatus = (
        ModelVersionStatus.REGISTERED
    )

    evaluation_id: str | None = None

    version: int = 1

    created_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )


@dataclass
class ExperimentRecord:
    experiment_id: str
    tenant_id: str
    model_id: str

    name: str
    dataset_reference: str

    status: ExperimentStatus = (
        ExperimentStatus.RUNNING
    )

    metrics: dict[str, float] = field(
        default_factory=dict
    )

    notes: str | None = None

    version: int = 1

    started_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    finished_at: datetime | None = None


@dataclass
class DeploymentRecord:
    deployment_id: str
    tenant_id: str

    model_id: str
    model_version_id: str

    environment: DeploymentEnvironment

    reason: str
    requested_by: str

    status: DeploymentStatus = (
        DeploymentStatus.REQUESTED
    )

    approved_by: str | None = None
    decision_note: str | None = None
    deployment_reference: str | None = None

    version: int = 1

    created_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint(
    operation: str,
    payload: BaseModel,
    resource_id: str | None = None,
) -> str:

    canonical = json.dumps(
        {
            "operation": operation,
            "resource_id": resource_id,
            "payload": payload.model_dump(
                mode="json",
                exclude={"source_request_id"},
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def require_mlops_access(
    principal: Principal,
    warehouse_id: str | None,
    *,
    write: bool,
    approve: bool = False,
) -> None:

    if approve:
        permission = Permission.AI_AGENT_CONFIGURE
    elif write:
        permission = Permission.AI_AGENT_CONFIGURE
    else:
        permission = Permission.ANALYTICS_READ

    # Global models require tenant-wide access.
    # Warehouse-scoped users cannot access global models.
    if warehouse_id is None:
        if principal.allowed_warehouse_ids is not None:
            raise HTTPException(
                status_code=403,
                detail="Global model access denied",
            )

    elif (
        principal.allowed_warehouse_ids is not None
        and warehouse_id
        not in principal.allowed_warehouse_ids
    ):
        raise HTTPException(
            status_code=403,
            detail="Warehouse access denied",
        )

    decision = permission_engine.evaluate(
        principal,
        permission,
        ResourceContext(
            tenant_id=principal.tenant_id,
            warehouse_id=warehouse_id,
        ),
    )

    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail="MLOps access denied",
        )


def to_model(
    record: MLModelRecord,
) -> MLModelResponse:

    return MLModelResponse(
        model_id=record.model_id,
        name=record.name,
        description=record.description,
        task_type=record.task_type,
        framework=record.framework,
        warehouse_id=record.warehouse_id,
        version=record.version,
        version_count=len(record.version_ids),
        created_by=record.created_by,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def to_version(
    record: MLModelVersionRecord,
) -> MLModelVersionResponse:

    return MLModelVersionResponse(
        model_version_id=record.model_version_id,
        model_id=record.model_id,
        version_name=record.version_name,
        artifact_reference=record.artifact_reference,
        artifact_sha256=record.artifact_sha256,
        dataset_reference=record.dataset_reference,
        parameters=json.loads(
            json.dumps(record.parameters)
        ),
        metrics=dict(record.metrics),
        status=record.status,
        evaluation_id=record.evaluation_id,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def to_experiment(
    record: ExperimentRecord,
) -> ExperimentResponse:

    return ExperimentResponse(
        experiment_id=record.experiment_id,
        model_id=record.model_id,
        name=record.name,
        dataset_reference=record.dataset_reference,
        status=record.status,
        metrics=dict(record.metrics),
        notes=record.notes,
        version=record.version,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


def to_deployment(
    record: DeploymentRecord,
) -> DeploymentResponse:

    return DeploymentResponse(
        deployment_id=record.deployment_id,
        model_id=record.model_id,
        model_version_id=record.model_version_id,
        environment=record.environment,
        status=record.status,
        reason=record.reason,
        requested_by=record.requested_by,
        approved_by=record.approved_by,
        decision_note=record.decision_note,
        deployment_reference=record.deployment_reference,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


# ============================================================
# MLOPS STORE
# ============================================================

class MLOpsStore:

    def __init__(self):

        self._models: dict[
            str, MLModelRecord
        ] = {}

        self._versions: dict[
            str, MLModelVersionRecord
        ] = {}

        self._experiments: dict[
            str, ExperimentRecord
        ] = {}

        self._deployments: dict[
            str, DeploymentRecord
        ] = {}

        self._monitoring: dict[
            str, MonitoringRecordResponse
        ] = {}

        self._monitoring_tenants: dict[
            str, str
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    @staticmethod
    def _check_version(
        actual: int,
        expected: int,
    ) -> None:

        if actual != expected:
            raise HTTPException(
                status_code=409,
                detail="Version conflict",
            )

    def _get_model(
        self,
        principal: Principal,
        model_id: str,
        *,
        write: bool,
    ) -> MLModelRecord:

        record = self._models.get(model_id)

        if (
            record is None
            or record.tenant_id
            != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Model not found",
            )

        require_mlops_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    def _get_version(
        self,
        principal: Principal,
        version_id: str,
        *,
        write: bool,
    ) -> MLModelVersionRecord:

        record = self._versions.get(
            version_id
        )

        if (
            record is None
            or record.tenant_id
            != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Model version not found",
            )

        self._get_model(
            principal,
            record.model_id,
            write=write,
        )

        return record

    def _get_deployment(
        self,
        principal: Principal,
        deployment_id: str,
        *,
        write: bool,
    ) -> DeploymentRecord:

        record = self._deployments.get(
            deployment_id
        )

        if (
            record is None
            or record.tenant_id
            != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Deployment request not found",
            )

        self._get_model(
            principal,
            record.model_id,
            write=write,
        )

        return record

    def _idempotent_result(
        self,
        key: tuple[str, str, str],
        request_hash: str,
    ) -> str | None:

        previous = self._idempotency.get(
            key
        )

        if previous is None:
            return None

        old_hash, result_id = previous

        if old_hash != request_hash:
            raise HTTPException(
                status_code=409,
                detail="Idempotency conflict",
            )

        return result_id

    def _check_idempotency_capacity(self):

        if (
            len(self._idempotency)
            >= MAX_IDEMPOTENCY_KEYS
        ):
            raise HTTPException(
                status_code=503,
                detail="Idempotency capacity reached",
            )

    async def create_model(
        self,
        *,
        principal: Principal,
        payload: MLModelCreate,
    ) -> MLModelResponse:

        require_mlops_access(
            principal,
            payload.warehouse_id,
            write=True,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = fingerprint(
            "create_model",
            payload,
        )

        async with self._lock:

            previous = self._idempotent_result(
                key,
                request_hash,
            )

            if previous:
                return to_model(
                    self._get_model(
                        principal,
                        previous,
                        write=False,
                    )
                )

            count = sum(
                record.tenant_id
                == principal.tenant_id
                for record in self._models.values()
            )

            if count >= MAX_MODELS_PER_TENANT:
                raise HTTPException(
                    status_code=503,
                    detail="Model registry capacity reached",
                )

            self._check_idempotency_capacity()

            record = MLModelRecord(
                model_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                name=payload.name,
                description=payload.description,
                task_type=payload.task_type,
                framework=payload.framework,
                warehouse_id=payload.warehouse_id,
                created_by=principal.principal_id,
            )

            self._models[record.model_id] = record

            self._idempotency[key] = (
                request_hash,
                record.model_id,
            )

            return to_model(record)

    async def list_models(
        self,
        *,
        principal: Principal,
        limit: int,
    ) -> list[MLModelResponse]:

        async with self._lock:

            records = [
                record
                for record in self._models.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                )
            ]

            records.sort(
                key=lambda item: item.created_at,
                reverse=True,
            )

            results = []

            for record in records:

                try:
                    require_mlops_access(
                        principal,
                        record.warehouse_id,
                        write=False,
                    )

                except HTTPException:
                    continue

                results.append(to_model(record))

                if len(results) >= limit:
                    break

            return results

    async def get_model(
        self,
        *,
        principal: Principal,
        model_id: str,
    ) -> MLModelResponse:

        async with self._lock:

            return to_model(
                self._get_model(
                    principal,
                    model_id,
                    write=False,
                )
            )

    async def register_version(
        self,
        *,
        principal: Principal,
        model_id: str,
        payload: MLModelVersionCreate,
    ) -> MLModelVersionResponse:

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = fingerprint(
            "register_version",
            payload,
            model_id,
        )

        async with self._lock:

            model = self._get_model(
                principal,
                model_id,
                write=True,
            )

            previous = self._idempotent_result(
                key,
                request_hash,
            )

            if previous:
                return to_version(
                    self._get_version(
                        principal,
                        previous,
                        write=False,
                    )
                )

            self._check_version(
                model.version,
                payload.expected_model_version,
            )

            if (
                len(model.version_ids)
                >= MAX_VERSIONS_PER_MODEL
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Model version capacity reached",
                )

            if any(
                self._versions[version_id].version_name
                == payload.version_name
                for version_id in model.version_ids
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Model version name already exists",
                )

            self._check_idempotency_capacity()

            record = MLModelVersionRecord(
                model_version_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                model_id=model_id,
                version_name=payload.version_name,
                artifact_reference=payload.artifact_reference,
                artifact_sha256=payload.artifact_sha256,
                dataset_reference=payload.dataset_reference,
                parameters=json.loads(
                    json.dumps(payload.parameters)
                ),
                metrics=dict(payload.metrics),
            )

            self._versions[
                record.model_version_id
            ] = record

            model.version_ids.append(
                record.model_version_id
            )

            model.version += 1
            model.updated_at = utc_now()

            self._idempotency[key] = (
                request_hash,
                record.model_version_id,
            )

            return to_version(record)

    async def list_versions(
        self,
        *,
        principal: Principal,
        model_id: str,
    ) -> list[MLModelVersionResponse]:

        async with self._lock:

            model = self._get_model(
                principal,
                model_id,
                write=False,
            )

            return [
                to_version(self._versions[version_id])
                for version_id in model.version_ids
            ]

    async def validate_version(
        self,
        *,
        principal: Principal,
        version_id: str,
        payload: ModelValidationRequest,
    ) -> MLModelVersionResponse:

        async with self._lock:

            record = self._get_version(
                principal,
                version_id,
                write=True,
            )

            self._check_version(
                record.version,
                payload.expected_version,
            )

            if (
                record.status
                != ModelVersionStatus.REGISTERED
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Model version cannot be validated",
                )

            # This only records an evaluation reference.
            # Production must fetch the evaluation,
            # verify tenant, dataset, artifact hash,
            # threshold result and provenance.

            record.evaluation_id = (
                payload.evaluation_id
            )

            record.status = (
                ModelVersionStatus.VALIDATED
            )

            record.version += 1
            record.updated_at = utc_now()

            return to_version(record)

    async def create_experiment(
        self,
        *,
        principal: Principal,
        payload: ExperimentCreate,
    ) -> ExperimentResponse:

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = fingerprint(
            "create_experiment",
            payload,
        )

        async with self._lock:

            self._get_model(
                principal,
                payload.model_id,
                write=True,
            )

            previous = self._idempotent_result(
                key,
                request_hash,
            )

            if previous:
                return to_experiment(
                    self._experiments[previous]
                )

            count = sum(
                record.tenant_id
                == principal.tenant_id
                for record in self._experiments.values()
            )

            if count >= MAX_EXPERIMENTS_PER_TENANT:
                raise HTTPException(
                    status_code=503,
                    detail="Experiment capacity reached",
                )

            self._check_idempotency_capacity()

            record = ExperimentRecord(
                experiment_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                model_id=payload.model_id,
                name=payload.name,
                dataset_reference=payload.dataset_reference,
            )

            self._experiments[
                record.experiment_id
            ] = record

            self._idempotency[key] = (
                request_hash,
                record.experiment_id,
            )

            return to_experiment(record)

    async def finish_experiment(
        self,
        *,
        principal: Principal,
        experiment_id: str,
        payload: ExperimentFinish,
    ) -> ExperimentResponse:

        async with self._lock:

            record = self._experiments.get(
                experiment_id
            )

            if (
                record is None
                or record.tenant_id
                != principal.tenant_id
            ):
                raise HTTPException(
                    status_code=404,
                    detail="Experiment not found",
                )

            self._get_model(
                principal,
                record.model_id,
                write=True,
            )

            self._check_version(
                record.version,
                payload.expected_version,
            )

            if record.status != ExperimentStatus.RUNNING:
                raise HTTPException(
                    status_code=409,
                    detail="Experiment already finished",
                )

            record.status = payload.status
            record.metrics = dict(payload.metrics)
            record.notes = payload.notes
            record.finished_at = utc_now()
            record.version += 1

            return to_experiment(record)

    async def request_deployment(
        self,
        *,
        principal: Principal,
        payload: DeploymentRequestCreate,
    ) -> DeploymentResponse:

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = fingerprint(
            "request_deployment",
            payload,
        )

        async with self._lock:

            version = self._get_version(
                principal,
                payload.model_version_id,
                write=True,
            )

            previous = self._idempotent_result(
                key,
                request_hash,
            )

            if previous:
                return to_deployment(
                    self._get_deployment(
                        principal,
                        previous,
                        write=False,
                    )
                )

            if version.status not in {
                ModelVersionStatus.VALIDATED,
                ModelVersionStatus.APPROVED,
                ModelVersionStatus.DEPLOYED,
            }:
                raise HTTPException(
                    status_code=409,
                    detail="Model version is not validated",
                )

            self._check_idempotency_capacity()

            record = DeploymentRecord(
                deployment_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                model_id=version.model_id,
                model_version_id=version.model_version_id,
                environment=payload.environment,
                reason=payload.reason,
                requested_by=principal.principal_id,
            )

            self._deployments[
                record.deployment_id
            ] = record

            self._idempotency[key] = (
                request_hash,
                record.deployment_id,
            )

            return to_deployment(record)

    async def decide_deployment(
        self,
        *,
        principal: Principal,
        deployment_id: str,
        payload: DeploymentDecision,
    ) -> DeploymentResponse:

        async with self._lock:

            record = self._get_deployment(
                principal,
                deployment_id,
                write=True,
            )

            model = self._get_model(
                principal,
                record.model_id,
                write=True,
            )

            require_mlops_access(
                principal,
                model.warehouse_id,
                write=True,
                approve=True,
            )

            self._check_version(
                record.version,
                payload.expected_version,
            )

            if (
                record.status
                != DeploymentStatus.REQUESTED
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Deployment request already decided",
                )

            if (
                record.requested_by
                == principal.principal_id
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Self-approval is not allowed",
                )

            record.status = (
                DeploymentStatus.APPROVED
                if payload.approve
                else DeploymentStatus.REJECTED
            )

            record.approved_by = principal.principal_id
            record.decision_note = payload.decision_note

            record.version += 1
            record.updated_at = utc_now()

            return to_deployment(record)

    async def confirm_deployment(
        self,
        *,
        principal: Principal,
        deployment_id: str,
        payload: DeploymentConfirmation,
    ) -> DeploymentResponse:

        async with self._lock:

            record = self._get_deployment(
                principal,
                deployment_id,
                write=True,
            )

            self._check_version(
                record.version,
                payload.expected_version,
            )

            if (
                record.status
                != DeploymentStatus.APPROVED
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Deployment is not approved",
                )

            # This records a deployment reference.
            # It does not execute or verify a deployment.

            record.status = DeploymentStatus.DEPLOYED
            record.deployment_reference = (
                payload.deployment_reference
            )

            record.version += 1
            record.updated_at = utc_now()

            version = self._versions[
                record.model_version_id
            ]

            version.status = ModelVersionStatus.DEPLOYED
            version.version += 1
            version.updated_at = utc_now()

            return to_deployment(record)

    async def record_monitoring(
        self,
        *,
        principal: Principal,
        payload: MonitoringRecordCreate,
    ) -> MonitoringRecordResponse:

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = fingerprint(
            "record_monitoring",
            payload,
        )

        async with self._lock:

            version = self._get_version(
                principal,
                payload.model_version_id,
                write=True,
            )

            previous = self._idempotent_result(
                key,
                request_hash,
            )

            if previous:
                return self._monitoring[
                    previous
                ].model_copy(deep=True)

            count = sum(
                tenant_id == principal.tenant_id
                for tenant_id
                in self._monitoring_tenants.values()
            )

            if (
                count >= MAX_MONITORING_RECORDS_PER_TENANT
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Monitoring capacity reached",
                )

            self._check_idempotency_capacity()

            if (
                payload.metric_value
                >= payload.critical_threshold
            ):
                drift = DriftStatus.CRITICAL

            elif (
                payload.metric_value
                >= payload.warning_threshold
            ):
                drift = DriftStatus.WARNING

            else:
                drift = DriftStatus.NORMAL

            record = MonitoringRecordResponse(
                monitoring_id=secrets.token_urlsafe(20),
                model_id=version.model_id,
                model_version_id=version.model_version_id,
                metric_name=payload.metric_name,
                metric_value=payload.metric_value,
                warning_threshold=payload.warning_threshold,
                critical_threshold=payload.critical_threshold,
                drift_status=drift,
                source_reference=payload.source_reference,
                observed_at=payload.observed_at,
                created_at=utc_now(),
            )

            self._monitoring[
                record.monitoring_id
            ] = record

            self._monitoring_tenants[
                record.monitoring_id
            ] = principal.tenant_id

            self._idempotency[key] = (
                request_hash,
                record.monitoring_id,
            )

            return record.model_copy(deep=True)

    async def summary(
        self,
        *,
        principal: Principal,
    ) -> MLOpsSummaryResponse:

        async with self._lock:

            visible_models = {
                model.model_id
                for model in self._models.values()
                if (
                    model.tenant_id
                    == principal.tenant_id
                    and self._can_read_model(
                        principal,
                        model,
                    )
                )
            }

            versions = [
                record
                for record in self._versions.values()
                if record.model_id in visible_models
            ]

            experiments = [
                record
                for record in self._experiments.values()
                if record.model_id in visible_models
            ]

            deployments = [
                record
                for record in self._deployments.values()
                if record.model_id in visible_models
            ]

            monitoring = [
                record
                for record in self._monitoring.values()
                if (
                    record.model_id in visible_models
                    and self._monitoring_tenants.get(
                        record.monitoring_id
                    ) == principal.tenant_id
                )
            ]

            return MLOpsSummaryResponse(
                total_models=len(visible_models),
                total_model_versions=len(versions),
                total_experiments=len(experiments),
                running_experiments=sum(
                    record.status
                    == ExperimentStatus.RUNNING
                    for record in experiments
                ),
                completed_experiments=sum(
                    record.status
                    == ExperimentStatus.COMPLETED
                    for record in experiments
                ),
                deployment_requests=len(deployments),
                deployed_records=sum(
                    record.status
                    == DeploymentStatus.DEPLOYED
                    for record in deployments
                ),
                monitoring_records=len(monitoring),
                warning_records=sum(
                    record.drift_status
                    == DriftStatus.WARNING
                    for record in monitoring
                ),
                critical_records=sum(
                    record.drift_status
                    == DriftStatus.CRITICAL
                    for record in monitoring
                ),
            )

    @staticmethod
    def _can_read_model(
        principal: Principal,
        model: MLModelRecord,
    ) -> bool:

        try:
            require_mlops_access(
                principal,
                model.warehouse_id,
                write=False,
            )
            return True

        except HTTPException:
            return False


mlops_store = MLOpsStore()


# ============================================================
# SERVICE
# ============================================================

class MLOpsService:

    def __init__(
        self,
        store: MLOpsStore,
    ):
        self.store = store

    async def register_model(
        self,
        principal: Principal,
        payload: MLModelCreate,
    ) -> MLModelResponse:

        return await self.store.create_model(
            principal=principal,
            payload=payload,
        )

    async def register_version(
        self,
        principal: Principal,
        model_id: str,
        payload: MLModelVersionCreate,
    ) -> MLModelVersionResponse:

        return await self.store.register_version(
            principal=principal,
            model_id=model_id,
            payload=payload,
        )


mlops_service = MLOpsService(
    mlops_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["MLOps Management"],
)


@router.post(
    "/models",
    response_model=MLModelResponse,
    status_code=201,
)
async def create_ml_model(
    payload: MLModelCreate,
    principal: CurrentPrincipal,
):
    return await mlops_service.register_model(
        principal,
        payload,
    )


@router.get(
    "/models",
    response_model=list[MLModelResponse],
)
async def list_ml_models(
    principal: CurrentPrincipal,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await mlops_store.list_models(
        principal=principal,
        limit=limit,
    )


@router.get(
    "/models/{model_id}",
    response_model=MLModelResponse,
)
async def get_ml_model(
    model_id: str,
    principal: CurrentPrincipal,
):
    return await mlops_store.get_model(
        principal=principal,
        model_id=model_id,
    )


@router.post(
    "/models/{model_id}/versions",
    response_model=MLModelVersionResponse,
    status_code=201,
)
async def register_model_version(
    model_id: str,
    payload: MLModelVersionCreate,
    principal: CurrentPrincipal,
):
    return await mlops_service.register_version(
        principal,
        model_id,
        payload,
    )


@router.get(
    "/models/{model_id}/versions",
    response_model=list[MLModelVersionResponse],
)
async def list_model_versions(
    model_id: str,
    principal: CurrentPrincipal,
):
    return await mlops_store.list_versions(
        principal=principal,
        model_id=model_id,
    )


@router.post(
    "/versions/{version_id}/validate",
    response_model=MLModelVersionResponse,
)
async def validate_model_version(
    version_id: str,
    payload: ModelValidationRequest,
    principal: CurrentPrincipal,
):
    return await mlops_store.validate_version(
        principal=principal,
        version_id=version_id,
        payload=payload,
    )


@router.post(
    "/experiments",
    response_model=ExperimentResponse,
    status_code=201,
)
async def create_experiment(
    payload: ExperimentCreate,
    principal: CurrentPrincipal,
):
    return await mlops_store.create_experiment(
        principal=principal,
        payload=payload,
    )


@router.post(
    "/experiments/{experiment_id}/finish",
    response_model=ExperimentResponse,
)
async def finish_experiment(
    experiment_id: str,
    payload: ExperimentFinish,
    principal: CurrentPrincipal,
):
    return await mlops_store.finish_experiment(
        principal=principal,
        experiment_id=experiment_id,
        payload=payload,
    )


@router.post(
    "/deployments",
    response_model=DeploymentResponse,
    status_code=201,
)
async def request_model_deployment(
    payload: DeploymentRequestCreate,
    principal: CurrentPrincipal,
):
    return await mlops_store.request_deployment(
        principal=principal,
        payload=payload,
    )


@router.post(
    "/deployments/{deployment_id}/decision",
    response_model=DeploymentResponse,
)
async def decide_model_deployment(
    deployment_id: str,
    payload: DeploymentDecision,
    principal: CurrentPrincipal,
):
    return await mlops_store.decide_deployment(
        principal=principal,
        deployment_id=deployment_id,
        payload=payload,
    )


@router.post(
    "/deployments/{deployment_id}/confirm",
    response_model=DeploymentResponse,
)
async def confirm_model_deployment(
    deployment_id: str,
    payload: DeploymentConfirmation,
    principal: CurrentPrincipal,
):
    return await mlops_store.confirm_deployment(
        principal=principal,
        deployment_id=deployment_id,
        payload=payload,
    )


@router.post(
    "/monitoring",
    response_model=MonitoringRecordResponse,
    status_code=201,
)
async def record_model_monitoring(
    payload: MonitoringRecordCreate,
    principal: CurrentPrincipal,
):
    return await mlops_store.record_monitoring(
        principal=principal,
        payload=payload,
    )


@router.get(
    "/summary",
    response_model=MLOpsSummaryResponse,
)
async def mlops_summary(
    principal: CurrentPrincipal,
):
    return await mlops_store.summary(
        principal=principal,
    )


__all__ = [
    "MLTaskType",
    "MLFramework",
    "ModelVersionStatus",
    "ExperimentStatus",
    "DeploymentEnvironment",
    "DeploymentStatus",
    "DriftStatus",
    "MLModelCreate",
    "MLModelVersionCreate",
    "ExperimentCreate",
    "ExperimentFinish",
    "ModelValidationRequest",
    "DeploymentRequestCreate",
    "DeploymentDecision",
    "DeploymentConfirmation",
    "MonitoringRecordCreate",
    "MLModelResponse",
    "MLModelVersionResponse",
    "ExperimentResponse",
    "DeploymentResponse",
    "MonitoringRecordResponse",
    "MLOpsSummaryResponse",
    "MLOpsStore",
    "MLOpsService",
    "mlops_store",
    "mlops_service",
    "router",
]
