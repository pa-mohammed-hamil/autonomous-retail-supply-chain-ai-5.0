from __future__ import annotations

"""Planned module: notification. Implementation pending."""

"""
backend/models/notification.py

Autonomous Retail Supply Chain AI 5.0
Notification ORM Model

Features:
- Multi-tenant notification management
- Employee, manager, corporate and external recipients
- Email, SMS, push, WhatsApp, in-app and webhook channels
- AI agent, ML model and business event notifications
- Delivery lifecycle, retry scheduling and failures
- Read receipts and acknowledgment
- Priority, severity, scheduling and expiration
- Escalation and approval references
- Provider metadata and delivery history
- Deduplication and idempotency keys
- Audit timestamps and soft deletion
- Optimistic concurrency control

Requirements:
    Python >= 3.10
    SQLAlchemy >= 2.0

Shared Base:
    backend.models.base.Base

Important:
    Actual message delivery, authorization,
    provider integration, retry workers and
    escalation scheduling belong in services.
"""


import enum
import uuid

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SQLEnum,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


# ============================================================
# UTILITIES
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_notification_code() -> str:
    return f"NTF-{uuid.uuid4().hex[:16].upper()}"


def enum_column(enum_class, name: str):
    return SQLEnum(
        enum_class,
        name=name,
        native_enum=False,
        values_callable=lambda members: [
            member.value for member in members
        ],
        validate_strings=True,
        length=60,
    )


def datetime_string(
    value: datetime | None,
) -> str | None:
    return value.isoformat() if value else None


def enum_value(
    value: enum.Enum | None,
) -> str | None:
    return value.value if value is not None else None


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError(
            "Timezone-aware datetime is required"
        )

    return value.astimezone(timezone.utc)


# ============================================================
# ENUMS
# ============================================================

class NotificationType(str, enum.Enum):
    GENERAL = "general"
    SYSTEM = "system"
    EMPLOYEE_ALERT = "employee_alert"
    CORPORATE_ALERT = "corporate_alert"
    INVENTORY_LOW = "inventory_low"
    STOCKOUT = "stockout"
    DEMAND_SPIKE = "demand_spike"
    DEMAND_FORECAST = "demand_forecast"
    SUPPLIER_RISK = "supplier_risk"
    SUPPLIER_DELAY = "supplier_delay"
    PURCHASE_ORDER = "purchase_order"
    DELIVERY_UPDATE = "delivery_update"
    DELIVERY_DELAY = "delivery_delay"
    LOGISTICS_DISRUPTION = "logistics_disruption"
    WAREHOUSE_INCIDENT = "warehouse_incident"
    SAFETY_INCIDENT = "safety_incident"
    EMERGENCY = "emergency"
    PREDICTIVE_MAINTENANCE = "predictive_maintenance"
    MODEL_DRIFT = "model_drift"
    MODEL_DEPLOYMENT = "model_deployment"
    AGENT_ACTION = "agent_action"
    AGENT_FAILURE = "agent_failure"
    APPROVAL_REQUEST = "approval_request"
    APPROVAL_RESULT = "approval_result"
    ESCALATION = "escalation"
    SECURITY = "security"
    COMPLIANCE = "compliance"
    CUSTOMER_FEEDBACK = "customer_feedback"
    REPORT_READY = "report_ready"
    OTHER = "other"


class NotificationChannel(str, enum.Enum):
    IN_APP = "in_app"
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    WHATSAPP = "whatsapp"
    WEBHOOK = "webhook"
    WORKPLACE = "workplace"


class NotificationStatus(str, enum.Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    ACKNOWLEDGED = "acknowledged"
    RETRY_PENDING = "retry_pending"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class NotificationPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class NotificationSeverity(str, enum.Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class NotificationSource(str, enum.Enum):
    SYSTEM = "system"
    USER = "user"
    EMPLOYEE = "employee"
    MANAGER = "manager"
    RULE_ENGINE = "rule_engine"
    EVENT_BUS = "event_bus"
    AI_AGENT = "ai_agent"
    ML_MODEL = "ml_model"
    API = "api"
    INTEGRATION = "integration"
    SCHEDULER = "scheduler"


class NotificationRecipientType(str, enum.Enum):
    USER = "user"
    EMPLOYEE = "employee"
    MANAGER = "manager"
    TEAM = "team"
    DEPARTMENT = "department"
    ROLE = "role"
    CUSTOMER = "customer"
    SUPPLIER = "supplier"
    EXTERNAL = "external"


class NotificationDeliveryStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    PENDING = "pending"
    ACCEPTED = "accepted"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    REJECTED = "rejected"
    BOUNCED = "bounced"


# ============================================================
# NOTIFICATION MODEL
# ============================================================

class Notification(Base):
    __tablename__ = "notifications"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "notification_code",
            name="uq_notification_org_code",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_notification_org_idempotency",
        ),
        CheckConstraint(
            "retry_count >= 0",
            name="notification_retry_nonnegative",
        ),
        CheckConstraint(
            "max_retries >= 0",
            name="notification_max_retries_nonnegative",
        ),
        CheckConstraint(
            "retry_count <= max_retries",
            name="notification_retry_limit",
        ),
        CheckConstraint(
            "delivery_attempts >= 0",
            name="notification_attempts_nonnegative",
        ),
        CheckConstraint(
            "occurrence_count >= 1",
            name="notification_occurrence_positive",
        ),
        CheckConstraint(
            "escalation_level >= 0",
            name="notification_escalation_nonnegative",
        ),
        CheckConstraint(
            "version >= 1",
            name="notification_version_positive",
        ),
        Index(
            "ix_notification_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_notification_org_recipient",
            "organization_id",
            "recipient_id",
        ),
        Index(
            "ix_notification_org_channel",
            "organization_id",
            "channel",
        ),
        Index(
            "ix_notification_org_priority",
            "organization_id",
            "priority",
        ),
        Index(
            "ix_notification_org_type",
            "organization_id",
            "notification_type",
        ),
        Index(
            "ix_notification_org_schedule",
            "organization_id",
            "scheduled_at",
        ),
        Index(
            "ix_notification_org_retry",
            "organization_id",
            "next_retry_at",
        ),
        Index(
            "ix_notification_org_created",
            "organization_id",
            "created_at",
        ),
    )

    # --------------------------------------------------------
    # IDENTIFIERS
    # --------------------------------------------------------

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    organization_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    notification_code: Mapped[str] = mapped_column(
        String(40),
        default=generate_notification_code,
        nullable=False,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    deduplication_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        index=True,
    )

    # --------------------------------------------------------
    # NOTIFICATION CONTENT
    # --------------------------------------------------------

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    short_message: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    notification_type: Mapped[
        NotificationType
    ] = mapped_column(
        enum_column(
            NotificationType,
            "notification_type",
        ),
        default=NotificationType.GENERAL,
        nullable=False,
    )

    channel: Mapped[
        NotificationChannel
    ] = mapped_column(
        enum_column(
            NotificationChannel,
            "notification_channel",
        ),
        default=NotificationChannel.IN_APP,
        nullable=False,
    )

    status: Mapped[
        NotificationStatus
    ] = mapped_column(
        enum_column(
            NotificationStatus,
            "notification_status",
        ),
        default=NotificationStatus.DRAFT,
        nullable=False,
    )

    priority: Mapped[
        NotificationPriority
    ] = mapped_column(
        enum_column(
            NotificationPriority,
            "notification_priority",
        ),
        default=NotificationPriority.NORMAL,
        nullable=False,
    )

    severity: Mapped[
        NotificationSeverity
    ] = mapped_column(
        enum_column(
            NotificationSeverity,
            "notification_severity",
        ),
        default=NotificationSeverity.INFO,
        nullable=False,
    )

    source: Mapped[
        NotificationSource
    ] = mapped_column(
        enum_column(
            NotificationSource,
            "notification_source",
        ),
        default=NotificationSource.SYSTEM,
        nullable=False,
    )

    # --------------------------------------------------------
    # RECIPIENT
    # --------------------------------------------------------

    recipient_type: Mapped[
        NotificationRecipientType
    ] = mapped_column(
        enum_column(
            NotificationRecipientType,
            "notification_recipient_type",
        ),
        default=NotificationRecipientType.USER,
        nullable=False,
    )

    recipient_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    recipient_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    recipient_address: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    recipient_team_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    recipient_department_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    recipient_role: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # --------------------------------------------------------
    # SENDER
    # --------------------------------------------------------

    sender_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    sender_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # --------------------------------------------------------
    # SOURCE ENTITY REFERENCES
    # --------------------------------------------------------

    source_entity_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    source_entity_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    employee_alert_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    corporate_alert_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    incident_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    inventory_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    warehouse_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    product_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    supplier_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    delivery_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    purchase_order_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    demand_forecast_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    market_trend_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    model_registry_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # AI AGENT AND APPROVAL
    # --------------------------------------------------------

    agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    agent_action_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    approval_request_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    escalation_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # TEMPLATE
    # --------------------------------------------------------

    template_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    template_version: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    template_variables: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    locale: Mapped[str] = mapped_column(
        String(20),
        default="en-IN",
        nullable=False,
    )

    # --------------------------------------------------------
    # ACTION LINKS
    # --------------------------------------------------------

    action_label: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    action_url: Mapped[str | None] = mapped_column(
        String(2048),
        nullable=True,
    )

    # --------------------------------------------------------
    # SCHEDULING
    # --------------------------------------------------------

    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    queued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # DELIVERY TRACKING
    # --------------------------------------------------------

    delivery_status: Mapped[
        NotificationDeliveryStatus
    ] = mapped_column(
        enum_column(
            NotificationDeliveryStatus,
            "notification_delivery_status",
        ),
        default=NotificationDeliveryStatus.NOT_STARTED,
        nullable=False,
    )

    provider_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    provider_message_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    provider_response_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    delivery_attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # READ AND ACKNOWLEDGMENT
    # --------------------------------------------------------

    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    acknowledged_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    acknowledgment_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    requires_acknowledgment: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    acknowledgment_deadline: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # RETRIES
    # --------------------------------------------------------

    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    max_retries: Mapped[int] = mapped_column(
        Integer,
        default=3,
        nullable=False,
    )

    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    error_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # --------------------------------------------------------
    # ESCALATION
    # --------------------------------------------------------

    escalation_level: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # DEDUPLICATION
    # --------------------------------------------------------

    occurrence_count: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    last_occurrence_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # DELIVERY HISTORY
    # --------------------------------------------------------

    delivery_history: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # --------------------------------------------------------
    # METADATA
    # --------------------------------------------------------

    notification_data: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    provider_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # AUDIT
    # --------------------------------------------------------

    created_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    updated_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    trace_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    correlation_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    # --------------------------------------------------------
    # SOFT DELETE
    # --------------------------------------------------------

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    deleted_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # OPTIMISTIC CONCURRENCY
    # --------------------------------------------------------

    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    __mapper_args__ = {
        "version_id_col": version,
    }

    # ========================================================
    # PROPERTIES
    # ========================================================

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            NotificationStatus.ACKNOWLEDGED,
            NotificationStatus.FAILED,
            NotificationStatus.CANCELLED,
            NotificationStatus.EXPIRED,
        }

    @property
    def is_expired(self) -> bool:
        return (
            self.expires_at is not None
            and as_utc(self.expires_at) <= utc_now()
        )

    @property
    def is_unread(self) -> bool:
        return (
            self.read_at is None
            and self.status in {
                NotificationStatus.DELIVERED,
                NotificationStatus.READ,
            }
        )

    @property
    def can_retry(self) -> bool:
        return (
            not self.is_deleted
            and not self.is_expired
            and self.status in {
                NotificationStatus.FAILED,
                NotificationStatus.RETRY_PENDING,
            }
            and self.retry_count < self.max_retries
        )

    @property
    def needs_acknowledgment(self) -> bool:
        return (
            self.requires_acknowledgment
            and self.acknowledged_at is None
            and self.status in {
                NotificationStatus.DELIVERED,
                NotificationStatus.READ,
            }
        )

    @property
    def acknowledgment_overdue(self) -> bool:
        return (
            self.needs_acknowledgment
            and self.acknowledgment_deadline is not None
            and as_utc(self.acknowledgment_deadline)
            <= utc_now()
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_active(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Notification is deleted"
            )

        if self.status in {
            NotificationStatus.CANCELLED,
            NotificationStatus.EXPIRED,
            NotificationStatus.ACKNOWLEDGED,
        }:
            raise ValueError(
                "Notification is no longer active"
            )

    def _add_history(
        self,
        event: str,
        **details: Any,
    ) -> None:
        history = list(self.delivery_history or [])

        history.append({
            "event": event,
            "timestamp": utc_now().isoformat(),
            **details,
        })

        self.delivery_history = history
        self._touch()

    # ========================================================
    # SCHEDULE
    # ========================================================

    def schedule(
        self,
        scheduled_at: datetime,
    ) -> None:
        self._ensure_active()

        if self.status != NotificationStatus.DRAFT:
            raise ValueError(
                "Only draft notifications can be scheduled"
            )

        scheduled = as_utc(scheduled_at)

        if scheduled <= utc_now():
            raise ValueError(
                "Scheduled time must be in the future"
            )

        if (
            self.expires_at is not None
            and scheduled >= as_utc(self.expires_at)
        ):
            raise ValueError(
                "Scheduled time must precede expiration"
            )

        self.scheduled_at = scheduled
        self.status = NotificationStatus.SCHEDULED

        self._add_history(
            "scheduled",
            scheduled_at=scheduled.isoformat(),
        )

    # ========================================================
    # QUEUE
    # ========================================================

    def queue(self) -> None:
        self._ensure_active()

        if self.status not in {
            NotificationStatus.DRAFT,
            NotificationStatus.SCHEDULED,
            NotificationStatus.RETRY_PENDING,
        }:
            raise ValueError(
                "Notification cannot be queued"
            )

        if self.is_expired:
            raise ValueError(
                "Notification has expired"
            )

        now = utc_now()

        if (
            self.status == NotificationStatus.SCHEDULED
            and self.scheduled_at is not None
            and as_utc(self.scheduled_at) > now
        ):
            raise ValueError(
                "Scheduled notification is not due"
            )

        if (
            self.status == NotificationStatus.RETRY_PENDING
            and self.next_retry_at is not None
            and as_utc(self.next_retry_at) > now
        ):
            raise ValueError(
                "Retry is not due yet"
            )

        self.status = NotificationStatus.QUEUED
        self.delivery_status = (
            NotificationDeliveryStatus.PENDING
        )
        self.queued_at = now
        self.next_retry_at = None

        self._add_history("queued")

    # ========================================================
    # START SENDING
    # ========================================================

    def start_sending(
        self,
        provider_name: str,
    ) -> None:
        self._ensure_active()

        if self.status != NotificationStatus.QUEUED:
            raise ValueError(
                "Notification must be queued first"
            )

        if self.is_expired:
            raise ValueError(
                "Notification has expired"
            )

        if not provider_name.strip():
            raise ValueError(
                "Provider name is required"
            )

        self.provider_name = provider_name
        self.status = NotificationStatus.SENDING
        self.delivery_attempts += 1
        self.last_attempt_at = utc_now()

        self._add_history(
            "sending",
            provider=provider_name,
            attempt=self.delivery_attempts,
        )

    # ========================================================
    # MARK SENT
    # ========================================================

    def mark_sent(
        self,
        provider_message_id: str,
        response_code: str | None = None,
    ) -> None:
        self._ensure_active()

        if self.status != NotificationStatus.SENDING:
            raise ValueError(
                "Notification is not sending"
            )

        if not provider_message_id:
            raise ValueError(
                "Provider message ID is required"
            )

        self.provider_message_id = provider_message_id
        self.provider_response_code = response_code
        self.delivery_status = (
            NotificationDeliveryStatus.SENT
        )
        self.status = NotificationStatus.SENT
        self.sent_at = utc_now()
        self.failure_reason = None
        self.error_code = None

        self._add_history(
            "sent",
            provider_message_id=provider_message_id,
        )

    # ========================================================
    # MARK DELIVERED
    # ========================================================

    def mark_delivered(self) -> None:
        self._ensure_active()

        if self.status not in {
            NotificationStatus.SENT,
            NotificationStatus.SENDING,
        }:
            raise ValueError(
                "Notification cannot be marked delivered"
            )

        now = utc_now()

        if self.sent_at is None:
            self.sent_at = now

        self.delivered_at = now
        self.delivery_status = (
            NotificationDeliveryStatus.DELIVERED
        )
        self.status = NotificationStatus.DELIVERED

        self._add_history("delivered")

    # ========================================================
    # MARK READ
    # ========================================================

    def mark_read(self) -> None:
        self._ensure_active()

        if self.status not in {
            NotificationStatus.DELIVERED,
            NotificationStatus.READ,
        }:
            raise ValueError(
                "Notification must be delivered first"
            )

        if self.read_at is None:
            self.read_at = utc_now()

        self.status = NotificationStatus.READ
        self._add_history("read")

    # ========================================================
    # ACKNOWLEDGE
    # ========================================================

    def acknowledge(
        self,
        *,
        user_id: str,
        note: str | None = None,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            NotificationStatus.DELIVERED,
            NotificationStatus.READ,
        }:
            raise ValueError(
                "Notification must be delivered first"
            )

        if not self.requires_acknowledgment:
            raise ValueError(
                "Notification does not require acknowledgment"
            )

        if not user_id:
            raise ValueError(
                "Acknowledging user ID is required"
            )

        # Verify recipient identity and permissions
        # in the service layer.
        self.acknowledged_by = user_id
        self.acknowledged_at = utc_now()
        self.acknowledgment_note = note
        self.status = NotificationStatus.ACKNOWLEDGED

        self._add_history(
            "acknowledged",
            user_id=user_id,
        )

    # ========================================================
    # DELIVERY FAILURE
    # ========================================================

    def mark_failed(
        self,
        *,
        reason: str,
        error_code: str | None = None,
        retryable: bool = True,
        retry_delay_seconds: int = 60,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            NotificationStatus.SENDING,
            NotificationStatus.SENT,
            NotificationStatus.QUEUED,
        }:
            raise ValueError(
                "Notification cannot be failed now"
            )

        if not reason.strip():
            raise ValueError(
                "Failure reason required"
            )

        if retry_delay_seconds < 0:
            raise ValueError(
                "Retry delay cannot be negative"
            )

        self.failure_reason = reason
        self.error_code = error_code
        self.delivery_status = (
            NotificationDeliveryStatus.FAILED
        )

        if (
            retryable
            and not self.is_expired
            and self.retry_count < self.max_retries
        ):
            self.retry_count += 1
            self.next_retry_at = (
                utc_now()
                + timedelta(seconds=retry_delay_seconds)
            )

            if (
                self.expires_at is not None
                and self.next_retry_at
                >= as_utc(self.expires_at)
            ):
                self.next_retry_at = None
                self.status = NotificationStatus.FAILED
            else:
                self.status = (
                    NotificationStatus.RETRY_PENDING
                )
        else:
            self.status = NotificationStatus.FAILED
            self.next_retry_at = None

        self._add_history(
            "delivery_failed",
            reason=reason,
            error_code=error_code,
            retry_count=self.retry_count,
            next_retry_at=datetime_string(
                self.next_retry_at
            ),
        )

    # ========================================================
    # CANCEL
    # ========================================================

    def cancel(self, reason: str) -> None:
        self._ensure_active()

        if self.status not in {
            NotificationStatus.DRAFT,
            NotificationStatus.SCHEDULED,
            NotificationStatus.QUEUED,
            NotificationStatus.RETRY_PENDING,
            NotificationStatus.FAILED,
        }:
            raise ValueError(
                "Notification can no longer be cancelled"
            )

        if not reason.strip():
            raise ValueError(
                "Cancellation reason required"
            )

        self.status = NotificationStatus.CANCELLED
        self.next_retry_at = None

        self._add_history(
            "cancelled",
            reason=reason,
        )

    # ========================================================
    # EXPIRE
    # ========================================================

    def expire(self) -> None:
        self._ensure_active()

        if self.expires_at is None:
            raise ValueError(
                "Expiration time is not configured"
            )

        if not self.is_expired:
            raise ValueError(
                "Notification has not expired"
            )

        if self.status in {
            NotificationStatus.DELIVERED,
            NotificationStatus.READ,
            NotificationStatus.SENT,
        }:
            raise ValueError(
                "Already delivered or sent notification "
                "cannot be expired"
            )

        self.status = NotificationStatus.EXPIRED
        self.next_retry_at = None

        self._add_history("expired")

    # ========================================================
    # ESCALATE
    # ========================================================

    def escalate(
        self,
        escalation_id: str,
    ) -> None:
        if self.is_deleted:
            raise ValueError(
                "Notification is deleted"
            )

        if not escalation_id:
            raise ValueError(
                "Escalation ID is required"
            )

        if not self.requires_acknowledgment:
            raise ValueError(
                "Escalation requires acknowledgment policy"
            )

        if self.acknowledged_at is not None:
            raise ValueError(
                "Already acknowledged"
            )

        if self.status not in {
            NotificationStatus.DELIVERED,
            NotificationStatus.READ,
        }:
            raise ValueError(
                "Notification must be delivered first"
            )

        if not self.acknowledgment_overdue:
            raise ValueError(
                "Acknowledgment deadline has not passed"
            )

        self.escalation_id = escalation_id
        self.escalation_level += 1
        self.escalated_at = utc_now()

        self._add_history(
            "escalated",
            escalation_id=escalation_id,
            level=self.escalation_level,
        )

    # ========================================================
    # RECORD OCCURRENCE
    # ========================================================

    def record_occurrence(self) -> None:
        self._ensure_active()

        if self.status not in {
            NotificationStatus.DRAFT,
            NotificationStatus.SCHEDULED,
            NotificationStatus.QUEUED,
            NotificationStatus.RETRY_PENDING,
        }:
            raise ValueError(
                "Cannot aggregate occurrence in current state"
            )

        self.occurrence_count += 1
        self.last_occurrence_at = utc_now()

        self._add_history(
            "occurrence_recorded",
            occurrence_count=self.occurrence_count,
        )

    # ========================================================
    # SOFT DELETE
    # ========================================================

    def soft_delete(self, user_id: str) -> None:
        if self.is_deleted:
            raise ValueError(
                "Notification already deleted"
            )

        if not user_id:
            raise ValueError(
                "Deleting user ID is required"
            )

        if self.status in {
            NotificationStatus.QUEUED,
            NotificationStatus.SENDING,
            NotificationStatus.RETRY_PENDING,
        }:
            raise ValueError(
                "Cancel active delivery before deleting"
            )

        self.is_deleted = True
        self.deleted_by = user_id
        self.deleted_at = utc_now()
        self._touch()

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "notification_code": self.notification_code,
            "idempotency_key": self.idempotency_key,
            "deduplication_key": self.deduplication_key,
            "title": self.title,
            "message": self.message,
            "short_message": self.short_message,
            "notification_type": enum_value(
                self.notification_type
            ),
            "channel": enum_value(self.channel),
            "status": enum_value(self.status),
            "priority": enum_value(self.priority),
            "severity": enum_value(self.severity),
            "source": enum_value(self.source),
            "recipient_type": enum_value(
                self.recipient_type
            ),
            "recipient_id": self.recipient_id,
            "recipient_name": self.recipient_name,
            "recipient_address": self.recipient_address,
            "recipient_team_id": self.recipient_team_id,
            "recipient_department_id": (
                self.recipient_department_id
            ),
            "recipient_role": self.recipient_role,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "source_entity_type": self.source_entity_type,
            "source_entity_id": self.source_entity_id,
            "employee_alert_id": self.employee_alert_id,
            "corporate_alert_id": self.corporate_alert_id,
            "incident_id": self.incident_id,
            "inventory_id": self.inventory_id,
            "warehouse_id": self.warehouse_id,
            "product_id": self.product_id,
            "supplier_id": self.supplier_id,
            "delivery_id": self.delivery_id,
            "purchase_order_id": self.purchase_order_id,
            "demand_forecast_id": self.demand_forecast_id,
            "market_trend_id": self.market_trend_id,
            "model_registry_id": self.model_registry_id,
            "agent_run_id": self.agent_run_id,
            "agent_action_id": self.agent_action_id,
            "approval_request_id": self.approval_request_id,
            "escalation_id": self.escalation_id,
            "template_id": self.template_id,
            "template_version": self.template_version,
            "template_variables": self.template_variables,
            "locale": self.locale,
            "action_label": self.action_label,
            "action_url": self.action_url,
            "scheduled_at": datetime_string(
                self.scheduled_at
            ),
            "queued_at": datetime_string(self.queued_at),
            "expires_at": datetime_string(self.expires_at),
            "delivery_status": enum_value(
                self.delivery_status
            ),
            "provider_name": self.provider_name,
            "provider_message_id": self.provider_message_id,
            "provider_response_code": (
                self.provider_response_code
            ),
            "delivery_attempts": self.delivery_attempts,
            "sent_at": datetime_string(self.sent_at),
            "delivered_at": datetime_string(
                self.delivered_at
            ),
            "read_at": datetime_string(self.read_at),
            "acknowledged_at": datetime_string(
                self.acknowledged_at
            ),
            "acknowledged_by": self.acknowledged_by,
            "acknowledgment_note": self.acknowledgment_note,
            "requires_acknowledgment": (
                self.requires_acknowledgment
            ),
            "acknowledgment_deadline": datetime_string(
                self.acknowledgment_deadline
            ),
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "next_retry_at": datetime_string(
                self.next_retry_at
            ),
            "last_attempt_at": datetime_string(
                self.last_attempt_at
            ),
            "failure_reason": self.failure_reason,
            "error_code": self.error_code,
            "escalation_level": self.escalation_level,
            "escalated_at": datetime_string(
                self.escalated_at
            ),
            "occurrence_count": self.occurrence_count,
            "last_occurrence_at": datetime_string(
                self.last_occurrence_at
            ),
            "delivery_history": self.delivery_history,
            "notification_data": self.notification_data,
            "provider_metadata": self.provider_metadata,
            "is_expired": self.is_expired,
            "is_unread": self.is_unread,
            "can_retry": self.can_retry,
            "needs_acknowledgment": (
                self.needs_acknowledgment
            ),
            "acknowledgment_overdue": (
                self.acknowledgment_overdue
            ),
            "is_deleted": self.is_deleted,
            "version": self.version,
            "created_at": datetime_string(
                self.created_at
            ),
            "updated_at": datetime_string(
                self.updated_at
            ),
        }

    def __repr__(self) -> str:
        return (
            f"<Notification("
            f"id={self.id}, "
            f"code={self.notification_code}, "
            f"channel={enum_value(self.channel)}, "
            f"status={enum_value(self.status)}"
            f")>"
        )
