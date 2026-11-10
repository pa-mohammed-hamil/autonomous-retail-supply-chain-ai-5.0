from __future__ import annotations

"""Planned module: replenishment plan. Implementation pending."""

"""
backend/models/replenishment_plan.py

Autonomous Retail Supply Chain AI 5.0
Enterprise Inventory Replenishment Planning

Features:
- Multi-tenant replenishment planning
- Product, supplier and warehouse references
- Multi-line replenishment plans
- Demand forecast integration
- Safety stock and reorder point calculation
- Economic Order Quantity (EOQ)
- Inventory coverage and stockout risk
- AI recommendations and model traceability
- Supplier selection and lead-time tracking
- Budget and estimated procurement cost
- Human approval workflow
- Purchase order generation tracking
- Partial and full plan execution
- Audit history and soft deletion
- Optimistic concurrency control

Important:
    This module stores replenishment plans.

    Inventory changes, supplier eligibility,
    purchase order creation, reservations,
    actual payments and authorization must
    be handled by transactional services.
"""


import enum
import uuid

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SQLEnum,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


# ============================================================
# HELPERS
# ============================================================

ZERO = Decimal("0.0000")
QUANTUM = Decimal("0.0001")
MAX_DECIMAL = Decimal("100000000000000")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_plan_number() -> str:
    return f"REP-{uuid.uuid4().hex[:16].upper()}"


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


def to_decimal(
    value: Decimal | str | int | float,
    field: str,
    *,
    positive: bool = False,
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

    if result < 0 or (positive and result == 0):
        raise ValueError(
            f"{field} must be positive"
            if positive
            else f"{field} must be nonnegative"
        )

    if result >= MAX_DECIMAL:
        raise ValueError(
            f"{field} exceeds supported precision"
        )

    if result != result.quantize(QUANTUM):
        raise ValueError(
            f"{field} supports at most 4 decimal places"
        )

    return result


def score_decimal(
    value: Decimal | str | int | float,
    field: str,
) -> Decimal:
    result = to_decimal(value, field)

    if result > 1:
        raise ValueError(
            f"{field} must be between 0 and 1"
        )

    return result


def nonnegative_int(value: int, field: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        raise ValueError(
            f"{field} must be a nonnegative integer"
        )
    return value


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


def ceil_quantity(value: Decimal) -> Decimal:
    return value.to_integral_value(
        rounding=ROUND_CEILING
    ).quantize(QUANTUM)


# ============================================================
# ENUMS
# ============================================================

class ReplenishmentPlanStatus(str, enum.Enum):
    DRAFT = "draft"
    ANALYZING = "analyzing"
    READY = "ready"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    PARTIALLY_EXECUTED = "partially_executed"
    EXECUTED = "executed"
    COMPLETED = "completed"
    ON_HOLD = "on_hold"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class ReplenishmentPlanType(str, enum.Enum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    DEMAND_DRIVEN = "demand_driven"
    FORECAST_DRIVEN = "forecast_driven"
    SAFETY_STOCK = "safety_stock"
    EMERGENCY = "emergency"
    SEASONAL = "seasonal"
    PROMOTIONAL = "promotional"
    INTER_WAREHOUSE = "inter_warehouse"


class ReplenishmentPlanSource(str, enum.Enum):
    MANUAL = "manual"
    REORDER_RULE = "reorder_rule"
    DEMAND_FORECAST = "demand_forecast"
    INVENTORY_MONITOR = "inventory_monitor"
    AI_AGENT = "ai_agent"
    ERP = "erp"
    WMS = "wms"
    API = "api"
    SCHEDULER = "scheduler"


class ReplenishmentPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"


class ReplenishmentRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class ReplenishmentApprovalStatus(str, enum.Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReplenishmentLineStatus(str, enum.Enum):
    PLANNED = "planned"
    APPROVED = "approved"
    PARTIALLY_ORDERED = "partially_ordered"
    ORDERED = "ordered"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class ReplenishmentStrategy(str, enum.Enum):
    REORDER_POINT = "reorder_point"
    MIN_MAX = "min_max"
    EOQ = "eoq"
    DEMAND_FORECAST = "demand_forecast"
    SAFETY_STOCK = "safety_stock"
    JUST_IN_TIME = "just_in_time"
    PERIODIC_REVIEW = "periodic_review"
    MANUAL = "manual"


# ============================================================
# REPLENISHMENT PLAN
# ============================================================

class ReplenishmentPlan(Base):
    __tablename__ = "replenishment_plans"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "plan_number",
            name="uq_replenishment_org_number",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_replenishment_org_idempotency",
        ),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_replenishment_org_id",
        ),
        CheckConstraint(
            "budget_amount >= 0",
            name="replenishment_budget_nonnegative",
        ),
        CheckConstraint(
            "estimated_total_cost >= 0",
            name="replenishment_cost_nonnegative",
        ),
        CheckConstraint(
            "actual_total_cost >= 0",
            name="replenishment_actual_cost_nonnegative",
        ),
        CheckConstraint(
            "forecast_confidence IS NULL OR "
            "(forecast_confidence >= 0 "
            "AND forecast_confidence <= 1)",
            name="replenishment_forecast_confidence_range",
        ),
        CheckConstraint(
            "ai_confidence IS NULL OR "
            "(ai_confidence >= 0 "
            "AND ai_confidence <= 1)",
            name="replenishment_ai_confidence_range",
        ),
        CheckConstraint(
            "version >= 1",
            name="replenishment_version_positive",
        ),
        Index(
            "ix_replenishment_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_replenishment_org_warehouse",
            "organization_id",
            "warehouse_id",
        ),
        Index(
            "ix_replenishment_org_supplier",
            "organization_id",
            "preferred_supplier_id",
        ),
        Index(
            "ix_replenishment_org_created",
            "organization_id",
            "created_at",
        ),
        Index(
            "ix_replenishment_org_planned",
            "organization_id",
            "planned_execution_at",
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

    plan_number: Mapped[str] = mapped_column(
        String(50),
        default=generate_plan_number,
        nullable=False,
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # --------------------------------------------------------
    # PLAN DETAILS
    # --------------------------------------------------------

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    status: Mapped[
        ReplenishmentPlanStatus
    ] = mapped_column(
        enum_column(
            ReplenishmentPlanStatus,
            "replenishment_plan_status",
        ),
        default=ReplenishmentPlanStatus.DRAFT,
        nullable=False,
    )

    plan_type: Mapped[
        ReplenishmentPlanType
    ] = mapped_column(
        enum_column(
            ReplenishmentPlanType,
            "replenishment_plan_type",
        ),
        default=ReplenishmentPlanType.DEMAND_DRIVEN,
        nullable=False,
    )

    source: Mapped[
        ReplenishmentPlanSource
    ] = mapped_column(
        enum_column(
            ReplenishmentPlanSource,
            "replenishment_plan_source",
        ),
        default=ReplenishmentPlanSource.MANUAL,
        nullable=False,
    )

    priority: Mapped[
        ReplenishmentPriority
    ] = mapped_column(
        enum_column(
            ReplenishmentPriority,
            "replenishment_plan_priority",
        ),
        default=ReplenishmentPriority.NORMAL,
        nullable=False,
    )

    strategy: Mapped[
        ReplenishmentStrategy
    ] = mapped_column(
        enum_column(
            ReplenishmentStrategy,
            "replenishment_plan_strategy",
        ),
        default=ReplenishmentStrategy.DEMAND_FORECAST,
        nullable=False,
    )

    # --------------------------------------------------------
    # WAREHOUSE / SUPPLIER
    # --------------------------------------------------------

    warehouse_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    destination_warehouse_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    preferred_supplier_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    supplier_selection_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # REFERENCES
    # --------------------------------------------------------

    demand_forecast_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    supplier_risk_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    model_registry_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    simulation_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # PLANNING PERIOD
    # --------------------------------------------------------

    planning_start_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    planning_end_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    planned_execution_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    expected_completion_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    execution_started_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    executed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # FINANCIAL PLANNING
    # --------------------------------------------------------

    currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    budget_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    estimated_total_cost: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    actual_total_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    budget_override_approved: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    budget_override_by: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # AI / FORECAST INTELLIGENCE
    # --------------------------------------------------------

    ai_generated: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    ai_model_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    ai_confidence: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    forecast_confidence: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(6, 4),
        nullable=True,
    )

    ai_recommendation: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    ai_explanation: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    ai_analysis: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    stockout_risk_level: Mapped[
        ReplenishmentRiskLevel
    ] = mapped_column(
        enum_column(
            ReplenishmentRiskLevel,
            "replenishment_stockout_risk_level",
        ),
        default=ReplenishmentRiskLevel.UNKNOWN,
        nullable=False,
    )

    # --------------------------------------------------------
    # APPROVAL
    # --------------------------------------------------------

    requires_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    approval_status: Mapped[
        ReplenishmentApprovalStatus
    ] = mapped_column(
        enum_column(
            ReplenishmentApprovalStatus,
            "replenishment_approval_status",
        ),
        default=ReplenishmentApprovalStatus.NOT_REQUIRED,
        nullable=False,
    )

    approval_request_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    requested_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    approved_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    approved_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    rejected_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    rejection_reason: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # EXECUTION
    # --------------------------------------------------------

    purchase_order_ids: Mapped[
        list[str]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    transfer_order_ids: Mapped[
        list[str]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    execution_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # HOLD / FAILURE / CANCELLATION
    # --------------------------------------------------------

    previous_status: Mapped[
        ReplenishmentPlanStatus | None
    ] = mapped_column(
        enum_column(
            ReplenishmentPlanStatus,
            "replenishment_previous_status",
        ),
        nullable=True,
    )

    hold_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    held_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    failure_reason: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    cancelled_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    cancelled_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    cancellation_reason: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # AUDIT
    # --------------------------------------------------------

    plan_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    plan_history: Mapped[
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

    # --------------------------------------------------------
    # RELATIONSHIPS
    # --------------------------------------------------------

    items: Mapped[
        list["ReplenishmentPlanItem"]
    ] = relationship(
        "ReplenishmentPlanItem",
        back_populates="plan",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ReplenishmentPlanItem.line_number",
    )

    # ========================================================
    # PROPERTIES
    # ========================================================

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            ReplenishmentPlanStatus.COMPLETED,
            ReplenishmentPlanStatus.REJECTED,
            ReplenishmentPlanStatus.CANCELLED,
            ReplenishmentPlanStatus.ARCHIVED,
        }

    @property
    def is_approved(self) -> bool:
        return (
            not self.requires_approval
            or self.approval_status
            == ReplenishmentApprovalStatus.APPROVED
        )

    @property
    def is_over_budget(self) -> bool:
        return (
            self.estimated_total_cost
            > self.budget_amount
        )

    @property
    def total_planned_quantity(self) -> Decimal:
        return sum(
            (
                item.recommended_quantity
                for item in self.items
                if item.status
                != ReplenishmentLineStatus.CANCELLED
            ),
            ZERO,
        )

    @property
    def total_ordered_quantity(self) -> Decimal:
        return sum(
            (
                item.ordered_quantity
                for item in self.items
            ),
            ZERO,
        )

    @property
    def total_received_quantity(self) -> Decimal:
        return sum(
            (
                item.received_quantity
                for item in self.items
            ),
            ZERO,
        )

    @property
    def is_fully_executed(self) -> bool:
        active_items = [
            item for item in self.items
            if item.status
            != ReplenishmentLineStatus.CANCELLED
        ]

        return bool(active_items) and all(
            item.ordered_quantity
            >= item.recommended_quantity
            for item in active_items
        )

    @property
    def is_fully_received(self) -> bool:
        active_items = [
            item for item in self.items
            if item.status
            != ReplenishmentLineStatus.CANCELLED
        ]

        return bool(active_items) and all(
            item.received_quantity
            >= item.recommended_quantity
            for item in active_items
        )

    @property
    def execution_progress(self) -> Decimal:
        planned = self.total_planned_quantity

        if planned <= 0:
            return ZERO

        return min(
            Decimal("100"),
            (
                self.total_ordered_quantity
                / planned
                * Decimal("100")
            ).quantize(QUANTUM),
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_not_deleted(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Replenishment plan has been deleted"
            )

    def _ensure_editable(self) -> None:
        self._ensure_not_deleted()

        if self.status not in {
            ReplenishmentPlanStatus.DRAFT,
            ReplenishmentPlanStatus.ANALYZING,
        }:
            raise ValueError(
                "Plan cannot be edited in current state"
            )

    def _record_event(
        self,
        event: str,
        *,
        actor_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        history = list(self.plan_history or [])

        history.append({
            "event_id": generate_uuid(),
            "event": event,
            "actor_id": actor_id,
            "timestamp": utc_now().isoformat(),
            "details": details or {},
        })

        self.plan_history = history
        self._touch()

    # ========================================================
    # ADD REPLENISHMENT ITEM
    # ========================================================

    def add_item(
        self,
        *,
        product_id: str,
        sku: str,
        product_name: str,
        current_stock: Decimal | str | int | float,
        reserved_stock: Decimal | str | int | float,
        forecast_demand: Decimal | str | int | float,
        safety_stock: Decimal | str | int | float,
        reorder_point: Decimal | str | int | float,
        recommended_quantity: Decimal | str | int | float,
        estimated_unit_cost: Decimal | str | int | float,
        actor_id: str,
        supplier_id: str | None = None,
        lead_time_days: int = 0,
    ) -> "ReplenishmentPlanItem":
        self._ensure_editable()

        product_id = require_text(
            product_id,
            "Product ID",
        )

        if any(
            item.product_id == product_id
            for item in self.items
        ):
            raise ValueError(
                "Product already exists in this plan"
            )

        line_number = max(
            (item.line_number for item in self.items),
            default=0,
        ) + 1

        item = ReplenishmentPlanItem(
            organization_id=self.organization_id,
            line_number=line_number,
            product_id=product_id,
            sku=require_text(sku, "SKU"),
            product_name=require_text(
                product_name,
                "Product name",
            ),
            supplier_id=supplier_id,
            current_stock=to_decimal(
                current_stock,
                "current_stock",
            ),
            reserved_stock=to_decimal(
                reserved_stock,
                "reserved_stock",
            ),
            forecast_demand=to_decimal(
                forecast_demand,
                "forecast_demand",
            ),
            safety_stock=to_decimal(
                safety_stock,
                "safety_stock",
            ),
            reorder_point=to_decimal(
                reorder_point,
                "reorder_point",
            ),
            recommended_quantity=to_decimal(
                recommended_quantity,
                "recommended_quantity",
                positive=True,
            ),
            estimated_unit_cost=to_decimal(
                estimated_unit_cost,
                "estimated_unit_cost",
            ),
            lead_time_days=nonnegative_int(
                lead_time_days,
                "lead_time_days",
            ),
        )

        item.recalculate()
        self.items.append(item)
        self.recalculate_totals()

        self._record_event(
            "replenishment_item_added",
            actor_id=actor_id,
            details={
                "product_id": product_id,
                "recommended_quantity": str(
                    item.recommended_quantity
                ),
            },
        )

        return item

    # ========================================================
    # RECALCULATE TOTALS
    # ========================================================

    def recalculate_totals(self) -> None:
        self._ensure_editable()

        for item in self.items:
            item.recalculate()

        self.estimated_total_cost = sum(
            (
                item.estimated_total_cost
                for item in self.items
                if item.status
                != ReplenishmentLineStatus.CANCELLED
            ),
            ZERO,
        )

        self._touch()

    # ========================================================
    # START ANALYSIS
    # ========================================================

    def start_analysis(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != ReplenishmentPlanStatus.DRAFT:
            raise ValueError(
                "Only draft plans can start analysis"
            )

        self.status = ReplenishmentPlanStatus.ANALYZING

        self._record_event(
            "replenishment_analysis_started",
            actor_id=actor_id,
        )

    # ========================================================
    # RECORD AI ANALYSIS
    # ========================================================

    def update_ai_analysis(
        self,
        *,
        model_id: str,
        confidence: Decimal | str | int | float,
        recommendation: str,
        explanation: str,
        analysis: dict[str, Any],
        stockout_risk_level: ReplenishmentRiskLevel,
        forecast_confidence: (
            Decimal | str | int | float | None
        ) = None,
        agent_run_id: str | None = None,
    ) -> None:
        self._ensure_editable()

        self.ai_generated = True
        self.ai_model_id = require_text(
            model_id,
            "Model ID",
        )
        self.agent_run_id = agent_run_id
        self.ai_confidence = score_decimal(
            confidence,
            "confidence",
        )

        if forecast_confidence is not None:
            self.forecast_confidence = score_decimal(
                forecast_confidence,
                "forecast_confidence",
            )

        self.ai_recommendation = require_text(
            recommendation,
            "Recommendation",
        )
        self.ai_explanation = require_text(
            explanation,
            "Explanation",
        )
        self.ai_analysis = dict(analysis)
        self.stockout_risk_level = stockout_risk_level

        self._record_event(
            "replenishment_ai_analysis_updated",
            details={
                "model_id": model_id,
                "risk_level": stockout_risk_level.value,
            },
        )

    # ========================================================
    # MARK READY
    # ========================================================

    def mark_ready(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        if not self.items:
            raise ValueError(
                "Replenishment plan requires items"
            )

        self.recalculate_totals()

        if (
            self.is_over_budget
            and not self.budget_override_approved
        ):
            raise ValueError(
                "Plan exceeds budget"
            )

        self.status = ReplenishmentPlanStatus.READY

        self._record_event(
            "replenishment_plan_ready",
            actor_id=actor_id,
        )

    # ========================================================
    # APPROVE BUDGET OVERRIDE
    # ========================================================

    def approve_budget_override(
        self,
        *,
        approver_id: str,
    ) -> None:
        self._ensure_editable()

        # Service must enforce budget approval
        # permissions and approval limits.

        self.budget_override_approved = True
        self.budget_override_by = require_text(
            approver_id,
            "Approver ID",
        )

        self._record_event(
            "replenishment_budget_override_approved",
            actor_id=approver_id,
        )

    # ========================================================
    # REQUEST APPROVAL
    # ========================================================

    def request_approval(
        self,
        *,
        actor_id: str,
        approval_request_id: str | None = None,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != ReplenishmentPlanStatus.READY:
            raise ValueError(
                "Plan must be ready for approval"
            )

        self.requested_by = require_text(
            actor_id,
            "Actor ID",
        )

        if self.requires_approval:
            self.approval_request_id = require_text(
                approval_request_id,
                "Approval request ID",
            )
            self.approval_status = (
                ReplenishmentApprovalStatus.PENDING
            )
            self.status = (
                ReplenishmentPlanStatus.PENDING_APPROVAL
            )
        else:
            self.approval_status = (
                ReplenishmentApprovalStatus.NOT_REQUIRED
            )
            self.status = (
                ReplenishmentPlanStatus.APPROVED
            )
            for item in self.items:
                item.status = (
                    ReplenishmentLineStatus.APPROVED
                )

        self._record_event(
            "replenishment_approval_requested",
            actor_id=actor_id,
        )

    # ========================================================
    # APPROVE
    # ========================================================

    def approve(
        self,
        *,
        approver_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != (
            ReplenishmentPlanStatus.PENDING_APPROVAL
        ):
            raise ValueError(
                "Plan is not pending approval"
            )

        # Service must verify the linked approval
        # and actor authorization.

        self.approval_status = (
            ReplenishmentApprovalStatus.APPROVED
        )
        self.approved_by = require_text(
            approver_id,
            "Approver ID",
        )
        self.approved_at = utc_now()
        self.status = ReplenishmentPlanStatus.APPROVED

        for item in self.items:
            if item.status == ReplenishmentLineStatus.PLANNED:
                item.status = (
                    ReplenishmentLineStatus.APPROVED
                )

        self._record_event(
            "replenishment_plan_approved",
            actor_id=approver_id,
        )

    # ========================================================
    # REJECT
    # ========================================================

    def reject(
        self,
        *,
        reviewer_id: str,
        reason: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != (
            ReplenishmentPlanStatus.PENDING_APPROVAL
        ):
            raise ValueError(
                "Plan is not pending approval"
            )

        self.approval_status = (
            ReplenishmentApprovalStatus.REJECTED
        )
        self.rejected_by = require_text(
            reviewer_id,
            "Reviewer ID",
        )
        self.rejection_reason = require_text(
            reason,
            "Rejection reason",
        )
        self.status = ReplenishmentPlanStatus.REJECTED

        self._record_event(
            "replenishment_plan_rejected",
            actor_id=reviewer_id,
            details={"reason": reason},
        )

    # ========================================================
    # START EXECUTION
    # ========================================================

    def start_execution(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != ReplenishmentPlanStatus.APPROVED:
            raise ValueError(
                "Plan must be approved"
            )

        if not self.is_approved:
            raise ValueError(
                "Approval is incomplete"
            )

        self.status = ReplenishmentPlanStatus.EXECUTING
        self.execution_started_at = utc_now()

        self._record_event(
            "replenishment_execution_started",
            actor_id=actor_id,
        )

    # ========================================================
    # RECORD PURCHASE ORDER
    # ========================================================

    def record_purchase_order(
        self,
        *,
        purchase_order_id: str,
        item_id: str,
        quantity: Decimal | str | int | float,
        actor_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status not in {
            ReplenishmentPlanStatus.EXECUTING,
            ReplenishmentPlanStatus.PARTIALLY_EXECUTED,
        }:
            raise ValueError(
                "Plan is not executing"
            )

        item = next(
            (
                item for item in self.items
                if item.id == item_id
            ),
            None,
        )

        if item is None:
            raise ValueError(
                "Replenishment item not found"
            )

        quantity = to_decimal(
            quantity,
            "quantity",
            positive=True,
        )

        item.record_ordered(quantity)

        po_id = require_text(
            purchase_order_id,
            "Purchase order ID",
        )

        order_ids = list(self.purchase_order_ids or [])

        if po_id not in order_ids:
            order_ids.append(po_id)

        self.purchase_order_ids = order_ids

        if self.is_fully_executed:
            self.status = ReplenishmentPlanStatus.EXECUTED
            self.executed_at = utc_now()
        else:
            self.status = (
                ReplenishmentPlanStatus.PARTIALLY_EXECUTED
            )

        self._record_event(
            "replenishment_purchase_order_recorded",
            actor_id=actor_id,
            details={
                "purchase_order_id": po_id,
                "item_id": item_id,
                "quantity": str(quantity),
            },
        )

    # ========================================================
    # RECORD RECEIPT
    # ========================================================

    def record_receipt(
        self,
        *,
        item_id: str,
        quantity: Decimal | str | int | float,
        actor_id: str,
        receipt_reference: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status not in {
            ReplenishmentPlanStatus.PARTIALLY_EXECUTED,
            ReplenishmentPlanStatus.EXECUTED,
        }:
            raise ValueError(
                "Plan has not generated procurement"
            )

        item = next(
            (
                item for item in self.items
                if item.id == item_id
            ),
            None,
        )

        if item is None:
            raise ValueError(
                "Replenishment item not found"
            )

        quantity = to_decimal(
            quantity,
            "quantity",
            positive=True,
        )

        # Receiving service must first validate
        # inventory movement and receipt idempotency.

        item.record_received(quantity)

        self._record_event(
            "replenishment_receipt_recorded",
            actor_id=actor_id,
            details={
                "item_id": item_id,
                "quantity": str(quantity),
                "receipt_reference": require_text(
                    receipt_reference,
                    "Receipt reference",
                ),
            },
        )

    # ========================================================
    # COMPLETE
    # ========================================================

    def complete(
        self,
        *,
        actor_id: str,
        actual_total_cost: (
            Decimal | str | int | float
        ),
    ) -> None:
        self._ensure_not_deleted()

        if self.status != ReplenishmentPlanStatus.EXECUTED:
            raise ValueError(
                "Plan must be fully executed"
            )

        if not self.is_fully_received:
            raise ValueError(
                "All replenishment items must be received"
            )

        self.actual_total_cost = to_decimal(
            actual_total_cost,
            "actual_total_cost",
        )
        self.completed_at = utc_now()
        self.status = ReplenishmentPlanStatus.COMPLETED

        self._record_event(
            "replenishment_plan_completed",
            actor_id=actor_id,
        )

    # ========================================================
    # HOLD
    # ========================================================

    def place_on_hold(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.is_terminal or self.status in {
            ReplenishmentPlanStatus.ON_HOLD,
            ReplenishmentPlanStatus.FAILED,
        }:
            raise ValueError(
                "Plan cannot be placed on hold"
            )

        self.previous_status = self.status
        self.status = ReplenishmentPlanStatus.ON_HOLD
        self.hold_reason = require_text(
            reason,
            "Hold reason",
        )
        self.held_at = utc_now()

        self._record_event(
            "replenishment_plan_on_hold",
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # RELEASE HOLD
    # ========================================================

    def release_hold(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.status != ReplenishmentPlanStatus.ON_HOLD:
            raise ValueError(
                "Plan is not on hold"
            )

        if self.previous_status is None:
            raise ValueError(
                "Previous plan status is unavailable"
            )

        self.status = self.previous_status
        self.previous_status = None
        self.hold_reason = None
        self.held_at = None

        self._record_event(
            "replenishment_plan_hold_released",
            actor_id=actor_id,
        )

    # ========================================================
    # FAIL
    # ========================================================

    def mark_failed(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.is_terminal:
            raise ValueError(
                "Terminal plan cannot fail"
            )

        self.status = ReplenishmentPlanStatus.FAILED
        self.failure_reason = require_text(
            reason,
            "Failure reason",
        )

        self._record_event(
            "replenishment_plan_failed",
            actor_id=actor_id,
            details={"reason": reason},
        )

    # ========================================================
    # CANCEL
    # ========================================================

    def cancel(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_not_deleted()

        if self.is_terminal:
            raise ValueError(
                "Terminal plan cannot be cancelled"
            )

        if self.total_ordered_quantity > 0:
            raise ValueError(
                "Plan has procurement commitments; "
                "cancel purchase orders first"
            )

        self.status = ReplenishmentPlanStatus.CANCELLED
        self.cancelled_at = utc_now()
        self.cancelled_by = require_text(
            actor_id,
            "Actor ID",
        )
        self.cancellation_reason = require_text(
            reason,
            "Cancellation reason",
        )

        self._record_event(
            "replenishment_plan_cancelled",
            actor_id=actor_id,
            details={"reason": reason},
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
            ReplenishmentPlanStatus.COMPLETED,
            ReplenishmentPlanStatus.REJECTED,
            ReplenishmentPlanStatus.CANCELLED,
            ReplenishmentPlanStatus.FAILED,
        }:
            raise ValueError(
                "Plan cannot be archived"
            )

        self.status = ReplenishmentPlanStatus.ARCHIVED

        self._record_event(
            "replenishment_plan_archived",
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
            ReplenishmentPlanStatus.DRAFT,
            ReplenishmentPlanStatus.REJECTED,
            ReplenishmentPlanStatus.CANCELLED,
            ReplenishmentPlanStatus.ARCHIVED,
        }:
            raise ValueError(
                "Plan cannot be deleted"
            )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = require_text(
            actor_id,
            "Actor ID",
        )

        self._record_event(
            "replenishment_plan_soft_deleted",
            actor_id=actor_id,
        )

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(
        self,
        *,
        include_items: bool = True,
        include_history: bool = False,
    ) -> dict[str, Any]:
        result = {
            "id": self.id,
            "organization_id": self.organization_id,
            "plan_number": self.plan_number,
            "title": self.title,
            "description": self.description,
            "status": enum_value(self.status),
            "plan_type": enum_value(self.plan_type),
            "source": enum_value(self.source),
            "priority": enum_value(self.priority),
            "strategy": enum_value(self.strategy),

            "warehouse_id": self.warehouse_id,
            "destination_warehouse_id": (
                self.destination_warehouse_id
            ),
            "preferred_supplier_id": (
                self.preferred_supplier_id
            ),

            "demand_forecast_id": (
                self.demand_forecast_id
            ),
            "supplier_risk_id": self.supplier_risk_id,
            "model_registry_id": (
                self.model_registry_id
            ),
            "agent_run_id": self.agent_run_id,
            "simulation_id": self.simulation_id,

            "planning_start_at": iso(
                self.planning_start_at
            ),
            "planning_end_at": iso(
                self.planning_end_at
            ),
            "planned_execution_at": iso(
                self.planned_execution_at
            ),
            "expected_completion_at": iso(
                self.expected_completion_at
            ),
            "execution_started_at": iso(
                self.execution_started_at
            ),
            "executed_at": iso(self.executed_at),
            "completed_at": iso(self.completed_at),

            "currency": self.currency,
            "budget_amount": decimal_string(
                self.budget_amount
            ),
            "estimated_total_cost": decimal_string(
                self.estimated_total_cost
            ),
            "actual_total_cost": decimal_string(
                self.actual_total_cost
            ),
            "is_over_budget": self.is_over_budget,
            "budget_override_approved": (
                self.budget_override_approved
            ),

            "ai_generated": self.ai_generated,
            "ai_model_id": self.ai_model_id,
            "ai_confidence": decimal_string(
                self.ai_confidence
            ),
            "forecast_confidence": decimal_string(
                self.forecast_confidence
            ),
            "ai_recommendation": (
                self.ai_recommendation
            ),
            "ai_explanation": self.ai_explanation,
            "stockout_risk_level": enum_value(
                self.stockout_risk_level
            ),

            "requires_approval": self.requires_approval,
            "approval_status": enum_value(
                self.approval_status
            ),
            "approval_request_id": (
                self.approval_request_id
            ),
            "approved_by": self.approved_by,
            "approved_at": iso(self.approved_at),
            "rejection_reason": self.rejection_reason,

            "purchase_order_ids": (
                self.purchase_order_ids
            ),
            "transfer_order_ids": (
                self.transfer_order_ids
            ),

            "total_planned_quantity": decimal_string(
                self.total_planned_quantity
            ),
            "total_ordered_quantity": decimal_string(
                self.total_ordered_quantity
            ),
            "total_received_quantity": decimal_string(
                self.total_received_quantity
            ),
            "execution_progress": decimal_string(
                self.execution_progress
            ),
            "is_fully_executed": (
                self.is_fully_executed
            ),
            "is_fully_received": (
                self.is_fully_received
            ),
            "is_approved": self.is_approved,
            "is_terminal": self.is_terminal,

            "hold_reason": self.hold_reason,
            "failure_reason": self.failure_reason,
            "cancelled_at": iso(self.cancelled_at),
            "cancellation_reason": (
                self.cancellation_reason
            ),

            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "is_deleted": self.is_deleted,
            "version": self.version,
        }

        if include_items:
            result["items"] = [
                item.to_dict() for item in self.items
            ]

        if include_history:
            result["plan_history"] = (
                self.plan_history
            )

        return result

    def __repr__(self) -> str:
        return (
            f"<ReplenishmentPlan("
            f"id={self.id}, "
            f"plan_number={self.plan_number}, "
            f"status={enum_value(self.status)}"
            f")>"
        )


# ============================================================
# REPLENISHMENT PLAN ITEM
# ============================================================

class ReplenishmentPlanItem(Base):
    __tablename__ = "replenishment_plan_items"

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "plan_id"],
            [
                "replenishment_plans.organization_id",
                "replenishment_plans.id",
            ],
            name="fk_replenishment_item_same_tenant_plan",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "plan_id",
            "line_number",
            name="uq_replenishment_item_line",
        ),
        UniqueConstraint(
            "plan_id",
            "product_id",
            name="uq_replenishment_item_product",
        ),
        CheckConstraint(
            "current_stock >= 0",
            name="replenishment_item_stock_nonnegative",
        ),
        CheckConstraint(
            "reserved_stock >= 0",
            name="replenishment_item_reserved_nonnegative",
        ),
        CheckConstraint(
            "forecast_demand >= 0",
            name="replenishment_item_forecast_nonnegative",
        ),
        CheckConstraint(
            "safety_stock >= 0",
            name="replenishment_item_safety_nonnegative",
        ),
        CheckConstraint(
            "reorder_point >= 0",
            name="replenishment_item_reorder_nonnegative",
        ),
        CheckConstraint(
            "recommended_quantity > 0",
            name="replenishment_item_recommended_positive",
        ),
        CheckConstraint(
            "ordered_quantity >= 0",
            name="replenishment_item_ordered_nonnegative",
        ),
        CheckConstraint(
            "received_quantity >= 0",
            name="replenishment_item_received_nonnegative",
        ),
        CheckConstraint(
            "ordered_quantity <= recommended_quantity",
            name="replenishment_item_ordered_limit",
        ),
        CheckConstraint(
            "received_quantity <= ordered_quantity",
            name="replenishment_item_received_limit",
        ),
        CheckConstraint(
            "estimated_unit_cost >= 0",
            name="replenishment_item_unit_cost_nonnegative",
        ),
        CheckConstraint(
            "estimated_total_cost >= 0",
            name="replenishment_item_total_cost_nonnegative",
        ),
        CheckConstraint(
            "lead_time_days >= 0",
            name="replenishment_item_lead_time_nonnegative",
        ),
        Index(
            "ix_replenishment_item_org_product",
            "organization_id",
            "product_id",
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
    )

    plan_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    line_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # --------------------------------------------------------
    # PRODUCT / SUPPLIER
    # --------------------------------------------------------

    product_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    sku: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    product_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    supplier_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    unit_of_measure: Mapped[str] = mapped_column(
        String(30),
        default="units",
        nullable=False,
    )

    # --------------------------------------------------------
    # INVENTORY / DEMAND
    # --------------------------------------------------------

    current_stock: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    reserved_stock: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    forecast_demand: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    safety_stock: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    reorder_point: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    recommended_quantity: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(18, 4),
        nullable=False,
    )

    ordered_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    received_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=ZERO,
        nullable=False,
    )

    # --------------------------------------------------------
    # SUPPLIER / COST
    # --------------------------------------------------------

    lead_time_days: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    estimated_unit_cost: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    estimated_total_cost: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(20, 4),
        default=ZERO,
        nullable=False,
    )

    # --------------------------------------------------------
    # STATUS
    # --------------------------------------------------------

    status: Mapped[
        ReplenishmentLineStatus
    ] = mapped_column(
        enum_column(
            ReplenishmentLineStatus,
            "replenishment_line_status",
        ),
        default=ReplenishmentLineStatus.PLANNED,
        nullable=False,
    )

    item_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
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

    plan: Mapped["ReplenishmentPlan"] = relationship(
        "ReplenishmentPlan",
        back_populates="items",
    )

    # ========================================================
    # PROPERTIES
    # ========================================================

    @property
    def available_stock(self) -> Decimal:
        return max(
            ZERO,
            self.current_stock - self.reserved_stock,
        )

    @property
    def stock_deficit(self) -> Decimal:
        return max(
            ZERO,
            self.forecast_demand
            + self.safety_stock
            - self.available_stock,
        )

    @property
    def remaining_to_order(self) -> Decimal:
        return (
            self.recommended_quantity
            - self.ordered_quantity
        )

    @property
    def remaining_to_receive(self) -> Decimal:
        return (
            self.ordered_quantity
            - self.received_quantity
        )

    @property
    def is_below_reorder_point(self) -> bool:
        return (
            self.available_stock
            <= self.reorder_point
        )

    # ========================================================
    # CALCULATE RECOMMENDATION
    # ========================================================

    def calculate_recommended_quantity(
        self,
    ) -> Decimal:
        """
        Basic demand coverage calculation.

        This is not a complete stochastic inventory
        optimization algorithm. Advanced models should
        account for lead-time uncertainty, seasonality,
        minimum order quantities and supplier constraints.
        """

        return ceil_quantity(self.stock_deficit)

    # ========================================================
    # RECALCULATE COST
    # ========================================================

    def recalculate(self) -> None:
        self.estimated_total_cost = (
            self.recommended_quantity
            * self.estimated_unit_cost
        ).quantize(QUANTUM)

        self.updated_at = utc_now()

    # ========================================================
    # RECORD ORDERED QUANTITY
    # ========================================================

    def record_ordered(
        self,
        quantity: Decimal | str | int | float,
    ) -> None:
        if self.status == ReplenishmentLineStatus.CANCELLED:
            raise ValueError(
                "Cancelled item cannot be ordered"
            )

        quantity = to_decimal(
            quantity,
            "quantity",
            positive=True,
        )

        if quantity > self.remaining_to_order:
            raise ValueError(
                "Ordered quantity exceeds recommendation"
            )

        self.ordered_quantity += quantity

        if (
            self.ordered_quantity
            >= self.recommended_quantity
        ):
            self.status = ReplenishmentLineStatus.ORDERED
        else:
            self.status = (
                ReplenishmentLineStatus.PARTIALLY_ORDERED
            )

        self.updated_at = utc_now()

    # ========================================================
    # RECORD RECEIVED QUANTITY
    # ========================================================

    def record_received(
        self,
        quantity: Decimal | str | int | float,
    ) -> None:
        if self.status == ReplenishmentLineStatus.CANCELLED:
            raise ValueError(
                "Cancelled item cannot receive stock"
            )

        quantity = to_decimal(
            quantity,
            "quantity",
            positive=True,
        )

        if quantity > self.remaining_to_receive:
            raise ValueError(
                "Received quantity exceeds ordered quantity"
            )

        self.received_quantity += quantity

        if (
            self.received_quantity
            >= self.recommended_quantity
        ):
            self.status = ReplenishmentLineStatus.RECEIVED
        else:
            self.status = (
                ReplenishmentLineStatus.PARTIALLY_RECEIVED
            )

        self.updated_at = utc_now()

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "plan_id": self.plan_id,
            "line_number": self.line_number,
            "product_id": self.product_id,
            "sku": self.sku,
            "product_name": self.product_name,
            "supplier_id": self.supplier_id,
            "unit_of_measure": self.unit_of_measure,

            "current_stock": decimal_string(
                self.current_stock
            ),
            "reserved_stock": decimal_string(
                self.reserved_stock
            ),
            "available_stock": decimal_string(
                self.available_stock
            ),
            "forecast_demand": decimal_string(
                self.forecast_demand
            ),
            "safety_stock": decimal_string(
                self.safety_stock
            ),
            "reorder_point": decimal_string(
                self.reorder_point
            ),
            "stock_deficit": decimal_string(
                self.stock_deficit
            ),
            "recommended_quantity": decimal_string(
                self.recommended_quantity
            ),
            "ordered_quantity": decimal_string(
                self.ordered_quantity
            ),
            "received_quantity": decimal_string(
                self.received_quantity
            ),
            "remaining_to_order": decimal_string(
                self.remaining_to_order
            ),
            "remaining_to_receive": decimal_string(
                self.remaining_to_receive
            ),
            "is_below_reorder_point": (
                self.is_below_reorder_point
            ),

            "lead_time_days": self.lead_time_days,
            "estimated_unit_cost": decimal_string(
                self.estimated_unit_cost
            ),
            "estimated_total_cost": decimal_string(
                self.estimated_total_cost
            ),
            "status": enum_value(self.status),
            "item_metadata": self.item_metadata,
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
        }

    def __repr__(self) -> str:
        return (
            f"<ReplenishmentPlanItem("
            f"id={self.id}, "
            f"product_id={self.product_id}, "
            f"recommended={self.recommended_quantity}, "
            f"ordered={self.ordered_quantity}"
            f")>"
        )
