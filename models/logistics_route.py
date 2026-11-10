from __future__ import annotations

"""Planned module: market trend. Implementation pending."""

"""
backend/models/logistics_route.py

Autonomous Retail Supply Chain AI 5.0
Enterprise Logistics Route Management ORM

Features:
- Multi-tenant logistics route management
- Multi-stop delivery and pickup routes
- Vehicle and driver assignment
- AI route optimization metadata
- Planned vs actual distance, time and cost
- Traffic, weather and operational risks
- GPS tracking and route deviation detection
- Route lifecycle and dispatch management
- Human approval for consequential actions
- Route performance and delivery metrics
- Optimistic concurrency and audit metadata
- Soft deletion

Requirements:
    Python >= 3.10
    SQLAlchemy >= 2.0

Shared ORM:
    backend.models.base.Base

Notes:
    Route optimization, live GPS ingestion,
    navigation, driver authorization, and
    external notifications belong in services.
"""


import enum
import math
import uuid

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
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


def generate_route_code() -> str:
    return f"RTE-{uuid.uuid4().hex[:16].upper()}"


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


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Invalid decimal value") from None

    if not result.is_finite() or result < 0:
        raise ValueError(
            "Value must be finite and nonnegative"
        )

    if result.as_tuple().exponent < -4:
        raise ValueError(
            "Maximum supported precision is 4 decimal places"
        )

    return result


def validate_probability(value: float, name: str) -> float:
    result = float(value)

    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError(
            f"{name} must be between 0 and 1"
        )

    return result


def validate_coordinates(
    latitude: float,
    longitude: float,
) -> tuple[float, float]:
    lat = float(latitude)
    lon = float(longitude)

    if not math.isfinite(lat) or not -90 <= lat <= 90:
        raise ValueError("Invalid latitude")

    if not math.isfinite(lon) or not -180 <= lon <= 180:
        raise ValueError("Invalid longitude")

    return lat, lon


def datetime_string(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def decimal_string(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


# ============================================================
# ENUMS
# ============================================================

class LogisticsRouteType(str, enum.Enum):
    DELIVERY = "delivery"
    PICKUP = "pickup"
    MIXED = "mixed"
    WAREHOUSE_TRANSFER = "warehouse_transfer"
    SUPPLIER_COLLECTION = "supplier_collection"
    LAST_MILE = "last_mile"
    FIRST_MILE = "first_mile"
    MIDDLE_MILE = "middle_mile"
    RETURN = "return"
    EMERGENCY = "emergency"


class LogisticsRouteStatus(str, enum.Enum):
    DRAFT = "draft"
    PLANNED = "planned"
    OPTIMIZING = "optimizing"
    OPTIMIZED = "optimized"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    DISPATCHED = "dispatched"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class LogisticsRoutePriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    EMERGENCY = "emergency"


class LogisticsRouteSource(str, enum.Enum):
    MANUAL = "manual"
    ERP = "erp"
    WMS = "wms"
    TMS = "tms"
    LOGISTICS_API = "logistics_api"
    AI_AGENT = "ai_agent"
    OPTIMIZATION_ENGINE = "optimization_engine"
    SYSTEM = "system"


class RouteOptimizationObjective(str, enum.Enum):
    MINIMIZE_DISTANCE = "minimize_distance"
    MINIMIZE_TIME = "minimize_time"
    MINIMIZE_COST = "minimize_cost"
    MINIMIZE_FUEL = "minimize_fuel"
    MINIMIZE_EMISSIONS = "minimize_emissions"
    MAXIMIZE_ON_TIME_DELIVERY = "maximize_on_time_delivery"
    BALANCED = "balanced"


class RouteRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class RouteStopStatus(str, enum.Enum):
    PENDING = "pending"
    ARRIVED = "arrived"
    IN_SERVICE = "in_service"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class RouteStopType(str, enum.Enum):
    ORIGIN = "origin"
    DELIVERY = "delivery"
    PICKUP = "pickup"
    TRANSFER = "transfer"
    BREAK = "break"
    DESTINATION = "destination"


# ============================================================
# LOGISTICS ROUTE MODEL
# ============================================================

class LogisticsRoute(Base):
    __tablename__ = "logistics_routes"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "route_code",
            name="uq_logistics_route_org_code",
        ),
        CheckConstraint(
            "planned_distance_km >= 0",
            name="route_planned_distance_nonnegative",
        ),
        CheckConstraint(
            "actual_distance_km >= 0",
            name="route_actual_distance_nonnegative",
        ),
        CheckConstraint(
            "planned_duration_minutes >= 0",
            name="route_planned_duration_nonnegative",
        ),
        CheckConstraint(
            "actual_duration_minutes >= 0",
            name="route_actual_duration_nonnegative",
        ),
        CheckConstraint(
            "estimated_cost >= 0",
            name="route_estimated_cost_nonnegative",
        ),
        CheckConstraint(
            "actual_cost >= 0",
            name="route_actual_cost_nonnegative",
        ),
        CheckConstraint(
            "estimated_fuel_liters >= 0",
            name="route_estimated_fuel_nonnegative",
        ),
        CheckConstraint(
            "actual_fuel_liters >= 0",
            name="route_actual_fuel_nonnegative",
        ),
        CheckConstraint(
            "total_stops >= 0",
            name="route_stops_nonnegative",
        ),
        CheckConstraint(
            "completed_stops >= 0",
            name="route_completed_stops_nonnegative",
        ),
        CheckConstraint(
            "failed_stops >= 0",
            name="route_failed_stops_nonnegative",
        ),
        CheckConstraint(
            "completed_stops + failed_stops <= total_stops",
            name="route_stop_counts_valid",
        ),
        CheckConstraint(
            "deviation_count >= 0",
            name="route_deviation_nonnegative",
        ),
        CheckConstraint(
            "ai_confidence IS NULL OR "
            "(ai_confidence >= 0 AND ai_confidence <= 1)",
            name="route_ai_confidence_range",
        ),
        CheckConstraint(
            "delay_probability IS NULL OR "
            "(delay_probability >= 0 AND delay_probability <= 1)",
            name="route_delay_probability_range",
        ),
        CheckConstraint(
            "risk_score IS NULL OR "
            "(risk_score >= 0 AND risk_score <= 1)",
            name="route_risk_score_range",
        ),
        Index(
            "ix_route_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_route_org_warehouse",
            "organization_id",
            "origin_warehouse_id",
        ),
        Index(
            "ix_route_org_driver",
            "organization_id",
            "driver_id",
        ),
        Index(
            "ix_route_org_vehicle",
            "organization_id",
            "vehicle_id",
        ),
        Index(
            "ix_route_org_departure",
            "organization_id",
            "planned_departure_at",
        ),
        Index(
            "ix_route_org_risk",
            "organization_id",
            "risk_level",
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

    route_code: Mapped[str] = mapped_column(
        String(40),
        default=generate_route_code,
        nullable=False,
    )

    external_route_id: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    # --------------------------------------------------------
    # ROUTE INFORMATION
    # --------------------------------------------------------

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    route_type: Mapped[LogisticsRouteType] = mapped_column(
        enum_column(
            LogisticsRouteType,
            "logistics_route_type",
        ),
        default=LogisticsRouteType.DELIVERY,
        nullable=False,
    )

    status: Mapped[LogisticsRouteStatus] = mapped_column(
        enum_column(
            LogisticsRouteStatus,
            "logistics_route_status",
        ),
        default=LogisticsRouteStatus.DRAFT,
        nullable=False,
    )

    priority: Mapped[LogisticsRoutePriority] = mapped_column(
        enum_column(
            LogisticsRoutePriority,
            "logistics_route_priority",
        ),
        default=LogisticsRoutePriority.NORMAL,
        nullable=False,
    )

    source: Mapped[LogisticsRouteSource] = mapped_column(
        enum_column(
            LogisticsRouteSource,
            "logistics_route_source",
        ),
        default=LogisticsRouteSource.SYSTEM,
        nullable=False,
    )

    # --------------------------------------------------------
    # WAREHOUSE AND DELIVERY REFERENCES
    # --------------------------------------------------------

    origin_warehouse_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    destination_warehouse_id: Mapped[
        str | None
    ] = mapped_column(
        String(36),
        nullable=True,
    )

    delivery_batch_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    fulfillment_order_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    logistics_provider_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    integration_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # DRIVER AND VEHICLE
    # --------------------------------------------------------

    driver_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    vehicle_id: Mapped[str | None] = mapped_column(
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

    # --------------------------------------------------------
    # ORIGIN AND DESTINATION
    # --------------------------------------------------------

    origin_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    origin_latitude: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    origin_longitude: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    destination_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    destination_latitude: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    destination_longitude: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    # --------------------------------------------------------
    # MULTI-STOP ROUTE
    # --------------------------------------------------------

    # For high-volume production systems, individual stops
    # should also be stored in a dedicated route_stops table.
    stops: Mapped[list[dict[str, Any]]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    total_stops: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    completed_stops: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    failed_stops: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # --------------------------------------------------------
    # SCHEDULE
    # --------------------------------------------------------

    planned_departure_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    planned_arrival_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    actual_departure_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    actual_arrival_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    predicted_arrival_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # DISTANCE AND DURATION
    # --------------------------------------------------------

    planned_distance_km: Mapped[Decimal] = mapped_column(
        Numeric(14, 4),
        default=Decimal("0"),
        nullable=False,
    )

    actual_distance_km: Mapped[Decimal] = mapped_column(
        Numeric(14, 4),
        default=Decimal("0"),
        nullable=False,
    )

    planned_duration_minutes: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    actual_duration_minutes: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    # --------------------------------------------------------
    # COST AND FUEL
    # --------------------------------------------------------

    currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    estimated_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    actual_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        default=Decimal("0"),
        nullable=False,
    )

    estimated_fuel_liters: Mapped[Decimal] = mapped_column(
        Numeric(14, 4),
        default=Decimal("0"),
        nullable=False,
    )

    actual_fuel_liters: Mapped[Decimal] = mapped_column(
        Numeric(14, 4),
        default=Decimal("0"),
        nullable=False,
    )

    estimated_emissions_kg: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(14, 4),
        nullable=True,
    )

    actual_emissions_kg: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(14, 4),
        nullable=True,
    )

    # --------------------------------------------------------
    # AI ROUTE OPTIMIZATION
    # --------------------------------------------------------

    optimization_objective: Mapped[
        RouteOptimizationObjective
    ] = mapped_column(
        enum_column(
            RouteOptimizationObjective,
            "route_optimization_objective",
        ),
        default=RouteOptimizationObjective.BALANCED,
        nullable=False,
    )

    is_optimized: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    optimization_model: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    optimization_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    optimized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    ai_confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    ai_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    ai_recommendation: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    optimization_metadata: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
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
    # RISK ANALYSIS
    # --------------------------------------------------------

    risk_level: Mapped[RouteRiskLevel] = mapped_column(
        enum_column(
            RouteRiskLevel,
            "logistics_route_risk_level",
        ),
        default=RouteRiskLevel.UNKNOWN,
        nullable=False,
    )

    risk_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    delay_probability: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    traffic_risk: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    weather_risk: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    road_condition_risk: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    risk_factors: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # --------------------------------------------------------
    # GPS TRACKING
    # --------------------------------------------------------

    current_latitude: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    current_longitude: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    last_location_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    deviation_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    last_deviation_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # APPROVAL
    # --------------------------------------------------------

    requires_human_approval: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
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
    # EXECUTION AND RESULTS
    # --------------------------------------------------------

    dispatch_reference: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    cancellation_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # METADATA
    # --------------------------------------------------------

    route_metadata: Mapped[
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
    def is_terminal(self) -> bool:
        return self.status in {
            LogisticsRouteStatus.COMPLETED,
            LogisticsRouteStatus.FAILED,
            LogisticsRouteStatus.CANCELLED,
        }

    @property
    def is_active(self) -> bool:
        return (
            not self.is_deleted
            and self.status in {
                LogisticsRouteStatus.DISPATCHED,
                LogisticsRouteStatus.IN_PROGRESS,
                LogisticsRouteStatus.PAUSED,
            }
        )

    @property
    def pending_stops(self) -> int:
        return max(
            0,
            self.total_stops
            - self.completed_stops
            - self.failed_stops,
        )

    @property
    def completion_rate(self) -> float | None:
        if self.total_stops == 0:
            return None

        return self.completed_stops / self.total_stops

    @property
    def distance_variance_km(self) -> Decimal:
        return (
            self.actual_distance_km
            - self.planned_distance_km
        )

    @property
    def cost_variance(self) -> Decimal:
        return self.actual_cost - self.estimated_cost

    @property
    def is_delayed(self) -> bool:
        if self.is_terminal:
            if (
                self.status == LogisticsRouteStatus.COMPLETED
                and self.planned_arrival_at
                and self.actual_arrival_at
            ):
                return (
                    as_utc(self.actual_arrival_at)
                    > as_utc(self.planned_arrival_at)
                )
            return False

        if self.planned_arrival_at is None:
            return False

        return utc_now() > as_utc(self.planned_arrival_at)

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_actionable(self) -> None:
        if self.is_deleted:
            raise ValueError("Route is deleted")

        if self.is_terminal:
            raise ValueError(
                "Route is completed, failed or cancelled"
            )

    def _invalidate_approval(self) -> None:
        self.approved_by = None
        self.approved_at = None
        self.approval_request_id = None

    def _find_stop_index(self, stop_id: str) -> int:
        for index, stop in enumerate(self.stops or []):
            if stop.get("id") == stop_id:
                return index

        raise ValueError("Route stop not found")

    # ========================================================
    # ADD ROUTE STOP
    # ========================================================

    def add_stop(
        self,
        *,
        name: str,
        latitude: float,
        longitude: float,
        stop_type: RouteStopType = RouteStopType.DELIVERY,
        delivery_id: str | None = None,
        planned_arrival_at: datetime | None = None,
        service_minutes: int = 0,
    ) -> str:
        self._ensure_actionable()

        if self.status not in {
            LogisticsRouteStatus.DRAFT,
            LogisticsRouteStatus.PLANNED,
            LogisticsRouteStatus.OPTIMIZED,
        }:
            raise ValueError(
                "Stops cannot be changed after approval "
                "or dispatch"
            )

        if not name.strip():
            raise ValueError("Stop name is required")

        if (
            isinstance(service_minutes, bool)
            or not isinstance(service_minutes, int)
            or service_minutes < 0
        ):
            raise ValueError(
                "Service minutes must be nonnegative"
            )

        lat, lon = validate_coordinates(
            latitude,
            longitude,
        )

        stop_id = generate_uuid()
        stops = list(self.stops or [])

        stops.append(
            {
                "id": stop_id,
                "sequence": len(stops) + 1,
                "name": name,
                "latitude": lat,
                "longitude": lon,
                "stop_type": stop_type.value,
                "delivery_id": delivery_id,
                "planned_arrival_at": (
                    datetime_string(planned_arrival_at)
                ),
                "actual_arrival_at": None,
                "completed_at": None,
                "service_minutes": service_minutes,
                "status": RouteStopStatus.PENDING.value,
            }
        )

        self.stops = stops
        self.total_stops = len(stops)

        self.is_optimized = False
        self.optimized_at = None
        self._invalidate_approval()
        self.status = LogisticsRouteStatus.PLANNED
        self._touch()

        return stop_id

    # ========================================================
    # UPDATE STOP STATUS
    # ========================================================

    def update_stop_status(
        self,
        *,
        stop_id: str,
        status: RouteStopStatus,
    ) -> None:
        self._ensure_actionable()

        if self.status != LogisticsRouteStatus.IN_PROGRESS:
            raise ValueError(
                "Route must be in progress"
            )

        index = self._find_stop_index(stop_id)
        stops = [dict(stop) for stop in self.stops]

        stop = stops[index]
        old_status = RouteStopStatus(stop["status"])

        allowed_transitions = {
            RouteStopStatus.PENDING: {
                RouteStopStatus.ARRIVED,
                RouteStopStatus.SKIPPED,
                RouteStopStatus.FAILED,
            },
            RouteStopStatus.ARRIVED: {
                RouteStopStatus.IN_SERVICE,
                RouteStopStatus.COMPLETED,
                RouteStopStatus.FAILED,
            },
            RouteStopStatus.IN_SERVICE: {
                RouteStopStatus.COMPLETED,
                RouteStopStatus.FAILED,
            },
            RouteStopStatus.COMPLETED: set(),
            RouteStopStatus.SKIPPED: set(),
            RouteStopStatus.FAILED: set(),
        }

        if status not in allowed_transitions[old_status]:
            raise ValueError(
                "Invalid route stop status transition"
            )

        now = utc_now().isoformat()

        stop["status"] = status.value

        if status == RouteStopStatus.ARRIVED:
            stop["actual_arrival_at"] = now

        if status in {
            RouteStopStatus.COMPLETED,
            RouteStopStatus.SKIPPED,
            RouteStopStatus.FAILED,
        }:
            stop["completed_at"] = now

        self.stops = stops

        self.completed_stops = sum(
            stop["status"] == RouteStopStatus.COMPLETED.value
            for stop in stops
        )

        self.failed_stops = sum(
            stop["status"] in {
                RouteStopStatus.FAILED.value,
                RouteStopStatus.SKIPPED.value,
            }
            for stop in stops
        )

        self._touch()

    # ========================================================
    # ASSIGN DRIVER AND VEHICLE
    # ========================================================

    def assign_resources(
        self,
        *,
        driver_id: str,
        vehicle_id: str,
        assigned_by: str,
    ) -> None:
        self._ensure_actionable()

        if self.status not in {
            LogisticsRouteStatus.DRAFT,
            LogisticsRouteStatus.PLANNED,
            LogisticsRouteStatus.OPTIMIZED,
            LogisticsRouteStatus.APPROVED,
        }:
            raise ValueError(
                "Resources cannot be changed in current state"
            )

        if not all((driver_id, vehicle_id, assigned_by)):
            raise ValueError(
                "Driver, vehicle and assigner are required"
            )

        self.driver_id = driver_id
        self.vehicle_id = vehicle_id
        self.assigned_by = assigned_by
        self.assigned_at = utc_now()

        self._invalidate_approval()
        self.status = LogisticsRouteStatus.PLANNED
        self.updated_by = assigned_by
        self._touch()

    # ========================================================
    # UPDATE ROUTE PLAN
    # ========================================================

    def update_plan(
        self,
        *,
        planned_distance_km: Decimal | int | float,
        planned_duration_minutes: int,
        estimated_cost: Decimal | int | float,
        estimated_fuel_liters: Decimal | int | float,
        departure_at: datetime,
        arrival_at: datetime,
    ) -> None:
        self._ensure_actionable()

        if self.status not in {
            LogisticsRouteStatus.DRAFT,
            LogisticsRouteStatus.PLANNED,
            LogisticsRouteStatus.OPTIMIZED,
        }:
            raise ValueError(
                "Route plan cannot be changed now"
            )

        if (
            isinstance(planned_duration_minutes, bool)
            or not isinstance(planned_duration_minutes, int)
            or planned_duration_minutes < 0
        ):
            raise ValueError(
                "Duration must be a nonnegative integer"
            )

        if as_utc(arrival_at) <= as_utc(departure_at):
            raise ValueError(
                "Arrival must be after departure"
            )

        self.planned_distance_km = to_decimal(
            planned_distance_km
        )
        self.planned_duration_minutes = (
            planned_duration_minutes
        )
        self.estimated_cost = to_decimal(estimated_cost)
        self.estimated_fuel_liters = to_decimal(
            estimated_fuel_liters
        )
        self.planned_departure_at = departure_at
        self.planned_arrival_at = arrival_at

        self.is_optimized = False
        self.optimized_at = None
        self._invalidate_approval()
        self.status = LogisticsRouteStatus.PLANNED
        self._touch()

    # ========================================================
    # RECORD AI OPTIMIZATION
    # ========================================================

    def record_optimization(
        self,
        *,
        model_name: str,
        confidence: float,
        summary: str,
        recommendation: str,
        optimized_distance_km: Decimal | int | float,
        optimized_duration_minutes: int,
        optimized_cost: Decimal | int | float,
        optimization_metadata: dict[str, Any] | None = None,
    ) -> None:
        self._ensure_actionable()

        if self.status not in {
            LogisticsRouteStatus.PLANNED,
            LogisticsRouteStatus.OPTIMIZING,
            LogisticsRouteStatus.OPTIMIZED,
        }:
            raise ValueError(
                "Route must be planned before optimization"
            )

        if not model_name.strip():
            raise ValueError("Model name is required")

        if (
            isinstance(optimized_duration_minutes, bool)
            or not isinstance(optimized_duration_minutes, int)
            or optimized_duration_minutes < 0
        ):
            raise ValueError(
                "Optimized duration must be nonnegative"
            )

        self.optimization_model = model_name
        self.ai_confidence = validate_probability(
            confidence,
            "confidence",
        )
        self.ai_summary = summary
        self.ai_recommendation = recommendation
        self.planned_distance_km = to_decimal(
            optimized_distance_km
        )
        self.planned_duration_minutes = (
            optimized_duration_minutes
        )
        self.estimated_cost = to_decimal(optimized_cost)
        self.optimization_metadata = (
            dict(optimization_metadata or {})
        )

        self.is_optimized = True
        self.optimized_at = utc_now()
        self._invalidate_approval()
        self.status = LogisticsRouteStatus.OPTIMIZED
        self._touch()

    # ========================================================
    # UPDATE RISK
    # ========================================================

    def update_risk(
        self,
        *,
        risk_level: RouteRiskLevel,
        risk_score: float,
        delay_probability: float,
        traffic_risk: str | None = None,
        weather_risk: str | None = None,
        road_condition_risk: str | None = None,
    ) -> None:
        self._ensure_actionable()

        self.risk_level = risk_level
        self.risk_score = validate_probability(
            risk_score,
            "risk_score",
        )
        self.delay_probability = validate_probability(
            delay_probability,
            "delay_probability",
        )
        self.traffic_risk = traffic_risk
        self.weather_risk = weather_risk
        self.road_condition_risk = road_condition_risk
        self._touch()

    # ========================================================
    # REQUEST APPROVAL
    # ========================================================

    def request_approval(
        self,
        approval_request_id: str,
    ) -> None:
        self._ensure_actionable()

        if self.status not in {
            LogisticsRouteStatus.PLANNED,
            LogisticsRouteStatus.OPTIMIZED,
        }:
            raise ValueError(
                "Route must be planned or optimized"
            )

        if not approval_request_id:
            raise ValueError(
                "Approval request ID is required"
            )

        self.approval_request_id = approval_request_id
        self.approved_by = None
        self.approved_at = None
        self.status = LogisticsRouteStatus.PENDING_APPROVAL
        self._touch()

    # ========================================================
    # APPROVE ROUTE
    # ========================================================

    def approve(self, user_id: str) -> None:
        self._ensure_actionable()

        if self.status != (
            LogisticsRouteStatus.PENDING_APPROVAL
        ):
            raise ValueError(
                "Route is not pending approval"
            )

        if not user_id:
            raise ValueError("Approver ID is required")

        # The service must verify that the referenced
        # approval request is approved and belongs to
        # this route, organization and current revision.
        self.approved_by = user_id
        self.approved_at = utc_now()
        self.status = LogisticsRouteStatus.APPROVED
        self._touch()

    # ========================================================
    # DISPATCH
    # ========================================================

    def dispatch(
        self,
        *,
        dispatch_reference: str,
    ) -> None:
        self._ensure_actionable()

        if self.requires_human_approval:
            if self.status != LogisticsRouteStatus.APPROVED:
                raise ValueError(
                    "Route requires verified approval"
                )
        elif self.status not in {
            LogisticsRouteStatus.PLANNED,
            LogisticsRouteStatus.OPTIMIZED,
            LogisticsRouteStatus.APPROVED,
        }:
            raise ValueError(
                "Route is not ready for dispatch"
            )

        if not self.driver_id or not self.vehicle_id:
            raise ValueError(
                "Driver and vehicle must be assigned"
            )

        if self.total_stops == 0:
            raise ValueError(
                "Cannot dispatch a route without stops"
            )

        if not dispatch_reference.strip():
            raise ValueError(
                "Dispatch reference is required"
            )

        self.dispatch_reference = dispatch_reference
        self.status = LogisticsRouteStatus.DISPATCHED
        self._touch()

    # ========================================================
    # START ROUTE
    # ========================================================

    def start_route(self) -> None:
        self._ensure_actionable()

        if self.status != LogisticsRouteStatus.DISPATCHED:
            raise ValueError(
                "Route must be dispatched first"
            )

        self.actual_departure_at = utc_now()
        self.status = LogisticsRouteStatus.IN_PROGRESS
        self._touch()

    # ========================================================
    # PAUSE / RESUME
    # ========================================================

    def pause(self) -> None:
        self._ensure_actionable()

        if self.status != LogisticsRouteStatus.IN_PROGRESS:
            raise ValueError(
                "Only in-progress routes can be paused"
            )

        self.status = LogisticsRouteStatus.PAUSED
        self._touch()

    def resume(self) -> None:
        self._ensure_actionable()

        if self.status != LogisticsRouteStatus.PAUSED:
            raise ValueError(
                "Route is not paused"
            )

        self.status = LogisticsRouteStatus.IN_PROGRESS
        self._touch()

    # ========================================================
    # GPS UPDATE
    # ========================================================

    def update_location(
        self,
        *,
        latitude: float,
        longitude: float,
        observed_at: datetime | None = None,
    ) -> None:
        self._ensure_actionable()

        if self.status not in {
            LogisticsRouteStatus.IN_PROGRESS,
            LogisticsRouteStatus.PAUSED,
        }:
            raise ValueError(
                "GPS tracking requires an active route"
            )

        lat, lon = validate_coordinates(
            latitude,
            longitude,
        )

        timestamp = observed_at or utc_now()

        if (
            self.last_location_at is not None
            and as_utc(timestamp)
            < as_utc(self.last_location_at)
        ):
            raise ValueError(
                "Out-of-order GPS observation"
            )

        self.current_latitude = lat
        self.current_longitude = lon
        self.last_location_at = timestamp
        self._touch()

    # ========================================================
    # RECORD ROUTE DEVIATION
    # ========================================================

    def record_deviation(
        self,
        *,
        reason: str,
    ) -> None:
        self._ensure_actionable()

        if self.status not in {
            LogisticsRouteStatus.IN_PROGRESS,
            LogisticsRouteStatus.PAUSED,
        }:
            raise ValueError(
                "Deviation requires an active route"
            )

        if not reason.strip():
            raise ValueError(
                "Deviation reason is required"
            )

        self.deviation_count += 1
        self.last_deviation_at = utc_now()

        metadata = dict(self.route_metadata or {})
        metadata["last_deviation"] = {
            "reason": reason,
            "recorded_at": utc_now().isoformat(),
        }
        self.route_metadata = metadata

        self._touch()

    # ========================================================
    # UPDATE ETA
    # ========================================================

    def update_predicted_arrival(
        self,
        predicted_at: datetime,
    ) -> None:
        self._ensure_actionable()

        if self.status not in {
            LogisticsRouteStatus.DISPATCHED,
            LogisticsRouteStatus.IN_PROGRESS,
            LogisticsRouteStatus.PAUSED,
        }:
            raise ValueError(
                "ETA can only be updated for dispatched routes"
            )

        self.predicted_arrival_at = predicted_at
        self._touch()

    # ========================================================
    # COMPLETE ROUTE
    # ========================================================

    def complete(
        self,
        *,
        actual_distance_km: Decimal | int | float,
        actual_cost: Decimal | int | float,
        actual_fuel_liters: Decimal | int | float,
    ) -> None:
        self._ensure_actionable()

        if self.status != LogisticsRouteStatus.IN_PROGRESS:
            raise ValueError(
                "Route must be in progress"
            )

        if self.pending_stops > 0:
            raise ValueError(
                "All route stops must be finalized"
            )

        if self.failed_stops > 0:
            raise ValueError(
                "Route has failed or skipped stops; "
                "reconcile delivery exceptions before "
                "marking fully completed"
            )

        now = utc_now()

        if self.actual_departure_at is None:
            raise ValueError(
                "Actual departure timestamp is missing"
            )

        self.actual_distance_km = to_decimal(
            actual_distance_km
        )
        self.actual_cost = to_decimal(actual_cost)
        self.actual_fuel_liters = to_decimal(
            actual_fuel_liters
        )
        self.actual_arrival_at = now

        self.actual_duration_minutes = max(
            0,
            int(
                (
                    as_utc(now)
                    - as_utc(self.actual_departure_at)
                ).total_seconds() // 60
            ),
        )

        self.status = LogisticsRouteStatus.COMPLETED
        self.completed_at = now
        self._touch()

    # ========================================================
    # FAIL ROUTE
    # ========================================================

    def fail(self, reason: str) -> None:
        self._ensure_actionable()

        if self.status not in {
            LogisticsRouteStatus.DISPATCHED,
            LogisticsRouteStatus.IN_PROGRESS,
            LogisticsRouteStatus.PAUSED,
        }:
            raise ValueError(
                "Only dispatched or active routes can fail"
            )

        if not reason.strip():
            raise ValueError(
                "Failure reason is required"
            )

        self.failure_reason = reason
        self.status = LogisticsRouteStatus.FAILED
        self._touch()

    # ========================================================
    # CANCEL ROUTE
    # ========================================================

    def cancel(
        self,
        *,
        user_id: str,
        reason: str,
    ) -> None:
        self._ensure_actionable()

        if self.status in {
            LogisticsRouteStatus.DISPATCHED,
            LogisticsRouteStatus.IN_PROGRESS,
            LogisticsRouteStatus.PAUSED,
        }:
            raise ValueError(
                "Dispatched routes require operational "
                "cancellation and driver notification "
                "through the logistics service"
            )

        if not user_id or not reason.strip():
            raise ValueError(
                "User ID and cancellation reason required"
            )

        self.cancellation_reason = reason
        self.status = LogisticsRouteStatus.CANCELLED
        self.updated_by = user_id
        self._touch()

    # ========================================================
    # SOFT DELETE
    # ========================================================

    def soft_delete(self, user_id: str) -> None:
        if self.is_deleted:
            raise ValueError(
                "Route already deleted"
            )

        if not user_id:
            raise ValueError(
                "Deleting user ID required"
            )

        if self.status not in {
            LogisticsRouteStatus.DRAFT,
            LogisticsRouteStatus.CANCELLED,
        }:
            raise ValueError(
                "Only draft or cancelled routes "
                "can be soft deleted"
            )

        self.is_deleted = True
        self.deleted_by = user_id
        self.deleted_at = utc_now()
        self._touch()

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "route_code": self.route_code,
            "external_route_id": self.external_route_id,
            "name": self.name,
            "description": self.description,
            "route_type": self.route_type.value,
            "status": self.status.value,
            "priority": self.priority.value,
            "source": self.source.value,
            "origin_warehouse_id": self.origin_warehouse_id,
            "destination_warehouse_id": (
                self.destination_warehouse_id
            ),
            "delivery_batch_id": self.delivery_batch_id,
            "fulfillment_order_id": (
                self.fulfillment_order_id
            ),
            "logistics_provider_id": (
                self.logistics_provider_id
            ),
            "integration_id": self.integration_id,
            "driver_id": self.driver_id,
            "vehicle_id": self.vehicle_id,
            "assigned_by": self.assigned_by,
            "assigned_at": datetime_string(
                self.assigned_at
            ),
            "origin_name": self.origin_name,
            "origin_latitude": self.origin_latitude,
            "origin_longitude": self.origin_longitude,
            "destination_name": self.destination_name,
            "destination_latitude": self.destination_latitude,
            "destination_longitude": self.destination_longitude,
            "stops": self.stops,
            "total_stops": self.total_stops,
            "completed_stops": self.completed_stops,
            "failed_stops": self.failed_stops,
            "pending_stops": self.pending_stops,
            "completion_rate": self.completion_rate,
            "planned_departure_at": datetime_string(
                self.planned_departure_at
            ),
            "planned_arrival_at": datetime_string(
                self.planned_arrival_at
            ),
            "actual_departure_at": datetime_string(
                self.actual_departure_at
            ),
            "actual_arrival_at": datetime_string(
                self.actual_arrival_at
            ),
            "predicted_arrival_at": datetime_string(
                self.predicted_arrival_at
            ),
            "planned_distance_km": decimal_string(
                self.planned_distance_km
            ),
            "actual_distance_km": decimal_string(
                self.actual_distance_km
            ),
            "distance_variance_km": decimal_string(
                self.distance_variance_km
            ),
            "planned_duration_minutes": (
                self.planned_duration_minutes
            ),
            "actual_duration_minutes": (
                self.actual_duration_minutes
            ),
            "currency": self.currency,
            "estimated_cost": decimal_string(
                self.estimated_cost
            ),
            "actual_cost": decimal_string(
                self.actual_cost
            ),
            "cost_variance": decimal_string(
                self.cost_variance
            ),
            "estimated_fuel_liters": decimal_string(
                self.estimated_fuel_liters
            ),
            "actual_fuel_liters": decimal_string(
                self.actual_fuel_liters
            ),
            "estimated_emissions_kg": decimal_string(
                self.estimated_emissions_kg
            ),
            "actual_emissions_kg": decimal_string(
                self.actual_emissions_kg
            ),
            "optimization_objective": (
                self.optimization_objective.value
            ),
            "is_optimized": self.is_optimized,
            "optimization_model": self.optimization_model,
            "optimization_version": (
                self.optimization_version
            ),
            "optimized_at": datetime_string(
                self.optimized_at
            ),
            "ai_confidence": self.ai_confidence,
            "ai_summary": self.ai_summary,
            "ai_recommendation": self.ai_recommendation,
            "optimization_metadata": (
                self.optimization_metadata
            ),
            "agent_run_id": self.agent_run_id,
            "agent_action_id": self.agent_action_id,
            "risk_level": self.risk_level.value,
            "risk_score": self.risk_score,
            "delay_probability": self.delay_probability,
            "traffic_risk": self.traffic_risk,
            "weather_risk": self.weather_risk,
            "road_condition_risk": self.road_condition_risk,
            "risk_factors": self.risk_factors,
            "current_latitude": self.current_latitude,
            "current_longitude": self.current_longitude,
            "last_location_at": datetime_string(
                self.last_location_at
            ),
            "deviation_count": self.deviation_count,
            "last_deviation_at": datetime_string(
                self.last_deviation_at
            ),
            "requires_human_approval": (
                self.requires_human_approval
            ),
            "approval_request_id": self.approval_request_id,
            "approved_by": self.approved_by,
            "approved_at": datetime_string(
                self.approved_at
            ),
            "dispatch_reference": self.dispatch_reference,
            "failure_reason": self.failure_reason,
            "cancellation_reason": self.cancellation_reason,
            "completed_at": datetime_string(
                self.completed_at
            ),
            "is_active": self.is_active,
            "is_delayed": self.is_delayed,
            "is_deleted": self.is_deleted,
            "route_metadata": self.route_metadata,
            "version": self.version,
            "created_at": datetime_string(
                self.created_at
            ),
            "updated_at": datetime_string(
                self.updated_at
            ),
        }

    def __repr__(self) -> str:
        return (
            f"<LogisticsRoute("
            f"id={self.id}, "
            f"code={self.route_code}, "
            f"status={self.status.value}, "
            f"stops={self.total_stops}"
            f")>"
        )
