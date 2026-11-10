from __future__ import annotations

"""Planned module: supplier api adapter. Implementation pending."""

"""
backend/notifications/adapters/sms_adapter.py

Autonomous Retail Supply Chain AI 5.0

Python 3.10+

Adapter between:
- notification_router.py
- sms_notifier.py
- recipient storage
- delivery tracking / outbox

Features:
- Tenant-scoped recipient lookup
- SMS channel validation
- Verified phone requirement
- Recipient opt-in enforcement
- Structured notification mapping
- SMS length validation
- Provider failure classification
- Async-compatible execution
- Idempotency-key propagation

Important:
Provider acceptance is not handset delivery.

Durable deduplication, retry scheduling,
quiet-hour policies, rate limiting and
delivery receipts must be enforced by
the surrounding notification platform.
"""


import asyncio
import logging

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from backend.notifications.notification_router import (
    DeliveryInstruction,
    NotificationChannel,
)

from backend.notifications.sms_notifier import (
    SMSCategory,
    SMSDeliveryError,
    SMSPayload,
    SMSRecipient,
    SMSSeverity,
    RetailSMSNotifier,
)


logger = logging.getLogger(__name__)


class SMSAdapterStatus(str, Enum):
    ACCEPTED = "accepted"
    RETRYABLE_FAILURE = "retryable_failure"
    PERMANENT_FAILURE = "permanent_failure"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class SMSRecipientRecord:
    tenant_id: str
    user_id: str
    phone_number: str
    phone_verified: bool
    sms_enabled: bool
    active: bool = True


@dataclass(frozen=True)
class SMSAdapterResult:
    tenant_id: str
    event_id: str
    recipient_user_id: str
    idempotency_key: str
    status: SMSAdapterStatus
    accepted: bool
    retryable: bool
    provider_message_id: str | None = None
    provider_status: str | None = None
    error_code: str | None = None


class SMSRecipientRepository(Protocol):
    def get_sms_recipient(
        self,
        *,
        tenant_id: str,
        user_id: str,
    ) -> SMSRecipientRecord | None:
        ...


class SMSNotifierProtocol(Protocol):
    def send(
        self,
        *,
        recipient: SMSRecipient,
        payload: SMSPayload,
    ):
        ...


class RetailSMSAdapter:
    MAX_TITLE_LENGTH = 100
    MAX_MESSAGE_LENGTH = 600

    CATEGORY_MAPPING = {
        "inventory": SMSCategory.INVENTORY,
        "stockout": SMSCategory.STOCKOUT,
        "supplier": SMSCategory.SUPPLIER,
        "warehouse": SMSCategory.WAREHOUSE,
        "quality": SMSCategory.QUALITY,
        "logistics": SMSCategory.LOGISTICS,
        "finance": SMSCategory.FINANCE,
        "security": SMSCategory.SECURITY,
        "incident": SMSCategory.INCIDENT,
    }

    SEVERITY_MAPPING = {
        "info": SMSSeverity.INFO,
        "low": SMSSeverity.LOW,
        "medium": SMSSeverity.MEDIUM,
        "high": SMSSeverity.HIGH,
        "critical": SMSSeverity.CRITICAL,
    }

    def __init__(
        self,
        *,
        recipient_repository: SMSRecipientRepository,
        notifier: SMSNotifierProtocol,
    ) -> None:
        self.recipient_repository = recipient_repository
        self.notifier = notifier

    @staticmethod
    def _enum_value(value: object) -> str:
        """
        Supports both str-backed enums and
        plain string values.
        """
        raw = getattr(value, "value", value)
        return str(raw).lower()

    @staticmethod
    def _result(
        instruction: DeliveryInstruction,
        *,
        status: SMSAdapterStatus,
        accepted: bool = False,
        retryable: bool = False,
        provider_message_id: str | None = None,
        provider_status: str | None = None,
        error_code: str | None = None,
    ) -> SMSAdapterResult:
        return SMSAdapterResult(
            tenant_id=instruction.tenant_id,
            event_id=instruction.event_id,
            recipient_user_id=(
                instruction.recipient_user_id
            ),
            idempotency_key=(
                instruction.idempotency_key
            ),
            status=status,
            accepted=accepted,
            retryable=retryable,
            provider_message_id=provider_message_id,
            provider_status=provider_status,
            error_code=error_code,
        )

    def _build_payload(
        self,
        instruction: DeliveryInstruction,
    ) -> SMSPayload:
        category_value = self._enum_value(
            instruction.category
        )

        severity_value = self._enum_value(
            instruction.severity
        )

        category = self.CATEGORY_MAPPING.get(
            category_value
        )

        severity = self.SEVERITY_MAPPING.get(
            severity_value
        )

        if category is None:
            raise ValueError(
                "Unsupported SMS notification category"
            )

        if severity is None:
            raise ValueError(
                "Unsupported SMS notification severity"
            )

        title = " ".join(
            instruction.title.split()
        )

        message = " ".join(
            instruction.message.split()
        )

        if not title or not message:
            raise ValueError(
                "SMS title and message are required"
            )

        if len(title) > self.MAX_TITLE_LENGTH:
            raise ValueError(
                "SMS title exceeds 100 characters"
            )

        if len(message) > self.MAX_MESSAGE_LENGTH:
            raise ValueError(
                "SMS message exceeds 600 characters"
            )

        if not instruction.resource_id:
            raise ValueError(
                "SMS resource ID is required"
            )

        return SMSPayload(
            tenant_id=instruction.tenant_id,
            event_id=instruction.event_id,
            category=category,
            severity=severity,
            resource_id=instruction.resource_id,
            title=title,
            message=message,
        )

    def deliver(
        self,
        instruction: DeliveryInstruction,
    ) -> SMSAdapterResult:
        # This adapter only processes SMS.
        if self._enum_value(
            instruction.channel
        ) != NotificationChannel.SMS.value:
            return self._result(
                instruction,
                status=SMSAdapterStatus.SKIPPED,
                error_code="wrong_channel",
            )

        if not instruction.idempotency_key:
            return self._result(
                instruction,
                status=(
                    SMSAdapterStatus.PERMANENT_FAILURE
                ),
                error_code="missing_idempotency_key",
            )

        recipient = (
            self.recipient_repository.get_sms_recipient(
                tenant_id=instruction.tenant_id,
                user_id=instruction.recipient_user_id,
            )
        )

        if recipient is None:
            return self._result(
                instruction,
                status=SMSAdapterStatus.SKIPPED,
                error_code="recipient_not_found",
            )

        if (
            recipient.tenant_id
            != instruction.tenant_id
            or recipient.user_id
            != instruction.recipient_user_id
        ):
            return self._result(
                instruction,
                status=(
                    SMSAdapterStatus.PERMANENT_FAILURE
                ),
                error_code="recipient_scope_mismatch",
            )

        if not recipient.active:
            return self._result(
                instruction,
                status=SMSAdapterStatus.SKIPPED,
                error_code="recipient_inactive",
            )

        if not recipient.sms_enabled:
            return self._result(
                instruction,
                status=SMSAdapterStatus.SKIPPED,
                error_code="sms_opt_out",
            )

        if not recipient.phone_verified:
            return self._result(
                instruction,
                status=SMSAdapterStatus.SKIPPED,
                error_code="phone_not_verified",
            )

        try:
            payload = self._build_payload(
                instruction
            )

            sms_recipient = SMSRecipient(
                tenant_id=recipient.tenant_id,
                user_id=recipient.user_id,
                phone_number=recipient.phone_number,
                phone_verified=(
                    recipient.phone_verified
                ),
                sms_enabled=(
                    recipient.sms_enabled
                ),
                active=recipient.active,
            )

        except (ValueError, TypeError):
            return self._result(
                instruction,
                status=(
                    SMSAdapterStatus.PERMANENT_FAILURE
                ),
                error_code="invalid_sms_payload",
            )

        try:
            provider_result = self.notifier.send(
                recipient=sms_recipient,
                payload=payload,
            )

        except SMSDeliveryError as exc:
            retryable = bool(
                getattr(exc, "retryable", False)
            )

            return self._result(
                instruction,
                status=(
                    SMSAdapterStatus.RETRYABLE_FAILURE
                    if retryable
                    else SMSAdapterStatus.PERMANENT_FAILURE
                ),
                retryable=retryable,
                error_code=(
                    getattr(exc, "error_code", None)
                    or "sms_delivery_error"
                ),
            )

        except (TimeoutError, ConnectionError):
            logger.warning(
                "SMS transport failure: "
                "tenant=%s event=%s",
                instruction.tenant_id,
                instruction.event_id,
            )

            return self._result(
                instruction,
                status=(
                    SMSAdapterStatus.RETRYABLE_FAILURE
                ),
                retryable=True,
                error_code="transport_error",
            )

        accepted = bool(
            provider_result.accepted
        )

        retryable = bool(
            provider_result.retryable
        )

        return self._result(
            instruction,
            status=(
                SMSAdapterStatus.ACCEPTED
                if accepted
                else (
                    SMSAdapterStatus.RETRYABLE_FAILURE
                    if retryable
                    else SMSAdapterStatus.PERMANENT_FAILURE
                )
            ),
            accepted=accepted,
            retryable=(
                retryable if not accepted else False
            ),
            provider_message_id=(
                provider_result.provider_message_id
            ),
            provider_status=(
                provider_result.provider_status
            ),
            error_code=(
                provider_result.error_code
            ),
        )

    async def deliver_async(
        self,
        instruction: DeliveryInstruction,
    ) -> SMSAdapterResult:
        return await asyncio.to_thread(
            self.deliver,
            instruction,
        )


class InMemorySMSRecipientRepository:
    """
    Demo-only repository.
    """

    def __init__(
        self,
        recipients: list[SMSRecipientRecord],
    ) -> None:
        self.recipients = {
            (r.tenant_id, r.user_id): r
            for r in recipients
        }

    def get_sms_recipient(
        self,
        *,
        tenant_id: str,
        user_id: str,
    ) -> SMSRecipientRecord | None:
        return self.recipients.get(
            (tenant_id, user_id)
        )


if __name__ == "__main__":
    # Uses the existing demonstration gateway
    # from sms_notifier.py.
    from backend.notifications.sms_notifier import (
        DemoSMSGateway,
    )

    recipients = InMemorySMSRecipientRepository(
        [
            SMSRecipientRecord(
                tenant_id="retail-demo",
                user_id="manager001",
                phone_number="+919000000001",
                phone_verified=True,
                sms_enabled=True,
                active=True,
            )
        ]
    )

    notifier = RetailSMSNotifier(
        gateway=DemoSMSGateway()
    )

    adapter = RetailSMSAdapter(
        recipient_repository=recipients,
        notifier=notifier,
    )

    instruction = DeliveryInstruction(
        tenant_id="retail-demo",
        event_id="EVENT001",
        recipient_user_id="manager001",
        channel=NotificationChannel.SMS,
        idempotency_key="sms-event001-manager001",
        title="Critical stock alert",
        message=(
            "SKU001 is below the minimum "
            "inventory threshold."
        ),
        severity="critical",
        category="inventory",
        resource_id="SKU001",
    )

    result = adapter.deliver(instruction)

    print(result)

    # DemoSMSGateway does not send a real SMS.
