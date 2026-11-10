from __future__ import annotations

"""Planned module: workplace notifier. Implementation pending."""

"""
backend/notifications/workplace_notifier.py

Autonomous Retail Supply Chain AI 5.0

Python 3.10+
Dependency: httpx

Features:
- Slack and Microsoft Teams workplace notifications
- Tenant-scoped destinations
- HTTPS webhook delivery
- Safe message formatting
- Severity and category metadata
- Per-destination delivery results
- Retryable/permanent error classification
- Async delivery
- Injectable HTTP transport for tests

Security:
- Webhook URLs are secrets.
- Never log webhook URLs.
- Resolve destinations from trusted configuration.
- Do not accept arbitrary webhook URLs from users.
- Do not include personal or financial secrets.
- Use a durable outbox for production retries.
"""


import asyncio
import hashlib
import json
import logging
import re

from dataclasses import dataclass
from enum import Enum
from typing import Protocol
from urllib.parse import urlsplit

import httpx


logger = logging.getLogger(__name__)


def required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def clean_text(
    value: str,
    *,
    maximum: int,
) -> str:
    text = " ".join(required(value, "text").split())

    if len(text) > maximum:
        raise ValueError(
            f"Text exceeds {maximum} characters"
        )

    return text


class WorkplacePlatform(str, Enum):
    SLACK = "slack"
    TEAMS = "teams"


class WorkplaceSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class WorkplaceCategory(str, Enum):
    INVENTORY = "inventory"
    STOCKOUT = "stockout"
    SUPPLIER = "supplier"
    WAREHOUSE = "warehouse"
    QUALITY = "quality"
    LOGISTICS = "logistics"
    FINANCE = "finance"
    SECURITY = "security"
    INCIDENT = "incident"
    ESCALATION = "escalation"
    GENERAL = "general"


@dataclass(frozen=True)
class WorkplaceDestination:
    tenant_id: str
    destination_id: str
    platform: WorkplacePlatform
    webhook_url: str
    enabled: bool = True
    allowed_categories: frozenset[
        WorkplaceCategory
    ] = frozenset(WorkplaceCategory)

    def __post_init__(self) -> None:
        required(self.tenant_id, "tenant_id")
        required(self.destination_id, "destination_id")

        parsed = urlsplit(self.webhook_url)

        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
        ):
            raise ValueError(
                "Webhook must be an HTTPS URL"
            )


@dataclass(frozen=True)
class WorkplacePayload:
    tenant_id: str
    event_id: str
    category: WorkplaceCategory
    severity: WorkplaceSeverity
    title: str
    message: str
    resource_id: str

    def __post_init__(self) -> None:
        required(self.tenant_id, "tenant_id")
        required(self.event_id, "event_id")
        required(self.resource_id, "resource_id")

        clean_text(self.title, maximum=150)
        clean_text(self.message, maximum=2000)


@dataclass(frozen=True)
class WorkplaceDeliveryResult:
    tenant_id: str
    event_id: str
    destination_id: str
    platform: WorkplacePlatform
    accepted: bool
    status_code: int | None
    retryable: bool
    idempotency_key: str
    error_code: str | None = None


class WorkplaceDestinationRepository(Protocol):
    """
    Implement with trusted tenant-scoped
    destination configuration.

    Never return destinations belonging
    to another tenant.
    """

    def get_destination(
        self,
        *,
        tenant_id: str,
        destination_id: str,
    ) -> WorkplaceDestination | None:
        ...


class WorkplaceHTTPTransport(Protocol):
    def post(
        self,
        url: str,
        payload: dict,
        *,
        timeout: float,
    ) -> httpx.Response:
        ...


class HTTPXWorkplaceTransport:
    def post(
        self,
        url: str,
        payload: dict,
        *,
        timeout: float,
    ) -> httpx.Response:
        # Trust no proxy configuration from
        # environment for webhook delivery.
        with httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            return client.post(
                url,
                json=payload,
                headers={
                    "Content-Type": "application/json"
                },
            )


class WorkplaceMessageFormatter:
    @staticmethod
    def _escape_slack(value: str) -> str:
        return (
            value.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    @classmethod
    def format(
        cls,
        *,
        platform: WorkplacePlatform,
        event: WorkplacePayload,
    ) -> dict:
        severity = event.severity.value.upper()

        title = clean_text(
            event.title,
            maximum=150,
        )

        message = clean_text(
            event.message,
            maximum=2000,
        )

        resource = clean_text(
            event.resource_id,
            maximum=200,
        )

        if platform == WorkplacePlatform.SLACK:
            safe_title = cls._escape_slack(title)
            safe_message = cls._escape_slack(message)
            safe_resource = cls._escape_slack(resource)

            return {
                "text": (
                    f"[Retail AI][{severity}] "
                    f"{title}"
                ),
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": title,
                        },
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"*Severity:* {severity}\n"
                                f"*Category:* "
                                f"{event.category.value}\n"
                                f"*Resource:* {safe_resource}\n"
                                f"{safe_message}"
                            ),
                        },
                    },
                ],
            }

        # Microsoft Teams Workflows.
        #
        # The receiving Power Automate workflow
        # must accept this JSON schema and post
        # the content into the configured channel.
        return {
            "type": "RetailOperationalAlert",
            "event_id": event.event_id,
            "severity": event.severity.value,
            "category": event.category.value,
            "title": title,
            "message": message,
            "resource_id": resource,
        }


class RetailWorkplaceNotifier:
    def __init__(
        self,
        *,
        repository: WorkplaceDestinationRepository,
        transport: WorkplaceHTTPTransport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be positive"
            )

        self.repository = repository
        self.transport = (
            transport or HTTPXWorkplaceTransport()
        )
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def delivery_key(
        *,
        tenant_id: str,
        event_id: str,
        destination_id: str,
    ) -> str:
        identity = json.dumps(
            {
                "tenant_id": tenant_id,
                "event_id": event_id,
                "destination_id": destination_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

        return hashlib.sha256(
            identity.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _classify_status(
        status_code: int,
    ) -> tuple[bool, bool]:
        if 200 <= status_code < 300:
            return True, False

        if (
            status_code in {408, 425, 429}
            or 500 <= status_code < 600
        ):
            return False, True

        return False, False

    def send(
        self,
        *,
        destination_id: str,
        payload: WorkplacePayload,
    ) -> WorkplaceDeliveryResult:
        destination_id = required(
            destination_id,
            "destination_id",
        )

        destination = (
            self.repository.get_destination(
                tenant_id=payload.tenant_id,
                destination_id=destination_id,
            )
        )

        if destination is None:
            raise PermissionError(
                "Workplace destination not found"
            )

        if destination.tenant_id != payload.tenant_id:
            raise PermissionError(
                "Cross-tenant workplace delivery denied"
            )

        if not destination.enabled:
            raise PermissionError(
                "Workplace destination is disabled"
            )

        if (
            payload.category
            not in destination.allowed_categories
        ):
            raise PermissionError(
                "Destination is not authorized "
                "for this alert category"
            )

        formatted = WorkplaceMessageFormatter.format(
            platform=destination.platform,
            event=payload,
        )

        key = self.delivery_key(
            tenant_id=payload.tenant_id,
            event_id=payload.event_id,
            destination_id=destination_id,
        )

        try:
            response = self.transport.post(
                destination.webhook_url,
                formatted,
                timeout=self.timeout_seconds,
            )

            accepted, retryable = (
                self._classify_status(
                    response.status_code
                )
            )

            return WorkplaceDeliveryResult(
                tenant_id=payload.tenant_id,
                event_id=payload.event_id,
                destination_id=destination_id,
                platform=destination.platform,
                accepted=accepted,
                status_code=response.status_code,
                retryable=retryable,
                idempotency_key=key,
                error_code=(
                    None
                    if accepted
                    else f"http_{response.status_code}"
                ),
            )

        except (
            httpx.TimeoutException,
            httpx.TransportError,
        ) as exc:
            logger.warning(
                "Workplace delivery transport failure: "
                "tenant=%s event=%s destination=%s",
                payload.tenant_id,
                payload.event_id,
                destination_id,
            )

            return WorkplaceDeliveryResult(
                tenant_id=payload.tenant_id,
                event_id=payload.event_id,
                destination_id=destination_id,
                platform=destination.platform,
                accepted=False,
                status_code=None,
                retryable=True,
                idempotency_key=key,
                error_code="transport_error",
            )

    async def send_async(
        self,
        *,
        destination_id: str,
        payload: WorkplacePayload,
    ) -> WorkplaceDeliveryResult:
        return await asyncio.to_thread(
            self.send,
            destination_id=destination_id,
            payload=payload,
        )


class InMemoryWorkplaceRepository:
    """
    Demo repository only.
    """

    def __init__(
        self,
        destinations: list[WorkplaceDestination],
    ) -> None:
        self.destinations = {
            (
                destination.tenant_id,
                destination.destination_id,
            ): destination
            for destination in destinations
        }

    def get_destination(
        self,
        *,
        tenant_id: str,
        destination_id: str,
    ) -> WorkplaceDestination | None:
        return self.destinations.get(
            (tenant_id, destination_id)
        )


if __name__ == "__main__":
    # This demonstration only constructs a payload.
    # It does not send an actual webhook.

    payload = WorkplacePayload(
        tenant_id="retail-demo",
        event_id="EVT001",
        category=WorkplaceCategory.INVENTORY,
        severity=WorkplaceSeverity.CRITICAL,
        title="Critical stock alert",
        message=(
            "Only 12 units remaining. "
            "Review replenishment immediately."
        ),
        resource_id="WH001:SKU001",
    )

    print(
        WorkplaceMessageFormatter.format(
            platform=WorkplacePlatform.SLACK,
            event=payload,
        )
    )
