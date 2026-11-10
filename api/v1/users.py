from __future__ import annotations

"""Planned module: users. Implementation pending."""

"""
backend/users.py

Autonomous Retail Supply Chain AI 5.0
Enterprise User Management API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Tenant-isolated user directory
    - Unique email per tenant
    - User invitation records
    - Employee profiles
    - Role assignments
    - Warehouse access assignments
    - Account activation and suspension
    - User profile updates
    - Optimistic concurrency
    - Idempotent user creation
    - User statistics
    - Administrative access control

IMPORTANT:
    This is a prototype user-directory module.
    It does not authenticate users, send invitations,
    create passwords, or provision login credentials.

    Production identity lifecycle operations must be
    coordinated with the authentication provider.
"""


import asyncio
import hashlib
import json
import secrets

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from fastapi import APIRouter, HTTPException, Query
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
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


API_PREFIX = "/api/v1/users"

MAX_USERS_PER_TENANT = 50000
MAX_WAREHOUSES_PER_USER = 200
MAX_ROLES_PER_USER = 10
MAX_EVENTS_PER_USER = 500
MAX_IDEMPOTENCY_KEYS = 100000
MAX_LIST_LIMIT = 200


# ============================================================
# ENUMS
# ============================================================

class UserStatus(str, Enum):
    INVITED = "invited"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"


class UserRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    WAREHOUSE_MANAGER = "warehouse_manager"
    INVENTORY_MANAGER = "inventory_manager"
    PROCUREMENT_MANAGER = "procurement_manager"
    LOGISTICS_MANAGER = "logistics_manager"
    ANALYST = "analyst"
    EMPLOYEE = "employee"
    VIEWER = "viewer"


class UserDepartment(str, Enum):
    ADMINISTRATION = "administration"
    PROCUREMENT = "procurement"
    INVENTORY = "inventory"
    WAREHOUSE = "warehouse"
    LOGISTICS = "logistics"
    FINANCE = "finance"
    ANALYTICS = "analytics"
    OPERATIONS = "operations"
    IT = "it"
    OTHER = "other"


class UserEventType(str, Enum):
    CREATED = "created"
    PROFILE_UPDATED = "profile_updated"
    ROLES_UPDATED = "roles_updated"
    WAREHOUSES_UPDATED = "warehouses_updated"
    ACTIVATED = "activated"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"


# ============================================================
# REQUEST MODELS
# ============================================================

class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr

    full_name: str = Field(
        min_length=2,
        max_length=150,
    )

    employee_code: str | None = Field(
        default=None,
        min_length=2,
        max_length=50,
        pattern=r"^[A-Za-z0-9._-]+$",
    )

    department: UserDepartment = (
        UserDepartment.OPERATIONS
    )

    job_title: str | None = Field(
        default=None,
        max_length=150,
    )

    phone: str | None = Field(
        default=None,
        pattern=r"^\+?[0-9]{7,15}$",
    )

    roles: list[UserRole] = Field(
        default_factory=lambda: [UserRole.EMPLOYEE],
        min_length=1,
        max_length=MAX_ROLES_PER_USER,
    )

    warehouse_ids: list[str] | None = Field(
        default_factory=list,
        max_length=MAX_WAREHOUSES_PER_USER,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_assignments(self):

        if len(set(self.roles)) != len(self.roles):
            raise ValueError("Duplicate roles")

        if (
            self.warehouse_ids is not None
            and len(set(self.warehouse_ids))
            != len(self.warehouse_ids)
        ):
            raise ValueError("Duplicate warehouse IDs")

        if (
            UserRole.OWNER in self.roles
            and self.warehouse_ids is not None
        ):
            raise ValueError(
                "Owner must have tenant-wide scope"
            )

        return self


class UserProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    full_name: str | None = Field(
        default=None,
        min_length=2,
        max_length=150,
    )

    department: UserDepartment | None = None

    job_title: str | None = Field(
        default=None,
        max_length=150,
    )

    phone: str | None = Field(
        default=None,
        pattern=r"^\+?[0-9]{7,15}$",
    )


class UserRolesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    roles: list[UserRole] = Field(
        min_length=1,
        max_length=MAX_ROLES_PER_USER,
    )

    @model_validator(mode="after")
    def validate_roles(self):

        if len(set(self.roles)) != len(self.roles):
            raise ValueError("Duplicate roles")

        return self


class UserWarehousesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    # None means tenant-wide access.
    # [] means no assigned warehouses.
    warehouse_ids: list[str] | None = Field(
        max_length=MAX_WAREHOUSES_PER_USER,
    )

    @model_validator(mode="after")
    def validate_warehouses(self):

        if (
            self.warehouse_ids is not None
            and len(set(self.warehouse_ids))
            != len(self.warehouse_ids)
        ):
            raise ValueError("Duplicate warehouse IDs")

        return self


class UserStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    reason: str = Field(
        min_length=3,
        max_length=500,
    )


# ============================================================
# RESPONSE MODELS
# ============================================================

class UserEventResponse(BaseModel):
    event_id: str
    event_type: UserEventType
    actor_id: str
    details: str | None
    created_at: datetime


class UserResponse(BaseModel):
    user_id: str
    email: EmailStr
    full_name: str
    employee_code: str | None
    department: UserDepartment
    job_title: str | None
    phone: str | None
    roles: list[UserRole]
    warehouse_ids: list[str] | None
    status: UserStatus
    version: int
    created_at: datetime
    updated_at: datetime


class UserDetailResponse(UserResponse):
    created_by: str
    events: list[UserEventResponse]


class UserStatisticsResponse(BaseModel):
    total_users: int
    invited: int
    active: int
    suspended: int
    deactivated: int
    administrators: int
    warehouse_managers: int
    tenant_wide_users: int


# ============================================================
# INTERNAL RECORD
# ============================================================

@dataclass
class UserRecord:
    user_id: str
    tenant_id: str
    email: str
    full_name: str
    employee_code: str | None
    department: UserDepartment
    job_title: str | None
    phone: str | None
    roles: list[UserRole]
    warehouse_ids: list[str] | None
    created_by: str

    status: UserStatus = UserStatus.INVITED
    version: int = 1

    events: list[UserEventResponse] = field(
        default_factory=list
    )

    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def fingerprint(payload: UserCreate) -> str:

    data = payload.model_dump(
        mode="json",
        exclude={"source_request_id"},
    )

    canonical = json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def require_user_admin(principal: Principal) -> None:

    # Only tenant-wide administrators may manage users.
    if principal.allowed_warehouse_ids is not None:
        raise HTTPException(
            status_code=403,
            detail="Tenant-wide access required",
        )

    decision = permission_engine.evaluate(
        principal,
        Permission.SYSTEM_CONFIGURE,
        ResourceContext(
            tenant_id=principal.tenant_id,
            warehouse_id=None,
        ),
    )

    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail="User administration denied",
        )


def to_response(record: UserRecord) -> UserResponse:

    return UserResponse(
        user_id=record.user_id,
        email=record.email,
        full_name=record.full_name,
        employee_code=record.employee_code,
        department=record.department,
        job_title=record.job_title,
        phone=record.phone,
        roles=list(record.roles),
        warehouse_ids=(
            list(record.warehouse_ids)
            if record.warehouse_ids is not None
            else None
        ),
        status=record.status,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def to_detail(record: UserRecord) -> UserDetailResponse:

    return UserDetailResponse(
        **to_response(record).model_dump(),
        created_by=record.created_by,
        events=list(record.events),
    )


# ============================================================
# USER STORE
# ============================================================

class UserStore:

    def __init__(self):

        self._users: dict[str, UserRecord] = {}

        self._email_index: dict[
            tuple[str, str],
            str,
        ] = {}

        self._employee_index: dict[
            tuple[str, str],
            str,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    def _get(
        self,
        principal: Principal,
        user_id: str,
    ) -> UserRecord:

        record = self._users.get(user_id)

        if (
            record is None
            or record.tenant_id != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="User not found",
            )

        return record

    @staticmethod
    def _check_version(
        record: UserRecord,
        expected_version: int,
    ) -> None:

        if record.version != expected_version:
            raise HTTPException(
                status_code=409,
                detail="User version conflict",
            )

    @staticmethod
    def _add_event(
        record: UserRecord,
        event_type: UserEventType,
        actor_id: str,
        details: str | None = None,
    ) -> None:

        if len(record.events) >= MAX_EVENTS_PER_USER:
            raise HTTPException(
                status_code=503,
                detail="User event capacity reached",
            )

        record.events.append(
            UserEventResponse(
                event_id=secrets.token_urlsafe(16),
                event_type=event_type,
                actor_id=actor_id,
                details=details,
                created_at=utc_now(),
            )
        )

    @staticmethod
    def _touch(record: UserRecord) -> None:
        record.version += 1
        record.updated_at = utc_now()

    @staticmethod
    def _is_owner(record: UserRecord) -> bool:
        return UserRole.OWNER in record.roles

    def _ensure_owner_retained(
        self,
        record: UserRecord,
    ) -> None:

        if not self._is_owner(record):
            return

        remaining = [
            user
            for user in self._users.values()
            if (
                user.tenant_id == record.tenant_id
                and user.user_id != record.user_id
                and UserRole.OWNER in user.roles
                and user.status == UserStatus.ACTIVE
            )
        ]

        if not remaining:
            raise HTTPException(
                status_code=409,
                detail="Cannot remove the last active owner",
            )

    async def create(
        self,
        principal: Principal,
        payload: UserCreate,
    ) -> UserResponse:

        require_user_admin(principal)

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = fingerprint(payload)
        email = normalize_email(str(payload.email))

        async with self._lock:

            previous = self._idempotency.get(key)

            if previous:

                previous_hash, user_id = previous

                if previous_hash != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return to_response(
                    self._get(principal, user_id)
                )

            if (
                principal.tenant_id,
                email,
            ) in self._email_index:
                raise HTTPException(
                    status_code=409,
                    detail="Email already registered",
                )

            if payload.employee_code:

                employee_key = (
                    principal.tenant_id,
                    payload.employee_code.casefold(),
                )

                if employee_key in self._employee_index:
                    raise HTTPException(
                        status_code=409,
                        detail="Employee code already exists",
                    )

            tenant_count = sum(
                record.tenant_id == principal.tenant_id
                for record in self._users.values()
            )

            if (
                tenant_count >= MAX_USERS_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="User directory capacity reached",
                )

            # A new user is only invited in this store.
            # The auth provider must verify the invitation
            # and establish a real identity before activation.

            record = UserRecord(
                user_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                email=email,
                full_name=payload.full_name,
                employee_code=payload.employee_code,
                department=payload.department,
                job_title=payload.job_title,
                phone=payload.phone,
                roles=list(payload.roles),
                warehouse_ids=(
                    list(payload.warehouse_ids)
                    if payload.warehouse_ids is not None
                    else None
                ),
                created_by=principal.principal_id,
            )

            self._add_event(
                record,
                UserEventType.CREATED,
                principal.principal_id,
            )

            self._users[record.user_id] = record

            self._email_index[
                (principal.tenant_id, email)
            ] = record.user_id

            if payload.employee_code:

                self._employee_index[
                    (
                        principal.tenant_id,
                        payload.employee_code.casefold(),
                    )
                ] = record.user_id

            self._idempotency[key] = (
                request_hash,
                record.user_id,
            )

            return to_response(record)

    async def get(
        self,
        principal: Principal,
        user_id: str,
    ) -> UserDetailResponse:

        require_user_admin(principal)

        async with self._lock:
            return to_detail(
                self._get(principal, user_id)
            )

    async def list_users(
        self,
        principal: Principal,
        *,
        search: str | None,
        status: UserStatus | None,
        role: UserRole | None,
        limit: int,
    ) -> list[UserResponse]:

        require_user_admin(principal)

        async with self._lock:

            records = [
                record
                for record in self._users.values()
                if (
                    record.tenant_id == principal.tenant_id
                    and (
                        status is None
                        or record.status == status
                    )
                    and (
                        role is None
                        or role in record.roles
                    )
                )
            ]

            if search:

                query = search.casefold()

                records = [
                    record
                    for record in records
                    if (
                        query in record.full_name.casefold()
                        or query in record.email
                        or (
                            record.employee_code
                            and query
                            in record.employee_code.casefold()
                        )
                    )
                ]

            records.sort(
                key=lambda record: record.created_at,
                reverse=True,
            )

            return [
                to_response(record)
                for record in records[:limit]
            ]

    async def update_profile(
        self,
        principal: Principal,
        user_id: str,
        payload: UserProfileUpdate,
    ) -> UserDetailResponse:

        require_user_admin(principal)

        async with self._lock:

            record = self._get(principal, user_id)

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status == UserStatus.DEACTIVATED:
                raise HTTPException(
                    status_code=409,
                    detail="Deactivated user cannot be edited",
                )

            updates = payload.model_dump(
                exclude_unset=True,
                exclude={"expected_version"},
            )

            for name, value in updates.items():
                setattr(record, name, value)

            self._add_event(
                record,
                UserEventType.PROFILE_UPDATED,
                principal.principal_id,
            )

            self._touch(record)

            return to_detail(record)

    async def update_roles(
        self,
        principal: Principal,
        user_id: str,
        payload: UserRolesUpdate,
    ) -> UserDetailResponse:

        require_user_admin(principal)

        async with self._lock:

            record = self._get(principal, user_id)

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status == UserStatus.DEACTIVATED:
                raise HTTPException(
                    status_code=409,
                    detail="Deactivated user cannot be edited",
                )

            if (
                self._is_owner(record)
                and UserRole.OWNER not in payload.roles
            ):
                self._ensure_owner_retained(record)

            if (
                UserRole.OWNER in payload.roles
                and record.warehouse_ids is not None
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Owner requires tenant-wide access",
                )

            record.roles = list(payload.roles)

            self._add_event(
                record,
                UserEventType.ROLES_UPDATED,
                principal.principal_id,
            )

            self._touch(record)

            return to_detail(record)

    async def update_warehouses(
        self,
        principal: Principal,
        user_id: str,
        payload: UserWarehousesUpdate,
    ) -> UserDetailResponse:

        require_user_admin(principal)

        async with self._lock:

            record = self._get(principal, user_id)

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status == UserStatus.DEACTIVATED:
                raise HTTPException(
                    status_code=409,
                    detail="Deactivated user cannot be edited",
                )

            if (
                self._is_owner(record)
                and payload.warehouse_ids is not None
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Owner must retain tenant-wide scope",
                )

            record.warehouse_ids = (
                list(payload.warehouse_ids)
                if payload.warehouse_ids is not None
                else None
            )

            self._add_event(
                record,
                UserEventType.WAREHOUSES_UPDATED,
                principal.principal_id,
            )

            self._touch(record)

            return to_detail(record)

    async def change_status(
        self,
        principal: Principal,
        user_id: str,
        payload: UserStatusUpdate,
        new_status: UserStatus,
    ) -> UserResponse:

        require_user_admin(principal)

        async with self._lock:

            record = self._get(principal, user_id)

            self._check_version(
                record,
                payload.expected_version,
            )

            allowed = {
                UserStatus.INVITED: {
                    UserStatus.ACTIVE,
                    UserStatus.DEACTIVATED,
                },
                UserStatus.ACTIVE: {
                    UserStatus.SUSPENDED,
                    UserStatus.DEACTIVATED,
                },
                UserStatus.SUSPENDED: {
                    UserStatus.ACTIVE,
                    UserStatus.DEACTIVATED,
                },
                UserStatus.DEACTIVATED: set(),
            }

            if new_status not in allowed[record.status]:
                raise HTTPException(
                    status_code=409,
                    detail="Invalid user status transition",
                )

            if (
                record.user_id == principal.principal_id
                and new_status in {
                    UserStatus.SUSPENDED,
                    UserStatus.DEACTIVATED,
                }
            ):
                raise HTTPException(
                    status_code=403,
                    detail="Cannot suspend or deactivate yourself",
                )

            if (
                self._is_owner(record)
                and new_status in {
                    UserStatus.SUSPENDED,
                    UserStatus.DEACTIVATED,
                }
            ):
                self._ensure_owner_retained(record)

            # Important:
            # This updates only the directory record.
            # Production must atomically coordinate with
            # identity provisioning/token revocation.

            event_type = {
                UserStatus.ACTIVE: UserEventType.ACTIVATED,
                UserStatus.SUSPENDED: UserEventType.SUSPENDED,
                UserStatus.DEACTIVATED: UserEventType.DEACTIVATED,
            }[new_status]

            self._add_event(
                record,
                event_type,
                principal.principal_id,
                payload.reason,
            )

            record.status = new_status

            self._touch(record)

            return to_response(record)

    async def statistics(
        self,
        principal: Principal,
    ) -> UserStatisticsResponse:

        require_user_admin(principal)

        async with self._lock:

            records = [
                record
                for record in self._users.values()
                if record.tenant_id == principal.tenant_id
            ]

            statuses = [
                record.status
                for record in records
            ]

            return UserStatisticsResponse(
                total_users=len(records),
                invited=statuses.count(
                    UserStatus.INVITED
                ),
                active=statuses.count(
                    UserStatus.ACTIVE
                ),
                suspended=statuses.count(
                    UserStatus.SUSPENDED
                ),
                deactivated=statuses.count(
                    UserStatus.DEACTIVATED
                ),
                administrators=sum(
                    UserRole.ADMIN in record.roles
                    for record in records
                ),
                warehouse_managers=sum(
                    UserRole.WAREHOUSE_MANAGER
                    in record.roles
                    for record in records
                ),
                tenant_wide_users=sum(
                    record.warehouse_ids is None
                    for record in records
                ),
            )


user_store = UserStore()


# ============================================================
# USER SERVICE
# ============================================================

class UserService:

    def __init__(self, store: UserStore):
        self.store = store

    async def invite(
        self,
        principal: Principal,
        payload: UserCreate,
    ) -> UserResponse:

        return await self.store.create(
            principal,
            payload,
        )


user_service = UserService(user_store)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["User Management"],
)


@router.post(
    "",
    response_model=UserResponse,
    status_code=201,
)
async def create_user(
    payload: UserCreate,
    principal: CurrentPrincipal,
):
    return await user_service.invite(
        principal,
        payload,
    )


@router.get(
    "",
    response_model=list[UserResponse],
)
async def list_users(
    principal: CurrentPrincipal,
    search: str | None = Query(
        default=None,
        max_length=200,
    ),
    status: UserStatus | None = None,
    role: UserRole | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await user_store.list_users(
        principal,
        search=search,
        status=status,
        role=role,
        limit=limit,
    )


@router.get(
    "/statistics",
    response_model=UserStatisticsResponse,
)
async def user_statistics(
    principal: CurrentPrincipal,
):
    return await user_store.statistics(
        principal
    )


@router.get(
    "/{user_id}",
    response_model=UserDetailResponse,
)
async def get_user(
    user_id: str,
    principal: CurrentPrincipal,
):
    return await user_store.get(
        principal,
        user_id,
    )


@router.patch(
    "/{user_id}",
    response_model=UserDetailResponse,
)
async def update_user_profile(
    user_id: str,
    payload: UserProfileUpdate,
    principal: CurrentPrincipal,
):
    return await user_store.update_profile(
        principal,
        user_id,
        payload,
    )


@router.patch(
    "/{user_id}/roles",
    response_model=UserDetailResponse,
)
async def update_user_roles(
    user_id: str,
    payload: UserRolesUpdate,
    principal: CurrentPrincipal,
):
    return await user_store.update_roles(
        principal,
        user_id,
        payload,
    )


@router.patch(
    "/{user_id}/warehouses",
    response_model=UserDetailResponse,
)
async def update_user_warehouses(
    user_id: str,
    payload: UserWarehousesUpdate,
    principal: CurrentPrincipal,
):
    return await user_store.update_warehouses(
        principal,
        user_id,
        payload,
    )


@router.post(
    "/{user_id}/activate",
    response_model=UserResponse,
)
async def activate_user(
    user_id: str,
    payload: UserStatusUpdate,
    principal: CurrentPrincipal,
):
    return await user_store.change_status(
        principal,
        user_id,
        payload,
        UserStatus.ACTIVE,
    )


@router.post(
    "/{user_id}/suspend",
    response_model=UserResponse,
)
async def suspend_user(
    user_id: str,
    payload: UserStatusUpdate,
    principal: CurrentPrincipal,
):
    return await user_store.change_status(
        principal,
        user_id,
        payload,
        UserStatus.SUSPENDED,
    )


@router.post(
    "/{user_id}/deactivate",
    response_model=UserResponse,
)
async def deactivate_user(
    user_id: str,
    payload: UserStatusUpdate,
    principal: CurrentPrincipal,
):
    return await user_store.change_status(
        principal,
        user_id,
        payload,
        UserStatus.DEACTIVATED,
    )


__all__ = [
    "UserStatus",
    "UserRole",
    "UserDepartment",
    "UserEventType",
    "UserCreate",
    "UserProfileUpdate",
    "UserRolesUpdate",
    "UserWarehousesUpdate",
    "UserStatusUpdate",
    "UserEventResponse",
    "UserResponse",
    "UserDetailResponse",
    "UserStatisticsResponse",
    "UserStore",
    "UserService",
    "user_store",
    "user_service",
    "router",
]
