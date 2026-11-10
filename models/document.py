from __future__ import annotations

"""Planned module: document. Implementation pending."""

"""
backend/models/document.py

Enterprise Document Management ORM Model.

Python 3.10+
SQLAlchemy 2.0+

Includes:
- Document metadata and storage references
- Multi-tenant isolation
- File integrity and MIME metadata
- OCR and AI extraction tracking
- RAG indexing status
- Document approval workflow
- Version tracking
- Retention and soft deletion
- Optimistic concurrency control

Storage, scanning, OCR, embeddings, authorization,
and audit logging are implemented in services.
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
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_document_number() -> str:
    return f"DOC-{uuid.uuid4().hex[:16].upper()}"


def enum_type(enum_cls, name: str):
    return SQLEnum(
        enum_cls,
        name=name,
        native_enum=False,
        values_callable=lambda cls: [
            item.value for item in cls
        ],
        validate_strings=True,
        length=60,
    )


class DocumentType(str, enum.Enum):
    SUPPLIER_CONTRACT = "supplier_contract"
    PURCHASE_ORDER = "purchase_order"
    INVOICE = "invoice"
    DELIVERY_NOTE = "delivery_note"
    SHIPPING_LABEL = "shipping_label"
    BILL_OF_LADING = "bill_of_lading"
    WAREHOUSE_REPORT = "warehouse_report"
    INVENTORY_REPORT = "inventory_report"
    QUALITY_CERTIFICATE = "quality_certificate"
    COMPLIANCE_DOCUMENT = "compliance_document"
    FINANCIAL_REPORT = "financial_report"
    CUSTOMER_DOCUMENT = "customer_document"
    PRODUCT_DOCUMENT = "product_document"
    POLICY = "policy"
    SOP = "sop"
    OTHER = "other"


class DocumentStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    SCANNING = "scanning"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    ARCHIVED = "archived"
    QUARANTINED = "quarantined"


class ProcessingStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DocumentVisibility(str, enum.Enum):
    PRIVATE = "private"
    ORGANIZATION = "organization"
    RESTRICTED = "restricted"


class DocumentSource(str, enum.Enum):
    USER_UPLOAD = "user_upload"
    API = "api"
    ERP = "erp"
    SUPPLIER_PORTAL = "supplier_portal"
    EMAIL_IMPORT = "email_import"
    AI_AGENT = "ai_agent"
    SYSTEM = "system"


class Document(Base):
    __tablename__ = "documents"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "document_number",
            name="uq_document_org_number",
        ),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_document_org_id",
        ),
        CheckConstraint(
            "file_size_bytes >= 0",
            name="document_file_size_nonnegative",
        ),
        CheckConstraint(
            "page_count IS NULL OR page_count >= 0",
            name="document_page_count_nonnegative",
        ),
        CheckConstraint(
            "document_version >= 1",
            name="document_version_positive",
        ),
        CheckConstraint(
            "retention_until IS NULL OR "
            "retention_until >= created_at",
            name="document_retention_valid",
        ),
        Index(
            "ix_documents_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_documents_org_type",
            "organization_id",
            "document_type",
        ),
        Index(
            "ix_documents_org_entity",
            "organization_id",
            "entity_type",
            "entity_id",
        ),
        Index(
            "ix_documents_org_created",
            "organization_id",
            "created_at",
        ),
        Index(
            "ix_documents_org_approval",
            "organization_id",
            "approval_status",
        ),
    )

    # Identifiers

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

    document_number: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=generate_document_number,
    )

    # Document information

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    document_type: Mapped[DocumentType] = mapped_column(
        enum_type(DocumentType, "document_type"),
        default=DocumentType.OTHER,
        nullable=False,
    )

    status: Mapped[DocumentStatus] = mapped_column(
        enum_type(DocumentStatus, "document_status"),
        default=DocumentStatus.UPLOADED,
        nullable=False,
    )

    source: Mapped[DocumentSource] = mapped_column(
        enum_type(DocumentSource, "document_source"),
        default=DocumentSource.USER_UPLOAD,
        nullable=False,
    )

    visibility: Mapped[DocumentVisibility] = mapped_column(
        enum_type(
            DocumentVisibility,
            "document_visibility",
        ),
        default=DocumentVisibility.PRIVATE,
        nullable=False,
    )

    # Business references

    entity_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    entity_id: Mapped[str | None] = mapped_column(
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

    product_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    purchase_order_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    delivery_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # File metadata

    original_filename: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    storage_provider: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    storage_bucket: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    storage_key: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
    )

    mime_type: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    file_extension: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    file_size_bytes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    checksum_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    page_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    language_code: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    # Security

    is_encrypted: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    contains_pii: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    scan_status: Mapped[ProcessingStatus] = mapped_column(
        enum_type(
            ProcessingStatus,
            "document_scan_status",
        ),
        default=ProcessingStatus.NOT_STARTED,
        nullable=False,
    )

    scanned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    scan_result: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # OCR

    ocr_status: Mapped[ProcessingStatus] = mapped_column(
        enum_type(
            ProcessingStatus,
            "document_ocr_status",
        ),
        default=ProcessingStatus.NOT_STARTED,
        nullable=False,
    )

    ocr_engine: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    ocr_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    extracted_text_key: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    # AI extraction

    extraction_status: Mapped[ProcessingStatus] = mapped_column(
        enum_type(
            ProcessingStatus,
            "document_extraction_status",
        ),
        default=ProcessingStatus.NOT_STARTED,
        nullable=False,
    )

    extraction_model: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    extracted_fields: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    ai_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    extraction_completed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # RAG

    indexing_status: Mapped[ProcessingStatus] = mapped_column(
        enum_type(
            ProcessingStatus,
            "document_indexing_status",
        ),
        default=ProcessingStatus.NOT_STARTED,
        nullable=False,
    )

    vector_collection: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    embedding_model: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    chunk_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    indexed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Approval

    approval_status: Mapped[
        DocumentApprovalStatus
    ] = mapped_column(
        enum_type(
            DocumentApprovalStatus,
            "document_approval_status",
        ),
        default=DocumentApprovalStatus.NOT_REQUIRED,
        nullable=False,
    )

    approval_request_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    approved_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    rejection_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Versioning

    document_version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    previous_document_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # Retention

    retention_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    legal_hold: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # Metadata

    tags: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    processing_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Audit

    uploaded_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    updated_by: Mapped[str | None] = mapped_column(
        String(36),
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

    # Soft delete

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

    # Optimistic concurrency

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
    def is_ready(self) -> bool:
        return (
            not self.is_deleted
            and self.status == DocumentStatus.READY
            and self.scan_status == ProcessingStatus.COMPLETED
        )

    @property
    def is_searchable(self) -> bool:
        return (
            self.is_ready
            and self.indexing_status
            == ProcessingStatus.COMPLETED
        )

    @property
    def is_approved(self) -> bool:
        return self.approval_status in {
            DocumentApprovalStatus.APPROVED,
            DocumentApprovalStatus.NOT_REQUIRED,
        }

    # ========================================================
    # HELPERS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_active(self) -> None:
        if self.is_deleted:
            raise ValueError("Document has been deleted")

    # ========================================================
    # PROCESSING WORKFLOW
    # ========================================================

    def start_scanning(self) -> None:
        self._ensure_active()

        if self.status != DocumentStatus.UPLOADED:
            raise ValueError(
                "Only uploaded documents can be scanned"
            )

        self.status = DocumentStatus.SCANNING
        self.scan_status = ProcessingStatus.RUNNING
        self._touch()

    def complete_scanning(
        self,
        result: dict[str, Any],
        *,
        safe: bool,
    ) -> None:
        self._ensure_active()

        if self.scan_status != ProcessingStatus.RUNNING:
            raise ValueError("Scan is not running")

        self.scan_result = dict(result)
        self.scanned_at = utc_now()
        self.scan_status = ProcessingStatus.COMPLETED

        if safe:
            self.status = DocumentStatus.PROCESSING
        else:
            self.status = DocumentStatus.QUARANTINED

        self._touch()

    def start_ocr(self, engine: str) -> None:
        self._ensure_active()

        if (
            self.status != DocumentStatus.PROCESSING
            or self.scan_status != ProcessingStatus.COMPLETED
        ):
            raise ValueError(
                "Document must pass scanning before OCR"
            )

        if not engine.strip():
            raise ValueError("OCR engine is required")

        self.ocr_engine = engine
        self.ocr_status = ProcessingStatus.RUNNING
        self._touch()

    def complete_ocr(
        self,
        extracted_text_key: str,
        page_count: int | None = None,
    ) -> None:
        self._ensure_active()

        if self.ocr_status != ProcessingStatus.RUNNING:
            raise ValueError("OCR is not running")

        if not extracted_text_key.strip():
            raise ValueError(
                "Extracted text storage key is required"
            )

        if page_count is not None and page_count < 0:
            raise ValueError("Invalid page count")

        self.extracted_text_key = extracted_text_key
        self.page_count = page_count
        self.ocr_status = ProcessingStatus.COMPLETED
        self.ocr_completed_at = utc_now()
        self._touch()

    def complete_extraction(
        self,
        *,
        model_name: str,
        fields: dict[str, Any],
        summary: str | None = None,
    ) -> None:
        self._ensure_active()

        if self.status != DocumentStatus.PROCESSING:
            raise ValueError(
                "Document is not processing"
            )

        if not model_name.strip():
            raise ValueError("Model name is required")

        self.extraction_model = model_name
        self.extracted_fields = dict(fields)
        self.ai_summary = summary
        self.extraction_status = ProcessingStatus.COMPLETED
        self.extraction_completed_at = utc_now()
        self._touch()

    def complete_indexing(
        self,
        *,
        collection: str,
        embedding_model: str,
        chunk_count: int,
    ) -> None:
        self._ensure_active()

        if self.status != DocumentStatus.PROCESSING:
            raise ValueError(
                "Document is not processing"
            )

        if not collection.strip() or not embedding_model.strip():
            raise ValueError(
                "Collection and embedding model are required"
            )

        if chunk_count < 0:
            raise ValueError(
                "Chunk count cannot be negative"
            )

        self.vector_collection = collection
        self.embedding_model = embedding_model
        self.chunk_count = chunk_count
        self.indexing_status = ProcessingStatus.COMPLETED
        self.indexed_at = utc_now()
        self._touch()

    def mark_ready(self) -> None:
        self._ensure_active()

        if self.status != DocumentStatus.PROCESSING:
            raise ValueError(
                "Document must be processing"
            )

        if self.scan_status != ProcessingStatus.COMPLETED:
            raise ValueError(
                "Security scanning must be complete"
            )

        self.status = DocumentStatus.READY
        self.processing_error = None
        self._touch()

    def mark_failed(self, error: str) -> None:
        self._ensure_active()

        if self.status in {
            DocumentStatus.ARCHIVED,
            DocumentStatus.QUARANTINED,
        }:
            raise ValueError(
                "Cannot fail an archived or quarantined document"
            )

        if not error.strip():
            raise ValueError("Error message is required")

        self.status = DocumentStatus.FAILED
        self.processing_error = error
        self._touch()

    # ========================================================
    # APPROVAL WORKFLOW
    # ========================================================

    def request_approval(
        self,
        approval_request_id: str,
    ) -> None:
        self._ensure_active()

        if self.status != DocumentStatus.READY:
            raise ValueError(
                "Document must be ready for approval"
            )

        if not approval_request_id:
            raise ValueError(
                "Approval request ID is required"
            )

        self.approval_request_id = approval_request_id
        self.approval_status = DocumentApprovalStatus.PENDING
        self._touch()

    def approve(self, user_id: str) -> None:
        self._ensure_active()

        if self.approval_status != DocumentApprovalStatus.PENDING:
            raise ValueError(
                "Document is not pending approval"
            )

        if not user_id:
            raise ValueError("Approver is required")

        self.approval_status = DocumentApprovalStatus.APPROVED
        self.approved_by = user_id
        self.approved_at = utc_now()
        self.rejection_reason = None
        self._touch()

    def reject(
        self,
        user_id: str,
        reason: str,
    ) -> None:
        self._ensure_active()

        if self.approval_status != DocumentApprovalStatus.PENDING:
            raise ValueError(
                "Document is not pending approval"
            )

        if not user_id or not reason.strip():
            raise ValueError(
                "Reviewer and rejection reason are required"
            )

        self.approval_status = DocumentApprovalStatus.REJECTED
        self.rejection_reason = reason
        self._touch()

    # ========================================================
    # ARCHIVE
    # ========================================================

    def archive(self) -> None:
        self._ensure_active()

        if self.status != DocumentStatus.READY:
            raise ValueError(
                "Only ready documents can be archived"
            )

        self.status = DocumentStatus.ARCHIVED
        self._touch()

    # ========================================================
    # SOFT DELETE
    # ========================================================

    def soft_delete(self, user_id: str) -> None:
        self._ensure_active()

        if not user_id:
            raise ValueError(
                "Deleting user is required"
            )

        if self.legal_hold:
            raise ValueError(
                "Document is under legal hold"
            )

        if (
            self.retention_until is not None
            and self.retention_until > utc_now()
        ):
            raise ValueError(
                "Document retention period has not expired"
            )

        self.is_deleted = True
        self.deleted_by = user_id
        self.deleted_at = utc_now()
        self._touch()

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(self) -> dict[str, Any]:
        def dt(value: datetime | None) -> str | None:
            return value.isoformat() if value else None

        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "document_number": self.document_number,
            "title": self.title,
            "description": self.description,
            "document_type": self.document_type.value,
            "status": self.status.value,
            "source": self.source.value,
            "visibility": self.visibility.value,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "supplier_id": self.supplier_id,
            "warehouse_id": self.warehouse_id,
            "product_id": self.product_id,
            "purchase_order_id": self.purchase_order_id,
            "delivery_id": self.delivery_id,
            "original_filename": self.original_filename,
            "storage_provider": self.storage_provider,
            "mime_type": self.mime_type,
            "file_extension": self.file_extension,
            "file_size_bytes": self.file_size_bytes,
            "checksum_sha256": self.checksum_sha256,
            "page_count": self.page_count,
            "language_code": self.language_code,
            "is_encrypted": self.is_encrypted,
            "contains_pii": self.contains_pii,
            "scan_status": self.scan_status.value,
            "ocr_status": self.ocr_status.value,
            "extraction_status": self.extraction_status.value,
            "indexing_status": self.indexing_status.value,
            "approval_status": self.approval_status.value,
            "document_version": self.document_version,
            "previous_document_id": self.previous_document_id,
            "ai_summary": self.ai_summary,
            "chunk_count": self.chunk_count,
            "uploaded_by": self.uploaded_by,
            "legal_hold": self.legal_hold,
            "retention_until": dt(self.retention_until),
            "is_ready": self.is_ready,
            "is_searchable": self.is_searchable,
            "is_approved": self.is_approved,
            "is_deleted": self.is_deleted,
            "version": self.version,
            "created_at": dt(self.created_at),
            "updated_at": dt(self.updated_at),
        }

    def __repr__(self) -> str:
        return (
            f"<Document("
            f"id={self.id}, "
            f"number={self.document_number}, "
            f"status={self.status.value}"
            f")>"
        )
