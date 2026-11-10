from __future__ import annotations

"""Planned module: workplace adapter. Implementation pending."""

"""
backend/notifications/adapters/workplace_adapter.py

Autonomous Retail Supply Chain AI 5.0

Python 3.10+

Adapter for workplace collaboration alerts.

Integrates with:
- workplace_notifier.py
- notification_router.py
- delivery_tracker.py
- escalation_policy.py
- deduplication.py

Features:
- Tenant-scoped delivery
- Authorized destination routing
- Slack / Microsoft Teams support
- Notification category mapping
- Severity mapping
- Destination/category allowlists
- Message length validation
- Idempotency-key propagation
- Structured provider outcomes
- Async-compatible execution
- Injectable repository and notifier

This adapter does not independently enforce
durable delivery deduplication or retries.
"""


import asyncio
import logging

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from backend.notifications.workplace_notifier import (
    WorkplaceCategory,
    WorkplaceDeliveryResult,
    WorkplacePayload,
    WorkplaceSeverity,
    RetailWorkplaceNotifier,
)


logger = logging.getLogger(__name__)


class WorkplaceAdapterStatus(str, Enum):
    ACCEPTED = "accepted"
    RETRYABLE_FAILURE = "retryable_failure"
    PERMANENT_FAILURE = "permanent_failure"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class WorkplaceDeliveryRequest:
    tenant_id: str
    event_id: str
    destination_id: str
    idempotency_key: str
    category: str
    severity: str
    title: str
    message: str
    resource_id: str

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "event_id",
            "destination_id",
            "idempotency_key",
            "category",
            "severity",
            "title",
            "message",
            "resource_id",
        ):
            value = getattr(self, name)

            if (
                not isinstance(value, str)
                or not value.strip()
            ):
                raise ValueError(
                    f"{name} is required"
                )


@dataclass(frozen=True)
class WorkplaceDestinationPolicy:
    tenant_id: str
    destination_id: str
    enabled: bool = True
    allowed_categories: frozenset[str] = (
        frozenset()
    )
    minimum_severity: str = "medium"
    approval_required: bool = False


@dataclass(frozen=True)
class WorkplaceAdapterResult:
    tenant_id: str
    event_id: str
    destination_id: str
    idempotency_key: str
    status: WorkplaceAdapterStatus
    accepted: bool
    retryable: bool
    provider_status_code: int | None = None
    error_code: str | None = None


class WorkplacePolicyRepository(Protocol):
    def get_policy(
        self,
        *,
        tenant_id: str,
        destination_id: str,
    ) -> WorkplaceDestinationPolicy | None:
        ...


class WorkplaceApprovalVerifier(Protocol):
    def is_approved(
        self,
        *,
        tenant_id: str,
        event_id: str,
        destination_id: str,
    ) -> bool:
        ...


class WorkplaceNotifierProtocol(Protocol):
    def send(
        self,
        *,
        destination_id: str,
        payload: WorkplacePayload,
    ) -> WorkplaceDeliveryResult:
        ...


class RetailWorkplaceAdapter:
    MAX_TITLE_LENGTH = 150
    MAX_MESSAGE_LENGTH = 3000

    CATEGORY_MAPPING = {
        "inventory": WorkplaceCategory.INVENTORY,
        "stockout": WorkplaceCategory.STOCKOUT,
        "supplier": WorkplaceCategory.SUPPLIER,
        "warehouse": WorkplaceCategory.WAREHOUSE,
        "quality": WorkplaceCategory.QUALITY,
        "logistics": WorkplaceCategory.LOGISTICS,
        "finance": WorkplaceCategory.FINANCE,
        "security": WorkplaceCategory.SECURITY,
        "incident": WorkplaceCategory.INCIDENT,
        "escalation": WorkplaceCategory.ESCALATION,
        "general": WorkplaceCategory.GENERAL,
    }

    SEVERITY_MAPPING = {
        "info": WorkplaceSeverity.INFO,
        "low": WorkplaceSeverity.LOW,
        "medium": WorkplaceSeverity.MEDIUM,
        "high": WorkplaceSeverity.HIGH,
        "critical": WorkplaceSeverity.CRITICAL,
    }

    SEVERITY_ORDER = {
        "info": 0,
        "low": 1,
        "medium": 2,
        "high": 3,
        "critical": 4,
    }

    def __init__(
        self,
        *,
        policy_repository: WorkplacePolicyRepository,
        notifier: WorkplaceNotifierProtocol,
        approval_verifier: (
            WorkplaceApprovalVerifier | None
        ) = None,
    ) -> None:
        self.policy_repository = policy_repository
        self.notifier = notifier
        self.approval_verifier = approval_verifier

    @staticmethod
    def _result(
        request: WorkplaceDeliveryRequest,
        *,
        status: WorkplaceAdapterStatus,
        accepted: bool = False,
        retryable: bool = False,
        provider_status_code: int | None = None,
        error_code: str | None = None,
    ) -> WorkplaceAdapterResult:
        return WorkplaceAdapterResult(
            tenant_id=request.tenant_id,
            event_id=request.event_id,
            destination_id=request.destination_id,
            idempotency_key=request.idempotency_key,
            status=status,
            accepted=accepted,
            retryable=retryable,
            provider_status_code=(
                provider_status_code
            ),
            error_code=error_code,
        )

    @staticmethod
    def _clean_text(
        value: str,
        *,
        max_length: int,
    ) -> str:
        text = " ".join(
            value.split()
        )

        if not text:
            raise ValueError(
                "Notification text is empty"
            )

        if len(text) > max_length:
            raise ValueError(
                "Notification text exceeds limit"
            )

        return text

    def _build_payload(
        self,
        request: WorkplaceDeliveryRequest,
    ) -> WorkplacePayload:
        category = self.CATEGORY_MAPPING.get(
            request.category.lower()
        )

        severity = self.SEVERITY_MAPPING.get(
            request.severity.lower()
        )

        if category is None:
            raise ValueError(
                "Unsupported workplace category"
            )

        if severity is None:
            raise ValueError(
                "Unsupported workplace severity"
            )

        return WorkplacePayload(
            tenant_id=request.tenant_id,
            event_id=request.event_id,
            category=category,
            severity=severity,
            title=self._clean_text(
                request.title,
                max_length=self.MAX_TITLE_LENGTH,
            ),
            message=self._clean_text(
                request.message,
                max_length=self.MAX_MESSAGE_LENGTH,
            ),
            resource_id=request.resource_id,
        )

    def deliver(
        self,
        request: WorkplaceDeliveryRequest,
    ) -> WorkplaceAdapterResult:
        policy = self.policy_repository.get_policy(
            tenant_id=request.tenant_id,
            destination_id=request.destination_id,
        )

        if policy is None:
            return self._result(
                request,
                status=WorkplaceAdapterStatus.SKIPPED,
                error_code="destination_not_found",
            )

        if (
            policy.tenant_id != request.tenant_id
            or policy.destination_id
            != request.destination_id
        ):
            return self._result(
                request,
                status=(
                    WorkplaceAdapterStatus.PERMANENT_FAILURE
                ),
                error_code="destination_scope_mismatch",
            )

        if not policy.enabled:
            return self._result(
                request,
                status=WorkplaceAdapterStatus.SKIPPED,
                error_code="destination_disabled",
            )

        category_name = request.category.lower()
        severity_name = request.severity.lower()

        if category_name not in self.CATEGORY_MAPPING:
            return self._result(
                request,
                status=(
                    WorkplaceAdapterStatus.PERMANENT_FAILURE
                ),
                error_code="invalid_category",
            )

        if severity_name not in self.SEVERITY_ORDER:
            return self._result(
                request,
                status=(
                    WorkplaceAdapterStatus.PERMANENT_FAILURE
                ),
                error_code="invalid_severity",
            )

        if (
            policy.allowed_categories
            and category_name not in (
                policy.allowed_categories
            )
        ):
            return self._result(
                request,
                status=WorkplaceAdapterStatus.SKIPPED,
                error_code="category_not_allowed",
            )

        minimum = self.SEVERITY_ORDER.get(
            policy.minimum_severity.lower()
        )

        if minimum is None:
            return self._result(
                request,
                status=(
                    WorkplaceAdapterStatus.PERMANENT_FAILURE
                ),
                error_code="invalid_policy",
            )

        if self.SEVERITY_ORDER[severity_name] < minimum:
            return self._result(
                request,
                status=WorkplaceAdapterStatus.SKIPPED,
                error_code="below_severity_threshold",
            )

        if policy.approval_required:
            if self.approval_verifier is None:
                return self._result(
                    request,
                    status=(
                        WorkplaceAdapterStatus.PERMANENT_FAILURE
                    ),
                    error_code="approval_verifier_missing",
                )

            if not self.approval_verifier.is_approved(
                tenant_id=request.tenant_id,
                event_id=request.event_id,
                destination_id=request.destination_id,
            ):
                return self._result(
                    request,
                    status=WorkplaceAdapterStatus.SKIPPED,
                    error_code="approval_required",
                )

        try:
            payload = self._build_payload(
                request
            )

        except (ValueError, TypeError):
            return self._result(
                request,
                status=(
                    WorkplaceAdapterStatus.PERMANENT_FAILURE
                ),
                error_code="invalid_payload",
            )

        try:
            provider_result = self.notifier.send(
                destination_id=request.destination_id,
                payload=payload,
            )

        except (TimeoutError, ConnectionError):
            logger.warning(
                "Workplace delivery transport failure: "
                "tenant=%s event=%s",
                request.tenant_id,
                request.event_id,
            )

            return self._result(
                request,
                status=(
                    WorkplaceAdapterStatus.RETRYABLE_FAILURE
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
            request,
            status=(
                WorkplaceAdapterStatus.ACCEPTED
                if accepted
                else (
                    WorkplaceAdapterStatus.RETRYABLE_FAILURE
                    if retryable
                    else WorkplaceAdapterStatus.PERMANENT_FAILURE
                )
            ),
            accepted=accepted,
            retryable=(
                retryable if not accepted else False
            ),
            provider_status_code=(
                provider_result.status_code
            ),
            error_code=(
                provider_result.error_code
            ),
        )

    async def deliver_async(
        self,
        request: WorkplaceDeliveryRequest,
    ) -> WorkplaceAdapterResult:
        return await asyncio.to_thread(
            self.deliver,
            request,
        )


class InMemoryWorkplacePolicyRepository:
    """
    Demo-only repository.
    """

    def __init__(
        self,
        policies: list[WorkplaceDestinationPolicy],
    ) -> None:
        self.policies = {
            (p.tenant_id, p.destination_id): p
            for p in policies
        }

    def get_policy(
        self,
        *,
        tenant_id: str,
        destination_id: str,
    ) -> WorkplaceDestinationPolicy | None:
        return self.policies.get(
            (tenant_id, destination_id)
        )


class DemoWorkplaceNotifier:
    """
    No real Slack or Teams message is sent.
    """

    def send(
        self,
        *,
        destination_id: str,
        payload: WorkplacePayload,
    ) -> WorkplaceDeliveryResult:
        from backend.notifications.workplace_notifier import (
            WorkplacePlatform,
        )

        return WorkplaceDeliveryResult(
            tenant_id=payload.tenant_id,
            event_id=payload.event_id,
            destination_id=destination_id,
            platform=WorkplacePlatform.SLACK,
            accepted=True,
            status_code=200,
            retryable=False,
            idempotency_key=(
                f"{payload.tenant_id}:"
                f"{payload.event_id}:"
                f"{destination_id}"
            ),
        )


if __name__ == "__main__":
    repository = InMemoryWorkplacePolicyRepository(
        [
            WorkplaceDestinationPolicy(
                tenant_id="retail-demo",
                destination_id="OPS_SLACK",
                enabled=True,
                allowed_categories=frozenset(
                    {
                        "inventory",
                        "stockout",
                        "supplier",
                        "logistics",
                        "incident",
                    }
                ),
                minimum_severity="high",
                approval_required=False,
            )
        ]
    )

    adapter = RetailWorkplaceAdapter(
        policy_repository=repository,
        notifier=DemoWorkplaceNotifier(),
    )

    request = WorkplaceDeliveryRequest(
        tenant_id="retail-demo",
        event_id="EVENT001",
        destination_id="OPS_SLACK",
        idempotency_key=(
            "retail-demo:EVENT001:OPS_SLACK"
        ),
        category="inventory",
        severity="critical",
        title="Critical inventory alert",
        message=(
            "SKU001 stock is below the "
            "critical threshold."
        ),
        resource_id="SKU001",
    )

    print(adapter.deliver(request))

    # Demo only: no external message is sent.
