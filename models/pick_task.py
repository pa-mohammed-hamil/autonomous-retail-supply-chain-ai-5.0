from __future__ import annotations

"""Planned module: pick task. Implementation pending."""

"""
backend/models/pick_task.py

Autonomous Retail Supply Chain AI 5.0
Warehouse Picking Task ORM Model

Features:
- Multi-tenant warehouse picking
- Fulfillment and packing task references
- SKU-level pick lines
- Bin, zone, batch and lot tracking
- Inventory reservation references
- Barcode verification
- Partial picking and shortages
- Employee assignment
- AI route and pick recommendations
- Quality checks
- Human approval
- SLA tracking
- Exception handling
- Pick-to-pack handoff
- Audit history
- Soft deletion
- Optimistic concurrency

Requirements:
    Python >= 3.10
    SQLAlchemy >= 2.0

Shared Base:
    backend.models.base.Base

Production notes:
- Inventory movements must be transactional.
- Stock availability must be validated by services.
- Physical picking must be authorized.
- JSON history is supplementary; use immutable
  audit/event tables for compliance.
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

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_pick_task_number() -> str:
    return f"PICK-{uuid.uuid4().hex[:16].upper()}"


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

    if result != result.quantize(Decimal("0.0001")):
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


# ============================================================
# ENUMS
# ============================================================

class PickTaskStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    ASSIGNED = "assigned"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    PARTIALLY_PICKED = "partially_picked"
    PICKED = "picked"
    QUALITY_CHECK = "quality_check"
    READY_FOR_PACKING = "ready_for_packing"
    HANDED_OFF = "handed_off"
    COMPLETED = "completed"
    ON_HOLD = "on_hold"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PickTaskPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"


class PickTaskType(str, enum.Enum):
    SINGLE_ORDER = "single_order"
    BATCH = "batch"
    WAVE = "wave"
    ZONE = "zone"
    CLUSTER = "cluster"
    EXPRESS = "express"
    REPLENISHMENT = "replenishment"
    RETURN = "return"


class PickTaskSource(str, enum.Enum):
    FULFILLMENT = "fulfillment"
    WMS = "wms"
    ERP = "erp"
    MANUAL = "manual"
    API = "api"
    RULE_ENGINE = "rule_engine"
    AI_AGENT = "ai_agent"


class PickTaskQualityStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    PASSED = "passed"
    FAILED = "failed"
    REINSPECTION = "reinspection"


class PickTaskExceptionType(str, enum.Enum):
    STOCK_SHORTAGE = "stock_shortage"
    WRONG_ITEM = "wrong_item"
    DAMAGED_ITEM = "damaged_item"
    EXPIRED_ITEM = "expired_item"
    BARCODE_MISMATCH = "barcode_mismatch"
    BIN_MISMATCH = "bin_mismatch"
    QUANTITY_MISMATCH = "quantity_mismatch"
    INACCESSIBLE_LOCATION = "inaccessible_location"
    EQUIPMENT_FAILURE = "equipment_failure"
    SAFETY_ISSUE = "safety_issue"
    SYSTEM_ERROR = "system_error"
    OTHER = "other"


class PickTaskRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class PickTaskApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# ============================================================
# PICK TASK MODEL
# ============================================================

class PickTask(Base):
    __tablename__ = "pick_tasks"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "task_number",
            name="uq_pick_task_org_number",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_pick_task_org_idempotency",
        ),
        CheckConstraint(
            "total_quantity >= 0",
            name="pick_task_total_nonnegative",
        ),
        CheckConstraint(
            "picked_quantity >= 0",
            name="pick_task_picked_nonnegative",
        ),
        CheckConstraint(
            "picked_quantity <= total_quantity",
            name="pick_task_picked_limit",
        ),
        CheckConstraint(
            "shortage_quantity >= 0",
            name="pick_task_shortage_nonnegative",
        ),
        CheckConstraint(
            "damaged_quantity >= 0",
            name="pick_task_damaged_nonnegative",
        ),
        CheckConstraint(
            "exception_count >= 0",
            name="pick_task_exception_nonnegative",
        ),
        CheckConstraint(
            "sla_breach_count >= 0",
            name="pick_task_sla_nonnegative",
        ),
        CheckConstraint(
            "version >= 1",
            name="pick_task_version_positive",
        ),
        Index(
            "ix_pick_task_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_pick_task_org_warehouse",
            "organization_id",
            "warehouse_id",
        ),
        Index(
            "ix_pick_task_org_fulfillment",
            "organization_id",
            "fulfillment_order_id",
        ),
        Index(
            "ix_pick_task_org_assignee",
            "organization_id",
            "assigned_to",
        ),
        Index(
            "ix_pick_task_org_priority",
            "organization_id",
            "priority",
        ),
        Index(
            "ix_pick_task_org_deadline",
            "organization_id",
            "due_at",
        ),
        Index(
            "ix_pick_task_org_created",
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
        default=generate_pick_task_number,
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

    status: Mapped[PickTaskStatus] = mapped_column(
        enum_column(
            PickTaskStatus,
            "pick_task_status",
        ),
        default=PickTaskStatus.DRAFT,
        nullable=False,
    )

    priority: Mapped[PickTaskPriority] = mapped_column(
        enum_column(
            PickTaskPriority,
            "pick_task_priority",
        ),
        default=PickTaskPriority.NORMAL,
        nullable=False,
    )

    task_type: Mapped[PickTaskType] = mapped_column(
        enum_column(
            PickTaskType,
            "pick_task_type",
        ),
        default=PickTaskType.SINGLE_ORDER,
        nullable=False,
    )

    source: Mapped[PickTaskSource] = mapped_column(
        enum_column(
            PickTaskSource,
            "pick_task_source",
        ),
        default=PickTaskSource.FULFILLMENT,
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

    pack_task_id: Mapped[str | None] = mapped_column(
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

    pick_wave_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    pick_batch_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    inventory_reservation_id: Mapped[
        str | None
    ] = mapped_column(
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

    picked_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    shortage_quantity: Mapped[Decimal] = mapped_column(
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
    # PICKING LINES
    # --------------------------------------------------------

    picking_lines: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # --------------------------------------------------------
    # PICK ROUTE
    # --------------------------------------------------------

    picking_route: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    current_bin_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # BARCODE VERIFICATION
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
        PickTaskQualityStatus
    ] = mapped_column(
        enum_column(
            PickTaskQualityStatus,
            "pick_task_quality_status",
        ),
        default=PickTaskQualityStatus.PENDING,
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
    # AI PICKING INTELLIGENCE
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

    ai_risk_level: Mapped[PickTaskRiskLevel] = mapped_column(
        enum_column(
            PickTaskRiskLevel,
            "pick_task_risk_level",
        ),
        default=PickTaskRiskLevel.UNKNOWN,
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
        PickTaskApprovalStatus
    ] = mapped_column(
        enum_column(
            PickTaskApprovalStatus,
            "pick_task_approval_status",
        ),
        default=PickTaskApprovalStatus.NOT_REQUIRED,
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

    picked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    handed_off_at: Mapped[datetime | None] = mapped_column(
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
        PickTaskExceptionType | None
    ] = mapped_column(
        enum_column(
            PickTaskExceptionType,
            "pick_task_exception_type",
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
        PickTaskStatus | None
    ] = mapped_column(
        enum_column(
            PickTaskStatus,
            "pick_task_previous_status",
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
            self.total_quantity
            - self.picked_quantity
            - self.shortage_quantity,
        )

    @property
    def picking_progress(self) -> float:
        if self.total_quantity <= 0:
            return 0.0

        return round(
            float(
                self.picked_quantity
                / self.total_quantity
                * Decimal("100")
            ),
            2,
        )

    @property
    def is_fully_picked(self) -> bool:
        return (
            self.total_quantity > 0
            and self.picked_quantity == self.total_quantity
            and self.shortage_quantity == 0
        )

    @property
    def is_overdue(self) -> bool:
        return (
            self.due_at is not None
            and ensure_aware(self.due_at) < utc_now()
            and self.status not in {
                PickTaskStatus.COMPLETED,
                PickTaskStatus.CANCELLED,
                PickTaskStatus.FAILED,
            }
        )

    @property
    def is_approved(self) -> bool:
        return (
            not self.requires_approval
            or self.approval_status
            == PickTaskApprovalStatus.APPROVED
        )

    @property
    def is_quality_approved(self) -> bool:
        return (
            not self.quality_check_required
            or self.quality_status
            == PickTaskQualityStatus.PASSED
        )

    @property
    def can_handoff(self) -> bool:
        return (
            not self.is_deleted
            and self.status
            == PickTaskStatus.READY_FOR_PACKING
            and self.is_fully_picked
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
                "Picking task has been deleted"
            )

        if self.status in {
            PickTaskStatus.COMPLETED,
            PickTaskStatus.CANCELLED,
            PickTaskStatus.FAILED,
        }:
            raise ValueError(
                "Picking task is in a terminal state"
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
        lines = self.picking_lines or []

        if not lines:
            return

        expected = sum(
            (
                Decimal(str(line["expected_quantity"]))
                for line in lines
            ),
            Decimal("0"),
        )

        picked = sum(
            (
                Decimal(str(line["picked_quantity"]))
                for line in lines
            ),
            Decimal("0"),
        )

        shortages = sum(
            (
                Decimal(str(line["shortage_quantity"]))
                for line in lines
            ),
            Decimal("0"),
        )

        if expected != self.total_quantity:
            raise ValueError(
                "Line quantities do not match task total"
            )

        if picked != self.picked_quantity:
            raise ValueError(
                "Picked quantities do not match task total"
            )

        if shortages != self.shortage_quantity:
            raise ValueError(
                "Shortage quantities do not match task total"
            )

    # ========================================================
    # ADD PICKING LINE
    # ========================================================

    def add_picking_line(
        self,
        *,
        product_id: str,
        sku: str,
        expected_quantity: Decimal | int | float | str,
        bin_id: str,
        inventory_id: str | None = None,
        barcode: str | None = None,
        batch_number: str | None = None,
        lot_number: str | None = None,
    ) -> None:
        self._ensure_active()

        if self.status != PickTaskStatus.DRAFT:
            raise ValueError(
                "Picking lines can only be added in draft"
            )

        quantity = to_decimal(
            expected_quantity,
            field_name="expected_quantity",
            allow_zero=False,
        )

        sku = require_text(sku, "SKU")
        bin_id = require_text(bin_id, "Bin ID")

        lines = list(self.picking_lines or [])

        if any(
            line["sku"] == sku
            and line["bin_id"] == bin_id
            and line.get("lot_number") == lot_number
            for line in lines
        ):
            raise ValueError(
                "Duplicate SKU/bin/lot picking line"
            )

        lines.append({
            "line_id": generate_uuid(),
            "product_id": require_text(
                product_id,
                "Product ID",
            ),
            "inventory_id": inventory_id,
            "sku": sku,
            "bin_id": bin_id,
            "barcode": barcode,
            "batch_number": batch_number,
            "lot_number": lot_number,
            "expected_quantity": str(quantity),
            "picked_quantity": "0",
            "shortage_quantity": "0",
            "verified": False,
            "created_at": utc_now().isoformat(),
        })

        self.picking_lines = lines
        self.total_quantity += quantity

        self._add_history(
            "picking_line_added",
            details={
                "sku": sku,
                "bin_id": bin_id,
                "quantity": str(quantity),
            },
        )

    # ========================================================
    # SUBMIT TASK
    # ========================================================

    def submit(self) -> None:
        self._ensure_active()

        if self.status != PickTaskStatus.DRAFT:
            raise ValueError(
                "Only draft tasks can be submitted"
            )

        if self.total_quantity <= 0:
            raise ValueError(
                "Total quantity must be positive"
            )

        if not self.picking_lines:
            raise ValueError(
                "At least one picking line is required"
            )

        self._validate_line_totals()
        self.status = PickTaskStatus.PENDING

        self._add_history("submitted")

    # ========================================================
    # ASSIGN TASK
    # ========================================================

    def assign(
        self,
        *,
        employee_id: str,
        assigned_by: str,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            PickTaskStatus.PENDING,
            PickTaskStatus.ASSIGNED,
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
        self.assigned_at = utc_now()
        self.status = PickTaskStatus.ASSIGNED

        self._add_history(
            "assigned",
            actor_id=assigned_by,
            details={
                "employee_id": employee_id,
            },
        )

    # ========================================================
    # CONFIGURE PICK ROUTE
    # ========================================================

    def configure_picking_route(
        self,
        route: list[dict[str, Any]],
    ) -> None:
        self._ensure_active()

        if self.status not in {
            PickTaskStatus.DRAFT,
            PickTaskStatus.PENDING,
            PickTaskStatus.ASSIGNED,
        }:
            raise ValueError(
                "Picking route cannot be changed now"
            )

        if not isinstance(route, list):
            raise ValueError(
                "Route must be a list"
            )

        self.picking_route = [
            dict(stop) for stop in route
        ]

        self._add_history(
            "picking_route_updated",
            details={"stops": len(route)},
        )

    # ========================================================
    # MARK READY
    # ========================================================

    def mark_ready(self) -> None:
        self._ensure_active()

        if self.status != PickTaskStatus.ASSIGNED:
            raise ValueError(
                "Task must be assigned first"
            )

        self._validate_line_totals()
        self.status = PickTaskStatus.READY

        self._add_history("ready_for_picking")

    # ========================================================
    # START PICKING
    # ========================================================

    def start_picking(
        self,
        employee_id: str,
    ) -> None:
        self._ensure_active()

        if self.status != PickTaskStatus.READY:
            raise ValueError(
                "Task is not ready for picking"
            )

        if self.assigned_to != employee_id:
            raise ValueError(
                "Task is assigned to another employee"
            )

        self.started_by = employee_id
        self.started_at = utc_now()
        self.status = PickTaskStatus.IN_PROGRESS

        self._add_history(
            "picking_started",
            actor_id=employee_id,
        )

    # ========================================================
    # RECORD PICKING
    # ========================================================

    def record_picking(
        self,
        *,
        line_id: str,
        quantity: Decimal | int | float | str,
        employee_id: str,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            PickTaskStatus.IN_PROGRESS,
            PickTaskStatus.PARTIALLY_PICKED,
        }:
            raise ValueError(
                "Task is not currently picking"
            )

        if self.assigned_to != employee_id:
            raise ValueError(
                "Only assigned employee can record picking"
            )

        quantity_decimal = to_decimal(
            quantity,
            field_name="quantity",
            allow_zero=False,
        )

        lines = [
            dict(line)
            for line in (self.picking_lines or [])
        ]

        line = next(
            (
                item for item in lines
                if item["line_id"] == line_id
            ),
            None,
        )

        if line is None:
            raise ValueError(
                "Picking line not found"
            )

        expected = Decimal(
            line["expected_quantity"]
        )
        already_picked = Decimal(
            line["picked_quantity"]
        )
        shortage = Decimal(
            line["shortage_quantity"]
        )

        if (
            already_picked
            + shortage
            + quantity_decimal
            > expected
        ):
            raise ValueError(
                "Picked quantity exceeds remaining allocation"
            )

        line["picked_quantity"] = str(
            already_picked + quantity_decimal
        )
        line["last_picked_at"] = utc_now().isoformat()

        self.picking_lines = lines
        self.picked_quantity += quantity_decimal

        if self.is_fully_picked:
            self.status = PickTaskStatus.PICKED
            self.picked_at = utc_now()
        else:
            self.status = PickTaskStatus.PARTIALLY_PICKED

        self._validate_line_totals()

        self._add_history(
            "quantity_picked",
            actor_id=employee_id,
            details={
                "line_id": line_id,
                "quantity": str(quantity_decimal),
            },
        )

    # ========================================================
    # RECORD SHORTAGE
    # ========================================================

    def record_shortage(
        self,
        *,
        line_id: str,
        quantity: Decimal | int | float | str,
        employee_id: str,
        reason: str,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            PickTaskStatus.IN_PROGRESS,
            PickTaskStatus.PARTIALLY_PICKED,
        }:
            raise ValueError(
                "Task is not currently picking"
            )

        if self.assigned_to != employee_id:
            raise ValueError(
                "Only assigned employee can report shortage"
            )

        quantity_decimal = to_decimal(
            quantity,
            field_name="quantity",
            allow_zero=False,
        )

        lines = [
            dict(line)
            for line in (self.picking_lines or [])
        ]

        line = next(
            (
                item for item in lines
                if item["line_id"] == line_id
            ),
            None,
        )

        if line is None:
            raise ValueError(
                "Picking line not found"
            )

        expected = Decimal(line["expected_quantity"])
        picked = Decimal(line["picked_quantity"])
        shortage = Decimal(line["shortage_quantity"])

        if picked + shortage + quantity_decimal > expected:
            raise ValueError(
                "Shortage exceeds remaining quantity"
            )

        line["shortage_quantity"] = str(
            shortage + quantity_decimal
        )

        self.picking_lines = lines
        self.shortage_quantity += quantity_decimal

        self.record_exception(
            exception_type=(
                PickTaskExceptionType.STOCK_SHORTAGE
            ),
            description=require_text(
                reason,
                "Shortage reason",
            ),
            reported_by=employee_id,
        )

        self._validate_line_totals()

    # ========================================================
    # VERIFY BARCODE
    # ========================================================

    def verify_barcode(
        self,
        *,
        line_id: str,
        scanned_barcode: str,
        employee_id: str,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            PickTaskStatus.IN_PROGRESS,
            PickTaskStatus.PARTIALLY_PICKED,
            PickTaskStatus.PICKED,
        }:
            raise ValueError(
                "Barcode verification is not allowed now"
            )

        lines = [
            dict(line)
            for line in (self.picking_lines or [])
        ]

        line = next(
            (
                item for item in lines
                if item["line_id"] == line_id
            ),
            None,
        )

        if line is None:
            raise ValueError(
                "Picking line not found"
            )

        expected_barcode = line.get("barcode")

        if not expected_barcode:
            raise ValueError(
                "Expected barcode is not configured"
            )

        if scanned_barcode != expected_barcode:
            raise ValueError(
                "Barcode mismatch"
            )

        line["verified"] = True
        line["verified_by"] = employee_id
        line["verified_at"] = utc_now().isoformat()

        self.picking_lines = lines

        self.barcode_verified = bool(lines) and all(
            item.get("verified", False)
            for item in lines
        )

        if self.barcode_verified:
            self.barcode_verified_at = utc_now()
            self.barcode_verified_by = employee_id

        records = list(self.verification_records or [])

        records.append({
            "line_id": line_id,
            "barcode": scanned_barcode,
            "verified_by": employee_id,
            "verified_at": utc_now().isoformat(),
        })

        self.verification_records = records

        self._add_history(
            "barcode_verified",
            actor_id=employee_id,
            details={"line_id": line_id},
        )

    # ========================================================
    # START QUALITY CHECK
    # ========================================================

    def start_quality_check(
        self,
        inspector_id: str,
    ) -> None:
        self._ensure_active()

        if self.status != PickTaskStatus.PICKED:
            raise ValueError(
                "Task must be fully picked"
            )

        if not self.quality_check_required:
            raise ValueError(
                "Quality check is not required"
            )

        if (
            self.barcode_verification_required
            and not self.barcode_verified
        ):
            raise ValueError(
                "Barcode verification is incomplete"
            )

        self.quality_status = (
            PickTaskQualityStatus.IN_PROGRESS
        )
        self.quality_checked_by = require_text(
            inspector_id,
            "Inspector ID",
        )
        self.status = PickTaskStatus.QUALITY_CHECK

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

        if self.status != PickTaskStatus.QUALITY_CHECK:
            raise ValueError(
                "Task is not in quality check"
            )

        if self.quality_status != (
            PickTaskQualityStatus.IN_PROGRESS
        ):
            raise ValueError(
                "Quality check has not started"
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
                PickTaskQualityStatus.PASSED
            )
            self.status = PickTaskStatus.PICKED
        else:
            self.quality_status = (
                PickTaskQualityStatus.FAILED
            )
            self.previous_status = PickTaskStatus.PICKED
            self.status = PickTaskStatus.ON_HOLD
            self.hold_reason = (
                notes or "Quality inspection failed"
            )
            self.held_at = utc_now()

        self._add_history(
            "quality_check_completed",
            actor_id=inspector_id,
            details={"passed": passed},
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

        if self.status not in {
            PickTaskStatus.PICKED,
            PickTaskStatus.ON_HOLD,
        }:
            raise ValueError(
                "Task is not ready for approval"
            )

        if self.approval_status == (
            PickTaskApprovalStatus.PENDING
        ):
            raise ValueError(
                "Approval is already pending"
            )

        self.approval_request_id = require_text(
            approval_request_id,
            "Approval request ID",
        )
        self.approval_status = (
            PickTaskApprovalStatus.PENDING
        )
        self.approved_by = None
        self.approved_at = None

        self._add_history("approval_requested")

    # ========================================================
    # APPROVE TASK
    # ========================================================

    def approve(
        self,
        user_id: str,
    ) -> None:
        self._ensure_active()

        if self.approval_status != (
            PickTaskApprovalStatus.PENDING
        ):
            raise ValueError(
                "Approval is not pending"
            )

        self.approval_status = (
            PickTaskApprovalStatus.APPROVED
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
        risk_level: PickTaskRiskLevel = (
            PickTaskRiskLevel.UNKNOWN
        ),
    ) -> None:
        self._ensure_active()

        self.ai_recommendation = dict(recommendation)
        self.ai_model_id = model_id
        self.ai_agent_run_id = agent_run_id
        self.ai_risk_level = risk_level
        self.ai_recommendation_updated_at = utc_now()

        self._add_history("ai_recommendation_updated")

    # ========================================================
    # RECORD EXCEPTION
    # ========================================================

    def record_exception(
        self,
        *,
        exception_type: PickTaskExceptionType,
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
                "type": exception_type.value,
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

        if self.status == PickTaskStatus.ON_HOLD:
            raise ValueError(
                "Task is already on hold"
            )

        self.previous_status = self.status
        self.status = PickTaskStatus.ON_HOLD
        self.hold_reason = require_text(
            reason,
            "Hold reason",
        )
        self.held_at = utc_now()

        self._add_history(
            "placed_on_hold",
            actor_id=user_id,
        )

    # ========================================================
    # RELEASE HOLD
    # ========================================================

    def release_hold(
        self,
        user_id: str,
    ) -> None:
        self._ensure_active()

        if self.status != PickTaskStatus.ON_HOLD:
            raise ValueError(
                "Task is not on hold"
            )

        if self.quality_status == (
            PickTaskQualityStatus.FAILED
        ):
            raise ValueError(
                "Failed quality inspection requires "
                "corrective action and reinspection"
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
    # MARK READY FOR PACKING
    # ========================================================

    def mark_ready_for_packing(self) -> None:
        self._ensure_active()

        if self.status != PickTaskStatus.PICKED:
            raise ValueError(
                "Task must be picked first"
            )

        if not self.is_fully_picked:
            raise ValueError(
                "Picking is incomplete"
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

        self.status = PickTaskStatus.READY_FOR_PACKING

        self._add_history("ready_for_packing")

    # ========================================================
    # HANDOFF TO PACKING
    # ========================================================

    def handoff_to_packing(
        self,
        *,
        pack_task_id: str,
        employee_id: str,
    ) -> None:
        self._ensure_active()

        if not self.can_handoff:
            raise ValueError(
                "Task is not ready for packing handoff"
            )

        self.pack_task_id = require_text(
            pack_task_id,
            "Pack task ID",
        )
        self.handed_off_at = utc_now()
        self.status = PickTaskStatus.HANDED_OFF

        self._add_history(
            "handed_off_to_packing",
            actor_id=employee_id,
            details={
                "pack_task_id": pack_task_id,
            },
        )

    # ========================================================
    # COMPLETE TASK
    # ========================================================

    def complete(
        self,
        employee_id: str,
    ) -> None:
        self._ensure_active()

        if self.status != PickTaskStatus.HANDED_OFF:
            raise ValueError(
                "Packing handoff is required"
            )

        self.completed_by = require_text(
            employee_id,
            "Employee ID",
        )
        self.completed_at = utc_now()
        self.status = PickTaskStatus.COMPLETED

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
            PickTaskStatus.READY_FOR_PACKING,
            PickTaskStatus.HANDED_OFF,
        }:
            raise ValueError(
                "Task cannot be cancelled after handoff"
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
        self.status = PickTaskStatus.CANCELLED

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
                "Picking task already deleted"
            )

        if self.status not in {
            PickTaskStatus.DRAFT,
            PickTaskStatus.CANCELLED,
            PickTaskStatus.FAILED,
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
            "pack_task_id": self.pack_task_id,
            "warehouse_id": self.warehouse_id,
            "warehouse_zone_id": self.warehouse_zone_id,
            "pick_wave_id": self.pick_wave_id,
            "pick_batch_id": self.pick_batch_id,
            "inventory_reservation_id": (
                self.inventory_reservation_id
            ),
            "customer_id": self.customer_id,
            "assigned_to": self.assigned_to,
            "assigned_team_id": self.assigned_team_id,
            "assigned_by": self.assigned_by,
            "assigned_at": iso_datetime(self.assigned_at),
            "started_by": self.started_by,
            "completed_by": self.completed_by,
            "total_quantity": str(self.total_quantity),
            "picked_quantity": str(self.picked_quantity),
            "shortage_quantity": str(
                self.shortage_quantity
            ),
            "damaged_quantity": str(self.damaged_quantity),
            "remaining_quantity": str(
                self.remaining_quantity
            ),
            "quantity_unit": self.quantity_unit,
            "picking_progress": self.picking_progress,
            "picking_lines": self.picking_lines,
            "picking_route": self.picking_route,
            "current_bin_id": self.current_bin_id,
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
            "picked_at": iso_datetime(self.picked_at),
            "handed_off_at": iso_datetime(
                self.handed_off_at
            ),
            "completed_at": iso_datetime(
                self.completed_at
            ),
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
            "cancelled_at": iso_datetime(
                self.cancelled_at
            ),
            "cancelled_by": self.cancelled_by,
            "cancellation_reason": self.cancellation_reason,
            "failure_reason": self.failure_reason,
            "task_history": self.task_history,
            "task_metadata": self.task_metadata,
            "is_fully_picked": self.is_fully_picked,
            "is_approved": self.is_approved,
            "is_quality_approved": self.is_quality_approved,
            "can_handoff": self.can_handoff,
            "is_deleted": self.is_deleted,
            "version": self.version,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": iso_datetime(self.created_at),
            "updated_at": iso_datetime(self.updated_at),
        }

    def __repr__(self) -> str:
        return (
            f"<PickTask("
            f"id={self.id}, "
            f"task_number={self.task_number}, "
            f"status={enum_value(self.status)}, "
            f"picked={self.picked_quantity}/"
            f"{self.total_quantity}"
            f")>"
        )
