from __future__ import annotations

"""Planned module: feedback. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
backend/services/customer_feedback_service.py

Python 3.10+ | Standard library only

Features:
- Customer reviews and complaints
- 1-5 star ratings
- Tenant and warehouse access control
- Source-event idempotency
- Basic heuristic sentiment
- Complaint lifecycle
- Support assignment
- Feedback analytics
- Audit trail
- Notification outbox
- JSON export

Reference implementation.
No real ML model or external messaging is connected.
"""


import copy
import json
import threading
import uuid

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def required_text(
    value: str,
    name: str,
    limit: int = 5000,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
    ):
        raise ValueError(f"Invalid {name}")
    return value.strip()


class FeedbackCategory(str, Enum):
    PRODUCT = "product"
    DELIVERY = "delivery"
    SERVICE = "service"
    QUALITY = "quality"
    PRICING = "pricing"
    RETURN = "return"
    OTHER = "other"


class FeedbackStatus(str, Enum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"
    CLOSED = "closed"


class FeedbackSentiment(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


@dataclass(frozen=True)
class FeedbackActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str] = frozenset()
    is_active: bool = True


@dataclass(frozen=True)
class FeedbackInput:
    tenant_id: str
    customer_id: str
    order_id: str
    product_sku: str
    category: FeedbackCategory
    rating: int
    title: str
    comment: str
    source_reference: str
    warehouse_id: str | None = None


@dataclass
class CustomerFeedback:
    feedback_id: str
    tenant_id: str
    customer_id: str
    order_id: str
    product_sku: str
    category: FeedbackCategory
    rating: int
    title: str
    comment: str
    source_reference: str
    warehouse_id: str | None
    sentiment: FeedbackSentiment
    status: FeedbackStatus
    assigned_to: str | None
    resolution_note: str | None
    created_at: str
    updated_at: str
    version: int = 1


@dataclass(frozen=True)
class FeedbackAuditEvent:
    event_id: str
    tenant_id: str
    feedback_id: str
    actor_id: str
    action: str
    timestamp: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class FeedbackOutboxEvent:
    event_id: str
    tenant_id: str
    feedback_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: str
    delivered: bool = False


SentimentPredictor = Callable[[str], FeedbackSentiment]


class RetailCustomerFeedbackService:
    WRITER_ROLES = frozenset({
        "customer_service",
        "feedback_manager",
        "operations_manager",
        "corporate_admin",
    })

    READER_ROLES = WRITER_ROLES | frozenset({
        "business_analyst",
        "quality_manager",
        "risk_analyst",
    })

    MANAGER_ROLES = frozenset({
        "feedback_manager",
        "operations_manager",
        "corporate_admin",
    })

    POSITIVE_WORDS = {
        "excellent", "great", "good", "fast",
        "perfect", "happy", "amazing", "love",
        "satisfied", "reliable",
    }

    NEGATIVE_WORDS = {
        "bad", "poor", "late", "damaged",
        "broken", "slow", "worst", "refund",
        "missing", "defective", "disappointed",
    }

    def __init__(
        self,
        tenant_id: str,
        sentiment_predictor: SentimentPredictor | None = None,
    ):
        self.tenant_id = required_text(
            tenant_id, "tenant_id", 200
        )
        self.sentiment_predictor = sentiment_predictor

        self._lock = threading.RLock()
        self._feedback: dict[str, CustomerFeedback] = {}
        self._source_index: dict[str, str] = {}
        self._audit: list[FeedbackAuditEvent] = []
        self._outbox: dict[str, FeedbackOutboxEvent] = {}

    def _authorize(
        self,
        actor: FeedbackActor,
        roles: frozenset[str],
        warehouse_id: str | None = None,
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.user_id.strip()
            or not actor.roles.intersection(roles)
        ):
            raise PermissionError("Feedback access denied")

        if warehouse_id is None:
            if "corporate_admin" not in actor.roles:
                raise PermissionError("Corporate scope required")
        elif (
            "corporate_admin" not in actor.roles
            and warehouse_id not in actor.warehouse_ids
        ):
            raise PermissionError("Warehouse scope denied")

    @classmethod
    def heuristic_sentiment(
        cls,
        comment: str,
    ) -> FeedbackSentiment:
        import re

        words = set(re.findall(r"[a-z]+", comment.lower()))
        score = (
            len(words & cls.POSITIVE_WORDS)
            - len(words & cls.NEGATIVE_WORDS)
        )

        if score > 0:
            return FeedbackSentiment.POSITIVE
        if score < 0:
            return FeedbackSentiment.NEGATIVE
        return FeedbackSentiment.NEUTRAL

    def _audit_event(
        self,
        actor_id: str,
        feedback_id: str,
        action: str,
        details: dict | None = None,
    ) -> None:
        self._audit.append(
            FeedbackAuditEvent(
                event_id=str(uuid.uuid4()),
                tenant_id=self.tenant_id,
                feedback_id=feedback_id,
                actor_id=actor_id,
                action=action,
                timestamp=utc_now(),
                details=copy.deepcopy(details or {}),
            )
        )

    def _emit(
        self,
        feedback: CustomerFeedback,
        event_type: str,
    ) -> None:
        event = FeedbackOutboxEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            feedback_id=feedback.feedback_id,
            event_type=event_type,
            payload={
                "feedback_id": feedback.feedback_id,
                "category": feedback.category.value,
                "rating": feedback.rating,
                "sentiment": feedback.sentiment.value,
                "status": feedback.status.value,
                "warehouse_id": feedback.warehouse_id,
            },
            created_at=utc_now(),
        )
        self._outbox[event.event_id] = event

    @staticmethod
    def _touch(feedback: CustomerFeedback) -> None:
        feedback.version += 1
        feedback.updated_at = utc_now()

    def submit_feedback(
        self,
        actor: FeedbackActor,
        data: FeedbackInput,
    ) -> CustomerFeedback:
        self._authorize(
            actor, self.WRITER_ROLES, data.warehouse_id
        )

        if data.tenant_id != self.tenant_id:
            raise PermissionError("Cross-tenant feedback")

        if type(data.rating) is not int or not 1 <= data.rating <= 5:
            raise ValueError("Rating must be an integer from 1 to 5")

        for name in (
            "customer_id", "order_id", "product_sku",
            "title", "comment", "source_reference"
        ):
            required_text(getattr(data, name), name)

        with self._lock:
            existing_id = self._source_index.get(data.source_reference)

            if existing_id:
                existing = self._feedback[existing_id]

                if (
                    existing.customer_id != data.customer_id
                    or existing.order_id != data.order_id
                    or existing.product_sku != data.product_sku
                    or existing.category != data.category
                    or existing.rating != data.rating
                    or existing.title != data.title
                    or existing.comment != data.comment
                    or existing.warehouse_id != data.warehouse_id
                ):
                    raise ValueError("Conflicting source reference")

                return copy.deepcopy(existing)

            sentiment = (
                self.sentiment_predictor(data.comment)
                if self.sentiment_predictor
                else self.heuristic_sentiment(data.comment)
            )

            if not isinstance(sentiment, FeedbackSentiment):
                raise ValueError("Invalid sentiment predictor output")

            current = utc_now()

            feedback = CustomerFeedback(
                feedback_id=str(uuid.uuid4()),
                tenant_id=self.tenant_id,
                customer_id=data.customer_id,
                order_id=data.order_id,
                product_sku=data.product_sku,
                category=data.category,
                rating=data.rating,
                title=data.title,
                comment=data.comment,
                source_reference=data.source_reference,
                warehouse_id=data.warehouse_id,
                sentiment=sentiment,
                status=FeedbackStatus.OPEN,
                assigned_to=None,
                resolution_note=None,
                created_at=current,
                updated_at=current,
            )

            self._feedback[feedback.feedback_id] = feedback
            self._source_index[data.source_reference] = feedback.feedback_id

            self._audit_event(
                actor.user_id, feedback.feedback_id, "feedback_submitted"
            )
            self._emit(feedback, "feedback.created")

            if feedback.rating <= 2:
                self._emit(feedback, "feedback.low_rating_alert")

            return copy.deepcopy(feedback)

    def get_feedback(
        self,
        actor: FeedbackActor,
        feedback_id: str,
    ) -> CustomerFeedback:
        with self._lock:
            feedback = self._feedback.get(feedback_id)
            if feedback is None:
                raise KeyError("Feedback not found")

            self._authorize(
                actor, self.READER_ROLES, feedback.warehouse_id
            )
            return copy.deepcopy(feedback)

    def list_feedback(
        self,
        actor: FeedbackActor,
        status: FeedbackStatus | None = None,
        sentiment: FeedbackSentiment | None = None,
    ) -> list[CustomerFeedback]:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.roles.intersection(self.READER_ROLES)
        ):
            raise PermissionError("Feedback access denied")

        with self._lock:
            return [
                copy.deepcopy(item)
                for item in self._feedback.values()
                if (
                    (
                        "corporate_admin" in actor.roles
                        or (
                            item.warehouse_id is not None
                            and item.warehouse_id in actor.warehouse_ids
                        )
                    )
                    and (status is None or item.status == status)
                    and (
                        sentiment is None
                        or item.sentiment == sentiment
                    )
                )
            ]

    def assign_feedback(
        self,
        actor: FeedbackActor,
        feedback_id: str,
        expected_version: int,
        assignee_id: str,
    ) -> CustomerFeedback:
        assignee_id = required_text(
            assignee_id, "assignee_id", 200
        )

        with self._lock:
            feedback = self._feedback.get(feedback_id)
            if feedback is None:
                raise KeyError("Feedback not found")

            self._authorize(
                actor, self.MANAGER_ROLES, feedback.warehouse_id
            )

            if feedback.version != expected_version:
                raise ValueError("Version conflict")

            if feedback.status in {
                FeedbackStatus.RESOLVED,
                FeedbackStatus.CLOSED,
            }:
                raise ValueError("Feedback already resolved or closed")

            feedback.assigned_to = assignee_id
            feedback.status = FeedbackStatus.IN_REVIEW
            self._touch(feedback)

            self._audit_event(
                actor.user_id,
                feedback_id,
                "feedback_assigned",
                {"assignee_id": assignee_id},
            )
            self._emit(feedback, "feedback.assigned")

            return copy.deepcopy(feedback)

    def resolve_feedback(
        self,
        actor: FeedbackActor,
        feedback_id: str,
        expected_version: int,
        resolution_note: str,
    ) -> CustomerFeedback:
        resolution_note = required_text(
            resolution_note, "resolution_note", 2000
        )

        with self._lock:
            feedback = self._feedback.get(feedback_id)
            if feedback is None:
                raise KeyError("Feedback not found")

            self._authorize(
                actor, self.WRITER_ROLES, feedback.warehouse_id
            )

            if feedback.version != expected_version:
                raise ValueError("Version conflict")

            if feedback.status not in {
                FeedbackStatus.OPEN,
                FeedbackStatus.IN_REVIEW,
            }:
                raise ValueError("Feedback cannot be resolved")

            feedback.status = FeedbackStatus.RESOLVED
            feedback.resolution_note = resolution_note
            self._touch(feedback)

            self._audit_event(
                actor.user_id, feedback_id, "feedback_resolved"
            )
            self._emit(feedback, "feedback.resolved")

            return copy.deepcopy(feedback)

    def close_feedback(
        self,
        actor: FeedbackActor,
        feedback_id: str,
        expected_version: int,
    ) -> CustomerFeedback:
        with self._lock:
            feedback = self._feedback.get(feedback_id)
            if feedback is None:
                raise KeyError("Feedback not found")

            self._authorize(
                actor, self.MANAGER_ROLES, feedback.warehouse_id
            )

            if feedback.version != expected_version:
                raise ValueError("Version conflict")

            if feedback.status != FeedbackStatus.RESOLVED:
                raise ValueError("Resolve feedback before closing")

            feedback.status = FeedbackStatus.CLOSED
            self._touch(feedback)

            self._audit_event(
                actor.user_id, feedback_id, "feedback_closed"
            )
            self._emit(feedback, "feedback.closed")

            return copy.deepcopy(feedback)

    def analytics(self, actor: FeedbackActor) -> dict[str, Any]:
        records = self.list_feedback(actor)
        total = len(records)

        return {
            "tenant_id": self.tenant_id,
            "total_feedback": total,
            "average_rating": (
                round(sum(r.rating for r in records) / total, 2)
                if total else None
            ),
            "by_sentiment": {
                sentiment.value: sum(
                    r.sentiment == sentiment for r in records
                )
                for sentiment in FeedbackSentiment
            },
            "by_status": {
                status.value: sum(
                    r.status == status for r in records
                )
                for status in FeedbackStatus
            },
            "low_rating_count": sum(
                r.rating <= 2 for r in records
            ),
            "resolution_rate_pct": (
                round(
                    100 * sum(
                        r.status in {
                            FeedbackStatus.RESOLVED,
                            FeedbackStatus.CLOSED,
                        }
                        for r in records
                    ) / total,
                    2,
                )
                if total else None
            ),
        }

    def pending_events(
        self,
        actor: FeedbackActor,
    ) -> list[FeedbackOutboxEvent]:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.roles.intersection(self.WRITER_ROLES)
        ):
            raise PermissionError("Outbox access denied")

        with self._lock:
            return [
                copy.deepcopy(event)
                for event in self._outbox.values()
                if (
                    not event.delivered
                    and (
                        "corporate_admin" in actor.roles
                        or (
                            self._feedback[event.feedback_id].warehouse_id
                            is not None
                            and self._feedback[
                                event.feedback_id
                            ].warehouse_id in actor.warehouse_ids
                        )
                    )
                )
            ]

    def mark_event_delivered(
        self,
        actor: FeedbackActor,
        event_id: str,
    ) -> None:
        with self._lock:
            event = self._outbox.get(event_id)
            if event is None:
                raise KeyError("Event not found")

            feedback = self._feedback[event.feedback_id]
            self._authorize(
                actor, self.WRITER_ROLES, feedback.warehouse_id
            )
            event.delivered = True

    def audit_events(
        self,
        actor: FeedbackActor,
        feedback_id: str,
    ) -> list[FeedbackAuditEvent]:
        self.get_feedback(actor, feedback_id)

        with self._lock:
            return [
                copy.deepcopy(event)
                for event in self._audit
                if event.feedback_id == feedback_id
            ]

    def export_json(
        self,
        actor: FeedbackActor,
        output_path: str | Path,
    ) -> Path:
        records = self.list_feedback(actor)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                [asdict(r) for r in records],
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    service = RetailCustomerFeedbackService("demo")

    manager = FeedbackActor(
        user_id="manager001",
        tenant_id="demo",
        roles=frozenset({"feedback_manager"}),
        warehouse_ids=frozenset({"WH001"}),
    )

    feedback = service.submit_feedback(
        manager,
        FeedbackInput(
            tenant_id="demo",
            customer_id="C001",
            order_id="ORD001",
            product_sku="SKU001",
            category=FeedbackCategory.DELIVERY,
            rating=2,
            title="Delayed delivery",
            comment="Late delivery and poor service.",
            source_reference="REVIEW001",
            warehouse_id="WH001",
        ),
    )

    print("Sentiment:", feedback.sentiment.value)

    feedback = service.assign_feedback(
        manager,
        feedback.feedback_id,
        feedback.version,
        "support001",
    )

    feedback = service.resolve_feedback(
        manager,
        feedback.feedback_id,
        feedback.version,
        "Customer contacted and issue resolved.",
    )

    feedback = service.close_feedback(
        manager,
        feedback.feedback_id,
        feedback.version,
    )

    print("Status:", feedback.status.value)
    print("Analytics:", service.analytics(manager))
