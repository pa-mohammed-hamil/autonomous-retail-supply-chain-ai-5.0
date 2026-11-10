from __future__ import annotations

"""Planned module: stock alerts. Implementation pending."""

"""
backend/stock_alerts.py

Autonomous Retail Supply Chain AI 5.0
Warehouse Stock Alert Management API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Tenant and warehouse isolation
    - Low-stock and stockout detection
    - Overstock and excess-stock warnings
    - Reorder point monitoring
    - Days-of-cover estimation
    - Severity classification
    - Alert deduplication
    - Alert acknowledgment and resolution
    - Optimistic concurrency
    - Idempotent stock evaluations
    - Alert history and analytics
    - Replenishment recommendations

IMPORTANT:
    This is an in-memory prototype.
    Stock quantities are supplied as input snapshots.
    It does not automatically query inventory,
    place purchase orders, or send notifications.
"""


import asyncio
import hashlib
import json
import math
import secrets

from dataclasses import dataclass, field
from datetime import datetime, timezone
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


API_PREFIX = "/api/v1/stock-alerts"

MAX_ALERTS_PER_TENANT = 50000
MAX_EVENTS_PER_ALERT = 200
MAX_BATCH_ITEMS = 200
MAX_IDEMPOTENCY_KEYS = 100000
MAX_LIST_LIMIT = 200


# ============================================================
# ENUMS
# ============================================================

class StockAlertType(str, Enum):
    LOW_STOCK = "low_stock"
    STOCKOUT = "stockout"
    REORDER_REQUIRED = "reorder_required"
    OVERSTOCK = "overstock"
    EXCESS_STOCK = "excess_stock"
    LOW_DAYS_COVER = "low_days_cover"


class StockAlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


class StockAlertStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class StockAlertEventType(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    REOPENED = "reopened"


# ============================================================
# REQUEST SCHEMAS
# ============================================================

class StockSnapshot(BaseModel):
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

    reorder_point: int = Field(ge=0)
    safety_stock: int = Field(ge=0)
    maximum_stock: int = Field(ge=0)

    average_daily_demand: float = Field(
        default=0.0,
        ge=0.0,
        allow_inf_nan=False,
    )

    lead_time_days: int = Field(
        default=0,
        ge=0,
        le=3650,
    )

    @model_validator(mode="after")
    def validate_snapshot(self):

        if self.reserved_quantity > self.on_hand_quantity:
            raise ValueError(
                "Reserved quantity exceeds on-hand quantity"
            )

        if (
            self.maximum_stock > 0
            and self.maximum_stock < self.reorder_point
        ):
            raise ValueError(
                "Maximum stock must be >= reorder point"
            )

        return self


class StockEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot: StockSnapshot

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )


class StockBatchEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshots: list[StockSnapshot] = Field(
        min_length=1,
        max_length=MAX_BATCH_ITEMS,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_unique_items(self):

        keys = [
            (
                item.warehouse_id,
                item.product_id,
            )
            for item in self.snapshots
        ]

        if len(keys) != len(set(keys)):
            raise ValueError(
                "Duplicate warehouse/product snapshots"
            )

        return self


class StockAlertVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    notes: str = Field(
        default="",
        max_length=1000,
    )


# ============================================================
# RESPONSE SCHEMAS
# ============================================================

class StockRecommendation(BaseModel):
    available_quantity: int
    reorder_quantity: int
    days_of_cover: float | None
    estimated_lead_time_demand: int


class StockAlertEventResponse(BaseModel):
    event_id: str
    event_type: StockAlertEventType
    actor_id: str
    details: str | None
    created_at: datetime


class StockAlertResponse(BaseModel):
    alert_id: str

    warehouse_id: str
    product_id: str
    sku: str

    alert_type: StockAlertType
    severity: StockAlertSeverity
    status: StockAlertStatus

    message: str

    on_hand_quantity: int
    reserved_quantity: int
    available_quantity: int

    reorder_point: int
    safety_stock: int
    maximum_stock: int

    recommendation: StockRecommendation

    version: int

    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


class StockAlertDetailResponse(StockAlertResponse):
    events: list[StockAlertEventResponse]


class StockEvaluationResponse(BaseModel):
    warehouse_id: str
    product_id: str

    available_quantity: int
    healthy: bool

    alerts: list[StockAlertResponse]

    recommendation: StockRecommendation

    evaluated_at: datetime


class StockBatchEvaluationResponse(BaseModel):
    evaluated_count: int
    healthy_count: int
    affected_product_count: int
    results: list[StockEvaluationResponse]


class StockAlertAnalyticsResponse(BaseModel):
    total_alerts: int
    open_alerts: int
    acknowledged_alerts: int
    resolved_alerts: int

    critical_alerts: int
    high_alerts: int
    warning_alerts: int

    stockout_alerts: int
    low_stock_alerts: int
    reorder_alerts: int
    overstock_alerts: int
    excess_stock_alerts: int
    low_cover_alerts: int


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass
class StockAlertRecord:
    alert_id: str
    tenant_id: str

    warehouse_id: str
    product_id: str
    sku: str

    alert_type: StockAlertType
    severity: StockAlertSeverity
    status: StockAlertStatus

    message: str
    snapshot: StockSnapshot
    recommendation: StockRecommendation

    events: list[StockAlertEventResponse] = field(
        default_factory=list
    )

    version: int = 1

    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    resolved_at: datetime | None = None


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def require_stock_alert_access(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool,
) -> None:

    # Existing inventory permissions are used.
    # Production can add STOCK_ALERT_READ/WRITE.

    permission = (
        Permission.INVENTORY_WRITE
        if write
        else Permission.INVENTORY_READ
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
            detail="Stock alert access denied",
        )


def snapshot_fingerprint(
    snapshots: list[StockSnapshot],
) -> str:

    payload = [
        snapshot.model_dump(mode="json")
        for snapshot in snapshots
    ]

    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def to_response(
    record: StockAlertRecord,
) -> StockAlertResponse:

    snapshot = record.snapshot

    return StockAlertResponse(
        alert_id=record.alert_id,
        warehouse_id=record.warehouse_id,
        product_id=record.product_id,
        sku=record.sku,
        alert_type=record.alert_type,
        severity=record.severity,
        status=record.status,
        message=record.message,
        on_hand_quantity=snapshot.on_hand_quantity,
        reserved_quantity=snapshot.reserved_quantity,
        available_quantity=(
            snapshot.on_hand_quantity
            - snapshot.reserved_quantity
        ),
        reorder_point=snapshot.reorder_point,
        safety_stock=snapshot.safety_stock,
        maximum_stock=snapshot.maximum_stock,
        recommendation=record.recommendation,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        resolved_at=record.resolved_at,
    )


def to_detail(
    record: StockAlertRecord,
) -> StockAlertDetailResponse:

    return StockAlertDetailResponse(
        **to_response(record).model_dump(),
        events=list(record.events),
    )


# ============================================================
# STOCK ALERT ENGINE
# ============================================================

class StockAlertEngine:

    @staticmethod
    def recommendation(
        snapshot: StockSnapshot,
    ) -> StockRecommendation:

        available = (
            snapshot.on_hand_quantity
            - snapshot.reserved_quantity
        )

        demand = snapshot.average_daily_demand

        lead_time_demand = math.ceil(
            demand * snapshot.lead_time_days
        )

        target = max(
            snapshot.reorder_point,
            snapshot.safety_stock
            + lead_time_demand,
        )

        if snapshot.maximum_stock > 0:
            target = min(
                target,
                snapshot.maximum_stock,
            )

        reorder_quantity = max(
            0,
            target - available,
        )

        days_of_cover = (
            round(available / demand, 2)
            if demand > 0
            else None
        )

        return StockRecommendation(
            available_quantity=available,
            reorder_quantity=reorder_quantity,
            days_of_cover=days_of_cover,
            estimated_lead_time_demand=lead_time_demand,
        )

    @staticmethod
    def detect(
        snapshot: StockSnapshot,
    ) -> list[
        tuple[
            StockAlertType,
            StockAlertSeverity,
            str,
        ]
    ]:

        available = (
            snapshot.on_hand_quantity
            - snapshot.reserved_quantity
        )

        alerts = []

        if available == 0:

            alerts.append((
                StockAlertType.STOCKOUT,
                StockAlertSeverity.CRITICAL,
                "Product is out of available stock",
            ))

        elif available <= snapshot.safety_stock:

            alerts.append((
                StockAlertType.LOW_STOCK,
                StockAlertSeverity.HIGH,
                "Available stock is at or below safety stock",
            ))

        elif available <= snapshot.reorder_point:

            alerts.append((
                StockAlertType.LOW_STOCK,
                StockAlertSeverity.WARNING,
                "Available stock is below replenishment threshold",
            ))

        if available <= snapshot.reorder_point:

            alerts.append((
                StockAlertType.REORDER_REQUIRED,
                (
                    StockAlertSeverity.CRITICAL
                    if available == 0
                    else StockAlertSeverity.HIGH
                ),
                "Replenishment review is required",
            ))

        if snapshot.maximum_stock > 0:

            if available > snapshot.maximum_stock:

                alerts.append((
                    StockAlertType.OVERSTOCK,
                    StockAlertSeverity.WARNING,
                    "Available stock exceeds configured maximum",
                ))

            if available > snapshot.maximum_stock * 1.5:

                alerts.append((
                    StockAlertType.EXCESS_STOCK,
                    StockAlertSeverity.HIGH,
                    "Significant excess stock detected",
                ))

        demand = snapshot.average_daily_demand

        if demand > 0 and available > 0:

            days_cover = available / demand

            if days_cover < snapshot.lead_time_days:

                alerts.append((
                    StockAlertType.LOW_DAYS_COVER,
                    StockAlertSeverity.HIGH,
                    "Stock cover is shorter than supplier lead time",
                ))

        return alerts


# ============================================================
# STOCK ALERT STORE
# ============================================================

class StockAlertStore:

    def __init__(self):

        self._alerts: dict[
            str,
            StockAlertRecord,
        ] = {}

        self._active_index: dict[
            tuple[str, str, str, StockAlertType],
            str,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, list[StockEvaluationResponse]],
        ] = {}

        self._lock = asyncio.Lock()

        self.engine = StockAlertEngine()

    @staticmethod
    def _add_event(
        record: StockAlertRecord,
        event_type: StockAlertEventType,
        actor_id: str,
        details: str | None = None,
    ) -> None:

        if len(record.events) >= MAX_EVENTS_PER_ALERT:
            raise HTTPException(
                status_code=503,
                detail="Alert event capacity reached",
            )

        record.events.append(
            StockAlertEventResponse(
                event_id=secrets.token_urlsafe(16),
                event_type=event_type,
                actor_id=actor_id,
                details=details,
                created_at=utc_now(),
            )
        )

    @staticmethod
    def _touch(
        record: StockAlertRecord,
    ) -> None:

        record.version += 1
        record.updated_at = utc_now()

    def _get(
        self,
        principal: Principal,
        alert_id: str,
        *,
        write: bool,
    ) -> StockAlertRecord:

        record = self._alerts.get(alert_id)

        if (
            record is None
            or record.tenant_id != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Stock alert not found",
            )

        require_stock_alert_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    @staticmethod
    def _check_version(
        record: StockAlertRecord,
        expected_version: int,
    ) -> None:

        if record.version != expected_version:
            raise HTTPException(
                status_code=409,
                detail="Stock alert version conflict",
            )

    def _evaluate_locked(
        self,
        principal: Principal,
        snapshot: StockSnapshot,
    ) -> StockEvaluationResponse:

        detected = self.engine.detect(snapshot)

        recommendation = self.engine.recommendation(
            snapshot
        )

        result_alerts = []

        for alert_type, severity, message in detected:

            key = (
                principal.tenant_id,
                snapshot.warehouse_id,
                snapshot.product_id,
                alert_type,
            )

            existing_id = self._active_index.get(key)

            if existing_id:

                record = self._alerts[existing_id]

                self._add_event(
                    record,
                    StockAlertEventType.UPDATED,
                    principal.principal_id,
                    "Alert refreshed from stock snapshot",
                )

                record.snapshot = snapshot
                record.recommendation = recommendation
                record.severity = severity
                record.message = message

                self._touch(record)

            else:

                record = StockAlertRecord(
                    alert_id=secrets.token_urlsafe(20),
                    tenant_id=principal.tenant_id,
                    warehouse_id=snapshot.warehouse_id,
                    product_id=snapshot.product_id,
                    sku=snapshot.sku,
                    alert_type=alert_type,
                    severity=severity,
                    status=StockAlertStatus.OPEN,
                    message=message,
                    snapshot=snapshot,
                    recommendation=recommendation,
                )

                self._add_event(
                    record,
                    StockAlertEventType.CREATED,
                    principal.principal_id,
                )

                self._alerts[record.alert_id] = record
                self._active_index[key] = record.alert_id

            result_alerts.append(
                to_response(record)
            )

        return StockEvaluationResponse(
            warehouse_id=snapshot.warehouse_id,
            product_id=snapshot.product_id,
            available_quantity=(
                snapshot.on_hand_quantity
                - snapshot.reserved_quantity
            ),
            healthy=not bool(detected),
            alerts=result_alerts,
            recommendation=recommendation,
            evaluated_at=utc_now(),
        )

    async def evaluate_batch(
        self,
        principal: Principal,
        snapshots: list[StockSnapshot],
        source_request_id: str,
    ) -> StockBatchEvaluationResponse:

        for snapshot in snapshots:
            require_stock_alert_access(
                principal,
                snapshot.warehouse_id,
                write=True,
            )

        key = (
            principal.tenant_id,
            principal.principal_id,
            source_request_id,
        )

        fingerprint = snapshot_fingerprint(snapshots)

        async with self._lock:

            previous = self._idempotency.get(key)

            if previous:

                previous_hash, previous_results = previous

                if previous_hash != fingerprint:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                results = previous_results

            else:

                tenant_count = sum(
                    alert.tenant_id == principal.tenant_id
                    for alert in self._alerts.values()
                )

                if (
                    tenant_count >= MAX_ALERTS_PER_TENANT
                    or len(self._idempotency)
                    >= MAX_IDEMPOTENCY_KEYS
                ):
                    raise HTTPException(
                        status_code=503,
                        detail="Stock alert capacity reached",
                    )

                results = [
                    self._evaluate_locked(
                        principal,
                        snapshot,
                    )
                    for snapshot in snapshots
                ]

                self._idempotency[key] = (
                    fingerprint,
                    results,
                )

            return StockBatchEvaluationResponse(
                evaluated_count=len(results),
                healthy_count=sum(
                    result.healthy
                    for result in results
                ),
                affected_product_count=sum(
                    not result.healthy
                    for result in results
                ),
                results=results,
            )

    async def get(
        self,
        principal: Principal,
        alert_id: str,
    ) -> StockAlertDetailResponse:

        async with self._lock:

            return to_detail(
                self._get(
                    principal,
                    alert_id,
                    write=False,
                )
            )

    async def list_alerts(
        self,
        principal: Principal,
        warehouse_id: str | None,
        status: StockAlertStatus | None,
        severity: StockAlertSeverity | None,
        alert_type: StockAlertType | None,
        limit: int,
    ) -> list[StockAlertResponse]:

        if warehouse_id is not None:
            require_stock_alert_access(
                principal,
                warehouse_id,
                write=False,
            )

        async with self._lock:

            records = sorted(
                (
                    record
                    for record in self._alerts.values()
                    if (
                        record.tenant_id
                        == principal.tenant_id
                        and (
                            warehouse_id is None
                            or record.warehouse_id
                            == warehouse_id
                        )
                        and (
                            status is None
                            or record.status == status
                        )
                        and (
                            severity is None
                            or record.severity == severity
                        )
                        and (
                            alert_type is None
                            or record.alert_type == alert_type
                        )
                    )
                ),
                key=lambda record: record.created_at,
                reverse=True,
            )

            results = []

            for record in records:

                try:
                    require_stock_alert_access(
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

    async def acknowledge(
        self,
        principal: Principal,
        alert_id: str,
        payload: StockAlertVersionRequest,
    ) -> StockAlertResponse:

        async with self._lock:

            record = self._get(
                principal,
                alert_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status != StockAlertStatus.OPEN:
                raise HTTPException(
                    status_code=409,
                    detail="Only open alerts can be acknowledged",
                )

            self._add_event(
                record,
                StockAlertEventType.ACKNOWLEDGED,
                principal.principal_id,
                payload.notes,
            )

            record.status = StockAlertStatus.ACKNOWLEDGED

            self._touch(record)

            return to_response(record)

    async def resolve(
        self,
        principal: Principal,
        alert_id: str,
        payload: StockAlertVersionRequest,
    ) -> StockAlertResponse:

        async with self._lock:

            record = self._get(
                principal,
                alert_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status == StockAlertStatus.RESOLVED:
                raise HTTPException(
                    status_code=409,
                    detail="Alert already resolved",
                )

            self._add_event(
                record,
                StockAlertEventType.RESOLVED,
                principal.principal_id,
                payload.notes,
            )

            record.status = StockAlertStatus.RESOLVED
            record.resolved_at = utc_now()

            key = (
                record.tenant_id,
                record.warehouse_id,
                record.product_id,
                record.alert_type,
            )

            self._active_index.pop(key, None)

            self._touch(record)

            return to_response(record)

    async def analytics(
        self,
        principal: Principal,
        warehouse_id: str,
    ) -> StockAlertAnalyticsResponse:

        require_stock_alert_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._alerts.values()
                if (
                    record.tenant_id == principal.tenant_id
                    and record.warehouse_id == warehouse_id
                )
            ]

            statuses = [record.status for record in records]
            severities = [record.severity for record in records]
            types = [record.alert_type for record in records]

            return StockAlertAnalyticsResponse(
                total_alerts=len(records),
                open_alerts=statuses.count(
                    StockAlertStatus.OPEN
                ),
                acknowledged_alerts=statuses.count(
                    StockAlertStatus.ACKNOWLEDGED
                ),
                resolved_alerts=statuses.count(
                    StockAlertStatus.RESOLVED
                ),
                critical_alerts=severities.count(
                    StockAlertSeverity.CRITICAL
                ),
                high_alerts=severities.count(
                    StockAlertSeverity.HIGH
                ),
                warning_alerts=severities.count(
                    StockAlertSeverity.WARNING
                ),
                stockout_alerts=types.count(
                    StockAlertType.STOCKOUT
                ),
                low_stock_alerts=types.count(
                    StockAlertType.LOW_STOCK
                ),
                reorder_alerts=types.count(
                    StockAlertType.REORDER_REQUIRED
                ),
                overstock_alerts=types.count(
                    StockAlertType.OVERSTOCK
                ),
                excess_stock_alerts=types.count(
                    StockAlertType.EXCESS_STOCK
                ),
                low_cover_alerts=types.count(
                    StockAlertType.LOW_DAYS_COVER
                ),
            )


stock_alert_store = StockAlertStore()


# ============================================================
# SERVICE
# ============================================================

class StockAlertService:

    def __init__(
        self,
        store: StockAlertStore,
    ):
        self.store = store

    async def evaluate(
        self,
        principal: Principal,
        payload: StockEvaluationRequest,
    ) -> StockBatchEvaluationResponse:

        return await self.store.evaluate_batch(
            principal,
            [payload.snapshot],
            payload.source_request_id,
        )


stock_alert_service = StockAlertService(
    stock_alert_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Stock Alerts"],
)


@router.post(
    "/evaluate",
    response_model=StockBatchEvaluationResponse,
)
async def evaluate_stock(
    payload: StockEvaluationRequest,
    principal: CurrentPrincipal,
):
    return await stock_alert_service.evaluate(
        principal,
        payload,
    )


@router.post(
    "/evaluate-batch",
    response_model=StockBatchEvaluationResponse,
)
async def evaluate_stock_batch(
    payload: StockBatchEvaluationRequest,
    principal: CurrentPrincipal,
):
    return await stock_alert_store.evaluate_batch(
        principal,
        payload.snapshots,
        payload.source_request_id,
    )


@router.get(
    "",
    response_model=list[StockAlertResponse],
)
async def list_stock_alerts(
    principal: CurrentPrincipal,
    warehouse_id: str | None = None,
    status: StockAlertStatus | None = None,
    severity: StockAlertSeverity | None = None,
    alert_type: StockAlertType | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await stock_alert_store.list_alerts(
        principal,
        warehouse_id,
        status,
        severity,
        alert_type,
        limit,
    )


@router.get(
    "/analytics/{warehouse_id}",
    response_model=StockAlertAnalyticsResponse,
)
async def stock_alert_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
):
    return await stock_alert_store.analytics(
        principal,
        warehouse_id,
    )


@router.get(
    "/{alert_id}",
    response_model=StockAlertDetailResponse,
)
async def get_stock_alert(
    alert_id: str,
    principal: CurrentPrincipal,
):
    return await stock_alert_store.get(
        principal,
        alert_id,
    )


@router.post(
    "/{alert_id}/acknowledge",
    response_model=StockAlertResponse,
)
async def acknowledge_stock_alert(
    alert_id: str,
    payload: StockAlertVersionRequest,
    principal: CurrentPrincipal,
):
    return await stock_alert_store.acknowledge(
        principal,
        alert_id,
        payload,
    )


@router.post(
    "/{alert_id}/resolve",
    response_model=StockAlertResponse,
)
async def resolve_stock_alert(
    alert_id: str,
    payload: StockAlertVersionRequest,
    principal: CurrentPrincipal,
):
    return await stock_alert_store.resolve(
        principal,
        alert_id,
        payload,
    )


__all__ = [
    "StockAlertType",
    "StockAlertSeverity",
    "StockAlertStatus",
    "StockAlertEventType",
    "StockSnapshot",
    "StockEvaluationRequest",
    "StockBatchEvaluationRequest",
    "StockAlertVersionRequest",
    "StockRecommendation",
    "StockAlertEventResponse",
    "StockAlertResponse",
    "StockAlertDetailResponse",
    "StockEvaluationResponse",
    "StockBatchEvaluationResponse",
    "StockAlertAnalyticsResponse",
    "StockAlertEngine",
    "StockAlertStore",
    "StockAlertService",
    "stock_alert_store",
    "stock_alert_service",
    "router",
]
