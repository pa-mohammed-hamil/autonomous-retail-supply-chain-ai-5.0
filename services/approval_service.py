from __future__ import annotations

"""Planned module: customer feedback service. Implementation pending."""

"""
backend/services/approval_service.py

Autonomous Retail Supply Chain AI 5.0

Human-in-the-loop approval workflow.

Python 3.10+
Dependencies: standard library only

Features:
- Multi-tenant approval isolation
- Role-based approval authorization
- Risk-based approval policies
- Multi-approver workflows
- Separation of duties
- Approval expiration
- Payload integrity verification
- Idempotent execution claims
- Append-only in-memory audit log
- Explicit execution gateway integration

IMPORTANT:
This is an in-memory reference
implementation, not a durable
transactional production service.

The caller must authenticate identities
and provide trusted actor contexts.

Production execution requires an
atomic database claim, persistent audit,
and an idempotent downstream executor.
"""


import copy
import hashlib
import json
import math
import threading
import uuid

from dataclasses import (
    asdict,
    dataclass,
    field,
)
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from enum import Enum
from typing import Any, Callable


def utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    EXECUTING = "executing"
    EXECUTED = "executed"
    EXECUTION_FAILED = "execution_failed"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ActionType(str, Enum):
    PURCHASE_ORDER = "purchase_order"
    INVENTORY_REPLENISHMENT = (
        "inventory_replenishment"
    )
    SUPPLIER_CHANGE = "supplier_change"
    PRICE_CHANGE = "price_change"
    REFUND = "refund"
    STOCK_TRANSFER = "stock_transfer"
    INVENTORY_ADJUSTMENT = (
        "inventory_adjustment"
    )


@dataclass(frozen=True)
class ApprovalActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    is_active: bool = True


@dataclass(frozen=True)
class ApprovalPolicy:
    action_type: ActionType
    risk_level: RiskLevel
    required_roles: frozenset[str]
    minimum_approvals: int
    expiry_minutes: int = 1440
    requester_can_approve: bool = False


@dataclass
class ApprovalRequest:
    request_id: str
    tenant_id: str
    requester_id: str
    action_type: ActionType
    risk_level: RiskLevel
    payload: dict[str, Any]
    payload_hash: str
    reason: str
    status: ApprovalStatus
    required_roles: frozenset[str]
    minimum_approvals: int
    requester_can_approve: bool
    created_at: str
    expires_at: str
    approvals: dict[str, str] = field(
        default_factory=dict
    )
    rejection_reason: str | None = None
    execution_id: str | None = None
    execution_result: Any = None


@dataclass(frozen=True)
class ApprovalAuditEvent:
    event_id: str
    request_id: str
    tenant_id: str
    actor_id: str
    event_type: str
    timestamp: str
    details: dict[str, Any]


class RetailApprovalService:
    """
    Approval orchestration service.

    No business action is executed
    when an approval request is
    merely approved.

    Execution is a separate step,
    requiring a trusted executor.
    """

    def __init__(
        self,
        policies: list[ApprovalPolicy] | None = None,
    ):
        self._lock = threading.RLock()

        self._requests: dict[
            str,
            ApprovalRequest,
        ] = {}

        self._audit: list[
            ApprovalAuditEvent
        ] = []

        self._policies = {
            policy.action_type: policy
            for policy in (
                policies
                if policies is not None
                else self.default_policies()
            )
        }

        if not self._policies:
            raise ValueError(
                "At least one approval "
                "policy is required"
            )

        for policy in self._policies.values():
            if (
                policy.minimum_approvals < 1
                or policy.expiry_minutes < 1
                or not policy.required_roles
            ):
                raise ValueError(
                    "Invalid approval policy"
                )

    @staticmethod
    def default_policies() -> list[
        ApprovalPolicy
    ]:
        return [
            ApprovalPolicy(
                action_type=(
                    ActionType.PURCHASE_ORDER
                ),
                risk_level=RiskLevel.HIGH,
                required_roles=frozenset({
                    "procurement_manager",
                    "finance_manager",
                }),
                minimum_approvals=2,
            ),
            ApprovalPolicy(
                action_type=(
                    ActionType.INVENTORY_REPLENISHMENT
                ),
                risk_level=RiskLevel.MEDIUM,
                required_roles=frozenset({
                    "inventory_manager",
                }),
                minimum_approvals=1,
            ),
            ApprovalPolicy(
                action_type=(
                    ActionType.SUPPLIER_CHANGE
                ),
                risk_level=RiskLevel.HIGH,
                required_roles=frozenset({
                    "procurement_manager",
                    "compliance_manager",
                }),
                minimum_approvals=2,
            ),
            ApprovalPolicy(
                action_type=(
                    ActionType.PRICE_CHANGE
                ),
                risk_level=RiskLevel.HIGH,
                required_roles=frozenset({
                    "pricing_manager",
                    "finance_manager",
                }),
                minimum_approvals=2,
            ),
            ApprovalPolicy(
                action_type=ActionType.REFUND,
                risk_level=RiskLevel.HIGH,
                required_roles=frozenset({
                    "finance_manager",
                }),
                minimum_approvals=1,
            ),
            ApprovalPolicy(
                action_type=(
                    ActionType.STOCK_TRANSFER
                ),
                risk_level=RiskLevel.MEDIUM,
                required_roles=frozenset({
                    "warehouse_manager",
                }),
                minimum_approvals=1,
            ),
            ApprovalPolicy(
                action_type=(
                    ActionType.INVENTORY_ADJUSTMENT
                ),
                risk_level=RiskLevel.HIGH,
                required_roles=frozenset({
                    "inventory_manager",
                    "audit_manager",
                }),
                minimum_approvals=2,
            ),
        ]

    @staticmethod
    def _hash_payload(
        payload: dict[str, Any],
    ) -> str:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

        return hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _validate_actor(
        actor: ApprovalActor,
    ) -> None:
        if (
            not actor.is_active
            or not actor.user_id.strip()
            or not actor.tenant_id.strip()
        ):
            raise PermissionError(
                "Inactive or invalid actor"
            )

    @staticmethod
    def _validate_payload(
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            not isinstance(payload, dict)
            or not payload
        ):
            raise ValueError(
                "Nonempty payload required"
            )

        # JSON round-trip ensures that
        # payload is serializable and
        # detached from caller mutation.
        serialized = json.dumps(
            payload,
            allow_nan=False,
            sort_keys=True,
        )

        if len(serialized) > 100_000:
            raise ValueError(
                "Payload too large"
            )

        return json.loads(
            serialized
        )

    def _log(
        self,
        request: ApprovalRequest,
        actor_id: str,
        event_type: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._audit.append(
            ApprovalAuditEvent(
                event_id=str(uuid.uuid4()),
                request_id=request.request_id,
                tenant_id=request.tenant_id,
                actor_id=actor_id,
                event_type=event_type,
                timestamp=utc_now().isoformat(),
                details=copy.deepcopy(
                    details or {}
                ),
            )
        )

    def _get(
        self,
        request_id: str,
        actor: ApprovalActor,
    ) -> ApprovalRequest:
        self._validate_actor(actor)

        request = self._requests.get(
            request_id
        )

        if (
            request is None
            or request.tenant_id
            != actor.tenant_id
        ):
            raise KeyError(
                "Approval request not found"
            )

        return request

    def _refresh_expiration(
        self,
        request: ApprovalRequest,
    ) -> None:
        if request.status not in (
            ApprovalStatus.PENDING,
            ApprovalStatus.APPROVED,
        ):
            return

        expires_at = datetime.fromisoformat(
            request.expires_at
        )

        if utc_now() >= expires_at:
            request.status = (
                ApprovalStatus.EXPIRED
            )

            self._log(
                request,
                "system",
                "expired",
            )

    def create_request(
        self,
        requester: ApprovalActor,
        action_type: ActionType,
        payload: dict[str, Any],
        reason: str,
    ) -> ApprovalRequest:
        with self._lock:
            self._validate_actor(
                requester
            )

            if action_type not in self._policies:
                raise ValueError(
                    "Unsupported action type"
                )

            if (
                not isinstance(reason, str)
                or not reason.strip()
            ):
                raise ValueError(
                    "Approval reason required"
                )

            validated_payload = (
                self._validate_payload(
                    payload
                )
            )

            policy = self._policies[
                action_type
            ]

            created = utc_now()

            request = ApprovalRequest(
                request_id=str(
                    uuid.uuid4()
                ),
                tenant_id=requester.tenant_id,
                requester_id=requester.user_id,
                action_type=action_type,
                risk_level=policy.risk_level,
                payload=validated_payload,
                payload_hash=self._hash_payload(
                    validated_payload
                ),
                reason=reason.strip(),
                status=ApprovalStatus.PENDING,
                required_roles=(
                    policy.required_roles
                ),
                minimum_approvals=(
                    policy.minimum_approvals
                ),
                requester_can_approve=(
                    policy.requester_can_approve
                ),
                created_at=created.isoformat(),
                expires_at=(
                    created
                    + timedelta(
                        minutes=policy.expiry_minutes
                    )
                ).isoformat(),
            )

            self._requests[
                request.request_id
            ] = request

            self._log(
                request,
                requester.user_id,
                "created",
                {
                    "action_type": (
                        action_type.value
                    ),
                    "risk_level": (
                        policy.risk_level.value
                    ),
                    "payload_hash": (
                        request.payload_hash
                    ),
                },
            )

            return copy.deepcopy(
                request
            )

    def approve(
        self,
        request_id: str,
        approver: ApprovalActor,
    ) -> ApprovalRequest:
        with self._lock:
            request = self._get(
                request_id,
                approver,
            )

            self._refresh_expiration(
                request
            )

            if request.status != (
                ApprovalStatus.PENDING
            ):
                raise ValueError(
                    "Request is not pending"
                )

            if (
                approver.user_id
                == request.requester_id
                and not request.requester_can_approve
            ):
                raise PermissionError(
                    "Requester cannot self-approve"
                )

            matching_roles = (
                approver.roles
                & request.required_roles
            )

            if not matching_roles:
                raise PermissionError(
                    "Approver lacks required role"
                )

            if (
                approver.user_id
                in request.approvals
            ):
                raise ValueError(
                    "User already approved"
                )

            # Assign one eligible role
            # that is not already represented.
            used_roles = set(
                request.approvals.values()
            )

            available_roles = sorted(
                matching_roles - used_roles
            )

            if not available_roles:
                raise PermissionError(
                    "A distinct approval role "
                    "is required"
                )

            role = available_roles[0]

            request.approvals[
                approver.user_id
            ] = role

            self._log(
                request,
                approver.user_id,
                "approved_by_user",
                {"role": role},
            )

            if (
                len(request.approvals)
                >= request.minimum_approvals
            ):
                request.status = (
                    ApprovalStatus.APPROVED
                )

                self._log(
                    request,
                    "system",
                    "fully_approved",
                )

            return copy.deepcopy(
                request
            )

    def reject(
        self,
        request_id: str,
        approver: ApprovalActor,
        reason: str,
    ) -> ApprovalRequest:
        with self._lock:
            request = self._get(
                request_id,
                approver,
            )

            self._refresh_expiration(
                request
            )

            if request.status != (
                ApprovalStatus.PENDING
            ):
                raise ValueError(
                    "Request cannot be rejected"
                )

            if not (
                approver.roles
                & request.required_roles
            ):
                raise PermissionError(
                    "Rejection role not authorized"
                )

            if (
                not isinstance(reason, str)
                or not reason.strip()
            ):
                raise ValueError(
                    "Rejection reason required"
                )

            request.status = (
                ApprovalStatus.REJECTED
            )

            request.rejection_reason = (
                reason.strip()
            )

            self._log(
                request,
                approver.user_id,
                "rejected",
                {"reason": reason.strip()},
            )

            return copy.deepcopy(
                request
            )

    def cancel(
        self,
        request_id: str,
        actor: ApprovalActor,
    ) -> ApprovalRequest:
        with self._lock:
            request = self._get(
                request_id,
                actor,
            )

            self._refresh_expiration(
                request
            )

            if (
                actor.user_id
                != request.requester_id
            ):
                raise PermissionError(
                    "Only requester may cancel"
                )

            if request.status not in (
                ApprovalStatus.PENDING,
                ApprovalStatus.APPROVED,
            ):
                raise ValueError(
                    "Request cannot be cancelled"
                )

            request.status = (
                ApprovalStatus.CANCELLED
            )

            self._log(
                request,
                actor.user_id,
                "cancelled",
            )

            return copy.deepcopy(
                request
            )

    def get_request(
        self,
        request_id: str,
        actor: ApprovalActor,
    ) -> ApprovalRequest:
        with self._lock:
            request = self._get(
                request_id,
                actor,
            )

            self._refresh_expiration(
                request
            )

            return copy.deepcopy(
                request
            )

    def list_requests(
        self,
        actor: ApprovalActor,
        status: ApprovalStatus | None = None,
    ) -> list[ApprovalRequest]:
        with self._lock:
            self._validate_actor(
                actor
            )

            results = []

            for request in self._requests.values():
                if (
                    request.tenant_id
                    != actor.tenant_id
                ):
                    continue

                self._refresh_expiration(
                    request
                )

                # Requester sees own requests;
                # eligible approvers see
                # actionable requests.
                can_view = (
                    actor.user_id
                    == request.requester_id
                    or bool(
                        actor.roles
                        & request.required_roles
                    )
                )

                if not can_view:
                    continue

                if (
                    status is not None
                    and request.status != status
                ):
                    continue

                results.append(
                    copy.deepcopy(request)
                )

            return results

    def execute_approved(
        self,
        request_id: str,
        actor: ApprovalActor,
        executor: Callable[
            [ActionType, dict[str, Any], str],
            Any,
        ],
    ) -> ApprovalRequest:
        """
        Execute a previously approved
        action through a trusted gateway.

        executor receives:
            action_type
            immutable-copy payload
            execution_id

        Executor must enforce:
        - business authorization
        - transaction/idempotency
        - current policy validation
        - downstream access controls

        No automatic retry is performed.
        """

        if not callable(executor):
            raise ValueError(
                "Executor must be callable"
            )

        with self._lock:
            request = self._get(
                request_id,
                actor,
            )

            self._refresh_expiration(
                request
            )

            if request.status != (
                ApprovalStatus.APPROVED
            ):
                raise PermissionError(
                    "Request is not approved"
                )

            if "execution_operator" not in (
                actor.roles
            ):
                raise PermissionError(
                    "Execution role required"
                )

            if self._hash_payload(
                request.payload
            ) != request.payload_hash:
                raise ValueError(
                    "Approved payload was modified"
                )

            execution_id = str(
                uuid.uuid4()
            )

            request.execution_id = (
                execution_id
            )

            request.status = (
                ApprovalStatus.EXECUTING
            )

            self._log(
                request,
                actor.user_id,
                "execution_started",
                {
                    "execution_id": (
                        execution_id
                    )
                },
            )

            action_type = (
                request.action_type
            )

            payload = copy.deepcopy(
                request.payload
            )

        # Execute outside the lock.
        # A production implementation
        # must persist the execution
        # claim before this call.
        try:
            result = executor(
                action_type,
                payload,
                execution_id,
            )
        except Exception as exc:
            with self._lock:
                request.status = (
                    ApprovalStatus.EXECUTION_FAILED
                )

                self._log(
                    request,
                    actor.user_id,
                    "execution_failed",
                    {
                        "error_type": (
                            type(exc).__name__
                        )
                    },
                )

                return copy.deepcopy(
                    request
                )

        with self._lock:
            request.execution_result = (
                copy.deepcopy(result)
            )

            request.status = (
                ApprovalStatus.EXECUTED
            )

            self._log(
                request,
                actor.user_id,
                "executed",
                {
                    "execution_id": (
                        execution_id
                    )
                },
            )

            return copy.deepcopy(
                request
            )

    def audit_events(
        self,
        request_id: str,
        actor: ApprovalActor,
    ) -> list[ApprovalAuditEvent]:
        with self._lock:
            request = self._get(
                request_id,
                actor,
            )

            if not (
                actor.user_id
                == request.requester_id
                or actor.roles
                & request.required_roles
                or "auditor" in actor.roles
            ):
                raise PermissionError(
                    "Audit access denied"
                )

            return [
                copy.deepcopy(event)
                for event in self._audit
                if (
                    event.request_id
                    == request_id
                    and event.tenant_id
                    == actor.tenant_id
                )
            ]


if __name__ == "__main__":
    service = RetailApprovalService()

    agent = ApprovalActor(
        user_id="retail-ai-agent",
        tenant_id="demo",
        roles=frozenset({
            "ai_agent",
        }),
    )

    procurement_manager = ApprovalActor(
        user_id="procurement-user",
        tenant_id="demo",
        roles=frozenset({
            "procurement_manager",
        }),
    )

    finance_manager = ApprovalActor(
        user_id="finance-user",
        tenant_id="demo",
        roles=frozenset({
            "finance_manager",
        }),
    )

    operator = ApprovalActor(
        user_id="execution-user",
        tenant_id="demo",
        roles=frozenset({
            "execution_operator",
        }),
    )

    request = service.create_request(
        requester=agent,
        action_type=ActionType.PURCHASE_ORDER,
        payload={
            "supplier_id": "SUP001",
            "sku": "SKU001",
            "quantity": 100,
            "unit_price": 500,
            "currency": "INR",
        },
        reason=(
            "AI detected inventory "
            "below reorder threshold"
        ),
    )

    print(
        "Created:",
        request.status.value,
    )

    request = service.approve(
        request.request_id,
        procurement_manager,
    )

    print(
        "First approval:",
        request.status.value,
    )

    request = service.approve(
        request.request_id,
        finance_manager,
    )

    print(
        "Second approval:",
        request.status.value,
    )

    def demo_executor(
        action_type: ActionType,
        payload: dict[str, Any],
        execution_id: str,
    ) -> dict[str, Any]:
        # Demonstration only.
        # No real purchase order is sent.
        return {
            "execution_id": execution_id,
            "action": action_type.value,
            "status": "simulated",
            "sku": payload["sku"],
        }

    request = service.execute_approved(
        request.request_id,
        operator,
        demo_executor,
    )

    print(
        "Execution:",
        request.status.value,
    )

    print(
        json.dumps(
            asdict(request),
            indent=2,
            default=str,
        )
    )
