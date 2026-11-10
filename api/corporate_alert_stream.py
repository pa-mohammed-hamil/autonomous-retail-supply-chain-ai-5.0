from __future__ import annotations

"""Planned module: corporate alert stream. Implementation pending."""

"""
backend/corporate_alert_stream.py

Autonomous Retail Supply Chain AI 5.0

Real-time corporate alert streaming.

Python 3.10+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Corporate alert creation
    - Alert severity classification
    - Department-based routing
    - Tenant-isolated alert storage
    - WebSocket notification delivery
    - Alert acknowledgment
    - Alert resolution
    - Alert deduplication
    - Executive and operations alerts
    - Permission-aware access
    - Audit-friendly event structure

Important:
    In-memory storage is for development.
    Production requires PostgreSQL,
    transactional outbox, and Redis Streams.
"""


import asyncio
import hashlib
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
# ENUMS
# ============================================================

class CorporateAlertSeverity(str, Enum):

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CorporateAlertStatus(str, Enum):

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class CorporateDepartment(str, Enum):

    EXECUTIVE = "executive"
    OPERATIONS = "operations"
    INVENTORY = "inventory"
    PROCUREMENT = "procurement"
    WAREHOUSE = "warehouse"
    LOGISTICS = "logistics"
    FINANCE = "finance"
    SECURITY = "security"
    AI_OPERATIONS = "ai_operations"


class CorporateAlertCategory(str, Enum):

    LOW_STOCK = "low_stock"
    STOCKOUT = "stockout"
    DEMAND_SPIKE = "demand_spike"
    SUPPLIER_RISK = "supplier_risk"
    PROCUREMENT_DELAY = "procurement_delay"
    SHIPMENT_DELAY = "shipment_delay"
    WAREHOUSE_INCIDENT = "warehouse_incident"
    FINANCIAL_ANOMALY = "financial_anomaly"
    PRODUCT_QUALITY = "product_quality"
    AI_AGENT_FAILURE = "ai_agent_failure"
    SECURITY_INCIDENT = "security_incident"
    SYSTEM_OUTAGE = "system_outage"


# ============================================================
# CATEGORY POLICIES
# ============================================================

CATEGORY_DEPARTMENTS = {
    CorporateAlertCategory.LOW_STOCK: (
        CorporateDepartment.INVENTORY
    ),
    CorporateAlertCategory.STOCKOUT: (
        CorporateDepartment.INVENTORY
    ),
    CorporateAlertCategory.DEMAND_SPIKE: (
        CorporateDepartment.OPERATIONS
    ),
    CorporateAlertCategory.SUPPLIER_RISK: (
        CorporateDepartment.PROCUREMENT
    ),
    CorporateAlertCategory.PROCUREMENT_DELAY: (
        CorporateDepartment.PROCUREMENT
    ),
    CorporateAlertCategory.SHIPMENT_DELAY: (
        CorporateDepartment.LOGISTICS
    ),
    CorporateAlertCategory.WAREHOUSE_INCIDENT: (
        CorporateDepartment.WAREHOUSE
    ),
    CorporateAlertCategory.FINANCIAL_ANOMALY: (
        CorporateDepartment.FINANCE
    ),
    CorporateAlertCategory.PRODUCT_QUALITY: (
        CorporateDepartment.OPERATIONS
    ),
    CorporateAlertCategory.AI_AGENT_FAILURE: (
        CorporateDepartment.AI_OPERATIONS
    ),
    CorporateAlertCategory.SECURITY_INCIDENT: (
        CorporateDepartment.SECURITY
    ),
    CorporateAlertCategory.SYSTEM_OUTAGE: (
        CorporateDepartment.AI_OPERATIONS
    ),
}


CATEGORY_PERMISSIONS = {
    CorporateAlertCategory.LOW_STOCK:
        Permission.INVENTORY_READ,
    CorporateAlertCategory.STOCKOUT:
        Permission.INVENTORY_READ,
    CorporateAlertCategory.DEMAND_SPIKE:
        Permission.ANALYTICS_READ,
    CorporateAlertCategory.SUPPLIER_RISK:
        Permission.SUPPLIER_READ,
    CorporateAlertCategory.PROCUREMENT_DELAY:
        Permission.PROCUREMENT_READ,
    CorporateAlertCategory.SHIPMENT_DELAY:
        Permission.LOGISTICS_READ,
    CorporateAlertCategory.WAREHOUSE_INCIDENT:
        Permission.INCIDENT_READ,
    CorporateAlertCategory.FINANCIAL_ANOMALY:
        Permission.FINANCE_READ,
    CorporateAlertCategory.PRODUCT_QUALITY:
        Permission.PRODUCT_READ,
    CorporateAlertCategory.AI_AGENT_FAILURE:
        Permission.AI_AGENT_READ,
    CorporateAlertCategory.SECURITY_INCIDENT:
        Permission.AUDIT_READ,
    CorporateAlertCategory.SYSTEM_OUTAGE:
        Permission.SYSTEM_CONFIGURE,
}


# ============================================================
# ALERT SCHEMAS
# ============================================================

class CorporateAlertCreate(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    category: CorporateAlertCategory

    severity: CorporateAlertSeverity

    title: str = Field(
        min_length=3,
        max_length=160,
    )

    message: str = Field(
        min_length=3,
        max_length=2000,
    )

    resource_id: str | None = Field(
        default=None,
        max_length=128,
    )

    warehouse_id: str | None = Field(
        default=None,
        max_length=128,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict
    )


class CorporateAlertResponse(BaseModel):

    alert_id: str
    tenant_id: str

    category: CorporateAlertCategory
    department: CorporateDepartment

    severity: CorporateAlertSeverity
    status: CorporateAlertStatus

    title: str
    message: str

    resource_id: str | None
    warehouse_id: str | None

    created_at: datetime
    updated_at: datetime

    acknowledged_by: str | None
    resolved_by: str | None

    occurrence_count: int


# ============================================================
# INTERNAL ALERT RECORD
# ============================================================

@dataclass
class CorporateAlertRecord:

    alert_id: str
    tenant_id: str

    category: CorporateAlertCategory
    department: CorporateDepartment

    severity: CorporateAlertSeverity
    status: CorporateAlertStatus

    title: str
    message: str

    resource_id: str | None
    warehouse_id: str | None

    metadata: dict[str, Any]

    created_at: datetime
    updated_at: datetime

    acknowledged_by: str | None = None
    resolved_by: str | None = None

    occurrence_count: int = 1

    fingerprint: str = ""


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def alert_fingerprint(
    tenant_id: str,
    category: CorporateAlertCategory,
    resource_id: str | None,
    warehouse_id: str | None,
) -> str:

    payload = "|".join([
        tenant_id,
        category.value,
        resource_id or "",
        warehouse_id or "",
    ])

    return hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()


def alert_to_response(
    alert: CorporateAlertRecord,
) -> CorporateAlertResponse:

    return CorporateAlertResponse(
        alert_id=alert.alert_id,
        tenant_id=alert.tenant_id,
        category=alert.category,
        department=alert.department,
        severity=alert.severity,
        status=alert.status,
        title=alert.title,
        message=alert.message,
        resource_id=alert.resource_id,
        warehouse_id=alert.warehouse_id,
        created_at=alert.created_at,
        updated_at=alert.updated_at,
        acknowledged_by=alert.acknowledged_by,
        resolved_by=alert.resolved_by,
        occurrence_count=alert.occurrence_count,
    )


# ============================================================
# ALERT STORE
# ============================================================

class CorporateAlertStore:

    def __init__(self):

        self._alerts: dict[
            str, CorporateAlertRecord
        ] = {}

        self._fingerprints: dict[
            tuple[str, str], str
        ] = {}

        self._lock = asyncio.Lock()

    async def create(
        self,
        tenant_id: str,
        payload: CorporateAlertCreate,
    ) -> CorporateAlertRecord:

        fingerprint = alert_fingerprint(
            tenant_id,
            payload.category,
            payload.resource_id,
            payload.warehouse_id,
        )

        now = utc_now()

        async with self._lock:

            existing_id = (
                self._fingerprints.get(
                    (tenant_id, fingerprint)
                )
            )

            if existing_id is not None:

                existing = self._alerts.get(
                    existing_id
                )

                if (
                    existing is not None
                    and existing.status
                    != CorporateAlertStatus.RESOLVED
                ):

                    existing.occurrence_count += 1
                    existing.updated_at = now
                    existing.message = payload.message

                    # Severity escalation should
                    # never silently downgrade.
                    severity_order = {
                        CorporateAlertSeverity.INFO: 0,
                        CorporateAlertSeverity.LOW: 1,
                        CorporateAlertSeverity.MEDIUM: 2,
                        CorporateAlertSeverity.HIGH: 3,
                        CorporateAlertSeverity.CRITICAL: 4,
                    }

                    if severity_order[
                        payload.severity
                    ] > severity_order[
                        existing.severity
                    ]:
                        existing.severity = (
                            payload.severity
                        )

                    return existing

            alert_id = (
                secrets.token_urlsafe(20)
            )

            alert = CorporateAlertRecord(
                alert_id=alert_id,
                tenant_id=tenant_id,
                category=payload.category,
                department=(
                    CATEGORY_DEPARTMENTS[
                        payload.category
                    ]
                ),
                severity=payload.severity,
                status=CorporateAlertStatus.OPEN,
                title=payload.title,
                message=payload.message,
                resource_id=payload.resource_id,
                warehouse_id=payload.warehouse_id,
                metadata=payload.metadata,
                created_at=now,
                updated_at=now,
                fingerprint=fingerprint,
            )

            self._alerts[
                alert_id
            ] = alert

            self._fingerprints[
                (tenant_id, fingerprint)
            ] = alert_id

            return alert

    async def get(
        self,
        tenant_id: str,
        alert_id: str,
    ) -> CorporateAlertRecord | None:

        async with self._lock:

            alert = self._alerts.get(
                alert_id
            )

            if (
                alert is None
                or alert.tenant_id != tenant_id
            ):
                return None

            return alert

    async def list_alerts(
        self,
        tenant_id: str,
        *,
        status: CorporateAlertStatus | None = None,
        limit: int = 50,
    ) -> list[CorporateAlertRecord]:

        async with self._lock:

            alerts = [
                alert
                for alert in self._alerts.values()
                if (
                    alert.tenant_id == tenant_id
                    and (
                        status is None
                        or alert.status == status
                    )
                )
            ]

        alerts.sort(
            key=lambda item: item.created_at,
            reverse=True,
        )

        return alerts[:limit]

    async def acknowledge(
        self,
        tenant_id: str,
        alert_id: str,
        principal_id: str,
    ) -> CorporateAlertRecord | None:

        async with self._lock:

            alert = self._alerts.get(
                alert_id
            )

            if (
                alert is None
                or alert.tenant_id != tenant_id
            ):
                return None

            if alert.status == CorporateAlertStatus.OPEN:

                alert.status = (
                    CorporateAlertStatus.ACKNOWLEDGED
                )

                alert.acknowledged_by = principal_id
                alert.updated_at = utc_now()

            return alert

    async def resolve(
        self,
        tenant_id: str,
        alert_id: str,
        principal_id: str,
    ) -> CorporateAlertRecord | None:

        async with self._lock:

            alert = self._alerts.get(
                alert_id
            )

            if (
                alert is None
                or alert.tenant_id != tenant_id
            ):
                return None

            if alert.status != CorporateAlertStatus.RESOLVED:

                alert.status = (
                    CorporateAlertStatus.RESOLVED
                )

                alert.resolved_by = principal_id
                alert.updated_at = utc_now()

                self._fingerprints.pop(
                    (
                        tenant_id,
                        alert.fingerprint,
                    ),
                    None,
                )

            return alert


alert_store = CorporateAlertStore()


# ============================================================
# AUTHORIZATION
# ============================================================

def require_alert_access(
    principal: Principal,
    alert: CorporateAlertRecord,
) -> None:

    if principal.tenant_id != alert.tenant_id:

        raise HTTPException(
            status_code=404,
            detail="Alert not found",
        )

    permission = CATEGORY_PERMISSIONS[
        alert.category
    ]

    decision = permission_engine.evaluate(
        principal,
        permission,
    )

    if not decision.allowed:

        raise HTTPException(
            status_code=403,
            detail="Alert access denied",
        )

    allowed_warehouses = (
        principal.allowed_warehouse_ids
    )

    if (
        alert.warehouse_id is not None
        and allowed_warehouses is not None
        and alert.warehouse_id
        not in allowed_warehouses
    ):

        raise HTTPException(
            status_code=403,
            detail="Warehouse access denied",
        )


# ============================================================
# REALTIME DELIVERY
# ============================================================

async def publish_corporate_alert(
    alert: CorporateAlertRecord,
) -> int:
    """
    Deliver a minimal alert notification.

    The existing ConnectionManager handles
    tenant routing and base permissions.

    For restricted warehouses, a
    resource-aware subscription mechanism
    is required before broadcasting.
    """

    if alert.warehouse_id is not None:
        # Do not broadcast restricted
        # warehouse alerts tenant-wide.
        return 0

    return await connection_manager.broadcast_to_tenant(
        tenant_id=alert.tenant_id,
        required_permission=(
            CATEGORY_PERMISSIONS[
                alert.category
            ]
        ),
        message=RealtimeMessage(
            event=RealtimeEventType.NOTIFICATION,
            data={
                "kind": "corporate_alert",
                "alert_id": alert.alert_id,
                "category": alert.category.value,
                "severity": alert.severity.value,
                "status": alert.status.value,
            },
        ),
    )


# ============================================================
# SERVICE
# ============================================================

class CorporateAlertStreamService:

    def __init__(
        self,
        store: CorporateAlertStore,
    ):
        self.store = store

    async def create_alert(
        self,
        *,
        tenant_id: str,
        payload: CorporateAlertCreate,
    ) -> CorporateAlertRecord:

        alert = await self.store.create(
            tenant_id,
            payload,
        )

        await publish_corporate_alert(
            alert
        )

        return alert

    async def acknowledge_alert(
        self,
        *,
        principal: Principal,
        alert_id: str,
    ) -> CorporateAlertRecord:

        alert = await self.store.get(
            principal.tenant_id,
            alert_id,
        )

        if alert is None:
            raise HTTPException(
                status_code=404,
                detail="Alert not found",
            )

        require_alert_access(
            principal,
            alert,
        )

        permission_engine.require(
            principal,
            Permission.INCIDENT_WRITE,
        )

        updated = await self.store.acknowledge(
            principal.tenant_id,
            alert_id,
            principal.principal_id,
        )

        assert updated is not None

        await publish_corporate_alert(
            updated
        )

        return updated

    async def resolve_alert(
        self,
        *,
        principal: Principal,
        alert_id: str,
    ) -> CorporateAlertRecord:

        alert = await self.store.get(
            principal.tenant_id,
            alert_id,
        )

        if alert is None:
            raise HTTPException(
                status_code=404,
                detail="Alert not found",
            )

        require_alert_access(
            principal,
            alert,
        )

        permission_engine.require(
            principal,
            Permission.INCIDENT_WRITE,
        )

        updated = await self.store.resolve(
            principal.tenant_id,
            alert_id,
            principal.principal_id,
        )

        assert updated is not None

        await publish_corporate_alert(
            updated
        )

        return updated


corporate_alert_stream = (
    CorporateAlertStreamService(
        alert_store
    )
)


# ============================================================
# API ROUTER
# ============================================================

router = APIRouter(
    prefix="/api/v1/corporate-alerts",
    tags=["Corporate Alerts"],
)


@router.post(
    "",
    response_model=CorporateAlertResponse,
)
async def create_corporate_alert(
    payload: CorporateAlertCreate,
    principal: CurrentPrincipal,
):

    permission_engine.require(
        principal,
        Permission.INCIDENT_WRITE,
    )

    # Require permission for the alert's
    # category as well.
    permission_engine.require(
        principal,
        CATEGORY_PERMISSIONS[
            payload.category
        ],
    )

    if (
        payload.warehouse_id is not None
        and principal.allowed_warehouse_ids
        is not None
        and payload.warehouse_id
        not in principal.allowed_warehouse_ids
    ):
        raise HTTPException(
            status_code=403,
            detail="Warehouse access denied",
        )

    alert = (
        await corporate_alert_stream.create_alert(
            tenant_id=principal.tenant_id,
            payload=payload,
        )
    )

    return alert_to_response(alert)


@router.get(
    "",
    response_model=list[CorporateAlertResponse],
)
async def list_corporate_alerts(
    principal: CurrentPrincipal,
    status: CorporateAlertStatus | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
    ),
):

    alerts = await alert_store.list_alerts(
        principal.tenant_id,
        status=status,
        limit=limit,
    )

    visible = []

    for alert in alerts:

        try:
            require_alert_access(
                principal,
                alert,
            )

        except HTTPException:
            continue

        visible.append(
            alert_to_response(alert)
        )

    return visible


@router.get(
    "/{alert_id}",
    response_model=CorporateAlertResponse,
)
async def get_corporate_alert(
    alert_id: str,
    principal: CurrentPrincipal,
):

    alert = await alert_store.get(
        principal.tenant_id,
        alert_id,
    )

    if alert is None:
        raise HTTPException(
            status_code=404,
            detail="Alert not found",
        )

    require_alert_access(
        principal,
        alert,
    )

    return alert_to_response(alert)


@router.post(
    "/{alert_id}/acknowledge",
    response_model=CorporateAlertResponse,
)
async def acknowledge_corporate_alert(
    alert_id: str,
    principal: CurrentPrincipal,
):

    alert = (
        await corporate_alert_stream.acknowledge_alert(
            principal=principal,
            alert_id=alert_id,
        )
    )

    return alert_to_response(alert)


@router.post(
    "/{alert_id}/resolve",
    response_model=CorporateAlertResponse,
)
async def resolve_corporate_alert(
    alert_id: str,
    principal: CurrentPrincipal,
):

    alert = (
        await corporate_alert_stream.resolve_alert(
            principal=principal,
            alert_id=alert_id,
        )
    )

    return alert_to_response(alert)
