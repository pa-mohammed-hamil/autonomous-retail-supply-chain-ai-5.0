from __future__ import annotations

"""Planned module: market trends. Implementation pending."""

"""
backend/market_trends.py

Autonomous Retail Supply Chain AI 5.0
Market Trends Intelligence API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Capabilities:
    - Market observation ingestion
    - Product/category market histories
    - Price and demand trend detection
    - Competitor price comparison
    - Moving-average analytics
    - Volatility and risk indicators
    - Market opportunity signals
    - Tenant/warehouse access control
    - Idempotent ingestion
    - Optimistic concurrency
    - Market overview dashboards

Prototype limitations:
    - In-memory single-process storage
    - No live market-data provider
    - No source verification
    - No ML model training
    - No automatic pricing changes
    - No durable audit ledger
"""


import asyncio
import hashlib
import json
import secrets
import statistics

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum

from fastapi import APIRouter, HTTPException, Query

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


API_PREFIX = "/api/v1/market-trends"

MAX_OBSERVATIONS_PER_TENANT = 100_000
MAX_IDEMPOTENCY_KEYS = 150_000
MAX_LIST_LIMIT = 200
MAX_ANALYSIS_DAYS = 365
MAX_ANALYSIS_POINTS = 1000

MONEY_QUANTUM = Decimal("0.01")


# ============================================================
# ENUMS
# ============================================================

class MarketSourceType(str, Enum):
    INTERNAL_SALES = "internal_sales"
    MARKET_RESEARCH = "market_research"
    COMPETITOR_CATALOG = "competitor_catalog"
    SUPPLIER_FEED = "supplier_feed"
    MARKETPLACE = "marketplace"
    MANUAL = "manual"


class MarketMetricType(str, Enum):
    SELLING_PRICE = "selling_price"
    COMPETITOR_PRICE = "competitor_price"
    UNIT_DEMAND = "unit_demand"
    SALES_VOLUME = "sales_volume"
    SUPPLIER_COST = "supplier_cost"


class TrendDirection(str, Enum):
    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"
    INSUFFICIENT_DATA = "insufficient_data"


class MarketRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class OpportunityType(str, Enum):
    DEMAND_GROWTH = "demand_growth"
    PRICE_ADVANTAGE = "price_advantage"
    COST_PRESSURE = "cost_pressure"
    DEMAND_DECLINE = "demand_decline"
    NONE = "none"


# ============================================================
# REQUEST MODELS
# ============================================================

class MarketObservationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    category_id: str = Field(
        min_length=1,
        max_length=128,
    )

    source_type: MarketSourceType

    source_reference: str = Field(
        min_length=3,
        max_length=200,
    )

    metric_type: MarketMetricType

    observation_date: date

    value: Decimal = Field(
        ge=0,
        le=Decimal("999999999999.99"),
        max_digits=14,
        decimal_places=2,
    )

    currency: str | None = Field(
        default=None,
        pattern=r"^[A-Z]{3}$",
    )

    competitor_id: str | None = Field(
        default=None,
        max_length=128,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_observation(self):

        monetary = {
            MarketMetricType.SELLING_PRICE,
            MarketMetricType.COMPETITOR_PRICE,
            MarketMetricType.SUPPLIER_COST,
        }

        if self.metric_type in monetary:
            if self.currency is None:
                raise ValueError(
                    "Currency required for monetary metrics"
                )

        elif self.currency is not None:
            raise ValueError(
                "Currency is only valid for monetary metrics"
            )

        if self.metric_type == MarketMetricType.COMPETITOR_PRICE:
            if not self.competitor_id:
                raise ValueError(
                    "Competitor ID required"
                )

        elif self.competitor_id is not None:
            raise ValueError(
                "Competitor ID only applies to competitor prices"
            )

        if self.observation_date > datetime.now(
            timezone.utc
        ).date():
            raise ValueError(
                "Future observation dates are not allowed"
            )

        return self


class MarketTrendQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str
    product_id: str

    metric_type: MarketMetricType

    currency: str | None = None

    days: int = Field(
        default=30,
        ge=2,
        le=MAX_ANALYSIS_DAYS,
    )

    moving_average_window: int = Field(
        default=7,
        ge=2,
        le=90,
    )


class CompetitorComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    currency: str = Field(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    )

    days: int = Field(
        default=30,
        ge=1,
        le=MAX_ANALYSIS_DAYS,
    )


# ============================================================
# RESPONSE MODELS
# ============================================================

class MarketObservationResponse(BaseModel):
    observation_id: str

    warehouse_id: str
    product_id: str
    category_id: str

    source_type: MarketSourceType
    source_reference: str

    metric_type: MarketMetricType
    observation_date: date

    value: Decimal
    currency: str | None
    competitor_id: str | None

    created_by: str
    created_at: datetime


class MarketTrendPoint(BaseModel):
    observation_date: date
    average_value: float
    observation_count: int
    moving_average: float | None


class MarketTrendResponse(BaseModel):
    warehouse_id: str
    product_id: str

    metric_type: MarketMetricType
    currency: str | None

    observation_count: int
    unique_observation_days: int

    first_value: float | None
    latest_value: float | None

    average_value: float | None
    minimum_value: float | None
    maximum_value: float | None

    change_percent: float | None
    volatility_percent: float | None

    trend: TrendDirection
    risk_level: MarketRiskLevel

    points: list[MarketTrendPoint]

    methodology: str


class CompetitorPriceResponse(BaseModel):
    competitor_id: str

    average_price: Decimal
    latest_price: Decimal

    observation_count: int
    latest_observation_date: date


class CompetitorComparisonResponse(BaseModel):
    warehouse_id: str
    product_id: str
    currency: str

    internal_price: Decimal | None

    competitors: list[CompetitorPriceResponse]

    lowest_competitor_price: Decimal | None
    highest_competitor_price: Decimal | None

    price_advantage_percent: float | None

    opportunity: OpportunityType


class MarketOverviewResponse(BaseModel):
    warehouse_id: str

    total_observations: int
    unique_products: int
    unique_categories: int

    price_observations: int
    demand_observations: int
    competitor_observations: int

    unique_sources: int

    earliest_observation_date: date | None
    latest_observation_date: date | None


# ============================================================
# INTERNAL RECORD
# ============================================================

@dataclass
class MarketObservationRecord:
    observation_id: str
    tenant_id: str

    warehouse_id: str
    product_id: str
    category_id: str

    source_type: MarketSourceType
    source_reference: str

    metric_type: MarketMetricType
    observation_date: date

    value: Decimal
    currency: str | None
    competitor_id: str | None

    created_by: str

    created_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def money(value: Decimal) -> Decimal:
    return value.quantize(
        MONEY_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def request_fingerprint(
    payload: MarketObservationCreate,
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


def require_market_access(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool,
) -> None:

    # Placeholder permission mapping.
    # Add MARKET_DATA_READ and MARKET_DATA_WRITE
    # to backend.permissions for production.

    permission = (
        Permission.AI_AGENT_CONFIGURE
        if write
        else Permission.ANALYTICS_READ
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
            detail="Market data access denied",
        )


def to_observation(
    record: MarketObservationRecord,
) -> MarketObservationResponse:

    return MarketObservationResponse(
        observation_id=record.observation_id,
        warehouse_id=record.warehouse_id,
        product_id=record.product_id,
        category_id=record.category_id,
        source_type=record.source_type,
        source_reference=record.source_reference,
        metric_type=record.metric_type,
        observation_date=record.observation_date,
        value=record.value,
        currency=record.currency,
        competitor_id=record.competitor_id,
        created_by=record.created_by,
        created_at=record.created_at,
    )


# ============================================================
# TREND ANALYSIS ENGINE
# ============================================================

class MarketTrendEngine:

    @staticmethod
    def percentage_change(
        first: float,
        latest: float,
    ) -> float | None:

        if first == 0:
            return None

        return round(
            (latest - first) / first * 100,
            2,
        )

    @staticmethod
    def volatility(
        values: list[float],
    ) -> float | None:

        if len(values) < 3:
            return None

        average = statistics.mean(values)

        if average == 0:
            return None

        deviation = statistics.pstdev(values)

        return round(
            deviation / abs(average) * 100,
            2,
        )

    @staticmethod
    def classify_trend(
        change_percent: float | None,
        count: int,
    ) -> TrendDirection:

        if count < 3 or change_percent is None:
            return TrendDirection.INSUFFICIENT_DATA

        if change_percent >= 5:
            return TrendDirection.INCREASING

        if change_percent <= -5:
            return TrendDirection.DECREASING

        return TrendDirection.STABLE

    @staticmethod
    def classify_risk(
        volatility: float | None,
        count: int,
    ) -> MarketRiskLevel:

        if count < 3 or volatility is None:
            return MarketRiskLevel.UNKNOWN

        if volatility >= 40:
            return MarketRiskLevel.CRITICAL

        if volatility >= 25:
            return MarketRiskLevel.HIGH

        if volatility >= 10:
            return MarketRiskLevel.MEDIUM

        return MarketRiskLevel.LOW

    @classmethod
    def analyze(
        cls,
        records: list[MarketObservationRecord],
        query: MarketTrendQuery,
    ) -> MarketTrendResponse:

        grouped: dict[date, list[float]] = {}

        for record in records:
            grouped.setdefault(
                record.observation_date,
                [],
            ).append(float(record.value))

        dates = sorted(grouped)

        daily_values = [
            statistics.mean(grouped[day])
            for day in dates
        ]

        points = []

        for index, day in enumerate(dates):

            moving_average = None

            window = query.moving_average_window

            if index + 1 >= window:
                moving_average = round(
                    statistics.mean(
                        daily_values[
                            index - window + 1:
                            index + 1
                        ]
                    ),
                    4,
                )

            points.append(
                MarketTrendPoint(
                    observation_date=day,
                    average_value=round(
                        daily_values[index],
                        4,
                    ),
                    observation_count=len(
                        grouped[day]
                    ),
                    moving_average=moving_average,
                )
            )

        first = (
            daily_values[0]
            if daily_values
            else None
        )

        latest = (
            daily_values[-1]
            if daily_values
            else None
        )

        change = (
            cls.percentage_change(
                first,
                latest,
            )
            if first is not None
            and latest is not None
            else None
        )

        volatility = cls.volatility(
            daily_values
        )

        return MarketTrendResponse(
            warehouse_id=query.warehouse_id,
            product_id=query.product_id,
            metric_type=query.metric_type,
            currency=query.currency,
            observation_count=len(records),
            unique_observation_days=len(dates),
            first_value=(
                round(first, 4)
                if first is not None
                else None
            ),
            latest_value=(
                round(latest, 4)
                if latest is not None
                else None
            ),
            average_value=(
                round(
                    statistics.mean(daily_values),
                    4,
                )
                if daily_values
                else None
            ),
            minimum_value=(
                round(min(daily_values), 4)
                if daily_values
                else None
            ),
            maximum_value=(
                round(max(daily_values), 4)
                if daily_values
                else None
            ),
            change_percent=change,
            volatility_percent=volatility,
            trend=cls.classify_trend(
                change,
                len(dates),
            ),
            risk_level=cls.classify_risk(
                volatility,
                len(dates),
            ),
            points=points,
            methodology=(
                "Daily arithmetic averages; "
                "trailing moving average; "
                "first-to-last percentage change; "
                "population coefficient of variation. "
                "Missing dates are not imputed. "
                "These are heuristic signals, "
                "not verified forecasts."
            ),
        )


# ============================================================
# MARKET DATA STORE
# ============================================================

class MarketTrendStore:

    def __init__(self):

        self._records: dict[
            str,
            MarketObservationRecord,
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
        payload: MarketObservationCreate,
    ) -> MarketObservationResponse:

        require_market_access(
            principal,
            payload.warehouse_id,
            write=True,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        fingerprint = request_fingerprint(
            payload
        )

        async with self._lock:

            previous = self._idempotency.get(
                key
            )

            if previous is not None:

                previous_hash, observation_id = (
                    previous
                )

                if previous_hash != fingerprint:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                record = self._records[
                    observation_id
                ]

                return to_observation(record)

            tenant_count = sum(
                record.tenant_id
                == principal.tenant_id
                for record in self._records.values()
            )

            if (
                tenant_count >= MAX_OBSERVATIONS_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Market data capacity reached",
                )

            record = MarketObservationRecord(
                observation_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                product_id=payload.product_id,
                category_id=payload.category_id,
                source_type=payload.source_type,
                source_reference=payload.source_reference,
                metric_type=payload.metric_type,
                observation_date=payload.observation_date,
                value=payload.value,
                currency=payload.currency,
                competitor_id=payload.competitor_id,
                created_by=principal.principal_id,
            )

            self._records[
                record.observation_id
            ] = record

            self._idempotency[key] = (
                fingerprint,
                record.observation_id,
            )

            return to_observation(record)

    async def get(
        self,
        *,
        principal: Principal,
        observation_id: str,
    ) -> MarketObservationResponse:

        async with self._lock:

            record = self._records.get(
                observation_id
            )

            if (
                record is None
                or record.tenant_id
                != principal.tenant_id
            ):
                raise HTTPException(
                    status_code=404,
                    detail="Observation not found",
                )

            require_market_access(
                principal,
                record.warehouse_id,
                write=False,
            )

            return to_observation(record)

    async def list_records(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
        product_id: str | None,
        category_id: str | None,
        metric_type: MarketMetricType | None,
        limit: int,
    ) -> list[MarketObservationResponse]:

        require_market_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._records.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and record.warehouse_id
                    == warehouse_id
                    and (
                        product_id is None
                        or record.product_id == product_id
                    )
                    and (
                        category_id is None
                        or record.category_id == category_id
                    )
                    and (
                        metric_type is None
                        or record.metric_type == metric_type
                    )
                )
            ]

            records.sort(
                key=lambda item: (
                    item.observation_date,
                    item.created_at,
                ),
                reverse=True,
            )

            return [
                to_observation(record)
                for record in records[:limit]
            ]

    async def query_history(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
        product_id: str,
        metric_type: MarketMetricType,
        currency: str | None,
        days: int,
    ) -> list[MarketObservationRecord]:

        require_market_access(
            principal,
            warehouse_id,
            write=False,
        )

        from datetime import timedelta

        cutoff = utc_now().date() - timedelta(
            days=days - 1
        )

        async with self._lock:

            records = [
                record
                for record in self._records.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and record.warehouse_id
                    == warehouse_id
                    and record.product_id
                    == product_id
                    and record.metric_type
                    == metric_type
                    and record.observation_date
                    >= cutoff
                    and record.currency == currency
                )
            ]

            records.sort(
                key=lambda item: (
                    item.observation_date,
                    item.created_at,
                )
            )

            if len(records) > MAX_ANALYSIS_POINTS:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Too many observations for "
                        "one analysis; narrow the period"
                    ),
                )

            return list(records)

    async def comparison(
        self,
        *,
        principal: Principal,
        payload: CompetitorComparisonRequest,
    ) -> CompetitorComparisonResponse:

        require_market_access(
            principal,
            payload.warehouse_id,
            write=False,
        )

        from datetime import timedelta

        cutoff = utc_now().date() - timedelta(
            days=payload.days - 1
        )

        async with self._lock:

            records = [
                record
                for record in self._records.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and record.warehouse_id
                    == payload.warehouse_id
                    and record.product_id
                    == payload.product_id
                    and record.currency
                    == payload.currency
                    and record.observation_date
                    >= cutoff
                )
            ]

            internal = [
                record
                for record in records
                if record.metric_type
                == MarketMetricType.SELLING_PRICE
            ]

            internal.sort(
                key=lambda item: (
                    item.observation_date,
                    item.created_at,
                )
            )

            internal_price = (
                internal[-1].value
                if internal
                else None
            )

            competitor_groups: dict[
                str,
                list[MarketObservationRecord],
            ] = {}

            for record in records:

                if (
                    record.metric_type
                    != MarketMetricType.COMPETITOR_PRICE
                ):
                    continue

                if record.competitor_id is None:
                    continue

                competitor_groups.setdefault(
                    record.competitor_id,
                    [],
                ).append(record)

            competitors = []

            for competitor_id, group in sorted(
                competitor_groups.items()
            ):

                group.sort(
                    key=lambda item: (
                        item.observation_date,
                        item.created_at,
                    )
                )

                average_price = (
                    sum(
                        (
                            item.value
                            for item in group
                        ),
                        Decimal("0"),
                    )
                    / Decimal(len(group))
                )

                competitors.append(
                    CompetitorPriceResponse(
                        competitor_id=competitor_id,
                        average_price=money(
                            average_price
                        ),
                        latest_price=group[-1].value,
                        observation_count=len(group),
                        latest_observation_date=(
                            group[-1].observation_date
                        ),
                    )
                )

            prices = [
                item.latest_price
                for item in competitors
            ]

            lowest = min(prices) if prices else None
            highest = max(prices) if prices else None

            advantage = None
            opportunity = OpportunityType.NONE

            if (
                internal_price is not None
                and lowest is not None
                and lowest > 0
            ):

                advantage = round(
                    float(
                        (
                            lowest - internal_price
                        ) / lowest * 100
                    ),
                    2,
                )

                if advantage >= 5:
                    opportunity = (
                        OpportunityType.PRICE_ADVANTAGE
                    )

                elif advantage <= -5:
                    opportunity = (
                        OpportunityType.COST_PRESSURE
                    )

            return CompetitorComparisonResponse(
                warehouse_id=payload.warehouse_id,
                product_id=payload.product_id,
                currency=payload.currency,
                internal_price=internal_price,
                competitors=competitors,
                lowest_competitor_price=lowest,
                highest_competitor_price=highest,
                price_advantage_percent=advantage,
                opportunity=opportunity,
            )

    async def overview(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
    ) -> MarketOverviewResponse:

        require_market_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._records.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and record.warehouse_id
                    == warehouse_id
                )
            ]

            dates = [
                record.observation_date
                for record in records
            ]

            return MarketOverviewResponse(
                warehouse_id=warehouse_id,
                total_observations=len(records),
                unique_products=len({
                    record.product_id
                    for record in records
                }),
                unique_categories=len({
                    record.category_id
                    for record in records
                }),
                price_observations=sum(
                    record.metric_type
                    == MarketMetricType.SELLING_PRICE
                    for record in records
                ),
                demand_observations=sum(
                    record.metric_type
                    == MarketMetricType.UNIT_DEMAND
                    for record in records
                ),
                competitor_observations=sum(
                    record.metric_type
                    == MarketMetricType.COMPETITOR_PRICE
                    for record in records
                ),
                unique_sources=len({
                    (
                        record.source_type,
                        record.source_reference,
                    )
                    for record in records
                }),
                earliest_observation_date=(
                    min(dates)
                    if dates
                    else None
                ),
                latest_observation_date=(
                    max(dates)
                    if dates
                    else None
                ),
            )


market_trend_store = MarketTrendStore()


# ============================================================
# SERVICE
# ============================================================

class MarketTrendService:

    def __init__(
        self,
        store: MarketTrendStore,
    ):
        self.store = store

    async def ingest(
        self,
        principal: Principal,
        payload: MarketObservationCreate,
    ) -> MarketObservationResponse:

        return await self.store.create(
            principal=principal,
            payload=payload,
        )

    async def analyze(
        self,
        principal: Principal,
        query: MarketTrendQuery,
    ) -> MarketTrendResponse:

        monetary = {
            MarketMetricType.SELLING_PRICE,
            MarketMetricType.COMPETITOR_PRICE,
            MarketMetricType.SUPPLIER_COST,
        }

        if query.metric_type in monetary:
            if query.currency is None:
                raise HTTPException(
                    status_code=422,
                    detail="Currency is required",
                )

        elif query.currency is not None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Currency not applicable "
                    "to this metric"
                ),
            )

        records = await self.store.query_history(
            principal=principal,
            warehouse_id=query.warehouse_id,
            product_id=query.product_id,
            metric_type=query.metric_type,
            currency=query.currency,
            days=query.days,
        )

        return MarketTrendEngine.analyze(
            records,
            query,
        )


market_trend_service = MarketTrendService(
    market_trend_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Market Trends Intelligence"],
)


@router.post(
    "/observations",
    response_model=MarketObservationResponse,
    status_code=201,
)
async def create_market_observation(
    payload: MarketObservationCreate,
    principal: CurrentPrincipal,
):
    return await market_trend_service.ingest(
        principal,
        payload,
    )


@router.get(
    "/observations",
    response_model=list[MarketObservationResponse],
)
async def list_market_observations(
    principal: CurrentPrincipal,
    warehouse_id: str,
    product_id: str | None = None,
    category_id: str | None = None,
    metric_type: MarketMetricType | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await market_trend_store.list_records(
        principal=principal,
        warehouse_id=warehouse_id,
        product_id=product_id,
        category_id=category_id,
        metric_type=metric_type,
        limit=limit,
    )


@router.get(
    "/observations/{observation_id}",
    response_model=MarketObservationResponse,
)
async def get_market_observation(
    observation_id: str,
    principal: CurrentPrincipal,
):
    return await market_trend_store.get(
        principal=principal,
        observation_id=observation_id,
    )


@router.post(
    "/analyze",
    response_model=MarketTrendResponse,
)
async def analyze_market_trend(
    payload: MarketTrendQuery,
    principal: CurrentPrincipal,
):
    return await market_trend_service.analyze(
        principal,
        payload,
    )


@router.post(
    "/competitors/compare",
    response_model=CompetitorComparisonResponse,
)
async def compare_competitor_prices(
    payload: CompetitorComparisonRequest,
    principal: CurrentPrincipal,
):
    return await market_trend_store.comparison(
        principal=principal,
        payload=payload,
    )


@router.get(
    "/overview/{warehouse_id}",
    response_model=MarketOverviewResponse,
)
async def get_market_overview(
    warehouse_id: str,
    principal: CurrentPrincipal,
):
    return await market_trend_store.overview(
        principal=principal,
        warehouse_id=warehouse_id,
    )


__all__ = [
    "MarketSourceType",
    "MarketMetricType",
    "TrendDirection",
    "MarketRiskLevel",
    "OpportunityType",
    "MarketObservationCreate",
    "MarketTrendQuery",
    "CompetitorComparisonRequest",
    "MarketObservationResponse",
    "MarketTrendPoint",
    "MarketTrendResponse",
    "CompetitorPriceResponse",
    "CompetitorComparisonResponse",
    "MarketOverviewResponse",
    "MarketTrendEngine",
    "MarketTrendStore",
    "MarketTrendService",
    "market_trend_store",
    "market_trend_service",
    "router",
]
