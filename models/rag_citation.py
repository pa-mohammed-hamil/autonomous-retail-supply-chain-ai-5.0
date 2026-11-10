from __future__ import annotations

"""Planned module: rag citation. Implementation pending."""

"""
backend/models/rag_citation.py

Autonomous Retail Supply Chain AI 5.0
Enterprise RAG Citation and Evidence Model

Features:
- Multi-tenant citation storage
- RAG query, response and document references
- Source provenance and document versioning
- Chunk, page, section and character references
- Citation markers and evidence text
- Hybrid retrieval and reranking metadata
- Faithfulness, relevance and confidence scores
- Citation verification workflow
- Evidence expiration and invalidation
- Access classification and redaction
- AI agent and model traceability
- Audit history and soft deletion
- Optimistic concurrency control

Security:
- Never trust retrieved text as instructions.
- Enforce document-level authorization in services.
- Verify evidence against immutable source versions.
- Avoid storing secrets or unnecessary personal data.
- Do not treat model confidence as proof of accuracy.
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
# HELPERS
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
        length=60,
    )


def require_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def score(
    value: Decimal | int | float | str,
    field: str,
) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")

    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(
            f"{field} must be numeric"
        ) from None

    if not result.is_finite() or not (
        Decimal("0") <= result <= Decimal("1")
    ):
        raise ValueError(
            f"{field} must be between 0 and 1"
        )

    if result != result.quantize(Decimal("0.0001")):
        raise ValueError(
            f"{field} supports at most 4 decimal places"
        )

    return result


def aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError(
            "Timezone-aware datetime required"
        )
    return value.astimezone(timezone.utc)


def enum_value(value: enum.Enum | None):
    return value.value if value is not None else None


def iso(value: datetime | None):
    return value.isoformat() if value else None


def decimal_string(value: Decimal | None):
    return str(value) if value is not None else None


# ============================================================
# ENUMS
# ============================================================

class CitationStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_VERIFICATION = "pending_verification"
    VERIFIED = "verified"
    REJECTED = "rejected"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"
    ARCHIVED = "archived"


class CitationSourceType(str, enum.Enum):
    PDF = "pdf"
    DOCUMENT = "document"
    SPREADSHEET = "spreadsheet"
    PRESENTATION = "presentation"
    TEXT = "text"
    HTML = "html"
    WEBPAGE = "webpage"
    DATABASE = "database"
    API = "api"
    KNOWLEDGE_BASE = "knowledge_base"
    EMAIL = "email"
    IMAGE_OCR = "image_ocr"
    AUDIO_TRANSCRIPT = "audio_transcript"
    VIDEO_TRANSCRIPT = "video_transcript"
    ERP = "erp"
    WMS = "wms"
    SUPPLIER_API = "supplier_api"
    MARKET_DATA = "market_data"
    OTHER = "other"


class CitationRetrievalMethod(str, enum.Enum):
    VECTOR = "vector"
    BM25 = "bm25"
    HYBRID = "hybrid"
    GRAPH_RAG = "graph_rag"
    KEYWORD = "keyword"
    SQL = "sql"
    API_LOOKUP = "api_lookup"
    MANUAL = "manual"
    OTHER = "other"


class CitationVerificationMethod(str, enum.Enum):
    EXACT_MATCH = "exact_match"
    SOURCE_SPAN = "source_span"
    SEMANTIC_ENTAILMENT = "semantic_entailment"
    HUMAN_REVIEW = "human_review"
    MULTI_SOURCE = "multi_source"
    AUTOMATED_EVALUATION = "automated_evaluation"


class CitationAccessLevel(str, enum.Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class CitationRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class CitationClaimType(str, enum.Enum):
    FACT = "fact"
    NUMERIC = "numeric"
    FORECAST = "forecast"
    POLICY = "policy"
    COMPLIANCE = "compliance"
    RECOMMENDATION = "recommendation"
    COMPARISON = "comparison"
    SUMMARY = "summary"
    OTHER = "other"


# ============================================================
# RAG CITATION MODEL
# ============================================================

class RAGCitation(Base):
    __tablename__ = "rag_citations"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "response_id",
            "citation_key",
            name="uq_rag_citation_response_key",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_rag_citation_idempotency",
        ),
        CheckConstraint(
            "citation_index >= 1",
            name="rag_citation_index_positive",
        ),
        CheckConstraint(
            "page_number IS NULL OR page_number >= 1",
            name="rag_citation_page_positive",
        ),
        CheckConstraint(
            "page_end IS NULL OR page_end >= 1",
            name="rag_citation_page_end_positive",
        ),
        CheckConstraint(
            "page_number IS NULL OR page_end IS NULL "
            "OR page_end >= page_number",
            name="rag_citation_page_order",
        ),
        CheckConstraint(
            "start_offset IS NULL OR start_offset >= 0",
            name="rag_citation_start_nonnegative",
        ),
        CheckConstraint(
            "end_offset IS NULL OR end_offset >= 0",
            name="rag_citation_end_nonnegative",
        ),
        CheckConstraint(
            "start_offset IS NULL OR end_offset IS NULL "
            "OR end_offset >= start_offset",
            name="rag_citation_offset_order",
        ),
        CheckConstraint(
            "retrieval_rank IS NULL OR retrieval_rank >= 1",
            name="rag_citation_rank_positive",
        ),
        CheckConstraint(
            "confidence_score IS NULL OR "
            "(confidence_score >= 0 "
            "AND confidence_score <= 1)",
            name="rag_citation_confidence_range",
        ),
        CheckConstraint(
            "relevance_score IS NULL OR "
            "(relevance_score >= 0 "
            "AND relevance_score <= 1)",
            name="rag_citation_relevance_range",
        ),
        CheckConstraint(
            "faithfulness_score IS NULL OR "
            "(faithfulness_score >= 0 "
            "AND faithfulness_score <= 1)",
            name="rag_citation_faithfulness_range",
        ),
        CheckConstraint(
            "version >= 1",
            name="rag_citation_version_positive",
        ),
        Index(
            "ix_rag_citation_org_response",
            "organization_id",
            "response_id",
        ),
        Index(
            "ix_rag_citation_org_document",
            "organization_id",
            "document_id",
        ),
        Index(
            "ix_rag_citation_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_rag_citation_org_query",
            "organization_id",
            "query_id",
        ),
        Index(
            "ix_rag_citation_org_chunk",
            "organization_id",
            "chunk_id",
        ),
        Index(
            "ix_rag_citation_org_created",
            "organization_id",
            "created_at",
        ),
    )

    # --------------------------------------------------------
    # IDENTITY / TENANCY
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

    idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # --------------------------------------------------------
    # RAG EXECUTION REFERENCES
    # --------------------------------------------------------

    query_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    response_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    conversation_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    message_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    rag_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    model_registry_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # CITATION IDENTITY
    # --------------------------------------------------------

    citation_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    citation_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    citation_label: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    citation_marker: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    status: Mapped[CitationStatus] = mapped_column(
        enum_column(
            CitationStatus,
            "rag_citation_status",
        ),
        default=CitationStatus.DRAFT,
        nullable=False,
    )

    claim_type: Mapped[CitationClaimType] = mapped_column(
        enum_column(
            CitationClaimType,
            "rag_citation_claim_type",
        ),
        default=CitationClaimType.FACT,
        nullable=False,
    )

    # --------------------------------------------------------
    # SOURCE DOCUMENT
    # --------------------------------------------------------

    document_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    document_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    source_type: Mapped[
        CitationSourceType
    ] = mapped_column(
        enum_column(
            CitationSourceType,
            "rag_citation_source_type",
        ),
        nullable=False,
    )

    source_title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    source_uri: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    source_external_id: Mapped[
        str | None
    ] = mapped_column(
        String(255),
        nullable=True,
    )

    source_author: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    source_published_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    source_last_modified_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    source_content_sha256: Mapped[
        str | None
    ] = mapped_column(
        String(64),
        nullable=True,
    )

    # --------------------------------------------------------
    # CHUNK / SOURCE LOCATION
    # --------------------------------------------------------

    chunk_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    chunk_index: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    page_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    page_end: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    section_title: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    heading_path: Mapped[
        list[str]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    start_offset: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    end_offset: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    location_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # CLAIM AND EVIDENCE
    # --------------------------------------------------------

    supported_claim: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    evidence_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    evidence_context: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    evidence_language: Mapped[str] = mapped_column(
        String(20),
        default="en",
        nullable=False,
    )

    evidence_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # RETRIEVAL / RERANKING
    # --------------------------------------------------------

    retrieval_method: Mapped[
        CitationRetrievalMethod
    ] = mapped_column(
        enum_column(
            CitationRetrievalMethod,
            "rag_citation_retrieval_method",
        ),
        default=CitationRetrievalMethod.HYBRID,
        nullable=False,
    )

    retrieval_rank: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    retrieval_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 6),
        nullable=True,
    )

    rerank_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(18, 6),
        nullable=True,
    )

    retriever_model_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    reranker_model_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    embedding_model: Mapped[
        str | None
    ] = mapped_column(
        String(255),
        nullable=True,
    )

    retrieval_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # EVALUATION SCORES
    # --------------------------------------------------------

    confidence_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    relevance_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    faithfulness_score: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    evaluation_result_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # VERIFICATION
    # --------------------------------------------------------

    verification_method: Mapped[
        CitationVerificationMethod | None
    ] = mapped_column(
        enum_column(
            CitationVerificationMethod,
            "rag_citation_verification_method",
        ),
        nullable=True,
    )

    verification_notes: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    verified_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    verified_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    rejected_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    rejected_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    rejection_reason: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # SECURITY / ACCESS
    # --------------------------------------------------------

    access_level: Mapped[
        CitationAccessLevel
    ] = mapped_column(
        enum_column(
            CitationAccessLevel,
            "rag_citation_access_level",
        ),
        default=CitationAccessLevel.INTERNAL,
        nullable=False,
    )

    risk_level: Mapped[
        CitationRiskLevel
    ] = mapped_column(
        enum_column(
            CitationRiskLevel,
            "rag_citation_risk_level",
        ),
        default=CitationRiskLevel.UNKNOWN,
        nullable=False,
    )

    contains_pii: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    is_redacted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    redaction_reason: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    access_policy_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # FRESHNESS / VALIDITY
    # --------------------------------------------------------

    valid_from: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    valid_until: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_source_checked_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    invalidated_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    invalidated_by: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    invalidation_reason: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # AUDIT / METADATA
    # --------------------------------------------------------

    citation_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    citation_history: Mapped[
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

    correlation_id: Mapped[
        str | None
    ] = mapped_column(
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

    deleted_at: Mapped[
        datetime | None
    ] = mapped_column(
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
    def is_verified(self) -> bool:
        return (
            self.status == CitationStatus.VERIFIED
            and not self.is_deleted
        )

    @property
    def is_expired(self) -> bool:
        return (
            self.valid_until is not None
            and utc_now() >= aware_datetime(
                self.valid_until
            )
        )

    @property
    def is_currently_valid(self) -> bool:
        if not self.is_verified or self.is_expired:
            return False

        if self.valid_from is not None:
            if utc_now() < aware_datetime(
                self.valid_from
            ):
                return False

        return True

    @property
    def is_sensitive(self) -> bool:
        return (
            self.contains_pii
            or self.access_level in {
                CitationAccessLevel.CONFIDENTIAL,
                CitationAccessLevel.RESTRICTED,
            }
        )

    @property
    def can_be_displayed(self) -> bool:
        # This only checks local citation state.
        # Services must separately authorize access
        # to the source document and evidence text.
        return (
            self.is_currently_valid
            and not self.is_redacted
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_not_deleted(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Citation has been deleted"
            )

    def _record_event(
        self,
        event: str,
        *,
        actor_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        history = list(self.citation_history or [])

        history.append({
            "event_id": generate_uuid(),
            "event": event,
            "actor_id": actor_id,
            "timestamp": utc_now().isoformat(),
            "details": details or {},
        })

        self.citation_history = history
        self._touch()

    # ========================================================
    # UPDATE EVIDENCE
    # ========================================================

    def update_evidence(
        self,
        *,
        claim: str,
        evidence: str,
        actor_id: str,
        page_number: int | None = None,
        section_title: str | None = None,
        start_offset: int | None = None,
        end_offset: int | None = None,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != CitationStatus.DRAFT:
            raise ValueError(
                "Only draft citations can be edited"
            )

        if page_number is not None and page_number < 1:
            raise ValueError(
                "Page number must be positive"
            )

        if start_offset is not None and start_offset < 0:
            raise ValueError(
                "Start offset must be nonnegative"
            )

        if end_offset is not None and end_offset < 0:
            raise ValueError(
                "End offset must be nonnegative"
            )

        if (
            start_offset is not None
            and end_offset is not None
            and end_offset < start_offset
        ):
            raise ValueError(
                "End offset precedes start offset"
            )

        self.supported_claim = require_text(
            claim,
            "Supported claim",
        )
        self.evidence_text = require_text(
            evidence,
            "Evidence text",
        )

        self.page_number = page_number
        self.section_title = section_title
        self.start_offset = start_offset
        self.end_offset = end_offset
        self.updated_by = actor_id

        self._record_event(
            "citation_evidence_updated",
            actor_id=actor_id,
        )

    # ========================================================
    # UPDATE RETRIEVAL METRICS
    # ========================================================

    def update_retrieval_metrics(
        self,
        *,
        retrieval_method: CitationRetrievalMethod,
        retrieval_rank: int | None = None,
        retrieval_score: Decimal | None = None,
        rerank_score: Decimal | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != CitationStatus.DRAFT:
            raise ValueError(
                "Retrieval metrics are immutable "
                "after verification begins"
            )

        if retrieval_rank is not None:
            if (
                isinstance(retrieval_rank, bool)
                or not isinstance(retrieval_rank, int)
                or retrieval_rank < 1
            ):
                raise ValueError(
                    "Retrieval rank must be positive"
                )

        self.retrieval_method = retrieval_method
        self.retrieval_rank = retrieval_rank

        for field, value in (
            ("retrieval_score", retrieval_score),
            ("rerank_score", rerank_score),
        ):
            if value is not None:
                parsed = Decimal(str(value))
                if not parsed.is_finite():
                    raise ValueError(
                        f"{field} must be finite"
                    )
                if parsed != parsed.quantize(
                    Decimal("0.000001")
                ):
                    raise ValueError(
                        f"{field} supports at most "
                        "6 decimal places"
                    )
                setattr(self, field, parsed)

        if metadata is not None:
            self.retrieval_metadata = dict(metadata)

        self._record_event(
            "retrieval_metrics_updated",
        )

    # ========================================================
    # UPDATE EVALUATION
    # ========================================================

    def update_evaluation(
        self,
        *,
        confidence: Decimal | int | float | str,
        relevance: Decimal | int | float | str,
        faithfulness: Decimal | int | float | str,
        evaluation_result_id: str | None = None,
    ) -> None:
        self._ensure_not_deleted()

        if self.status not in {
            CitationStatus.DRAFT,
            CitationStatus.PENDING_VERIFICATION,
        }:
            raise ValueError(
                "Citation evaluation cannot be updated"
            )

        self.confidence_score = score(
            confidence,
            "confidence",
        )
        self.relevance_score = score(
            relevance,
            "relevance",
        )
        self.faithfulness_score = score(
            faithfulness,
            "faithfulness",
        )

        if evaluation_result_id is not None:
            self.evaluation_result_id = (
                evaluation_result_id
            )

        self._record_event(
            "citation_evaluation_updated",
        )

    # ========================================================
    # REQUEST VERIFICATION
    # ========================================================

    def request_verification(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != CitationStatus.DRAFT:
            raise ValueError(
                "Only draft citations can request verification"
            )

        require_text(
            self.supported_claim,
            "Supported claim",
        )
        require_text(
            self.evidence_text,
            "Evidence text",
        )
        require_text(
            self.source_title,
            "Source title",
        )

        if not (
            self.document_id
            or self.source_uri
            or self.source_external_id
        ):
            raise ValueError(
                "Citation requires a resolvable source"
            )

        if self.is_expired:
            raise ValueError(
                "Expired evidence cannot be verified"
            )

        self.status = CitationStatus.PENDING_VERIFICATION

        self._record_event(
            "citation_verification_requested",
            actor_id=actor_id,
        )

    # ========================================================
    # VERIFY CITATION
    # ========================================================

    def verify(
        self,
        *,
        verifier_id: str,
        method: CitationVerificationMethod,
        notes: str | None = None,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != (
            CitationStatus.PENDING_VERIFICATION
        ):
            raise ValueError(
                "Citation is not pending verification"
            )

        if self.is_expired:
            raise ValueError(
                "Citation evidence has expired"
            )

        # Service layer must actually compare evidence
        # against the authorized source version and
        # verify that it supports the stated claim.

        self.status = CitationStatus.VERIFIED
        self.verification_method = method
        self.verification_notes = notes
        self.verified_by = require_text(
            verifier_id,
            "Verifier ID",
        )
        self.verified_at = utc_now()

        self._record_event(
            "citation_verified",
            actor_id=verifier_id,
            details={"method": method.value},
        )

    # ========================================================
    # REJECT CITATION
    # ========================================================

    def reject(
        self,
        *,
        reviewer_id: str,
        reason: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != (
            CitationStatus.PENDING_VERIFICATION
        ):
            raise ValueError(
                "Citation is not pending verification"
            )

        self.status = CitationStatus.REJECTED
        self.rejected_by = require_text(
            reviewer_id,
            "Reviewer ID",
        )
        self.rejected_at = utc_now()
        self.rejection_reason = require_text(
            reason,
            "Rejection reason",
        )

        self._record_event(
            "citation_rejected",
            actor_id=reviewer_id,
            details={"reason": reason},
        )

    # ========================================================
    # INVALIDATE CITATION
    # ========================================================

    def invalidate(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status in {
            CitationStatus.INVALIDATED,
            CitationStatus.ARCHIVED,
        }:
            raise ValueError(
                "Citation is already invalidated or archived"
            )

        self.status = CitationStatus.INVALIDATED
        self.invalidated_at = utc_now()
        self.invalidated_by = require_text(
            actor_id,
            "Actor ID",
        )
        self.invalidation_reason = require_text(
            reason,
            "Invalidation reason",
        )

        self._record_event(
            "citation_invalidated",
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # EXPIRE CITATION
    # ========================================================

    def expire(
        self,
        *,
        actor_id: str | None = None,
    ) -> None:
        self._ensure_not_deleted()

        if not self.is_expired:
            raise ValueError(
                "Citation has not reached expiration"
            )

        if self.status in {
            CitationStatus.ARCHIVED,
            CitationStatus.INVALIDATED,
            CitationStatus.EXPIRED,
        }:
            raise ValueError(
                "Citation is already terminal"
            )

        self.status = CitationStatus.EXPIRED

        self._record_event(
            "citation_expired",
            actor_id=actor_id,
        )

    # ========================================================
    # REDACT CITATION
    # ========================================================

    def redact(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_not_deleted()

        self.is_redacted = True
        self.redaction_reason = require_text(
            reason,
            "Redaction reason",
        )

        self._record_event(
            "citation_redacted",
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # UPDATE SOURCE FRESHNESS
    # ========================================================

    def record_source_check(
        self,
        *,
        checked_at: datetime,
        source_unchanged: bool,
        actor_id: str | None = None,
    ) -> None:
        self._ensure_not_deleted()

        self.last_source_checked_at = aware_datetime(
            checked_at
        )

        if not source_unchanged:
            self.invalidate(
                actor_id=actor_id or "system",
                reason="Source content changed",
            )
            return

        self._record_event(
            "citation_source_checked",
            actor_id=actor_id,
            details={"source_unchanged": True},
        )

    # ========================================================
    # ARCHIVE
    # ========================================================

    def archive(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status not in {
            CitationStatus.REJECTED,
            CitationStatus.INVALIDATED,
            CitationStatus.EXPIRED,
        }:
            raise ValueError(
                "Only terminal citations can be archived"
            )

        self.status = CitationStatus.ARCHIVED

        self._record_event(
            "citation_archived",
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
        self._ensure_not_deleted()

        if self.status not in {
            CitationStatus.DRAFT,
            CitationStatus.REJECTED,
            CitationStatus.ARCHIVED,
        }:
            raise ValueError(
                "Citation cannot be deleted in current state"
            )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = require_text(
            actor_id,
            "Actor ID",
        )

        self._record_event(
            "citation_soft_deleted",
            actor_id=actor_id,
        )

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(
        self,
        *,
        include_evidence: bool = False,
        include_history: bool = False,
    ) -> dict[str, Any]:
        result = {
            "id": self.id,
            "organization_id": self.organization_id,
            "query_id": self.query_id,
            "response_id": self.response_id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "rag_run_id": self.rag_run_id,
            "agent_run_id": self.agent_run_id,
            "model_registry_id": self.model_registry_id,

            "citation_index": self.citation_index,
            "citation_key": self.citation_key,
            "citation_label": self.citation_label,
            "citation_marker": self.citation_marker,
            "status": enum_value(self.status),
            "claim_type": enum_value(self.claim_type),

            "document_id": self.document_id,
            "document_version": self.document_version,
            "source_type": enum_value(
                self.source_type
            ),
            "source_title": self.source_title,
            "source_external_id": (
                self.source_external_id
            ),
            "source_author": self.source_author,
            "source_published_at": iso(
                self.source_published_at
            ),
            "source_last_modified_at": iso(
                self.source_last_modified_at
            ),
            "source_content_sha256": (
                self.source_content_sha256
            ),

            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "page_number": self.page_number,
            "page_end": self.page_end,
            "section_title": self.section_title,
            "heading_path": self.heading_path,
            "start_offset": self.start_offset,
            "end_offset": self.end_offset,
            "location_metadata": (
                self.location_metadata
            ),

            "retrieval_method": enum_value(
                self.retrieval_method
            ),
            "retrieval_rank": self.retrieval_rank,
            "retrieval_score": decimal_string(
                self.retrieval_score
            ),
            "rerank_score": decimal_string(
                self.rerank_score
            ),
            "retriever_model_id": (
                self.retriever_model_id
            ),
            "reranker_model_id": (
                self.reranker_model_id
            ),
            "embedding_model": self.embedding_model,

            "confidence_score": decimal_string(
                self.confidence_score
            ),
            "relevance_score": decimal_string(
                self.relevance_score
            ),
            "faithfulness_score": decimal_string(
                self.faithfulness_score
            ),
            "evaluation_result_id": (
                self.evaluation_result_id
            ),

            "verification_method": enum_value(
                self.verification_method
            ),
            "verification_notes": (
                self.verification_notes
            ),
            "verified_by": self.verified_by,
            "verified_at": iso(self.verified_at),
            "rejected_by": self.rejected_by,
            "rejected_at": iso(self.rejected_at),
            "rejection_reason": self.rejection_reason,

            "access_level": enum_value(
                self.access_level
            ),
            "risk_level": enum_value(
                self.risk_level
            ),
            "contains_pii": self.contains_pii,
            "is_redacted": self.is_redacted,
            "redaction_reason": self.redaction_reason,
            "access_policy_id": self.access_policy_id,

            "valid_from": iso(self.valid_from),
            "valid_until": iso(self.valid_until),
            "last_source_checked_at": iso(
                self.last_source_checked_at
            ),
            "invalidated_at": iso(
                self.invalidated_at
            ),
            "invalidated_by": self.invalidated_by,
            "invalidation_reason": (
                self.invalidation_reason
            ),

            "is_verified": self.is_verified,
            "is_expired": self.is_expired,
            "is_currently_valid": (
                self.is_currently_valid
            ),
            "is_sensitive": self.is_sensitive,
            "can_be_displayed": self.can_be_displayed,

            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "trace_id": self.trace_id,
            "correlation_id": self.correlation_id,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "is_deleted": self.is_deleted,
            "deleted_at": iso(self.deleted_at),
            "deleted_by": self.deleted_by,
            "version": self.version,
        }

        # Only include source/evidence after
        # application-level access authorization.
        if include_evidence:
            result.update({
                "source_uri": self.source_uri,
                "supported_claim": self.supported_claim,
                "evidence_text": self.evidence_text,
                "evidence_context": self.evidence_context,
                "evidence_language": (
                    self.evidence_language
                ),
                "evidence_metadata": (
                    self.evidence_metadata
                ),
                "retrieval_metadata": (
                    self.retrieval_metadata
                ),
                "citation_metadata": (
                    self.citation_metadata
                ),
            })

        if include_history:
            result["citation_history"] = (
                self.citation_history
            )

        return result

    def __repr__(self) -> str:
        return (
            f"<RAGCitation("
            f"id={self.id}, "
            f"response_id={self.response_id}, "
            f"citation_key={self.citation_key}, "
            f"status={enum_value(self.status)}"
            f")>"
        )
