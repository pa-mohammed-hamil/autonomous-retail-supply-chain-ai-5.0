from __future__ import annotations

"""Planned module: corporate alert. Implementation pending."""

"""
backend/models/corporate_alert.py

Autonomous Retail Supply Chain AI 5.0
Enterprise Corporate Alert Model

Features:
- Multi-tenant corporate alerts
- AI-generated and rule-based alerts
- Inventory, supplier, logistics and security alerts
- Severity and priority classification
- Acknowledgment and resolution workflows
- Alert deduplication
- Escalation management
- Delivery tracking
- Related entity and agent references
- UTC timestamps and soft deletion
- Optimistic concurrency control

Dependencies:
    SQLAlchemy >= 2.0

Uses:
    backend.models.base.Base
"""


import enum
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


def enum_column(enum_class, name: str):
    return SQLEnum(
        enum_class,
        name=name,
        native_enum=False,
        values_callable=lambda members: [
            member.value for member in members
        ],
        validate_strings=True,
        length=50,
    )


def normalize_datetime(
    value: datetime,
) -> datetime:
    """Normalize datetime for UTC comparisons."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


# ============================================================
# ENUMS
# ============================================================

class CorporateAlertType(str, enum.Enum):
    INVENTORY_SHORTAGE = "inventory_shortage"
    INVENTORY_OVERSTOCK = "inventory_overstock"
    STOCKOUT_RISK = "stockout_risk"
    DEMAND_SPIKE = "demand_spike"
    DEMAND_DROP = "demand_drop"

    SUPPLIER_RISK = "supplier_risk"
    SUPPLIER_DELAY = "supplier_delay"
    SUPPLIER_QUALITY = "supplier_quality"

    PROCUREMENT = "procurement"
    PURCHASE_ORDER = "purchase_order"

    WAREHOUSE_CAPACITY = "warehouse_capacity"
    WAREHOUSE_INCIDENT = "warehouse_incident"

    LOGISTICS_DELAY = "logistics_delay"
    DELIVERY_FAILURE = "delivery_failure"
    FLEET_INCIDENT = "fleet_incident"

    FINANCIAL_RISK = "financial_risk"
    COST_ANOMALY = "cost_anomaly"

    SECURITY_INCIDENT = "security_incident"
    ACCESS_VIOLATION = "access_violation"
    POLICY_VIOLATION = "policy_violation"

    AI_AGENT_FAILURE = "ai_agent_failure"
    MODEL_DRIFT = "model_drift"
    DATA_QUALITY = "data_quality"
    SYSTEM_HEALTH = "system_health"

    APPROVAL_REQUIRED = "approval_required"
    EMERGENCY = "emergency"
    COMPLIANCE = "compliance"
    GENERAL = "general"


class CorporateAlertSeverity(str, enum.Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CorporateAlertPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class CorporateAlertStatus(str, enum.Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    INVESTIGATING = "investigating"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


class CorporateAlertSource(str, enum.Enum):
    SYSTEM = "system"
    AI_AGENT = "ai_agent"
    ML_MODEL = "ml_model"
    RULE_ENGINE = "rule_engine"
    USER = "user"
    INTEGRATION = "integration"
    MONITORING = "monitoring"


class AlertDeliveryStatus(str, enum.Enum):
    PENDING = "pending"
    QUEUED = "queued"
    PARTIALLY_SENT = "partially_sent"
    SENT = "sent"
    FAILED = "failed"


# ============================================================
# CORPORATE ALERT MODEL
# ============================================================

class CorporateAlert(Base):
    __tablename__ = "corporate_alerts"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "deduplication_key",
            name="uq_corporate_alert_dedup",
        ),
        CheckConstraint(
            "escalation_level >= 0",
            name="corporate_alert_escalation_nonnegative",
        ),
        CheckConstraint(
            "occurrence_count >= 1",
            name="corporate_alert_occurrence_positive",
        ),
        CheckConstraint(
            "delivery_attempts >= 0",
            name="corporate_alert_delivery_attempts",
        ),
        CheckConstraint(
            "confidence_score IS NULL OR "
            "(confidence_score >= 0 AND confidence_score <= 1)",
            name="corporate_alert_confidence_range",
        ),
        Index(
            "ix_corporate_alert_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_corporate_alert_org_severity",
            "organization_id",
            "severity",
        ),
        Index(
            "ix_corporate_alert_org_type",
            "organization_id",
            "alert_type",
        ),
        Index(
            "ix_corporate_alert_org_created",
            "organization_id",
            "created_at",
        ),
        Index(
            "ix_corporate_alert_assignee",
            "organization_id",
            "assigned_to",
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
        String(100),
        unique=True,
        nullable=False,
        default=lambda: f"ALT-{uuid.uuid4().hex[:16].upper()}",
    )

    deduplication_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # --------------------------------------------------------
    # ALERT CONTENT
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

    alert_type: Mapped[CorporateAlertType] = mapped_column(
        enum_column(
            CorporateAlertType,
            "corporate_alert_type",
        ),
        default=CorporateAlertType.GENERAL,
        nullable=False,
    )

    severity: Mapped[CorporateAlertSeverity] = mapped_column(
        enum_column(
            CorporateAlertSeverity,
            "corporate_alert_severity",
        ),
        default=CorporateAlertSeverity.INFO,
        nullable=False,
    )

    priority: Mapped[CorporateAlertPriority] = mapped_column(
        enum_column(
            CorporateAlertPriority,
            "corporate_alert_priority",
        ),
        default=CorporateAlertPriority.NORMAL,
        nullable=False,
    )

    status: Mapped[CorporateAlertStatus] = mapped_column(
        enum_column(
            CorporateAlertStatus,
            "corporate_alert_status",
        ),
        default=CorporateAlertStatus.OPEN,
        nullable=False,
    )

    source: Mapped[CorporateAlertSource] = mapped_column(
        enum_column(
            CorporateAlertSource,
            "corporate_alert_source",
        ),
        default=CorporateAlertSource.SYSTEM,
        nullable=False,
    )

    # --------------------------------------------------------
    # ORIGIN AND ENTITY REFERENCES
    # --------------------------------------------------------

    source_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    source_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    entity_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    entity_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
        index=True,
    )

    warehouse_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    supplier_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    product_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

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

    # --------------------------------------------------------
    # AI / ML INFORMATION
    # --------------------------------------------------------

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

    recommended_action: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # ALERT DATA
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
    # ASSIGNMENT
    # --------------------------------------------------------

    assigned_to: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    assigned_team: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    assigned_role: Mapped[str | None] = mapped_column(
        String(100),
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
    # DELIVERY TRACKING
    # --------------------------------------------------------

    delivery_status: Mapped[AlertDeliveryStatus] = (
        mapped_column(
            enum_column(
                AlertDeliveryStatus,
                "corporate_alert_delivery_status",
            ),
            default=AlertDeliveryStatus.PENDING,
            nullable=False,
        )
    )

    delivery_attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    last_delivery_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    last_delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # DEDUPLICATION AND OCCURRENCE
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
    # LIFECYCLE
    # --------------------------------------------------------

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # OBSERVABILITY
    # --------------------------------------------------------

    correlation_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    trace_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    # --------------------------------------------------------
    # TIMESTAMPS AND CONCURRENCY
    # --------------------------------------------------------

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
    def is_open(self) -> bool:
        return self.status == CorporateAlertStatus.OPEN

    @property
    def is_resolved(self) -> bool:
        return self.status == CorporateAlertStatus.RESOLVED

    @property
    def is_critical(self) -> bool:
        return self.severity == CorporateAlertSeverity.CRITICAL

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            CorporateAlertStatus.RESOLVED,
            CorporateAlertStatus.DISMISSED,
            CorporateAlertStatus.EXPIRED,
        }

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False

        return (
            normalize_datetime(self.expires_at)
            <= utc_now()
        )

    @property
    def requires_attention(self) -> bool:
        return (
            not self.is_deleted
            and not self.is_terminal
            and not self.is_expired
        )

    # ========================================================
    # INTERNAL VALIDATION
    # ========================================================

    def _ensure_actionable(self) -> None:
        if self.is_deleted:
            raise ValueError("Alert has been deleted")

        if self.is_terminal:
            raise ValueError(
                "Alert is already in a terminal state"
            )

        if self.is_expired:
            raise ValueError("Alert has expired")

    def _touch(self) -> None:
        self.updated_at = utc_now()

    # ========================================================
    # ACKNOWLEDGMENT
    # ========================================================

    def acknowledge(
        self,
        user_id: str,
        note: str | None = None,
    ) -> None:
        self._ensure_actionable()

        if not user_id:
            raise ValueError(
                "Acknowledging user is required"
            )

        if self.acknowledged_at is not None:
            raise ValueError(
                "Alert has already been acknowledged"
            )

        self.acknowledged_by = user_id
        self.acknowledged_at = utc_now()
        self.acknowledgment_note = note

        if self.status == CorporateAlertStatus.OPEN:
            self.status = CorporateAlertStatus.ACKNOWLEDGED

        self._touch()

    # ========================================================
    # INVESTIGATION
    # ========================================================

    def start_investigation(
        self,
        user_id: str,
    ) -> None:
        self._ensure_actionable()

        if not user_id:
            raise ValueError(
                "Investigating user is required"
            )

        if self.status not in {
            CorporateAlertStatus.OPEN,
            CorporateAlertStatus.ACKNOWLEDGED,
            CorporateAlertStatus.ESCALATED,
        }:
            raise ValueError(
                "Invalid state for investigation"
            )

        self.assigned_to = user_id
        self.status = CorporateAlertStatus.INVESTIGATING
        self._touch()

    # ========================================================
    # ESCALATION
    # ========================================================

    def escalate(
        self,
        escalated_to: str,
        reason: str,
    ) -> None:
        self._ensure_actionable()

        if not escalated_to:
            raise ValueError(
                "Escalation recipient is required"
            )

        if not reason or not reason.strip():
            raise ValueError(
                "Escalation reason is required"
            )

        self.escalation_level += 1
        self.escalated_to = escalated_to
        self.escalated_at = utc_now()
        self.escalation_reason = reason
        self.status = CorporateAlertStatus.ESCALATED
        self._touch()

    # ========================================================
    # RESOLUTION
    # ========================================================

    def resolve(
        self,
        user_id: str,
        resolution_note: str,
    ) -> None:
        self._ensure_actionable()

        if not user_id:
            raise ValueError(
                "Resolving user is required"
            )

        if not resolution_note.strip():
            raise ValueError(
                "Resolution note is required"
            )

        self.resolved_by = user_id
        self.resolved_at = utc_now()
        self.resolution_note = resolution_note
        self.status = CorporateAlertStatus.RESOLVED
        self._touch()

    # ========================================================
    # DISMISSAL
    # ========================================================

    def dismiss(
        self,
        user_id: str,
        reason: str,
    ) -> None:
        self._ensure_actionable()

        if not user_id:
            raise ValueError(
                "Dismissing user is required"
            )

        if not reason.strip():
            raise ValueError(
                "Dismissal reason is required"
            )

        self.resolved_by = user_id
        self.resolved_at = utc_now()
        self.resolution_note = reason
        self.status = CorporateAlertStatus.DISMISSED
        self._touch()

    # ========================================================
    # EXPIRATION
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

        self.status = CorporateAlertStatus.EXPIRED
        self._touch()

    # ========================================================
    # DEDUPLICATION
    # ========================================================

    def record_occurrence(self) -> None:
        self._ensure_actionable()

        self.occurrence_count += 1
        self.last_occurred_at = utc_now()
        self._touch()

    # ========================================================
    # DELIVERY TRACKING
    # ========================================================

    def mark_delivery_queued(self) -> None:
        if self.is_deleted:
            raise ValueError("Alert is deleted")

        self.delivery_status = AlertDeliveryStatus.QUEUED
        self._touch()

    def mark_delivery_sent(self) -> None:
        if self.is_deleted:
            raise ValueError("Alert is deleted")

        self.delivery_attempts += 1
        self.delivery_status = AlertDeliveryStatus.SENT
        self.last_delivered_at = utc_now()
        self.last_delivery_error = None
        self._touch()

    def mark_delivery_failed(
        self,
        error: str,
    ) -> None:
        if self.is_deleted:
            raise ValueError("Alert is deleted")

        self.delivery_attempts += 1
        self.delivery_status = AlertDeliveryStatus.FAILED
        self.last_delivery_error = error
        self._touch()

    # ========================================================
    # SOFT DELETE
    # ========================================================

    def soft_delete(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Alert already deleted"
            )

        self.is_deleted = True
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
            "title": self.title,
            "message": self.message,
            "description": self.description,
            "alert_type": self.alert_type.value,
            "severity": self.severity.value,
            "priority": self.priority.value,
            "status": self.status.value,
            "source": self.source.value,
            "source_name": self.source_name,
            "source_id": self.source_id,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "warehouse_id": self.warehouse_id,
            "supplier_id": self.supplier_id,
            "product_id": self.product_id,
            "agent_run_id": self.agent_run_id,
            "agent_action_id": self.agent_action_id,
            "approval_request_id": self.approval_request_id,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "confidence_score": self.confidence_score,
            "recommended_action": self.recommended_action,
            "alert_payload": self.alert_payload,
            "context_data": self.context_data,
            "assigned_to": self.assigned_to,
            "assigned_team": self.assigned_team,
            "assigned_role": self.assigned_role,
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": dt(self.acknowledged_at),
            "escalation_level": self.escalation_level,
            "escalated_to": self.escalated_to,
            "escalated_at": dt(self.escalated_at),
            "resolved_by": self.resolved_by,
            "resolved_at": dt(self.resolved_at),
            "resolution_note": self.resolution_note,
            "delivery_status": self.delivery_status.value,
            "delivery_attempts": self.delivery_attempts,
            "occurrence_count": self.occurrence_count,
            "first_occurred_at": dt(self.first_occurred_at),
            "last_occurred_at": dt(self.last_occurred_at),
            "expires_at": dt(self.expires_at),
            "is_deleted": self.is_deleted,
            "requires_attention": self.requires_attention,
            "trace_id": self.trace_id,
            "correlation_id": self.correlation_id,
            "version": self.version,
            "created_at": dt(self.created_at),
            "updated_at": dt(self.updated_at),
        }

    def __repr__(self) -> str:
        return (
            f"<CorporateAlert("
            f"id={self.id}, "
            f"type={self.alert_type.value}, "
            f"severity={self.severity.value}, "
            f"status={self.status.value}"
            f")>"
        )
