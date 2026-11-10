from __future__ import annotations

"""Planned module: incidents. Implementation pending."""

"""
backend/incidents.py

Autonomous Retail Supply Chain AI 5.0
Enterprise Incident Management API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Incident reporting
    - Warehouse and tenant isolation
    - Safety and operational incident categories
    - Severity classification
    - Assignment and escalation
    - Investigation lifecycle
    - Resolution and closure
    - Incident event history
    - Idempotent creation
    - Optimistic concurrency
    - Incident analytics
    - Bounded in-memory storage

Important:
    This module records operational incidents.
    It does not automatically contact emergency
    services, dispatch responders, or control
    industrial equipment.

    Production integration requires:
        PostgreSQL persistence
        Audit event outbox
        Verified employee assignments
        Emergency response procedures
        Notification integrations
        Evidence storage
        Incident response SLAs
        Retention and privacy controls
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


API_PREFIX = "/api/v1/incidents"

MAX_INCIDENTS_PER_TENANT = 50_000
MAX_EVENTS_PER_INCIDENT = 200
MAX_IDEMPOTENCY_KEYS = 100_000
MAX_LIST_LIMIT = 200


# ============================================================
# ENUMS
# ============================================================

class IncidentCategory(str, Enum):
    INVENTORY_DISCREPANCY = "inventory_discrepancy"
    STOCKOUT = "stockout"
    SUPPLIER_DISRUPTION = "supplier_disruption"
    DELIVERY_DELAY = "delivery_delay"
    VEHICLE_BREAKDOWN = "vehicle_breakdown"
    EQUIPMENT_FAILURE = "equipment_failure"
    WORKPLACE_SAFETY = "workplace_safety"
    FIRE_HAZARD = "fire_hazard"
    SECURITY_BREACH = "security_breach"
    PRODUCT_DAMAGE = "product_damage"
    QUALITY_ISSUE = "quality_issue"
    SYSTEM_OUTAGE = "system_outage"
    AI_AGENT_FAILURE = "ai_agent_failure"
    OTHER = "other"


class IncidentSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(str, Enum):
    REPORTED = "reported"
    ACKNOWLEDGED = "acknowledged"
    INVESTIGATING = "investigating"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CLOSED = "closed"


class IncidentEventType(str, Enum):
    CREATED = "created"
    ACKNOWLEDGED = "acknowledged"
    ASSIGNED = "assigned"
    INVESTIGATION_STARTED = "investigation_started"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    REOPENED = "reopened"
    CLOSED = "closed"


ALLOWED_TRANSITIONS = {
    IncidentStatus.REPORTED: {
        IncidentStatus.ACKNOWLEDGED,
        IncidentStatus.ESCALATED,
    },
    IncidentStatus.ACKNOWLEDGED: {
        IncidentStatus.INVESTIGATING,
        IncidentStatus.ESCALATED,
    },
    IncidentStatus.INVESTIGATING: {
        IncidentStatus.ESCALATED,
        IncidentStatus.RESOLVED,
    },
    IncidentStatus.ESCALATED: {
        IncidentStatus.INVESTIGATING,
        IncidentStatus.RESOLVED,
    },
    IncidentStatus.RESOLVED: {
        IncidentStatus.INVESTIGATING,
        IncidentStatus.CLOSED,
    },
    IncidentStatus.CLOSED: set(),
}


# ============================================================
# REQUEST MODELS
# ============================================================

class IncidentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    category: IncidentCategory
    severity: IncidentSeverity

    title: str = Field(
        min_length=5,
        max_length=200,
    )

    description: str = Field(
        min_length=10,
        max_length=5000,
    )

    resource_type: str | None = Field(
        default=None,
        max_length=100,
    )

    resource_id: str | None = Field(
        default=None,
        max_length=128,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_resource(self):

        if bool(self.resource_type) != bool(
            self.resource_id
        ):
            raise ValueError(
                "resource_type and resource_id "
                "must be supplied together"
            )

        return self


class IncidentVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class IncidentAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assigned_to: str = Field(
        min_length=1,
        max_length=128,
    )

    expected_version: int = Field(ge=1)


class IncidentEscalationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    reason: str = Field(
        min_length=5,
        max_length=1000,
    )


class IncidentResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    resolution_summary: str = Field(
        min_length=10,
        max_length=3000,
    )

    root_cause: str = Field(
        min_length=5,
        max_length=2000,
    )

    corrective_action: str = Field(
        min_length=5,
        max_length=2000,
    )


# ============================================================
# RESPONSE MODELS
# ============================================================

class IncidentEventResponse(BaseModel):
    event_id: str
    incident_id: str
    event_type: IncidentEventType

    actor_id: str
    timestamp: datetime
    version: int

    note: str | None = None


class IncidentResponse(BaseModel):
    incident_id: str
    warehouse_id: str

    category: IncidentCategory
    severity: IncidentSeverity
    status: IncidentStatus

    title: str
    description: str

    resource_type: str | None
    resource_id: str | None

    reported_by: str
    assigned_to: str | None

    escalation_count: int

    resolution_summary: str | None
    root_cause: str | None
    corrective_action: str | None

    version: int

    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    closed_at: datetime | None


class IncidentDetailResponse(IncidentResponse):
    events: list[IncidentEventResponse]


class IncidentAnalyticsResponse(BaseModel):
    warehouse_id: str

    total_incidents: int

    reported: int
    acknowledged: int
    investigating: int
    escalated: int
    resolved: int
    closed: int

    low: int
    medium: int
    high: int
    critical: int

    total_escalations: int

    average_resolution_hours: float | None


# ============================================================
# INTERNAL RECORD
# ============================================================

@dataclass
class IncidentRecord:
    incident_id: str
    tenant_id: str
    warehouse_id: str

    category: IncidentCategory
    severity: IncidentSeverity

    title: str
    description: str

    resource_type: str | None
    resource_id: str | None

    reported_by: str

    status: IncidentStatus = (
        IncidentStatus.REPORTED
    )

    assigned_to: str | None = None

    escalation_count: int = 0

    resolution_summary: str | None = None
    root_cause: str | None = None
    corrective_action: str | None = None

    version: int = 1

    events: list[
        IncidentEventResponse
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

    resolved_at: datetime | None = None
    closed_at: datetime | None = None


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def request_fingerprint(
    payload: IncidentCreate,
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


def require_incident_access(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool,
) -> None:

    permission = (
        Permission.INCIDENT_WRITE
        if write
        else Permission.INCIDENT_READ
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
            detail="Incident access denied",
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


def to_response(
    record: IncidentRecord,
) -> IncidentResponse:

    return IncidentResponse(
        incident_id=record.incident_id,
        warehouse_id=record.warehouse_id,
        category=record.category,
        severity=record.severity,
        status=record.status,
        title=record.title,
        description=record.description,
        resource_type=record.resource_type,
        resource_id=record.resource_id,
        reported_by=record.reported_by,
        assigned_to=record.assigned_to,
        escalation_count=record.escalation_count,
        resolution_summary=record.resolution_summary,
        root_cause=record.root_cause,
        corrective_action=record.corrective_action,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        resolved_at=record.resolved_at,
        closed_at=record.closed_at,
    )


def to_detail(
    record: IncidentRecord,
) -> IncidentDetailResponse:

    return IncidentDetailResponse(
        **to_response(record).model_dump(),
        events=[
            event.model_copy(deep=True)
            for event in record.events
        ],
    )


# ============================================================
# INCIDENT STORE
# ============================================================

class IncidentStore:

    def __init__(self):

        self._records: dict[
            str,
            IncidentRecord,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    def _get(
        self,
        principal: Principal,
        incident_id: str,
        *,
        write: bool,
    ) -> IncidentRecord:

        record = self._records.get(
            incident_id
        )

        if (
            record is None
            or record.tenant_id
            != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Incident not found",
            )

        require_incident_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    @staticmethod
    def _check_version(
        record: IncidentRecord,
        expected_version: int,
    ) -> None:

        if record.version != expected_version:
            raise HTTPException(
                status_code=409,
                detail="Incident version conflict",
            )

    @staticmethod
    def _check_event_capacity(
        record: IncidentRecord,
    ) -> None:

        if len(record.events) >= MAX_EVENTS_PER_INCIDENT:
            raise HTTPException(
                status_code=503,
                detail="Incident event capacity reached",
            )

    @staticmethod
    def _append_event(
        record: IncidentRecord,
        event_type: IncidentEventType,
        actor_id: str,
        note: str | None = None,
    ) -> None:

        record.events.append(
            IncidentEventResponse(
                event_id=secrets.token_urlsafe(18),
                incident_id=record.incident_id,
                event_type=event_type,
                actor_id=actor_id,
                timestamp=utc_now(),
                version=record.version,
                note=note,
            )
        )

    @staticmethod
    def _transition(
        record: IncidentRecord,
        new_status: IncidentStatus,
        event_type: IncidentEventType,
        actor_id: str,
        note: str | None = None,
    ) -> None:

        if new_status not in ALLOWED_TRANSITIONS[
            record.status
        ]:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Invalid transition: "
                    f"{record.status.value} -> "
                    f"{new_status.value}"
                ),
            )

        IncidentStore._check_event_capacity(
            record
        )

        record.status = new_status
        record.version += 1
        record.updated_at = utc_now()

        IncidentStore._append_event(
            record,
            event_type,
            actor_id,
            note,
        )

    async def create(
        self,
        *,
        principal: Principal,
        payload: IncidentCreate,
    ) -> IncidentResponse:

        require_incident_access(
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

                old_hash, incident_id = previous

                if old_hash != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return to_response(
                    self._get(
                        principal,
                        incident_id,
                        write=False,
                    )
                )

            tenant_count = sum(
                record.tenant_id
                == principal.tenant_id
                for record in self._records.values()
            )

            if (
                tenant_count >= MAX_INCIDENTS_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Incident capacity reached",
                )

            record = IncidentRecord(
                incident_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                category=payload.category,
                severity=payload.severity,
                title=payload.title.strip(),
                description=payload.description.strip(),
                resource_type=payload.resource_type,
                resource_id=payload.resource_id,
                reported_by=principal.principal_id,
            )

            self._append_event(
                record,
                IncidentEventType.CREATED,
                principal.principal_id,
            )

            self._records[
                record.incident_id
            ] = record

            self._idempotency[key] = (
                request_hash,
                record.incident_id,
            )

            return to_response(record)

    async def get(
        self,
        *,
        principal: Principal,
        incident_id: str,
    ) -> IncidentDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                incident_id,
                write=False,
            )

            return to_detail(record)

    async def list_records(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
        status: IncidentStatus | None,
        severity: IncidentSeverity | None,
        category: IncidentCategory | None,
        limit: int,
    ) -> list[IncidentResponse]:

        require_incident_access(
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
                    and record.warehouse_id
                    == warehouse_id
                    and (
                        status is None
                        or record.status == status
                    )
                    and (
                        severity is None
                        or record.severity == severity
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

            return [
                to_response(record)
                for record in records[:limit]
            ]

    async def acknowledge(
        self,
        *,
        principal: Principal,
        incident_id: str,
        payload: IncidentVersionRequest,
    ) -> IncidentDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                incident_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._transition(
                record,
                IncidentStatus.ACKNOWLEDGED,
                IncidentEventType.ACKNOWLEDGED,
                principal.principal_id,
            )

            return to_detail(record)

    async def assign(
        self,
        *,
        principal: Principal,
        incident_id: str,
        payload: IncidentAssignmentRequest,
    ) -> IncidentDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                incident_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status == IncidentStatus.CLOSED:
                raise HTTPException(
                    status_code=409,
                    detail="Closed incident cannot be assigned",
                )

            self._check_event_capacity(
                record
            )

            record.assigned_to = payload.assigned_to
            record.version += 1
            record.updated_at = utc_now()

            self._append_event(
                record,
                IncidentEventType.ASSIGNED,
                principal.principal_id,
            )

            return to_detail(record)

    async def start_investigation(
        self,
        *,
        principal: Principal,
        incident_id: str,
        payload: IncidentVersionRequest,
    ) -> IncidentDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                incident_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if not record.assigned_to:
                raise HTTPException(
                    status_code=409,
                    detail="Assign incident before investigation",
                )

            self._transition(
                record,
                IncidentStatus.INVESTIGATING,
                IncidentEventType.INVESTIGATION_STARTED,
                principal.principal_id,
            )

            return to_detail(record)

    async def escalate(
        self,
        *,
        principal: Principal,
        incident_id: str,
        payload: IncidentEscalationRequest,
    ) -> IncidentDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                incident_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._transition(
                record,
                IncidentStatus.ESCALATED,
                IncidentEventType.ESCALATED,
                principal.principal_id,
                payload.reason.strip(),
            )

            record.escalation_count += 1

            return to_detail(record)

    async def resolve(
        self,
        *,
        principal: Principal,
        incident_id: str,
        payload: IncidentResolutionRequest,
    ) -> IncidentDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                incident_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if (
                IncidentStatus.RESOLVED
                not in ALLOWED_TRANSITIONS[record.status]
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Incident cannot be resolved",
                )

            self._check_event_capacity(
                record
            )

            record.resolution_summary = (
                payload.resolution_summary.strip()
            )

            record.root_cause = (
                payload.root_cause.strip()
            )

            record.corrective_action = (
                payload.corrective_action.strip()
            )

            record.resolved_at = utc_now()

            self._transition(
                record,
                IncidentStatus.RESOLVED,
                IncidentEventType.RESOLVED,
                principal.principal_id,
            )

            return to_detail(record)

    async def reopen(
        self,
        *,
        principal: Principal,
        incident_id: str,
        payload: IncidentVersionRequest,
    ) -> IncidentDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                incident_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._transition(
                record,
                IncidentStatus.INVESTIGATING,
                IncidentEventType.REOPENED,
                principal.principal_id,
            )

            record.resolved_at = None
            record.resolution_summary = None
            record.root_cause = None
            record.corrective_action = None

            return to_detail(record)

    async def close(
        self,
        *,
        principal: Principal,
        incident_id: str,
        payload: IncidentVersionRequest,
    ) -> IncidentDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                incident_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._transition(
                record,
                IncidentStatus.CLOSED,
                IncidentEventType.CLOSED,
                principal.principal_id,
            )

            record.closed_at = utc_now()

            return to_detail(record)

    async def analytics(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
    ) -> IncidentAnalyticsResponse:

        require_incident_access(
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
                    and record.warehouse_id
                    == warehouse_id
                )
            ]

            status_counts = {
                status: sum(
                    record.status == status
                    for record in records
                )
                for status in IncidentStatus
            }

            severity_counts = {
                severity: sum(
                    record.severity == severity
                    for record in records
                )
                for severity in IncidentSeverity
            }

            resolution_hours = [
                (
                    record.resolved_at
                    - record.created_at
                ).total_seconds() / 3600
                for record in records
                if record.resolved_at is not None
            ]

            average_resolution = (
                round(
                    sum(resolution_hours)
                    / len(resolution_hours),
                    2,
                )
                if resolution_hours
                else None
            )

            return IncidentAnalyticsResponse(
                warehouse_id=warehouse_id,
                total_incidents=len(records),
                reported=status_counts[
                    IncidentStatus.REPORTED
                ],
                acknowledged=status_counts[
                    IncidentStatus.ACKNOWLEDGED
                ],
                investigating=status_counts[
                    IncidentStatus.INVESTIGATING
                ],
                escalated=status_counts[
                    IncidentStatus.ESCALATED
                ],
                resolved=status_counts[
                    IncidentStatus.RESOLVED
                ],
                closed=status_counts[
                    IncidentStatus.CLOSED
                ],
                low=severity_counts[
                    IncidentSeverity.LOW
                ],
                medium=severity_counts[
                    IncidentSeverity.MEDIUM
                ],
                high=severity_counts[
                    IncidentSeverity.HIGH
                ],
                critical=severity_counts[
                    IncidentSeverity.CRITICAL
                ],
                total_escalations=sum(
                    record.escalation_count
                    for record in records
                ),
                average_resolution_hours=(
                    average_resolution
                ),
            )


incident_store = IncidentStore()


# ============================================================
# SERVICE
# ============================================================

class IncidentService:

    def __init__(
        self,
        store: IncidentStore,
    ):
        self.store = store

    async def report(
        self,
        principal: Principal,
        payload: IncidentCreate,
    ) -> IncidentResponse:

        return await self.store.create(
            principal=principal,
            payload=payload,
        )

    async def resolve(
        self,
        principal: Principal,
        incident_id: str,
        payload: IncidentResolutionRequest,
    ) -> IncidentDetailResponse:

        return await self.store.resolve(
            principal=principal,
            incident_id=incident_id,
            payload=payload,
        )


incident_service = IncidentService(
    incident_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Incident Management"],
)


@router.post(
    "",
    response_model=IncidentResponse,
    status_code=201,
)
async def create_incident(
    payload: IncidentCreate,
    principal: CurrentPrincipal,
):
    return await incident_service.report(
        principal,
        payload,
    )


@router.get(
    "",
    response_model=list[IncidentResponse],
)
async def list_incidents(
    principal: CurrentPrincipal,
    warehouse_id: str,
    status: IncidentStatus | None = None,
    severity: IncidentSeverity | None = None,
    category: IncidentCategory | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await incident_store.list_records(
        principal=principal,
        warehouse_id=warehouse_id,
        status=status,
        severity=severity,
        category=category,
        limit=limit,
    )


@router.get(
    "/analytics/{warehouse_id}",
    response_model=IncidentAnalyticsResponse,
)
async def incident_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
):
    return await incident_store.analytics(
        principal=principal,
        warehouse_id=warehouse_id,
    )


@router.get(
    "/{incident_id}",
    response_model=IncidentDetailResponse,
)
async def get_incident(
    incident_id: str,
    principal: CurrentPrincipal,
):
    return await incident_store.get(
        principal=principal,
        incident_id=incident_id,
    )


@router.post(
    "/{incident_id}/acknowledge",
    response_model=IncidentDetailResponse,
)
async def acknowledge_incident(
    incident_id: str,
    payload: IncidentVersionRequest,
    principal: CurrentPrincipal,
):
    return await incident_store.acknowledge(
        principal=principal,
        incident_id=incident_id,
        payload=payload,
    )


@router.post(
    "/{incident_id}/assign",
    response_model=IncidentDetailResponse,
)
async def assign_incident(
    incident_id: str,
    payload: IncidentAssignmentRequest,
    principal: CurrentPrincipal,
):
    return await incident_store.assign(
        principal=principal,
        incident_id=incident_id,
        payload=payload,
    )


@router.post(
    "/{incident_id}/investigate",
    response_model=IncidentDetailResponse,
)
async def investigate_incident(
    incident_id: str,
    payload: IncidentVersionRequest,
    principal: CurrentPrincipal,
):
    return await incident_store.start_investigation(
        principal=principal,
        incident_id=incident_id,
        payload=payload,
    )


@router.post(
    "/{incident_id}/escalate",
    response_model=IncidentDetailResponse,
)
async def escalate_incident(
    incident_id: str,
    payload: IncidentEscalationRequest,
    principal: CurrentPrincipal,
):
    return await incident_store.escalate(
        principal=principal,
        incident_id=incident_id,
        payload=payload,
    )


@router.post(
    "/{incident_id}/resolve",
    response_model=IncidentDetailResponse,
)
async def resolve_incident(
    incident_id: str,
    payload: IncidentResolutionRequest,
    principal: CurrentPrincipal,
):
    return await incident_service.resolve(
        principal,
        incident_id,
        payload,
    )


@router.post(
    "/{incident_id}/reopen",
    response_model=IncidentDetailResponse,
)
async def reopen_incident(
    incident_id: str,
    payload: IncidentVersionRequest,
    principal: CurrentPrincipal,
):
    return await incident_store.reopen(
        principal=principal,
        incident_id=incident_id,
        payload=payload,
    )


@router.post(
    "/{incident_id}/close",
    response_model=IncidentDetailResponse,
)
async def close_incident(
    incident_id: str,
    payload: IncidentVersionRequest,
    principal: CurrentPrincipal,
):
    return await incident_store.close(
        principal=principal,
        incident_id=incident_id,
        payload=payload,
    )


__all__ = [
    "IncidentCategory",
    "IncidentSeverity",
    "IncidentStatus",
    "IncidentEventType",
    "IncidentCreate",
    "IncidentVersionRequest",
    "IncidentAssignmentRequest",
    "IncidentEscalationRequest",
    "IncidentResolutionRequest",
    "IncidentEventResponse",
    "IncidentResponse",
    "IncidentDetailResponse",
    "IncidentAnalyticsResponse",
    "IncidentRecord",
    "IncidentStore",
    "IncidentService",
    "incident_store",
    "incident_service",
    "router",
]
