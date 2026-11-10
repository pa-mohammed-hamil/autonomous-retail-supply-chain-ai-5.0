from __future__ import annotations


# backend/main.py

"""
Autonomous Retail Supply Chain Optimization & Agentic AI
========================================================

Unified frontend and backend application.

Frontend:
    frontend/index.html
    frontend/pages/*.html
    frontend/css/*.css
    frontend/js/*.js
    frontend/assets/*
    frontend/images/*
    frontend/videos/*

Backend:
    backend/app.py
    backend/dependencies.py
    backend/api/v1/*.py

Run from the project root:

    python -m uvicorn backend.main:app --reload

Open:
    http://127.0.0.1:8000/

API documentation:
    http://127.0.0.1:8000/docs

Health:
    http://127.0.0.1:8000/health

Frontend status:
    http://127.0.0.1:8000/frontend-status
"""


import logging
import mimetypes
import os
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.app import create_app


# ============================================================
# APPLICATION CONFIGURATION
# ============================================================

APP_TITLE = (
    "Autonomous Retail Supply Chain "
    "Optimization & Agentic AI"
)

APP_VERSION = "1.0.0"

BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"

FRONTEND_DIR = Path(
    os.getenv(
        "FRONTEND_DIR",
        str(BASE_DIR / "frontend"),
    )
).expanduser().resolve()

INDEX_FILE = FRONTEND_DIR / "index.html"
PAGES_DIR = FRONTEND_DIR / "pages"

logger = logging.getLogger("retail_supply_chain.main")


# ============================================================
# MIME TYPES
# ============================================================

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("video/webm", ".webm")
mimetypes.add_type("application/wasm", ".wasm")


# ============================================================
# FRONTEND PAGE REGISTRY
# ============================================================

FRONTEND_PAGES: dict[str, str] = {
    # General
    "dashboard": "dashboard.html",
    "login": "login.html",
    "register": "register.html",
    "forgot-password": "forgot-password.html",
    "profile": "profile.html",
    "settings": "settings.html",

    # Retail and inventory
    "products": "products.html",
    "categories": "categories.html",
    "inventory": "inventory.html",
    "warehouses": "warehouses.html",
    "warehouse-bins": "warehouse-bins.html",
    "stores": "stores.html",
    "stock-movements": "stock-movements.html",
    "stock-alerts": "stock-alerts.html",
    "stockout-predictions": "stockout-predictions.html",
    "product-quality": "product-quality.html",
    "pricing": "pricing.html",

    # Sales and procurement
    "sales": "sales.html",
    "orders": "orders.html",
    "suppliers": "suppliers.html",
    "supplier-risk": "supplier-risk.html",
    "supplier-contracts": "supplier-contracts.html",
    "purchase-orders": "purchase-orders.html",
    "replenishment": "replenishment.html",
    "returns": "returns.html",
    "refunds": "refunds.html",

    # Fulfillment and logistics
    "fulfillment": "fulfillment.html",
    "picking": "picking.html",
    "packing": "packing.html",
    "deliveries": "deliveries.html",
    "logistics": "logistics.html",
    "vehicles": "vehicles.html",
    "fleet": "fleet.html",

    # AI and analytics
    "ai-agents": "ai-agents.html",
    "ai-copilot": "ai-copilot.html",
    "ai-features-dashboard": "ai-features-dashboard.html",
    "demand-forecasting": "demand-forecasting.html",
    "market-trends": "market-trends.html",
    "analytics": "analytics.html",
    "financials": "financials.html",
    "digital-twin": "digital-twin.html",
    "simulations": "simulations.html",
    "rag": "rag.html",
    "mlops": "mlops.html",
    "llmops": "llmops.html",
    "models": "models.html",
    "evaluations": "evaluations.html",
    "benchmarks": "benchmarks.html",
    
    # New AI Features
    "pricing-optimization": "pricing-optimization.html",
    "sustainability": "sustainability.html",
    "maintenance": "maintenance.html",
    "assortment": "assortment.html",
    "personalization": "personalization.html",
    "voice-assistant": "voice-assistant.html",
    "auto-stock": "auto-stock.html",

    # Enterprise operations
    "organizations": "organizations.html",
    "users": "users.html",
    "approvals": "approvals.html",
    "notifications": "notifications.html",
    "employee-alerts": "employee-alerts.html",
    "corporate-alerts": "corporate-alerts.html",
    "incidents": "incidents.html",
    "integrations": "integrations.html",
    "documents": "documents.html",
    "audit-logs": "audit-logs.html",
    "reports": "reports.html",
    "customer-feedback": "customer-feedback.html",
}


# ============================================================
# STATIC ASSET REGISTRY
# ============================================================

STATIC_DIRECTORIES: dict[str, Path] = {
    "css": FRONTEND_DIR / "css",
    "js": FRONTEND_DIR / "js",
    "assets": FRONTEND_DIR / "assets",
    "images": FRONTEND_DIR / "images",
    "videos": FRONTEND_DIR / "videos",
    "fonts": FRONTEND_DIR / "fonts",
    "icons": FRONTEND_DIR / "icons",
    "components": FRONTEND_DIR / "components",
}


# ============================================================
# FRONTEND SECURITY HELPERS
# ============================================================

BLOCKED_SUFFIXES = {
    ".py",
    ".pyc",
    ".env",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".bak",
    ".log",
    ".sql",
    ".sh",
    ".bat",
    ".ps1",
}

BLOCKED_NAMES = {
    ".env",
    ".git",
    ".gitignore",
    ".htaccess",
    ".htpasswd",
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "secrets.json",
    "credentials.json",
}


def resolve_frontend_file(relative_path: str) -> Path:
    """
    Resolve a frontend file safely.

    Prevents directory traversal and access to
    sensitive configuration or source files.
    """

    if not relative_path:
        raise HTTPException(
            status_code=404,
            detail="Frontend file not found",
        )

    decoded_path = unquote(relative_path)

    candidate = (
        FRONTEND_DIR / decoded_path
    ).resolve()

    if not candidate.is_relative_to(FRONTEND_DIR):
        raise HTTPException(
            status_code=403,
            detail="Access denied",
        )

    relative_parts = candidate.relative_to(
        FRONTEND_DIR
    ).parts

    for part in relative_parts:
        if part.startswith("."):
            raise HTTPException(
                status_code=403,
                detail="Access denied",
            )

        if part.lower() in BLOCKED_NAMES:
            raise HTTPException(
                status_code=403,
                detail="Access denied",
            )

    if candidate.suffix.lower() in BLOCKED_SUFFIXES:
        raise HTTPException(
            status_code=403,
            detail="Access denied",
        )

    if not candidate.is_file():
        raise HTTPException(
            status_code=404,
            detail="Frontend file not found",
        )

    return candidate


def serve_frontend_file(
    relative_path: str,
) -> FileResponse:

    file_path = resolve_frontend_file(
        relative_path
    )

    content_type = (
        mimetypes.guess_type(str(file_path))[0]
        or "application/octet-stream"
    )

    return FileResponse(
        path=file_path,
        media_type=content_type,
    )


# ============================================================
# FRONTEND APPLICATION
# ============================================================

frontend_app = FastAPI(
    title=f"{APP_TITLE} Frontend",
    version=APP_VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


# ============================================================
# STATIC ASSETS
# ============================================================

def mount_static_directories(
    application: FastAPI,
) -> None:

    for route_name, directory in (
        STATIC_DIRECTORIES.items()
    ):
        if not directory.is_dir():
            logger.debug(
                "Static directory not found: %s",
                directory,
            )
            continue

        application.mount(
            f"/{route_name}",
            StaticFiles(
                directory=str(directory),
                check_dir=True,
                follow_symlink=False,
            ),
            name=f"frontend_{route_name}",
        )

        logger.info(
            "Mounted frontend assets: /%s",
            route_name,
        )


mount_static_directories(frontend_app)


# ============================================================
# HOME PAGE
# ============================================================

@frontend_app.get(
    "/",
    include_in_schema=False,
)
async def frontend_home() -> FileResponse:

    return serve_frontend_file(
        "index.html"
    )


@frontend_app.get(
    "/index.html",
    include_in_schema=False,
)
async def frontend_index() -> FileResponse:

    return serve_frontend_file(
        "index.html"
    )


# ============================================================
# FRONTEND PAGE ROUTES
# ============================================================

def make_page_handler(filename: str):
    """
    Create a separate endpoint for each HTML page.

    This avoids late-binding closure issues.
    """

    async def page_handler() -> FileResponse:
        return serve_frontend_file(
            f"pages/{filename}"
        )

    return page_handler


def register_frontend_pages(
    application: FastAPI,
) -> None:

    for route_name, filename in (
        FRONTEND_PAGES.items()
    ):
        application.add_api_route(
            path=f"/{route_name}",
            endpoint=make_page_handler(filename),
            methods=["GET"],
            include_in_schema=False,
            name=f"frontend_{route_name}",
        )


register_frontend_pages(frontend_app)


# ============================================================
# FRONTEND CONFIGURATION
# ============================================================

@frontend_app.get(
    "/frontend-config.json",
    include_in_schema=False,
)
async def frontend_config() -> JSONResponse:

    return JSONResponse(
        content={
            "application": APP_TITLE,
            "version": APP_VERSION,
            "api_base_url": "/api/v1",
            "health_url": "/health",
            "docs_url": "/docs",
            "websocket_base_url": "/api/v1/ws",
            "frontend_pages": {
                name: f"/{name}"
                for name in FRONTEND_PAGES
            },
        },
        headers={
            "Cache-Control": "no-store",
        },
    )


# ============================================================
# FRONTEND STATUS
# ============================================================

@frontend_app.get(
    "/frontend-status",
    include_in_schema=False,
)
async def frontend_status() -> dict[str, Any]:

    available_pages = [
        name
        for name, filename in (
            FRONTEND_PAGES.items()
        )
        if (PAGES_DIR / filename).is_file()
    ]

    missing_pages = [
        name
        for name, filename in (
            FRONTEND_PAGES.items()
        )
        if not (PAGES_DIR / filename).is_file()
    ]

    available_assets = {
        name: directory.is_dir()
        for name, directory in (
            STATIC_DIRECTORIES.items()
        )
    }

    return {
        "application": APP_TITLE,
        "frontend_directory": str(FRONTEND_DIR),
        "frontend_exists": FRONTEND_DIR.is_dir(),
        "index_exists": INDEX_FILE.is_file(),
        "available_pages": available_pages,
        "missing_pages": missing_pages,
        "available_page_count": len(available_pages),
        "total_configured_pages": len(FRONTEND_PAGES),
        "static_directories": available_assets,
        "api_base_url": "/api/v1",
    }


# ============================================================
# FAVICON
# ============================================================

@frontend_app.get(
    "/favicon.ico",
    include_in_schema=False,
)
async def favicon() -> FileResponse:

    candidates = [
        "favicon.ico",
        "assets/favicon.ico",
        "images/favicon.ico",
    ]

    for relative_path in candidates:
        candidate = (
            FRONTEND_DIR / relative_path
        )

        if candidate.is_file():
            return serve_frontend_file(
                relative_path
            )

    raise HTTPException(
        status_code=404,
        detail="Favicon not found",
    )


# ============================================================
# ROBOTS
# ============================================================

@frontend_app.get(
    "/robots.txt",
    include_in_schema=False,
)
async def robots() -> FileResponse:

    return serve_frontend_file(
        "robots.txt"
    )


# ============================================================
# FRONTEND FALLBACK
# ============================================================

@frontend_app.get(
    "/{requested_path:path}",
    include_in_schema=False,
)
async def frontend_fallback(
    requested_path: str,
) -> FileResponse:
    """
    Supports existing frontend HTML and asset files.

    Examples:
        /pages/inventory.html
        /pages/suppliers.html
        /dashboard.html
        /css/style.css
        /js/app.js

    Missing files return 404.
    """

    reserved_paths = {
        "api",
        "docs",
        "redoc",
        "health",
        "metrics",
        "openapi.json",
    }

    first_segment = requested_path.split(
        "/",
        1,
    )[0]

    if first_segment in reserved_paths:
        raise HTTPException(
            status_code=404,
            detail="Endpoint not found",
        )

    return serve_frontend_file(
        requested_path
    )


# ============================================================
# MAIN BACKEND APPLICATION
# ============================================================

app: FastAPI = create_app()


# ============================================================
# REGISTER NEW FEATURE API ROUTERS
# ============================================================

# Import all new feature routers
from backend.api.v1 import (
    pricing,
    sustainability,
    maintenance,
    assortment,
    personalization,
    voice_assistant,
    auto_stock,
)

# Register all new feature endpoints
app.include_router(pricing.router, prefix="/api/v1", tags=["pricing"])
app.include_router(sustainability.router, prefix="/api/v1", tags=["sustainability"])
app.include_router(maintenance.router, prefix="/api/v1", tags=["maintenance"])
app.include_router(assortment.router, prefix="/api/v1", tags=["assortment"])
app.include_router(personalization.router, prefix="/api/v1", tags=["personalization"])
app.include_router(voice_assistant.router, prefix="/api/v1", tags=["voice-assistant"])
app.include_router(auto_stock.router, prefix="/api/v1", tags=["auto-stock"])

logger.info("✅ All 7 advanced AI feature APIs registered successfully")


# ============================================================
# FRONTEND + BACKEND INTEGRATION
# ============================================================

# The existing backend application owns:
#
#   /api/v1/*
#   /health
#   /health/live
#   /health/ready
#   /docs
#   /redoc
#   /openapi.json
#   /metrics
#
# The frontend application owns:
#
#   /
#   /index.html
#   /dashboard
#   /inventory
#   /warehouses
#   /suppliers
#   /pages/*.html
#   /css/*
#   /js/*
#   /assets/*
#
# Important:
# backend/app.py already registers a GET "/" endpoint.
# To ensure index.html loads, the frontend is mounted
# before that backend root route in the router order.
#
# Other backend routes continue to work because
# the frontend mount is registered only after those
# routes are already registered.


def connect_frontend(
    application: FastAPI,
) -> None:

    # Register frontend routes ahead of the backend's
    # existing root route while preserving backend APIs.
    #
    # Starlette checks routes in order.
    # Insert the frontend mount immediately before the
    # existing GET "/" route.

    root_index = None

    for index, route in enumerate(
        application.router.routes
    ):
        route_path = getattr(
            route,
            "path",
            None,
        )

        route_methods = getattr(
            route,
            "methods",
            set(),
        )

        if (
            route_path == "/"
            and "GET" in route_methods
        ):
            root_index = index
            break

    from starlette.routing import Mount

    frontend_mount = Mount(
        path="/",
        app=frontend_app,
        name="frontend",
    )

    if root_index is None:
        application.router.routes.append(
            frontend_mount
        )
    else:
        application.router.routes.insert(
            root_index,
            frontend_mount,
        )

    logger.info(
        "Frontend connected at / from %s",
        FRONTEND_DIR,
    )


connect_frontend(app)


# ============================================================
# LOCAL DEVELOPMENT SERVER
# ============================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=os.getenv(
            "HOST",
            "127.0.0.1",
        ),
        port=int(
            os.getenv(
                "PORT",
                "8000",
            )
        ),
        reload=(
            os.getenv(
                "ENVIRONMENT",
                "development",
            ).lower()
            != "production"
        ),
        log_level="info",
    )
