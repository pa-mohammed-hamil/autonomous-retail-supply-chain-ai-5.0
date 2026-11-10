from __future__ import annotations

"""Planned module: feedback stream. Implementation pending."""

"""
backend/feedback_stream.py

Autonomous Retail Supply Chain AI 5.0

Tenant-isolated feedback ingestion and streaming.

Python 3.10+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Customer and employee feedback
    - Feedback categories and ratings
    - Trusted-source sentiment updates
    - Idempotent feedback ingestion
    - Feedback lifecycle management
    - Authorized feedback review
    - Minimal WebSocket notifications
    - Tenant-isolated data access
    - Warehouse-aware access checks
    - Bounded in-memory development store

Production requirements:
    - PostgreSQL persistence
    - Durable idempotency
    - Transactional outbox
    - Redis event delivery
    - Source authentication
    - Retention and privacy controls
"""


import asyncio
import hashlib
import secrets

from dataclasses import dataclass, replace
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
)

from backend.permissions import (
    CurrentPrincipal,
    Permission,
    Principal,
    permission_engine,
)

from backend.connection_manager import (
    RealtimeEventType,
    RealtimeMessage,
    connection_manager,
)


# ============================================================
# CONFIGURATION
# ============================================================

MAX_FEEDBACK_PER_TENANT = 10000
MAX_TEXT_LENGTH = 4000
MAX_SOURCE_ID_LENGTH = 128

# Reuse existing permission names.
#
# These operations should eventually have
# dedicated FEEDBACK_READ, FEEDBACK_WRITE,
# and FEEDBACK_MODERATE permissions.

READ_PERMISSION = Permission.ANALYTICS_READ
WRITE_PERMISSION = Permission.ANALYTICS_READ
MODERATE_PERMISSION = Permission.INCIDENT_WRITE


# ============================================================
# ENUMS
# ============================================================

class FeedbackSource(str, Enum):
    CUSTOMER = "customer"
    EMPLOYEE = "employee"
    SUPPLIER = "supplier"
    PARTNER = "partner"


class FeedbackCategory(str, Enum):
    PRODUCT_QUALITY = "product_quality"
    DELIVERY = "delivery"
    INVENTORY = "inventory"
    CUSTOMER_SERVICE = "customer_service"
    SUPPLIER = "supplier"
    WAREHOUSE = "warehouse"
    PRICING = "pricing"
    OTHER = "other"


class SentimentLabel(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    UNKNOWN = "unknown"


class FeedbackStatus(str, Enum):
    NEW = "new"
    REVIEWING = "reviewing"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class FeedbackEventType(str, Enum):
    CREATED = "feedback_created"
    SENTIMENT_UPDATED = "sentiment_updated"
    STATUS_UPDATED = "feedback_status_updated"
    ESCALATION_SUGGESTED = "escalation_suggested"


# ============================================================
# REQUEST / RESPONSE SCHEMAS
# ============================================================

class FeedbackCreate(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    source: FeedbackSource
    category: FeedbackCategory

    text: str = Field(
        min_length=3,
        max_length=MAX_TEXT_LENGTH,
    )

    rating: int | None = Field(
        default=None,
        ge=1,
        le=5,
    )

    product_id: str | None = Field(
        default=None,
        max_length=128,
    )

    warehouse_id: str | None = Field(
        default=None,
        max_length=128,
    )

    order_id: str | None = Field(
        default=None,
        max_length=128,
    )

    source_event_id: str = Field(
        min_length=8,
        max_length=MAX_SOURCE_ID_LENGTH,
    )


class SentimentUpdate(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    sentiment: SentimentLabel

    confidence: float = Field(
        ge=0,
        le=1,
        allow_inf_nan=False,
    )

    model_version: str = Field(
        min_length=1,
        max_length=128,
    )


class FeedbackResponse(BaseModel):

    feedback_id: str

    source: FeedbackSource
    category: FeedbackCategory

    text: str
    rating: int | None

    product_id: str | None
    warehouse_id: str | None
    order_id: str | None

    sentiment: SentimentLabel
    sentiment_confidence: float | None

    status: FeedbackStatus

    created_at: datetime
    updated_at: datetime

    reviewed_by: str | None
    model_version: str | None


class FeedbackSummary(BaseModel):

    total: int

    positive: int
    neutral: int
    negative: int
    unknown: int

    average_rating: float | None

    unresolved: int


# ============================================================
# INTERNAL RECORD
# ============================================================

@dataclass(frozen=True)
class FeedbackRecord:

    feedback_id: str
    tenant_id: str
    submitted_by: str

    source: FeedbackSource
    category: FeedbackCategory

    text: str
    rating: int | None

    product_id: str | None
    warehouse_id: str | None
    order_id: str | None

    source_event_id: str
    payload_fingerprint: str

    sentiment: SentimentLabel
    sentiment_confidence: float | None

    model_version: str | None

    status: FeedbackStatus

    created_at: datetime
    updated_at: datetime

    reviewed_by: str | None = None


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_response(
    record: FeedbackRecord,
) -> FeedbackResponse:

    return FeedbackResponse(
        feedback_id=record.feedback_id,
        source=record.source,
        category=record.category,
        text=record.text,
        rating=record.rating,
        product_id=record.product_id,
        warehouse_id=record.warehouse_id,
        order_id=record.order_id,
        sentiment=record.sentiment,
        sentiment_confidence=(
            record.sentiment_confidence
        ),
        status=record.status,
        created_at=record.created_at,
        updated_at=record.updated_at,
        reviewed_by=record.reviewed_by,
        model_version=record.model_version,
    )


def fingerprint_payload(
    payload: FeedbackCreate,
) -> str:

    encoded = payload.model_dump_json(
        exclude={"source_event_id"}
    ).encode("utf-8")

    return hashlib.sha256(
        encoded
    ).hexdigest()


# ============================================================
# AUTHORIZATION
# ============================================================

def require_feedback_access(
    principal: Principal,
    record: FeedbackRecord,
    *,
    permission: Permission = READ_PERMISSION,
) -> None:

    if principal.tenant_id != record.tenant_id:

        raise HTTPException(
            status_code=404,
            detail="Feedback not found",
        )

    decision = permission_engine.evaluate(
        principal,
        permission,
    )

    if not decision.allowed:

        raise HTTPException(
            status_code=403,
            detail="Feedback access denied",
        )

    allowed = principal.allowed_warehouse_ids

    if (
        record.warehouse_id is not None
        and allowed is not None
        and record.warehouse_id not in allowed
    ):

        raise HTTPException(
            status_code=403,
            detail="Warehouse access denied",
        )


def require_warehouse_scope(
    principal: Principal,
    warehouse_id: str | None,
) -> None:

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


# ============================================================
# DEVELOPMENT STORE
# ============================================================

class FeedbackStore:

    def __init__(self):

        self._records: dict[
            str, FeedbackRecord
        ] = {}

        self._idempotency: dict[
            tuple[str, str], str
        ] = {}

        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        tenant_id: str,
        submitted_by: str,
        payload: FeedbackCreate,
    ) -> tuple[FeedbackRecord, bool]:

        key = (
            tenant_id,
            payload.source_event_id,
        )

        fingerprint = fingerprint_payload(
            payload
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
                        detail=(
                            "Idempotency key reused "
                            "with different content"
                        ),
                    )

                return existing, False

            tenant_count = sum(
                record.tenant_id == tenant_id
                for record in self._records.values()
            )

            if tenant_count >= MAX_FEEDBACK_PER_TENANT:

                raise HTTPException(
                    status_code=503,
                    detail="Feedback capacity reached",
                )

            now = utc_now()

            record = FeedbackRecord(
                feedback_id=secrets.token_urlsafe(20),
                tenant_id=tenant_id,
                submitted_by=submitted_by,
                source=payload.source,
                category=payload.category,
                text=payload.text,
                rating=payload.rating,
                product_id=payload.product_id,
                warehouse_id=payload.warehouse_id,
                order_id=payload.order_id,
                source_event_id=payload.source_event_id,
                payload_fingerprint=fingerprint,
                sentiment=SentimentLabel.UNKNOWN,
                sentiment_confidence=None,
                model_version=None,
                status=FeedbackStatus.NEW,
                created_at=now,
                updated_at=now,
            )

            self._records[
                record.feedback_id
            ] = record

            self._idempotency[key] = (
                record.feedback_id
            )

            return record, True

    async def get(
        self,
        *,
        tenant_id: str,
        feedback_id: str,
    ) -> FeedbackRecord | None:

        async with self._lock:

            record = self._records.get(
                feedback_id
            )

            if (
                record is None
                or record.tenant_id != tenant_id
            ):
                return None

            return record

    async def list_records(
        self,
        *,
        tenant_id: str,
        status: FeedbackStatus | None = None,
        limit: int = 50,
    ) -> list[FeedbackRecord]:

        async with self._lock:

            records = [
                record
                for record in self._records.values()
                if (
                    record.tenant_id == tenant_id
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

        return records[:limit]

    async def update_sentiment(
        self,
        *,
        tenant_id: str,
        feedback_id: str,
        payload: SentimentUpdate,
    ) -> FeedbackRecord | None:

        async with self._lock:

            record = self._records.get(
                feedback_id
            )

            if (
                record is None
                or record.tenant_id != tenant_id
            ):
                return None

            updated = replace(
                record,
                sentiment=payload.sentiment,
                sentiment_confidence=(
                    payload.confidence
                ),
                model_version=payload.model_version,
                updated_at=utc_now(),
            )

            self._records[
                feedback_id
            ] = updated

            return updated

    async def update_status(
        self,
        *,
        tenant_id: str,
        feedback_id: str,
        status: FeedbackStatus,
        reviewed_by: str,
    ) -> FeedbackRecord | None:

        async with self._lock:

            record = self._records.get(
                feedback_id
            )

            if (
                record is None
                or record.tenant_id != tenant_id
            ):
                return None

            updated = replace(
                record,
                status=status,
                reviewed_by=reviewed_by,
                updated_at=utc_now(),
            )

            self._records[
                feedback_id
            ] = updated

            return updated

    async def summary(
        self,
        *,
        tenant_id: str,
        allowed_warehouse_ids: (
            frozenset[str] | set[str] | None
        ) = None,
    ) -> FeedbackSummary:

        async with self._lock:

            records = [
                record
                for record in self._records.values()
                if (
                    record.tenant_id == tenant_id
                    and (
                        allowed_warehouse_ids is None
                        or (
                            record.warehouse_id
                            is not None
                            and record.warehouse_id
                            in allowed_warehouse_ids
                        )
                    )
                )
            ]

        ratings = [
            record.rating
            for record in records
            if record.rating is not None
        ]

        return FeedbackSummary(
            total=len(records),
            positive=sum(
                record.sentiment
                == SentimentLabel.POSITIVE
                for record in records
            ),
            neutral=sum(
                record.sentiment
                == SentimentLabel.NEUTRAL
                for record in records
            ),
            negative=sum(
                record.sentiment
                == SentimentLabel.NEGATIVE
                for record in records
            ),
            unknown=sum(
                record.sentiment
                == SentimentLabel.UNKNOWN
                for record in records
            ),
            average_rating=(
                round(
                    sum(ratings) / len(ratings),
                    2,
                )
                if ratings
                else None
            ),
            unresolved=sum(
                record.status not in {
                    FeedbackStatus.RESOLVED,
                    FeedbackStatus.DISMISSED,
                }
                for record in records
            ),
        )


feedback_store = FeedbackStore()


# ============================================================
# REALTIME NOTIFICATION
# ============================================================

async def publish_feedback_event(
    record: FeedbackRecord,
    event_type: FeedbackEventType,
) -> int:
    """
    Broadcast minimal metadata only when
    there is no warehouse-specific resource.

    Warehouse-specific feedback requires
    resource-aware subscriptions.

    Do not broadcast feedback text, customer
    identifiers, or order details.
    """

    if record.warehouse_id is not None:
        return 0

    return await connection_manager.broadcast_to_tenant(
        tenant_id=record.tenant_id,
        required_permission=READ_PERMISSION,
        message=RealtimeMessage(
            event=RealtimeEventType.NOTIFICATION,
            data={
                "kind": "feedback",
                "event": event_type.value,
                "feedback_id": record.feedback_id,
                "category": record.category.value,
                "status": record.status.value,
            },
        ),
    )


# ============================================================
# SERVICE
# ============================================================

class FeedbackStreamService:

    def __init__(
        self,
        store: FeedbackStore,
    ):
        self.store = store

    async def submit(
        self,
        *,
        principal: Principal,
        payload: FeedbackCreate,
    ) -> FeedbackRecord:

        permission_engine.require(
            principal,
            WRITE_PERMISSION,
        )

        require_warehouse_scope(
            principal,
            payload.warehouse_id,
        )

        record, created = await self.store.create(
            tenant_id=principal.tenant_id,
            submitted_by=principal.principal_id,
            payload=payload,
        )

        if created:
            await publish_feedback_event(
                record,
                FeedbackEventType.CREATED,
            )

        return record

    async def set_sentiment(
        self,
        *,
        principal: Principal,
        feedback_id: str,
        payload: SentimentUpdate,
    ) -> FeedbackRecord:

        permission_engine.require(
            principal,
            MODERATE_PERMISSION,
        )

        record = await self.store.get(
            tenant_id=principal.tenant_id,
            feedback_id=feedback_id,
        )

        if record is None:

            raise HTTPException(
                status_code=404,
                detail="Feedback not found",
            )

        require_feedback_access(
            principal,
            record,
        )

        updated = await self.store.update_sentiment(
            tenant_id=principal.tenant_id,
            feedback_id=feedback_id,
            payload=payload,
        )

        assert updated is not None

        await publish_feedback_event(
            updated,
            FeedbackEventType.SENTIMENT_UPDATED,
        )

        return updated

    async def set_status(
        self,
        *,
        principal: Principal,
        feedback_id: str,
        target: FeedbackStatus,
    ) -> FeedbackRecord:

        permission_engine.require(
            principal,
            MODERATE_PERMISSION,
        )

        record = await self.store.get(
            tenant_id=principal.tenant_id,
            feedback_id=feedback_id,
        )

        if record is None:

            raise HTTPException(
                status_code=404,
                detail="Feedback not found",
            )

        require_feedback_access(
            principal,
            record,
        )

        updated = await self.store.update_status(
            tenant_id=principal.tenant_id,
            feedback_id=feedback_id,
            status=target,
            reviewed_by=principal.principal_id,
        )

        assert updated is not None

        await publish_feedback_event(
            updated,
            FeedbackEventType.STATUS_UPDATED,
        )

        return updated


feedback_stream = FeedbackStreamService(
    feedback_store
)


# ============================================================
# API ROUTER
# ============================================================

router = APIRouter(
    prefix="/api/v1/feedback-stream",
    tags=["Feedback Stream"],
)


@router.post(
    "",
    response_model=FeedbackResponse,
)
async def submit_feedback(
    payload: FeedbackCreate,
    principal: CurrentPrincipal,
):

    record = await feedback_stream.submit(
        principal=principal,
        payload=payload,
    )

    return to_response(record)


@router.get(
    "",
    response_model=list[FeedbackResponse],
)
async def list_feedback(
    principal: CurrentPrincipal,
    status: FeedbackStatus | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
    ),
):

    permission_engine.require(
        principal,
        READ_PERMISSION,
    )

    records = await feedback_store.list_records(
        tenant_id=principal.tenant_id,
        status=status,
        limit=limit,
    )

    visible = []

    for record in records:

        try:
            require_feedback_access(
                principal,
                record,
            )

        except HTTPException:
            continue

        visible.append(
            to_response(record)
        )

    return visible


@router.get(
    "/summary",
    response_model=FeedbackSummary,
)
async def get_feedback_summary(
    principal: CurrentPrincipal,
):

    permission_engine.require(
        principal,
        READ_PERMISSION,
    )

    return await feedback_store.summary(
        tenant_id=principal.tenant_id,
        allowed_warehouse_ids=(
            principal.allowed_warehouse_ids
        ),
    )


@router.get(
    "/{feedback_id}",
    response_model=FeedbackResponse,
)
async def get_feedback(
    feedback_id: str,
    principal: CurrentPrincipal,
):

    record = await feedback_store.get(
        tenant_id=principal.tenant_id,
        feedback_id=feedback_id,
    )

    if record is None:

        raise HTTPException(
            status_code=404,
            detail="Feedback not found",
        )

    require_feedback_access(
        principal,
        record,
    )

    return to_response(record)


@router.post(
    "/{feedback_id}/sentiment",
    response_model=FeedbackResponse,
)
async def update_feedback_sentiment(
    feedback_id: str,
    payload: SentimentUpdate,
    principal: CurrentPrincipal,
):

    record = await feedback_stream.set_sentiment(
        principal=principal,
        feedback_id=feedback_id,
        payload=payload,
    )

    return to_response(record)


@router.post(
    "/{feedback_id}/status/{target}",
    response_model=FeedbackResponse,
)
async def update_feedback_status(
    feedback_id: str,
    target: FeedbackStatus,
    principal: CurrentPrincipal,
):

    record = await feedback_stream.set_status(
        principal=principal,
        feedback_id=feedback_id,
        target=target,
    )

    return to_response(record)
