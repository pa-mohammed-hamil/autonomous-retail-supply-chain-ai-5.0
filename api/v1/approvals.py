from __future__ import annotations

"""Planned module: approvals. Implementation pending."""

"""
backend/approvals.py

Autonomous Retail Supply Chain AI 5.0
Human-in-the-Loop Approval Management API

Python 3.10+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Approval request creation
    - Role-based authorization
    - Human-in-the-loop workflows
    - Separation of duties
    - Purchase order approvals
    - Inventory transfer approvals
    - Supplier change approvals
    - AI agent action approvals
    - Financial action approvals
    - Approval/rejection/cancellation
    - Request expiration
    - Tenant and warehouse isolation
    - Optimistic concurrency
    - Idempotent creation
    - Bounded audit history
    - No automatic execution of actions

IMPORTANT:
    This module records approval decisions.

    Approval does NOT automatically execute
    a purchase order, transfer, payment,
    supplier update, or agent tool.

    The downstream service must revalidate
    permissions, resource state, approved
    action details, and approval validity.

    This is an in-memory prototype.
"""


import asyncio
import hashlib
import json
import secrets

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
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

MAX_APPROVALS_PER_TENANT = 10000
MAX_HISTORY_PER_APPROVAL = 100

DEFAULT_EXPIRY_HOURS = 24
MAX_EXPIRY_HOURS = 168

MAX_REASON_LENGTH = 2000
MAX_RESOURCE_ID_LENGTH = 128

MAX_LIST_LIMIT = 200


# ============================================================
# ENUMS
# ============================================================

class ApprovalActionType(str, Enum):

    PURCHASE_ORDER_CREATE = (
        "purchase_order_create"
    )

    PURCHASE_ORDER_APPROVE = (
        "purchase_order_approve"
    )

    INVENTORY_TRANSFER = (
        "inventory_transfer"
    )

    INVENTORY_ADJUSTMENT = (
        "inventory_adjustment"
    )

    SUPPLIER_UPDATE = (
        "supplier_update"
    )

    SUPPLIER_BLOCK = (
        "supplier_block"
    )

    PRICING_CHANGE = (
        "pricing_change"
    )

    FINANCIAL_ACTION = (
        "financial_action"
    )

    LOGISTICS_REROUTE = (
        "logistics_reroute"
    )

    AI_AGENT_ACTION = (
        "ai_agent_action"
    )

    NOTIFICATION_SEND = (
        "notification_send"
    )


class ApprovalStatus(str, Enum):

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ApprovalEventType(str, Enum):

    CREATED = "created"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class ApprovalPriority(str, Enum):

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ============================================================
# ACTION PERMISSIONS
# ============================================================

# These permissions must be present in
# backend.permissions.Permission.
#
# Adapt names if your existing permission
# enum uses different identifiers.

ACTION_PERMISSIONS = {

    ApprovalActionType.PURCHASE_ORDER_CREATE:
        Permission.PROCUREMENT_WRITE,

    ApprovalActionType.PURCHASE_ORDER_APPROVE:
        Permission.PROCUREMENT_APPROVE,

    ApprovalActionType.INVENTORY_TRANSFER:
        Permission.INVENTORY_WRITE,

    ApprovalActionType.INVENTORY_ADJUSTMENT:
        Permission.INVENTORY_WRITE,

    ApprovalActionType.SUPPLIER_UPDATE:
        Permission.SUPPLIER_WRITE,

    ApprovalActionType.SUPPLIER_BLOCK:
        Permission.SUPPLIER_WRITE,

    ApprovalActionType.PRICING_CHANGE:
        Permission.PRODUCT_WRITE,

    ApprovalActionType.FINANCIAL_ACTION:
        Permission.FINANCE_WRITE,

    ApprovalActionType.LOGISTICS_REROUTE:
        Permission.LOGISTICS_WRITE,

    ApprovalActionType.AI_AGENT_ACTION:
        Permission.AI_AGENT_EXECUTE,

    ApprovalActionType.NOTIFICATION_SEND:
        Permission.NOTIFICATION_SEND,
}


# ============================================================
# REQUEST MODELS
# ============================================================

class ApprovalCreate(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    action_type: ApprovalActionType

    resource_id: str = Field(
        min_length=1,
        max_length=MAX_RESOURCE_ID_LENGTH,
    )

    warehouse_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    priority: ApprovalPriority = (
        ApprovalPriority.MEDIUM
    )

    reason: str = Field(
        min_length=1,
        max_length=MAX_REASON_LENGTH,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    agent_run_id: str | None = Field(
        default=None,
        max_length=128,
    )

    action_payload_hash: str = Field(
        pattern=r"^[a-f0-9]{64}$",
    )

    expires_in_hours: int = Field(
        default=DEFAULT_EXPIRY_HOURS,
        ge=1,
        le=MAX_EXPIRY_HOURS,
    )


class ApprovalDecision(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    expected_version: int = Field(
        ge=1
    )

    reason: str = Field(
        min_length=1,
        max_length=MAX_REASON_LENGTH,
    )


class ApprovalCancelRequest(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    expected_version: int = Field(
        ge=1
    )

    reason: str = Field(
        min_length=1,
        max_length=MAX_REASON_LENGTH,
    )


# ============================================================
# RESPONSE MODELS
# ============================================================

class ApprovalEventResponse(BaseModel):

    event_id: str
    approval_id: str

    event_type: ApprovalEventType

    actor_id: str

    message: str

    version: int

    timestamp: datetime


class ApprovalResponse(BaseModel):

    approval_id: str

    action_type: ApprovalActionType

    resource_id: str
    warehouse_id: str | None

    priority: ApprovalPriority

    status: ApprovalStatus

    requester_id: str

    approver_id: str | None

    reason: str

    action_payload_hash: str

    agent_run_id: str | None

    version: int

    created_at: datetime
    expires_at: datetime

    decided_at: datetime | None
    cancelled_at: datetime | None


class ApprovalDetailResponse(
    ApprovalResponse
):

    history: list[
        ApprovalEventResponse
    ]


class ApprovalSummary(BaseModel):

    total: int
    pending: int
    approved: int
    rejected: int
    cancelled: int
    expired: int


# ============================================================
# INTERNAL RECORD
# ============================================================

@dataclass
class ApprovalRecord:

    approval_id: str

    tenant_id: str

    action_type: ApprovalActionType

    resource_id: str
    warehouse_id: str | None

    priority: ApprovalPriority

    requester_id: str

    source_request_id: str
    payload_fingerprint: str

    action_payload_hash: str

    agent_run_id: str | None

    reason: str

    status: ApprovalStatus = (
        ApprovalStatus.PENDING
    )

    approver_id: str | None = None

    version: int = 1

    created_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    expires_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    decided_at: datetime | None = None
    cancelled_at: datetime | None = None

    history: list[
        ApprovalEventResponse
    ] = field(
        default_factory=list
    )


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint_request(
    payload: ApprovalCreate,
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


def to_response(
    record: ApprovalRecord,
) -> ApprovalResponse:

    return ApprovalResponse(
        approval_id=record.approval_id,
        action_type=record.action_type,
        resource_id=record.resource_id,
        warehouse_id=record.warehouse_id,
        priority=record.priority,
        status=record.status,
        requester_id=record.requester_id,
        approver_id=record.approver_id,
        reason=record.reason,
        action_payload_hash=(
            record.action_payload_hash
        ),
        agent_run_id=record.agent_run_id,
        version=record.version,
        created_at=record.created_at,
        expires_at=record.expires_at,
        decided_at=record.decided_at,
        cancelled_at=record.cancelled_at,
    )


def to_detail_response(
    record: ApprovalRecord,
) -> ApprovalDetailResponse:

    return ApprovalDetailResponse(
        **to_response(record).model_dump(),
        history=list(record.history),
    )


# ============================================================
# AUTHORIZATION
# ============================================================

def require_permission(
    principal: Principal,
    permission: Permission,
    warehouse_id: str | None,
) -> None:

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
            detail="Approval permission denied",
        )

    allowed = principal.allowed_warehouse_ids

    if (
        warehouse_id is not None
        and allowed is not None
        and warehouse_id not in allowed
    ):
        raise HTTPException(
            status_code=403,
            detail="Warehouse access denied",
        )


def require_approval_read(
    principal: Principal,
    record: ApprovalRecord,
) -> None:

    if record.tenant_id != principal.tenant_id:
        raise HTTPException(
            status_code=404,
            detail="Approval not found",
        )

    require_permission(
        principal,
        Permission.PROCUREMENT_READ,
        record.warehouse_id,
    )

    if (
        record.requester_id
        != principal.principal_id
    ):

        action_permission = (
            ACTION_PERMISSIONS[
                record.action_type
            ]
        )

        require_permission(
            principal,
            action_permission,
            record.warehouse_id,
        )


def require_approval_decision(
    principal: Principal,
    record: ApprovalRecord,
) -> None:

    if record.requester_id == principal.principal_id:
        raise HTTPException(
            status_code=403,
            detail=(
                "Self-approval is not permitted"
            ),
        )

    action_permission = ACTION_PERMISSIONS[
        record.action_type
    ]

    require_permission(
        principal,
        action_permission,
        record.warehouse_id,
    )

    # A dedicated approval permission is
    # required for consequential actions.
    require_permission(
        principal,
        Permission.PROCUREMENT_APPROVE,
        record.warehouse_id,
    )


# ============================================================
# APPROVAL STORE
# ============================================================

class ApprovalStore:

    def __init__(self):

        self._records: dict[
            str,
            ApprovalRecord,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            str,
        ] = {}

        self._lock = asyncio.Lock()

    def _append_event(
        self,
        record: ApprovalRecord,
        event_type: ApprovalEventType,
        actor_id: str,
        message: str,
    ) -> None:

        record.history.append(
            ApprovalEventResponse(
                event_id=secrets.token_urlsafe(16),
                approval_id=record.approval_id,
                event_type=event_type,
                actor_id=actor_id,
                message=message,
                version=record.version,
                timestamp=utc_now(),
            )
        )

        if (
            len(record.history)
            > MAX_HISTORY_PER_APPROVAL
        ):
            record.history = record.history[
                -MAX_HISTORY_PER_APPROVAL:
            ]

    def _expire_if_needed(
        self,
        record: ApprovalRecord,
    ) -> None:

        if (
            record.status == ApprovalStatus.PENDING
            and utc_now() >= record.expires_at
        ):

            record.status = ApprovalStatus.EXPIRED
            record.version += 1

            self._append_event(
                record,
                ApprovalEventType.EXPIRED,
                "system",
                "Approval request expired",
            )

    async def create(
        self,
        *,
        principal: Principal,
        payload: ApprovalCreate,
    ) -> ApprovalRecord:

        # A requester must be authorized to
        # request the corresponding action.
        require_permission(
            principal,
            ACTION_PERMISSIONS[
                payload.action_type
            ],
            payload.warehouse_id,
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

            existing_id = self._idempotency.get(
                key
            )

            if existing_id is not None:

                existing = self._records[
                    existing_id
                ]

                if (
                    existing.payload_fingerprint
                    != fingerprint
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return existing

            tenant_count = sum(
                record.tenant_id
                == principal.tenant_id
                for record in self._records.values()
            )

            if (
                tenant_count
                >= MAX_APPROVALS_PER_TENANT
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Approval capacity reached",
                )

            now = utc_now()

            record = ApprovalRecord(
                approval_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                action_type=payload.action_type,
                resource_id=payload.resource_id,
                warehouse_id=payload.warehouse_id,
                priority=payload.priority,
                requester_id=principal.principal_id,
                source_request_id=(
                    payload.source_request_id
                ),
                payload_fingerprint=fingerprint,
                action_payload_hash=(
                    payload.action_payload_hash
                ),
                agent_run_id=payload.agent_run_id,
                reason=payload.reason,
                created_at=now,
                expires_at=(
                    now
                    + timedelta(
                        hours=payload.expires_in_hours
                    )
                ),
            )

            self._append_event(
                record,
                ApprovalEventType.CREATED,
                principal.principal_id,
                "Approval request created",
            )

            self._records[
                record.approval_id
            ] = record

            self._idempotency[key] = (
                record.approval_id
            )

            return record

    async def get(
        self,
        *,
        principal: Principal,
        approval_id: str,
    ) -> ApprovalRecord:

        async with self._lock:

            record = self._records.get(
                approval_id
            )

            if (
                record is None
                or record.tenant_id
                != principal.tenant_id
            ):
                raise HTTPException(
                    status_code=404,
                    detail="Approval not found",
                )

            self._expire_if_needed(
                record
            )

            require_approval_read(
                principal,
                record,
            )

            return record

    async def list_records(
        self,
        *,
        principal: Principal,
        status: ApprovalStatus | None = None,
        limit: int = 50,
    ) -> list[ApprovalRecord]:

        require_permission(
            principal,
            Permission.PROCUREMENT_READ,
            None,
        )

        async with self._lock:

            records = []

            for record in self._records.values():

                if (
                    record.tenant_id
                    != principal.tenant_id
                ):
                    continue

                self._expire_if_needed(
                    record
                )

                if (
                    status is not None
                    and record.status != status
                ):
                    continue

                allowed = (
                    principal.allowed_warehouse_ids
                )

                if (
                    record.warehouse_id is not None
                    and allowed is not None
                    and record.warehouse_id
                    not in allowed
                ):
                    continue

                if (
                    record.requester_id
                    != principal.principal_id
                ):

                    decision = (
                        permission_engine.evaluate(
                            principal,
                            ACTION_PERMISSIONS[
                                record.action_type
                            ],
                            ResourceContext(
                                tenant_id=principal.tenant_id,
                                warehouse_id=(
                                    record.warehouse_id
                                ),
                            ),
                        )
                    )

                    if not decision.allowed:
                        continue

                records.append(record)

            records.sort(
                key=lambda item: item.created_at,
                reverse=True,
            )

            return records[:limit]

    async def decide(
        self,
        *,
        principal: Principal,
        approval_id: str,
        payload: ApprovalDecision,
        approve: bool,
    ) -> ApprovalRecord:

        async with self._lock:

            record = self._records.get(
                approval_id
            )

            if (
                record is None
                or record.tenant_id
                != principal.tenant_id
            ):
                raise HTTPException(
                    status_code=404,
                    detail="Approval not found",
                )

            self._expire_if_needed(
                record
            )

            require_approval_decision(
                principal,
                record,
            )

            if (
                record.version
                != payload.expected_version
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Approval version conflict",
                )

            if record.status != ApprovalStatus.PENDING:
                raise HTTPException(
                    status_code=409,
                    detail="Approval is not pending",
                )

            record.status = (
                ApprovalStatus.APPROVED
                if approve
                else ApprovalStatus.REJECTED
            )

            record.approver_id = (
                principal.principal_id
            )

            record.decided_at = utc_now()

            record.version += 1

            self._append_event(
                record,
                (
                    ApprovalEventType.APPROVED
                    if approve
                    else ApprovalEventType.REJECTED
                ),
                principal.principal_id,
                payload.reason,
            )

            return record

    async def cancel(
        self,
        *,
        principal: Principal,
        approval_id: str,
        payload: ApprovalCancelRequest,
    ) -> ApprovalRecord:

        async with self._lock:

            record = self._records.get(
                approval_id
            )

            if (
                record is None
                or record.tenant_id
                != principal.tenant_id
            ):
                raise HTTPException(
                    status_code=404,
                    detail="Approval not found",
                )

            self._expire_if_needed(
                record
            )

            if (
                record.requester_id
                != principal.principal_id
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Only requester can cancel",
                )

            require_approval_read(
                principal,
                record,
            )

            if (
                record.version
                != payload.expected_version
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Approval version conflict",
                )

            if record.status != ApprovalStatus.PENDING:
                raise HTTPException(
                    status_code=409,
                    detail="Approval is not pending",
                )

            record.status = ApprovalStatus.CANCELLED

            record.cancelled_at = utc_now()

            record.version += 1

            self._append_event(
                record,
                ApprovalEventType.CANCELLED,
                principal.principal_id,
                payload.reason,
            )

            return record


approval_store = ApprovalStore()


# ============================================================
# APPROVAL SERVICE
# ============================================================

class ApprovalService:

    def __init__(
        self,
        store: ApprovalStore,
    ):
        self.store = store

    async def create(
        self,
        *,
        principal: Principal,
        payload: ApprovalCreate,
    ) -> ApprovalRecord:

        return await self.store.create(
            principal=principal,
            payload=payload,
        )

    async def approve(
        self,
        *,
        principal: Principal,
        approval_id: str,
        payload: ApprovalDecision,
    ) -> ApprovalRecord:

        return await self.store.decide(
            principal=principal,
            approval_id=approval_id,
            payload=payload,
            approve=True,
        )

    async def reject(
        self,
        *,
        principal: Principal,
        approval_id: str,
        payload: ApprovalDecision,
    ) -> ApprovalRecord:

        return await self.store.decide(
            principal=principal,
            approval_id=approval_id,
            payload=payload,
            approve=False,
        )


approval_service = ApprovalService(
    approval_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix="/api/v1/approvals",
    tags=["Human Approvals"],
)


@router.post(
    "",
    response_model=ApprovalResponse,
    status_code=201,
)
async def create_approval(
    payload: ApprovalCreate,
    principal: CurrentPrincipal,
):

    record = await approval_service.create(
        principal=principal,
        payload=payload,
    )

    return to_response(record)


@router.get(
    "",
    response_model=list[ApprovalResponse],
)
async def list_approvals(
    principal: CurrentPrincipal,
    status: ApprovalStatus | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):

    records = await approval_store.list_records(
        principal=principal,
        status=status,
        limit=limit,
    )

    return [
        to_response(record)
        for record in records
    ]


@router.get(
    "/{approval_id}",
    response_model=ApprovalDetailResponse,
)
async def get_approval(
    approval_id: str,
    principal: CurrentPrincipal,
):

    record = await approval_store.get(
        principal=principal,
        approval_id=approval_id,
    )

    return to_detail_response(
        record
    )


@router.post(
    "/{approval_id}/approve",
    response_model=ApprovalResponse,
)
async def approve_request(
    approval_id: str,
    payload: ApprovalDecision,
    principal: CurrentPrincipal,
):

    record = await approval_service.approve(
        principal=principal,
        approval_id=approval_id,
        payload=payload,
    )

    return to_response(record)


@router.post(
    "/{approval_id}/reject",
    response_model=ApprovalResponse,
)
async def reject_request(
    approval_id: str,
    payload: ApprovalDecision,
    principal: CurrentPrincipal,
):

    record = await approval_service.reject(
        principal=principal,
        approval_id=approval_id,
        payload=payload,
    )

    return to_response(record)


@router.post(
    "/{approval_id}/cancel",
    response_model=ApprovalResponse,
)
async def cancel_request(
    approval_id: str,
    payload: ApprovalCancelRequest,
    principal: CurrentPrincipal,
):

    record = await approval_store.cancel(
        principal=principal,
        approval_id=approval_id,
        payload=payload,
    )

    return to_response(record)


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "ApprovalActionType",
    "ApprovalStatus",
    "ApprovalPriority",
    "ApprovalEventType",
    "ApprovalCreate",
    "ApprovalDecision",
    "ApprovalCancelRequest",
    "ApprovalResponse",
    "ApprovalDetailResponse",
    "ApprovalSummary",
    "ApprovalRecord",
    "ApprovalStore",
    "ApprovalService",
    "approval_store",
    "approval_service",
    "router",
]
