from __future__ import annotations

"""Planned module: escalation. Implementation pending."""

"""
backend/models/escalation.py

Autonomous Retail Supply Chain AI 5.0
Enterprise Escalation Management ORM Model

Features:
- Multi-tenant escalation management
- Employee and corporate alert escalation
- Incident, delivery and supplier-risk escalation
- SLA deadlines and breach tracking
- Employee, manager, team and department routing
- AI-generated escalation recommendations
- Human approval references
- Acknowledgment and resolution workflow
- Escalation history metadata
- Optimistic concurrency
- Soft deletion and UTC audit timestamps

Requirements:
    Python >= 3.10
    SQLAlchemy >= 2.0

Shared ORM:
    backend.models.base.Base
"""


import enum
import math
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


def generate_escalation_code() -> str:
    return f"ESC-{uuid.uuid4().hex[:16].upper()}"


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


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


# ============================================================
# ENUMS
# ============================================================

class EscalationType(str, enum.Enum):
    EMPLOYEE_ALERT = "employee_alert"
    CORPORATE_ALERT = "corporate_alert"
    WAREHOUSE_INCIDENT = "warehouse_incident"
    SAFETY_INCIDENT = "safety_incident"
    EMERGENCY = "emergency"

    INVENTORY_SHORTAGE = "inventory_shortage"
    STOCKOUT_RISK = "stockout_risk"
    DEMAND_ANOMALY = "demand_anomaly"

    SUPPLIER_RISK = "supplier_risk"
    SUPPLIER_DELAY = "supplier_delay"
    PURCHASE_ORDER = "purchase_order"

    DELIVERY_DELAY = "delivery_delay"
    DELIVERY_FAILURE = "delivery_failure"
    LOGISTICS_DISRUPTION = "logistics_disruption"

    EQUIPMENT_FAILURE = "equipment_failure"
    PREDICTIVE_MAINTENANCE = "predictive_maintenance"

    SECURITY_INCIDENT = "security_incident"
    COMPLIANCE_VIOLATION = "compliance_violation"

    AI_AGENT_FAILURE = "ai_agent_failure"
    MODEL_DRIFT = "model_drift"
    SYSTEM_FAILURE = "system_failure"

    APPROVAL_DELAY = "approval_delay"
    SLA_BREACH = "sla_breach"
    CUSTOMER_COMPLAINT = "customer_complaint"
    OTHER = "other"


class EscalationStatus(str, enum.Enum):
    OPEN = "open"
    ASSIGNED = "assigned"
    ACKNOWLEDGED = "acknowledged"
    IN_PROGRESS = "in_progress"
    ESCALATED = "escalated"
    PENDING_APPROVAL = "pending_approval"
    RESOLVED = "resolved"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class EscalationSeverity(str, enum.Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EscalationPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class EscalationSource(str, enum.Enum):
    SYSTEM = "system"
    EMPLOYEE = "employee"
    MANAGER = "manager"
    AI_AGENT = "ai_agent"
    ML_MODEL = "ml_model"
    RULE_ENGINE = "rule_engine"
    MONITORING = "monitoring"
    INTEGRATION = "integration"
    CUSTOMER_SUPPORT = "customer_support"


class EscalationTargetType(str, enum.Enum):
    EMPLOYEE = "employee"
    MANAGER = "manager"
    TEAM = "team"
    DEPARTMENT = "department"
    ROLE = "role"
    ON_CALL = "on_call"
    EXTERNAL = "external"


class EscalationTrigger(str, enum.Enum):
    MANUAL = "manual"
    TIMEOUT = "timeout"
    SLA_BREACH = "sla_breach"
    SEVERITY = "severity"
    REPEATED_FAILURE = "repeated_failure"
    RISK_THRESHOLD = "risk_threshold"
    UNACKNOWLEDGED = "unacknowledged"
    APPROVAL_TIMEOUT = "approval_timeout"
    AUTOMATED_RULE = "automated_rule"
    AI_RECOMMENDATION = "ai_recommendation"


# ============================================================
# ESCALATION MODEL
# ============================================================

class Escalation(Base):
    __tablename__ = "escalations"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "escalation_code",
            name="uq_escalation_org_code",
        ),
        UniqueConstraint(
            "organization_id",
            "deduplication_key",
            name="uq_escalation_org_dedup",
        ),
        CheckConstraint(
            "escalation_level >= 1",
            name="escalation_level_positive",
        ),
        CheckConstraint(
            "max_escalation_level >= 1",
            name="escalation_max_level_positive",
        ),
        CheckConstraint(
            "escalation_level <= max_escalation_level",
            name="escalation_level_limit",
        ),
        CheckConstraint(
            "sla_minutes IS NULL OR sla_minutes > 0",
            name="escalation_sla_minutes_positive",
        ),
        CheckConstraint(
            "acknowledgment_sla_minutes IS NULL OR "
            "acknowledgment_sla_minutes > 0",
            name="escalation_ack_sla_positive",
        ),
        CheckConstraint(
            "confidence_score IS NULL OR "
            "(confidence_score >= 0 "
            "AND confidence_score <= 1)",
            name="escalation_confidence_range",
        ),
        CheckConstraint(
            "occurrence_count >= 1",
            name="escalation_occurrences_positive",
        ),
        Index(
            "ix_escalation_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_escalation_org_severity",
            "organization_id",
            "severity",
        ),
        Index(
            "ix_escalation_org_source_entity",
            "organization_id",
            "entity_type",
            "entity_id",
        ),
        Index(
            "ix_escalation_org_assignee",
            "organization_id",
            "assigned_to",
        ),
        Index(
            "ix_escalation_org_sla",
            "organization_id",
            "sla_deadline_at",
        ),
        Index(
            "ix_escalation_org_created",
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

    escalation_code: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=generate_escalation_code,
    )

    deduplication_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # --------------------------------------------------------
    # ESCALATION INFORMATION
    # --------------------------------------------------------

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    escalation_type: Mapped[EscalationType] = mapped_column(
        enum_column(
            EscalationType,
            "escalation_type",
        ),
        default=EscalationType.OTHER,
        nullable=False,
    )

    status: Mapped[EscalationStatus] = mapped_column(
        enum_column(
            EscalationStatus,
            "escalation_status",
        ),
        default=EscalationStatus.OPEN,
        nullable=False,
    )

    severity: Mapped[EscalationSeverity] = mapped_column(
        enum_column(
            EscalationSeverity,
            "escalation_severity",
        ),
        default=EscalationSeverity.MEDIUM,
        nullable=False,
    )

    priority: Mapped[EscalationPriority] = mapped_column(
        enum_column(
            EscalationPriority,
            "escalation_priority",
        ),
        default=EscalationPriority.NORMAL,
        nullable=False,
    )

    source: Mapped[EscalationSource] = mapped_column(
        enum_column(
            EscalationSource,
            "escalation_source",
        ),
        default=EscalationSource.SYSTEM,
        nullable=False,
    )

    trigger: Mapped[EscalationTrigger] = mapped_column(
        enum_column(
            EscalationTrigger,
            "escalation_trigger",
        ),
        default=EscalationTrigger.MANUAL,
        nullable=False,
    )

    # --------------------------------------------------------
    # SOURCE ENTITY
    # --------------------------------------------------------

    entity_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    entity_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    employee_alert_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )

    corporate_alert_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )

    incident_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
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

    delivery_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    purchase_order_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # ESCALATION ROUTING
    # --------------------------------------------------------

    target_type: Mapped[EscalationTargetType] = mapped_column(
        enum_column(
            EscalationTargetType,
            "escalation_target_type",
        ),
        default=EscalationTargetType.MANAGER,
        nullable=False,
    )

    assigned_to: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    assigned_team_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    assigned_department_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    assigned_role: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    assigned_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # ESCALATION LEVEL
    # --------------------------------------------------------

    escalation_level: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    max_escalation_level: Mapped[int] = mapped_column(
        Integer,
        default=5,
        nullable=False,
    )

    previous_assignee_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    last_escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # SLA MANAGEMENT
    # --------------------------------------------------------

    sla_minutes: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    acknowledgment_sla_minutes: Mapped[
        int | None
    ] = mapped_column(
        Integer,
        nullable=True,
    )

    sla_deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    acknowledgment_deadline_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    sla_breached: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    sla_breached_at: Mapped[datetime | None] = mapped_column(
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

    closed_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # AI INTEGRATION
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
    # EVENT HISTORY
    # --------------------------------------------------------

    escalation_history: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    context_data: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    occurrence_count: Mapped[int] = mapped_column(
        Integer,
        default=1,
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
            EscalationStatus.CLOSED,
            EscalationStatus.CANCELLED,
        }

    @property
    def is_critical(self) -> bool:
        return self.severity == EscalationSeverity.CRITICAL

    @property
    def is_overdue(self) -> bool:
        if self.sla_deadline_at is None:
            return False

        if self.status in {
            EscalationStatus.RESOLVED,
            EscalationStatus.CLOSED,
            EscalationStatus.CANCELLED,
        }:
            return False

        return as_utc(self.sla_deadline_at) <= utc_now()

    @property
    def acknowledgment_overdue(self) -> bool:
        if self.acknowledged_at is not None:
            return False

        if self.acknowledgment_deadline_at is None:
            return False

        if self.status in {
            EscalationStatus.RESOLVED,
            EscalationStatus.CLOSED,
            EscalationStatus.CANCELLED,
        }:
            return False

        return (
            as_utc(self.acknowledgment_deadline_at)
            <= utc_now()
        )

    @property
    def can_escalate_further(self) -> bool:
        return (
            not self.is_deleted
            and not self.is_terminal
            and self.status != EscalationStatus.RESOLVED
            and self.escalation_level
            < self.max_escalation_level
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_active(self) -> None:
        if self.is_deleted:
            raise ValueError("Escalation is deleted")

        if self.is_terminal:
            raise ValueError(
                "Escalation is already closed or cancelled"
            )

    def _append_history(
        self,
        action: str,
        *,
        actor_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        history = list(self.escalation_history or [])

        history.append(
            {
                "action": action,
                "actor_id": actor_id,
                "timestamp": utc_now().isoformat(),
                "level": self.escalation_level,
                "details": details or {},
            }
        )

        self.escalation_history = history
        self._touch()

    # ========================================================
    # ASSIGN
    # ========================================================

    def assign(
        self,
        *,
        assigned_to: str,
        assigned_by: str,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            EscalationStatus.OPEN,
            EscalationStatus.ESCALATED,
        }:
            raise ValueError(
                "Escalation cannot be assigned in current state"
            )

        if not assigned_to or not assigned_by:
            raise ValueError(
                "Assignee and assigning user are required"
            )

        self.previous_assignee_id = self.assigned_to
        self.assigned_to = assigned_to
        self.assigned_by = assigned_by
        self.assigned_at = utc_now()
        self.status = EscalationStatus.ASSIGNED

        self._append_history(
            "assigned",
            actor_id=assigned_by,
            details={"assigned_to": assigned_to},
        )

    # ========================================================
    # CONFIGURE SLA
    # ========================================================

    def configure_sla(
        self,
        *,
        resolution_minutes: int,
        acknowledgment_minutes: int,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            EscalationStatus.OPEN,
            EscalationStatus.ASSIGNED,
        }:
            raise ValueError(
                "SLA cannot be reconfigured in current state"
            )

        if resolution_minutes <= 0:
            raise ValueError(
                "Resolution SLA must be positive"
            )

        if acknowledgment_minutes <= 0:
            raise ValueError(
                "Acknowledgment SLA must be positive"
            )

        now = utc_now()

        self.sla_minutes = resolution_minutes
        self.acknowledgment_sla_minutes = (
            acknowledgment_minutes
        )

        self.sla_deadline_at = now + timedelta(
            minutes=resolution_minutes
        )

        self.acknowledgment_deadline_at = now + timedelta(
            minutes=acknowledgment_minutes
        )

        self._append_history(
            "sla_configured",
            details={
                "resolution_minutes": resolution_minutes,
                "acknowledgment_minutes": (
                    acknowledgment_minutes
                ),
            },
        )

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

        if self.status != EscalationStatus.ASSIGNED:
            raise ValueError(
                "Escalation must be assigned first"
            )

        if user_id != self.assigned_to:
            raise ValueError(
                "Only the assigned user can acknowledge"
            )

        self.acknowledged_by = user_id
        self.acknowledged_at = utc_now()
        self.acknowledgment_note = note
        self.status = EscalationStatus.ACKNOWLEDGED

        self._append_history(
            "acknowledged",
            actor_id=user_id,
        )

    # ========================================================
    # START INVESTIGATION
    # ========================================================

    def start_investigation(self, user_id: str) -> None:
        self._ensure_active()

        if self.status != EscalationStatus.ACKNOWLEDGED:
            raise ValueError(
                "Escalation must be acknowledged first"
            )

        if user_id != self.assigned_to:
            raise ValueError(
                "Only assigned user can start investigation"
            )

        self.status = EscalationStatus.IN_PROGRESS

        self._append_history(
            "investigation_started",
            actor_id=user_id,
        )

    # ========================================================
    # ESCALATE TO NEXT LEVEL
    # ========================================================

    def escalate(
        self,
        *,
        new_assignee_id: str,
        escalated_by: str,
        reason: str,
    ) -> None:
        self._ensure_active()

        if not self.can_escalate_further:
            raise ValueError(
                "Maximum escalation level reached"
            )

        if self.status not in {
            EscalationStatus.ASSIGNED,
            EscalationStatus.ACKNOWLEDGED,
            EscalationStatus.IN_PROGRESS,
            EscalationStatus.ESCALATED,
        }:
            raise ValueError(
                "Escalation cannot advance in current state"
            )

        if not new_assignee_id or not escalated_by:
            raise ValueError(
                "Assignee and actor are required"
            )

        if not reason.strip():
            raise ValueError(
                "Escalation reason is required"
            )

        old_assignee = self.assigned_to

        self.previous_assignee_id = old_assignee
        self.assigned_to = new_assignee_id
        self.assigned_by = escalated_by
        self.assigned_at = utc_now()
        self.escalation_level += 1
        self.last_escalated_at = utc_now()
        self.reason = reason

        # A new escalation level needs fresh acknowledgment.
        self.acknowledged_by = None
        self.acknowledged_at = None
        self.acknowledgment_note = None

        self.status = EscalationStatus.ESCALATED

        self._append_history(
            "escalated",
            actor_id=escalated_by,
            details={
                "previous_assignee": old_assignee,
                "new_assignee": new_assignee_id,
                "reason": reason,
            },
        )

    # ========================================================
    # RECORD SLA BREACH
    # ========================================================

    def record_sla_breach(self) -> None:
        self._ensure_active()

        if self.status == EscalationStatus.RESOLVED:
            raise ValueError(
                "Resolved escalation cannot breach SLA"
            )

        if not self.is_overdue:
            raise ValueError(
                "SLA deadline has not passed"
            )

        if self.sla_breached:
            return

        self.sla_breached = True
        self.sla_breached_at = utc_now()

        self._append_history(
            "sla_breached",
            details={
                "sla_deadline": (
                    self.sla_deadline_at.isoformat()
                    if self.sla_deadline_at else None
                ),
            },
        )

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
        self._ensure_active()

        if self.status == EscalationStatus.RESOLVED:
            raise ValueError(
                "Resolved escalation cannot be modified"
            )

        if (
            not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise ValueError(
                "Confidence must be between 0 and 1"
            )

        if not model_name.strip():
            raise ValueError("Model name is required")

        self.model_name = model_name
        self.confidence_score = confidence
        self.ai_summary = summary
        self.recommended_action = recommended_action

        self._append_history(
            "ai_recommendation_updated",
            details={
                "model_name": model_name,
                "confidence": confidence,
            },
        )

    # ========================================================
    # APPROVAL WORKFLOW
    # ========================================================

    def request_approval(
        self,
        approval_request_id: str,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            EscalationStatus.ACKNOWLEDGED,
            EscalationStatus.IN_PROGRESS,
        }:
            raise ValueError(
                "Escalation must be under review"
            )

        if not approval_request_id:
            raise ValueError(
                "Approval request ID is required"
            )

        self.requires_human_approval = True
        self.approval_request_id = approval_request_id
        self.status = EscalationStatus.PENDING_APPROVAL

        self._append_history(
            "approval_requested",
            details={
                "approval_request_id": approval_request_id
            },
        )

    # ========================================================
    # RESOLVE
    # ========================================================

    def resolve(
        self,
        *,
        user_id: str,
        note: str,
        approval_confirmed: bool = False,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            EscalationStatus.ACKNOWLEDGED,
            EscalationStatus.IN_PROGRESS,
            EscalationStatus.PENDING_APPROVAL,
        }:
            raise ValueError(
                "Escalation cannot be resolved in current state"
            )

        if not user_id or not note.strip():
            raise ValueError(
                "Resolver and resolution note are required"
            )

        if (
            self.requires_human_approval
            and not approval_confirmed
        ):
            raise ValueError(
                "Verified approval is required"
            )

        self.status = EscalationStatus.RESOLVED
        self.resolved_by = user_id
        self.resolved_at = utc_now()
        self.resolution_note = note

        self._append_history(
            "resolved",
            actor_id=user_id,
            details={"note": note},
        )

    # ========================================================
    # CLOSE
    # ========================================================

    def close(self, user_id: str) -> None:
        self._ensure_active()

        if self.status != EscalationStatus.RESOLVED:
            raise ValueError(
                "Escalation must be resolved before closure"
            )

        if not user_id:
            raise ValueError(
                "Closing user is required"
            )

        self.status = EscalationStatus.CLOSED
        self.closed_by = user_id
        self.closed_at = utc_now()

        self._append_history(
            "closed",
            actor_id=user_id,
        )

    # ========================================================
    # CANCEL
    # ========================================================

    def cancel(
        self,
        *,
        user_id: str,
        reason: str,
    ) -> None:
        self._ensure_active()

        if self.status == EscalationStatus.RESOLVED:
            raise ValueError(
                "Resolved escalation cannot be cancelled"
            )

        if not user_id or not reason.strip():
            raise ValueError(
                "Actor and cancellation reason required"
            )

        if self.is_critical:
            raise ValueError(
                "Critical escalation requires an "
                "authorized safety review before cancellation"
            )

        self.status = EscalationStatus.CANCELLED
        self.resolution_note = reason

        self._append_history(
            "cancelled",
            actor_id=user_id,
            details={"reason": reason},
        )

    # ========================================================
    # SOFT DELETE
    # ========================================================

    def soft_delete(self, user_id: str) -> None:
        if self.is_deleted:
            raise ValueError(
                "Escalation already deleted"
            )

        if not user_id:
            raise ValueError(
                "Deleting user is required"
            )

        if not self.is_terminal:
            raise ValueError(
                "Only closed or cancelled escalations "
                "can be soft deleted"
            )

        self.is_deleted = True
        self.deleted_by = user_id
        self.deleted_at = utc_now()

        self._append_history(
            "soft_deleted",
            actor_id=user_id,
        )

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(self) -> dict[str, Any]:
        def dt(value: datetime | None) -> str | None:
            return value.isoformat() if value else None

        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "escalation_code": self.escalation_code,
            "deduplication_key": self.deduplication_key,
            "title": self.title,
            "description": self.description,
            "reason": self.reason,
            "escalation_type": self.escalation_type.value,
            "status": self.status.value,
            "severity": self.severity.value,
            "priority": self.priority.value,
            "source": self.source.value,
            "trigger": self.trigger.value,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "employee_alert_id": self.employee_alert_id,
            "corporate_alert_id": self.corporate_alert_id,
            "incident_id": self.incident_id,
            "warehouse_id": self.warehouse_id,
            "supplier_id": self.supplier_id,
            "product_id": self.product_id,
            "delivery_id": self.delivery_id,
            "purchase_order_id": self.purchase_order_id,
            "target_type": self.target_type.value,
            "assigned_to": self.assigned_to,
            "assigned_team_id": self.assigned_team_id,
            "assigned_department_id": (
                self.assigned_department_id
            ),
            "assigned_role": self.assigned_role,
            "assigned_by": self.assigned_by,
            "assigned_at": dt(self.assigned_at),
            "escalation_level": self.escalation_level,
            "max_escalation_level": self.max_escalation_level,
            "previous_assignee_id": self.previous_assignee_id,
            "last_escalated_at": dt(self.last_escalated_at),
            "sla_minutes": self.sla_minutes,
            "acknowledgment_sla_minutes": (
                self.acknowledgment_sla_minutes
            ),
            "sla_deadline_at": dt(self.sla_deadline_at),
            "acknowledgment_deadline_at": dt(
                self.acknowledgment_deadline_at
            ),
            "sla_breached": self.sla_breached,
            "sla_breached_at": dt(self.sla_breached_at),
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": dt(self.acknowledged_at),
            "acknowledgment_note": self.acknowledgment_note,
            "resolved_by": self.resolved_by,
            "resolved_at": dt(self.resolved_at),
            "resolution_note": self.resolution_note,
            "closed_by": self.closed_by,
            "closed_at": dt(self.closed_at),
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
            "escalation_history": self.escalation_history,
            "context_data": self.context_data,
            "occurrence_count": self.occurrence_count,
            "is_overdue": self.is_overdue,
            "acknowledgment_overdue": (
                self.acknowledgment_overdue
            ),
            "can_escalate_further": (
                self.can_escalate_further
            ),
            "is_deleted": self.is_deleted,
            "version": self.version,
            "created_at": dt(self.created_at),
            "updated_at": dt(self.updated_at),
        }

    def __repr__(self) -> str:
        return (
            f"<Escalation("
            f"id={self.id}, "
            f"code={self.escalation_code}, "
            f"status={self.status.value}, "
            f"level={self.escalation_level}"
            f")>"
        )
