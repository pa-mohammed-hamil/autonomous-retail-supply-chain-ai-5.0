from __future__ import annotations

"""Planned module: supplier service. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
backend/services/supplier_service.py

Python 3.10+ | Standard library only

Reference implementation.

Features:
- Tenant-isolated supplier registry
- Supplier onboarding
- Supplier status lifecycle
- Compliance evidence references
- Product/SKU assignments
- Supplier performance snapshots
- Procurement eligibility checks
- Optimistic concurrency
- Role-based access control
- Audit trail and event outbox
- JSON export

Important:
- Compliance is not independently verified
- Approvals require a trusted verifier
- Data is stored in memory
- Events are not automatically delivered
"""


import copy
import json
import re
import threading
import uuid

from dataclasses import (
    asdict,
    dataclass,
    field,
)
from datetime import (
    date,
    datetime,
    timezone,
)
from decimal import (
    Decimal,
    InvalidOperation,
)
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def required_text(
    value: str,
    name: str,
    max_length: int = 200,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > max_length
    ):
        raise ValueError(
            f"Invalid {name}"
        )

    return value.strip()


def nonnegative_decimal(
    value: object,
) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(
            "Invalid decimal value"
        )

    try:
        result = Decimal(str(value))
    except (
        InvalidOperation,
        ValueError,
    ) as exc:
        raise ValueError(
            "Invalid decimal value"
        ) from exc

    if (
        not result.is_finite()
        or result < 0
    ):
        raise ValueError(
            "Value must be nonnegative"
        )

    return result


def percentage(
    value: object,
    name: str,
) -> float:
    result = nonnegative_decimal(
        value
    )

    if result > 100:
        raise ValueError(
            f"{name} must be 0-100"
        )

    return float(result)


def positive_int(
    value: int,
    name: str,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        raise ValueError(
            f"{name} must be positive integer"
        )

    return value


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
class SupplierContact:
    contact_name: str
    email: str
    phone: str = ""


@dataclass(frozen=True)
class SupplierProduct:
    sku: str
    unit_cost: Decimal
    lead_time_days: int
    minimum_order_quantity: int = 1


@dataclass(frozen=True)
class SupplierPerformance:
    total_deliveries: int
    on_time_deliveries: int
    inspected_units: int
    defective_units: int
    recorded_at: str


@dataclass
class RetailSupplier:
    supplier_id: str
    tenant_id: str
    name: str
    country: str
    contact: SupplierContact
    categories: tuple[str, ...]
    status: SupplierStatus
    products: dict[
        str, SupplierProduct
    ]
    compliance_references: tuple[
        str, ...
    ]
    compliance_expiry: str | None
    performance: SupplierPerformance | None
    created_by: str
    created_at: str
    updated_at: str
    version: int = 1
    approval_reference: str | None = None
    suspension_reason: str | None = None


@dataclass(frozen=True)
class SupplierAuditEvent:
    event_id: str
    tenant_id: str
    supplier_id: str
    actor_id: str
    action: str
    timestamp: str
    details: dict = field(
        default_factory=dict
    )


@dataclass
class SupplierOutboxEvent:
    event_id: str
    tenant_id: str
    supplier_id: str
    event_type: str
    payload: dict
    created_at: str
    delivered: bool = False


# External verifier should check that
# the approval is valid, current,
# scoped to this supplier and action,
# and not previously consumed.
ApprovalVerifier = Callable[
    [str, str, str],
    bool,
]


class RetailSupplierService:
    MANAGER_ROLES = frozenset({
        "supplier_manager",
        "procurement_manager",
        "operations_manager",
        "corporate_admin",
    })

    REVIEWER_ROLES = frozenset({
        "procurement_manager",
        "risk_manager",
        "corporate_admin",
    })

    READER_ROLES = (
        MANAGER_ROLES
        | REVIEWER_ROLES
        | frozenset({
            "procurement_analyst",
            "supplier_risk_analyst",
            "quality_manager",
        })
    )

    def __init__(
        self,
        tenant_id: str,
        currency: str = "INR",
        approval_verifier: (
            ApprovalVerifier | None
        ) = None,
    ):
        self.tenant_id = required_text(
            tenant_id,
            "tenant_id",
        )

        if not re.fullmatch(
            r"[A-Za-z]{3}",
            currency,
        ):
            raise ValueError(
                "Invalid currency"
            )

        self.currency = (
            currency.upper()
        )

        self.approval_verifier = (
            approval_verifier
        )

        self._lock = (
            threading.RLock()
        )

        self._suppliers: dict[
            str, RetailSupplier
        ] = {}

        self._audit: list[
            SupplierAuditEvent
        ] = []

        self._outbox: dict[
            str, SupplierOutboxEvent
        ] = {}

    def _authorize(
        self,
        actor: SupplierActor,
        roles: frozenset[str],
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id
            != self.tenant_id
            or not actor.user_id.strip()
            or not (actor.roles & roles)
        ):
            raise PermissionError(
                "Supplier access denied"
            )

    def _get(
        self,
        supplier_id: str,
    ) -> RetailSupplier:
        supplier = (
            self._suppliers.get(
                supplier_id
            )
        )

        if supplier is None:
            raise KeyError(
                "Supplier not found"
            )

        return supplier

    def _check_version(
        self,
        supplier: RetailSupplier,
        expected_version: int,
    ) -> None:
        if (
            isinstance(
                expected_version,
                bool,
            )
            or not isinstance(
                expected_version,
                int,
            )
            or supplier.version
            != expected_version
        ):
            raise ValueError(
                "Supplier version conflict"
            )

    def _touch(
        self,
        supplier: RetailSupplier,
    ) -> None:
        supplier.version += 1
        supplier.updated_at = (
            utc_now()
        )

    def _audit_event(
        self,
        actor: SupplierActor,
        supplier: RetailSupplier,
        action: str,
        details: dict | None = None,
    ) -> None:
        self._audit.append(
            SupplierAuditEvent(
                event_id=str(
                    uuid.uuid4()
                ),
                tenant_id=self.tenant_id,
                supplier_id=(
                    supplier.supplier_id
                ),
                actor_id=actor.user_id,
                action=action,
                timestamp=utc_now(),
                details=copy.deepcopy(
                    details or {}
                ),
            )
        )

    def _emit(
        self,
        supplier: RetailSupplier,
        event_type: str,
        payload: dict,
    ) -> None:
        event = SupplierOutboxEvent(
            event_id=str(
                uuid.uuid4()
            ),
            tenant_id=self.tenant_id,
            supplier_id=(
                supplier.supplier_id
            ),
            event_type=event_type,
            payload=copy.deepcopy(
                payload
            ),
            created_at=utc_now(),
        )

        self._outbox[
            event.event_id
        ] = event

    def _verify_approval(
        self,
        supplier_id: str,
        action: str,
        reference: str,
    ) -> None:
        reference = required_text(
            reference,
            "approval_reference",
        )

        if self.approval_verifier is None:
            raise PermissionError(
                "Trusted approval verifier required"
            )

        if not self.approval_verifier(
            supplier_id,
            action,
            reference,
        ):
            raise PermissionError(
                "Approval verification failed"
            )

    @staticmethod
    def _validate_contact(
        contact: SupplierContact,
    ) -> None:
        required_text(
            contact.contact_name,
            "contact_name",
        )

        email = required_text(
            contact.email,
            "email",
        )

        if (
            "@" not in email
            or " " in email
        ):
            raise ValueError(
                "Invalid email"
            )

        if contact.phone:
            required_text(
                contact.phone,
                "phone",
                max_length=40,
            )

    @staticmethod
    def _validate_product(
        product: SupplierProduct,
    ) -> None:
        required_text(
            product.sku,
            "sku",
        )

        nonnegative_decimal(
            product.unit_cost
        )

        positive_int(
            product.lead_time_days,
            "lead_time_days",
        )

        positive_int(
            product.minimum_order_quantity,
            "minimum_order_quantity",
        )

    def register_supplier(
        self,
        actor: SupplierActor,
        supplier_id: str,
        name: str,
        country: str,
        contact: SupplierContact,
        categories: Iterable[str],
        compliance_references: (
            Iterable[str] | None
        ) = None,
        compliance_expiry: (
            str | None
        ) = None,
    ) -> RetailSupplier:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
        )

        supplier_id = required_text(
            supplier_id,
            "supplier_id",
        )

        name = required_text(
            name,
            "name",
        )

        country = required_text(
            country,
            "country",
        )

        self._validate_contact(
            contact
        )

        categories = tuple(
            sorted({
                required_text(
                    category,
                    "category",
                )
                for category in categories
            })
        )

        references = tuple(
            sorted({
                required_text(
                    reference,
                    "compliance_reference",
                )
                for reference in (
                    compliance_references
                    or ()
                )
            })
        )

        if compliance_expiry:
            date.fromisoformat(
                compliance_expiry
            )

        with self._lock:
            if supplier_id in (
                self._suppliers
            ):
                raise ValueError(
                    "Supplier ID already exists"
                )

            timestamp = utc_now()

            supplier = RetailSupplier(
                supplier_id=supplier_id,
                tenant_id=self.tenant_id,
                name=name,
                country=country,
                contact=contact,
                categories=categories,
                status=SupplierStatus.PENDING,
                products={},
                compliance_references=(
                    references
                ),
                compliance_expiry=(
                    compliance_expiry
                ),
                performance=None,
                created_by=actor.user_id,
                created_at=timestamp,
                updated_at=timestamp,
            )

            self._suppliers[
                supplier_id
            ] = supplier

            self._audit_event(
                actor,
                supplier,
                "supplier_registered",
            )

            self._emit(
                supplier,
                "supplier.registered",
                {
                    "supplier_id": (
                        supplier_id
                    ),
                    "status": "pending",
                },
            )

            return copy.deepcopy(
                supplier
            )

    def activate_supplier(
        self,
        actor: SupplierActor,
        supplier_id: str,
        expected_version: int,
        approval_reference: str,
    ) -> RetailSupplier:
        self._authorize(
            actor,
            self.REVIEWER_ROLES,
        )

        with self._lock:
            supplier = self._get(
                supplier_id
            )

            self._check_version(
                supplier,
                expected_version,
            )

            if supplier.status not in {
                SupplierStatus.PENDING,
                SupplierStatus.INACTIVE,
                SupplierStatus.SUSPENDED,
            }:
                raise ValueError(
                    "Supplier cannot be activated"
                )

            if (
                not supplier.compliance_references
            ):
                raise ValueError(
                    "Compliance evidence required"
                )

            if (
                supplier.compliance_expiry
                and date.fromisoformat(
                    supplier.compliance_expiry
                ) < date.today()
            ):
                raise ValueError(
                    "Compliance evidence expired"
                )

            self._verify_approval(
                supplier_id,
                "activate_supplier",
                approval_reference,
            )

            supplier.status = (
                SupplierStatus.ACTIVE
            )

            supplier.approval_reference = (
                approval_reference
            )

            supplier.suspension_reason = (
                None
            )

            self._touch(
                supplier
            )

            self._audit_event(
                actor,
                supplier,
                "supplier_activated",
                {
                    "approval_reference": (
                        approval_reference
                    ),
                },
            )

            self._emit(
                supplier,
                "supplier.activated",
                {
                    "supplier_id": (
                        supplier_id
                    ),
                },
            )

            return copy.deepcopy(
                supplier
            )

    def suspend_supplier(
        self,
        actor: SupplierActor,
        supplier_id: str,
        expected_version: int,
        reason: str,
        approval_reference: str,
    ) -> RetailSupplier:
        self._authorize(
            actor,
            self.REVIEWER_ROLES,
        )

        reason = required_text(
            reason,
            "reason",
        )

        with self._lock:
            supplier = self._get(
                supplier_id
            )

            self._check_version(
                supplier,
                expected_version,
            )

            if supplier.status != (
                SupplierStatus.ACTIVE
            ):
                raise ValueError(
                    "Only active suppliers can be suspended"
                )

            self._verify_approval(
                supplier_id,
                "suspend_supplier",
                approval_reference,
            )

            supplier.status = (
                SupplierStatus.SUSPENDED
            )

            supplier.suspension_reason = (
                reason
            )

            self._touch(
                supplier
            )

            self._audit_event(
                actor,
                supplier,
                "supplier_suspended",
                {
                    "reason": reason,
                    "approval_reference": (
                        approval_reference
                    ),
                },
            )

            self._emit(
                supplier,
                "supplier.suspended",
                {
                    "supplier_id": (
                        supplier_id
                    ),
                    "reason": reason,
                },
            )

            return copy.deepcopy(
                supplier
            )

    def deactivate_supplier(
        self,
        actor: SupplierActor,
        supplier_id: str,
        expected_version: int,
    ) -> RetailSupplier:
        self._authorize(
            actor,
            self.REVIEWER_ROLES,
        )

        with self._lock:
            supplier = self._get(
                supplier_id
            )

            self._check_version(
                supplier,
                expected_version,
            )

            if supplier.status not in {
                SupplierStatus.ACTIVE,
                SupplierStatus.SUSPENDED,
            }:
                raise ValueError(
                    "Supplier cannot be deactivated"
                )

            supplier.status = (
                SupplierStatus.INACTIVE
            )

            self._touch(
                supplier
            )

            self._audit_event(
                actor,
                supplier,
                "supplier_deactivated",
            )

            self._emit(
                supplier,
                "supplier.deactivated",
                {
                    "supplier_id": (
                        supplier_id
                    ),
                },
            )

            return copy.deepcopy(
                supplier
            )

    def update_contact(
        self,
        actor: SupplierActor,
        supplier_id: str,
        expected_version: int,
        contact: SupplierContact,
    ) -> RetailSupplier:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
        )

        self._validate_contact(
            contact
        )

        with self._lock:
            supplier = self._get(
                supplier_id
            )

            self._check_version(
                supplier,
                expected_version,
            )

            supplier.contact = (
                contact
            )

            self._touch(
                supplier
            )

            self._audit_event(
                actor,
                supplier,
                "supplier_contact_updated",
            )

            return copy.deepcopy(
                supplier
            )

    def add_product(
        self,
        actor: SupplierActor,
        supplier_id: str,
        expected_version: int,
        product: SupplierProduct,
    ) -> RetailSupplier:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
        )

        self._validate_product(
            product
        )

        with self._lock:
            supplier = self._get(
                supplier_id
            )

            self._check_version(
                supplier,
                expected_version,
            )

            if product.sku in (
                supplier.products
            ):
                raise ValueError(
                    "Supplier SKU already assigned"
                )

            supplier.products[
                product.sku
            ] = product

            self._touch(
                supplier
            )

            self._audit_event(
                actor,
                supplier,
                "supplier_product_added",
                {
                    "sku": product.sku,
                },
            )

            self._emit(
                supplier,
                "supplier.product_added",
                {
                    "sku": product.sku,
                },
            )

            return copy.deepcopy(
                supplier
            )

    def record_performance(
        self,
        actor: SupplierActor,
        supplier_id: str,
        expected_version: int,
        total_deliveries: int,
        on_time_deliveries: int,
        inspected_units: int,
        defective_units: int,
    ) -> RetailSupplier:
        self._authorize(
            actor,
            self.REVIEWER_ROLES,
        )

        for name, value in (
            ("total_deliveries", total_deliveries),
            ("on_time_deliveries", on_time_deliveries),
            ("inspected_units", inspected_units),
            ("defective_units", defective_units),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ValueError(
                    f"Invalid {name}"
                )

        if (
            on_time_deliveries
            > total_deliveries
        ):
            raise ValueError(
                "On-time deliveries exceed total"
            )

        if (
            defective_units
            > inspected_units
        ):
            raise ValueError(
                "Defective units exceed inspected units"
            )

        with self._lock:
            supplier = self._get(
                supplier_id
            )

            self._check_version(
                supplier,
                expected_version,
            )

            supplier.performance = (
                SupplierPerformance(
                    total_deliveries=(
                        total_deliveries
                    ),
                    on_time_deliveries=(
                        on_time_deliveries
                    ),
                    inspected_units=(
                        inspected_units
                    ),
                    defective_units=(
                        defective_units
                    ),
                    recorded_at=utc_now(),
                )
            )

            self._touch(
                supplier
            )

            self._audit_event(
                actor,
                supplier,
                "supplier_performance_recorded",
            )

            return copy.deepcopy(
                supplier
            )

    def procurement_eligibility(
        self,
        actor: SupplierActor,
        supplier_id: str,
        sku: str,
        quantity: int,
    ) -> dict:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        positive_int(
            quantity,
            "quantity",
        )

        with self._lock:
            supplier = self._get(
                supplier_id
            )

            product = (
                supplier.products.get(
                    sku
                )
            )

            reasons = []

            if supplier.status != (
                SupplierStatus.ACTIVE
            ):
                reasons.append(
                    "Supplier is not active"
                )

            if product is None:
                reasons.append(
                    "SKU not assigned to supplier"
                )

            elif quantity < (
                product.minimum_order_quantity
            ):
                reasons.append(
                    "Below minimum order quantity"
                )

            if (
                supplier.compliance_expiry
                and date.fromisoformat(
                    supplier.compliance_expiry
                ) < date.today()
            ):
                reasons.append(
                    "Compliance evidence expired"
                )

            return {
                "supplier_id": supplier_id,
                "sku": sku,
                "quantity": quantity,
                "eligible": not reasons,
                "reasons": reasons,
                "currency": self.currency,
            }

    def get_supplier(
        self,
        actor: SupplierActor,
        supplier_id: str,
    ) -> RetailSupplier:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        with self._lock:
            return copy.deepcopy(
                self._get(
                    supplier_id
                )
            )

    def list_suppliers(
        self,
        actor: SupplierActor,
        status: SupplierStatus | None = None,
    ) -> list[RetailSupplier]:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        with self._lock:
            return [
                copy.deepcopy(
                    supplier
                )
                for supplier in (
                    self._suppliers.values()
                )
                if (
                    status is None
                    or supplier.status
                    == status
                )
            ]

    def supplier_metrics(
        self,
        actor: SupplierActor,
    ) -> dict:
        suppliers = (
            self.list_suppliers(
                actor
            )
        )

        counts = {
            status.value: sum(
                supplier.status == status
                for supplier in suppliers
            )
            for status in SupplierStatus
        }

        return {
            "tenant_id": self.tenant_id,
            "total_suppliers": len(
                suppliers
            ),
            "status_counts": counts,
            "total_supplier_sku_assignments": sum(
                len(supplier.products)
                for supplier in suppliers
            ),
        }

    def pending_events(
        self,
        actor: SupplierActor,
    ) -> list[SupplierOutboxEvent]:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
        )

        with self._lock:
            return [
                copy.deepcopy(
                    event
                )
                for event in (
                    self._outbox.values()
                )
                if not event.delivered
            ]

    def mark_event_delivered(
        self,
        actor: SupplierActor,
        event_id: str,
    ) -> None:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
        )

        with self._lock:
            event = (
                self._outbox.get(
                    event_id
                )
            )

            if event is None:
                raise KeyError(
                    "Event not found"
                )

            event.delivered = True

    def audit_events(
        self,
        actor: SupplierActor,
        supplier_id: str,
    ) -> list[SupplierAuditEvent]:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        with self._lock:
            self._get(
                supplier_id
            )

            return [
                copy.deepcopy(
                    event
                )
                for event in (
                    self._audit
                )
                if event.supplier_id == (
                    supplier_id
                )
            ]

    def export_json(
        self,
        actor: SupplierActor,
        output_path: str | Path,
    ) -> Path:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
        )

        suppliers = (
            self.list_suppliers(
                actor
            )
        )

        output = Path(
            output_path
        )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            json.dumps(
                [
                    asdict(supplier)
                    for supplier in suppliers
                ],
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        return output


if __name__ == "__main__":
    # Demo-only approval verifier.
    # Never use this in production.
    def demo_approval(
        supplier_id: str,
        action: str,
        reference: str,
    ) -> bool:
        return reference == (
            "DEMO-APPROVED"
        )

    service = RetailSupplierService(
        tenant_id="demo",
        approval_verifier=(
            demo_approval
        ),
    )

    manager = SupplierActor(
        user_id="procurement-manager",
        tenant_id="demo",
        roles=frozenset({
            "procurement_manager",
        }),
    )

    supplier = (
        service.register_supplier(
            actor=manager,
            supplier_id="SUP001",
            name="Example Supplier",
            country="India",
            contact=SupplierContact(
                contact_name="Supplier Contact",
                email="contact@example.com",
            ),
            categories=[
                "Electronics",
            ],
            compliance_references=[
                "DOC001",
            ],
            compliance_expiry=(
                "2027-12-31"
            ),
        )
    )

    supplier = (
        service.activate_supplier(
            actor=manager,
            supplier_id="SUP001",
            expected_version=(
                supplier.version
            ),
            approval_reference=(
                "DEMO-APPROVED"
            ),
        )
    )

    supplier = (
        service.add_product(
            actor=manager,
            supplier_id="SUP001",
            expected_version=(
                supplier.version
            ),
            product=SupplierProduct(
                sku="SKU001",
                unit_cost=Decimal(
                    "1250.00"
                ),
                lead_time_days=7,
                minimum_order_quantity=10,
            ),
        )
    )

    print(
        service.procurement_eligibility(
            actor=manager,
            supplier_id="SUP001",
            sku="SKU001",
            quantity=20,
        )
    )

    print(
        service.supplier_metrics(
            manager
        )
    )
