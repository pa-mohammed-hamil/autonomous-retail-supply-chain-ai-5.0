from __future__ import annotations

"""Planned module: benchmarks. Implementation pending."""

"""
backend/benchmarks.py

Autonomous Retail Supply Chain AI 5.0
AI / ML / RAG / Agent Benchmark Management

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Forecasting benchmarks
    - Classification benchmarks
    - RAG retrieval benchmarks
    - Agent execution benchmarks
    - API latency benchmarks
    - Baseline comparisons
    - Configurable quality thresholds
    - Evaluation run history
    - Tenant isolation
    - Warehouse-scoped access
    - Idempotent submissions
    - Bounded in-memory storage
    - Safe metric validation

IMPORTANT:
    This module evaluates submitted metrics.

    It does not independently execute models,
    generate predictions, run agents, or
    measure production API traffic.

    Production evaluation workers must
    compute and attest metrics from trusted
    datasets and execution traces.
"""


import asyncio
import hashlib
import json
import math
import secrets

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from backend.permissions import (
    CurrentPrincipal,
    Permission,
    Principal,
    ResourceContext,
    permission_engine,
)


# ============================================================
# CONFIGURATION
# ============================================================

MAX_BENCHMARKS_PER_TENANT = 5000
MAX_METRICS_PER_RUN = 50
MAX_LIST_LIMIT = 200

MAX_METRIC_VALUE = 1_000_000_000.0

MIN_SAMPLE_COUNT = 1

API_PREFIX = "/api/v1/benchmarks"


# ============================================================
# ENUMS
# ============================================================

class BenchmarkCategory(str, Enum):
    FORECASTING = "forecasting"
    CLASSIFICATION = "classification"
    RAG = "rag"
    AGENT = "agent"
    API = "api"


class BenchmarkStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    NO_THRESHOLDS = "no_thresholds"


class MetricDirection(str, Enum):
    LOWER_IS_BETTER = "lower_is_better"
    HIGHER_IS_BETTER = "higher_is_better"


class BenchmarkMetric(str, Enum):

    # Forecasting
    MAE = "mae"
    RMSE = "rmse"
    WAPE = "wape"
    SMAPE = "smape"
    FORECAST_BIAS = "forecast_bias"

    # Classification
    ACCURACY = "accuracy"
    PRECISION = "precision"
    RECALL = "recall"
    F1_SCORE = "f1_score"
    ROC_AUC = "roc_auc"

    # RAG
    RECALL_AT_K = "recall_at_k"
    PRECISION_AT_K = "precision_at_k"
    MRR = "mrr"
    NDCG_AT_K = "ndcg_at_k"
    FAITHFULNESS = "faithfulness"
    CITATION_ACCURACY = "citation_accuracy"

    # Agent
    TASK_SUCCESS_RATE = "task_success_rate"
    TOOL_SUCCESS_RATE = "tool_success_rate"
    APPROVAL_COMPLIANCE = "approval_compliance"
    AGENT_LATENCY_MS = "agent_latency_ms"
    AGENT_COST_USD = "agent_cost_usd"

    # API
    P50_LATENCY_MS = "p50_latency_ms"
    P95_LATENCY_MS = "p95_latency_ms"
    P99_LATENCY_MS = "p99_latency_ms"
    ERROR_RATE = "error_rate"
    THROUGHPUT_RPS = "throughput_rps"


# ============================================================
# METRIC DEFINITIONS
# ============================================================

class MetricDefinition(BaseModel):
    direction: MetricDirection
    minimum: float | None = None
    maximum: float | None = None


METRIC_DEFINITIONS: dict[
    BenchmarkMetric,
    MetricDefinition,
] = {

    BenchmarkMetric.MAE: MetricDefinition(
        direction=MetricDirection.LOWER_IS_BETTER,
        minimum=0,
    ),

    BenchmarkMetric.RMSE: MetricDefinition(
        direction=MetricDirection.LOWER_IS_BETTER,
        minimum=0,
    ),

    BenchmarkMetric.WAPE: MetricDefinition(
        direction=MetricDirection.LOWER_IS_BETTER,
        minimum=0,
    ),

    BenchmarkMetric.SMAPE: MetricDefinition(
        direction=MetricDirection.LOWER_IS_BETTER,
        minimum=0,
        maximum=200,
    ),

    BenchmarkMetric.FORECAST_BIAS: MetricDefinition(
        direction=MetricDirection.LOWER_IS_BETTER,
    ),

    BenchmarkMetric.ACCURACY: MetricDefinition(
        direction=MetricDirection.HIGHER_IS_BETTER,
        minimum=0,
        maximum=1,
    ),

    BenchmarkMetric.PRECISION: MetricDefinition(
        direction=MetricDirection.HIGHER_IS_BETTER,
        minimum=0,
        maximum=1,
    ),

    BenchmarkMetric.RECALL: MetricDefinition(
        direction=MetricDirection.HIGHER_IS_BETTER,
        minimum=0,
        maximum=1,
    ),

    BenchmarkMetric.F1_SCORE: MetricDefinition(
        direction=MetricDirection.HIGHER_IS_BETTER,
        minimum=0,
        maximum=1,
    ),

    BenchmarkMetric.ROC_AUC: MetricDefinition(
        direction=MetricDirection.HIGHER_IS_BETTER,
        minimum=0,
        maximum=1,
    ),

    BenchmarkMetric.RECALL_AT_K: MetricDefinition(
        direction=MetricDirection.HIGHER_IS_BETTER,
        minimum=0,
        maximum=1,
    ),

    BenchmarkMetric.PRECISION_AT_K: MetricDefinition(
        direction=MetricDirection.HIGHER_IS_BETTER,
        minimum=0,
        maximum=1,
    ),

    BenchmarkMetric.MRR: MetricDefinition(
        direction=MetricDirection.HIGHER_IS_BETTER,
        minimum=0,
        maximum=1,
    ),

    BenchmarkMetric.NDCG_AT_K: MetricDefinition(
        direction=MetricDirection.HIGHER_IS_BETTER,
        minimum=0,
        maximum=1,
    ),

    BenchmarkMetric.FAITHFULNESS: MetricDefinition(
        direction=MetricDirection.HIGHER_IS_BETTER,
        minimum=0,
        maximum=1,
    ),

    BenchmarkMetric.CITATION_ACCURACY: MetricDefinition(
        direction=MetricDirection.HIGHER_IS_BETTER,
        minimum=0,
        maximum=1,
    ),

    BenchmarkMetric.TASK_SUCCESS_RATE: MetricDefinition(
        direction=MetricDirection.HIGHER_IS_BETTER,
        minimum=0,
        maximum=1,
    ),

    BenchmarkMetric.TOOL_SUCCESS_RATE: MetricDefinition(
        direction=MetricDirection.HIGHER_IS_BETTER,
        minimum=0,
        maximum=1,
    ),

    BenchmarkMetric.APPROVAL_COMPLIANCE: MetricDefinition(
        direction=MetricDirection.HIGHER_IS_BETTER,
        minimum=0,
        maximum=1,
    ),

    BenchmarkMetric.AGENT_LATENCY_MS: MetricDefinition(
        direction=MetricDirection.LOWER_IS_BETTER,
        minimum=0,
    ),

    BenchmarkMetric.AGENT_COST_USD: MetricDefinition(
        direction=MetricDirection.LOWER_IS_BETTER,
        minimum=0,
    ),

    BenchmarkMetric.P50_LATENCY_MS: MetricDefinition(
        direction=MetricDirection.LOWER_IS_BETTER,
        minimum=0,
    ),

    BenchmarkMetric.P95_LATENCY_MS: MetricDefinition(
        direction=MetricDirection.LOWER_IS_BETTER,
        minimum=0,
    ),

    BenchmarkMetric.P99_LATENCY_MS: MetricDefinition(
        direction=MetricDirection.LOWER_IS_BETTER,
        minimum=0,
    ),

    BenchmarkMetric.ERROR_RATE: MetricDefinition(
        direction=MetricDirection.LOWER_IS_BETTER,
        minimum=0,
        maximum=1,
    ),

    BenchmarkMetric.THROUGHPUT_RPS: MetricDefinition(
        direction=MetricDirection.HIGHER_IS_BETTER,
        minimum=0,
    ),
}


CATEGORY_METRICS = {
    BenchmarkCategory.FORECASTING: {
        BenchmarkMetric.MAE,
        BenchmarkMetric.RMSE,
        BenchmarkMetric.WAPE,
        BenchmarkMetric.SMAPE,
        BenchmarkMetric.FORECAST_BIAS,
    },
    BenchmarkCategory.CLASSIFICATION: {
        BenchmarkMetric.ACCURACY,
        BenchmarkMetric.PRECISION,
        BenchmarkMetric.RECALL,
        BenchmarkMetric.F1_SCORE,
        BenchmarkMetric.ROC_AUC,
    },
    BenchmarkCategory.RAG: {
        BenchmarkMetric.RECALL_AT_K,
        BenchmarkMetric.PRECISION_AT_K,
        BenchmarkMetric.MRR,
        BenchmarkMetric.NDCG_AT_K,
        BenchmarkMetric.FAITHFULNESS,
        BenchmarkMetric.CITATION_ACCURACY,
    },
    BenchmarkCategory.AGENT: {
        BenchmarkMetric.TASK_SUCCESS_RATE,
        BenchmarkMetric.TOOL_SUCCESS_RATE,
        BenchmarkMetric.APPROVAL_COMPLIANCE,
        BenchmarkMetric.AGENT_LATENCY_MS,
        BenchmarkMetric.AGENT_COST_USD,
    },
    BenchmarkCategory.API: {
        BenchmarkMetric.P50_LATENCY_MS,
        BenchmarkMetric.P95_LATENCY_MS,
        BenchmarkMetric.P99_LATENCY_MS,
        BenchmarkMetric.ERROR_RATE,
        BenchmarkMetric.THROUGHPUT_RPS,
    },
}


# ============================================================
# REQUEST MODELS
# ============================================================

class MetricInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: BenchmarkMetric

    value: float = Field(
        allow_inf_nan=False,
    )


class ThresholdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: BenchmarkMetric

    minimum: float | None = Field(
        default=None,
        allow_inf_nan=False,
    )

    maximum: float | None = Field(
        default=None,
        allow_inf_nan=False,
    )

    @model_validator(mode="after")
    def validate_bounds(self):

        if (
            self.minimum is None
            and self.maximum is None
        ):
            raise ValueError(
                "At least one threshold bound is required"
            )

        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError(
                "Minimum threshold exceeds maximum"
            )

        return self


class BenchmarkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=200,
    )

    category: BenchmarkCategory

    model_name: str = Field(
        min_length=1,
        max_length=128,
    )

    model_version: str = Field(
        min_length=1,
        max_length=128,
    )

    dataset_id: str = Field(
        min_length=1,
        max_length=128,
    )

    dataset_version: str = Field(
        min_length=1,
        max_length=128,
    )

    warehouse_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    sample_count: int = Field(
        ge=MIN_SAMPLE_COUNT,
    )

    metrics: list[MetricInput] = Field(
        min_length=1,
        max_length=MAX_METRICS_PER_RUN,
    )

    thresholds: list[ThresholdInput] = Field(
        default_factory=list,
        max_length=MAX_METRICS_PER_RUN,
    )

    baseline_benchmark_id: str | None = None

    @model_validator(mode="after")
    def validate_metrics(self):

        permitted = CATEGORY_METRICS[
            self.category
        ]

        metric_names = [
            metric.name
            for metric in self.metrics
        ]

        if len(metric_names) != len(set(metric_names)):
            raise ValueError(
                "Duplicate metric names"
            )

        if any(
            name not in permitted
            for name in metric_names
        ):
            raise ValueError(
                "Metric is not valid for benchmark category"
            )

        for metric in self.metrics:

            definition = METRIC_DEFINITIONS[
                metric.name
            ]

            if (
                definition.minimum is not None
                and metric.value < definition.minimum
            ):
                raise ValueError(
                    f"{metric.name.value} is below its valid range"
                )

            if (
                definition.maximum is not None
                and metric.value > definition.maximum
            ):
                raise ValueError(
                    f"{metric.name.value} exceeds its valid range"
                )

            if abs(metric.value) > MAX_METRIC_VALUE:
                raise ValueError(
                    "Metric value exceeds allowed magnitude"
                )

        threshold_names = [
            threshold.metric
            for threshold in self.thresholds
        ]

        if len(threshold_names) != len(
            set(threshold_names)
        ):
            raise ValueError(
                "Duplicate threshold definitions"
            )

        if any(
            name not in metric_names
            for name in threshold_names
        ):
            raise ValueError(
                "Threshold metric has no submitted value"
            )

        return self


# ============================================================
# RESPONSE MODELS
# ============================================================

class MetricResult(BaseModel):
    name: BenchmarkMetric
    value: float
    direction: MetricDirection


class ThresholdResult(BaseModel):
    metric: BenchmarkMetric
    actual_value: float
    minimum: float | None
    maximum: float | None
    passed: bool


class BaselineComparison(BaseModel):
    metric: BenchmarkMetric
    current_value: float
    baseline_value: float
    absolute_difference: float
    improvement: float
    direction: MetricDirection


class BenchmarkResponse(BaseModel):
    benchmark_id: str
    name: str
    category: BenchmarkCategory

    model_name: str
    model_version: str

    dataset_id: str
    dataset_version: str

    warehouse_id: str | None

    sample_count: int
    status: BenchmarkStatus

    metrics: list[MetricResult]
    thresholds: list[ThresholdResult]

    baseline_benchmark_id: str | None
    baseline_comparisons: list[BaselineComparison]

    created_at: datetime


class BenchmarkSummary(BaseModel):
    total: int
    passed: int
    failed: int
    no_thresholds: int


class BenchmarkCatalogResponse(BaseModel):
    categories: list[BenchmarkCategory]
    metrics: dict[str, list[str]]


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint_request(
    payload: BenchmarkCreate,
) -> str:

    canonical = json.dumps(
        payload.model_dump(
            mode="json",
            exclude={"source_request_id"},
        ),
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def validate_access(
    principal: Principal,
    warehouse_id: str | None,
    *,
    execute: bool,
) -> None:

    permission = (
        Permission.AI_AGENT_EXECUTE
        if execute
        else Permission.ANALYTICS_READ
    )

    resource = ResourceContext(
        tenant_id=principal.tenant_id,
        warehouse_id=warehouse_id,
    )

    decision = permission_engine.evaluate(
        principal,
        permission,
        resource,
    )

    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail="Benchmark access denied",
        )

    allowed = principal.allowed_warehouse_ids

    if warehouse_id is None:
        if allowed is not None:
            raise HTTPException(
                status_code=403,
                detail="Unscoped benchmark access denied",
            )

    elif (
        allowed is not None
        and warehouse_id not in allowed
    ):
        raise HTTPException(
            status_code=403,
            detail="Warehouse access denied",
        )


# ============================================================
# METRIC EVALUATION
# ============================================================

def evaluate_thresholds(
    metrics: list[MetricInput],
    thresholds: list[ThresholdInput],
) -> tuple[
    BenchmarkStatus,
    list[ThresholdResult],
]:

    values = {
        metric.name: metric.value
        for metric in metrics
    }

    results = []

    for threshold in thresholds:

        value = values[
            threshold.metric
        ]

        passed = True

        if threshold.minimum is not None:
            passed = (
                passed
                and value >= threshold.minimum
            )

        if threshold.maximum is not None:
            passed = (
                passed
                and value <= threshold.maximum
            )

        results.append(
            ThresholdResult(
                metric=threshold.metric,
                actual_value=value,
                minimum=threshold.minimum,
                maximum=threshold.maximum,
                passed=passed,
            )
        )

    if not results:
        return (
            BenchmarkStatus.NO_THRESHOLDS,
            results,
        )

    status = (
        BenchmarkStatus.PASSED
        if all(
            result.passed
            for result in results
        )
        else BenchmarkStatus.FAILED
    )

    return status, results


def compare_baseline(
    current: list[MetricInput],
    baseline: BenchmarkResponse,
) -> list[BaselineComparison]:

    baseline_values = {
        metric.name: metric.value
        for metric in baseline.metrics
    }

    comparisons = []

    for metric in current:

        if metric.name not in baseline_values:
            continue

        previous = baseline_values[
            metric.name
        ]

        direction = METRIC_DEFINITIONS[
            metric.name
        ].direction

        difference = metric.value - previous

        improvement = (
            -difference
            if direction
            == MetricDirection.LOWER_IS_BETTER
            else difference
        )

        comparisons.append(
            BaselineComparison(
                metric=metric.name,
                current_value=metric.value,
                baseline_value=previous,
                absolute_difference=difference,
                improvement=improvement,
                direction=direction,
            )
        )

    return comparisons


# ============================================================
# BENCHMARK STORE
# ============================================================

class BenchmarkStore:

    def __init__(self):

        self._records: dict[
            str,
            tuple[
                str,
                str,
                BenchmarkResponse,
            ],
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        principal: Principal,
        payload: BenchmarkCreate,
    ) -> BenchmarkResponse:

        validate_access(
            principal,
            payload.warehouse_id,
            execute=True,
        )

        fingerprint = fingerprint_request(
            payload
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        async with self._lock:

            existing = self._idempotency.get(
                key
            )

            if existing is not None:

                benchmark_id, old_fingerprint = (
                    existing
                )

                if old_fingerprint != fingerprint:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return self._records[
                    benchmark_id
                ][2].model_copy(deep=True)

            tenant_count = sum(
                tenant_id == principal.tenant_id
                for tenant_id, _, _
                in self._records.values()
            )

            if (
                tenant_count
                >= MAX_BENCHMARKS_PER_TENANT
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Benchmark capacity reached",
                )

            baseline = None

            if payload.baseline_benchmark_id:

                entry = self._records.get(
                    payload.baseline_benchmark_id
                )

                if (
                    entry is None
                    or entry[0] != principal.tenant_id
                ):
                    raise HTTPException(
                        status_code=404,
                        detail="Baseline benchmark not found",
                    )

                baseline = entry[2]

                if (
                    baseline.category != payload.category
                    or baseline.dataset_id
                    != payload.dataset_id
                    or baseline.dataset_version
                    != payload.dataset_version
                    or baseline.warehouse_id
                    != payload.warehouse_id
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Incompatible baseline benchmark",
                    )

            status, threshold_results = (
                evaluate_thresholds(
                    payload.metrics,
                    payload.thresholds,
                )
            )

            metric_results = [
                MetricResult(
                    name=metric.name,
                    value=metric.value,
                    direction=METRIC_DEFINITIONS[
                        metric.name
                    ].direction,
                )
                for metric in payload.metrics
            ]

            comparisons = (
                compare_baseline(
                    payload.metrics,
                    baseline,
                )
                if baseline is not None
                else []
            )

            benchmark = BenchmarkResponse(
                benchmark_id=secrets.token_urlsafe(20),
                name=payload.name,
                category=payload.category,
                model_name=payload.model_name,
                model_version=payload.model_version,
                dataset_id=payload.dataset_id,
                dataset_version=payload.dataset_version,
                warehouse_id=payload.warehouse_id,
                sample_count=payload.sample_count,
                status=status,
                metrics=metric_results,
                thresholds=threshold_results,
                baseline_benchmark_id=(
                    payload.baseline_benchmark_id
                ),
                baseline_comparisons=comparisons,
                created_at=utc_now(),
            )

            self._records[
                benchmark.benchmark_id
            ] = (
                principal.tenant_id,
                principal.principal_id,
                benchmark,
            )

            self._idempotency[key] = (
                benchmark.benchmark_id,
                fingerprint,
            )

            return benchmark.model_copy(deep=True)

    async def get(
        self,
        *,
        principal: Principal,
        benchmark_id: str,
    ) -> BenchmarkResponse:

        async with self._lock:

            entry = self._records.get(
                benchmark_id
            )

            if (
                entry is None
                or entry[0] != principal.tenant_id
            ):
                raise HTTPException(
                    status_code=404,
                    detail="Benchmark not found",
                )

            benchmark = entry[2]

            validate_access(
                principal,
                benchmark.warehouse_id,
                execute=False,
            )

            return benchmark.model_copy(
                deep=True
            )

    async def list_records(
        self,
        *,
        principal: Principal,
        category: BenchmarkCategory | None,
        warehouse_id: str | None,
        limit: int,
    ) -> list[BenchmarkResponse]:

        validate_access(
            principal,
            warehouse_id,
            execute=False,
        )

        async with self._lock:

            records = [
                benchmark
                for tenant_id, _, benchmark
                in self._records.values()
                if (
                    tenant_id == principal.tenant_id
                    and (
                        category is None
                        or benchmark.category == category
                    )
                    and (
                        warehouse_id is None
                        or benchmark.warehouse_id
                        == warehouse_id
                    )
                )
            ]

            records.sort(
                key=lambda item: item.created_at,
                reverse=True,
            )

            return [
                item.model_copy(deep=True)
                for item in records[:limit]
            ]


benchmark_store = BenchmarkStore()


# ============================================================
# BENCHMARK SERVICE
# ============================================================

class BenchmarkService:

    def __init__(
        self,
        store: BenchmarkStore,
    ):
        self.store = store

    async def submit(
        self,
        *,
        principal: Principal,
        payload: BenchmarkCreate,
    ) -> BenchmarkResponse:

        return await self.store.create(
            principal=principal,
            payload=payload,
        )

    def catalog(
        self,
    ) -> BenchmarkCatalogResponse:

        return BenchmarkCatalogResponse(
            categories=list(BenchmarkCategory),
            metrics={
                category.value: sorted(
                    metric.value
                    for metric in metrics
                )
                for category, metrics
                in CATEGORY_METRICS.items()
            },
        )


benchmark_service = BenchmarkService(
    benchmark_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["AI Benchmarks"],
)


@router.get(
    "/catalog",
    response_model=BenchmarkCatalogResponse,
)
async def benchmark_catalog(
    principal: CurrentPrincipal,
):

    validate_access(
        principal,
        None,
        execute=False,
    )

    return benchmark_service.catalog()


@router.post(
    "",
    response_model=BenchmarkResponse,
    status_code=201,
)
async def submit_benchmark(
    payload: BenchmarkCreate,
    principal: CurrentPrincipal,
):

    return await benchmark_service.submit(
        principal=principal,
        payload=payload,
    )


@router.get(
    "",
    response_model=list[BenchmarkResponse],
)
async def list_benchmarks(
    principal: CurrentPrincipal,
    category: BenchmarkCategory | None = None,
    warehouse_id: str | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):

    return await benchmark_store.list_records(
        principal=principal,
        category=category,
        warehouse_id=warehouse_id,
        limit=limit,
    )


@router.get(
    "/{benchmark_id}",
    response_model=BenchmarkResponse,
)
async def get_benchmark(
    benchmark_id: str,
    principal: CurrentPrincipal,
):

    return await benchmark_store.get(
        principal=principal,
        benchmark_id=benchmark_id,
    )


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "BenchmarkCategory",
    "BenchmarkStatus",
    "MetricDirection",
    "BenchmarkMetric",
    "MetricInput",
    "ThresholdInput",
    "BenchmarkCreate",
    "MetricResult",
    "ThresholdResult",
    "BaselineComparison",
    "BenchmarkResponse",
    "BenchmarkSummary",
    "BenchmarkCatalogResponse",
    "MetricDefinition",
    "METRIC_DEFINITIONS",
    "CATEGORY_METRICS",
    "BenchmarkStore",
    "BenchmarkService",
    "benchmark_store",
    "benchmark_service",
    "router",
]
