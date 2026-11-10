from __future__ import annotations

"""Planned module: supplier. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
backend/services/supplier_service.py

Python 3.10+ | Standard library only

Features:
- Tenant-isolated supplier registry
- Role-based authorization
- Supplier onboarding and approval
- Active / suspended / inactive lifecycle
- Contact management
- Product catalog by supplier
- Lead-time and pricing information
- Supplier performance records
- Weighted reliability scoring
- Procurement eligibility
- Audit trail
- Event outbox
- JSON export

Reference implementation, in-memory only.
"""


import copy
import json
import math
import threading
import uuid

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, Callable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def required(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 255
    ):
        raise ValueError(f"Invalid {name}")
    return value.strip()


def money(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("Invalid money")

    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0:
            raise ValueError("Invalid money")
        return result.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid money") from exc


def percent(value: Any) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0 <= float(value) <= 100
    ):
        raise ValueError("Percentage must be 0-100")
    return float(value)


class SupplierStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    INACTIVE = "inactive"


@dataclass(frozen=True)
class SupplierActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    is_active: bool = True


@dataclass(frozen=True)
class SupplierProduct:
    sku: str
    unit_cost: Decimal
    lead_time_days: int
    minimum_order_quantity: int


@dataclass(frozen=True)
class SupplierPerformance:
    performance_id: str
    supplier_id: str
    on_time_delivery_pct: float
    quality_acceptance_pct: float
    order_accuracy_pct: float
    recorded_at: str


@dataclass
class RetailSupplier:
    supplier_id: str
    tenant_id: str
    name: str
    contact_email: str
    country: str
    status: SupplierStatus
    products: dict[str, SupplierProduct]
    performance: list[SupplierPerformance]
    created_at: str
    updated_at: str
    version: int = 1


@dataclass(frozen=True)
class SupplierAuditEvent:
    event_id: str
    tenant_id: str
    supplier_id: str
    actor_id: str
    action: str
    timestamp: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SupplierOutboxEvent:
    event_id: str
    tenant_id: str
    supplier_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: str
    delivered: bool = False


ApprovalVerifier = Callable[[str, str, str], bool]


class RetailSupplierService:
    WRITER_ROLES = frozenset({
        "supplier_manager",
        "procurement_manager",
        "operations_manager",
        "corporate_admin",
    })

    APPROVER_ROLES = frozenset({
        "procurement_manager",
        "corporate_admin",
    })

    READER_ROLES = WRITER_ROLES | frozenset({
        "supplier_analyst",
        "inventory_manager",
        "demand_planner",
        "business_analyst",
    })

    def __init__(
        self,
        tenant_id: str,
        currency: str = "INR",
        approval_verifier: ApprovalVerifier | None = None,
    ):
        self.tenant_id = required(tenant_id, "tenant_id")
        self.currency = required(currency, "currency").upper()
        self.approval_verifier = approval_verifier

        self._lock = threading.RLock()
        self._suppliers: dict[str, RetailSupplier] = {}
        self._audit: list[SupplierAuditEvent] = []
        self._outbox: dict[str, SupplierOutboxEvent] = {}

    def _authorize(
        self,
        actor: SupplierActor,
        roles: frozenset[str],
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.user_id.strip()
            or not actor.roles.intersection(roles)
        ):
            raise PermissionError("Supplier access denied")

    def _get(self, supplier_id: str) -> RetailSupplier:
        supplier = self._suppliers.get(supplier_id)
        if supplier is None:
            raise KeyError("Supplier not found")
        return supplier

    def _record(
        self,
        actor_id: str,
        supplier: RetailSupplier,
        action: str,
        details: dict | None = None,
    ) -> None:
        self._audit.append(SupplierAuditEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            supplier_id=supplier.supplier_id,
            actor_id=actor_id,
            action=action,
            timestamp=utc_now(),
            details=copy.deepcopy(details or {}),
        ))

        event = SupplierOutboxEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            supplier_id=supplier.supplier_id,
            event_type=f"supplier.{action}",
            payload={
                "supplier_id": supplier.supplier_id,
                "status": supplier.status.value,
                "version": supplier.version,
            },
            created_at=utc_now(),
        )
        self._outbox[event.event_id] = event

    @staticmethod
    def _touch(supplier: RetailSupplier) -> None:
        supplier.version += 1
        supplier.updated_at = utc_now()

    def register_supplier(
        self,
        actor: SupplierActor,
        supplier_id: str,
        name: str,
        contact_email: str,
        country: str,
    ) -> RetailSupplier:
        self._authorize(actor, self.WRITER_ROLES)

        supplier_id = required(supplier_id, "supplier_id")
        name = required(name, "name")
        contact_email = required(
            contact_email, "contact_email"
        )
        country = required(country, "country")

        with self._lock:
            if supplier_id in self._suppliers:
                raise ValueError("Supplier already exists")

            current = utc_now()

            supplier = RetailSupplier(
                supplier_id=supplier_id,
                tenant_id=self.tenant_id,
                name=name,
                contact_email=contact_email,
                country=country,
                status=SupplierStatus.PENDING,
                products={},
                performance=[],
                created_at=current,
                updated_at=current,
            )

            self._suppliers[supplier_id] = supplier
            self._record(
                actor.user_id, supplier, "registered"
            )
            return copy.deepcopy(supplier)

    def activate_supplier(
        self,
        actor: SupplierActor,
        supplier_id: str,
        expected_version: int,
        approval_reference: str,
    ) -> RetailSupplier:
        self._authorize(actor, self.APPROVER_ROLES)
        approval_reference = required(
            approval_reference, "approval_reference"
        )

        with self._lock:
            supplier = self._get(supplier_id)

            if supplier.version != expected_version:
                raise ValueError("Version conflict")

            if supplier.status not in {
                SupplierStatus.PENDING,
                SupplierStatus.SUSPENDED,
            }:
                raise ValueError("Invalid activation transition")

            if self.approval_verifier is None:
                raise PermissionError(
                    "Approval verifier not configured"
                )

            if not self.approval_verifier(
                supplier_id,
                "activate",
                approval_reference,
            ):
                raise PermissionError("Approval denied")

            supplier.status = SupplierStatus.ACTIVE
            self._touch(supplier)
            self._record(
                actor.user_id,
                supplier,
                "activated",
                {"approval_reference": approval_reference},
            )
            return copy.deepcopy(supplier)

    def suspend_supplier(
        self,
        actor: SupplierActor,
        supplier_id: str,
        expected_version: int,
        reason: str,
    ) -> RetailSupplier:
        self._authorize(actor, self.APPROVER_ROLES)
        reason = required(reason, "reason")

        with self._lock:
            supplier = self._get(supplier_id)

            if supplier.version != expected_version:
                raise ValueError("Version conflict")

            if supplier.status != SupplierStatus.ACTIVE:
                raise ValueError("Only active suppliers can be suspended")

            supplier.status = SupplierStatus.SUSPENDED
            self._touch(supplier)
            self._record(
                actor.user_id,
                supplier,
                "suspended",
                {"reason": reason},
            )
            return copy.deepcopy(supplier)

    def deactivate_supplier(
        self,
        actor: SupplierActor,
        supplier_id: str,
        expected_version: int,
    ) -> RetailSupplier:
        self._authorize(actor, self.APPROVER_ROLES)

        with self._lock:
            supplier = self._get(supplier_id)

            if supplier.version != expected_version:
                raise ValueError("Version conflict")

            if supplier.status == SupplierStatus.INACTIVE:
                raise ValueError("Supplier already inactive")

            supplier.status = SupplierStatus.INACTIVE
            self._touch(supplier)
            self._record(
                actor.user_id, supplier, "deactivated"
            )
            return copy.deepcopy(supplier)

    def update_contact(
        self,
        actor: SupplierActor,
        supplier_id: str,
        expected_version: int,
        contact_email: str,
    ) -> RetailSupplier:
        self._authorize(actor, self.WRITER_ROLES)
        contact_email = required(
            contact_email, "contact_email"
        )

        with self._lock:
            supplier = self._get(supplier_id)

            if supplier.version != expected_version:
                raise ValueError("Version conflict")

            if supplier.status == SupplierStatus.INACTIVE:
                raise ValueError("Inactive supplier cannot be edited")

            supplier.contact_email = contact_email
            self._touch(supplier)
            self._record(
                actor.user_id, supplier, "contact_updated"
            )
            return copy.deepcopy(supplier)

    def add_product(
        self,
        actor: SupplierActor,
        supplier_id: str,
        expected_version: int,
        sku: str,
        unit_cost: Any,
        lead_time_days: int,
        minimum_order_quantity: int,
    ) -> RetailSupplier:
        self._authorize(actor, self.WRITER_ROLES)

        sku = required(sku, "sku")
        cost = money(unit_cost)

        if (
            type(lead_time_days) is not int
            or lead_time_days < 0
            or type(minimum_order_quantity) is not int
            or minimum_order_quantity <= 0
        ):
            raise ValueError("Invalid sourcing constraints")

        with self._lock:
            supplier = self._get(supplier_id)

            if supplier.version != expected_version:
                raise ValueError("Version conflict")

            if supplier.status == SupplierStatus.INACTIVE:
                raise ValueError("Inactive supplier")

            if sku in supplier.products:
                raise ValueError("SKU already registered")

            supplier.products[sku] = SupplierProduct(
                sku=sku,
                unit_cost=cost,
                lead_time_days=lead_time_days,
                minimum_order_quantity=minimum_order_quantity,
            )

            self._touch(supplier)
            self._record(
                actor.user_id,
                supplier,
                "product_added",
                {"sku": sku},
            )
            return copy.deepcopy(supplier)

    def record_performance(
        self,
        actor: SupplierActor,
        supplier_id: str,
        expected_version: int,
        on_time_delivery_pct: float,
        quality_acceptance_pct: float,
        order_accuracy_pct: float,
    ) -> RetailSupplier:
        self._authorize(actor, self.WRITER_ROLES)

        on_time = percent(on_time_delivery_pct)
        quality = percent(quality_acceptance_pct)
        accuracy = percent(order_accuracy_pct)

        with self._lock:
            supplier = self._get(supplier_id)

            if supplier.version != expected_version:
                raise ValueError("Version conflict")

            if supplier.status == SupplierStatus.INACTIVE:
                raise ValueError("Inactive supplier")

            supplier.performance.append(SupplierPerformance(
                performance_id=str(uuid.uuid4()),
                supplier_id=supplier_id,
                on_time_delivery_pct=on_time,
                quality_acceptance_pct=quality,
                order_accuracy_pct=accuracy,
                recorded_at=utc_now(),
            ))

            self._touch(supplier)
            self._record(
                actor.user_id,
                supplier,
                "performance_recorded",
            )
            return copy.deepcopy(supplier)

    @staticmethod
    def supplier_score(
        supplier: RetailSupplier,
    ) -> float | None:
        if not supplier.performance:
            return None

        scores = [
            (
                0.4 * p.on_time_delivery_pct
                + 0.4 * p.quality_acceptance_pct
                + 0.2 * p.order_accuracy_pct
            )
            for p in supplier.performance
        ]

        return round(sum(scores) / len(scores), 2)

    def procurement_eligibility(
        self,
        actor: SupplierActor,
        supplier_id: str,
        sku: str,
        minimum_score: float = 75.0,
    ) -> dict[str, Any]:
        supplier = self.get_supplier(actor, supplier_id)
        minimum_score = percent(minimum_score)

        score = self.supplier_score(supplier)
        has_product = sku in supplier.products

        eligible = (
            supplier.status == SupplierStatus.ACTIVE
            and has_product
            and score is not None
            and score >= minimum_score
        )

        reasons = []

        if supplier.status != SupplierStatus.ACTIVE:
            reasons.append("Supplier not active")

        if not has_product:
            reasons.append("SKU not supplied")

        if score is None:
            reasons.append("No performance history")
        elif score < minimum_score:
            reasons.append("Supplier score below threshold")

        return {
            "supplier_id": supplier_id,
            "sku": sku,
            "eligible": eligible,
            "score": score,
            "minimum_score": minimum_score,
            "reasons": reasons,
        }

    def get_supplier(
        self,
        actor: SupplierActor,
        supplier_id: str,
    ) -> RetailSupplier:
        self._authorize(actor, self.READER_ROLES)

        with self._lock:
            return copy.deepcopy(self._get(supplier_id))

    def list_suppliers(
        self,
        actor: SupplierActor,
        status: SupplierStatus | None = None,
    ) -> list[RetailSupplier]:
        self._authorize(actor, self.READER_ROLES)

        with self._lock:
            return [
                copy.deepcopy(supplier)
                for supplier in self._suppliers.values()
                if status is None or supplier.status == status
            ]

    def supplier_metrics(
        self,
        actor: SupplierActor,
    ) -> dict[str, Any]:
        suppliers = self.list_suppliers(actor)
        scores = [
            score
            for supplier in suppliers
            if (score := self.supplier_score(supplier))
            is not None
        ]

        return {
            "tenant_id": self.tenant_id,
            "total_suppliers": len(suppliers),
            "active": sum(
                s.status == SupplierStatus.ACTIVE
                for s in suppliers
            ),
            "pending": sum(
                s.status == SupplierStatus.PENDING
                for s in suppliers
            ),
            "suspended": sum(
                s.status == SupplierStatus.SUSPENDED
                for s in suppliers
            ),
            "average_supplier_score": (
                round(sum(scores) / len(scores), 2)
                if scores else None
            ),
        }

    def pending_events(
        self,
        actor: SupplierActor,
    ) -> list[SupplierOutboxEvent]:
        self._authorize(actor, self.WRITER_ROLES)

        with self._lock:
            return [
                copy.deepcopy(event)
                for event in self._outbox.values()
                if not event.delivered
            ]

    def mark_event_delivered(
        self,
        actor: SupplierActor,
        event_id: str,
    ) -> None:
        self._authorize(actor, self.WRITER_ROLES)

        with self._lock:
            event = self._outbox.get(event_id)
            if event is None:
                raise KeyError("Event not found")
            event.delivered = True

    def audit_events(
        self,
        actor: SupplierActor,
        supplier_id: str,
    ) -> list[SupplierAuditEvent]:
        self.get_supplier(actor, supplier_id)

        with self._lock:
            return [
                copy.deepcopy(event)
                for event in self._audit
                if event.supplier_id == supplier_id
            ]

    def export_json(
        self,
        actor: SupplierActor,
        output_path: str | Path,
    ) -> Path:
        suppliers = self.list_suppliers(actor)

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(
            json.dumps(
                [asdict(s) for s in suppliers],
                indent=2,
                default=lambda obj: (
                    obj.value if isinstance(obj, Enum)
                    else str(obj)
                ),
            ),
            encoding="utf-8",
        )

        return path


if __name__ == "__main__":
    def demo_approval(
        supplier_id: str,
        action: str,
        reference: str,
    ) -> bool:
        return (
            action == "activate"
            and reference == "APPROVED-DEMO"
        )

    service = RetailSupplierService(
        tenant_id="demo",
        approval_verifier=demo_approval,
    )

    manager = SupplierActor(
        user_id="manager001",
        tenant_id="demo",
        roles=frozenset({"procurement_manager"}),
    )

    supplier = service.register_supplier(
        manager,
        supplier_id="SUP001",
        name="Smart Supply Technologies",
        contact_email="demo@example.com",
        country="India",
    )

    supplier = service.activate_supplier(
        manager,
        supplier.supplier_id,
        supplier.version,
        "APPROVED-DEMO",
    )

    supplier = service.add_product(
        manager,
        supplier.supplier_id,
        supplier.version,
        sku="SKU001",
        unit_cost="1200.00",
        lead_time_days=7,
        minimum_order_quantity=20,
    )

    supplier = service.record_performance(
        manager,
        supplier.supplier_id,
        supplier.version,
        on_time_delivery_pct=92,
        quality_acceptance_pct=96,
        order_accuracy_pct=94,
    )

    print("Supplier:", supplier.name)
    print("Score:", service.supplier_score(supplier))
    print(
        "Eligibility:",
        service.procurement_eligibility(
            manager, "SUP001", "SKU001"
        ),
    )
