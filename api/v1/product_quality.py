from __future__ import annotations

"""Planned module: product quality. Implementation pending."""

"""
backend/product_quality.py

Autonomous Retail Supply Chain AI 5.0
Product Quality Management API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Product and batch quality inspections
    - Incoming, storage, outbound and return inspections
    - Defect recording and classification
    - Inspection sampling and acceptance thresholds
    - Quality review and approval
    - Batch quarantine recommendations
    - Corrective and preventive actions (CAPA)
    - Quality incident references
    - Product quality analytics
    - Tenant and warehouse authorization
    - Optimistic concurrency
    - Idempotent inspection creation

IMPORTANT:
    This is a prototype using in-memory storage.

    Quarantine and release decisions are recorded
    internally. They do not change authoritative
    inventory availability or warehouse stock.

    AI defect detection and physical inspection
    hardware are not implemented here.
"""


import asyncio
import hashlib
import json
import secrets

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any

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


API_PREFIX = "/api/v1/product-quality"

MAX_INSPECTIONS_PER_TENANT = 50000
MAX_DEFECTS_PER_INSPECTION = 200
MAX_ACTIONS_PER_INSPECTION = 100
MAX_EVENTS_PER_INSPECTION = 500
MAX_IDEMPOTENCY_KEYS = 100000
MAX_LIST_LIMIT = 200

PERCENT_QUANTUM = Decimal("0.01")


# ============================================================
# ENUMS
# ============================================================

class InspectionType(str, Enum):
    INCOMING = "incoming"
    STORAGE = "storage"
    OUTBOUND = "outbound"
    RETURN = "return"
    RANDOM_AUDIT = "random_audit"
    SUPPLIER_AUDIT = "supplier_audit"


class InspectionStatus(str, Enum):
    CREATED = "created"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    REVIEW_PENDING = "review_pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class QualityResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    CONDITIONAL = "conditional"


class DefectSeverity(str, Enum):
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


class DefectCategory(str, Enum):
    PHYSICAL_DAMAGE = "physical_damage"
    FUNCTIONAL_FAILURE = "functional_failure"
    PACKAGING = "packaging"
    LABELING = "labeling"
    DIMENSIONAL = "dimensional"
    CONTAMINATION = "contamination"
    EXPIRED = "expired"
    COUNTERFEIT_SUSPECTED = "counterfeit_suspected"
    MISSING_COMPONENT = "missing_component"
    OTHER = "other"


class QuarantineStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    RECOMMENDED = "recommended"
    APPROVED = "approved"
    RELEASED = "released"


class CorrectiveActionStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    VERIFIED = "verified"
    CANCELLED = "cancelled"


class QualityEventType(str, Enum):
    CREATED = "created"
    ASSIGNED = "assigned"
    STARTED = "started"
    DEFECT_RECORDED = "defect_recorded"
    REVIEW_SUBMITTED = "review_submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    QUARANTINE_APPROVED = "quarantine_approved"
    QUARANTINE_RELEASED = "quarantine_released"
    CORRECTIVE_ACTION_CREATED = "corrective_action_created"
    CORRECTIVE_ACTION_UPDATED = "corrective_action_updated"
    CANCELLED = "cancelled"


# ============================================================
# REQUEST SCHEMAS
# ============================================================

class QualityInspectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    batch_id: str = Field(
        min_length=1,
        max_length=128,
    )

    supplier_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    purchase_order_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    inspection_type: InspectionType

    batch_quantity: int = Field(
        gt=0,
        le=10000000,
    )

    sample_quantity: int = Field(
        gt=0,
        le=10000000,
    )

    maximum_defect_percent: Decimal = Field(
        default=Decimal("2.00"),
        ge=0,
        le=100,
        max_digits=5,
        decimal_places=2,
    )

    notes: str = Field(
        default="",
        max_length=2000,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_sampling(self):

        if self.sample_quantity > self.batch_quantity:
            raise ValueError(
                "Sample quantity cannot exceed batch quantity"
            )

        return self


class QualityAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inspector_id: str = Field(
        min_length=1,
        max_length=128,
    )

    expected_version: int = Field(ge=1)


class QualityVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class DefectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: DefectCategory
    severity: DefectSeverity

    affected_quantity: int = Field(
        gt=0,
        le=10000000,
    )

    description: str = Field(
        min_length=5,
        max_length=2000,
    )

    evidence_reference: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
    )

    ai_detected: bool = False

    model_reference: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    expected_version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_ai_reference(self):

        if self.ai_detected and not self.model_reference:
            raise ValueError(
                "AI-detected defects require a model reference"
            )

        return self


class QualityReviewSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    inspected_quantity: int = Field(
        gt=0,
        le=10000000,
    )

    defective_units: int = Field(
        ge=0,
        le=10000000,
    )

    recommendation_notes: str = Field(
        default="",
        max_length=2000,
    )

    @model_validator(mode="after")
    def validate_quantities(self):

        if self.defective_units > self.inspected_quantity:
            raise ValueError(
                "Defective units cannot exceed inspected units"
            )

        return self


class QualityDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    decision_notes: str = Field(
        min_length=5,
        max_length=2000,
    )


class CorrectiveActionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        min_length=5,
        max_length=200,
    )

    description: str = Field(
        min_length=10,
        max_length=2000,
    )

    owner_id: str = Field(
        min_length=1,
        max_length=128,
    )

    due_at: datetime

    expected_version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_due_date(self):

        if self.due_at.tzinfo is None:
            raise ValueError(
                "Due date must include timezone"
            )

        if self.due_at <= datetime.now(timezone.utc):
            raise ValueError(
                "Due date must be in the future"
            )

        return self


class CorrectiveActionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_action_version: int = Field(ge=1)

    status: CorrectiveActionStatus

    notes: str = Field(
        default="",
        max_length=2000,
    )


class QualityCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    reason: str = Field(
        min_length=5,
        max_length=500,
    )


# ============================================================
# RESPONSE SCHEMAS
# ============================================================

class QualityDefectResponse(BaseModel):
    defect_id: str

    category: DefectCategory
    severity: DefectSeverity

    affected_quantity: int
    description: str

    evidence_reference: str | None

    ai_detected: bool
    model_reference: str | None

    recorded_by: str
    created_at: datetime


class CorrectiveActionResponse(BaseModel):
    action_id: str

    title: str
    description: str

    owner_id: str
    status: CorrectiveActionStatus

    due_at: datetime

    version: int

    created_at: datetime
    updated_at: datetime


class QualityEventResponse(BaseModel):
    event_id: str
    event_type: QualityEventType

    actor_id: str
    details: str | None

    created_at: datetime


class QualityInspectionResponse(BaseModel):
    inspection_id: str

    warehouse_id: str
    product_id: str
    batch_id: str

    supplier_id: str | None
    purchase_order_id: str | None

    inspection_type: InspectionType
    status: InspectionStatus

    inspector_id: str | None

    batch_quantity: int
    sample_quantity: int

    inspected_quantity: int
    defective_units: int

    defect_rate_percent: Decimal

    maximum_defect_percent: Decimal

    result: QualityResult | None
    quarantine_status: QuarantineStatus

    defect_count: int
    corrective_action_count: int

    version: int

    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class QualityInspectionDetailResponse(
    QualityInspectionResponse
):
    defects: list[QualityDefectResponse]
    corrective_actions: list[CorrectiveActionResponse]
    events: list[QualityEventResponse]

    recommendation_notes: str
    decision_notes: str | None


class QualityAnalyticsResponse(BaseModel):
    total_inspections: int

    created: int
    assigned: int
    in_progress: int
    review_pending: int
    approved: int
    rejected: int
    cancelled: int

    total_sampled_units: int
    total_defective_units: int

    overall_defect_rate_percent: Decimal

    minor_defects: int
    major_defects: int
    critical_defects: int

    quarantine_recommended: int
    quarantine_approved: int

    open_corrective_actions: int
    completed_corrective_actions: int


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass
class QualityDefectRecord:
    defect_id: str

    category: DefectCategory
    severity: DefectSeverity

    affected_quantity: int
    description: str

    evidence_reference: str | None

    ai_detected: bool
    model_reference: str | None

    recorded_by: str

    created_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )


@dataclass
class CorrectiveActionRecord:
    action_id: str

    title: str
    description: str
    owner_id: str

    due_at: datetime

    status: CorrectiveActionStatus = (
        CorrectiveActionStatus.OPEN
    )

    version: int = 1

    created_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )


@dataclass
class QualityInspectionRecord:
    inspection_id: str
    tenant_id: str

    warehouse_id: str
    product_id: str
    batch_id: str

    supplier_id: str | None
    purchase_order_id: str | None

    inspection_type: InspectionType

    batch_quantity: int
    sample_quantity: int

    maximum_defect_percent: Decimal

    created_by: str
    notes: str

    status: InspectionStatus = (
        InspectionStatus.CREATED
    )

    inspector_id: str | None = None

    inspected_quantity: int = 0
    defective_units: int = 0

    result: QualityResult | None = None

    quarantine_status: QuarantineStatus = (
        QuarantineStatus.NOT_REQUIRED
    )

    recommendation_notes: str = ""
    decision_notes: str | None = None

    defects: dict[
        str,
        QualityDefectRecord,
    ] = field(default_factory=dict)

    corrective_actions: dict[
        str,
        CorrectiveActionRecord,
    ] = field(default_factory=dict)

    events: list[
        QualityEventResponse
    ] = field(default_factory=list)

    version: int = 1

    created_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    completed_at: datetime | None = None


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def percentage(
    numerator: int,
    denominator: int,
) -> Decimal:

    if denominator <= 0:
        return Decimal("0.00")

    return (
        Decimal(numerator)
        / Decimal(denominator)
        * Decimal("100")
    ).quantize(
        PERCENT_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def request_fingerprint(
    payload: QualityInspectionCreate,
) -> str:

    canonical = json.dumps(
        payload.model_dump(
            mode="json",
            exclude={"source_request_id"},
        ),
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def require_quality_access(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool,
) -> None:

    # Temporary permission mapping.
    #
    # Production should add:
    # QUALITY_READ
    # QUALITY_INSPECT
    # QUALITY_APPROVE
    # QUALITY_QUARANTINE
    # QUALITY_RELEASE

    permission = (
        Permission.INVENTORY_WRITE
        if write
        else Permission.INVENTORY_READ
    )

    if (
        principal.allowed_warehouse_ids is not None
        and warehouse_id
        not in principal.allowed_warehouse_ids
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
            detail="Quality management access denied",
        )


def to_defect(
    record: QualityDefectRecord,
) -> QualityDefectResponse:

    return QualityDefectResponse(
        defect_id=record.defect_id,
        category=record.category,
        severity=record.severity,
        affected_quantity=record.affected_quantity,
        description=record.description,
        evidence_reference=record.evidence_reference,
        ai_detected=record.ai_detected,
        model_reference=record.model_reference,
        recorded_by=record.recorded_by,
        created_at=record.created_at,
    )


def to_action(
    record: CorrectiveActionRecord,
) -> CorrectiveActionResponse:

    return CorrectiveActionResponse(
        action_id=record.action_id,
        title=record.title,
        description=record.description,
        owner_id=record.owner_id,
        status=record.status,
        due_at=record.due_at,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def to_response(
    record: QualityInspectionRecord,
) -> QualityInspectionResponse:

    return QualityInspectionResponse(
        inspection_id=record.inspection_id,
        warehouse_id=record.warehouse_id,
        product_id=record.product_id,
        batch_id=record.batch_id,
        supplier_id=record.supplier_id,
        purchase_order_id=record.purchase_order_id,
        inspection_type=record.inspection_type,
        status=record.status,
        inspector_id=record.inspector_id,
        batch_quantity=record.batch_quantity,
        sample_quantity=record.sample_quantity,
        inspected_quantity=record.inspected_quantity,
        defective_units=record.defective_units,
        defect_rate_percent=percentage(
            record.defective_units,
            record.inspected_quantity,
        ),
        maximum_defect_percent=(
            record.maximum_defect_percent
        ),
        result=record.result,
        quarantine_status=record.quarantine_status,
        defect_count=len(record.defects),
        corrective_action_count=len(
            record.corrective_actions
        ),
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
    )


def to_detail(
    record: QualityInspectionRecord,
) -> QualityInspectionDetailResponse:

    return QualityInspectionDetailResponse(
        **to_response(record).model_dump(),
        defects=[
            to_defect(defect)
            for defect in record.defects.values()
        ],
        corrective_actions=[
            to_action(action)
            for action in record.corrective_actions.values()
        ],
        events=list(record.events),
        recommendation_notes=record.recommendation_notes,
        decision_notes=record.decision_notes,
    )


# ============================================================
# QUALITY STORE
# ============================================================

class ProductQualityStore:

    def __init__(self):

        self._inspections: dict[
            str,
            QualityInspectionRecord,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    def _get(
        self,
        principal: Principal,
        inspection_id: str,
        *,
        write: bool,
    ) -> QualityInspectionRecord:

        record = self._inspections.get(
            inspection_id
        )

        if (
            record is None
            or record.tenant_id
            != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Quality inspection not found",
            )

        require_quality_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    @staticmethod
    def _check_version(
        record: QualityInspectionRecord,
        expected_version: int,
    ) -> None:

        if record.version != expected_version:
            raise HTTPException(
                status_code=409,
                detail="Inspection version conflict",
            )

    @staticmethod
    def _require_status(
        record: QualityInspectionRecord,
        allowed: set[InspectionStatus],
    ) -> None:

        if record.status not in allowed:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Operation is not allowed "
                    f"in status {record.status.value}"
                ),
            )

    @staticmethod
    def _add_event(
        record: QualityInspectionRecord,
        event_type: QualityEventType,
        actor_id: str,
        details: str | None = None,
    ) -> None:

        if (
            len(record.events)
            >= MAX_EVENTS_PER_INSPECTION
        ):
            raise HTTPException(
                status_code=503,
                detail="Inspection event capacity reached",
            )

        record.events.append(
            QualityEventResponse(
                event_id=secrets.token_urlsafe(16),
                event_type=event_type,
                actor_id=actor_id,
                details=details,
                created_at=utc_now(),
            )
        )

    @staticmethod
    def _touch(
        record: QualityInspectionRecord,
    ) -> None:

        record.version += 1
        record.updated_at = utc_now()

    async def create(
        self,
        *,
        principal: Principal,
        payload: QualityInspectionCreate,
    ) -> QualityInspectionResponse:

        require_quality_access(
            principal,
            payload.warehouse_id,
            write=True,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = request_fingerprint(
            payload
        )

        async with self._lock:

            previous = self._idempotency.get(
                key
            )

            if previous is not None:

                old_hash, inspection_id = previous

                if old_hash != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return to_response(
                    self._get(
                        principal,
                        inspection_id,
                        write=False,
                    )
                )

            tenant_count = sum(
                record.tenant_id
                == principal.tenant_id
                for record in self._inspections.values()
            )

            if (
                tenant_count
                >= MAX_INSPECTIONS_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Quality inspection capacity reached",
                )

            record = QualityInspectionRecord(
                inspection_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                product_id=payload.product_id,
                batch_id=payload.batch_id,
                supplier_id=payload.supplier_id,
                purchase_order_id=payload.purchase_order_id,
                inspection_type=payload.inspection_type,
                batch_quantity=payload.batch_quantity,
                sample_quantity=payload.sample_quantity,
                maximum_defect_percent=(
                    payload.maximum_defect_percent
                ),
                created_by=principal.principal_id,
                notes=payload.notes,
            )

            self._add_event(
                record,
                QualityEventType.CREATED,
                principal.principal_id,
            )

            self._inspections[
                record.inspection_id
            ] = record

            self._idempotency[key] = (
                request_hash,
                record.inspection_id,
            )

            return to_response(record)

    async def get(
        self,
        *,
        principal: Principal,
        inspection_id: str,
    ) -> QualityInspectionDetailResponse:

        async with self._lock:

            return to_detail(
                self._get(
                    principal,
                    inspection_id,
                    write=False,
                )
            )

    async def list_inspections(
        self,
        *,
        principal: Principal,
        warehouse_id: str | None,
        status: InspectionStatus | None,
        limit: int,
    ) -> list[QualityInspectionResponse]:

        if warehouse_id is not None:
            require_quality_access(
                principal,
                warehouse_id,
                write=False,
            )

        async with self._lock:

            records = [
                record
                for record in self._inspections.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and (
                        warehouse_id is None
                        or record.warehouse_id
                        == warehouse_id
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
                    require_quality_access(
                        principal,
                        record.warehouse_id,
                        write=False,
                    )

                except HTTPException:
                    continue

                results.append(
                    to_response(record)
                )

                if len(results) >= limit:
                    break

            return results

    async def assign(
        self,
        *,
        principal: Principal,
        inspection_id: str,
        payload: QualityAssignment,
    ) -> QualityInspectionResponse:

        async with self._lock:

            record = self._get(
                principal,
                inspection_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {InspectionStatus.CREATED},
            )

            record.inspector_id = payload.inspector_id
            record.status = InspectionStatus.ASSIGNED

            self._add_event(
                record,
                QualityEventType.ASSIGNED,
                principal.principal_id,
                payload.inspector_id,
            )

            self._touch(record)

            return to_response(record)

    async def start(
        self,
        *,
        principal: Principal,
        inspection_id: str,
        expected_version: int,
    ) -> QualityInspectionResponse:

        async with self._lock:

            record = self._get(
                principal,
                inspection_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            self._require_status(
                record,
                {InspectionStatus.ASSIGNED},
            )

            record.status = InspectionStatus.IN_PROGRESS

            self._add_event(
                record,
                QualityEventType.STARTED,
                principal.principal_id,
            )

            self._touch(record)

            return to_response(record)

    async def record_defect(
        self,
        *,
        principal: Principal,
        inspection_id: str,
        payload: DefectCreate,
    ) -> QualityInspectionDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                inspection_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {InspectionStatus.IN_PROGRESS},
            )

            if (
                len(record.defects)
                >= MAX_DEFECTS_PER_INSPECTION
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Defect record capacity reached",
                )

            if (
                payload.affected_quantity
                > record.sample_quantity
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Affected quantity exceeds sample size",
                )

            defect = QualityDefectRecord(
                defect_id=secrets.token_urlsafe(16),
                category=payload.category,
                severity=payload.severity,
                affected_quantity=payload.affected_quantity,
                description=payload.description,
                evidence_reference=payload.evidence_reference,
                ai_detected=payload.ai_detected,
                model_reference=payload.model_reference,
                recorded_by=principal.principal_id,
            )

            self._add_event(
                record,
                QualityEventType.DEFECT_RECORDED,
                principal.principal_id,
                defect.defect_id,
            )

            record.defects[
                defect.defect_id
            ] = defect

            self._touch(record)

            return to_detail(record)

    async def submit_review(
        self,
        *,
        principal: Principal,
        inspection_id: str,
        payload: QualityReviewSubmit,
    ) -> QualityInspectionResponse:

        async with self._lock:

            record = self._get(
                principal,
                inspection_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {InspectionStatus.IN_PROGRESS},
            )

            if (
                payload.inspected_quantity
                != record.sample_quantity
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Inspected quantity must equal planned sample",
                )

            # Individual defect records can overlap.
            # Therefore, their affected quantities
            # must not be summed to infer unique
            # defective units.

            if (
                payload.defective_units == 0
                and record.defects
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Recorded defects require defective units",
                )

            record.inspected_quantity = (
                payload.inspected_quantity
            )

            record.defective_units = (
                payload.defective_units
            )

            record.recommendation_notes = (
                payload.recommendation_notes
            )

            defect_rate = percentage(
                record.defective_units,
                record.inspected_quantity,
            )

            critical_defect = any(
                defect.severity
                == DefectSeverity.CRITICAL
                for defect in record.defects.values()
            )

            if critical_defect:

                record.result = QualityResult.FAIL

            elif (
                defect_rate
                > record.maximum_defect_percent
            ):

                record.result = QualityResult.FAIL

            elif any(
                defect.severity == DefectSeverity.MAJOR
                for defect in record.defects.values()
            ):

                record.result = QualityResult.CONDITIONAL

            else:

                record.result = QualityResult.PASS

            if record.result != QualityResult.PASS:

                record.quarantine_status = (
                    QuarantineStatus.RECOMMENDED
                )

            record.status = (
                InspectionStatus.REVIEW_PENDING
            )

            self._add_event(
                record,
                QualityEventType.REVIEW_SUBMITTED,
                principal.principal_id,
                record.result.value,
            )

            self._touch(record)

            return to_response(record)

    async def decide(
        self,
        *,
        principal: Principal,
        inspection_id: str,
        payload: QualityDecisionRequest,
        approve: bool,
    ) -> QualityInspectionResponse:

        async with self._lock:

            record = self._get(
                principal,
                inspection_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {InspectionStatus.REVIEW_PENDING},
            )

            if principal.principal_id in {
                record.created_by,
                record.inspector_id,
            }:
                raise HTTPException(
                    status_code=403,
                    detail="Inspection creator or inspector cannot approve",
                )

            # Never approve a failed or conditional
            # inspection through this simple endpoint.
            # Conditional release requires a separate
            # documented exception workflow.

            if (
                approve
                and record.result != QualityResult.PASS
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Only passing inspections may be approved",
                )

            record.status = (
                InspectionStatus.APPROVED
                if approve
                else InspectionStatus.REJECTED
            )

            record.decision_notes = (
                payload.decision_notes
            )

            record.completed_at = utc_now()

            if not approve:
                record.quarantine_status = (
                    QuarantineStatus.RECOMMENDED
                )

            self._add_event(
                record,
                (
                    QualityEventType.APPROVED
                    if approve
                    else QualityEventType.REJECTED
                ),
                principal.principal_id,
                payload.decision_notes,
            )

            self._touch(record)

            return to_response(record)

    async def approve_quarantine(
        self,
        *,
        principal: Principal,
        inspection_id: str,
        expected_version: int,
    ) -> QualityInspectionResponse:

        async with self._lock:

            record = self._get(
                principal,
                inspection_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            if (
                record.quarantine_status
                != QuarantineStatus.RECOMMENDED
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Quarantine is not recommended",
                )

            # Production requires a dedicated
            # quarantine permission and an atomic
            # inventory hold transaction.

            self._add_event(
                record,
                QualityEventType.QUARANTINE_APPROVED,
                principal.principal_id,
            )

            record.quarantine_status = (
                QuarantineStatus.APPROVED
            )

            self._touch(record)

            return to_response(record)

    async def release_quarantine(
        self,
        *,
        principal: Principal,
        inspection_id: str,
        expected_version: int,
    ) -> QualityInspectionResponse:

        async with self._lock:

            record = self._get(
                principal,
                inspection_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            if (
                record.quarantine_status
                != QuarantineStatus.APPROVED
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Batch is not quarantined",
                )

            if (
                record.status
                != InspectionStatus.APPROVED
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Quality approval required for release",
                )

            self._add_event(
                record,
                QualityEventType.QUARANTINE_RELEASED,
                principal.principal_id,
            )

            record.quarantine_status = (
                QuarantineStatus.RELEASED
            )

            self._touch(record)

            return to_response(record)

    async def create_corrective_action(
        self,
        *,
        principal: Principal,
        inspection_id: str,
        payload: CorrectiveActionCreate,
    ) -> CorrectiveActionResponse:

        async with self._lock:

            record = self._get(
                principal,
                inspection_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status == InspectionStatus.CANCELLED:
                raise HTTPException(
                    status_code=409,
                    detail="Cancelled inspection cannot receive actions",
                )

            if (
                len(record.corrective_actions)
                >= MAX_ACTIONS_PER_INSPECTION
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Corrective action capacity reached",
                )

            action = CorrectiveActionRecord(
                action_id=secrets.token_urlsafe(16),
                title=payload.title,
                description=payload.description,
                owner_id=payload.owner_id,
                due_at=payload.due_at,
            )

            self._add_event(
                record,
                QualityEventType.CORRECTIVE_ACTION_CREATED,
                principal.principal_id,
                action.action_id,
            )

            record.corrective_actions[
                action.action_id
            ] = action

            self._touch(record)

            return to_action(action)

    async def update_corrective_action(
        self,
        *,
        principal: Principal,
        inspection_id: str,
        action_id: str,
        payload: CorrectiveActionUpdate,
    ) -> CorrectiveActionResponse:

        async with self._lock:

            record = self._get(
                principal,
                inspection_id,
                write=True,
            )

            action = record.corrective_actions.get(
                action_id
            )

            if action is None:
                raise HTTPException(
                    status_code=404,
                    detail="Corrective action not found",
                )

            if (
                action.version
                != payload.expected_action_version
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Corrective action version conflict",
                )

            allowed_transitions = {
                CorrectiveActionStatus.OPEN: {
                    CorrectiveActionStatus.IN_PROGRESS,
                    CorrectiveActionStatus.CANCELLED,
                },
                CorrectiveActionStatus.IN_PROGRESS: {
                    CorrectiveActionStatus.COMPLETED,
                    CorrectiveActionStatus.CANCELLED,
                },
                CorrectiveActionStatus.COMPLETED: {
                    CorrectiveActionStatus.VERIFIED,
                },
                CorrectiveActionStatus.VERIFIED: set(),
                CorrectiveActionStatus.CANCELLED: set(),
            }

            if (
                payload.status
                not in allowed_transitions[action.status]
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Invalid corrective action transition",
                )

            self._add_event(
                record,
                QualityEventType.CORRECTIVE_ACTION_UPDATED,
                principal.principal_id,
                action.action_id,
            )

            action.status = payload.status
            action.version += 1
            action.updated_at = utc_now()

            self._touch(record)

            return to_action(action)

    async def cancel(
        self,
        *,
        principal: Principal,
        inspection_id: str,
        payload: QualityCancelRequest,
    ) -> QualityInspectionResponse:

        async with self._lock:

            record = self._get(
                principal,
                inspection_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status in {
                InspectionStatus.APPROVED,
                InspectionStatus.REJECTED,
                InspectionStatus.CANCELLED,
            }:
                raise HTTPException(
                    status_code=409,
                    detail="Inspection cannot be cancelled",
                )

            self._add_event(
                record,
                QualityEventType.CANCELLED,
                principal.principal_id,
                payload.reason,
            )

            record.status = InspectionStatus.CANCELLED

            self._touch(record)

            return to_response(record)

    async def analytics(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
    ) -> QualityAnalyticsResponse:

        require_quality_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._inspections.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and record.warehouse_id
                    == warehouse_id
                )
            ]

            statuses = [
                record.status
                for record in records
            ]

            defects = [
                defect
                for record in records
                for defect in record.defects.values()
            ]

            actions = [
                action
                for record in records
                for action in record.corrective_actions.values()
            ]

            total_sampled = sum(
                record.inspected_quantity
                for record in records
            )

            total_defective = sum(
                record.defective_units
                for record in records
            )

            return QualityAnalyticsResponse(
                total_inspections=len(records),
                created=statuses.count(
                    InspectionStatus.CREATED
                ),
                assigned=statuses.count(
                    InspectionStatus.ASSIGNED
                ),
                in_progress=statuses.count(
                    InspectionStatus.IN_PROGRESS
                ),
                review_pending=statuses.count(
                    InspectionStatus.REVIEW_PENDING
                ),
                approved=statuses.count(
                    InspectionStatus.APPROVED
                ),
                rejected=statuses.count(
                    InspectionStatus.REJECTED
                ),
                cancelled=statuses.count(
                    InspectionStatus.CANCELLED
                ),
                total_sampled_units=total_sampled,
                total_defective_units=total_defective,
                overall_defect_rate_percent=percentage(
                    total_defective,
                    total_sampled,
                ),
                minor_defects=sum(
                    defect.severity
                    == DefectSeverity.MINOR
                    for defect in defects
                ),
                major_defects=sum(
                    defect.severity
                    == DefectSeverity.MAJOR
                    for defect in defects
                ),
                critical_defects=sum(
                    defect.severity
                    == DefectSeverity.CRITICAL
                    for defect in defects
                ),
                quarantine_recommended=sum(
                    record.quarantine_status
                    == QuarantineStatus.RECOMMENDED
                    for record in records
                ),
                quarantine_approved=sum(
                    record.quarantine_status
                    == QuarantineStatus.APPROVED
                    for record in records
                ),
                open_corrective_actions=sum(
                    action.status in {
                        CorrectiveActionStatus.OPEN,
                        CorrectiveActionStatus.IN_PROGRESS,
                    }
                    for action in actions
                ),
                completed_corrective_actions=sum(
                    action.status in {
                        CorrectiveActionStatus.COMPLETED,
                        CorrectiveActionStatus.VERIFIED,
                    }
                    for action in actions
                ),
            )


product_quality_store = ProductQualityStore()


# ============================================================
# SERVICE
# ============================================================

class ProductQualityService:

    def __init__(
        self,
        store: ProductQualityStore,
    ):
        self.store = store

    async def create(
        self,
        principal: Principal,
        payload: QualityInspectionCreate,
    ) -> QualityInspectionResponse:

        return await self.store.create(
            principal=principal,
            payload=payload,
        )


product_quality_service = ProductQualityService(
    product_quality_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Product Quality"],
)


@router.post(
    "",
    response_model=QualityInspectionResponse,
    status_code=201,
)
async def create_quality_inspection(
    payload: QualityInspectionCreate,
    principal: CurrentPrincipal,
):
    return await product_quality_service.create(
        principal,
        payload,
    )


@router.get(
    "",
    response_model=list[QualityInspectionResponse],
)
async def list_quality_inspections(
    principal: CurrentPrincipal,
    warehouse_id: str | None = None,
    status: InspectionStatus | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await product_quality_store.list_inspections(
        principal=principal,
        warehouse_id=warehouse_id,
        status=status,
        limit=limit,
    )


@router.get(
    "/analytics/{warehouse_id}",
    response_model=QualityAnalyticsResponse,
)
async def product_quality_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
):
    return await product_quality_store.analytics(
        principal=principal,
        warehouse_id=warehouse_id,
    )


@router.get(
    "/{inspection_id}",
    response_model=QualityInspectionDetailResponse,
)
async def get_quality_inspection(
    inspection_id: str,
    principal: CurrentPrincipal,
):
    return await product_quality_store.get(
        principal=principal,
        inspection_id=inspection_id,
    )


@router.post(
    "/{inspection_id}/assign",
    response_model=QualityInspectionResponse,
)
async def assign_quality_inspection(
    inspection_id: str,
    payload: QualityAssignment,
    principal: CurrentPrincipal,
):
    return await product_quality_store.assign(
        principal=principal,
        inspection_id=inspection_id,
        payload=payload,
    )


@router.post(
    "/{inspection_id}/start",
    response_model=QualityInspectionResponse,
)
async def start_quality_inspection(
    inspection_id: str,
    payload: QualityVersionRequest,
    principal: CurrentPrincipal,
):
    return await product_quality_store.start(
        principal=principal,
        inspection_id=inspection_id,
        expected_version=payload.expected_version,
    )


@router.post(
    "/{inspection_id}/defects",
    response_model=QualityInspectionDetailResponse,
)
async def record_quality_defect(
    inspection_id: str,
    payload: DefectCreate,
    principal: CurrentPrincipal,
):
    return await product_quality_store.record_defect(
        principal=principal,
        inspection_id=inspection_id,
        payload=payload,
    )


@router.post(
    "/{inspection_id}/submit-review",
    response_model=QualityInspectionResponse,
)
async def submit_quality_review(
    inspection_id: str,
    payload: QualityReviewSubmit,
    principal: CurrentPrincipal,
):
    return await product_quality_store.submit_review(
        principal=principal,
        inspection_id=inspection_id,
        payload=payload,
    )


@router.post(
    "/{inspection_id}/approve",
    response_model=QualityInspectionResponse,
)
async def approve_quality_inspection(
    inspection_id: str,
    payload: QualityDecisionRequest,
    principal: CurrentPrincipal,
):
    return await product_quality_store.decide(
        principal=principal,
        inspection_id=inspection_id,
        payload=payload,
        approve=True,
    )


@router.post(
    "/{inspection_id}/reject",
    response_model=QualityInspectionResponse,
)
async def reject_quality_inspection(
    inspection_id: str,
    payload: QualityDecisionRequest,
    principal: CurrentPrincipal,
):
    return await product_quality_store.decide(
        principal=principal,
        inspection_id=inspection_id,
        payload=payload,
        approve=False,
    )


@router.post(
    "/{inspection_id}/quarantine",
    response_model=QualityInspectionResponse,
)
async def approve_quality_quarantine(
    inspection_id: str,
    payload: QualityVersionRequest,
    principal: CurrentPrincipal,
):
    return await product_quality_store.approve_quarantine(
        principal=principal,
        inspection_id=inspection_id,
        expected_version=payload.expected_version,
    )


@router.post(
    "/{inspection_id}/release",
    response_model=QualityInspectionResponse,
)
async def release_quality_quarantine(
    inspection_id: str,
    payload: QualityVersionRequest,
    principal: CurrentPrincipal,
):
    return await product_quality_store.release_quarantine(
        principal=principal,
        inspection_id=inspection_id,
        expected_version=payload.expected_version,
    )


@router.post(
    "/{inspection_id}/corrective-actions",
    response_model=CorrectiveActionResponse,
    status_code=201,
)
async def create_quality_corrective_action(
    inspection_id: str,
    payload: CorrectiveActionCreate,
    principal: CurrentPrincipal,
):
    return await product_quality_store.create_corrective_action(
        principal=principal,
        inspection_id=inspection_id,
        payload=payload,
    )


@router.patch(
    "/{inspection_id}/corrective-actions/{action_id}",
    response_model=CorrectiveActionResponse,
)
async def update_quality_corrective_action(
    inspection_id: str,
    action_id: str,
    payload: CorrectiveActionUpdate,
    principal: CurrentPrincipal,
):
    return await product_quality_store.update_corrective_action(
        principal=principal,
        inspection_id=inspection_id,
        action_id=action_id,
        payload=payload,
    )


@router.post(
    "/{inspection_id}/cancel",
    response_model=QualityInspectionResponse,
)
async def cancel_quality_inspection(
    inspection_id: str,
    payload: QualityCancelRequest,
    principal: CurrentPrincipal,
):
    return await product_quality_store.cancel(
        principal=principal,
        inspection_id=inspection_id,
        payload=payload,
    )


__all__ = [
    "InspectionType",
    "InspectionStatus",
    "QualityResult",
    "DefectSeverity",
    "DefectCategory",
    "QuarantineStatus",
    "CorrectiveActionStatus",
    "QualityEventType",
    "QualityInspectionCreate",
    "QualityAssignment",
    "QualityVersionRequest",
    "DefectCreate",
    "QualityReviewSubmit",
    "QualityDecisionRequest",
    "CorrectiveActionCreate",
    "CorrectiveActionUpdate",
    "QualityCancelRequest",
    "QualityDefectResponse",
    "CorrectiveActionResponse",
    "QualityEventResponse",
    "QualityInspectionResponse",
    "QualityInspectionDetailResponse",
    "QualityAnalyticsResponse",
    "ProductQualityStore",
    "ProductQualityService",
    "product_quality_store",
    "product_quality_service",
    "router",
]
