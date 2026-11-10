from __future__ import annotations

"""Planned module: simulation service. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
backend/services/sentiment_service.py

Python 3.10+ | Standard library only

Reference implementation:
- Multi-tenant RBAC
- Customer feedback sentiment
- Rule-based sentiment classification
- Optional ML classifier adapter
- Aspect detection
- Complaint priority assessment
- Idempotent feedback analysis
- Product-level analytics
- Audit history
- Notification outbox
- JSON export

The default classifier is heuristic.
It is not a trained NLP model.
"""


import copy
import json
import math
import re
import threading
import uuid

from collections import Counter
from dataclasses import (
    asdict,
    dataclass,
    field,
)
from datetime import (
    datetime,
    timezone,
)
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def required_text(
    value: str,
    name: str,
    max_length: int = 10000,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > max_length
    ):
        raise ValueError(
            f"Invalid {name}"
        )

    return value.strip()


class SentimentLabel(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class SentimentPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FeedbackSource(str, Enum):
    PRODUCT_REVIEW = "product_review"
    DELIVERY = "delivery"
    SUPPORT = "support"
    CUSTOMER_COMPLAINT = (
        "customer_complaint"
    )
    GENERAL = "general"


@dataclass(frozen=True)
class SentimentActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    is_active: bool = True


@dataclass(frozen=True)
class SentimentInput:
    feedback_id: str
    tenant_id: str
    customer_id: str
    text: str
    source: FeedbackSource
    product_id: str | None = None
    order_id: str | None = None
    rating: int | None = None


@dataclass(frozen=True)
class SentimentPrediction:
    label: SentimentLabel
    confidence: float
    score: float
    model_name: str


@dataclass(frozen=True)
class SentimentResult:
    analysis_id: str
    tenant_id: str
    feedback_id: str
    customer_id: str
    product_id: str | None
    order_id: str | None
    source: FeedbackSource
    label: SentimentLabel
    confidence: float
    sentiment_score: float
    priority: SentimentPriority
    aspects: tuple[str, ...]
    keywords: tuple[str, ...]
    model_name: str
    analyzed_at: str


@dataclass(frozen=True)
class SentimentAuditEvent:
    event_id: str
    tenant_id: str
    analysis_id: str
    actor_id: str
    action: str
    timestamp: str
    details: dict = field(
        default_factory=dict
    )


@dataclass
class SentimentOutboxEvent:
    event_id: str
    tenant_id: str
    event_type: str
    source_id: str
    payload: dict
    created_at: str
    delivered: bool = False


# Optional model contract:
# classifier(text) -> SentimentPrediction
SentimentClassifier = Callable[
    [str],
    SentimentPrediction,
]


class RetailSentimentService:
    READER_ROLES = frozenset({
        "sentiment_analyst",
        "customer_support",
        "product_manager",
        "operations_manager",
        "corporate_admin",
    })

    ANALYST_ROLES = frozenset({
        "sentiment_analyst",
        "product_manager",
        "operations_manager",
        "corporate_admin",
    })

    POSITIVE_WORDS = frozenset({
        "good",
        "great",
        "excellent",
        "amazing",
        "fast",
        "reliable",
        "perfect",
        "happy",
        "satisfied",
        "love",
        "quality",
        "helpful",
        "smooth",
        "affordable",
    })

    NEGATIVE_WORDS = frozenset({
        "bad",
        "poor",
        "terrible",
        "broken",
        "damaged",
        "late",
        "delay",
        "delayed",
        "worst",
        "refund",
        "defective",
        "expensive",
        "unhappy",
        "disappointed",
        "missing",
        "failed",
        "unsafe",
    })

    NEGATORS = frozenset({
        "not",
        "never",
        "no",
        "hardly",
    })

    ASPECT_KEYWORDS = {
        "product_quality": {
            "quality",
            "broken",
            "damaged",
            "defective",
            "durable",
        },
        "delivery": {
            "delivery",
            "shipping",
            "late",
            "delayed",
            "courier",
        },
        "pricing": {
            "price",
            "cost",
            "expensive",
            "affordable",
            "discount",
        },
        "customer_service": {
            "support",
            "service",
            "agent",
            "helpful",
            "response",
        },
        "refunds": {
            "refund",
            "return",
            "replacement",
        },
        "availability": {
            "stock",
            "unavailable",
            "missing",
            "inventory",
        },
    }

    CRITICAL_TERMS = {
        "fire",
        "injury",
        "electric shock",
        "data breach",
        "dangerous",
        "toxic",
    }

    def __init__(
        self,
        tenant_id: str,
        classifier: SentimentClassifier | None = None,
    ):
        self.tenant_id = required_text(
            tenant_id,
            "tenant_id",
        )

        self.classifier = classifier

        self._lock = threading.RLock()

        self._results: dict[
            str, SentimentResult
        ] = {}

        self._inputs: dict[
            str, SentimentInput
        ] = {}

        self._audit: list[
            SentimentAuditEvent
        ] = []

        self._outbox: dict[
            str, SentimentOutboxEvent
        ] = {}

    def _authorize(
        self,
        actor: SentimentActor,
        roles: frozenset[str],
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id
            != self.tenant_id
            or not actor.user_id.strip()
            or not (actor.roles & roles)
        ):
            raise PermissionError(
                "Sentiment access denied"
            )

    @staticmethod
    def _tokens(
        text: str,
    ) -> list[str]:
        return re.findall(
            r"[a-z]+",
            text.lower(),
        )

    def _rule_prediction(
        self,
        text: str,
    ) -> SentimentPrediction:
        tokens = self._tokens(
            text
        )

        score = 0

        for index, token in enumerate(
            tokens
        ):
            polarity = 0

            if token in (
                self.POSITIVE_WORDS
            ):
                polarity = 1

            elif token in (
                self.NEGATIVE_WORDS
            ):
                polarity = -1

            if polarity:
                context = tokens[
                    max(0, index - 3):
                    index
                ]

                if any(
                    word in self.NEGATORS
                    for word in context
                ):
                    polarity *= -1

                score += polarity

        if score > 0:
            label = (
                SentimentLabel.POSITIVE
            )

        elif score < 0:
            label = (
                SentimentLabel.NEGATIVE
            )

        else:
            label = (
                SentimentLabel.NEUTRAL
            )

        normalized_score = max(
            -1.0,
            min(
                1.0,
                score / 5,
            ),
        )

        # Heuristic strength, not
        # calibrated model confidence.
        confidence = min(
            0.85,
            0.50 + abs(score) * 0.08,
        )

        return SentimentPrediction(
            label=label,
            confidence=round(
                confidence, 3
            ),
            score=round(
                normalized_score, 3
            ),
            model_name=(
                "retail_lexicon_v1"
            ),
        )

    def _detect_aspects(
        self,
        text: str,
    ) -> tuple[str, ...]:
        tokens = set(
            self._tokens(text)
        )

        return tuple(
            sorted(
                aspect
                for aspect, keywords
                in self.ASPECT_KEYWORDS.items()
                if tokens & keywords
            )
        )

    def _keywords(
        self,
        text: str,
    ) -> tuple[str, ...]:
        tokens = self._tokens(
            text
        )

        relevant = (
            self.POSITIVE_WORDS
            | self.NEGATIVE_WORDS
        )

        return tuple(
            sorted({
                token
                for token in tokens
                if token in relevant
            })
        )

    def _priority(
        self,
        feedback: SentimentInput,
        prediction: SentimentPrediction,
        aspects: tuple[str, ...],
    ) -> SentimentPriority:
        lowered = (
            feedback.text.lower()
        )

        if any(
            term in lowered
            for term in self.CRITICAL_TERMS
        ):
            return (
                SentimentPriority.CRITICAL
            )

        if (
            prediction.label
            == SentimentLabel.NEGATIVE
        ):
            if (
                feedback.rating == 1
                or "product_quality"
                in aspects
                or "refunds"
                in aspects
            ):
                return (
                    SentimentPriority.HIGH
                )

            return (
                SentimentPriority.MEDIUM
            )

        if feedback.rating is not None:
            if feedback.rating <= 2:
                return (
                    SentimentPriority.MEDIUM
                )

        return (
            SentimentPriority.LOW
        )

    def analyze(
        self,
        actor: SentimentActor,
        feedback: SentimentInput,
    ) -> SentimentResult:
        self._authorize(
            actor,
            self.ANALYST_ROLES,
        )

        if feedback.tenant_id != (
            self.tenant_id
        ):
            raise PermissionError(
                "Cross-tenant feedback"
            )

        required_text(
            feedback.feedback_id,
            "feedback_id",
        )

        required_text(
            feedback.customer_id,
            "customer_id",
        )

        text = required_text(
            feedback.text,
            "feedback text",
        )

        if (
            feedback.rating is not None
            and (
                isinstance(
                    feedback.rating,
                    bool,
                )
                or not isinstance(
                    feedback.rating,
                    int,
                )
                or not (
                    1 <= feedback.rating <= 5
                )
            )
        ):
            raise ValueError(
                "Rating must be 1 to 5"
            )

        with self._lock:
            existing = self._results.get(
                feedback.feedback_id
            )

            if existing:
                if (
                    self._inputs[
                        feedback.feedback_id
                    ] != feedback
                ):
                    raise ValueError(
                        "Feedback ID conflict"
                    )

                return copy.deepcopy(
                    existing
                )

        if self.classifier:
            prediction = self.classifier(
                text
            )
        else:
            prediction = (
                self._rule_prediction(
                    text
                )
            )

        if not isinstance(
            prediction,
            SentimentPrediction,
        ):
            raise TypeError(
                "Classifier must return SentimentPrediction"
            )

        if (
            not math.isfinite(
                prediction.confidence
            )
            or not 0 <= (
                prediction.confidence
            ) <= 1
            or not math.isfinite(
                prediction.score
            )
            or not -1 <= (
                prediction.score
            ) <= 1
        ):
            raise ValueError(
                "Invalid classifier output"
            )

        aspects = self._detect_aspects(
            text
        )

        priority = self._priority(
            feedback,
            prediction,
            aspects,
        )

        result = SentimentResult(
            analysis_id=str(
                uuid.uuid4()
            ),
            tenant_id=self.tenant_id,
            feedback_id=(
                feedback.feedback_id
            ),
            customer_id=(
                feedback.customer_id
            ),
            product_id=(
                feedback.product_id
            ),
            order_id=(
                feedback.order_id
            ),
            source=feedback.source,
            label=prediction.label,
            confidence=(
                prediction.confidence
            ),
            sentiment_score=(
                prediction.score
            ),
            priority=priority,
            aspects=aspects,
            keywords=self._keywords(
                text
            ),
            model_name=(
                prediction.model_name
            ),
            analyzed_at=utc_now(),
        )

        with self._lock:
            existing = self._results.get(
                feedback.feedback_id
            )

            if existing:
                if (
                    self._inputs[
                        feedback.feedback_id
                    ] != feedback
                ):
                    raise ValueError(
                        "Feedback ID conflict"
                    )

                return copy.deepcopy(
                    existing
                )

            self._results[
                feedback.feedback_id
            ] = result

            self._inputs[
                feedback.feedback_id
            ] = feedback

            self._audit.append(
                SentimentAuditEvent(
                    event_id=str(
                        uuid.uuid4()
                    ),
                    tenant_id=self.tenant_id,
                    analysis_id=(
                        result.analysis_id
                    ),
                    actor_id=actor.user_id,
                    action=(
                        "sentiment_analyzed"
                    ),
                    timestamp=utc_now(),
                    details={
                        "label": (
                            result.label.value
                        ),
                        "priority": (
                            result.priority.value
                        ),
                    },
                )
            )

            if priority in {
                SentimentPriority.HIGH,
                SentimentPriority.CRITICAL,
            }:
                event = SentimentOutboxEvent(
                    event_id=str(
                        uuid.uuid4()
                    ),
                    tenant_id=self.tenant_id,
                    event_type=(
                        "sentiment.review_required"
                    ),
                    source_id=(
                        result.analysis_id
                    ),
                    payload={
                        "feedback_id": (
                            feedback.feedback_id
                        ),
                        "product_id": (
                            feedback.product_id
                        ),
                        "priority": (
                            priority.value
                        ),
                        "aspects": list(
                            aspects
                        ),
                    },
                    created_at=utc_now(),
                )

                self._outbox[
                    event.event_id
                ] = event

            return copy.deepcopy(
                result
            )

    def analyze_batch(
        self,
        actor: SentimentActor,
        feedbacks: Iterable[
            SentimentInput
        ],
    ) -> list[SentimentResult]:
        return [
            self.analyze(
                actor,
                feedback,
            )
            for feedback in feedbacks
        ]

    def get_result(
        self,
        actor: SentimentActor,
        feedback_id: str,
    ) -> SentimentResult:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        with self._lock:
            result = self._results.get(
                feedback_id
            )

            if result is None:
                raise KeyError(
                    "Sentiment result not found"
                )

            return copy.deepcopy(
                result
            )

    def list_results(
        self,
        actor: SentimentActor,
        product_id: str | None = None,
        label: SentimentLabel | None = None,
    ) -> list[SentimentResult]:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        with self._lock:
            return [
                copy.deepcopy(
                    result
                )
                for result in (
                    self._results.values()
                )
                if (
                    (
                        product_id is None
                        or result.product_id
                        == product_id
                    )
                    and (
                        label is None
                        or result.label
                        == label
                    )
                )
            ]

    def analytics(
        self,
        actor: SentimentActor,
        product_id: str | None = None,
    ) -> dict:
        results = self.list_results(
            actor,
            product_id=product_id,
        )

        labels = Counter(
            result.label.value
            for result in results
        )

        priorities = Counter(
            result.priority.value
            for result in results
        )

        aspects = Counter(
            aspect
            for result in results
            for aspect in (
                result.aspects
            )
        )

        total = len(
            results
        )

        average_score = (
            sum(
                result.sentiment_score
                for result in results
            ) / total
            if total
            else 0.0
        )

        return {
            "tenant_id": self.tenant_id,
            "product_id": product_id,
            "total_feedback": total,
            "positive": labels[
                "positive"
            ],
            "neutral": labels[
                "neutral"
            ],
            "negative": labels[
                "negative"
            ],
            "positive_pct": round(
                labels["positive"]
                / total * 100,
                2,
            ) if total else 0.0,
            "negative_pct": round(
                labels["negative"]
                / total * 100,
                2,
            ) if total else 0.0,
            "average_sentiment_score": round(
                average_score,
                3,
            ),
            "priority_counts": dict(
                priorities
            ),
            "aspect_counts": dict(
                aspects
            ),
        }

    def pending_events(
        self,
        actor: SentimentActor,
    ) -> list[SentimentOutboxEvent]:
        self._authorize(
            actor,
            self.ANALYST_ROLES,
        )

        with self._lock:
            return [
                copy.deepcopy(
                    event
                )
                for event in (
                    self._outbox.values()
                )
                if not event.delivered
            ]

    def mark_event_delivered(
        self,
        actor: SentimentActor,
        event_id: str,
    ) -> None:
        self._authorize(
            actor,
            self.ANALYST_ROLES,
        )

        with self._lock:
            event = self._outbox.get(
                event_id
            )

            if event is None:
                raise KeyError(
                    "Event not found"
                )

            event.delivered = True

    def export_json(
        self,
        actor: SentimentActor,
        output_path: str | Path,
    ) -> Path:
        self._authorize(
            actor,
            self.ANALYST_ROLES,
        )

        results = self.list_results(
            actor
        )

        output = Path(
            output_path
        )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            json.dumps(
                [
                    asdict(result)
                    for result in results
                ],
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        return output


if __name__ == "__main__":
    service = RetailSentimentService(
        tenant_id="demo"
    )

    analyst = SentimentActor(
        user_id="analyst-001",
        tenant_id="demo",
        roles=frozenset({
            "sentiment_analyst",
        }),
    )

    feedbacks = [
        SentimentInput(
            feedback_id="F001",
            tenant_id="demo",
            customer_id="C001",
            product_id="SKU001",
            text=(
                "Excellent product quality "
                "and fast delivery."
            ),
            source=(
                FeedbackSource.PRODUCT_REVIEW
            ),
            rating=5,
        ),
        SentimentInput(
            feedback_id="F002",
            tenant_id="demo",
            customer_id="C002",
            product_id="SKU001",
            text=(
                "The product was damaged "
                "and delivery was late."
            ),
            source=(
                FeedbackSource.CUSTOMER_COMPLAINT
            ),
            rating=1,
        ),
        SentimentInput(
            feedback_id="F003",
            tenant_id="demo",
            customer_id="C003",
            product_id="SKU001",
            text=(
                "Package received today."
            ),
            source=(
                FeedbackSource.DELIVERY
            ),
            rating=3,
        ),
    ]

    for feedback in feedbacks:
        result = service.analyze(
            analyst,
            feedback,
        )

        print(
            feedback.feedback_id,
            result.label.value,
            result.priority.value,
        )

    print(
        json.dumps(
            service.analytics(
                analyst,
                product_id="SKU001",
            ),
            indent=2,
        )
    )
