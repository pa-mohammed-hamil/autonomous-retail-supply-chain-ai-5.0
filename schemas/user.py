from __future__ import annotations

"""Planned module: user. Implementation pending."""

"""
backend/services/user_service.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+ | Standard library only

Features:
- Tenant-isolated user profiles
- Role-based access control
- Warehouse assignments
- User activation and suspension
- Profile updates
- Role and warehouse management
- Optimistic concurrency
- Audit history
- In-memory notification outbox

Authentication remains the responsibility
of auth_service.py.

Reference implementation, not production-ready.
"""


import copy
import re
import threading
import uuid

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def required(value: str, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 255
    ):
        raise ValueError(f"Invalid {field}")
    return value.strip()


def normalize_email(value: str) -> str:
    email = required(value, "email").lower()

    if not re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+", email
    ):
        raise ValueError("Invalid email")

    return email


class UserStatus(str, Enum):
    INVITED = "invited"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DISABLED = "disabled"


class UserRole(str, Enum):
    CORPORATE_ADMIN = "corporate_admin"
    OPERATIONS_MANAGER = "operations_manager"
    WAREHOUSE_MANAGER = "warehouse_manager"
    WAREHOUSE_OPERATOR = "warehouse_operator"
    INVENTORY_MANAGER = "inventory_manager"
    PROCUREMENT_MANAGER = "procurement_manager"
    LOGISTICS_MANAGER = "logistics_manager"
    SALES_MANAGER = "sales_manager"
    FINANCE_MANAGER = "finance_manager"
    DEMAND_PLANNER = "demand_planner"
    BUSINESS_ANALYST = "business_analyst"
    AI_ENGINEER = "ai_engineer"
    SECURITY_MANAGER = "security_manager"


@dataclass(frozen=True)
class UserActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str] = frozenset()
    is_active: bool = True


@dataclass
class RetailUser:
    user_id: str
    tenant_id: str
    full_name: str
    email: str
    department: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str]
    status: UserStatus
    created_at: str
    updated_at: str
    version: int = 1


@dataclass(frozen=True)
class UserAuditEvent:
    event_id: str
    tenant_id: str
    user_id: str
    actor_id: str
    action: str
    timestamp: str
    details: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass
class UserOutboxEvent:
    event_id: str
    tenant_id: str
    user_id: str
    event_type: str
    created_at: str
    delivered: bool = False


class RetailUserService:
    ADMIN_ROLES = frozenset({
        "corporate_admin",
        "security_manager",
    })

    VIEWER_ROLES = ADMIN_ROLES | frozenset({
        "operations_manager",
        "warehouse_manager",
    })

    def __init__(self, tenant_id: str):
        self.tenant_id = required(
            tenant_id, "tenant_id"
        )

        self._lock = threading.RLock()
        self._users: dict[str, RetailUser] = {}
        self._email_index: dict[str, str] = {}
        self._audit: list[UserAuditEvent] = []
        self._outbox: dict[str, UserOutboxEvent] = {}

    def _authorize(
        self,
        actor: UserActor,
        roles: frozenset[str],
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.user_id.strip()
            or not actor.roles.intersection(roles)
        ):
            raise PermissionError("User access denied")

    def _get(self, user_id: str) -> RetailUser:
        user = self._users.get(user_id)

        if user is None:
            raise KeyError("User not found")

        return user

    def _record(
        self,
        actor_id: str,
        user: RetailUser,
        action: str,
        details: dict | None = None,
    ) -> None:
        self._audit.append(UserAuditEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            user_id=user.user_id,
            actor_id=actor_id,
            action=action,
            timestamp=utc_now(),
            details=copy.deepcopy(details or {}),
        ))

        event = UserOutboxEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            user_id=user.user_id,
            event_type=f"user.{action}",
            created_at=utc_now(),
        )

        self._outbox[event.event_id] = event

    @staticmethod
    def _touch(user: RetailUser) -> None:
        user.version += 1
        user.updated_at = utc_now()

    @staticmethod
    def _validate_roles(
        roles: frozenset[str],
    ) -> None:
        allowed = {role.value for role in UserRole}

        if not roles or not roles.issubset(allowed):
            raise ValueError("Invalid role assignment")

    def create_user(
        self,
        actor: UserActor,
        user_id: str,
        full_name: str,
        email: str,
        department: str,
        roles: frozenset[str],
        warehouse_ids: frozenset[str],
    ) -> RetailUser:
        self._authorize(actor, self.ADMIN_ROLES)

        user_id = required(user_id, "user_id")
        full_name = required(full_name, "full_name")
        email = normalize_email(email)
        department = required(department, "department")
        self._validate_roles(roles)

        if (
            "corporate_admin" in roles
            and "corporate_admin" not in actor.roles
        ):
            raise PermissionError(
                "Only corporate admins can assign admin role"
            )

        if any(
            not isinstance(w, str) or not w.strip()
            for w in warehouse_ids
        ):
            raise ValueError("Invalid warehouse assignment")

        with self._lock:
            if user_id in self._users:
                raise ValueError("User ID already exists")

            if email in self._email_index:
                raise ValueError("Email already exists")

            current = utc_now()

            user = RetailUser(
                user_id=user_id,
                tenant_id=self.tenant_id,
                full_name=full_name,
                email=email,
                department=department,
                roles=roles,
                warehouse_ids=warehouse_ids,
                status=UserStatus.INVITED,
                created_at=current,
                updated_at=current,
            )

            self._users[user_id] = user
            self._email_index[email] = user_id

            self._record(
                actor.user_id, user, "created"
            )

            return copy.deepcopy(user)

    def activate_user(
        self,
        actor: UserActor,
        user_id: str,
        expected_version: int,
    ) -> RetailUser:
        self._authorize(actor, self.ADMIN_ROLES)

        with self._lock:
            user = self._get(user_id)

            if user.version != expected_version:
                raise ValueError("Version conflict")

            if user.status not in {
                UserStatus.INVITED,
                UserStatus.SUSPENDED,
            }:
                raise ValueError(
                    "Invalid activation transition"
                )

            user.status = UserStatus.ACTIVE
            self._touch(user)

            self._record(
                actor.user_id, user, "activated"
            )

            return copy.deepcopy(user)

    def suspend_user(
        self,
        actor: UserActor,
        user_id: str,
        expected_version: int,
        reason: str,
    ) -> RetailUser:
        self._authorize(actor, self.ADMIN_ROLES)
        reason = required(reason, "reason")

        with self._lock:
            user = self._get(user_id)

            if user.version != expected_version:
                raise ValueError("Version conflict")

            if user.status != UserStatus.ACTIVE:
                raise ValueError("User is not active")

            if user.user_id == actor.user_id:
                raise PermissionError(
                    "Cannot suspend own account"
                )

            user.status = UserStatus.SUSPENDED
            self._touch(user)

            self._record(
                actor.user_id,
                user,
                "suspended",
                {"reason": reason},
            )

            return copy.deepcopy(user)

    def disable_user(
        self,
        actor: UserActor,
        user_id: str,
        expected_version: int,
    ) -> RetailUser:
        self._authorize(actor, self.ADMIN_ROLES)

        with self._lock:
            user = self._get(user_id)

            if user.version != expected_version:
                raise ValueError("Version conflict")

            if user.user_id == actor.user_id:
                raise PermissionError(
                    "Cannot disable own account"
                )

            if user.status == UserStatus.DISABLED:
                raise ValueError("Already disabled")

            user.status = UserStatus.DISABLED
            self._touch(user)

            self._record(
                actor.user_id, user, "disabled"
            )

            return copy.deepcopy(user)

    def update_profile(
        self,
        actor: UserActor,
        user_id: str,
        expected_version: int,
        *,
        full_name: str | None = None,
        department: str | None = None,
    ) -> RetailUser:
        self._authorize(actor, self.ADMIN_ROLES)

        with self._lock:
            user = self._get(user_id)

            if user.version != expected_version:
                raise ValueError("Version conflict")

            if user.status == UserStatus.DISABLED:
                raise ValueError("Disabled user cannot be edited")

            if full_name is not None:
                user.full_name = required(
                    full_name, "full_name"
                )

            if department is not None:
                user.department = required(
                    department, "department"
                )

            self._touch(user)
            self._record(
                actor.user_id, user, "profile_updated"
            )

            return copy.deepcopy(user)

    def assign_roles(
        self,
        actor: UserActor,
        user_id: str,
        expected_version: int,
        roles: frozenset[str],
    ) -> RetailUser:
        self._authorize(actor, self.ADMIN_ROLES)
        self._validate_roles(roles)

        if (
            "corporate_admin" in roles
            and "corporate_admin" not in actor.roles
        ):
            raise PermissionError(
                "Corporate admin permission required"
            )

        with self._lock:
            user = self._get(user_id)

            if user.version != expected_version:
                raise ValueError("Version conflict")

            if user.status == UserStatus.DISABLED:
                raise ValueError("Cannot modify disabled user")

            if (
                "corporate_admin" in user.roles
                and "corporate_admin" not in actor.roles
            ):
                raise PermissionError(
                    "Cannot modify corporate admin"
                )

            if user.user_id == actor.user_id:
                raise PermissionError(
                    "Cannot change own roles"
                )

            user.roles = roles
            self._touch(user)

            self._record(
                actor.user_id,
                user,
                "roles_updated",
                {"roles": sorted(roles)},
            )

            return copy.deepcopy(user)

    def assign_warehouses(
        self,
        actor: UserActor,
        user_id: str,
        expected_version: int,
        warehouse_ids: frozenset[str],
    ) -> RetailUser:
        self._authorize(actor, self.ADMIN_ROLES)

        if any(
            not isinstance(w, str) or not w.strip()
            for w in warehouse_ids
        ):
            raise ValueError("Invalid warehouse assignment")

        with self._lock:
            user = self._get(user_id)

            if user.version != expected_version:
                raise ValueError("Version conflict")

            if user.status == UserStatus.DISABLED:
                raise ValueError("Cannot modify disabled user")

            user.warehouse_ids = warehouse_ids
            self._touch(user)

            self._record(
                actor.user_id,
                user,
                "warehouses_updated",
                {"warehouse_ids": sorted(warehouse_ids)},
            )

            return copy.deepcopy(user)

    def get_user(
        self,
        actor: UserActor,
        user_id: str,
    ) -> RetailUser:
        with self._lock:
            user = self._get(user_id)

            if actor.user_id != user_id:
                self._authorize(
                    actor, self.VIEWER_ROLES
                )
            elif (
                not actor.is_active
                or actor.tenant_id != self.tenant_id
            ):
                raise PermissionError("Access denied")

            return copy.deepcopy(user)

    def list_users(
        self,
        actor: UserActor,
        status: UserStatus | None = None,
    ) -> list[RetailUser]:
        self._authorize(actor, self.VIEWER_ROLES)

        with self._lock:
            return [
                copy.deepcopy(user)
                for user in self._users.values()
                if status is None or user.status == status
            ]

    def user_metrics(
        self,
        actor: UserActor,
    ) -> dict[str, Any]:
        users = self.list_users(actor)

        return {
            "tenant_id": self.tenant_id,
            "total_users": len(users),
            "active_users": sum(
                u.status == UserStatus.ACTIVE
                for u in users
            ),
            "invited_users": sum(
                u.status == UserStatus.INVITED
                for u in users
            ),
            "suspended_users": sum(
                u.status == UserStatus.SUSPENDED
                for u in users
            ),
            "disabled_users": sum(
                u.status == UserStatus.DISABLED
                for u in users
            ),
        }

    def audit_events(
        self,
        actor: UserActor,
        user_id: str,
    ) -> list[UserAuditEvent]:
        self._authorize(actor, self.ADMIN_ROLES)

        with self._lock:
            self._get(user_id)

            return [
                copy.deepcopy(event)
                for event in self._audit
                if event.user_id == user_id
            ]

    def pending_events(
        self,
        actor: UserActor,
    ) -> list[UserOutboxEvent]:
        self._authorize(actor, self.ADMIN_ROLES)

        with self._lock:
            return [
                copy.deepcopy(event)
                for event in self._outbox.values()
                if not event.delivered
            ]

    def mark_event_delivered(
        self,
        actor: UserActor,
        event_id: str,
    ) -> None:
        self._authorize(actor, self.ADMIN_ROLES)

        with self._lock:
            event = self._outbox.get(event_id)

            if event is None:
                raise KeyError("Event not found")

            event.delivered = True


if __name__ == "__main__":
    service = RetailUserService("demo")

    admin = UserActor(
        user_id="ADMIN001",
        tenant_id="demo",
        roles=frozenset({"corporate_admin"}),
    )

    user = service.create_user(
        actor=admin,
        user_id="USER001",
        full_name="Demo Warehouse Manager",
        email="warehouse@example.com",
        department="Warehouse Operations",
        roles=frozenset({"warehouse_manager"}),
        warehouse_ids=frozenset({"WH001"}),
    )

    user = service.activate_user(
        admin, user.user_id, user.version
    )

    print("User:", user.full_name)
    print("Status:", user.status.value)
    print("Metrics:", service.user_metrics(admin))
 