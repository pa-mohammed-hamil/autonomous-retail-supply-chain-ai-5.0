from __future__ import annotations

"""Planned module: alert repository. Implementation pending."""

"""
backend/repositories/alert_repository.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+ | Standard library only

Features:
- Tenant-isolated alert storage
- Warehouse-scoped authorization
- Source-event idempotency
- Optimistic concurrency
- Alert search and filtering
- Pagination
- Audit history
- Transactional-style in-memory outbox
- JSON export

Reference implementation, not durable storage.
"""


import copy
import json
import threading
import uuid

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def required(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 255
    ):
        raise ValueError(f"Invalid {name}")
    return value.strip()


class AlertSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class AlertActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str] = frozenset()
    is_active: bool = True


@dataclass
class AlertRecord:
    alert_id: str
    tenant_id: str
    warehouse_id: str
    category: str
    severity: AlertSeverity
    title: str
    message: str
    source_event_id: str
    status: AlertStatus
    assigned_to: str | None
    created_at: str
    updated_at: str
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AlertAuditRecord:
    audit_id: str
    tenant_id: str
    alert_id: str
    actor_id: str
    action: str
    timestamp: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class AlertOutboxRecord:
    event_id: str
    tenant_id: str
    alert_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: str
    delivered: bool = False


class RetailAlertRepository:
    WRITER_ROLES = frozenset({
        "corporate_admin",
        "operations_manager",
        "warehouse_manager",
        "inventory_manager",
        "security_manager",
        "alert_operator",
    })

    READER_ROLES = WRITER_ROLES | frozenset({
        "inventory_analyst",
        "logistics_manager",
        "procurement_manager",
        "business_analyst",
    })

    def __init__(self, tenant_id: str):
        self.tenant_id = required(tenant_id, "tenant_id")
        self._lock = threading.RLock()
        self._alerts: dict[str, AlertRecord] = {}
        self._source_index: dict[str, str] = {}
        self._audit: list[AlertAuditRecord] = []
        self._outbox: dict[str, AlertOutboxRecord] = {}

    def _authorize(
        self,
        actor: AlertActor,
        roles: frozenset[str],
        warehouse_id: str | None = None,
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.user_id.strip()
            or not actor.roles.intersection(roles)
        ):
            raise PermissionError("Alert access denied")

        if (
            warehouse_id is not None
            and "corporate_admin" not in actor.roles
            and warehouse_id not in actor.warehouse_ids
        ):
            raise PermissionError("Warehouse access denied")

    def _get(self, alert_id: str) -> AlertRecord:
        alert = self._alerts.get(alert_id)
        if alert is None:
            raise KeyError("Alert not found")
        return alert

    def _record(
        self,
        actor: AlertActor,
        alert: AlertRecord,
        action: str,
        details: dict | None = None,
    ) -> None:
        self._audit.append(AlertAuditRecord(
            audit_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            alert_id=alert.alert_id,
            actor_id=actor.user_id,
            action=action,
            timestamp=utc_now(),
            details=copy.deepcopy(details or {}),
        ))

        event = AlertOutboxRecord(
            event_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            alert_id=alert.alert_id,
            event_type=f"alert.{action}",
            payload={
                "alert_id": alert.alert_id,
                "warehouse_id": alert.warehouse_id,
                "severity": alert.severity.value,
                "status": alert.status.value,
                "version": alert.version,
            },
            created_at=utc_now(),
        )

        self._outbox[event.event_id] = event

    def create(
        self,
        actor: AlertActor,
        warehouse_id: str,
        category: str,
        severity: AlertSeverity,
        title: str,
        message: str,
        source_event_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> AlertRecord:
        warehouse_id = required(
            warehouse_id, "warehouse_id"
        )
        self._authorize(
            actor, self.WRITER_ROLES, warehouse_id
        )

        category = required(category, "category")
        title = required(title, "title")
        message = required(message, "message")
        source_event_id = required(
            source_event_id, "source_event_id"
        )

        if not isinstance(severity, AlertSeverity):
            raise ValueError("Invalid alert severity")

        if metadata is not None and not isinstance(
            metadata, dict
        ):
            raise ValueError("Invalid metadata")

        with self._lock:
            existing_id = self._source_index.get(
                source_event_id
            )

            if existing_id is not None:
                existing = self._get(existing_id)
                if (
                    existing.warehouse_id != warehouse_id
                    or existing.category != category
                    or existing.severity != severity
                    or existing.title != title
                    or existing.message != message
                    or existing.metadata != (metadata or {})
                ):
                    raise ValueError(
                        "Conflicting source event"
                    )
                return copy.deepcopy(existing)

            current = utc_now()

            alert = AlertRecord(
                alert_id=str(uuid.uuid4()),
                tenant_id=self.tenant_id,
                warehouse_id=warehouse_id,
                category=category,
                severity=severity,
                title=title,
                message=message,
                source_event_id=source_event_id,
                status=AlertStatus.OPEN,
                assigned_to=None,
                created_at=current,
                updated_at=current,
                metadata=copy.deepcopy(metadata or {}),
            )

            self._alerts[alert.alert_id] = alert
            self._source_index[source_event_id] = (
                alert.alert_id
            )

            self._record(actor, alert, "created")
            return copy.deepcopy(alert)

    def get(
        self,
        actor: AlertActor,
        alert_id: str,
    ) -> AlertRecord:
        with self._lock:
            alert = self._get(alert_id)
            self._authorize(
                actor, self.READER_ROLES,
                alert.warehouse_id,
            )
            return copy.deepcopy(alert)

    def update_status(
        self,
        actor: AlertActor,
        alert_id: str,
        expected_version: int,
        new_status: AlertStatus,
        assigned_to: str | None = None,
    ) -> AlertRecord:
        if not isinstance(new_status, AlertStatus):
            raise ValueError("Invalid alert status")

        allowed = {
            AlertStatus.OPEN: {
                AlertStatus.ACKNOWLEDGED,
                AlertStatus.ESCALATED,
            },
            AlertStatus.ACKNOWLEDGED: {
                AlertStatus.ESCALATED,
                AlertStatus.RESOLVED,
            },
            AlertStatus.ESCALATED: {
                AlertStatus.ACKNOWLEDGED,
                AlertStatus.RESOLVED,
            },
            AlertStatus.RESOLVED: {
                AlertStatus.OPEN,
            },
        }

        with self._lock:
            alert = self._get(alert_id)
            self._authorize(
                actor, self.WRITER_ROLES,
                alert.warehouse_id,
            )

            if alert.version != expected_version:
                raise ValueError("Version conflict")

            if new_status not in allowed[alert.status]:
                raise ValueError(
                    "Invalid status transition"
                )

            if assigned_to is not None:
                alert.assigned_to = required(
                    assigned_to, "assigned_to"
                )

            alert.status = new_status
            alert.version += 1
            alert.updated_at = utc_now()

            self._record(
                actor,
                alert,
                "status_updated",
                {"new_status": new_status.value},
            )

            return copy.deepcopy(alert)

    def list_alerts(
        self,
        actor: AlertActor,
        *,
        warehouse_id: str | None = None,
        severity: AlertSeverity | None = None,
        status: AlertStatus | None = None,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AlertRecord]:
        self._authorize(actor, self.READER_ROLES)

        if (
            type(limit) is not int
            or type(offset) is not int
            or not 1 <= limit <= 500
            or offset < 0
        ):
            raise ValueError("Invalid pagination")

        if warehouse_id is not None:
            self._authorize(
                actor, self.READER_ROLES,
                warehouse_id,
            )

        with self._lock:
            alerts = [
                alert
                for alert in self._alerts.values()
                if (
                    (
                        "corporate_admin" in actor.roles
                        or alert.warehouse_id
                        in actor.warehouse_ids
                    )
                    and (
                        warehouse_id is None
                        or alert.warehouse_id == warehouse_id
                    )
                    and (
                        severity is None
                        or alert.severity == severity
                    )
                    and (
                        status is None
                        or alert.status == status
                    )
                    and (
                        category is None
                        or alert.category == category
                    )
                )
            ]

            alerts.sort(
                key=lambda a: (
                    a.created_at, a.alert_id
                ),
                reverse=True,
            )

            return copy.deepcopy(
                alerts[offset:offset + limit]
            )

    def count(
        self,
        actor: AlertActor,
        status: AlertStatus | None = None,
    ) -> int:
        self._authorize(actor, self.READER_ROLES)

        with self._lock:
            return sum(
                1
                for alert in self._alerts.values()
                if (
                    (
                        "corporate_admin" in actor.roles
                        or alert.warehouse_id
                        in actor.warehouse_ids
                    )
                    and (
                        status is None
                        or alert.status == status
                    )
                )
            )

    def pending_events(
        self,
        actor: AlertActor,
    ) -> list[AlertOutboxRecord]:
        self._authorize(actor, self.WRITER_ROLES)

        with self._lock:
            return [
                copy.deepcopy(event)
                for event in self._outbox.values()
                if (
                    not event.delivered
                    and (
                        "corporate_admin" in actor.roles
                        or self._alerts[
                            event.alert_id
                        ].warehouse_id
                        in actor.warehouse_ids
                    )
                )
            ]

    def mark_event_delivered(
        self,
        actor: AlertActor,
        event_id: str,
    ) -> None:
        with self._lock:
            event = self._outbox.get(event_id)

            if event is None:
                raise KeyError("Outbox event not found")

            alert = self._get(event.alert_id)
            self._authorize(
                actor, self.WRITER_ROLES,
                alert.warehouse_id,
            )

            event.delivered = True

    def audit_history(
        self,
        actor: AlertActor,
        alert_id: str,
    ) -> list[AlertAuditRecord]:
        self.get(actor, alert_id)

        with self._lock:
            return [
                copy.deepcopy(event)
                for event in self._audit
                if event.alert_id == alert_id
            ]

    def export_json(
        self,
        actor: AlertActor,
        output_path: str | Path,
    ) -> Path:
        self._authorize(actor, self.READER_ROLES)

        with self._lock:
            alerts = [
                copy.deepcopy(alert)
                for alert in self._alerts.values()
                if (
                    "corporate_admin" in actor.roles
                    or alert.warehouse_id
                    in actor.warehouse_ids
                )
            ]

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(
            json.dumps(
                [asdict(a) for a in alerts],
                indent=2,
                default=lambda obj: (
                    obj.value
                    if isinstance(obj, Enum)
                    else str(obj)
                ),
            ),
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    repo = RetailAlertRepository("demo")

    manager = AlertActor(
        user_id="MANAGER001",
        tenant_id="demo",
        roles=frozenset({"warehouse_manager"}),
        warehouse_ids=frozenset({"WH001"}),
    )

    alert = repo.create(
        actor=manager,
        warehouse_id="WH001",
        category="inventory",
        severity=AlertSeverity.HIGH,
        title="Low stock detected",
        message="SKU001 stock below reorder point",
        source_event_id="INVENTORY-EVENT-001",
        metadata={"sku": "SKU001"},
    )

    alert = repo.update_status(
        manager,
        alert.alert_id,
        alert.version,
        AlertStatus.ACKNOWLEDGED,
        assigned_to="MANAGER001",
    )

    print("Alert:", alert.title)
    print("Status:", alert.status.value)
    print("Open alerts:", repo.count(manager, AlertStatus.OPEN))
    print("Audit events:", len(
        repo.audit_history(manager, alert.alert_id)
    ))
