from __future__ import annotations

"""Planned module: replenishment. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
backend/services/replenishment_service.py

Python 3.10+ | Standard library only

Features:
- Tenant and warehouse RBAC
- Reorder point calculation
- Demand-driven stock targets
- Incoming stock awareness
- Batch recommendations
- Replenishment request lifecycle
- External approval verification
- Procurement handoff events
- Optimistic version checks
- Source-reference idempotency
- Audit trail
- Notification outbox
- JSON export

In-memory reference implementation.
"""


import copy
import json
import math
import threading
import uuid

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid {name}")
    if len(value) > 255:
        raise ValueError(f"{name} too long")
    return value.strip()


def nonnegative_int(value: int, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be nonnegative integer")
    return value


def nonnegative_float(value: float, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"Invalid {name}")
    return float(value)


class ReplenishmentStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUBMITTED = "submitted"
    CANCELLED = "cancelled"


class ReplenishmentRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ReplenishmentActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str] = frozenset()
    is_active: bool = True


@dataclass(frozen=True)
class ReplenishmentInput:
    tenant_id: str
    warehouse_id: str
    sku: str
    on_hand: int
    reserved: int
    incoming: int
    average_daily_demand: float
    lead_time_days: int
    review_period_days: int
    safety_stock: int
    minimum_order_quantity: int = 1
    order_multiple: int = 1


@dataclass(frozen=True)
class ReplenishmentRecommendation:
    warehouse_id: str
    sku: str
    available: int
    inventory_position: int
    reorder_point: int
    target_stock: int
    suggested_quantity: int
    risk: ReplenishmentRisk
    requires_replenishment: bool


@dataclass
class ReplenishmentRequest:
    request_id: str
    tenant_id: str
    warehouse_id: str
    sku: str
    quantity: int
    status: ReplenishmentStatus
    source_reference: str
    created_by: str
    approved_by: str | None
    approval_reference: str | None
    procurement_reference: str | None
    rejection_reason: str | None
    created_at: str
    updated_at: str
    version: int = 1


@dataclass(frozen=True)
class ReplenishmentAuditEvent:
    event_id: str
    tenant_id: str
    request_id: str
    actor_id: str
    action: str
    timestamp: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplenishmentOutboxEvent:
    event_id: str
    tenant_id: str
    request_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: str
    delivered: bool = False


ApprovalVerifier = Callable[[str, str], bool]


class RetailReplenishmentService:
    PLANNER_ROLES = frozenset({
        "inventory_manager",
        "demand_planner",
        "procurement_manager",
        "operations_manager",
        "corporate_admin",
    })

    APPROVER_ROLES = frozenset({
        "procurement_manager",
        "operations_manager",
        "corporate_admin",
    })

    READER_ROLES = PLANNER_ROLES | frozenset({
        "inventory_analyst",
        "warehouse_manager",
    })

    def __init__(
        self,
        tenant_id: str,
        approval_verifier: ApprovalVerifier | None = None,
    ):
        self.tenant_id = required(tenant_id, "tenant_id")
        self.approval_verifier = approval_verifier

        self._lock = threading.RLock()
        self._requests: dict[str, ReplenishmentRequest] = {}
        self._source_index: dict[str, str] = {}
        self._audit: list[ReplenishmentAuditEvent] = []
        self._outbox: dict[str, ReplenishmentOutboxEvent] = {}

    def _authorize(
        self,
        actor: ReplenishmentActor,
        roles: frozenset[str],
        warehouse_id: str,
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.user_id.strip()
            or not actor.roles.intersection(roles)
        ):
            raise PermissionError("Replenishment access denied")

        if (
            "corporate_admin" not in actor.roles
            and warehouse_id not in actor.warehouse_ids
        ):
            raise PermissionError("Warehouse scope denied")

    def _get(self, request_id: str) -> ReplenishmentRequest:
        request = self._requests.get(request_id)
        if request is None:
            raise KeyError("Replenishment request not found")
        return request

    def _record(
        self,
        actor_id: str,
        request: ReplenishmentRequest,
        action: str,
        details: dict | None = None,
    ) -> None:
        self._audit.append(ReplenishmentAuditEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            request_id=request.request_id,
            actor_id=actor_id,
            action=action,
            timestamp=utc_now(),
            details=copy.deepcopy(details or {}),
        ))

        event = ReplenishmentOutboxEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            request_id=request.request_id,
            event_type=f"replenishment.{action}",
            payload={
                "request_id": request.request_id,
                "warehouse_id": request.warehouse_id,
                "sku": request.sku,
                "quantity": request.quantity,
                "status": request.status.value,
            },
            created_at=utc_now(),
        )

        self._outbox[event.event_id] = event

    @staticmethod
    def _touch(request: ReplenishmentRequest) -> None:
        request.version += 1
        request.updated_at = utc_now()

    def recommend(
        self,
        actor: ReplenishmentActor,
        data: ReplenishmentInput,
    ) -> ReplenishmentRecommendation:
        self._authorize(
            actor, self.READER_ROLES, data.warehouse_id
        )

        if data.tenant_id != self.tenant_id:
            raise PermissionError("Cross-tenant replenishment")

        required(data.warehouse_id, "warehouse_id")
        required(data.sku, "sku")

        for name in (
            "on_hand", "reserved", "incoming",
            "lead_time_days", "review_period_days",
            "safety_stock",
        ):
            nonnegative_int(getattr(data, name), name)

        nonnegative_float(
            data.average_daily_demand,
            "average_daily_demand",
        )

        if data.reserved > data.on_hand:
            raise ValueError("Reserved exceeds on-hand stock")

        if (
            type(data.minimum_order_quantity) is not int
            or data.minimum_order_quantity < 1
            or type(data.order_multiple) is not int
            or data.order_multiple < 1
        ):
            raise ValueError("Invalid ordering constraints")

        available = data.on_hand - data.reserved
        inventory_position = available + data.incoming

        reorder_point = math.ceil(
            data.average_daily_demand * data.lead_time_days
            + data.safety_stock
        )

        target_stock = math.ceil(
            data.average_daily_demand * (
                data.lead_time_days
                + data.review_period_days
            ) + data.safety_stock
        )

        needs_order = inventory_position <= reorder_point

        if needs_order:
            raw = max(
                0, target_stock - inventory_position
            )

            if raw > 0:
                raw = max(
                    raw, data.minimum_order_quantity
                )
                suggested = (
                    math.ceil(raw / data.order_multiple)
                    * data.order_multiple
                )
            else:
                suggested = 0
        else:
            suggested = 0

        if available <= 0:
            risk = ReplenishmentRisk.CRITICAL
        elif available <= data.safety_stock:
            risk = ReplenishmentRisk.HIGH
        elif inventory_position <= reorder_point:
            risk = ReplenishmentRisk.MEDIUM
        else:
            risk = ReplenishmentRisk.LOW

        return ReplenishmentRecommendation(
            warehouse_id=data.warehouse_id,
            sku=data.sku,
            available=available,
            inventory_position=inventory_position,
            reorder_point=reorder_point,
            target_stock=target_stock,
            suggested_quantity=suggested,
            risk=risk,
            requires_replenishment=suggested > 0,
        )

    def recommend_batch(
        self,
        actor: ReplenishmentActor,
        inputs: Iterable[ReplenishmentInput],
    ) -> list[ReplenishmentRecommendation]:
        return [
            self.recommend(actor, item)
            for item in inputs
        ]

    def create_request(
        self,
        actor: ReplenishmentActor,
        recommendation: ReplenishmentRecommendation,
        source_reference: str,
    ) -> ReplenishmentRequest:
        self._authorize(
            actor, self.PLANNER_ROLES,
            recommendation.warehouse_id,
        )

        source_reference = required(
            source_reference, "source_reference"
        )

        if recommendation.suggested_quantity <= 0:
            raise ValueError("No replenishment needed")

        with self._lock:
            existing_id = self._source_index.get(source_reference)

            if existing_id:
                existing = self._requests[existing_id]

                if (
                    existing.warehouse_id
                    != recommendation.warehouse_id
                    or existing.sku != recommendation.sku
                    or existing.quantity
                    != recommendation.suggested_quantity
                ):
                    raise ValueError("Conflicting source reference")

                return copy.deepcopy(existing)

            current = utc_now()

            request = ReplenishmentRequest(
                request_id=str(uuid.uuid4()),
                tenant_id=self.tenant_id,
                warehouse_id=recommendation.warehouse_id,
                sku=recommendation.sku,
                quantity=recommendation.suggested_quantity,
                status=ReplenishmentStatus.PENDING_APPROVAL,
                source_reference=source_reference,
                created_by=actor.user_id,
                approved_by=None,
                approval_reference=None,
                procurement_reference=None,
                rejection_reason=None,
                created_at=current,
                updated_at=current,
            )

            self._requests[request.request_id] = request
            self._source_index[source_reference] = request.request_id

            self._record(
                actor.user_id, request, "requested"
            )
            return copy.deepcopy(request)

    def approve_request(
        self,
        actor: ReplenishmentActor,
        request_id: str,
        expected_version: int,
        approval_reference: str,
    ) -> ReplenishmentRequest:
        approval_reference = required(
            approval_reference, "approval_reference"
        )

        with self._lock:
            request = self._get(request_id)
            self._authorize(
                actor, self.APPROVER_ROLES,
                request.warehouse_id,
            )

            if request.version != expected_version:
                raise ValueError("Version conflict")

            if request.status != ReplenishmentStatus.PENDING_APPROVAL:
                raise ValueError("Request not pending approval")

            if actor.user_id == request.created_by:
                raise PermissionError(
                    "Requester cannot approve own request"
                )

            if self.approval_verifier is None:
                raise PermissionError(
                    "Approval verifier not configured"
                )

            if not self.approval_verifier(
                "inventory_replenishment",
                approval_reference,
            ):
                raise PermissionError("Approval verification failed")

            request.status = ReplenishmentStatus.APPROVED
            request.approved_by = actor.user_id
            request.approval_reference = approval_reference
            self._touch(request)

            self._record(
                actor.user_id, request, "approved",
                {"approval_reference": approval_reference},
            )
            return copy.deepcopy(request)

    def reject_request(
        self,
        actor: ReplenishmentActor,
        request_id: str,
        expected_version: int,
        reason: str,
    ) -> ReplenishmentRequest:
        reason = required(reason, "reason")

        with self._lock:
            request = self._get(request_id)
            self._authorize(
                actor, self.APPROVER_ROLES,
                request.warehouse_id,
            )

            if request.version != expected_version:
                raise ValueError("Version conflict")

            if request.status != ReplenishmentStatus.PENDING_APPROVAL:
                raise ValueError("Request not pending approval")

            request.status = ReplenishmentStatus.REJECTED
            request.rejection_reason = reason
            self._touch(request)

            self._record(
                actor.user_id, request, "rejected",
                {"reason": reason},
            )
            return copy.deepcopy(request)

    def submit_to_procurement(
        self,
        actor: ReplenishmentActor,
        request_id: str,
        expected_version: int,
        procurement_reference: str,
    ) -> ReplenishmentRequest:
        procurement_reference = required(
            procurement_reference, "procurement_reference"
        )

        with self._lock:
            request = self._get(request_id)
            self._authorize(
                actor, self.APPROVER_ROLES,
                request.warehouse_id,
            )

            if request.version != expected_version:
                raise ValueError("Version conflict")

            if request.status != ReplenishmentStatus.APPROVED:
                raise ValueError("Request must be approved")

            request.status = ReplenishmentStatus.SUBMITTED
            request.procurement_reference = procurement_reference
            self._touch(request)

            self._record(
                actor.user_id, request, "submitted",
                {"procurement_reference": procurement_reference},
            )
            return copy.deepcopy(request)

    def cancel_request(
        self,
        actor: ReplenishmentActor,
        request_id: str,
        expected_version: int,
    ) -> ReplenishmentRequest:
        with self._lock:
            request = self._get(request_id)
            self._authorize(
                actor, self.PLANNER_ROLES,
                request.warehouse_id,
            )

            if request.version != expected_version:
                raise ValueError("Version conflict")

            if request.status not in {
                ReplenishmentStatus.PENDING_APPROVAL,
                ReplenishmentStatus.APPROVED,
            }:
                raise ValueError("Request cannot be cancelled")

            request.status = ReplenishmentStatus.CANCELLED
            self._touch(request)

            self._record(
                actor.user_id, request, "cancelled"
            )
            return copy.deepcopy(request)

    def get_request(
        self,
        actor: ReplenishmentActor,
        request_id: str,
    ) -> ReplenishmentRequest:
        with self._lock:
            request = self._get(request_id)
            self._authorize(
                actor, self.READER_ROLES,
                request.warehouse_id,
            )
            return copy.deepcopy(request)

    def list_requests(
        self,
        actor: ReplenishmentActor,
        status: ReplenishmentStatus | None = None,
    ) -> list[ReplenishmentRequest]:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.roles.intersection(self.READER_ROLES)
        ):
            raise PermissionError("Replenishment access denied")

        with self._lock:
            return [
                copy.deepcopy(request)
                for request in self._requests.values()
                if (
                    (
                        "corporate_admin" in actor.roles
                        or request.warehouse_id in actor.warehouse_ids
                    )
                    and (
                        status is None
                        or request.status == status
                    )
                )
            ]

    def metrics(
        self,
        actor: ReplenishmentActor,
    ) -> dict[str, Any]:
        records = self.list_requests(actor)

        return {
            "tenant_id": self.tenant_id,
            "total_requests": len(records),
            "pending_approval": sum(
                r.status == ReplenishmentStatus.PENDING_APPROVAL
                for r in records
            ),
            "approved": sum(
                r.status == ReplenishmentStatus.APPROVED
                for r in records
            ),
            "submitted": sum(
                r.status == ReplenishmentStatus.SUBMITTED
                for r in records
            ),
            "rejected": sum(
                r.status == ReplenishmentStatus.REJECTED
                for r in records
            ),
            "cancelled": sum(
                r.status == ReplenishmentStatus.CANCELLED
                for r in records
            ),
            "submitted_units": sum(
                r.quantity
                for r in records
                if r.status == ReplenishmentStatus.SUBMITTED
            ),
        }

    def pending_events(
        self,
        actor: ReplenishmentActor,
    ) -> list[ReplenishmentOutboxEvent]:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.roles.intersection(self.PLANNER_ROLES)
        ):
            raise PermissionError("Outbox access denied")

        with self._lock:
            return [
                copy.deepcopy(event)
                for event in self._outbox.values()
                if (
                    not event.delivered
                    and (
                        "corporate_admin" in actor.roles
                        or self._requests[
                            event.request_id
                        ].warehouse_id in actor.warehouse_ids
                    )
                )
            ]

    def mark_event_delivered(
        self,
        actor: ReplenishmentActor,
        event_id: str,
    ) -> None:
        with self._lock:
            event = self._outbox.get(event_id)
            if event is None:
                raise KeyError("Event not found")

            request = self._get(event.request_id)
            self._authorize(
                actor, self.PLANNER_ROLES,
                request.warehouse_id,
            )
            event.delivered = True

    def audit_events(
        self,
        actor: ReplenishmentActor,
        request_id: str,
    ) -> list[ReplenishmentAuditEvent]:
        self.get_request(actor, request_id)

        with self._lock:
            return [
                copy.deepcopy(event)
                for event in self._audit
                if event.request_id == request_id
            ]

    def export_json(
        self,
        actor: ReplenishmentActor,
        output_path: str | Path,
    ) -> Path:
        records = self.list_requests(actor)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(
            json.dumps(
                [asdict(record) for record in records],
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    def demo_approval(
        action: str,
        reference: str,
    ) -> bool:
        return (
            action == "inventory_replenishment"
            and reference == "APPROVED-DEMO"
        )

    service = RetailReplenishmentService(
        tenant_id="demo",
        approval_verifier=demo_approval,
    )

    planner = ReplenishmentActor(
        user_id="planner001",
        tenant_id="demo",
        roles=frozenset({"demand_planner"}),
        warehouse_ids=frozenset({"WH001"}),
    )

    approver = ReplenishmentActor(
        user_id="manager001",
        tenant_id="demo",
        roles=frozenset({"procurement_manager"}),
        warehouse_ids=frozenset({"WH001"}),
    )

    recommendation = service.recommend(
        planner,
        ReplenishmentInput(
            tenant_id="demo",
            warehouse_id="WH001",
            sku="SKU001",
            on_hand=80,
            reserved=20,
            incoming=10,
            average_daily_demand=15,
            lead_time_days=7,
            review_period_days=7,
            safety_stock=30,
            minimum_order_quantity=20,
            order_multiple=10,
        ),
    )

    print("Recommendation:", recommendation)

    if recommendation.requires_replenishment:
        request = service.create_request(
            planner,
            recommendation,
            source_reference="FORECAST001",
        )

        request = service.approve_request(
            approver,
            request.request_id,
            request.version,
            approval_reference="APPROVED-DEMO",
        )

        request = service.submit_to_procurement(
            approver,
            request.request_id,
            request.version,
            procurement_reference="PO001",
        )

        print("Request:", request.status.value)
        print("Metrics:", service.metrics(approver))
