from __future__ import annotations

"""Planned module: sms notifier. Implementation pending."""

"""
backend/notifications/sms_notifier.py

Autonomous Retail Supply Chain AI 5.0

Python 3.10+
Twilio SMS integration

Features:
- Tenant-aware SMS requests
- Verified recipient phone numbers
- Severity-based SMS templates
- E.164 phone validation
- Async-compatible provider delivery
- Provider message IDs
- Retry classification
- Structured SMS results
- Optional SMS gateway abstraction

Important:
- Recipient authorization is enforced upstream.
- Never trust phone numbers supplied by an
  unauthenticated notification request.
- SMS provider acceptance is not final delivery.
- Persist requests before sending.
"""


import asyncio
import logging
import os
import re

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from twilio.base.exceptions import (
    TwilioRestException,
)
from twilio.http.http_client import TwilioHttpClient
from twilio.rest import Client


logger = logging.getLogger(__name__)


E164_PATTERN = re.compile(
    r"^\+[1-9]\d{1,14}$"
)


def required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{name} is required"
        )
    return value.strip()


def validate_phone(value: str) -> str:
    phone = required(value, "phone")

    if not E164_PATTERN.fullmatch(phone):
        raise ValueError(
            "Phone number must use E.164 format"
        )

    return phone


class SMSSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SMSCategory(str, Enum):
    INVENTORY = "inventory"
    STOCKOUT = "stockout"
    SUPPLIER = "supplier"
    WAREHOUSE = "warehouse"
    QUALITY = "quality"
    LOGISTICS = "logistics"
    FINANCE = "finance"
    INCIDENT = "incident"
    SECURITY = "security"


@dataclass(frozen=True)
class SMSConfig:
    account_sid: str
    auth_token: str
    from_number: str
    timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        required(
            self.account_sid,
            "account_sid",
        )

        required(
            self.auth_token,
            "auth_token",
        )

        validate_phone(
            self.from_number
        )

        if self.timeout_seconds <= 0:
            raise ValueError(
                "timeout_seconds must be positive"
            )

    @classmethod
    def from_env(cls) -> "SMSConfig":
        return cls(
            account_sid=os.environ[
                "TWILIO_ACCOUNT_SID"
            ],
            auth_token=os.environ[
                "TWILIO_AUTH_TOKEN"
            ],
            from_number=os.environ[
                "TWILIO_FROM_NUMBER"
            ],
            timeout_seconds=float(
                os.environ.get(
                    "SMS_TIMEOUT_SECONDS",
                    "15",
                )
            ),
        )


@dataclass(frozen=True)
class SMSRecipient:
    tenant_id: str
    user_id: str
    phone_number: str
    phone_verified: bool
    sms_enabled: bool
    active: bool

    def __post_init__(self) -> None:
        required(
            self.tenant_id,
            "tenant_id",
        )

        required(
            self.user_id,
            "user_id",
        )

        validate_phone(
            self.phone_number
        )


@dataclass(frozen=True)
class SMSPayload:
    tenant_id: str
    event_id: str
    category: SMSCategory
    severity: SMSSeverity
    resource_id: str
    title: str
    message: str

    def __post_init__(self) -> None:
        for field_name in (
            "tenant_id",
            "event_id",
            "resource_id",
            "title",
            "message",
        ):
            required(
                getattr(self, field_name),
                field_name,
            )

        if len(self.title) > 100:
            raise ValueError(
                "SMS title is too long"
            )

        if len(self.message) > 600:
            raise ValueError(
                "SMS message is too long"
            )


@dataclass(frozen=True)
class SMSResult:
    tenant_id: str
    event_id: str
    recipient_user_id: str
    accepted: bool
    provider_message_id: str | None
    provider_status: str | None
    retryable: bool
    error_code: str | None = None


class SMSDeliveryError(Exception):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        error_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.error_code = error_code


class SMSGateway(Protocol):
    def send(
        self,
        *,
        to_number: str,
        body: str,
    ) -> tuple[str, str]:
        """
        Returns:
            provider_message_id, provider_status
        """
        ...


class TwilioSMSGateway:
    def __init__(
        self,
        config: SMSConfig,
    ) -> None:
        self.config = config

        http_client = TwilioHttpClient(
            timeout=config.timeout_seconds
        )

        self.client = Client(
            config.account_sid,
            config.auth_token,
            http_client=http_client,
        )

    def send(
        self,
        *,
        to_number: str,
        body: str,
    ) -> tuple[str, str]:
        validate_phone(to_number)

        try:
            response = (
                self.client.messages.create(
                    from_=self.config.from_number,
                    to=to_number,
                    body=body,
                )
            )

            return (
                str(response.sid),
                str(response.status),
            )

        except TwilioRestException as exc:
            status = exc.status

            # Temporary provider errors and
            # rate limits may be retried.
            retryable = (
                status == 429
                or 500 <= status < 600
            )

            raise SMSDeliveryError(
                "SMS provider rejected request",
                retryable=retryable,
                error_code=str(exc.code),
            ) from exc

        except (
            TimeoutError,
            OSError,
        ) as exc:
            raise SMSDeliveryError(
                "SMS provider transport failure",
                retryable=True,
                error_code="transport_error",
            ) from exc


class RetailSMSTemplates:
    @staticmethod
    def render(
        payload: SMSPayload,
    ) -> str:
        severity = (
            payload.severity.value.upper()
        )

        title = " ".join(
            payload.title.split()
        )

        message = " ".join(
            payload.message.split()
        )

        resource = " ".join(
            payload.resource_id.split()
        )

        body = (
            f"[Retail AI][{severity}] "
            f"{title}. "
            f"{message} "
            f"Ref: {resource}."
        )

        if len(body) > 900:
            raise ValueError(
                "Rendered SMS exceeds safety limit"
            )

        return body


class RetailSMSNotifier:
    def __init__(
        self,
        gateway: SMSGateway,
    ) -> None:
        self.gateway = gateway

    @staticmethod
    def _authorize(
        recipient: SMSRecipient,
        payload: SMSPayload,
    ) -> None:
        if (
            recipient.tenant_id
            != payload.tenant_id
        ):
            raise PermissionError(
                "Cross-tenant SMS denied"
            )

        if not recipient.active:
            raise PermissionError(
                "Recipient account is inactive"
            )

        if not recipient.phone_verified:
            raise PermissionError(
                "Recipient phone is unverified"
            )

        if not recipient.sms_enabled:
            raise PermissionError(
                "SMS notifications are disabled"
            )

    def send(
        self,
        *,
        recipient: SMSRecipient,
        payload: SMSPayload,
    ) -> SMSResult:
        self._authorize(
            recipient,
            payload,
        )

        body = RetailSMSTemplates.render(
            payload
        )

        try:
            message_id, status = (
                self.gateway.send(
                    to_number=recipient.phone_number,
                    body=body,
                )
            )

            logger.info(
                "SMS accepted: tenant=%s "
                "event=%s user=%s",
                payload.tenant_id,
                payload.event_id,
                recipient.user_id,
            )

            return SMSResult(
                tenant_id=payload.tenant_id,
                event_id=payload.event_id,
                recipient_user_id=recipient.user_id,
                accepted=True,
                provider_message_id=message_id,
                provider_status=status,
                retryable=False,
            )

        except SMSDeliveryError as exc:
            logger.warning(
                "SMS failure: tenant=%s "
                "event=%s retryable=%s",
                payload.tenant_id,
                payload.event_id,
                exc.retryable,
            )

            return SMSResult(
                tenant_id=payload.tenant_id,
                event_id=payload.event_id,
                recipient_user_id=recipient.user_id,
                accepted=False,
                provider_message_id=None,
                provider_status=None,
                retryable=exc.retryable,
                error_code=exc.error_code,
            )

    async def send_async(
        self,
        *,
        recipient: SMSRecipient,
        payload: SMSPayload,
    ) -> SMSResult:
        return await asyncio.to_thread(
            self.send,
            recipient=recipient,
            payload=payload,
        )


class DemoSMSGateway:
    """
    Local demonstration gateway.
    Never sends a real SMS.
    """

    def send(
        self,
        *,
        to_number: str,
        body: str,
    ) -> tuple[str, str]:
        validate_phone(to_number)

        logger.info(
            "Demo SMS accepted"
        )

        return (
            "DEMO_MESSAGE_ID",
            "queued",
        )


if __name__ == "__main__":
    notifier = RetailSMSNotifier(
        DemoSMSGateway()
    )

    recipient = SMSRecipient(
        tenant_id="retail-demo",
        user_id="EMP001",
        phone_number="+919999999999",
        phone_verified=True,
        sms_enabled=True,
        active=True,
    )

    payload = SMSPayload(
        tenant_id="retail-demo",
        event_id="EVT001",
        category=SMSCategory.INVENTORY,
        severity=SMSSeverity.CRITICAL,
        resource_id="WH001:SKU001",
        title="Critical low stock",
        message=(
            "Only 12 units remaining. "
            "Review replenishment immediately."
        ),
    )

    result = notifier.send(
        recipient=recipient,
        payload=payload,
    )

    print(result)
