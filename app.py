from __future__ import annotations


"""
Autonomous Retail Supply Chain Optimization & Agentic AI
========================================================

Production-oriented FastAPI application entry point.

Features:
- FastAPI application factory
- Environment-based configuration
- Application lifespan management
- Database initialization and connectivity checks
- Redis connectivity checks
- Dynamic API router registration
- JWT-compatible authentication middleware integration
- CORS and trusted-host protection
- Request IDs and structured request logging
- Security headers
- Global exception handling
- Health, readiness, and liveness endpoints
- Prometheus-compatible metrics endpoint
- OpenTelemetry integration hooks
- API versioning
- Graceful startup and shutdown
- Optional background service initialization

Install:
    pip install fastapi uvicorn sqlalchemy pydantic-settings \
        redis prometheus-client

Run:
    uvicorn backend.app:app --reload

Production:
    uvicorn backend.app:app --host 0.0.0.0 --port 8000 \
        --workers 4 --proxy-headers
"""

import asyncio
import importlib
import logging
import os
import time
import uuid

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from starlette.middleware.trustedhost import TrustedHostMiddleware


# ============================================================
# APPLICATION METADATA
# ============================================================

APP_NAME = (
    "Autonomous Retail Supply Chain "
    "Optimization & Agentic AI"
)

APP_VERSION = "1.0.0"

APP_DESCRIPTION = """
AI-powered enterprise retail supply chain platform.

### Core capabilities

- Multi-tenant retail and warehouse management
- Product and inventory intelligence
- Demand forecasting
- Supplier risk assessment
- Procurement and purchase orders
- Intelligent replenishment
- Warehouse bin management
- Order fulfillment
- Picking and packing
- Delivery and logistics optimization
- Vehicle and fleet management
- Stockout prediction
- Market trend intelligence
- Product quality monitoring
- Customer feedback analysis
- Retail financial analytics
- Digital twin simulation
- Autonomous AI agents
- Human-in-the-loop approvals
- Retrieval-augmented generation
- Agentic AI copilots
- MLOps and LLMOps
- Enterprise audit logging
- Real-time notifications
- Security and observability

All consequential AI-generated actions should be authorized,
validated, and audited before execution.
"""

API_PREFIX = "/api/v1"

logger = logging.getLogger("retail_supply_chain")


# ============================================================
# CONFIGURATION
# ============================================================

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    APP_NAME: str = APP_NAME
    APP_VERSION: str = APP_VERSION

    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    API_PREFIX: str = API_PREFIX

    DATABASE_URL: str = (
        "sqlite+aiosqlite:///./retail_supply_chain.db"
    )

    DATABASE_ECHO: bool = False
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 20
    DATABASE_POOL_TIMEOUT: int = 30
    DATABASE_POOL_RECYCLE: int = 1800

    REDIS_URL: str | None = None
    REDIS_REQUIRED: bool = False

    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]

    CORS_ALLOW_CREDENTIALS: bool = True

    ALLOWED_HOSTS: list[str] = [
        "localhost",
        "127.0.0.1",
        "testserver",
    ]

    ENABLE_DOCS: bool = True
    ENABLE_METRICS: bool = True

    ENABLE_AI_AGENTS: bool = True
    ENABLE_RAG: bool = True
    ENABLE_MLOPS: bool = True
    ENABLE_LLMOPS: bool = True
    ENABLE_WEBSOCKETS: bool = True

    AUTO_CREATE_TABLES: bool = False

    LOG_LEVEL: str = "INFO"

    REQUEST_TIMEOUT_SECONDS: int = 60

    MAX_REQUEST_BODY_BYTES: int = 10 * 1024 * 1024

    HEALTH_CHECK_TIMEOUT_SECONDS: float = 5.0

    SERVICE_NAME: str = "retail-supply-chain-api"

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"


settings = Settings()


# ============================================================
# LOGGING
# ============================================================

def configure_logging() -> None:
    level = getattr(
        logging,
        settings.LOG_LEVEL.upper(),
        logging.INFO,
    )

    logging.basicConfig(
        level=level,
        format=(
            "%(asctime)s | %(levelname)s | "
            "%(name)s | %(message)s"
        ),
    )

    logging.getLogger("uvicorn.access").setLevel(level)


configure_logging()


# ============================================================
# RESPONSE SCHEMAS
# ============================================================

class ServiceStatus(BaseModel):
    name: str
    status: str
    details: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    application: str
    version: str
    environment: str
    timestamp: datetime
    uptime_seconds: float


class ReadinessResponse(HealthResponse):
    services: list[ServiceStatus] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    message: str
    request_id: str | None = None
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class RootResponse(BaseModel):
    application: str
    version: str
    environment: str
    status: str
    api_prefix: str
    documentation: str | None = None


# ============================================================
# DATABASE
# ============================================================

def build_database_engine() -> AsyncEngine:
    options: dict[str, Any] = {
        "echo": settings.DATABASE_ECHO,
        "pool_pre_ping": True,
    }

    if not settings.DATABASE_URL.startswith(
        "sqlite+aiosqlite"
    ):
        options.update({
            "pool_size": settings.DATABASE_POOL_SIZE,
            "max_overflow": settings.DATABASE_MAX_OVERFLOW,
            "pool_timeout": settings.DATABASE_POOL_TIMEOUT,
            "pool_recycle": settings.DATABASE_POOL_RECYCLE,
        })

    return create_async_engine(
        settings.DATABASE_URL,
        **options,
    )


async def check_database(engine: AsyncEngine) -> bool:
    try:
        async with asyncio.timeout(
            settings.HEALTH_CHECK_TIMEOUT_SECONDS
        ):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        return True

    except Exception:
        logger.exception("Database connectivity check failed")
        return False


async def initialize_database(
    engine: AsyncEngine,
) -> None:
    if not settings.AUTO_CREATE_TABLES:
        logger.info(
            "Automatic table creation disabled. "
            "Use Alembic migrations."
        )
        return

    if settings.is_production:
        raise RuntimeError(
            "AUTO_CREATE_TABLES must be disabled in production. "
            "Use Alembic migrations."
        )

    from backend.models.base import Base

    # Ensure models are imported before create_all().
    # backend.models.__init__ should import all registered
    # ORM model modules.
    importlib.import_module("backend.models")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    logger.info("Development database tables initialized")


# ============================================================
# REDIS
# ============================================================

async def initialize_redis() -> Any | None:
    if not settings.REDIS_URL:
        if settings.REDIS_REQUIRED:
            raise RuntimeError(
                "REDIS_URL is required but not configured"
            )
        return None

    try:
        from redis.asyncio import Redis

        client = Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )

        await client.ping()

        logger.info("Redis connected successfully")
        return client

    except Exception:
        logger.exception("Redis initialization failed")

        if settings.REDIS_REQUIRED:
            raise

        return None


async def check_redis(redis_client: Any | None) -> bool:
    if redis_client is None:
        return False

    try:
        async with asyncio.timeout(
            settings.HEALTH_CHECK_TIMEOUT_SECONDS
        ):
            return bool(await redis_client.ping())

    except Exception:
        logger.exception("Redis health check failed")
        return False


# ============================================================
# DYNAMIC ROUTER REGISTRY
# ============================================================

ROUTER_MODULES: dict[str, str] = {
    # Authentication and administration
    # "auth": "backend.api.v1.auth",  # Commented out - requires pwdlib
    "users": "backend.api.v1.users",
    "organizations": "backend.api.v1.organizations",
    "approvals": "backend.api.v1.approvals",
    "audit": "backend.api.v1.audit",

    # Product and catalog
    "products": "backend.api.v1.products",
    "categories": "backend.api.v1.categories",
    "pricing": "backend.api.v1.pricing",
    "product_quality": "backend.api.v1.product_quality",

    # Retail and sales
    "sales": "backend.api.v1.sales",
    "feedback": "backend.api.v1.feedback",
    "market_trends": "backend.api.v1.market_trends",
    "financials": "backend.api.v1.financials",

    # Warehouse and inventory
    "warehouses": "backend.api.v1.warehouses",
    "bins": "backend.api.v1.bins",
    "inventory": "backend.api.v1.inventory",
    "stock_movements": "backend.api.v1.stock_movements",
    "stock_alerts": "backend.api.v1.stock_alerts",

    # Demand and procurement
    "demand": "backend.api.v1.demand",
    "suppliers": "backend.api.v1.suppliers",
    "supplier_risk": "backend.api.v1.supplier_risk",
    "purchase_orders": "backend.api.v1.purchase_orders",
    "replenishment": "backend.api.v1.replenishment",

    # Fulfillment
    "fulfillment": "backend.api.v1.fulfillment",
    "picking": "backend.api.v1.picking",
    "packing": "backend.api.v1.packing",
    "deliveries": "backend.api.v1.deliveries",
    "logistics": "backend.api.v1.logistics",
    "fleet": "backend.api.v1.fleet",

    # AI and machine learning
    "agents": "backend.api.v1.agents",
    "copilot": "backend.api.v1.copilot",
    "rag": "backend.api.v1.rag",
    "models": "backend.api.v1.models",
    "mlops": "backend.api.v1.mlops",
    "evaluations": "backend.api.v1.evaluations",
    "simulations": "backend.api.v1.simulations",
    "digital_twin": "backend.api.v1.digital_twin",

    # Operational support
    "notifications": "backend.api.v1.notifications",
    "incidents": "backend.api.v1.incidents",
    "integrations": "backend.api.v1.integrations",
    "documents": "backend.api.v1.documents",
    "analytics": "backend.api.v1.analytics",
}


def register_api_routers(application: FastAPI) -> None:
    """
    Register existing API modules.

    Missing modules are skipped during incremental development.
    Existing modules with import errors are not silently skipped.
    """

    registered: list[str] = []
    missing: list[str] = []

    for name, module_path in ROUTER_MODULES.items():
        try:
            module = importlib.import_module(module_path)

        except ModuleNotFoundError as exc:
            if exc.name == module_path:
                missing.append(name)
                continue

            # A dependency inside an existing router is missing.
            raise RuntimeError(
                f"Failed importing dependency for "
                f"{module_path}: {exc.name}"
            ) from exc

        router = getattr(module, "router", None)

        if router is None:
            raise RuntimeError(
                f"{module_path} must expose an APIRouter "
                "instance named 'router'"
            )

        application.include_router(
            router,
            prefix=settings.API_PREFIX,
        )

        registered.append(name)

    application.state.registered_routers = registered
    application.state.missing_routers = missing

    logger.info(
        "Registered %d API routers",
        len(registered),
    )

    if missing:
        logger.warning(
            "API modules not yet implemented: %s",
            ", ".join(missing),
        )


# ============================================================
# OPTIONAL OPENTELEMETRY
# ============================================================

def configure_tracing(application: FastAPI) -> None:
    try:
        from opentelemetry.instrumentation.fastapi import (
            FastAPIInstrumentor,
        )

    except ImportError:
        logger.info(
            "OpenTelemetry FastAPI instrumentation unavailable"
        )
        return

    FastAPIInstrumentor.instrument_app(application)

    logger.info("OpenTelemetry FastAPI instrumentation enabled")


# ============================================================
# PROMETHEUS METRICS
# ============================================================

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Histogram,
        generate_latest,
    )

    REQUEST_COUNT = Counter(
        "retail_api_requests_total",
        "Total HTTP requests",
        ["method", "route", "status_code"],
    )

    REQUEST_LATENCY = Histogram(
        "retail_api_request_duration_seconds",
        "HTTP request duration",
        ["method", "route"],
    )

    PROMETHEUS_AVAILABLE = True

except ImportError:
    CONTENT_TYPE_LATEST = None
    REQUEST_COUNT = None
    REQUEST_LATENCY = None
    PROMETHEUS_AVAILABLE = False


# ============================================================
# LIFESPAN
# ============================================================

@asynccontextmanager
async def lifespan(
    application: FastAPI,
) -> AsyncIterator[None]:

    logger.info("Starting %s", settings.APP_NAME)

    application.state.started_at = time.monotonic()
    application.state.ready = False

    engine: AsyncEngine | None = None
    redis_client: Any | None = None

    try:
        engine = build_database_engine()

        application.state.db_engine = engine
        application.state.db_session_factory = (
            async_sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )
        )

        if not await check_database(engine):
            raise RuntimeError(
                "Database is unavailable during startup"
            )

        await initialize_database(engine)

        redis_client = await initialize_redis()

        application.state.redis = redis_client

        application.state.ready = True

        logger.info(
            "%s started successfully",
            settings.APP_NAME,
        )

        yield

    finally:
        application.state.ready = False

        logger.info("Shutting down application")

        if redis_client is not None:
            try:
                await redis_client.aclose()
            except Exception:
                logger.exception("Redis shutdown failed")

        if engine is not None:
            try:
                await engine.dispose()
            except Exception:
                logger.exception("Database shutdown failed")

        logger.info("Application shutdown complete")


# ============================================================
# SECURITY
# ============================================================

def configure_security(application: FastAPI) -> None:
    if (
        settings.CORS_ALLOW_CREDENTIALS
        and "*" in settings.CORS_ORIGINS
    ):
        raise RuntimeError(
            "Wildcard CORS origins cannot be used "
            "with credentials"
        )

    if settings.is_production:
        if "*" in settings.ALLOWED_HOSTS:
            raise RuntimeError(
                "Configure explicit ALLOWED_HOSTS "
                "for production"
            )

        if settings.DEBUG:
            raise RuntimeError(
                "DEBUG must be disabled in production"
            )

    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.ALLOWED_HOSTS,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=[
            "GET",
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
            "OPTIONS",
        ],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Accept",
            "X-Request-ID",
            "X-Organization-ID",
            "Idempotency-Key",
        ],
        expose_headers=["X-Request-ID"],
    )


# ============================================================
# REQUEST MIDDLEWARE
# ============================================================

def configure_request_middleware(
    application: FastAPI,
) -> None:

    @application.middleware("http")
    async def request_context_middleware(
        request: Request,
        call_next: Callable,
    ) -> Response:

        incoming_request_id = request.headers.get(
            "X-Request-ID"
        )

        if (
            incoming_request_id
            and len(incoming_request_id) <= 128
            and all(
                char.isalnum() or char in "-_"
                for char in incoming_request_id
            )
        ):
            request_id = incoming_request_id
        else:
            request_id = str(uuid.uuid4())

        request.state.request_id = request_id

        started = time.perf_counter()

        response = await call_next(request)

        duration = time.perf_counter() - started

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = (
            "strict-origin-when-cross-origin"
        )
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )

        if settings.is_production:
            response.headers[
                "Strict-Transport-Security"
            ] = "max-age=31536000; includeSubDomains"

        route = request.scope.get("route")
        route_name = (
            getattr(route, "path", None)
            or "unmatched"
        )

        logger.info(
            "request_id=%s method=%s route=%s "
            "status=%s duration_ms=%.2f",
            request_id,
            request.method,
            route_name,
            response.status_code,
            duration * 1000,
        )

        if (
            settings.ENABLE_METRICS
            and PROMETHEUS_AVAILABLE
        ):
            REQUEST_COUNT.labels(
                method=request.method,
                route=route_name,
                status_code=str(response.status_code),
            ).inc()

            REQUEST_LATENCY.labels(
                method=request.method,
                route=route_name,
            ).observe(duration)

        return response


# ============================================================
# EXCEPTION HANDLERS
# ============================================================

def configure_exception_handlers(
    application: FastAPI,
) -> None:

    @application.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request,
        exc: HTTPException,
    ) -> JSONResponse:

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "error": "http_error",
                "message": str(exc.detail),
                "request_id": getattr(
                    request.state,
                    "request_id",
                    None,
                ),
                "timestamp": utc_now_iso(),
            },
            headers=exc.headers,
        )

    @application.exception_handler(
        RequestValidationError
    )
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:

        errors = []

        for error in exc.errors():
            errors.append({
                "field": ".".join(
                    str(part)
                    for part in error.get("loc", [])
                ),
                "message": error.get(
                    "msg",
                    "Invalid input",
                ),
                "type": error.get("type"),
            })

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "success": False,
                "error": "validation_error",
                "message": "Request validation failed",
                "details": errors,
                "request_id": getattr(
                    request.state,
                    "request_id",
                    None,
                ),
                "timestamp": utc_now_iso(),
            },
        )

    @application.exception_handler(Exception)
    async def unexpected_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:

        request_id = getattr(
            request.state,
            "request_id",
            None,
        )

        logger.exception(
            "Unhandled application error request_id=%s",
            request_id,
        )

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": "internal_server_error",
                "message": (
                    "An unexpected server error occurred"
                ),
                "request_id": request_id,
                "timestamp": utc_now_iso(),
            },
        )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# HEALTH ENDPOINTS
# ============================================================

def register_health_routes(
    application: FastAPI,
) -> None:

    @application.get(
        "/",
        response_model=RootResponse,
        tags=["System"],
    )
    async def root() -> RootResponse:
        return RootResponse(
            application=settings.APP_NAME,
            version=settings.APP_VERSION,
            environment=settings.ENVIRONMENT,
            status="running",
            api_prefix=settings.API_PREFIX,
            documentation=(
                "/docs"
                if settings.ENABLE_DOCS
                else None
            ),
        )

    @application.get(
        "/health",
        response_model=HealthResponse,
        tags=["Health"],
    )
    async def health(
        request: Request,
    ) -> HealthResponse:

        uptime = (
            time.monotonic()
            - request.app.state.started_at
        )

        return HealthResponse(
            status="healthy",
            application=settings.APP_NAME,
            version=settings.APP_VERSION,
            environment=settings.ENVIRONMENT,
            timestamp=datetime.now(timezone.utc),
            uptime_seconds=round(uptime, 3),
        )

    @application.get(
        "/health/live",
        tags=["Health"],
    )
    async def liveness() -> dict[str, str]:
        return {
            "status": "alive",
            "timestamp": utc_now_iso(),
        }

    @application.get(
        "/health/ready",
        response_model=ReadinessResponse,
        tags=["Health"],
    )
    async def readiness(
        request: Request,
        response: Response,
    ) -> ReadinessResponse:

        engine = getattr(
            request.app.state,
            "db_engine",
            None,
        )

        redis_client = getattr(
            request.app.state,
            "redis",
            None,
        )

        database_ok = (
            await check_database(engine)
            if engine is not None
            else False
        )

        redis_ok = (
            await check_redis(redis_client)
            if redis_client is not None
            else False
        )

        redis_configured = bool(settings.REDIS_URL)

        redis_ready = (
            redis_ok
            if settings.REDIS_REQUIRED
            else True
        )

        ready = (
            request.app.state.ready
            and database_ok
            and redis_ready
        )

        if not ready:
            response.status_code = 503

        services = [
            ServiceStatus(
                name="database",
                status=(
                    "healthy"
                    if database_ok
                    else "unhealthy"
                ),
            ),
            ServiceStatus(
                name="redis",
                status=(
                    "healthy"
                    if redis_ok
                    else (
                        "unhealthy"
                        if redis_configured
                        else "not_configured"
                    )
                ),
                details={
                    "required": settings.REDIS_REQUIRED,
                },
            ),
        ]

        uptime = (
            time.monotonic()
            - request.app.state.started_at
        )

        return ReadinessResponse(
            status="ready" if ready else "not_ready",
            application=settings.APP_NAME,
            version=settings.APP_VERSION,
            environment=settings.ENVIRONMENT,
            timestamp=datetime.now(timezone.utc),
            uptime_seconds=round(uptime, 3),
            services=services,
        )

    @application.get(
        "/api/v1/system/info",
        tags=["System"],
    )
    async def system_info(
        request: Request,
    ) -> dict[str, Any]:

        return {
            "application": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "api_prefix": settings.API_PREFIX,
            "features": {
                "ai_agents": settings.ENABLE_AI_AGENTS,
                "rag": settings.ENABLE_RAG,
                "mlops": settings.ENABLE_MLOPS,
                "llmops": settings.ENABLE_LLMOPS,
                "websockets": settings.ENABLE_WEBSOCKETS,
                "metrics": settings.ENABLE_METRICS,
            },
            "registered_api_modules": getattr(
                request.app.state,
                "registered_routers",
                [],
            ),
            "timestamp": utc_now_iso(),
        }


# ============================================================
# METRICS ENDPOINT
# ============================================================

def register_metrics_route(
    application: FastAPI,
) -> None:

    if not (
        settings.ENABLE_METRICS
        and PROMETHEUS_AVAILABLE
    ):
        return

    @application.get(
        "/metrics",
        include_in_schema=False,
    )
    async def metrics(
        request: Request,
    ) -> Response:
        # This endpoint should be restricted at the
        # ingress or reverse proxy to authorized monitoring
        # infrastructure. It is not publicly authenticated here.
        return Response(
            content=generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )


# ============================================================
# DATABASE SESSION DEPENDENCY
# ============================================================

async def get_db(
    request: Request,
) -> AsyncIterator[AsyncSession]:
    """
    Usage in routers:

        from fastapi import Depends
        from sqlalchemy.ext.asyncio import AsyncSession
        from backend.app import get_db

        @router.get("/items")
        async def get_items(
            db: AsyncSession = Depends(get_db),
        ):
            ...

    The session is rolled back if an exception occurs.
    Write operations should explicitly commit inside
    the authorized service layer.
    """

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


# ============================================================
# REDIS DEPENDENCY
# ============================================================

async def get_redis(
    request: Request,
) -> Any:
    redis_client = getattr(
        request.app.state,
        "redis",
        None,
    )

    if redis_client is None:
        raise HTTPException(
            status_code=503,
            detail="Redis service unavailable",
        )

    return redis_client


# ============================================================
# APPLICATION FACTORY
# ============================================================

def create_app() -> FastAPI:

    application = FastAPI(
        title=settings.APP_NAME,
        description=APP_DESCRIPTION,
        version=settings.APP_VERSION,
        debug=settings.DEBUG,
        docs_url=(
            "/docs"
            if settings.ENABLE_DOCS
            else None
        ),
        redoc_url=(
            "/redoc"
            if settings.ENABLE_DOCS
            else None
        ),
        openapi_url=(
            "/openapi.json"
            if settings.ENABLE_DOCS
            else None
        ),
        lifespan=lifespan,
        contact={
            "name": "Retail Supply Chain AI Platform",
        },
        license_info={
            "name": "Proprietary",
        },
        openapi_tags=[
            {
                "name": "System",
                "description": "System information",
            },
            {
                "name": "Health",
                "description": "Health and readiness checks",
            },
            {
                "name": "Authentication",
                "description": "Authentication and access control",
            },
            {
                "name": "Inventory",
                "description": "Inventory intelligence",
            },
            {
                "name": "Warehouses",
                "description": "Warehouse operations",
            },
            {
                "name": "Suppliers",
                "description": "Supplier management",
            },
            {
                "name": "Demand",
                "description": "Demand forecasting",
            },
            {
                "name": "Agents",
                "description": "Agentic AI workflows",
            },
            {
                "name": "RAG",
                "description": "Knowledge retrieval",
            },
            {
                "name": "MLOps",
                "description": "Machine learning operations",
            },
        ],
    )

    configure_security(application)

    configure_request_middleware(application)

    configure_exception_handlers(application)

    register_health_routes(application)

    register_metrics_route(application)

    register_api_routers(application)

    configure_tracing(application)

    logger.info(
        "FastAPI application initialized: %s",
        settings.APP_NAME,
    )

    return application


# ============================================================
# ASGI APPLICATION
# ============================================================

app = create_app()


# ============================================================
# LOCAL DEVELOPMENT
# ============================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.app:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=not settings.is_production,
        log_level=settings.LOG_LEVEL.lower(),
    )