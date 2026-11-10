from __future__ import annotations

"""Planned module: audit. Implementation pending."""

"""
backend/audit.py

Autonomous Retail Supply Chain AI 5.0
Centralized Audit Logging and Investigation API

Python 3.10+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Structured audit events
    - Tenant-isolated audit records
    - User, service, and AI agent actors
    - Inventory, supplier, procurement audits
    - Agent execution and approval audits
    - Authentication and security events
    - Correlation and request IDs
    - Sensitive-field redaction
    - Tamper-evident SHA-256 hash chain
    - Filtered audit search
    - Integrity verification
    - Bounded in-memory storage

SECURITY:
    - Only trusted backend services may append
    - No public audit-write endpoint
    - Authenticated, authorized read endpoints
    - Warehouse-scoped access controls
    - Never log passwords, tokens, or secrets

IMPORTANT:
    This is an in-memory prototype.

    Hash chaining detects changes only while
    trusted reference hashes remain intact.

    Production requires append-only durable
    storage, external hash anchoring, retention
    policies, and independent audit controls.
"""


import asyncio
import hashlib
import json
import re
import secrets

from collections import defaultdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
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

MAX_EVENTS_PER_TENANT = 100_000
MAX_METADATA_FIELDS = 30
MAX_METADATA_VALUE_LENGTH = 300
MAX_SEARCH_LIMIT = 200

GENESIS_HASH = "0" * 64

SENSITIVE_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "session",
    "private_key",
    "client_secret",
    "credit_card",
    "card_number",
    "cvv",
    "pin",
    "otp",
}

# Metadata must be operational, not a dump
# of request/response bodies or documents.
SAFE_METADATA_KEYS = {
    "operation",
    "status",
    "reason_code",
    "error_code",
    "resource_version",
    "previous_status",
    "new_status",
    "workflow",
    "agent_type",
    "tool_name",
    "approval_status",
    "quantity_delta",
    "event_source",
    "source_system",
    "policy_id",
    "permission",
    "duration_ms",
    "retry_count",
}


# ============================================================
# ENUMS
# ============================================================

class AuditCategory(str, Enum):
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    INVENTORY = "inventory"
    PROCUREMENT = "procurement"
    SUPPLIER = "supplier"
    WAREHOUSE = "warehouse"
    LOGISTICS = "logistics"
    SALES = "sales"
    FINANCE = "finance"
    AI_AGENT = "ai_agent"
    APPROVAL = "approval"
    NOTIFICATION = "notification"
    SECURITY = "security"
    SYSTEM = "system"


class AuditAction(str, Enum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    EXECUTE = "execute"
    APPROVE = "approve"
    REJECT = "reject"
    CANCEL = "cancel"
    LOGIN = "login"
    LOGOUT = "logout"
    ACCESS_DENIED = "access_denied"
    CONFIG_CHANGE = "config_change"
    EXPORT = "export"


class AuditOutcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"


class AuditSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


class AuditActorType(str, Enum):
    USER = "user"
    SERVICE = "service"
    AI_AGENT = "ai_agent"
    SYSTEM = "system"


# ============================================================
# INPUT MODEL — TRUSTED SERVICES ONLY
# ============================================================

class AuditEventCreate(BaseModel):

    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(
        min_length=1,
        max_length=128,
    )

    actor_id: str = Field(
        min_length=1,
        max_length=128,
    )

    actor_type: AuditActorType

    category: AuditCategory
    action: AuditAction
    outcome: AuditOutcome

    severity: AuditSeverity = AuditSeverity.INFO

    resource_type: str = Field(
        min_length=1,
        max_length=128,
    )

    resource_id: str | None = Field(
        default=None,
        max_length=128,
    )

    warehouse_id: str | None = Field(
        default=None,
        max_length=128,
    )

    request_id: str | None = Field(
        default=None,
        max_length=128,
    )

    correlation_id: str | None = Field(
        default=None,
        max_length=128,
    )

    agent_run_id: str | None = Field(
        default=None,
        max_length=128,
    )

    approval_id: str | None = Field(
        default=None,
        max_length=128,
    )

    description: str = Field(
        min_length=1,
        max_length=500,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator("metadata")
    @classmethod
    def validate_metadata(
        cls,
        value: dict[str, Any],
    ) -> dict[str, Any]:

        if len(value) > MAX_METADATA_FIELDS:
            raise ValueError(
                "Too many metadata fields"
            )

        return value


# ============================================================
# RESPONSE MODELS
# ============================================================

class AuditEventResponse(BaseModel):
    audit_id: str
    tenant_id: str

    sequence: int

    actor_id: str
    actor_type: AuditActorType

    category: AuditCategory
    action: AuditAction
    outcome: AuditOutcome
    severity: AuditSeverity

    resource_type: str
    resource_id: str | None
    warehouse_id: str | None

    request_id: str | None
    correlation_id: str | None

    agent_run_id: str | None
    approval_id: str | None

    description: str
    metadata: dict[str, Any]

    timestamp: datetime

    previous_hash: str
    event_hash: str


class AuditSearchResponse(BaseModel):
    total: int
    returned: int
    events: list[AuditEventResponse]


class AuditIntegrityResponse(BaseModel):
    tenant_id: str
    valid: bool
    checked_events: int
    first_invalid_sequence: int | None
    latest_hash: str
    checked_at: datetime
    note: str


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_key(value: str) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "_",
        value.lower(),
    ).strip("_")


def redact_metadata(
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """
    Strict metadata allowlist.

    Unknown fields are discarded, rather
    than accidentally persisted as secrets.
    """

    sanitized: dict[str, Any] = {}

    for key, value in metadata.items():

        normalized = normalize_key(key)

        if normalized in SENSITIVE_KEYS:
            continue

        if normalized not in SAFE_METADATA_KEYS:
            continue

        if isinstance(value, bool):
            safe_value: str | int | float | bool | None = value

        elif isinstance(value, int):
            safe_value = value

        elif isinstance(value, float):
            if not (
                float("-inf") < value < float("inf")
            ):
                continue
            safe_value = value

        elif value is None:
            safe_value = None

        elif isinstance(value, str):
            safe_value = value[
                :MAX_METADATA_VALUE_LENGTH
            ]

        else:
            continue

        sanitized[normalized] = safe_value

    return sanitized


def canonical_event_data(
    event: AuditEventResponse,
) -> str:

    data = event.model_dump(
        mode="json",
        exclude={"event_hash"},
    )

    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def calculate_event_hash(
    event: AuditEventResponse,
) -> str:

    canonical = canonical_event_data(event)

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def require_audit_access(
    principal: Principal,
    warehouse_id: str | None,
) -> None:

    # SYSTEM_CONFIGURE is used as a
    # restrictive prototype permission.
    #
    # Production should define a dedicated
    # AUDIT_READ permission.

    resource = ResourceContext(
        tenant_id=principal.tenant_id,
        warehouse_id=warehouse_id,
    )

    decision = permission_engine.evaluate(
        principal,
        Permission.SYSTEM_CONFIGURE,
        resource,
    )

    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail="Audit access denied",
        )

    allowed = principal.allowed_warehouse_ids

    if (
        warehouse_id is not None
        and allowed is not None
        and warehouse_id not in allowed
    ):
        raise HTTPException(
            status_code=403,
            detail="Warehouse scope denied",
        )


def require_global_audit_access(
    principal: Principal,
) -> None:
    """
    Global audit access is only available
    to principals with unrestricted
    warehouse scope.
    """

    if principal.allowed_warehouse_ids is not None:
        raise HTTPException(
            status_code=403,
            detail="Global audit access denied",
        )

    require_audit_access(
        principal,
        None,
    )


# ============================================================
# AUDIT STORE
# ============================================================

class AuditStore:

    def __init__(self):

        self._events: dict[
            str,
            list[AuditEventResponse],
        ] = defaultdict(list)

        self._lock = asyncio.Lock()

    async def append(
        self,
        payload: AuditEventCreate,
    ) -> AuditEventResponse:
        """
        Trusted internal ingestion only.

        Never expose this method through
        an unauthenticated HTTP endpoint.
        """

        async with self._lock:

            events = self._events[
                payload.tenant_id
            ]

            if (
                len(events)
                >= MAX_EVENTS_PER_TENANT
            ):
                raise RuntimeError(
                    "Audit storage capacity reached; "
                    "durable archival required"
                )

            sequence = len(events) + 1

            previous_hash = (
                events[-1].event_hash
                if events
                else GENESIS_HASH
            )

            event = AuditEventResponse(
                audit_id=secrets.token_urlsafe(20),
                tenant_id=payload.tenant_id,
                sequence=sequence,
                actor_id=payload.actor_id,
                actor_type=payload.actor_type,
                category=payload.category,
                action=payload.action,
                outcome=payload.outcome,
                severity=payload.severity,
                resource_type=payload.resource_type,
                resource_id=payload.resource_id,
                warehouse_id=payload.warehouse_id,
                request_id=payload.request_id,
                correlation_id=payload.correlation_id,
                agent_run_id=payload.agent_run_id,
                approval_id=payload.approval_id,
                description=payload.description,
                metadata=redact_metadata(
                    payload.metadata
                ),
                timestamp=utc_now(),
                previous_hash=previous_hash,
                event_hash="",
            )

            event.event_hash = calculate_event_hash(
                event
            )

            events.append(event)

            return event.model_copy(deep=True)

    async def get(
        self,
        *,
        tenant_id: str,
        audit_id: str,
    ) -> AuditEventResponse | None:

        async with self._lock:

            for event in self._events.get(
                tenant_id,
                (),
            ):
                if event.audit_id == audit_id:
                    return event.model_copy(
                        deep=True
                    )

        return None

    async def search(
        self,
        *,
        tenant_id: str,
        category: AuditCategory | None = None,
        action: AuditAction | None = None,
        outcome: AuditOutcome | None = None,
        actor_id: str | None = None,
        warehouse_id: str | None = None,
        resource_id: str | None = None,
        correlation_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        allowed_warehouse_ids: frozenset[str] | None = None,
        include_unscoped: bool = True,
    ) -> AuditSearchResponse:

        async with self._lock:

            events = list(
                self._events.get(
                    tenant_id,
                    (),
                )
            )

        filtered = []

        for event in reversed(events):

            if (
                allowed_warehouse_ids is not None
                and event.warehouse_id
                not in allowed_warehouse_ids
            ):
                continue

            if (
                not include_unscoped
                and event.warehouse_id is None
            ):
                continue

            if (
                warehouse_id is not None
                and event.warehouse_id
                != warehouse_id
            ):
                continue

            if (
                category is not None
                and event.category != category
            ):
                continue

            if (
                action is not None
                and event.action != action
            ):
                continue

            if (
                outcome is not None
                and event.outcome != outcome
            ):
                continue

            if (
                actor_id is not None
                and event.actor_id != actor_id
            ):
                continue

            if (
                resource_id is not None
                and event.resource_id != resource_id
            ):
                continue

            if (
                correlation_id is not None
                and event.correlation_id
                != correlation_id
            ):
                continue

            if (
                since is not None
                and event.timestamp < since
            ):
                continue

            if (
                until is not None
                and event.timestamp > until
            ):
                continue

            filtered.append(event)

        return AuditSearchResponse(
            total=len(filtered),
            returned=min(
                len(filtered),
                limit,
            ),
            events=[
                event.model_copy(deep=True)
                for event in filtered[:limit]
            ],
        )

    async def verify_integrity(
        self,
        *,
        tenant_id: str,
    ) -> AuditIntegrityResponse:

        async with self._lock:

            events = [
                event.model_copy(deep=True)
                for event in self._events.get(
                    tenant_id,
                    (),
                )
            ]

        expected_previous_hash = GENESIS_HASH

        for index, event in enumerate(
            events,
            start=1,
        ):

            if (
                event.sequence != index
                or event.previous_hash
                != expected_previous_hash
                or event.event_hash
                != calculate_event_hash(event)
            ):

                return AuditIntegrityResponse(
                    tenant_id=tenant_id,
                    valid=False,
                    checked_events=index,
                    first_invalid_sequence=index,
                    latest_hash=(
                        expected_previous_hash
                    ),
                    checked_at=utc_now(),
                    note=(
                        "Audit chain integrity "
                        "verification failed."
                    ),
                )

            expected_previous_hash = (
                event.event_hash
            )

        return AuditIntegrityResponse(
            tenant_id=tenant_id,
            valid=True,
            checked_events=len(events),
            first_invalid_sequence=None,
            latest_hash=expected_previous_hash,
            checked_at=utc_now(),
            note=(
                "Retained in-memory audit chain "
                "is internally consistent. "
                "This does not establish "
                "independent tamper resistance."
            ),
        )


audit_store = AuditStore()


# ============================================================
# TRUSTED AUDIT SERVICE
# ============================================================

class AuditService:

    def __init__(
        self,
        store: AuditStore,
    ):
        self.store = store

    async def record(
        self,
        payload: AuditEventCreate,
    ) -> AuditEventResponse:

        return await self.store.append(
            payload
        )

    async def record_agent_event(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        agent_run_id: str,
        action: AuditAction,
        outcome: AuditOutcome,
        warehouse_id: str | None = None,
        request_id: str | None = None,
    ) -> AuditEventResponse:

        return await self.record(
            AuditEventCreate(
                tenant_id=tenant_id,
                actor_id=actor_id,
                actor_type=AuditActorType.AI_AGENT,
                category=AuditCategory.AI_AGENT,
                action=action,
                outcome=outcome,
                resource_type="agent_run",
                resource_id=agent_run_id,
                warehouse_id=warehouse_id,
                request_id=request_id,
                agent_run_id=agent_run_id,
                description="AI agent lifecycle event",
            )
        )

    async def record_approval_event(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        approval_id: str,
        action: AuditAction,
        outcome: AuditOutcome,
        warehouse_id: str | None = None,
    ) -> AuditEventResponse:

        return await self.record(
            AuditEventCreate(
                tenant_id=tenant_id,
                actor_id=actor_id,
                actor_type=AuditActorType.USER,
                category=AuditCategory.APPROVAL,
                action=action,
                outcome=outcome,
                resource_type="approval",
                resource_id=approval_id,
                warehouse_id=warehouse_id,
                approval_id=approval_id,
                description="Human approval decision",
            )
        )


audit_service = AuditService(
    audit_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix="/api/v1/audit",
    tags=["Audit & Compliance"],
)


@router.get(
    "/events",
    response_model=AuditSearchResponse,
)
async def search_audit_events(
    principal: CurrentPrincipal,
    category: AuditCategory | None = None,
    action: AuditAction | None = None,
    outcome: AuditOutcome | None = None,
    actor_id: str | None = None,
    warehouse_id: str | None = None,
    resource_id: str | None = None,
    correlation_id: str | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_SEARCH_LIMIT,
    ),
):

    if warehouse_id is None:
        require_global_audit_access(
            principal
        )
    else:
        require_audit_access(
            principal,
            warehouse_id,
        )

    return await audit_store.search(
        tenant_id=principal.tenant_id,
        category=category,
        action=action,
        outcome=outcome,
        actor_id=actor_id,
        warehouse_id=warehouse_id,
        resource_id=resource_id,
        correlation_id=correlation_id,
        limit=limit,
        allowed_warehouse_ids=(
            principal.allowed_warehouse_ids
        ),
        include_unscoped=(
            principal.allowed_warehouse_ids
            is None
        ),
    )


@router.get(
    "/events/{audit_id}",
    response_model=AuditEventResponse,
)
async def get_audit_event(
    audit_id: str,
    principal: CurrentPrincipal,
):

    event = await audit_store.get(
        tenant_id=principal.tenant_id,
        audit_id=audit_id,
    )

    if event is None:
        raise HTTPException(
            status_code=404,
            detail="Audit event not found",
        )

    if event.warehouse_id is None:
        require_global_audit_access(
            principal
        )
    else:
        require_audit_access(
            principal,
            event.warehouse_id,
        )

    return event


@router.get(
    "/integrity",
    response_model=AuditIntegrityResponse,
)
async def verify_audit_integrity(
    principal: CurrentPrincipal,
):

    require_global_audit_access(
        principal
    )

    return await audit_store.verify_integrity(
        tenant_id=principal.tenant_id,
    )


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "AuditCategory",
    "AuditAction",
    "AuditOutcome",
    "AuditSeverity",
    "AuditActorType",
    "AuditEventCreate",
    "AuditEventResponse",
    "AuditSearchResponse",
    "AuditIntegrityResponse",
    "AuditStore",
    "AuditService",
    "audit_store",
    "audit_service",
    "router",
]
