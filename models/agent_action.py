from __future__ import annotations

"""Planned module: agent action. Implementation pending."""

"""
backend/models/agent_action.py

Agent Action Database Model
Autonomous Retail Supply Chain AI 5.0

Features:
- Multi-agent action tracking
- Agent run relationships
- Tool execution records
- Human approval workflow
- Action lifecycle management
- Retry and failure tracking
- Execution timing and latency
- Input/output JSON storage
- Audit and trace correlation
- Multi-tenant isolation
- Idempotency support

Dependencies:
    SQLAlchemy >= 2.0

Assumes:
    backend.models.base.Base
    agent_runs.id uses String(36)
"""


import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)
from sqlalchemy.ext.mutable import MutableDict

from backend.models.base import Base


# ============================================================
# UTILITIES
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid.uuid4())


# ============================================================
# ENUMS
# ============================================================

class AgentActionStatus(str, enum.Enum):
    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    SKIPPED = "skipped"


class AgentActionType(str, enum.Enum):
    TOOL_CALL = "tool_call"
    DATA_RETRIEVAL = "data_retrieval"
    DATA_ANALYSIS = "data_analysis"
    FORECAST = "forecast"
    PREDICTION = "prediction"
    OPTIMIZATION = "optimization"
    RAG_QUERY = "rag_query"
    NOTIFICATION = "notification"
    ESCALATION = "escalation"
    PROCUREMENT = "procurement"
    INVENTORY_UPDATE = "inventory_update"
    STOCK_TRANSFER = "stock_transfer"
    SUPPLIER_ASSESSMENT = "supplier_assessment"
    WAREHOUSE_OPERATION = "warehouse_operation"
    LOGISTICS_OPERATION = "logistics_operation"
    REPORT_GENERATION = "report_generation"
    SIMULATION = "simulation"
    APPROVAL_REQUEST = "approval_request"
    OTHER = "other"


class AgentActionRisk(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AgentApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


def enum_type(enum_class, name: str):
    return SAEnum(
        enum_class,
        name=name,
        native_enum=False,
        values_callable=lambda cls: [
            member.value for member in cls
        ],
        validate_strings=True,
        length=40,
    )


# ============================================================
# AGENT ACTION MODEL
# ============================================================

class AgentAction(Base):
    __tablename__ = "agent_actions"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_agent_action_idempotency",
        ),
        CheckConstraint(
            "retry_count >= 0",
            name="ck_agent_action_retry_count",
        ),
        CheckConstraint(
            "max_retries >= 0",
            name="ck_agent_action_max_retries",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_agent_action_duration",
        ),
        Index(
            "ix_agent_action_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_agent_action_run_created",
            "agent_run_id",
            "created_at",
        ),
        Index(
            "ix_agent_action_org_type",
            "organization_id",
            "action_type",
        ),
    )

    # --------------------------------------------------------
    # IDENTIFIERS
    # --------------------------------------------------------

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=new_uuid,
    )

    organization_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    agent_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "agent_runs.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    agent_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        index=True,
    )

    agent_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # --------------------------------------------------------
    # ACTION INFORMATION
    # --------------------------------------------------------

    action_name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    action_type: Mapped[AgentActionType] = mapped_column(
        enum_type(
            AgentActionType,
            "agent_action_type",
        ),
        nullable=False,
        default=AgentActionType.OTHER,
    )

    status: Mapped[AgentActionStatus] = mapped_column(
        enum_type(
            AgentActionStatus,
            "agent_action_status",
        ),
        nullable=False,
        default=AgentActionStatus.PENDING,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    risk_level: Mapped[AgentActionRisk] = mapped_column(
        enum_type(
            AgentActionRisk,
            "agent_action_risk",
        ),
        nullable=False,
        default=AgentActionRisk.LOW,
    )

    priority: Mapped[int] = mapped_column(
        Integer,
        default=5,
        nullable=False,
    )

    # --------------------------------------------------------
    # TOOL EXECUTION
    # --------------------------------------------------------

    tool_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    tool_version: Mapped[str | None] = mapped_column(
        String(100),
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

    # --------------------------------------------------------
    # HUMAN APPROVAL
    # --------------------------------------------------------

    requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    approval_status: Mapped[AgentApprovalStatus] = (
        mapped_column(
            enum_type(
                AgentApprovalStatus,
                "agent_approval_status",
            ),
            default=AgentApprovalStatus.NOT_REQUIRED,
            nullable=False,
        )
    )

    approval_request_id: Mapped[str | None] = (
        mapped_column(
            String(36),
            nullable=True,
            index=True,
        )
    )

    approved_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    approved_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=True,
        )
    )

    approval_expires_at: Mapped[datetime | None] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=True,
        )
    )

    rejection_reason: Mapped[str | None] = (
        mapped_column(
            Text,
            nullable=True,
        )
    )

    # --------------------------------------------------------
    # EXECUTION CONTROL
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

    timeout_seconds: Mapped[int] = mapped_column(
        Integer,
        default=60,
        nullable=False,
    )

    idempotency_key: Mapped[str | None] = (
        mapped_column(
            String(200),
            nullable=True,
        )
    )

    # --------------------------------------------------------
    # ERROR HANDLING
    # --------------------------------------------------------

    error_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    error_details: Mapped[dict[str, Any] | None] = (
        mapped_column(
            MutableDict.as_mutable(JSON),
            nullable=True,
        )
    )

    # --------------------------------------------------------
    # OBSERVABILITY
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # TIMESTAMPS
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

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # RELATIONSHIPS
    # --------------------------------------------------------

    agent_run: Mapped["AgentRun"] = relationship(
        "AgentRun",
        back_populates="actions",
    )

    # --------------------------------------------------------
    # BUSINESS METHODS
    # --------------------------------------------------------

    def can_execute(self) -> bool:
        if self.status not in {
            AgentActionStatus.PENDING,
            AgentActionStatus.APPROVED,
            AgentActionStatus.RETRYING,
        }:
            return False

        if not self.requires_approval:
            return True

        if (
            self.approval_status
            != AgentApprovalStatus.APPROVED
        ):
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
                "Action is not authorized for execution"
            )

        self.status = AgentActionStatus.RUNNING
        self.started_at = utc_now()
        self.updated_at = utc_now()

    def mark_completed(
        self,
        output: dict[str, Any] | None = None,
    ) -> None:
        if self.status != AgentActionStatus.RUNNING:
            raise ValueError(
                "Only running actions can complete"
            )

        self.status = AgentActionStatus.COMPLETED
        self.output_payload = output
        self.completed_at = utc_now()
        self.updated_at = utc_now()

        self._update_duration()

    def mark_failed(
        self,
        error_message: str,
        error_code: str | None = None,
    ) -> None:
        if self.status != AgentActionStatus.RUNNING:
            raise ValueError(
                "Only running actions can fail"
            )

        self.status = AgentActionStatus.FAILED
        self.error_message = error_message
        self.error_code = error_code
        self.completed_at = utc_now()
        self.updated_at = utc_now()

        self._update_duration()

    def schedule_retry(self) -> None:
        if self.status not in {
            AgentActionStatus.FAILED,
            AgentActionStatus.TIMED_OUT,
        }:
            raise ValueError(
                "Only failed or timed-out actions can retry"
            )

        if self.retry_count >= self.max_retries:
            raise ValueError(
                "Maximum retry count reached"
            )

        self.retry_count += 1
        self.status = AgentActionStatus.RETRYING
        self.started_at = None
        self.completed_at = None
        self.duration_ms = None
        self.updated_at = utc_now()

    def approve(
        self,
        approver_id: str,
    ) -> None:
        if not self.requires_approval:
            raise ValueError(
                "Approval is not required"
            )

        if (
            self.approval_status
            != AgentApprovalStatus.PENDING
        ):
            raise ValueError(
                "Approval request is not pending"
            )

        if (
            self.approval_expires_at is not None
            and self.approval_expires_at <= utc_now()
        ):
            raise ValueError(
                "Approval request has expired"
            )

        self.approval_status = (
            AgentApprovalStatus.APPROVED
        )
        self.approved_by = approver_id
        self.approved_at = utc_now()
        self.status = AgentActionStatus.APPROVED
        self.updated_at = utc_now()

    def reject(self, reason: str) -> None:
        if (
            self.approval_status
            != AgentApprovalStatus.PENDING
        ):
            raise ValueError(
                "Approval request is not pending"
            )

        self.approval_status = (
            AgentApprovalStatus.REJECTED
        )
        self.rejection_reason = reason
        self.status = AgentActionStatus.REJECTED
        self.updated_at = utc_now()

    def cancel(self) -> None:
        if self.status in {
            AgentActionStatus.COMPLETED,
            AgentActionStatus.CANCELLED,
            AgentActionStatus.REJECTED,
        }:
            raise ValueError(
                "Action cannot be cancelled"
            )

        self.status = AgentActionStatus.CANCELLED
        self.updated_at = utc_now()

    def _update_duration(self) -> None:
        if self.started_at and self.completed_at:
            delta = (
                self.completed_at - self.started_at
            )

            self.duration_ms = max(
                0,
                int(delta.total_seconds() * 1000),
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
            f"<AgentAction("
            f"id={self.id}, "
            f"agent={self.agent_name}, "
            f"action={self.action_name}, "
            f"status={self.status.value}"
            f")>"
        )
