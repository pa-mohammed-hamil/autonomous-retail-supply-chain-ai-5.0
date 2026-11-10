from __future__ import annotations

"""Planned module: email adapter. Implementation pending."""

"""
backend/notifications/adapters/email_adapter.py

Autonomous Retail Supply Chain AI 5.0

Python 3.10+

Connects:
- notification_router.py
- recipient_resolver.py
- templates.py
- email_notifier.py
- delivery_tracker.py (through returned outcomes)

Features:
- Tenant-scoped recipient lookup
- Verified email address checks
- Recipient notification preferences
- Template rendering
- SMTP delivery delegation
- Async support
- Idempotency-key propagation
- Retryable error classification
- Structured delivery outcomes
- No logging of email addresses or message bodies

Important:
- The adapter does not persist idempotency keys.
- Use delivery_tracker.py and a durable outbox.
- Authorization is based on trusted repository records.
"""


import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from backend.notifications.email_notifier import (
    EmailPayload,
    EmailSendResult,
    EmailTransportError,
    RetailEmailNotifier,
    validate_email,
)

from backend.notifications.templates import (
    NotificationChannel as TemplateChannel,
    NotificationSeverity as TemplateSeverity,
    RetailNotificationTemplates,
    TemplateError,
)


logger = logging.getLogger(__name__)


def required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


class EmailAdapterStatus(str, Enum):
    ACCEPTED = "accepted"
    RETRYABLE_FAILURE = "retryable_failure"
    PERMANENT_FAILURE = "permanent_failure"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class EmailRecipientRecord:
    tenant_id: str
    user_id: str
    email_address: str
    email_verified: bool
    email_enabled: bool
    active: bool

    def __post_init__(self) -> None:
        required(self.tenant_id, "tenant_id")
        required(self.user_id, "user_id")


@dataclass(frozen=True)
class EmailDeliveryRequest:
    tenant_id: str
    event_id: str
    recipient_user_id: str
    idempotency_key: str
    template_id: str
    severity: str
    variables: dict[str, str]
    resource_id: str

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "event_id",
            "recipient_user_id",
            "idempotency_key",
            "template_id",
            "resource_id",
        ):
            required(getattr(self, name), name)

        if not isinstance(self.variables, dict):
            raise ValueError(
                "variables must be a dictionary"
            )

        if not all(
            isinstance(k, str)
            and isinstance(v, str)
            for k, v in self.variables.items()
        ):
            raise ValueError(
                "Template variables must be strings"
            )


@dataclass(frozen=True)
class EmailAdapterResult:
    tenant_id: str
    event_id: str
    recipient_user_id: str
    idempotency_key: str
    status: EmailAdapterStatus
    accepted: bool
    retryable: bool
    provider_message_id: str | None = None
    error_code: str | None = None
    template_version: str | None = None


class EmailRecipientRepository(Protocol):
    """
    Implement using trusted user/contact records.

    The repository must enforce tenant scoping.
    """

    def get_email_recipient(
        self,
        *,
        tenant_id: str,
        user_id: str,
    ) -> EmailRecipientRecord | None:
        ...


class EmailTransport(Protocol):
    """
    Compatible with RetailEmailNotifier.
    """

    def send(
        self,
        payload: EmailPayload,
    ) -> EmailSendResult:
        ...


class RetailEmailAdapter:
    def __init__(
        self,
        *,
        recipient_repository: EmailRecipientRepository,
        notifier: EmailTransport,
        templates: RetailNotificationTemplates | None = None,
    ) -> None:
        self.recipients = recipient_repository
        self.notifier = notifier
        self.templates = (
            templates or RetailNotificationTemplates()
        )

    @staticmethod
    def _result(
        request: EmailDeliveryRequest,
        *,
        status: EmailAdapterStatus,
        retryable: bool = False,
        provider_message_id: str | None = None,
        error_code: str | None = None,
        template_version: str | None = None,
    ) -> EmailAdapterResult:
        return EmailAdapterResult(
            tenant_id=request.tenant_id,
            event_id=request.event_id,
            recipient_user_id=request.recipient_user_id,
            idempotency_key=request.idempotency_key,
            status=status,
            accepted=(
                status == EmailAdapterStatus.ACCEPTED
            ),
            retryable=retryable,
            provider_message_id=provider_message_id,
            error_code=error_code,
            template_version=template_version,
        )

    def deliver(
        self,
        request: EmailDeliveryRequest,
    ) -> EmailAdapterResult:
        recipient = (
            self.recipients.get_email_recipient(
                tenant_id=request.tenant_id,
                user_id=request.recipient_user_id,
            )
        )

        if recipient is None:
            return self._result(
                request,
                status=EmailAdapterStatus.SKIPPED,
                error_code="recipient_not_found",
            )

        if (
            recipient.tenant_id != request.tenant_id
            or recipient.user_id
                != request.recipient_user_id
        ):
            return self._result(
                request,
                status=EmailAdapterStatus.SKIPPED,
                error_code="recipient_scope_mismatch",
            )

        if not recipient.active:
            return self._result(
                request,
                status=EmailAdapterStatus.SKIPPED,
                error_code="recipient_inactive",
            )

        if not recipient.email_verified:
            return self._result(
                request,
                status=EmailAdapterStatus.SKIPPED,
                error_code="email_not_verified",
            )

        if not recipient.email_enabled:
            return self._result(
                request,
                status=EmailAdapterStatus.SKIPPED,
                error_code="email_disabled",
            )

        try:
            address = validate_email(
                recipient.email_address
            )

        except ValueError:
            return self._result(
                request,
                status=(
                    EmailAdapterStatus.PERMANENT_FAILURE
                ),
                error_code="invalid_email_address",
            )

        try:
            severity = TemplateSeverity(
                request.severity.lower()
            )

            rendered = self.templates.render(
                template_id=request.template_id,
                channel=TemplateChannel.EMAIL,
                severity=severity,
                values=request.variables,
            )

        except (TemplateError, ValueError):
            return self._result(
                request,
                status=(
                    EmailAdapterStatus.PERMANENT_FAILURE
                ),
                error_code="template_render_failed",
            )

        payload = EmailPayload(
            recipient_email=address,
            subject=rendered.subject,
            text_body=rendered.text_body,
            html_body=rendered.html_body,
            correlation_id=request.event_id,
        )

        try:
            response = self.notifier.send(payload)

            if not response.accepted:
                return self._result(
                    request,
                    status=(
                        EmailAdapterStatus.RETRYABLE_FAILURE
                    ),
                    retryable=True,
                    error_code="provider_not_accepted",
                    template_version=(
                        rendered.template_version
                    ),
                )

            return self._result(
                request,
                status=EmailAdapterStatus.ACCEPTED,
                provider_message_id=(
                    response.message_id
                ),
                template_version=(
                    rendered.template_version
                ),
            )

        except EmailTransportError as exc:
            return self._result(
                request,
                status=(
                    EmailAdapterStatus.RETRYABLE_FAILURE
                    if exc.retryable
                    else EmailAdapterStatus.PERMANENT_FAILURE
                ),
                retryable=exc.retryable,
                error_code="email_transport_error",
                template_version=(
                    rendered.template_version
                ),
            )

        except (
            TimeoutError,
            OSError,
            ConnectionError,
        ):
            logger.exception(
                "Email transport failure: "
                "tenant=%s event=%s",
                request.tenant_id,
                request.event_id,
            )

            return self._result(
                request,
                status=(
                    EmailAdapterStatus.RETRYABLE_FAILURE
                ),
                retryable=True,
                error_code="network_failure",
                template_version=(
                    rendered.template_version
                ),
            )

    async def deliver_async(
        self,
        request: EmailDeliveryRequest,
    ) -> EmailAdapterResult:
        return await asyncio.to_thread(
            self.deliver,
            request,
        )


class InMemoryEmailRecipientRepository:
    """
    Demo/test implementation only.
    """

    def __init__(
        self,
        recipients: list[EmailRecipientRecord],
    ) -> None:
        self._recipients = {
            (r.tenant_id, r.user_id): r
            for r in recipients
        }

    def get_email_recipient(
        self,
        *,
        tenant_id: str,
        user_id: str,
    ) -> EmailRecipientRecord | None:
        return self._recipients.get(
            (tenant_id, user_id)
        )


class FakeEmailTransport:
    """
    No network requests are performed.
    """

    def send(
        self,
        payload: EmailPayload,
    ) -> EmailSendResult:
        return EmailSendResult(
            accepted=True,
            recipient_email=payload.recipient_email,
            message_id="FAKE-EMAIL-001",
            provider_response="accepted",
        )


if __name__ == "__main__":
    repository = InMemoryEmailRecipientRepository(
        [
            EmailRecipientRecord(
                tenant_id="retail-demo",
                user_id="EMP001",
                email_address="manager@example.com",
                email_verified=True,
                email_enabled=True,
                active=True,
            )
        ]
    )

    adapter = RetailEmailAdapter(
        recipient_repository=repository,
        notifier=FakeEmailTransport(),
    )

    result = adapter.deliver(
        EmailDeliveryRequest(
            tenant_id="retail-demo",
            event_id="EVT001",
            recipient_user_id="EMP001",
            idempotency_key="email-EVT001-EMP001",
            template_id="inventory.low_stock",
            severity="high",
            resource_id="WH001:SKU001",
            variables={
                "product_name": "Rice 10kg",
                "available_units": "12",
                "warehouse_id": "WH001",
                "reorder_point": "100",
            },
        )
    )

    print(result)
