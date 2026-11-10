from __future__ import annotations

"""Planned module: integrations. Implementation pending."""

"""
backend/integrations.py

Autonomous Retail Supply Chain AI 5.0
Enterprise Integration Management API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - External integration registry
    - ERP / WMS / POS / supplier / logistics connectors
    - Credential reference management
    - Connection configuration
    - Provider health checks
    - Synchronization job management
    - Job retry and failure tracking
    - Tenant and warehouse isolation
    - Idempotent integration creation
    - Optimistic concurrency
    - Integration analytics

Security:
    - Never accepts raw API keys or passwords
    - Credentials must be stored in a secret manager
    - Only secret references are retained
    - Does not make arbitrary HTTP requests
    - Provider execution requires trusted adapters

Limitations:
    - In-memory prototype
    - No actual external network synchronization
    - No durable job queue
    - No database persistence
    - No real provider authentication
"""


import asyncio
import hashlib
import json
import secrets

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

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


API_PREFIX = "/api/v1/integrations"

MAX_INTEGRATIONS_PER_TENANT = 1000
MAX_JOBS_PER_TENANT = 20_000
MAX_EVENTS_PER_INTEGRATION = 200
MAX_IDEMPOTENCY_KEYS = 50_000
MAX_LIST_LIMIT = 200


# ============================================================
# ENUMS
# ============================================================

class IntegrationType(str, Enum):
    ERP = "erp"
    WMS = "wms"
    POS = "pos"
    SUPPLIER = "supplier"
    LOGISTICS = "logistics"
    MARKETPLACE = "marketplace"
    FINANCE = "finance"
    NOTIFICATION = "notification"
    ANALYTICS = "analytics"


class IntegrationStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"


class ConnectionHealth(str, Enum):
    NOT_TESTED = "not_tested"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class SyncDirection(str, Enum):
    IMPORT = "import"
    EXPORT = "export"


class SyncResource(str, Enum):
    PRODUCTS = "products"
    INVENTORY = "inventory"
    ORDERS = "orders"
    SUPPLIERS = "suppliers"
    SHIPMENTS = "shipments"
    PRICES = "prices"
    FINANCIAL_RECORDS = "financial_records"


class SyncStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class IntegrationEventType(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    ACTIVATED = "activated"
    PAUSED = "paused"
    DISABLED = "disabled"
    HEALTH_RECORDED = "health_recorded"
    SYNC_QUEUED = "sync_queued"


# ============================================================
# TRUSTED PROVIDER CATALOG
# ============================================================

PROVIDER_CATALOG = {
    "generic_erp": IntegrationType.ERP,
    "generic_wms": IntegrationType.WMS,
    "generic_pos": IntegrationType.POS,
    "generic_supplier": IntegrationType.SUPPLIER,
    "generic_logistics": IntegrationType.LOGISTICS,
    "generic_marketplace": IntegrationType.MARKETPLACE,
    "generic_finance": IntegrationType.FINANCE,
    "generic_notification": IntegrationType.NOTIFICATION,
    "generic_analytics": IntegrationType.ANALYTICS,
}


# ============================================================
# REQUEST MODELS
# ============================================================

class IntegrationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=3,
        max_length=150,
    )

    integration_type: IntegrationType

    provider: str = Field(
        min_length=3,
        max_length=100,
    )

    warehouse_id: str | None = Field(
        default=None,
        max_length=128,
    )

    credential_reference: str = Field(
        min_length=8,
        max_length=300,
        pattern=r"^secret://[a-zA-Z0-9/_-]+$",
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_provider(self):

        expected_type = PROVIDER_CATALOG.get(
            self.provider
        )

        if expected_type is None:
            raise ValueError(
                "Unsupported integration provider"
            )

        if expected_type != self.integration_type:
            raise ValueError(
                "Provider and integration type mismatch"
            )

        return self


class IntegrationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    name: str | None = Field(
        default=None,
        min_length=3,
        max_length=150,
    )

    credential_reference: str | None = Field(
        default=None,
        min_length=8,
        max_length=300,
        pattern=r"^secret://[a-zA-Z0-9/_-]+$",
    )


class IntegrationStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    status: IntegrationStatus


class IntegrationHealthUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    health: ConnectionHealth

    reason_code: str | None = Field(
        default=None,
        max_length=100,
    )


class SyncCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource: SyncResource
    direction: SyncDirection

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )


class SyncResultUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    status: SyncStatus

    records_processed: int = Field(
        default=0,
        ge=0,
        le=100_000_000,
    )

    records_failed: int = Field(
        default=0,
        ge=0,
        le=100_000_000,
    )

    error_code: str | None = Field(
        default=None,
        max_length=100,
    )


# ============================================================
# RESPONSE MODELS
# ============================================================

class IntegrationResponse(BaseModel):
    integration_id: str

    name: str
    integration_type: IntegrationType
    provider: str
    warehouse_id: str | None

    status: IntegrationStatus
    health: ConnectionHealth

    credential_configured: bool

    version: int

    created_by: str
    created_at: datetime
    updated_at: datetime


class IntegrationEventResponse(BaseModel):
    event_id: str
    event_type: IntegrationEventType
    actor_id: str
    version: int
    timestamp: datetime
    reason_code: str | None = None


class IntegrationDetailResponse(
    IntegrationResponse
):
    events: list[IntegrationEventResponse]


class SyncJobResponse(BaseModel):
    job_id: str
    integration_id: str

    resource: SyncResource
    direction: SyncDirection

    status: SyncStatus

    records_processed: int
    records_failed: int

    error_code: str | None

    attempt: int
    version: int

    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class IntegrationAnalyticsResponse(BaseModel):
    total_integrations: int
    active_integrations: int
    paused_integrations: int
    disabled_integrations: int

    healthy_integrations: int
    degraded_integrations: int
    unavailable_integrations: int

    total_sync_jobs: int
    completed_sync_jobs: int
    failed_sync_jobs: int
    queued_sync_jobs: int


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass
class IntegrationRecord:
    integration_id: str
    tenant_id: str

    name: str
    integration_type: IntegrationType
    provider: str
    warehouse_id: str | None

    credential_reference: str

    created_by: str

    status: IntegrationStatus = (
        IntegrationStatus.DRAFT
    )

    health: ConnectionHealth = (
        ConnectionHealth.NOT_TESTED
    )

    version: int = 1

    events: list[
        IntegrationEventResponse
    ] = field(default_factory=list)

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
class SyncJobRecord:
    job_id: str
    tenant_id: str
    integration_id: str

    resource: SyncResource
    direction: SyncDirection

    status: SyncStatus = SyncStatus.QUEUED

    records_processed: int = 0
    records_failed: int = 0

    error_code: str | None = None

    attempt: int = 0
    version: int = 1

    created_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    started_at: datetime | None = None
    completed_at: datetime | None = None


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint(
    operation: str,
    payload: BaseModel,
    *,
    integration_id: str | None = None,
) -> str:

    data = payload.model_dump(
        mode="json",
        exclude={"source_request_id"},
    )

    canonical = json.dumps(
        {
            "operation": operation,
            "integration_id": integration_id,
            "payload": data,
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def require_integration_access(
    principal: Principal,
    warehouse_id: str | None,
    *,
    write: bool,
) -> None:

    # Dedicated INTEGRATION_READ and
    # INTEGRATION_WRITE permissions should
    # replace these placeholders.

    permission = (
        Permission.SYSTEM_CONFIGURE
        if write
        else Permission.ANALYTICS_READ
    )

    allowed = principal.allowed_warehouse_ids

    if warehouse_id is None and allowed is not None:
        raise HTTPException(
            status_code=403,
            detail="Tenant-wide integration access denied",
        )

    if (
        warehouse_id is not None
        and allowed is not None
        and warehouse_id not in allowed
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
            detail="Integration access denied",
        )


def to_integration_response(
    record: IntegrationRecord,
) -> IntegrationResponse:

    return IntegrationResponse(
        integration_id=record.integration_id,
        name=record.name,
        integration_type=record.integration_type,
        provider=record.provider,
        warehouse_id=record.warehouse_id,
        status=record.status,
        health=record.health,
        credential_configured=bool(
            record.credential_reference
        ),
        version=record.version,
        created_by=record.created_by,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def to_integration_detail(
    record: IntegrationRecord,
) -> IntegrationDetailResponse:

    return IntegrationDetailResponse(
        **to_integration_response(
            record
        ).model_dump(),
        events=[
            event.model_copy(deep=True)
            for event in record.events
        ],
    )


def to_sync_response(
    record: SyncJobRecord,
) -> SyncJobResponse:

    return SyncJobResponse(
        job_id=record.job_id,
        integration_id=record.integration_id,
        resource=record.resource,
        direction=record.direction,
        status=record.status,
        records_processed=record.records_processed,
        records_failed=record.records_failed,
        error_code=record.error_code,
        attempt=record.attempt,
        version=record.version,
        created_at=record.created_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
    )


# ============================================================
# INTEGRATION STORE
# ============================================================

class IntegrationStore:

    def __init__(self):

        self._integrations: dict[
            str,
            IntegrationRecord,
        ] = {}

        self._jobs: dict[
            str,
            SyncJobRecord,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    def _get_integration(
        self,
        principal: Principal,
        integration_id: str,
        *,
        write: bool,
    ) -> IntegrationRecord:

        record = self._integrations.get(
            integration_id
        )

        if (
            record is None
            or record.tenant_id
            != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Integration not found",
            )

        require_integration_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    def _get_job(
        self,
        principal: Principal,
        job_id: str,
        *,
        write: bool,
    ) -> SyncJobRecord:

        job = self._jobs.get(job_id)

        if (
            job is None
            or job.tenant_id != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Sync job not found",
            )

        self._get_integration(
            principal,
            job.integration_id,
            write=write,
        )

        return job

    @staticmethod
    def _check_version(
        actual: int,
        expected: int,
    ) -> None:

        if actual != expected:
            raise HTTPException(
                status_code=409,
                detail="Version conflict",
            )

    @staticmethod
    def _append_event(
        record: IntegrationRecord,
        event_type: IntegrationEventType,
        actor_id: str,
        reason_code: str | None = None,
    ) -> None:

        if (
            len(record.events)
            >= MAX_EVENTS_PER_INTEGRATION
        ):
            raise HTTPException(
                status_code=503,
                detail="Integration event capacity reached",
            )

        record.events.append(
            IntegrationEventResponse(
                event_id=secrets.token_urlsafe(18),
                event_type=event_type,
                actor_id=actor_id,
                version=record.version,
                timestamp=utc_now(),
                reason_code=reason_code,
            )
        )

    async def create(
        self,
        *,
        principal: Principal,
        payload: IntegrationCreate,
    ) -> IntegrationResponse:

        require_integration_access(
            principal,
            payload.warehouse_id,
            write=True,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = fingerprint(
            "create_integration",
            payload,
        )

        async with self._lock:

            previous = self._idempotency.get(
                key
            )

            if previous is not None:

                old_hash, integration_id = previous

                if old_hash != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return to_integration_response(
                    self._get_integration(
                        principal,
                        integration_id,
                        write=False,
                    )
                )

            tenant_count = sum(
                record.tenant_id
                == principal.tenant_id
                for record in self._integrations.values()
            )

            if (
                tenant_count >= MAX_INTEGRATIONS_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Integration capacity reached",
                )

            record = IntegrationRecord(
                integration_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                name=payload.name.strip(),
                integration_type=payload.integration_type,
                provider=payload.provider,
                warehouse_id=payload.warehouse_id,
                credential_reference=(
                    payload.credential_reference
                ),
                created_by=principal.principal_id,
            )

            self._append_event(
                record,
                IntegrationEventType.CREATED,
                principal.principal_id,
            )

            self._integrations[
                record.integration_id
            ] = record

            self._idempotency[key] = (
                request_hash,
                record.integration_id,
            )

            return to_integration_response(
                record
            )

    async def get(
        self,
        *,
        principal: Principal,
        integration_id: str,
    ) -> IntegrationDetailResponse:

        async with self._lock:

            record = self._get_integration(
                principal,
                integration_id,
                write=False,
            )

            return to_integration_detail(
                record
            )

    async def list_integrations(
        self,
        *,
        principal: Principal,
        warehouse_id: str | None,
        integration_type: IntegrationType | None,
        status: IntegrationStatus | None,
        limit: int,
    ) -> list[IntegrationResponse]:

        if warehouse_id is not None:
            require_integration_access(
                principal,
                warehouse_id,
                write=False,
            )

        async with self._lock:

            records = []

            for record in self._integrations.values():

                if record.tenant_id != principal.tenant_id:
                    continue

                if (
                    warehouse_id is not None
                    and record.warehouse_id
                    != warehouse_id
                ):
                    continue

                if (
                    integration_type is not None
                    and record.integration_type
                    != integration_type
                ):
                    continue

                if (
                    status is not None
                    and record.status != status
                ):
                    continue

                try:
                    require_integration_access(
                        principal,
                        record.warehouse_id,
                        write=False,
                    )
                except HTTPException:
                    continue

                records.append(record)

            records.sort(
                key=lambda item: item.created_at,
                reverse=True,
            )

            return [
                to_integration_response(record)
                for record in records[:limit]
            ]

    async def update(
        self,
        *,
        principal: Principal,
        integration_id: str,
        payload: IntegrationUpdate,
    ) -> IntegrationDetailResponse:

        async with self._lock:

            record = self._get_integration(
                principal,
                integration_id,
                write=True,
            )

            self._check_version(
                record.version,
                payload.expected_version,
            )

            if record.status == IntegrationStatus.DISABLED:
                raise HTTPException(
                    status_code=409,
                    detail="Disabled integration is immutable",
                )

            if len(record.events) >= MAX_EVENTS_PER_INTEGRATION:
                raise HTTPException(
                    status_code=503,
                    detail="Integration event capacity reached",
                )

            if payload.name is not None:
                record.name = payload.name.strip()

            if payload.credential_reference is not None:
                record.credential_reference = (
                    payload.credential_reference
                )
                record.health = (
                    ConnectionHealth.NOT_TESTED
                )
                record.status = IntegrationStatus.DRAFT

            record.version += 1
            record.updated_at = utc_now()

            self._append_event(
                record,
                IntegrationEventType.UPDATED,
                principal.principal_id,
            )

            return to_integration_detail(
                record
            )

    async def update_status(
        self,
        *,
        principal: Principal,
        integration_id: str,
        payload: IntegrationStatusUpdate,
    ) -> IntegrationDetailResponse:

        async with self._lock:

            record = self._get_integration(
                principal,
                integration_id,
                write=True,
            )

            self._check_version(
                record.version,
                payload.expected_version,
            )

            if record.status == IntegrationStatus.DISABLED:
                raise HTTPException(
                    status_code=409,
                    detail="Disabled integration cannot be reactivated",
                )

            if payload.status == IntegrationStatus.DRAFT:
                raise HTTPException(
                    status_code=409,
                    detail="Draft is not a manual transition",
                )

            if (
                payload.status == IntegrationStatus.ACTIVE
                and record.health != ConnectionHealth.HEALTHY
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Healthy connection required",
                )

            if payload.status == record.status:
                raise HTTPException(
                    status_code=409,
                    detail="Integration already has this status",
                )

            if len(record.events) >= MAX_EVENTS_PER_INTEGRATION:
                raise HTTPException(
                    status_code=503,
                    detail="Integration event capacity reached",
                )

            record.status = payload.status
            record.version += 1
            record.updated_at = utc_now()

            event_type = {
                IntegrationStatus.ACTIVE:
                    IntegrationEventType.ACTIVATED,
                IntegrationStatus.PAUSED:
                    IntegrationEventType.PAUSED,
                IntegrationStatus.DISABLED:
                    IntegrationEventType.DISABLED,
            }[payload.status]

            self._append_event(
                record,
                event_type,
                principal.principal_id,
            )

            return to_integration_detail(
                record
            )

    async def record_health(
        self,
        *,
        principal: Principal,
        integration_id: str,
        payload: IntegrationHealthUpdate,
    ) -> IntegrationDetailResponse:

        async with self._lock:

            record = self._get_integration(
                principal,
                integration_id,
                write=True,
            )

            self._check_version(
                record.version,
                payload.expected_version,
            )

            if record.status == IntegrationStatus.DISABLED:
                raise HTTPException(
                    status_code=409,
                    detail="Integration disabled",
                )

            if len(record.events) >= MAX_EVENTS_PER_INTEGRATION:
                raise HTTPException(
                    status_code=503,
                    detail="Integration event capacity reached",
                )

            # This is an administrative health record.
            # It does not perform a real provider check.
            # In production, only trusted adapter workers
            # should be able to record health results.

            record.health = payload.health

            if (
                payload.health
                != ConnectionHealth.HEALTHY
                and record.status
                == IntegrationStatus.ACTIVE
            ):
                record.status = IntegrationStatus.PAUSED

            record.version += 1
            record.updated_at = utc_now()

            self._append_event(
                record,
                IntegrationEventType.HEALTH_RECORDED,
                principal.principal_id,
                payload.reason_code,
            )

            return to_integration_detail(
                record
            )

    async def create_sync_job(
        self,
        *,
        principal: Principal,
        integration_id: str,
        payload: SyncCreate,
    ) -> SyncJobResponse:

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = fingerprint(
            "create_sync_job",
            payload,
            integration_id=integration_id,
        )

        async with self._lock:

            record = self._get_integration(
                principal,
                integration_id,
                write=True,
            )

            previous = self._idempotency.get(
                key
            )

            if previous is not None:

                old_hash, job_id = previous

                if old_hash != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return to_sync_response(
                    self._get_job(
                        principal,
                        job_id,
                        write=False,
                    )
                )

            if record.status != IntegrationStatus.ACTIVE:
                raise HTTPException(
                    status_code=409,
                    detail="Integration is not active",
                )

            if record.health != ConnectionHealth.HEALTHY:
                raise HTTPException(
                    status_code=409,
                    detail="Integration is not healthy",
                )

            tenant_jobs = sum(
                job.tenant_id == principal.tenant_id
                for job in self._jobs.values()
            )

            if (
                tenant_jobs >= MAX_JOBS_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
                or len(record.events)
                >= MAX_EVENTS_PER_INTEGRATION
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Sync capacity reached",
                )

            job = SyncJobRecord(
                job_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                integration_id=integration_id,
                resource=payload.resource,
                direction=payload.direction,
            )

            self._jobs[job.job_id] = job

            self._idempotency[key] = (
                request_hash,
                job.job_id,
            )

            self._append_event(
                record,
                IntegrationEventType.SYNC_QUEUED,
                principal.principal_id,
            )

            # No worker is dispatched automatically.

            return to_sync_response(job)

    async def get_sync_job(
        self,
        *,
        principal: Principal,
        job_id: str,
    ) -> SyncJobResponse:

        async with self._lock:

            job = self._get_job(
                principal,
                job_id,
                write=False,
            )

            return to_sync_response(job)

    async def list_sync_jobs(
        self,
        *,
        principal: Principal,
        integration_id: str,
        status: SyncStatus | None,
        limit: int,
    ) -> list[SyncJobResponse]:

        async with self._lock:

            self._get_integration(
                principal,
                integration_id,
                write=False,
            )

            jobs = [
                job
                for job in self._jobs.values()
                if (
                    job.tenant_id
                    == principal.tenant_id
                    and job.integration_id
                    == integration_id
                    and (
                        status is None
                        or job.status == status
                    )
                )
            ]

            jobs.sort(
                key=lambda item: item.created_at,
                reverse=True,
            )

            return [
                to_sync_response(job)
                for job in jobs[:limit]
            ]

    async def analytics(
        self,
        *,
        principal: Principal,
    ) -> IntegrationAnalyticsResponse:

        # Tenant-wide analytics require unrestricted
        # warehouse scope.
        require_integration_access(
            principal,
            None,
            write=False,
        )

        async with self._lock:

            integrations = [
                record
                for record in self._integrations.values()
                if record.tenant_id
                == principal.tenant_id
            ]

            jobs = [
                job
                for job in self._jobs.values()
                if job.tenant_id
                == principal.tenant_id
            ]

            return IntegrationAnalyticsResponse(
                total_integrations=len(integrations),
                active_integrations=sum(
                    item.status == IntegrationStatus.ACTIVE
                    for item in integrations
                ),
                paused_integrations=sum(
                    item.status == IntegrationStatus.PAUSED
                    for item in integrations
                ),
                disabled_integrations=sum(
                    item.status == IntegrationStatus.DISABLED
                    for item in integrations
                ),
                healthy_integrations=sum(
                    item.health == ConnectionHealth.HEALTHY
                    for item in integrations
                ),
                degraded_integrations=sum(
                    item.health == ConnectionHealth.DEGRADED
                    for item in integrations
                ),
                unavailable_integrations=sum(
                    item.health == ConnectionHealth.UNAVAILABLE
                    for item in integrations
                ),
                total_sync_jobs=len(jobs),
                completed_sync_jobs=sum(
                    job.status == SyncStatus.COMPLETED
                    for job in jobs
                ),
                failed_sync_jobs=sum(
                    job.status == SyncStatus.FAILED
                    for job in jobs
                ),
                queued_sync_jobs=sum(
                    job.status == SyncStatus.QUEUED
                    for job in jobs
                ),
            )


integration_store = IntegrationStore()


# ============================================================
# SERVICE
# ============================================================

class IntegrationService:

    def __init__(
        self,
        store: IntegrationStore,
    ):
        self.store = store

    async def register(
        self,
        principal: Principal,
        payload: IntegrationCreate,
    ) -> IntegrationResponse:

        return await self.store.create(
            principal=principal,
            payload=payload,
        )

    async def queue_sync(
        self,
        principal: Principal,
        integration_id: str,
        payload: SyncCreate,
    ) -> SyncJobResponse:

        return await self.store.create_sync_job(
            principal=principal,
            integration_id=integration_id,
            payload=payload,
        )


integration_service = IntegrationService(
    integration_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Enterprise Integrations"],
)


@router.post(
    "",
    response_model=IntegrationResponse,
    status_code=201,
)
async def create_integration(
    payload: IntegrationCreate,
    principal: CurrentPrincipal,
):
    return await integration_service.register(
        principal,
        payload,
    )


@router.get(
    "",
    response_model=list[IntegrationResponse],
)
async def list_integrations(
    principal: CurrentPrincipal,
    warehouse_id: str | None = None,
    integration_type: IntegrationType | None = None,
    status: IntegrationStatus | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await integration_store.list_integrations(
        principal=principal,
        warehouse_id=warehouse_id,
        integration_type=integration_type,
        status=status,
        limit=limit,
    )


@router.get(
    "/analytics",
    response_model=IntegrationAnalyticsResponse,
)
async def integration_analytics(
    principal: CurrentPrincipal,
):
    return await integration_store.analytics(
        principal=principal,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=SyncJobResponse,
)
async def get_sync_job(
    job_id: str,
    principal: CurrentPrincipal,
):
    return await integration_store.get_sync_job(
        principal=principal,
        job_id=job_id,
    )


@router.get(
    "/{integration_id}",
    response_model=IntegrationDetailResponse,
)
async def get_integration(
    integration_id: str,
    principal: CurrentPrincipal,
):
    return await integration_store.get(
        principal=principal,
        integration_id=integration_id,
    )


@router.patch(
    "/{integration_id}",
    response_model=IntegrationDetailResponse,
)
async def update_integration(
    integration_id: str,
    payload: IntegrationUpdate,
    principal: CurrentPrincipal,
):
    return await integration_store.update(
        principal=principal,
        integration_id=integration_id,
        payload=payload,
    )


@router.patch(
    "/{integration_id}/status",
    response_model=IntegrationDetailResponse,
)
async def update_integration_status(
    integration_id: str,
    payload: IntegrationStatusUpdate,
    principal: CurrentPrincipal,
):
    return await integration_store.update_status(
        principal=principal,
        integration_id=integration_id,
        payload=payload,
    )


@router.post(
    "/{integration_id}/health",
    response_model=IntegrationDetailResponse,
)
async def record_integration_health(
    integration_id: str,
    payload: IntegrationHealthUpdate,
    principal: CurrentPrincipal,
):
    return await integration_store.record_health(
        principal=principal,
        integration_id=integration_id,
        payload=payload,
    )


@router.post(
    "/{integration_id}/sync",
    response_model=SyncJobResponse,
    status_code=201,
)
async def create_sync_job(
    integration_id: str,
    payload: SyncCreate,
    principal: CurrentPrincipal,
):
    return await integration_service.queue_sync(
        principal,
        integration_id,
        payload,
    )


@router.get(
    "/{integration_id}/jobs",
    response_model=list[SyncJobResponse],
)
async def list_integration_jobs(
    integration_id: str,
    principal: CurrentPrincipal,
    status: SyncStatus | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await integration_store.list_sync_jobs(
        principal=principal,
        integration_id=integration_id,
        status=status,
        limit=limit,
    )


__all__ = [
    "IntegrationType",
    "IntegrationStatus",
    "ConnectionHealth",
    "SyncDirection",
    "SyncResource",
    "SyncStatus",
    "IntegrationCreate",
    "IntegrationUpdate",
    "IntegrationStatusUpdate",
    "IntegrationHealthUpdate",
    "SyncCreate",
    "SyncResultUpdate",
    "IntegrationResponse",
    "IntegrationDetailResponse",
    "SyncJobResponse",
    "IntegrationAnalyticsResponse",
    "IntegrationStore",
    "IntegrationService",
    "integration_store",
    "integration_service",
    "router",
]
