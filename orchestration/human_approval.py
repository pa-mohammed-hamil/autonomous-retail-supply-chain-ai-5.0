"""Planned module: human approval. Implementation pending."""

"""
File: ai/orchestration/human_approval.py

Human-in-the-loop approval management.
Python 3.10+ | Standard library only

This baseline stores approval requests in memory.
Use persistent storage for production deployments.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


class ApprovalError(ValueError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ApprovalRequest:
    approval_id: str
    workflow_id: str
    tenant_id: str
    node_id: str
    requested_by: str
    allowed_approver_roles: set[str]
    reason: str
    payload: dict[str, Any]
    status: str = "pending"
    created_at: str = field(default_factory=now)
    decided_at: str | None = None
    decided_by: str | None = None
    decision_reason: str | None = None


class HumanApprovalManager:
    def __init__(self) -> None:
        self._requests: dict[str, ApprovalRequest] = {}
        self._lock = threading.RLock()

    def create_request(
        self,
        workflow_id: str,
        tenant_id: str,
        node_id: str,
        requested_by: str,
        allowed_approver_roles: set[str],
        reason: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not all([
            workflow_id, tenant_id, node_id,
            requested_by, reason,
        ]):
            raise ApprovalError(
                "Missing required approval fields."
            )

        if not allowed_approver_roles:
            raise ApprovalError(
                "At least one approver role is required."
            )

        if not isinstance(payload, dict):
            raise ApprovalError(
                "Approval payload must be a dictionary."
            )

        request = ApprovalRequest(
            approval_id=str(uuid4()),
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            node_id=node_id,
            requested_by=requested_by,
            allowed_approver_roles=set(
                allowed_approver_roles
            ),
            reason=reason,
            payload=dict(payload),
        )

        with self._lock:
            self._requests[request.approval_id] = request

        return self._serialize(request)

    def _serialize(
        self, request: ApprovalRequest
    ) -> dict[str, Any]:
        result = asdict(request)
        result["allowed_approver_roles"] = sorted(
            request.allowed_approver_roles
        )
        return result

    def get_request(
        self,
        approval_id: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            request = self._requests.get(approval_id)

            if request is None or request.tenant_id != tenant_id:
                raise ApprovalError(
                    "Approval request not found."
                )

            return self._serialize(request)

    def decide(
        self,
        approval_id: str,
        tenant_id: str,
        approver_id: str,
        approver_roles: set[str],
        approved: bool,
        reason: str,
    ) -> dict[str, Any]:
        if not isinstance(approved, bool):
            raise ApprovalError(
                "approved must be boolean."
            )

        if not reason.strip():
            raise ApprovalError(
                "Decision reason is required."
            )

        with self._lock:
            request = self._requests.get(approval_id)

            if request is None or request.tenant_id != tenant_id:
                raise ApprovalError(
                    "Approval request not found."
                )

            if request.status != "pending":
                raise ApprovalError(
                    "Approval request already decided."
                )

            if not (
                request.allowed_approver_roles
                & approver_roles
            ):
                raise ApprovalError(
                    "Approver lacks required role."
                )

            if approver_id == request.requested_by:
                raise ApprovalError(
                    "Requester cannot self-approve."
                )

            request.status = (
                "approved" if approved else "rejected"
            )
            request.decided_at = now()
            request.decided_by = approver_id
            request.decision_reason = reason

            return self._serialize(request)

    def pending_requests(
        self,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        with self._lock:
            return [
                self._serialize(request)
                for request in self._requests.values()
                if (
                    request.tenant_id == tenant_id
                    and request.status == "pending"
                )
            ]
