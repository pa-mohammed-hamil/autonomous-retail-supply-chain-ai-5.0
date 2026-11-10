from __future__ import annotations

"""Planned module: simulations. Implementation pending."""

"""
backend/simulations.py

Autonomous Retail Supply Chain AI 5.0
Supply Chain What-If Simulation API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Demand spike simulations
    - Supplier delay simulations
    - Stockout risk simulations
    - Replenishment simulations
    - Logistics disruption simulations
    - Warehouse capacity simulations
    - Scenario comparison
    - Cost and service-level estimation
    - Deterministic simulation engine
    - Tenant/warehouse authorization
    - Idempotent simulation creation
    - Optimistic concurrency for cancellation
    - Simulation history and analytics

This is a deterministic prototype. It does not
execute real inventory transfers, procurement,
pricing, or logistics actions.
"""


import asyncio
import hashlib
import json
import secrets

from dataclasses import dataclass
from datetime import datetime, timezone
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


API_PREFIX = "/api/v1/simulations"

MAX_SIMULATIONS_PER_TENANT = 50000
MAX_IDEMPOTENCY_KEYS = 100000
MAX_LIST_LIMIT = 200
MONEY_QUANTUM = Decimal("0.01")


# ============================================================
# ENUMS
# ============================================================

class SimulationType(str, Enum):
    DEMAND_SPIKE = "demand_spike"
    SUPPLIER_DELAY = "supplier_delay"
    STOCKOUT = "stockout"
    REPLENISHMENT = "replenishment"
    LOGISTICS_DISRUPTION = "logistics_disruption"
    WAREHOUSE_CAPACITY = "warehouse_capacity"


class SimulationStatus(str, Enum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ============================================================
# REQUEST MODELS
# ============================================================

class SimulationParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_stock: int = Field(ge=0, le=100000000)

    daily_demand: float = Field(
        gt=0,
        le=10000000,
        allow_inf_nan=False,
    )

    lead_time_days: int = Field(
        ge=0,
        le=3650,
    )

    forecast_horizon_days: int = Field(
        default=30,
        ge=1,
        le=365,
    )

    safety_stock: int = Field(
        default=0,
        ge=0,
        le=100000000,
    )

    demand_multiplier: float = Field(
        default=1.0,
        gt=0,
        le=100,
        allow_inf_nan=False,
    )

    supplier_delay_days: int = Field(
        default=0,
        ge=0,
        le=365,
    )

    replenishment_quantity: int = Field(
        default=0,
        ge=0,
        le=100000000,
    )

    transport_delay_days: int = Field(
        default=0,
        ge=0,
        le=365,
    )

    warehouse_capacity: int | None = Field(
        default=None,
        gt=0,
    )

    unit_cost: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        max_digits=16,
        decimal_places=2,
    )

    selling_price: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        max_digits=16,
        decimal_places=2,
    )

    holding_cost_per_unit_day: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        max_digits=12,
        decimal_places=4,
    )

    stockout_penalty_per_unit: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        max_digits=12,
        decimal_places=2,
    )

    @model_validator(mode="after")
    def validate_parameters(self):

        if (
            self.warehouse_capacity is not None
            and self.current_stock > self.warehouse_capacity
        ):
            raise ValueError(
                "Current stock exceeds warehouse capacity"
            )

        return self


class SimulationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=3, max_length=200)

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    simulation_type: SimulationType

    parameters: SimulationParameters

    notes: str = Field(
        default="",
        max_length=2000,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )


class SimulationCompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    simulation_ids: list[str] = Field(
        min_length=2,
        max_length=10,
    )

    @model_validator(mode="after")
    def unique_ids(self):

        if len(set(self.simulation_ids)) != len(
            self.simulation_ids
        ):
            raise ValueError(
                "Duplicate simulation IDs"
            )

        return self


class SimulationCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    reason: str = Field(
        min_length=3,
        max_length=500,
    )


# ============================================================
# RESPONSE MODELS
# ============================================================

class SimulationMetrics(BaseModel):
    forecast_demand_units: float

    projected_available_units: float
    projected_shortage_units: float
    projected_surplus_units: float

    days_of_cover: float
    effective_lead_time_days: int

    fill_rate_percent: float
    capacity_utilization_percent: float | None

    procurement_cost: Decimal
    holding_cost: Decimal
    stockout_cost: Decimal
    total_estimated_cost: Decimal

    risk_score: float
    risk_level: RiskLevel


class SimulationResponse(BaseModel):
    simulation_id: str

    name: str
    warehouse_id: str
    product_id: str

    simulation_type: SimulationType
    status: SimulationStatus

    metrics: SimulationMetrics

    recommendations: list[str]

    version: int
    created_at: datetime


class SimulationDetailResponse(SimulationResponse):
    parameters: SimulationParameters
    notes: str
    created_by: str


class SimulationComparisonItem(BaseModel):
    simulation_id: str
    name: str
    simulation_type: SimulationType

    total_estimated_cost: Decimal
    fill_rate_percent: float
    risk_score: float
    risk_level: RiskLevel


class SimulationComparisonResponse(BaseModel):
    warehouse_id: str
    product_id: str

    simulations: list[SimulationComparisonItem]

    lowest_cost_simulation_id: str
    highest_fill_rate_simulation_id: str
    lowest_risk_simulation_id: str


class SimulationAnalyticsResponse(BaseModel):
    total_simulations: int
    completed_simulations: int
    cancelled_simulations: int

    high_risk_simulations: int
    critical_risk_simulations: int

    average_risk_score: float | None
    average_fill_rate_percent: float | None


# ============================================================
# INTERNAL RECORD
# ============================================================

@dataclass
class SimulationRecord:
    simulation_id: str
    tenant_id: str

    name: str
    warehouse_id: str
    product_id: str

    simulation_type: SimulationType
    parameters: SimulationParameters

    metrics: SimulationMetrics
    recommendations: list[str]

    notes: str
    created_by: str

    status: SimulationStatus = (
        SimulationStatus.COMPLETED
    )

    version: int = 1

    created_at: datetime = datetime.min.replace(
        tzinfo=timezone.utc
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


def fingerprint(payload: SimulationCreate) -> str:

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


def require_simulation_access(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool,
) -> None:

    # Replace these placeholder permissions with
    # SIMULATION_READ / SIMULATION_EXECUTE.

    permission = (
        Permission.AI_AGENT_CONFIGURE
        if write
        else Permission.ANALYTICS_READ
    )

    if (
        principal.allowed_warehouse_ids is not None
        and warehouse_id not in principal.allowed_warehouse_ids
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
            detail="Simulation access denied",
        )


# ============================================================
# SIMULATION ENGINE
# ============================================================

class SimulationEngine:

    @staticmethod
    def calculate(
        simulation_type: SimulationType,
        parameters: SimulationParameters,
    ) -> tuple[SimulationMetrics, list[str]]:

        p = parameters

        demand_multiplier = p.demand_multiplier
        supplier_delay = p.supplier_delay_days
        transport_delay = p.transport_delay_days
        replenishment = p.replenishment_quantity

        if simulation_type == SimulationType.DEMAND_SPIKE:
            demand_multiplier = max(
                demand_multiplier,
                1.5,
            )

        elif simulation_type == SimulationType.SUPPLIER_DELAY:
            supplier_delay = max(
                supplier_delay,
                3,
            )

        elif simulation_type == SimulationType.LOGISTICS_DISRUPTION:
            transport_delay = max(
                transport_delay,
                2,
            )

        elif simulation_type == SimulationType.REPLENISHMENT:
            replenishment = max(
                replenishment,
                p.safety_stock,
            )

        effective_daily_demand = (
            p.daily_demand * demand_multiplier
        )

        effective_lead_time = (
            p.lead_time_days
            + supplier_delay
            + transport_delay
        )

        horizon = p.forecast_horizon_days

        forecast_demand = (
            effective_daily_demand * horizon
        )

        # Simplified assumption:
        # replenishment arrives within the horizon
        # only if lead time <= horizon.
        inbound_units = (
            replenishment
            if effective_lead_time <= horizon
            else 0
        )

        total_supply = (
            p.current_stock + inbound_units
        )

        projected_shortage = max(
            0.0,
            forecast_demand - total_supply,
        )

        projected_surplus = max(
            0.0,
            total_supply - forecast_demand,
        )

        fulfilled_units = min(
            forecast_demand,
            total_supply,
        )

        fill_rate = (
            fulfilled_units / forecast_demand * 100
            if forecast_demand > 0
            else 100.0
        )

        days_of_cover = (
            total_supply / effective_daily_demand
            if effective_daily_demand > 0
            else 0.0
        )

        capacity_utilization = None

        if p.warehouse_capacity is not None:

            peak_stock = (
                p.current_stock + inbound_units
            )

            capacity_utilization = (
                peak_stock
                / p.warehouse_capacity
                * 100
            )

        procurement_cost = money(
            Decimal(replenishment)
            * p.unit_cost
        )

        # Simplified holding-cost estimate.
        average_inventory = max(
            0.0,
            (
                p.current_stock
                + projected_surplus
            ) / 2,
        )

        holding_cost = money(
            Decimal(str(average_inventory))
            * Decimal(horizon)
            * p.holding_cost_per_unit_day
        )

        stockout_cost = money(
            Decimal(str(projected_shortage))
            * p.stockout_penalty_per_unit
        )

        total_cost = money(
            procurement_cost
            + holding_cost
            + stockout_cost
        )

        shortage_ratio = (
            projected_shortage / forecast_demand
            if forecast_demand > 0
            else 0.0
        )

        lead_time_risk = min(
            effective_lead_time / max(horizon, 1),
            1.0,
        )

        capacity_risk = (
            min(
                max(
                    capacity_utilization - 100,
                    0,
                ) / 100,
                1.0,
            )
            if capacity_utilization is not None
            else 0.0
        )

        risk_score = round(
            min(
                100.0,
                (
                    shortage_ratio * 65
                    + lead_time_risk * 25
                    + capacity_risk * 10
                ),
            ),
            2,
        )

        if risk_score >= 75:
            risk_level = RiskLevel.CRITICAL
        elif risk_score >= 50:
            risk_level = RiskLevel.HIGH
        elif risk_score >= 25:
            risk_level = RiskLevel.MEDIUM
        else:
            risk_level = RiskLevel.LOW

        recommendations = []

        if projected_shortage > 0:
            recommendations.append(
                "Review replenishment quantities and "
                "available inventory before the forecast horizon."
            )

        if effective_lead_time > horizon:
            recommendations.append(
                "Consider alternative suppliers or "
                "expedited logistics because lead time "
                "exceeds the forecast horizon."
            )

        if (
            capacity_utilization is not None
            and capacity_utilization > 100
        ):
            recommendations.append(
                "Evaluate warehouse overflow capacity "
                "or stagger inbound deliveries."
            )

        if risk_level in {
            RiskLevel.HIGH,
            RiskLevel.CRITICAL,
        }:
            recommendations.append(
                "Escalate this scenario for human review "
                "before operational decisions."
            )

        if not recommendations:
            recommendations.append(
                "Scenario indicators are within the "
                "configured heuristic risk thresholds."
            )

        metrics = SimulationMetrics(
            forecast_demand_units=round(
                forecast_demand, 2
            ),
            projected_available_units=round(
                total_supply, 2
            ),
            projected_shortage_units=round(
                projected_shortage, 2
            ),
            projected_surplus_units=round(
                projected_surplus, 2
            ),
            days_of_cover=round(
                days_of_cover, 2
            ),
            effective_lead_time_days=(
                effective_lead_time
            ),
            fill_rate_percent=round(
                fill_rate, 2
            ),
            capacity_utilization_percent=(
                round(capacity_utilization, 2)
                if capacity_utilization is not None
                else None
            ),
            procurement_cost=procurement_cost,
            holding_cost=holding_cost,
            stockout_cost=stockout_cost,
            total_estimated_cost=total_cost,
            risk_score=risk_score,
            risk_level=risk_level,
        )

        return metrics, recommendations


# ============================================================
# RESPONSE MAPPING
# ============================================================

def to_response(
    record: SimulationRecord,
) -> SimulationResponse:

    return SimulationResponse(
        simulation_id=record.simulation_id,
        name=record.name,
        warehouse_id=record.warehouse_id,
        product_id=record.product_id,
        simulation_type=record.simulation_type,
        status=record.status,
        metrics=record.metrics,
        recommendations=list(record.recommendations),
        version=record.version,
        created_at=record.created_at,
    )


def to_detail(
    record: SimulationRecord,
) -> SimulationDetailResponse:

    return SimulationDetailResponse(
        **to_response(record).model_dump(),
        parameters=record.parameters,
        notes=record.notes,
        created_by=record.created_by,
    )


# ============================================================
# SIMULATION STORE
# ============================================================

class SimulationStore:

    def __init__(self):

        self._simulations: dict[
            str,
            SimulationRecord,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    def _get(
        self,
        principal: Principal,
        simulation_id: str,
        *,
        write: bool,
    ) -> SimulationRecord:

        record = self._simulations.get(
            simulation_id
        )

        if (
            record is None
            or record.tenant_id != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Simulation not found",
            )

        require_simulation_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    async def create(
        self,
        *,
        principal: Principal,
        payload: SimulationCreate,
    ) -> SimulationResponse:

        require_simulation_access(
            principal,
            payload.warehouse_id,
            write=True,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = fingerprint(payload)

        async with self._lock:

            previous = self._idempotency.get(key)

            if previous is not None:

                old_hash, simulation_id = previous

                if old_hash != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return to_response(
                    self._get(
                        principal,
                        simulation_id,
                        write=False,
                    )
                )

            tenant_count = sum(
                record.tenant_id == principal.tenant_id
                for record in self._simulations.values()
            )

            if (
                tenant_count
                >= MAX_SIMULATIONS_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Simulation capacity reached",
                )

            metrics, recommendations = (
                SimulationEngine.calculate(
                    payload.simulation_type,
                    payload.parameters,
                )
            )

            record = SimulationRecord(
                simulation_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                name=payload.name,
                warehouse_id=payload.warehouse_id,
                product_id=payload.product_id,
                simulation_type=payload.simulation_type,
                parameters=payload.parameters,
                metrics=metrics,
                recommendations=recommendations,
                notes=payload.notes,
                created_by=principal.principal_id,
                created_at=utc_now(),
            )

            self._simulations[
                record.simulation_id
            ] = record

            self._idempotency[key] = (
                request_hash,
                record.simulation_id,
            )

            return to_response(record)

    async def get(
        self,
        *,
        principal: Principal,
        simulation_id: str,
    ) -> SimulationDetailResponse:

        async with self._lock:

            return to_detail(
                self._get(
                    principal,
                    simulation_id,
                    write=False,
                )
            )

    async def list_simulations(
        self,
        *,
        principal: Principal,
        warehouse_id: str | None,
        simulation_type: SimulationType | None,
        limit: int,
    ) -> list[SimulationResponse]:

        if warehouse_id is not None:
            require_simulation_access(
                principal,
                warehouse_id,
                write=False,
            )

        async with self._lock:

            records = [
                record
                for record in self._simulations.values()
                if (
                    record.tenant_id == principal.tenant_id
                    and (
                        warehouse_id is None
                        or record.warehouse_id == warehouse_id
                    )
                    and (
                        simulation_type is None
                        or record.simulation_type == simulation_type
                    )
                )
            ]

            records.sort(
                key=lambda record: record.created_at,
                reverse=True,
            )

            results = []

            for record in records:

                try:
                    require_simulation_access(
                        principal,
                        record.warehouse_id,
                        write=False,
                    )
                except HTTPException:
                    continue

                results.append(to_response(record))

                if len(results) >= limit:
                    break

            return results

    async def compare(
        self,
        *,
        principal: Principal,
        payload: SimulationCompareRequest,
    ) -> SimulationComparisonResponse:

        async with self._lock:

            records = [
                self._get(
                    principal,
                    simulation_id,
                    write=False,
                )
                for simulation_id in payload.simulation_ids
            ]

            if any(
                record.status != SimulationStatus.COMPLETED
                for record in records
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Only completed simulations can be compared",
                )

            warehouse_ids = {
                record.warehouse_id
                for record in records
            }

            product_ids = {
                record.product_id
                for record in records
            }

            if (
                len(warehouse_ids) != 1
                or len(product_ids) != 1
            ):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Comparison requires the same "
                        "warehouse and product"
                    ),
                )

            # Compare only simulations with the same
            # currency/cost assumptions in production.
            items = [
                SimulationComparisonItem(
                    simulation_id=record.simulation_id,
                    name=record.name,
                    simulation_type=record.simulation_type,
                    total_estimated_cost=(
                        record.metrics.total_estimated_cost
                    ),
                    fill_rate_percent=(
                        record.metrics.fill_rate_percent
                    ),
                    risk_score=record.metrics.risk_score,
                    risk_level=record.metrics.risk_level,
                )
                for record in records
            ]

            lowest_cost = min(
                items,
                key=lambda item: item.total_estimated_cost,
            )

            highest_fill = max(
                items,
                key=lambda item: item.fill_rate_percent,
            )

            lowest_risk = min(
                items,
                key=lambda item: item.risk_score,
            )

            return SimulationComparisonResponse(
                warehouse_id=records[0].warehouse_id,
                product_id=records[0].product_id,
                simulations=items,
                lowest_cost_simulation_id=(
                    lowest_cost.simulation_id
                ),
                highest_fill_rate_simulation_id=(
                    highest_fill.simulation_id
                ),
                lowest_risk_simulation_id=(
                    lowest_risk.simulation_id
                ),
            )

    async def cancel(
        self,
        *,
        principal: Principal,
        simulation_id: str,
        payload: SimulationCancelRequest,
    ) -> SimulationResponse:

        async with self._lock:

            record = self._get(
                principal,
                simulation_id,
                write=True,
            )

            if record.version != payload.expected_version:
                raise HTTPException(
                    status_code=409,
                    detail="Simulation version conflict",
                )

            if record.status == SimulationStatus.CANCELLED:
                raise HTTPException(
                    status_code=409,
                    detail="Simulation already cancelled",
                )

            record.status = SimulationStatus.CANCELLED
            record.version += 1

            return to_response(record)

    async def analytics(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
    ) -> SimulationAnalyticsResponse:

        require_simulation_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._simulations.values()
                if (
                    record.tenant_id == principal.tenant_id
                    and record.warehouse_id == warehouse_id
                )
            ]

            completed = [
                record
                for record in records
                if record.status == SimulationStatus.COMPLETED
            ]

            return SimulationAnalyticsResponse(
                total_simulations=len(records),
                completed_simulations=len(completed),
                cancelled_simulations=(
                    len(records) - len(completed)
                ),
                high_risk_simulations=sum(
                    record.metrics.risk_level == RiskLevel.HIGH
                    for record in completed
                ),
                critical_risk_simulations=sum(
                    record.metrics.risk_level == RiskLevel.CRITICAL
                    for record in completed
                ),
                average_risk_score=(
                    round(
                        sum(
                            record.metrics.risk_score
                            for record in completed
                        ) / len(completed),
                        2,
                    )
                    if completed
                    else None
                ),
                average_fill_rate_percent=(
                    round(
                        sum(
                            record.metrics.fill_rate_percent
                            for record in completed
                        ) / len(completed),
                        2,
                    )
                    if completed
                    else None
                ),
            )


simulation_store = SimulationStore()


# ============================================================
# SERVICE
# ============================================================

class SimulationService:

    def __init__(
        self,
        store: SimulationStore,
    ):
        self.store = store

    async def create(
        self,
        principal: Principal,
        payload: SimulationCreate,
    ) -> SimulationResponse:

        return await self.store.create(
            principal=principal,
            payload=payload,
        )


simulation_service = SimulationService(
    simulation_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Supply Chain Simulations"],
)


@router.post(
    "",
    response_model=SimulationResponse,
    status_code=201,
)
async def create_simulation(
    payload: SimulationCreate,
    principal: CurrentPrincipal,
):
    return await simulation_service.create(
        principal,
        payload,
    )


@router.get(
    "",
    response_model=list[SimulationResponse],
)
async def list_simulations(
    principal: CurrentPrincipal,
    warehouse_id: str | None = None,
    simulation_type: SimulationType | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await simulation_store.list_simulations(
        principal=principal,
        warehouse_id=warehouse_id,
        simulation_type=simulation_type,
        limit=limit,
    )


@router.post(
    "/compare",
    response_model=SimulationComparisonResponse,
)
async def compare_simulations(
    payload: SimulationCompareRequest,
    principal: CurrentPrincipal,
):
    return await simulation_store.compare(
        principal=principal,
        payload=payload,
    )


@router.get(
    "/analytics/{warehouse_id}",
    response_model=SimulationAnalyticsResponse,
)
async def simulation_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
):
    return await simulation_store.analytics(
        principal=principal,
        warehouse_id=warehouse_id,
    )


@router.get(
    "/{simulation_id}",
    response_model=SimulationDetailResponse,
)
async def get_simulation(
    simulation_id: str,
    principal: CurrentPrincipal,
):
    return await simulation_store.get(
        principal=principal,
        simulation_id=simulation_id,
    )


@router.post(
    "/{simulation_id}/cancel",
    response_model=SimulationResponse,
)
async def cancel_simulation(
    simulation_id: str,
    payload: SimulationCancelRequest,
    principal: CurrentPrincipal,
):
    return await simulation_store.cancel(
        principal=principal,
        simulation_id=simulation_id,
        payload=payload,
    )


__all__ = [
    "SimulationType",
    "SimulationStatus",
    "RiskLevel",
    "SimulationParameters",
    "SimulationCreate",
    "SimulationCompareRequest",
    "SimulationCancelRequest",
    "SimulationMetrics",
    "SimulationResponse",
    "SimulationDetailResponse",
    "SimulationComparisonItem",
    "SimulationComparisonResponse",
    "SimulationAnalyticsResponse",
    "SimulationEngine",
    "SimulationStore",
    "SimulationService",
    "simulation_store",
    "simulation_service",
    "router",
]
