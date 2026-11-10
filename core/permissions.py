from __future__ import annotations

"""Planned module: permissions. Implementation pending."""

"""
backend/permissions.py

Autonomous Retail Supply Chain AI 5.0

Tenant-aware role-based access control.

Python 3.10+
FastAPI / Pydantic 2

Features:
- Centralized permission registry
- Role-to-permission mapping
- Multiple roles per principal
- Tenant isolation
- Resource-level authorization
- Warehouse access restrictions
- Explicit approval gates
- AI agent tool permissions
- FastAPI dependencies
- Fail-closed authorization
- Safe authorization decisions

Security assumptions:
- Authentication occurs upstream.
- Principal data comes from verified auth.
- Tenant membership is validated.
- Resource tenant IDs come from trusted DB data.
- Feature flags are not permissions.
- Authorization is repeated at the service
  boundary, not only at the HTTP layer.
"""


from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Callable, Iterable

from fastapi import (
    Depends,
    HTTPException,
    Request,
    status,
)


# ============================================================
# ERRORS
# ============================================================

class AuthorizationError(PermissionError):
    pass


class AuthenticationRequired(
    AuthorizationError
):
    pass


class AccessDenied(
    AuthorizationError
):
    pass


# ============================================================
# ROLES
# ============================================================

class Role(str, Enum):
    ADMIN = "admin"
    WAREHOUSE_MANAGER = "warehouse_manager"
    INVENTORY_MANAGER = "inventory_manager"
    PROCUREMENT_MANAGER = "procurement_manager"
    LOGISTICS_MANAGER = "logistics_manager"
    FINANCE_MANAGER = "finance_manager"
    AI_OPERATOR = "ai_operator"
    ANALYST = "analyst"
    VIEWER = "viewer"
    SERVICE_ACCOUNT = "service_account"


# ============================================================
# PERMISSIONS
# ============================================================

class Permission(str, Enum):

    PRODUCT_READ = "product:read"
    PRODUCT_WRITE = "product:write"

    INVENTORY_READ = "inventory:read"
    INVENTORY_WRITE = "inventory:write"
    INVENTORY_TRANSFER = "inventory:transfer"

    WAREHOUSE_READ = "warehouse:read"
    WAREHOUSE_WRITE = "warehouse:write"

    SUPPLIER_READ = "supplier:read"
    SUPPLIER_WRITE = "supplier:write"

    PROCUREMENT_READ = "procurement:read"
    PROCUREMENT_WRITE = "procurement:write"
    PROCUREMENT_APPROVE = "procurement:approve"

    LOGISTICS_READ = "logistics:read"
    LOGISTICS_WRITE = "logistics:write"

    FINANCE_READ = "finance:read"
    FINANCE_WRITE = "finance:write"
    FINANCE_APPROVE = "finance:approve"

    ANALYTICS_READ = "analytics:read"
    REPORT_EXPORT = "report:export"

    RAG_QUERY = "rag:query"

    AI_AGENT_READ = "ai_agent:read"
    AI_AGENT_EXECUTE = "ai_agent:execute"
    AI_AGENT_APPROVE = "ai_agent:approve"
    AI_AGENT_CONFIGURE = "ai_agent:configure"

    INTEGRATION_READ = "integration:read"
    INTEGRATION_WRITE = "integration:write"

    NOTIFICATION_READ = "notification:read"
    NOTIFICATION_SEND = "notification:send"

    INCIDENT_READ = "incident:read"
    INCIDENT_WRITE = "incident:write"

    AUDIT_READ = "audit:read"

    USER_READ = "user:read"
    USER_MANAGE = "user:manage"

    ROLE_MANAGE = "role:manage"
    FEATURE_FLAG_MANAGE = "feature_flag:manage"

    SYSTEM_CONFIGURE = "system:configure"


# ============================================================
# ROLE PERMISSIONS
# ============================================================

ROLE_PERMISSIONS: dict[
    Role, frozenset[Permission]
] = {

    Role.ADMIN: frozenset(Permission),

    Role.WAREHOUSE_MANAGER: frozenset({
        Permission.PRODUCT_READ,
        Permission.INVENTORY_READ,
        Permission.INVENTORY_WRITE,
        Permission.INVENTORY_TRANSFER,
        Permission.WAREHOUSE_READ,
        Permission.WAREHOUSE_WRITE,
        Permission.LOGISTICS_READ,
        Permission.ANALYTICS_READ,
        Permission.INCIDENT_READ,
        Permission.INCIDENT_WRITE,
    }),

    Role.INVENTORY_MANAGER: frozenset({
        Permission.PRODUCT_READ,
        Permission.INVENTORY_READ,
        Permission.INVENTORY_WRITE,
        Permission.INVENTORY_TRANSFER,
        Permission.WAREHOUSE_READ,
        Permission.SUPPLIER_READ,
        Permission.PROCUREMENT_READ,
        Permission.ANALYTICS_READ,
    }),

    Role.PROCUREMENT_MANAGER: frozenset({
        Permission.PRODUCT_READ,
        Permission.INVENTORY_READ,
        Permission.SUPPLIER_READ,
        Permission.SUPPLIER_WRITE,
        Permission.PROCUREMENT_READ,
        Permission.PROCUREMENT_WRITE,
        Permission.PROCUREMENT_APPROVE,
        Permission.ANALYTICS_READ,
    }),

    Role.LOGISTICS_MANAGER: frozenset({
        Permission.INVENTORY_READ,
        Permission.WAREHOUSE_READ,
        Permission.LOGISTICS_READ,
        Permission.LOGISTICS_WRITE,
        Permission.SUPPLIER_READ,
        Permission.ANALYTICS_READ,
    }),

    Role.FINANCE_MANAGER: frozenset({
        Permission.FINANCE_READ,
        Permission.FINANCE_WRITE,
        Permission.FINANCE_APPROVE,
        Permission.PROCUREMENT_READ,
        Permission.ANALYTICS_READ,
        Permission.REPORT_EXPORT,
    }),

    Role.AI_OPERATOR: frozenset({
        Permission.AI_AGENT_READ,
        Permission.AI_AGENT_EXECUTE,
        Permission.RAG_QUERY,
        Permission.ANALYTICS_READ,
        Permission.INVENTORY_READ,
        Permission.PRODUCT_READ,
    }),

    Role.ANALYST: frozenset({
        Permission.PRODUCT_READ,
        Permission.INVENTORY_READ,
        Permission.WAREHOUSE_READ,
        Permission.SUPPLIER_READ,
        Permission.PROCUREMENT_READ,
        Permission.LOGISTICS_READ,
        Permission.ANALYTICS_READ,
        Permission.RAG_QUERY,
    }),

    Role.VIEWER: frozenset({
        Permission.PRODUCT_READ,
        Permission.INVENTORY_READ,
        Permission.ANALYTICS_READ,
    }),

    # Service accounts must receive narrowly
    # scoped permissions through an external,
    # authenticated service identity policy.
    Role.SERVICE_ACCOUNT: frozenset(),
}


# ============================================================
# PRINCIPAL
# ============================================================

@dataclass(frozen=True)
class Principal:
    """
    Verified application identity.

    Must be constructed by trusted
    authentication code only.
    """

    principal_id: str
    tenant_id: str

    roles: frozenset[Role]

    active: bool = True

    allowed_warehouse_ids: (
        frozenset[str] | None
    ) = None

    explicit_permissions: frozenset[
        Permission
    ] = field(
        default_factory=frozenset
    )

    def __post_init__(self) -> None:

        if not self.principal_id.strip():
            raise ValueError(
                "principal_id is required"
            )

        if not self.tenant_id.strip():
            raise ValueError(
                "tenant_id is required"
            )

        if not self.roles:
            raise ValueError(
                "At least one role is required"
            )


# ============================================================
# RESOURCE CONTEXT
# ============================================================

@dataclass(frozen=True)
class ResourceContext:

    tenant_id: str

    warehouse_id: str | None = None

    owner_id: str | None = None

    requires_approval: bool = False

    approved: bool = False

    def __post_init__(self) -> None:

        if not self.tenant_id.strip():
            raise ValueError(
                "Resource tenant is required"
            )


# ============================================================
# AUTHORIZATION DECISION
# ============================================================

@dataclass(frozen=True)
class AuthorizationDecision:

    allowed: bool

    reason: str

    permission: Permission


# ============================================================
# PERMISSION ENGINE
# ============================================================

class PermissionEngine:

    def effective_permissions(
        self,
        principal: Principal,
    ) -> frozenset[Permission]:

        if not principal.active:
            return frozenset()

        granted = set(
            principal.explicit_permissions
        )

        for role in principal.roles:

            granted.update(
                ROLE_PERMISSIONS.get(
                    role,
                    frozenset(),
                )
            )

        return frozenset(granted)

    def evaluate(
        self,
        principal: Principal | None,
        permission: Permission,
        *,
        resource: ResourceContext | None = None,
    ) -> AuthorizationDecision:

        if principal is None:

            return AuthorizationDecision(
                allowed=False,
                reason="unauthenticated",
                permission=permission,
            )

        if not principal.active:

            return AuthorizationDecision(
                allowed=False,
                reason="principal_inactive",
                permission=permission,
            )

        if (
            resource is not None
            and principal.tenant_id
            != resource.tenant_id
        ):

            return AuthorizationDecision(
                allowed=False,
                reason="tenant_mismatch",
                permission=permission,
            )

        effective = (
            self.effective_permissions(
                principal
            )
        )

        if permission not in effective:

            return AuthorizationDecision(
                allowed=False,
                reason="permission_missing",
                permission=permission,
            )

        if resource is not None:

            if resource.warehouse_id is not None:

                allowed_warehouses = (
                    principal.allowed_warehouse_ids
                )

                if (
                    allowed_warehouses is not None
                    and resource.warehouse_id
                    not in allowed_warehouses
                ):

                    return AuthorizationDecision(
                        allowed=False,
                        reason="warehouse_restricted",
                        permission=permission,
                    )

            if (
                resource.requires_approval
                and not resource.approved
            ):

                return AuthorizationDecision(
                    allowed=False,
                    reason="approval_required",
                    permission=permission,
                )

        return AuthorizationDecision(
            allowed=True,
            reason="allowed",
            permission=permission,
        )

    def require(
        self,
        principal: Principal | None,
        permission: Permission,
        *,
        resource: ResourceContext | None = None,
    ) -> None:

        decision = self.evaluate(
            principal,
            permission,
            resource=resource,
        )

        if not decision.allowed:

            raise AccessDenied(
                decision.reason
            )

    def require_all(
        self,
        principal: Principal | None,
        permissions: Iterable[Permission],
        *,
        resource: ResourceContext | None = None,
    ) -> None:

        for permission in permissions:

            self.require(
                principal,
                permission,
                resource=resource,
            )

    def require_any(
        self,
        principal: Principal | None,
        permissions: Iterable[Permission],
        *,
        resource: ResourceContext | None = None,
    ) -> None:

        requested = tuple(permissions)

        if not requested:
            raise AccessDenied(
                "No permissions requested"
            )

        if not any(
            self.evaluate(
                principal,
                permission,
                resource=resource,
            ).allowed
            for permission in requested
        ):
            raise AccessDenied(
                "No matching permission"
            )


permission_engine = PermissionEngine()


# ============================================================
# TRUSTED AUTHENTICATION INTEGRATION
# ============================================================

def set_authenticated_principal(
    request: Request,
    principal: Principal,
) -> None:
    """
    Call only from trusted authentication
    middleware after verifying credentials,
    tenant membership, and account status.

    This helper does NOT authenticate.
    """

    request.state.principal = principal

    request.state.tenant_id = (
        principal.tenant_id
    )


def get_current_principal(
    request: Request,
) -> Principal:

    principal = getattr(
        request.state,
        "principal",
        None,
    )

    if not isinstance(
        principal,
        Principal,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    if not principal.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account inactive",
        )

    return principal


CurrentPrincipal = Annotated[
    Principal,
    Depends(get_current_principal),
]


# ============================================================
# FASTAPI PERMISSION DEPENDENCY
# ============================================================

def require_permission(
    permission: Permission,
) -> Callable:

    def dependency(
        principal: CurrentPrincipal,
    ) -> Principal:

        decision = permission_engine.evaluate(
            principal,
            permission,
        )

        if not decision.allowed:

            raise HTTPException(
                status_code=403,
                detail="Permission denied",
            )

        return principal

    return dependency


def require_role(
    role: Role,
) -> Callable:

    def dependency(
        principal: CurrentPrincipal,
    ) -> Principal:

        if role not in principal.roles:

            raise HTTPException(
                status_code=403,
                detail="Required role missing",
            )

        return principal

    return dependency


# ============================================================
# AI AGENT AUTHORIZATION
# ============================================================

class AgentAction(str, Enum):

    READ_DATA = "read_data"

    EXECUTE_ANALYSIS = "execute_analysis"

    CREATE_PURCHASE_ORDER = (
        "create_purchase_order"
    )

    TRANSFER_INVENTORY = (
        "transfer_inventory"
    )

    UPDATE_PRICING = "update_pricing"

    SEND_NOTIFICATION = (
        "send_notification"
    )

    APPROVE_PURCHASE_ORDER = (
        "approve_purchase_order"
    )


AGENT_ACTION_PERMISSIONS: dict[
    AgentAction, Permission
] = {

    AgentAction.READ_DATA: (
        Permission.AI_AGENT_READ
    ),

    AgentAction.EXECUTE_ANALYSIS: (
        Permission.AI_AGENT_EXECUTE
    ),

    AgentAction.CREATE_PURCHASE_ORDER: (
        Permission.PROCUREMENT_WRITE
    ),

    AgentAction.TRANSFER_INVENTORY: (
        Permission.INVENTORY_TRANSFER
    ),

    AgentAction.UPDATE_PRICING: (
        Permission.PRODUCT_WRITE
    ),

    AgentAction.SEND_NOTIFICATION: (
        Permission.NOTIFICATION_SEND
    ),

    AgentAction.APPROVE_PURCHASE_ORDER: (
        Permission.PROCUREMENT_APPROVE
    ),
}


def authorize_agent_action(
    principal: Principal,
    action: AgentAction,
    *,
    resource: ResourceContext,
) -> None:
    """
    Authorization for AI-initiated actions.

    The invoking user and service account
    must both be authorized by the
    surrounding agent execution service.

    This function checks only the
    supplied principal.
    """

    permission = (
        AGENT_ACTION_PERMISSIONS[action]
    )

    permission_engine.require(
        principal,
        Permission.AI_AGENT_EXECUTE,
        resource=resource,
    )

    permission_engine.require(
        principal,
        permission,
        resource=resource,
    )

    if action in {
        AgentAction.CREATE_PURCHASE_ORDER,
        AgentAction.TRANSFER_INVENTORY,
        AgentAction.UPDATE_PRICING,
        AgentAction.APPROVE_PURCHASE_ORDER,
    }:

        if not resource.approved:
            raise AccessDenied(
                "Human approval required"
            )


# ============================================================
# AUTHORIZATION UTILITIES
# ============================================================

def has_permission(
    principal: Principal,
    permission: Permission,
) -> bool:

    return permission_engine.evaluate(
        principal,
        permission,
    ).allowed


def has_role(
    principal: Principal,
    role: Role,
) -> bool:

    return (
        principal.active
        and role in principal.roles
    )


def require_same_tenant(
    principal: Principal,
    resource_tenant_id: str,
) -> None:

    if (
        not principal.active
        or principal.tenant_id
        != resource_tenant_id
    ):

        raise AccessDenied(
            "Tenant access denied"
        )
