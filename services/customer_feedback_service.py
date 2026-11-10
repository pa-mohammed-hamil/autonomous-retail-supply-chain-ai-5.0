from __future__ import annotations


"""
backend/services/customer_feedback_service.py

Autonomous Retail Supply Chain AI 5.0

Customer Feedback Intelligence Service

Python 3.10+
Dependencies: standard library only.

Features:
- Feedback submission
- Ratings and review management
- Rule-based sentiment baseline
- Feedback topic classification
- Complaint priority detection
- Feedback status workflows
- Tenant-scoped access
- Duplicate submission prevention
- Customer satisfaction analytics
- JSON export
- Optional ML sentiment integration

This is an in-memory prototype.

Production requires authenticated
customer identities, database
persistence, moderation, privacy
controls, and authorization.
"""


import copy
import hashlib
import json
import re
import threading
import uuid

from collections import Counter
from dataclasses import (
    asdict,
    dataclass,
    field,
)
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Callable,
)


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


class FeedbackType(str, Enum):
    PRODUCT_REVIEW = "product_review"
    DELIVERY = "delivery"
    COMPLAINT = "complaint"
    SUPPORT = "support"
    SUGGESTION = "suggestion"
    GENERAL = "general"


class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class FeedbackPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FeedbackStatus(str, Enum):
    NEW = "new"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"
    CLOSED = "closed"


@dataclass(frozen=True)
class FeedbackActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    is_active: bool = True


@dataclass
class CustomerFeedback:
    feedback_id: str
    tenant_id: str
    customer_id: str
    feedback_type: FeedbackType
    text: str
    rating: int | None
    product_id: str | None
    order_id: str | None
    sentiment: Sentiment
    sentiment_score: float
    sentiment_method: str
    topics: list[str]
    priority: FeedbackPriority
    status: FeedbackStatus
    created_at: str
    updated_at: str
    resolution_note: str | None = None
    resolved_by: str | None = None
    metadata: dict[str, Any] = field(
        default_factory=dict
    )


class RetailCustomerFeedbackService:
    """
    Feedback processing and analytics.

    The default sentiment model is a
    simple lexical baseline.

    Optional sentiment_predictor:

        predictor(text) -> {
            "sentiment": "negative",
            "score": 0.92
        }

    The score is treated as a
    model-reported confidence, not
    a calibrated probability.
    """

    POSITIVE_TERMS = {
        "excellent", "great", "good",
        "amazing", "fast", "perfect",
        "satisfied", "happy", "quality",
        "reliable", "helpful", "love",
        "smooth", "recommended",
    }

    NEGATIVE_TERMS = {
        "bad", "poor", "broken",
        "damaged", "late", "delay",
        "delayed", "missing", "wrong",
        "defective", "refund", "failed",
        "terrible", "worst", "unhappy",
        "disappointed", "slow",
    }

    TOPIC_TERMS = {
        "delivery": {
            "delivery", "shipping",
            "courier", "late", "delay",
            "delayed", "tracking",
        },
        "product_quality": {
            "quality", "broken",
            "damaged", "defective",
            "product", "faulty",
        },
        "pricing": {
            "price", "expensive",
            "discount", "cost",
            "overpriced",
        },
        "customer_support": {
            "support", "service",
            "agent", "response",
            "helpdesk",
        },
        "refund_returns": {
            "refund", "return",
            "replacement", "exchange",
        },
        "availability": {
            "stock", "unavailable",
            "outofstock", "inventory",
        },
    }

    CRITICAL_PHRASES = (
        "data breach",
        "payment fraud",
        "identity theft",
        "unsafe product",
        "serious injury",
        "fire hazard",
    )

    def __init__(
        self,
        sentiment_predictor: (
            Callable[[str], dict[str, Any]]
            | None
        ) = None,
    ):
        self._lock = threading.RLock()

        self._feedback: dict[
            str, CustomerFeedback
        ] = {}

        self._submission_keys: dict[
            tuple[str, str],
            str,
        ] = {}

        self.sentiment_predictor = (
            sentiment_predictor
        )

    @staticmethod
    def _validate_actor(
        actor: FeedbackActor,
    ) -> None:
        if (
            not actor.is_active
            or not actor.user_id.strip()
            or not actor.tenant_id.strip()
        ):
            raise PermissionError(
                "Invalid actor"
            )

    @staticmethod
    def _tokens(
        text: str,
    ) -> list[str]:
        return re.findall(
            r"[a-z]+",
            text.casefold(),
        )

    def _predict_sentiment(
        self,
        text: str,
    ) -> tuple[
        Sentiment,
        float,
        str,
    ]:
        if self.sentiment_predictor:
            prediction = (
                self.sentiment_predictor(
                    text
                )
            )

            if not isinstance(
                prediction,
                dict,
            ):
                raise ValueError(
                    "Invalid sentiment response"
                )

            sentiment = Sentiment(
                prediction["sentiment"]
            )

            score = prediction["score"]

            if (
                isinstance(score, bool)
                or not isinstance(
                    score,
                    (int, float),
                )
                or not 0 <= score <= 1
            ):
                raise ValueError(
                    "Invalid sentiment score"
                )

            return (
                sentiment,
                float(score),
                "ml_predictor",
            )

        tokens = self._tokens(text)

        positive = sum(
            token in self.POSITIVE_TERMS
            for token in tokens
        )

        negative = sum(
            token in self.NEGATIVE_TERMS
            for token in tokens
        )

        if positive > negative:
            sentiment = Sentiment.POSITIVE
        elif negative > positive:
            sentiment = Sentiment.NEGATIVE
        else:
            sentiment = Sentiment.NEUTRAL

        total = positive + negative

        score = (
            abs(positive - negative) / total
            if total
            else 0.0
        )

        return (
            sentiment,
            round(score, 4),
            "lexical_baseline",
        )

    def _detect_topics(
        self,
        text: str,
    ) -> list[str]:
        tokens = set(
            self._tokens(text)
        )

        topics = [
            topic
            for topic, keywords in (
                self.TOPIC_TERMS.items()
            )
            if tokens & keywords
        ]

        return topics or ["general"]

    def _priority(
        self,
        text: str,
        rating: int | None,
        sentiment: Sentiment,
        feedback_type: FeedbackType,
    ) -> FeedbackPriority:
        normalized = text.casefold()

        if any(
            phrase in normalized
            for phrase in self.CRITICAL_PHRASES
        ):
            return FeedbackPriority.CRITICAL

        if (
            feedback_type == FeedbackType.COMPLAINT
            and (
                rating is not None
                and rating <= 2
            )
        ):
            return FeedbackPriority.HIGH

        if (
            sentiment == Sentiment.NEGATIVE
            or (
                rating is not None
                and rating <= 2
            )
        ):
            return FeedbackPriority.MEDIUM

        return FeedbackPriority.LOW

    @staticmethod
    def _validate_metadata(
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        metadata = metadata or {}

        if not isinstance(
            metadata,
            dict,
        ):
            raise ValueError(
                "Metadata must be a dict"
            )

        encoded = json.dumps(
            metadata,
            allow_nan=False,
            sort_keys=True,
        )

        if len(encoded) > 20000:
            raise ValueError(
                "Metadata too large"
            )

        return json.loads(encoded)

    def submit_feedback(
        self,
        actor: FeedbackActor,
        text: str,
        feedback_type: FeedbackType,
        rating: int | None = None,
        product_id: str | None = None,
        order_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> CustomerFeedback:
        with self._lock:
            self._validate_actor(
                actor
            )

            if not (
                actor.roles
                & {
                    "customer",
                    "feedback_submitter",
                    "support_agent",
                }
            ):
                raise PermissionError(
                    "Feedback submission denied"
                )

            if (
                not isinstance(text, str)
                or not text.strip()
                or len(text) > 10000
            ):
                raise ValueError(
                    "Invalid feedback text"
                )

            if (
                rating is not None
                and (
                    isinstance(rating, bool)
                    or not isinstance(
                        rating,
                        int,
                    )
                    or not 1 <= rating <= 5
                )
            ):
                raise ValueError(
                    "Rating must be 1 to 5"
                )

            if idempotency_key:
                key = (
                    actor.tenant_id,
                    idempotency_key,
                )

                existing_id = (
                    self._submission_keys.get(
                        key
                    )
                )

                if existing_id:
                    existing = (
                        self._feedback[
                            existing_id
                        ]
                    )

                    if (
                        existing.customer_id
                        != actor.user_id
                    ):
                        raise PermissionError(
                            "Idempotency key already used"
                        )

                    return copy.deepcopy(
                        existing
                    )

            (
                sentiment,
                score,
                method,
            ) = self._predict_sentiment(
                text
            )

            topics = self._detect_topics(
                text
            )

            priority = self._priority(
                text,
                rating,
                sentiment,
                feedback_type,
            )

            now = utc_now()

            feedback = CustomerFeedback(
                feedback_id=str(
                    uuid.uuid4()
                ),
                tenant_id=actor.tenant_id,
                customer_id=actor.user_id,
                feedback_type=feedback_type,
                text=text.strip(),
                rating=rating,
                product_id=product_id,
                order_id=order_id,
                sentiment=sentiment,
                sentiment_score=score,
                sentiment_method=method,
                topics=topics,
                priority=priority,
                status=FeedbackStatus.NEW,
                created_at=now,
                updated_at=now,
                metadata=(
                    self._validate_metadata(
                        metadata
                    )
                ),
            )

            self._feedback[
                feedback.feedback_id
            ] = feedback

            if idempotency_key:
                self._submission_keys[
                    (
                        actor.tenant_id,
                        idempotency_key,
                    )
                ] = feedback.feedback_id

            return copy.deepcopy(
                feedback
            )

    def _get(
        self,
        feedback_id: str,
        actor: FeedbackActor,
    ) -> CustomerFeedback:
        self._validate_actor(actor)

        feedback = self._feedback.get(
            feedback_id
        )

        if (
            feedback is None
            or feedback.tenant_id
            != actor.tenant_id
        ):
            raise KeyError(
                "Feedback not found"
            )

        is_owner = (
            feedback.customer_id
            == actor.user_id
        )

        is_staff = bool(
            actor.roles
            & {
                "support_agent",
                "customer_experience_manager",
                "corporate_admin",
            }
        )

        if not (
            is_owner or is_staff
        ):
            raise PermissionError(
                "Feedback access denied"
            )

        return feedback

    def get_feedback(
        self,
        feedback_id: str,
        actor: FeedbackActor,
    ) -> CustomerFeedback:
        with self._lock:
            return copy.deepcopy(
                self._get(
                    feedback_id,
                    actor,
                )
            )

    def update_status(
        self,
        feedback_id: str,
        actor: FeedbackActor,
        status: FeedbackStatus,
        resolution_note: str | None = None,
    ) -> CustomerFeedback:
        with self._lock:
            self._validate_actor(
                actor
            )

            if not (
                actor.roles
                & {
                    "support_agent",
                    "customer_experience_manager",
                    "corporate_admin",
                }
            ):
                raise PermissionError(
                    "Status update denied"
                )

            feedback = self._get(
                feedback_id,
                actor,
            )

            allowed = {
                FeedbackStatus.NEW: {
                    FeedbackStatus.IN_REVIEW,
                },
                FeedbackStatus.IN_REVIEW: {
                    FeedbackStatus.RESOLVED,
                },
                FeedbackStatus.RESOLVED: {
                    FeedbackStatus.CLOSED,
                },
                FeedbackStatus.CLOSED: set(),
            }

            if status not in allowed[
                feedback.status
            ]:
                raise ValueError(
                    "Invalid status transition"
                )

            if (
                status == FeedbackStatus.RESOLVED
                and (
                    not resolution_note
                    or not resolution_note.strip()
                )
            ):
                raise ValueError(
                    "Resolution note required"
                )

            feedback.status = status
            feedback.updated_at = utc_now()

            if status == FeedbackStatus.RESOLVED:
                feedback.resolution_note = (
                    resolution_note.strip()
                )

                feedback.resolved_by = (
                    actor.user_id
                )

            return copy.deepcopy(
                feedback
            )

    def list_feedback(
        self,
        actor: FeedbackActor,
        status: FeedbackStatus | None = None,
        product_id: str | None = None,
    ) -> list[CustomerFeedback]:
        with self._lock:
            self._validate_actor(
                actor
            )

            is_staff = bool(
                actor.roles
                & {
                    "support_agent",
                    "customer_experience_manager",
                    "corporate_admin",
                }
            )

            results = []

            for feedback in (
                self._feedback.values()
            ):
                if (
                    feedback.tenant_id
                    != actor.tenant_id
                ):
                    continue

                if (
                    not is_staff
                    and feedback.customer_id
                    != actor.user_id
                ):
                    continue

                if (
                    status is not None
                    and feedback.status
                    != status
                ):
                    continue

                if (
                    product_id is not None
                    and feedback.product_id
                    != product_id
                ):
                    continue

                results.append(
                    copy.deepcopy(
                        feedback
                    )
                )

            return results

    def analytics(
        self,
        actor: FeedbackActor,
    ) -> dict[str, Any]:
        if not (
            actor.roles
            & {
                "customer_experience_manager",
                "corporate_admin",
            }
        ):
            raise PermissionError(
                "Analytics access denied"
            )

        records = self.list_feedback(
            actor
        )

        ratings = [
            item.rating
            for item in records
            if item.rating is not None
        ]

        sentiments = Counter(
            item.sentiment.value
            for item in records
        )

        priorities = Counter(
            item.priority.value
            for item in records
        )

        topics = Counter(
            topic
            for item in records
            for topic in item.topics
        )

        statuses = Counter(
            item.status.value
            for item in records
        )

        return {
            "tenant_id": actor.tenant_id,
            "total_feedback": len(records),
            "average_rating": (
                round(
                    sum(ratings)
                    / len(ratings),
                    2,
                )
                if ratings
                else None
            ),
            "rating_count": len(ratings),
            "positive_feedback": (
                sentiments["positive"]
            ),
            "negative_feedback": (
                sentiments["negative"]
            ),
            "neutral_feedback": (
                sentiments["neutral"]
            ),
            "sentiment_distribution": (
                dict(sentiments)
            ),
            "priority_distribution": (
                dict(priorities)
            ),
            "topic_distribution": (
                dict(topics)
            ),
            "status_distribution": (
                dict(statuses)
            ),
            "negative_feedback_rate_pct": (
                round(
                    sentiments["negative"]
                    / len(records) * 100,
                    2,
                )
                if records
                else None
            ),
            "resolution_rate_pct": (
                round(
                    (
                        statuses["resolved"]
                        + statuses["closed"]
                    )
                    / len(records) * 100,
                    2,
                )
                if records
                else None
            ),
        }

    def export_json(
        self,
        actor: FeedbackActor,
        output_path: str | Path,
    ) -> Path:
        if "corporate_admin" not in (
            actor.roles
        ):
            raise PermissionError(
                "Export access denied"
            )

        records = self.list_feedback(
            actor
        )

        output = Path(output_path)

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            json.dumps(
                [
                    asdict(item)
                    for item in records
                ],
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return output


if __name__ == "__main__":
    service = RetailCustomerFeedbackService()

    customer = FeedbackActor(
        user_id="customer-001",
        tenant_id="demo",
        roles=frozenset({
            "customer",
        }),
    )

    manager = FeedbackActor(
        user_id="cx-manager",
        tenant_id="demo",
        roles=frozenset({
            "customer_experience_manager",
        }),
    )

    feedback = service.submit_feedback(
        actor=customer,
        text=(
            "The product quality is good "
            "but the delivery was delayed."
        ),
        feedback_type=FeedbackType.DELIVERY,
        rating=3,
        product_id="SKU001",
        order_id="ORD001",
        idempotency_key="feedback-001",
    )

    print(
        "Feedback created:",
        feedback.feedback_id,
    )

    print(
        "Sentiment:",
        feedback.sentiment.value,
    )

    service.update_status(
        feedback.feedback_id,
        manager,
        FeedbackStatus.IN_REVIEW,
    )

    service.update_status(
        feedback.feedback_id,
        manager,
        FeedbackStatus.RESOLVED,
        resolution_note=(
            "Delivery issue reviewed"
        ),
    )

    print(
        json.dumps(
            service.analytics(manager),
            indent=2,
        )
    )
