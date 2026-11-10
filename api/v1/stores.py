from __future__ import annotations

"""Planned module: stores. Implementation pending."""

"""
backend/stores.py

Autonomous Retail Supply Chain AI 5.0
Multi-Tenant Retail Store Management API

Python 3.11+
Dependencies: fastapi, pydantic>=2

Features:
- Store and branch registration
- Unique store codes per tenant
- Address and contact details
- Weekly opening hours
- Warehouse associations
- Store manager assignment
- Store lifecycle management
- Tenant and warehouse authorization
- Idempotent store creation
- Optimistic concurrency
- Store analytics

Prototype: in-memory, single-process storage.
"""


import asyncio
import hashlib
import json
import secrets

from dataclasses import dataclass, field
from datetime import datetime, timezone, time
from enum import Enum

from fastapi import APIRouter, HTTPException, Query
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


API_PREFIX = "/api/v1/stores"

MAX_STORES_PER_TENANT = 10000
MAX_WAREHOUSES_PER_STORE = 20
MAX_EVENTS_PER_STORE = 1000
MAX_IDEMPOTENCY_KEYS = 100000
MAX_LIST_LIMIT = 200


# ============================================================
# ENUMS
# ============================================================

class StoreType(str, Enum):
    SUPERMARKET = "supermarket"
    HYPERMARKET = "hypermarket"
    CONVENIENCE = "convenience"
    DEPARTMENT = "department"
    SPECIALTY = "specialty"
    OUTLET = "outlet"
    DARK_STORE = "dark_store"
    OTHER = "other"


class StoreStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    TEMPORARILY_CLOSED = "temporarily_closed"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class StoreEventType(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    ACTIVATED = "activated"
    CLOSED = "closed"
    REOPENED = "reopened"
    DEACTIVATED = "deactivated"
    ARCHIVED = "archived"
    MANAGER_ASSIGNED = "manager_assigned"
    WAREHOUSE_LINKED = "warehouse_linked"
    WAREHOUSE_UNLINKED = "warehouse_unlinked"
    HOURS_UPDATED = "hours_updated"


class Weekday(str, Enum):
    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


# ============================================================
# REQUEST SCHEMAS
# ============================================================

class StoreAddress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line1: str = Field(min_length=3, max_length=250)
    line2: str | None = Field(default=None, max_length=250)
    city: str = Field(min_length=2, max_length=100)
    state: str = Field(min_length=2, max_length=100)
    postal_code: str = Field(min_length=3, max_length=20)
    country_code: str = Field(
        default="IN",
        pattern=r"^[A-Z]{2}$",
    )


class StoreContact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str | None = Field(
        default=None,
        max_length=254,
    )

    phone: str | None = Field(
        default=None,
        min_length=7,
        max_length=25,
    )

    @model_validator(mode="after")
    def validate_contact(self):
        if self.email:
            if (
                self.email.count("@") != 1
                or " " in self.email
                or "." not in self.email.split("@")[-1]
            ):
                raise ValueError("Invalid contact email")
        return self


class OpeningHours(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weekday: Weekday
    is_closed: bool = False
    opens_at: time | None = None
    closes_at: time | None = None

    @model_validator(mode="after")
    def validate_hours(self):

        if self.is_closed:
            if self.opens_at or self.closes_at:
                raise ValueError(
                    "Closed days cannot have opening hours"
                )
        else:
            if not self.opens_at or not self.closes_at:
                raise ValueError(
                    "Open days require opening and closing times"
                )

            if self.opens_at == self.closes_at:
                raise ValueError(
                    "Opening and closing times must differ"
                )

        return self


class StoreCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_code: str = Field(
        min_length=2,
        max_length=50,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

    name: str = Field(min_length=2, max_length=200)

    store_type: StoreType = StoreType.SUPERMARKET

    organization_id: str = Field(
        min_length=1,
        max_length=128,
    )

    address: StoreAddress
    contact: StoreContact = Field(
        default_factory=StoreContact
    )

    timezone_name: str = Field(
        default="Asia/Kolkata",
        min_length=3,
        max_length=100,
    )

    warehouse_ids: list[str] = Field(
        default_factory=list,
        max_length=MAX_WAREHOUSES_PER_STORE,
    )

    opening_hours: list[OpeningHours] = Field(
        default_factory=list,
        max_length=7,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_references(self):

        if len(self.warehouse_ids) != len(
            set(self.warehouse_ids)
        ):
            raise ValueError("Duplicate warehouse IDs")

        weekdays = [
            entry.weekday
            for entry in self.opening_hours
        ]

        if len(weekdays) != len(set(weekdays)):
            raise ValueError("Duplicate weekdays")

        return self


class StoreUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    name: str | None = Field(
        default=None,
        min_length=2,
        max_length=200,
    )

    address: StoreAddress | None = None
    contact: StoreContact | None = None
    timezone_name: str | None = Field(
        default=None,
        min_length=3,
        max_length=100,
    )


class StoreVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class StoreStatusRequest(StoreVersionRequest):
    reason: str = Field(min_length=3, max_length=500)


class StoreManagerAssignment(StoreVersionRequest):
    manager_id: str = Field(
        min_length=1,
        max_length=128,
    )


class StoreWarehouseRequest(StoreVersionRequest):
    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )


class StoreHoursUpdate(StoreVersionRequest):
    opening_hours: list[OpeningHours] = Field(
        max_length=7,
    )

    @model_validator(mode="after")
    def validate_days(self):

        weekdays = [
            item.weekday
            for item in self.opening_hours
        ]

        if len(weekdays) != len(set(weekdays)):
            raise ValueError("Duplicate weekdays")

        return self


# ============================================================
# RESPONSE SCHEMAS
# ============================================================

class StoreEventResponse(BaseModel):
    event_id: str
    event_type: StoreEventType
    actor_id: str
    details: str | None
    created_at: datetime


class StoreResponse(BaseModel):
    store_id: str
    store_code: str
    name: str
    store_type: StoreType
    status: StoreStatus

    organization_id: str
    manager_id: str | None

    city: str
    state: str
    country_code: str

    warehouse_count: int
    version: int

    created_at: datetime
    updated_at: datetime


class StoreDetailResponse(StoreResponse):
    address: StoreAddress
    contact: StoreContact
    timezone_name: str
    warehouse_ids: list[str]
    opening_hours: list[OpeningHours]
    events: list[StoreEventResponse]


class StoreAnalyticsResponse(BaseModel):
    total_stores: int
    draft: int
    active: int
    temporarily_closed: int
    inactive: int
    archived: int
    stores_with_manager: int
    stores_without_manager: int
    stores_with_warehouse: int
    stores_without_warehouse: int
    total_warehouse_associations: int


# ============================================================
# INTERNAL RECORD
# ============================================================

@dataclass
class StoreRecord:
    store_id: str
    tenant_id: str
    store_code: str
    name: str
    store_type: StoreType
    organization_id: str

    address: StoreAddress
    contact: StoreContact
    timezone_name: str

    warehouse_ids: set[str]
    opening_hours: list[OpeningHours]

    created_by: str
    manager_id: str | None = None

    status: StoreStatus = StoreStatus.DRAFT
    version: int = 1

    events: list[StoreEventResponse] = field(
        default_factory=list
    )

    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ============================================================
# AUTHORIZATION
# ============================================================

def require_store_access(
    principal: Principal,
    *,
    write: bool,
    warehouse_ids: set[str] | None = None,
) -> None:
    """
    Prototype permission mapping.

    Add STORE_READ, STORE_WRITE and STORE_MANAGE
    to backend/permissions.py for production.
    """

    permission = (
        Permission.SYSTEM_CONFIGURE
        if write
        else Permission.ANALYTICS_READ
    )

    # Store configuration is tenant-wide in this
    # prototype. Restrict warehouse-scoped principals.
    if principal.allowed_warehouse_ids is not None:
        raise HTTPException(
            status_code=403,
            detail="Tenant-wide store access required",
        )

    decision = permission_engine.evaluate(
        principal,
        permission,
        ResourceContext(
            tenant_id=principal.tenant_id,
            warehouse_id=None,
        ),
    )

    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail="Store access denied",
        )


# ============================================================
# SERIALIZATION
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_store_response(
    record: StoreRecord,
) -> StoreResponse:

    return StoreResponse(
        store_id=record.store_id,
        store_code=record.store_code,
        name=record.name,
        store_type=record.store_type,
        status=record.status,
        organization_id=record.organization_id,
        manager_id=record.manager_id,
        city=record.address.city,
        state=record.address.state,
        country_code=record.address.country_code,
        warehouse_count=len(record.warehouse_ids),
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def to_store_detail(
    record: StoreRecord,
) -> StoreDetailResponse:

    return StoreDetailResponse(
        **to_store_response(record).model_dump(),
        address=record.address,
        contact=record.contact,
        timezone_name=record.timezone_name,
        warehouse_ids=sorted(record.warehouse_ids),
        opening_hours=list(record.opening_hours),
        events=list(record.events),
    )


# ============================================================
# STORE REPOSITORY (IN MEMORY)
# ============================================================

class StoreStore:

    def __init__(self):

        self._stores: dict[str, StoreRecord] = {}

        self._code_index: dict[
            tuple[str, str],
            str,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    @staticmethod
    def _fingerprint(
        payload: StoreCreate,
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

    @staticmethod
    def _check_version(
        record: StoreRecord,
        expected_version: int,
    ) -> None:

        if record.version != expected_version:
            raise HTTPException(
                status_code=409,
                detail="Store version conflict",
            )

    @staticmethod
    def _event(
        record: StoreRecord,
        event_type: StoreEventType,
        actor_id: str,
        details: str | None = None,
    ) -> None:

        if len(record.events) >= MAX_EVENTS_PER_STORE:
            raise HTTPException(
                status_code=503,
                detail="Store event capacity reached",
            )

        record.events.append(
            StoreEventResponse(
                event_id=secrets.token_urlsafe(16),
                event_type=event_type,
                actor_id=actor_id,
                details=details,
                created_at=utc_now(),
            )
        )

    @staticmethod
    def _touch(record: StoreRecord) -> None:
        record.version += 1
        record.updated_at = utc_now()

    def _get(
        self,
        principal: Principal,
        store_id: str,
        *,
        write: bool,
    ) -> StoreRecord:

        record = self._stores.get(store_id)

        if (
            record is None
            or record.tenant_id != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Store not found",
            )

        require_store_access(
            principal,
            write=write,
        )

        return record

    async def create(
        self,
        principal: Principal,
        payload: StoreCreate,
    ) -> StoreResponse:

        require_store_access(
            principal,
            write=True,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        fingerprint = self._fingerprint(payload)
        code = payload.store_code.strip().upper()

        async with self._lock:

            previous = self._idempotency.get(key)

            if previous is not None:
                old_hash, store_id = previous

                if old_hash != fingerprint:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency key conflict",
                    )

                return to_store_response(
                    self._get(
                        principal,
                        store_id,
                        write=False,
                    )
                )

            code_key = (principal.tenant_id, code)

            if code_key in self._code_index:
                raise HTTPException(
                    status_code=409,
                    detail="Store code already exists",
                )

            count = sum(
                item.tenant_id == principal.tenant_id
                for item in self._stores.values()
            )

            if (
                count >= MAX_STORES_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Store capacity reached",
                )

            record = StoreRecord(
                store_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                store_code=code,
                name=payload.name,
                store_type=payload.store_type,
                organization_id=payload.organization_id,
                address=payload.address,
                contact=payload.contact,
                timezone_name=payload.timezone_name,
                warehouse_ids=set(payload.warehouse_ids),
                opening_hours=list(payload.opening_hours),
                created_by=principal.principal_id,
            )

            self._event(
                record,
                StoreEventType.CREATED,
                principal.principal_id,
            )

            self._stores[record.store_id] = record
            self._code_index[code_key] = record.store_id
            self._idempotency[key] = (
                fingerprint,
                record.store_id,
            )

            return to_store_response(record)

    async def get(
        self,
        principal: Principal,
        store_id: str,
    ) -> StoreDetailResponse:

        async with self._lock:
            return to_store_detail(
                self._get(
                    principal,
                    store_id,
                    write=False,
                )
            )

    async def list_stores(
        self,
        principal: Principal,
        *,
        organization_id: str | None,
        status: StoreStatus | None,
        search: str | None,
        limit: int,
    ) -> list[StoreResponse]:

        require_store_access(
            principal,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._stores.values()
                if (
                    record.tenant_id == principal.tenant_id
                    and (
                        organization_id is None
                        or record.organization_id
                        == organization_id
                    )
                    and (
                        status is None
                        or record.status == status
                    )
                )
            ]

            if search:
                needle = search.casefold()

                records = [
                    record
                    for record in records
                    if (
                        needle in record.name.casefold()
                        or needle in record.store_code.casefold()
                        or needle in record.address.city.casefold()
                    )
                ]

            records.sort(
                key=lambda record: record.created_at,
                reverse=True,
            )

            return [
                to_store_response(record)
                for record in records[:limit]
            ]

    async def update(
        self,
        principal: Principal,
        store_id: str,
        payload: StoreUpdate,
    ) -> StoreDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                store_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status == StoreStatus.ARCHIVED:
                raise HTTPException(
                    status_code=409,
                    detail="Archived stores are immutable",
                )

            updates = payload.model_dump(
                exclude_unset=True,
                exclude={"expected_version"},
            )

            for name, value in updates.items():
                if name in {
                    "name",
                    "address",
                    "contact",
                    "timezone_name",
                }:
                    setattr(record, name, value)

            self._event(
                record,
                StoreEventType.UPDATED,
                principal.principal_id,
            )

            self._touch(record)

            return to_store_detail(record)

    async def change_status(
        self,
        principal: Principal,
        store_id: str,
        expected_version: int,
        new_status: StoreStatus,
        reason: str,
    ) -> StoreResponse:

        transitions = {
            StoreStatus.DRAFT: {
                StoreStatus.ACTIVE,
                StoreStatus.INACTIVE,
                StoreStatus.ARCHIVED,
            },
            StoreStatus.ACTIVE: {
                StoreStatus.TEMPORARILY_CLOSED,
                StoreStatus.INACTIVE,
            },
            StoreStatus.TEMPORARILY_CLOSED: {
                StoreStatus.ACTIVE,
                StoreStatus.INACTIVE,
            },
            StoreStatus.INACTIVE: {
                StoreStatus.ACTIVE,
                StoreStatus.ARCHIVED,
            },
            StoreStatus.ARCHIVED: set(),
        }

        event_types = {
            StoreStatus.ACTIVE: StoreEventType.ACTIVATED,
            StoreStatus.TEMPORARILY_CLOSED:
                StoreEventType.CLOSED,
            StoreStatus.INACTIVE:
                StoreEventType.DEACTIVATED,
            StoreStatus.ARCHIVED:
                StoreEventType.ARCHIVED,
        }

        async with self._lock:

            record = self._get(
                principal,
                store_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            if new_status not in transitions[record.status]:
                raise HTTPException(
                    status_code=409,
                    detail="Invalid store status transition",
                )

            event_type = event_types[new_status]

            if (
                record.status
                == StoreStatus.TEMPORARILY_CLOSED
                and new_status == StoreStatus.ACTIVE
            ):
                event_type = StoreEventType.REOPENED

            self._event(
                record,
                event_type,
                principal.principal_id,
                reason,
            )

            record.status = new_status
            self._touch(record)

            return to_store_response(record)

    async def assign_manager(
        self,
        principal: Principal,
        store_id: str,
        payload: StoreManagerAssignment,
    ) -> StoreDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                store_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status == StoreStatus.ARCHIVED:
                raise HTTPException(
                    status_code=409,
                    detail="Archived store is immutable",
                )

            self._event(
                record,
                StoreEventType.MANAGER_ASSIGNED,
                principal.principal_id,
                payload.manager_id,
            )

            record.manager_id = payload.manager_id
            self._touch(record)

            return to_store_detail(record)

    async def link_warehouse(
        self,
        principal: Principal,
        store_id: str,
        payload: StoreWarehouseRequest,
        *,
        remove: bool = False,
    ) -> StoreDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                store_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status == StoreStatus.ARCHIVED:
                raise HTTPException(
                    status_code=409,
                    detail="Archived store is immutable",
                )

            if remove:

                if payload.warehouse_id not in record.warehouse_ids:
                    raise HTTPException(
                        status_code=404,
                        detail="Warehouse association not found",
                    )

            else:

                if payload.warehouse_id in record.warehouse_ids:
                    raise HTTPException(
                        status_code=409,
                        detail="Warehouse already linked",
                    )

                if (
                    len(record.warehouse_ids)
                    >= MAX_WAREHOUSES_PER_STORE
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Warehouse association limit reached",
                    )

            self._event(
                record,
                (
                    StoreEventType.WAREHOUSE_UNLINKED
                    if remove
                    else StoreEventType.WAREHOUSE_LINKED
                ),
                principal.principal_id,
                payload.warehouse_id,
            )

            if remove:
                record.warehouse_ids.remove(
                    payload.warehouse_id
                )
            else:
                record.warehouse_ids.add(
                    payload.warehouse_id
                )

            self._touch(record)

            return to_store_detail(record)

    async def update_hours(
        self,
        principal: Principal,
        store_id: str,
        payload: StoreHoursUpdate,
    ) -> StoreDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                store_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status == StoreStatus.ARCHIVED:
                raise HTTPException(
                    status_code=409,
                    detail="Archived store is immutable",
                )

            self._event(
                record,
                StoreEventType.HOURS_UPDATED,
                principal.principal_id,
            )

            record.opening_hours = list(
                payload.opening_hours
            )

            self._touch(record)

            return to_store_detail(record)

    async def analytics(
        self,
        principal: Principal,
    ) -> StoreAnalyticsResponse:

        require_store_access(
            principal,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._stores.values()
                if record.tenant_id == principal.tenant_id
            ]

            statuses = [
                record.status
                for record in records
            ]

            return StoreAnalyticsResponse(
                total_stores=len(records),
                draft=statuses.count(StoreStatus.DRAFT),
                active=statuses.count(StoreStatus.ACTIVE),
                temporarily_closed=statuses.count(
                    StoreStatus.TEMPORARILY_CLOSED
                ),
                inactive=statuses.count(
                    StoreStatus.INACTIVE
                ),
                archived=statuses.count(
                    StoreStatus.ARCHIVED
                ),
                stores_with_manager=sum(
                    record.manager_id is not None
                    for record in records
                ),
                stores_without_manager=sum(
                    record.manager_id is None
                    for record in records
                ),
                stores_with_warehouse=sum(
                    bool(record.warehouse_ids)
                    for record in records
                ),
                stores_without_warehouse=sum(
                    not record.warehouse_ids
                    for record in records
                ),
                total_warehouse_associations=sum(
                    len(record.warehouse_ids)
                    for record in records
                ),
            )


store_store = StoreStore()


# ============================================================
# SERVICE LAYER
# ============================================================

class StoreService:

    def __init__(self, store: StoreStore):
        self.store = store

    async def create(
        self,
        principal: Principal,
        payload: StoreCreate,
    ) -> StoreResponse:

        return await self.store.create(
            principal,
            payload,
        )


store_service = StoreService(store_store)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Retail Stores"],
)


@router.post(
    "",
    response_model=StoreResponse,
    status_code=201,
)
async def create_store(
    payload: StoreCreate,
    principal: CurrentPrincipal,
):
    return await store_service.create(
        principal,
        payload,
    )


@router.get(
    "",
    response_model=list[StoreResponse],
)
async def list_stores(
    principal: CurrentPrincipal,
    organization_id: str | None = None,
    status: StoreStatus | None = None,
    search: str | None = Query(
        default=None,
        max_length=200,
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await store_store.list_stores(
        principal,
        organization_id=organization_id,
        status=status,
        search=search,
        limit=limit,
    )


@router.get(
    "/analytics",
    response_model=StoreAnalyticsResponse,
)
async def store_analytics(
    principal: CurrentPrincipal,
):
    return await store_store.analytics(principal)


@router.get(
    "/{store_id}",
    response_model=StoreDetailResponse,
)
async def get_store(
    store_id: str,
    principal: CurrentPrincipal,
):
    return await store_store.get(
        principal,
        store_id,
    )


@router.patch(
    "/{store_id}",
    response_model=StoreDetailResponse,
)
async def update_store(
    store_id: str,
    payload: StoreUpdate,
    principal: CurrentPrincipal,
):
    return await store_store.update(
        principal,
        store_id,
        payload,
    )


@router.post(
    "/{store_id}/activate",
    response_model=StoreResponse,
)
async def activate_store(
    store_id: str,
    payload: StoreStatusRequest,
    principal: CurrentPrincipal,
):
    return await store_store.change_status(
        principal,
        store_id,
        payload.expected_version,
        StoreStatus.ACTIVE,
        payload.reason,
    )


@router.post(
    "/{store_id}/close",
    response_model=StoreResponse,
)
async def temporarily_close_store(
    store_id: str,
    payload: StoreStatusRequest,
    principal: CurrentPrincipal,
):
    return await store_store.change_status(
        principal,
        store_id,
        payload.expected_version,
        StoreStatus.TEMPORARILY_CLOSED,
        payload.reason,
    )


@router.post(
    "/{store_id}/deactivate",
    response_model=StoreResponse,
)
async def deactivate_store(
    store_id: str,
    payload: StoreStatusRequest,
    principal: CurrentPrincipal,
):
    return await store_store.change_status(
        principal,
        store_id,
        payload.expected_version,
        StoreStatus.INACTIVE,
        payload.reason,
    )


@router.post(
    "/{store_id}/archive",
    response_model=StoreResponse,
)
async def archive_store(
    store_id: str,
    payload: StoreStatusRequest,
    principal: CurrentPrincipal,
):
    return await store_store.change_status(
        principal,
        store_id,
        payload.expected_version,
        StoreStatus.ARCHIVED,
        payload.reason,
    )


@router.post(
    "/{store_id}/manager",
    response_model=StoreDetailResponse,
)
async def assign_store_manager(
    store_id: str,
    payload: StoreManagerAssignment,
    principal: CurrentPrincipal,
):
    return await store_store.assign_manager(
        principal,
        store_id,
        payload,
    )


@router.post(
    "/{store_id}/warehouses",
    response_model=StoreDetailResponse,
)
async def link_store_warehouse(
    store_id: str,
    payload: StoreWarehouseRequest,
    principal: CurrentPrincipal,
):
    return await store_store.link_warehouse(
        principal,
        store_id,
        payload,
    )


@router.delete(
    "/{store_id}/warehouses",
    response_model=StoreDetailResponse,
)
async def unlink_store_warehouse(
    store_id: str,
    payload: StoreWarehouseRequest,
    principal: CurrentPrincipal,
):
    return await store_store.link_warehouse(
        principal,
        store_id,
        payload,
        remove=True,
    )


@router.put(
    "/{store_id}/hours",
    response_model=StoreDetailResponse,
)
async def update_store_hours(
    store_id: str,
    payload: StoreHoursUpdate,
    principal: CurrentPrincipal,
):
    return await store_store.update_hours(
        principal,
        store_id,
        payload,
    )


__all__ = [
    "StoreType",
    "StoreStatus",
    "StoreEventType",
    "Weekday",
    "StoreAddress",
    "StoreContact",
    "OpeningHours",
    "StoreCreate",
    "StoreUpdate",
    "StoreVersionRequest",
    "StoreStatusRequest",
    "StoreManagerAssignment",
    "StoreWarehouseRequest",
    "StoreHoursUpdate",
    "StoreEventResponse",
    "StoreResponse",
    "StoreDetailResponse",
    "StoreAnalyticsResponse",
    "StoreStore",
    "StoreService",
    "store_store",
    "store_service",
    "router",
]
