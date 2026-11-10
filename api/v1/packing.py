from __future__ import annotations

"""Planned module: packing. Implementation pending."""

"""
backend/packing.py

Autonomous Retail Supply Chain AI 5.0
Warehouse Packing Management API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Warehouse packing jobs
    - Packing station assignment
    - Package item verification
    - Barcode/SKU verification
    - Packing material tracking
    - Package weight validation
    - Quality inspection
    - Packing completion
    - Dispatch readiness
    - Packing analytics
    - Tenant and warehouse isolation
    - Optimistic concurrency
    - Idempotent job creation

IMPORTANT:
    This is an in-memory prototype.
    It does not reserve inventory, print labels,
    control scales, or dispatch shipments.
"""


import asyncio
import hashlib
import json
import secrets

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

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


API_PREFIX = "/api/v1/packing"

MAX_JOBS_PER_TENANT = 50000
MAX_ITEMS_PER_JOB = 200
MAX_PACKAGES_PER_JOB = 100
MAX_EVENTS_PER_JOB = 300
MAX_IDEMPOTENCY_KEYS = 100000
MAX_LIST_LIMIT = 200


# ============================================================
# ENUMS
# ============================================================

class PackingStatus(str, Enum):
    CREATED = "created"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    VERIFICATION_PENDING = "verification_pending"
    QUALITY_CHECK = "quality_check"
    COMPLETED = "completed"
    READY_FOR_DISPATCH = "ready_for_dispatch"
    CANCELLED = "cancelled"


class PackageStatus(str, Enum):
    OPEN = "open"
    SEALED = "sealed"


class PackingPriority(str, Enum):
    STANDARD = "standard"
    EXPRESS = "express"
    CRITICAL = "critical"


class PackagingMaterial(str, Enum):
    CORRUGATED_BOX = "corrugated_box"
    POLY_MAILER = "poly_mailer"
    PAPER_MAILER = "paper_mailer"
    PADDED_ENVELOPE = "padded_envelope"
    WOODEN_CRATE = "wooden_crate"
    REUSABLE_CONTAINER = "reusable_container"


class QualityResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"


class PackingEventType(str, Enum):
    CREATED = "created"
    ASSIGNED = "assigned"
    STARTED = "started"
    PACKAGE_CREATED = "package_created"
    ITEM_PACKED = "item_packed"
    PACKAGE_SEALED = "package_sealed"
    VERIFICATION_STARTED = "verification_started"
    QUALITY_CHECK_STARTED = "quality_check_started"
    QUALITY_PASSED = "quality_passed"
    QUALITY_FAILED = "quality_failed"
    COMPLETED = "completed"
    READY_FOR_DISPATCH = "ready_for_dispatch"
    CANCELLED = "cancelled"


# ============================================================
# REQUEST SCHEMAS
# ============================================================

class PackingItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    sku: str = Field(
        min_length=1,
        max_length=100,
    )

    quantity: int = Field(
        gt=0,
        le=100000,
    )


class PackingJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    fulfillment_id: str = Field(
        min_length=1,
        max_length=128,
    )

    order_id: str = Field(
        min_length=1,
        max_length=128,
    )

    priority: PackingPriority = (
        PackingPriority.STANDARD
    )

    items: list[PackingItemCreate] = Field(
        min_length=1,
        max_length=MAX_ITEMS_PER_JOB,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_items(self):

        product_ids = [
            item.product_id
            for item in self.items
        ]

        if len(set(product_ids)) != len(
            product_ids
        ):
            raise ValueError(
                "Duplicate products are not allowed"
            )

        return self


class PackingAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    station_id: str = Field(
        min_length=1,
        max_length=128,
    )

    operator_id: str = Field(
        min_length=1,
        max_length=128,
    )

    expected_version: int = Field(ge=1)


class PackingVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class PackageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material: PackagingMaterial

    max_weight_kg: Decimal = Field(
        gt=0,
        max_digits=10,
        decimal_places=3,
    )

    expected_version: int = Field(ge=1)


class PackItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_id: str = Field(
        min_length=1,
        max_length=128,
    )

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    scanned_sku: str = Field(
        min_length=1,
        max_length=100,
    )

    quantity: int = Field(
        gt=0,
        le=100000,
    )

    expected_version: int = Field(ge=1)


class SealPackageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    measured_weight_kg: Decimal = Field(
        gt=0,
        max_digits=10,
        decimal_places=3,
    )

    label_reference: str = Field(
        min_length=1,
        max_length=200,
    )


class QualityInspectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    result: QualityResult

    inspection_reference: str = Field(
        min_length=1,
        max_length=200,
    )

    notes: str = Field(
        default="",
        max_length=1000,
    )


class PackingCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    reason: str = Field(
        min_length=3,
        max_length=500,
    )


# ============================================================
# RESPONSE SCHEMAS
# ============================================================

class PackingItemResponse(BaseModel):
    product_id: str
    sku: str

    required_quantity: int
    packed_quantity: int

    remaining_quantity: int


class PackageItemResponse(BaseModel):
    product_id: str
    sku: str
    quantity: int


class PackageResponse(BaseModel):
    package_id: str

    material: PackagingMaterial
    status: PackageStatus

    max_weight_kg: Decimal
    measured_weight_kg: Decimal | None

    label_reference: str | None

    items: list[PackageItemResponse]

    created_at: datetime
    sealed_at: datetime | None


class PackingEventResponse(BaseModel):
    event_id: str
    event_type: PackingEventType

    actor_id: str
    details: str | None

    created_at: datetime


class PackingJobResponse(BaseModel):
    packing_job_id: str

    warehouse_id: str
    fulfillment_id: str
    order_id: str

    priority: PackingPriority
    status: PackingStatus

    station_id: str | None
    operator_id: str | None

    items: list[PackingItemResponse]

    package_count: int

    quality_result: QualityResult | None

    version: int

    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class PackingJobDetailResponse(PackingJobResponse):
    packages: list[PackageResponse]
    events: list[PackingEventResponse]


class PackingAnalyticsResponse(BaseModel):
    total_jobs: int
    created_jobs: int
    assigned_jobs: int
    in_progress_jobs: int
    verification_pending_jobs: int
    quality_check_jobs: int
    completed_jobs: int
    ready_for_dispatch_jobs: int
    cancelled_jobs: int

    total_packages: int
    sealed_packages: int

    quality_passed_jobs: int
    quality_failed_jobs: int

    average_completion_minutes: float | None


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass
class PackingItemRecord:
    product_id: str
    sku: str

    required_quantity: int
    packed_quantity: int = 0


@dataclass
class PackageRecord:
    package_id: str

    material: PackagingMaterial
    max_weight_kg: Decimal

    status: PackageStatus = (
        PackageStatus.OPEN
    )

    measured_weight_kg: Decimal | None = None
    label_reference: str | None = None

    items: dict[str, int] = field(
        default_factory=dict
    )

    created_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    sealed_at: datetime | None = None


@dataclass
class PackingJobRecord:
    packing_job_id: str
    tenant_id: str

    warehouse_id: str
    fulfillment_id: str
    order_id: str

    priority: PackingPriority

    items: dict[
        str,
        PackingItemRecord,
    ]

    created_by: str

    status: PackingStatus = (
        PackingStatus.CREATED
    )

    station_id: str | None = None
    operator_id: str | None = None

    packages: dict[
        str,
        PackageRecord,
    ] = field(default_factory=dict)

    events: list[
        PackingEventResponse
    ] = field(default_factory=list)

    quality_result: QualityResult | None = None
    quality_reference: str | None = None

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


def request_fingerprint(
    payload: PackingJobCreate,
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


def require_packing_access(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool,
) -> None:

    # Existing inventory permissions are
    # temporary mappings.
    #
    # Production should add:
    # PACKING_READ
    # PACKING_WRITE
    # PACKING_QUALITY_APPROVE

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
            detail="Packing access denied",
        )


def item_response(
    item: PackingItemRecord,
) -> PackingItemResponse:

    return PackingItemResponse(
        product_id=item.product_id,
        sku=item.sku,
        required_quantity=item.required_quantity,
        packed_quantity=item.packed_quantity,
        remaining_quantity=(
            item.required_quantity
            - item.packed_quantity
        ),
    )


def package_response(
    package: PackageRecord,
    items: dict[str, PackingItemRecord],
) -> PackageResponse:

    return PackageResponse(
        package_id=package.package_id,
        material=package.material,
        status=package.status,
        max_weight_kg=package.max_weight_kg,
        measured_weight_kg=package.measured_weight_kg,
        label_reference=package.label_reference,
        items=[
            PackageItemResponse(
                product_id=product_id,
                sku=items[product_id].sku,
                quantity=quantity,
            )
            for product_id, quantity
            in package.items.items()
        ],
        created_at=package.created_at,
        sealed_at=package.sealed_at,
    )


def to_response(
    record: PackingJobRecord,
) -> PackingJobResponse:

    return PackingJobResponse(
        packing_job_id=record.packing_job_id,
        warehouse_id=record.warehouse_id,
        fulfillment_id=record.fulfillment_id,
        order_id=record.order_id,
        priority=record.priority,
        status=record.status,
        station_id=record.station_id,
        operator_id=record.operator_id,
        items=[
            item_response(item)
            for item in record.items.values()
        ],
        package_count=len(record.packages),
        quality_result=record.quality_result,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        completed_at=record.completed_at,
    )


def to_detail(
    record: PackingJobRecord,
) -> PackingJobDetailResponse:

    return PackingJobDetailResponse(
        **to_response(record).model_dump(),
        packages=[
            package_response(
                package,
                record.items,
            )
            for package in record.packages.values()
        ],
        events=list(record.events),
    )


# ============================================================
# PACKING STORE
# ============================================================

class PackingStore:

    def __init__(self):

        self._jobs: dict[
            str,
            PackingJobRecord,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    def _get(
        self,
        principal: Principal,
        packing_job_id: str,
        *,
        write: bool,
    ) -> PackingJobRecord:

        record = self._jobs.get(
            packing_job_id
        )

        if (
            record is None
            or record.tenant_id
            != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Packing job not found",
            )

        require_packing_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    @staticmethod
    def _check_version(
        record: PackingJobRecord,
        expected_version: int,
    ) -> None:

        if record.version != expected_version:
            raise HTTPException(
                status_code=409,
                detail="Packing job version conflict",
            )

    @staticmethod
    def _require_status(
        record: PackingJobRecord,
        allowed: set[PackingStatus],
    ) -> None:

        if record.status not in allowed:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Packing operation is not allowed "
                    f"in status {record.status.value}"
                ),
            )

    @staticmethod
    def _add_event(
        record: PackingJobRecord,
        event_type: PackingEventType,
        actor_id: str,
        details: str | None = None,
    ) -> None:

        if (
            len(record.events)
            >= MAX_EVENTS_PER_JOB
        ):
            raise HTTPException(
                status_code=503,
                detail="Packing event capacity reached",
            )

        record.events.append(
            PackingEventResponse(
                event_id=secrets.token_urlsafe(16),
                event_type=event_type,
                actor_id=actor_id,
                details=details,
                created_at=utc_now(),
            )
        )

    @staticmethod
    def _touch(
        record: PackingJobRecord,
    ) -> None:

        record.version += 1
        record.updated_at = utc_now()

    async def create(
        self,
        *,
        principal: Principal,
        payload: PackingJobCreate,
    ) -> PackingJobResponse:

        require_packing_access(
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

                old_hash, packing_job_id = previous

                if old_hash != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return to_response(
                    self._get(
                        principal,
                        packing_job_id,
                        write=False,
                    )
                )

            tenant_count = sum(
                job.tenant_id
                == principal.tenant_id
                for job in self._jobs.values()
            )

            if (
                tenant_count >= MAX_JOBS_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Packing capacity reached",
                )

            record = PackingJobRecord(
                packing_job_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                fulfillment_id=payload.fulfillment_id,
                order_id=payload.order_id,
                priority=payload.priority,
                items={
                    item.product_id: PackingItemRecord(
                        product_id=item.product_id,
                        sku=item.sku,
                        required_quantity=item.quantity,
                    )
                    for item in payload.items
                },
                created_by=principal.principal_id,
            )

            self._add_event(
                record,
                PackingEventType.CREATED,
                principal.principal_id,
            )

            self._jobs[
                record.packing_job_id
            ] = record

            self._idempotency[key] = (
                request_hash,
                record.packing_job_id,
            )

            return to_response(record)

    async def get(
        self,
        *,
        principal: Principal,
        packing_job_id: str,
    ) -> PackingJobDetailResponse:

        async with self._lock:

            return to_detail(
                self._get(
                    principal,
                    packing_job_id,
                    write=False,
                )
            )

    async def list_jobs(
        self,
        *,
        principal: Principal,
        warehouse_id: str | None,
        status: PackingStatus | None,
        limit: int,
    ) -> list[PackingJobResponse]:

        if warehouse_id is not None:
            require_packing_access(
                principal,
                warehouse_id,
                write=False,
            )

        async with self._lock:

            records = [
                record
                for record in self._jobs.values()
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
                    require_packing_access(
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
        packing_job_id: str,
        payload: PackingAssignment,
    ) -> PackingJobResponse:

        async with self._lock:

            record = self._get(
                principal,
                packing_job_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {PackingStatus.CREATED},
            )

            record.station_id = payload.station_id
            record.operator_id = payload.operator_id
            record.status = PackingStatus.ASSIGNED

            self._add_event(
                record,
                PackingEventType.ASSIGNED,
                principal.principal_id,
                f"Station: {payload.station_id}",
            )

            self._touch(record)

            return to_response(record)

    async def start(
        self,
        *,
        principal: Principal,
        packing_job_id: str,
        expected_version: int,
    ) -> PackingJobResponse:

        async with self._lock:

            record = self._get(
                principal,
                packing_job_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            self._require_status(
                record,
                {PackingStatus.ASSIGNED},
            )

            record.status = PackingStatus.IN_PROGRESS

            self._add_event(
                record,
                PackingEventType.STARTED,
                principal.principal_id,
            )

            self._touch(record)

            return to_response(record)

    async def create_package(
        self,
        *,
        principal: Principal,
        packing_job_id: str,
        payload: PackageCreate,
    ) -> PackingJobDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                packing_job_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {PackingStatus.IN_PROGRESS},
            )

            if (
                len(record.packages)
                >= MAX_PACKAGES_PER_JOB
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Package limit reached",
                )

            package = PackageRecord(
                package_id=secrets.token_urlsafe(16),
                material=payload.material,
                max_weight_kg=payload.max_weight_kg,
            )

            self._add_event(
                record,
                PackingEventType.PACKAGE_CREATED,
                principal.principal_id,
                package.package_id,
            )

            record.packages[
                package.package_id
            ] = package

            self._touch(record)

            return to_detail(record)

    async def pack_item(
        self,
        *,
        principal: Principal,
        packing_job_id: str,
        payload: PackItemRequest,
    ) -> PackingJobDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                packing_job_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {PackingStatus.IN_PROGRESS},
            )

            package = record.packages.get(
                payload.package_id
            )

            if package is None:
                raise HTTPException(
                    status_code=404,
                    detail="Package not found",
                )

            if package.status != PackageStatus.OPEN:
                raise HTTPException(
                    status_code=409,
                    detail="Package is sealed",
                )

            item = record.items.get(
                payload.product_id
            )

            if item is None:
                raise HTTPException(
                    status_code=404,
                    detail="Product not in packing job",
                )

            if item.sku != payload.scanned_sku:
                raise HTTPException(
                    status_code=422,
                    detail="Scanned SKU mismatch",
                )

            remaining = (
                item.required_quantity
                - item.packed_quantity
            )

            if payload.quantity > remaining:
                raise HTTPException(
                    status_code=409,
                    detail="Packed quantity exceeds requirement",
                )

            self._add_event(
                record,
                PackingEventType.ITEM_PACKED,
                principal.principal_id,
                (
                    f"{payload.product_id}: "
                    f"{payload.quantity}"
                ),
            )

            item.packed_quantity += payload.quantity

            package.items[
                payload.product_id
            ] = (
                package.items.get(
                    payload.product_id,
                    0,
                )
                + payload.quantity
            )

            self._touch(record)

            return to_detail(record)

    async def seal_package(
        self,
        *,
        principal: Principal,
        packing_job_id: str,
        package_id: str,
        payload: SealPackageRequest,
    ) -> PackingJobDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                packing_job_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {PackingStatus.IN_PROGRESS},
            )

            package = record.packages.get(
                package_id
            )

            if package is None:
                raise HTTPException(
                    status_code=404,
                    detail="Package not found",
                )

            if package.status != PackageStatus.OPEN:
                raise HTTPException(
                    status_code=409,
                    detail="Package already sealed",
                )

            if not package.items:
                raise HTTPException(
                    status_code=409,
                    detail="Cannot seal an empty package",
                )

            if (
                payload.measured_weight_kg
                > package.max_weight_kg
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Package exceeds maximum weight",
                )

            self._add_event(
                record,
                PackingEventType.PACKAGE_SEALED,
                principal.principal_id,
                package_id,
            )

            package.status = PackageStatus.SEALED
            package.measured_weight_kg = (
                payload.measured_weight_kg
            )
            package.label_reference = (
                payload.label_reference
            )
            package.sealed_at = utc_now()

            self._touch(record)

            return to_detail(record)

    async def start_verification(
        self,
        *,
        principal: Principal,
        packing_job_id: str,
        expected_version: int,
    ) -> PackingJobResponse:

        async with self._lock:

            record = self._get(
                principal,
                packing_job_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            self._require_status(
                record,
                {PackingStatus.IN_PROGRESS},
            )

            if not record.packages:
                raise HTTPException(
                    status_code=409,
                    detail="No packages created",
                )

            if any(
                item.packed_quantity
                != item.required_quantity
                for item in record.items.values()
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Packing quantities are incomplete",
                )

            if any(
                package.status
                != PackageStatus.SEALED
                for package in record.packages.values()
            ):
                raise HTTPException(
                    status_code=409,
                    detail="All packages must be sealed",
                )

            record.status = (
                PackingStatus.VERIFICATION_PENDING
            )

            self._add_event(
                record,
                PackingEventType.VERIFICATION_STARTED,
                principal.principal_id,
            )

            self._touch(record)

            return to_response(record)

    async def start_quality_check(
        self,
        *,
        principal: Principal,
        packing_job_id: str,
        expected_version: int,
    ) -> PackingJobResponse:

        async with self._lock:

            record = self._get(
                principal,
                packing_job_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            self._require_status(
                record,
                {PackingStatus.VERIFICATION_PENDING},
            )

            record.status = PackingStatus.QUALITY_CHECK

            self._add_event(
                record,
                PackingEventType.QUALITY_CHECK_STARTED,
                principal.principal_id,
            )

            self._touch(record)

            return to_response(record)

    async def inspect_quality(
        self,
        *,
        principal: Principal,
        packing_job_id: str,
        payload: QualityInspectionRequest,
    ) -> PackingJobResponse:

        async with self._lock:

            record = self._get(
                principal,
                packing_job_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            self._require_status(
                record,
                {PackingStatus.QUALITY_CHECK},
            )

            record.quality_result = payload.result
            record.quality_reference = (
                payload.inspection_reference
            )

            if payload.result == QualityResult.PASS:

                event_type = (
                    PackingEventType.QUALITY_PASSED
                )

            else:

                event_type = (
                    PackingEventType.QUALITY_FAILED
                )

                # Failed jobs return to packing
                # for inspection and rework.
                # Reopening sealed packages needs
                # a dedicated audited workflow.
                record.status = PackingStatus.IN_PROGRESS

            self._add_event(
                record,
                event_type,
                principal.principal_id,
                payload.inspection_reference,
            )

            self._touch(record)

            return to_response(record)

    async def complete(
        self,
        *,
        principal: Principal,
        packing_job_id: str,
        expected_version: int,
    ) -> PackingJobResponse:

        async with self._lock:

            record = self._get(
                principal,
                packing_job_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            self._require_status(
                record,
                {PackingStatus.QUALITY_CHECK},
            )

            if record.quality_result != QualityResult.PASS:
                raise HTTPException(
                    status_code=409,
                    detail="Quality inspection must pass",
                )

            record.status = PackingStatus.COMPLETED
            record.completed_at = utc_now()

            self._add_event(
                record,
                PackingEventType.COMPLETED,
                principal.principal_id,
            )

            self._touch(record)

            return to_response(record)

    async def ready_for_dispatch(
        self,
        *,
        principal: Principal,
        packing_job_id: str,
        expected_version: int,
    ) -> PackingJobResponse:

        async with self._lock:

            record = self._get(
                principal,
                packing_job_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            self._require_status(
                record,
                {PackingStatus.COMPLETED},
            )

            record.status = (
                PackingStatus.READY_FOR_DISPATCH
            )

            self._add_event(
                record,
                PackingEventType.READY_FOR_DISPATCH,
                principal.principal_id,
            )

            self._touch(record)

            return to_response(record)

    async def cancel(
        self,
        *,
        principal: Principal,
        packing_job_id: str,
        payload: PackingCancelRequest,
    ) -> PackingJobResponse:

        async with self._lock:

            record = self._get(
                principal,
                packing_job_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status in {
                PackingStatus.COMPLETED,
                PackingStatus.READY_FOR_DISPATCH,
                PackingStatus.CANCELLED,
            }:
                raise HTTPException(
                    status_code=409,
                    detail="Packing job cannot be cancelled",
                )

            self._add_event(
                record,
                PackingEventType.CANCELLED,
                principal.principal_id,
                payload.reason,
            )

            record.status = PackingStatus.CANCELLED

            self._touch(record)

            return to_response(record)

    async def analytics(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
    ) -> PackingAnalyticsResponse:

        require_packing_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._jobs.values()
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

            packages = [
                package
                for record in records
                for package in record.packages.values()
            ]

            durations = [
                (
                    record.completed_at
                    - record.created_at
                ).total_seconds() / 60
                for record in records
                if record.completed_at is not None
            ]

            return PackingAnalyticsResponse(
                total_jobs=len(records),
                created_jobs=statuses.count(
                    PackingStatus.CREATED
                ),
                assigned_jobs=statuses.count(
                    PackingStatus.ASSIGNED
                ),
                in_progress_jobs=statuses.count(
                    PackingStatus.IN_PROGRESS
                ),
                verification_pending_jobs=statuses.count(
                    PackingStatus.VERIFICATION_PENDING
                ),
                quality_check_jobs=statuses.count(
                    PackingStatus.QUALITY_CHECK
                ),
                completed_jobs=statuses.count(
                    PackingStatus.COMPLETED
                ),
                ready_for_dispatch_jobs=statuses.count(
                    PackingStatus.READY_FOR_DISPATCH
                ),
                cancelled_jobs=statuses.count(
                    PackingStatus.CANCELLED
                ),
                total_packages=len(packages),
                sealed_packages=sum(
                    package.status == PackageStatus.SEALED
                    for package in packages
                ),
                quality_passed_jobs=sum(
                    record.quality_result
                    == QualityResult.PASS
                    for record in records
                ),
                quality_failed_jobs=sum(
                    record.quality_result
                    == QualityResult.FAIL
                    for record in records
                ),
                average_completion_minutes=(
                    round(
                        sum(durations) / len(durations),
                        2,
                    )
                    if durations
                    else None
                ),
            )


packing_store = PackingStore()


# ============================================================
# SERVICE
# ============================================================

class PackingService:

    def __init__(
        self,
        store: PackingStore,
    ):
        self.store = store

    async def create(
        self,
        principal: Principal,
        payload: PackingJobCreate,
    ) -> PackingJobResponse:

        return await self.store.create(
            principal=principal,
            payload=payload,
        )


packing_service = PackingService(
    packing_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Warehouse Packing"],
)


@router.post(
    "",
    response_model=PackingJobResponse,
    status_code=201,
)
async def create_packing_job(
    payload: PackingJobCreate,
    principal: CurrentPrincipal,
):
    return await packing_service.create(
        principal,
        payload,
    )


@router.get(
    "",
    response_model=list[PackingJobResponse],
)
async def list_packing_jobs(
    principal: CurrentPrincipal,
    warehouse_id: str | None = None,
    status: PackingStatus | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await packing_store.list_jobs(
        principal=principal,
        warehouse_id=warehouse_id,
        status=status,
        limit=limit,
    )


@router.get(
    "/analytics/{warehouse_id}",
    response_model=PackingAnalyticsResponse,
)
async def packing_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
):
    return await packing_store.analytics(
        principal=principal,
        warehouse_id=warehouse_id,
    )


@router.get(
    "/{packing_job_id}",
    response_model=PackingJobDetailResponse,
)
async def get_packing_job(
    packing_job_id: str,
    principal: CurrentPrincipal,
):
    return await packing_store.get(
        principal=principal,
        packing_job_id=packing_job_id,
    )


@router.post(
    "/{packing_job_id}/assign",
    response_model=PackingJobResponse,
)
async def assign_packing_job(
    packing_job_id: str,
    payload: PackingAssignment,
    principal: CurrentPrincipal,
):
    return await packing_store.assign(
        principal=principal,
        packing_job_id=packing_job_id,
        payload=payload,
    )


@router.post(
    "/{packing_job_id}/start",
    response_model=PackingJobResponse,
)
async def start_packing_job(
    packing_job_id: str,
    payload: PackingVersionRequest,
    principal: CurrentPrincipal,
):
    return await packing_store.start(
        principal=principal,
        packing_job_id=packing_job_id,
        expected_version=payload.expected_version,
    )


@router.post(
    "/{packing_job_id}/packages",
    response_model=PackingJobDetailResponse,
)
async def create_packing_package(
    packing_job_id: str,
    payload: PackageCreate,
    principal: CurrentPrincipal,
):
    return await packing_store.create_package(
        principal=principal,
        packing_job_id=packing_job_id,
        payload=payload,
    )


@router.post(
    "/{packing_job_id}/pack-item",
    response_model=PackingJobDetailResponse,
)
async def pack_packing_item(
    packing_job_id: str,
    payload: PackItemRequest,
    principal: CurrentPrincipal,
):
    return await packing_store.pack_item(
        principal=principal,
        packing_job_id=packing_job_id,
        payload=payload,
    )


@router.post(
    "/{packing_job_id}/packages/{package_id}/seal",
    response_model=PackingJobDetailResponse,
)
async def seal_packing_package(
    packing_job_id: str,
    package_id: str,
    payload: SealPackageRequest,
    principal: CurrentPrincipal,
):
    return await packing_store.seal_package(
        principal=principal,
        packing_job_id=packing_job_id,
        package_id=package_id,
        payload=payload,
    )


@router.post(
    "/{packing_job_id}/verify",
    response_model=PackingJobResponse,
)
async def verify_packing_job(
    packing_job_id: str,
    payload: PackingVersionRequest,
    principal: CurrentPrincipal,
):
    return await packing_store.start_verification(
        principal=principal,
        packing_job_id=packing_job_id,
        expected_version=payload.expected_version,
    )


@router.post(
    "/{packing_job_id}/quality-check",
    response_model=PackingJobResponse,
)
async def start_packing_quality_check(
    packing_job_id: str,
    payload: PackingVersionRequest,
    principal: CurrentPrincipal,
):
    return await packing_store.start_quality_check(
        principal=principal,
        packing_job_id=packing_job_id,
        expected_version=payload.expected_version,
    )


@router.post(
    "/{packing_job_id}/inspect",
    response_model=PackingJobResponse,
)
async def inspect_packing_quality(
    packing_job_id: str,
    payload: QualityInspectionRequest,
    principal: CurrentPrincipal,
):
    return await packing_store.inspect_quality(
        principal=principal,
        packing_job_id=packing_job_id,
        payload=payload,
    )


@router.post(
    "/{packing_job_id}/complete",
    response_model=PackingJobResponse,
)
async def complete_packing_job(
    packing_job_id: str,
    payload: PackingVersionRequest,
    principal: CurrentPrincipal,
):
    return await packing_store.complete(
        principal=principal,
        packing_job_id=packing_job_id,
        expected_version=payload.expected_version,
    )


@router.post(
    "/{packing_job_id}/ready",
    response_model=PackingJobResponse,
)
async def mark_packing_ready(
    packing_job_id: str,
    payload: PackingVersionRequest,
    principal: CurrentPrincipal,
):
    return await packing_store.ready_for_dispatch(
        principal=principal,
        packing_job_id=packing_job_id,
        expected_version=payload.expected_version,
    )


@router.post(
    "/{packing_job_id}/cancel",
    response_model=PackingJobResponse,
)
async def cancel_packing_job(
    packing_job_id: str,
    payload: PackingCancelRequest,
    principal: CurrentPrincipal,
):
    return await packing_store.cancel(
        principal=principal,
        packing_job_id=packing_job_id,
        payload=payload,
    )


__all__ = [
    "PackingStatus",
    "PackageStatus",
    "PackingPriority",
    "PackagingMaterial",
    "QualityResult",
    "PackingEventType",
    "PackingItemCreate",
    "PackingJobCreate",
    "PackingAssignment",
    "PackingVersionRequest",
    "PackageCreate",
    "PackItemRequest",
    "SealPackageRequest",
    "QualityInspectionRequest",
    "PackingCancelRequest",
    "PackingItemResponse",
    "PackageItemResponse",
    "PackageResponse",
    "PackingEventResponse",
    "PackingJobResponse",
    "PackingJobDetailResponse",
    "PackingAnalyticsResponse",
    "PackingStore",
    "PackingService",
    "packing_store",
    "packing_service",
    "router",
]
