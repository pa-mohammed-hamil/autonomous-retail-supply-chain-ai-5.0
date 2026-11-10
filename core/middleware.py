from __future__ import annotations

"""Planned module: middleware. Implementation pending."""

"""
backend/middleware.py

Autonomous Retail Supply Chain AI 5.0

Centralized FastAPI / Starlette middleware.

Features
--------
1. Request ID generation
2. Correlation ID propagation
3. Structured HTTP logging
4. Prometheus HTTP metrics
5. Security response headers
6. Request body size limits
7. Request timeout handling
8. Trusted tenant context
9. Centralized exception responses
10. Request processing duration
11. Sensitive endpoint protection
12. Middleware configuration

Dependencies
------------
fastapi
starlette
prometheus-client

Existing project modules
------------------------
backend.logging
backend.metrics

Security
--------
- Tenant identity must come from verified auth.
- No raw request bodies are logged.
- Untrusted client IDs are not trusted.
- Metrics endpoints require separate access control.
- Middleware does not replace RBAC or rate limiting.
"""


import asyncio
import logging
import re
import time
import uuid

from dataclasses import dataclass
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import (
    BaseHTTPMiddleware,
)
from starlette.responses import Response

from backend.logging import (
    get_logger,
    log_event,
    logging_context,
)

from backend.metrics import metrics


logger = get_logger("middleware")


# ============================================================
# CONFIGURATION
# ============================================================

@dataclass(frozen=True)
class MiddlewareConfig:

    max_request_bytes: int = 10 * 1024 * 1024

    request_timeout_seconds: float = 30.0

    enable_logging: bool = True

    enable_metrics: bool = True

    enable_security_headers: bool = True

    enable_request_timeout: bool = True

    enable_body_limit: bool = True

    hide_server_header: bool = True

    content_security_policy: str = (
        "default-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    )

    def __post_init__(self) -> None:

        if self.max_request_bytes <= 0:
            raise ValueError(
                "max_request_bytes must be positive"
            )

        if self.request_timeout_seconds <= 0:
            raise ValueError(
                "request_timeout_seconds must be positive"
            )


# ============================================================
# HELPERS
# ============================================================

SAFE_REQUEST_ID = re.compile(
    r"^[A-Za-z0-9_-]{1,64}$"
)


def generate_request_id() -> str:

    return str(uuid.uuid4())


def normalize_correlation_id(
    value: str | None,
) -> str:

    if value and SAFE_REQUEST_ID.fullmatch(value):
        return value

    return generate_request_id()


def get_route_template(
    request: Request,
) -> str:

    route = request.scope.get("route")

    if route is None:
        return "/unmatched"

    path = getattr(route, "path", None)

    if not isinstance(path, str):
        return "/unmatched"

    return path


def get_status_class(
    status_code: int,
) -> str:

    return f"{status_code // 100}xx"


def error_response(
    *,
    status_code: int,
    message: str,
    request_id: str | None = None,
) -> JSONResponse:

    response = JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {
                "status_code": status_code,
                "message": message,
                "request_id": request_id,
            },
        },
    )

    if request_id:
        response.headers["X-Request-ID"] = request_id

    return response


# ============================================================
# REQUEST CONTEXT MIDDLEWARE
# ============================================================

class RequestContextMiddleware(
    BaseHTTPMiddleware
):

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:

        request_id = generate_request_id()

        correlation_id = normalize_correlation_id(
            request.headers.get(
                "X-Correlation-ID"
            )
        )

        request.state.request_id = request_id

        request.state.correlation_id = (
            correlation_id
        )

        # Do not trust X-Tenant-ID supplied by clients.
        # Verified authentication middleware or
        # dependencies must populate this value.
        request.state.tenant_id = None

        with logging_context(
            request_id=request_id,
            correlation_id=correlation_id,
        ):

            response = await call_next(request)

            response.headers[
                "X-Request-ID"
            ] = request_id

            response.headers[
                "X-Correlation-ID"
            ] = correlation_id

            return response


# ============================================================
# STRUCTURED LOGGING MIDDLEWARE
# ============================================================

class RequestLoggingMiddleware(
    BaseHTTPMiddleware
):

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:

        started = time.perf_counter()

        try:

            response = await call_next(
                request
            )

        except Exception:

            duration_ms = (
                time.perf_counter() - started
            ) * 1000

            log_event(
                logger,
                "http.request_failed",
                level=logging.ERROR,
                method=request.method,
                route=get_route_template(request),
                duration_ms=round(
                    duration_ms, 2
                ),
            )

            raise

        duration_ms = (
            time.perf_counter() - started
        ) * 1000

        log_event(
            logger,
            "http.request_completed",
            method=request.method,
            route=get_route_template(request),
            status_code=response.status_code,
            duration_ms=round(
                duration_ms, 2
            ),
        )

        return response


# ============================================================
# PROMETHEUS METRICS MIDDLEWARE
# ============================================================

class MetricsMiddleware(
    BaseHTTPMiddleware
):

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:

        started = time.perf_counter()

        metrics.http_in_flight.inc()

        response = None

        try:

            response = await call_next(
                request
            )

            return response

        finally:

            duration = (
                time.perf_counter() - started
            )

            metrics.http_in_flight.dec()

            status_code = (
                response.status_code
                if response is not None
                else 500
            )

            metrics.record_http(
                method=request.method,
                route=get_route_template(
                    request
                ),
                status_code=status_code,
                duration_seconds=duration,
            )


# ============================================================
# SECURITY HEADERS MIDDLEWARE
# ============================================================

class SecurityHeadersMiddleware(
    BaseHTTPMiddleware
):

    def __init__(
        self,
        app,
        *,
        content_security_policy: str,
    ) -> None:

        super().__init__(app)

        self.content_security_policy = (
            content_security_policy
        )

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:

        response = await call_next(
            request
        )

        response.headers[
            "X-Content-Type-Options"
        ] = "nosniff"

        response.headers[
            "X-Frame-Options"
        ] = "DENY"

        response.headers[
            "Referrer-Policy"
        ] = "no-referrer"

        response.headers[
            "Permissions-Policy"
        ] = (
            "camera=(), microphone=(), "
            "geolocation=()"
        )

        response.headers[
            "Content-Security-Policy"
        ] = self.content_security_policy

        if request.url.scheme == "https":

            response.headers[
                "Strict-Transport-Security"
            ] = (
                "max-age=31536000; "
                "includeSubDomains"
            )

        return response


# ============================================================
# REQUEST SIZE LIMIT MIDDLEWARE
# ============================================================

class RequestSizeLimitMiddleware:
    """
    Pure ASGI middleware.

    Enforces a request body limit even when
    Content-Length is absent.

    A matching Content-Length is not trusted
    as the sole enforcement mechanism.
    """

    def __init__(
        self,
        app,
        max_request_bytes: int,
    ) -> None:

        self.app = app

        self.max_request_bytes = (
            max_request_bytes
        )

    async def __call__(
        self,
        scope,
        receive,
        send,
    ) -> None:

        if scope["type"] != "http":

            await self.app(
                scope,
                receive,
                send,
            )

            return

        headers = dict(
            scope.get("headers", [])
        )

        raw_length = headers.get(
            b"content-length"
        )

        if raw_length is not None:

            try:
                declared_size = int(
                    raw_length
                )

            except ValueError:
                declared_size = -1

            if declared_size < 0:

                response = JSONResponse(
                    status_code=400,
                    content={
                        "detail": (
                            "Invalid Content-Length"
                        )
                    },
                )

                await response(
                    scope,
                    receive,
                    send,
                )

                return

            if declared_size > (
                self.max_request_bytes
            ):

                response = JSONResponse(
                    status_code=413,
                    content={
                        "detail": (
                            "Request body too large"
                        )
                    },
                )

                await response(
                    scope,
                    receive,
                    send,
                )

                return

        received_bytes = 0

        async def limited_receive():

            nonlocal received_bytes

            message = await receive()

            if message["type"] == "http.request":

                body = message.get(
                    "body", b""
                )

                received_bytes += len(
                    body
                )

                if received_bytes > (
                    self.max_request_bytes
                ):

                    raise RequestBodyTooLarge()

            return message

        response_started = False

        async def tracking_send(message):

            nonlocal response_started

            if message["type"] == (
                "http.response.start"
            ):
                response_started = True

            await send(message)

        try:

            await self.app(
                scope,
                limited_receive,
                tracking_send,
            )

        except RequestBodyTooLarge:

            if response_started:
                # A response has already begun.
                # It is unsafe to send another
                # response start message.
                raise

            response = JSONResponse(
                status_code=413,
                content={
                    "detail": (
                        "Request body too large"
                    )
                },
            )

            await response(
                scope,
                receive,
                send,
            )


class RequestBodyTooLarge(Exception):
    pass


# ============================================================
# REQUEST TIMEOUT MIDDLEWARE
# ============================================================

class RequestTimeoutMiddleware(
    BaseHTTPMiddleware
):

    def __init__(
        self,
        app,
        timeout_seconds: float,
    ) -> None:

        super().__init__(app)

        self.timeout_seconds = (
            timeout_seconds
        )

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:

        try:

            return await asyncio.wait_for(
                call_next(request),
                timeout=self.timeout_seconds,
            )

        except asyncio.TimeoutError:

            return error_response(
                status_code=504,
                message="Request timed out",
                request_id=getattr(
                    request.state,
                    "request_id",
                    None,
                ),
            )


# ============================================================
# EXCEPTION HANDLING MIDDLEWARE
# ============================================================

class ExceptionHandlingMiddleware(
    BaseHTTPMiddleware
):

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:

        try:

            return await call_next(
                request
            )

        except Exception:

            logger.exception(
                "Unhandled application exception"
            )

            return error_response(
                status_code=500,
                message="Internal server error",
                request_id=getattr(
                    request.state,
                    "request_id",
                    None,
                ),
            )


# ============================================================
# TRUSTED TENANT CONTEXT
# ============================================================

def set_verified_tenant(
    request: Request,
    tenant_id: str,
) -> None:
    """
    Call only after successful authentication
    and tenant membership authorization.

    This function does not itself verify
    authentication or authorization.
    """

    if not tenant_id.strip():
        raise ValueError(
            "tenant_id cannot be blank"
        )

    request.state.tenant_id = tenant_id


def get_verified_tenant(
    request: Request,
) -> str:

    tenant_id = getattr(
        request.state,
        "tenant_id",
        None,
    )

    if not tenant_id:
        raise PermissionError(
            "Verified tenant context missing"
        )

    return tenant_id


# ============================================================
# MIDDLEWARE REGISTRATION
# ============================================================

def register_middlewares(
    app: FastAPI,
    config: MiddlewareConfig | None = None,
) -> None:
    """
    Register middleware before the app
    starts serving requests.

    Starlette executes the last added
    middleware first on incoming requests.

    Expected request order:
      1. Request context
      2. Exception handling
      3. Request body limit
      4. Request timeout
      5. Security headers
      6. Metrics
      7. Logging
      8. FastAPI routing
    """

    config = config or MiddlewareConfig()

    if config.enable_logging:

        app.add_middleware(
            RequestLoggingMiddleware
        )

    if config.enable_metrics:

        app.add_middleware(
            MetricsMiddleware
        )

    if config.enable_security_headers:

        app.add_middleware(
            SecurityHeadersMiddleware,
            content_security_policy=(
                config.content_security_policy
            ),
        )

    if config.enable_request_timeout:

        app.add_middleware(
            RequestTimeoutMiddleware,
            timeout_seconds=(
                config.request_timeout_seconds
            ),
        )

    if config.enable_body_limit:

        app.add_middleware(
            RequestSizeLimitMiddleware,
            max_request_bytes=(
                config.max_request_bytes
            ),
        )

    app.add_middleware(
        ExceptionHandlingMiddleware
    )

    app.add_middleware(
        RequestContextMiddleware
    )
