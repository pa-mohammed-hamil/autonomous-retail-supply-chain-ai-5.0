from __future__ import annotations

"""Planned module: audit log. Implementation pending."""

"""
backend/models/audit_log.py

Autonomous Retail Supply Chain AI 5.0
Enterprise Audit Logging Database Model

Features:
- AI agent activity auditing
- Human approval decision tracking
- Supplier and procurement audit trails
- Warehouse and inventory change history
- Authentication and security events
- Multi-tenant audit isolation
- Actor identity and request correlation
- Before/after state snapshots
- Structured metadata
- Sensitive data redaction
- UTC timestamps
- Indexed audit search
- Append-only ORM protections
- Optional hash-chain integrity support

Dependencies:
    SQLAlchemy >= 2.0

Existing module:
    backend.models.base.Base

Production requirements:
    PostgreSQL database permissions
    Alembic migrations
    Centralized audit service
    Secure identity and tenant resolution
    Restricted access to audit records
"""


import enum
import hashlib
import json
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
    event,
    inspect,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)
from sqlalchemy.ext.mutable import MutableDict

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


# ============================================================
# ENUMS
# ============================================================

class AuditAction(str, enum.Enum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"

    LOGIN = "login"
    LOGOUT = "logout"
    LOGIN_FAILED = "login_failed"

    APPROVE = "approve"
    REJECT = "reject"
    CANCEL = "cancel"

    EXECUTE = "execute"
    RETRY = "retry"
    COMPLETE = "complete"
    FAIL = "fail"

    EXPORT = "export"
    IMPORT = "import"

    INVENTORY_ADJUSTMENT = "inventory_adjustment"
    STOCK_TRANSFER = "stock_transfer"
    PURCHASE_ORDER = "purchase_order"

    SUPPLIER_ASSESSMENT = "supplier_assessment"
    WAREHOUSE_OPERATION = "warehouse_operation"
    LOGISTICS_OPERATION = "logistics_operation"

    AGENT_ACTION = "agent_action"
    TOOL_CALL = "tool_call"
    MODEL_INFERENCE = "model_inference"

    POLICY_CHANGE = "policy_change"
    PERMISSION_CHANGE = "permission_change"

    SECURITY_ALERT = "security_alert"
    ACCESS_DENIED = "access_denied"

    OTHER = "other"


class AuditActorType(str, enum.Enum):
    USER = "user"
    AGENT = "agent"
    SERVICE = "service"
    SYSTEM = "system"
    API_KEY = "api_key"


class AuditOutcome(str, enum.Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
    PARTIAL = "partial"


class AuditSeverity(str, enum.Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ============================================================
# SENSITIVE DATA PROTECTION
# ============================================================

SENSITIVE_FIELDS = {
    "password",
    "passwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "authorization",
    "cookie",
    "session_id",
    "private_key",
    "client_secret",
    "credit_card",
    "card_number",
    "cvv",
    "otp",
    "pin",
    "bank_account",
    "account_number",
}


def redact_sensitive_data(
    value: Any,
) -> Any:
    """
    Recursively redact sensitive dictionary keys.

    This is defense-in-depth, not a complete DLP system.
    Do not log raw credentials, tokens, or private data.
    """

    if isinstance(value, dict):
        result = {}

        for key, item in value.items():
            normalized = str(key).lower()

            if normalized in SENSITIVE_FIELDS:
                result[key] = "[REDACTED]"
            else:
                result[key] = redact_sensitive_data(item)

        return result

    if isinstance(value, list):
        return [
            redact_sensitive_data(item)
            for item in value
        ]

    if isinstance(value, tuple):
        return [
            redact_sensitive_data(item)
            for item in value
        ]

    return value


def canonical_json(
    value: dict[str, Any],
) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        ensure_ascii=False,
    )


def calculate_event_hash(
    payload: dict[str, Any],
    previous_hash: str | None = None,
) -> str:
    """
    Calculate a SHA-256 hash for an audit event.

    The audit service must serialize chain writes,
    persist previous_hash and protect chain heads.
    A hash alone does not prevent tampering.
    """

    data = {
        "previous_hash": previous_hash,
        "event": payload,
    }

    encoded = canonical_json(data).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


# ============================================================
# AUDIT LOG MODEL
# ============================================================

class AuditLog(Base):
    __tablename__ = "audit_logs"

    __table_args__ = (
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_audit_log_duration",
        ),
        Index(
            "ix_audit_org_created",
            "organization_id",
            "created_at",
        ),
        Index(
            "ix_audit_org_action",
            "organization_id",
            "action",
        ),
        Index(
            "ix_audit_org_resource",
            "organization_id",
            "resource_type",
            "resource_id",
        ),
        Index(
            "ix_audit_actor_created",
            "actor_id",
            "created_at",
        ),
        Index(
            "ix_audit_trace_created",
            "trace_id",
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

    event_id: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        nullable=False,
        default=generate_uuid,
    )

    # --------------------------------------------------------
    # EVENT DETAILS
    # --------------------------------------------------------

    action: Mapped[AuditAction] = mapped_column(
        enum_column(
            AuditAction,
            "audit_action",
        ),
        nullable=False,
    )

    outcome: Mapped[AuditOutcome] = mapped_column(
        enum_column(
            AuditOutcome,
            "audit_outcome",
        ),
        default=AuditOutcome.SUCCESS,
        nullable=False,
    )

    severity: Mapped[AuditSeverity] = mapped_column(
        enum_column(
            AuditSeverity,
            "audit_severity",
        ),
        default=AuditSeverity.INFO,
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # ACTOR INFORMATION
    # --------------------------------------------------------

    actor_type: Mapped[AuditActorType] = mapped_column(
        enum_column(
            AuditActorType,
            "audit_actor_type",
        ),
        nullable=False,
    )

    actor_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
        index=True,
    )

    actor_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    agent_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    # --------------------------------------------------------
    # RESOURCE INFORMATION
    # --------------------------------------------------------

    resource_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    resource_id: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
        index=True,
    )

    resource_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # --------------------------------------------------------
    # AGENT AND APPROVAL REFERENCES
    # --------------------------------------------------------

    agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )

    agent_action_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )

    approval_request_id: Mapped[str | None] = (
        mapped_column(
            String(36),
            nullable=True,
            index=True,
        )
    )

    # These references are intentionally not foreign
    # keys, allowing audit history to survive deletion
    # or archival of operational records.

    # --------------------------------------------------------
    # REQUEST CONTEXT
    # --------------------------------------------------------

    request_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    correlation_id: Mapped[str | None] = mapped_column(
        String(100),
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

    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
    )

    user_agent: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    http_method: Mapped[str | None] = mapped_column(
        String(10),
        nullable=True,
    )

    endpoint: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    http_status_code: Mapped[int | None] = (
        mapped_column(
            Integer,
            nullable=True,
        )
    )

    # --------------------------------------------------------
    # STATE CHANGE HISTORY
    # --------------------------------------------------------

    before_state: Mapped[
        dict[str, Any] | None
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        nullable=True,
    )

    after_state: Mapped[
        dict[str, Any] | None
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        nullable=True,
    )

    changes: Mapped[
        dict[str, Any] | None
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        nullable=True,
    )

    event_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        "metadata",
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # EXECUTION INFORMATION
    # --------------------------------------------------------

    duration_ms: Mapped[int | None] = mapped_column(
        Integer,
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

    # --------------------------------------------------------
    # HASH CHAIN INTEGRITY
    # --------------------------------------------------------

    previous_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    event_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )

    # --------------------------------------------------------
    # TIMESTAMPS
    # --------------------------------------------------------

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        index=True,
    )

    # --------------------------------------------------------
    # FACTORY METHOD
    # --------------------------------------------------------

    @classmethod
    def create_event(
        cls,
        *,
        organization_id: str,
        action: AuditAction,
        actor_type: AuditActorType,
        resource_type: str,
        actor_id: str | None = None,
        resource_id: str | None = None,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        severity: AuditSeverity = AuditSeverity.INFO,
        description: str | None = None,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
        changes: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
        agent_run_id: str | None = None,
        agent_action_id: str | None = None,
        approval_request_id: str | None = None,
        previous_hash: str | None = None,
    ) -> "AuditLog":

        record = cls(
            id=generate_uuid(),
            event_id=generate_uuid(),
            organization_id=organization_id,
            action=action,
            actor_type=actor_type,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            severity=severity,
            description=description,
            before_state=redact_sensitive_data(
                before_state
            ) if before_state is not None else None,
            after_state=redact_sensitive_data(
                after_state
            ) if after_state is not None else None,
            changes=redact_sensitive_data(
                changes
            ) if changes is not None else None,
            event_metadata=redact_sensitive_data(
                metadata or {}
            ),
            request_id=request_id,
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            agent_action_id=agent_action_id,
            approval_request_id=approval_request_id,
            previous_hash=previous_hash,
            created_at=utc_now(),
        )

        return record

    # --------------------------------------------------------
    # HASH PAYLOAD
    # --------------------------------------------------------

    def hash_payload(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "organization_id": self.organization_id,
            "action": self.action.value,
            "outcome": self.outcome.value,
            "severity": self.severity.value,
            "actor_type": self.actor_type.value,
            "actor_id": self.actor_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "description": self.description,
            "before_state": self.before_state,
            "after_state": self.after_state,
            "changes": self.changes,
            "metadata": self.event_metadata,
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "agent_run_id": self.agent_run_id,
            "agent_action_id": self.agent_action_id,
            "approval_request_id": (
                self.approval_request_id
            ),
            "created_at": (
                self.created_at.isoformat()
                if self.created_at else None
            ),
        }

    def calculate_hash(self) -> str:
        return calculate_event_hash(
            self.hash_payload(),
            self.previous_hash,
        )

    def seal(self) -> None:
        if self.event_hash is not None:
            raise ValueError(
                "Audit event is already sealed"
            )

        self.event_hash = self.calculate_hash()

    def verify_integrity(self) -> bool:
        if not self.event_hash:
            return False

        return self.event_hash == self.calculate_hash()

    # --------------------------------------------------------
    # SERIALIZATION
    # --------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_id": self.event_id,
            "organization_id": self.organization_id,
            "action": self.action.value,
            "outcome": self.outcome.value,
            "severity": self.severity.value,
            "description": self.description,
            "actor_type": self.actor_type.value,
            "actor_id": self.actor_id,
            "actor_name": self.actor_name,
            "agent_name": self.agent_name,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "resource_name": self.resource_name,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "trace_id": self.trace_id,
            "agent_run_id": self.agent_run_id,
            "agent_action_id": self.agent_action_id,
            "approval_request_id": (
                self.approval_request_id
            ),
            "before_state": self.before_state,
            "after_state": self.after_state,
            "changes": self.changes,
            "metadata": self.event_metadata,
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "previous_hash": self.previous_hash,
            "event_hash": self.event_hash,
            "created_at": (
                self.created_at.isoformat()
                if self.created_at else None
            ),
        }

    def __repr__(self) -> str:
        return (
            f"<AuditLog("
            f"id={self.id}, "
            f"action={self.action.value}, "
            f"resource={self.resource_type}, "
            f"outcome={self.outcome.value}"
            f")>"
        )


# ============================================================
# APPEND-ONLY ORM PROTECTION
# ============================================================

@event.listens_for(AuditLog, "before_update")
def prevent_audit_update(
    mapper,
    connection,
    target,
) -> None:
    raise ValueError(
        "Audit logs are append-only and cannot be updated"
    )


@event.listens_for(AuditLog, "before_delete")
def prevent_audit_delete(
    mapper,
    connection,
    target,
) -> None:
    raise ValueError(
        "Audit logs are append-only and cannot be deleted"
    )
