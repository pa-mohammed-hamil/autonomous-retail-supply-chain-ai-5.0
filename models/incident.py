from __future__ import annotations

"""Planned module: incident. Implementation pending."""



"""
backend/models/incident.py

Autonomous Retail Supply Chain AI 5.0
Enterprise Incident Management ORM

Features:
- Multi-tenant incident management
- Warehouse, inventory and logistics incidents
- Workplace safety and emergency incidents
- Supplier, equipment and system failures
- AI/ML and cybersecurity incidents
- Incident ownership and assignment
- SLA and escalation tracking
- Root-cause analysis
- Corrective and preventive actions
- Human approval references
- Audit metadata and optimistic locking
- Soft deletion

Requirements:
    Python >= 3.10
    SQLAlchemy >= 2.0
"""


import enum
import math
import uuid

from datetime import datetime, timedelta, timezone
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


def generate_incident_number() -> str:
    return f"INC-{uuid.uuid4().hex[:16].upper()}"


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


def validate_score(value: float, name: str) -> float:
    result = float(value)

    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError(
            f"{name} must be a finite value between 0 and 1"
        )

    return result


# ============================================================
# ENUMS
# ============================================================

class IncidentType(str, enum.Enum):
    WAREHOUSE = "warehouse"
    INVENTORY_SHORTAGE = "inventory_shortage"
    INVENTORY_MISMATCH = "inventory_mismatch"
    STOCKOUT = "stockout"
    OVERSTOCK = "overstock"
    PRODUCT_DAMAGE = "product_damage"
    PRODUCT_QUALITY = "product_quality"

    SUPPLIER_DELAY = "supplier_delay"
    SUPPLIER_FAILURE = "supplier_failure"
    PURCHASE_ORDER_ISSUE = "purchase_order_issue"

    DELIVERY_DELAY = "delivery_delay"
    DELIVERY_FAILURE = "delivery_failure"
    TRANSPORT_ACCIDENT = "transport_accident"
    LOGISTICS_DISRUPTION = "logistics_disruption"

    EQUIPMENT_FAILURE = "equipment_failure"
    MACHINE_BREAKDOWN = "machine_breakdown"
    PREDICTIVE_MAINTENANCE = "predictive_maintenance"

    WORKPLACE_INJURY = "workplace_injury"
    SAFETY_HAZARD = "safety_hazard"
    FIRE = "fire"
    FLOOD = "flood"
    NATURAL_DISASTER = "natural_disaster"
    MEDICAL_EMERGENCY = "medical_emergency"

    SECURITY_BREACH = "security_breach"
    UNAUTHORIZED_ACCESS = "unauthorized_access"
    DATA_BREACH = "data_breach"
    CYBER_ATTACK = "cyber_attack"

    AI_AGENT_FAILURE = "ai_agent_failure"
    MODEL_DRIFT = "model_drift"
    FORECAST_FAILURE = "forecast_failure"
    SYSTEM_OUTAGE = "system_outage"
    API_FAILURE = "api_failure"
    DATA_PIPELINE_FAILURE = "data_pipeline_failure"

    CUSTOMER_COMPLAINT = "customer_complaint"
    COMPLIANCE_VIOLATION = "compliance_violation"
    OTHER = "other"


class IncidentStatus(str, enum.Enum):
    REPORTED = "reported"
    TRIAGED = "triaged"
    ASSIGNED = "assigned"
    INVESTIGATING = "investigating"
    CONTAINED = "contained"
    MITIGATING = "mitigating"
    MONITORING = "monitoring"
    PENDING_APPROVAL = "pending_approval"
    RESOLVED = "resolved"
    CLOSED = "closed"
    REOPENED = "reopened"
    CANCELLED = "cancelled"


class IncidentSeverity(str, enum.Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class IncidentPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    IMMEDIATE = "immediate"


class IncidentSource(str, enum.Enum):
    EMPLOYEE = "employee"
    MANAGER = "manager"
    CUSTOMER = "customer"
    SUPPLIER = "supplier"
    SENSOR = "sensor"
    IOT_DEVICE = "iot_device"
    CCTV = "cctv"
    AI_AGENT = "ai_agent"
    ML_MODEL = "ml_model"
    RULE_ENGINE = "rule_engine"
    MONITORING = "monitoring"
    ERP = "erp"
    WMS = "wms"
    EXTERNAL_API = "external_api"
    SYSTEM = "system"


class IncidentImpactLevel(str, enum.Enum):
    NONE = "none"
    MINOR = "minor"
    MODERATE = "moderate"
    MAJOR = "major"
    SEVERE = "severe"
    CATASTROPHIC = "catastrophic"


class IncidentRootCauseCategory(str, enum.Enum):
    UNKNOWN = "unknown"
    HUMAN_ERROR = "human_error"
    PROCESS_FAILURE = "process_failure"
    EQUIPMENT_FAILURE = "equipment_failure"
    SOFTWARE_FAILURE = "software_failure"
    NETWORK_FAILURE = "network_failure"
    SUPPLIER_FAILURE = "supplier_failure"
    ENVIRONMENTAL = "environmental"
    SECURITY = "security"
    DATA_QUALITY = "data_quality"
    MODEL_ERROR = "model_error"
    OTHER = "other"


# ============================================================
# INCIDENT MODEL
# ============================================================

class Incident(Base):
    __tablename__ = "incidents"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "incident_number",
            name="uq_incident_org_number",
        ),
        UniqueConstraint(
            "organization_id",
            "deduplication_key",
            name="uq_incident_org_dedup",
        ),
        CheckConstraint(
            "affected_people_count >= 0",
            name="incident_people_nonnegative",
        ),
        CheckConstraint(
            "injured_people_count >= 0",
            name="incident_injured_nonnegative",
        ),
        CheckConstraint(
            "injured_people_count <= affected_people_count",
            name="incident_injured_limit",
        ),
        CheckConstraint(
            "occurrence_count >= 1",
            name="incident_occurrence_positive",
        ),
        CheckConstraint(
            "ai_confidence IS NULL OR "
            "(ai_confidence >= 0 AND ai_confidence <= 1)",
            name="incident_ai_confidence_range",
        ),
        CheckConstraint(
            "risk_score IS NULL OR "
            "(risk_score >= 0 AND risk_score <= 1)",
            name="incident_risk_score_range",
        ),
        CheckConstraint(
            "sla_minutes IS NULL OR sla_minutes > 0",
            name="incident_sla_positive",
        ),
        Index(
            "ix_incident_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_incident_org_severity",
            "organization_id",
            "severity",
        ),
        Index(
            "ix_incident_org_type",
            "organization_id",
            "incident_type",
        ),
        Index(
            "ix_incident_org_warehouse",
            "organization_id",
            "warehouse_id",
        ),
        Index(
            "ix_incident_org_assignee",
            "organization_id",
            "assigned_to",
        ),
        Index(
            "ix_incident_org_detected",
            "organization_id",
            "detected_at",
        ),
        Index(
            "ix_incident_org_sla",
            "organization_id",
            "sla_deadline_at",
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

    incident_number: Mapped[str] = mapped_column(
        String(40),
        default=generate_incident_number,
        nullable=False,
    )

    deduplication_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    # --------------------------------------------------------
    # INCIDENT INFORMATION
    # --------------------------------------------------------

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    incident_type: Mapped[IncidentType] = mapped_column(
        enum_column(
            IncidentType,
            "incident_type",
        ),
        nullable=False,
    )

    status: Mapped[IncidentStatus] = mapped_column(
        enum_column(
            IncidentStatus,
            "incident_status",
        ),
        default=IncidentStatus.REPORTED,
        nullable=False,
    )

    severity: Mapped[IncidentSeverity] = mapped_column(
        enum_column(
            IncidentSeverity,
            "incident_severity",
        ),
        default=IncidentSeverity.MEDIUM,
        nullable=False,
    )

    priority: Mapped[IncidentPriority] = mapped_column(
        enum_column(
            IncidentPriority,
            "incident_priority",
        ),
        default=IncidentPriority.NORMAL,
        nullable=False,
    )

    source: Mapped[IncidentSource] = mapped_column(
        enum_column(
            IncidentSource,
            "incident_source",
        ),
        default=IncidentSource.SYSTEM,
        nullable=False,
    )

    impact_level: Mapped[IncidentImpactLevel] = mapped_column(
        enum_column(
            IncidentImpactLevel,
            "incident_impact_level",
        ),
        default=IncidentImpactLevel.MINOR,
        nullable=False,
    )

    # --------------------------------------------------------
    # BUSINESS REFERENCES
    # --------------------------------------------------------

    warehouse_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    supplier_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    product_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    inventory_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    delivery_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    fulfillment_order_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    purchase_order_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    equipment_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    employee_alert_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    corporate_alert_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    escalation_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # LOCATION
    # --------------------------------------------------------

    location_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    location_details: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # --------------------------------------------------------
    # ASSIGNMENT
    # --------------------------------------------------------

    reported_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

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

    # --------------------------------------------------------
    # IMPACT
    # --------------------------------------------------------

    affected_people_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    injured_people_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    operational_impact: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    financial_impact_estimate: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        default="INR",
        nullable=False,
    )

    # --------------------------------------------------------
    # ROOT CAUSE ANALYSIS
    # --------------------------------------------------------

    root_cause_category: Mapped[
        IncidentRootCauseCategory
    ] = mapped_column(
        enum_column(
            IncidentRootCauseCategory,
            "incident_root_cause_category",
        ),
        default=IncidentRootCauseCategory.UNKNOWN,
        nullable=False,
    )

    root_cause_description: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    contributing_factors: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    corrective_actions: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    preventive_actions: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # --------------------------------------------------------
    # SLA
    # --------------------------------------------------------

    sla_minutes: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    sla_deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    sla_breached: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    sla_breached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # --------------------------------------------------------
    # AI ANALYSIS
    # --------------------------------------------------------

    agent_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    agent_action_id: Mapped[str | None] = mapped_column(
        String(36),
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

    ai_confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    risk_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    ai_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    ai_root_cause: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    recommended_action: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
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
    # INCIDENT TIMELINE
    # --------------------------------------------------------

    occurred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    triaged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    investigation_started_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    contained_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    closed_at: Mapped[datetime | None] = mapped_column(
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

    resolution_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    closed_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    cancellation_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    occurrence_count: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    # --------------------------------------------------------
    # EVIDENCE AND METADATA
    # --------------------------------------------------------

    evidence: Mapped[
        list[dict[str, Any]]
    ] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    incident_metadata: Mapped[
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
            IncidentStatus.CLOSED,
            IncidentStatus.CANCELLED,
        }

    @property
    def is_critical(self) -> bool:
        return self.severity in {
            IncidentSeverity.CRITICAL,
            IncidentSeverity.EMERGENCY,
        }

    @property
    def is_overdue(self) -> bool:
        if self.sla_deadline_at is None:
            return False

        if self.status in {
            IncidentStatus.RESOLVED,
            IncidentStatus.CLOSED,
            IncidentStatus.CANCELLED,
        }:
            return False

        return as_utc(self.sla_deadline_at) <= utc_now()

    @property
    def requires_immediate_attention(self) -> bool:
        return (
            not self.is_deleted
            and not self.is_terminal
            and self.status != IncidentStatus.RESOLVED
            and (
                self.is_critical
                or self.is_overdue
                or self.priority == IncidentPriority.IMMEDIATE
            )
        )

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _touch(self) -> None:
        self.updated_at = utc_now()

    def _ensure_active(self) -> None:
        if self.is_deleted:
            raise ValueError("Incident is deleted")

        if self.is_terminal:
            raise ValueError(
                "Incident is closed or cancelled"
            )

    # ========================================================
    # TRIAGE
    # ========================================================

    def triage(
        self,
        *,
        severity: IncidentSeverity,
        priority: IncidentPriority,
        impact_level: IncidentImpactLevel,
        user_id: str,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            IncidentStatus.REPORTED,
            IncidentStatus.REOPENED,
        }:
            raise ValueError(
                "Incident cannot be triaged in current state"
            )

        if not user_id:
            raise ValueError("User ID is required")

        self.severity = severity
        self.priority = priority
        self.impact_level = impact_level
        self.status = IncidentStatus.TRIAGED
        self.triaged_at = utc_now()
        self.updated_by = user_id
        self._touch()

    # ========================================================
    # ASSIGN
    # ========================================================

    def assign(
        self,
        *,
        assigned_to: str,
        assigned_by: str,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            IncidentStatus.TRIAGED,
            IncidentStatus.ASSIGNED,
        }:
            raise ValueError(
                "Incident must be triaged before assignment"
            )

        if not assigned_to or not assigned_by:
            raise ValueError(
                "Assignee and assigning user are required"
            )

        self.assigned_to = assigned_to
        self.assigned_by = assigned_by
        self.assigned_at = utc_now()
        self.status = IncidentStatus.ASSIGNED
        self.updated_by = assigned_by
        self._touch()

    # ========================================================
    # START INVESTIGATION
    # ========================================================

    def start_investigation(self, user_id: str) -> None:
        self._ensure_active()

        if self.status != IncidentStatus.ASSIGNED:
            raise ValueError(
                "Incident must be assigned first"
            )

        if user_id != self.assigned_to:
            raise ValueError(
                "Only assigned user can start investigation"
            )

        self.status = IncidentStatus.INVESTIGATING
        self.investigation_started_at = utc_now()
        self.updated_by = user_id
        self._touch()

    # ========================================================
    # CONTAIN INCIDENT
    # ========================================================

    def mark_contained(self, user_id: str) -> None:
        self._ensure_active()

        if self.status != IncidentStatus.INVESTIGATING:
            raise ValueError(
                "Incident must be under investigation"
            )

        if not user_id:
            raise ValueError("User ID is required")

        self.status = IncidentStatus.CONTAINED
        self.contained_at = utc_now()
        self.updated_by = user_id
        self._touch()

    # ========================================================
    # START MITIGATION
    # ========================================================

    def start_mitigation(self, user_id: str) -> None:
        self._ensure_active()

        if self.status not in {
            IncidentStatus.INVESTIGATING,
            IncidentStatus.CONTAINED,
        }:
            raise ValueError(
                "Incident is not ready for mitigation"
            )

        if not user_id:
            raise ValueError("User ID is required")

        self.status = IncidentStatus.MITIGATING
        self.updated_by = user_id
        self._touch()

    # ========================================================
    # RECORD ROOT CAUSE
    # ========================================================

    def record_root_cause(
        self,
        *,
        category: IncidentRootCauseCategory,
        description: str,
        user_id: str,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            IncidentStatus.INVESTIGATING,
            IncidentStatus.CONTAINED,
            IncidentStatus.MITIGATING,
            IncidentStatus.MONITORING,
        }:
            raise ValueError(
                "Incident must be under investigation"
            )

        if not description.strip() or not user_id:
            raise ValueError(
                "Root cause and user ID are required"
            )

        self.root_cause_category = category
        self.root_cause_description = description
        self.updated_by = user_id
        self._touch()

    # ========================================================
    # CORRECTIVE ACTION
    # ========================================================

    def add_corrective_action(
        self,
        *,
        description: str,
        assigned_to: str,
        due_at: datetime | None = None,
    ) -> None:
        self._ensure_active()

        if not description.strip() or not assigned_to:
            raise ValueError(
                "Action description and assignee required"
            )

        actions = list(self.corrective_actions or [])

        actions.append(
            {
                "id": generate_uuid(),
                "description": description,
                "assigned_to": assigned_to,
                "due_at": (
                    as_utc(due_at).isoformat()
                    if due_at else None
                ),
                "status": "pending",
                "created_at": utc_now().isoformat(),
            }
        )

        self.corrective_actions = actions
        self._touch()

    # ========================================================
    # PREVENTIVE ACTION
    # ========================================================

    def add_preventive_action(
        self,
        *,
        description: str,
        assigned_to: str,
    ) -> None:
        self._ensure_active()

        if not description.strip() or not assigned_to:
            raise ValueError(
                "Action description and assignee required"
            )

        actions = list(self.preventive_actions or [])

        actions.append(
            {
                "id": generate_uuid(),
                "description": description,
                "assigned_to": assigned_to,
                "status": "pending",
                "created_at": utc_now().isoformat(),
            }
        )

        self.preventive_actions = actions
        self._touch()

    # ========================================================
    # SLA
    # ========================================================

    def configure_sla(self, minutes: int) -> None:
        self._ensure_active()

        if minutes <= 0:
            raise ValueError(
                "SLA minutes must be positive"
            )

        if self.status not in {
            IncidentStatus.REPORTED,
            IncidentStatus.TRIAGED,
        }:
            raise ValueError(
                "SLA must be configured before investigation"
            )

        self.sla_minutes = minutes
        self.sla_deadline_at = utc_now() + timedelta(
            minutes=minutes
        )
        self._touch()

    def record_sla_breach(self) -> None:
        self._ensure_active()

        if self.status == IncidentStatus.RESOLVED:
            raise ValueError(
                "Resolved incident cannot newly breach SLA"
            )

        if not self.is_overdue:
            raise ValueError(
                "SLA deadline has not passed"
            )

        if self.sla_breached:
            return

        self.sla_breached = True
        self.sla_breached_at = utc_now()
        self._touch()

    # ========================================================
    # AI ANALYSIS
    # ========================================================

    def update_ai_analysis(
        self,
        *,
        model_name: str,
        confidence: float,
        risk_score: float,
        summary: str,
        root_cause: str,
        recommended_action: str,
    ) -> None:
        self._ensure_active()

        if not model_name.strip():
            raise ValueError(
                "Model name is required"
            )

        self.ai_confidence = validate_score(
            confidence,
            "confidence",
        )

        self.risk_score = validate_score(
            risk_score,
            "risk_score",
        )

        self.model_name = model_name
        self.ai_summary = summary
        self.ai_root_cause = root_cause
        self.recommended_action = recommended_action
        self._touch()

    # ========================================================
    # HUMAN APPROVAL
    # ========================================================

    def request_approval(
        self,
        approval_request_id: str,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            IncidentStatus.INVESTIGATING,
            IncidentStatus.CONTAINED,
            IncidentStatus.MITIGATING,
            IncidentStatus.MONITORING,
        }:
            raise ValueError(
                "Incident is not ready for approval"
            )

        if not approval_request_id:
            raise ValueError(
                "Approval request ID required"
            )

        metadata = dict(self.incident_metadata or {})
        metadata["status_before_approval"] = self.status.value
        self.incident_metadata = metadata

        self.requires_human_approval = True
        self.approval_request_id = approval_request_id
        self.status = IncidentStatus.PENDING_APPROVAL
        self._touch()

    # ========================================================
    # RESOLVE
    # ========================================================

    def resolve(
        self,
        *,
        user_id: str,
        summary: str,
        approval_confirmed: bool = False,
    ) -> None:
        self._ensure_active()

        if self.status not in {
            IncidentStatus.INVESTIGATING,
            IncidentStatus.CONTAINED,
            IncidentStatus.MITIGATING,
            IncidentStatus.MONITORING,
            IncidentStatus.PENDING_APPROVAL,
        }:
            raise ValueError(
                "Incident cannot be resolved"
            )

        if not user_id or not summary.strip():
            raise ValueError(
                "Resolver and summary are required"
            )

        if (
            self.requires_human_approval
            and not approval_confirmed
        ):
            raise ValueError(
                "Verified human approval is required"
            )

        self.status = IncidentStatus.RESOLVED
        self.resolved_by = user_id
        self.resolved_at = utc_now()
        self.resolution_summary = summary
        self.updated_by = user_id
        self._touch()

    # ========================================================
    # CLOSE
    # ========================================================

    def close(self, user_id: str) -> None:
        self._ensure_active()

        if self.status != IncidentStatus.RESOLVED:
            raise ValueError(
                "Incident must be resolved before closure"
            )

        if not user_id:
            raise ValueError("User ID is required")

        self.status = IncidentStatus.CLOSED
        self.closed_by = user_id
        self.closed_at = utc_now()
        self.updated_by = user_id
        self._touch()

    # ========================================================
    # REOPEN
    # ========================================================

    def reopen(
        self,
        *,
        user_id: str,
        reason: str,
    ) -> None:
        if self.is_deleted:
            raise ValueError("Incident is deleted")

        if self.status not in {
            IncidentStatus.RESOLVED,
            IncidentStatus.CLOSED,
        }:
            raise ValueError(
                "Only resolved or closed incidents can reopen"
            )

        if not user_id or not reason.strip():
            raise ValueError(
                "User ID and reason are required"
            )

        metadata = dict(self.incident_metadata or {})
        metadata["last_reopen_reason"] = reason
        metadata["last_reopened_at"] = utc_now().isoformat()
        self.incident_metadata = metadata

        self.status = IncidentStatus.REOPENED
        self.resolved_at = None
        self.resolved_by = None
        self.closed_at = None
        self.closed_by = None
        self.updated_by = user_id
        self._touch()

    # ========================================================
    # CANCEL
    # ========================================================

    def cancel(
        self,
        *,
        user_id: str,
        reason: str,
    ) -> None:
        self._ensure_active()

        if self.status == IncidentStatus.RESOLVED:
            raise ValueError(
                "Resolved incidents cannot be cancelled"
            )

        if not user_id or not reason.strip():
            raise ValueError(
                "User ID and reason are required"
            )

        if self.is_critical:
            raise ValueError(
                "Critical and emergency incidents require "
                "an authorized safety review"
            )

        self.status = IncidentStatus.CANCELLED
        self.cancellation_reason = reason
        self.updated_by = user_id
        self._touch()

    # ========================================================
    # SOFT DELETE
    # ========================================================

    def soft_delete(self, user_id: str) -> None:
        if self.is_deleted:
            raise ValueError(
                "Incident already deleted"
            )

        if not user_id:
            raise ValueError(
                "Deleting user is required"
            )

        if not self.is_terminal:
            raise ValueError(
                "Only closed or cancelled incidents "
                "can be soft deleted"
            )

        self.is_deleted = True
        self.deleted_by = user_id
        self.deleted_at = utc_now()
        self.updated_by = user_id
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
            "incident_number": self.incident_number,
            "deduplication_key": self.deduplication_key,
            "title": self.title,
            "description": self.description,
            "incident_type": self.incident_type.value,
            "status": self.status.value,
            "severity": self.severity.value,
            "priority": self.priority.value,
            "source": self.source.value,
            "impact_level": self.impact_level.value,
            "warehouse_id": self.warehouse_id,
            "supplier_id": self.supplier_id,
            "product_id": self.product_id,
            "inventory_id": self.inventory_id,
            "delivery_id": self.delivery_id,
            "fulfillment_order_id": (
                self.fulfillment_order_id
            ),
            "purchase_order_id": self.purchase_order_id,
            "equipment_id": self.equipment_id,
            "employee_alert_id": self.employee_alert_id,
            "corporate_alert_id": self.corporate_alert_id,
            "escalation_id": self.escalation_id,
            "location_name": self.location_name,
            "location_details": self.location_details,
            "reported_by": self.reported_by,
            "assigned_to": self.assigned_to,
            "assigned_team_id": self.assigned_team_id,
            "assigned_by": self.assigned_by,
            "assigned_at": dt(self.assigned_at),
            "affected_people_count": (
                self.affected_people_count
            ),
            "injured_people_count": (
                self.injured_people_count
            ),
            "operational_impact": self.operational_impact,
            "financial_impact_estimate": (
                self.financial_impact_estimate
            ),
            "currency": self.currency,
            "root_cause_category": (
                self.root_cause_category.value
            ),
            "root_cause_description": (
                self.root_cause_description
            ),
            "contributing_factors": self.contributing_factors,
            "corrective_actions": self.corrective_actions,
            "preventive_actions": self.preventive_actions,
            "sla_minutes": self.sla_minutes,
            "sla_deadline_at": dt(self.sla_deadline_at),
            "sla_breached": self.sla_breached,
            "sla_breached_at": dt(self.sla_breached_at),
            "is_overdue": self.is_overdue,
            "requires_immediate_attention": (
                self.requires_immediate_attention
            ),
            "agent_run_id": self.agent_run_id,
            "agent_action_id": self.agent_action_id,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "ai_confidence": self.ai_confidence,
            "risk_score": self.risk_score,
            "ai_summary": self.ai_summary,
            "ai_root_cause": self.ai_root_cause,
            "recommended_action": self.recommended_action,
            "requires_human_approval": (
                self.requires_human_approval
            ),
            "approval_request_id": self.approval_request_id,
            "occurred_at": dt(self.occurred_at),
            "detected_at": dt(self.detected_at),
            "triaged_at": dt(self.triaged_at),
            "investigation_started_at": dt(
                self.investigation_started_at
            ),
            "contained_at": dt(self.contained_at),
            "resolved_at": dt(self.resolved_at),
            "closed_at": dt(self.closed_at),
            "resolved_by": self.resolved_by,
            "resolution_summary": self.resolution_summary,
            "closed_by": self.closed_by,
            "cancellation_reason": self.cancellation_reason,
            "occurrence_count": self.occurrence_count,
            "evidence": self.evidence,
            "incident_metadata": self.incident_metadata,
            "is_deleted": self.is_deleted,
            "version": self.version,
            "created_at": dt(self.created_at),
            "updated_at": dt(self.updated_at),
        }

    def __repr__(self) -> str:
        return (
            f"<Incident("
            f"id={self.id}, "
            f"number={self.incident_number}, "
            f"type={self.incident_type.value}, "
            f"status={self.status.value}, "
            f"severity={self.severity.value}"
            f")>"
        )
