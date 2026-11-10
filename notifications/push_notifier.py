from __future__ import annotations

"""Planned module: push notifier. Implementation pending."""

"""
backend/notifications/push_notifier.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+ | Firebase Cloud Messaging

Features:
- FCM Android/iOS/Web push
- Tenant-scoped device registry abstraction
- Per-user multi-device delivery
- Notification priority handling
- Per-token result tracking
- Async-compatible Firebase calls
- Permanent/retryable error classification
- Safe notification payloads

Security:
- Never expose Firebase service account credentials.
- Device ownership must be authenticated upstream.
- Device tokens are secrets: encrypt at rest.
- Do not log device tokens.
- Do not put sensitive operational data in push bodies.
"""


import asyncio
import logging
import re

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol
from uuid import uuid4

import firebase_admin

from firebase_admin import (
    credentials,
    messaging,
)

from firebase_admin.exceptions import (
    FirebaseError,
)


logger = logging.getLogger(__name__)


def required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


class PushPlatform(str, Enum):
    ANDROID = "android"
    IOS = "ios"
    WEB = "web"


class PushPriority(str, Enum):
    NORMAL = "normal"
    HIGH = "high"


class PushSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class PushDevice:
    tenant_id: str
    user_id: str
    device_id: str
    token: str
    platform: PushPlatform
    enabled: bool = True

    def __post_init__(self) -> None:
        required(self.tenant_id, "tenant_id")
        required(self.user_id, "user_id")
        required(self.device_id, "device_id")
        required(self.token, "token")


@dataclass(frozen=True)
class PushPayload:
    tenant_id: str
    event_id: str
    title: str
    body: str
    severity: PushSeverity
    resource_id: str
    deep_link: str = "/notifications"

    def __post_init__(self) -> None:
        required(self.tenant_id, "tenant_id")
        required(self.event_id, "event_id")
        required(self.title, "title")
        required(self.body, "body")
        required(self.resource_id, "resource_id")

        if len(self.title) > 150:
            raise ValueError("Push title too long")

        if len(self.body) > 500:
            raise ValueError("Push body too long")

        if not re.fullmatch(
            r"/[A-Za-z0-9/_-]*",
            self.deep_link,
        ):
            raise ValueError(
                "Only safe internal deep links are allowed"
            )


@dataclass(frozen=True)
class PushTokenResult:
    device_id: str
    accepted: bool
    provider_message_id: str | None
    retryable: bool
    revoke_token: bool
    error_code: str | None = None


@dataclass(frozen=True)
class PushBatchResult:
    event_id: str
    tenant_id: str
    attempted: int
    accepted: int
    failed: int
    results: tuple[PushTokenResult, ...]


class PushDeviceRepository(Protocol):
    """
    Implement using an authenticated, tenant-scoped
    database repository.

    Do not trust tenant_id/user_id supplied by a
    public request without verifying authorization.
    """

    def active_devices(
        self,
        *,
        tenant_id: str,
        user_id: str,
    ) -> list[PushDevice]:
        ...

    def revoke_device(
        self,
        *,
        tenant_id: str,
        user_id: str,
        device_id: str,
    ) -> None:
        ...


class FirebasePushNotifier:
    def __init__(
        self,
        *,
        firebase_app: firebase_admin.App,
        device_repository: PushDeviceRepository,
    ) -> None:
        self.app = firebase_app
        self.devices = device_repository

    @staticmethod
    def initialize_firebase(
        credential_path: str,
        *,
        app_name: str | None = None,
    ) -> firebase_admin.App:
        credential_path = required(
            credential_path, "credential_path"
        )

        credential = credentials.Certificate(
            credential_path
        )

        # Use a distinct app name for independently
        # configured Firebase projects.
        return firebase_admin.initialize_app(
            credential,
            name=app_name or str(uuid4()),
        )

    @staticmethod
    def _priority(
        severity: PushSeverity,
    ) -> PushPriority:
        if severity in {
            PushSeverity.HIGH,
            PushSeverity.CRITICAL,
        }:
            return PushPriority.HIGH

        return PushPriority.NORMAL

    @staticmethod
    def _classify_exception(
        exc: Exception,
    ) -> tuple[bool, bool, str]:
        """
        Returns:
            retryable, revoke_token, error_code

        Provider-specific errors are classified
        conservatively. Unknown errors are not
        automatically treated as invalid tokens.
        """
        name = type(exc).__name__

        if name in {
            "UnregisteredError",
            "SenderIdMismatchError",
        }:
            return False, True, name

        if name in {
            "QuotaExceededError",
            "UnavailableError",
            "InternalError",
        }:
            return True, False, name

        if name in {
            "InvalidArgumentError",
            "ThirdPartyAuthError",
        }:
            return False, False, name

        return True, False, name

    def _message(
        self,
        *,
        device: PushDevice,
        payload: PushPayload,
    ) -> messaging.Message:
        priority = self._priority(
            payload.severity
        )

        data = {
            "event_id": payload.event_id,
            "resource_id": payload.resource_id,
            "severity": payload.severity.value,
            "deep_link": payload.deep_link,
        }

        notification = messaging.Notification(
            title=payload.title,
            body=payload.body,
        )

        android = messaging.AndroidConfig(
            priority=priority.value,
            notification=messaging.AndroidNotification(
                channel_id="retail_operations",
            ),
        )

        apns = messaging.APNSConfig(
            headers={
                "apns-priority": (
                    "10"
                    if priority == PushPriority.HIGH
                    else "5"
                ),
            },
            payload=messaging.APNSPayload(
                aps=messaging.Aps(
                    sound="default",
                ),
            ),
        )

        webpush = messaging.WebpushConfig(
            headers={
                "Urgency": (
                    "high"
                    if priority == PushPriority.HIGH
                    else "normal"
                ),
            },
        )

        return messaging.Message(
            token=device.token,
            notification=notification,
            data=data,
            android=android,
            apns=apns,
            webpush=webpush,
        )

    def send_to_user(
        self,
        *,
        tenant_id: str,
        user_id: str,
        payload: PushPayload,
    ) -> PushBatchResult:
        tenant_id = required(
            tenant_id, "tenant_id"
        )
        user_id = required(
            user_id, "user_id"
        )

        if payload.tenant_id != tenant_id:
            raise ValueError(
                "Cross-tenant push delivery denied"
            )

        devices = self.devices.active_devices(
            tenant_id=tenant_id,
            user_id=user_id,
        )

        eligible = [
            device
            for device in devices
            if device.enabled
            and device.tenant_id == tenant_id
            and device.user_id == user_id
        ]

        results: list[PushTokenResult] = []

        for device in eligible:
            try:
                message = self._message(
                    device=device,
                    payload=payload,
                )

                provider_id = messaging.send(
                    message,
                    app=self.app,
                )

                results.append(
                    PushTokenResult(
                        device_id=device.device_id,
                        accepted=True,
                        provider_message_id=provider_id,
                        retryable=False,
                        revoke_token=False,
                    )
                )

            except Exception as exc:
                retryable, revoke, code = (
                    self._classify_exception(exc)
                )

                logger.warning(
                    "Push delivery failed: "
                    "device_id=%s error=%s",
                    device.device_id,
                    code,
                )

                if revoke:
                    # Repository implementations must
                    # enforce tenant/user ownership.
                    self.devices.revoke_device(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        device_id=device.device_id,
                    )

                results.append(
                    PushTokenResult(
                        device_id=device.device_id,
                        accepted=False,
                        provider_message_id=None,
                        retryable=retryable,
                        revoke_token=revoke,
                        error_code=code,
                    )
                )

        accepted = sum(
            result.accepted
            for result in results
        )

        return PushBatchResult(
            event_id=payload.event_id,
            tenant_id=tenant_id,
            attempted=len(results),
            accepted=accepted,
            failed=len(results) - accepted,
            results=tuple(results),
        )

    async def send_to_user_async(
        self,
        *,
        tenant_id: str,
        user_id: str,
        payload: PushPayload,
    ) -> PushBatchResult:
        return await asyncio.to_thread(
            self.send_to_user,
            tenant_id=tenant_id,
            user_id=user_id,
            payload=payload,
        )


if __name__ == "__main__":
    # Example initialization:
    #
    # app = FirebasePushNotifier.initialize_firebase(
    #     "/secure/firebase-service-account.json"
    # )
    #
    # repository = YourPushDeviceRepository(...)
    #
    # notifier = FirebasePushNotifier(
    #     firebase_app=app,
    #     device_repository=repository,
    # )
    #
    # payload = PushPayload(
    #     tenant_id="retail-demo",
    #     event_id="EVT001",
    #     title="Critical Stock Alert",
    #     body="Warehouse inventory needs attention.",
    #     severity=PushSeverity.CRITICAL,
    #     resource_id="WH001:SKU001",
    # )
    #
    # result = notifier.send_to_user(
    #     tenant_id="retail-demo",
    #     user_id="EMP001",
    #     payload=payload,
    # )
    #
    # print(result)
    pass
