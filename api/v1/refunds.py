from __future__ import annotations

"""Planned module: refunds. Implementation pending."""

"""
backend/refunds.py

Autonomous Retail Supply Chain AI 5.0
Refund Management API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Customer and supplier refund requests
    - Partial and full refund amounts
    - Eligibility review
    - Human approval and rejection
    - Separation of duties
    - Payment processing handoff
    - Provider-confirmed settlement
    - Failed refund handling
    - Cancellation
    - Idempotent creation
    - Optimistic concurrency
    - Tenant and warehouse authorization
    - Refund analytics

IMPORTANT:
    This is a demonstration implementation.
    It does not transfer money or call a payment gateway.
    Settlement confirmation is a privileged administrative
    action in this prototype, not a trusted provider webhook.

Production requires:
    - Authoritative payment/transaction verification
    - Dedicated refund permissions
    - Signed payment-provider webhooks
    - Durable database transactions
    - Financial ledger reconciliation
    - Idempotent gateway operations
    - Fraud controls and audit trails
"""


import asyncio
import hashlib
import json
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


API_PREFIX = "/api/v1/refunds"

MAX_REFUNDS_PER_TENANT = 50000
MAX_EVENTS_PER_REFUND = 100
MAX_IDEMPOTENCY_KEYS = 100000
MAX_LIST_LIMIT = 200

MONEY_QUANTUM = Decimal("0.01")


# ============================================================
# ENUMS
# ============================================================

class RefundType(str, Enum):
    CUSTOMER = "customer"
    SUPPLIER = "supplier"


class RefundReason(str, Enum):
    DAMAGED = "damaged"
    DEFECTIVE = "defective"
    WRONG_ITEM = "wrong_item"
    NOT_DELIVERED = "not_delivered"
    ORDER_CANCELLED = "order_cancelled"
    OVERPAYMENT = "overpayment"
    PRICE_ADJUSTMENT = "price_adjustment"
    SUPPLIER_RETURN = "supplier_return"
    OTHER = "other"


class RefundStatus(str, Enum):
    REQUESTED = "requested"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RefundMethod(str, Enum):
    ORIGINAL_PAYMENT = "original_payment"
    BANK_TRANSFER = "bank_transfer"
    STORE_CREDIT = "store_credit"


class RefundEventType(str, Enum):
    CREATED = "created"
    REVIEW_STARTED = "review_started"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROCESSING_STARTED = "processing_started"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ============================================================
# REQUEST MODELS
# ============================================================

class RefundCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    refund_type: RefundType

    order_id: str = Field(
        min_length=1,
        max_length=128,
    )

    payment_reference: str = Field(
        min_length=1,
        max_length=200,
    )

    recipient_id: str = Field(
        min_length=1,
        max_length=128,
    )

    reason: RefundReason

    description: str = Field(
        min_length=5,
        max_length=2000,
    )

    requested_amount: Decimal = Field(
        gt=0,
        max_digits=16,
        decimal_places=2,
    )

    currency: str = Field(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    )

    refund_method: RefundMethod = (
        RefundMethod.ORIGINAL_PAYMENT
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )


class RefundVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class RefundReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    review_reference: str = Field(
        min_length=3,
        max_length=200,
    )


class RefundDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    approved_amount: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=16,
        decimal_places=2,
    )

    notes: str = Field(
        min_length=5,
        max_length=1000,
    )


class RefundProcessingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    gateway_request_reference: str = Field(
        min_length=5,
        max_length=200,
    )


class RefundSettlementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    provider_transaction_id: str = Field(
        min_length=5,
        max_length=200,
    )

    settled_amount: Decimal = Field(
        gt=0,
        max_digits=16,
        decimal_places=2,
    )


class RefundFailureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    error_code: str = Field(
        min_length=2,
        max_length=100,
    )

    reason: str = Field(
        min_length=5,
        max_length=1000,
    )


class RefundCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    reason: str = Field(
        min_length=5,
        max_length=500,
    )


# ============================================================
# RESPONSE MODELS
# ============================================================

class RefundEventResponse(BaseModel):
    event_id: str
    event_type: RefundEventType
    actor_id: str
    details: str | None
    created_at: datetime


class RefundResponse(BaseModel):
    refund_id: str

    warehouse_id: str
    refund_type: RefundType

    order_id: str
    payment_reference: str
    recipient_id: str

    reason: RefundReason
    refund_method: RefundMethod

    requested_amount: Decimal
    approved_amount: Decimal | None
    settled_amount: Decimal | None

    currency: str
    status: RefundStatus

    version: int

    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class RefundDetailResponse(RefundResponse):
    description: str
    created_by: str

    review_reference: str | None
    reviewed_by: str | None
    approved_by: str | None

    decision_notes: str | None
    gateway_request_reference: str | None
    provider_transaction_id: str | None

    failure_code: str | None
    failure_reason: str | None

    events: list[RefundEventResponse]


class RefundAnalyticsResponse(BaseModel):
    total_refunds: int

    requested: int
    under_review: int
    approved: int
    rejected: int
    processing: int
    completed: int
    failed: int
    cancelled: int

    total_requested_amount: Decimal
    total_approved_amount: Decimal
    total_settled_amount: Decimal

    customer_refunds: int
    supplier_refunds: int


# ============================================================
# INTERNAL RECORD
# ============================================================

@dataclass
class RefundRecord:
    refund_id: str
    tenant_id: str
    warehouse_id: str

    refund_type: RefundType
    order_id: str
    payment_reference: str
    recipient_id: str

    reason: RefundReason
    description: str
    refund_method: RefundMethod

    requested_amount: Decimal
    currency: str
    created_by: str

    status: RefundStatus = RefundStatus.REQUESTED

    approved_amount: Decimal | None = None
    settled_amount: Decimal | None = None

    review_reference: str | None = None
    reviewed_by: str | None = None
    approved_by: str | None = None

    decision_notes: str | None = None
    gateway_request_reference: str | None = None
    provider_transaction_id: str | None = None

    failure_code: str | None = None
    failure_reason: str | None = None

    events: list[RefundEventResponse] = field(
        default_factory=list
    )

    version: int = 1

    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    completed_at: datetime | None = None


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


def fingerprint(payload: RefundCreate) -> str:

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


def require_refund_access(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool,
) -> None:
    """
    Temporary permission mapping.

    Production should define separate permissions:
        REFUND_READ
        REFUND_CREATE
        REFUND_REVIEW
        REFUND_APPROVE
        REFUND_PROCESS
        REFUND_SETTLE
        REFUND_CANCEL
    """

    permission = (
        Permission.SYSTEM_CONFIGURE
        if write
        else Permission.FINANCE_READ
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
            detail="Refund access denied",
        )


def to_response(
    record: RefundRecord,
) -> RefundResponse:

    return RefundResponse(
        refund_id=record.refund_id,
        warehouse_id=record.warehouse_id,
        refund_type=record.refund_type,
        order_id=record.order_id,
        payment_reference=record.payment_reference,
        recipient_id=record.recipient_id,
        reason=record.reason,
        refund_method=record.refund_method,
        requested_amount=record.requested_amount,
        approved_amount=record.approved_amount,
        settled_amount=record.settled_amount,
        currency=record.currency,
        status=record.status,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
    )


def to_detail(
    record: RefundRecord,
) -> RefundDetailResponse:

    return RefundDetailResponse(
        **to_response(record).model_dump(),
        description=record.description,
        created_by=record.created_by,
        review_reference=record.review_reference,
        reviewed_by=record.reviewed_by,
        approved_by=record.approved_by,
        decision_notes=record.decision_notes,
        gateway_request_reference=(
            record.gateway_request_reference
        ),
        provider_transaction_id=(
            record.provider_transaction_id
        ),
        failure_code=record.failure_code,
        failure_reason=record.failure_reason,
        events=list(record.events),
    )


# ============================================================
# REFUND STORE
# ============================================================

class RefundStore:

    def __init__(self):

        self._refunds: dict[str, RefundRecord] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    def _get(
        self,
        principal: Principal,
        refund_id: str,
        *,
        write: bool,
    ) -> RefundRecord:

        record = self._refunds.get(refund_id)

        if (
            record is None
            or record.tenant_id != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Refund not found",
            )

        require_refund_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    @staticmethod
    def _check_version(
        record: RefundRecord,
        expected_version: int,
    ) -> None:

        if record.version != expected_version:
            raise HTTPException(
                status_code=409,
                detail="Refund version conflict",
            )

    @staticmethod
    def _require_status(
        record: RefundRecord,
        statuses: set[RefundStatus],
    ) -> None:

        if record.status not in statuses:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Operation not permitted "
                    f"in status {record.status.value}"
                ),
            )

    @staticmethod
    def _event(
        record: RefundRecord,
        event_type: RefundEventType,
        actor_id: str,
        details: str | None = None,
    ) -> None:

        if len(record.events) >= MAX_EVENTS_PER_REFUND:
            raise HTTPException(
                status_code=503,
                detail="Refund event capacity reached",
            )

        record.events.append(
            RefundEventResponse(
                event_id=secrets.token_urlsafe(16),
                event_type=event_type,
                actor_id=actor_id,
                details=details,
                created_at=utc_now(),
            )
        )

    @staticmethod
    def _touch(record: RefundRecord) -> None:
        record.version += 1
        record.updated_at = utc_now()

    async def create(
        self,
        principal: Principal,
        payload: RefundCreate,
    ) -> RefundResponse:

        require_refund_access(
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

            if previous:

                previous_hash, refund_id = previous

                if previous_hash != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return to_response(
                    self._get(
                        principal,
                        refund_id,
                        write=False,
                    )
                )

            tenant_count = sum(
                record.tenant_id == principal.tenant_id
                for record in self._refunds.values()
            )

            if (
                tenant_count >= MAX_REFUNDS_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Refund capacity reached",
                )

            record = RefundRecord(
                refund_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                refund_type=payload.refund_type,
                order_id=payload.order_id,
                payment_reference=payload.payment_reference,
                recipient_id=payload.recipient_id,
                reason=payload.reason,
                description=payload.description,
                refund_method=payload.refund_method,
                requested_amount=money(
                    payload.requested_amount
                ),
                currency=payload.currency,
                created_by=principal.principal_id,
            )

            self._event(
                record,
                RefundEventType.CREATED,
                principal.principal_id,
            )

            self._refunds[record.refund_id] = record

            self._idempotency[key] = (
                request_hash,
                record.refund_id,
            )

            return to_response(record)

    async def get(
        self,
        principal: Principal,
        refund_id: str,
    ) -> RefundDetailResponse:

        async with self._lock:

            return to_detail(
                self._get(
                    principal,
                    refund_id,
                    write=False,
                )
            )

    async def list_refunds(
        self,
        principal: Principal,
        warehouse_id: str | None,
        status: RefundStatus | None,
        limit: int,
    ) -> list[RefundResponse]:

        if warehouse_id is not None:
            require_refund_access(
                principal,
                warehouse_id,
                write=False,
            )

        async with self._lock:

            records = sorted(
                (
                    record
                    for record in self._refunds.values()
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
                ),
                key=lambda record: record.created_at,
                reverse=True,
            )

            result = []

            for record in records:

                try:
                    require_refund_access(
                        principal,
                        record.warehouse_id,
                        write=False,
                    )
                except HTTPException:
                    continue

                result.append(to_response(record))

                if len(result) >= limit:
                    break

            return result

    async def start_review(
        self,
        principal: Principal,
        refund_id: str,
        payload: RefundReviewRequest,
    ) -> RefundResponse:

        async with self._lock:

            record = self._get(
                principal,
                refund_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {RefundStatus.REQUESTED},
            )

            if record.created_by == principal.principal_id:
                raise HTTPException(
                    status_code=403,
                    detail="Creator cannot review own refund",
                )

            record.review_reference = (
                payload.review_reference
            )

            record.reviewed_by = principal.principal_id
            record.status = RefundStatus.UNDER_REVIEW

            self._event(
                record,
                RefundEventType.REVIEW_STARTED,
                principal.principal_id,
                payload.review_reference,
            )

            self._touch(record)

            return to_response(record)

    async def decide(
        self,
        principal: Principal,
        refund_id: str,
        payload: RefundDecisionRequest,
        *,
        approve: bool,
    ) -> RefundResponse:

        async with self._lock:

            record = self._get(
                principal,
                refund_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {RefundStatus.UNDER_REVIEW},
            )

            if principal.principal_id in {
                record.created_by,
                record.reviewed_by,
            }:
                raise HTTPException(
                    status_code=403,
                    detail="Independent approver required",
                )

            if approve:

                if payload.approved_amount is None:
                    raise HTTPException(
                        status_code=422,
                        detail="Approved amount required",
                    )

                amount = money(payload.approved_amount)

                if amount > record.requested_amount:
                    raise HTTPException(
                        status_code=409,
                        detail="Approved amount exceeds request",
                    )

                record.approved_amount = amount
                record.approved_by = principal.principal_id
                record.status = RefundStatus.APPROVED

                event_type = RefundEventType.APPROVED

            else:

                if payload.approved_amount is not None:
                    raise HTTPException(
                        status_code=422,
                        detail="Rejected refund cannot have an approved amount",
                    )

                record.status = RefundStatus.REJECTED
                event_type = RefundEventType.REJECTED

            record.decision_notes = payload.notes

            self._event(
                record,
                event_type,
                principal.principal_id,
                payload.notes,
            )

            self._touch(record)

            return to_response(record)

    async def start_processing(
        self,
        principal: Principal,
        refund_id: str,
        payload: RefundProcessingRequest,
    ) -> RefundResponse:

        async with self._lock:

            record = self._get(
                principal,
                refund_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {RefundStatus.APPROVED},
            )

            record.gateway_request_reference = (
                payload.gateway_request_reference
            )

            record.status = RefundStatus.PROCESSING

            self._event(
                record,
                RefundEventType.PROCESSING_STARTED,
                principal.principal_id,
                payload.gateway_request_reference,
            )

            self._touch(record)

            return to_response(record)

    async def confirm_settlement(
        self,
        principal: Principal,
        refund_id: str,
        payload: RefundSettlementRequest,
    ) -> RefundResponse:

        async with self._lock:

            record = self._get(
                principal,
                refund_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {RefundStatus.PROCESSING},
            )

            if (
                money(payload.settled_amount)
                != record.approved_amount
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Settlement amount does not match approval",
                )

            record.settled_amount = money(
                payload.settled_amount
            )

            record.provider_transaction_id = (
                payload.provider_transaction_id
            )

            record.status = RefundStatus.COMPLETED
            record.completed_at = utc_now()

            self._event(
                record,
                RefundEventType.COMPLETED,
                principal.principal_id,
                payload.provider_transaction_id,
            )

            self._touch(record)

            return to_response(record)

    async def fail(
        self,
        principal: Principal,
        refund_id: str,
        payload: RefundFailureRequest,
    ) -> RefundResponse:

        async with self._lock:

            record = self._get(
                principal,
                refund_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {RefundStatus.PROCESSING},
            )

            record.status = RefundStatus.FAILED
            record.failure_code = payload.error_code
            record.failure_reason = payload.reason

            self._event(
                record,
                RefundEventType.FAILED,
                principal.principal_id,
                payload.reason,
            )

            self._touch(record)

            return to_response(record)

    async def cancel(
        self,
        principal: Principal,
        refund_id: str,
        payload: RefundCancelRequest,
    ) -> RefundResponse:

        async with self._lock:

            record = self._get(
                principal,
                refund_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {
                    RefundStatus.REQUESTED,
                    RefundStatus.UNDER_REVIEW,
                    RefundStatus.APPROVED,
                },
            )

            record.status = RefundStatus.CANCELLED

            self._event(
                record,
                RefundEventType.CANCELLED,
                principal.principal_id,
                payload.reason,
            )

            self._touch(record)

            return to_response(record)

    async def analytics(
        self,
        principal: Principal,
        warehouse_id: str,
    ) -> RefundAnalyticsResponse:

        require_refund_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._refunds.values()
                if (
                    record.tenant_id == principal.tenant_id
                    and record.warehouse_id == warehouse_id
                )
            ]

            statuses = [
                record.status
                for record in records
            ]

            return RefundAnalyticsResponse(
                total_refunds=len(records),
                requested=statuses.count(
                    RefundStatus.REQUESTED
                ),
                under_review=statuses.count(
                    RefundStatus.UNDER_REVIEW
                ),
                approved=statuses.count(
                    RefundStatus.APPROVED
                ),
                rejected=statuses.count(
                    RefundStatus.REJECTED
                ),
                processing=statuses.count(
                    RefundStatus.PROCESSING
                ),
                completed=statuses.count(
                    RefundStatus.COMPLETED
                ),
                failed=statuses.count(
                    RefundStatus.FAILED
                ),
                cancelled=statuses.count(
                    RefundStatus.CANCELLED
                ),
                total_requested_amount=money(
                    sum(
                        (
                            record.requested_amount
                            for record in records
                        ),
                        Decimal("0"),
                    )
                ),
                total_approved_amount=money(
                    sum(
                        (
                            record.approved_amount or Decimal("0")
                            for record in records
                        ),
                        Decimal("0"),
                    )
                ),
                total_settled_amount=money(
                    sum(
                        (
                            record.settled_amount or Decimal("0")
                            for record in records
                        ),
                        Decimal("0"),
                    )
                ),
                customer_refunds=sum(
                    record.refund_type == RefundType.CUSTOMER
                    for record in records
                ),
                supplier_refunds=sum(
                    record.refund_type == RefundType.SUPPLIER
                    for record in records
                ),
            )


refund_store = RefundStore()


# ============================================================
# SERVICE
# ============================================================

class RefundService:

    def __init__(self, store: RefundStore):
        self.store = store

    async def create(
        self,
        principal: Principal,
        payload: RefundCreate,
    ) -> RefundResponse:

        return await self.store.create(
            principal,
            payload,
        )


refund_service = RefundService(refund_store)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Refund Management"],
)


@router.post(
    "",
    response_model=RefundResponse,
    status_code=201,
)
async def create_refund(
    payload: RefundCreate,
    principal: CurrentPrincipal,
):
    return await refund_service.create(
        principal,
        payload,
    )


@router.get(
    "",
    response_model=list[RefundResponse],
)
async def list_refunds(
    principal: CurrentPrincipal,
    warehouse_id: str | None = None,
    status: RefundStatus | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await refund_store.list_refunds(
        principal,
        warehouse_id,
        status,
        limit,
    )


@router.get(
    "/analytics/{warehouse_id}",
    response_model=RefundAnalyticsResponse,
)
async def refund_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
):
    return await refund_store.analytics(
        principal,
        warehouse_id,
    )


@router.get(
    "/{refund_id}",
    response_model=RefundDetailResponse,
)
async def get_refund(
    refund_id: str,
    principal: CurrentPrincipal,
):
    return await refund_store.get(
        principal,
        refund_id,
    )


@router.post(
    "/{refund_id}/review",
    response_model=RefundResponse,
)
async def review_refund(
    refund_id: str,
    payload: RefundReviewRequest,
    principal: CurrentPrincipal,
):
    return await refund_store.start_review(
        principal,
        refund_id,
        payload,
    )


@router.post(
    "/{refund_id}/approve",
    response_model=RefundResponse,
)
async def approve_refund(
    refund_id: str,
    payload: RefundDecisionRequest,
    principal: CurrentPrincipal,
):
    return await refund_store.decide(
        principal,
        refund_id,
        payload,
        approve=True,
    )


@router.post(
    "/{refund_id}/reject",
    response_model=RefundResponse,
)
async def reject_refund(
    refund_id: str,
    payload: RefundDecisionRequest,
    principal: CurrentPrincipal,
):
    return await refund_store.decide(
        principal,
        refund_id,
        payload,
        approve=False,
    )


@router.post(
    "/{refund_id}/process",
    response_model=RefundResponse,
)
async def process_refund(
    refund_id: str,
    payload: RefundProcessingRequest,
    principal: CurrentPrincipal,
):
    return await refund_store.start_processing(
        principal,
        refund_id,
        payload,
    )


@router.post(
    "/{refund_id}/settle",
    response_model=RefundResponse,
)
async def settle_refund(
    refund_id: str,
    payload: RefundSettlementRequest,
    principal: CurrentPrincipal,
):
    return await refund_store.confirm_settlement(
        principal,
        refund_id,
        payload,
    )


@router.post(
    "/{refund_id}/fail",
    response_model=RefundResponse,
)
async def fail_refund(
    refund_id: str,
    payload: RefundFailureRequest,
    principal: CurrentPrincipal,
):
    return await refund_store.fail(
        principal,
        refund_id,
        payload,
    )


@router.post(
    "/{refund_id}/cancel",
    response_model=RefundResponse,
)
async def cancel_refund(
    refund_id: str,
    payload: RefundCancelRequest,
    principal: CurrentPrincipal,
):
    return await refund_store.cancel(
        principal,
        refund_id,
        payload,
    )


__all__ = [
    "RefundType",
    "RefundReason",
    "RefundStatus",
    "RefundMethod",
    "RefundEventType",
    "RefundCreate",
    "RefundVersionRequest",
    "RefundReviewRequest",
    "RefundDecisionRequest",
    "RefundProcessingRequest",
    "RefundSettlementRequest",
    "RefundFailureRequest",
    "RefundCancelRequest",
    "RefundEventResponse",
    "RefundResponse",
    "RefundDetailResponse",
    "RefundAnalyticsResponse",
    "RefundStore",
    "RefundService",
    "refund_store",
    "refund_service",
    "router",
]
