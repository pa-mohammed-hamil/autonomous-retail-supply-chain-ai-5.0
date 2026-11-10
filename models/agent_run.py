from __future__ import annotations

"""Planned module: agent run. Implementation pending."""


import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_id() -> str:
    return str(uuid.uuid4())


class ActionStatus(str, enum.Enum):
    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class ActionType(str, enum.Enum):
    TOOL_CALL = "tool_call"
    DATA_RETRIEVAL = "data_retrieval"
    PREDICTION = "prediction"
    FORECASTING = "forecasting"
    OPTIMIZATION = "optimization"
    INVENTORY_UPDATE = "inventory_update"
    PROCUREMENT = "procurement"
    SUPPLIER_RISK = "supplier_risk"
    WAREHOUSE_OPERATION = "warehouse_operation"
    LOGISTICS_OPERATION = "logistics_operation"
    NOTIFICATION = "notification"
    ESCALATION = "escalation"
    RAG_QUERY = "rag_query"
    REPORT_GENERATION = "report_generation"
    SIMULATION = "simulation"
    OTHER = "other"


class ActionRisk(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


def enum_column(enum_class, name: str):
    return SQLEnum(
        enum_class,
        name=name,
        native_enum=False,
        values_callable=lambda members: [
            member.value for member in members
        ],
        validate_strings=True,
        length=40,
    )


class AgentAction(Base):
    __tablename__ = "agent_actions"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_agent_actions_idempotency",
        ),
        CheckConstraint(
            "retry_count >= 0 AND max_retries >= 0",
            name="ck_agent_actions_retries",
        ),
        CheckConstraint(
            "priority BETWEEN 1 AND 10",
            name="ck_agent_actions_priority",
        ),
        CheckConstraint(
            "timeout_seconds > 0",
            name="ck_agent_actions_timeout",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_agent_actions_duration",
        ),
        Index(
            "ix_agent_actions_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_agent_actions_run_created",
            "agent_run_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_id,
    )

    organization_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    agent_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    agent_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    action_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    action_type: Mapped[ActionType] = mapped_column(
        enum_column(ActionType, "agent_action_type"),
        default=ActionType.OTHER,
        nullable=False,
    )

    status: Mapped[ActionStatus] = mapped_column(
        enum_column(ActionStatus, "agent_action_status"),
        default=ActionStatus.PENDING,
        nullable=False,
    )

    risk_level: Mapped[ActionRisk] = mapped_column(
        enum_column(ActionRisk, "agent_action_risk"),
        default=ActionRisk.LOW,
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    priority: Mapped[int] = mapped_column(
        Integer,
        default=5,
        nullable=False,
    )

    tool_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    input_payload: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    output_payload: Mapped[dict[str, Any] | None] = (
        mapped_column(
            MutableDict.as_mutable(JSON),
            nullable=True,
        )
    )

    execution_metadata: Mapped[dict[str, Any]] = (
        mapped_column(
            "metadata",
            MutableDict.as_mutable(JSON),
            default=dict,
            nullable=False,
        )
    )

    requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    approval_status: Mapped[ApprovalStatus] = mapped_column(
        enum_column(
            ApprovalStatus,
            "agent_action_approval_status",
        ),
        default=ApprovalStatus.NOT_REQUIRED,
        nullable=False,
    )

    approval_request_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )

    approved_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    approval_expires_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=True,
        )
    )

    rejection_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

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

    timeout_seconds: Mapped[int] = mapped_column(
        Integer,
        default=60,
        nullable=False,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    error_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    trace_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    span_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    duration_ms: Mapped[int | None] = mapped_column(
        Integer,
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

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    agent_run: Mapped["AgentRun"] = relationship(
        "AgentRun",
        back_populates="actions",
    )

    def can_execute(self) -> bool:
        if self.status not in {
            ActionStatus.PENDING,
            ActionStatus.APPROVED,
            ActionStatus.RETRYING,
        }:
            return False

        if not self.requires_approval:
            return True

        if self.approval_status != ApprovalStatus.APPROVED:
            return False

        if (
            self.approval_expires_at is not None
            and self.approval_expires_at <= utc_now()
        ):
            return False

        return True

    def mark_running(self) -> None:
        if not self.can_execute():
            raise ValueError(
                "Action is not approved or executable"
            )

        self.status = ActionStatus.RUNNING
        self.started_at = utc_now()
        self.completed_at = None
        self.updated_at = utc_now()

    def mark_completed(
        self,
        output: dict[str, Any] | None = None,
    ) -> None:
        if self.status != ActionStatus.RUNNING:
            raise ValueError("Action is not running")

        self.status = ActionStatus.COMPLETED
        self.output_payload = output
        self.completed_at = utc_now()
        self.updated_at = utc_now()
        self._calculate_duration()

    def mark_failed(
        self,
        message: str,
        code: str | None = None,
    ) -> None:
        if self.status != ActionStatus.RUNNING:
            raise ValueError("Action is not running")

        self.status = ActionStatus.FAILED
        self.error_message = message
        self.error_code = code
        self.completed_at = utc_now()
        self.updated_at = utc_now()
        self._calculate_duration()

    def schedule_retry(self) -> None:
        if self.status not in {
            ActionStatus.FAILED,
            ActionStatus.TIMED_OUT,
        }:
            raise ValueError(
                "Only failed actions can be retried"
            )

        if self.retry_count >= self.max_retries:
            raise ValueError("Maximum retries exceeded")

        self.retry_count += 1
        self.status = ActionStatus.RETRYING
        self.started_at = None
        self.completed_at = None
        self.duration_ms = None
        self.updated_at = utc_now()

    def approve(self, approver_id: str) -> None:
        if not self.requires_approval:
            raise ValueError("Approval is not required")

        if self.approval_status != ApprovalStatus.PENDING:
            raise ValueError("Approval is not pending")

        if (
            self.approval_expires_at is not None
            and self.approval_expires_at <= utc_now()
        ):
            raise ValueError("Approval has expired")

        self.approval_status = ApprovalStatus.APPROVED
        self.approved_by = approver_id
        self.approved_at = utc_now()
        self.status = ActionStatus.APPROVED
        self.updated_at = utc_now()

    def reject(self, reason: str) -> None:
        if self.approval_status != ApprovalStatus.PENDING:
            raise ValueError("Approval is not pending")

        self.approval_status = ApprovalStatus.REJECTED
        self.rejection_reason = reason
        self.status = ActionStatus.REJECTED
        self.updated_at = utc_now()

    def cancel(self) -> None:
        if self.status in {
            ActionStatus.COMPLETED,
            ActionStatus.CANCELLED,
            ActionStatus.REJECTED,
        }:
            raise ValueError(
                "Cannot cancel a terminal action"
            )

        self.status = ActionStatus.CANCELLED
        self.updated_at = utc_now()

    def _calculate_duration(self) -> None:
        if self.started_at and self.completed_at:
            elapsed = (
                self.completed_at - self.started_at
            )
            self.duration_ms = max(
                0,
                int(elapsed.total_seconds() * 1000),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "agent_run_id": self.agent_run_id,
            "agent_name": self.agent_name,
            "action_name": self.action_name,
            "action_type": self.action_type.value,
            "status": self.status.value,
            "risk_level": self.risk_level.value,
            "priority": self.priority,
            "tool_name": self.tool_name,
            "requires_approval": self.requires_approval,
            "approval_status": self.approval_status.value,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "duration_ms": self.duration_ms,
            "trace_id": self.trace_id,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "created_at": (
                self.created_at.isoformat()
                if self.created_at else None
            ),
            "started_at": (
                self.started_at.isoformat()
                if self.started_at else None
            ),
            "completed_at": (
                self.completed_at.isoformat()
                if self.completed_at else None
            ),
        }

    def __repr__(self) -> str:
        return (
            f"<AgentAction id={self.id} "
            f"agent={self.agent_name} "
            f"status={self.status.value}>"
        )
