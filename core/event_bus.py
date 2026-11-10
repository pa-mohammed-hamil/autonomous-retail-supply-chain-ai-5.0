from __future__ import annotations

"""Planned module: event bus. Implementation pending."""

"""
backend/event_bus.py

Autonomous Retail Supply Chain AI 5.0

Redis Streams event bus.

Python 3.10+
redis-py >= 5

Features:
- Tenant-scoped event streams
- Structured JSON events
- Event schema versioning
- Redis consumer groups
- At-least-once delivery
- Message acknowledgment
- Retryable pending messages
- Dead-letter stream
- Handler registration
- Basic observability
- No arbitrary code deserialization

Production requirements:
- Durable transactional outbox
- Idempotent event handlers
- Tenant authorization
- Redis persistence and monitoring
"""


import json
import logging
import os
import time
import uuid

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

import redis
from redis.exceptions import (
    ResponseError,
    RedisError,
)


logger = logging.getLogger(__name__)


class EventBusError(RuntimeError):
    pass


class EventType(str, Enum):
    INVENTORY_LOW = "inventory.low"
    INVENTORY_STOCKOUT = "inventory.stockout"
    INVENTORY_TRANSFERRED = "inventory.transferred"

    PRODUCT_CREATED = "product.created"
    PRODUCT_UPDATED = "product.updated"

    SUPPLIER_DELAYED = "supplier.delayed"
    SUPPLIER_RISK_HIGH = "supplier.risk_high"

    PURCHASE_ORDER_CREATED = (
        "purchase_order.created"
    )
    PURCHASE_ORDER_APPROVED = (
        "purchase_order.approved"
    )

    SHIPMENT_DELAYED = "shipment.delayed"
    SHIPMENT_DELIVERED = "shipment.delivered"

    FORECAST_COMPLETED = "forecast.completed"

    INCIDENT_CREATED = "incident.created"
    INCIDENT_RESOLVED = "incident.resolved"

    NOTIFICATION_REQUESTED = (
        "notification.requested"
    )


@dataclass(frozen=True)
class Event:
    event_type: str
    tenant_id: str
    payload: dict[str, Any]

    event_id: str = field(
        default_factory=lambda: str(uuid.uuid4())
    )

    schema_version: int = 1

    occurred_at: str = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        ).isoformat()
    )

    correlation_id: str | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id.strip():
            raise ValueError(
                "tenant_id is required"
            )

        if not self.event_type.strip():
            raise ValueError(
                "event_type is required"
            )

        if not isinstance(self.payload, dict):
            raise ValueError(
                "payload must be a dictionary"
            )

        if self.schema_version < 1:
            raise ValueError(
                "schema_version must be positive"
            )

    def to_json(self) -> str:
        return json.dumps(
            {
                "event_id": self.event_id,
                "event_type": self.event_type,
                "tenant_id": self.tenant_id,
                "payload": self.payload,
                "schema_version": self.schema_version,
                "occurred_at": self.occurred_at,
                "correlation_id": self.correlation_id,
            },
            separators=(",", ":"),
            allow_nan=False,
        )

    @classmethod
    def from_json(cls, raw: str) -> "Event":
        data = json.loads(raw)

        if not isinstance(data, dict):
            raise ValueError(
                "Invalid event envelope"
            )

        return cls(
            event_id=data["event_id"],
            event_type=data["event_type"],
            tenant_id=data["tenant_id"],
            payload=data["payload"],
            schema_version=data["schema_version"],
            occurred_at=data["occurred_at"],
            correlation_id=data.get(
                "correlation_id"
            ),
        )


@dataclass(frozen=True)
class EventBusConfig:
    redis_url: str
    stream_prefix: str = "retail:events"
    max_stream_length: int = 100_000
    block_ms: int = 2000
    batch_size: int = 10
    max_attempts: int = 5
    retry_idle_ms: int = 30_000

    @classmethod
    def from_env(cls) -> "EventBusConfig":
        return cls(
            redis_url=os.environ.get(
                "REDIS_URL",
                "redis://localhost:6379/0",
            )
        )

    def __post_init__(self) -> None:
        if not self.redis_url.startswith(
            ("redis://", "rediss://")
        ):
            raise ValueError(
                "Invalid Redis URL"
            )

        if self.max_stream_length < 1:
            raise ValueError(
                "Invalid stream length"
            )

        if self.batch_size < 1:
            raise ValueError(
                "Invalid batch size"
            )

        if self.max_attempts < 1:
            raise ValueError(
                "Invalid max_attempts"
            )


EventHandler = Callable[[Event], None]


class RetailEventBus:
    def __init__(
        self,
        config: EventBusConfig,
        client: redis.Redis | None = None,
    ) -> None:
        self.config = config

        self.client = client or redis.Redis.from_url(
            config.redis_url,
            decode_responses=True,
            socket_timeout=10,
            socket_connect_timeout=5,
            health_check_interval=30,
        )

        self.handlers: dict[
            str, list[EventHandler]
        ] = {}

    def stream_name(
        self,
        tenant_id: str,
    ) -> str:
        if not tenant_id.strip():
            raise ValueError(
                "tenant_id is required"
            )

        # Tenant IDs are not inserted directly
        # into Redis key names.
        import hashlib

        tenant_key = hashlib.sha256(
            tenant_id.encode("utf-8")
        ).hexdigest()[:24]

        return (
            f"{self.config.stream_prefix}:"
            f"{tenant_key}"
        )

    def dead_letter_stream(
        self,
        tenant_id: str,
    ) -> str:
        return (
            self.stream_name(tenant_id)
            + ":dead"
        )

    def publish(
        self,
        event: Event,
    ) -> str:
        """
        Append an event to Redis Streams.

        Publishing is not atomic with
        PostgreSQL transactions.
        """
        stream = self.stream_name(
            event.tenant_id
        )

        message_id = self.client.xadd(
            stream,
            {"event": event.to_json()},
            maxlen=self.config.max_stream_length,
            approximate=True,
        )

        logger.info(
            "Published event type=%s id=%s",
            event.event_type,
            event.event_id,
        )

        return str(message_id)

    def register_handler(
        self,
        event_type: str,
        handler: EventHandler,
    ) -> None:
        if not callable(handler):
            raise TypeError(
                "handler must be callable"
            )

        self.handlers.setdefault(
            event_type, []
        ).append(handler)

    def create_consumer_group(
        self,
        *,
        tenant_id: str,
        group: str,
    ) -> None:
        if not group.strip():
            raise ValueError(
                "group is required"
            )

        stream = self.stream_name(
            tenant_id
        )

        try:
            self.client.xgroup_create(
                stream,
                group,
                id="0",
                mkstream=True,
            )

        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def _dispatch(
        self,
        event: Event,
    ) -> None:
        handlers = self.handlers.get(
            event.event_type, []
        )

        for handler in handlers:
            handler(event)

    def _dead_letter(
        self,
        *,
        tenant_id: str,
        message_id: str,
        event_raw: str,
        reason: str,
    ) -> None:
        self.client.xadd(
            self.dead_letter_stream(
                tenant_id
            ),
            {
                "source_message_id": message_id,
                "event": event_raw,
                "reason": reason[:500],
                "failed_at": datetime.now(
                    timezone.utc
                ).isoformat(),
            },
        )

    def _process_message(
        self,
        *,
        tenant_id: str,
        group: str,
        message_id: str,
        fields: dict[str, str],
        delivery_count: int = 1,
    ) -> bool:
        stream = self.stream_name(
            tenant_id
        )

        raw = fields.get("event", "")

        try:
            event = Event.from_json(raw)

            if event.tenant_id != tenant_id:
                raise EventBusError(
                    "Tenant mismatch"
                )

            self._dispatch(event)

            self.client.xack(
                stream,
                group,
                message_id,
            )

            return True

        except Exception as exc:
            logger.exception(
                "Event processing failed"
            )

            if (
                delivery_count
                >= self.config.max_attempts
            ):
                # DLQ append must succeed before
                # acknowledging the source.
                self._dead_letter(
                    tenant_id=tenant_id,
                    message_id=message_id,
                    event_raw=raw,
                    reason=type(exc).__name__,
                )

                self.client.xack(
                    stream,
                    group,
                    message_id,
                )

            return False

    def consume_once(
        self,
        *,
        tenant_id: str,
        group: str,
        consumer: str,
    ) -> int:
        """
        Read new messages for one consumer.

        Pending messages must be recovered
        separately using recover_pending().
        """
        if not consumer.strip():
            raise ValueError(
                "consumer is required"
            )

        self.create_consumer_group(
            tenant_id=tenant_id,
            group=group,
        )

        stream = self.stream_name(
            tenant_id
        )

        messages = self.client.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">"},
            count=self.config.batch_size,
            block=self.config.block_ms,
        )

        processed = 0

        for _, entries in messages:
            for message_id, fields in entries:
                if self._process_message(
                    tenant_id=tenant_id,
                    group=group,
                    message_id=message_id,
                    fields=fields,
                ):
                    processed += 1

        return processed

    def recover_pending(
        self,
        *,
        tenant_id: str,
        group: str,
        consumer: str,
    ) -> int:
        """
        Claim messages idle long enough
        to be retried by this consumer.

        Requires Redis 6.2+.
        """
        stream = self.stream_name(
            tenant_id
        )

        self.create_consumer_group(
            tenant_id=tenant_id,
            group=group,
        )

        result = self.client.xautoclaim(
            stream,
            group,
            consumer,
            min_idle_time=(
                self.config.retry_idle_ms
            ),
            start_id="0-0",
            count=self.config.batch_size,
        )

        entries = result[1]
        processed = 0

        for message_id, fields in entries:
            pending = self.client.xpending_range(
                stream,
                group,
                min=message_id,
                max=message_id,
                count=1,
            )

            deliveries = (
                pending[0]["times_delivered"]
                if pending
                else 1
            )

            if self._process_message(
                tenant_id=tenant_id,
                group=group,
                message_id=message_id,
                fields=fields,
                delivery_count=deliveries,
            ):
                processed += 1

        return processed

    def consume_forever(
        self,
        *,
        tenant_id: str,
        group: str,
        consumer: str,
        poll_delay_seconds: float = 0.1,
    ) -> None:
        """
        Run one worker loop.

        Stop through process supervision
        or KeyboardInterrupt.
        """
        while True:
            try:
                self.recover_pending(
                    tenant_id=tenant_id,
                    group=group,
                    consumer=consumer,
                )

                self.consume_once(
                    tenant_id=tenant_id,
                    group=group,
                    consumer=consumer,
                )

            except RedisError:
                logger.exception(
                    "Redis event bus unavailable"
                )
                time.sleep(2)

            except KeyboardInterrupt:
                break

            time.sleep(
                poll_delay_seconds
            )

    def health_check(self) -> bool:
        try:
            return bool(self.client.ping())
        except RedisError:
            return False

    def close(self) -> None:
        self.client.close()


def create_event_bus() -> RetailEventBus:
    return RetailEventBus(
        EventBusConfig.from_env()
    )
