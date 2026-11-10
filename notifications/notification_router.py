from __future__ import annotations

"""Planned module: notification router. Implementation pending."""

"""
backend/notifications/notification_router.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+

Features:
- Tenant-scoped notification routing
- Recipient role and warehouse authorization
- Severity-based channel policies
- User channel preferences
- Quiet-hour handling
- Critical-alert channel escalation
- Stable delivery idempotency keys
- Deterministic delivery plans
- No external network or database side effects

Integrates with:
    alert_rules.py
    escalation_policy.py
    deduplication.py
    delivery_tracker.py
    dashboard_notifier.py
    email_notifier.py
"""


from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from enum import Enum
from hashlib import sha256
from typing import Iterable
from zoneinfo import ZoneInfo
import json


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def aware(value: datetime, name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(
            f"{name} must be timezone-aware"
        )
    return value


class NotificationChannel(str, Enum):
    DASHBOARD = "dashboard"
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"


class NotificationSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class NotificationCategory(str, Enum):
    INVENTORY = "inventory"
    STOCKOUT = "stockout"
    SUPPLIER = "supplier"
    WAREHOUSE = "warehouse"
    QUALITY = "quality"
    LOGISTICS = "logistics"
    FINANCE = "finance"
    SECURITY = "security"
    INCIDENT = "incident"
    GENERAL = "general"


@dataclass(frozen=True)
class QuietHours:
    start: time
    end: time
    timezone_name: str = "UTC"

    def __post_init__(self) -> None:
        ZoneInfo(self.timezone_name)

        if (
            self.start.tzinfo is not None
            or self.end.tzinfo is not None
        ):
            raise ValueError(
                "Quiet-hour times must be naive local times"
            )

    def active(self, at: datetime) -> bool:
        local = aware(at, "at").astimezone(
            ZoneInfo(self.timezone_name)
        ).time().replace(tzinfo=None)

        if self.start == self.end:
            return False

        if self.start < self.end:
            return self.start <= local < self.end

        return (
            local >= self.start
            or local < self.end
        )


@dataclass(frozen=True)
class Recipient:
    tenant_id: str
    user_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str] = frozenset()
    allowed_channels: frozenset[NotificationChannel] = (
        frozenset({
            NotificationChannel.DASHBOARD,
            NotificationChannel.EMAIL,
        })
    )
    disabled_channels: frozenset[NotificationChannel] = (
        frozenset()
    )
    quiet_hours: QuietHours | None = None
    active: bool = True
    global_warehouse_access: bool = False

    def __post_init__(self) -> None:
        required(self.tenant_id, "tenant_id")
        required(self.user_id, "user_id")


@dataclass(frozen=True)
class NotificationEvent:
    tenant_id: str
    event_id: str
    severity: NotificationSeverity
    category: NotificationCategory
    title: str
    message: str
    resource_id: str
    warehouse_id: str | None = None
    required_roles: frozenset[str] = frozenset()
    requested_channels: frozenset[
        NotificationChannel
    ] | None = None
    occurred_at: datetime = field(
        default_factory=utc_now
    )

    def __post_init__(self) -> None:
        required(self.tenant_id, "tenant_id")
        required(self.event_id, "event_id")
        required(self.title, "title")
        required(self.message, "message")
        required(self.resource_id, "resource_id")
        aware(self.occurred_at, "occurred_at")


@dataclass(frozen=True)
class DeliveryInstruction:
    tenant_id: str
    event_id: str
    recipient_user_id: str
    channel: NotificationChannel
    idempotency_key: str
    title: str
    message: str
    severity: NotificationSeverity
    category: NotificationCategory
    resource_id: str


@dataclass(frozen=True)
class RoutingResult:
    event_id: str
    tenant_id: str
    deliveries: tuple[DeliveryInstruction, ...]
    eligible_recipients: int
    suppressed_recipients: int
    suppressed_channels: int


class RetailNotificationRouter:
    DEFAULT_CHANNELS = {
        NotificationSeverity.INFO: frozenset({
            NotificationChannel.DASHBOARD,
        }),
        NotificationSeverity.LOW: frozenset({
            NotificationChannel.DASHBOARD,
        }),
        NotificationSeverity.MEDIUM: frozenset({
            NotificationChannel.DASHBOARD,
            NotificationChannel.EMAIL,
        }),
        NotificationSeverity.HIGH: frozenset({
            NotificationChannel.DASHBOARD,
            NotificationChannel.EMAIL,
            NotificationChannel.PUSH,
        }),
        NotificationSeverity.CRITICAL: frozenset({
            NotificationChannel.DASHBOARD,
            NotificationChannel.EMAIL,
            NotificationChannel.SMS,
            NotificationChannel.PUSH,
        }),
    }

    def __init__(
        self,
        *,
        critical_bypass_quiet_hours: bool = True,
    ) -> None:
        self.critical_bypass_quiet_hours = (
            critical_bypass_quiet_hours
        )

    @staticmethod
    def delivery_key(
        *,
        tenant_id: str,
        event_id: str,
        user_id: str,
        channel: NotificationChannel,
    ) -> str:
        canonical = json.dumps(
            {
                "tenant_id": tenant_id,
                "event_id": event_id,
                "user_id": user_id,
                "channel": channel.value,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

        return sha256(
            canonical.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _eligible(
        event: NotificationEvent,
        recipient: Recipient,
    ) -> bool:
        if not recipient.active:
            return False

        if recipient.tenant_id != event.tenant_id:
            return False

        if (
            event.required_roles
            and not event.required_roles.intersection(
                recipient.roles
            )
        ):
            return False

        if (
            event.warehouse_id is not None
            and not recipient.global_warehouse_access
            and event.warehouse_id
                not in recipient.warehouse_ids
        ):
            return False

        return True

    def route(
        self,
        *,
        event: NotificationEvent,
        recipients: Iterable[Recipient],
        now: datetime | None = None,
    ) -> RoutingResult:
        evaluated_at = aware(
            now or utc_now(), "now"
        )

        channels = (
            event.requested_channels
            if event.requested_channels is not None
            else self.DEFAULT_CHANNELS[event.severity]
        )

        deliveries = []
        eligible = 0
        suppressed_recipients = 0
        suppressed_channels = 0
        seen_users: set[str] = set()

        for recipient in recipients:
            if recipient.user_id in seen_users:
                continue

            seen_users.add(recipient.user_id)

            if not self._eligible(event, recipient):
                suppressed_recipients += 1
                continue

            eligible += 1

            permitted = (
                channels
                & recipient.allowed_channels
                - recipient.disabled_channels
            )

            quiet = (
                recipient.quiet_hours is not None
                and recipient.quiet_hours.active(
                    evaluated_at
                )
            )

            if quiet and not (
                event.severity
                    == NotificationSeverity.CRITICAL
                and self.critical_bypass_quiet_hours
            ):
                # Dashboard inbox updates remain available.
                permitted = permitted & frozenset({
                    NotificationChannel.DASHBOARD
                })

            suppressed_channels += (
                len(channels) - len(permitted)
            )

            for channel in sorted(
                permitted,
                key=lambda item: item.value,
            ):
                deliveries.append(
                    DeliveryInstruction(
                        tenant_id=event.tenant_id,
                        event_id=event.event_id,
                        recipient_user_id=recipient.user_id,
                        channel=channel,
                        idempotency_key=self.delivery_key(
                            tenant_id=event.tenant_id,
                            event_id=event.event_id,
                            user_id=recipient.user_id,
                            channel=channel,
                        ),
                        title=event.title,
                        message=event.message,
                        severity=event.severity,
                        category=event.category,
                        resource_id=event.resource_id,
                    )
                )

        return RoutingResult(
            event_id=event.event_id,
            tenant_id=event.tenant_id,
            deliveries=tuple(deliveries),
            eligible_recipients=eligible,
            suppressed_recipients=suppressed_recipients,
            suppressed_channels=suppressed_channels,
        )


if __name__ == "__main__":
    router = RetailNotificationRouter()

    event = NotificationEvent(
        tenant_id="retail-demo",
        event_id="EVT001",
        severity=NotificationSeverity.CRITICAL,
        category=NotificationCategory.INVENTORY,
        title="Critical low stock",
        message="SKU001 has 12 units remaining.",
        resource_id="WH001:SKU001",
        warehouse_id="WH001",
        required_roles=frozenset({
            "inventory_manager",
            "warehouse_manager",
        }),
    )

    recipients = [
        Recipient(
            tenant_id="retail-demo",
            user_id="EMP001",
            roles=frozenset({
                "inventory_manager",
            }),
            warehouse_ids=frozenset({
                "WH001",
            }),
            allowed_channels=frozenset({
                NotificationChannel.DASHBOARD,
                NotificationChannel.EMAIL,
                NotificationChannel.PUSH,
            }),
        ),
        Recipient(
            tenant_id="other-tenant",
            user_id="EMP002",
            roles=frozenset({
                "inventory_manager",
            }),
            warehouse_ids=frozenset({
                "WH001",
            }),
        ),
    ]

    result = router.route(
        event=event,
        recipients=recipients,
    )

    print("Eligible:", result.eligible_recipients)
    print("Deliveries:", len(result.deliveries))

    for delivery in result.deliveries:
        print(
            delivery.recipient_user_id,
            delivery.channel.value,
            delivery.idempotency_key[:12],
        )
