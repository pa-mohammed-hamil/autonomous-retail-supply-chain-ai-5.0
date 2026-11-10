from __future__ import annotations

"""Planned module: replenishment. Implementation pending."""

"""
backend/replenishment.py

Autonomous Retail Supply Chain AI 5.0
Intelligent Inventory Replenishment API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Reorder point calculations
    - Safety stock calculations
    - Lead-time demand estimation
    - Days-of-cover estimation
    - Inventory replenishment recommendations
    - Supplier minimum order quantities
    - Order multiple constraints
    - Budget-aware replenishment planning
    - Human approval / rejection
    - Draft purchase order proposals
    - Tenant and warehouse authorization
    - Optimistic concurrency
    - Idempotent plan creation
    - Replenishment analytics

Prototype:
    In-memory planning and approval workflow.
    No real stock changes or supplier orders.
"""


import asyncio
import hashlib
import json
import math
import secrets

from dataclasses import dataclass, field
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


API_PREFIX = "/api/v1/replenishment"

MAX_PLANS_PER_TENANT = 50000
MAX_ITEMS_PER_PLAN = 200
MAX_EVENTS_PER_PLAN = 500
MAX_IDEMPOTENCY_KEYS = 100000
MAX_LIST_LIMIT = 200

MONEY_QUANTUM = Decimal("0.01")


# ============================================================
# ENUMS
# ============================================================

class ReplenishmentStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    PO_PROPOSED = "po_proposed"
    CANCELLED = "cancelled"


class ReplenishmentPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class ReplenishmentStrategy(str, Enum):
    REORDER_POINT = "reorder_point"
    DAYS_OF_COVER = "days_of_cover"
    HYBRID = "hybrid"


class ReplenishmentEventType(str, Enum):
    CREATED = "created"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    PO_PROPOSED = "po_proposed"
    CANCELLED = "cancelled"


# ============================================================
# REQUEST MODELS
# ============================================================

class ReplenishmentItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    sku: str = Field(
        min_length=1,
        max_length=100,
    )

    supplier_id: str = Field(
        min_length=1,
        max_length=128,
    )

    on_hand_quantity: int = Field(ge=0)
    reserved_quantity: int = Field(ge=0)
    incoming_quantity: int = Field(ge=0)

    average_daily_demand: float = Field(
        ge=0,
        le=10000000,
        allow_inf_nan=False,
    )

    demand_std_dev: float = Field(
        ge=0,
        le=10000000,
        allow_inf_nan=False,
    )

    lead_time_days: int = Field(
        ge=1,
        le=365,
    )

    safety_stock_z_score: float = Field(
        default=1.65,
        ge=0,
        le=5,
        allow_inf_nan=False,
    )

    target_cover_days: int = Field(
        default=30,
        ge=1,
        le=365,
    )

    minimum_order_quantity: int = Field(
        default=1,
        ge=1,
    )

    order_multiple: int = Field(
        default=1,
        ge=1,
    )

    unit_cost: Decimal = Field(
        ge=0,
        max_digits=16,
        decimal_places=2,
    )

    @model_validator(mode="after")
    def validate_stock(self):

        if self.reserved_quantity > self.on_hand_quantity:
            raise ValueError(
                "Reserved quantity cannot exceed on-hand quantity"
            )

        return self


class ReplenishmentPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    strategy: ReplenishmentStrategy = (
        ReplenishmentStrategy.HYBRID
    )

    currency: str = Field(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    )

    budget_limit: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=2,
    )

    items: list[
        ReplenishmentItemInput
    ] = Field(
        min_length=1,
        max_length=MAX_ITEMS_PER_PLAN,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_items(self):

        product_ids = [
            item.product_id
            for item in self.items
        ]

        if len(set(product_ids)) != len(product_ids):
            raise ValueError(
                "Duplicate products in replenishment plan"
            )

        return self


class ReplenishmentVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class ReplenishmentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    notes: str = Field(
        min_length=3,
        max_length=1000,
    )


class ReplenishmentCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    reason: str = Field(
        min_length=5,
        max_length=500,
    )


# ============================================================
# RESPONSE MODELS
# ============================================================

class ReplenishmentItemResponse(BaseModel):
    product_id: str
    sku: str
    supplier_id: str

    available_quantity: int
    incoming_quantity: int
    inventory_position: int

    average_daily_demand: float
    lead_time_days: int

    safety_stock: int
    reorder_point: int
    target_stock: int

    recommended_quantity: int
    unit_cost: Decimal
    estimated_cost: Decimal

    days_of_cover: float | None
    priority: ReplenishmentPriority
    reorder_required: bool


class ReplenishmentEventResponse(BaseModel):
    event_id: str
    event_type: ReplenishmentEventType
    actor_id: str
    details: str | None
    created_at: datetime


class ReplenishmentPlanResponse(BaseModel):
    plan_id: str
    warehouse_id: str
    strategy: ReplenishmentStrategy
    currency: str
    status: ReplenishmentStatus

    total_products: int
    products_requiring_reorder: int
    total_recommended_units: int

    total_estimated_cost: Decimal
    budget_limit: Decimal | None
    within_budget: bool

    version: int
    created_at: datetime
    updated_at: datetime


class ReplenishmentPlanDetailResponse(
    ReplenishmentPlanResponse
):
    items: list[ReplenishmentItemResponse]
    events: list[ReplenishmentEventResponse]
    approval_notes: str | None


class PurchaseOrderProposal(BaseModel):
    supplier_id: str
    warehouse_id: str
    currency: str
    items: list[dict]
    estimated_total: Decimal


class ReplenishmentPOProposalResponse(BaseModel):
    plan_id: str
    proposals: list[PurchaseOrderProposal]
    total_estimated_cost: Decimal


class ReplenishmentAnalyticsResponse(BaseModel):
    total_plans: int
    draft: int
    pending_approval: int
    approved: int
    rejected: int
    po_proposed: int
    cancelled: int
    total_recommended_units: int
    total_estimated_cost: Decimal
    critical_product_recommendations: int


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass
class ReplenishmentPlanRecord:
    plan_id: str
    tenant_id: str
    warehouse_id: str
    strategy: ReplenishmentStrategy
    currency: str

    items: list[ReplenishmentItemResponse]
    created_by: str

    budget_limit: Decimal | None

    status: ReplenishmentStatus = (
        ReplenishmentStatus.DRAFT
    )

    approval_notes: str | None = None

    events: list[
        ReplenishmentEventResponse
    ] = field(default_factory=list)

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


def money(value: Decimal) -> Decimal:
    return value.quantize(
        MONEY_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def round_up(value: float) -> int:
    return math.ceil(max(value, 0))


def request_fingerprint(
    payload: ReplenishmentPlanCreate,
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


def require_replenishment_access(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool,
) -> None:

    # Dedicated REPLENISHMENT_READ/WRITE/APPROVE
    # permissions should be added for production.

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
            detail="Replenishment access denied",
        )


# ============================================================
# REPLENISHMENT ENGINE
# ============================================================

class ReplenishmentEngine:

    @staticmethod
    def calculate(
        item: ReplenishmentItemInput,
        strategy: ReplenishmentStrategy,
    ) -> ReplenishmentItemResponse:

        available = (
            item.on_hand_quantity
            - item.reserved_quantity
        )

        inventory_position = (
            available
            + item.incoming_quantity
        )

        daily_demand = item.average_daily_demand

        lead_time_demand = (
            daily_demand
            * item.lead_time_days
        )

        safety_stock = round_up(
            item.safety_stock_z_score
            * item.demand_std_dev
            * math.sqrt(item.lead_time_days)
        )

        reorder_point = round_up(
            lead_time_demand
            + safety_stock
        )

        target_cover_stock = round_up(
            daily_demand
            * item.target_cover_days
            + safety_stock
        )

        if strategy == ReplenishmentStrategy.REORDER_POINT:
            target_stock = reorder_point

        elif strategy == ReplenishmentStrategy.DAYS_OF_COVER:
            target_stock = target_cover_stock

        else:
            target_stock = max(
                reorder_point,
                target_cover_stock,
            )

        reorder_required = (
            inventory_position <= reorder_point
        )

        raw_quantity = (
            max(
                target_stock - inventory_position,
                0,
            )
            if reorder_required
            else 0
        )

        if raw_quantity > 0:

            raw_quantity = max(
                raw_quantity,
                item.minimum_order_quantity,
            )

            recommended_quantity = (
                (
                    raw_quantity
                    + item.order_multiple
                    - 1
                )
                // item.order_multiple
            ) * item.order_multiple

        else:
            recommended_quantity = 0

        estimated_cost = money(
            Decimal(recommended_quantity)
            * item.unit_cost
        )

        days_of_cover = (
            round(
                available / daily_demand,
                2,
            )
            if daily_demand > 0
            else None
        )

        if (
            available == 0
            and daily_demand > 0
        ):
            priority = ReplenishmentPriority.CRITICAL

        elif (
            days_of_cover is not None
            and days_of_cover
            < item.lead_time_days
        ):
            priority = ReplenishmentPriority.HIGH

        elif reorder_required:
            priority = ReplenishmentPriority.NORMAL

        else:
            priority = ReplenishmentPriority.LOW

        return ReplenishmentItemResponse(
            product_id=item.product_id,
            sku=item.sku,
            supplier_id=item.supplier_id,
            available_quantity=available,
            incoming_quantity=item.incoming_quantity,
            inventory_position=inventory_position,
            average_daily_demand=daily_demand,
            lead_time_days=item.lead_time_days,
            safety_stock=safety_stock,
            reorder_point=reorder_point,
            target_stock=target_stock,
            recommended_quantity=recommended_quantity,
            unit_cost=item.unit_cost,
            estimated_cost=estimated_cost,
            days_of_cover=days_of_cover,
            priority=priority,
            reorder_required=reorder_required,
        )


# ============================================================
# REPLENISHMENT STORE
# ============================================================

class ReplenishmentStore:

    def __init__(self):

        self._plans: dict[
            str,
            ReplenishmentPlanRecord,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    def _get(
        self,
        principal: Principal,
        plan_id: str,
        *,
        write: bool,
    ) -> ReplenishmentPlanRecord:

        record = self._plans.get(plan_id)

        if (
            record is None
            or record.tenant_id
            != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Replenishment plan not found",
            )

        require_replenishment_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    @staticmethod
    def _check_version(
        record: ReplenishmentPlanRecord,
        expected_version: int,
    ) -> None:

        if record.version != expected_version:
            raise HTTPException(
                status_code=409,
                detail="Replenishment version conflict",
            )

    @staticmethod
    def _add_event(
        record: ReplenishmentPlanRecord,
        event_type: ReplenishmentEventType,
        actor_id: str,
        details: str | None = None,
    ) -> None:

        if len(record.events) >= MAX_EVENTS_PER_PLAN:
            raise HTTPException(
                status_code=503,
                detail="Plan event capacity reached",
            )

        record.events.append(
            ReplenishmentEventResponse(
                event_id=secrets.token_urlsafe(16),
                event_type=event_type,
                actor_id=actor_id,
                details=details,
                created_at=utc_now(),
            )
        )

    @staticmethod
    def _touch(
        record: ReplenishmentPlanRecord,
    ) -> None:

        record.version += 1
        record.updated_at = utc_now()

    @staticmethod
    def _summary(
        record: ReplenishmentPlanRecord,
    ) -> ReplenishmentPlanResponse:

        total_cost = money(
            sum(
                (
                    item.estimated_cost
                    for item in record.items
                ),
                Decimal("0"),
            )
        )

        return ReplenishmentPlanResponse(
            plan_id=record.plan_id,
            warehouse_id=record.warehouse_id,
            strategy=record.strategy,
            currency=record.currency,
            status=record.status,
            total_products=len(record.items),
            products_requiring_reorder=sum(
                item.recommended_quantity > 0
                for item in record.items
            ),
            total_recommended_units=sum(
                item.recommended_quantity
                for item in record.items
            ),
            total_estimated_cost=total_cost,
            budget_limit=record.budget_limit,
            within_budget=(
                record.budget_limit is None
                or total_cost <= record.budget_limit
            ),
            version=record.version,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @classmethod
    def _detail(
        cls,
        record: ReplenishmentPlanRecord,
    ) -> ReplenishmentPlanDetailResponse:

        return ReplenishmentPlanDetailResponse(
            **cls._summary(record).model_dump(),
            items=list(record.items),
            events=list(record.events),
            approval_notes=record.approval_notes,
        )

    async def create(
        self,
        principal: Principal,
        payload: ReplenishmentPlanCreate,
    ) -> ReplenishmentPlanResponse:

        require_replenishment_access(
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

            previous = self._idempotency.get(key)

            if previous:

                old_hash, plan_id = previous

                if old_hash != fingerprint:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return self._summary(
                    self._get(
                        principal,
                        plan_id,
                        write=False,
                    )
                )

            tenant_count = sum(
                record.tenant_id
                == principal.tenant_id
                for record in self._plans.values()
            )

            if (
                tenant_count >= MAX_PLANS_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Replenishment capacity reached",
                )

            recommendations = [
                ReplenishmentEngine.calculate(
                    item,
                    payload.strategy,
                )
                for item in payload.items
            ]

            record = ReplenishmentPlanRecord(
                plan_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                strategy=payload.strategy,
                currency=payload.currency,
                items=recommendations,
                created_by=principal.principal_id,
                budget_limit=payload.budget_limit,
            )

            self._add_event(
                record,
                ReplenishmentEventType.CREATED,
                principal.principal_id,
            )

            self._plans[record.plan_id] = record

            self._idempotency[key] = (
                fingerprint,
                record.plan_id,
            )

            return self._summary(record)

    async def get(
        self,
        principal: Principal,
        plan_id: str,
    ) -> ReplenishmentPlanDetailResponse:

        async with self._lock:

            return self._detail(
                self._get(
                    principal,
                    plan_id,
                    write=False,
                )
            )

    async def list_plans(
        self,
        principal: Principal,
        warehouse_id: str | None,
        status: ReplenishmentStatus | None,
        limit: int,
    ) -> list[ReplenishmentPlanResponse]:

        async with self._lock:

            records = [
                record
                for record in self._plans.values()
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
                )
            ]

            records.sort(
                key=lambda item: item.created_at,
                reverse=True,
            )

            results = []

            for record in records:

                try:
                    require_replenishment_access(
                        principal,
                        record.warehouse_id,
                        write=False,
                    )
                except HTTPException:
                    continue

                results.append(
                    self._summary(record)
                )

                if len(results) >= limit:
                    break

            return results

    async def submit(
        self,
        principal: Principal,
        plan_id: str,
        expected_version: int,
    ) -> ReplenishmentPlanResponse:

        async with self._lock:

            record = self._get(
                principal,
                plan_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            if record.status != ReplenishmentStatus.DRAFT:
                raise HTTPException(
                    status_code=409,
                    detail="Only draft plans can be submitted",
                )

            if not any(
                item.recommended_quantity > 0
                for item in record.items
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Plan has no replenishment requirements",
                )

            record.status = (
                ReplenishmentStatus.PENDING_APPROVAL
            )

            self._add_event(
                record,
                ReplenishmentEventType.SUBMITTED,
                principal.principal_id,
            )

            self._touch(record)

            return self._summary(record)

    async def decide(
        self,
        principal: Principal,
        plan_id: str,
        payload: ReplenishmentDecision,
        approve: bool,
    ) -> ReplenishmentPlanResponse:

        async with self._lock:

            record = self._get(
                principal,
                plan_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if (
                record.status
                != ReplenishmentStatus.PENDING_APPROVAL
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Plan is not pending approval",
                )

            if record.created_by == principal.principal_id:
                raise HTTPException(
                    status_code=403,
                    detail="Creator cannot approve own plan",
                )

            summary = self._summary(record)

            if approve and not summary.within_budget:
                raise HTTPException(
                    status_code=409,
                    detail="Plan exceeds budget limit",
                )

            record.status = (
                ReplenishmentStatus.APPROVED
                if approve
                else ReplenishmentStatus.REJECTED
            )

            record.approval_notes = payload.notes

            self._add_event(
                record,
                (
                    ReplenishmentEventType.APPROVED
                    if approve
                    else ReplenishmentEventType.REJECTED
                ),
                principal.principal_id,
                payload.notes,
            )

            self._touch(record)

            return self._summary(record)

    async def propose_purchase_orders(
        self,
        principal: Principal,
        plan_id: str,
        expected_version: int,
    ) -> ReplenishmentPOProposalResponse:

        async with self._lock:

            record = self._get(
                principal,
                plan_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            if record.status != ReplenishmentStatus.APPROVED:
                raise HTTPException(
                    status_code=409,
                    detail="Plan must be approved first",
                )

            groups: dict[
                str,
                list[ReplenishmentItemResponse],
            ] = {}

            for item in record.items:

                if item.recommended_quantity <= 0:
                    continue

                groups.setdefault(
                    item.supplier_id,
                    [],
                ).append(item)

            proposals = []

            for supplier_id, items in groups.items():

                estimated_total = money(
                    sum(
                        (
                            item.estimated_cost
                            for item in items
                        ),
                        Decimal("0"),
                    )
                )

                proposals.append(
                    PurchaseOrderProposal(
                        supplier_id=supplier_id,
                        warehouse_id=record.warehouse_id,
                        currency=record.currency,
                        items=[
                            {
                                "product_id": item.product_id,
                                "sku": item.sku,
                                "quantity": item.recommended_quantity,
                                "unit_cost": str(item.unit_cost),
                            }
                            for item in items
                        ],
                        estimated_total=estimated_total,
                    )
                )

            self._add_event(
                record,
                ReplenishmentEventType.PO_PROPOSED,
                principal.principal_id,
            )

            record.status = (
                ReplenishmentStatus.PO_PROPOSED
            )

            self._touch(record)

            return ReplenishmentPOProposalResponse(
                plan_id=record.plan_id,
                proposals=proposals,
                total_estimated_cost=money(
                    sum(
                        (
                            proposal.estimated_total
                            for proposal in proposals
                        ),
                        Decimal("0"),
                    )
                ),
            )

    async def cancel(
        self,
        principal: Principal,
        plan_id: str,
        payload: ReplenishmentCancelRequest,
    ) -> ReplenishmentPlanResponse:

        async with self._lock:

            record = self._get(
                principal,
                plan_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status in {
                ReplenishmentStatus.PO_PROPOSED,
                ReplenishmentStatus.CANCELLED,
            }:
                raise HTTPException(
                    status_code=409,
                    detail="Plan cannot be cancelled",
                )

            self._add_event(
                record,
                ReplenishmentEventType.CANCELLED,
                principal.principal_id,
                payload.reason,
            )

            record.status = (
                ReplenishmentStatus.CANCELLED
            )

            self._touch(record)

            return self._summary(record)

    async def analytics(
        self,
        principal: Principal,
        warehouse_id: str,
    ) -> ReplenishmentAnalyticsResponse:

        require_replenishment_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._plans.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and record.warehouse_id
                    == warehouse_id
                )
            ]

            statuses = [
                record.status
                for record in records
            ]

            items = [
                item
                for record in records
                for item in record.items
            ]

            return ReplenishmentAnalyticsResponse(
                total_plans=len(records),
                draft=statuses.count(
                    ReplenishmentStatus.DRAFT
                ),
                pending_approval=statuses.count(
                    ReplenishmentStatus.PENDING_APPROVAL
                ),
                approved=statuses.count(
                    ReplenishmentStatus.APPROVED
                ),
                rejected=statuses.count(
                    ReplenishmentStatus.REJECTED
                ),
                po_proposed=statuses.count(
                    ReplenishmentStatus.PO_PROPOSED
                ),
                cancelled=statuses.count(
                    ReplenishmentStatus.CANCELLED
                ),
                total_recommended_units=sum(
                    item.recommended_quantity
                    for item in items
                ),
                total_estimated_cost=money(
                    sum(
                        (
                            item.estimated_cost
                            for item in items
                        ),
                        Decimal("0"),
                    )
                ),
                critical_product_recommendations=sum(
                    item.priority
                    == ReplenishmentPriority.CRITICAL
                    for item in items
                ),
            )


replenishment_store = ReplenishmentStore()


# ============================================================
# SERVICE
# ============================================================

class ReplenishmentService:

    def __init__(
        self,
        store: ReplenishmentStore,
    ):
        self.store = store

    async def create(
        self,
        principal: Principal,
        payload: ReplenishmentPlanCreate,
    ) -> ReplenishmentPlanResponse:

        return await self.store.create(
            principal,
            payload,
        )


replenishment_service = ReplenishmentService(
    replenishment_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Replenishment"],
)


@router.post(
    "",
    response_model=ReplenishmentPlanResponse,
    status_code=201,
)
async def create_replenishment_plan(
    payload: ReplenishmentPlanCreate,
    principal: CurrentPrincipal,
):
    return await replenishment_service.create(
        principal,
        payload,
    )


@router.get(
    "",
    response_model=list[ReplenishmentPlanResponse],
)
async def list_replenishment_plans(
    principal: CurrentPrincipal,
    warehouse_id: str | None = None,
    status: ReplenishmentStatus | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await replenishment_store.list_plans(
        principal,
        warehouse_id,
        status,
        limit,
    )


@router.get(
    "/analytics/{warehouse_id}",
    response_model=ReplenishmentAnalyticsResponse,
)
async def replenishment_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
):
    return await replenishment_store.analytics(
        principal,
        warehouse_id,
    )


@router.get(
    "/{plan_id}",
    response_model=ReplenishmentPlanDetailResponse,
)
async def get_replenishment_plan(
    plan_id: str,
    principal: CurrentPrincipal,
):
    return await replenishment_store.get(
        principal,
        plan_id,
    )


@router.post(
    "/{plan_id}/submit",
    response_model=ReplenishmentPlanResponse,
)
async def submit_replenishment_plan(
    plan_id: str,
    payload: ReplenishmentVersionRequest,
    principal: CurrentPrincipal,
):
    return await replenishment_store.submit(
        principal,
        plan_id,
        payload.expected_version,
    )


@router.post(
    "/{plan_id}/approve",
    response_model=ReplenishmentPlanResponse,
)
async def approve_replenishment_plan(
    plan_id: str,
    payload: ReplenishmentDecision,
    principal: CurrentPrincipal,
):
    return await replenishment_store.decide(
        principal,
        plan_id,
        payload,
        approve=True,
    )


@router.post(
    "/{plan_id}/reject",
    response_model=ReplenishmentPlanResponse,
)
async def reject_replenishment_plan(
    plan_id: str,
    payload: ReplenishmentDecision,
    principal: CurrentPrincipal,
):
    return await replenishment_store.decide(
        principal,
        plan_id,
        payload,
        approve=False,
    )


@router.post(
    "/{plan_id}/purchase-order-proposals",
    response_model=ReplenishmentPOProposalResponse,
)
async def propose_replenishment_purchase_orders(
    plan_id: str,
    payload: ReplenishmentVersionRequest,
    principal: CurrentPrincipal,
):
    return await replenishment_store.propose_purchase_orders(
        principal,
        plan_id,
        payload.expected_version,
    )


@router.post(
    "/{plan_id}/cancel",
    response_model=ReplenishmentPlanResponse,
)
async def cancel_replenishment_plan(
    plan_id: str,
    payload: ReplenishmentCancelRequest,
    principal: CurrentPrincipal,
):
    return await replenishment_store.cancel(
        principal,
        plan_id,
        payload,
    )


__all__ = [
    "ReplenishmentStatus",
    "ReplenishmentPriority",
    "ReplenishmentStrategy",
    "ReplenishmentEventType",
    "ReplenishmentItemInput",
    "ReplenishmentPlanCreate",
    "ReplenishmentVersionRequest",
    "ReplenishmentDecision",
    "ReplenishmentCancelRequest",
    "ReplenishmentItemResponse",
    "ReplenishmentEventResponse",
    "ReplenishmentPlanResponse",
    "ReplenishmentPlanDetailResponse",
    "PurchaseOrderProposal",
    "ReplenishmentPOProposalResponse",
    "ReplenishmentAnalyticsResponse",
    "ReplenishmentEngine",
    "ReplenishmentStore",
    "ReplenishmentService",
    "replenishment_store",
    "replenishment_service",
    "router",
]
