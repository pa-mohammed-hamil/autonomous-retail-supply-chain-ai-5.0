from __future__ import annotations

"""Planned module: employee alert service. Implementation pending."""

"""
backend/services/employee_alert_service.py

Autonomous Retail Supply Chain AI 5.0

Employee Alert and Notification Service

Python 3.10+
Standard library only.

Features:
- Multi-tenant employee registry
- Role/department/employee targeting
- Severity-based employee alerts
- Per-employee acknowledgment
- Resolution by authorized staff
- Overdue acknowledgment escalation
- In-app inbox
- Optional notification adapters
- Delivery idempotency per alert,
  employee, and channel
- Tenant-scoped audit history

Reference implementation:
- In-memory storage
- No external messages sent by default
- No real authentication provider
- No database persistence

Caller must supply trusted identity
and authorized service context.
"""


import copy
import json
import threading
import uuid

from dataclasses import (
    asdict,
    dataclass,
    field,
)
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EmployeeAlertSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EmployeeAlertCategory(str, Enum):
    SHIFT = "shift"
    TASK = "task"
    INVENTORY = "inventory"
    STOCKOUT = "stockout"
    WAREHOUSE = "warehouse"
    DELIVERY = "delivery"
    SUPPLIER = "supplier"
    EQUIPMENT = "equipment"
    MAINTENANCE = "maintenance"
    SAFETY = "safety"
    SECURITY = "security"
    TRAINING = "training"
    GENERAL = "general"


class EmployeeAlertStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class NotificationChannel(str, Enum):
    IN_APP = "in_app"
    EMAIL = "email"
    SMS = "sms"
    WEBHOOK = "webhook"


@dataclass(frozen=True)
class EmployeeActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    is_active: bool = True


@dataclass(frozen=True)
class EmployeeProfile:
    employee_id: str
    tenant_id: str
    department: str
    roles: frozenset[str]
    channels: frozenset[
        NotificationChannel
    ] = frozenset({
        NotificationChannel.IN_APP
    })
    is_active: bool = True


@dataclass(frozen=True)
class EmployeeAlertPolicy:
    category: EmployeeAlertCategory
    acknowledgment_minutes: int
    escalation_roles: frozenset[str]


@dataclass
class EmployeeAlert:
    alert_id: str
    tenant_id: str
    category: EmployeeAlertCategory
    severity: EmployeeAlertSeverity
    title: str
    message: str
    source: str
    created_by: str
    created_at: str
    status: EmployeeAlertStatus
    recipient_ids: list[str]
    acknowledgment_deadline: str
    escalation_roles: list[str]
    acknowledgments: dict[
        str, str
    ] = field(default_factory=dict)
    escalated: bool = False
    escalated_at: str | None = None
    resolved_by: str | None = None
    resolved_at: str | None = None
    resolution_note: str | None = None
    metadata: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class EmployeeAlertAuditEvent:
    event_id: str
    alert_id: str
    tenant_id: str
    actor_id: str
    event_type: str
    timestamp: str
    details: dict[str, Any]


@dataclass(frozen=True)
class EmployeeDeliveryAttempt:
    attempt_id: str
    alert_id: str
    employee_id: str
    channel: NotificationChannel
    status: str
    timestamp: str
    error_type: str | None = None


class RetailEmployeeAlertService:
    """
    Tenant-scoped employee alerts.

    Managers can create, resolve,
    and cancel alerts.

    Employees can view and acknowledge
    alerts addressed to them.

    Notification adapters are injected
    and not configured by default.
    """

    PUBLISHER_ROLES = frozenset({
        "employee_alert_publisher",
        "operations_manager",
        "warehouse_manager",
        "corporate_admin",
    })

    MANAGER_ROLES = frozenset({
        "operations_manager",
        "warehouse_manager",
        "corporate_admin",
    })

    def __init__(
        self,
        policies: (
            Iterable[EmployeeAlertPolicy]
            | None
        ) = None,
    ):
        self._lock = threading.RLock()

        self._employees: dict[
            tuple[str, str],
            EmployeeProfile,
        ] = {}

        self._alerts: dict[
            str, EmployeeAlert
        ] = {}

        self._audit: list[
            EmployeeAlertAuditEvent
        ] = []

        self._deliveries: list[
            EmployeeDeliveryAttempt
        ] = []

        self._delivery_claims: set[
            tuple[
                str,
                str,
                NotificationChannel,
            ]
        ] = set()

        self._senders: dict[
            NotificationChannel,
            Callable[
                [EmployeeProfile, EmployeeAlert],
                None,
            ],
        ] = {}

        selected = list(
            policies
            if policies is not None
            else self.default_policies()
        )

        if len({
            policy.category
            for policy in selected
        }) != len(selected):
            raise ValueError(
                "Duplicate alert policy"
            )

        self._policies = {
            policy.category: policy
            for policy in selected
        }

        for policy in selected:
            if policy.acknowledgment_minutes < 1:
                raise ValueError(
                    "Invalid acknowledgment SLA"
                )

    @staticmethod
    def default_policies() -> list[
        EmployeeAlertPolicy
    ]:
        return [
            EmployeeAlertPolicy(
                category=category,
                acknowledgment_minutes=(
                    10
                    if category in {
                        EmployeeAlertCategory.SAFETY,
                        EmployeeAlertCategory.SECURITY,
                    }
                    else 30
                    if category in {
                        EmployeeAlertCategory.STOCKOUT,
                        EmployeeAlertCategory.EQUIPMENT,
                        EmployeeAlertCategory.MAINTENANCE,
                    }
                    else 120
                ),
                escalation_roles=frozenset({
                    "operations_manager",
                }),
            )
            for category in (
                EmployeeAlertCategory
            )
        ]

    @staticmethod
    def _validate_actor(
        actor: EmployeeActor,
    ) -> None:
        if (
            not actor.is_active
            or not actor.user_id.strip()
            or not actor.tenant_id.strip()
        ):
            raise PermissionError(
                "Invalid or inactive actor"
            )

    @staticmethod
    def _metadata(
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if metadata is None:
            return {}

        if not isinstance(metadata, dict):
            raise ValueError(
                "Metadata must be a dictionary"
            )

        encoded = json.dumps(
            metadata,
            allow_nan=False,
            sort_keys=True,
        )

        if len(encoded) > 20_000:
            raise ValueError(
                "Metadata exceeds size limit"
            )

        return json.loads(encoded)

    def _audit_event(
        self,
        alert: EmployeeAlert,
        actor_id: str,
        event_type: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._audit.append(
            EmployeeAlertAuditEvent(
                event_id=str(uuid.uuid4()),
                alert_id=alert.alert_id,
                tenant_id=alert.tenant_id,
                actor_id=actor_id,
                event_type=event_type,
                timestamp=utc_now().isoformat(),
                details=copy.deepcopy(
                    details or {}
                ),
            )
        )

    def register_employee(
        self,
        actor: EmployeeActor,
        employee: EmployeeProfile,
    ) -> None:
        with self._lock:
            self._validate_actor(actor)

            if not (
                actor.roles
                & {
                    "hr_admin",
                    "corporate_admin",
                }
            ):
                raise PermissionError(
                    "Employee registration denied"
                )

            if (
                employee.tenant_id
                != actor.tenant_id
            ):
                raise PermissionError(
                    "Cross-tenant employee"
                )

            if (
                not employee.employee_id.strip()
                or not employee.department.strip()
            ):
                raise ValueError(
                    "Invalid employee profile"
                )

            self._employees[
                (
                    employee.tenant_id,
                    employee.employee_id,
                )
            ] = copy.deepcopy(
                employee
            )

    def register_sender(
        self,
        actor: EmployeeActor,
        channel: NotificationChannel,
        sender: Callable[
            [EmployeeProfile, EmployeeAlert],
            None,
        ],
    ) -> None:
        with self._lock:
            self._validate_actor(actor)

            if "corporate_admin" not in (
                actor.roles
            ):
                raise PermissionError(
                    "Sender registration denied"
                )

            if not callable(sender):
                raise ValueError(
                    "Sender must be callable"
                )

            self._senders[channel] = sender

    def create_alert(
        self,
        actor: EmployeeActor,
        category: EmployeeAlertCategory,
        severity: EmployeeAlertSeverity,
        title: str,
        message: str,
        source: str,
        employee_ids: (
            Iterable[str] | None
        ) = None,
        departments: (
            Iterable[str] | None
        ) = None,
        target_roles: (
            Iterable[str] | None
        ) = None,
        metadata: dict[str, Any] | None = None,
    ) -> EmployeeAlert:
        with self._lock:
            self._validate_actor(actor)

            if not (
                actor.roles
                & self.PUBLISHER_ROLES
            ):
                raise PermissionError(
                    "Alert publishing denied"
                )

            if (
                not title.strip()
                or not message.strip()
                or not source.strip()
            ):
                raise ValueError(
                    "Title, message and "
                    "source are required"
                )

            if (
                len(title) > 200
                or len(message) > 5000
                or len(source) > 200
            ):
                raise ValueError(
                    "Alert text too long"
                )

            explicit_ids = set(
                employee_ids or []
            )

            departments = set(
                departments or []
            )

            target_roles = set(
                target_roles or []
            )

            if not (
                explicit_ids
                or departments
                or target_roles
            ):
                raise ValueError(
                    "At least one recipient "
                    "target is required"
                )

            # Fail closed on unknown or
            # inactive explicitly named
            # employees.
            for employee_id in explicit_ids:
                employee = (
                    self._employees.get(
                        (
                            actor.tenant_id,
                            employee_id,
                        )
                    )
                )

                if (
                    employee is None
                    or not employee.is_active
                ):
                    raise ValueError(
                        "Invalid targeted employee"
                    )

            recipients = set()

            for employee in (
                self._employees.values()
            ):
                if (
                    employee.tenant_id
                    != actor.tenant_id
                    or not employee.is_active
                ):
                    continue

                if (
                    employee.employee_id
                    in explicit_ids
                    or employee.department
                    in departments
                    or bool(
                        employee.roles
                        & target_roles
                    )
                ):
                    recipients.add(
                        employee.employee_id
                    )

            if not recipients:
                raise ValueError(
                    "No eligible recipients"
                )

            policy = self._policies.get(
                category
            )

            if policy is None:
                raise ValueError(
                    "Alert category policy missing"
                )

            now = utc_now()

            alert = EmployeeAlert(
                alert_id=str(uuid.uuid4()),
                tenant_id=actor.tenant_id,
                category=category,
                severity=severity,
                title=title.strip(),
                message=message.strip(),
                source=source.strip(),
                created_by=actor.user_id,
                created_at=now.isoformat(),
                status=EmployeeAlertStatus.OPEN,
                recipient_ids=sorted(
                    recipients
                ),
                acknowledgment_deadline=(
                    now
                    + timedelta(
                        minutes=(
                            policy.acknowledgment_minutes
                        )
                    )
                ).isoformat(),
                escalation_roles=sorted(
                    policy.escalation_roles
                ),
                metadata=self._metadata(
                    metadata
                ),
            )

            self._alerts[
                alert.alert_id
            ] = alert

            self._audit_event(
                alert,
                actor.user_id,
                "created",
                {
                    "recipient_count": (
                        len(recipients)
                    ),
                    "severity": (
                        severity.value
                    ),
                },
            )

            return copy.deepcopy(
                alert
            )

    def _get(
        self,
        alert_id: str,
        actor: EmployeeActor,
    ) -> EmployeeAlert:
        self._validate_actor(actor)

        alert = self._alerts.get(
            alert_id
        )

        if (
            alert is None
            or alert.tenant_id
            != actor.tenant_id
        ):
            raise KeyError(
                "Employee alert not found"
            )

        is_recipient = (
            actor.user_id
            in alert.recipient_ids
        )

        is_manager = bool(
            actor.roles
            & self.MANAGER_ROLES
        )

        if not (
            is_recipient or is_manager
        ):
            raise PermissionError(
                "Employee alert access denied"
            )

        return alert

    def get_alert(
        self,
        alert_id: str,
        actor: EmployeeActor,
    ) -> EmployeeAlert:
        with self._lock:
            return copy.deepcopy(
                self._get(
                    alert_id,
                    actor,
                )
            )

    def employee_inbox(
        self,
        actor: EmployeeActor,
        unacknowledged_only: bool = False,
    ) -> list[EmployeeAlert]:
        with self._lock:
            self._validate_actor(actor)

            results = []

            for alert in self._alerts.values():
                if (
                    alert.tenant_id
                    != actor.tenant_id
                    or actor.user_id
                    not in alert.recipient_ids
                ):
                    continue

                if (
                    unacknowledged_only
                    and (
                        actor.user_id
                        in alert.acknowledgments
                        or alert.status
                        != EmployeeAlertStatus.OPEN
                    )
                ):
                    continue

                results.append(
                    copy.deepcopy(alert)
                )

            return sorted(
                results,
                key=lambda item: (
                    item.created_at
                ),
                reverse=True,
            )

    def acknowledge(
        self,
        alert_id: str,
        actor: EmployeeActor,
    ) -> EmployeeAlert:
        with self._lock:
            alert = self._get(
                alert_id,
                actor,
            )

            if (
                actor.user_id
                not in alert.recipient_ids
            ):
                raise PermissionError(
                    "Only recipients may acknowledge"
                )

            if alert.status != (
                EmployeeAlertStatus.OPEN
            ):
                raise ValueError(
                    "Alert is not open"
                )

            if (
                actor.user_id
                in alert.acknowledgments
            ):
                # Idempotent acknowledgment.
                return copy.deepcopy(
                    alert
                )

            timestamp = (
                utc_now().isoformat()
            )

            alert.acknowledgments[
                actor.user_id
            ] = timestamp

            self._audit_event(
                alert,
                actor.user_id,
                "acknowledged",
            )

            return copy.deepcopy(
                alert
            )

    def resolve(
        self,
        alert_id: str,
        actor: EmployeeActor,
        resolution_note: str,
    ) -> EmployeeAlert:
        with self._lock:
            alert = self._get(
                alert_id,
                actor,
            )

            if not (
                actor.roles
                & self.MANAGER_ROLES
            ):
                raise PermissionError(
                    "Resolution requires manager"
                )

            if alert.status != (
                EmployeeAlertStatus.OPEN
            ):
                raise ValueError(
                    "Alert is not open"
                )

            if (
                not resolution_note
                or not resolution_note.strip()
            ):
                raise ValueError(
                    "Resolution note required"
                )

            alert.status = (
                EmployeeAlertStatus.RESOLVED
            )

            alert.resolved_by = (
                actor.user_id
            )

            alert.resolved_at = (
                utc_now().isoformat()
            )

            alert.resolution_note = (
                resolution_note.strip()[:1000]
            )

            self._audit_event(
                alert,
                actor.user_id,
                "resolved",
            )

            return copy.deepcopy(
                alert
            )

    def escalate_overdue(
        self,
        actor: EmployeeActor,
    ) -> list[EmployeeAlert]:
        """
        Scheduler operation.

        Escalates an alert when at
        least one recipient has not
        acknowledged by its deadline.

        Escalation records the event;
        delivery must be separately
        handled by a worker.
        """
        with self._lock:
            self._validate_actor(actor)

            if "alert_scheduler" not in (
                actor.roles
            ):
                raise PermissionError(
                    "Scheduler role required"
                )

            now = utc_now()
            results = []

            for alert in self._alerts.values():
                if (
                    alert.tenant_id
                    != actor.tenant_id
                    or alert.status
                    != EmployeeAlertStatus.OPEN
                    or alert.escalated
                ):
                    continue

                deadline = (
                    datetime.fromisoformat(
                        alert.acknowledgment_deadline
                    )
                )

                if now < deadline:
                    continue

                pending = (
                    set(alert.recipient_ids)
                    - set(
                        alert.acknowledgments
                    )
                )

                if not pending:
                    continue

                alert.escalated = True
                alert.escalated_at = (
                    now.isoformat()
                )

                self._audit_event(
                    alert,
                    actor.user_id,
                    "escalated",
                    {
                        "pending_count": (
                            len(pending)
                        ),
                        "escalation_roles": (
                            alert.escalation_roles
                        ),
                    },
                )

                results.append(
                    copy.deepcopy(alert)
                )

            return results

    def dispatch(
        self,
        alert_id: str,
        actor: EmployeeActor,
    ) -> list[EmployeeDeliveryAttempt]:
        """
        Dispatch to configured adapters.

        The sender is considered
        successful when it returns
        without raising an exception.

        Real delivery confirmation
        requires provider callbacks.

        A claim prevents repeat
        dispatch attempts within this
        service instance. Failures are
        not retried automatically.
        """
        with self._lock:
            alert = copy.deepcopy(
                self._get(
                    alert_id,
                    actor,
                )
            )

            if not (
                actor.roles
                & self.PUBLISHER_ROLES
            ):
                raise PermissionError(
                    "Dispatch denied"
                )

            if alert.status != (
                EmployeeAlertStatus.OPEN
            ):
                raise ValueError(
                    "Alert is not open"
                )

            tasks = []

            for employee_id in (
                alert.recipient_ids
            ):
                employee = (
                    self._employees.get(
                        (
                            alert.tenant_id,
                            employee_id,
                        )
                    )
                )

                if (
                    employee is None
                    or not employee.is_active
                ):
                    continue

                for channel in (
                    employee.channels
                ):
                    key = (
                        alert.alert_id,
                        employee_id,
                        channel,
                    )

                    if key in (
                        self._delivery_claims
                    ):
                        continue

                    sender = (
                        self._senders.get(
                            channel
                        )
                    )

                    if sender is None:
                        continue

                    self._delivery_claims.add(
                        key
                    )

                    tasks.append(
                        (
                            copy.deepcopy(
                                employee
                            ),
                            channel,
                            sender,
                        )
                    )

        attempts = []

        for (
            employee,
            channel,
            sender,
        ) in tasks:
            try:
                sender(
                    employee,
                    copy.deepcopy(alert),
                )

                status = "accepted"
                error_type = None

            except Exception as exc:
                status = "failed"
                error_type = (
                    type(exc).__name__
                )

            attempts.append(
                EmployeeDeliveryAttempt(
                    attempt_id=str(
                        uuid.uuid4()
                    ),
                    alert_id=alert.alert_id,
                    employee_id=(
                        employee.employee_id
                    ),
                    channel=channel,
                    status=status,
                    timestamp=(
                        utc_now().isoformat()
                    ),
                    error_type=error_type,
                )
            )

        with self._lock:
            self._deliveries.extend(
                attempts
            )

            original = (
                self._alerts.get(
                    alert.alert_id
                )
            )

            if original is not None:
                self._audit_event(
                    original,
                    actor.user_id,
                    "dispatch_completed",
                    {
                        "attempts": (
                            len(attempts)
                        ),
                        "accepted": sum(
                            item.status
                            == "accepted"
                            for item in attempts
                        ),
                    },
                )

        return attempts

    def audit_events(
        self,
        alert_id: str,
        actor: EmployeeActor,
    ) -> list[EmployeeAlertAuditEvent]:
        with self._lock:
            alert = self._get(
                alert_id,
                actor,
            )

            if not (
                actor.roles
                & self.MANAGER_ROLES
            ):
                raise PermissionError(
                    "Audit access requires manager"
                )

            return [
                copy.deepcopy(event)
                for event in self._audit
                if (
                    event.alert_id
                    == alert.alert_id
                    and event.tenant_id
                    == actor.tenant_id
                )
            ]

    def export_json(
        self,
        actor: EmployeeActor,
        output_path: str | Path,
    ) -> Path:
        with self._lock:
            self._validate_actor(actor)

            if "corporate_admin" not in (
                actor.roles
            ):
                raise PermissionError(
                    "Export requires corporate_admin"
                )

            records = [
                asdict(alert)
                for alert in (
                    self._alerts.values()
                )
                if alert.tenant_id
                == actor.tenant_id
            ]

        output = Path(
            output_path
        )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            json.dumps(
                records,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return output


if __name__ == "__main__":
    service = RetailEmployeeAlertService()

    admin = EmployeeActor(
        user_id="admin-001",
        tenant_id="demo",
        roles=frozenset({
            "corporate_admin",
        }),
    )

    employee = EmployeeProfile(
        employee_id="EMP001",
        tenant_id="demo",
        department="warehouse",
        roles=frozenset({
            "warehouse_staff",
        }),
        channels=frozenset({
            NotificationChannel.IN_APP,
        }),
    )

    service.register_employee(
        admin,
        employee,
    )

    def demo_in_app_sender(
        employee: EmployeeProfile,
        alert: EmployeeAlert,
    ) -> None:
        print(
            f"IN-APP: {employee.employee_id} "
            f"-> {alert.title}"
        )

    service.register_sender(
        admin,
        NotificationChannel.IN_APP,
        demo_in_app_sender,
    )

    alert = service.create_alert(
        actor=admin,
        category=EmployeeAlertCategory.STOCKOUT,
        severity=EmployeeAlertSeverity.HIGH,
        title="Urgent SKU001 Restock",
        message=(
            "SKU001 stock is below the "
            "minimum reorder threshold."
        ),
        source="inventory_service",
        departments=["warehouse"],
        metadata={
            "sku": "SKU001",
            "warehouse_id": "WH001",
        },
    )

    service.dispatch(
        alert.alert_id,
        admin,
    )

    employee_actor = EmployeeActor(
        user_id="EMP001",
        tenant_id="demo",
        roles=frozenset({
            "warehouse_staff",
        }),
    )

    service.acknowledge(
        alert.alert_id,
        employee_actor,
    )

    service.resolve(
        alert.alert_id,
        admin,
        "Warehouse restock task assigned",
    )

    print(
        json.dumps(
            asdict(
                service.get_alert(
                    alert.alert_id,
                    admin,
                )
            ),
            indent=2,
        )
    )
