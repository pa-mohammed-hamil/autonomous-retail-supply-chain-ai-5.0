from __future__ import annotations

"""Planned module: rate limit. Implementation pending."""

"""
backend/rate_limit.py

Autonomous Retail Supply Chain AI 5.0

Distributed FastAPI rate limiting.

Dependencies:
    fastapi
    redis >= 5

Features:
- Redis-backed distributed limits
- Atomic Lua counter updates
- Fixed-window rate limiting
- Per-user and per-tenant limits
- Endpoint-specific policies
- Authentication endpoint protection
- Retry-After response headers
- Standard rate-limit response headers
- Fail-closed protected endpoints
- Safe Redis key construction
- FastAPI middleware integration

Security:
- Never trust X-User-ID or X-Tenant-ID.
- Use authenticated server-side identity.
- Do not use user-provided strings as
  Redis key components without hashing.
- Rate limiting does not replace RBAC.
- Fixed windows permit boundary bursts.
"""


import hashlib
import math
import os
import re

from dataclasses import dataclass
from typing import Any

import redis

from fastapi import FastAPI
from starlette.responses import JSONResponse

from backend.permissions import Principal


# ============================================================
# EXCEPTIONS
# ============================================================

class RateLimitError(RuntimeError):
    pass


class RateLimitUnavailable(RateLimitError):
    pass


# ============================================================
# POLICIES
# ============================================================

@dataclass(frozen=True)
class RateLimitPolicy:

    name: str
    limit: int
    window_seconds: int

    # "user" and "tenant" require verified
    # authentication context.
    scope: str = "user"

    fail_closed: bool = True

    def __post_init__(self) -> None:

        if not re.fullmatch(
            r"[a-z0-9_]{1,64}",
            self.name,
        ):
            raise ValueError(
                "Invalid policy name"
            )

        if self.limit < 1:
            raise ValueError(
                "limit must be positive"
            )

        if self.window_seconds < 1:
            raise ValueError(
                "window_seconds must be positive"
            )

        if self.scope not in {
            "user",
            "tenant",
            "client",
        }:
            raise ValueError(
                "Unsupported rate-limit scope"
            )


# ============================================================
# DEFAULT RATE LIMITS
# ============================================================

DEFAULT_POLICIES = {

    "default": RateLimitPolicy(
        name="default",
        limit=120,
        window_seconds=60,
        scope="user",
    ),

    "authentication": RateLimitPolicy(
        name="authentication",
        limit=5,
        window_seconds=60,
        scope="client",
    ),

    "inventory_read": RateLimitPolicy(
        name="inventory_read",
        limit=120,
        window_seconds=60,
        scope="user",
    ),

    "inventory_write": RateLimitPolicy(
        name="inventory_write",
        limit=30,
        window_seconds=60,
        scope="user",
    ),

    "procurement_write": RateLimitPolicy(
        name="procurement_write",
        limit=10,
        window_seconds=60,
        scope="user",
    ),

    "rag_query": RateLimitPolicy(
        name="rag_query",
        limit=20,
        window_seconds=60,
        scope="user",
    ),

    "ai_agent": RateLimitPolicy(
        name="ai_agent",
        limit=10,
        window_seconds=60,
        scope="user",
    ),

    "ai_generation": RateLimitPolicy(
        name="ai_generation",
        limit=5,
        window_seconds=60,
        scope="user",
    ),

    "notification_send": RateLimitPolicy(
        name="notification_send",
        limit=30,
        window_seconds=60,
        scope="tenant",
    ),

    "integration": RateLimitPolicy(
        name="integration",
        limit=60,
        window_seconds=60,
        scope="tenant",
    ),
}


# ============================================================
# CONFIGURATION
# ============================================================

@dataclass(frozen=True)
class RateLimitConfig:

    redis_url: str

    key_prefix: str = "retail:rate_limit"

    redis_timeout_seconds: float = 2.0

    @classmethod
    def from_env(
        cls,
    ) -> "RateLimitConfig":

        return cls(
            redis_url=os.getenv(
                "REDIS_URL",
                "redis://localhost:6379/0",
            ),
            key_prefix=os.getenv(
                "RATE_LIMIT_PREFIX",
                "retail:rate_limit",
            ),
        )


# ============================================================
# ATOMIC LUA SCRIPT
# ============================================================

RATE_LIMIT_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])

-- Redis server time is shared by clients.
local now = redis.call('TIME')
local now_ms =
    tonumber(now[1]) * 1000 +
    math.floor(tonumber(now[2]) / 1000)

local window_id =
    math.floor(now_ms / window_ms)

local bucket_key =
    key .. ':' .. tostring(window_id)

local count = redis.call(
    'INCR',
    bucket_key
)

if count == 1 then
    redis.call(
        'PEXPIRE',
        bucket_key,
        window_ms * 2
    )
end

local remaining = math.max(
    0,
    limit - count
)

local retry_ms =
    window_ms - (now_ms % window_ms)

local allowed = 0

if count <= limit then
    allowed = 1
end

return {
    allowed,
    remaining,
    retry_ms,
    count
}
"""


# ============================================================
# DECISION MODEL
# ============================================================

@dataclass(frozen=True)
class RateLimitDecision:

    allowed: bool

    limit: int

    remaining: int

    retry_after_seconds: int

    policy: str


# ============================================================
# REDIS RATE LIMITER
# ============================================================

class RedisRateLimiter:

    def __init__(
        self,
        config: RateLimitConfig,
        client: redis.Redis | None = None,
    ) -> None:

        self.config = config

        self.client = (
            client
            or redis.Redis.from_url(
                config.redis_url,
                decode_responses=True,
                socket_timeout=(
                    config.redis_timeout_seconds
                ),
                socket_connect_timeout=(
                    config.redis_timeout_seconds
                ),
                health_check_interval=30,
            )
        )

        self._script = (
            self.client.register_script(
                RATE_LIMIT_SCRIPT
            )
        )

    @staticmethod
    def _hash_identity(
        identity: str,
    ) -> str:

        return hashlib.sha256(
            identity.encode("utf-8")
        ).hexdigest()

    def _make_key(
        self,
        policy: RateLimitPolicy,
        identity: str,
    ) -> str:

        if not identity:
            raise ValueError(
                "Rate-limit identity required"
            )

        digest = self._hash_identity(
            identity
        )

        return (
            f"{self.config.key_prefix}:"
            f"{policy.name}:{digest}"
        )

    def check(
        self,
        *,
        policy: RateLimitPolicy,
        identity: str,
    ) -> RateLimitDecision:

        key = self._make_key(
            policy,
            identity,
        )

        try:

            result = self._script(
                keys=[key],
                args=[
                    policy.limit,
                    policy.window_seconds * 1000,
                ],
            )

            allowed = bool(
                int(result[0])
            )

            remaining = int(
                result[1]
            )

            retry_after = math.ceil(
                int(result[2]) / 1000
            )

            return RateLimitDecision(
                allowed=allowed,
                limit=policy.limit,
                remaining=remaining,
                retry_after_seconds=(
                    retry_after
                ),
                policy=policy.name,
            )

        except redis.RedisError as exc:

            if policy.fail_closed:

                raise RateLimitUnavailable(
                    "Rate limiter unavailable"
                ) from exc

            return RateLimitDecision(
                allowed=True,
                limit=policy.limit,
                remaining=0,
                retry_after_seconds=0,
                policy=policy.name,
            )

    def health_check(self) -> bool:

        try:
            return bool(
                self.client.ping()
            )

        except redis.RedisError:
            return False

    def close(self) -> None:
        self.client.close()


# ============================================================
# ROUTE POLICY MATCHING
# ============================================================

@dataclass(frozen=True)
class RoutePolicy:

    method: str

    path_pattern: str

    policy_name: str

    def matches(
        self,
        method: str,
        path: str,
    ) -> bool:

        return (
            method.upper()
            == self.method.upper()
            and re.fullmatch(
                self.path_pattern,
                path,
            ) is not None
        )


DEFAULT_ROUTE_POLICIES = [

    RoutePolicy(
        "POST",
        r"/api/v1/auth/login",
        "authentication",
    ),

    RoutePolicy(
        "POST",
        r"/api/v1/auth/register",
        "authentication",
    ),

    RoutePolicy(
        "GET",
        r"/api/v1/inventory(?:/.*)?",
        "inventory_read",
    ),

    RoutePolicy(
        "POST",
        r"/api/v1/inventory(?:/.*)?",
        "inventory_write",
    ),

    RoutePolicy(
        "POST",
        r"/api/v1/procurement(?:/.*)?",
        "procurement_write",
    ),

    RoutePolicy(
        "POST",
        r"/api/v1/rag/query",
        "rag_query",
    ),

    RoutePolicy(
        "POST",
        r"/api/v1/agents(?:/.*)?",
        "ai_agent",
    ),

    RoutePolicy(
        "POST",
        r"/api/v1/ai/generate",
        "ai_generation",
    ),

    RoutePolicy(
        "POST",
        r"/api/v1/notifications/send",
        "notification_send",
    ),

    RoutePolicy(
        "POST",
        r"/api/v1/integrations(?:/.*)?",
        "integration",
    ),
]


# ============================================================
# ASGI RATE LIMIT MIDDLEWARE
# ============================================================

class RateLimitMiddleware:
    """
    Pure ASGI middleware.

    Place after trusted authentication
    middleware for user/tenant policies.

    Anonymous authentication endpoints
    use a server-derived client identity.
    """

    def __init__(
        self,
        app,
        *,
        limiter: RedisRateLimiter,
        policies: dict[
            str, RateLimitPolicy
        ] | None = None,
        routes: list[
            RoutePolicy
        ] | None = None,
    ) -> None:

        self.app = app
        self.limiter = limiter

        self.policies = (
            policies or DEFAULT_POLICIES
        )

        self.routes = (
            routes or DEFAULT_ROUTE_POLICIES
        )

    def _select_policy(
        self,
        method: str,
        path: str,
    ) -> RateLimitPolicy:

        for route in self.routes:

            if route.matches(
                method,
                path,
            ):

                return self.policies[
                    route.policy_name
                ]

        return self.policies["default"]

    @staticmethod
    def _principal(
        scope: dict[str, Any],
    ) -> Principal | None:

        state = scope.get(
            "state",
            {}
        )

        principal = state.get(
            "principal"
        )

        if isinstance(
            principal,
            Principal,
        ):
            return principal

        return None

    def _identity(
        self,
        scope: dict[str, Any],
        policy: RateLimitPolicy,
    ) -> str | None:

        principal = self._principal(
            scope
        )

        if policy.scope == "user":

            if principal is None:
                return None

            return (
                f"{principal.tenant_id}:"
                f"{principal.principal_id}"
            )

        if policy.scope == "tenant":

            if principal is None:
                return None

            return principal.tenant_id

        # ASGI client address is acceptable
        # only when proxy headers are
        # configured with trusted proxy rules.
        client = scope.get(
            "client"
        )

        if client is None:
            return None

        return str(client[0])

    @staticmethod
    async def _send_response(
        scope,
        receive,
        send,
        *,
        status_code: int,
        message: str,
        retry_after: int | None = None,
    ) -> None:

        headers = {}

        if retry_after is not None:
            headers["Retry-After"] = str(
                retry_after
            )

        response = JSONResponse(
            status_code=status_code,
            content={
                "success": False,
                "error": message,
            },
            headers=headers,
        )

        await response(
            scope,
            receive,
            send,
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

        method = scope.get(
            "method",
            "GET",
        )

        path = scope.get(
            "path",
            "/",
        )

        policy = self._select_policy(
            method,
            path,
        )

        identity = self._identity(
            scope,
            policy,
        )

        if identity is None:

            await self._send_response(
                scope,
                receive,
                send,
                status_code=401,
                message=(
                    "Authenticated identity "
                    "required"
                ),
            )

            return

        try:

            decision = self.limiter.check(
                policy=policy,
                identity=identity,
            )

        except RateLimitUnavailable:

            await self._send_response(
                scope,
                receive,
                send,
                status_code=503,
                message=(
                    "Rate limiting service "
                    "temporarily unavailable"
                ),
            )

            return

        if not decision.allowed:

            await self._send_response(
                scope,
                receive,
                send,
                status_code=429,
                message=(
                    "Rate limit exceeded"
                ),
                retry_after=(
                    decision.retry_after_seconds
                ),
            )

            return

        async def send_with_headers(
            message,
        ):

            if message["type"] == (
                "http.response.start"
            ):

                headers = list(
                    message.get(
                        "headers",
                        [],
                    )
                )

                headers.extend([
                    (
                        b"x-ratelimit-limit",
                        str(
                            decision.limit
                        ).encode(),
                    ),
                    (
                        b"x-ratelimit-remaining",
                        str(
                            decision.remaining
                        ).encode(),
                    ),
                ])

                message["headers"] = headers

            await send(message)

        await self.app(
            scope,
            receive,
            send_with_headers,
        )


# ============================================================
# FASTAPI REGISTRATION
# ============================================================

def register_rate_limiting(
    app: FastAPI,
    *,
    redis_url: str | None = None,
) -> RedisRateLimiter:

    config = RateLimitConfig(
        redis_url=(
            redis_url
            or RateLimitConfig.from_env().redis_url
        )
    )

    limiter = RedisRateLimiter(
        config
    )

    app.add_middleware(
        RateLimitMiddleware,
        limiter=limiter,
    )

    return limiter
