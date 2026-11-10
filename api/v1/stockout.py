from __future__ import annotations

"""Planned module: stockout. Implementation pending."""

"""
backend/stockout.py

Autonomous Retail Supply Chain AI 5.0
Stockout Detection, Risk & Prevention API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Tenant and warehouse-scoped stock monitoring
    - Stockout and low-stock detection
    - Days-of-cover calculations
    - Lead-time demand estimation
    - Safety stock and reorder recommendations
    - Deterministic stockout risk scoring
    - Alert lifecycle management
    - Idempotent stock snapshots
    - Optimistic concurrency
    - Stockout analytics

Important:
    This is a deterministic prototype, not a trained
    machine-learning prediction system.

    No inventory, purchasing, or notification actions
    are executed automatically.
"""


import asyncio
import hashlib
import json
import math
import secrets

from dataclasses import dataclass, field
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
    FiniteFloat,
    model_validator,
)

from backend.permissions import (
    CurrentPrincipal,
    Permission,
    Principal,
    ResourceContext,
    permission_engine,
)


API_PREFIX = "/api/v1/stockout"

MAX_RECORDS_PER_TENANT = 50000
MAX_ALERTS_PER_RECORD = 100
MAX_EVENTS_PER_RECORD = 500
MAX_IDEMPOTENCY_KEYS = 100000
MAX_LIST_LIMIT = 200

NonNegativeFloat = Annotated[
    FiniteFloat,
    Field(ge=0, le=100000000),
]

PositiveFloat = Annotated[
    FiniteFloat,
    Field(gt=0, le=100000000),
]


# ============================================================
# ENUMS
# ============================================================

class StockoutRiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class StockoutStatus(str, Enum):
    HEALTHY = "healthy"
    LOW_STOCK = "low_stock"
    STOCKOUT = "stockout"


class StockoutAlertStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class StockoutEventType(str, Enum):
    SNAPSHOT_CREATED = "snapshot_created"
    SNAPSHOT_UPDATED = "snapshot_updated"
    ALERT_CREATED = "alert_created"
    ALERT_ACKNOWLEDGED = "alert_acknowledged"
    ALERT_RESOLVED = "alert_resolved"


# ============================================================
# REQUEST MODELS
# ============================================================

class StockoutSnapshotCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    sku: str = Field(
        min_length=1,
        max_length=100,
    )

    on_hand_quantity: int = Field(ge=0)
    reserved_quantity: int = Field(ge=0)

    incoming_quantity: int = Field(
        default=0,
        ge=0,
    )

    average_daily_demand: NonNegativeFloat

    demand_std_dev: NonNegativeFloat = 0

    lead_time_days: PositiveFloat

    service_level_z: Annotated[
        FiniteFloat,
        Field(ge=0, le=5),
    ] = 1.65

    reorder_review_days: NonNegativeFloat = 7

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_quantities(self):

        if self.reserved_quantity > self.on_hand_quantity:
            raise ValueError(
                "Reserved quantity cannot exceed on-hand quantity"
            )

        return self


class StockoutSnapshotUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    on_hand_quantity: int = Field(ge=0)
    reserved_quantity: int = Field(ge=0)

    incoming_quantity: int = Field(ge=0)

    average_daily_demand: NonNegativeFloat
    demand_std_dev: NonNegativeFloat

    lead_time_days: PositiveFloat
    service_level_z: Annotated[
        FiniteFloat,
        Field(ge=0, le=5),
    ]

    reorder_review_days: NonNegativeFloat

    @model_validator(mode="after")
    def validate_quantities(self):

        if self.reserved_quantity > self.on_hand_quantity:
            raise ValueError(
                "Reserved quantity cannot exceed on-hand quantity"
            )

        return self


class StockoutRiskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on_hand_quantity: int = Field(ge=0)
    reserved_quantity: int = Field(ge=0)

    incoming_quantity: int = Field(ge=0)

    average_daily_demand: NonNegativeFloat

    demand_std_dev: NonNegativeFloat = 0

    lead_time_days: PositiveFloat

    service_level_z: Annotated[
        FiniteFloat,
        Field(ge=0, le=5),
    ] = 1.65

    reorder_review_days: NonNegativeFloat = 7

    @model_validator(mode="after")
    def validate_quantities(self):

        if self.reserved_quantity > self.on_hand_quantity:
            raise ValueError(
                "Reserved quantity cannot exceed on-hand quantity"
            )

        return self


class StockoutAlertCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    reason: str = Field(
        min_length=5,
        max_length=500,
    )


class StockoutAlertAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    notes: str = Field(
        min_length=3,
        max_length=500,
    )


# ============================================================
# RESPONSE MODELS
# ============================================================

class StockoutRiskResponse(BaseModel):
    status: StockoutStatus
    risk_level: StockoutRiskLevel

    risk_score: float

    available_quantity: int

    days_of_cover: float | None

    lead_time_demand: float
    safety_stock: int
    reorder_point: int

    recommended_order_quantity: int

    projected_shortage_quantity: int

    explanation: str


class StockoutEventResponse(BaseModel):
    event_id: str
    event_type: StockoutEventType
    actor_id: str
    details: str | None
    created_at: datetime


class StockoutAlertResponse(BaseModel):
    alert_id: str
    status: StockoutAlertStatus
    risk_level: StockoutRiskLevel
    reason: str
    created_by: str
    acknowledged_by: str | None
    resolved_by: str | None
    created_at: datetime
    resolved_at: datetime | None


class StockoutRecordResponse(BaseModel):
    stockout_record_id: str

    warehouse_id: str
    product_id: str
    sku: str

    on_hand_quantity: int
    reserved_quantity: int
    incoming_quantity: int

    average_daily_demand: float

    risk: StockoutRiskResponse

    open_alert_count: int

    version: int

    created_at: datetime
    updated_at: datetime


class StockoutDetailResponse(StockoutRecordResponse):
    alerts: list[StockoutAlertResponse]
    events: list[StockoutEventResponse]


class StockoutAnalyticsResponse(BaseModel):
    total_products: int

    healthy_products: int
    low_stock_products: int
    stockout_products: int

    high_risk_products: int
    critical_risk_products: int

    open_alerts: int

    total_recommended_order_quantity: int


# ============================================================
# RISK ENGINE
# ============================================================

class StockoutRiskEngine:
    """
    Deterministic inventory risk calculator.

    Assumptions:
    - Average demand and lead time are supplied inputs.
    - Demand variability is approximated using a
      square-root-of-lead-time safety stock formula.
    - Incoming inventory is NOT assumed to arrive before
      the next stockout unless separately verified.
    """

    @staticmethod
    def evaluate(
        request: StockoutRiskRequest,
    ) -> StockoutRiskResponse:

        available = (
            request.on_hand_quantity
            - request.reserved_quantity
        )

        daily_demand = request.average_daily_demand
        lead_time = request.lead_time_days

        lead_time_demand = daily_demand * lead_time

        safety_stock = math.ceil(
            request.service_level_z
            * request.demand_std_dev
            * math.sqrt(lead_time)
        )

        reorder_point = math.ceil(
            lead_time_demand + safety_stock
        )

        target_stock = math.ceil(
            daily_demand
            * (
                lead_time
                + request.reorder_review_days
            )
            + safety_stock
        )

        recommended_quantity = max(
            0,
            target_stock
            - available
            - request.incoming_quantity,
        )

        projected_shortage = max(
            0,
            math.ceil(lead_time_demand)
            - available,
        )

        if daily_demand > 0:
            days_of_cover = available / daily_demand
        else:
            days_of_cover = None

        if available == 0:
            status = StockoutStatus.STOCKOUT

        elif available <= reorder_point:
            status = StockoutStatus.LOW_STOCK

        else:
            status = StockoutStatus.HEALTHY

        if daily_demand <= 0:
            risk_score = (
                100.0 if available == 0 else 0.0
            )

        elif available == 0:
            risk_score = 100.0

        else:
            coverage_ratio = (
                available
                / max(lead_time_demand, 1e-9)
            )

            coverage_risk = max(
                0.0,
                min(
                    1.0,
                    1.0 - coverage_ratio,
                ),
            )

            buffer_risk = max(
                0.0,
                min(
                    1.0,
                    (
                        reorder_point - available
                    ) / max(reorder_point, 1),
                ),
            )

            risk_score = 100.0 * (
                0.7 * coverage_risk
                + 0.3 * buffer_risk
            )

        risk_score = round(
            max(0.0, min(100.0, risk_score)),
            2,
        )

        if available == 0:
            risk_level = StockoutRiskLevel.CRITICAL

        elif risk_score >= 75:
            risk_level = StockoutRiskLevel.CRITICAL

        elif risk_score >= 50:
            risk_level = StockoutRiskLevel.HIGH

        elif risk_score >= 25:
            risk_level = StockoutRiskLevel.MEDIUM

        elif status == StockoutStatus.LOW_STOCK:
            risk_level = StockoutRiskLevel.LOW

        else:
            risk_level = StockoutRiskLevel.NONE

        explanation = (
            f"Available stock: {available} units. "
            f"Estimated lead-time demand: "
            f"{lead_time_demand:.2f} units. "
            f"Safety stock: {safety_stock} units. "
            f"Reorder point: {reorder_point} units. "
            f"Recommended replenishment: "
            f"{recommended_quantity} units."
        )

        return StockoutRiskResponse(
            status=status,
            risk_level=risk_level,
            risk_score=risk_score,
            available_quantity=available,
            days_of_cover=(
                round(days_of_cover, 2)
                if days_of_cover is not None
                else None
            ),
            lead_time_demand=round(
                lead_time_demand, 2
            ),
            safety_stock=safety_stock,
            reorder_point=reorder_point,
            recommended_order_quantity=(
                recommended_quantity
            ),
            projected_shortage_quantity=(
                projected_shortage
            ),
            explanation=explanation,
        )


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass
class StockoutRecord:
    stockout_record_id: str
    tenant_id: str

    warehouse_id: str
    product_id: str
    sku: str

    request: StockoutRiskRequest

    created_by: str

    alerts: list[StockoutAlertResponse] = field(
        default_factory=list
    )

    events: list[StockoutEventResponse] = field(
        default_factory=list
    )

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
# SECURITY
# ============================================================

def require_stockout_access(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool,
) -> None:

    permission = (
        Permission.INVENTORY_WRITE
        if write
        else Permission.INVENTORY_READ
    )

    if (
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
            detail="Stockout access denied",
        )


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint(
    payload: StockoutSnapshotCreate,
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


def risk_request_from_snapshot(
    payload: StockoutSnapshotCreate
    | StockoutSnapshotUpdate,
) -> StockoutRiskRequest:

    return StockoutRiskRequest(
        on_hand_quantity=payload.on_hand_quantity,
        reserved_quantity=payload.reserved_quantity,
        incoming_quantity=payload.incoming_quantity,
        average_daily_demand=payload.average_daily_demand,
        demand_std_dev=payload.demand_std_dev,
        lead_time_days=payload.lead_time_days,
        service_level_z=payload.service_level_z,
        reorder_review_days=payload.reorder_review_days,
    )


def to_response(
    record: StockoutRecord,
) -> StockoutRecordResponse:

    risk = StockoutRiskEngine.evaluate(
        record.request
    )

    return StockoutRecordResponse(
        stockout_record_id=record.stockout_record_id,
        warehouse_id=record.warehouse_id,
        product_id=record.product_id,
        sku=record.sku,
        on_hand_quantity=(
            record.request.on_hand_quantity
        ),
        reserved_quantity=(
            record.request.reserved_quantity
        ),
        incoming_quantity=(
            record.request.incoming_quantity
        ),
        average_daily_demand=(
            record.request.average_daily_demand
        ),
        risk=risk,
        open_alert_count=sum(
            alert.status != StockoutAlertStatus.RESOLVED
            for alert in record.alerts
        ),
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def to_detail(
    record: StockoutRecord,
) -> StockoutDetailResponse:

    return StockoutDetailResponse(
        **to_response(record).model_dump(),
        alerts=list(record.alerts),
        events=list(record.events),
    )


# ============================================================
# STOCKOUT STORE
# ============================================================

class StockoutStore:

    def __init__(self):

        self._records: dict[
            str,
            StockoutRecord,
        ] = {}

        self._product_index: dict[
            tuple[str, str, str],
            str,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    def _get(
        self,
        principal: Principal,
        record_id: str,
        *,
        write: bool,
    ) -> StockoutRecord:

        record = self._records.get(record_id)

        if (
            record is None
            or record.tenant_id
            != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Stockout record not found",
            )

        require_stockout_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    @staticmethod
    def _check_version(
        record: StockoutRecord,
        expected_version: int,
    ) -> None:

        if record.version != expected_version:
            raise HTTPException(
                status_code=409,
                detail="Stockout record version conflict",
            )

    @staticmethod
    def _touch(record: StockoutRecord) -> None:
        record.version += 1
        record.updated_at = utc_now()

    @staticmethod
    def _event(
        record: StockoutRecord,
        event_type: StockoutEventType,
        actor_id: str,
        details: str | None = None,
    ) -> None:

        if len(record.events) >= MAX_EVENTS_PER_RECORD:
            raise HTTPException(
                status_code=503,
                detail="Stockout event capacity reached",
            )

        record.events.append(
            StockoutEventResponse(
                event_id=secrets.token_urlsafe(16),
                event_type=event_type,
                actor_id=actor_id,
                details=details,
                created_at=utc_now(),
            )
        )

    async def create(
        self,
        principal: Principal,
        payload: StockoutSnapshotCreate,
    ) -> StockoutRecordResponse:

        require_stockout_access(
            principal,
            payload.warehouse_id,
            write=True,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        payload_hash = fingerprint(payload)

        product_key = (
            principal.tenant_id,
            payload.warehouse_id,
            payload.product_id,
        )

        async with self._lock:

            previous = self._idempotency.get(key)

            if previous:

                old_hash, record_id = previous

                if old_hash != payload_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return to_response(
                    self._get(
                        principal,
                        record_id,
                        write=False,
                    )
                )

            if product_key in self._product_index:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Stockout snapshot already exists "
                        "for this warehouse and product"
                    ),
                )

            tenant_count = sum(
                record.tenant_id == principal.tenant_id
                for record in self._records.values()
            )

            if (
                tenant_count >= MAX_RECORDS_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Stockout capacity reached",
                )

            record = StockoutRecord(
                stockout_record_id=(
                    secrets.token_urlsafe(20)
                ),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                product_id=payload.product_id,
                sku=payload.sku,
                request=risk_request_from_snapshot(
                    payload
                ),
                created_by=principal.principal_id,
            )

            self._event(
                record,
                StockoutEventType.SNAPSHOT_CREATED,
                principal.principal_id,
            )

            self._records[
                record.stockout_record_id
            ] = record

            self._product_index[product_key] = (
                record.stockout_record_id
            )

            self._idempotency[key] = (
                payload_hash,
                record.stockout_record_id,
            )

            return to_response(record)

    async def get(
        self,
        principal: Principal,
        record_id: str,
    ) -> StockoutDetailResponse:

        async with self._lock:

            return to_detail(
                self._get(
                    principal,
                    record_id,
                    write=False,
                )
            )

    async def list_records(
        self,
        principal: Principal,
        warehouse_id: str | None,
        limit: int,
    ) -> list[StockoutRecordResponse]:

        if warehouse_id:
            require_stockout_access(
                principal,
                warehouse_id,
                write=False,
            )

        async with self._lock:

            records = []

            for record in self._records.values():

                if record.tenant_id != principal.tenant_id:
                    continue

                if (
                    warehouse_id is not None
                    and record.warehouse_id != warehouse_id
                ):
                    continue

                try:
                    require_stockout_access(
                        principal,
                        record.warehouse_id,
                        write=False,
                    )
                except HTTPException:
                    continue

                records.append(record)

            records.sort(
                key=lambda item: item.updated_at,
                reverse=True,
            )

            return [
                to_response(record)
                for record in records[:limit]
            ]

    async def update(
        self,
        principal: Principal,
        record_id: str,
        payload: StockoutSnapshotUpdate,
    ) -> StockoutRecordResponse:

        async with self._lock:

            record = self._get(
                principal,
                record_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._event(
                record,
                StockoutEventType.SNAPSHOT_UPDATED,
                principal.principal_id,
            )

            record.request = risk_request_from_snapshot(
                payload
            )

            self._touch(record)

            return to_response(record)

    async def create_alert(
        self,
        principal: Principal,
        record_id: str,
        payload: StockoutAlertCreate,
    ) -> StockoutAlertResponse:

        async with self._lock:

            record = self._get(
                principal,
                record_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            risk = StockoutRiskEngine.evaluate(
                record.request
            )

            if risk.risk_level == StockoutRiskLevel.NONE:
                raise HTTPException(
                    status_code=409,
                    detail="No stockout risk detected",
                )

            if any(
                alert.status != StockoutAlertStatus.RESOLVED
                for alert in record.alerts
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Active stockout alert already exists",
                )

            if len(record.alerts) >= MAX_ALERTS_PER_RECORD:
                raise HTTPException(
                    status_code=503,
                    detail="Alert capacity reached",
                )

            self._event(
                record,
                StockoutEventType.ALERT_CREATED,
                principal.principal_id,
                payload.reason,
            )

            alert = StockoutAlertResponse(
                alert_id=secrets.token_urlsafe(20),
                status=StockoutAlertStatus.OPEN,
                risk_level=risk.risk_level,
                reason=payload.reason,
                created_by=principal.principal_id,
                acknowledged_by=None,
                resolved_by=None,
                created_at=utc_now(),
                resolved_at=None,
            )

            record.alerts.append(alert)

            self._touch(record)

            return alert

    async def alert_action(
        self,
        principal: Principal,
        record_id: str,
        alert_id: str,
        payload: StockoutAlertAction,
        *,
        resolve: bool,
    ) -> StockoutAlertResponse:

        async with self._lock:

            record = self._get(
                principal,
                record_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            alert = next(
                (
                    item
                    for item in record.alerts
                    if item.alert_id == alert_id
                ),
                None,
            )

            if alert is None:
                raise HTTPException(
                    status_code=404,
                    detail="Stockout alert not found",
                )

            if resolve:

                if alert.status == StockoutAlertStatus.RESOLVED:
                    raise HTTPException(
                        status_code=409,
                        detail="Alert already resolved",
                    )

                risk = StockoutRiskEngine.evaluate(
                    record.request
                )

                if risk.status != StockoutStatus.HEALTHY:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Stock is not healthy; "
                            "cannot resolve the alert"
                        ),
                    )

                self._event(
                    record,
                    StockoutEventType.ALERT_RESOLVED,
                    principal.principal_id,
                    payload.notes,
                )

                alert.status = StockoutAlertStatus.RESOLVED
                alert.resolved_by = principal.principal_id
                alert.resolved_at = utc_now()

            else:

                if alert.status != StockoutAlertStatus.OPEN:
                    raise HTTPException(
                        status_code=409,
                        detail="Alert cannot be acknowledged",
                    )

                self._event(
                    record,
                    StockoutEventType.ALERT_ACKNOWLEDGED,
                    principal.principal_id,
                    payload.notes,
                )

                alert.status = (
                    StockoutAlertStatus.ACKNOWLEDGED
                )

                alert.acknowledged_by = (
                    principal.principal_id
                )

            self._touch(record)

            return alert

    async def analytics(
        self,
        principal: Principal,
        warehouse_id: str,
    ) -> StockoutAnalyticsResponse:

        require_stockout_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._records.values()
                if (
                    record.tenant_id == principal.tenant_id
                    and record.warehouse_id == warehouse_id
                )
            ]

            risks = [
                StockoutRiskEngine.evaluate(
                    record.request
                )
                for record in records
            ]

            return StockoutAnalyticsResponse(
                total_products=len(records),
                healthy_products=sum(
                    risk.status == StockoutStatus.HEALTHY
                    for risk in risks
                ),
                low_stock_products=sum(
                    risk.status == StockoutStatus.LOW_STOCK
                    for risk in risks
                ),
                stockout_products=sum(
                    risk.status == StockoutStatus.STOCKOUT
                    for risk in risks
                ),
                high_risk_products=sum(
                    risk.risk_level == StockoutRiskLevel.HIGH
                    for risk in risks
                ),
                critical_risk_products=sum(
                    risk.risk_level == StockoutRiskLevel.CRITICAL
                    for risk in risks
                ),
                open_alerts=sum(
                    alert.status != StockoutAlertStatus.RESOLVED
                    for record in records
                    for alert in record.alerts
                ),
                total_recommended_order_quantity=sum(
                    risk.recommended_order_quantity
                    for risk in risks
                ),
            )


stockout_store = StockoutStore()


# ============================================================
# SERVICE
# ============================================================

class StockoutService:

    def __init__(
        self,
        store: StockoutStore,
    ):
        self.store = store

    async def evaluate(
        self,
        payload: StockoutRiskRequest,
    ) -> StockoutRiskResponse:

        return StockoutRiskEngine.evaluate(payload)


stockout_service = StockoutService(
    stockout_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Stockout Management"],
)


@router.post(
    "/evaluate",
    response_model=StockoutRiskResponse,
)
async def evaluate_stockout_risk(
    payload: StockoutRiskRequest,
    principal: CurrentPrincipal,
):
    # This endpoint evaluates caller-supplied numbers.
    # It does not retrieve inventory from a warehouse.
    # Require an authenticated inventory reader.
    if not principal.active:
        raise HTTPException(
            status_code=403,
            detail="Inactive principal",
        )

    return await stockout_service.evaluate(payload)


@router.post(
    "/snapshots",
    response_model=StockoutRecordResponse,
    status_code=201,
)
async def create_stockout_snapshot(
    payload: StockoutSnapshotCreate,
    principal: CurrentPrincipal,
):
    return await stockout_store.create(
        principal,
        payload,
    )


@router.get(
    "/snapshots",
    response_model=list[StockoutRecordResponse],
)
async def list_stockout_snapshots(
    principal: CurrentPrincipal,
    warehouse_id: str | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await stockout_store.list_records(
        principal,
        warehouse_id,
        limit,
    )


@router.get(
    "/analytics/{warehouse_id}",
    response_model=StockoutAnalyticsResponse,
)
async def stockout_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
):
    return await stockout_store.analytics(
        principal,
        warehouse_id,
    )


@router.get(
    "/snapshots/{record_id}",
    response_model=StockoutDetailResponse,
)
async def get_stockout_snapshot(
    record_id: str,
    principal: CurrentPrincipal,
):
    return await stockout_store.get(
        principal,
        record_id,
    )


@router.put(
    "/snapshots/{record_id}",
    response_model=StockoutRecordResponse,
)
async def update_stockout_snapshot(
    record_id: str,
    payload: StockoutSnapshotUpdate,
    principal: CurrentPrincipal,
):
    return await stockout_store.update(
        principal,
        record_id,
        payload,
    )


@router.post(
    "/snapshots/{record_id}/alerts",
    response_model=StockoutAlertResponse,
    status_code=201,
)
async def create_stockout_alert(
    record_id: str,
    payload: StockoutAlertCreate,
    principal: CurrentPrincipal,
):
    return await stockout_store.create_alert(
        principal,
        record_id,
        payload,
    )


@router.post(
    "/snapshots/{record_id}/alerts/{alert_id}/acknowledge",
    response_model=StockoutAlertResponse,
)
async def acknowledge_stockout_alert(
    record_id: str,
    alert_id: str,
    payload: StockoutAlertAction,
    principal: CurrentPrincipal,
):
    return await stockout_store.alert_action(
        principal,
        record_id,
        alert_id,
        payload,
        resolve=False,
    )


@router.post(
    "/snapshots/{record_id}/alerts/{alert_id}/resolve",
    response_model=StockoutAlertResponse,
)
async def resolve_stockout_alert(
    record_id: str,
    alert_id: str,
    payload: StockoutAlertAction,
    principal: CurrentPrincipal,
):
    return await stockout_store.alert_action(
        principal,
        record_id,
        alert_id,
        payload,
        resolve=True,
    )


__all__ = [
    "StockoutRiskLevel",
    "StockoutStatus",
    "StockoutAlertStatus",
    "StockoutEventType",
    "StockoutSnapshotCreate",
    "StockoutSnapshotUpdate",
    "StockoutRiskRequest",
    "StockoutAlertCreate",
    "StockoutAlertAction",
    "StockoutRiskResponse",
    "StockoutEventResponse",
    "StockoutAlertResponse",
    "StockoutRecordResponse",
    "StockoutDetailResponse",
    "StockoutAnalyticsResponse",
    "StockoutRiskEngine",
    "StockoutStore",
    "StockoutService",
    "stockout_store",
    "stockout_service",
    "router",
]
