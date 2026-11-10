from __future__ import annotations

"""Planned module: demand event. Implementation pending."""

"""
backend/models/demand_event.py

Autonomous Retail Supply Chain AI 5.0
Demand Intelligence Event ORM Model

Features:
- Demand spikes and drops
- Seasonal and promotional demand
- AI forecasting events
- Demand anomaly detection
- Product/category/warehouse references
- Actual vs expected demand
- Confidence and severity classification
- Event acknowledgment and resolution
- AI-generated recommendations
- Multi-tenant isolation
- Deduplication
- Optimistic concurrency
- UTC timestamps
- Soft deletion

Requirements:
    Python >= 3.10
    SQLAlchemy >= 2.0

Shared ORM:
    backend.models.base.Base
"""


import enum
import math
import uuid

from datetime import datetime, timezone
from decimal import Decimal
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

from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base


# ============================================================
# UTILITIES
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_event_code() -> str:
    return f"DEM-{uuid.uuid4().hex[:16].upper()}"


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


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def calculate_percentage_change(
    actual: Decimal,
    expected: Decimal,
) -> Decimal | None:
    """
    Return percentage change.

    None indicates an undefined percentage
    when expected demand is zero.
    """
    if expected == 0:
        return None

    return (
        (actual - expected)
        / expected
        * Decimal("100")
    ).quantize(Decimal("0.01"))


# ============================================================
# ENUMS
# ============================================================

class DemandEventType(str, enum.Enum):
    DEMAND_SPIKE = "demand_spike"
    DEMAND_DROP = "demand_drop"
    DEMAND_ANOMALY = "demand_anomaly"

    SEASONAL_INCREASE = "seasonal_increase"
    SEASONAL_DECREASE = "seasonal_decrease"

    PROMOTION_IMPACT = "promotion_impact"
    HOLIDAY_IMPACT = "holiday_impact"
    WEATHER_IMPACT = "weather_impact"

    MARKET_TREND = "market_trend"
    COMPETITOR_IMPACT = "competitor_impact"

    STOCKOUT_RISK = "stockout_risk"
    OVERSTOCK_RISK = "overstock_risk"

    FORECAST_DEVIATION = "forecast_deviation"
    FORECAST_UPDATE = "forecast_update"

    NEW_PRODUCT_DEMAND = "new_product_demand"
    CUSTOMER_BEHAVIOR_CHANGE = "customer_behavior_change"

    SUPPLY_DISRUPTION = "supply_disruption"
    OTHER = "other"


class DemandEventStatus(str, enum.Enum):
    DETECTED = "detected"
    VALIDATED = "validated"
    ACKNOWLEDGED = "acknowledged"
    INVESTIGATING = "investigating"
    ACTION_REQUIRED = "action_required"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
    EXPIRED = "expired"


class DemandEventSeverity(str, enum.Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DemandEventSource(str, enum.Enum):
    ML_MODEL = "ml_model"
    FORECAST_ENGINE = "forecast_engine"
    ANOMALY_DETECTOR = "anomaly_detector"
    RULE_ENGINE = "rule_engine"
    AI_AGENT = "ai_agent"
    SALES_SYSTEM = "sales_system"
    ERP = "erp"
    MARKET_DATA = "market_data"
    USER = "user"
    OTHER = "other"


class DemandDirection(str, enum.Enum):
    INCREASE = "increase"
    DECREASE = "decrease"
    STABLE = "stable"
    UNKNOWN = "unknown"


# ============================================================
# DEMAND EVENT MODEL
# ============================================================

class DemandEvent(Base):
    __tablename__ = "demand_events"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "event_code",
            name="uq_demand_event_org_code",
        ),
        UniqueConstraint(
            "organization_id",
            "deduplication_key",
            name="uq_demand_event_org_dedup",
        ),
        CheckConstraint(
            "expected_demand IS NULL OR expected_demand >= 0",
            name="demand_event_expected_nonnegative",
        ),
        CheckConstraint(
            "actual_demand IS NULL OR actual_demand >= 0",
            name="demand_event_actual_nonnegative",
        ),
        CheckConstraint(
            "forecast_demand IS NULL OR forecast_demand >= 0",
            name="demand_event_forecast_nonnegative",
        ),
        CheckConstraint(
            "confidence_score IS NULL OR "
            "(confidence_score >= 0 AND confidence_score <= 1)",
            name="demand_event_confidence_range",
        ),
        CheckConstraint(
            "anomaly_score IS NULL OR "
            "(anomaly_score >= 0 AND anomaly_score <= 1)",
            name="demand_event_anomaly_range",
        ),
        CheckConstraint(
            "occurrence_count >= 1",
            name="demand_event_occurrence_positive",
        ),
        CheckConstraint(
            "event_end_at IS NULL OR "
            "event_end_at >= event_start_at",
            name="demand_event_valid_period",
        ),
        Index(
            "ix_demand_event_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_demand_event_org_type",
            "organization_id",
            "event_type",
        ),
        Index(
            "ix_demand_event_org_severity",
            "organization_id",
            "severity",
        ),
        Index(
            "ix_demand_event_org_product",
            "organization_id",
            "product_id",
        ),
        Index(
            "ix_demand_event_org_warehouse",
            "organization_id",
            "warehouse_id",
        ),
        Index(
            "ix_demand_event_org_start",
            "organization_id",
            "event_start_at",
        ),
        Index(
            "ix_demand_event_org_detected",
            "organization_id",
            "detected_at",
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

    event_code: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=generate_event_code,
    )

    deduplication_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # --------------------------------------------------------
    # ENTITY REFERENCES
    # --------------------------------------------------------

    product_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )

    category_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    warehouse_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )

    supplier_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    region_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    sales_channel: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # --------------------------------------------------------
    # EVENT INFORMATION
    # --------------------------------------------------------

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    event_type: Mapped[DemandEventType] = mapped_column(
        enum_column(
            DemandEventType,
            "demand_event_type",
        ),
        nullable=False,
    )

    status: Mapped[DemandEventStatus] = mapped_column(
        enum_column(
            DemandEventStatus,
            "demand_event_status",
        ),
        default=DemandEventStatus.DETECTED,
        nullable=False,
    )

    severity: Mapped[DemandEventSeverity] = mapped_column(
        enum_column(
            DemandEventSeverity,
            "demand_event_severity",
        ),
        default=DemandEventSeverity.INFO,
        nullable=False,
    )

    source: Mapped[DemandEventSource] = mapped_column(
        enum_column(
            DemandEventSource,
            "demand_event_source",
        ),
        default=DemandEventSource.RULE_ENGINE,
        nullable=False,
    )

    direction: Mapped[DemandDirection] = mapped_column(
        enum_column(
            DemandDirection,
            "demand_direction",
        ),
        default=DemandDirection.UNKNOWN,
        nullable=False,
    )

    # --------------------------------------------------------
    # DEMAND METRICS
    # --------------------------------------------------------

    expected_demand: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    actual_demand: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    forecast_demand: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    demand_difference: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 4),
        nullable=True,
    )

    percentage_change: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )

    unit_of_measure: Mapped[str] = mapped_column(
        String(30),
        default="units",
        nullable=False,
    )

    # --------------------------------------------------------
    # AI / ML DETECTION
    # --------------------------------------------------------

    confidence_score: Mapped[float | None] = mapped_column(
        nullable=True,
    )

    anomaly_score: Mapped[float | None] = mapped_column(
        nullable=True,
    )

    model_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    model_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    forecast_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    agent_action_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # AI RECOMMENDATIONS
    # --------------------------------------------------------

    root_cause: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    ai_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    recommended_action: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    requires_action: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    requires_human_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    approval_request_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # STRUCTURED EVENT DATA
    # --------------------------------------------------------

    event_payload: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    contributing_factors: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    analysis_metadata: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # EVENT TIMELINE
    # --------------------------------------------------------

    event_start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    event_end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    last_occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    occurrence_count: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # ACKNOWLEDGMENT
    # --------------------------------------------------------

    acknowledged_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # RESOLUTION
    # --------------------------------------------------------

    resolved_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    resolution_note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
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
    # OBSERVABILITY
    # --------------------------------------------------------

    trace_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    correlation_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # --------------------------------------------------------
    # AUDIT TIMESTAMPS
    # --------------------------------------------------------

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
    def is_terminal(self) -> bool:
        return self.status in {
            DemandEventStatus.RESOLVED,
            DemandEventStatus.DISMISSED,
            DemandEventStatus.EXPIRED,
        }

    @property
    def is_critical(self) -> bool:
        return (
            self.severity
            == DemandEventSeverity.CRITICAL
        )

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False

        return normalize_datetime(
            self.expires_at
        ) <= utc_now()

    @property
    def needs_attention(self) -> bool:
        return (
            not self.is_deleted
            and not self.is_terminal
            and not self.is_expired
            and self.requires_action
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_actionable(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Demand event has been deleted"
            )

        if self.is_terminal:
            raise ValueError(
                "Demand event is already terminal"
            )

        if self.is_expired:
            raise ValueError(
                "Demand event has expired"
            )

    # ========================================================
    # UPDATE DEMAND METRICS
    # ========================================================

    def update_demand_metrics(
        self,
        *,
        actual: Decimal | float | int,
        expected: Decimal | float | int,
        forecast: Decimal | float | int | None = None,
    ) -> None:
        self._ensure_actionable()

        actual_value = Decimal(str(actual))
        expected_value = Decimal(str(expected))

        if not actual_value.is_finite():
            raise ValueError("Actual demand must be finite")

        if not expected_value.is_finite():
            raise ValueError("Expected demand must be finite")

        if actual_value < 0 or expected_value < 0:
            raise ValueError(
                "Demand cannot be negative"
            )

        self.actual_demand = actual_value
        self.expected_demand = expected_value
        self.demand_difference = (
            actual_value - expected_value
        )

        self.percentage_change = (
            calculate_percentage_change(
                actual_value,
                expected_value,
            )
        )

        if forecast is not None:
            forecast_value = Decimal(str(forecast))

            if (
                not forecast_value.is_finite()
                or forecast_value < 0
            ):
                raise ValueError(
                    "Forecast demand must be finite and nonnegative"
                )

            self.forecast_demand = forecast_value

        if actual_value > expected_value:
            self.direction = DemandDirection.INCREASE

        elif actual_value < expected_value:
            self.direction = DemandDirection.DECREASE

        else:
            self.direction = DemandDirection.STABLE

        self._touch()

    # ========================================================
    # UPDATE AI ANALYSIS
    # ========================================================

    def update_ai_analysis(
        self,
        *,
        model_name: str,
        confidence: float,
        anomaly_score: float | None = None,
        model_version: str | None = None,
        summary: str | None = None,
        root_cause: str | None = None,
        recommended_action: str | None = None,
    ) -> None:
        self._ensure_actionable()

        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError(
                "Confidence must be between 0 and 1"
            )

        if anomaly_score is not None:
            if (
                not math.isfinite(anomaly_score)
                or not 0 <= anomaly_score <= 1
            ):
                raise ValueError(
                    "Anomaly score must be between 0 and 1"
                )

        self.model_name = model_name
        self.model_version = model_version
        self.confidence_score = confidence
        self.anomaly_score = anomaly_score
        self.ai_summary = summary
        self.root_cause = root_cause
        self.recommended_action = recommended_action

        self._touch()

    # ========================================================
    # VALIDATE EVENT
    # ========================================================

    def validate(self) -> None:
        self._ensure_actionable()

        if self.status != DemandEventStatus.DETECTED:
            raise ValueError(
                "Only detected events can be validated"
            )

        self.status = DemandEventStatus.VALIDATED
        self._touch()

    # ========================================================
    # ACKNOWLEDGE EVENT
    # ========================================================

    def acknowledge(self, user_id: str) -> None:
        self._ensure_actionable()

        if self.status not in {
            DemandEventStatus.DETECTED,
            DemandEventStatus.VALIDATED,
            DemandEventStatus.ACTION_REQUIRED,
        }:
            raise ValueError(
                "Event cannot be acknowledged in current state"
            )

        if not user_id:
            raise ValueError(
                "Acknowledging user is required"
            )

        self.acknowledged_by = user_id
        self.acknowledged_at = utc_now()
        self.status = DemandEventStatus.ACKNOWLEDGED

        self._touch()

    # ========================================================
    # INVESTIGATION
    # ========================================================

    def start_investigation(self) -> None:
        self._ensure_actionable()

        if self.status not in {
            DemandEventStatus.VALIDATED,
            DemandEventStatus.ACKNOWLEDGED,
            DemandEventStatus.ACTION_REQUIRED,
        }:
            raise ValueError(
                "Invalid event state for investigation"
            )

        self.status = DemandEventStatus.INVESTIGATING
        self._touch()

    # ========================================================
    # MARK ACTION REQUIRED
    # ========================================================

    def mark_action_required(
        self,
        recommended_action: str,
        *,
        requires_approval: bool = False,
    ) -> None:
        self._ensure_actionable()

        if not recommended_action.strip():
            raise ValueError(
                "Recommended action is required"
            )

        self.requires_action = True
        self.requires_human_approval = requires_approval
        self.recommended_action = recommended_action
        self.status = DemandEventStatus.ACTION_REQUIRED

        self._touch()

    # ========================================================
    # RESOLVE EVENT
    # ========================================================

    def resolve(
        self,
        *,
        user_id: str,
        resolution_note: str,
    ) -> None:
        self._ensure_actionable()

        if not user_id:
            raise ValueError(
                "Resolving user is required"
            )

        if not resolution_note.strip():
            raise ValueError(
                "Resolution note is required"
            )

        self.status = DemandEventStatus.RESOLVED
        self.resolved_by = user_id
        self.resolved_at = utc_now()
        self.resolution_note = resolution_note
        self.requires_action = False

        self._touch()

    # ========================================================
    # DISMISS EVENT
    # ========================================================

    def dismiss(
        self,
        *,
        user_id: str,
        reason: str,
    ) -> None:
        self._ensure_actionable()

        if not user_id:
            raise ValueError(
                "Dismissing user is required"
            )

        if not reason.strip():
            raise ValueError(
                "Dismissal reason is required"
            )

        self.status = DemandEventStatus.DISMISSED
        self.resolved_by = user_id
        self.resolved_at = utc_now()
        self.resolution_note = reason
        self.requires_action = False

        self._touch()

    # ========================================================
    # EXPIRE EVENT
    # ========================================================

    def expire(self) -> None:
        if self.is_terminal:
            raise ValueError(
                "Terminal event cannot expire"
            )

        if not self.is_expired:
            raise ValueError(
                "Event has not reached expiration"
            )

        self.status = DemandEventStatus.EXPIRED
        self.requires_action = False
        self._touch()

    # ========================================================
    # RECORD REPEATED OCCURRENCE
    # ========================================================

    def record_occurrence(self) -> None:
        self._ensure_actionable()

        self.occurrence_count += 1
        self.last_occurred_at = utc_now()

        self._touch()

    # ========================================================
    # SOFT DELETE
    # ========================================================

    def soft_delete(self, user_id: str) -> None:
        if self.is_deleted:
            raise ValueError(
                "Demand event is already deleted"
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

        def decimal_value(
            value: Decimal | None,
        ) -> str | None:
            return str(value) if value is not None else None

        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "event_code": self.event_code,
            "deduplication_key": self.deduplication_key,
            "product_id": self.product_id,
            "category_id": self.category_id,
            "warehouse_id": self.warehouse_id,
            "supplier_id": self.supplier_id,
            "region_id": self.region_id,
            "sales_channel": self.sales_channel,
            "title": self.title,
            "description": self.description,
            "event_type": self.event_type.value,
            "status": self.status.value,
            "severity": self.severity.value,
            "source": self.source.value,
            "direction": self.direction.value,
            "expected_demand": decimal_value(
                self.expected_demand
            ),
            "actual_demand": decimal_value(
                self.actual_demand
            ),
            "forecast_demand": decimal_value(
                self.forecast_demand
            ),
            "demand_difference": decimal_value(
                self.demand_difference
            ),
            "percentage_change": decimal_value(
                self.percentage_change
            ),
            "unit_of_measure": self.unit_of_measure,
            "confidence_score": self.confidence_score,
            "anomaly_score": self.anomaly_score,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "forecast_run_id": self.forecast_run_id,
            "agent_run_id": self.agent_run_id,
            "agent_action_id": self.agent_action_id,
            "root_cause": self.root_cause,
            "ai_summary": self.ai_summary,
            "recommended_action": self.recommended_action,
            "requires_action": self.requires_action,
            "requires_human_approval": (
                self.requires_human_approval
            ),
            "approval_request_id": (
                self.approval_request_id
            ),
            "event_payload": self.event_payload,
            "contributing_factors": (
                self.contributing_factors
            ),
            "analysis_metadata": self.analysis_metadata,
            "event_start_at": dt(self.event_start_at),
            "event_end_at": dt(self.event_end_at),
            "detected_at": dt(self.detected_at),
            "last_occurred_at": dt(
                self.last_occurred_at
            ),
            "occurrence_count": self.occurrence_count,
            "expires_at": dt(self.expires_at),
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": dt(self.acknowledged_at),
            "resolved_by": self.resolved_by,
            "resolved_at": dt(self.resolved_at),
            "resolution_note": self.resolution_note,
            "is_deleted": self.is_deleted,
            "deleted_at": dt(self.deleted_at),
            "deleted_by": self.deleted_by,
            "needs_attention": self.needs_attention,
            "is_critical": self.is_critical,
            "trace_id": self.trace_id,
            "correlation_id": self.correlation_id,
            "version": self.version,
            "created_at": dt(self.created_at),
            "updated_at": dt(self.updated_at),
        }

    def __repr__(self) -> str:
        return (
            f"<DemandEvent("
            f"id={self.id}, "
            f"type={self.event_type.value}, "
            f"status={self.status.value}, "
            f"severity={self.severity.value}"
            f")>"
        )
