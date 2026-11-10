from __future__ import annotations

"""Planned module: customer feedback. Implementation pending."""

"""
backend/models/customer_feedback.py

Autonomous Retail Supply Chain AI 5.0
Customer Feedback Database Model

Features:
- Product and service feedback
- Customer ratings and reviews
- Delivery and logistics feedback
- AI sentiment analysis
- Feedback category classification
- Complaint and escalation tracking
- Human review workflows
- AI-generated recommendations
- Multi-tenant isolation
- Soft deletion
- Optimistic concurrency control
- UTC audit timestamps

Requirements:
    SQLAlchemy >= 2.0

Uses:
    backend.models.base.Base
"""


import enum
import uuid

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SQLEnum,
    Float,
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
        length=50,
    )


# ============================================================
# ENUMS
# ============================================================

class FeedbackType(str, enum.Enum):
    PRODUCT_REVIEW = "product_review"
    SERVICE_REVIEW = "service_review"
    DELIVERY_REVIEW = "delivery_review"
    WAREHOUSE_FEEDBACK = "warehouse_feedback"
    ORDER_FEEDBACK = "order_feedback"
    COMPLAINT = "complaint"
    SUGGESTION = "suggestion"
    FEATURE_REQUEST = "feature_request"
    GENERAL = "general"


class FeedbackStatus(str, enum.Enum):
    NEW = "new"
    UNDER_REVIEW = "under_review"
    IN_PROGRESS = "in_progress"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CLOSED = "closed"
    REJECTED = "rejected"


class FeedbackPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class SentimentLabel(str, enum.Enum):
    VERY_NEGATIVE = "very_negative"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    POSITIVE = "positive"
    VERY_POSITIVE = "very_positive"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class FeedbackSource(str, enum.Enum):
    WEBSITE = "website"
    MOBILE_APP = "mobile_app"
    EMAIL = "email"
    SMS = "sms"
    CHATBOT = "chatbot"
    CUSTOMER_SUPPORT = "customer_support"
    MARKETPLACE = "marketplace"
    SOCIAL_MEDIA = "social_media"
    API = "api"
    OTHER = "other"


class FeedbackCategory(str, enum.Enum):
    PRODUCT_QUALITY = "product_quality"
    PRODUCT_AVAILABILITY = "product_availability"
    PRICING = "pricing"
    DELIVERY_DELAY = "delivery_delay"
    DAMAGED_PRODUCT = "damaged_product"
    WRONG_PRODUCT = "wrong_product"
    CUSTOMER_SERVICE = "customer_service"
    REFUND = "refund"
    RETURN = "return"
    PAYMENT = "payment"
    USER_EXPERIENCE = "user_experience"
    GENERAL = "general"


# ============================================================
# CUSTOMER FEEDBACK MODEL
# ============================================================

class CustomerFeedback(Base):
    __tablename__ = "customer_feedback"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "feedback_code",
            name="uq_customer_feedback_org_code",
        ),
        CheckConstraint(
            "rating IS NULL OR "
            "(rating >= 1 AND rating <= 5)",
            name="customer_feedback_rating_range",
        ),
        CheckConstraint(
            "sentiment_score IS NULL OR "
            "(sentiment_score >= -1 "
            "AND sentiment_score <= 1)",
            name="customer_feedback_sentiment_range",
        ),
        CheckConstraint(
            "sentiment_confidence IS NULL OR "
            "(sentiment_confidence >= 0 "
            "AND sentiment_confidence <= 1)",
            name="customer_feedback_confidence_range",
        ),
        CheckConstraint(
            "escalation_level >= 0",
            name="customer_feedback_escalation_level",
        ),
        Index(
            "ix_feedback_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_feedback_org_product",
            "organization_id",
            "product_id",
        ),
        Index(
            "ix_feedback_org_customer",
            "organization_id",
            "customer_id",
        ),
        Index(
            "ix_feedback_org_created",
            "organization_id",
            "created_at",
        ),
        Index(
            "ix_feedback_org_sentiment",
            "organization_id",
            "sentiment_label",
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

    feedback_code: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default=lambda: (
            f"FB-{uuid.uuid4().hex[:16].upper()}"
        ),
    )

    # --------------------------------------------------------
    # CUSTOMER AND BUSINESS REFERENCES
    # --------------------------------------------------------

    customer_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )

    product_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )

    order_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )

    delivery_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    warehouse_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    supplier_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # FEEDBACK CONTENT
    # --------------------------------------------------------

    title: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    feedback_type: Mapped[FeedbackType] = mapped_column(
        enum_column(
            FeedbackType,
            "customer_feedback_type",
        ),
        default=FeedbackType.GENERAL,
        nullable=False,
    )

    category: Mapped[FeedbackCategory] = mapped_column(
        enum_column(
            FeedbackCategory,
            "customer_feedback_category",
        ),
        default=FeedbackCategory.GENERAL,
        nullable=False,
    )

    source: Mapped[FeedbackSource] = mapped_column(
        enum_column(
            FeedbackSource,
            "customer_feedback_source",
        ),
        default=FeedbackSource.WEBSITE,
        nullable=False,
    )

    rating: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    is_verified_purchase: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # --------------------------------------------------------
    # FEEDBACK WORKFLOW
    # --------------------------------------------------------

    status: Mapped[FeedbackStatus] = mapped_column(
        enum_column(
            FeedbackStatus,
            "customer_feedback_status",
        ),
        default=FeedbackStatus.NEW,
        nullable=False,
    )

    priority: Mapped[FeedbackPriority] = mapped_column(
        enum_column(
            FeedbackPriority,
            "customer_feedback_priority",
        ),
        default=FeedbackPriority.NORMAL,
        nullable=False,
    )

    assigned_to: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    assigned_team: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    # --------------------------------------------------------
    # AI SENTIMENT ANALYSIS
    # --------------------------------------------------------

    sentiment_label: Mapped[SentimentLabel] = (
        mapped_column(
            enum_column(
                SentimentLabel,
                "customer_feedback_sentiment",
            ),
            default=SentimentLabel.UNKNOWN,
            nullable=False,
        )
    )

    sentiment_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    sentiment_confidence: Mapped[float | None] = (
        mapped_column(
            Float,
            nullable=True,
        )
    )

    sentiment_model: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    sentiment_model_version: Mapped[str | None] = (
        mapped_column(
            String(100),
            nullable=True,
        )
    )

    sentiment_analyzed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # AI INSIGHTS
    # --------------------------------------------------------

    ai_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    ai_recommended_action: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    ai_tags: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    analysis_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    requires_human_review: Mapped[bool] = (
        mapped_column(
            Boolean,
            default=False,
            nullable=False,
        )
    )

    human_reviewed_by: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    human_reviewed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # ESCALATION
    # --------------------------------------------------------

    escalation_level: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    escalated_to: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    escalation_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # RESOLUTION
    # --------------------------------------------------------

    resolution_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    resolved_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    customer_response: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    responded_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # ATTACHMENTS AND EXTRA DATA
    # --------------------------------------------------------

    attachments: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    extra_data: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # AUDIT AND OBSERVABILITY
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # SOFT DELETE
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # OPTIMISTIC LOCKING
    # --------------------------------------------------------

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
    def is_resolved(self) -> bool:
        return self.status in {
            FeedbackStatus.RESOLVED,
            FeedbackStatus.CLOSED,
        }

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
    def is_critical(self) -> bool:
        return (
            self.priority == FeedbackPriority.URGENT
            or self.sentiment_label
            == SentimentLabel.VERY_NEGATIVE
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _ensure_not_deleted(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Customer feedback has been deleted"
            )

    def _touch(self) -> None:
        self.updated_at = utc_now()

    # ========================================================
    # ASSIGNMENT
    # ========================================================

    def assign(
        self,
        user_id: str,
        team: str | None = None,
    ) -> None:
        self._ensure_not_deleted()

        if not user_id:
            raise ValueError(
                "Assigned user ID is required"
            )

        if self.status in {
            FeedbackStatus.CLOSED,
            FeedbackStatus.REJECTED,
        }:
            raise ValueError(
                "Cannot assign closed or rejected feedback"
            )

        self.assigned_to = user_id
        self.assigned_team = team

        if self.status == FeedbackStatus.NEW:
            self.status = FeedbackStatus.UNDER_REVIEW

        self._touch()

    # ========================================================
    # AI SENTIMENT UPDATE
    # ========================================================

    def update_sentiment(
        self,
        *,
        label: SentimentLabel,
        score: float,
        confidence: float,
        model_name: str,
        model_version: str | None = None,
        summary: str | None = None,
        recommended_action: str | None = None,
    ) -> None:
        self._ensure_not_deleted()

        if not -1 <= score <= 1:
            raise ValueError(
                "Sentiment score must be between -1 and 1"
            )

        if not 0 <= confidence <= 1:
            raise ValueError(
                "Confidence must be between 0 and 1"
            )

        self.sentiment_label = label
        self.sentiment_score = score
        self.sentiment_confidence = confidence
        self.sentiment_model = model_name
        self.sentiment_model_version = model_version
        self.sentiment_analyzed_at = utc_now()
        self.ai_summary = summary
        self.ai_recommended_action = recommended_action

        if label == SentimentLabel.VERY_NEGATIVE:
            self.requires_human_review = True

        self._touch()

    # ========================================================
    # HUMAN REVIEW
    # ========================================================

    def mark_human_reviewed(
        self,
        reviewer_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if not reviewer_id:
            raise ValueError(
                "Reviewer ID is required"
            )

        self.human_reviewed_by = reviewer_id
        self.human_reviewed_at = utc_now()
        self.requires_human_review = False

        if self.status == FeedbackStatus.NEW:
            self.status = FeedbackStatus.UNDER_REVIEW

        self._touch()

    # ========================================================
    # ESCALATION
    # ========================================================

    def escalate(
        self,
        *,
        user_id: str,
        reason: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status in {
            FeedbackStatus.RESOLVED,
            FeedbackStatus.CLOSED,
            FeedbackStatus.REJECTED,
        }:
            raise ValueError(
                "Cannot escalate terminal feedback"
            )

        if not user_id:
            raise ValueError(
                "Escalation recipient is required"
            )

        if not reason.strip():
            raise ValueError(
                "Escalation reason is required"
            )

        self.escalation_level += 1
        self.escalated_to = user_id
        self.escalated_at = utc_now()
        self.escalation_reason = reason
        self.status = FeedbackStatus.ESCALATED
        self._touch()

    # ========================================================
    # RESOLUTION
    # ========================================================

    def resolve(
        self,
        *,
        user_id: str,
        resolution_note: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status in {
            FeedbackStatus.RESOLVED,
            FeedbackStatus.CLOSED,
            FeedbackStatus.REJECTED,
        }:
            raise ValueError(
                "Feedback is already terminal"
            )

        if not user_id:
            raise ValueError(
                "Resolving user is required"
            )

        if not resolution_note.strip():
            raise ValueError(
                "Resolution note is required"
            )

        self.status = FeedbackStatus.RESOLVED
        self.resolved_by = user_id
        self.resolved_at = utc_now()
        self.resolution_note = resolution_note
        self._touch()

    # ========================================================
    # CUSTOMER RESPONSE
    # ========================================================

    def respond(
        self,
        *,
        user_id: str,
        response: str,
    ) -> None:
        self._ensure_not_deleted()

        if not user_id:
            raise ValueError(
                "Responding user is required"
            )

        if not response.strip():
            raise ValueError(
                "Response cannot be empty"
            )

        self.customer_response = response
        self.responded_by = user_id
        self.responded_at = utc_now()
        self._touch()

    # ========================================================
    # CLOSE FEEDBACK
    # ========================================================

    def close(self) -> None:
        self._ensure_not_deleted()

        if self.status != FeedbackStatus.RESOLVED:
            raise ValueError(
                "Only resolved feedback can be closed"
            )

        self.status = FeedbackStatus.CLOSED
        self._touch()

    # ========================================================
    # SOFT DELETE
    # ========================================================

    def soft_delete(
        self,
        user_id: str,
    ) -> None:
        if self.is_deleted:
            raise ValueError(
                "Feedback already deleted"
            )

        if not user_id:
            raise ValueError(
                "Deleting user is required"
            )

        self.is_deleted = True
        self.deleted_by = user_id
        self.deleted_at = utc_now()
        self._touch()

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(self) -> dict[str, Any]:

        def dt(
            value: datetime | None,
        ) -> str | None:
            return value.isoformat() if value else None

        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "feedback_code": self.feedback_code,
            "customer_id": self.customer_id,
            "product_id": self.product_id,
            "order_id": self.order_id,
            "delivery_id": self.delivery_id,
            "warehouse_id": self.warehouse_id,
            "supplier_id": self.supplier_id,
            "title": self.title,
            "message": self.message,
            "feedback_type": self.feedback_type.value,
            "category": self.category.value,
            "source": self.source.value,
            "rating": self.rating,
            "is_verified_purchase": (
                self.is_verified_purchase
            ),
            "status": self.status.value,
            "priority": self.priority.value,
            "assigned_to": self.assigned_to,
            "assigned_team": self.assigned_team,
            "sentiment_label": self.sentiment_label.value,
            "sentiment_score": self.sentiment_score,
            "sentiment_confidence": (
                self.sentiment_confidence
            ),
            "sentiment_model": self.sentiment_model,
            "sentiment_model_version": (
                self.sentiment_model_version
            ),
            "sentiment_analyzed_at": dt(
                self.sentiment_analyzed_at
            ),
            "ai_summary": self.ai_summary,
            "ai_recommended_action": (
                self.ai_recommended_action
            ),
            "ai_tags": self.ai_tags,
            "requires_human_review": (
                self.requires_human_review
            ),
            "human_reviewed_by": (
                self.human_reviewed_by
            ),
            "human_reviewed_at": dt(
                self.human_reviewed_at
            ),
            "escalation_level": self.escalation_level,
            "escalated_to": self.escalated_to,
            "escalated_at": dt(self.escalated_at),
            "escalation_reason": (
                self.escalation_reason
            ),
            "resolution_note": self.resolution_note,
            "resolved_by": self.resolved_by,
            "resolved_at": dt(self.resolved_at),
            "customer_response": self.customer_response,
            "responded_by": self.responded_by,
            "responded_at": dt(self.responded_at),
            "attachments": self.attachments,
            "extra_data": self.extra_data,
            "trace_id": self.trace_id,
            "correlation_id": self.correlation_id,
            "is_deleted": self.is_deleted,
            "deleted_at": dt(self.deleted_at),
            "deleted_by": self.deleted_by,
            "version": self.version,
            "created_at": dt(self.created_at),
            "updated_at": dt(self.updated_at),
        }

    def __repr__(self) -> str:
        return (
            f"<CustomerFeedback("
            f"id={self.id}, "
            f"status={self.status.value}, "
            f"sentiment={self.sentiment_label.value}"
            f")>"
        )
