from __future__ import annotations

"""Planned module: digital twin. Implementation pending."""

"""
backend/digital_twin.py

Autonomous Retail Supply Chain AI 5.0
Warehouse Digital Twin and Scenario Simulation API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Warehouse digital twin creation
    - Inventory and capacity snapshots
    - Daily demand simulation
    - Supplier delay scenarios
    - Demand surge scenarios
    - Replenishment scenarios
    - Warehouse disruption scenarios
    - Cost and service-level estimates
    - Scenario comparison
    - Tenant and warehouse isolation
    - Optimistic concurrency
    - Bounded in-memory storage

Limitations:
    - Deterministic planning model
    - No live IoT or WMS synchronization
    - No automatic purchase orders
    - No real-world operational actions
    - No persistent database
"""


import asyncio
import hashlib
import json
import math
import secrets

from dataclasses import dataclass, field
from datetime import datetime, timezone
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


API_PREFIX = "/api/v1/digital-twin"

MAX_TWINS_PER_TENANT = 1000
MAX_RUNS_PER_TENANT = 5000
MAX_SKUS_PER_TWIN = 500
MAX_HORIZON_DAYS = 180


# ============================================================
# ENUMS
# ============================================================

class TwinStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"


class ScenarioType(str, Enum):
    BASELINE = "baseline"
    DEMAND_SURGE = "demand_surge"
    SUPPLIER_DELAY = "supplier_delay"
    CAPACITY_REDUCTION = "capacity_reduction"
    REPLENISHMENT = "replenishment"
    COMBINED = "combined"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ============================================================
# REQUEST MODELS
# ============================================================

class TwinSKU(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    opening_stock: int = Field(
        ge=0,
        le=100_000_000,
    )

    daily_demand: float = Field(
        ge=0,
        le=1_000_000,
        allow_inf_nan=False,
    )

    reorder_point: int = Field(
        ge=0,
        le=100_000_000,
    )

    reorder_quantity: int = Field(
        ge=0,
        le=100_000_000,
    )

    lead_time_days: int = Field(
        ge=1,
        le=365,
    )

    unit_holding_cost_per_day: float = Field(
        default=0.0,
        ge=0,
        le=1_000_000,
        allow_inf_nan=False,
    )

    stockout_cost_per_unit: float = Field(
        default=0.0,
        ge=0,
        le=1_000_000,
        allow_inf_nan=False,
    )


class TwinCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    name: str = Field(
        min_length=2,
        max_length=150,
    )

    capacity_units: int = Field(
        gt=0,
        le=1_000_000_000,
    )

    skus: list[TwinSKU] = Field(
        min_length=1,
        max_length=MAX_SKUS_PER_TWIN,
    )

    @model_validator(mode="after")
    def validate_skus(self):
        ids = [sku.product_id for sku in self.skus]

        if len(ids) != len(set(ids)):
            raise ValueError(
                "Duplicate product IDs are not allowed"
            )

        if sum(
            sku.opening_stock
            for sku in self.skus
        ) > self.capacity_units:
            raise ValueError(
                "Opening inventory exceeds capacity"
            )

        return self


class TwinUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    capacity_units: int = Field(
        gt=0,
        le=1_000_000_000,
    )

    skus: list[TwinSKU] = Field(
        min_length=1,
        max_length=MAX_SKUS_PER_TWIN,
    )

    @model_validator(mode="after")
    def validate_skus(self):
        ids = [sku.product_id for sku in self.skus]

        if len(ids) != len(set(ids)):
            raise ValueError(
                "Duplicate product IDs are not allowed"
            )

        if sum(
            sku.opening_stock
            for sku in self.skus
        ) > self.capacity_units:
            raise ValueError(
                "Opening inventory exceeds capacity"
            )

        return self


class ScenarioParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    demand_multiplier: float = Field(
        default=1.0,
        ge=0,
        le=5,
        allow_inf_nan=False,
    )

    additional_lead_time_days: int = Field(
        default=0,
        ge=0,
        le=180,
    )

    capacity_multiplier: float = Field(
        default=1.0,
        gt=0,
        le=2,
        allow_inf_nan=False,
    )

    replenishment_multiplier: float = Field(
        default=1.0,
        ge=0,
        le=5,
        allow_inf_nan=False,
    )


class SimulationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_name: str = Field(
        min_length=2,
        max_length=150,
    )

    scenario_type: ScenarioType

    horizon_days: int = Field(
        default=30,
        ge=1,
        le=MAX_HORIZON_DAYS,
    )

    expected_twin_version: int = Field(ge=1)

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    parameters: ScenarioParameters = Field(
        default_factory=ScenarioParameters
    )


# ============================================================
# RESPONSE MODELS
# ============================================================

class TwinResponse(BaseModel):
    twin_id: str
    warehouse_id: str
    name: str

    status: TwinStatus
    capacity_units: int

    skus: list[TwinSKU]

    version: int
    created_at: datetime
    updated_at: datetime


class DailySimulationPoint(BaseModel):
    day: int
    opening_stock: float
    demand_units: float
    fulfilled_units: float
    lost_sales_units: float
    replenished_units: float
    closing_stock: float
    capacity_units: float
    capacity_excess_units: float


class SKUSimulationResult(BaseModel):
    product_id: str
    total_demand: float
    fulfilled_units: float
    lost_sales_units: float
    ending_stock: float
    replenishment_units: float
    stockout_days: int
    holding_cost: float
    stockout_cost: float


class SimulationSummary(BaseModel):
    total_demand: float
    fulfilled_units: float
    lost_sales_units: float
    fill_rate_percent: float
    ending_stock: float
    replenishment_units: float
    holding_cost: float
    stockout_cost: float
    total_estimated_cost: float
    peak_capacity_excess_units: float
    risk_level: RiskLevel


class SimulationResponse(BaseModel):
    simulation_id: str
    twin_id: str
    warehouse_id: str

    scenario_name: str
    scenario_type: ScenarioType

    twin_version: int
    horizon_days: int

    parameters: ScenarioParameters

    summary: SimulationSummary

    sku_results: list[SKUSimulationResult]
    daily: list[DailySimulationPoint]

    generated_at: datetime


class ScenarioComparison(BaseModel):
    baseline_simulation_id: str
    scenario_simulation_id: str

    fill_rate_change_percentage_points: float
    lost_sales_change_units: float
    total_cost_change: float
    ending_stock_change_units: float
    capacity_excess_change_units: float


# ============================================================
# INTERNAL RECORD
# ============================================================

@dataclass
class TwinRecord:
    twin_id: str
    tenant_id: str
    warehouse_id: str
    owner_id: str

    name: str
    capacity_units: int
    skus: list[TwinSKU]

    status: TwinStatus = TwinStatus.ACTIVE
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
class SimulationRecord:
    tenant_id: str
    owner_id: str
    result: SimulationResponse


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def require_twin_access(
    principal: Principal,
    warehouse_id: str,
    *,
    execute: bool,
) -> None:

    permission = (
        Permission.AI_AGENT_EXECUTE
        if execute
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
            detail="Digital twin permission denied",
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


def to_twin_response(
    record: TwinRecord,
) -> TwinResponse:

    return TwinResponse(
        twin_id=record.twin_id,
        warehouse_id=record.warehouse_id,
        name=record.name,
        status=record.status,
        capacity_units=record.capacity_units,
        skus=[
            sku.model_copy(deep=True)
            for sku in record.skus
        ],
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def fingerprint(
    payload: SimulationCreate,
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


# ============================================================
# SIMULATION ENGINE
# ============================================================

class DigitalTwinEngine:
    """
    Deterministic daily simulation.

    Inventory units are assumed to consume
    one capacity unit each.

    Demand is modeled as expected fractional
    units for planning purposes.

    Replenishment orders are scheduled when
    projected stock falls to reorder point.

    Unfulfilled demand is lost, not backordered.
    """

    def run(
        self,
        *,
        twin: TwinResponse,
        payload: SimulationCreate,
    ) -> SimulationResponse:

        params = payload.parameters

        capacity = (
            twin.capacity_units
            * params.capacity_multiplier
        )

        state = {}

        for sku in twin.skus:

            state[sku.product_id] = {
                "sku": sku,
                "stock": float(
                    sku.opening_stock
                ),
                "pipeline": [],
                "demand": 0.0,
                "fulfilled": 0.0,
                "lost": 0.0,
                "replenished": 0.0,
                "stockout_days": 0,
                "holding_cost": 0.0,
                "stockout_cost": 0.0,
            }

        daily_points = []
        peak_capacity_excess = 0.0

        for day in range(
            1,
            payload.horizon_days + 1,
        ):

            opening_stock = sum(
                item["stock"]
                for item in state.values()
            )

            day_demand = 0.0
            day_fulfilled = 0.0
            day_lost = 0.0
            day_replenished = 0.0

            # Receive scheduled replenishments.
            for item in state.values():

                due = [
                    quantity
                    for arrival_day, quantity
                    in item["pipeline"]
                    if arrival_day == day
                ]

                incoming = sum(due)

                item["pipeline"] = [
                    (arrival_day, quantity)
                    for arrival_day, quantity
                    in item["pipeline"]
                    if arrival_day > day
                ]

                item["stock"] += incoming
                item["replenished"] += incoming
                day_replenished += incoming

            # Capacity check: overflow is
            # measured but not silently removed.
            post_receipt_stock = sum(
                item["stock"]
                for item in state.values()
            )

            capacity_excess = max(
                0.0,
                post_receipt_stock - capacity,
            )

            peak_capacity_excess = max(
                peak_capacity_excess,
                capacity_excess,
            )

            # Fulfill demand and create
            # replenishment orders.
            for item in state.values():

                sku = item["sku"]

                demand = (
                    sku.daily_demand
                    * params.demand_multiplier
                )

                fulfilled = min(
                    item["stock"],
                    demand,
                )

                lost = max(
                    0.0,
                    demand - fulfilled,
                )

                item["stock"] -= fulfilled

                item["demand"] += demand
                item["fulfilled"] += fulfilled
                item["lost"] += lost

                day_demand += demand
                day_fulfilled += fulfilled
                day_lost += lost

                if lost > 0:
                    item["stockout_days"] += 1

                item["holding_cost"] += (
                    item["stock"]
                    * sku.unit_holding_cost_per_day
                )

                item["stockout_cost"] += (
                    lost
                    * sku.stockout_cost_per_unit
                )

                pipeline_quantity = sum(
                    quantity
                    for _, quantity
                    in item["pipeline"]
                )

                inventory_position = (
                    item["stock"]
                    + pipeline_quantity
                )

                if (
                    inventory_position
                    <= sku.reorder_point
                    and sku.reorder_quantity > 0
                ):

                    quantity = (
                        sku.reorder_quantity
                        * params.replenishment_multiplier
                    )

                    if quantity > 0:

                        arrival_day = (
                            day
                            + sku.lead_time_days
                            + params.additional_lead_time_days
                        )

                        item["pipeline"].append(
                            (
                                arrival_day,
                                quantity,
                            )
                        )

            closing_stock = sum(
                item["stock"]
                for item in state.values()
            )

            daily_points.append(
                DailySimulationPoint(
                    day=day,
                    opening_stock=round(
                        opening_stock,
                        2,
                    ),
                    demand_units=round(
                        day_demand,
                        2,
                    ),
                    fulfilled_units=round(
                        day_fulfilled,
                        2,
                    ),
                    lost_sales_units=round(
                        day_lost,
                        2,
                    ),
                    replenished_units=round(
                        day_replenished,
                        2,
                    ),
                    closing_stock=round(
                        closing_stock,
                        2,
                    ),
                    capacity_units=round(
                        capacity,
                        2,
                    ),
                    capacity_excess_units=round(
                        capacity_excess,
                        2,
                    ),
                )
            )

        sku_results = []

        for product_id, item in state.items():

            sku_results.append(
                SKUSimulationResult(
                    product_id=product_id,
                    total_demand=round(
                        item["demand"],
                        2,
                    ),
                    fulfilled_units=round(
                        item["fulfilled"],
                        2,
                    ),
                    lost_sales_units=round(
                        item["lost"],
                        2,
                    ),
                    ending_stock=round(
                        item["stock"],
                        2,
                    ),
                    replenishment_units=round(
                        item["replenished"],
                        2,
                    ),
                    stockout_days=(
                        item["stockout_days"]
                    ),
                    holding_cost=round(
                        item["holding_cost"],
                        2,
                    ),
                    stockout_cost=round(
                        item["stockout_cost"],
                        2,
                    ),
                )
            )

        total_demand = sum(
            item.total_demand
            for item in sku_results
        )

        total_fulfilled = sum(
            item.fulfilled_units
            for item in sku_results
        )

        total_lost = sum(
            item.lost_sales_units
            for item in sku_results
        )

        holding_cost = sum(
            item.holding_cost
            for item in sku_results
        )

        stockout_cost = sum(
            item.stockout_cost
            for item in sku_results
        )

        fill_rate = (
            total_fulfilled / total_demand * 100
            if total_demand > 0
            else 100.0
        )

        if (
            fill_rate < 70
            or peak_capacity_excess > capacity * 0.2
        ):
            risk = RiskLevel.CRITICAL

        elif (
            fill_rate < 85
            or peak_capacity_excess > 0
        ):
            risk = RiskLevel.HIGH

        elif fill_rate < 95:
            risk = RiskLevel.MEDIUM

        else:
            risk = RiskLevel.LOW

        summary = SimulationSummary(
            total_demand=round(
                total_demand,
                2,
            ),
            fulfilled_units=round(
                total_fulfilled,
                2,
            ),
            lost_sales_units=round(
                total_lost,
                2,
            ),
            fill_rate_percent=round(
                fill_rate,
                2,
            ),
            ending_stock=round(
                sum(
                    item.ending_stock
                    for item in sku_results
                ),
                2,
            ),
            replenishment_units=round(
                sum(
                    item.replenishment_units
                    for item in sku_results
                ),
                2,
            ),
            holding_cost=round(
                holding_cost,
                2,
            ),
            stockout_cost=round(
                stockout_cost,
                2,
            ),
            total_estimated_cost=round(
                holding_cost + stockout_cost,
                2,
            ),
            peak_capacity_excess_units=round(
                peak_capacity_excess,
                2,
            ),
            risk_level=risk,
        )

        return SimulationResponse(
            simulation_id=secrets.token_urlsafe(20),
            twin_id=twin.twin_id,
            warehouse_id=twin.warehouse_id,
            scenario_name=payload.scenario_name,
            scenario_type=payload.scenario_type,
            twin_version=twin.version,
            horizon_days=payload.horizon_days,
            parameters=params,
            summary=summary,
            sku_results=sku_results,
            daily=daily_points,
            generated_at=utc_now(),
        )


digital_twin_engine = DigitalTwinEngine()


# ============================================================
# STORE
# ============================================================

class DigitalTwinStore:

    def __init__(self):

        self._twins: dict[
            str,
            TwinRecord,
        ] = {}

        self._simulations: dict[
            str,
            SimulationRecord,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    def _get_twin(
        self,
        principal: Principal,
        twin_id: str,
        *,
        execute: bool,
    ) -> TwinRecord:

        record = self._twins.get(
            twin_id
        )

        if (
            record is None
            or record.tenant_id != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Digital twin not found",
            )

        require_twin_access(
            principal,
            record.warehouse_id,
            execute=execute,
        )

        return record

    async def create(
        self,
        *,
        principal: Principal,
        payload: TwinCreate,
    ) -> TwinResponse:

        require_twin_access(
            principal,
            payload.warehouse_id,
            execute=True,
        )

        async with self._lock:

            tenant_count = sum(
                record.tenant_id == principal.tenant_id
                for record in self._twins.values()
            )

            if tenant_count >= MAX_TWINS_PER_TENANT:
                raise HTTPException(
                    status_code=503,
                    detail="Digital twin capacity reached",
                )

            record = TwinRecord(
                twin_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                owner_id=principal.principal_id,
                name=payload.name,
                capacity_units=payload.capacity_units,
                skus=[
                    sku.model_copy(deep=True)
                    for sku in payload.skus
                ],
            )

            self._twins[
                record.twin_id
            ] = record

            return to_twin_response(
                record
            )

    async def get(
        self,
        *,
        principal: Principal,
        twin_id: str,
    ) -> TwinResponse:

        async with self._lock:

            record = self._get_twin(
                principal,
                twin_id,
                execute=False,
            )

            return to_twin_response(
                record
            )

    async def list_twins(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
        limit: int,
    ) -> list[TwinResponse]:

        require_twin_access(
            principal,
            warehouse_id,
            execute=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._twins.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and record.warehouse_id
                    == warehouse_id
                )
            ]

            records.sort(
                key=lambda item: item.created_at,
                reverse=True,
            )

            return [
                to_twin_response(record)
                for record in records[:limit]
            ]

    async def update(
        self,
        *,
        principal: Principal,
        twin_id: str,
        payload: TwinUpdate,
    ) -> TwinResponse:

        async with self._lock:

            record = self._get_twin(
                principal,
                twin_id,
                execute=True,
            )

            if (
                record.version
                != payload.expected_version
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Digital twin version conflict",
                )

            if record.status != TwinStatus.ACTIVE:
                raise HTTPException(
                    status_code=409,
                    detail="Digital twin is paused",
                )

            record.capacity_units = (
                payload.capacity_units
            )

            record.skus = [
                sku.model_copy(deep=True)
                for sku in payload.skus
            ]

            record.version += 1
            record.updated_at = utc_now()

            return to_twin_response(
                record
            )

    async def simulate(
        self,
        *,
        principal: Principal,
        twin_id: str,
        payload: SimulationCreate,
    ) -> SimulationResponse:

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = hashlib.sha256(
            (
                twin_id + ":"
                + fingerprint(payload)
            ).encode("utf-8")
        ).hexdigest()

        async with self._lock:

            record = self._get_twin(
                principal,
                twin_id,
                execute=True,
            )

            previous = self._idempotency.get(
                key
            )

            if previous is not None:

                old_hash, simulation_id = previous

                if old_hash != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                saved = self._simulations[
                    simulation_id
                ]

                return saved.result.model_copy(
                    deep=True
                )

            if record.status != TwinStatus.ACTIVE:
                raise HTTPException(
                    status_code=409,
                    detail="Digital twin is paused",
                )

            if (
                record.version
                != payload.expected_twin_version
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Digital twin version conflict",
                )

            tenant_runs = sum(
                item.tenant_id == principal.tenant_id
                for item in self._simulations.values()
            )

            if tenant_runs >= MAX_RUNS_PER_TENANT:
                raise HTTPException(
                    status_code=503,
                    detail="Simulation capacity reached",
                )

            # Freeze the source snapshot.
            snapshot = to_twin_response(
                record
            )

            # This prototype holds one lock
            # during simulation execution.
            # Use a bounded worker pool for
            # expensive production models.
            result = digital_twin_engine.run(
                twin=snapshot,
                payload=payload,
            )

            self._simulations[
                result.simulation_id
            ] = SimulationRecord(
                tenant_id=principal.tenant_id,
                owner_id=principal.principal_id,
                result=result.model_copy(
                    deep=True
                ),
            )

            self._idempotency[key] = (
                request_hash,
                result.simulation_id,
            )

            return result

    async def get_simulation(
        self,
        *,
        principal: Principal,
        simulation_id: str,
    ) -> SimulationResponse:

        async with self._lock:

            saved = self._simulations.get(
                simulation_id
            )

            if (
                saved is None
                or saved.tenant_id
                != principal.tenant_id
                or saved.owner_id
                != principal.principal_id
            ):
                raise HTTPException(
                    status_code=404,
                    detail="Simulation not found",
                )

            require_twin_access(
                principal,
                saved.result.warehouse_id,
                execute=False,
            )

            return saved.result.model_copy(
                deep=True
            )

    async def compare(
        self,
        *,
        principal: Principal,
        baseline_id: str,
        scenario_id: str,
    ) -> ScenarioComparison:

        baseline = await self.get_simulation(
            principal=principal,
            simulation_id=baseline_id,
        )

        scenario = await self.get_simulation(
            principal=principal,
            simulation_id=scenario_id,
        )

        if (
            baseline.twin_id != scenario.twin_id
            or baseline.twin_version
            != scenario.twin_version
            or baseline.horizon_days
            != scenario.horizon_days
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Scenarios must use the same "
                    "twin version and horizon"
                ),
            )

        if (
            baseline.scenario_type
            != ScenarioType.BASELINE
        ):
            raise HTTPException(
                status_code=409,
                detail="First simulation must be baseline",
            )

        a = baseline.summary
        b = scenario.summary

        return ScenarioComparison(
            baseline_simulation_id=baseline_id,
            scenario_simulation_id=scenario_id,
            fill_rate_change_percentage_points=round(
                b.fill_rate_percent
                - a.fill_rate_percent,
                2,
            ),
            lost_sales_change_units=round(
                b.lost_sales_units
                - a.lost_sales_units,
                2,
            ),
            total_cost_change=round(
                b.total_estimated_cost
                - a.total_estimated_cost,
                2,
            ),
            ending_stock_change_units=round(
                b.ending_stock
                - a.ending_stock,
                2,
            ),
            capacity_excess_change_units=round(
                b.peak_capacity_excess_units
                - a.peak_capacity_excess_units,
                2,
            ),
        )


digital_twin_store = DigitalTwinStore()


# ============================================================
# SERVICE
# ============================================================

class DigitalTwinService:

    def __init__(
        self,
        store: DigitalTwinStore,
    ):
        self.store = store

    async def create(
        self,
        principal: Principal,
        payload: TwinCreate,
    ) -> TwinResponse:

        return await self.store.create(
            principal=principal,
            payload=payload,
        )

    async def simulate(
        self,
        principal: Principal,
        twin_id: str,
        payload: SimulationCreate,
    ) -> SimulationResponse:

        return await self.store.simulate(
            principal=principal,
            twin_id=twin_id,
            payload=payload,
        )


digital_twin_service = DigitalTwinService(
    digital_twin_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Warehouse Digital Twin"],
)


@router.post(
    "/twins",
    response_model=TwinResponse,
    status_code=201,
)
async def create_digital_twin(
    payload: TwinCreate,
    principal: CurrentPrincipal,
):
    return await digital_twin_service.create(
        principal,
        payload,
    )


@router.get(
    "/twins",
    response_model=list[TwinResponse],
)
async def list_digital_twins(
    principal: CurrentPrincipal,
    warehouse_id: str,
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
    ),
):
    return await digital_twin_store.list_twins(
        principal=principal,
        warehouse_id=warehouse_id,
        limit=limit,
    )


@router.get(
    "/twins/{twin_id}",
    response_model=TwinResponse,
)
async def get_digital_twin(
    twin_id: str,
    principal: CurrentPrincipal,
):
    return await digital_twin_store.get(
        principal=principal,
        twin_id=twin_id,
    )


@router.put(
    "/twins/{twin_id}",
    response_model=TwinResponse,
)
async def update_digital_twin(
    twin_id: str,
    payload: TwinUpdate,
    principal: CurrentPrincipal,
):
    return await digital_twin_store.update(
        principal=principal,
        twin_id=twin_id,
        payload=payload,
    )


@router.post(
    "/twins/{twin_id}/simulate",
    response_model=SimulationResponse,
    status_code=201,
)
async def run_digital_twin_simulation(
    twin_id: str,
    payload: SimulationCreate,
    principal: CurrentPrincipal,
):
    return await digital_twin_service.simulate(
        principal,
        twin_id,
        payload,
    )


@router.get(
    "/simulations/{simulation_id}",
    response_model=SimulationResponse,
)
async def get_simulation(
    simulation_id: str,
    principal: CurrentPrincipal,
):
    return await digital_twin_store.get_simulation(
        principal=principal,
        simulation_id=simulation_id,
    )


@router.get(
    "/compare",
    response_model=ScenarioComparison,
)
async def compare_simulations(
    principal: CurrentPrincipal,
    baseline_id: str,
    scenario_id: str,
):
    return await digital_twin_store.compare(
        principal=principal,
        baseline_id=baseline_id,
        scenario_id=scenario_id,
    )


__all__ = [
    "TwinStatus",
    "ScenarioType",
    "RiskLevel",
    "TwinSKU",
    "TwinCreate",
    "TwinUpdate",
    "ScenarioParameters",
    "SimulationCreate",
    "TwinResponse",
    "DailySimulationPoint",
    "SKUSimulationResult",
    "SimulationSummary",
    "SimulationResponse",
    "ScenarioComparison",
    "DigitalTwinEngine",
    "DigitalTwinStore",
    "DigitalTwinService",
    "digital_twin_engine",
    "digital_twin_store",
    "digital_twin_service",
    "router",
]
