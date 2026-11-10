from __future__ import annotations

"""Planned module: router. Implementation pending."""

"""
backend/router.py

Autonomous Retail Supply Chain AI 5.0

Centralized FastAPI router registry.

Python 3.10+
Dependencies:
    fastapi

Responsibilities:
    - Register existing API routers
    - Organize API domains
    - Support API versioning
    - Detect duplicate HTTP routes
    - Support optional modules
    - Register healtsales_streamh endpoints
    - Expose a safe API index
    - Avoid duplicate router inclusion

Security:
    - Authentication belongs in dependencies
      and endpoint implementations.
    - Optional routers must not bypass auth.
    - Never expose internal module errors.
    - Production must explicitly enable
      supported modules.

Note:
    Existing stream routers already declare
    their complete /api/v1/... prefixes.

    Therefore, they are mounted directly,
    without an additional /api/v1 prefix.
"""


import importlib
import logging

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from fastapi import (
    APIRouter,
    FastAPI,
    HTTPException,
)

from fastapi.routing import APIRoute


logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

API_VERSION = "v1"

API_PREFIX = f"/api/{API_VERSION}"

SERVICE_NAME = (
    "Autonomous Retail Supply Chain AI"
)

SERVICE_VERSION = "5.0"


# ============================================================
# ROUTER GROUPS
# ============================================================

class RouterGroup(str, Enum):

    CORE = "core"
    INVENTORY = "inventory"
    PRODUCT = "product"
    DEMAND = "demand"
    LOGISTICS = "logistics"
    PROCUREMENT = "procurement"
    SUPPLIER = "supplier"
    WAREHOUSE = "warehouse"
    ANALYTICS = "analytics"
    FEEDBACK = "feedback"
    NOTIFICATIONS = "notifications"
    AI = "ai"
    RAG = "rag"
    SECURITY = "security"
    MONITORING = "monitoring"


# ============================================================
# ROUTER DEFINITION
# ============================================================

@dataclass(frozen=True)
class RouterDefinition:

    name: str
    module_path: str
    group: RouterGroup

    router_attribute: str = "router"

    required: bool = False

    enabled: bool = True


# ============================================================
# REGISTRY
# ============================================================

ROUTER_REGISTRY: tuple[RouterDefinition, ...] = (

    RouterDefinition(
        name="healthcheck",
        module_path="backend.healthcheck",
        group=RouterGroup.MONITORING,
        required=True,
    ),

    RouterDefinition(
        name="agent_stream",
        module_path="backend.agent_stream",
        group=RouterGroup.AI,
    ),

    RouterDefinition(
        name="realtime",
        module_path="backend.connection_manager",
        group=RouterGroup.CORE,
    ),

    RouterDefinition(
        name="corporate_alert_stream",
        module_path="backend.corporate_alert_stream",
        group=RouterGroup.NOTIFICATIONS,
    ),

    RouterDefinition(
        name="employee_alert_stream",
        module_path="backend.employee_alert_stream",
        group=RouterGroup.NOTIFICATIONS,
    ),

    RouterDefinition(
        name="demand_stream",
        module_path="backend.demand_stream",
        group=RouterGroup.DEMAND,
    ),

    RouterDefinition(
        name="feedback_stream",
        module_path="backend.feedback_stream",
        group=RouterGroup.FEEDBACK,
    ),

    RouterDefinition(
        name="inventory_stream",
        module_path="backend.inventory_stream",
        group=RouterGroup.INVENTORY,
    ),

    RouterDefinition(
        name="logistics_stream",
        module_path="backend.logistics_stream",
        group=RouterGroup.LOGISTICS,
    ),

    RouterDefinition(
        name="product_stream",
        module_path="backend.product_stream",
        group=RouterGroup.PRODUCT,
    ),
)


# ============================================================
# ROUTER REGISTRATION ERRORS
# ============================================================

class RouterRegistrationError(RuntimeError):
    pass


class DuplicateRouterError(RouterRegistrationError):
    pass


class RouterImportError(RouterRegistrationError):
    pass


# ============================================================
# ROUTER LOADING
# ============================================================

def load_router(
    definition: RouterDefinition,
) -> APIRouter | None:
    """
    Import an existing router.

    Optional modules can be disabled through
    the registry. Missing required modules
    stop application initialization.
    """

    if not definition.enabled:
        return None

    try:

        module = importlib.import_module(
            definition.module_path
        )

        router = getattr(
            module,
            definition.router_attribute,
        )

    except (
        ImportError,
        AttributeError,
    ) as exc:

        if definition.required:

            raise RouterImportError(
                f"Required router unavailable: "
                f"{definition.name}"
            ) from exc

        logger.warning(
            "Optional router unavailable",
            extra={
                "router_name": definition.name,
            },
        )

        return None

    if not isinstance(router, APIRouter):

        raise RouterRegistrationError(
            f"Invalid APIRouter: "
            f"{definition.name}"
        )

    return router


# ============================================================
# DUPLICATE ROUTE VALIDATION
# ============================================================

def validate_duplicate_routes(
    app: FastAPI,
) -> None:
    """
    Detect duplicate HTTP method/path pairs.

    WebSocket routes are checked separately
    by their path.
    """

    http_routes: set[
        tuple[str, str]
    ] = set()

    websocket_routes: set[str] = set()

    for route in app.routes:

        if isinstance(route, APIRoute):

            for method in route.methods or set():

                key = (
                    method.upper(),
                    route.path,
                )

                if key in http_routes:

                    raise DuplicateRouterError(
                        "Duplicate HTTP route: "
                        f"{method} {route.path}"
                    )

                http_routes.add(key)

        elif (
            route.__class__.__name__
            == "APIWebSocketRoute"
        ):

            if route.path in websocket_routes:

                raise DuplicateRouterError(
                    "Duplicate WebSocket route: "
                    f"{route.path}"
                )

            websocket_routes.add(
                route.path
            )


# ============================================================
# ROUTER MANAGER
# ============================================================

class RouterManager:

    def __init__(
        self,
        registry: Iterable[
            RouterDefinition
        ] = ROUTER_REGISTRY,
    ):

        self.registry = tuple(
            registry
        )

        self._registered: set[str] = set()

    def register(
        self,
        app: FastAPI,
    ) -> list[str]:
        """
        Register enabled API routers.

        This should be called once during
        application construction.
        """

        registered: list[str] = []

        for definition in self.registry:

            if not definition.enabled:
                continue

            if definition.name in self._registered:
                continue

            router = load_router(
                definition
            )

            if router is None:
                continue

            app.include_router(
                router,
            )

            self._registered.add(
                definition.name
            )

            registered.append(
                definition.name
            )

            logger.info(
                "API router registered",
                extra={
                    "router_name": definition.name,
                    "router_group": (
                        definition.group.value
                    ),
                },
            )

        validate_duplicate_routes(
            app
        )

        return registered

    def registered_routers(
        self,
    ) -> list[str]:

        return sorted(
            self._registered
        )


# ============================================================
# API INDEX
# ============================================================

api_index_router = APIRouter(
    prefix=API_PREFIX,
    tags=["API"],
)


@api_index_router.get(
    "",
    include_in_schema=False,
)
async def api_index():

    return {
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "api_version": API_VERSION,
        "status": "available",
        "documentation": "/docs",
    }


# ============================================================
# PUBLIC REGISTRATION FUNCTION
# ============================================================

def register_api_routers(
    app: FastAPI,
    *,
    registry: Iterable[
        RouterDefinition
    ] = ROUTER_REGISTRY,
) -> list[str]:
    """
    Central registration entry point.

    Call once during FastAPI app creation.
    """

    manager = RouterManager(
        registry=registry
    )

    registered = manager.register(
        app
    )

    app.include_router(
        api_index_router
    )

    validate_duplicate_routes(
        app
    )

    app.state.registered_routers = (
        registered
    )

    return registered


# ============================================================
# OPTIONAL ROUTER CONFIGURATION
# ============================================================

def build_router_registry(
    *,
    enabled_names: set[str] | None = None,
) -> tuple[RouterDefinition, ...]:
    """
    Build a deployment-specific registry.

    Required routers remain enabled.
    Optional routers can be selected
    explicitly by name.
    """

    definitions = []

    for definition in ROUTER_REGISTRY:

        enabled = (
            definition.required
            or enabled_names is None
            or definition.name in enabled_names
        )

        definitions.append(
            RouterDefinition(
                name=definition.name,
                module_path=definition.module_path,
                group=definition.group,
                router_attribute=(
                    definition.router_attribute
                ),
                required=definition.required,
                enabled=enabled,
            )
        )

    return tuple(
        definitions
    )


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "API_VERSION",
    "API_PREFIX",
    "RouterGroup",
    "RouterDefinition",
    "RouterRegistrationError",
    "DuplicateRouterError",
    "RouterImportError",
    "ROUTER_REGISTRY",
    "RouterManager",
    "load_router",
    "validate_duplicate_routes",
    "register_api_routers",
    "build_router_registry",
]
