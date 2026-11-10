from __future__ import annotations

"""Planned module: organizations. Implementation pending."""

"""
backend/organizations.py

Autonomous Retail Supply Chain AI 5.0
Organization & Multi-Tenant Management API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Organization creation
    - Tenant-isolated organization registry
    - Organization settings
    - Organization member management
    - Member role assignments
    - Warehouse-scoped memberships
    - Member suspension and reactivation
    - Organization lifecycle management
    - Idempotent creation
    - Optimistic concurrency
    - Organization analytics
    - Membership audit events

Security:
    - Tenant isolation
    - No cross-tenant membership writes
    - No self-promotion to owner
    - No removal of the final active owner
    - Warehouse authorization
    - Version checks
    - Role-based permissions

Prototype limitations:
    - In-memory storage
    - No invitation email delivery
    - No external identity verification
    - No durable database transactions
    - No organization billing
    - No real SSO provisioning
"""


import asyncio
import hashlib
import json
import secrets

from dataclasses import dataclass, field
from datetime import datetime, timezone
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


API_PREFIX = "/api/v1/organizations"

MAX_ORGANIZATIONS_PER_TENANT = 100
MAX_MEMBERS_PER_ORGANIZATION = 5000
MAX_WAREHOUSES_PER_ORGANIZATION = 500
MAX_EVENTS_PER_ORGANIZATION = 10000
MAX_IDEMPOTENCY_KEYS = 100000
MAX_LIST_LIMIT = 200


# ============================================================
# ENUMS
# ============================================================

class OrganizationType(str, Enum):
    RETAIL = "retail"
    WHOLESALE = "wholesale"
    DISTRIBUTION = "distribution"
    MANUFACTURING = "manufacturing"
    LOGISTICS = "logistics"
    ECOMMERCE = "ecommerce"
    SUPPLY_CHAIN = "supply_chain"
    OTHER = "other"


class OrganizationStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class OrganizationRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MANAGER = "manager"
    ANALYST = "analyst"
    EMPLOYEE = "employee"
    VIEWER = "viewer"


class MembershipStatus(str, Enum):
    INVITED = "invited"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REMOVED = "removed"


class OrganizationEventType(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    SUSPENDED = "suspended"
    REACTIVATED = "reactivated"
    ARCHIVED = "archived"
    MEMBER_INVITED = "member_invited"
    MEMBER_ACTIVATED = "member_activated"
    MEMBER_ROLE_UPDATED = "member_role_updated"
    MEMBER_SUSPENDED = "member_suspended"
    MEMBER_REMOVED = "member_removed"
    WAREHOUSE_ADDED = "warehouse_added"
    WAREHOUSE_REMOVED = "warehouse_removed"


# ============================================================
# REQUEST MODELS
# ============================================================

class OrganizationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=3,
        max_length=200,
    )

    organization_type: OrganizationType

    country_code: str = Field(
        default="IN",
        pattern=r"^[A-Z]{2}$",
    )

    currency: str = Field(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    )

    timezone_name: str = Field(
        default="Asia/Kolkata",
        min_length=3,
        max_length=100,
    )

    description: str = Field(
        default="",
        max_length=2000,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )


class OrganizationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    name: str | None = Field(
        default=None,
        min_length=3,
        max_length=200,
    )

    description: str | None = Field(
        default=None,
        max_length=2000,
    )

    currency: str | None = Field(
        default=None,
        pattern=r"^[A-Z]{3}$",
    )

    timezone_name: str | None = Field(
        default=None,
        min_length=3,
        max_length=100,
    )

    @model_validator(mode="after")
    def validate_update(self):

        if all(
            value is None
            for value in (
                self.name,
                self.description,
                self.currency,
                self.timezone_name,
            )
        ):
            raise ValueError(
                "At least one update field is required"
            )

        return self


class OrganizationVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class OrganizationMemberInvite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(
        min_length=1,
        max_length=128,
    )

    role: OrganizationRole = (
        OrganizationRole.EMPLOYEE
    )

    warehouse_ids: list[str] = Field(
        default_factory=list,
        max_length=100,
    )

    expected_organization_version: int = Field(
        ge=1
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_invitation(self):

        if self.role == OrganizationRole.OWNER:
            raise ValueError(
                "Owner role cannot be granted by invitation"
            )

        if len(set(self.warehouse_ids)) != len(
            self.warehouse_ids
        ):
            raise ValueError(
                "Duplicate warehouse IDs"
            )

        return self


class MemberRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_membership_version: int = Field(
        ge=1
    )

    role: OrganizationRole

    warehouse_ids: list[str] = Field(
        default_factory=list,
        max_length=100,
    )

    @model_validator(mode="after")
    def validate_role(self):

        if self.role == OrganizationRole.OWNER:
            raise ValueError(
                "Owner role changes require a separate transfer workflow"
            )

        if len(set(self.warehouse_ids)) != len(
            self.warehouse_ids
        ):
            raise ValueError(
                "Duplicate warehouse IDs"
            )

        return self


class MemberVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


class OrganizationWarehouseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    expected_version: int = Field(ge=1)


# ============================================================
# RESPONSE MODELS
# ============================================================

class OrganizationResponse(BaseModel):
    organization_id: str

    name: str
    organization_type: OrganizationType

    country_code: str
    currency: str
    timezone_name: str
    description: str

    status: OrganizationStatus

    warehouse_count: int
    member_count: int

    version: int

    created_by: str
    created_at: datetime
    updated_at: datetime


class OrganizationMemberResponse(BaseModel):
    membership_id: str
    organization_id: str

    user_id: str
    role: OrganizationRole

    status: MembershipStatus
    warehouse_ids: list[str]

    version: int

    invited_by: str
    invited_at: datetime
    activated_at: datetime | None


class OrganizationEventResponse(BaseModel):
    event_id: str
    organization_id: str

    event_type: OrganizationEventType

    actor_id: str
    target_reference: str | None

    created_at: datetime


class OrganizationDetailResponse(OrganizationResponse):
    warehouse_ids: list[str]
    members: list[OrganizationMemberResponse]
    recent_events: list[OrganizationEventResponse]


class OrganizationAnalyticsResponse(BaseModel):
    total_organizations: int
    active_organizations: int
    suspended_organizations: int
    archived_organizations: int

    total_memberships: int
    active_memberships: int
    invited_memberships: int
    suspended_memberships: int

    total_warehouse_assignments: int


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass
class MembershipRecord:
    membership_id: str
    organization_id: str
    tenant_id: str

    user_id: str
    role: OrganizationRole
    warehouse_ids: list[str]

    invited_by: str

    status: MembershipStatus = (
        MembershipStatus.INVITED
    )

    version: int = 1

    invited_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    activated_at: datetime | None = None


@dataclass
class OrganizationRecord:
    organization_id: str
    tenant_id: str

    name: str
    organization_type: OrganizationType

    country_code: str
    currency: str
    timezone_name: str
    description: str

    created_by: str

    status: OrganizationStatus = (
        OrganizationStatus.ACTIVE
    )

    warehouse_ids: set[str] = field(
        default_factory=set
    )

    membership_ids: list[str] = field(
        default_factory=list
    )

    event_ids: list[str] = field(
        default_factory=list
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


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint(
    operation: str,
    payload: BaseModel,
    resource_id: str | None = None,
) -> str:

    canonical = json.dumps(
        {
            "operation": operation,
            "resource_id": resource_id,
            "payload": payload.model_dump(
                mode="json",
                exclude={"source_request_id"},
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def require_organization_access(
    principal: Principal,
    *,
    write: bool,
) -> None:

    # Prototype mapping.
    # Production should introduce:
    # ORGANIZATION_READ
    # ORGANIZATION_WRITE
    # ORGANIZATION_MEMBERS_MANAGE
    # ORGANIZATION_OWNER_TRANSFER

    permission = (
        Permission.SYSTEM_CONFIGURE
        if write
        else Permission.ANALYTICS_READ
    )

    if principal.allowed_warehouse_ids is not None:
        raise HTTPException(
            status_code=403,
            detail="Tenant-wide organization access required",
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
            detail="Organization access denied",
        )


def to_member(
    record: MembershipRecord,
) -> OrganizationMemberResponse:

    return OrganizationMemberResponse(
        membership_id=record.membership_id,
        organization_id=record.organization_id,
        user_id=record.user_id,
        role=record.role,
        status=record.status,
        warehouse_ids=list(record.warehouse_ids),
        version=record.version,
        invited_by=record.invited_by,
        invited_at=record.invited_at,
        activated_at=record.activated_at,
    )


def to_organization(
    record: OrganizationRecord,
    members: dict[str, MembershipRecord],
) -> OrganizationResponse:

    return OrganizationResponse(
        organization_id=record.organization_id,
        name=record.name,
        organization_type=record.organization_type,
        country_code=record.country_code,
        currency=record.currency,
        timezone_name=record.timezone_name,
        description=record.description,
        status=record.status,
        warehouse_count=len(record.warehouse_ids),
        member_count=sum(
            members[mid].status
            != MembershipStatus.REMOVED
            for mid in record.membership_ids
        ),
        version=record.version,
        created_by=record.created_by,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


# ============================================================
# ORGANIZATION STORE
# ============================================================

class OrganizationStore:

    def __init__(self):

        self._organizations: dict[
            str, OrganizationRecord
        ] = {}

        self._memberships: dict[
            str, MembershipRecord
        ] = {}

        self._events: dict[
            str, OrganizationEventResponse
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    def _get_organization(
        self,
        principal: Principal,
        organization_id: str,
        *,
        write: bool,
    ) -> OrganizationRecord:

        record = self._organizations.get(
            organization_id
        )

        if (
            record is None
            or record.tenant_id
            != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Organization not found",
            )

        require_organization_access(
            principal,
            write=write,
        )

        return record

    def _get_membership(
        self,
        principal: Principal,
        organization_id: str,
        membership_id: str,
        *,
        write: bool,
    ) -> MembershipRecord:

        self._get_organization(
            principal,
            organization_id,
            write=write,
        )

        record = self._memberships.get(
            membership_id
        )

        if (
            record is None
            or record.tenant_id
            != principal.tenant_id
            or record.organization_id
            != organization_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Membership not found",
            )

        return record

    @staticmethod
    def _check_version(
        actual: int,
        expected: int,
    ) -> None:

        if actual != expected:
            raise HTTPException(
                status_code=409,
                detail="Version conflict",
            )

    def _add_event(
        self,
        record: OrganizationRecord,
        event_type: OrganizationEventType,
        actor_id: str,
        target_reference: str | None = None,
    ) -> None:

        if (
            len(record.event_ids)
            >= MAX_EVENTS_PER_ORGANIZATION
        ):
            # Production must use durable,
            # append-only audit storage.
            raise HTTPException(
                status_code=503,
                detail="Organization event capacity reached",
            )

        event = OrganizationEventResponse(
            event_id=secrets.token_urlsafe(20),
            organization_id=record.organization_id,
            event_type=event_type,
            actor_id=actor_id,
            target_reference=target_reference,
            created_at=utc_now(),
        )

        self._events[event.event_id] = event

        record.event_ids.append(
            event.event_id
        )

    def _check_idempotency(
        self,
        key: tuple[str, str, str],
        request_hash: str,
    ) -> str | None:

        previous = self._idempotency.get(
            key
        )

        if previous is None:
            return None

        old_hash, result_id = previous

        if old_hash != request_hash:
            raise HTTPException(
                status_code=409,
                detail="Idempotency conflict",
            )

        return result_id

    def _check_idempotency_capacity(self):

        if (
            len(self._idempotency)
            >= MAX_IDEMPOTENCY_KEYS
        ):
            raise HTTPException(
                status_code=503,
                detail="Idempotency capacity reached",
            )

    async def create(
        self,
        *,
        principal: Principal,
        payload: OrganizationCreate,
    ) -> OrganizationResponse:

        require_organization_access(
            principal,
            write=True,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = fingerprint(
            "create_organization",
            payload,
        )

        async with self._lock:

            previous = self._check_idempotency(
                key,
                request_hash,
            )

            if previous:
                return to_organization(
                    self._get_organization(
                        principal,
                        previous,
                        write=False,
                    ),
                    self._memberships,
                )

            tenant_count = sum(
                record.tenant_id
                == principal.tenant_id
                for record in self._organizations.values()
            )

            if (
                tenant_count
                >= MAX_ORGANIZATIONS_PER_TENANT
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Organization capacity reached",
                )

            self._check_idempotency_capacity()

            record = OrganizationRecord(
                organization_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                name=payload.name,
                organization_type=payload.organization_type,
                country_code=payload.country_code,
                currency=payload.currency,
                timezone_name=payload.timezone_name,
                description=payload.description,
                created_by=principal.principal_id,
            )

            owner = MembershipRecord(
                membership_id=secrets.token_urlsafe(20),
                organization_id=record.organization_id,
                tenant_id=principal.tenant_id,
                user_id=principal.principal_id,
                role=OrganizationRole.OWNER,
                warehouse_ids=[],
                invited_by=principal.principal_id,
                status=MembershipStatus.ACTIVE,
                activated_at=utc_now(),
            )

            record.membership_ids.append(
                owner.membership_id
            )

            self._organizations[
                record.organization_id
            ] = record

            self._memberships[
                owner.membership_id
            ] = owner

            self._add_event(
                record,
                OrganizationEventType.CREATED,
                principal.principal_id,
            )

            self._idempotency[key] = (
                request_hash,
                record.organization_id,
            )

            return to_organization(
                record,
                self._memberships,
            )

    async def get(
        self,
        *,
        principal: Principal,
        organization_id: str,
    ) -> OrganizationDetailResponse:

        async with self._lock:

            record = self._get_organization(
                principal,
                organization_id,
                write=False,
            )

            members = [
                to_member(
                    self._memberships[mid]
                )
                for mid in record.membership_ids
            ]

            events = [
                self._events[event_id]
                for event_id
                in record.event_ids[-50:]
            ]

            return OrganizationDetailResponse(
                **to_organization(
                    record,
                    self._memberships,
                ).model_dump(),
                warehouse_ids=sorted(
                    record.warehouse_ids
                ),
                members=members,
                recent_events=events,
            )

    async def list_organizations(
        self,
        *,
        principal: Principal,
        limit: int,
    ) -> list[OrganizationResponse]:

        require_organization_access(
            principal,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._organizations.values()
                if record.tenant_id
                == principal.tenant_id
            ]

            records.sort(
                key=lambda item: item.created_at,
                reverse=True,
            )

            return [
                to_organization(
                    record,
                    self._memberships,
                )
                for record in records[:limit]
            ]

    async def update(
        self,
        *,
        principal: Principal,
        organization_id: str,
        payload: OrganizationUpdate,
    ) -> OrganizationResponse:

        async with self._lock:

            record = self._get_organization(
                principal,
                organization_id,
                write=True,
            )

            self._check_version(
                record.version,
                payload.expected_version,
            )

            if record.status == OrganizationStatus.ARCHIVED:
                raise HTTPException(
                    status_code=409,
                    detail="Archived organization cannot be updated",
                )

            if payload.name is not None:
                record.name = payload.name

            if payload.description is not None:
                record.description = payload.description

            if payload.currency is not None:
                record.currency = payload.currency

            if payload.timezone_name is not None:
                record.timezone_name = (
                    payload.timezone_name
                )

            self._add_event(
                record,
                OrganizationEventType.UPDATED,
                principal.principal_id,
            )

            record.version += 1
            record.updated_at = utc_now()

            return to_organization(
                record,
                self._memberships,
            )

    async def change_status(
        self,
        *,
        principal: Principal,
        organization_id: str,
        expected_version: int,
        status: OrganizationStatus,
    ) -> OrganizationResponse:

        async with self._lock:

            record = self._get_organization(
                principal,
                organization_id,
                write=True,
            )

            self._check_version(
                record.version,
                expected_version,
            )

            if record.status == OrganizationStatus.ARCHIVED:
                raise HTTPException(
                    status_code=409,
                    detail="Archived organization is terminal",
                )

            if record.status == status:
                raise HTTPException(
                    status_code=409,
                    detail="Organization already has this status",
                )

            event_types = {
                OrganizationStatus.SUSPENDED:
                    OrganizationEventType.SUSPENDED,
                OrganizationStatus.ACTIVE:
                    OrganizationEventType.REACTIVATED,
                OrganizationStatus.ARCHIVED:
                    OrganizationEventType.ARCHIVED,
            }

            self._add_event(
                record,
                event_types[status],
                principal.principal_id,
            )

            record.status = status
            record.version += 1
            record.updated_at = utc_now()

            return to_organization(
                record,
                self._memberships,
            )

    async def invite_member(
        self,
        *,
        principal: Principal,
        organization_id: str,
        payload: OrganizationMemberInvite,
    ) -> OrganizationMemberResponse:

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = fingerprint(
            "invite_member",
            payload,
            organization_id,
        )

        async with self._lock:

            organization = self._get_organization(
                principal,
                organization_id,
                write=True,
            )

            previous = self._check_idempotency(
                key,
                request_hash,
            )

            if previous:
                return to_member(
                    self._memberships[previous]
                )

            self._check_version(
                organization.version,
                payload.expected_organization_version,
            )

            if (
                organization.status
                != OrganizationStatus.ACTIVE
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Organization is not active",
                )

            if (
                len(organization.membership_ids)
                >= MAX_MEMBERS_PER_ORGANIZATION
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Membership capacity reached",
                )

            if not set(payload.warehouse_ids).issubset(
                organization.warehouse_ids
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Warehouse not assigned to organization",
                )

            for membership_id in organization.membership_ids:

                existing = self._memberships[
                    membership_id
                ]

                if (
                    existing.user_id == payload.user_id
                    and existing.status
                    != MembershipStatus.REMOVED
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="User already has a membership",
                    )

            self._check_idempotency_capacity()

            # Production: verify the user exists and
            # belongs to the same identity tenant
            # before issuing an invitation.

            membership = MembershipRecord(
                membership_id=secrets.token_urlsafe(20),
                organization_id=organization_id,
                tenant_id=principal.tenant_id,
                user_id=payload.user_id,
                role=payload.role,
                warehouse_ids=list(
                    payload.warehouse_ids
                ),
                invited_by=principal.principal_id,
            )

            self._memberships[
                membership.membership_id
            ] = membership

            organization.membership_ids.append(
                membership.membership_id
            )

            self._add_event(
                organization,
                OrganizationEventType.MEMBER_INVITED,
                principal.principal_id,
                membership.membership_id,
            )

            organization.version += 1
            organization.updated_at = utc_now()

            self._idempotency[key] = (
                request_hash,
                membership.membership_id,
            )

            return to_member(membership)

    async def activate_membership(
        self,
        *,
        principal: Principal,
        organization_id: str,
        membership_id: str,
        expected_version: int,
    ) -> OrganizationMemberResponse:

        async with self._lock:

            membership = self._get_membership(
                principal,
                organization_id,
                membership_id,
                write=True,
            )

            organization = self._organizations[
                organization_id
            ]

            self._check_version(
                membership.version,
                expected_version,
            )

            if (
                organization.status
                != OrganizationStatus.ACTIVE
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Organization is not active",
                )

            if (
                membership.status
                != MembershipStatus.INVITED
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Membership is not invited",
                )

            # Production: require an authenticated
            # invitation acceptance by the invitee,
            # or verified identity-provider event.

            membership.status = MembershipStatus.ACTIVE
            membership.activated_at = utc_now()
            membership.version += 1

            self._add_event(
                organization,
                OrganizationEventType.MEMBER_ACTIVATED,
                principal.principal_id,
                membership_id,
            )

            organization.version += 1
            organization.updated_at = utc_now()

            return to_member(membership)

    async def update_member_role(
        self,
        *,
        principal: Principal,
        organization_id: str,
        membership_id: str,
        payload: MemberRoleUpdate,
    ) -> OrganizationMemberResponse:

        async with self._lock:

            membership = self._get_membership(
                principal,
                organization_id,
                membership_id,
                write=True,
            )

            organization = self._organizations[
                organization_id
            ]

            self._check_version(
                membership.version,
                payload.expected_membership_version,
            )

            if membership.role == OrganizationRole.OWNER:
                raise HTTPException(
                    status_code=403,
                    detail="Owner role cannot be changed here",
                )

            if (
                membership.status
                != MembershipStatus.ACTIVE
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Membership is not active",
                )

            if (
                not set(payload.warehouse_ids).issubset(
                    organization.warehouse_ids
                )
            ):
                raise HTTPException(
                    status_code=422,
                    detail="Unknown organization warehouse",
                )

            membership.role = payload.role
            membership.warehouse_ids = list(
                payload.warehouse_ids
            )
            membership.version += 1

            self._add_event(
                organization,
                OrganizationEventType.MEMBER_ROLE_UPDATED,
                principal.principal_id,
                membership_id,
            )

            organization.version += 1
            organization.updated_at = utc_now()

            return to_member(membership)

    async def suspend_member(
        self,
        *,
        principal: Principal,
        organization_id: str,
        membership_id: str,
        expected_version: int,
    ) -> OrganizationMemberResponse:

        async with self._lock:

            membership = self._get_membership(
                principal,
                organization_id,
                membership_id,
                write=True,
            )

            organization = self._organizations[
                organization_id
            ]

            self._check_version(
                membership.version,
                expected_version,
            )

            if membership.role == OrganizationRole.OWNER:
                raise HTTPException(
                    status_code=403,
                    detail="Owner cannot be suspended here",
                )

            if membership.status != MembershipStatus.ACTIVE:
                raise HTTPException(
                    status_code=409,
                    detail="Membership is not active",
                )

            membership.status = MembershipStatus.SUSPENDED
            membership.version += 1

            self._add_event(
                organization,
                OrganizationEventType.MEMBER_SUSPENDED,
                principal.principal_id,
                membership_id,
            )

            organization.version += 1
            organization.updated_at = utc_now()

            return to_member(membership)

    async def remove_member(
        self,
        *,
        principal: Principal,
        organization_id: str,
        membership_id: str,
        expected_version: int,
    ) -> OrganizationMemberResponse:

        async with self._lock:

            membership = self._get_membership(
                principal,
                organization_id,
                membership_id,
                write=True,
            )

            organization = self._organizations[
                organization_id
            ]

            self._check_version(
                membership.version,
                expected_version,
            )

            if membership.role == OrganizationRole.OWNER:
                raise HTTPException(
                    status_code=403,
                    detail="Owner removal requires ownership transfer",
                )

            if membership.status == MembershipStatus.REMOVED:
                raise HTTPException(
                    status_code=409,
                    detail="Membership already removed",
                )

            membership.status = MembershipStatus.REMOVED
            membership.version += 1

            self._add_event(
                organization,
                OrganizationEventType.MEMBER_REMOVED,
                principal.principal_id,
                membership_id,
            )

            organization.version += 1
            organization.updated_at = utc_now()

            return to_member(membership)

    async def add_warehouse(
        self,
        *,
        principal: Principal,
        organization_id: str,
        payload: OrganizationWarehouseRequest,
    ) -> OrganizationResponse:

        async with self._lock:

            organization = self._get_organization(
                principal,
                organization_id,
                write=True,
            )

            self._check_version(
                organization.version,
                payload.expected_version,
            )

            if (
                organization.status
                != OrganizationStatus.ACTIVE
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Organization is not active",
                )

            if (
                payload.warehouse_id
                in organization.warehouse_ids
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Warehouse already assigned",
                )

            if (
                len(organization.warehouse_ids)
                >= MAX_WAREHOUSES_PER_ORGANIZATION
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Warehouse assignment limit reached",
                )

            # Production: verify warehouse ownership
            # in the authoritative warehouse service.

            self._add_event(
                organization,
                OrganizationEventType.WAREHOUSE_ADDED,
                principal.principal_id,
                payload.warehouse_id,
            )

            organization.warehouse_ids.add(
                payload.warehouse_id
            )

            organization.version += 1
            organization.updated_at = utc_now()

            return to_organization(
                organization,
                self._memberships,
            )

    async def remove_warehouse(
        self,
        *,
        principal: Principal,
        organization_id: str,
        payload: OrganizationWarehouseRequest,
    ) -> OrganizationResponse:

        async with self._lock:

            organization = self._get_organization(
                principal,
                organization_id,
                write=True,
            )

            self._check_version(
                organization.version,
                payload.expected_version,
            )

            if (
                payload.warehouse_id
                not in organization.warehouse_ids
            ):
                raise HTTPException(
                    status_code=404,
                    detail="Warehouse not assigned",
                )

            self._add_event(
                organization,
                OrganizationEventType.WAREHOUSE_REMOVED,
                principal.principal_id,
                payload.warehouse_id,
            )

            organization.warehouse_ids.remove(
                payload.warehouse_id
            )

            for membership_id in organization.membership_ids:

                membership = self._memberships[
                    membership_id
                ]

                if (
                    payload.warehouse_id
                    in membership.warehouse_ids
                ):
                    membership.warehouse_ids.remove(
                        payload.warehouse_id
                    )
                    membership.version += 1

            organization.version += 1
            organization.updated_at = utc_now()

            return to_organization(
                organization,
                self._memberships,
            )

    async def analytics(
        self,
        *,
        principal: Principal,
    ) -> OrganizationAnalyticsResponse:

        require_organization_access(
            principal,
            write=False,
        )

        async with self._lock:

            organizations = [
                record
                for record in self._organizations.values()
                if record.tenant_id
                == principal.tenant_id
            ]

            memberships = [
                record
                for record in self._memberships.values()
                if record.tenant_id
                == principal.tenant_id
            ]

            return OrganizationAnalyticsResponse(
                total_organizations=len(organizations),
                active_organizations=sum(
                    record.status
                    == OrganizationStatus.ACTIVE
                    for record in organizations
                ),
                suspended_organizations=sum(
                    record.status
                    == OrganizationStatus.SUSPENDED
                    for record in organizations
                ),
                archived_organizations=sum(
                    record.status
                    == OrganizationStatus.ARCHIVED
                    for record in organizations
                ),
                total_memberships=len(memberships),
                active_memberships=sum(
                    record.status
                    == MembershipStatus.ACTIVE
                    for record in memberships
                ),
                invited_memberships=sum(
                    record.status
                    == MembershipStatus.INVITED
                    for record in memberships
                ),
                suspended_memberships=sum(
                    record.status
                    == MembershipStatus.SUSPENDED
                    for record in memberships
                ),
                total_warehouse_assignments=sum(
                    len(record.warehouse_ids)
                    for record in organizations
                ),
            )


organization_store = OrganizationStore()


# ============================================================
# SERVICE
# ============================================================

class OrganizationService:

    def __init__(
        self,
        store: OrganizationStore,
    ):
        self.store = store

    async def create(
        self,
        principal: Principal,
        payload: OrganizationCreate,
    ) -> OrganizationResponse:

        return await self.store.create(
            principal=principal,
            payload=payload,
        )


organization_service = OrganizationService(
    organization_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Organization Management"],
)


@router.post(
    "",
    response_model=OrganizationResponse,
    status_code=201,
)
async def create_organization(
    payload: OrganizationCreate,
    principal: CurrentPrincipal,
):
    return await organization_service.create(
        principal,
        payload,
    )


@router.get(
    "",
    response_model=list[OrganizationResponse],
)
async def list_organizations(
    principal: CurrentPrincipal,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await organization_store.list_organizations(
        principal=principal,
        limit=limit,
    )


@router.get(
    "/analytics",
    response_model=OrganizationAnalyticsResponse,
)
async def organization_analytics(
    principal: CurrentPrincipal,
):
    return await organization_store.analytics(
        principal=principal,
    )


@router.get(
    "/{organization_id}",
    response_model=OrganizationDetailResponse,
)
async def get_organization(
    organization_id: str,
    principal: CurrentPrincipal,
):
    return await organization_store.get(
        principal=principal,
        organization_id=organization_id,
    )


@router.patch(
    "/{organization_id}",
    response_model=OrganizationResponse,
)
async def update_organization(
    organization_id: str,
    payload: OrganizationUpdate,
    principal: CurrentPrincipal,
):
    return await organization_store.update(
        principal=principal,
        organization_id=organization_id,
        payload=payload,
    )


@router.post(
    "/{organization_id}/suspend",
    response_model=OrganizationResponse,
)
async def suspend_organization(
    organization_id: str,
    payload: OrganizationVersionRequest,
    principal: CurrentPrincipal,
):
    return await organization_store.change_status(
        principal=principal,
        organization_id=organization_id,
        expected_version=payload.expected_version,
        status=OrganizationStatus.SUSPENDED,
    )


@router.post(
    "/{organization_id}/reactivate",
    response_model=OrganizationResponse,
)
async def reactivate_organization(
    organization_id: str,
    payload: OrganizationVersionRequest,
    principal: CurrentPrincipal,
):
    return await organization_store.change_status(
        principal=principal,
        organization_id=organization_id,
        expected_version=payload.expected_version,
        status=OrganizationStatus.ACTIVE,
    )


@router.post(
    "/{organization_id}/archive",
    response_model=OrganizationResponse,
)
async def archive_organization(
    organization_id: str,
    payload: OrganizationVersionRequest,
    principal: CurrentPrincipal,
):
    return await organization_store.change_status(
        principal=principal,
        organization_id=organization_id,
        expected_version=payload.expected_version,
        status=OrganizationStatus.ARCHIVED,
    )


@router.post(
    "/{organization_id}/members",
    response_model=OrganizationMemberResponse,
    status_code=201,
)
async def invite_organization_member(
    organization_id: str,
    payload: OrganizationMemberInvite,
    principal: CurrentPrincipal,
):
    return await organization_store.invite_member(
        principal=principal,
        organization_id=organization_id,
        payload=payload,
    )


@router.post(
    "/{organization_id}/members/{membership_id}/activate",
    response_model=OrganizationMemberResponse,
)
async def activate_organization_member(
    organization_id: str,
    membership_id: str,
    payload: MemberVersionRequest,
    principal: CurrentPrincipal,
):
    return await organization_store.activate_membership(
        principal=principal,
        organization_id=organization_id,
        membership_id=membership_id,
        expected_version=payload.expected_version,
    )


@router.patch(
    "/{organization_id}/members/{membership_id}/role",
    response_model=OrganizationMemberResponse,
)
async def update_organization_member_role(
    organization_id: str,
    membership_id: str,
    payload: MemberRoleUpdate,
    principal: CurrentPrincipal,
):
    return await organization_store.update_member_role(
        principal=principal,
        organization_id=organization_id,
        membership_id=membership_id,
        payload=payload,
    )


@router.post(
    "/{organization_id}/members/{membership_id}/suspend",
    response_model=OrganizationMemberResponse,
)
async def suspend_organization_member(
    organization_id: str,
    membership_id: str,
    payload: MemberVersionRequest,
    principal: CurrentPrincipal,
):
    return await organization_store.suspend_member(
        principal=principal,
        organization_id=organization_id,
        membership_id=membership_id,
        expected_version=payload.expected_version,
    )


@router.post(
    "/{organization_id}/members/{membership_id}/remove",
    response_model=OrganizationMemberResponse,
)
async def remove_organization_member(
    organization_id: str,
    membership_id: str,
    payload: MemberVersionRequest,
    principal: CurrentPrincipal,
):
    return await organization_store.remove_member(
        principal=principal,
        organization_id=organization_id,
        membership_id=membership_id,
        expected_version=payload.expected_version,
    )


@router.post(
    "/{organization_id}/warehouses",
    response_model=OrganizationResponse,
)
async def assign_organization_warehouse(
    organization_id: str,
    payload: OrganizationWarehouseRequest,
    principal: CurrentPrincipal,
):
    return await organization_store.add_warehouse(
        principal=principal,
        organization_id=organization_id,
        payload=payload,
    )


@router.delete(
    "/{organization_id}/warehouses",
    response_model=OrganizationResponse,
)
async def remove_organization_warehouse(
    organization_id: str,
    payload: OrganizationWarehouseRequest,
    principal: CurrentPrincipal,
):
    return await organization_store.remove_warehouse(
        principal=principal,
        organization_id=organization_id,
        payload=payload,
    )


__all__ = [
    "OrganizationType",
    "OrganizationStatus",
    "OrganizationRole",
    "MembershipStatus",
    "OrganizationEventType",
    "OrganizationCreate",
    "OrganizationUpdate",
    "OrganizationVersionRequest",
    "OrganizationMemberInvite",
    "MemberRoleUpdate",
    "MemberVersionRequest",
    "OrganizationWarehouseRequest",
    "OrganizationResponse",
    "OrganizationMemberResponse",
    "OrganizationEventResponse",
    "OrganizationDetailResponse",
    "OrganizationAnalyticsResponse",
    "OrganizationStore",
    "OrganizationService",
    "organization_store",
    "organization_service",
    "router",
]
