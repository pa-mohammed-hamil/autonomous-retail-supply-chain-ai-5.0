from __future__ import annotations

"""Planned module: simulation stream. Implementation pending."""

"""
backend/simulation_stream.py

Autonomous Retail Supply Chain AI 5.0

Simulation execution and progress streaming.

Python 3.10+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - What-if supply chain scenarios
    - Demand spike simulation
    - Supplier delay simulation
    - Warehouse disruption simulation
    - Inventory replenishment simulation
    - Transportation cost simulation
    - Scenario comparison
    - Async simulation execution
    - Server-Sent Events (SSE)
    - Tenant and warehouse isolation
    - Bounded execution history
    - Simulation cancellation
    - No production inventory mutations

IMPORTANT:
    This is an illustrative deterministic
    simulation engine.

    Results are estimates, not verified
    forecasts or optimization decisions.

    Production requires durable job storage,
    authenticated SSE access, worker queues,
    calibrated models, and audit logging.
"""


import asyncio
import json
import secrets

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, AsyncIterator

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    Query,
)

from fastapi.responses import StreamingResponse

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

MAX_SIMULATIONS = 1000
MAX_EVENTS_PER_SIMULATION = 200
MAX_SCENARIOS_PER_REQUEST = 10
MAX_CONCURRENT_SIMULATIONS = 4

SSE_HEARTBEAT_SECONDS = 15
SSE_TIMEOUT_SECONDS = 600

SIMULATION_STEPS = 5

MAX_QUANTITY = 10_000_000
MAX_MONEY = Decimal("999999999999.99")


# ============================================================
# ENUMS
# ============================================================

class SimulationType(str, Enum):
    DEMAND_SPIKE = "demand_spike"
    SUPPLIER_DELAY = "supplier_delay"
    WAREHOUSE_DISRUPTION = "warehouse_disruption"
    REPLENISHMENT = "replenishment"
    TRANSPORT_COST = "transport_cost"
    COMBINED = "combined"


class SimulationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SimulationEventType(str, Enum):
    CREATED = "created"
    STARTED = "started"
    PROGRESS = "progress"
    SCENARIO_COMPLETED = "scenario_completed"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    HEARTBEAT = "heartbeat"


# ============================================================
# REQUEST SCHEMAS
# ============================================================

class SimulationScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str = Field(
        min_length=1,
        max_length=128,
    )

    name: str = Field(
        min_length=1,
        max_length=200,
    )

    simulation_type: SimulationType

    demand_multiplier: Decimal = Field(
        default=Decimal("1"),
        ge=0,
        le=10,
    )

    supplier_delay_days: int = Field(
        default=0,
        ge=0,
        le=365,
    )

    warehouse_capacity_multiplier: Decimal = Field(
        default=Decimal("1"),
        ge=0,
        le=5,
    )

    replenishment_units: int = Field(
        default=0,
        ge=0,
        le=MAX_QUANTITY,
    )

    transport_cost_multiplier: Decimal = Field(
        default=Decimal("1"),
        ge=0,
        le=10,
    )


class SimulationBaseline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    current_stock: int = Field(
        ge=0,
        le=MAX_QUANTITY,
    )

    daily_demand: Decimal = Field(
        ge=0,
        le=MAX_QUANTITY,
    )

    warehouse_capacity: int = Field(
        gt=0,
        le=MAX_QUANTITY,
    )

    supplier_lead_time_days: int = Field(
        ge=0,
        le=365,
    )

    unit_holding_cost: Decimal = Field(
        ge=0,
        le=MAX_MONEY,
    )

    unit_stockout_cost: Decimal = Field(
        ge=0,
        le=MAX_MONEY,
    )

    transport_cost: Decimal = Field(
        ge=0,
        le=MAX_MONEY,
    )

    currency: str = Field(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    )

    @model_validator(mode="after")
    def validate_baseline(self):
        if self.current_stock > self.warehouse_capacity:
            raise ValueError(
                "Current stock exceeds warehouse capacity"
            )
        return self


class SimulationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=1,
        max_length=200,
    )

    baseline: SimulationBaseline

    scenarios: list[SimulationScenario] = Field(
        min_length=1,
        max_length=MAX_SCENARIOS_PER_REQUEST,
    )

    horizon_days: int = Field(
        default=30,
        ge=1,
        le=365,
    )

    @model_validator(mode="after")
    def validate_scenarios(self):
        ids = [
            scenario.scenario_id
            for scenario in self.scenarios
        ]

        if len(ids) != len(set(ids)):
            raise ValueError(
                "Scenario IDs must be unique"
            )

        return self


# ============================================================
# RESPONSE SCHEMAS
# ============================================================

class SimulationMetrics(BaseModel):
    projected_demand_units: Decimal
    projected_available_units: Decimal
    projected_fulfilled_units: Decimal
    projected_stockout_units: Decimal
    projected_ending_stock_units: Decimal

    projected_holding_cost: Decimal
    projected_stockout_cost: Decimal
    projected_transport_cost: Decimal
    projected_total_cost: Decimal

    effective_lead_time_days: int
    effective_capacity_units: Decimal

    currency: str


class ScenarioResult(BaseModel):
    scenario_id: str
    scenario_name: str
    simulation_type: SimulationType
    metrics: SimulationMetrics

    cost_difference_from_baseline: Decimal
    cost_change_percent: Decimal | None


class SimulationResult(BaseModel):
    simulation_id: str
    name: str
    status: SimulationStatus

    baseline_metrics: SimulationMetrics
    scenario_results: list[ScenarioResult]

    best_scenario_id: str | None

    completed_at: datetime


class SimulationEvent(BaseModel):
    event_id: str
    simulation_id: str
    sequence: int = Field(ge=1)

    event_type: SimulationEventType
    status: SimulationStatus

    progress_percent: float = Field(
        ge=0,
        le=100,
    )

    message: str
    timestamp: datetime


class SimulationSnapshot(BaseModel):
    simulation_id: str
    name: str
    status: SimulationStatus
    progress_percent: float

    warehouse_id: str
    product_id: str

    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    error_code: str | None = None


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def calculate_metrics(
    baseline: SimulationBaseline,
    *,
    horizon_days: int,
    demand_multiplier: Decimal = Decimal("1"),
    supplier_delay_days: int = 0,
    capacity_multiplier: Decimal = Decimal("1"),
    replenishment_units: int = 0,
    transport_multiplier: Decimal = Decimal("1"),
) -> SimulationMetrics:
    """
    Simplified deterministic what-if model.

    All replenishment is treated as arriving
    within the horizon only if the effective
    lead time does not exceed the horizon.

    Does not model daily demand variation,
    partial deliveries, expiry, or returns.
    """

    effective_lead_time = (
        baseline.supplier_lead_time_days
        + supplier_delay_days
    )

    effective_capacity = (
        Decimal(baseline.warehouse_capacity)
        * capacity_multiplier
    )

    projected_demand = (
        baseline.daily_demand
        * demand_multiplier
        * Decimal(horizon_days)
    )

    incoming_units = (
        Decimal(replenishment_units)
        if effective_lead_time <= horizon_days
        else Decimal("0")
    )

    projected_supply = min(
        effective_capacity,
        Decimal(baseline.current_stock)
        + incoming_units,
    )

    fulfilled = min(
        projected_demand,
        projected_supply,
    )

    stockout = max(
        Decimal("0"),
        projected_demand - fulfilled,
    )

    ending_stock = max(
        Decimal("0"),
        projected_supply - fulfilled,
    )

    holding_cost = (
        ending_stock
        * baseline.unit_holding_cost
        * Decimal(horizon_days)
    )

    stockout_cost = (
        stockout
        * baseline.unit_stockout_cost
    )

    transport_cost = (
        baseline.transport_cost
        * transport_multiplier
    )

    total_cost = (
        holding_cost
        + stockout_cost
        + transport_cost
    )

    return SimulationMetrics(
        projected_demand_units=projected_demand,
        projected_available_units=projected_supply,
        projected_fulfilled_units=fulfilled,
        projected_stockout_units=stockout,
        projected_ending_stock_units=ending_stock,
        projected_holding_cost=holding_cost,
        projected_stockout_cost=stockout_cost,
        projected_transport_cost=transport_cost,
        projected_total_cost=total_cost,
        effective_lead_time_days=effective_lead_time,
        effective_capacity_units=effective_capacity,
        currency=baseline.currency,
    )


def simulate_scenario(
    baseline: SimulationBaseline,
    scenario: SimulationScenario,
    horizon_days: int,
) -> SimulationMetrics:

    return calculate_metrics(
        baseline,
        horizon_days=horizon_days,
        demand_multiplier=scenario.demand_multiplier,
        supplier_delay_days=scenario.supplier_delay_days,
        capacity_multiplier=(
            scenario.warehouse_capacity_multiplier
        ),
        replenishment_units=scenario.replenishment_units,
        transport_multiplier=(
            scenario.transport_cost_multiplier
        ),
    )


def calculate_cost_change(
    baseline_cost: Decimal,
    scenario_cost: Decimal,
) -> tuple[Decimal, Decimal | None]:

    difference = scenario_cost - baseline_cost

    if baseline_cost == 0:
        return difference, None

    percentage = (
        difference / baseline_cost
    ) * Decimal("100")

    return difference, percentage


# ============================================================
# AUTHORIZATION
# ============================================================

def require_simulation_access(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool = False,
) -> None:

    permission = (
        Permission.AI_AGENT_EXECUTE
        if write
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
            detail="Simulation access denied",
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


# ============================================================
# INTERNAL EXECUTION STATE
# ============================================================

@dataclass
class SimulationExecution:
    simulation_id: str
    tenant_id: str
    owner_id: str

    request: SimulationCreate

    status: SimulationStatus = (
        SimulationStatus.PENDING
    )

    progress_percent: float = 0.0

    created_at: datetime = field(
        default_factory=utc_now
    )

    started_at: datetime | None = None
    completed_at: datetime | None = None

    result: SimulationResult | None = None
    error_code: str | None = None

    sequence: int = 0

    events: deque[SimulationEvent] = field(
        default_factory=lambda: deque(
            maxlen=MAX_EVENTS_PER_SIMULATION
        )
    )

    changed: asyncio.Event = field(
        default_factory=asyncio.Event
    )

    task: asyncio.Task | None = None

    cancel_requested: bool = False


# ============================================================
# SIMULATION MANAGER
# ============================================================

class SimulationManager:

    def __init__(self):

        self._executions: dict[
            str,
            SimulationExecution,
        ] = {}

        self._lock = asyncio.Lock()

        self._semaphore = asyncio.Semaphore(
            MAX_CONCURRENT_SIMULATIONS
        )

    async def create(
        self,
        *,
        principal: Principal,
        payload: SimulationCreate,
    ) -> SimulationExecution:

        require_simulation_access(
            principal,
            payload.baseline.warehouse_id,
            write=True,
        )

        async with self._lock:

            if len(self._executions) >= MAX_SIMULATIONS:
                raise HTTPException(
                    status_code=503,
                    detail="Simulation capacity reached",
                )

            execution = SimulationExecution(
                simulation_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                owner_id=principal.principal_id,
                request=payload,
            )

            self._executions[
                execution.simulation_id
            ] = execution

            self._publish(
                execution,
                SimulationEventType.CREATED,
                "Simulation created",
            )

            execution.task = asyncio.create_task(
                self._run(execution)
            )

            return execution

    def _publish(
        self,
        execution: SimulationExecution,
        event_type: SimulationEventType,
        message: str,
    ) -> None:

        execution.sequence += 1

        event = SimulationEvent(
            event_id=secrets.token_urlsafe(12),
            simulation_id=execution.simulation_id,
            sequence=execution.sequence,
            event_type=event_type,
            status=execution.status,
            progress_percent=(
                execution.progress_percent
            ),
            message=message,
            timestamp=utc_now(),
        )

        execution.events.append(event)

        # SSE consumers independently read
        # from the bounded event history.
        execution.changed.set()

    async def _run(
        self,
        execution: SimulationExecution,
    ) -> None:

        try:

            async with self._semaphore:

                if execution.cancel_requested:
                    raise asyncio.CancelledError()

                execution.status = (
                    SimulationStatus.RUNNING
                )

                execution.started_at = utc_now()

                self._publish(
                    execution,
                    SimulationEventType.STARTED,
                    "Simulation started",
                )

                request = execution.request

                baseline_metrics = calculate_metrics(
                    request.baseline,
                    horizon_days=request.horizon_days,
                )

                results: list[ScenarioResult] = []

                total = len(request.scenarios)

                for index, scenario in enumerate(
                    request.scenarios,
                    start=1,
                ):

                    if execution.cancel_requested:
                        raise asyncio.CancelledError()

                    # Yield control to allow
                    # cancellation and SSE reads.
                    await asyncio.sleep(0)

                    metrics = simulate_scenario(
                        request.baseline,
                        scenario,
                        request.horizon_days,
                    )

                    difference, percentage = (
                        calculate_cost_change(
                            baseline_metrics.projected_total_cost,
                            metrics.projected_total_cost,
                        )
                    )

                    results.append(
                        ScenarioResult(
                            scenario_id=scenario.scenario_id,
                            scenario_name=scenario.name,
                            simulation_type=(
                                scenario.simulation_type
                            ),
                            metrics=metrics,
                            cost_difference_from_baseline=(
                                difference
                            ),
                            cost_change_percent=percentage,
                        )
                    )

                    execution.progress_percent = (
                        index / total
                    ) * 100

                    self._publish(
                        execution,
                        SimulationEventType.SCENARIO_COMPLETED,
                        "Scenario completed: "
                        f"{scenario.scenario_id}",
                    )

                best = min(
                    results,
                    key=lambda item: (
                        item.metrics.projected_total_cost,
                        item.scenario_id,
                    ),
                )

                execution.status = (
                    SimulationStatus.COMPLETED
                )

                execution.completed_at = utc_now()

                execution.result = SimulationResult(
                    simulation_id=execution.simulation_id,
                    name=request.name,
                    status=execution.status,
                    baseline_metrics=baseline_metrics,
                    scenario_results=results,
                    best_scenario_id=best.scenario_id,
                    completed_at=execution.completed_at,
                )

                self._publish(
                    execution,
                    SimulationEventType.COMPLETED,
                    "Simulation completed",
                )

        except asyncio.CancelledError:

            execution.status = (
                SimulationStatus.CANCELLED
            )

            execution.completed_at = utc_now()

            self._publish(
                execution,
                SimulationEventType.CANCELLED,
                "Simulation cancelled",
            )

        except Exception:

            execution.status = (
                SimulationStatus.FAILED
            )

            execution.error_code = (
                "SIMULATION_EXECUTION_FAILED"
            )

            execution.completed_at = utc_now()

            self._publish(
                execution,
                SimulationEventType.FAILED,
                "Simulation failed",
            )

    async def get(
        self,
        *,
        principal: Principal,
        simulation_id: str,
    ) -> SimulationExecution:

        async with self._lock:

            execution = self._executions.get(
                simulation_id
            )

        if (
            execution is None
            or execution.tenant_id
            != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Simulation not found",
            )

        require_simulation_access(
            principal,
            execution.request.baseline.warehouse_id,
        )

        if (
            execution.owner_id
            != principal.principal_id
        ):

            raise HTTPException(
                status_code=403,
                detail="Simulation owner access required",
            )

        return execution

    async def cancel(
        self,
        *,
        principal: Principal,
        simulation_id: str,
    ) -> SimulationExecution:

        execution = await self.get(
            principal=principal,
            simulation_id=simulation_id,
        )

        require_simulation_access(
            principal,
            execution.request.baseline.warehouse_id,
            write=True,
        )

        if execution.status in {
            SimulationStatus.COMPLETED,
            SimulationStatus.FAILED,
            SimulationStatus.CANCELLED,
        }:
            return execution

        execution.cancel_requested = True

        if execution.task is not None:
            execution.task.cancel()

        return execution


simulation_manager = SimulationManager()


# ============================================================
# RESPONSE HELPERS
# ============================================================

def to_snapshot(
    execution: SimulationExecution,
) -> SimulationSnapshot:

    return SimulationSnapshot(
        simulation_id=execution.simulation_id,
        name=execution.request.name,
        status=execution.status,
        progress_percent=execution.progress_percent,
        warehouse_id=(
            execution.request.baseline.warehouse_id
        ),
        product_id=(
            execution.request.baseline.product_id
        ),
        created_at=execution.created_at,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        error_code=execution.error_code,
    )


# ============================================================
# SERVER-SENT EVENTS
# ============================================================

def encode_sse(
    event: SimulationEvent,
) -> str:

    data = event.model_dump_json()

    return (
        f"id: {event.sequence}\n"
        f"event: {event.event_type.value}\n"
        f"data: {data}\n\n"
    )


async def stream_simulation_events(
    execution: SimulationExecution,
    request: Request,
    *,
    last_event_id: int = 0,
) -> AsyncIterator[str]:

    loop = asyncio.get_running_loop()

    started = loop.time()

    cursor = last_event_id

    while True:

        if await request.is_disconnected():
            return

        if (
            loop.time() - started
            >= SSE_TIMEOUT_SECONDS
        ):
            return

        # Read current history independently
        # for each SSE subscriber.
        events = [
            event
            for event in list(execution.events)
            if event.sequence > cursor
        ]

        for event in events:

            yield encode_sse(event)

            cursor = event.sequence

        if execution.status in {
            SimulationStatus.COMPLETED,
            SimulationStatus.FAILED,
            SimulationStatus.CANCELLED,
        }:
            return

        execution.changed.clear()

        # Recheck after clearing to reduce
        # the chance of missing a new event.
        if any(
            event.sequence > cursor
            for event in execution.events
        ):
            continue

        try:

            await asyncio.wait_for(
                execution.changed.wait(),
                timeout=SSE_HEARTBEAT_SECONDS,
            )

        except asyncio.TimeoutError:

            yield ": heartbeat\n\n"


# ============================================================
# API ROUTER
# ============================================================

router = APIRouter(
    prefix="/api/v1/simulation-stream",
    tags=["Simulation Stream"],
)


@router.post(
    "/simulations",
    response_model=SimulationSnapshot,
    status_code=202,
)
async def create_simulation(
    payload: SimulationCreate,
    principal: CurrentPrincipal,
):

    execution = await simulation_manager.create(
        principal=principal,
        payload=payload,
    )

    return to_snapshot(execution)


@router.get(
    "/simulations/{simulation_id}",
    response_model=SimulationSnapshot,
)
async def get_simulation(
    simulation_id: str,
    principal: CurrentPrincipal,
):

    execution = await simulation_manager.get(
        principal=principal,
        simulation_id=simulation_id,
    )

    return to_snapshot(execution)


@router.get(
    "/simulations/{simulation_id}/result",
    response_model=SimulationResult,
)
async def get_simulation_result(
    simulation_id: str,
    principal: CurrentPrincipal,
):

    execution = await simulation_manager.get(
        principal=principal,
        simulation_id=simulation_id,
    )

    if execution.result is None:
        raise HTTPException(
            status_code=409,
            detail="Simulation result not available",
        )

    return execution.result


@router.get(
    "/simulations/{simulation_id}/events",
)
async def get_simulation_events(
    simulation_id: str,
    request: Request,
    principal: CurrentPrincipal,
    last_event_id: int = Query(
        default=0,
        ge=0,
    ),
):

    execution = await simulation_manager.get(
        principal=principal,
        simulation_id=simulation_id,
    )

    return StreamingResponse(
        stream_simulation_events(
            execution,
            request,
            last_event_id=last_event_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/simulations/{simulation_id}/cancel",
    response_model=SimulationSnapshot,
)
async def cancel_simulation(
    simulation_id: str,
    principal: CurrentPrincipal,
):

    execution = await simulation_manager.cancel(
        principal=principal,
        simulation_id=simulation_id,
    )

    return to_snapshot(execution)
