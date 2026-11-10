from __future__ import annotations

"""Planned module: demand stream. Implementation pending."""

"""
backend/demand_stream.py

Autonomous Retail Supply Chain AI 5.0

Real-time demand intelligence streaming.

Python 3.10+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Demand observation ingestion
    - Real-time demand trend monitoring
    - Demand spike and drop detection
    - Forecast updates
    - Replenishment recommendations
    - Tenant and warehouse isolation
    - Idempotent event ingestion
    - WebSocket demand notifications
    - Permission-aware API endpoints
    - Bounded in-memory history
    - Structured event timestamps

Important:
    This is a development foundation.
    Production requires durable storage,
    event-bus integration, and historical
    demand models.

    Never interpret demand estimates as
    confirmed sales or stock availability.
"""


import asyncio
import math
import secrets
import statistics

from collections import deque
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
)

from backend.permissions import (
    CurrentPrincipal,
    Permission,
    Principal,
    ResourceContext,
    permission_engine,
)

from backend.connection_manager import (
    RealtimeEventType,
    RealtimeMessage,
    connection_manager,
)


# ============================================================
# CONFIGURATION
# ============================================================

MAX_HISTORY_PER_PRODUCT = 500

MAX_IDEMPOTENCY_RECORDS = 10000

DEFAULT_BASELINE_WINDOW = 14

MIN_BASELINE_SAMPLES = 3

SPIKE_RATIO = 1.5

DROP_RATIO = 0.6

MAX_UNITS_PER_OBSERVATION = 1_000_000


# ============================================================
# ENUMS
# ============================================================

class DemandEventType(str, Enum):

    OBSERVATION = "observation"
    FORECAST_UPDATED = "forecast_updated"

    SPIKE_DETECTED = "spike_detected"
    DROP_DETECTED = "drop_detected"

    TREND_UPDATED = "trend_updated"

    REPLENISHMENT_SUGGESTED = (
        "replenishment_suggested"
    )


class DemandTrend(str, Enum):

    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"
    INSUFFICIENT_DATA = "insufficient_data"


class DemandSeverity(str, Enum):

    INFO = "info"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ============================================================
# SCHEMAS
# ============================================================

class DemandObservationCreate(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    units_sold: int = Field(
        ge=0,
        le=MAX_UNITS_PER_OBSERVATION,
    )

    observed_at: datetime

    source_event_id: str = Field(
        min_length=8,
        max_length=128,
    )


class DemandForecastUpdate(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    forecast_units: float = Field(
        ge=0,
        allow_inf_nan=False,
    )

    horizon_days: int = Field(
        ge=1,
        le=365,
    )

    model_version: str = Field(
        min_length=1,
        max_length=128,
    )

    source_event_id: str = Field(
        min_length=8,
        max_length=128,
    )


class DemandObservationResponse(BaseModel):

    observation_id: str
    tenant_id: str

    product_id: str
    warehouse_id: str

    units_sold: int
    observed_at: datetime

    baseline_units: float | None
    demand_ratio: float | None

    trend: DemandTrend

    detected_event: DemandEventType | None


class DemandSnapshot(BaseModel):

    tenant_id: str
    product_id: str
    warehouse_id: str

    observations: int

    latest_units: int | None
    average_units: float | None

    trend: DemandTrend

    last_observed_at: datetime | None


# ============================================================
# INTERNAL MODELS
# ============================================================

@dataclass(frozen=True)
class DemandObservation:

    observation_id: str
    tenant_id: str

    product_id: str
    warehouse_id: str

    units_sold: int
    observed_at: datetime

    source_event_id: str

    baseline_units: float | None
    demand_ratio: float | None

    trend: DemandTrend

    detected_event: DemandEventType | None


@dataclass(frozen=True)
class DemandForecast:

    tenant_id: str

    product_id: str
    warehouse_id: str

    forecast_units: float
    horizon_days: int

    model_version: str
    updated_at: datetime


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:

    return datetime.now(timezone.utc)


def require_aware_datetime(
    value: datetime,
) -> datetime:

    if value.tzinfo is None:

        raise ValueError(
            "observed_at must include timezone"
        )

    return value.astimezone(
        timezone.utc
    )


def resource_key(
    tenant_id: str,
    product_id: str,
    warehouse_id: str,
) -> tuple[str, str, str]:

    return (
        tenant_id,
        product_id,
        warehouse_id,
    )


def require_demand_access(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool = False,
) -> None:

    permission = (
        Permission.ANALYTICS_READ
    )

    if write:
        # The existing RBAC model has no
        # dedicated DEMAND_WRITE permission.
        # Restrict ingestion to users with
        # inventory-write authority.
        permission = (
            Permission.INVENTORY_WRITE
        )

    permission_engine.require(
        principal,
        permission,
        ResourceContext(
            tenant_id=principal.tenant_id,
            warehouse_id=warehouse_id,
        ),
    )


# ============================================================
# DEMAND ANALYSIS
# ============================================================

def calculate_baseline(
    observations: list[DemandObservation],
    window: int = DEFAULT_BASELINE_WINDOW,
) -> float | None:

    values = [
        observation.units_sold
        for observation in observations[-window:]
    ]

    if len(values) < MIN_BASELINE_SAMPLES:
        return None

    return float(
        statistics.mean(values)
    )


def detect_demand_change(
    current_units: int,
    baseline_units: float | None,
) -> tuple[
    float | None,
    DemandEventType | None,
]:

    if baseline_units is None:
        return None, None

    if baseline_units == 0:

        if current_units > 0:
            return None, DemandEventType.SPIKE_DETECTED

        return 1.0, None

    ratio = current_units / baseline_units

    if ratio >= SPIKE_RATIO:

        return (
            ratio,
            DemandEventType.SPIKE_DETECTED,
        )

    if ratio <= DROP_RATIO:

        return (
            ratio,
            DemandEventType.DROP_DETECTED,
        )

    return ratio, None


def calculate_trend(
    observations: list[DemandObservation],
) -> DemandTrend:

    if len(observations) < 6:
        return DemandTrend.INSUFFICIENT_DATA

    recent = [
        item.units_sold
        for item in observations[-3:]
    ]

    previous = [
        item.units_sold
        for item in observations[-6:-3]
    ]

    recent_avg = statistics.mean(recent)
    previous_avg = statistics.mean(previous)

    if previous_avg == 0:

        if recent_avg > 0:
            return DemandTrend.INCREASING

        return DemandTrend.STABLE

    ratio = recent_avg / previous_avg

    if ratio >= 1.2:
        return DemandTrend.INCREASING

    if ratio <= 0.8:
        return DemandTrend.DECREASING

    return DemandTrend.STABLE


# ============================================================
# DEMAND STORE
# ============================================================

class DemandStreamStore:

    def __init__(self):

        self._observations: dict[
            tuple[str, str, str],
            deque[DemandObservation],
        ] = {}

        self._forecasts: dict[
            tuple[str, str, str],
            DemandForecast,
        ] = {}

        self._idempotency: dict[
            tuple[str, str], str
        ] = {}

        self._lock = asyncio.Lock()

    async def add_observation(
        self,
        tenant_id: str,
        payload: DemandObservationCreate,
    ) -> tuple[
        DemandObservation,
        bool,
    ]:

        observed_at = require_aware_datetime(
            payload.observed_at
        )

        key = resource_key(
            tenant_id,
            payload.product_id,
            payload.warehouse_id,
        )

        idempotency_key = (
            tenant_id,
            payload.source_event_id,
        )

        async with self._lock:

            existing_id = (
                self._idempotency.get(
                    idempotency_key
                )
            )

            if existing_id is not None:

                for history in self._observations.values():

                    for item in history:

                        if (
                            item.observation_id
                            == existing_id
                        ):
                            return item, False

                # An idempotency record outlived
                # the bounded observation history.
                # Do not silently reprocess it.
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Event already processed"
                    ),
                )

            history = (
                self._observations.setdefault(
                    key,
                    deque(
                        maxlen=MAX_HISTORY_PER_PRODUCT
                    ),
                )
            )

            previous = list(history)

            baseline = calculate_baseline(
                previous
            )

            ratio, event_type = (
                detect_demand_change(
                    payload.units_sold,
                    baseline,
                )
            )

            observation = DemandObservation(
                observation_id=(
                    secrets.token_urlsafe(18)
                ),
                tenant_id=tenant_id,
                product_id=payload.product_id,
                warehouse_id=payload.warehouse_id,
                units_sold=payload.units_sold,
                observed_at=observed_at,
                source_event_id=(
                    payload.source_event_id
                ),
                baseline_units=baseline,
                demand_ratio=ratio,
                trend=DemandTrend.INSUFFICIENT_DATA,
                detected_event=event_type,
            )

            history.append(
                observation
            )

            trend = calculate_trend(
                list(history)
            )

            observation = DemandObservation(
                **{
                    **observation.__dict__,
                    "trend": trend,
                }
            )

            history[-1] = observation

            if len(self._idempotency) >= (
                MAX_IDEMPOTENCY_RECORDS
            ):
                # In-memory bounded idempotency.
                # Durable deduplication is required
                # for production.
                oldest_key = next(
                    iter(self._idempotency)
                )

                self._idempotency.pop(
                    oldest_key,
                    None,
                )

            self._idempotency[
                idempotency_key
            ] = observation.observation_id

            return observation, True

    async def update_forecast(
        self,
        tenant_id: str,
        payload: DemandForecastUpdate,
    ) -> DemandForecast:

        key = resource_key(
            tenant_id,
            payload.product_id,
            payload.warehouse_id,
        )

        forecast = DemandForecast(
            tenant_id=tenant_id,
            product_id=payload.product_id,
            warehouse_id=payload.warehouse_id,
            forecast_units=payload.forecast_units,
            horizon_days=payload.horizon_days,
            model_version=payload.model_version,
            updated_at=utc_now(),
        )

        async with self._lock:

            self._forecasts[
                key
            ] = forecast

        return forecast

    async def get_snapshot(
        self,
        tenant_id: str,
        product_id: str,
        warehouse_id: str,
    ) -> DemandSnapshot:

        key = resource_key(
            tenant_id,
            product_id,
            warehouse_id,
        )

        async with self._lock:

            observations = list(
                self._observations.get(
                    key,
                    [],
                )
            )

        if not observations:

            return DemandSnapshot(
                tenant_id=tenant_id,
                product_id=product_id,
                warehouse_id=warehouse_id,
                observations=0,
                latest_units=None,
                average_units=None,
                trend=(
                    DemandTrend.INSUFFICIENT_DATA
                ),
                last_observed_at=None,
            )

        return DemandSnapshot(
            tenant_id=tenant_id,
            product_id=product_id,
            warehouse_id=warehouse_id,
            observations=len(observations),
            latest_units=(
                observations[-1].units_sold
            ),
            average_units=(
                statistics.mean(
                    item.units_sold
                    for item in observations
                )
            ),
            trend=(
                observations[-1].trend
            ),
            last_observed_at=(
                observations[-1].observed_at
            ),
        )


demand_store = DemandStreamStore()


# ============================================================
# REALTIME NOTIFICATIONS
# ============================================================

async def publish_demand_event(
    observation: DemandObservation,
) -> int:
    """
    Send a minimal tenant-scoped notification.

    Existing ConnectionManager does not
    implement warehouse-specific filtering.
    Therefore warehouse-level observations
    are not broadcast tenant-wide here.
    """

    return 0


async def publish_forecast_update(
    forecast: DemandForecast,
) -> int:
    """
    Intentionally disabled until
    warehouse-aware WebSocket routing
    is implemented.
    """

    return 0


# ============================================================
# API ROUTER
# ============================================================

router = APIRouter(
    prefix="/api/v1/demand-stream",
    tags=["Demand Stream"],
)


@router.post(
    "/observations",
    response_model=DemandObservationResponse,
)
async def ingest_demand_observation(
    payload: DemandObservationCreate,
    principal: CurrentPrincipal,
):

    require_demand_access(
        principal,
        payload.warehouse_id,
        write=True,
    )

    observation, created = (
        await demand_store.add_observation(
            principal.tenant_id,
            payload,
        )
    )

    if created:
        await publish_demand_event(
            observation
        )

    return DemandObservationResponse(
        observation_id=observation.observation_id,
        tenant_id=observation.tenant_id,
        product_id=observation.product_id,
        warehouse_id=observation.warehouse_id,
        units_sold=observation.units_sold,
        observed_at=observation.observed_at,
        baseline_units=observation.baseline_units,
        demand_ratio=observation.demand_ratio,
        trend=observation.trend,
        detected_event=(
            observation.detected_event
        ),
    )


@router.post("/forecasts")
async def update_demand_forecast(
    payload: DemandForecastUpdate,
    principal: CurrentPrincipal,
):

    require_demand_access(
        principal,
        payload.warehouse_id,
        write=True,
    )

    forecast = await demand_store.update_forecast(
        principal.tenant_id,
        payload,
    )

    await publish_forecast_update(
        forecast
    )

    return {
        "product_id": forecast.product_id,
        "warehouse_id": forecast.warehouse_id,
        "forecast_units": forecast.forecast_units,
        "horizon_days": forecast.horizon_days,
        "model_version": forecast.model_version,
        "updated_at": forecast.updated_at,
    }


@router.get(
    "/snapshot/{warehouse_id}/{product_id}",
    response_model=DemandSnapshot,
)
async def get_demand_snapshot(
    warehouse_id: str,
    product_id: str,
    principal: CurrentPrincipal,
):

    require_demand_access(
        principal,
        warehouse_id,
    )

    return await demand_store.get_snapshot(
        principal.tenant_id,
        product_id,
        warehouse_id,
    )
