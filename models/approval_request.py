from __future__ import annotations

"""Planned module: approval request. Implementation pending."""

"""
backend/models/approval_request.py

Human-in-the-Loop Approval Request Model
Autonomous Retail Supply Chain AI 5.0

Features:
- Agent action approval requests
- Human-in-the-loop authorization
- Risk-based approval policies
- Multi-tenant approval tracking
- Approval and rejection workflows
- Expiration and cancellation
- Audit timestamps
- Request payload snapshots
- Approval decision metadata
- Optimistic concurrency control
- Safe lifecycle transitions

Dependencies:
    SQLAlchemy >= 2.0

Required existing modules:
    backend.models.base
    backend.models.agent_action

Assumptions:
    agent_actions.id is String(36)
    organization_id is String(36)

Use Alembic for schema migrations.
"""


import enum
import uuid

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
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

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

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
        length=40,
    )


# ============================================================
# ENUMS
# ============================================================

class ApprovalRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalRequestType(str, enum.Enum):
    AGENT_ACTION = "agent_action"
    PURCHASE_ORDER = "purchase_order"
    STOCK_TRANSFER = "stock_transfer"
    INVENTORY_ADJUSTMENT = "inventory_adjustment"
    SUPPLIER_CHANGE = "supplier_change"
    PRICE_CHANGE = "price_change"
    LOGISTICS_OPERATION = "logistics_operation"
    FINANCIAL_OPERATION = "financial_operation"
    EMERGENCY_OPERATION = "emergency_operation"
    OTHER = "other"


class ApprovalRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


# ============================================================
# APPROVAL REQUEST MODEL
# ============================================================

class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "request_key",
            name="uq_approval_request_key",
        ),
        CheckConstraint(
            "required_approvals >= 1",
            name="ck_approval_required_count",
        ),
        CheckConstraint(
            "approval_count >= 0",
            name="ck_approval_count_nonnegative",
        ),
        CheckConstraint(
            "approval_count <= required_approvals",
            name="ck_approval_count_limit",
        ),
        Index(
            "ix_approval_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_approval_action_status",
            "agent_action_id",
            "status",
        ),
        Index(
            "ix_approval_expiration",
            "status",
            "expires_at",
        ),
        Index(
            "ix_approval_assignee_status",
            "assigned_approver_id",
            "status",
        ),
    )

    # --------------------------------------------------------
    # PRIMARY IDENTIFIERS
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

    request_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    agent_action_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "agent_actions.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
        index=True,
    )

    # --------------------------------------------------------
    # REQUEST INFORMATION
    # --------------------------------------------------------

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    request_type: Mapped[ApprovalRequestType] = (
        mapped_column(
            enum_column(
                ApprovalRequestType,
                "approval_request_type",
            ),
            default=ApprovalRequestType.AGENT_ACTION,
            nullable=False,
        )
    )

    status: Mapped[ApprovalRequestStatus] = (
        mapped_column(
            enum_column(
                ApprovalRequestStatus,
                "approval_request_status",
            ),
            default=ApprovalRequestStatus.PENDING,
            nullable=False,
        )
    )

    risk_level: Mapped[ApprovalRiskLevel] = (
        mapped_column(
            enum_column(
                ApprovalRiskLevel,
                "approval_risk_level",
            ),
            default=ApprovalRiskLevel.LOW,
            nullable=False,
        )
    )

    priority: Mapped[ApprovalPriority] = (
        mapped_column(
            enum_column(
                ApprovalPriority,
                "approval_priority",
            ),
            default=ApprovalPriority.NORMAL,
            nullable=False,
        )
    )

    # --------------------------------------------------------
    # REQUEST ORIGIN
    # --------------------------------------------------------

    requested_by: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    requested_by_agent: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
    )

    agent_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    # --------------------------------------------------------
    # APPROVAL ASSIGNMENT
    # --------------------------------------------------------

    assigned_approver_id: Mapped[str | None] = (
        mapped_column(
            String(36),
            nullable=True,
            index=True,
        )
    )

    assigned_role: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    required_approvals: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    approval_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # --------------------------------------------------------
    # REQUEST DATA
    # --------------------------------------------------------

    request_payload: Mapped[dict[str, Any]] = (
        mapped_column(
            MutableDict.as_mutable(JSON),
            default=dict,
            nullable=False,
        )
    )

    approval_context: Mapped[dict[str, Any]] = (
        mapped_column(
            MutableDict.as_mutable(JSON),
            default=dict,
            nullable=False,
        )
    )

    decision_metadata: Mapped[
        dict[str, Any] | None
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        nullable=True,
    )

    # --------------------------------------------------------
    # DECISION INFORMATION
    # --------------------------------------------------------

    decided_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    decision_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    decision_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # EXPIRATION AND CANCELLATION
    # --------------------------------------------------------

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    cancelled_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    cancellation_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # AUDIT AND OBSERVABILITY
    # --------------------------------------------------------

    trace_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    correlation_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
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
    # RELATIONSHIPS
    # --------------------------------------------------------

    agent_action: Mapped["AgentAction | None"] = (
        relationship(
            "AgentAction",
            foreign_keys=[agent_action_id],
        )
    )

    # --------------------------------------------------------
    # OPTIMISTIC CONCURRENCY
    # --------------------------------------------------------

    __mapper_args__ = {
        "version_id_col": version,
    }

    # --------------------------------------------------------
    # PROPERTIES
    # --------------------------------------------------------

    @property
    def is_pending(self) -> bool:
        return (
            self.status
            == ApprovalRequestStatus.PENDING
        )

    @property
    def is_approved(self) -> bool:
        return (
            self.status
            == ApprovalRequestStatus.APPROVED
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            ApprovalRequestStatus.APPROVED,
            ApprovalRequestStatus.REJECTED,
            ApprovalRequestStatus.EXPIRED,
            ApprovalRequestStatus.CANCELLED,
        }

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False

        expires_at = self.expires_at

        # SQLite may return naive datetime objects.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(
                tzinfo=timezone.utc
            )

        return utc_now() >= expires_at

    @property
    def remaining_approvals(self) -> int:
        return max(
            0,
            self.required_approvals
            - self.approval_count,
        )

    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------

    def ensure_pending(self) -> None:
        if not self.is_pending:
            raise ValueError(
                f"Approval request is {self.status.value}"
            )

        if self.is_expired:
            raise ValueError(
                "Approval request has expired"
            )

    # --------------------------------------------------------
    # APPROVAL DECISION
    # --------------------------------------------------------

    def approve(
        self,
        approver_id: str,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Record one approval.

        Returns True when the required approval
        threshold is reached.

        Important:
        Authorization and distinct-approver validation
        must be performed by the approval service.
        """

        self.ensure_pending()

        if not approver_id:
            raise ValueError(
                "Approver ID is required"
            )

        if self.approval_count >= self.required_approvals:
            raise ValueError(
                "Approval threshold already reached"
            )

        self.approval_count += 1
        self.decided_by = approver_id
        self.decision_reason = reason
        self.decision_metadata = metadata
        self.updated_at = utc_now()

        if (
            self.approval_count
            >= self.required_approvals
        ):
            self.status = (
                ApprovalRequestStatus.APPROVED
            )
            self.decision_at = utc_now()
            return True

        return False

    # --------------------------------------------------------
    # REJECTION
    # --------------------------------------------------------

    def reject(
        self,
        approver_id: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:

        self.ensure_pending()

        if not approver_id:
            raise ValueError(
                "Approver ID is required"
            )

        if not reason.strip():
            raise ValueError(
                "Rejection reason is required"
            )

        self.status = (
            ApprovalRequestStatus.REJECTED
        )

        self.decided_by = approver_id
        self.decision_reason = reason
        self.decision_metadata = metadata
        self.decision_at = utc_now()
        self.updated_at = utc_now()

    # --------------------------------------------------------
    # EXPIRATION
    # --------------------------------------------------------

    def expire(self) -> None:

        if not self.is_pending:
            raise ValueError(
                "Only pending requests can expire"
            )

        if not self.is_expired:
            raise ValueError(
                "Request has not reached expiration"
            )

        self.status = (
            ApprovalRequestStatus.EXPIRED
        )

        self.decision_at = utc_now()
        self.updated_at = utc_now()

    # --------------------------------------------------------
    # CANCELLATION
    # --------------------------------------------------------

    def cancel(
        self,
        cancelled_by: str,
        reason: str | None = None,
    ) -> None:

        if not self.is_pending:
            raise ValueError(
                "Only pending requests can be cancelled"
            )

        if not cancelled_by:
            raise ValueError(
                "Cancelling user is required"
            )

        self.status = (
            ApprovalRequestStatus.CANCELLED
        )

        self.cancelled_by = cancelled_by
        self.cancellation_reason = reason
        self.decision_at = utc_now()
        self.updated_at = utc_now()

    # --------------------------------------------------------
    # SERIALIZATION
    # --------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:

        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "request_key": self.request_key,
            "agent_action_id": self.agent_action_id,
            "title": self.title,
            "description": self.description,
            "request_type": self.request_type.value,
            "status": self.status.value,
            "risk_level": self.risk_level.value,
            "priority": self.priority.value,
            "requested_by": self.requested_by,
            "requested_by_agent": self.requested_by_agent,
            "agent_name": self.agent_name,
            "assigned_approver_id": (
                self.assigned_approver_id
            ),
            "assigned_role": self.assigned_role,
            "required_approvals": self.required_approvals,
            "approval_count": self.approval_count,
            "remaining_approvals": (
                self.remaining_approvals
            ),
            "decided_by": self.decided_by,
            "decision_reason": self.decision_reason,
            "is_expired": self.is_expired,
            "is_terminal": self.is_terminal,
            "version": self.version,
            "trace_id": self.trace_id,
            "created_at": (
                self.created_at.isoformat()
                if self.created_at else None
            ),
            "updated_at": (
                self.updated_at.isoformat()
                if self.updated_at else None
            ),
            "expires_at": (
                self.expires_at.isoformat()
                if self.expires_at else None
            ),
            "decision_at": (
                self.decision_at.isoformat()
                if self.decision_at else None
            ),
        }

    def __repr__(self) -> str:
        return (
            f"<ApprovalRequest("
            f"id={self.id}, "
            f"status={self.status.value}, "
            f"risk={self.risk_level.value}, "
            f"approvals={self.approval_count}/"
            f"{self.required_approvals}"
            f")>"
        )
