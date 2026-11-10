from __future__ import annotations

"""Planned module: delivery tracker. Implementation pending."""

"""
backend/notifications/delivery_tracker.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+ | SQLAlchemy 2.x

Install:
    pip install "sqlalchemy>=2.0,<3.0"

Requires:
    backend.repositories.base.Base
    backend.repositories.base.TenantModel
    backend.repositories.base.BaseRepository
    backend.repositories.base.VersionConflict

Important:
- Caller controls transaction boundaries.
- No external messages are sent from this module.
- Provider credentials must never be stored here.
- Tenant/user authorization belongs to the service layer.
"""


from datetime import datetime, timedelta, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
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


def required(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


class DeliveryChannel(str, Enum):
    DASHBOARD = "dashboard"
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"


class DeliveryStatus(str, Enum):
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class DeliveryRecord(TenantModel):
    __tablename__ = "retail_notification_deliveries"

    notification_id: Mapped[str] = mapped_column(
        String(120), nullable=False
    )

    recipient_user_id: Mapped[str] = mapped_column(
        String(120), nullable=False
    )

    channel: Mapped[str] = mapped_column(
        String(30), nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=DeliveryStatus.QUEUED.value,
    )

    idempotency_key: Mapped[str] = mapped_column(
        String(200), nullable=False
    )

    provider_message_id: Mapped[str | None] = (
        mapped_column(String(255))
    )

    attempts: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )

    max_attempts: Mapped[int] = mapped_column(
        Integer, default=3, nullable=False
    )

    next_retry_at: Mapped[datetime | None] = (
        mapped_column(DateTime(timezone=True))
    )

    last_error: Mapped[str | None] = mapped_column(
        Text
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

    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    delivered_at: Mapped[datetime | None] = (
        mapped_column(DateTime(timezone=True))
    )

    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_delivery_idempotency",
        ),
        UniqueConstraint(
            "tenant_id",
            "id",
            name="uq_delivery_tenant_id",
        ),
        CheckConstraint(
            "attempts >= 0",
            name="ck_delivery_attempts",
        ),
        CheckConstraint(
            "max_attempts > 0",
            name="ck_delivery_max_attempts",
        ),
        Index(
            "ix_delivery_retry",
            "tenant_id",
            "status",
            "next_retry_at",
        ),
        Index(
            "ix_delivery_recipient",
            "tenant_id",
            "recipient_user_id",
        ),
    )


class DeliveryAttempt(TenantModel):
    __tablename__ = "retail_delivery_attempts"

    delivery_id: Mapped[str] = mapped_column(
        String(120), nullable=False
    )

    attempt_number: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    outcome: Mapped[str] = mapped_column(
        String(30), nullable=False
    )

    error_message: Mapped[str | None] = (
        mapped_column(Text)
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "delivery_id"],
            [
                "retail_notification_deliveries.tenant_id",
                "retail_notification_deliveries.id",
            ],
        ),
        UniqueConstraint(
            "tenant_id",
            "delivery_id",
            "attempt_number",
            name="uq_delivery_attempt_number",
        ),
    )


class DeliveryAuditEvent(TenantModel):
    __tablename__ = "retail_delivery_audit_events"

    delivery_id: Mapped[str] = mapped_column(
        String(120), nullable=False
    )

    actor_id: Mapped[str] = mapped_column(
        String(120), nullable=False
    )

    action: Mapped[str] = mapped_column(
        String(100), nullable=False
    )

    details: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "delivery_id"],
            [
                "retail_notification_deliveries.tenant_id",
                "retail_notification_deliveries.id",
            ],
        ),
    )


class DeliveryOutbox(TenantModel):
    __tablename__ = "retail_delivery_outbox"

    delivery_id: Mapped[str] = mapped_column(
        String(120), nullable=False
    )

    event_type: Mapped[str] = mapped_column(
        String(100), nullable=False
    )

    payload: Mapped[dict] = mapped_column(
        JSON, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    delivered_at: Mapped[datetime | None] = (
        mapped_column(DateTime(timezone=True))
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "delivery_id"],
            [
                "retail_notification_deliveries.tenant_id",
                "retail_notification_deliveries.id",
            ],
        ),
    )


class RetailDeliveryTracker(
    BaseRepository[DeliveryRecord]
):
    def __init__(
        self,
        session: Session,
        tenant_id: str,
        retry_base_seconds: int = 30,
    ):
        super().__init__(
            session, DeliveryRecord,
            required(tenant_id, "tenant_id"),
        )

        if (
            type(retry_base_seconds) is not int
            or retry_base_seconds <= 0
        ):
            raise ValueError(
                "retry_base_seconds must be positive"
            )

        self.retry_base_seconds = retry_base_seconds

    def _event(
        self,
        delivery: DeliveryRecord,
        actor_id: str,
        action: str,
        details: dict | None = None,
    ) -> None:
        self.session.add(DeliveryAuditEvent(
            id=str(uuid4()),
            tenant_id=self.tenant_id,
            delivery_id=delivery.id,
            actor_id=required(actor_id, "actor_id"),
            action=action,
            details=details or {},
        ))

        self.session.add(DeliveryOutbox(
            id=str(uuid4()),
            tenant_id=self.tenant_id,
            delivery_id=delivery.id,
            event_type=f"delivery.{action}",
            payload={
                "delivery_id": delivery.id,
                "notification_id": delivery.notification_id,
                "recipient_user_id":
                    delivery.recipient_user_id,
                "channel": delivery.channel,
                "status": delivery.status,
            },
        ))

        self.session.flush()

    def _check_version(
        self,
        delivery: DeliveryRecord,
        expected_version: int,
    ) -> None:
        if delivery.version != expected_version:
            raise VersionConflict(
                "Delivery version conflict"
            )

    def enqueue(
        self,
        *,
        notification_id: str,
        recipient_user_id: str,
        channel: DeliveryChannel,
        idempotency_key: str,
        actor_id: str,
        max_attempts: int = 3,
    ) -> DeliveryRecord:
        notification_id = required(
            notification_id, "notification_id"
        )
        recipient_user_id = required(
            recipient_user_id, "recipient_user_id"
        )
        idempotency_key = required(
            idempotency_key, "idempotency_key"
        )

        if not isinstance(channel, DeliveryChannel):
            raise ValueError("Invalid delivery channel")

        if (
            type(max_attempts) is not int
            or max_attempts <= 0
        ):
            raise ValueError("Invalid max_attempts")

        existing = self.session.scalar(
            select(DeliveryRecord).where(
                DeliveryRecord.tenant_id
                    == self.tenant_id,
                DeliveryRecord.idempotency_key
                    == idempotency_key,
            )
        )

        if existing is not None:
            if (
                existing.notification_id
                    != notification_id
                or existing.recipient_user_id
                    != recipient_user_id
                or existing.channel != channel.value
                or existing.max_attempts != max_attempts
            ):
                raise ValueError(
                    "Conflicting idempotency key"
                )
            return existing

        delivery = DeliveryRecord(
            id=str(uuid4()),
            tenant_id=self.tenant_id,
            notification_id=notification_id,
            recipient_user_id=recipient_user_id,
            channel=channel.value,
            status=DeliveryStatus.QUEUED.value,
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
            next_retry_at=utc_now(),
        )

        self.create(delivery)

        self._event(
            delivery,
            actor_id,
            "queued",
        )

        return delivery

    def start_attempt(
        self,
        *,
        delivery_id: str,
        expected_version: int,
        actor_id: str,
    ) -> DeliveryRecord:
        delivery = self.get(delivery_id)

        self._check_version(
            delivery, expected_version
        )

        if delivery.status not in {
            DeliveryStatus.QUEUED.value,
            DeliveryStatus.FAILED.value,
        }:
            raise ValueError(
                "Delivery is not ready for retry"
            )

        if delivery.attempts >= delivery.max_attempts:
            raise ValueError(
                "Maximum delivery attempts reached"
            )

        current_time = utc_now()

        if (
            delivery.next_retry_at is not None
            and delivery.next_retry_at > current_time
        ):
            raise ValueError(
                "Retry is not due yet"
            )

        updated = self.update(
            record_id=delivery_id,
            expected_version=expected_version,
            changes={
                "status": DeliveryStatus.SENDING.value,
                "attempts": delivery.attempts + 1,
                "next_retry_at": None,
                "updated_at": current_time,
            },
            allowed_fields={
                "status",
                "attempts",
                "next_retry_at",
                "updated_at",
            },
        )

        self._event(
            updated,
            actor_id,
            "attempt_started",
            {"attempt": updated.attempts},
        )

        return updated

    def mark_sent(
        self,
        *,
        delivery_id: str,
        expected_version: int,
        actor_id: str,
        provider_message_id: str | None = None,
    ) -> DeliveryRecord:
        delivery = self.get(delivery_id)
        self._check_version(
            delivery, expected_version
        )

        if delivery.status != DeliveryStatus.SENDING.value:
            raise ValueError(
                "Delivery must be sending"
            )

        current_time = utc_now()

        updated = self.update(
            record_id=delivery_id,
            expected_version=expected_version,
            changes={
                "status": DeliveryStatus.SENT.value,
                "sent_at": current_time,
                "provider_message_id": (
                    required(
                        provider_message_id,
                        "provider_message_id",
                    )
                    if provider_message_id is not None
                    else None
                ),
                "updated_at": current_time,
            },
            allowed_fields={
                "status",
                "sent_at",
                "provider_message_id",
                "updated_at",
            },
        )

        self.session.add(DeliveryAttempt(
            id=str(uuid4()),
            tenant_id=self.tenant_id,
            delivery_id=updated.id,
            attempt_number=updated.attempts,
            outcome="sent",
        ))

        self._event(
            updated, actor_id, "sent"
        )
        return updated

    def mark_delivered(
        self,
        *,
        delivery_id: str,
        expected_version: int,
        actor_id: str,
    ) -> DeliveryRecord:
        delivery = self.get(delivery_id)
        self._check_version(
            delivery, expected_version
        )

        if delivery.status not in {
            DeliveryStatus.SENT.value,
            DeliveryStatus.DELIVERED.value,
        }:
            raise ValueError(
                "Delivery must be sent"
            )

        if delivery.status == DeliveryStatus.DELIVERED.value:
            return delivery

        current_time = utc_now()

        updated = self.update(
            record_id=delivery_id,
            expected_version=expected_version,
            changes={
                "status": DeliveryStatus.DELIVERED.value,
                "delivered_at": current_time,
                "updated_at": current_time,
            },
            allowed_fields={
                "status",
                "delivered_at",
                "updated_at",
            },
        )

        self._event(
            updated, actor_id, "delivered"
        )
        return updated

    def mark_read(
        self,
        *,
        delivery_id: str,
        expected_version: int,
        actor_id: str,
    ) -> DeliveryRecord:
        delivery = self.get(delivery_id)
        self._check_version(
            delivery, expected_version
        )

        if delivery.status not in {
            DeliveryStatus.DELIVERED.value,
            DeliveryStatus.READ.value,
        }:
            raise ValueError(
                "Delivery must be delivered first"
            )

        if delivery.status == DeliveryStatus.READ.value:
            return delivery

        current_time = utc_now()

        updated = self.update(
            record_id=delivery_id,
            expected_version=expected_version,
            changes={
                "status": DeliveryStatus.READ.value,
                "read_at": current_time,
                "updated_at": current_time,
            },
            allowed_fields={
                "status",
                "read_at",
                "updated_at",
            },
        )

        self._event(
            updated, actor_id, "read"
        )
        return updated

    def mark_failed(
        self,
        *,
        delivery_id: str,
        expected_version: int,
        actor_id: str,
        error_message: str,
    ) -> DeliveryRecord:
        delivery = self.get(delivery_id)
        self._check_version(
            delivery, expected_version
        )

        if delivery.status != DeliveryStatus.SENDING.value:
            raise ValueError(
                "Only sending deliveries can fail"
            )

        current_time = utc_now()

        exhausted = (
            delivery.attempts >= delivery.max_attempts
        )

        new_status = (
            DeliveryStatus.DEAD_LETTER
            if exhausted
            else DeliveryStatus.FAILED
        )

        delay_seconds = min(
            self.retry_base_seconds
            * (2 ** max(delivery.attempts - 1, 0)),
            3600,
        )

        next_retry = (
            None
            if exhausted
            else current_time + timedelta(
                seconds=delay_seconds
            )
        )

        updated = self.update(
            record_id=delivery_id,
            expected_version=expected_version,
            changes={
                "status": new_status.value,
                "last_error": required(
                    error_message, "error_message"
                )[:2000],
                "next_retry_at": next_retry,
                "updated_at": current_time,
            },
            allowed_fields={
                "status",
                "last_error",
                "next_retry_at",
                "updated_at",
            },
        )

        self.session.add(DeliveryAttempt(
            id=str(uuid4()),
            tenant_id=self.tenant_id,
            delivery_id=updated.id,
            attempt_number=updated.attempts,
            outcome="failed",
            error_message=updated.last_error,
        ))

        self._event(
            updated,
            actor_id,
            "dead_letter" if exhausted else "failed",
            {
                "attempt": updated.attempts,
                "next_retry_at": (
                    next_retry.isoformat()
                    if next_retry else None
                ),
            },
        )

        return updated

    def pending_deliveries(
        self,
        limit: int = 100,
    ) -> list[DeliveryRecord]:
        if (
            type(limit) is not int
            or not 1 <= limit <= 500
        ):
            raise ValueError("Invalid limit")

        current_time = utc_now()

        return list(self.session.scalars(
            select(DeliveryRecord)
            .where(
                DeliveryRecord.tenant_id
                    == self.tenant_id,
                DeliveryRecord.status.in_([
                    DeliveryStatus.QUEUED.value,
                    DeliveryStatus.FAILED.value,
                ]),
                DeliveryRecord.attempts
                    < DeliveryRecord.max_attempts,
                DeliveryRecord.next_retry_at
                    <= current_time,
            )
            .order_by(
                DeliveryRecord.next_retry_at,
                DeliveryRecord.id,
            )
            .limit(limit)
        ))

    def recipient_deliveries(
        self,
        recipient_user_id: str,
        limit: int = 100,
    ) -> list[DeliveryRecord]:
        recipient_user_id = required(
            recipient_user_id, "recipient_user_id"
        )

        if (
            type(limit) is not int
            or not 1 <= limit <= 500
        ):
            raise ValueError("Invalid limit")

        return list(self.session.scalars(
            select(DeliveryRecord)
            .where(
                DeliveryRecord.tenant_id
                    == self.tenant_id,
                DeliveryRecord.recipient_user_id
                    == recipient_user_id,
            )
            .order_by(
                DeliveryRecord.created_at.desc(),
                DeliveryRecord.id.desc(),
            )
            .limit(limit)
        ))

    def attempt_history(
        self,
        delivery_id: str,
    ) -> list[DeliveryAttempt]:
        self.get(delivery_id)

        return list(self.session.scalars(
            select(DeliveryAttempt)
            .where(
                DeliveryAttempt.tenant_id
                    == self.tenant_id,
                DeliveryAttempt.delivery_id
                    == delivery_id,
            )
            .order_by(
                DeliveryAttempt.attempt_number
            )
        ))

    def delivery_metrics(self) -> dict:
        rows = self.session.execute(
            select(
                DeliveryRecord.status,
                func.count(DeliveryRecord.id),
            )
            .where(
                DeliveryRecord.tenant_id
                    == self.tenant_id
            )
            .group_by(DeliveryRecord.status)
        ).all()

        counts = {
            status.value: 0
            for status in DeliveryStatus
        }

        for status, count in rows:
            counts[status] = count

        return {
            "total": sum(counts.values()),
            "by_status": counts,
            "delivered_or_read": (
                counts[DeliveryStatus.DELIVERED.value]
                + counts[DeliveryStatus.READ.value]
            ),
            "failed_or_dead_letter": (
                counts[DeliveryStatus.FAILED.value]
                + counts[DeliveryStatus.DEAD_LETTER.value]
            ),
        }

    def pending_outbox_events(
        self,
        limit: int = 100,
    ) -> list[DeliveryOutbox]:
        if (
            type(limit) is not int
            or not 1 <= limit <= 500
        ):
            raise ValueError("Invalid limit")

        return list(self.session.scalars(
            select(DeliveryOutbox)
            .where(
                DeliveryOutbox.tenant_id
                    == self.tenant_id,
                DeliveryOutbox.delivered_at.is_(None),
            )
            .order_by(
                DeliveryOutbox.created_at,
                DeliveryOutbox.id,
            )
            .limit(limit)
        ))

    def mark_outbox_delivered(
        self,
        event_id: str,
    ) -> None:
        event = self.session.scalar(
            select(DeliveryOutbox).where(
                DeliveryOutbox.tenant_id
                    == self.tenant_id,
                DeliveryOutbox.id == event_id,
            )
        )

        if event is None:
            raise ValueError(
                "Outbox event not found"
            )

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

    with Session(
        engine,
        expire_on_commit=False,
    ) as session:
        tracker = RetailDeliveryTracker(
            session,
            tenant_id="retail-demo",
        )

        with UnitOfWork(session):
            delivery = tracker.enqueue(
                notification_id="NOTIF001",
                recipient_user_id="EMP001",
                channel=DeliveryChannel.DASHBOARD,
                idempotency_key="NOTIF001:EMP001:dashboard",
                actor_id="SYSTEM",
            )

        with UnitOfWork(session):
            delivery = tracker.start_attempt(
                delivery_id=delivery.id,
                expected_version=delivery.version,
                actor_id="WORKER001",
            )

        with UnitOfWork(session):
            delivery = tracker.mark_sent(
                delivery_id=delivery.id,
                expected_version=delivery.version,
                actor_id="WORKER001",
            )

        with UnitOfWork(session):
            delivery = tracker.mark_delivered(
                delivery_id=delivery.id,
                expected_version=delivery.version,
                actor_id="DASHBOARD",
            )

        with UnitOfWork(session):
            delivery = tracker.mark_read(
                delivery_id=delivery.id,
                expected_version=delivery.version,
                actor_id="EMP001",
            )

        print("Status:", delivery.status)
        print("Attempts:", delivery.attempts)
        print("Metrics:", tracker.delivery_metrics())
