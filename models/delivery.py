from __future__ import annotations

"""Planned module: delivery. Implementation pending."""

"""
backend/models/delivery.py

Autonomous Retail Supply Chain AI 5.0
Enterprise Delivery & Logistics ORM Model

Features:
- Multi-tenant delivery management
- Order and warehouse references
- Carrier and shipment tracking
- Delivery status lifecycle
- Estimated and actual delivery timestamps
- Delivery attempt tracking
- Proof-of-delivery metadata
- Failed delivery and return workflows
- AI delay-risk predictions
- Delivery cost and currency
- Optimistic concurrency
- Soft deletion and audit timestamps

Dependencies:
    SQLAlchemy >= 2.0

Uses:
    backend.models.base.Base

Important:
    This module models delivery state.
    External carrier integrations, authorization,
    notifications, and audit events belong in
    separate services.
"""


import enum
import uuid

from datetime import datetime, timezone
from decimal import Decimal
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


def generate_delivery_number() -> str:
    return f"DLV-{uuid.uuid4().hex[:16].upper()}"


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


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


# ============================================================
# ENUMS
# ============================================================

class DeliveryStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY_FOR_PICKUP = "ready_for_pickup"
    PICKED_UP = "picked_up"
    IN_TRANSIT = "in_transit"
    AT_HUB = "at_hub"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERY_ATTEMPTED = "delivery_attempted"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETURN_REQUESTED = "return_requested"
    RETURN_IN_TRANSIT = "return_in_transit"
    RETURNED = "returned"
    CANCELLED = "cancelled"


class DeliveryPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class DeliveryMethod(str, enum.Enum):
    STANDARD = "standard"
    EXPRESS = "express"
    SAME_DAY = "same_day"
    NEXT_DAY = "next_day"
    SCHEDULED = "scheduled"
    PICKUP = "pickup"
    FREIGHT = "freight"


class DeliveryRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class ProofOfDeliveryType(str, enum.Enum):
    NONE = "none"
    SIGNATURE = "signature"
    PHOTO = "photo"
    OTP = "otp"
    DIGITAL_CONFIRMATION = "digital_confirmation"


# ============================================================
# DELIVERY MODEL
# ============================================================

class Delivery(Base):
    __tablename__ = "deliveries"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "delivery_number",
            name="uq_delivery_org_number",
        ),
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_delivery_org_id",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="delivery_attempts_nonnegative",
        ),
        CheckConstraint(
            "max_attempts >= 1",
            name="delivery_max_attempts_positive",
        ),
        CheckConstraint(
            "attempt_count <= max_attempts",
            name="delivery_attempts_limit",
        ),
        CheckConstraint(
            "delivery_cost >= 0",
            name="delivery_cost_nonnegative",
        ),
        CheckConstraint(
            "shipping_fee >= 0",
            name="delivery_shipping_fee_nonnegative",
        ),
        CheckConstraint(
            "weight_kg IS NULL OR weight_kg >= 0",
            name="delivery_weight_nonnegative",
        ),
        CheckConstraint(
            "distance_km IS NULL OR distance_km >= 0",
            name="delivery_distance_nonnegative",
        ),
        CheckConstraint(
            "delay_probability IS NULL OR "
            "(delay_probability >= 0 "
            "AND delay_probability <= 1)",
            name="delivery_delay_probability_range",
        ),
        Index(
            "ix_delivery_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_delivery_org_order",
            "organization_id",
            "order_id",
        ),
        Index(
            "ix_delivery_org_warehouse",
            "organization_id",
            "warehouse_id",
        ),
        Index(
            "ix_delivery_org_eta",
            "organization_id",
            "estimated_delivery_at",
        ),
        Index(
            "ix_delivery_tracking",
            "carrier_name",
            "tracking_number",
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

    delivery_number: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default=generate_delivery_number,
    )

    # --------------------------------------------------------
    # BUSINESS REFERENCES
    # --------------------------------------------------------

    order_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    customer_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )

    warehouse_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
        index=True,
    )

    shipment_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    fleet_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    vehicle_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    driver_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # DELIVERY INFORMATION
    # --------------------------------------------------------

    status: Mapped[DeliveryStatus] = mapped_column(
        enum_column(
            DeliveryStatus,
            "delivery_status",
        ),
        default=DeliveryStatus.PENDING,
        nullable=False,
    )

    priority: Mapped[DeliveryPriority] = mapped_column(
        enum_column(
            DeliveryPriority,
            "delivery_priority",
        ),
        default=DeliveryPriority.NORMAL,
        nullable=False,
    )

    delivery_method: Mapped[DeliveryMethod] = mapped_column(
        enum_column(
            DeliveryMethod,
            "delivery_method",
        ),
        default=DeliveryMethod.STANDARD,
        nullable=False,
    )

    # --------------------------------------------------------
    # CARRIER AND TRACKING
    # --------------------------------------------------------

    carrier_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    carrier_service: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    tracking_number: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    tracking_url: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    # --------------------------------------------------------
    # DESTINATION SNAPSHOT
    # --------------------------------------------------------

    recipient_name: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    recipient_phone: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    address_line1: Mapped[str] = mapped_column(
        String(300),
        nullable=False,
    )

    address_line2: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
    )

    city: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    state: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    postal_code: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    country: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    delivery_instructions: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # TIMELINE
    # --------------------------------------------------------

    scheduled_pickup_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    picked_up_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    estimated_delivery_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    actual_delivery_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_tracking_update_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # PACKAGE DETAILS
    # --------------------------------------------------------

    package_count: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    weight_kg: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 3),
        nullable=True,
    )

    distance_km: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )

    package_details: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # COST
    # --------------------------------------------------------

    currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    delivery_cost: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    shipping_fee: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        default=Decimal("0.00"),
        nullable=False,
    )

    # --------------------------------------------------------
    # DELIVERY ATTEMPTS
    # --------------------------------------------------------

    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    max_attempts: Mapped[int] = mapped_column(
        Integer,
        default=3,
        nullable=False,
    )

    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    failure_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # --------------------------------------------------------
    # PROOF OF DELIVERY
    # --------------------------------------------------------

    proof_type: Mapped[ProofOfDeliveryType] = mapped_column(
        enum_column(
            ProofOfDeliveryType,
            "delivery_proof_type",
        ),
        default=ProofOfDeliveryType.NONE,
        nullable=False,
    )

    proof_reference: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    received_by: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    proof_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # --------------------------------------------------------
    # AI DELIVERY RISK
    # --------------------------------------------------------

    delay_probability: Mapped[float | None] = mapped_column(
        nullable=True,
    )

    risk_level: Mapped[DeliveryRiskLevel] = mapped_column(
        enum_column(
            DeliveryRiskLevel,
            "delivery_risk_level",
        ),
        default=DeliveryRiskLevel.UNKNOWN,
        nullable=False,
    )

    risk_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    ai_recommended_action: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    prediction_model: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    prediction_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # RETURN INFORMATION
    # --------------------------------------------------------

    return_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    return_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    returned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # TRACKING AND AUDIT
    # --------------------------------------------------------

    tracking_metadata: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    trace_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    created_by: Mapped[str | None] = mapped_column(
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

    # --------------------------------------------------------
    # SOFT DELETION
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
    def is_delivered(self) -> bool:
        return self.status == DeliveryStatus.DELIVERED

    @property
    def is_returned(self) -> bool:
        return self.status == DeliveryStatus.RETURNED

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            DeliveryStatus.DELIVERED,
            DeliveryStatus.RETURNED,
            DeliveryStatus.CANCELLED,
        }

    @property
    def is_late(self) -> bool:
        if self.estimated_delivery_at is None:
            return False

        if self.status in {
            DeliveryStatus.CANCELLED,
            DeliveryStatus.RETURNED,
        }:
            return False

        deadline = as_utc(self.estimated_delivery_at)

        if self.actual_delivery_at is not None:
            return as_utc(self.actual_delivery_at) > deadline

        return (
            not self.is_delivered
            and utc_now() > deadline
        )

    @property
    def remaining_attempts(self) -> int:
        return max(
            0,
            self.max_attempts - self.attempt_count,
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_active(self) -> None:
        if self.is_deleted:
            raise ValueError("Delivery is deleted")

    def _transition(
        self,
        new_status: DeliveryStatus,
        allowed_from: set[DeliveryStatus],
    ) -> None:
        self._ensure_active()

        if self.status not in allowed_from:
            raise ValueError(
                f"Invalid delivery transition: "
                f"{self.status.value} -> {new_status.value}"
            )

        self.status = new_status
        self._touch()

    # ========================================================
    # CONFIRM DELIVERY
    # ========================================================

    def confirm(self) -> None:
        self._transition(
            DeliveryStatus.CONFIRMED,
            {DeliveryStatus.PENDING},
        )

    # ========================================================
    # PREPARE SHIPMENT
    # ========================================================

    def start_preparing(self) -> None:
        self._transition(
            DeliveryStatus.PREPARING,
            {DeliveryStatus.CONFIRMED},
        )

    def mark_ready_for_pickup(self) -> None:
        self._transition(
            DeliveryStatus.READY_FOR_PICKUP,
            {DeliveryStatus.PREPARING},
        )

    # ========================================================
    # PICKUP AND TRANSIT
    # ========================================================

    def mark_picked_up(self) -> None:
        self._transition(
            DeliveryStatus.PICKED_UP,
            {DeliveryStatus.READY_FOR_PICKUP},
        )

        self.picked_up_at = utc_now()

    def mark_in_transit(self) -> None:
        self._transition(
            DeliveryStatus.IN_TRANSIT,
            {
                DeliveryStatus.PICKED_UP,
                DeliveryStatus.AT_HUB,
            },
        )

    def mark_at_hub(self) -> None:
        self._transition(
            DeliveryStatus.AT_HUB,
            {DeliveryStatus.IN_TRANSIT},
        )

    def mark_out_for_delivery(self) -> None:
        self._transition(
            DeliveryStatus.OUT_FOR_DELIVERY,
            {
                DeliveryStatus.IN_TRANSIT,
                DeliveryStatus.AT_HUB,
                DeliveryStatus.DELIVERY_ATTEMPTED,
            },
        )

    # ========================================================
    # FAILED DELIVERY ATTEMPT
    # ========================================================

    def record_failed_attempt(
        self,
        reason: str,
    ) -> None:
        self._ensure_active()

        if self.status != DeliveryStatus.OUT_FOR_DELIVERY:
            raise ValueError(
                "Delivery must be out for delivery"
            )

        if self.attempt_count >= self.max_attempts:
            raise ValueError(
                "Maximum delivery attempts reached"
            )

        if not reason.strip():
            raise ValueError(
                "Failure reason is required"
            )

        self.attempt_count += 1
        self.last_attempt_at = utc_now()
        self.failure_reason = reason

        if self.attempt_count >= self.max_attempts:
            self.status = DeliveryStatus.FAILED
        else:
            self.status = DeliveryStatus.DELIVERY_ATTEMPTED

        self._touch()

    # ========================================================
    # SUCCESSFUL DELIVERY
    # ========================================================

    def mark_delivered(
        self,
        *,
        received_by: str | None = None,
        proof_type: ProofOfDeliveryType = (
            ProofOfDeliveryType.NONE
        ),
        proof_reference: str | None = None,
        proof_verified: bool = False,
    ) -> None:
        self._ensure_active()

        if self.status != DeliveryStatus.OUT_FOR_DELIVERY:
            raise ValueError(
                "Delivery must be out for delivery"
            )

        if (
            proof_type != ProofOfDeliveryType.NONE
            and not proof_reference
        ):
            raise ValueError(
                "Proof reference is required"
            )

        if (
            proof_verified
            and proof_type == ProofOfDeliveryType.NONE
        ):
            raise ValueError(
                "Cannot verify missing proof"
            )

        self.status = DeliveryStatus.DELIVERED
        self.actual_delivery_at = utc_now()
        self.received_by = received_by
        self.proof_type = proof_type
        self.proof_reference = proof_reference
        self.proof_verified = proof_verified
        self.failure_reason = None
        self._touch()

    # ========================================================
    # RETURN WORKFLOW
    # ========================================================

    def request_return(self, reason: str) -> None:
        self._ensure_active()

        if self.status not in {
            DeliveryStatus.DELIVERED,
            DeliveryStatus.FAILED,
        }:
            raise ValueError(
                "Return is not allowed in current state"
            )

        if not reason.strip():
            raise ValueError(
                "Return reason is required"
            )

        self.return_reason = reason
        self.return_requested_at = utc_now()
        self.status = DeliveryStatus.RETURN_REQUESTED
        self._touch()

    def mark_return_in_transit(self) -> None:
        self._transition(
            DeliveryStatus.RETURN_IN_TRANSIT,
            {DeliveryStatus.RETURN_REQUESTED},
        )

    def mark_returned(self) -> None:
        self._transition(
            DeliveryStatus.RETURNED,
            {DeliveryStatus.RETURN_IN_TRANSIT},
        )

        self.returned_at = utc_now()

    # ========================================================
    # CANCELLATION
    # ========================================================

    def cancel(self, reason: str) -> None:
        self._ensure_active()

        if self.status not in {
            DeliveryStatus.PENDING,
            DeliveryStatus.CONFIRMED,
            DeliveryStatus.PREPARING,
            DeliveryStatus.READY_FOR_PICKUP,
        }:
            raise ValueError(
                "Delivery cannot be cancelled at this stage"
            )

        if not reason.strip():
            raise ValueError(
                "Cancellation reason is required"
            )

        self.status = DeliveryStatus.CANCELLED
        self.failure_reason = reason
        self._touch()

    # ========================================================
    # AI RISK PREDICTION
    # ========================================================

    def update_delay_prediction(
        self,
        *,
        probability: float,
        risk_level: DeliveryRiskLevel,
        model_name: str,
        reason: str | None = None,
        recommended_action: str | None = None,
    ) -> None:
        self._ensure_active()

        if not 0 <= probability <= 1:
            raise ValueError(
                "Delay probability must be between 0 and 1"
            )

        self.delay_probability = probability
        self.risk_level = risk_level
        self.prediction_model = model_name
        self.risk_reason = reason
        self.ai_recommended_action = recommended_action
        self.prediction_at = utc_now()
        self._touch()

    # ========================================================
    # SOFT DELETE
    # ========================================================

    def soft_delete(self) -> None:
        if self.is_deleted:
            raise ValueError(
                "Delivery already deleted"
            )

        self.is_deleted = True
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
            "delivery_number": self.delivery_number,
            "order_id": self.order_id,
            "customer_id": self.customer_id,
            "warehouse_id": self.warehouse_id,
            "shipment_id": self.shipment_id,
            "fleet_id": self.fleet_id,
            "vehicle_id": self.vehicle_id,
            "driver_id": self.driver_id,
            "status": self.status.value,
            "priority": self.priority.value,
            "delivery_method": self.delivery_method.value,
            "carrier_name": self.carrier_name,
            "carrier_service": self.carrier_service,
            "tracking_number": self.tracking_number,
            "tracking_url": self.tracking_url,
            "recipient_name": self.recipient_name,
            "address_line1": self.address_line1,
            "address_line2": self.address_line2,
            "city": self.city,
            "state": self.state,
            "postal_code": self.postal_code,
            "country": self.country,
            "scheduled_pickup_at": dt(
                self.scheduled_pickup_at
            ),
            "picked_up_at": dt(self.picked_up_at),
            "estimated_delivery_at": dt(
                self.estimated_delivery_at
            ),
            "actual_delivery_at": dt(
                self.actual_delivery_at
            ),
            "package_count": self.package_count,
            "weight_kg": (
                str(self.weight_kg)
                if self.weight_kg is not None else None
            ),
            "distance_km": (
                str(self.distance_km)
                if self.distance_km is not None else None
            ),
            "currency": self.currency,
            "delivery_cost": str(self.delivery_cost),
            "shipping_fee": str(self.shipping_fee),
            "attempt_count": self.attempt_count,
            "max_attempts": self.max_attempts,
            "remaining_attempts": self.remaining_attempts,
            "last_attempt_at": dt(self.last_attempt_at),
            "failure_reason": self.failure_reason,
            "proof_type": self.proof_type.value,
            "proof_reference": self.proof_reference,
            "proof_verified": self.proof_verified,
            "delay_probability": self.delay_probability,
            "risk_level": self.risk_level.value,
            "risk_reason": self.risk_reason,
            "ai_recommended_action": (
                self.ai_recommended_action
            ),
            "prediction_model": self.prediction_model,
            "prediction_at": dt(self.prediction_at),
            "return_reason": self.return_reason,
            "return_requested_at": dt(
                self.return_requested_at
            ),
            "returned_at": dt(self.returned_at),
            "is_late": self.is_late,
            "is_delivered": self.is_delivered,
            "is_deleted": self.is_deleted,
            "version": self.version,
            "created_at": dt(self.created_at),
            "updated_at": dt(self.updated_at),
        }

    def __repr__(self) -> str:
        return (
            f"<Delivery("
            f"id={self.id}, "
            f"number={self.delivery_number}, "
            f"status={self.status.value}"
            f")>"
        )
