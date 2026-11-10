from __future__ import annotations

"""Planned module: deduplication. Implementation pending."""

"""
backend/notifications/deduplication.py

Autonomous Retail Supply Chain AI 5.0

Install:
    pip install "redis>=5,<7"

Features:
- Tenant-isolated deduplication
- Event ID deduplication
- Alert-condition suppression windows
- Atomic Redis SET NX EX
- Stable SHA-256 fingerprints
- Ownership-safe claim release
- Configurable TTL
- No plaintext sensitive data in Redis keys

Important:
A Redis claim is not a substitute for a durable
database transaction or idempotent outbox consumer.
"""


import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4

from redis import Redis


class DeduplicationScope(str, Enum):
    EVENT = "event"
    CONDITION = "condition"
    DELIVERY = "delivery"


@dataclass(frozen=True)
class DeduplicationConfig:
    event_ttl_seconds: int = 86400
    condition_ttl_seconds: int = 300
    delivery_ttl_seconds: int = 86400
    key_prefix: str = "retail:dedup:v1"

    def __post_init__(self) -> None:
        for name in (
            "event_ttl_seconds",
            "condition_ttl_seconds",
            "delivery_ttl_seconds",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(
                    f"{name} must be a positive integer"
                )

        if not self.key_prefix.strip():
            raise ValueError("key_prefix is required")


@dataclass(frozen=True)
class DeduplicationResult:
    accepted: bool
    fingerprint: str
    scope: DeduplicationScope
    claim_token: str | None
    ttl_seconds: int


_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


def required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


class RetailDeduplication:
    def __init__(
        self,
        redis_client: Redis,
        config: DeduplicationConfig | None = None,
    ) -> None:
        self.redis = redis_client
        self.config = config or DeduplicationConfig()

    @staticmethod
    def fingerprint(
        *,
        tenant_id: str,
        scope: DeduplicationScope,
        identity: Mapping[str, Any],
    ) -> str:
        tenant_id = required(tenant_id, "tenant_id")

        if not isinstance(scope, DeduplicationScope):
            raise ValueError("Invalid deduplication scope")

        if not identity:
            raise ValueError("Identity cannot be empty")

        canonical = json.dumps(
            {
                "tenant_id": tenant_id,
                "scope": scope.value,
                "identity": dict(identity),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

        return hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()

    def _ttl(self, scope: DeduplicationScope) -> int:
        return {
            DeduplicationScope.EVENT:
                self.config.event_ttl_seconds,
            DeduplicationScope.CONDITION:
                self.config.condition_ttl_seconds,
            DeduplicationScope.DELIVERY:
                self.config.delivery_ttl_seconds,
        }[scope]

    def _key(
        self,
        scope: DeduplicationScope,
        fingerprint: str,
    ) -> str:
        return (
            f"{self.config.key_prefix}:"
            f"{scope.value}:{fingerprint}"
        )

    def claim(
        self,
        *,
        tenant_id: str,
        scope: DeduplicationScope,
        identity: Mapping[str, Any],
        ttl_seconds: int | None = None,
    ) -> DeduplicationResult:
        fingerprint = self.fingerprint(
            tenant_id=tenant_id,
            scope=scope,
            identity=identity,
        )

        ttl = (
            self._ttl(scope)
            if ttl_seconds is None
            else ttl_seconds
        )

        if type(ttl) is not int or ttl <= 0:
            raise ValueError("TTL must be positive")

        token = str(uuid4())
        key = self._key(scope, fingerprint)

        accepted = bool(
            self.redis.set(
                key,
                token,
                nx=True,
                ex=ttl,
            )
        )

        return DeduplicationResult(
            accepted=accepted,
            fingerprint=fingerprint,
            scope=scope,
            claim_token=token if accepted else None,
            ttl_seconds=ttl,
        )

    def release(
        self,
        *,
        tenant_id: str,
        scope: DeduplicationScope,
        identity: Mapping[str, Any],
        claim_token: str,
    ) -> bool:
        fingerprint = self.fingerprint(
            tenant_id=tenant_id,
            scope=scope,
            identity=identity,
        )

        key = self._key(scope, fingerprint)

        deleted = self.redis.eval(
            _RELEASE_SCRIPT,
            1,
            key,
            required(claim_token, "claim_token"),
        )

        return bool(deleted)

    def claim_event(
        self,
        *,
        tenant_id: str,
        source_system: str,
        event_id: str,
    ) -> DeduplicationResult:
        return self.claim(
            tenant_id=tenant_id,
            scope=DeduplicationScope.EVENT,
            identity={
                "source_system": required(
                    source_system, "source_system"
                ),
                "event_id": required(
                    event_id, "event_id"
                ),
            },
        )

    def claim_condition(
        self,
        *,
        tenant_id: str,
        rule_code: str,
        resource_id: str,
        severity: str,
    ) -> DeduplicationResult:
        return self.claim(
            tenant_id=tenant_id,
            scope=DeduplicationScope.CONDITION,
            identity={
                "rule_code": required(
                    rule_code, "rule_code"
                ),
                "resource_id": required(
                    resource_id, "resource_id"
                ),
                "severity": required(
                    severity, "severity"
                ),
            },
        )

    def claim_delivery(
        self,
        *,
        tenant_id: str,
        event_id: str,
        user_id: str,
        channel: str = "dashboard",
    ) -> DeduplicationResult:
        return self.claim(
            tenant_id=tenant_id,
            scope=DeduplicationScope.DELIVERY,
            identity={
                "event_id": required(
                    event_id, "event_id"
                ),
                "user_id": required(
                    user_id, "user_id"
                ),
                "channel": required(
                    channel, "channel"
                ),
            },
        )


if __name__ == "__main__":
    # Requires a running Redis instance.
    redis_client = Redis.from_url(
        "redis://localhost:6379/0",
        decode_responses=True,
    )

    dedup = RetailDeduplication(redis_client)

    first = dedup.claim_condition(
        tenant_id="retail-demo",
        rule_code="LOW_STOCK",
        resource_id="WH001:SKU001",
        severity="critical",
    )

    second = dedup.claim_condition(
        tenant_id="retail-demo",
        rule_code="LOW_STOCK",
        resource_id="WH001:SKU001",
        severity="critical",
    )

    print("First accepted:", first.accepted)
    print("Second accepted:", second.accepted)
