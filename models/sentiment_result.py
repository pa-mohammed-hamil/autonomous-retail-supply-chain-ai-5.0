from __future__ import annotations

"""Planned module: sentiment result. Implementation pending."""
"""
backend/models/sentiment_result.py

Enterprise AI Sentiment Analysis Result Model.

Features:
- Multi-tenant sentiment analysis
- Customer reviews, feedback and complaints
- Product, delivery, supplier and employee sentiment
- Positive, negative, neutral and mixed classification
- Emotion detection
- Aspect-based sentiment analysis
- Multilingual NLP
- Confidence and sentiment scoring
- AI model and agent traceability
- Human review and correction
- Automated escalation recommendations
- PII-safe source references
- Immutable published analysis
- Audit history and soft deletion
- Optimistic concurrency control

IMPORTANT:
This ORM stores analysis results, not raw customer messages.
Retrieve source content through authorized services.

AI analysis does not automatically create incidents,
send notifications or modify customer records.
Those actions belong to permissioned service workflows.
"""


import enum
import uuid

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SQLEnum,
    Index,
    Integer,
    JSON,
    Numeric,
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

ZERO = Decimal("0.0000")
ONE = Decimal("1.0000")
QUANTUM = Decimal("0.0001")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_result_number() -> str:
    return f"SENT-{uuid.uuid4().hex[:16].upper()}"


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


def required_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def decimal_number(
    value: Decimal | str | int | float,
    field: str,
    *,
    minimum: Decimal = ZERO,
    maximum: Decimal = ONE,
) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")

    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(
            f"{field} must be numeric"
        ) from None

    if not result.is_finite():
        raise ValueError(f"{field} must be finite")

    if not minimum <= result <= maximum:
        raise ValueError(
            f"{field} must be between {minimum} and {maximum}"
        )

    if result != result.quantize(QUANTUM):
        raise ValueError(
            f"{field} supports at most four decimal places"
        )

    return result


def enum_value(value):
    return value.value if isinstance(value, enum.Enum) else value


def iso(value: datetime | None):
    return value.isoformat() if value else None


def decimal_string(value):
    return str(value) if value is not None else None


def validate_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Timezone-aware datetime required")
    return value.astimezone(timezone.utc)


# ============================================================
# ENUMS
# ============================================================

class SentimentLabel(str, enum.Enum):
    VERY_POSITIVE = "very_positive"
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    VERY_NEGATIVE = "very_negative"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class SentimentResultStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    ANALYZED = "analyzed"
    PENDING_REVIEW = "pending_review"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    PUBLISHED = "published"
    REJECTED = "rejected"
    FAILED = "failed"
    ARCHIVED = "archived"


class SentimentSourceType(str, enum.Enum):
    CUSTOMER_FEEDBACK = "customer_feedback"
    PRODUCT_REVIEW = "product_review"
    DELIVERY_FEEDBACK = "delivery_feedback"
    SUPPLIER_FEEDBACK = "supplier_feedback"
    EMPLOYEE_FEEDBACK = "employee_feedback"
    SUPPORT_TICKET = "support_ticket"
    CHAT_MESSAGE = "chat_message"
    EMAIL = "email"
    SURVEY = "survey"
    SOCIAL_MEDIA = "social_media"
    RETURN_REQUEST = "return_request"
    OTHER = "other"


class SentimentEmotion(str, enum.Enum):
    JOY = "joy"
    SATISFACTION = "satisfaction"
    TRUST = "trust"
    EXCITEMENT = "excitement"
    GRATITUDE = "gratitude"
    ANGER = "anger"
    FRUSTRATION = "frustration"
    SADNESS = "sadness"
    FEAR = "fear"
    DISAPPOINTMENT = "disappointment"
    CONFUSION = "confusion"
    SURPRISE = "surprise"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class SentimentPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"


class SentimentRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class SentimentAnalysisMethod(str, enum.Enum):
    TRANSFORMER = "transformer"
    LLM = "llm"
    HYBRID = "hybrid"
    RULE_BASED = "rule_based"
    LEXICON = "lexicon"
    CLASSICAL_ML = "classical_ml"
    HUMAN = "human"


class SentimentReviewStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class SentimentEscalationStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    RECOMMENDED = "recommended"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    TRIGGERED = "triggered"
    DISMISSED = "dismissed"


# ============================================================
# SENTIMENT RESULT
# ============================================================

class SentimentResult(Base):
    __tablename__ = "sentiment_results"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "result_number",
            name="uq_sentiment_org_number",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_sentiment_org_idempotency",
        ),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_sentiment_org_id",
        ),
        CheckConstraint(
            "sentiment_score IS NULL OR "
            "(sentiment_score >= -1 AND sentiment_score <= 1)",
            name="sentiment_score_range",
        ),
        CheckConstraint(
            "confidence IS NULL OR "
            "(confidence >= 0 AND confidence <= 1)",
            name="sentiment_confidence_range",
        ),
        CheckConstraint(
            "subjectivity_score IS NULL OR "
            "(subjectivity_score >= 0 AND subjectivity_score <= 1)",
            name="sentiment_subjectivity_range",
        ),
        CheckConstraint(
            "urgency_score IS NULL OR "
            "(urgency_score >= 0 AND urgency_score <= 1)",
            name="sentiment_urgency_range",
        ),
        CheckConstraint(
            "risk_score IS NULL OR "
            "(risk_score >= 0 AND risk_score <= 1)",
            name="sentiment_risk_score_range",
        ),
        CheckConstraint(
            "version >= 1",
            name="sentiment_version_positive",
        ),
        Index(
            "ix_sentiment_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_sentiment_org_source",
            "organization_id",
            "source_type",
            "source_id",
        ),
        Index(
            "ix_sentiment_org_product",
            "organization_id",
            "product_id",
        ),
        Index(
            "ix_sentiment_org_label",
            "organization_id",
            "sentiment_label",
        ),
        Index(
            "ix_sentiment_org_created",
            "organization_id",
            "created_at",
        ),
    )

    # --------------------------------------------------------
    # IDENTITY
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

    result_number: Mapped[str] = mapped_column(
        String(60),
        default=generate_result_number,
        nullable=False,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # --------------------------------------------------------
    # ANALYSIS STATUS
    # --------------------------------------------------------

    status: Mapped[SentimentResultStatus] = mapped_column(
        enum_column(
            SentimentResultStatus,
            "sentiment_result_status",
        ),
        default=SentimentResultStatus.PENDING,
        nullable=False,
    )

    source_type: Mapped[SentimentSourceType] = mapped_column(
        enum_column(
            SentimentSourceType,
            "sentiment_source_type",
        ),
        nullable=False,
    )

    source_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    analysis_method: Mapped[
        SentimentAnalysisMethod
    ] = mapped_column(
        enum_column(
            SentimentAnalysisMethod,
            "sentiment_analysis_method",
        ),
        default=SentimentAnalysisMethod.TRANSFORMER,
        nullable=False,
    )

    priority: Mapped[SentimentPriority] = mapped_column(
        enum_column(
            SentimentPriority,
            "sentiment_priority",
        ),
        default=SentimentPriority.NORMAL,
        nullable=False,
    )

    # --------------------------------------------------------
    # BUSINESS REFERENCES
    # --------------------------------------------------------

    customer_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    product_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    supplier_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    warehouse_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    sale_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    delivery_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    return_request_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    customer_feedback_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    incident_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # SOURCE TEXT METADATA
    # --------------------------------------------------------

    language_code: Mapped[str] = mapped_column(
        String(20),
        default="en",
        nullable=False,
    )

    detected_language: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    source_content_hash: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    source_content_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    text_length: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    token_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # --------------------------------------------------------
    # SENTIMENT CLASSIFICATION
    # --------------------------------------------------------

    sentiment_label: Mapped[SentimentLabel] = mapped_column(
        enum_column(
            SentimentLabel,
            "sentiment_result_label",
        ),
        default=SentimentLabel.UNKNOWN,
        nullable=False,
    )

    sentiment_score: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    subjectivity_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    dominant_emotion: Mapped[
        SentimentEmotion
    ] = mapped_column(
        enum_column(
            SentimentEmotion,
            "sentiment_dominant_emotion",
        ),
        default=SentimentEmotion.UNKNOWN,
        nullable=False,
    )

    emotion_scores: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    label_probabilities: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # ASPECT-BASED SENTIMENT
    # --------------------------------------------------------

    aspect_sentiments: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    keywords: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    topics: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # --------------------------------------------------------
    # AI INTERPRETATION
    # --------------------------------------------------------

    ai_model_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    ai_model_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    ai_agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    ai_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    ai_explanation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    ai_recommendations: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    analysis_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    analyzed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # URGENCY / RISK
    # --------------------------------------------------------

    urgency_score: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    risk_score: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    risk_level: Mapped[SentimentRiskLevel] = mapped_column(
        enum_column(
            SentimentRiskLevel,
            "sentiment_risk_level",
        ),
        default=SentimentRiskLevel.UNKNOWN,
        nullable=False,
    )

    requires_attention: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    requires_human_review: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # --------------------------------------------------------
    # HUMAN REVIEW
    # --------------------------------------------------------

    review_status: Mapped[
        SentimentReviewStatus
    ] = mapped_column(
        enum_column(
            SentimentReviewStatus,
            "sentiment_review_status",
        ),
        default=SentimentReviewStatus.NOT_REQUIRED,
        nullable=False,
    )

    reviewed_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    review_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    original_sentiment_label: Mapped[
        SentimentLabel | None
    ] = mapped_column(
        enum_column(
            SentimentLabel,
            "sentiment_original_label",
        ),
        nullable=True,
    )

    corrected_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    corrected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # ESCALATION
    # --------------------------------------------------------

    escalation_status: Mapped[
        SentimentEscalationStatus
    ] = mapped_column(
        enum_column(
            SentimentEscalationStatus,
            "sentiment_escalation_status",
        ),
        default=SentimentEscalationStatus.NOT_REQUIRED,
        nullable=False,
    )

    escalation_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    escalation_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    escalation_approved_by: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # PUBLICATION / FAILURE
    # --------------------------------------------------------

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    published_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    failure_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # AUDIT
    # --------------------------------------------------------

    result_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    result_history: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

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
    def is_negative(self) -> bool:
        return self.sentiment_label in {
            SentimentLabel.NEGATIVE,
            SentimentLabel.VERY_NEGATIVE,
        }

    @property
    def is_positive(self) -> bool:
        return self.sentiment_label in {
            SentimentLabel.POSITIVE,
            SentimentLabel.VERY_POSITIVE,
        }

    @property
    def is_final(self) -> bool:
        return self.status in {
            SentimentResultStatus.PUBLISHED,
            SentimentResultStatus.REJECTED,
            SentimentResultStatus.ARCHIVED,
        }

    @property
    def is_reviewed(self) -> bool:
        return self.review_status in {
            SentimentReviewStatus.APPROVED,
            SentimentReviewStatus.CORRECTED,
        }

    @property
    def needs_escalation(self) -> bool:
        return (
            self.requires_attention
            or self.risk_level in {
                SentimentRiskLevel.HIGH,
                SentimentRiskLevel.CRITICAL,
            }
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_active(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Sentiment result has been deleted"
            )

    def _require_status(
        self,
        *allowed: SentimentResultStatus,
    ) -> None:
        self._ensure_active()

        if self.status not in allowed:
            raise ValueError(
                f"Invalid sentiment result state: "
                f"{enum_value(self.status)}"
            )

    def _record_event(
        self,
        event: str,
        *,
        actor_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        history = list(self.result_history or [])

        history.append({
            "event_id": generate_uuid(),
            "event": event,
            "actor_id": actor_id,
            "timestamp": utc_now().isoformat(),
            "details": details or {},
        })

        self.result_history = history
        self._touch()

    # ========================================================
    # START ANALYSIS
    # ========================================================

    def start_analysis(
        self,
        *,
        actor_id: str,
        model_id: str,
        model_version: str | None = None,
        agent_run_id: str | None = None,
    ) -> None:
        self._require_status(
            SentimentResultStatus.PENDING
        )

        self.ai_model_id = required_text(
            model_id, "Model ID"
        )
        self.ai_model_version = model_version
        self.ai_agent_run_id = agent_run_id
        self.status = SentimentResultStatus.PROCESSING

        self._record_event(
            "sentiment_analysis_started",
            actor_id=actor_id,
            details={"model_id": model_id},
        )

    # ========================================================
    # RECORD SENTIMENT ANALYSIS
    # ========================================================

    def record_analysis(
        self,
        *,
        sentiment_label: SentimentLabel,
        sentiment_score: Decimal | str | float,
        confidence: Decimal | str | float,
        dominant_emotion: SentimentEmotion,
        summary: str,
        explanation: str,
        actor_id: str,
        subjectivity_score: Decimal | str | float = ZERO,
        label_probabilities: dict[str, Any] | None = None,
        emotion_scores: dict[str, Any] | None = None,
        keywords: list[str] | None = None,
        topics: list[str] | None = None,
    ) -> None:
        self._require_status(
            SentimentResultStatus.PROCESSING
        )

        if sentiment_label == SentimentLabel.UNKNOWN:
            raise ValueError(
                "Completed analysis requires a sentiment label"
            )

        score = decimal_number(
            sentiment_score,
            "sentiment_score",
            minimum=Decimal("-1"),
            maximum=ONE,
        )

        confidence_value = decimal_number(
            confidence,
            "confidence",
        )

        subjectivity = decimal_number(
            subjectivity_score,
            "subjectivity_score",
        )

        if label_probabilities is not None:
            for label, probability in label_probabilities.items():
                decimal_number(
                    probability,
                    f"label_probabilities[{label}]",
                )

        if emotion_scores is not None:
            for emotion, probability in emotion_scores.items():
                decimal_number(
                    probability,
                    f"emotion_scores[{emotion}]",
                )

        self.sentiment_label = sentiment_label
        self.sentiment_score = score
        self.confidence = confidence_value
        self.subjectivity_score = subjectivity
        self.dominant_emotion = dominant_emotion

        self.ai_summary = required_text(
            summary, "Summary"
        )
        self.ai_explanation = required_text(
            explanation, "Explanation"
        )

        self.label_probabilities = dict(
            label_probabilities or {}
        )
        self.emotion_scores = dict(
            emotion_scores or {}
        )

        self.keywords = [
            required_text(word, "Keyword")
            for word in (keywords or [])
        ]

        self.topics = [
            required_text(topic, "Topic")
            for topic in (topics or [])
        ]

        self.analyzed_at = utc_now()
        self.status = SentimentResultStatus.ANALYZED

        self._record_event(
            "sentiment_analysis_completed",
            actor_id=actor_id,
            details={
                "sentiment_label": sentiment_label.value,
                "sentiment_score": str(score),
                "confidence": str(confidence_value),
            },
        )

    # ========================================================
    # ASPECT-BASED SENTIMENT
    # ========================================================

    def add_aspect_sentiment(
        self,
        *,
        aspect: str,
        sentiment_label: SentimentLabel,
        sentiment_score: Decimal | str | float,
        confidence: Decimal | str | float,
        actor_id: str,
        explanation: str | None = None,
    ) -> None:
        self._require_status(
            SentimentResultStatus.ANALYZED
        )

        aspect_name = required_text(
            aspect, "Aspect"
        )

        if any(
            item["aspect"].casefold()
            == aspect_name.casefold()
            for item in (self.aspect_sentiments or [])
        ):
            raise ValueError(
                "Aspect already exists"
            )

        score = decimal_number(
            sentiment_score,
            "sentiment_score",
            minimum=Decimal("-1"),
            maximum=ONE,
        )
        confidence_value = decimal_number(
            confidence, "confidence"
        )

        aspects = list(self.aspect_sentiments or [])

        aspects.append({
            "id": generate_uuid(),
            "aspect": aspect_name,
            "sentiment_label": sentiment_label.value,
            "sentiment_score": str(score),
            "confidence": str(confidence_value),
            "explanation": explanation,
            "created_at": utc_now().isoformat(),
        })

        self.aspect_sentiments = aspects

        self._record_event(
            "sentiment_aspect_added",
            actor_id=actor_id,
            details={"aspect": aspect_name},
        )

    # ========================================================
    # UPDATE RISK
    # ========================================================

    def update_risk(
        self,
        *,
        risk_score: Decimal | str | float,
        urgency_score: Decimal | str | float,
        risk_level: SentimentRiskLevel,
        requires_attention: bool,
        actor_id: str,
    ) -> None:
        self._require_status(
            SentimentResultStatus.ANALYZED,
            SentimentResultStatus.PENDING_REVIEW,
        )

        self.risk_score = decimal_number(
            risk_score, "risk_score"
        )
        self.urgency_score = decimal_number(
            urgency_score, "urgency_score"
        )
        self.risk_level = risk_level
        self.requires_attention = bool(
            requires_attention
        )

        if risk_level in {
            SentimentRiskLevel.HIGH,
            SentimentRiskLevel.CRITICAL,
        }:
            self.requires_human_review = True
            self.review_status = SentimentReviewStatus.PENDING
            self.status = SentimentResultStatus.PENDING_REVIEW

        self._record_event(
            "sentiment_risk_updated",
            actor_id=actor_id,
            details={
                "risk_level": risk_level.value,
            },
        )

    # ========================================================
    # ADD RECOMMENDATION
    # ========================================================

    def add_recommendation(
        self,
        *,
        title: str,
        description: str,
        actor_id: str,
        priority: SentimentPriority = SentimentPriority.NORMAL,
    ) -> None:
        self._require_status(
            SentimentResultStatus.ANALYZED,
            SentimentResultStatus.PENDING_REVIEW,
            SentimentResultStatus.REVIEWED,
        )

        recommendations = list(
            self.ai_recommendations or []
        )

        recommendations.append({
            "recommendation_id": generate_uuid(),
            "title": required_text(title, "Title"),
            "description": required_text(
                description, "Description"
            ),
            "priority": priority.value,
            "status": "proposed",
            "created_at": utc_now().isoformat(),
        })

        self.ai_recommendations = recommendations

        self._record_event(
            "sentiment_recommendation_added",
            actor_id=actor_id,
            details={"title": title},
        )

    # ========================================================
    # REQUEST HUMAN REVIEW
    # ========================================================

    def request_review(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            SentimentResultStatus.ANALYZED
        )

        self.requires_human_review = True
        self.review_status = SentimentReviewStatus.PENDING
        self.status = SentimentResultStatus.PENDING_REVIEW

        self._record_event(
            "sentiment_review_requested",
            actor_id=actor_id,
        )

    # ========================================================
    # APPROVE HUMAN REVIEW
    # ========================================================

    def approve_review(
        self,
        *,
        reviewer_id: str,
        notes: str,
    ) -> None:
        self._require_status(
            SentimentResultStatus.PENDING_REVIEW
        )

        self.review_status = SentimentReviewStatus.APPROVED
        self.reviewed_by = required_text(
            reviewer_id, "Reviewer ID"
        )
        self.reviewed_at = utc_now()
        self.review_notes = required_text(
            notes, "Review notes"
        )
        self.status = SentimentResultStatus.REVIEWED

        self._record_event(
            "sentiment_review_approved",
            actor_id=reviewer_id,
        )

    # ========================================================
    # CORRECT SENTIMENT
    # ========================================================

    def correct_sentiment(
        self,
        *,
        reviewer_id: str,
        corrected_label: SentimentLabel,
        corrected_score: Decimal | str | float,
        notes: str,
    ) -> None:
        self._require_status(
            SentimentResultStatus.PENDING_REVIEW
        )

        if corrected_label == SentimentLabel.UNKNOWN:
            raise ValueError(
                "Corrected label cannot be unknown"
            )

        corrected_score_value = decimal_number(
            corrected_score,
            "corrected_score",
            minimum=Decimal("-1"),
            maximum=ONE,
        )

        self.original_sentiment_label = (
            self.sentiment_label
        )
        self.sentiment_label = corrected_label
        self.sentiment_score = corrected_score_value

        self.corrected_by = required_text(
            reviewer_id, "Reviewer ID"
        )
        self.corrected_at = utc_now()
        self.reviewed_by = reviewer_id
        self.reviewed_at = utc_now()
        self.review_notes = required_text(
            notes, "Correction notes"
        )

        self.review_status = SentimentReviewStatus.CORRECTED
        self.status = SentimentResultStatus.REVIEWED

        self._record_event(
            "sentiment_corrected",
            actor_id=reviewer_id,
            details={
                "original_label": enum_value(
                    self.original_sentiment_label
                ),
                "corrected_label": corrected_label.value,
                "corrected_score": str(
                    corrected_score_value
                ),
            },
        )

    # ========================================================
    # APPROVE RESULT
    # ========================================================

    def approve(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            SentimentResultStatus.ANALYZED,
            SentimentResultStatus.REVIEWED,
        )

        if (
            self.requires_human_review
            and not self.is_reviewed
        ):
            raise ValueError(
                "Human review must be completed"
            )

        self.status = SentimentResultStatus.APPROVED

        self._record_event(
            "sentiment_result_approved",
            actor_id=actor_id,
        )

    # ========================================================
    # PUBLISH
    # ========================================================

    def publish(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            SentimentResultStatus.APPROVED
        )

        if self.sentiment_label == SentimentLabel.UNKNOWN:
            raise ValueError(
                "Unknown sentiment cannot be published"
            )

        self.status = SentimentResultStatus.PUBLISHED
        self.published_at = utc_now()
        self.published_by = required_text(
            actor_id, "Actor ID"
        )

        self._record_event(
            "sentiment_result_published",
            actor_id=actor_id,
        )

    # ========================================================
    # ESCALATION RECOMMENDATION
    # ========================================================

    def recommend_escalation(
        self,
        *,
        reason: str,
        actor_id: str,
    ) -> None:
        self._require_status(
            SentimentResultStatus.ANALYZED,
            SentimentResultStatus.PENDING_REVIEW,
            SentimentResultStatus.REVIEWED,
            SentimentResultStatus.APPROVED,
            SentimentResultStatus.PUBLISHED,
        )

        if not self.needs_escalation:
            raise ValueError(
                "Escalation criteria not met"
            )

        if self.escalation_status not in {
            SentimentEscalationStatus.NOT_REQUIRED,
            SentimentEscalationStatus.DISMISSED,
        }:
            raise ValueError(
                "Escalation already exists"
            )

        self.escalation_status = (
            SentimentEscalationStatus.RECOMMENDED
        )
        self.escalation_reason = required_text(
            reason, "Escalation reason"
        )

        self._record_event(
            "sentiment_escalation_recommended",
            actor_id=actor_id,
        )

    # ========================================================
    # REQUEST ESCALATION APPROVAL
    # ========================================================

    def request_escalation_approval(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_active()

        if self.escalation_status != (
            SentimentEscalationStatus.RECOMMENDED
        ):
            raise ValueError(
                "Escalation is not recommended"
            )

        self.escalation_status = (
            SentimentEscalationStatus.PENDING_APPROVAL
        )

        self._record_event(
            "sentiment_escalation_approval_requested",
            actor_id=actor_id,
        )

    # ========================================================
    # APPROVE ESCALATION
    # ========================================================

    def approve_escalation(
        self,
        *,
        approver_id: str,
    ) -> None:
        self._ensure_active()

        if self.escalation_status != (
            SentimentEscalationStatus.PENDING_APPROVAL
        ):
            raise ValueError(
                "Escalation approval is not pending"
            )

        # Approval service must verify reviewer permissions.

        self.escalation_status = (
            SentimentEscalationStatus.APPROVED
        )
        self.escalation_approved_by = required_text(
            approver_id, "Approver ID"
        )

        self._record_event(
            "sentiment_escalation_approved",
            actor_id=approver_id,
        )

    # ========================================================
    # RECORD ESCALATION
    # ========================================================

    def record_escalation(
        self,
        *,
        escalation_id: str,
        actor_id: str,
    ) -> None:
        self._ensure_active()

        if self.escalation_status != (
            SentimentEscalationStatus.APPROVED
        ):
            raise ValueError(
                "Escalation is not approved"
            )

        # Escalation service creates the actual escalation
        # and returns its verified ID.

        self.escalation_id = required_text(
            escalation_id, "Escalation ID"
        )
        self.escalation_status = (
            SentimentEscalationStatus.TRIGGERED
        )
        self.escalated_at = utc_now()

        self._record_event(
            "sentiment_escalation_recorded",
            actor_id=actor_id,
            details={"escalation_id": escalation_id},
        )

    # ========================================================
    # MARK FAILED
    # ========================================================

    def mark_failed(
        self,
        *,
        failure_code: str,
        reason: str,
        actor_id: str,
    ) -> None:
        self._require_status(
            SentimentResultStatus.PENDING,
            SentimentResultStatus.PROCESSING,
        )

        self.failure_code = required_text(
            failure_code, "Failure code"
        )
        self.failure_reason = required_text(
            reason, "Failure reason"
        )
        self.status = SentimentResultStatus.FAILED

        self._record_event(
            "sentiment_analysis_failed",
            actor_id=actor_id,
            details={"failure_code": failure_code},
        )

    # ========================================================
    # ARCHIVE
    # ========================================================

    def archive(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            SentimentResultStatus.PUBLISHED,
            SentimentResultStatus.REJECTED,
            SentimentResultStatus.FAILED,
        )

        self.status = SentimentResultStatus.ARCHIVED
        self.archived_at = utc_now()

        self._record_event(
            "sentiment_result_archived",
            actor_id=actor_id,
        )

    # ========================================================
    # SOFT DELETE
    # ========================================================

    def soft_delete(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._require_status(
            SentimentResultStatus.PENDING,
            SentimentResultStatus.FAILED,
            SentimentResultStatus.ARCHIVED,
        )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = required_text(
            actor_id, "Actor ID"
        )

        self._record_event(
            "sentiment_result_soft_deleted",
            actor_id=actor_id,
        )

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(
        self,
        *,
        include_internal: bool = False,
        include_history: bool = False,
    ) -> dict[str, Any]:
        result = {
            "id": self.id,
            "organization_id": self.organization_id,
            "result_number": self.result_number,
            "status": enum_value(self.status),
            "source_type": enum_value(self.source_type),
            "source_id": self.source_id,
            "analysis_method": enum_value(
                self.analysis_method
            ),
            "priority": enum_value(self.priority),
            "customer_id": self.customer_id,
            "product_id": self.product_id,
            "supplier_id": self.supplier_id,
            "warehouse_id": self.warehouse_id,
            "sale_id": self.sale_id,
            "delivery_id": self.delivery_id,
            "return_request_id": self.return_request_id,
            "customer_feedback_id": self.customer_feedback_id,
            "incident_id": self.incident_id,
            "language_code": self.language_code,
            "detected_language": self.detected_language,
            "sentiment_label": enum_value(
                self.sentiment_label
            ),
            "sentiment_score": decimal_string(
                self.sentiment_score
            ),
            "confidence": decimal_string(
                self.confidence
            ),
            "subjectivity_score": decimal_string(
                self.subjectivity_score
            ),
            "dominant_emotion": enum_value(
                self.dominant_emotion
            ),
            "emotion_scores": self.emotion_scores,
            "label_probabilities": self.label_probabilities,
            "aspect_sentiments": self.aspect_sentiments,
            "keywords": self.keywords,
            "topics": self.topics,
            "ai_summary": self.ai_summary,
            "ai_recommendations": self.ai_recommendations,
            "urgency_score": decimal_string(
                self.urgency_score
            ),
            "risk_score": decimal_string(
                self.risk_score
            ),
            "risk_level": enum_value(self.risk_level),
            "requires_attention": self.requires_attention,
            "requires_human_review": (
                self.requires_human_review
            ),
            "review_status": enum_value(
                self.review_status
            ),
            "escalation_status": enum_value(
                self.escalation_status
            ),
            "escalation_id": self.escalation_id,
            "analyzed_at": iso(self.analyzed_at),
            "reviewed_at": iso(self.reviewed_at),
            "published_at": iso(self.published_at),
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "is_negative": self.is_negative,
            "is_positive": self.is_positive,
            "needs_escalation": self.needs_escalation,
            "is_deleted": self.is_deleted,
            "version": self.version,
        }

        if include_internal:
            result.update({
                "ai_model_id": self.ai_model_id,
                "ai_model_version": self.ai_model_version,
                "ai_agent_run_id": self.ai_agent_run_id,
                "ai_explanation": self.ai_explanation,
                "analysis_metadata": self.analysis_metadata,
                "reviewed_by": self.reviewed_by,
                "review_notes": self.review_notes,
                "original_sentiment_label": enum_value(
                    self.original_sentiment_label
                ),
                "corrected_by": self.corrected_by,
                "corrected_at": iso(self.corrected_at),
                "escalation_reason": self.escalation_reason,
                "escalation_approved_by": (
                    self.escalation_approved_by
                ),
                "result_metadata": self.result_metadata,
                "trace_id": self.trace_id,
                "correlation_id": self.correlation_id,
                "failure_code": self.failure_code,
                "failure_reason": self.failure_reason,
            })

        if include_history:
            result["result_history"] = (
                self.result_history
            )

        return result

    def __repr__(self) -> str:
        return (
            f"<SentimentResult("
            f"id={self.id}, "
            f"result_number={self.result_number}, "
            f"sentiment={enum_value(self.sentiment_label)}, "
            f"status={enum_value(self.status)}"
            f")>"
        )