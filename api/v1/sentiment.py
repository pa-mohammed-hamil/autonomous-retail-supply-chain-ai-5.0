from __future__ import annotations

"""Planned module: sentiment. Implementation pending."""

"""
backend/sentiment.py

Autonomous Retail Supply Chain AI 5.0
Customer & Supplier Sentiment Intelligence API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Positive, neutral, negative sentiment
    - Rule-based sentiment scoring
    - Aspect-based sentiment analysis
    - Customer complaint detection
    - Supplier feedback classification
    - Delivery experience analysis
    - Product quality issue detection
    - Batch sentiment analysis
    - Escalation recommendations
    - Tenant and warehouse authorization
    - Idempotent feedback creation
    - Optimistic concurrency
    - Sentiment history and analytics

Production integration:
    backend/services/sentiment_service.py
    backend/feedback.py
    backend/product_quality.py
    backend/employee_alerts.py
    backend/analytics.py
    ai/training/train_sentiment.py

IMPORTANT:
    The default classifier is a deterministic,
    English-language keyword demonstration.

    It is NOT a trained transformer model.
    Scores are heuristic, not calibrated
    probabilities.
"""


import asyncio
import hashlib
import json
import re
import secrets

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from backend.permissions import (
    CurrentPrincipal,
    Permission,
    Principal,
    ResourceContext,
    permission_engine,
)


API_PREFIX = "/api/v1/sentiment"

MAX_FEEDBACK_PER_TENANT = 100000
MAX_BATCH_SIZE = 100
MAX_TEXT_LENGTH = 10000
MAX_LIST_LIMIT = 200
MAX_IDEMPOTENCY_KEYS = 150000


# ============================================================
# ENUMS
# ============================================================

class SentimentLabel(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class FeedbackSource(str, Enum):
    CUSTOMER_REVIEW = "customer_review"
    PRODUCT_REVIEW = "product_review"
    SUPPLIER_FEEDBACK = "supplier_feedback"
    DELIVERY_FEEDBACK = "delivery_feedback"
    EMPLOYEE_FEEDBACK = "employee_feedback"
    SUPPORT_TICKET = "support_ticket"
    SURVEY = "survey"
    OTHER = "other"


class SentimentAspect(str, Enum):
    PRODUCT_QUALITY = "product_quality"
    DELIVERY = "delivery"
    PRICING = "pricing"
    CUSTOMER_SERVICE = "customer_service"
    SUPPLIER_RELIABILITY = "supplier_reliability"
    PACKAGING = "packaging"
    AVAILABILITY = "availability"
    GENERAL = "general"


class ComplaintCategory(str, Enum):
    DAMAGED_PRODUCT = "damaged_product"
    LATE_DELIVERY = "late_delivery"
    WRONG_PRODUCT = "wrong_product"
    POOR_QUALITY = "poor_quality"
    HIGH_PRICE = "high_price"
    OUT_OF_STOCK = "out_of_stock"
    POOR_SUPPORT = "poor_support"
    SUPPLIER_DELAY = "supplier_delay"
    OTHER = "other"


class EscalationPriority(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FeedbackStatus(str, Enum):
    NEW = "new"
    REVIEWED = "reviewed"
    RESOLVED = "resolved"


# ============================================================
# REQUEST SCHEMAS
# ============================================================

class SentimentAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(
        min_length=3,
        max_length=MAX_TEXT_LENGTH,
    )

    source: FeedbackSource = (
        FeedbackSource.CUSTOMER_REVIEW
    )

    warehouse_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    product_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    supplier_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    order_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )


class SentimentBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[SentimentAnalyzeRequest] = Field(
        min_length=1,
        max_length=MAX_BATCH_SIZE,
    )


class FeedbackCreate(SentimentAnalyzeRequest):
    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )


class FeedbackVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class FeedbackStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    status: FeedbackStatus

    notes: str = Field(
        min_length=3,
        max_length=1000,
    )


# ============================================================
# RESPONSE SCHEMAS
# ============================================================

class AspectSentimentResponse(BaseModel):
    aspect: SentimentAspect
    sentiment: SentimentLabel
    score: float
    matched_terms: list[str]


class SentimentAnalysisResponse(BaseModel):
    sentiment: SentimentLabel
    sentiment_score: float
    confidence: float

    positive_matches: list[str]
    negative_matches: list[str]

    aspects: list[AspectSentimentResponse]
    complaint_categories: list[ComplaintCategory]

    escalation_priority: EscalationPriority
    requires_human_review: bool

    model_name: str
    analyzed_at: datetime


class SentimentBatchResponse(BaseModel):
    results: list[SentimentAnalysisResponse]

    total: int
    positive: int
    neutral: int
    negative: int


class FeedbackResponse(BaseModel):
    feedback_id: str
    warehouse_id: str | None

    source: FeedbackSource

    product_id: str | None
    supplier_id: str | None
    order_id: str | None

    sentiment: SentimentLabel
    sentiment_score: float
    escalation_priority: EscalationPriority

    status: FeedbackStatus
    version: int

    created_at: datetime
    updated_at: datetime


class FeedbackDetailResponse(FeedbackResponse):
    text: str
    analysis: SentimentAnalysisResponse
    review_notes: list[str]


class SentimentAnalyticsResponse(BaseModel):
    total_feedback: int

    positive: int
    neutral: int
    negative: int

    positive_percentage: float
    negative_percentage: float

    average_sentiment_score: float

    high_priority_feedback: int
    critical_feedback: int
    unresolved_feedback: int

    complaint_distribution: dict[str, int]
    source_distribution: dict[str, int]


# ============================================================
# INTERNAL RECORD
# ============================================================

@dataclass
class FeedbackRecord:
    feedback_id: str
    tenant_id: str
    warehouse_id: str | None

    text: str
    source: FeedbackSource

    product_id: str | None
    supplier_id: str | None
    order_id: str | None

    analysis: SentimentAnalysisResponse

    created_by: str

    status: FeedbackStatus = FeedbackStatus.NEW

    review_notes: list[str] = field(
        default_factory=list
    )

    version: int = 1

    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ============================================================
# SECURITY
# ============================================================

def require_sentiment_access(
    principal: Principal,
    warehouse_id: str | None,
    *,
    write: bool,
) -> None:

    # Replace with dedicated SENTIMENT_READ/WRITE
    # permissions in production.

    permission = (
        Permission.INCIDENT_WRITE
        if write
        else Permission.ANALYTICS_READ
    )

    if warehouse_id is None:

        if principal.allowed_warehouse_ids is not None:
            raise HTTPException(
                status_code=403,
                detail="Tenant-wide access required",
            )

    elif (
        principal.allowed_warehouse_ids is not None
        and warehouse_id not in principal.allowed_warehouse_ids
    ):
        raise HTTPException(
            status_code=403,
            detail="Warehouse access denied",
        )

    decision = permission_engine.evaluate(
        principal,
        permission,
        ResourceContext(
            tenant_id=principal.tenant_id,
            warehouse_id=warehouse_id,
        ),
    )

    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail="Sentiment access denied",
        )


# ============================================================
# HEURISTIC SENTIMENT ENGINE
# ============================================================

TOKEN_PATTERN = re.compile(r"[a-zA-Z]+")

POSITIVE_TERMS = {
    "excellent": 3,
    "amazing": 3,
    "fantastic": 3,
    "perfect": 3,
    "great": 2,
    "good": 1,
    "reliable": 2,
    "fast": 1,
    "helpful": 2,
    "satisfied": 2,
    "happy": 2,
    "smooth": 1,
    "quality": 1,
    "recommended": 2,
    "love": 2,
    "efficient": 2,
    "affordable": 2,
}

NEGATIVE_TERMS = {
    "terrible": 3,
    "awful": 3,
    "horrible": 3,
    "worst": 3,
    "bad": 2,
    "poor": 2,
    "damaged": 3,
    "broken": 3,
    "defective": 3,
    "delayed": 2,
    "late": 2,
    "expensive": 2,
    "slow": 1,
    "unreliable": 2,
    "disappointed": 2,
    "missing": 2,
    "wrong": 2,
    "complaint": 1,
    "refund": 1,
    "unsafe": 3,
}

NEGATIONS = {
    "not",
    "never",
    "no",
    "hardly",
}

ASPECT_KEYWORDS = {
    SentimentAspect.PRODUCT_QUALITY: {
        "quality", "damaged", "broken",
        "defective", "durable", "product",
    },
    SentimentAspect.DELIVERY: {
        "delivery", "shipping", "delayed",
        "late", "courier", "arrived",
    },
    SentimentAspect.PRICING: {
        "price", "expensive", "affordable",
        "cost", "cheap", "pricing",
    },
    SentimentAspect.CUSTOMER_SERVICE: {
        "support", "service", "agent",
        "helpful", "response", "refund",
    },
    SentimentAspect.SUPPLIER_RELIABILITY: {
        "supplier", "vendor", "reliable",
        "unreliable", "procurement",
    },
    SentimentAspect.PACKAGING: {
        "packaging", "package", "box",
        "packing", "sealed",
    },
    SentimentAspect.AVAILABILITY: {
        "stock", "available", "missing",
        "inventory", "shortage",
    },
}

COMPLAINT_KEYWORDS = {
    ComplaintCategory.DAMAGED_PRODUCT: {
        "damaged", "broken", "defective",
    },
    ComplaintCategory.LATE_DELIVERY: {
        "late", "delayed",
    },
    ComplaintCategory.WRONG_PRODUCT: {
        "wrong", "incorrect",
    },
    ComplaintCategory.POOR_QUALITY: {
        "poor", "quality", "faulty",
    },
    ComplaintCategory.HIGH_PRICE: {
        "expensive", "overpriced",
    },
    ComplaintCategory.OUT_OF_STOCK: {
        "stockout", "unavailable", "shortage",
    },
    ComplaintCategory.POOR_SUPPORT: {
        "support", "unhelpful",
    },
    ComplaintCategory.SUPPLIER_DELAY: {
        "supplier", "vendor",
    },
}

CRITICAL_TERMS = {
    "unsafe",
    "dangerous",
    "injury",
    "fire",
    "fraud",
    "contaminated",
}


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.casefold())


class HeuristicSentimentEngine:

    MODEL_NAME = "heuristic-sentiment-demo-v1"

    @staticmethod
    def classify(
        score: float,
    ) -> SentimentLabel:

        if score > 0.15:
            return SentimentLabel.POSITIVE

        if score < -0.15:
            return SentimentLabel.NEGATIVE

        return SentimentLabel.NEUTRAL

    def score_tokens(
        self,
        tokens: list[str],
    ) -> tuple[float, list[str], list[str]]:

        positive = []
        negative = []

        total_score = 0
        total_weight = 0

        for index, token in enumerate(tokens):

            positive_weight = POSITIVE_TERMS.get(
                token, 0
            )

            negative_weight = NEGATIVE_TERMS.get(
                token, 0
            )

            if not positive_weight and not negative_weight:
                continue

            value = (
                positive_weight - negative_weight
            )

            window = tokens[
                max(0, index - 3):index
            ]

            if any(
                word in NEGATIONS
                for word in window
            ):
                value = -value

            total_score += value
            total_weight += abs(value)

            if value > 0:
                positive.append(token)

            elif value < 0:
                negative.append(token)

        if total_weight == 0:
            return 0.0, [], []

        score = total_score / total_weight

        return (
            round(max(-1.0, min(1.0, score)), 4),
            sorted(set(positive)),
            sorted(set(negative)),
        )

    def detect_aspects(
        self,
        tokens: list[str],
    ) -> list[AspectSentimentResponse]:

        results = []
        token_set = set(tokens)

        for aspect, keywords in ASPECT_KEYWORDS.items():

            matches = sorted(
                token_set & keywords
            )

            if not matches:
                continue

            # Aspect score is estimated using a
            # small context window around aspect terms.
            context_tokens = []

            for index, token in enumerate(tokens):

                if token not in keywords:
                    continue

                context_tokens.extend(
                    tokens[
                        max(0, index - 5):
                        min(len(tokens), index + 6)
                    ]
                )

            score, _, _ = self.score_tokens(
                context_tokens
            )

            results.append(
                AspectSentimentResponse(
                    aspect=aspect,
                    sentiment=self.classify(score),
                    score=score,
                    matched_terms=matches,
                )
            )

        if not results:

            score, _, _ = self.score_tokens(tokens)

            results.append(
                AspectSentimentResponse(
                    aspect=SentimentAspect.GENERAL,
                    sentiment=self.classify(score),
                    score=score,
                    matched_terms=[],
                )
            )

        return results

    @staticmethod
    def detect_complaints(
        tokens: list[str],
        sentiment: SentimentLabel,
    ) -> list[ComplaintCategory]:

        if sentiment != SentimentLabel.NEGATIVE:
            return []

        token_set = set(tokens)

        return [
            category
            for category, keywords
            in COMPLAINT_KEYWORDS.items()
            if token_set & keywords
        ]

    @staticmethod
    def escalation(
        tokens: list[str],
        sentiment: SentimentLabel,
        score: float,
        complaints: list[ComplaintCategory],
    ) -> EscalationPriority:

        token_set = set(tokens)

        if token_set & CRITICAL_TERMS:
            return EscalationPriority.CRITICAL

        if sentiment == SentimentLabel.NEGATIVE:

            if score <= -0.75:
                return EscalationPriority.HIGH

            if complaints:
                return EscalationPriority.MEDIUM

            return EscalationPriority.LOW

        return EscalationPriority.NONE

    def analyze(
        self,
        text: str,
    ) -> SentimentAnalysisResponse:

        tokens = tokenize(text)

        score, positive, negative = (
            self.score_tokens(tokens)
        )

        sentiment = self.classify(score)

        aspects = self.detect_aspects(tokens)

        complaints = self.detect_complaints(
            tokens,
            sentiment,
        )

        priority = self.escalation(
            tokens,
            sentiment,
            score,
            complaints,
        )

        matched_count = (
            len(positive) + len(negative)
        )

        # Heuristic evidence strength.
        # NOT a calibrated ML confidence.
        confidence = (
            min(0.95, 0.35 + matched_count * 0.12)
            if matched_count
            else 0.0
        )

        return SentimentAnalysisResponse(
            sentiment=sentiment,
            sentiment_score=score,
            confidence=round(confidence, 4),
            positive_matches=positive,
            negative_matches=negative,
            aspects=aspects,
            complaint_categories=complaints,
            escalation_priority=priority,
            requires_human_review=(
                priority in {
                    EscalationPriority.HIGH,
                    EscalationPriority.CRITICAL,
                }
            ),
            model_name=self.MODEL_NAME,
            analyzed_at=datetime.now(timezone.utc),
        )


# ============================================================
# SERIALIZATION HELPERS
# ============================================================

def to_feedback_response(
    record: FeedbackRecord,
) -> FeedbackResponse:

    return FeedbackResponse(
        feedback_id=record.feedback_id,
        warehouse_id=record.warehouse_id,
        source=record.source,
        product_id=record.product_id,
        supplier_id=record.supplier_id,
        order_id=record.order_id,
        sentiment=record.analysis.sentiment,
        sentiment_score=record.analysis.sentiment_score,
        escalation_priority=(
            record.analysis.escalation_priority
        ),
        status=record.status,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def to_feedback_detail(
    record: FeedbackRecord,
) -> FeedbackDetailResponse:

    return FeedbackDetailResponse(
        **to_feedback_response(record).model_dump(),
        text=record.text,
        analysis=record.analysis,
        review_notes=list(record.review_notes),
    )


# ============================================================
# SENTIMENT STORE
# ============================================================

class SentimentStore:

    def __init__(self):

        self._feedback: dict[
            str,
            FeedbackRecord,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    @staticmethod
    def _fingerprint(
        payload: FeedbackCreate,
    ) -> str:

        data = payload.model_dump(
            mode="json",
            exclude={"source_request_id"},
        )

        canonical = json.dumps(
            data,
            sort_keys=True,
            separators=(",", ":"),
        )

        return hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()

    def _get(
        self,
        principal: Principal,
        feedback_id: str,
        *,
        write: bool,
    ) -> FeedbackRecord:

        record = self._feedback.get(
            feedback_id
        )

        if (
            record is None
            or record.tenant_id != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Feedback not found",
            )

        require_sentiment_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    async def create(
        self,
        principal: Principal,
        payload: FeedbackCreate,
        engine: HeuristicSentimentEngine,
    ) -> FeedbackDetailResponse:

        require_sentiment_access(
            principal,
            payload.warehouse_id,
            write=True,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        fingerprint = self._fingerprint(payload)

        async with self._lock:

            previous = self._idempotency.get(key)

            if previous:

                old_hash, feedback_id = previous

                if old_hash != fingerprint:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return to_feedback_detail(
                    self._get(
                        principal,
                        feedback_id,
                        write=False,
                    )
                )

            tenant_count = sum(
                record.tenant_id == principal.tenant_id
                for record in self._feedback.values()
            )

            if (
                tenant_count >= MAX_FEEDBACK_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Feedback capacity reached",
                )

            analysis = engine.analyze(
                payload.text
            )

            record = FeedbackRecord(
                feedback_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                text=payload.text,
                source=payload.source,
                product_id=payload.product_id,
                supplier_id=payload.supplier_id,
                order_id=payload.order_id,
                analysis=analysis,
                created_by=principal.principal_id,
            )

            self._feedback[
                record.feedback_id
            ] = record

            self._idempotency[key] = (
                fingerprint,
                record.feedback_id,
            )

            return to_feedback_detail(record)

    async def get(
        self,
        principal: Principal,
        feedback_id: str,
    ) -> FeedbackDetailResponse:

        async with self._lock:

            return to_feedback_detail(
                self._get(
                    principal,
                    feedback_id,
                    write=False,
                )
            )

    async def list_feedback(
        self,
        principal: Principal,
        warehouse_id: str | None,
        sentiment: SentimentLabel | None,
        status: FeedbackStatus | None,
        limit: int,
    ) -> list[FeedbackResponse]:

        if warehouse_id is not None:
            require_sentiment_access(
                principal,
                warehouse_id,
                write=False,
            )

        async with self._lock:

            records = [
                record
                for record in self._feedback.values()
                if (
                    record.tenant_id == principal.tenant_id
                    and (
                        warehouse_id is None
                        or record.warehouse_id == warehouse_id
                    )
                    and (
                        sentiment is None
                        or record.analysis.sentiment == sentiment
                    )
                    and (
                        status is None
                        or record.status == status
                    )
                )
            ]

            records.sort(
                key=lambda item: item.created_at,
                reverse=True,
            )

            results = []

            for record in records:

                try:
                    require_sentiment_access(
                        principal,
                        record.warehouse_id,
                        write=False,
                    )
                except HTTPException:
                    continue

                results.append(
                    to_feedback_response(record)
                )

                if len(results) >= limit:
                    break

            return results

    async def update_status(
        self,
        principal: Principal,
        feedback_id: str,
        payload: FeedbackStatusUpdate,
    ) -> FeedbackDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                feedback_id,
                write=True,
            )

            if record.version != payload.expected_version:
                raise HTTPException(
                    status_code=409,
                    detail="Feedback version conflict",
                )

            allowed = {
                FeedbackStatus.NEW: {
                    FeedbackStatus.REVIEWED,
                },
                FeedbackStatus.REVIEWED: {
                    FeedbackStatus.RESOLVED,
                },
                FeedbackStatus.RESOLVED: set(),
            }

            if payload.status not in allowed[record.status]:
                raise HTTPException(
                    status_code=409,
                    detail="Invalid feedback status transition",
                )

            record.status = payload.status

            record.review_notes.append(
                f"{principal.principal_id}: {payload.notes}"
            )

            record.version += 1
            record.updated_at = datetime.now(timezone.utc)

            return to_feedback_detail(record)

    async def analytics(
        self,
        principal: Principal,
        warehouse_id: str | None,
    ) -> SentimentAnalyticsResponse:

        require_sentiment_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._feedback.values()
                if (
                    record.tenant_id == principal.tenant_id
                    and (
                        warehouse_id is None
                        or record.warehouse_id == warehouse_id
                    )
                )
            ]

            if warehouse_id is None:
                records = [
                    record
                    for record in records
                    if record.warehouse_id is None
                    or principal.allowed_warehouse_ids is None
                ]

            total = len(records)

            labels = Counter(
                record.analysis.sentiment
                for record in records
            )

            priorities = Counter(
                record.analysis.escalation_priority
                for record in records
            )

            complaints = Counter()

            sources = Counter()

            for record in records:

                sources[record.source.value] += 1

                for category in (
                    record.analysis.complaint_categories
                ):
                    complaints[category.value] += 1

            positive = labels[
                SentimentLabel.POSITIVE
            ]

            neutral = labels[
                SentimentLabel.NEUTRAL
            ]

            negative = labels[
                SentimentLabel.NEGATIVE
            ]

            average_score = (
                sum(
                    record.analysis.sentiment_score
                    for record in records
                ) / total
                if total
                else 0.0
            )

            return SentimentAnalyticsResponse(
                total_feedback=total,
                positive=positive,
                neutral=neutral,
                negative=negative,
                positive_percentage=round(
                    positive / total * 100, 2
                ) if total else 0.0,
                negative_percentage=round(
                    negative / total * 100, 2
                ) if total else 0.0,
                average_sentiment_score=round(
                    average_score, 4
                ),
                high_priority_feedback=priorities[
                    EscalationPriority.HIGH
                ],
                critical_feedback=priorities[
                    EscalationPriority.CRITICAL
                ],
                unresolved_feedback=sum(
                    record.status != FeedbackStatus.RESOLVED
                    for record in records
                ),
                complaint_distribution=dict(complaints),
                source_distribution=dict(sources),
            )


# ============================================================
# SERVICE
# ============================================================

class SentimentService:

    def __init__(
        self,
        store: SentimentStore,
        engine: HeuristicSentimentEngine,
    ):
        self.store = store
        self.engine = engine

    def analyze(
        self,
        payload: SentimentAnalyzeRequest,
    ) -> SentimentAnalysisResponse:

        return self.engine.analyze(
            payload.text
        )

    def batch_analyze(
        self,
        payload: SentimentBatchRequest,
    ) -> SentimentBatchResponse:

        results = [
            self.engine.analyze(item.text)
            for item in payload.items
        ]

        labels = Counter(
            item.sentiment
            for item in results
        )

        return SentimentBatchResponse(
            results=results,
            total=len(results),
            positive=labels[SentimentLabel.POSITIVE],
            neutral=labels[SentimentLabel.NEUTRAL],
            negative=labels[SentimentLabel.NEGATIVE],
        )


sentiment_store = SentimentStore()

sentiment_service = SentimentService(
    store=sentiment_store,
    engine=HeuristicSentimentEngine(),
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Sentiment Intelligence"],
)


@router.post(
    "/analyze",
    response_model=SentimentAnalysisResponse,
)
async def analyze_sentiment(
    payload: SentimentAnalyzeRequest,
    principal: CurrentPrincipal,
):
    require_sentiment_access(
        principal,
        payload.warehouse_id,
        write=False,
    )

    return sentiment_service.analyze(
        payload
    )


@router.post(
    "/batch",
    response_model=SentimentBatchResponse,
)
async def batch_sentiment_analysis(
    payload: SentimentBatchRequest,
    principal: CurrentPrincipal,
):
    for item in payload.items:
        require_sentiment_access(
            principal,
            item.warehouse_id,
            write=False,
        )

    return sentiment_service.batch_analyze(
        payload
    )


@router.post(
    "/feedback",
    response_model=FeedbackDetailResponse,
    status_code=201,
)
async def create_sentiment_feedback(
    payload: FeedbackCreate,
    principal: CurrentPrincipal,
):
    return await sentiment_store.create(
        principal,
        payload,
        sentiment_service.engine,
    )


@router.get(
    "/feedback",
    response_model=list[FeedbackResponse],
)
async def list_sentiment_feedback(
    principal: CurrentPrincipal,
    warehouse_id: str | None = None,
    sentiment: SentimentLabel | None = None,
    status: FeedbackStatus | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await sentiment_store.list_feedback(
        principal,
        warehouse_id,
        sentiment,
        status,
        limit,
    )


@router.get(
    "/analytics",
    response_model=SentimentAnalyticsResponse,
)
async def sentiment_analytics(
    principal: CurrentPrincipal,
    warehouse_id: str | None = None,
):
    return await sentiment_store.analytics(
        principal,
        warehouse_id,
    )


@router.get(
    "/feedback/{feedback_id}",
    response_model=FeedbackDetailResponse,
)
async def get_sentiment_feedback(
    feedback_id: str,
    principal: CurrentPrincipal,
):
    return await sentiment_store.get(
        principal,
        feedback_id,
    )


@router.patch(
    "/feedback/{feedback_id}/status",
    response_model=FeedbackDetailResponse,
)
async def update_sentiment_feedback_status(
    feedback_id: str,
    payload: FeedbackStatusUpdate,
    principal: CurrentPrincipal,
):
    return await sentiment_store.update_status(
        principal,
        feedback_id,
        payload,
    )


__all__ = [
    "SentimentLabel",
    "FeedbackSource",
    "SentimentAspect",
    "ComplaintCategory",
    "EscalationPriority",
    "FeedbackStatus",
    "SentimentAnalyzeRequest",
    "SentimentBatchRequest",
    "FeedbackCreate",
    "FeedbackVersionRequest",
    "FeedbackStatusUpdate",
    "AspectSentimentResponse",
    "SentimentAnalysisResponse",
    "SentimentBatchResponse",
    "FeedbackResponse",
    "FeedbackDetailResponse",
    "SentimentAnalyticsResponse",
    "HeuristicSentimentEngine",
    "SentimentStore",
    "SentimentService",
    "sentiment_store",
    "sentiment_service",
    "router",
]
