from __future__ import annotations

"""Planned module: escalation repository. Implementation pending."""

"""
backend/repositories/escalation_repository.py

Autonomous Retail Supply Chain AI 5.0

Requirements:
    pip install "sqlalchemy>=2.0,<3.0"

Depends on:
    backend/repositories/base.py

Features:
- Tenant-scoped escalation cases
- Idempotent case creation
- Priority and severity tracking
- SLA deadlines
- Assignment and acknowledgement
- Escalation levels
- Resolution and closure
- Optimistic concurrency
- Append-only case history
- Transactional outbox records

Repository methods do not commit transactions.
"""


import json
import uuid

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import (
    Mapped,
    Session,
    mapped_column,
)

from backend.repositories.base import (
    BaseRepository,
    TenantModel,
    VersionConflict,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


class EscalationPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EscalationStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CLOSED = "closed"


class EscalationCase(TenantModel):
    __tablename__ = "escalation_cases"

    source_event_id: Mapped[str] = mapped_column(
        String(150), nullable=False
    )
    source_type: Mapped[str] = mapped_column(
        String(80), nullable=False
    )
    resource_id: Mapped[str] = mapped_column(
        String(120), nullable=False
    )
    warehouse_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    title: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    description: Mapped[str] = mapped_column(
        String(2000), nullable=False
    )
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default=EscalationStatus.OPEN.value,
        nullable=False,
    )
    escalation_level: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False
    )
    assigned_to: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )
    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_event_id",
            name="uq_escalation_source_event",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_escalation_tenant_id",
        ),
        CheckConstraint(
            "escalation_level >= 1",
            name="ck_escalation_level",
        ),
        Index(
            "ix_escalation_queue",
            "tenant_id",
            "status",
            "priority",
            "due_at",
        ),
    )


class EscalationHistory(TenantModel):
    __tablename__ = "escalation_history"

    case_id: Mapped[str] = mapped_column(
        String(120), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(
        String(120), nullable=False
    )
    action: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    details: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "case_id"],
            [
                "escalation_cases.tenant_id",
                "escalation_cases.id",
            ],
        ),
        Index(
            "ix_escalation_history",
            "tenant_id",
            "case_id",
            "occurred_at",
        ),
    )


class EscalationOutbox(TenantModel):
    __tablename__ = "escalation_outbox"

    case_id: Mapped[str] = mapped_column(
        String(120), nullable=False
    )
    event_type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "case_id"],
            [
                "escalation_cases.tenant_id",
                "escalation_cases.id",
            ],
        ),
    )


class EscalationRepository(
    BaseRepository[EscalationCase]
):
    def __init__(
        self,
        session: Session,
        tenant_id: str,
    ):
        super().__init__(
            session,
            EscalationCase,
            tenant_id,
        )

    def _event(
        self,
        case: EscalationCase,
        actor_id: str,
        action: str,
        details: dict | None = None,
    ) -> None:
        details = details or {}

        self.session.add(EscalationHistory(
            id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            case_id=case.id,
            actor_id=actor_id,
            action=action,
            details=details,
        ))

        self.session.add(EscalationOutbox(
            id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            case_id=case.id,
            event_type=f"escalation.{action}",
            payload={
                "case_id": case.id,
                "status": case.status,
                "priority": case.priority,
                "escalation_level": case.escalation_level,
            },
        ))

        self.session.flush()

    def create_case(
        self,
        *,
        source_event_id: str,
        source_type: str,
        resource_id: str,
        title: str,
        description: str,
        priority: EscalationPriority,
        actor_id: str,
        sla_minutes: int,
        warehouse_id: str | None = None,
    ) -> EscalationCase:
        source_event_id = required(
            source_event_id, "source_event_id"
        )

        if not isinstance(
            priority, EscalationPriority
        ):
            raise ValueError("Invalid priority")

        if (
            type(sla_minutes) is not int
            or sla_minutes <= 0
        ):
            raise ValueError("Invalid SLA duration")

        source_type = required(
            source_type, "source_type"
        )
        resource_id = required(
            resource_id, "resource_id"
        )
        title = required(title, "title")
        description = required(
            description, "description"
        )
        actor_id = required(
            actor_id, "actor_id"
        )

        existing = self.session.scalar(
            select(EscalationCase).where(
                EscalationCase.tenant_id
                == self.tenant_id,
                EscalationCase.source_event_id
                == source_event_id,
            )
        )

        if existing is not None:
            if (
                existing.source_type != source_type
                or existing.resource_id != resource_id
                or existing.title != title
                or existing.description != description
                or existing.priority != priority.value
                or existing.warehouse_id != warehouse_id
            ):
                raise ValueError(
                    "Conflicting source event"
                )
            return existing

        current = utc_now()

        case = EscalationCase(
            id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            source_event_id=source_event_id,
            source_type=source_type,
            resource_id=resource_id,
            warehouse_id=warehouse_id,
            title=title,
            description=description,
            priority=priority.value,
            status=EscalationStatus.OPEN.value,
            escalation_level=1,
            due_at=current + timedelta(
                minutes=sla_minutes
            ),
            created_at=current,
            updated_at=current,
        )

        self.create(case)
        self._event(case, actor_id, "created")
        return case

    def transition(
        self,
        *,
        case_id: str,
        expected_version: int,
        new_status: EscalationStatus,
        actor_id: str,
        assigned_to: str | None = None,
        reason: str | None = None,
    ) -> EscalationCase:
        if not isinstance(
            new_status, EscalationStatus
        ):
            raise ValueError("Invalid status")

        actor_id = required(actor_id, "actor_id")

        transitions = {
            EscalationStatus.OPEN.value: {
                EscalationStatus.ACKNOWLEDGED.value,
                EscalationStatus.ESCALATED.value,
            },
            EscalationStatus.ACKNOWLEDGED.value: {
                EscalationStatus.ESCALATED.value,
                EscalationStatus.RESOLVED.value,
            },
            EscalationStatus.ESCALATED.value: {
                EscalationStatus.ACKNOWLEDGED.value,
                EscalationStatus.RESOLVED.value,
            },
            EscalationStatus.RESOLVED.value: {
                EscalationStatus.CLOSED.value,
            },
            EscalationStatus.CLOSED.value: set(),
        }

        case = self.get(case_id)

        if case.version != expected_version:
            raise VersionConflict(
                "Escalation version conflict"
            )

        if (
            new_status.value
            not in transitions[case.status]
        ):
            raise ValueError(
                "Invalid status transition"
            )

        changes: dict[str, Any] = {
            "status": new_status.value,
            "updated_at": utc_now(),
        }

        if assigned_to is not None:
            changes["assigned_to"] = required(
                assigned_to, "assigned_to"
            )

        if new_status == EscalationStatus.ESCALATED:
            changes["escalation_level"] = (
                case.escalation_level + 1
            )

        if new_status == EscalationStatus.RESOLVED:
            changes["resolved_at"] = utc_now()

        updated = self.update(
            record_id=case_id,
            expected_version=expected_version,
            changes=changes,
            allowed_fields={
                "status",
                "updated_at",
                "assigned_to",
                "escalation_level",
                "resolved_at",
            },
        )

        self._event(
            updated,
            actor_id,
            "status_changed",
            {
                "new_status": new_status.value,
                "reason": reason,
            },
        )

        return updated

    def overdue_cases(
        self,
        now: datetime | None = None,
    ) -> list[EscalationCase]:
        now = now or utc_now()

        statement = (
            self._query()
            .where(
                EscalationCase.due_at < now,
                EscalationCase.status.in_([
                    EscalationStatus.OPEN.value,
                    EscalationStatus.ACKNOWLEDGED.value,
                    EscalationStatus.ESCALATED.value,
                ]),
            )
            .order_by(EscalationCase.due_at)
        )

        return list(
            self.session.scalars(statement)
        )

    def by_assignee(
        self,
        user_id: str,
    ) -> list[EscalationCase]:
        statement = (
            self._query()
            .where(
                EscalationCase.assigned_to
                == required(user_id, "user_id")
            )
            .order_by(
                EscalationCase.due_at
            )
        )

        return list(
            self.session.scalars(statement)
        )

    def history(
        self,
        case_id: str,
    ) -> list[EscalationHistory]:
        self.get(case_id)

        statement = (
            select(EscalationHistory)
            .where(
                EscalationHistory.tenant_id
                == self.tenant_id,
                EscalationHistory.case_id
                == case_id,
            )
            .order_by(
                EscalationHistory.occurred_at,
                EscalationHistory.id,
            )
        )

        return list(
            self.session.scalars(statement)
        )

    def pending_events(
        self,
        limit: int = 100,
    ) -> list[EscalationOutbox]:
        if (
            type(limit) is not int
            or not 1 <= limit <= 500
        ):
            raise ValueError("Invalid limit")

        statement = (
            select(EscalationOutbox)
            .where(
                EscalationOutbox.tenant_id
                == self.tenant_id,
                EscalationOutbox.delivered_at.is_(None),
            )
            .order_by(
                EscalationOutbox.created_at,
                EscalationOutbox.id,
            )
            .limit(limit)
        )

        return list(
            self.session.scalars(statement)
        )

    def mark_event_delivered(
        self,
        event_id: str,
    ) -> None:
        event = self.session.scalar(
            select(EscalationOutbox).where(
                EscalationOutbox.id == event_id,
                EscalationOutbox.tenant_id
                == self.tenant_id,
            )
        )

        if event is None:
            raise KeyError("Outbox event not found")

        if event.delivered_at is None:
            event.delivered_at = utc_now()
            self.session.flush()


if __name__ == "__main__":
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from backend.repositories.base import (
        Base,
        UnitOfWork,
    )

    engine = create_engine(
        "sqlite+pysqlite:///:memory:"
    )

    Base.metadata.create_all(engine)

    with Session(engine) as session:
        repo = EscalationRepository(
            session, tenant_id="demo"
        )

        with UnitOfWork(session):
            case = repo.create_case(
                source_event_id="ALERT001",
                source_type="inventory_alert",
                resource_id="SKU001",
                title="Critical stockout risk",
                description=(
                    "Stock below safety threshold"
                ),
                priority=EscalationPriority.CRITICAL,
                actor_id="SYSTEM",
                sla_minutes=30,
                warehouse_id="WH001",
            )

        with UnitOfWork(session):
            case = repo.transition(
                case_id=case.id,
                expected_version=case.version,
                new_status=(
                    EscalationStatus.ACKNOWLEDGED
                ),
                actor_id="MANAGER001",
                assigned_to="MANAGER001",
            )

        print("Case:", case.id)
        print("Status:", case.status)
        print("History:", len(
            repo.history(case.id)
        ))
        print("Pending events:", len(
            repo.pending_events()
        ))
