from __future__ import annotations

"""Planned module: pack task. Implementation pending."""

"""
backend/models/pack_task.py

Autonomous Retail Supply Chain AI 5.0
Warehouse Packing Task ORM Model

Features:
- Multi-tenant packing operations
- Fulfillment order and warehouse references
- Packing task assignment and prioritization
- Pick-to-pack handoff tracking
- SKU-level packing lines
- Barcode and product verification
- Package dimensions and weight
- Packaging material tracking
- Quality-control inspections
- AI-assisted packing recommendations
- Human approval for exceptions
- SLA and deadline monitoring
- Packing exceptions and damage reports
- Partial packing and task completion
- Packing history and audit tracking
- Soft deletion and optimistic concurrency

Requirements:
    Python >= 3.10
    SQLAlchemy >= 2.0

Shared Base:
    backend.models.base.Base

Notes:
    - Quantities use Decimal for precision.
    - Database transactions must coordinate inventory,
      picking, fulfillment, and shipping updates.
    - Agent recommendations never directly authorize
      physical warehouse operations.
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

QUANTITY_PRECISION = Decimal("0.0001")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_pack_task_number() -> str:
    return f"PACK-{uuid.uuid4().hex[:16].upper()}"


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


def to_decimal(
    value: Decimal | int | float | str,
    *,
    field_name: str,
    allow_zero: bool = True,
) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric")

    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(
            f"{field_name} must be numeric"
        ) from None

    if not result.is_finite():
        raise ValueError(
            f"{field_name} must be finite"
        )

    if result < 0 or (not allow_zero and result == 0):
        raise ValueError(
            f"{field_name} must be positive"
            if not allow_zero
            else f"{field_name} cannot be negative"
        )

    if result != result.quantize(QUANTITY_PRECISION):
        raise ValueError(
            f"{field_name} supports at most "
            "four decimal places"
        )

    if result >= Decimal("100000000000000"):
        raise ValueError(
            f"{field_name} exceeds numeric precision"
        )

    return result


def require_text(
    value: str,
    field_name: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")

    return value.strip()


def iso_datetime(
    value: datetime | None,
) -> str | None:
    return value.isoformat() if value else None


def enum_value(
    value: enum.Enum | None,
) -> str | None:
    return value.value if value is not None else None


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError(
            "Timezone-aware datetime required"
        )

    return value.astimezone(timezone.utc)


def quantity_string(
    value: Decimal | None,
) -> str | None:
    return str(value) if value is not None else None


# ============================================================
# ENUMS
# ============================================================

class PackTaskStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    ASSIGNED = "assigned"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    PARTIALLY_PACKED = "partially_packed"
    PACKED = "packed"
    QUALITY_CHECK = "quality_check"
    READY_TO_SHIP = "ready_to_ship"
    COMPLETED = "completed"
    ON_HOLD = "on_hold"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PackTaskPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"


class PackTaskType(str, enum.Enum):
    STANDARD = "standard"
    EXPRESS = "express"
    BULK = "bulk"
    FRAGILE = "fragile"
    COLD_CHAIN = "cold_chain"
    HAZARDOUS = "hazardous"
    GIFT = "gift"
    RETURN_REPACK = "return_repack"
    CUSTOM = "custom"


class PackTaskSource(str, enum.Enum):
    FULFILLMENT = "fulfillment"
    PICK_TASK = "pick_task"
    WMS = "wms"
    ERP = "erp"
    MANUAL = "manual"
    API = "api"
    RULE_ENGINE = "rule_engine"
    AI_AGENT = "ai_agent"


class PackTaskQualityStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    FAILED = "failed"
    REINSPECTION = "reinspection"


class PackTaskExceptionType(str, enum.Enum):
    MISSING_ITEM = "missing_item"
    WRONG_ITEM = "wrong_item"
    DAMAGED_ITEM = "damaged_item"
    BARCODE_MISMATCH = "barcode_mismatch"
    QUANTITY_MISMATCH = "quantity_mismatch"
    PACKAGING_SHORTAGE = "packaging_shortage"
    WEIGHT_MISMATCH = "weight_mismatch"
    DIMENSION_MISMATCH = "dimension_mismatch"
    QUALITY_FAILURE = "quality_failure"
    EQUIPMENT_FAILURE = "equipment_failure"
    SAFETY_ISSUE = "safety_issue"
    OTHER = "other"


class PackTaskRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class PackTaskApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# ============================================================
# PACK TASK MODEL
# ============================================================

class PackTask(Base):
    __tablename__ = "pack_tasks"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "task_number",
            name="uq_pack_task_org_number",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_pack_task_org_idempotency",
        ),
        CheckConstraint(
            "total_quantity >= 0",
            name="pack_task_total_nonnegative",
        ),
        CheckConstraint(
            "packed_quantity >= 0",
            name="pack_task_packed_nonnegative",
        ),
        CheckConstraint(
            "packed_quantity <= total_quantity",
            name="pack_task_packed_limit",
        ),
        CheckConstraint(
            "damaged_quantity >= 0",
            name="pack_task_damaged_nonnegative",
        ),
        CheckConstraint(
            "damaged_quantity <= total_quantity",
            name="pack_task_damaged_limit",
        ),
        CheckConstraint(
            "package_count >= 0",
            name="pack_task_packages_nonnegative",
        ),
        CheckConstraint(
            "exception_count >= 0",
            name="pack_task_exceptions_nonnegative",
        ),
        CheckConstraint(
            "sla_breach_count >= 0",
            name="pack_task_sla_nonnegative",
        ),
        CheckConstraint(
            "version >= 1",
            name="pack_task_version_positive",
        ),
        Index(
            "ix_pack_task_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_pack_task_org_warehouse",
            "organization_id",
            "warehouse_id",
        ),
        Index(
            "ix_pack_task_org_fulfillment",
            "organization_id",
            "fulfillment_order_id",
        ),
        Index(
            "ix_pack_task_org_assignee",
            "organization_id",
            "assigned_to",
        ),
        Index(
            "ix_pack_task_org_priority",
            "organization_id",
            "priority",
        ),
        Index(
            "ix_pack_task_org_deadline",
            "organization_id",
            "due_at",
        ),
        Index(
            "ix_pack_task_org_created",
            "organization_id",
            "created_at",
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

    task_number: Mapped[str] = mapped_column(
        String(50),
        default=generate_pack_task_number,
        nullable=False,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # --------------------------------------------------------
    # TASK INFORMATION
    # --------------------------------------------------------

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    status: Mapped[PackTaskStatus] = mapped_column(
        enum_column(
            PackTaskStatus,
            "pack_task_status",
        ),
        default=PackTaskStatus.DRAFT,
        nullable=False,
    )

    priority: Mapped[PackTaskPriority] = mapped_column(
        enum_column(
            PackTaskPriority,
            "pack_task_priority",
        ),
        default=PackTaskPriority.NORMAL,
        nullable=False,
    )

    task_type: Mapped[PackTaskType] = mapped_column(
        enum_column(
            PackTaskType,
            "pack_task_type",
        ),
        default=PackTaskType.STANDARD,
        nullable=False,
    )

    source: Mapped[PackTaskSource] = mapped_column(
        enum_column(
            PackTaskSource,
            "pack_task_source",
        ),
        default=PackTaskSource.FULFILLMENT,
        nullable=False,
    )

    # --------------------------------------------------------
    # BUSINESS REFERENCES
    # --------------------------------------------------------

    fulfillment_order_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    order_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    pick_task_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    warehouse_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    warehouse_zone_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    packing_station_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    shipment_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    delivery_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    customer_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # ASSIGNMENT
    # --------------------------------------------------------

    assigned_to: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    assigned_team_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    assigned_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    started_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    completed_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # QUANTITIES
    # --------------------------------------------------------

    total_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    packed_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    damaged_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    quantity_unit: Mapped[str] = mapped_column(
        String(30),
        default="units",
        nullable=False,
    )

    # --------------------------------------------------------
    # SKU PACKING LINES
    # --------------------------------------------------------

    packing_lines: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # --------------------------------------------------------
    # PACKAGES
    # --------------------------------------------------------

    package_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    package_details: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    packaging_materials: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    packaging_instructions: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # VERIFICATION
    # --------------------------------------------------------

    barcode_verification_required: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    barcode_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    barcode_verified_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    barcode_verified_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    verification_records: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # --------------------------------------------------------
    # QUALITY CONTROL
    # --------------------------------------------------------

    quality_check_required: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    quality_status: Mapped[
        PackTaskQualityStatus
    ] = mapped_column(
        enum_column(
            PackTaskQualityStatus,
            "pack_task_quality_status",
        ),
        default=PackTaskQualityStatus.PENDING,
        nullable=False,
    )

    quality_checked_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    quality_checked_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    quality_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    quality_checklist: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # AI PACKING INTELLIGENCE
    # --------------------------------------------------------

    ai_recommendation: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    ai_model_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    ai_agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    ai_risk_level: Mapped[PackTaskRiskLevel] = mapped_column(
        enum_column(
            PackTaskRiskLevel,
            "pack_task_risk_level",
        ),
        default=PackTaskRiskLevel.UNKNOWN,
        nullable=False,
    )

    ai_recommendation_updated_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # HUMAN APPROVAL
    # --------------------------------------------------------

    requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    approval_status: Mapped[
        PackTaskApprovalStatus
    ] = mapped_column(
        enum_column(
            PackTaskApprovalStatus,
            "pack_task_approval_status",
        ),
        default=PackTaskApprovalStatus.NOT_REQUIRED,
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

    # --------------------------------------------------------
    # SLA
    # --------------------------------------------------------

    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    packed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    sla_breached: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    sla_breach_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # --------------------------------------------------------
    # EXCEPTIONS
    # --------------------------------------------------------

    exception_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    exceptions: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    last_exception_type: Mapped[
        PackTaskExceptionType | None
    ] = mapped_column(
        enum_column(
            PackTaskExceptionType,
            "pack_task_exception_type",
        ),
        nullable=True,
    )

    incident_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # HOLD / CANCELLATION
    # --------------------------------------------------------

    previous_status: Mapped[
        PackTaskStatus | None
    ] = mapped_column(
        enum_column(
            PackTaskStatus,
            "pack_task_previous_status",
        ),
        nullable=True,
    )

    hold_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    held_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    cancelled_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    cancellation_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # EVENT HISTORY
    # --------------------------------------------------------

    task_history: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # --------------------------------------------------------
    # METADATA
    # --------------------------------------------------------

    task_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # AUDIT
    # --------------------------------------------------------

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
    # OPTIMISTIC CONCURRENCY
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
    def remaining_quantity(self) -> Decimal:
        return max(
            Decimal("0"),
            self.total_quantity - self.packed_quantity,
        )

    @property
    def packing_progress(self) -> float:
        if self.total_quantity <= 0:
            return 0.0

        return round(
            float(
                self.packed_quantity
                / self.total_quantity
                * Decimal("100")
            ),
            2,
        )

    @property
    def is_fully_packed(self) -> bool:
        return (
            self.total_quantity > 0
            and self.packed_quantity == self.total_quantity
        )

    @property
    def is_overdue(self) -> bool:
        return (
            self.due_at is not None
            and ensure_aware(self.due_at) < utc_now()
            and self.status not in {
                PackTaskStatus.COMPLETED,
                PackTaskStatus.CANCELLED,
                PackTaskStatus.FAILED,
            }
        )

    @property
    def is_approved(self) -> bool:
        return (
            not self.requires_approval
            or self.approval_status
            == PackTaskApprovalStatus.APPROVED
        )

    @property
    def is_quality_approved(self) -> bool:
        return (
            not self.quality_check_required
            or self.quality_status
            == PackTaskQualityStatus.PASSED
        )

    @property
    def can_complete(self) -> bool:
        return (
            not self.is_deleted
            and self.status
            == PackTaskStatus.READY_TO_SHIP
            and self.is_fully_packed
            and self.is_quality_approved
            and self.is_approved
            and (
                not self.barcode_verification_required
                or self.barcode_verified
            )
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_active(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Packing task has been deleted"
            )

        if self.status in {
            PackTaskStatus.COMPLETED,
            PackTaskStatus.CANCELLED,
            PackTaskStatus.FAILED,
        }:
            raise ValueError(
                "Packing task is in a terminal state"
            )

    def _add_history(
        self,
        event: str,
        *,
        actor_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        history = list(self.task_history or [])

        history.append({
            "event": event,
            "actor_id": actor_id,
            "timestamp": utc_now().isoformat(),
            "details": details or {},
        })

        self.task_history = history
        self._touch()

    def _validate_line_totals(self) -> None:
        lines = self.packing_lines or []

        if not lines:
            return

        total_expected = sum(
            (
                Decimal(str(line["expected_quantity"]))
                for line in lines
            ),
            Decimal("0"),
        )

        total_packed = sum(
            (
                Decimal(str(line["packed_quantity"]))
                for line in lines
            ),
            Decimal("0"),
        )

        if total_expected != self.total_quantity:
            raise ValueError(
                "Packing line quantities do not match task total"
            )

        if total_packed != self.packed_quantity:
            raise ValueError(
                "Packing line packed quantities do not "
                "match task packed quantity"
            )

    # ========================================================
    # SUBMIT TASK
    # ========================================================

    def submit(self) -> None:
        self._ensure_active()

        if self.status != PackTaskStatus.DRAFT:
            raise ValueError(
                "Only draft tasks can be submitted"
            )

        if self.total_quantity <= 0:
            raise ValueError(
                "Total quantity must be positive"
            )

        self._validate_line_totals()

        self.status = PackTaskStatus.PENDING

        self._add_history("submitted")

    # ========================================================
    # ADD PACKING LINE
    # ========================================================

    def add_packing_line(
        self,
        *,
        product_id: str,
        sku: str,
        expected_quantity: Decimal | int | float | str,
        pick_task_line_id: str | None = None,
        barcode: str | None = None,
        batch_number: str | None = None,
    ) -> None:
        self._ensure_active()

        if self.status != PackTaskStatus.DRAFT:
            raise ValueError(
                "Packing lines can only be added in draft"
            )

        product_id = require_text(
            product_id,
            "Product ID",
        )
        sku = require_text(sku, "SKU")

        quantity = to_decimal(
            expected_quantity,
            field_name="expected_quantity",
            allow_zero=False,
        )

        lines = list(self.packing_lines or [])

        if any(line["sku"] == sku for line in lines):
            raise ValueError(
                "SKU already exists in packing task"
            )

        lines.append({
            "line_id": generate_uuid(),
            "product_id": product_id,
            "sku": sku,
            "pick_task_line_id": pick_task_line_id,
            "barcode": barcode,
            "batch_number": batch_number,
            "expected_quantity": str(quantity),
            "packed_quantity": "0",
            "verified": False,
            "created_at": utc_now().isoformat(),
        })

        self.packing_lines = lines
        self.total_quantity = (
            self.total_quantity + quantity
        )

        self._add_history(
            "packing_line_added",
            details={
                "sku": sku,
                "quantity": str(quantity),
            },
        )

    # ========================================================
    # ASSIGN TASK
    # ========================================================

    def assign(
        self,
        *,
        employee_id: str,
        assigned_by: str,
        packing_station_id: str | None = None,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            PackTaskStatus.PENDING,
            PackTaskStatus.ASSIGNED,
        }:
            raise ValueError(
                "Task cannot be assigned now"
            )

        self.assigned_to = require_text(
            employee_id,
            "Employee ID",
        )
        self.assigned_by = require_text(
            assigned_by,
            "Assigned by",
        )
        self.packing_station_id = packing_station_id
        self.assigned_at = utc_now()
        self.status = PackTaskStatus.ASSIGNED

        self._add_history(
            "assigned",
            actor_id=assigned_by,
            details={
                "employee_id": employee_id,
                "packing_station_id": packing_station_id,
            },
        )

    # ========================================================
    # MARK READY
    # ========================================================

    def mark_ready(self) -> None:
        self._ensure_active()

        if self.status != PackTaskStatus.ASSIGNED:
            raise ValueError(
                "Task must be assigned first"
            )

        self._validate_line_totals()

        self.status = PackTaskStatus.READY

        self._add_history("ready_for_packing")

    # ========================================================
    # START PACKING
    # ========================================================

    def start_packing(
        self,
        employee_id: str,
    ) -> None:
        self._ensure_active()

        if self.status != PackTaskStatus.READY:
            raise ValueError(
                "Task is not ready for packing"
            )

        if self.assigned_to != employee_id:
            raise ValueError(
                "Task is assigned to another employee"
            )

        self.started_by = employee_id
        self.started_at = utc_now()
        self.status = PackTaskStatus.IN_PROGRESS

        self._add_history(
            "packing_started",
            actor_id=employee_id,
        )

    # ========================================================
    # RECORD PACKED QUANTITY
    # ========================================================

    def record_packing(
        self,
        *,
        sku: str,
        quantity: Decimal | int | float | str,
        employee_id: str,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            PackTaskStatus.IN_PROGRESS,
            PackTaskStatus.PARTIALLY_PACKED,
        }:
            raise ValueError(
                "Task is not currently packing"
            )

        if self.assigned_to != employee_id:
            raise ValueError(
                "Only assigned employee can record packing"
            )

        quantity_decimal = to_decimal(
            quantity,
            field_name="quantity",
            allow_zero=False,
        )

        lines = [
            dict(line)
            for line in (self.packing_lines or [])
        ]

        matching_line = next(
            (
                line for line in lines
                if line["sku"] == sku
            ),
            None,
        )

        if matching_line is None:
            raise ValueError(
                "SKU does not exist in packing task"
            )

        expected = Decimal(
            matching_line["expected_quantity"]
        )

        already_packed = Decimal(
            matching_line["packed_quantity"]
        )

        if already_packed + quantity_decimal > expected:
            raise ValueError(
                "Packed quantity exceeds expected quantity"
            )

        matching_line["packed_quantity"] = str(
            already_packed + quantity_decimal
        )

        matching_line["last_packed_at"] = (
            utc_now().isoformat()
        )

        self.packing_lines = lines
        self.packed_quantity += quantity_decimal

        if self.is_fully_packed:
            self.status = PackTaskStatus.PACKED
            self.packed_at = utc_now()
        else:
            self.status = PackTaskStatus.PARTIALLY_PACKED

        self._validate_line_totals()

        self._add_history(
            "quantity_packed",
            actor_id=employee_id,
            details={
                "sku": sku,
                "quantity": str(quantity_decimal),
                "total_packed": str(self.packed_quantity),
            },
        )

    # ========================================================
    # VERIFY BARCODE
    # ========================================================

    def verify_barcode(
        self,
        *,
        sku: str,
        scanned_barcode: str,
        employee_id: str,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            PackTaskStatus.IN_PROGRESS,
            PackTaskStatus.PARTIALLY_PACKED,
            PackTaskStatus.PACKED,
        }:
            raise ValueError(
                "Barcode verification is not allowed now"
            )

        lines = [
            dict(line)
            for line in (self.packing_lines or [])
        ]

        matching_line = next(
            (
                line for line in lines
                if line["sku"] == sku
            ),
            None,
        )

        if matching_line is None:
            raise ValueError(
                "SKU not found"
            )

        expected_barcode = matching_line.get("barcode")

        if not expected_barcode:
            raise ValueError(
                "Expected barcode is not configured"
            )

        if scanned_barcode != expected_barcode:
            raise ValueError(
                "Barcode mismatch"
            )

        matching_line["verified"] = True
        matching_line["verified_by"] = employee_id
        matching_line["verified_at"] = (
            utc_now().isoformat()
        )

        self.packing_lines = lines

        self.barcode_verified = bool(lines) and all(
            line.get("verified", False)
            for line in lines
        )

        if self.barcode_verified:
            self.barcode_verified_at = utc_now()
            self.barcode_verified_by = employee_id

        records = list(self.verification_records or [])

        records.append({
            "sku": sku,
            "barcode": scanned_barcode,
            "verified_by": employee_id,
            "verified_at": utc_now().isoformat(),
        })

        self.verification_records = records

        self._add_history(
            "barcode_verified",
            actor_id=employee_id,
            details={"sku": sku},
        )

    # ========================================================
    # ADD PACKAGE
    # ========================================================

    def add_package(
        self,
        *,
        package_number: str,
        weight_kg: Decimal | int | float | str,
        length_cm: Decimal | int | float | str,
        width_cm: Decimal | int | float | str,
        height_cm: Decimal | int | float | str,
        packaging_type: str = "carton",
    ) -> None:
        self._ensure_active()

        if self.status not in {
            PackTaskStatus.IN_PROGRESS,
            PackTaskStatus.PARTIALLY_PACKED,
            PackTaskStatus.PACKED,
        }:
            raise ValueError(
                "Packages can only be added during packing"
            )

        package_number = require_text(
            package_number,
            "Package number",
        )

        packages = list(self.package_details or [])

        if any(
            package["package_number"] == package_number
            for package in packages
        ):
            raise ValueError(
                "Package number already exists"
            )

        package = {
            "package_id": generate_uuid(),
            "package_number": package_number,
            "weight_kg": str(
                to_decimal(
                    weight_kg,
                    field_name="weight_kg",
                    allow_zero=False,
                )
            ),
            "length_cm": str(
                to_decimal(
                    length_cm,
                    field_name="length_cm",
                    allow_zero=False,
                )
            ),
            "width_cm": str(
                to_decimal(
                    width_cm,
                    field_name="width_cm",
                    allow_zero=False,
                )
            ),
            "height_cm": str(
                to_decimal(
                    height_cm,
                    field_name="height_cm",
                    allow_zero=False,
                )
            ),
            "packaging_type": require_text(
                packaging_type,
                "Packaging type",
            ),
            "created_at": utc_now().isoformat(),
        }

        packages.append(package)

        self.package_details = packages
        self.package_count = len(packages)

        self._add_history(
            "package_added",
            details={
                "package_number": package_number,
            },
        )

    # ========================================================
    # START QUALITY CHECK
    # ========================================================

    def start_quality_check(
        self,
        inspector_id: str,
    ) -> None:
        self._ensure_active()

        if self.status != PackTaskStatus.PACKED:
            raise ValueError(
                "Task must be fully packed"
            )

        if not self.quality_check_required:
            raise ValueError(
                "Quality check is not required"
            )

        if self.barcode_verification_required:
            if not self.barcode_verified:
                raise ValueError(
                    "Barcode verification is incomplete"
                )

        self.quality_status = (
            PackTaskQualityStatus.IN_PROGRESS
        )
        self.quality_checked_by = require_text(
            inspector_id,
            "Inspector ID",
        )
        self.status = PackTaskStatus.QUALITY_CHECK

        self._add_history(
            "quality_check_started",
            actor_id=inspector_id,
        )

    # ========================================================
    # COMPLETE QUALITY CHECK
    # ========================================================

    def complete_quality_check(
        self,
        *,
        passed: bool,
        inspector_id: str,
        notes: str | None = None,
        checklist: dict[str, Any] | None = None,
    ) -> None:
        self._ensure_active()

        if self.status != PackTaskStatus.QUALITY_CHECK:
            raise ValueError(
                "Task is not in quality check"
            )

        if self.quality_status != (
            PackTaskQualityStatus.IN_PROGRESS
        ):
            raise ValueError(
                "Quality inspection has not started"
            )

        self.quality_checked_by = require_text(
            inspector_id,
            "Inspector ID",
        )
        self.quality_checked_at = utc_now()
        self.quality_notes = notes
        self.quality_checklist = dict(checklist or {})

        if passed:
            self.quality_status = (
                PackTaskQualityStatus.PASSED
            )
            self.status = PackTaskStatus.PACKED
        else:
            self.quality_status = (
                PackTaskQualityStatus.FAILED
            )
            self.status = PackTaskStatus.ON_HOLD
            self.previous_status = PackTaskStatus.PACKED
            self.hold_reason = (
                notes or "Quality inspection failed"
            )
            self.held_at = utc_now()

        self._add_history(
            "quality_check_completed",
            actor_id=inspector_id,
            details={
                "passed": passed,
                "notes": notes,
            },
        )

    # ========================================================
    # REQUEST APPROVAL
    # ========================================================

    def request_approval(
        self,
        approval_request_id: str,
    ) -> None:
        self._ensure_active()

        if not self.requires_approval:
            raise ValueError(
                "Approval is not required"
            )

        if self.approval_status == (
            PackTaskApprovalStatus.PENDING
        ):
            raise ValueError(
                "Approval is already pending"
            )

        if self.status not in {
            PackTaskStatus.PACKED,
            PackTaskStatus.ON_HOLD,
        }:
            raise ValueError(
                "Task is not ready for approval"
            )

        self.approval_request_id = require_text(
            approval_request_id,
            "Approval request ID",
        )
        self.approval_status = (
            PackTaskApprovalStatus.PENDING
        )
        self.approved_by = None
        self.approved_at = None

        self._add_history(
            "approval_requested",
            details={
                "approval_request_id": approval_request_id,
            },
        )

    # ========================================================
    # APPROVE TASK
    # ========================================================

    def approve(
        self,
        user_id: str,
    ) -> None:
        self._ensure_active()

        if self.approval_status != (
            PackTaskApprovalStatus.PENDING
        ):
            raise ValueError(
                "Approval is not pending"
            )

        # Authorization and approval-request validation
        # must be performed in the service layer.
        self.approval_status = (
            PackTaskApprovalStatus.APPROVED
        )
        self.approved_by = require_text(
            user_id,
            "Approver ID",
        )
        self.approved_at = utc_now()

        self._add_history(
            "approved",
            actor_id=user_id,
        )

    # ========================================================
    # UPDATE AI RECOMMENDATION
    # ========================================================

    def update_ai_recommendation(
        self,
        *,
        recommendation: dict[str, Any],
        model_id: str | None = None,
        agent_run_id: str | None = None,
        risk_level: PackTaskRiskLevel = (
            PackTaskRiskLevel.UNKNOWN
        ),
    ) -> None:
        self._ensure_active()

        self.ai_recommendation = dict(recommendation)
        self.ai_model_id = model_id
        self.ai_agent_run_id = agent_run_id
        self.ai_risk_level = risk_level
        self.ai_recommendation_updated_at = utc_now()

        self._add_history(
            "ai_recommendation_updated",
            details={
                "model_id": model_id,
                "agent_run_id": agent_run_id,
                "risk_level": risk_level.value,
            },
        )

    # ========================================================
    # RECORD EXCEPTION
    # ========================================================

    def record_exception(
        self,
        *,
        exception_type: PackTaskExceptionType,
        description: str,
        reported_by: str,
        incident_id: str | None = None,
    ) -> None:
        self._ensure_active()

        exceptions = list(self.exceptions or [])

        exceptions.append({
            "exception_id": generate_uuid(),
            "type": exception_type.value,
            "description": require_text(
                description,
                "Exception description",
            ),
            "reported_by": require_text(
                reported_by,
                "Reported by",
            ),
            "reported_at": utc_now().isoformat(),
            "incident_id": incident_id,
        })

        self.exceptions = exceptions
        self.exception_count += 1
        self.last_exception_type = exception_type

        if incident_id:
            self.incident_id = incident_id

        self._add_history(
            "exception_recorded",
            actor_id=reported_by,
            details={
                "exception_type": exception_type.value,
                "incident_id": incident_id,
            },
        )

    # ========================================================
    # PLACE ON HOLD
    # ========================================================

    def place_on_hold(
        self,
        *,
        reason: str,
        user_id: str,
    ) -> None:
        self._ensure_active()

        if self.status == PackTaskStatus.ON_HOLD:
            raise ValueError(
                "Task is already on hold"
            )

        self.previous_status = self.status
        self.status = PackTaskStatus.ON_HOLD
        self.hold_reason = require_text(
            reason,
            "Hold reason",
        )
        self.held_at = utc_now()

        self._add_history(
            "placed_on_hold",
            actor_id=user_id,
            details={"reason": reason},
        )

    # ========================================================
    # RELEASE HOLD
    # ========================================================

    def release_hold(
        self,
        user_id: str,
    ) -> None:
        self._ensure_active()

        if self.status != PackTaskStatus.ON_HOLD:
            raise ValueError(
                "Task is not on hold"
            )

        if self.quality_status == (
            PackTaskQualityStatus.FAILED
        ):
            raise ValueError(
                "Failed quality check must be resolved "
                "and reinspected before releasing hold"
            )

        if self.previous_status is None:
            raise ValueError(
                "Previous status is unavailable"
            )

        self.status = self.previous_status
        self.previous_status = None
        self.hold_reason = None
        self.held_at = None

        self._add_history(
            "hold_released",
            actor_id=user_id,
        )

    # ========================================================
    # MARK READY TO SHIP
    # ========================================================

    def mark_ready_to_ship(self) -> None:
        self._ensure_active()

        if self.status != PackTaskStatus.PACKED:
            raise ValueError(
                "Task must be packed first"
            )

        if not self.is_fully_packed:
            raise ValueError(
                "Packing is incomplete"
            )

        if not self.is_quality_approved:
            raise ValueError(
                "Quality approval required"
            )

        if not self.is_approved:
            raise ValueError(
                "Human approval required"
            )

        if (
            self.barcode_verification_required
            and not self.barcode_verified
        ):
            raise ValueError(
                "Barcode verification required"
            )

        if self.package_count <= 0:
            raise ValueError(
                "At least one package is required"
            )

        self.status = PackTaskStatus.READY_TO_SHIP

        self._add_history("ready_to_ship")

    # ========================================================
    # COMPLETE TASK
    # ========================================================

    def complete(
        self,
        employee_id: str,
    ) -> None:
        self._ensure_active()

        if not self.can_complete:
            raise ValueError(
                "Packing task is not ready for completion"
            )

        self.completed_by = require_text(
            employee_id,
            "Employee ID",
        )
        self.completed_at = utc_now()
        self.status = PackTaskStatus.COMPLETED

        self._add_history(
            "completed",
            actor_id=employee_id,
        )

    # ========================================================
    # RECORD SLA BREACH
    # ========================================================

    def record_sla_breach(self) -> None:
        self._ensure_active()

        if not self.is_overdue:
            raise ValueError(
                "Task has not exceeded its deadline"
            )

        if self.sla_breached:
            raise ValueError(
                "SLA breach already recorded"
            )

        self.sla_breached = True
        self.sla_breach_count += 1

        self._add_history("sla_breached")

    # ========================================================
    # CANCEL TASK
    # ========================================================

    def cancel(
        self,
        *,
        user_id: str,
        reason: str,
    ) -> None:
        self._ensure_active()

        if self.status in {
            PackTaskStatus.READY_TO_SHIP,
            PackTaskStatus.COMPLETED,
        }:
            raise ValueError(
                "Task cannot be cancelled after shipping handoff"
            )

        self.cancelled_by = require_text(
            user_id,
            "User ID",
        )
        self.cancellation_reason = require_text(
            reason,
            "Cancellation reason",
        )
        self.cancelled_at = utc_now()
        self.status = PackTaskStatus.CANCELLED

        self._add_history(
            "cancelled",
            actor_id=user_id,
            details={"reason": reason},
        )

    # ========================================================
    # SOFT DELETE
    # ========================================================

    def soft_delete(
        self,
        user_id: str,
    ) -> None:
        if self.is_deleted:
            raise ValueError(
                "Packing task already deleted"
            )

        if self.status not in {
            PackTaskStatus.DRAFT,
            PackTaskStatus.CANCELLED,
            PackTaskStatus.FAILED,
        }:
            raise ValueError(
                "Only draft, cancelled or failed tasks "
                "can be soft deleted"
            )

        self.deleted_by = require_text(
            user_id,
            "User ID",
        )
        self.deleted_at = utc_now()
        self.is_deleted = True

        self._touch()

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "task_number": self.task_number,
            "idempotency_key": self.idempotency_key,
            "title": self.title,
            "description": self.description,
            "status": enum_value(self.status),
            "priority": enum_value(self.priority),
            "task_type": enum_value(self.task_type),
            "source": enum_value(self.source),
            "fulfillment_order_id": self.fulfillment_order_id,
            "order_id": self.order_id,
            "pick_task_id": self.pick_task_id,
            "warehouse_id": self.warehouse_id,
            "warehouse_zone_id": self.warehouse_zone_id,
            "packing_station_id": self.packing_station_id,
            "shipment_id": self.shipment_id,
            "delivery_id": self.delivery_id,
            "customer_id": self.customer_id,
            "assigned_to": self.assigned_to,
            "assigned_team_id": self.assigned_team_id,
            "assigned_by": self.assigned_by,
            "assigned_at": iso_datetime(self.assigned_at),
            "started_by": self.started_by,
            "completed_by": self.completed_by,
            "total_quantity": quantity_string(
                self.total_quantity
            ),
            "packed_quantity": quantity_string(
                self.packed_quantity
            ),
            "damaged_quantity": quantity_string(
                self.damaged_quantity
            ),
            "remaining_quantity": quantity_string(
                self.remaining_quantity
            ),
            "quantity_unit": self.quantity_unit,
            "packing_progress": self.packing_progress,
            "packing_lines": self.packing_lines,
            "package_count": self.package_count,
            "package_details": self.package_details,
            "packaging_materials": self.packaging_materials,
            "packaging_instructions": (
                self.packaging_instructions
            ),
            "barcode_verification_required": (
                self.barcode_verification_required
            ),
            "barcode_verified": self.barcode_verified,
            "barcode_verified_at": iso_datetime(
                self.barcode_verified_at
            ),
            "barcode_verified_by": self.barcode_verified_by,
            "verification_records": self.verification_records,
            "quality_check_required": (
                self.quality_check_required
            ),
            "quality_status": enum_value(
                self.quality_status
            ),
            "quality_checked_by": self.quality_checked_by,
            "quality_checked_at": iso_datetime(
                self.quality_checked_at
            ),
            "quality_notes": self.quality_notes,
            "quality_checklist": self.quality_checklist,
            "ai_recommendation": self.ai_recommendation,
            "ai_model_id": self.ai_model_id,
            "ai_agent_run_id": self.ai_agent_run_id,
            "ai_risk_level": enum_value(self.ai_risk_level),
            "ai_recommendation_updated_at": iso_datetime(
                self.ai_recommendation_updated_at
            ),
            "requires_approval": self.requires_approval,
            "approval_status": enum_value(
                self.approval_status
            ),
            "approval_request_id": self.approval_request_id,
            "approved_by": self.approved_by,
            "approved_at": iso_datetime(self.approved_at),
            "scheduled_at": iso_datetime(self.scheduled_at),
            "due_at": iso_datetime(self.due_at),
            "started_at": iso_datetime(self.started_at),
            "packed_at": iso_datetime(self.packed_at),
            "completed_at": iso_datetime(self.completed_at),
            "sla_breached": self.sla_breached,
            "sla_breach_count": self.sla_breach_count,
            "is_overdue": self.is_overdue,
            "exception_count": self.exception_count,
            "exceptions": self.exceptions,
            "last_exception_type": enum_value(
                self.last_exception_type
            ),
            "incident_id": self.incident_id,
            "previous_status": enum_value(
                self.previous_status
            ),
            "hold_reason": self.hold_reason,
            "held_at": iso_datetime(self.held_at),
            "cancelled_at": iso_datetime(self.cancelled_at),
            "cancelled_by": self.cancelled_by,
            "cancellation_reason": self.cancellation_reason,
            "failure_reason": self.failure_reason,
            "task_history": self.task_history,
            "task_metadata": self.task_metadata,
            "is_fully_packed": self.is_fully_packed,
            "is_approved": self.is_approved,
            "is_quality_approved": self.is_quality_approved,
            "can_complete": self.can_complete,
            "is_deleted": self.is_deleted,
            "version": self.version,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": iso_datetime(self.created_at),
            "updated_at": iso_datetime(self.updated_at),
        }

    def __repr__(self) -> str:
        return (
            f"<PackTask("
            f"id={self.id}, "
            f"task_number={self.task_number}, "
            f"status={enum_value(self.status)}, "
            f"packed={self.packed_quantity}/"
            f"{self.total_quantity}"
            f")>"
        )
