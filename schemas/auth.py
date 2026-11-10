from __future__ import annotations

"""Planned module: auth. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
backend/services/auth_service.py

Reference implementation — Python 3.10+.

Features:
- Tenant-isolated user accounts
- PBKDF2-HMAC-SHA256 password hashing
- Constant-time credential comparisons
- Opaque random session tokens
- Hashed session-token storage
- Session expiry and revocation
- Account lockout
- RBAC and warehouse-scoped permissions
- Audit logging
- Safe public user views

Limitations:
- In-memory data
- No MFA, passkeys or OIDC
- No persistent rate limiting
- No distributed session store
- Not production-ready
"""


import copy
import hashlib
import hmac
import secrets
import threading
import uuid

from dataclasses import dataclass, field
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from enum import Enum
from typing import Iterable


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return now().isoformat()


def required(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 200
    ):
        raise ValueError(f"Invalid {name}")
    return value.strip()


class UserStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


@dataclass(frozen=True)
class AuthActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str]
    is_active: bool = True


@dataclass
class AuthUser:
    user_id: str
    tenant_id: str
    email: str
    password_hash: str
    password_salt: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str]
    status: UserStatus
    created_at: str
    failed_attempts: int = 0
    locked_until: str | None = None


@dataclass(frozen=True)
class PublicUser:
    user_id: str
    tenant_id: str
    email: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str]
    status: UserStatus


@dataclass
class AuthSession:
    session_id: str
    user_id: str
    tenant_id: str
    token_hash: str
    created_at: str
    expires_at: str
    revoked: bool = False


@dataclass(frozen=True)
class LoginResult:
    access_token: str
    session_id: str
    expires_at: str
    user: PublicUser


@dataclass(frozen=True)
class AuthAuditEvent:
    event_id: str
    tenant_id: str
    actor_id: str
    action: str
    timestamp: str
    details: dict = field(default_factory=dict)


class RetailAuthService:
    ITERATIONS = 600_000
    MAX_FAILED_ATTEMPTS = 5
    LOCKOUT_MINUTES = 15
    SESSION_MINUTES = 60

    ROLE_PERMISSIONS = {
        "corporate_admin": {
            "users:manage",
            "inventory:read",
            "inventory:write",
            "suppliers:read",
            "suppliers:write",
            "warehouse:read",
            "warehouse:write",
            "analytics:read",
            "alerts:manage",
            "agents:execute",
        },
        "operations_manager": {
            "inventory:read",
            "inventory:write",
            "suppliers:read",
            "warehouse:read",
            "analytics:read",
            "alerts:manage",
        },
        "warehouse_manager": {
            "inventory:read",
            "inventory:write",
            "warehouse:read",
            "warehouse:write",
            "alerts:manage",
        },
        "procurement_manager": {
            "suppliers:read",
            "suppliers:write",
            "inventory:read",
            "analytics:read",
        },
        "inventory_analyst": {
            "inventory:read",
            "analytics:read",
        },
        "ai_agent_operator": {
            "inventory:read",
            "suppliers:read",
            "analytics:read",
            "agents:execute",
        },
    }

    def __init__(self, tenant_id: str):
        self.tenant_id = required(
            tenant_id, "tenant_id"
        )
        self._lock = threading.RLock()
        self._users: dict[str, AuthUser] = {}
        self._emails: dict[str, str] = {}
        self._sessions: dict[str, AuthSession] = {}
        self._token_index: dict[str, str] = {}
        self._audit: list[AuthAuditEvent] = []

    @staticmethod
    def _public(user: AuthUser) -> PublicUser:
        return PublicUser(
            user_id=user.user_id,
            tenant_id=user.tenant_id,
            email=user.email,
            roles=user.roles,
            warehouse_ids=user.warehouse_ids,
            status=user.status,
        )

    @classmethod
    def _hash_password(
        cls,
        password: str,
        salt: bytes,
    ) -> str:
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            cls.ITERATIONS,
        ).hex()

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()

    def _audit_event(
        self,
        actor_id: str,
        action: str,
        details: dict | None = None,
    ) -> None:
        self._audit.append(
            AuthAuditEvent(
                event_id=str(uuid.uuid4()),
                tenant_id=self.tenant_id,
                actor_id=actor_id,
                action=action,
                timestamp=iso_now(),
                details=copy.deepcopy(details or {}),
            )
        )

    @staticmethod
    def _validate_password(
        password: str,
    ) -> None:
        if (
            not isinstance(password, str)
            or len(password) < 12
            or len(password.encode("utf-8")) > 1024
        ):
            raise ValueError(
                "Password must be 12+ characters "
                "and at most 1024 UTF-8 bytes"
            )

    def _create_user(
        self,
        user_id: str,
        email: str,
        password: str,
        roles: Iterable[str],
        warehouse_ids: Iterable[str],
    ) -> PublicUser:
        user_id = required(user_id, "user_id")
        email = required(email, "email").lower()
        self._validate_password(password)

        if "@" not in email or " " in email:
            raise ValueError("Invalid email")

        role_set = frozenset(roles)
        if (
            not role_set
            or not role_set.issubset(
                self.ROLE_PERMISSIONS.keys()
            )
        ):
            raise ValueError("Unsupported roles")

        warehouse_set = frozenset(
            required(w, "warehouse_id")
            for w in warehouse_ids
        )

        if user_id in self._users or email in self._emails:
            raise ValueError("User already exists")

        salt = secrets.token_bytes(16)

        user = AuthUser(
            user_id=user_id,
            tenant_id=self.tenant_id,
            email=email,
            password_hash=self._hash_password(
                password, salt
            ),
            password_salt=salt.hex(),
            roles=role_set,
            warehouse_ids=warehouse_set,
            status=UserStatus.ACTIVE,
            created_at=iso_now(),
        )

        self._users[user_id] = user
        self._emails[email] = user_id

        self._audit_event(
            user_id, "user_created"
        )

        return self._public(user)

    def bootstrap_admin(
        self,
        user_id: str,
        email: str,
        password: str,
    ) -> PublicUser:
        """
        Initial setup only.
        Disabled after the first account exists.
        """
        with self._lock:
            if self._users:
                raise PermissionError(
                    "Bootstrap is no longer available"
                )

            return self._create_user(
                user_id,
                email,
                password,
                roles={"corporate_admin"},
                warehouse_ids=set(),
            )

    def create_user(
        self,
        actor: AuthActor,
        user_id: str,
        email: str,
        password: str,
        roles: Iterable[str],
        warehouse_ids: Iterable[str] = (),
    ) -> PublicUser:
        self._require_permission(
            actor, "users:manage"
        )

        with self._lock:
            return self._create_user(
                user_id,
                email,
                password,
                roles,
                warehouse_ids,
            )

    def login(
        self,
        email: str,
        password: str,
    ) -> LoginResult:
        email = required(
            email, "email"
        ).lower()

        if not isinstance(password, str):
            raise PermissionError(
                "Invalid credentials"
            )

        with self._lock:
            user_id = self._emails.get(email)

            if user_id is None:
                # Avoid a trivial timing distinction
                # for unknown accounts.
                self._hash_password(
                    password,
                    bytes(16),
                )
                raise PermissionError(
                    "Invalid credentials"
                )

            user = self._users[user_id]

            if user.status != UserStatus.ACTIVE:
                raise PermissionError(
                    "Invalid credentials"
                )

            if user.locked_until:
                locked_until = (
                    datetime.fromisoformat(
                        user.locked_until
                    )
                )

                if now() < locked_until:
                    raise PermissionError(
                        "Account temporarily locked"
                    )

                user.locked_until = None
                user.failed_attempts = 0

            actual = self._hash_password(
                password,
                bytes.fromhex(
                    user.password_salt
                ),
            )

            valid = hmac.compare_digest(
                actual,
                user.password_hash,
            )

            if not valid:
                user.failed_attempts += 1

                if user.failed_attempts >= (
                    self.MAX_FAILED_ATTEMPTS
                ):
                    user.locked_until = (
                        now()
                        + timedelta(
                            minutes=self.LOCKOUT_MINUTES
                        )
                    ).isoformat()

                self._audit_event(
                    user_id,
                    "login_failed",
                )

                raise PermissionError(
                    "Invalid credentials"
                )

            user.failed_attempts = 0
            user.locked_until = None

            token = secrets.token_urlsafe(48)
            token_hash = self._hash_token(
                token
            )
            session_id = str(
                uuid.uuid4()
            )
            expires_at = (
                now()
                + timedelta(
                    minutes=self.SESSION_MINUTES
                )
            ).isoformat()

            session = AuthSession(
                session_id=session_id,
                user_id=user_id,
                tenant_id=self.tenant_id,
                token_hash=token_hash,
                created_at=iso_now(),
                expires_at=expires_at,
            )

            self._sessions[
                session_id
            ] = session

            self._token_index[
                token_hash
            ] = session_id

            self._audit_event(
                user_id,
                "login_success",
            )

            return LoginResult(
                access_token=token,
                session_id=session_id,
                expires_at=expires_at,
                user=self._public(user),
            )

    def authenticate(
        self,
        access_token: str,
    ) -> AuthActor:
        if not isinstance(access_token, str):
            raise PermissionError(
                "Invalid session"
            )

        token_hash = self._hash_token(
            access_token
        )

        with self._lock:
            session_id = (
                self._token_index.get(
                    token_hash
                )
            )

            if session_id is None:
                raise PermissionError(
                    "Invalid session"
                )

            session = self._sessions[
                session_id
            ]

            if (
                session.revoked
                or now() >= datetime.fromisoformat(
                    session.expires_at
                )
            ):
                raise PermissionError(
                    "Session expired or revoked"
                )

            user = self._users.get(
                session.user_id
            )

            if (
                user is None
                or user.status
                != UserStatus.ACTIVE
            ):
                raise PermissionError(
                    "Account disabled"
                )

            return AuthActor(
                user_id=user.user_id,
                tenant_id=user.tenant_id,
                roles=user.roles,
                warehouse_ids=(
                    user.warehouse_ids
                ),
            )

    def _require_permission(
        self,
        actor: AuthActor,
        permission: str,
        warehouse_id: str | None = None,
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id
            != self.tenant_id
        ):
            raise PermissionError(
                "Access denied"
            )

        # Do not trust caller-provided role claims.
        with self._lock:
            user = self._users.get(
                actor.user_id
            )

            if (
                user is None
                or user.status
                != UserStatus.ACTIVE
            ):
                raise PermissionError(
                    "Account unavailable"
                )

            if (
                actor.roles != user.roles
                or actor.warehouse_ids
                != user.warehouse_ids
            ):
                raise PermissionError(
                    "Actor claims do not match"
                )

            permissions = set()

            for role in user.roles:
                permissions.update(
                    self.ROLE_PERMISSIONS.get(
                        role, set()
                    )
                )

            if permission not in permissions:
                raise PermissionError(
                    "Missing permission"
                )

            if (
                warehouse_id is not None
                and "corporate_admin"
                not in user.roles
                and warehouse_id
                not in user.warehouse_ids
            ):
                raise PermissionError(
                    "Warehouse access denied"
                )

    def require_access(
        self,
        access_token: str,
        permission: str,
        warehouse_id: str | None = None,
    ) -> AuthActor:
        actor = self.authenticate(
            access_token
        )

        self._require_permission(
            actor,
            permission,
            warehouse_id,
        )

        return actor

    def logout(
        self,
        access_token: str,
    ) -> None:
        actor = self.authenticate(
            access_token
        )

        token_hash = self._hash_token(
            access_token
        )

        with self._lock:
            session_id = (
                self._token_index.pop(
                    token_hash,
                    None,
                )
            )

            if session_id:
                self._sessions[
                    session_id
                ].revoked = True

            self._audit_event(
                actor.user_id,
                "logout",
            )

    def disable_user(
        self,
        actor: AuthActor,
        user_id: str,
    ) -> None:
        self._require_permission(
            actor, "users:manage"
        )

        with self._lock:
            if actor.user_id == user_id:
                raise ValueError(
                    "Cannot disable own account"
                )

            user = self._users.get(
                user_id
            )

            if user is None:
                raise KeyError(
                    "User not found"
                )

            user.status = (
                UserStatus.DISABLED
            )

            for session in (
                self._sessions.values()
            ):
                if session.user_id == user_id:
                    session.revoked = True
                    self._token_index.pop(
                        session.token_hash,
                        None,
                    )

            self._audit_event(
                actor.user_id,
                "user_disabled",
                {"target_user_id": user_id},
            )

    def audit_events(
        self,
        actor: AuthActor,
    ) -> list[AuthAuditEvent]:
        self._require_permission(
            actor, "users:manage"
        )

        with self._lock:
            return copy.deepcopy(
                self._audit
            )


if __name__ == "__main__":
    service = RetailAuthService(
        tenant_id="demo"
    )

    service.bootstrap_admin(
        user_id="admin001",
        email="admin@example.com",
        password="Demo-Strong-Password-2026!",
    )

    login = service.login(
        email="admin@example.com",
        password="Demo-Strong-Password-2026!",
    )

    actor = service.require_access(
        login.access_token,
        "users:manage",
    )

    service.create_user(
        actor=actor,
        user_id="user001",
        email="analyst@example.com",
        password="Another-Strong-Password-2026!",
        roles={"inventory_analyst"},
        warehouse_ids={"WH001"},
    )

    analyst_login = service.login(
        "analyst@example.com",
        "Another-Strong-Password-2026!",
    )

    analyst = service.require_access(
        analyst_login.access_token,
        "inventory:read",
        warehouse_id="WH001",
    )

    print(
        "Authenticated:",
        analyst.user_id,
    )

    service.logout(
        analyst_login.access_token
    )

    print(
        "Session revoked successfully"
    )
