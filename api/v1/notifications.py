from __future__ import annotations

"""Planned module: notifications. Implementation pending."""

"""
backend/notifications.py

Autonomous Retail Supply Chain AI 5.0
Central Notification Management API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Tenant-isolated notifications
    - Warehouse-scoped notifications
    - Recipient-specific inboxes
    - Notification categories and priorities
    - In-app, email, SMS, push, and workplace channels
    - Read and acknowledgment tracking
    - Notification delivery state records
    - Idempotent notification creation
    - Optimistic concurrency
    - Notification statistics
    - Expiration and cancellation

IMPORTANT:
    This module records notification intent and state.
    It does not send actual emails, SMS, or push messages.

    External delivery requires authenticated workers,
    verified recipients, and provider adapters.
"""


import asyncio
import hashlib
import json
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


API_PREFIX = "/api/v1/notifications"

MAX_NOTIFICATIONS_PER_TENANT = 100_000
MAX_RECIPIENTS_PER_NOTIFICATION = 100
MAX_IDEMPOTENCY_KEYS = 150_000
MAX_LIST_LIMIT = 200


# ============================================================
# ENUMS
# ============================================================

class NotificationCategory(str, Enum):
    INVENTORY = "inventory"
    LOW_STOCK = "low_stock"
    STOCKOUT = "stockout"
    DEMAND = "demand"
    PROCUREMENT = "procurement"
    SUPPLIER = "supplier"
    WAREHOUSE = "warehouse"
    LOGISTICS = "logistics"
    DELIVERY = "delivery"
    ORDER = "order"
    FINANCE = "finance"
    APPROVAL = "approval"
    INCIDENT = "incident"
    SECURITY = "security"
    AI_AGENT = "ai_agent"
    SYSTEM = "system"
    GENERAL = "general"


class NotificationPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class NotificationChannel(str, Enum):
    IN_APP = "in_app"
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    WORKPLACE = "workplace"


class NotificationStatus(str, Enum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class RecipientStatus(str, Enum):
    UNREAD = "unread"
    READ = "read"
    ACKNOWLEDGED = "acknowledged"


class DeliveryStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"


# ============================================================
# REQUEST MODELS
# ============================================================

class NotificationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str | None = Field(
        default=None,
        max_length=128,
    )

    recipient_ids: list[str] = Field(
        min_length=1,
        max_length=MAX_RECIPIENTS_PER_NOTIFICATION,
    )

    category: NotificationCategory

    priority: NotificationPriority = (
        NotificationPriority.NORMAL
    )

    title: str = Field(
        min_length=3,
        max_length=200,
    )

    message: str = Field(
        min_length=3,
        max_length=4000,
    )

    channels: list[NotificationChannel] = Field(
        default_factory=lambda: [
            NotificationChannel.IN_APP
        ],
        min_length=1,
        max_length=5,
    )

    resource_type: str | None = Field(
        default=None,
        max_length=100,
    )

    resource_id: str | None = Field(
        default=None,
        max_length=128,
    )

    expires_at: datetime | None = None

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_notification(self):

        if len(set(self.recipient_ids)) != len(
            self.recipient_ids
        ):
            raise ValueError(
                "Duplicate recipients are not allowed"
            )

        if any(
            not recipient.strip()
            or len(recipient) > 128
            for recipient in self.recipient_ids
        ):
            raise ValueError(
                "Invalid recipient ID"
            )

        if len(set(self.channels)) != len(
            self.channels
        ):
            raise ValueError(
                "Duplicate channels are not allowed"
            )

        if (
            self.resource_type is None
        ) != (
            self.resource_id is None
        ):
            raise ValueError(
                "Resource type and ID must be provided together"
            )

        if self.expires_at is not None:

            if self.expires_at.tzinfo is None:
                raise ValueError(
                    "Expiration must include timezone"
                )

            if self.expires_at <= datetime.now(
                timezone.utc
            ):
                raise ValueError(
                    "Expiration must be in the future"
                )

        return self


class NotificationVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class NotificationDeliveryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_id: str = Field(
        min_length=1,
        max_length=128,
    )

    channel: NotificationChannel

    status: DeliveryStatus

    expected_version: int = Field(ge=1)

    provider_reference: str | None = Field(
        default=None,
        max_length=300,
    )

    error_code: str | None = Field(
        default=None,
        max_length=100,
    )


# ============================================================
# RESPONSE MODELS
# ============================================================

class NotificationDeliveryResponse(BaseModel):
    recipient_id: str
    channel: NotificationChannel
    status: DeliveryStatus

    provider_reference: str | None
    error_code: str | None

    updated_at: datetime


class NotificationResponse(BaseModel):
    notification_id: str

    warehouse_id: str | None

    category: NotificationCategory
    priority: NotificationPriority

    title: str
    message: str

    channels: list[NotificationChannel]
    recipient_count: int

    resource_type: str | None
    resource_id: str | None

    status: NotificationStatus

    expires_at: datetime | None

    version: int

    created_by: str
    created_at: datetime
    updated_at: datetime


class NotificationInboxResponse(BaseModel):
    notification_id: str

    category: NotificationCategory
    priority: NotificationPriority

    title: str
    message: str

    status: NotificationStatus
    recipient_status: RecipientStatus

    resource_type: str | None
    resource_id: str | None

    created_at: datetime
    read_at: datetime | None
    acknowledged_at: datetime | None


class NotificationDetailResponse(NotificationResponse):
    deliveries: list[NotificationDeliveryResponse]


class NotificationStatistics(BaseModel):
    total_notifications: int
    active_notifications: int
    cancelled_notifications: int
    expired_notifications: int

    critical_notifications: int
    high_priority_notifications: int

    total_recipient_entries: int
    unread_recipient_entries: int
    read_recipient_entries: int
    acknowledged_recipient_entries: int

    pending_delivery_records: int
    queued_delivery_records: int
    sent_delivery_records: int
    delivered_delivery_records: int
    failed_delivery_records: int


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass
class RecipientState:
    recipient_id: str

    status: RecipientStatus = (
        RecipientStatus.UNREAD
    )

    read_at: datetime | None = None
    acknowledged_at: datetime | None = None


@dataclass
class DeliveryRecord:
    recipient_id: str
    channel: NotificationChannel

    status: DeliveryStatus = (
        DeliveryStatus.PENDING
    )

    provider_reference: str | None = None
    error_code: str | None = None

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )


@dataclass
class NotificationRecord:
    notification_id: str
    tenant_id: str

    warehouse_id: str | None

    category: NotificationCategory
    priority: NotificationPriority

    title: str
    message: str

    channels: list[NotificationChannel]

    resource_type: str | None
    resource_id: str | None

    expires_at: datetime | None

    created_by: str

    status: NotificationStatus = (
        NotificationStatus.ACTIVE
    )

    version: int = 1

    recipients: dict[
        str,
        RecipientState,
    ] = field(default_factory=dict)

    deliveries: dict[
        tuple[str, NotificationChannel],
        DeliveryRecord,
    ] = field(default_factory=dict)

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


def request_fingerprint(
    payload: NotificationCreate,
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


def require_notification_access(
    principal: Principal,
    warehouse_id: str | None,
    *,
    write: bool,
) -> None:

    # Placeholder mapping:
    # Dedicated NOTIFICATION_SEND and
    # NOTIFICATION_MANAGE permissions
    # should be introduced.

    permission = (
        Permission.SYSTEM_CONFIGURE
        if write
        else Permission.NOTIFICATION_READ
    )

    if warehouse_id is None:

        if principal.allowed_warehouse_ids is not None:
            raise HTTPException(
                status_code=403,
                detail="Global notification access denied",
            )

    elif (
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
            detail="Notification access denied",
        )


def to_response(
    record: NotificationRecord,
) -> NotificationResponse:

    return NotificationResponse(
        notification_id=record.notification_id,
        warehouse_id=record.warehouse_id,
        category=record.category,
        priority=record.priority,
        title=record.title,
        message=record.message,
        channels=list(record.channels),
        recipient_count=len(record.recipients),
        resource_type=record.resource_type,
        resource_id=record.resource_id,
        status=record.status,
        expires_at=record.expires_at,
        version=record.version,
        created_by=record.created_by,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def to_detail(
    record: NotificationRecord,
) -> NotificationDetailResponse:

    return NotificationDetailResponse(
        **to_response(record).model_dump(),
        deliveries=[
            NotificationDeliveryResponse(
                recipient_id=item.recipient_id,
                channel=item.channel,
                status=item.status,
                provider_reference=(
                    item.provider_reference
                ),
                error_code=item.error_code,
                updated_at=item.updated_at,
            )
            for item in record.deliveries.values()
        ],
    )


def to_inbox(
    record: NotificationRecord,
    recipient: RecipientState,
) -> NotificationInboxResponse:

    return NotificationInboxResponse(
        notification_id=record.notification_id,
        category=record.category,
        priority=record.priority,
        title=record.title,
        message=record.message,
        status=record.status,
        recipient_status=recipient.status,
        resource_type=record.resource_type,
        resource_id=record.resource_id,
        created_at=record.created_at,
        read_at=recipient.read_at,
        acknowledged_at=recipient.acknowledged_at,
    )


# ============================================================
# NOTIFICATION STORE
# ============================================================

class NotificationStore:

    def __init__(self):

        self._records: dict[
            str,
            NotificationRecord,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    def _get(
        self,
        principal: Principal,
        notification_id: str,
    ) -> NotificationRecord:

        record = self._records.get(
            notification_id
        )

        if (
            record is None
            or record.tenant_id
            != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Notification not found",
            )

        return record

    @staticmethod
    def _check_version(
        record: NotificationRecord,
        expected_version: int,
    ) -> None:

        if record.version != expected_version:
            raise HTTPException(
                status_code=409,
                detail="Notification version conflict",
            )

    @staticmethod
    def _effective_status(
        record: NotificationRecord,
    ) -> NotificationStatus:

        if (
            record.status == NotificationStatus.ACTIVE
            and record.expires_at is not None
            and record.expires_at <= utc_now()
        ):
            return NotificationStatus.EXPIRED

        return record.status

    async def create(
        self,
        *,
        principal: Principal,
        payload: NotificationCreate,
    ) -> NotificationResponse:

        require_notification_access(
            principal,
            payload.warehouse_id,
            write=True,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = request_fingerprint(
            payload
        )

        async with self._lock:

            previous = self._idempotency.get(
                key
            )

            if previous is not None:

                old_hash, notification_id = previous

                if old_hash != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return to_response(
                    self._get(
                        principal,
                        notification_id,
                    )
                )

            tenant_count = sum(
                record.tenant_id
                == principal.tenant_id
                for record in self._records.values()
            )

            if (
                tenant_count
                >= MAX_NOTIFICATIONS_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Notification capacity reached",
                )

            record = NotificationRecord(
                notification_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                category=payload.category,
                priority=payload.priority,
                title=payload.title,
                message=payload.message,
                channels=list(payload.channels),
                resource_type=payload.resource_type,
                resource_id=payload.resource_id,
                expires_at=payload.expires_at,
                created_by=principal.principal_id,
            )

            for recipient_id in payload.recipient_ids:

                record.recipients[
                    recipient_id
                ] = RecipientState(
                    recipient_id=recipient_id,
                )

                for channel in payload.channels:

                    record.deliveries[
                        (recipient_id, channel)
                    ] = DeliveryRecord(
                        recipient_id=recipient_id,
                        channel=channel,
                    )

            self._records[
                record.notification_id
            ] = record

            self._idempotency[key] = (
                request_hash,
                record.notification_id,
            )

            return to_response(record)

    async def get(
        self,
        *,
        principal: Principal,
        notification_id: str,
    ) -> NotificationDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                notification_id,
            )

            require_notification_access(
                principal,
                record.warehouse_id,
                write=False,
            )

            result = to_detail(record)

            result.status = self._effective_status(
                record
            )

            return result

    async def list_records(
        self,
        *,
        principal: Principal,
        warehouse_id: str | None,
        category: NotificationCategory | None,
        limit: int,
    ) -> list[NotificationResponse]:

        require_notification_access(
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
                    and (
                        warehouse_id is None
                        or record.warehouse_id
                        == warehouse_id
                    )
                    and (
                        category is None
                        or record.category == category
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
                    require_notification_access(
                        principal,
                        record.warehouse_id,
                        write=False,
                    )

                except HTTPException:
                    continue

                result = to_response(record)

                result.status = self._effective_status(
                    record
                )

                results.append(result)

                if len(results) >= limit:
                    break

            return results

    async def inbox(
        self,
        *,
        principal: Principal,
        unread_only: bool,
        limit: int,
    ) -> list[NotificationInboxResponse]:

        async with self._lock:

            results = []

            for record in self._records.values():

                if (
                    record.tenant_id
                    != principal.tenant_id
                ):
                    continue

                recipient = record.recipients.get(
                    principal.principal_id
                )

                if recipient is None:
                    continue

                if (
                    unread_only
                    and recipient.status
                    != RecipientStatus.UNREAD
                ):
                    continue

                # Recipient inbox access must still
                # respect warehouse scope.

                if (
                    record.warehouse_id is not None
                    and principal.allowed_warehouse_ids
                    is not None
                    and record.warehouse_id
                    not in principal.allowed_warehouse_ids
                ):
                    continue

                result = to_inbox(
                    record,
                    recipient,
                )

                result.status = self._effective_status(
                    record
                )

                results.append(result)

            results.sort(
                key=lambda item: item.created_at,
                reverse=True,
            )

            return results[:limit]

    async def mark_read(
        self,
        *,
        principal: Principal,
        notification_id: str,
    ) -> NotificationInboxResponse:

        async with self._lock:

            record = self._get(
                principal,
                notification_id,
            )

            recipient = record.recipients.get(
                principal.principal_id
            )

            if recipient is None:
                raise HTTPException(
                    status_code=404,
                    detail="Inbox notification not found",
                )

            if (
                record.warehouse_id is not None
                and principal.allowed_warehouse_ids
                is not None
                and record.warehouse_id
                not in principal.allowed_warehouse_ids
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Warehouse access denied",
                )

            if recipient.status == RecipientStatus.UNREAD:

                recipient.status = RecipientStatus.READ
                recipient.read_at = utc_now()

                record.version += 1
                record.updated_at = utc_now()

            result = to_inbox(
                record,
                recipient,
            )

            result.status = self._effective_status(
                record
            )

            return result

    async def acknowledge(
        self,
        *,
        principal: Principal,
        notification_id: str,
    ) -> NotificationInboxResponse:

        async with self._lock:

            record = self._get(
                principal,
                notification_id,
            )

            recipient = record.recipients.get(
                principal.principal_id
            )

            if recipient is None:
                raise HTTPException(
                    status_code=404,
                    detail="Inbox notification not found",
                )

            if (
                record.warehouse_id is not None
                and principal.allowed_warehouse_ids
                is not None
                and record.warehouse_id
                not in principal.allowed_warehouse_ids
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Warehouse access denied",
                )

            if (
                recipient.status
                != RecipientStatus.ACKNOWLEDGED
            ):

                now = utc_now()

                recipient.status = (
                    RecipientStatus.ACKNOWLEDGED
                )

                if recipient.read_at is None:
                    recipient.read_at = now

                recipient.acknowledged_at = now

                record.version += 1
                record.updated_at = now

            result = to_inbox(
                record,
                recipient,
            )

            result.status = self._effective_status(
                record
            )

            return result

    async def cancel(
        self,
        *,
        principal: Principal,
        notification_id: str,
        expected_version: int,
    ) -> NotificationResponse:

        async with self._lock:

            record = self._get(
                principal,
                notification_id,
            )

            require_notification_access(
                principal,
                record.warehouse_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            if (
                self._effective_status(record)
                != NotificationStatus.ACTIVE
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Notification is not active",
                )

            record.status = NotificationStatus.CANCELLED
            record.version += 1
            record.updated_at = utc_now()

            return to_response(record)

    async def update_delivery(
        self,
        *,
        principal: Principal,
        notification_id: str,
        payload: NotificationDeliveryUpdate,
    ) -> NotificationDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                notification_id,
            )

            require_notification_access(
                principal,
                record.warehouse_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if (
                self._effective_status(record)
                != NotificationStatus.ACTIVE
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Notification is not active",
                )

            delivery = record.deliveries.get(
                (
                    payload.recipient_id,
                    payload.channel,
                )
            )

            if delivery is None:
                raise HTTPException(
                    status_code=404,
                    detail="Delivery record not found",
                )

            allowed_transitions = {
                DeliveryStatus.PENDING: {
                    DeliveryStatus.QUEUED,
                    DeliveryStatus.FAILED,
                },
                DeliveryStatus.QUEUED: {
                    DeliveryStatus.SENT,
                    DeliveryStatus.FAILED,
                },
                DeliveryStatus.SENT: {
                    DeliveryStatus.DELIVERED,
                    DeliveryStatus.FAILED,
                },
                DeliveryStatus.FAILED: {
                    DeliveryStatus.QUEUED,
                },
                DeliveryStatus.DELIVERED: set(),
            }

            if (
                payload.status
                not in allowed_transitions[
                    delivery.status
                ]
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Invalid delivery status transition",
                )

            # Production: only authenticated,
            # authorized provider workers should
            # update external delivery status.

            delivery.status = payload.status
            delivery.provider_reference = (
                payload.provider_reference
            )
            delivery.error_code = payload.error_code
            delivery.updated_at = utc_now()

            record.version += 1
            record.updated_at = utc_now()

            return to_detail(record)

    async def statistics(
        self,
        *,
        principal: Principal,
        warehouse_id: str | None,
    ) -> NotificationStatistics:

        require_notification_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = []

            for record in self._records.values():

                if (
                    record.tenant_id
                    != principal.tenant_id
                ):
                    continue

                if (
                    warehouse_id is not None
                    and record.warehouse_id
                    != warehouse_id
                ):
                    continue

                try:
                    require_notification_access(
                        principal,
                        record.warehouse_id,
                        write=False,
                    )

                except HTTPException:
                    continue

                records.append(record)

            recipients = [
                recipient
                for record in records
                for recipient in record.recipients.values()
            ]

            deliveries = [
                delivery
                for record in records
                for delivery in record.deliveries.values()
            ]

            statuses = [
                self._effective_status(record)
                for record in records
            ]

            return NotificationStatistics(
                total_notifications=len(records),
                active_notifications=statuses.count(
                    NotificationStatus.ACTIVE
                ),
                cancelled_notifications=statuses.count(
                    NotificationStatus.CANCELLED
                ),
                expired_notifications=statuses.count(
                    NotificationStatus.EXPIRED
                ),
                critical_notifications=sum(
                    record.priority
                    == NotificationPriority.CRITICAL
                    for record in records
                ),
                high_priority_notifications=sum(
                    record.priority
                    == NotificationPriority.HIGH
                    for record in records
                ),
                total_recipient_entries=len(recipients),
                unread_recipient_entries=sum(
                    recipient.status
                    == RecipientStatus.UNREAD
                    for recipient in recipients
                ),
                read_recipient_entries=sum(
                    recipient.status
                    == RecipientStatus.READ
                    for recipient in recipients
                ),
                acknowledged_recipient_entries=sum(
                    recipient.status
                    == RecipientStatus.ACKNOWLEDGED
                    for recipient in recipients
                ),
                pending_delivery_records=sum(
                    item.status == DeliveryStatus.PENDING
                    for item in deliveries
                ),
                queued_delivery_records=sum(
                    item.status == DeliveryStatus.QUEUED
                    for item in deliveries
                ),
                sent_delivery_records=sum(
                    item.status == DeliveryStatus.SENT
                    for item in deliveries
                ),
                delivered_delivery_records=sum(
                    item.status == DeliveryStatus.DELIVERED
                    for item in deliveries
                ),
                failed_delivery_records=sum(
                    item.status == DeliveryStatus.FAILED
                    for item in deliveries
                ),
            )


notification_store = NotificationStore()


# ============================================================
# SERVICE
# ============================================================

class NotificationService:

    def __init__(
        self,
        store: NotificationStore,
    ):
        self.store = store

    async def create(
        self,
        principal: Principal,
        payload: NotificationCreate,
    ) -> NotificationResponse:

        return await self.store.create(
            principal=principal,
            payload=payload,
        )


notification_service = NotificationService(
    notification_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Notification Management"],
)


@router.post(
    "",
    response_model=NotificationResponse,
    status_code=201,
)
async def create_notification(
    payload: NotificationCreate,
    principal: CurrentPrincipal,
):
    return await notification_service.create(
        principal,
        payload,
    )


@router.get(
    "/inbox",
    response_model=list[NotificationInboxResponse],
)
async def my_notification_inbox(
    principal: CurrentPrincipal,
    unread_only: bool = False,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await notification_store.inbox(
        principal=principal,
        unread_only=unread_only,
        limit=limit,
    )


@router.get(
    "/statistics",
    response_model=NotificationStatistics,
)
async def notification_statistics(
    principal: CurrentPrincipal,
    warehouse_id: str | None = None,
):
    return await notification_store.statistics(
        principal=principal,
        warehouse_id=warehouse_id,
    )


@router.get(
    "",
    response_model=list[NotificationResponse],
)
async def list_notifications(
    principal: CurrentPrincipal,
    warehouse_id: str | None = None,
    category: NotificationCategory | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await notification_store.list_records(
        principal=principal,
        warehouse_id=warehouse_id,
        category=category,
        limit=limit,
    )


@router.get(
    "/{notification_id}",
    response_model=NotificationDetailResponse,
)
async def get_notification(
    notification_id: str,
    principal: CurrentPrincipal,
):
    return await notification_store.get(
        principal=principal,
        notification_id=notification_id,
    )


@router.post(
    "/{notification_id}/read",
    response_model=NotificationInboxResponse,
)
async def mark_notification_read(
    notification_id: str,
    principal: CurrentPrincipal,
):
    return await notification_store.mark_read(
        principal=principal,
        notification_id=notification_id,
    )


@router.post(
    "/{notification_id}/acknowledge",
    response_model=NotificationInboxResponse,
)
async def acknowledge_notification(
    notification_id: str,
    principal: CurrentPrincipal,
):
    return await notification_store.acknowledge(
        principal=principal,
        notification_id=notification_id,
    )


@router.post(
    "/{notification_id}/cancel",
    response_model=NotificationResponse,
)
async def cancel_notification(
    notification_id: str,
    payload: NotificationVersionRequest,
    principal: CurrentPrincipal,
):
    return await notification_store.cancel(
        principal=principal,
        notification_id=notification_id,
        expected_version=payload.expected_version,
    )


@router.post(
    "/{notification_id}/delivery",
    response_model=NotificationDetailResponse,
)
async def update_notification_delivery(
    notification_id: str,
    payload: NotificationDeliveryUpdate,
    principal: CurrentPrincipal,
):
    return await notification_store.update_delivery(
        principal=principal,
        notification_id=notification_id,
        payload=payload,
    )


__all__ = [
    "NotificationCategory",
    "NotificationPriority",
    "NotificationChannel",
    "NotificationStatus",
    "RecipientStatus",
    "DeliveryStatus",
    "NotificationCreate",
    "NotificationVersionRequest",
    "NotificationDeliveryUpdate",
    "NotificationDeliveryResponse",
    "NotificationResponse",
    "NotificationInboxResponse",
    "NotificationDetailResponse",
    "NotificationStatistics",
    "NotificationStore",
    "NotificationService",
    "notification_store",
    "notification_service",
    "router",
]
