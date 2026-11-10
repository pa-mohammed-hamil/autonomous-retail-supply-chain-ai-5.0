from __future__ import annotations

"""Planned module: dependencies. Implementation pending."""
# backend/dependencies.py
"""
Autonomous Retail Supply Chain Optimization & Agentic AI
========================================================

Centralized FastAPI dependencies.

Features:
- Async SQLAlchemy database sessions
- Redis client access
- JWT bearer authentication
- Current user resolution
- Multi-tenant organization isolation
- Role-based access control (RBAC)
- Permission-based authorization
- API key authentication
- Human approval requirements
- AI agent authorization
- Feature flags
- Pagination and sorting
- Request context
- Idempotency key validation
- Service availability checks
- Redis-backed rate limiting
- Audit context
- Optional service dependencies

Required packages:
    pip install fastapi sqlalchemy pyjwt redis pydantic

Environment variables:
    JWT_SECRET_KEY=<secure-random-secret>
    JWT_ALGORITHM=HS256
    JWT_ISSUER=retail-supply-chain
    JWT_AUDIENCE=retail-supply-chain-api
    API_KEY_PEPPER=<secure-random-secret>

Security notes:
- Configure JWT_SECRET_KEY and API_KEY_PEPPER in production.
- Never trust X-Organization-ID without authorization.
- Never accept AI agent actions solely because a request
  contains an agent identifier.
- Never allow an agent to approve its own actions.
- Keep authorization enforcement in the service layer too.
- Use TLS and an API gateway in production.
- Authentication identity must be resolved from a trusted
  identity provider or database, not from user-supplied claims
  alone.
"""


import hashlib
import hmac
import logging
import os
import re
import secrets
import uuid

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import (
    Annotated,
    Any,
    AsyncIterator,
    Callable,
    Mapping,
    Protocol,
    Sequence,
)

import jwt

from fastapi import (
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Security,
    status,
)
from fastapi.security import (
    APIKeyHeader,
    HTTPAuthorizationCredentials,
    HTTPBearer,
)
from jwt import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger("retail_supply_chain.dependencies")


# ============================================================
# CONSTANTS
# ============================================================

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

MAX_IDEMPOTENCY_KEY_LENGTH = 128

MAX_REQUEST_ID_LENGTH = 128

MAX_SORT_FIELDS = 5

DEFAULT_RATE_LIMIT = 100
DEFAULT_RATE_WINDOW_SECONDS = 60

JWT_ALGORITHM = os.getenv(
    "JWT_ALGORITHM",
    "HS256",
)

JWT_ISSUER = os.getenv(
    "JWT_ISSUER",
    "retail-supply-chain",
)

JWT_AUDIENCE = os.getenv(
    "JWT_AUDIENCE",
    "retail-supply-chain-api",
)

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")

API_KEY_PEPPER = os.getenv("API_KEY_PEPPER")

AUTH_CLOCK_SKEW_SECONDS = 30

IDENTIFIER_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
)

IDEMPOTENCY_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
)


# ============================================================
# ENUMS
# ============================================================

class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    ORGANIZATION_ADMIN = "organization_admin"
    OPERATIONS_MANAGER = "operations_manager"
    WAREHOUSE_MANAGER = "warehouse_manager"
    INVENTORY_MANAGER = "inventory_manager"
    PROCUREMENT_MANAGER = "procurement_manager"
    SUPPLIER_MANAGER = "supplier_manager"
    LOGISTICS_MANAGER = "logistics_manager"
    FLEET_MANAGER = "fleet_manager"
    FINANCE_MANAGER = "finance_manager"
    DATA_ANALYST = "data_analyst"
    AI_ENGINEER = "ai_engineer"
    ML_ENGINEER = "ml_engineer"
    AI_AGENT = "ai_agent"
    AUDITOR = "auditor"
    VIEWER = "viewer"


class Permission(str, Enum):
    ORGANIZATION_READ = "organization:read"
    ORGANIZATION_WRITE = "organization:write"

    USER_READ = "user:read"
    USER_WRITE = "user:write"

    PRODUCT_READ = "product:read"
    PRODUCT_WRITE = "product:write"

    INVENTORY_READ = "inventory:read"
    INVENTORY_WRITE = "inventory:write"
    INVENTORY_ADJUST = "inventory:adjust"

    WAREHOUSE_READ = "warehouse:read"
    WAREHOUSE_WRITE = "warehouse:write"

    SUPPLIER_READ = "supplier:read"
    SUPPLIER_WRITE = "supplier:write"

    PROCUREMENT_READ = "procurement:read"
    PROCUREMENT_WRITE = "procurement:write"
    PROCUREMENT_APPROVE = "procurement:approve"

    DEMAND_READ = "demand:read"
    DEMAND_FORECAST = "demand:forecast"

    REPLENISHMENT_READ = "replenishment:read"
    REPLENISHMENT_WRITE = "replenishment:write"
    REPLENISHMENT_APPROVE = "replenishment:approve"

    FULFILLMENT_READ = "fulfillment:read"
    FULFILLMENT_WRITE = "fulfillment:write"

    LOGISTICS_READ = "logistics:read"
    LOGISTICS_WRITE = "logistics:write"

    FLEET_READ = "fleet:read"
    FLEET_WRITE = "fleet:write"

    FINANCE_READ = "finance:read"
    FINANCE_WRITE = "finance:write"

    ANALYTICS_READ = "analytics:read"

    AI_AGENT_READ = "ai_agent:read"
    AI_AGENT_EXECUTE = "ai_agent:execute"
    AI_AGENT_MANAGE = "ai_agent:manage"

    RAG_QUERY = "rag:query"
    RAG_MANAGE = "rag:manage"

    MODEL_READ = "model:read"
    MODEL_TRAIN = "model:train"
    MODEL_DEPLOY = "model:deploy"

    APPROVAL_READ = "approval:read"
    APPROVAL_DECIDE = "approval:decide"

    AUDIT_READ = "audit:read"

    INTEGRATION_READ = "integration:read"
    INTEGRATION_MANAGE = "integration:manage"

    NOTIFICATION_READ = "notification:read"
    NOTIFICATION_SEND = "notification:send"


class FeatureFlag(str, Enum):
    AI_AGENTS = "ai_agents"
    RAG = "rag"
    MLOPS = "mlops"
    LLMOPS = "llmops"
    DEMAND_FORECASTING = "demand_forecasting"
    SUPPLIER_RISK = "supplier_risk"
    REPLENISHMENT = "replenishment"
    DIGITAL_TWIN = "digital_twin"
    COMPUTER_VISION = "computer_vision"
    ROBOTICS = "robotics"
    ROUTE_OPTIMIZATION = "route_optimization"
    FINANCIAL_ANALYTICS = "financial_analytics"


# ============================================================
# ROLE PERMISSIONS
# ============================================================

ROLE_PERMISSIONS: dict[UserRole, frozenset[Permission]] = {
    UserRole.SUPER_ADMIN: frozenset(Permission),

    UserRole.ORGANIZATION_ADMIN: frozenset(Permission),

    UserRole.OPERATIONS_MANAGER: frozenset({
        Permission.ORGANIZATION_READ,
        Permission.PRODUCT_READ,
        Permission.INVENTORY_READ,
        Permission.INVENTORY_WRITE,
        Permission.WAREHOUSE_READ,
        Permission.WAREHOUSE_WRITE,
        Permission.SUPPLIER_READ,
        Permission.PROCUREMENT_READ,
        Permission.DEMAND_READ,
        Permission.DEMAND_FORECAST,
        Permission.REPLENISHMENT_READ,
        Permission.REPLENISHMENT_WRITE,
        Permission.FULFILLMENT_READ,
        Permission.FULFILLMENT_WRITE,
        Permission.LOGISTICS_READ,
        Permission.LOGISTICS_WRITE,
        Permission.ANALYTICS_READ,
        Permission.APPROVAL_READ,
        Permission.NOTIFICATION_READ,
    }),

    UserRole.WAREHOUSE_MANAGER: frozenset({
        Permission.WAREHOUSE_READ,
        Permission.WAREHOUSE_WRITE,
        Permission.INVENTORY_READ,
        Permission.INVENTORY_WRITE,
        Permission.FULFILLMENT_READ,
        Permission.FULFILLMENT_WRITE,
        Permission.ANALYTICS_READ,
        Permission.NOTIFICATION_READ,
    }),

    UserRole.INVENTORY_MANAGER: frozenset({
        Permission.PRODUCT_READ,
        Permission.INVENTORY_READ,
        Permission.INVENTORY_WRITE,
        Permission.INVENTORY_ADJUST,
        Permission.WAREHOUSE_READ,
        Permission.REPLENISHMENT_READ,
        Permission.REPLENISHMENT_WRITE,
        Permission.ANALYTICS_READ,
    }),

    UserRole.PROCUREMENT_MANAGER: frozenset({
        Permission.SUPPLIER_READ,
        Permission.SUPPLIER_WRITE,
        Permission.PROCUREMENT_READ,
        Permission.PROCUREMENT_WRITE,
        Permission.PROCUREMENT_APPROVE,
        Permission.REPLENISHMENT_READ,
        Permission.REPLENISHMENT_WRITE,
        Permission.APPROVAL_READ,
        Permission.ANALYTICS_READ,
    }),

    UserRole.SUPPLIER_MANAGER: frozenset({
        Permission.SUPPLIER_READ,
        Permission.SUPPLIER_WRITE,
        Permission.PROCUREMENT_READ,
        Permission.ANALYTICS_READ,
    }),

    UserRole.LOGISTICS_MANAGER: frozenset({
        Permission.LOGISTICS_READ,
        Permission.LOGISTICS_WRITE,
        Permission.FLEET_READ,
        Permission.FULFILLMENT_READ,
        Permission.ANALYTICS_READ,
    }),

    UserRole.FLEET_MANAGER: frozenset({
        Permission.FLEET_READ,
        Permission.FLEET_WRITE,
        Permission.LOGISTICS_READ,
        Permission.ANALYTICS_READ,
    }),

    UserRole.FINANCE_MANAGER: frozenset({
        Permission.FINANCE_READ,
        Permission.FINANCE_WRITE,
        Permission.PROCUREMENT_READ,
        Permission.SUPPLIER_READ,
        Permission.ANALYTICS_READ,
    }),

    UserRole.DATA_ANALYST: frozenset({
        Permission.PRODUCT_READ,
        Permission.INVENTORY_READ,
        Permission.WAREHOUSE_READ,
        Permission.SUPPLIER_READ,
        Permission.DEMAND_READ,
        Permission.LOGISTICS_READ,
        Permission.ANALYTICS_READ,
        Permission.MODEL_READ,
    }),

    UserRole.AI_ENGINEER: frozenset({
        Permission.AI_AGENT_READ,
        Permission.AI_AGENT_MANAGE,
        Permission.RAG_QUERY,
        Permission.RAG_MANAGE,
        Permission.MODEL_READ,
        Permission.MODEL_TRAIN,
        Permission.ANALYTICS_READ,
    }),

    UserRole.ML_ENGINEER: frozenset({
        Permission.MODEL_READ,
        Permission.MODEL_TRAIN,
        Permission.MODEL_DEPLOY,
        Permission.DEMAND_READ,
        Permission.DEMAND_FORECAST,
        Permission.ANALYTICS_READ,
    }),

    UserRole.AI_AGENT: frozenset({
        Permission.AI_AGENT_READ,
        Permission.RAG_QUERY,
        Permission.PRODUCT_READ,
        Permission.INVENTORY_READ,
        Permission.WAREHOUSE_READ,
        Permission.SUPPLIER_READ,
        Permission.DEMAND_READ,
        Permission.REPLENISHMENT_READ,
        Permission.LOGISTICS_READ,
        Permission.ANALYTICS_READ,
    }),

    UserRole.AUDITOR: frozenset({
        Permission.ORGANIZATION_READ,
        Permission.INVENTORY_READ,
        Permission.WAREHOUSE_READ,
        Permission.SUPPLIER_READ,
        Permission.PROCUREMENT_READ,
        Permission.FINANCE_READ,
        Permission.APPROVAL_READ,
        Permission.AUDIT_READ,
    }),

    UserRole.VIEWER: frozenset({
        Permission.PRODUCT_READ,
        Permission.INVENTORY_READ,
        Permission.WAREHOUSE_READ,
        Permission.ANALYTICS_READ,
    }),
}


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    organization_id: str
    roles: frozenset[UserRole]
    permissions: frozenset[Permission]
    is_active: bool = True
    is_service_account: bool = False
    is_ai_agent: bool = False
    token_id: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class OrganizationContext:
    organization_id: str
    user_id: str
    roles: frozenset[UserRole]
    permissions: frozenset[Permission]


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    user_id: str
    organization_id: str
    roles: frozenset[UserRole]
    permissions: frozenset[Permission]
    timestamp: datetime
    idempotency_key: str | None = None
    client_ip: str | None = None


@dataclass(frozen=True)
class PaginationParams:
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


@dataclass(frozen=True)
class SortField:
    field: str
    descending: bool = False


@dataclass(frozen=True)
class SortParams:
    fields: tuple[SortField, ...] = field(
        default_factory=tuple
    )


@dataclass(frozen=True)
class ApprovalContext:
    actor_id: str
    organization_id: str
    can_approve: bool
    is_ai_agent: bool


@dataclass(frozen=True)
class AgentExecutionContext:
    actor_id: str
    organization_id: str
    agent_id: str
    permissions: frozenset[Permission]
    requires_human_approval: bool = True


# ============================================================
# AUTHENTICATION PROVIDER CONTRACT
# ============================================================

class IdentityProvider(Protocol):
    """
    Implement this protocol with your database-backed
    identity service.

    Security requirements:
    - Look up the user by verified token subject.
    - Check active/disabled/deleted account status.
    - Resolve active organization membership.
    - Resolve roles from trusted database records.
    - Resolve direct permissions from trusted records.
    - Check token revocation and session validity.
    - Never trust role or permission claims alone.
    """

    async def resolve_user(
        self,
        *,
        subject: str,
        organization_id: str,
        token_id: str | None,
        claims: Mapping[str, Any],
    ) -> AuthenticatedUser | None:
        ...

    async def resolve_api_key(
        self,
        *,
        key_hash: str,
    ) -> AuthenticatedUser | None:
        ...


def get_identity_provider(
    request: Request,
) -> IdentityProvider:
    provider = getattr(
        request.app.state,
        "identity_provider",
        None,
    )

    if provider is None:
        raise HTTPException(
            status_code=503,
            detail="Identity provider is not configured",
        )

    return provider


# ============================================================
# SECURITY SCHEMES
# ============================================================

bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="BearerAuth",
    description="JWT bearer access token",
)

api_key_scheme = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    scheme_name="ApiKeyAuth",
)


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def unauthorized(
    message: str = "Authentication required",
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=message,
        headers={"WWW-Authenticate": "Bearer"},
    )


def forbidden(
    message: str = "Access denied",
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=message,
    )


def validate_identifier(
    value: str,
    name: str,
) -> str:
    if (
        not isinstance(value, str)
        or not IDENTIFIER_PATTERN.fullmatch(value)
    ):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {name}",
        )

    return value


def normalize_roles(
    roles: Sequence[str | UserRole],
) -> frozenset[UserRole]:
    result: set[UserRole] = set()

    for role in roles:
        try:
            result.add(UserRole(role))
        except ValueError as exc:
            raise ValueError(
                f"Unknown user role: {role}"
            ) from exc

    return frozenset(result)


def normalize_permissions(
    permissions: Sequence[str | Permission],
) -> frozenset[Permission]:
    result: set[Permission] = set()

    for permission in permissions:
        try:
            result.add(Permission(permission))
        except ValueError as exc:
            raise ValueError(
                f"Unknown permission: {permission}"
            ) from exc

    return frozenset(result)


def resolve_role_permissions(
    roles: frozenset[UserRole],
) -> frozenset[Permission]:
    permissions: set[Permission] = set()

    for role in roles:
        permissions.update(
            ROLE_PERMISSIONS.get(role, frozenset())
        )

    return frozenset(permissions)


def effective_permissions(
    user: AuthenticatedUser,
) -> frozenset[Permission]:
    return frozenset(
        set(user.permissions)
        | set(resolve_role_permissions(user.roles))
    )


def ensure_active_user(
    user: AuthenticatedUser,
) -> AuthenticatedUser:
    if not user.is_active:
        raise forbidden("User account is inactive")

    return user


# ============================================================
# JWT VALIDATION
# ============================================================

def decode_access_token(
    token: str,
) -> dict[str, Any]:
    if not JWT_SECRET_KEY:
        logger.error(
            "JWT_SECRET_KEY is not configured"
        )
        raise HTTPException(
            status_code=503,
            detail="Authentication service unavailable",
        )

    if not token or len(token) > 8192:
        raise unauthorized("Invalid access token")

    try:
        claims = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            audience=JWT_AUDIENCE,
            leeway=AUTH_CLOCK_SKEW_SECONDS,
            options={
                "require": [
                    "sub",
                    "exp",
                    "iat",
                    "iss",
                    "aud",
                ],
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_nbf": True,
            },
        )

    except InvalidTokenError as exc:
        raise unauthorized(
            "Invalid or expired access token"
        ) from exc

    if not isinstance(claims, dict):
        raise unauthorized("Invalid token claims")

    subject = claims.get("sub")
    organization_id = claims.get("organization_id")

    if not isinstance(subject, str) or not subject:
        raise unauthorized("Invalid token subject")

    if (
        not isinstance(organization_id, str)
        or not organization_id
    ):
        raise unauthorized(
            "Token does not contain an organization"
        )

    return claims


# ============================================================
# CURRENT USER
# ============================================================

async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_scheme),
    ],
    identity_provider: Annotated[
        IdentityProvider,
        Depends(get_identity_provider),
    ],
) -> AuthenticatedUser:

    if credentials is None:
        raise unauthorized()

    if credentials.scheme.lower() != "bearer":
        raise unauthorized(
            "Bearer authentication required"
        )

    claims = decode_access_token(
        credentials.credentials
    )

    subject = validate_identifier(
        claims["sub"],
        "token subject",
    )

    organization_id = validate_identifier(
        claims["organization_id"],
        "organization ID",
    )

    token_id = claims.get("jti")

    if token_id is not None:
        token_id = validate_identifier(
            token_id,
            "token ID",
        )

    try:
        user = await identity_provider.resolve_user(
            subject=subject,
            organization_id=organization_id,
            token_id=token_id,
            claims=claims,
        )

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Identity provider lookup failed"
        )
        raise HTTPException(
            status_code=503,
            detail="Identity service unavailable",
        ) from exc

    if user is None:
        raise unauthorized(
            "User or organization membership not found"
        )

    if user.id != subject:
        raise unauthorized(
            "Token identity does not match user"
        )

    if user.organization_id != organization_id:
        raise unauthorized(
            "Token organization does not match membership"
        )

    return ensure_active_user(user)


CurrentUser = Annotated[
    AuthenticatedUser,
    Depends(get_current_user),
]


# ============================================================
# OPTIONAL CURRENT USER
# ============================================================

async def get_optional_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_scheme),
    ],
    identity_provider: Annotated[
        IdentityProvider,
        Depends(get_identity_provider),
    ],
) -> AuthenticatedUser | None:

    if credentials is None:
        return None

    return await get_current_user(
        credentials=credentials,
        identity_provider=identity_provider,
    )


OptionalCurrentUser = Annotated[
    AuthenticatedUser | None,
    Depends(get_optional_current_user),
]


# ============================================================
# API KEY AUTHENTICATION
# ============================================================

def hash_api_key(api_key: str) -> str:
    if not API_KEY_PEPPER:
        raise HTTPException(
            status_code=503,
            detail="API key authentication unavailable",
        )

    return hmac.new(
        API_KEY_PEPPER.encode("utf-8"),
        api_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


async def get_api_key_user(
    api_key: Annotated[
        str | None,
        Security(api_key_scheme),
    ],
    identity_provider: Annotated[
        IdentityProvider,
        Depends(get_identity_provider),
    ],
) -> AuthenticatedUser:

    if not api_key:
        raise unauthorized("API key required")

    if len(api_key) < 24 or len(api_key) > 512:
        raise unauthorized("Invalid API key")

    key_hash = hash_api_key(api_key)

    try:
        user = await identity_provider.resolve_api_key(
            key_hash=key_hash,
        )

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception("API key lookup failed")
        raise HTTPException(
            status_code=503,
            detail="API key service unavailable",
        ) from exc

    if user is None:
        raise unauthorized("Invalid API key")

    if not user.is_service_account:
        raise forbidden(
            "API key must belong to a service account"
        )

    return ensure_active_user(user)


APIKeyUser = Annotated[
    AuthenticatedUser,
    Depends(get_api_key_user),
]


# ============================================================
# DATABASE DEPENDENCY
# ============================================================

async def get_db(
    request: Request,
) -> AsyncIterator[AsyncSession]:

    session_factory = getattr(
        request.app.state,
        "db_session_factory",
        None,
    )

    if session_factory is None:
        raise HTTPException(
            status_code=503,
            detail="Database service unavailable",
        )

    async with session_factory() as session:
        try:
            yield session

        except Exception:
            await session.rollback()
            raise


DatabaseSession = Annotated[
    AsyncSession,
    Depends(get_db),
]


# ============================================================
# REDIS DEPENDENCY
# ============================================================

async def get_redis(
    request: Request,
) -> Any:
    client = getattr(
        request.app.state,
        "redis",
        None,
    )

    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Redis service unavailable",
        )

    return client


RedisClient = Annotated[
    Any,
    Depends(get_redis),
]


# ============================================================
# ORGANIZATION CONTEXT
# ============================================================

async def get_organization_context(
    user: CurrentUser,
    x_organization_id: Annotated[
        str | None,
        Header(alias="X-Organization-ID"),
    ] = None,
) -> OrganizationContext:

    organization_id = user.organization_id

    if x_organization_id is not None:
        requested_organization = validate_identifier(
            x_organization_id,
            "organization ID",
        )

        # A super admin must still use a separately
        # verified organization membership or an
        # explicit audited impersonation workflow.
        if requested_organization != organization_id:
            raise forbidden(
                "Organization context does not match "
                "authenticated membership"
            )

    return OrganizationContext(
        organization_id=organization_id,
        user_id=user.id,
        roles=user.roles,
        permissions=effective_permissions(user),
    )


Organization = Annotated[
    OrganizationContext,
    Depends(get_organization_context),
]


# ============================================================
# ROLE-BASED ACCESS CONTROL
# ============================================================

def require_roles(
    *allowed_roles: UserRole,
) -> Callable[..., Any]:

    if not allowed_roles:
        raise ValueError(
            "At least one role must be specified"
        )

    allowed = frozenset(allowed_roles)

    async def dependency(
        user: CurrentUser,
    ) -> AuthenticatedUser:

        if not user.roles.intersection(allowed):
            raise forbidden(
                "Required role: "
                + ", ".join(
                    sorted(role.value for role in allowed)
                )
            )

        return user

    return dependency


def require_all_roles(
    *required_roles: UserRole,
) -> Callable[..., Any]:

    if not required_roles:
        raise ValueError(
            "At least one role must be specified"
        )

    required = frozenset(required_roles)

    async def dependency(
        user: CurrentUser,
    ) -> AuthenticatedUser:

        if not required.issubset(user.roles):
            raise forbidden(
                "Insufficient role privileges"
            )

        return user

    return dependency


# ============================================================
# PERMISSION-BASED AUTHORIZATION
# ============================================================

def require_permissions(
    *required_permissions: Permission,
) -> Callable[..., Any]:

    if not required_permissions:
        raise ValueError(
            "At least one permission must be specified"
        )

    required = frozenset(required_permissions)

    async def dependency(
        user: CurrentUser,
    ) -> AuthenticatedUser:

        granted = effective_permissions(user)

        if not required.issubset(granted):
            missing = required - granted

            raise forbidden(
                "Missing permissions: "
                + ", ".join(
                    sorted(
                        permission.value
                        for permission in missing
                    )
                )
            )

        return user

    return dependency


def require_any_permission(
    *allowed_permissions: Permission,
) -> Callable[..., Any]:

    if not allowed_permissions:
        raise ValueError(
            "At least one permission must be specified"
        )

    allowed = frozenset(allowed_permissions)

    async def dependency(
        user: CurrentUser,
    ) -> AuthenticatedUser:

        granted = effective_permissions(user)

        if not granted.intersection(allowed):
            raise forbidden(
                "Insufficient permissions"
            )

        return user

    return dependency


# ============================================================
# COMMON ROLE DEPENDENCIES
# ============================================================

AdminUser = Annotated[
    AuthenticatedUser,
    Depends(
        require_roles(
            UserRole.SUPER_ADMIN,
            UserRole.ORGANIZATION_ADMIN,
        )
    ),
]

WarehouseManager = Annotated[
    AuthenticatedUser,
    Depends(
        require_roles(
            UserRole.SUPER_ADMIN,
            UserRole.ORGANIZATION_ADMIN,
            UserRole.WAREHOUSE_MANAGER,
            UserRole.OPERATIONS_MANAGER,
        )
    ),
]

InventoryManager = Annotated[
    AuthenticatedUser,
    Depends(
        require_roles(
            UserRole.SUPER_ADMIN,
            UserRole.ORGANIZATION_ADMIN,
            UserRole.INVENTORY_MANAGER,
            UserRole.WAREHOUSE_MANAGER,
        )
    ),
]

ProcurementManager = Annotated[
    AuthenticatedUser,
    Depends(
        require_roles(
            UserRole.SUPER_ADMIN,
            UserRole.ORGANIZATION_ADMIN,
            UserRole.PROCUREMENT_MANAGER,
        )
    ),
]

LogisticsManager = Annotated[
    AuthenticatedUser,
    Depends(
        require_roles(
            UserRole.SUPER_ADMIN,
            UserRole.ORGANIZATION_ADMIN,
            UserRole.LOGISTICS_MANAGER,
        )
    ),
]

FinanceManager = Annotated[
    AuthenticatedUser,
    Depends(
        require_roles(
            UserRole.SUPER_ADMIN,
            UserRole.ORGANIZATION_ADMIN,
            UserRole.FINANCE_MANAGER,
        )
    ),
]

AIEngineer = Annotated[
    AuthenticatedUser,
    Depends(
        require_roles(
            UserRole.SUPER_ADMIN,
            UserRole.ORGANIZATION_ADMIN,
            UserRole.AI_ENGINEER,
            UserRole.ML_ENGINEER,
        )
    ),
]

Auditor = Annotated[
    AuthenticatedUser,
    Depends(
        require_roles(
            UserRole.SUPER_ADMIN,
            UserRole.ORGANIZATION_ADMIN,
            UserRole.AUDITOR,
        )
    ),
]


# ============================================================
# APPROVAL DEPENDENCY
# ============================================================

async def get_approval_context(
    user: CurrentUser,
    organization: Organization,
) -> ApprovalContext:

    permissions = effective_permissions(user)

    can_approve = (
        Permission.APPROVAL_DECIDE in permissions
        and not user.is_ai_agent
    )

    return ApprovalContext(
        actor_id=user.id,
        organization_id=organization.organization_id,
        can_approve=can_approve,
        is_ai_agent=user.is_ai_agent,
    )


Approval = Annotated[
    ApprovalContext,
    Depends(get_approval_context),
]


async def require_human_approver(
    approval: Approval,
) -> ApprovalContext:

    if approval.is_ai_agent:
        raise forbidden(
            "AI agents cannot provide human approval"
        )

    if not approval.can_approve:
        raise forbidden(
            "Human approval permission required"
        )

    return approval


HumanApprover = Annotated[
    ApprovalContext,
    Depends(require_human_approver),
]


# ============================================================
# AGENT EXECUTION CONTEXT
# ============================================================

async def get_agent_execution_context(
    user: CurrentUser,
    organization: Organization,
    x_agent_id: Annotated[
        str | None,
        Header(alias="X-Agent-ID"),
    ] = None,
) -> AgentExecutionContext:

    if not x_agent_id:
        raise HTTPException(
            status_code=422,
            detail="X-Agent-ID header is required",
        )

    agent_id = validate_identifier(
        x_agent_id,
        "agent ID",
    )

    permissions = effective_permissions(user)

    if Permission.AI_AGENT_EXECUTE not in permissions:
        raise forbidden(
            "AI agent execution permission required"
        )

    # This dependency verifies the invoking principal.
    # The agent registry/service must additionally verify:
    # - agent ownership and organization
    # - agent activation status
    # - tool-level scopes
    # - execution budgets
    # - risk classification
    # - approval requirements
    # - tool authorization
    # before executing any agent action.

    return AgentExecutionContext(
        actor_id=user.id,
        organization_id=organization.organization_id,
        agent_id=agent_id,
        permissions=permissions,
        requires_human_approval=True,
    )


AgentContext = Annotated[
    AgentExecutionContext,
    Depends(get_agent_execution_context),
]


# ============================================================
# FEATURE FLAGS
# ============================================================

async def get_feature_flags(
    request: Request,
) -> Mapping[str, bool]:
    flags = getattr(
        request.app.state,
        "feature_flags",
        None,
    )

    if flags is None:
        return {}

    if not isinstance(flags, Mapping):
        raise HTTPException(
            status_code=503,
            detail="Feature configuration unavailable",
        )

    return flags


def require_feature(
    feature: FeatureFlag,
) -> Callable[..., Any]:

    async def dependency(
        flags: Annotated[
            Mapping[str, bool],
            Depends(get_feature_flags),
        ],
    ) -> bool:

        if flags.get(feature.value) is not True:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Feature '{feature.value}' "
                    "is unavailable"
                ),
            )

        return True

    return dependency


# ============================================================
# PAGINATION
# ============================================================

async def get_pagination(
    page: Annotated[
        int,
        Query(ge=1, description="Page number"),
    ] = 1,
    page_size: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_PAGE_SIZE,
            description="Items per page",
        ),
    ] = DEFAULT_PAGE_SIZE,
) -> PaginationParams:

    return PaginationParams(
        page=page,
        page_size=page_size,
    )


Pagination = Annotated[
    PaginationParams,
    Depends(get_pagination),
]


# ============================================================
# SORTING
# ============================================================

def parse_sort_fields(
    sort: str | None,
    *,
    allowed_fields: frozenset[str],
    default_field: str = "created_at",
) -> SortParams:

    if not sort:
        if default_field not in allowed_fields:
            raise ValueError(
                "Default sort field is not allowed"
            )

        return SortParams(
            fields=(
                SortField(
                    field=default_field,
                    descending=True,
                ),
            )
        )

    raw_fields = [
        value.strip()
        for value in sort.split(",")
        if value.strip()
    ]

    if len(raw_fields) > MAX_SORT_FIELDS:
        raise HTTPException(
            status_code=422,
            detail="Too many sort fields",
        )

    parsed: list[SortField] = []
    seen: set[str] = set()

    for raw_field in raw_fields:
        descending = raw_field.startswith("-")

        field_name = (
            raw_field[1:]
            if descending
            else raw_field
        )

        if field_name not in allowed_fields:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Unsupported sort field: {field_name}"
                ),
            )

        if field_name in seen:
            raise HTTPException(
                status_code=422,
                detail="Duplicate sort field",
            )

        seen.add(field_name)

        parsed.append(
            SortField(
                field=field_name,
                descending=descending,
            )
        )

    return SortParams(fields=tuple(parsed))


def sorting_dependency(
    allowed_fields: Sequence[str],
    default_field: str = "created_at",
) -> Callable[..., Any]:

    allowed = frozenset(allowed_fields)

    async def dependency(
        sort: Annotated[
            str | None,
            Query(
                description=(
                    "Comma-separated sort fields; "
                    "prefix with '-' for descending"
                )
            ),
        ] = None,
    ) -> SortParams:

        return parse_sort_fields(
            sort,
            allowed_fields=allowed,
            default_field=default_field,
        )

    return dependency


# ============================================================
# IDEMPOTENCY
# ============================================================

async def get_idempotency_key(
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key"),
    ] = None,
) -> str | None:

    if idempotency_key is None:
        return None

    if (
        len(idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH
        or not IDEMPOTENCY_PATTERN.fullmatch(
            idempotency_key
        )
    ):
        raise HTTPException(
            status_code=422,
            detail="Invalid idempotency key",
        )

    return idempotency_key


IdempotencyKey = Annotated[
    str | None,
    Depends(get_idempotency_key),
]


async def require_idempotency_key(
    key: IdempotencyKey,
) -> str:

    if key is None:
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key header is required",
        )

    return key


RequiredIdempotencyKey = Annotated[
    str,
    Depends(require_idempotency_key),
]


# ============================================================
# REQUEST CONTEXT
# ============================================================

async def get_request_context(
    request: Request,
    user: CurrentUser,
    organization: Organization,
    idempotency_key: IdempotencyKey,
) -> RequestContext:

    request_id = getattr(
        request.state,
        "request_id",
        None,
    )

    if not request_id:
        request_id = str(uuid.uuid4())

    client_ip = (
        request.client.host
        if request.client is not None
        else None
    )

    return RequestContext(
        request_id=request_id,
        user_id=user.id,
        organization_id=organization.organization_id,
        roles=user.roles,
        permissions=effective_permissions(user),
        timestamp=utc_now(),
        idempotency_key=idempotency_key,
        client_ip=client_ip,
    )


Context = Annotated[
    RequestContext,
    Depends(get_request_context),
]


# ============================================================
# RATE LIMITING
# ============================================================

RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])

if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end

return current
"""


def rate_limit(
    *,
    max_requests: int = DEFAULT_RATE_LIMIT,
    window_seconds: int = DEFAULT_RATE_WINDOW_SECONDS,
) -> Callable[..., Any]:

    if max_requests <= 0:
        raise ValueError(
            "max_requests must be positive"
        )

    if window_seconds <= 0:
        raise ValueError(
            "window_seconds must be positive"
        )

    async def dependency(
        request: Request,
        user: CurrentUser,
        redis: RedisClient,
    ) -> None:

        # Use the authenticated identity and organization,
        # not a user-supplied IP or forwarded header.
        route = request.scope.get("route")

        route_path = (
            getattr(route, "path", None)
            or request.url.path
        )

        route_hash = hashlib.sha256(
            route_path.encode("utf-8")
        ).hexdigest()[:20]

        key = (
            "rate_limit:"
            f"{user.organization_id}:"
            f"{user.id}:"
            f"{route_hash}"
        )

        try:
            count = await redis.eval(
                RATE_LIMIT_SCRIPT,
                1,
                key,
                window_seconds,
            )

        except Exception as exc:
            logger.exception(
                "Rate limiting backend unavailable"
            )

            # Fail closed for protected endpoints.
            raise HTTPException(
                status_code=503,
                detail="Rate limiting unavailable",
            ) from exc

        if int(count) > max_requests:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={
                    "Retry-After": str(window_seconds),
                },
            )

    return dependency


# ============================================================
# OPTIONAL SERVICE DEPENDENCIES
# ============================================================

def get_registered_service(
    request: Request,
    service_name: str,
) -> Any:

    services = getattr(
        request.app.state,
        "services",
        None,
    )

    if not isinstance(services, Mapping):
        raise HTTPException(
            status_code=503,
            detail="Service registry unavailable",
        )

    service = services.get(service_name)

    if service is None:
        raise HTTPException(
            status_code=503,
            detail=f"Service '{service_name}' unavailable",
        )

    return service


def service_dependency(
    service_name: str,
) -> Callable[..., Any]:

    async def dependency(
        request: Request,
    ) -> Any:
        return get_registered_service(
            request,
            service_name,
        )

    return dependency


get_inventory_service = service_dependency(
    "inventory"
)

get_warehouse_service = service_dependency(
    "warehouse"
)

get_supplier_service = service_dependency(
    "supplier"
)

get_demand_forecasting_service = service_dependency(
    "demand_forecasting"
)

get_replenishment_service = service_dependency(
    "replenishment"
)

get_logistics_service = service_dependency(
    "logistics"
)

get_agent_service = service_dependency(
    "agents"
)

get_rag_service = service_dependency(
    "rag"
)

get_model_service = service_dependency(
    "models"
)

get_notification_service = service_dependency(
    "notifications"
)

get_audit_service = service_dependency(
    "audit"
)


InventoryService = Annotated[
    Any,
    Depends(get_inventory_service),
]

WarehouseService = Annotated[
    Any,
    Depends(get_warehouse_service),
]

SupplierService = Annotated[
    Any,
    Depends(get_supplier_service),
]

DemandForecastingService = Annotated[
    Any,
    Depends(get_demand_forecasting_service),
]

ReplenishmentService = Annotated[
    Any,
    Depends(get_replenishment_service),
]

LogisticsService = Annotated[
    Any,
    Depends(get_logistics_service),
]

AgentService = Annotated[
    Any,
    Depends(get_agent_service),
]

RAGService = Annotated[
    Any,
    Depends(get_rag_service),
]

ModelService = Annotated[
    Any,
    Depends(get_model_service),
]

NotificationService = Annotated[
    Any,
    Depends(get_notification_service),
]

AuditService = Annotated[
    Any,
    Depends(get_audit_service),
]


# ============================================================
# RESOURCE OWNERSHIP
# ============================================================

def ensure_same_organization(
    *,
    resource_organization_id: str,
    organization: OrganizationContext,
) -> None:

    if (
        resource_organization_id
        != organization.organization_id
    ):
        # Avoid exposing whether another tenant's
        # resource exists.
        raise HTTPException(
            status_code=404,
            detail="Resource not found",
        )


def ensure_resource_owner(
    *,
    resource_owner_id: str | None,
    user: AuthenticatedUser,
    allow_admin: bool = True,
) -> None:

    if resource_owner_id == user.id:
        return

    if allow_admin and user.roles.intersection({
        UserRole.SUPER_ADMIN,
        UserRole.ORGANIZATION_ADMIN,
    }):
        return

    raise forbidden(
        "You do not own this resource"
    )


# ============================================================
# AI ACTION AUTHORIZATION
# ============================================================

HIGH_RISK_ACTIONS = frozenset({
    "purchase_order:approve",
    "purchase_order:submit",
    "inventory:adjust",
    "inventory:delete",
    "supplier:block",
    "supplier:terminate",
    "warehouse:decommission",
    "payment:execute",
    "refund:execute",
    "delivery:dispatch",
    "model:deploy",
    "integration:write",
    "agent:external_action",
})


def requires_human_approval(
    action: str,
) -> bool:
    return action in HIGH_RISK_ACTIONS


def validate_agent_action(
    *,
    context: AgentExecutionContext,
    action: str,
    approved: bool = False,
    approval_actor_id: str | None = None,
) -> None:

    if not action:
        raise ValueError(
            "Action name is required"
        )

    if requires_human_approval(action):
        if not approved:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Human approval is required "
                    "before executing this action"
                ),
            )

        if not approval_actor_id:
            raise HTTPException(
                status_code=409,
                detail="Verified approver is required",
            )

        if approval_actor_id == context.actor_id:
            raise forbidden(
                "An agent cannot approve its own action"
            )

        # IMPORTANT:
        # The approved flag and approval_actor_id are
        # not sufficient proof of authorization.
        #
        # Before executing a consequential action,
        # the service must load a persisted approval
        # record from the database and verify:
        #
        # 1. Organization matches.
        # 2. Action and resource match.
        # 3. Approval is active and not expired.
        # 4. Approver is a verified human.
        # 5. Approver has approval permissions.
        # 6. Approval has not been consumed/revoked.
        # 7. Agent execution is within its allowed scope.
        #
        # Never use this function as the only approval
        # enforcement mechanism.


# ============================================================
# AUDIT METADATA
# ============================================================

def build_audit_metadata(
    context: RequestContext,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:

    if not action:
        raise ValueError(
            "Audit action is required"
        )

    if not resource_type:
        raise ValueError(
            "Audit resource type is required"
        )

    return {
        "event_id": str(uuid.uuid4()),
        "request_id": context.request_id,
        "organization_id": context.organization_id,
        "actor_id": context.user_id,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "timestamp": utc_now().isoformat(),
        "details": dict(details or {}),
    }


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "UserRole",
    "Permission",
    "FeatureFlag",
    "AuthenticatedUser",
    "OrganizationContext",
    "RequestContext",
    "PaginationParams",
    "SortField",
    "SortParams",
    "ApprovalContext",
    "AgentExecutionContext",
    "IdentityProvider",
    "ROLE_PERMISSIONS",
    "get_identity_provider",
    "get_current_user",
    "get_optional_current_user",
    "get_api_key_user",
    "get_db",
    "get_redis",
    "get_organization_context",
    "get_approval_context",
    "require_human_approver",
    "get_agent_execution_context",
    "get_feature_flags",
    "get_pagination",
    "get_idempotency_key",
    "require_idempotency_key",
    "get_request_context",
    "require_roles",
    "require_all_roles",
    "require_permissions",
    "require_any_permission",
    "require_feature",
    "rate_limit",
    "sorting_dependency",
    "parse_sort_fields",
    "service_dependency",
    "get_registered_service",
    "ensure_same_organization",
    "ensure_resource_owner",
    "requires_human_approval",
    "validate_agent_action",
    "build_audit_metadata",
    "CurrentUser",
    "OptionalCurrentUser",
    "APIKeyUser",
    "DatabaseSession",
    "RedisClient",
    "Organization",
    "AdminUser",
    "WarehouseManager",
    "InventoryManager",
    "ProcurementManager",
    "LogisticsManager",
    "FinanceManager",
    "AIEngineer",
    "Auditor",
    "Approval",
    "HumanApprover",
    "AgentContext",
    "Pagination",
    "IdempotencyKey",
    "RequiredIdempotencyKey",
    "Context",
    "InventoryService",
    "WarehouseService",
    "SupplierService",
    "DemandForecastingService",
    "ReplenishmentService",
    "LogisticsService",
    "AgentService",
    "RAGService",
    "ModelService",
    "NotificationService",
    "AuditService",
]