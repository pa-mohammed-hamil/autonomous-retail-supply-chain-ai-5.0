from __future__ import annotations

"""Planned module: demand. Implementation pending."""

"""
backend/demand.py

Autonomous Retail Supply Chain AI 5.0
Demand Forecasting and Inventory Planning API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Historical daily demand ingestion
    - Tenant and warehouse isolation
    - Demand forecasting
    - Weekly seasonality adjustment
    - Moving-average baseline
    - Demand volatility analysis
    - Forecast confidence bands
    - Stockout risk estimation
    - Replenishment recommendations
    - Demand scenario simulation
    - Forecast model metadata
    - Forecast quality metrics
    - Idempotent sales ingestion
    - Bounded in-memory prototype storage

IMPORTANT:
    This module uses a deterministic statistical
    baseline rather than a trained ML model.

    Integrate ai/ml/trend_forecasting.py and
    backend/services/demand_service.py through
    a tested forecasting adapter.

    The forecast bands are heuristic and
    must not be interpreted as calibrated
    prediction intervals.

    This module does not create purchase orders
    or modify inventory automatically.
"""


import asyncio
import hashlib
import json
import math
import secrets
import statistics

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from enum import Enum

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


# ============================================================
# CONFIGURATION
# ============================================================

API_PREFIX = "/api/v1/demand"

MAX_HISTORY_RECORDS = 100_000
MAX_FORECAST_DAYS = 90
MAX_HISTORY_DAYS = 730
MAX_SCENARIO_CHANGE_PERCENT = 200.0

MIN_HISTORY_DAYS = 7
DEFAULT_MOVING_AVERAGE_WINDOW = 28

MODEL_NAME = "seasonal-moving-average"
MODEL_VERSION = "1.0.0"


# ============================================================
# ENUMS
# ============================================================

class DemandTrend(str, Enum):
    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"
    INSUFFICIENT_DATA = "insufficient_data"


class DemandRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ForecastMethod(str, Enum):
    MOVING_AVERAGE = "moving_average"
    SEASONAL_MOVING_AVERAGE = (
        "seasonal_moving_average"
    )


# ============================================================
# REQUEST MODELS
# ============================================================

class DemandObservationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    observation_date: date

    quantity_sold: int = Field(
        ge=0,
        le=10_000_000,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )


class DemandForecastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    horizon_days: int = Field(
        default=14,
        ge=1,
        le=MAX_FORECAST_DAYS,
    )

    history_days: int = Field(
        default=90,
        ge=MIN_HISTORY_DAYS,
        le=MAX_HISTORY_DAYS,
    )

    moving_average_window: int = Field(
        default=DEFAULT_MOVING_AVERAGE_WINDOW,
        ge=3,
        le=90,
    )

    seasonal: bool = True


class DemandScenarioRequest(
    DemandForecastRequest
):
    demand_change_percent: float = Field(
        default=0,
        ge=-100,
        le=MAX_SCENARIO_CHANGE_PERCENT,
        allow_inf_nan=False,
    )


class ReplenishmentRequest(
    DemandForecastRequest
):
    current_stock: int = Field(
        ge=0,
        le=100_000_000,
    )

    incoming_stock: int = Field(
        default=0,
        ge=0,
        le=100_000_000,
    )

    lead_time_days: int = Field(
        ge=1,
        le=365,
    )

    review_period_days: int = Field(
        default=7,
        ge=1,
        le=90,
    )

    safety_stock_days: int = Field(
        default=5,
        ge=0,
        le=90,
    )

    @model_validator(mode="after")
    def validate_horizon(self):
        # Replenishment uses its own
        # protection period, which may be
        # longer than the display horizon.
        return self


# ============================================================
# RESPONSE MODELS
# ============================================================

class DemandObservationResponse(BaseModel):
    observation_id: str
    warehouse_id: str
    product_id: str
    observation_date: date
    quantity_sold: int
    created_at: datetime


class DemandHistoryResponse(BaseModel):
    warehouse_id: str
    product_id: str
    observations: list[
        DemandObservationResponse
    ]
    total_quantity: int
    average_daily_demand: float
    observed_days: int


class DemandForecastPoint(BaseModel):
    forecast_date: date
    predicted_quantity: float
    lower_bound: float
    upper_bound: float


class DemandForecastResponse(BaseModel):
    forecast_id: str

    warehouse_id: str
    product_id: str

    model_name: str
    model_version: str
    method: ForecastMethod

    generated_at: datetime
    horizon_days: int
    history_days_used: int

    average_daily_demand: float
    demand_std_dev: float
    trend: DemandTrend

    forecast_total: float

    confidence_band_note: str

    forecasts: list[
        DemandForecastPoint
    ]


class DemandScenarioResponse(BaseModel):
    warehouse_id: str
    product_id: str

    demand_change_percent: float

    baseline_total: float
    scenario_total: float
    quantity_difference: float

    baseline: list[DemandForecastPoint]
    scenario: list[DemandForecastPoint]


class ReplenishmentResponse(BaseModel):
    warehouse_id: str
    product_id: str

    current_stock: int
    incoming_stock: int

    average_daily_demand: float
    lead_time_days: int

    estimated_days_of_cover: float | None

    reorder_point: int
    target_stock: int
    recommended_order_quantity: int

    risk_level: DemandRiskLevel

    explanation: str


class DemandMetricsResponse(BaseModel):
    warehouse_id: str
    product_id: str

    observations: int
    total_units_sold: int

    average_daily_demand: float
    maximum_daily_demand: int

    standard_deviation: float

    coefficient_of_variation: float | None

    trend: DemandTrend


# ============================================================
# INTERNAL HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def safe_mean(
    values: list[float],
) -> float:

    return (
        statistics.mean(values)
        if values
        else 0.0
    )


def safe_std(
    values: list[float],
) -> float:

    return (
        statistics.pstdev(values)
        if len(values) > 1
        else 0.0
    )


def require_demand_access(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool = False,
) -> None:

    permission = (
        Permission.INVENTORY_WRITE
        if write
        else Permission.ANALYTICS_READ
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
            detail="Demand access denied",
        )

    allowed = principal.allowed_warehouse_ids

    if (
        allowed is not None
        and warehouse_id not in allowed
    ):
        raise HTTPException(
            status_code=403,
            detail="Warehouse access denied",
        )


def observation_fingerprint(
    payload: DemandObservationCreate,
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


def classify_trend(
    values: list[float],
) -> DemandTrend:

    if len(values) < 14:
        return DemandTrend.INSUFFICIENT_DATA

    midpoint = len(values) // 2

    first = safe_mean(
        values[:midpoint]
    )

    second = safe_mean(
        values[midpoint:]
    )

    if first == 0:
        return (
            DemandTrend.INCREASING
            if second > 0
            else DemandTrend.STABLE
        )

    change = (second - first) / first

    if change > 0.10:
        return DemandTrend.INCREASING

    if change < -0.10:
        return DemandTrend.DECREASING

    return DemandTrend.STABLE


# ============================================================
# DEMAND HISTORY STORE
# ============================================================

class DemandStore:

    def __init__(self):

        self._observations: dict[
            tuple[str, str, str, date],
            DemandObservationResponse,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[
                str,
                DemandObservationResponse,
            ],
        ] = {}

        self._lock = asyncio.Lock()

    async def ingest(
        self,
        *,
        principal: Principal,
        payload: DemandObservationCreate,
    ) -> DemandObservationResponse:

        require_demand_access(
            principal,
            payload.warehouse_id,
            write=True,
        )

        if payload.observation_date > date.today():
            raise HTTPException(
                status_code=422,
                detail="Future demand observations are not allowed",
            )

        fingerprint = observation_fingerprint(
            payload
        )

        idempotency_key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        record_key = (
            principal.tenant_id,
            payload.warehouse_id,
            payload.product_id,
            payload.observation_date,
        )

        async with self._lock:

            previous = self._idempotency.get(
                idempotency_key
            )

            if previous is not None:

                old_fingerprint, response = previous

                if old_fingerprint != fingerprint:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return response.model_copy(
                    deep=True
                )

            if record_key in self._observations:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Demand observation already exists "
                        "for this product and date"
                    ),
                )

            if (
                len(self._observations)
                >= MAX_HISTORY_RECORDS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Demand history capacity reached",
                )

            observation = DemandObservationResponse(
                observation_id=secrets.token_urlsafe(18),
                warehouse_id=payload.warehouse_id,
                product_id=payload.product_id,
                observation_date=payload.observation_date,
                quantity_sold=payload.quantity_sold,
                created_at=utc_now(),
            )

            self._observations[
                record_key
            ] = observation

            self._idempotency[
                idempotency_key
            ] = (
                fingerprint,
                observation.model_copy(deep=True),
            )

            return observation

    async def history(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
        product_id: str,
        days: int,
    ) -> list[DemandObservationResponse]:

        require_demand_access(
            principal,
            warehouse_id,
        )

        cutoff = (
            date.today()
            - timedelta(days=days - 1)
        )

        async with self._lock:

            records = [
                item.model_copy(deep=True)
                for key, item
                in self._observations.items()
                if (
                    key[0] == principal.tenant_id
                    and key[1] == warehouse_id
                    and key[2] == product_id
                    and key[3] >= cutoff
                    and key[3] <= date.today()
                )
            ]

            records.sort(
                key=lambda item: item.observation_date
            )

            return records


demand_store = DemandStore()


# ============================================================
# FORECAST ENGINE
# ============================================================

class DemandForecastEngine:

    @staticmethod
    def daily_series(
        observations: list[
            DemandObservationResponse
        ],
    ) -> tuple[list[date], list[float]]:

        if not observations:
            return [], []

        by_date = {
            item.observation_date: float(
                item.quantity_sold
            )
            for item in observations
        }

        start = observations[0].observation_date
        end = observations[-1].observation_date

        dates = []
        values = []

        current = start

        while current <= end:

            dates.append(current)

            # Missing dates are treated as zero.
            # Production data must distinguish
            # zero sales from missing records.
            values.append(
                by_date.get(current, 0.0)
            )

            current += timedelta(days=1)

        return dates, values

    @staticmethod
    def seasonality_factors(
        dates: list[date],
        values: list[float],
    ) -> dict[int, float]:

        overall = safe_mean(values)

        if overall <= 0:
            return {
                weekday: 1.0
                for weekday in range(7)
            }

        grouped = defaultdict(list)

        for day, value in zip(
            dates,
            values,
        ):
            grouped[
                day.weekday()
            ].append(value)

        factors = {}

        for weekday in range(7):

            weekday_values = grouped.get(
                weekday,
                [],
            )

            if len(weekday_values) < 2:
                factors[weekday] = 1.0
                continue

            factor = (
                safe_mean(weekday_values)
                / overall
            )

            factors[weekday] = max(
                0.25,
                min(2.5, factor),
            )

        # Normalize the factors so that
        # their weekly average equals 1.
        factor_mean = safe_mean(
            list(factors.values())
        )

        if factor_mean > 0:
            factors = {
                weekday: value / factor_mean
                for weekday, value
                in factors.items()
            }

        return factors

    def forecast(
        self,
        *,
        warehouse_id: str,
        product_id: str,
        observations: list[
            DemandObservationResponse
        ],
        horizon_days: int,
        moving_average_window: int,
        seasonal: bool,
    ) -> DemandForecastResponse:

        dates, values = self.daily_series(
            observations
        )

        if len(values) < MIN_HISTORY_DAYS:
            raise HTTPException(
                status_code=422,
                detail=(
                    "At least seven days of "
                    "demand history are required"
                ),
            )

        recent_values = values[
            -moving_average_window:
        ]

        baseline = safe_mean(
            recent_values
        )

        std_dev = safe_std(
            recent_values
        )

        factors = (
            self.seasonality_factors(
                dates,
                values,
            )
            if seasonal
            else {
                weekday: 1.0
                for weekday in range(7)
            }
        )

        last_date = dates[-1]

        # Forecast starts after the latest
        # recorded observation.
        # Production scheduling should enforce
        # data freshness before forecasting.

        forecasts = []

        for offset in range(
            1,
            horizon_days + 1,
        ):

            forecast_date = (
                last_date
                + timedelta(days=offset)
            )

            factor = factors[
                forecast_date.weekday()
            ]

            predicted = max(
                0.0,
                baseline * factor,
            )

            # Heuristic uncertainty band:
            # widening with forecast horizon.
            uncertainty = (
                1.96
                * std_dev
                * math.sqrt(
                    1 + offset / 7
                )
            )

            lower = max(
                0.0,
                predicted - uncertainty,
            )

            upper = (
                predicted + uncertainty
            )

            forecasts.append(
                DemandForecastPoint(
                    forecast_date=forecast_date,
                    predicted_quantity=round(
                        predicted,
                        2,
                    ),
                    lower_bound=round(
                        lower,
                        2,
                    ),
                    upper_bound=round(
                        upper,
                        2,
                    ),
                )
            )

        return DemandForecastResponse(
            forecast_id=secrets.token_urlsafe(18),
            warehouse_id=warehouse_id,
            product_id=product_id,
            model_name=MODEL_NAME,
            model_version=MODEL_VERSION,
            method=(
                ForecastMethod.SEASONAL_MOVING_AVERAGE
                if seasonal
                else ForecastMethod.MOVING_AVERAGE
            ),
            generated_at=utc_now(),
            horizon_days=horizon_days,
            history_days_used=len(values),
            average_daily_demand=round(
                baseline,
                2,
            ),
            demand_std_dev=round(
                std_dev,
                2,
            ),
            trend=classify_trend(
                values
            ),
            forecast_total=round(
                sum(
                    item.predicted_quantity
                    for item in forecasts
                ),
                2,
            ),
            confidence_band_note=(
                "Heuristic volatility bands; "
                "not statistically calibrated "
                "prediction intervals."
            ),
            forecasts=forecasts,
        )


forecast_engine = DemandForecastEngine()


# ============================================================
# DEMAND SERVICE
# ============================================================

class DemandService:

    def __init__(
        self,
        store: DemandStore,
        engine: DemandForecastEngine,
    ):
        self.store = store
        self.engine = engine

    async def get_forecast(
        self,
        *,
        principal: Principal,
        payload: DemandForecastRequest,
    ) -> DemandForecastResponse:

        observations = await self.store.history(
            principal=principal,
            warehouse_id=payload.warehouse_id,
            product_id=payload.product_id,
            days=payload.history_days,
        )

        return self.engine.forecast(
            warehouse_id=payload.warehouse_id,
            product_id=payload.product_id,
            observations=observations,
            horizon_days=payload.horizon_days,
            moving_average_window=(
                payload.moving_average_window
            ),
            seasonal=payload.seasonal,
        )

    async def get_scenario(
        self,
        *,
        principal: Principal,
        payload: DemandScenarioRequest,
    ) -> DemandScenarioResponse:

        baseline = await self.get_forecast(
            principal=principal,
            payload=payload,
        )

        multiplier = max(
            0.0,
            1 + payload.demand_change_percent / 100,
        )

        scenario = []

        for point in baseline.forecasts:

            scenario.append(
                DemandForecastPoint(
                    forecast_date=point.forecast_date,
                    predicted_quantity=round(
                        point.predicted_quantity
                        * multiplier,
                        2,
                    ),
                    lower_bound=round(
                        point.lower_bound
                        * multiplier,
                        2,
                    ),
                    upper_bound=round(
                        point.upper_bound
                        * multiplier,
                        2,
                    ),
                )
            )

        scenario_total = round(
            sum(
                item.predicted_quantity
                for item in scenario
            ),
            2,
        )

        return DemandScenarioResponse(
            warehouse_id=payload.warehouse_id,
            product_id=payload.product_id,
            demand_change_percent=(
                payload.demand_change_percent
            ),
            baseline_total=baseline.forecast_total,
            scenario_total=scenario_total,
            quantity_difference=round(
                scenario_total
                - baseline.forecast_total,
                2,
            ),
            baseline=baseline.forecasts,
            scenario=scenario,
        )

    async def replenishment(
        self,
        *,
        principal: Principal,
        payload: ReplenishmentRequest,
    ) -> ReplenishmentResponse:

        forecast = await self.get_forecast(
            principal=principal,
            payload=payload,
        )

        average = (
            forecast.average_daily_demand
        )

        protection_days = (
            payload.lead_time_days
            + payload.review_period_days
        )

        reorder_point = math.ceil(
            average
            * (
                payload.lead_time_days
                + payload.safety_stock_days
            )
        )

        target_stock = math.ceil(
            average
            * (
                protection_days
                + payload.safety_stock_days
            )
        )

        projected_available = (
            payload.current_stock
            + payload.incoming_stock
        )

        recommended = max(
            0,
            target_stock - projected_available,
        )

        days_of_cover = (
            payload.current_stock / average
            if average > 0
            else None
        )

        if average <= 0:
            risk = DemandRiskLevel.LOW

        elif payload.current_stock < average:
            risk = DemandRiskLevel.CRITICAL

        elif (
            payload.current_stock
            < average * payload.lead_time_days
        ):
            risk = DemandRiskLevel.HIGH

        elif (
            payload.current_stock
            < reorder_point
        ):
            risk = DemandRiskLevel.MEDIUM

        else:
            risk = DemandRiskLevel.LOW

        return ReplenishmentResponse(
            warehouse_id=payload.warehouse_id,
            product_id=payload.product_id,
            current_stock=payload.current_stock,
            incoming_stock=payload.incoming_stock,
            average_daily_demand=average,
            lead_time_days=payload.lead_time_days,
            estimated_days_of_cover=(
                round(days_of_cover, 2)
                if days_of_cover is not None
                else None
            ),
            reorder_point=reorder_point,
            target_stock=target_stock,
            recommended_order_quantity=recommended,
            risk_level=risk,
            explanation=(
                "Recommendation uses average demand, "
                "lead time, review period and a "
                "days-of-demand safety-stock buffer. "
                "It does not account for supplier "
                "minimum order quantities, "
                "service-level targets, lead-time "
                "uncertainty or inventory already "
                "allocated to open orders."
            ),
        )

    async def metrics(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
        product_id: str,
        days: int,
    ) -> DemandMetricsResponse:

        observations = await self.store.history(
            principal=principal,
            warehouse_id=warehouse_id,
            product_id=product_id,
            days=days,
        )

        dates, values = (
            self.engine.daily_series(
                observations
            )
        )

        average = safe_mean(values)
        std_dev = safe_std(values)

        cv = (
            std_dev / average
            if average > 0
            else None
        )

        return DemandMetricsResponse(
            warehouse_id=warehouse_id,
            product_id=product_id,
            observations=len(observations),
            total_units_sold=sum(
                item.quantity_sold
                for item in observations
            ),
            average_daily_demand=round(
                average,
                2,
            ),
            maximum_daily_demand=int(
                max(values, default=0)
            ),
            standard_deviation=round(
                std_dev,
                2,
            ),
            coefficient_of_variation=(
                round(cv, 4)
                if cv is not None
                else None
            ),
            trend=classify_trend(
                values
            ),
        )


demand_service = DemandService(
    demand_store,
    forecast_engine,
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Demand Forecasting"],
)


@router.post(
    "/observations",
    response_model=DemandObservationResponse,
    status_code=201,
)
async def ingest_demand_observation(
    payload: DemandObservationCreate,
    principal: CurrentPrincipal,
):
    return await demand_store.ingest(
        principal=principal,
        payload=payload,
    )


@router.get(
    "/history/{warehouse_id}/{product_id}",
    response_model=DemandHistoryResponse,
)
async def get_demand_history(
    warehouse_id: str,
    product_id: str,
    principal: CurrentPrincipal,
    days: int = Query(
        default=90,
        ge=1,
        le=MAX_HISTORY_DAYS,
    ),
):

    observations = await demand_store.history(
        principal=principal,
        warehouse_id=warehouse_id,
        product_id=product_id,
        days=days,
    )

    _, values = forecast_engine.daily_series(
        observations
    )

    return DemandHistoryResponse(
        warehouse_id=warehouse_id,
        product_id=product_id,
        observations=observations,
        total_quantity=sum(
            item.quantity_sold
            for item in observations
        ),
        average_daily_demand=round(
            safe_mean(values),
            2,
        ),
        observed_days=len(observations),
    )


@router.post(
    "/forecast",
    response_model=DemandForecastResponse,
)
async def forecast_demand(
    payload: DemandForecastRequest,
    principal: CurrentPrincipal,
):
    return await demand_service.get_forecast(
        principal=principal,
        payload=payload,
    )


@router.post(
    "/scenario",
    response_model=DemandScenarioResponse,
)
async def simulate_demand_scenario(
    payload: DemandScenarioRequest,
    principal: CurrentPrincipal,
):
    return await demand_service.get_scenario(
        principal=principal,
        payload=payload,
    )


@router.post(
    "/replenishment",
    response_model=ReplenishmentResponse,
)
async def recommend_replenishment(
    payload: ReplenishmentRequest,
    principal: CurrentPrincipal,
):
    return await demand_service.replenishment(
        principal=principal,
        payload=payload,
    )


@router.get(
    "/metrics/{warehouse_id}/{product_id}",
    response_model=DemandMetricsResponse,
)
async def get_demand_metrics(
    warehouse_id: str,
    product_id: str,
    principal: CurrentPrincipal,
    days: int = Query(
        default=90,
        ge=1,
        le=MAX_HISTORY_DAYS,
    ),
):
    return await demand_service.metrics(
        principal=principal,
        warehouse_id=warehouse_id,
        product_id=product_id,
        days=days,
    )


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "DemandTrend",
    "DemandRiskLevel",
    "ForecastMethod",
    "DemandObservationCreate",
    "DemandForecastRequest",
    "DemandScenarioRequest",
    "ReplenishmentRequest",
    "DemandObservationResponse",
    "DemandHistoryResponse",
    "DemandForecastPoint",
    "DemandForecastResponse",
    "DemandScenarioResponse",
    "ReplenishmentResponse",
    "DemandMetricsResponse",
    "DemandStore",
    "DemandForecastEngine",
    "DemandService",
    "demand_store",
    "forecast_engine",
    "demand_service",
    "router",
]
