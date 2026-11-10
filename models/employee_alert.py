from __future__ import annotations

"""Planned module: employee alert. Implementation pending."""

"""
backend/models/employee_alert.py

Autonomous Retail Supply Chain AI 5.0
Employee Alert ORM Model

Features:
- Organization-scoped employee alerts
- Warehouse, inventory and logistics notifications
- Safety and emergency alerts
- AI-generated recommendations
- Employee acknowledgment
- Assignment and escalation
- Delivery status tracking
- Alert expiration
- Deduplication and recurrence
- Optimistic concurrency control
- Soft deletion and audit timestamps

Requirements:
    Python >= 3.10
    SQLAlchemy >= 2.0

Shared base:
    backend.models.base.Base
"""


import enum
import math
import uuid

from datetime import datetime, timezone
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

from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


# ============================================================
# UTILITIES
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_alert_code() -> str:
    return f"EMP-{uuid.uuid4().hex[:16].upper()}"


def enum_column(enum_class, name: str):
    return SQLEnum(
        enum_class,
        name=name,
        native_enum=False,
        values_callable=lambda cls: [
            member.value for member in cls
        ],
        validate_strings=True,
        length=60,
    )


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


# ============================================================
# ENUMS
# ============================================================

class EmployeeAlertType(str, enum.Enum):
    GENERAL = "general"
    TASK_ASSIGNMENT = "task_assignment"
    TASK_REMINDER = "task_reminder"
    INVENTORY_SHORTAGE = "inventory_shortage"
    STOCKOUT_RISK = "stockout_risk"
    OVERSTOCK = "overstock"
    DEMAND_SPIKE = "demand_spike"
    WAREHOUSE_INCIDENT = "warehouse_incident"
    WAREHOUSE_CAPACITY = "warehouse_capacity"
    PICKING_DELAY = "picking_delay"
    PACKING_DELAY = "packing_delay"
    DELIVERY_DELAY = "delivery_delay"
    LOGISTICS_DISRUPTION = "logistics_disruption"
    SUPPLIER_DELAY = "supplier_delay"
    QUALITY_ISSUE = "quality_issue"
    EQUIPMENT_FAILURE = "equipment_failure"
    PREDICTIVE_MAINTENANCE = "predictive_maintenance"
    SAFETY_WARNING = "safety_warning"
    EMERGENCY = "emergency"
    SECURITY_INCIDENT = "security_incident"
    COMPLIANCE = "compliance"
    APPROVAL_REQUIRED = "approval_required"
    AI_RECOMMENDATION = "ai_recommendation"
    SYSTEM_NOTIFICATION = "system_notification"


class EmployeeAlertSeverity(str, enum.Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EmployeeAlertPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class EmployeeAlertStatus(str, enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    IN_PROGRESS = "in_progress"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


class EmployeeAlertSource(str, enum.Enum):
    SYSTEM = "system"
    MANAGER = "manager"
    AI_AGENT = "ai_agent"
    ML_MODEL = "ml_model"
    RULE_ENGINE = "rule_engine"
    ERP = "erp"
    WMS = "wms"
    MONITORING = "monitoring"
    INTEGRATION = "integration"


class EmployeeAlertChannel(str, enum.Enum):
    IN_APP = "in_app"
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    WORKPLACE = "workplace"
    MULTI_CHANNEL = "multi_channel"


class EmployeeAlertDeliveryStatus(str, enum.Enum):
    PENDING = "pending"
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    PARTIALLY_DELIVERED = "partially_delivered"
    FAILED = "failed"


# ============================================================
# EMPLOYEE ALERT MODEL
# ============================================================

class EmployeeAlert(Base):
    __tablename__ = "employee_alerts"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "alert_code",
            name="uq_employee_alert_org_code",
        ),
        UniqueConstraint(
            "organization_id",
            "deduplication_key",
            name="uq_employee_alert_org_dedup",
        ),
        CheckConstraint(
            "escalation_level >= 0",
            name="employee_alert_escalation_nonnegative",
        ),
        CheckConstraint(
            "occurrence_count >= 1",
            name="employee_alert_occurrence_positive",
        ),
        CheckConstraint(
            "delivery_attempts >= 0",
            name="employee_alert_attempts_nonnegative",
        ),
        CheckConstraint(
            "confidence_score IS NULL OR "
            "(confidence_score >= 0 "
            "AND confidence_score <= 1)",
            name="employee_alert_confidence_range",
        ),
        Index(
            "ix_employee_alert_org_employee",
            "organization_id",
            "employee_id",
        ),
        Index(
            "ix_employee_alert_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_employee_alert_org_severity",
            "organization_id",
            "severity",
        ),
        Index(
            "ix_employee_alert_org_warehouse",
            "organization_id",
            "warehouse_id",
        ),
        Index(
            "ix_employee_alert_org_created",
            "organization_id",
            "created_at",
        ),
        Index(
            "ix_employee_alert_org_expiry",
            "organization_id",
            "expires_at",
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

    alert_code: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=generate_alert_code,
    )

    deduplication_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # --------------------------------------------------------
    # RECIPIENT
    # --------------------------------------------------------

    employee_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    employee_role: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    department_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    team_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    manager_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # ALERT INFORMATION
    # --------------------------------------------------------

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    alert_type: Mapped[EmployeeAlertType] = mapped_column(
        enum_column(
            EmployeeAlertType,
            "employee_alert_type",
        ),
        default=EmployeeAlertType.GENERAL,
        nullable=False,
    )

    severity: Mapped[EmployeeAlertSeverity] = mapped_column(
        enum_column(
            EmployeeAlertSeverity,
            "employee_alert_severity",
        ),
        default=EmployeeAlertSeverity.INFO,
        nullable=False,
    )

    priority: Mapped[EmployeeAlertPriority] = mapped_column(
        enum_column(
            EmployeeAlertPriority,
            "employee_alert_priority",
        ),
        default=EmployeeAlertPriority.NORMAL,
        nullable=False,
    )

    status: Mapped[EmployeeAlertStatus] = mapped_column(
        enum_column(
            EmployeeAlertStatus,
            "employee_alert_status",
        ),
        default=EmployeeAlertStatus.PENDING,
        nullable=False,
    )

    source: Mapped[EmployeeAlertSource] = mapped_column(
        enum_column(
            EmployeeAlertSource,
            "employee_alert_source",
        ),
        default=EmployeeAlertSource.SYSTEM,
        nullable=False,
    )

    # --------------------------------------------------------
    # RELATED ENTITIES
    # --------------------------------------------------------

    entity_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    entity_id: Mapped[str | None] = mapped_column(
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

    incident_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    task_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    corporate_alert_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # AI AGENT REFERENCES
    # --------------------------------------------------------

    agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    agent_action_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    model_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    model_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    confidence_score: Mapped[float | None] = mapped_column(
        nullable=True,
    )

    ai_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    recommended_action: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    requires_human_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    approval_request_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # ASSIGNMENT
    # --------------------------------------------------------

    assigned_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # ACKNOWLEDGMENT
    # --------------------------------------------------------

    acknowledged_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    acknowledgment_note: Mapped[str | None] = mapped_column(
        Text,
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

    escalated_to: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    escalation_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # RESOLUTION
    # --------------------------------------------------------

    resolved_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    resolution_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # DELIVERY
    # --------------------------------------------------------

    channel: Mapped[EmployeeAlertChannel] = mapped_column(
        enum_column(
            EmployeeAlertChannel,
            "employee_alert_channel",
        ),
        default=EmployeeAlertChannel.IN_APP,
        nullable=False,
    )

    delivery_status: Mapped[
        EmployeeAlertDeliveryStatus
    ] = mapped_column(
        enum_column(
            EmployeeAlertDeliveryStatus,
            "employee_alert_delivery_status",
        ),
        default=EmployeeAlertDeliveryStatus.PENDING,
        nullable=False,
    )

    delivery_attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    last_delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_delivery_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # ALERT PAYLOAD
    # --------------------------------------------------------

    alert_payload: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    context_data: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # OCCURRENCES
    # --------------------------------------------------------

    occurrence_count: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    first_occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    last_occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # --------------------------------------------------------
    # EXPIRATION
    # --------------------------------------------------------

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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
    # OPTIMISTIC LOCKING
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
            EmployeeAlertStatus.RESOLVED,
            EmployeeAlertStatus.DISMISSED,
            EmployeeAlertStatus.EXPIRED,
        }

    @property
    def is_critical(self) -> bool:
        return (
            self.severity
            == EmployeeAlertSeverity.CRITICAL
        )

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False

        return as_utc(self.expires_at) <= utc_now()

    @property
    def requires_attention(self) -> bool:
        return (
            not self.is_deleted
            and not self.is_terminal
            and not self.is_expired
        )

    @property
    def is_overdue(self) -> bool:
        if self.due_at is None or self.is_terminal:
            return False

        return as_utc(self.due_at) < utc_now()

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_actionable(self) -> None:
        if self.is_deleted:
            raise ValueError("Employee alert is deleted")

        if self.is_terminal:
            raise ValueError(
                "Employee alert is already terminal"
            )

        if self.is_expired:
            raise ValueError(
                "Employee alert has expired"
            )

    # ========================================================
    # ACTIVATE
    # ========================================================

    def activate(self) -> None:
        self._ensure_actionable()

        if self.status != EmployeeAlertStatus.PENDING:
            raise ValueError(
                "Only pending alerts can be activated"
            )

        self.status = EmployeeAlertStatus.ACTIVE
        self._touch()

    # ========================================================
    # ACKNOWLEDGE
    # ========================================================

    def acknowledge(
        self,
        employee_id: str,
        note: str | None = None,
    ) -> None:
        self._ensure_actionable()

        if employee_id != self.employee_id:
            raise ValueError(
                "Only the recipient can acknowledge this alert"
            )

        if self.status not in {
            EmployeeAlertStatus.ACTIVE,
            EmployeeAlertStatus.ESCALATED,
        }:
            raise ValueError(
                "Alert is not in an acknowledgeable state"
            )

        if self.acknowledged_at is not None:
            raise ValueError(
                "Alert already acknowledged"
            )

        self.acknowledged_by = employee_id
        self.acknowledged_at = utc_now()
        self.acknowledgment_note = note
        self.status = EmployeeAlertStatus.ACKNOWLEDGED
        self._touch()

    # ========================================================
    # START WORK
    # ========================================================

    def start_work(self, employee_id: str) -> None:
        self._ensure_actionable()

        if employee_id != self.employee_id:
            raise ValueError(
                "Only the assigned employee can start work"
            )

        if self.status not in {
            EmployeeAlertStatus.ACTIVE,
            EmployeeAlertStatus.ACKNOWLEDGED,
            EmployeeAlertStatus.ESCALATED,
        }:
            raise ValueError(
                "Alert cannot enter in-progress state"
            )

        self.status = EmployeeAlertStatus.IN_PROGRESS
        self._touch()

    # ========================================================
    # ESCALATE
    # ========================================================

    def escalate(
        self,
        *,
        escalated_to: str,
        reason: str,
    ) -> None:
        self._ensure_actionable()

        if not escalated_to:
            raise ValueError(
                "Escalation recipient is required"
            )

        if not reason.strip():
            raise ValueError(
                "Escalation reason is required"
            )

        self.escalation_level += 1
        self.escalated_to = escalated_to
        self.escalated_at = utc_now()
        self.escalation_reason = reason
        self.status = EmployeeAlertStatus.ESCALATED
        self._touch()

    # ========================================================
    # RESOLVE
    # ========================================================

    def resolve(
        self,
        *,
        employee_id: str,
        note: str,
    ) -> None:
        self._ensure_actionable()

        if employee_id != self.employee_id:
            raise ValueError(
                "Only the assigned employee can resolve"
            )

        if self.status not in {
            EmployeeAlertStatus.ACKNOWLEDGED,
            EmployeeAlertStatus.IN_PROGRESS,
            EmployeeAlertStatus.ESCALATED,
        }:
            raise ValueError(
                "Alert cannot be resolved in current state"
            )

        if not note.strip():
            raise ValueError(
                "Resolution note is required"
            )

        self.resolved_by = employee_id
        self.resolved_at = utc_now()
        self.resolution_note = note
        self.status = EmployeeAlertStatus.RESOLVED
        self._touch()

    # ========================================================
    # DISMISS
    # ========================================================

    def dismiss(
        self,
        *,
        employee_id: str,
        reason: str,
    ) -> None:
        self._ensure_actionable()

        if employee_id != self.employee_id:
            raise ValueError(
                "Only the recipient can dismiss this alert"
            )

        if not reason.strip():
            raise ValueError(
                "Dismissal reason is required"
            )

        if self.severity == EmployeeAlertSeverity.CRITICAL:
            raise ValueError(
                "Critical alerts require an authorized "
                "resolution or escalation workflow"
            )

        self.resolved_by = employee_id
        self.resolved_at = utc_now()
        self.resolution_note = reason
        self.status = EmployeeAlertStatus.DISMISSED
        self._touch()

    # ========================================================
    # EXPIRE
    # ========================================================

    def expire(self) -> None:
        if self.is_terminal:
            raise ValueError(
                "Terminal alert cannot expire"
            )

        if not self.is_expired:
            raise ValueError(
                "Alert expiration time has not passed"
            )

        self.status = EmployeeAlertStatus.EXPIRED
        self._touch()

    # ========================================================
    # DELIVERY TRACKING
    # ========================================================

    def queue_delivery(self) -> None:
        self._ensure_actionable()

        self.delivery_status = (
            EmployeeAlertDeliveryStatus.QUEUED
        )
        self._touch()

    def mark_sent(self) -> None:
        self._ensure_actionable()

        self.delivery_attempts += 1
        self.delivery_status = (
            EmployeeAlertDeliveryStatus.SENT
        )
        self.last_delivery_error = None
        self._touch()

    def mark_delivered(self) -> None:
        self._ensure_actionable()

        if self.delivery_status not in {
            EmployeeAlertDeliveryStatus.SENT,
            EmployeeAlertDeliveryStatus.PARTIALLY_DELIVERED,
        }:
            raise ValueError(
                "Alert must be sent before delivery confirmation"
            )

        self.delivery_status = (
            EmployeeAlertDeliveryStatus.DELIVERED
        )
        self.last_delivered_at = utc_now()
        self._touch()

    def mark_delivery_failed(self, error: str) -> None:
        self._ensure_actionable()

        if not error.strip():
            raise ValueError(
                "Delivery error is required"
            )

        self.delivery_attempts += 1
        self.delivery_status = (
            EmployeeAlertDeliveryStatus.FAILED
        )
        self.last_delivery_error = error
        self._touch()

    # ========================================================
    # AI RECOMMENDATION
    # ========================================================

    def update_ai_recommendation(
        self,
        *,
        model_name: str,
        confidence: float,
        summary: str,
        recommended_action: str,
    ) -> None:
        self._ensure_actionable()

        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError(
                "Confidence must be between 0 and 1"
            )

        if not model_name.strip():
            raise ValueError(
                "Model name is required"
            )

        self.model_name = model_name
        self.confidence_score = confidence
        self.ai_summary = summary
        self.recommended_action = recommended_action
        self._touch()

    # ========================================================
    # RECORD OCCURRENCE
    # ========================================================

    def record_occurrence(self) -> None:
        self._ensure_actionable()

        self.occurrence_count += 1
        self.last_occurred_at = utc_now()
        self._touch()

    # ========================================================
    # SOFT DELETE
    # ========================================================

    def soft_delete(self, user_id: str) -> None:
        if self.is_deleted:
            raise ValueError(
                "Alert already deleted"
            )

        if not user_id:
            raise ValueError(
                "Deleting user is required"
            )

        self.is_deleted = True
        self.deleted_by = user_id
        self.deleted_at = utc_now()
        self._touch()

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(self) -> dict[str, Any]:
        def dt(value: datetime | None) -> str | None:
            return value.isoformat() if value else None

        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "alert_code": self.alert_code,
            "employee_id": self.employee_id,
            "employee_role": self.employee_role,
            "department_id": self.department_id,
            "team_id": self.team_id,
            "manager_id": self.manager_id,
            "title": self.title,
            "message": self.message,
            "description": self.description,
            "alert_type": self.alert_type.value,
            "severity": self.severity.value,
            "priority": self.priority.value,
            "status": self.status.value,
            "source": self.source.value,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "warehouse_id": self.warehouse_id,
            "product_id": self.product_id,
            "supplier_id": self.supplier_id,
            "delivery_id": self.delivery_id,
            "incident_id": self.incident_id,
            "task_id": self.task_id,
            "corporate_alert_id": self.corporate_alert_id,
            "agent_run_id": self.agent_run_id,
            "agent_action_id": self.agent_action_id,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "confidence_score": self.confidence_score,
            "ai_summary": self.ai_summary,
            "recommended_action": self.recommended_action,
            "requires_human_approval": (
                self.requires_human_approval
            ),
            "approval_request_id": self.approval_request_id,
            "assigned_by": self.assigned_by,
            "assigned_at": dt(self.assigned_at),
            "due_at": dt(self.due_at),
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": dt(self.acknowledged_at),
            "acknowledgment_note": self.acknowledgment_note,
            "escalation_level": self.escalation_level,
            "escalated_to": self.escalated_to,
            "escalated_at": dt(self.escalated_at),
            "escalation_reason": self.escalation_reason,
            "resolved_by": self.resolved_by,
            "resolved_at": dt(self.resolved_at),
            "resolution_note": self.resolution_note,
            "channel": self.channel.value,
            "delivery_status": self.delivery_status.value,
            "delivery_attempts": self.delivery_attempts,
            "last_delivered_at": dt(self.last_delivered_at),
            "last_delivery_error": self.last_delivery_error,
            "alert_payload": self.alert_payload,
            "context_data": self.context_data,
            "occurrence_count": self.occurrence_count,
            "first_occurred_at": dt(self.first_occurred_at),
            "last_occurred_at": dt(self.last_occurred_at),
            "expires_at": dt(self.expires_at),
            "is_critical": self.is_critical,
            "is_overdue": self.is_overdue,
            "requires_attention": self.requires_attention,
            "is_deleted": self.is_deleted,
            "version": self.version,
            "created_at": dt(self.created_at),
            "updated_at": dt(self.updated_at),
        }

    def __repr__(self) -> str:
        return (
            f"<EmployeeAlert("
            f"id={self.id}, "
            f"employee_id={self.employee_id}, "
            f"status={self.status.value}, "
            f"severity={self.severity.value}"
            f")>"
        )
