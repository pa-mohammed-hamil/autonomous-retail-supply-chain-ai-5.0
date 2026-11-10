from __future__ import annotations

"""Planned module: user. Implementation pending."""
# backend/models/user.py


import enum
import uuid
from datetime import datetime, timezone
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
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.base import Base


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def enum_column(enum_class: type[enum.Enum], name: str):
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


def required_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def optional_text(value: str | None) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise ValueError("Expected a string")

    return value.strip() or None


def normalize_email(email: str) -> str:
    value = required_text(email, "Email").lower()

    if (
        "@" not in value
        or value.startswith("@")
        or value.endswith("@")
        or any(char.isspace() for char in value)
    ):
        raise ValueError("Invalid email address")

    return value


def enum_value(value: Any) -> Any:
    return value.value if isinstance(value, enum.Enum) else value


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value

    if isinstance(value, enum.Enum):
        return value.value

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, float):
        if not __import__("math").isfinite(value):
            raise ValueError("Non-finite JSON number")
        return value

    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]

    raise ValueError(
        f"Unsupported JSON type: {type(value).__name__}"
    )


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


# ============================================================
# ENUMS
# ============================================================

class UserStatus(str, enum.Enum):
    INVITED = "invited"
    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    LOCKED = "locked"
    DEACTIVATED = "deactivated"
    ARCHIVED = "archived"


class UserRole(str, enum.Enum):
    SUPER_ADMIN = "super_admin"
    ORGANIZATION_ADMIN = "organization_admin"
    OPERATIONS_MANAGER = "operations_manager"
    SUPPLY_CHAIN_MANAGER = "supply_chain_manager"
    PROCUREMENT_MANAGER = "procurement_manager"
    INVENTORY_MANAGER = "inventory_manager"
    WAREHOUSE_MANAGER = "warehouse_manager"
    STORE_MANAGER = "store_manager"
    LOGISTICS_MANAGER = "logistics_manager"
    FINANCE_MANAGER = "finance_manager"
    RISK_MANAGER = "risk_manager"
    QUALITY_MANAGER = "quality_manager"
    DATA_ANALYST = "data_analyst"
    DATA_SCIENTIST = "data_scientist"
    AI_ENGINEER = "ai_engineer"
    ML_ENGINEER = "ml_engineer"
    AI_AGENT_OPERATOR = "ai_agent_operator"
    APPROVER = "approver"
    AUDITOR = "auditor"
    EMPLOYEE = "employee"
    SUPPLIER = "supplier"
    VIEWER = "viewer"


class UserType(str, enum.Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"
    SUPPLIER = "supplier"
    CONTRACTOR = "contractor"
    SERVICE_ACCOUNT = "service_account"


class UserAuthenticationProvider(str, enum.Enum):
    LOCAL = "local"
    GOOGLE = "google"
    MICROSOFT = "microsoft"
    OIDC = "oidc"
    SAML = "saml"
    SERVICE_ACCOUNT = "service_account"


class UserMFAType(str, enum.Enum):
    NONE = "none"
    TOTP = "totp"
    PASSKEY = "passkey"
    SECURITY_KEY = "security_key"
    AUTHENTICATOR_APP = "authenticator_app"


class UserNotificationPreference(str, enum.Enum):
    ALL = "all"
    IMPORTANT_ONLY = "important_only"
    CRITICAL_ONLY = "critical_only"
    NONE = "none"


class UserEventType(str, enum.Enum):
    CREATED = "created"
    INVITED = "invited"
    INVITATION_ACCEPTED = "invitation_accepted"
    EMAIL_VERIFIED = "email_verified"
    ACTIVATED = "activated"
    PROFILE_UPDATED = "profile_updated"
    ROLE_CHANGED = "role_changed"
    PERMISSION_UPDATED = "permission_updated"
    PASSWORD_CHANGED = "password_changed"
    LOGIN_SUCCEEDED = "login_succeeded"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    MFA_ENABLED = "mfa_enabled"
    MFA_DISABLED = "mfa_disabled"
    ACCOUNT_LOCKED = "account_locked"
    ACCOUNT_UNLOCKED = "account_unlocked"
    SUSPENDED = "suspended"
    REACTIVATED = "reactivated"
    DEACTIVATED = "deactivated"
    ACCESS_REVOKED = "access_revoked"
    ARCHIVED = "archived"
    SOFT_DELETED = "soft_deleted"


# ============================================================
# USER MODEL
# ============================================================

class User(Base):
    __tablename__ = "users"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_user_org_id",
        ),
        UniqueConstraint(
            "organization_id",
            "email",
            name="uq_user_org_email",
        ),
        UniqueConstraint(
            "organization_id",
            "employee_code",
            name="uq_user_org_employee_code",
        ),
        UniqueConstraint(
            "organization_id",
            "external_identity_id",
            name="uq_user_org_external_identity",
        ),
        CheckConstraint(
            "failed_login_attempts >= 0",
            name="ck_user_failed_logins",
        ),
        CheckConstraint(
            "session_version >= 1",
            name="ck_user_session_version",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_user_version",
        ),
        Index(
            "ix_user_org_status",
            "organization_id",
            "status",
        ),
        Index(
            "ix_user_org_role",
            "organization_id",
            "role",
        ),
        Index(
            "ix_user_org_type",
            "organization_id",
            "user_type",
        ),
        Index(
            "ix_user_org_department",
            "organization_id",
            "department",
        ),
        Index(
            "ix_user_org_last_login",
            "organization_id",
            "last_login_at",
        ),
    )

    # ========================================================
    # IDENTITY
    # ========================================================

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

    employee_code: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )

    external_identity_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    username: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    first_name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    last_name: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    display_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    phone_number: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
    )

    avatar_url: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    bio: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ========================================================
    # CLASSIFICATION
    # ========================================================

    status: Mapped[UserStatus] = mapped_column(
        enum_column(UserStatus, "user_status"),
        default=UserStatus.INVITED,
        nullable=False,
    )

    role: Mapped[UserRole] = mapped_column(
        enum_column(UserRole, "user_role"),
        default=UserRole.VIEWER,
        nullable=False,
    )

    user_type: Mapped[UserType] = mapped_column(
        enum_column(UserType, "user_type"),
        default=UserType.INTERNAL,
        nullable=False,
    )

    # ========================================================
    # ORGANIZATIONAL STRUCTURE
    # ========================================================

    department: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    designation: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    manager_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    primary_warehouse_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    primary_store_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    supplier_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    assigned_warehouse_ids: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    assigned_store_ids: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    assigned_region_ids: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    # ========================================================
    # AUTHENTICATION
    # ========================================================

    authentication_provider: Mapped[
        UserAuthenticationProvider
    ] = mapped_column(
        enum_column(
            UserAuthenticationProvider,
            "user_authentication_provider",
        ),
        default=UserAuthenticationProvider.LOCAL,
        nullable=False,
    )

    password_hash: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    password_changed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    password_reset_required: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    email_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    email_verified_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    phone_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    phone_verified_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # MFA
    # ========================================================

    mfa_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    mfa_type: Mapped[UserMFAType] = mapped_column(
        enum_column(
            UserMFAType,
            "user_mfa_type",
        ),
        default=UserMFAType.NONE,
        nullable=False,
    )

    mfa_enabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # MFA secrets, recovery codes, passkey credentials and
    # private authentication material must be stored in a
    # dedicated encrypted credential store, not this table.

    # ========================================================
    # ACCOUNT SECURITY
    # ========================================================

    failed_login_attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    last_failed_login_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_logout_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    session_version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    force_logout: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # ========================================================
    # RBAC AND PERMISSIONS
    # ========================================================

    custom_roles: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    permission_overrides: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    access_scopes: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    can_approve_purchase_orders: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    can_approve_replenishment: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    can_approve_supplier_contracts: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    can_approve_ai_actions: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    can_manage_ai_agents: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    can_view_financial_data: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    can_export_sensitive_data: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # ========================================================
    # AI AGENT ACCESS
    # ========================================================

    ai_assistant_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    agent_execution_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    allowed_agent_ids: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    allowed_ai_tools: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
    )

    ai_preferences: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    ai_approval_required: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # ========================================================
    # USER PREFERENCES
    # ========================================================

    language: Mapped[str] = mapped_column(
        String(20),
        default="en",
        nullable=False,
    )

    timezone_name: Mapped[str] = mapped_column(
        String(100),
        default="Asia/Kolkata",
        nullable=False,
    )

    date_format: Mapped[str] = mapped_column(
        String(30),
        default="YYYY-MM-DD",
        nullable=False,
    )

    theme: Mapped[str] = mapped_column(
        String(30),
        default="system",
        nullable=False,
    )

    notification_preference: Mapped[
        UserNotificationPreference
    ] = mapped_column(
        enum_column(
            UserNotificationPreference,
            "user_notification_preference",
        ),
        default=UserNotificationPreference.ALL,
        nullable=False,
    )

    email_notifications_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    push_notifications_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    sms_notifications_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    critical_alerts_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    notification_settings: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    dashboard_preferences: Mapped[
        dict[str, Any]
    ] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    # ========================================================
    # INVITATION
    # ========================================================

    invited_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    invited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    invitation_accepted_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Invitation tokens must be stored as hashes in a separate
    # short-lived token table.

    # ========================================================
    # LIFECYCLE
    # ========================================================

    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    suspension_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    deactivation_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ========================================================
    # AUDIT
    # ========================================================

    user_metadata: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    tags: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(JSON),
        default=list,
        nullable=False,
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

    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    __mapper_args__ = {
        "version_id_col": version,
    }

    # ========================================================
    # RELATIONSHIPS
    # ========================================================

    events: Mapped[list["UserEvent"]] = relationship(
        "UserEvent",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="UserEvent.created_at",
    )

    # ========================================================
    # INITIALIZATION
    # ========================================================

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        if self.id is None:
            self.id = generate_uuid()

        if self.email is not None:
            self.email = normalize_email(self.email)

        defaults = {
            "status": UserStatus.INVITED,
            "role": UserRole.VIEWER,
            "user_type": UserType.INTERNAL,
            "authentication_provider": (
                UserAuthenticationProvider.LOCAL
            ),
            "mfa_type": UserMFAType.NONE,
            "notification_preference": (
                UserNotificationPreference.ALL
            ),
            "email_verified": False,
            "phone_verified": False,
            "mfa_enabled": False,
            "password_reset_required": False,
            "failed_login_attempts": 0,
            "session_version": 1,
            "force_logout": False,
            "ai_assistant_enabled": True,
            "agent_execution_enabled": False,
            "ai_approval_required": True,
            "email_notifications_enabled": True,
            "push_notifications_enabled": True,
            "sms_notifications_enabled": False,
            "critical_alerts_enabled": True,
            "can_approve_purchase_orders": False,
            "can_approve_replenishment": False,
            "can_approve_supplier_contracts": False,
            "can_approve_ai_actions": False,
            "can_manage_ai_agents": False,
            "can_view_financial_data": False,
            "can_export_sensitive_data": False,
            "language": "en",
            "timezone_name": "Asia/Kolkata",
            "date_format": "YYYY-MM-DD",
            "theme": "system",
            "is_deleted": False,
            "version": 1,
        }

        for field, value in defaults.items():
            if getattr(self, field, None) is None:
                setattr(self, field, value)

        for field in (
            "permission_overrides",
            "ai_preferences",
            "notification_settings",
            "dashboard_preferences",
            "user_metadata",
        ):
            if getattr(self, field, None) is None:
                setattr(self, field, {})

        for field in (
            "assigned_warehouse_ids",
            "assigned_store_ids",
            "assigned_region_ids",
            "custom_roles",
            "access_scopes",
            "allowed_agent_ids",
            "allowed_ai_tools",
            "tags",
        ):
            if getattr(self, field, None) is None:
                setattr(self, field, [])

        if self.created_at is None:
            self.created_at = utc_now()

        if self.updated_at is None:
            self.updated_at = utc_now()

    # ========================================================
    # COMPUTED PROPERTIES
    # ========================================================

    @property
    def full_name(self) -> str:
        return " ".join(
            value
            for value in (
                self.first_name,
                self.last_name,
            )
            if value
        )

    @property
    def is_active(self) -> bool:
        return (
            self.status == UserStatus.ACTIVE
            and not self.is_deleted
        )

    @property
    def is_admin(self) -> bool:
        return self.role in {
            UserRole.SUPER_ADMIN,
            UserRole.ORGANIZATION_ADMIN,
        }

    @property
    def is_locked(self) -> bool:
        if self.status == UserStatus.LOCKED:
            return True

        if self.locked_until is None:
            return False

        locked_until = self.locked_until

        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(
                tzinfo=timezone.utc
            )

        return locked_until > utc_now()

    @property
    def can_login(self) -> bool:
        return (
            self.is_active
            and self.email_verified
            and not self.is_locked
            and not self.force_logout
        )

    @property
    def can_execute_ai_agents(self) -> bool:
        return (
            self.is_active
            and self.agent_execution_enabled
            and self.ai_assistant_enabled
        )

    @property
    def is_service_account(self) -> bool:
        return self.user_type == UserType.SERVICE_ACCOUNT

    # ========================================================
    # INTERNAL HELPERS
    # ========================================================

    def _ensure_editable(self) -> None:
        if self.is_deleted:
            raise ValueError("User has been deleted")

        if self.status == UserStatus.ARCHIVED:
            raise ValueError("Archived user cannot be modified")

    def _record_event(
        self,
        event_type: UserEventType,
        *,
        actor_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.events.append(
            UserEvent(
                id=generate_uuid(),
                organization_id=required_text(
                    self.organization_id,
                    "Organization ID",
                ),
                event_type=event_type,
                actor_id=actor_id,
                details=json_safe(details or {}),
                created_at=utc_now(),
            )
        )

        self.updated_at = utc_now()

        if actor_id is not None:
            self.updated_by = actor_id

    def _revoke_sessions(self) -> None:
        self.session_version = (
            self.session_version or 1
        ) + 1

        self.force_logout = True

    # ========================================================
    # VALIDATION
    # ========================================================

    def validate_user(self) -> None:
        required_text(
            self.organization_id,
            "Organization ID",
        )

        self.email = normalize_email(self.email)

        self.first_name = required_text(
            self.first_name,
            "First name",
        )

        if self.user_type == UserType.SERVICE_ACCOUNT:
            if self.authentication_provider != (
                UserAuthenticationProvider.SERVICE_ACCOUNT
            ):
                raise ValueError(
                    "Service accounts require service-account authentication"
                )

    # ========================================================
    # UPDATE PROFILE
    # ========================================================

    def update_profile(
        self,
        *,
        actor_id: str,
        first_name: str | None = None,
        last_name: str | None = None,
        display_name: str | None = None,
        phone_number: str | None = None,
        avatar_url: str | None = None,
        bio: str | None = None,
    ) -> None:
        self._ensure_editable()

        if first_name is not None:
            self.first_name = required_text(
                first_name,
                "First name",
            )

        if last_name is not None:
            self.last_name = optional_text(last_name)

        if display_name is not None:
            self.display_name = optional_text(display_name)

        if phone_number is not None:
            self.phone_number = optional_text(phone_number)

        if avatar_url is not None:
            self.avatar_url = optional_text(avatar_url)

        if bio is not None:
            self.bio = optional_text(bio)

        self._record_event(
            UserEventType.PROFILE_UPDATED,
            actor_id=actor_id,
        )

    # ========================================================
    # INVITE USER
    # ========================================================

    def invite(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        if self.status != UserStatus.INVITED:
            raise ValueError(
                "User is not in invited status"
            )

        self.validate_user()

        self.invited_by = required_text(
            actor_id,
            "Inviter ID",
        )

        self.invited_at = utc_now()

        self._record_event(
            UserEventType.INVITED,
            actor_id=actor_id,
        )

    # ========================================================
    # ACCEPT INVITATION
    # ========================================================

    def accept_invitation(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        if self.status != UserStatus.INVITED:
            raise ValueError(
                "Invitation is not pending"
            )

        self.invitation_accepted_at = utc_now()
        self.status = UserStatus.PENDING_VERIFICATION

        self._record_event(
            UserEventType.INVITATION_ACCEPTED,
            actor_id=actor_id,
        )

    # ========================================================
    # VERIFY EMAIL
    # ========================================================

    def verify_email(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        if self.email_verified:
            raise ValueError("Email already verified")

        # Call only after the authentication service has
        # validated a single-use email verification token.
        self.email_verified = True
        self.email_verified_at = utc_now()

        self._record_event(
            UserEventType.EMAIL_VERIFIED,
            actor_id=actor_id,
        )

    # ========================================================
    # ACTIVATE
    # ========================================================

    def activate(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        if self.status not in {
            UserStatus.PENDING_VERIFICATION,
            UserStatus.INACTIVE,
            UserStatus.DEACTIVATED,
        }:
            raise ValueError(
                "User cannot be activated from current status"
            )

        if not self.email_verified and not self.is_service_account:
            raise ValueError(
                "Email verification is required"
            )

        self.status = UserStatus.ACTIVE
        self.activated_at = utc_now()
        self.force_logout = False

        self._record_event(
            UserEventType.ACTIVATED,
            actor_id=actor_id,
        )

    # ========================================================
    # CHANGE ROLE
    # ========================================================

    def change_role(
        self,
        *,
        actor_id: str,
        new_role: UserRole,
    ) -> None:
        self._ensure_editable()

        if not isinstance(new_role, UserRole):
            raise ValueError("Invalid user role")

        old_role = self.role

        if old_role == new_role:
            return

        self.role = new_role
        self._revoke_sessions()

        self._record_event(
            UserEventType.ROLE_CHANGED,
            actor_id=actor_id,
            details={
                "old_role": enum_value(old_role),
                "new_role": new_role.value,
            },
        )

    # ========================================================
    # UPDATE PERMISSIONS
    # ========================================================

    def update_permissions(
        self,
        *,
        actor_id: str,
        permissions: dict[str, Any],
        scopes: list[str] | None = None,
    ) -> None:
        self._ensure_editable()

        if not isinstance(permissions, dict):
            raise ValueError(
                "Permissions must be a dictionary"
            )

        self.permission_overrides = json_safe(permissions)

        if scopes is not None:
            if not isinstance(scopes, list):
                raise ValueError("Scopes must be a list")

            self.access_scopes = [
                required_text(scope, "Scope")
                for scope in scopes
            ]

        self._revoke_sessions()

        self._record_event(
            UserEventType.PERMISSION_UPDATED,
            actor_id=actor_id,
        )

    # ========================================================
    # CHANGE PASSWORD HASH
    # ========================================================

    def set_password_hash(
        self,
        *,
        actor_id: str,
        password_hash: str,
    ) -> None:
        self._ensure_editable()

        if self.authentication_provider != (
            UserAuthenticationProvider.LOCAL
        ):
            raise ValueError(
                "Password updates require local authentication"
            )

        # Hashing, password policy, breach checks and
        # authorization must be performed by the auth service.
        # Never pass or store a plaintext password here.

        value = required_text(
            password_hash,
            "Password hash",
        )

        if not (
            value.startswith("$argon2id$")
            or value.startswith("$2b$")
            or value.startswith("$2a$")
            or value.startswith("$2y$")
        ):
            raise ValueError(
                "Expected an Argon2id or bcrypt password hash"
            )

        self.password_hash = value
        self.password_changed_at = utc_now()
        self.password_reset_required = False

        self._revoke_sessions()

        self._record_event(
            UserEventType.PASSWORD_CHANGED,
            actor_id=actor_id,
        )

    # ========================================================
    # ENABLE MFA
    # ========================================================

    def enable_mfa(
        self,
        *,
        actor_id: str,
        mfa_type: UserMFAType,
    ) -> None:
        self._ensure_editable()

        if mfa_type == UserMFAType.NONE:
            raise ValueError("Choose an MFA method")

        if not isinstance(mfa_type, UserMFAType):
            raise ValueError("Invalid MFA method")

        # The authentication service must first verify
        # successful MFA enrollment and proof of possession.

        self.mfa_enabled = True
        self.mfa_type = mfa_type
        self.mfa_enabled_at = utc_now()

        self._revoke_sessions()

        self._record_event(
            UserEventType.MFA_ENABLED,
            actor_id=actor_id,
            details={"mfa_type": mfa_type.value},
        )

    # ========================================================
    # DISABLE MFA
    # ========================================================

    def disable_mfa(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        if not self.mfa_enabled:
            raise ValueError("MFA is not enabled")

        # Require fresh authentication and authorization
        # in the security service before calling this method.

        self.mfa_enabled = False
        self.mfa_type = UserMFAType.NONE
        self.mfa_enabled_at = None

        self._revoke_sessions()

        self._record_event(
            UserEventType.MFA_DISABLED,
            actor_id=actor_id,
        )

    # ========================================================
    # RECORD SUCCESSFUL LOGIN
    # ========================================================

    def record_successful_login(
        self,
        *,
        actor_id: str | None = None,
    ) -> None:
        if not self.is_active or self.is_locked:
            raise ValueError("Account cannot log in")

        # Call only after the authentication service has
        # verified credentials and all required MFA factors.

        self.last_login_at = utc_now()
        self.last_activity_at = utc_now()
        self.failed_login_attempts = 0
        self.last_failed_login_at = None
        self.locked_until = None

        self._record_event(
            UserEventType.LOGIN_SUCCEEDED,
            actor_id=actor_id or self.id,
        )

    # ========================================================
    # RECORD FAILED LOGIN
    # ========================================================

    def record_failed_login(
        self,
        *,
        max_attempts: int = 5,
        lock_minutes: int = 15,
    ) -> None:
        if self.is_deleted:
            raise ValueError("User has been deleted")

        if max_attempts < 1 or lock_minutes < 1:
            raise ValueError(
                "Login limits must be positive"
            )

        self.failed_login_attempts = (
            self.failed_login_attempts or 0
        ) + 1

        self.last_failed_login_at = utc_now()

        self._record_event(
            UserEventType.LOGIN_FAILED,
            details={
                "failed_attempts": self.failed_login_attempts,
            },
        )

        if self.failed_login_attempts >= max_attempts:
            from datetime import timedelta

            self.locked_until = utc_now() + timedelta(
                minutes=lock_minutes
            )

            self._revoke_sessions()

            self._record_event(
                UserEventType.ACCOUNT_LOCKED,
                details={
                    "locked_until": iso(self.locked_until),
                },
            )

    # ========================================================
    # UNLOCK ACCOUNT
    # ========================================================

    def unlock(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        if not self.is_locked:
            raise ValueError("Account is not locked")

        self.failed_login_attempts = 0
        self.locked_until = None

        if self.status == UserStatus.LOCKED:
            self.status = UserStatus.ACTIVE

        self._record_event(
            UserEventType.ACCOUNT_UNLOCKED,
            actor_id=actor_id,
        )

    # ========================================================
    # LOGOUT
    # ========================================================

    def record_logout(
        self,
        *,
        actor_id: str | None = None,
    ) -> None:
        self.last_logout_at = utc_now()

        self._record_event(
            UserEventType.LOGOUT,
            actor_id=actor_id or self.id,
        )

    # ========================================================
    # REVOKE ALL SESSIONS
    # ========================================================

    def revoke_all_sessions(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        self._revoke_sessions()

        self._record_event(
            UserEventType.ACCESS_REVOKED,
            actor_id=actor_id,
        )

    # ========================================================
    # SUSPEND
    # ========================================================

    def suspend(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_editable()

        if self.status != UserStatus.ACTIVE:
            raise ValueError(
                "Only active users can be suspended"
            )

        self.suspension_reason = required_text(
            reason,
            "Suspension reason",
        )

        self.status = UserStatus.SUSPENDED
        self.suspended_at = utc_now()

        self._revoke_sessions()

        self._record_event(
            UserEventType.SUSPENDED,
            actor_id=actor_id,
            details={"reason": self.suspension_reason},
        )

    # ========================================================
    # REACTIVATE
    # ========================================================

    def reactivate(
        self,
        *,
        actor_id: str,
    ) -> None:
        self._ensure_editable()

        if self.status not in {
            UserStatus.SUSPENDED,
            UserStatus.INACTIVE,
            UserStatus.DEACTIVATED,
        }:
            raise ValueError(
                "User cannot be reactivated"
            )

        if not self.email_verified and not self.is_service_account:
            raise ValueError(
                "Email verification required"
            )

        self.status = UserStatus.ACTIVE
        self.suspension_reason = None
        self.force_logout = False
        self.activated_at = utc_now()

        self._record_event(
            UserEventType.REACTIVATED,
            actor_id=actor_id,
        )

    # ========================================================
    # DEACTIVATE
    # ========================================================

    def deactivate(
        self,
        *,
        actor_id: str,
        reason: str,
    ) -> None:
        self._ensure_editable()

        if self.status == UserStatus.DEACTIVATED:
            raise ValueError("User already deactivated")

        self.deactivation_reason = required_text(
            reason,
            "Deactivation reason",
        )

        self.status = UserStatus.DEACTIVATED
        self.deactivated_at = utc_now()

        self._revoke_sessions()

        self._record_event(
            UserEventType.DEACTIVATED,
            actor_id=actor_id,
            details={"reason": self.deactivation_reason},
        )

    # ========================================================
    # ARCHIVE
    # ========================================================

    def archive(
        self,
        *,
        actor_id: str,
    ) -> None:
        if self.is_deleted:
            raise ValueError("User already deleted")

        if self.status not in {
            UserStatus.DEACTIVATED,
            UserStatus.INACTIVE,
        }:
            raise ValueError(
                "User must be inactive or deactivated"
            )

        self.status = UserStatus.ARCHIVED
        self.archived_at = utc_now()

        self._revoke_sessions()

        self._record_event(
            UserEventType.ARCHIVED,
            actor_id=actor_id,
        )

    # ========================================================
    # SOFT DELETE
    # ========================================================

    def soft_delete(
        self,
        *,
        actor_id: str,
    ) -> None:
        if self.is_deleted:
            raise ValueError("User already deleted")

        if self.status not in {
            UserStatus.INVITED,
            UserStatus.ARCHIVED,
        }:
            raise ValueError(
                "Only invited or archived users can be deleted"
            )

        self.is_deleted = True
        self.deleted_at = utc_now()
        self.deleted_by = required_text(
            actor_id,
            "Actor ID",
        )

        self._revoke_sessions()

        self._record_event(
            UserEventType.SOFT_DELETED,
            actor_id=actor_id,
        )

    # ========================================================
    # SERIALIZATION
    # ========================================================

    def to_dict(
        self,
        *,
        include_private: bool = False,
        include_permissions: bool = False,
        include_events: bool = False,
    ) -> dict[str, Any]:

        data = {
            "id": self.id,
            "organization_id": self.organization_id,
            "employee_code": self.employee_code,
            "username": self.username,
            "email": self.email,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": self.full_name,
            "display_name": self.display_name,
            "avatar_url": self.avatar_url,
            "bio": self.bio,
            "status": enum_value(self.status),
            "role": enum_value(self.role),
            "user_type": enum_value(self.user_type),
            "department": self.department,
            "designation": self.designation,
            "primary_warehouse_id": (
                self.primary_warehouse_id
            ),
            "primary_store_id": self.primary_store_id,
            "email_verified": self.email_verified,
            "mfa_enabled": self.mfa_enabled,
            "language": self.language,
            "timezone_name": self.timezone_name,
            "theme": self.theme,
            "notification_preference": enum_value(
                self.notification_preference
            ),
            "ai_assistant_enabled": (
                self.ai_assistant_enabled
            ),
            "agent_execution_enabled": (
                self.agent_execution_enabled
            ),
            "is_active": self.is_active,
            "is_admin": self.is_admin,
            "is_locked": self.is_locked,
            "can_execute_ai_agents": (
                self.can_execute_ai_agents
            ),
            "created_at": iso(self.created_at),
            "updated_at": iso(self.updated_at),
            "version": self.version,
        }

        if include_permissions:
            data.update({
                "custom_roles": self.custom_roles,
                "permission_overrides": (
                    self.permission_overrides
                ),
                "access_scopes": self.access_scopes,
                "assigned_warehouse_ids": (
                    self.assigned_warehouse_ids
                ),
                "assigned_store_ids": self.assigned_store_ids,
                "assigned_region_ids": (
                    self.assigned_region_ids
                ),
                "can_approve_purchase_orders": (
                    self.can_approve_purchase_orders
                ),
                "can_approve_replenishment": (
                    self.can_approve_replenishment
                ),
                "can_approve_supplier_contracts": (
                    self.can_approve_supplier_contracts
                ),
                "can_approve_ai_actions": (
                    self.can_approve_ai_actions
                ),
                "can_manage_ai_agents": (
                    self.can_manage_ai_agents
                ),
                "can_view_financial_data": (
                    self.can_view_financial_data
                ),
                "can_export_sensitive_data": (
                    self.can_export_sensitive_data
                ),
                "allowed_agent_ids": self.allowed_agent_ids,
                "allowed_ai_tools": self.allowed_ai_tools,
                "ai_approval_required": (
                    self.ai_approval_required
                ),
            })

        if include_private:
            data.update({
                "phone_number": self.phone_number,
                "phone_verified": self.phone_verified,
                "authentication_provider": enum_value(
                    self.authentication_provider
                ),
                "password_changed_at": iso(
                    self.password_changed_at
                ),
                "password_reset_required": (
                    self.password_reset_required
                ),
                "last_login_at": iso(self.last_login_at),
                "last_logout_at": iso(self.last_logout_at),
                "last_activity_at": iso(
                    self.last_activity_at
                ),
                "failed_login_attempts": (
                    self.failed_login_attempts
                ),
                "locked_until": iso(self.locked_until),
                "session_version": self.session_version,
                "force_logout": self.force_logout,
                "manager_id": self.manager_id,
                "supplier_id": self.supplier_id,
                "ai_preferences": self.ai_preferences,
                "notification_settings": (
                    self.notification_settings
                ),
                "dashboard_preferences": (
                    self.dashboard_preferences
                ),
                "user_metadata": self.user_metadata,
                "tags": self.tags,
                "created_by": self.created_by,
                "updated_by": self.updated_by,
                "is_deleted": self.is_deleted,
                "deleted_at": iso(self.deleted_at),
            })

        if include_events:
            data["events"] = [
                event.to_dict()
                for event in self.events
            ]

        # Never serialize password_hash, credential secrets,
        # recovery codes or authentication tokens.
        return data

    def __repr__(self) -> str:
        return (
            f"<User("
            f"id={self.id!r}, "
            f"email={self.email!r}, "
            f"role={enum_value(self.role)!r}, "
            f"status={enum_value(self.status)!r}"
            f")>"
        )


# ============================================================
# USER AUDIT EVENT
# ============================================================

class UserEvent(Base):
    __tablename__ = "user_events"

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            [
                "users.organization_id",
                "users.id",
            ],
            name="fk_user_event_user",
            ondelete="CASCADE",
        ),
        Index(
            "ix_user_event_user_created",
            "user_id",
            "created_at",
        ),
        Index(
            "ix_user_event_org_type",
            "organization_id",
            "event_type",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    organization_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    user_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
    )

    event_type: Mapped[UserEventType] = mapped_column(
        enum_column(
            UserEventType,
            "user_event_type",
        ),
        nullable=False,
    )

    actor_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    details: Mapped[dict[str, Any]] = mapped_column(
        MutableDict.as_mutable(JSON),
        default=dict,
        nullable=False,
    )

    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
    )

    user_agent: Mapped[str | None] = mapped_column(
        String(500),
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

    user: Mapped[User] = relationship(
        "User",
        back_populates="events",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "user_id": self.user_id,
            "event_type": enum_value(self.event_type),
            "actor_id": self.actor_id,
            "description": self.description,
            "details": self.details,
            "created_at": iso(self.created_at),
        }

    def __repr__(self) -> str:
        return (
            f"<UserEvent("
            f"id={self.id!r}, "
            f"user_id={self.user_id!r}, "
            f"event_type={enum_value(self.event_type)!r}"
            f")>"
        )