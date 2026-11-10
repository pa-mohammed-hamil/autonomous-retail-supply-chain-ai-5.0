from __future__ import annotations

"""Planned module: procurement service. Implementation pending."""

"""
backend/services/procurement_service.py

Autonomous Retail Supply Chain AI 5.0
Procurement Management Service

Python 3.10+ | Standard library only.

Features:
- Tenant and warehouse authorization
- Supplier registration
- Purchase request creation
- Purchase order approval gating
- Decimal-based cost calculations
- Partial goods receipts
- Idempotent receiving
- Purchase order cancellation
- Immutable audit records
- Inventory receipt outbox events
- Procurement metrics
- JSON export

IMPORTANT:
This is an in-memory reference prototype.

An approval reference is accepted only
through an injected verification callback.
A trusted callback must consult the
real approval system and verify the
request's scope and final approval.

No supplier order is sent automatically.
No inventory balance is modified directly.
"""


import copy
import json
import threading
import uuid

from dataclasses import (
    asdict,
    dataclass,
    field,
    replace,
)
from datetime import (
    datetime,
    timezone,
)
from decimal import (
    Decimal,
    InvalidOperation,
)
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Callable,
)


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def required(
    value: str,
    name: str,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 200
    ):
        raise ValueError(
            f"Invalid {name}"
        )

    return value.strip()


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
            f"{name} must be a positive integer"
        )

    return value


def money(
    value: Any,
) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(
            "Invalid monetary amount"
        )

    try:
        result = Decimal(
            str(value)
        )
    except (
        InvalidOperation,
        ValueError,
    ) as exc:
        raise ValueError(
            "Invalid monetary amount"
        ) from exc

    if (
        not result.is_finite()
        or result < 0
    ):
        raise ValueError(
            "Amount must be finite and nonnegative"
        )

    if result != result.quantize(
        Decimal("0.01")
    ):
        raise ValueError(
            "Maximum two decimal places allowed"
        )

    return result


class ProcurementStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    ORDERED = "ordered"
    PARTIALLY_RECEIVED = (
        "partially_received"
    )
    RECEIVED = "received"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ProcurementActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str] = (
        frozenset()
    )
    is_active: bool = True


@dataclass(frozen=True)
class ProcurementSupplier:
    supplier_id: str
    tenant_id: str
    name: str
    active: bool = True


@dataclass(frozen=True)
class ProcurementItem:
    sku: str
    quantity: int
    unit_cost: Decimal

    @property
    def line_total(self) -> Decimal:
        return (
            self.unit_cost
            * self.quantity
        )


@dataclass
class PurchaseOrder:
    order_id: str
    tenant_id: str
    supplier_id: str
    warehouse_id: str
    items: list[ProcurementItem]
    currency: str
    total_amount: Decimal
    status: ProcurementStatus
    created_by: str
    created_at: str
    updated_at: str
    approval_reference: str | None = None
    ordered_at: str | None = None
    received_quantities: dict[
        str, int
    ] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class ProcurementReceipt:
    receipt_id: str
    tenant_id: str
    order_id: str
    warehouse_id: str
    sku: str
    quantity: int
    receipt_reference: str
    received_by: str
    received_at: str


@dataclass(frozen=True)
class ProcurementAuditEvent:
    event_id: str
    tenant_id: str
    order_id: str
    actor_id: str
    action: str
    timestamp: str
    details: dict[str, Any]


@dataclass
class ProcurementOutboxEvent:
    event_id: str
    tenant_id: str
    event_type: str
    source_id: str
    payload: dict[str, Any]
    created_at: str
    delivered: bool = False


# Callback must validate an approved
# request against this exact purchase:
#
# (approval_reference, tenant_id,
#  order_id, supplier_id,
#  warehouse_id, total_amount)
#
# Return True only if the external
# approval is valid and finalized.

ApprovalVerifier = Callable[
    [
        str,
        str,
        str,
        str,
        str,
        Decimal,
    ],
    bool,
]


class RetailProcurementService:
    BUYER_ROLES = frozenset({
        "procurement_officer",
        "procurement_manager",
        "corporate_admin",
    })

    MANAGER_ROLES = frozenset({
        "procurement_manager",
        "corporate_admin",
    })

    RECEIVER_ROLES = frozenset({
        "warehouse_staff",
        "warehouse_manager",
        "corporate_admin",
    })

    READER_ROLES = (
        BUYER_ROLES
        | RECEIVER_ROLES
        | frozenset({
            "procurement_analyst",
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
        self.tenant_id = required(
            tenant_id,
            "tenant_id",
        )

        if (
            not isinstance(currency, str)
            or len(currency) != 3
            or not currency.isalpha()
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

        self._lock = threading.RLock()

        self._suppliers: dict[
            str, ProcurementSupplier
        ] = {}

        self._orders: dict[
            str, PurchaseOrder
        ] = {}

        self._receipts: dict[
            tuple[str, str],
            ProcurementReceipt,
        ] = {}

        self._audit: list[
            ProcurementAuditEvent
        ] = []

        self._outbox: dict[
            str, ProcurementOutboxEvent
        ] = {}

    def _authorize(
        self,
        actor: ProcurementActor,
        roles: frozenset[str],
        warehouse_id: str | None = None,
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id
            != self.tenant_id
            or not actor.user_id.strip()
            or not (actor.roles & roles)
        ):
            raise PermissionError(
                "Procurement access denied"
            )

        if (
            warehouse_id is not None
            and "corporate_admin"
            not in actor.roles
            and warehouse_id
            not in actor.warehouse_ids
        ):
            raise PermissionError(
                "Warehouse access denied"
            )

    def _audit_event(
        self,
        actor: ProcurementActor,
        order: PurchaseOrder,
        action: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._audit.append(
            ProcurementAuditEvent(
                event_id=str(uuid.uuid4()),
                tenant_id=self.tenant_id,
                order_id=order.order_id,
                actor_id=actor.user_id,
                action=action,
                timestamp=utc_now(),
                details=copy.deepcopy(
                    details or {}
                ),
            )
        )

    def _outbox_event(
        self,
        event_type: str,
        source_id: str,
        payload: dict[str, Any],
    ) -> None:
        event = ProcurementOutboxEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            event_type=event_type,
            source_id=source_id,
            payload=copy.deepcopy(
                payload
            ),
            created_at=utc_now(),
        )

        self._outbox[
            event.event_id
        ] = event

    def _order(
        self,
        actor: ProcurementActor,
        order_id: str,
        roles: frozenset[str],
    ) -> PurchaseOrder:
        order = self._orders.get(
            order_id
        )

        if order is None:
            raise KeyError(
                "Purchase order not found"
            )

        self._authorize(
            actor,
            roles,
            order.warehouse_id,
        )

        return order

    def register_supplier(
        self,
        actor: ProcurementActor,
        supplier_id: str,
        name: str,
    ) -> ProcurementSupplier:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
        )

        supplier_id = required(
            supplier_id,
            "supplier_id",
        )

        name = required(
            name,
            "supplier name",
        )

        with self._lock:
            if supplier_id in (
                self._suppliers
            ):
                raise ValueError(
                    "Supplier already exists"
                )

            supplier = ProcurementSupplier(
                supplier_id=supplier_id,
                tenant_id=self.tenant_id,
                name=name,
            )

            self._suppliers[
                supplier_id
            ] = supplier

            return supplier

    def create_order(
        self,
        actor: ProcurementActor,
        order_id: str,
        supplier_id: str,
        warehouse_id: str,
        items: list[ProcurementItem],
    ) -> PurchaseOrder:
        self._authorize(
            actor,
            self.BUYER_ROLES,
            warehouse_id,
        )

        order_id = required(
            order_id,
            "order_id",
        )

        warehouse_id = required(
            warehouse_id,
            "warehouse_id",
        )

        if not items:
            raise ValueError(
                "Purchase order requires items"
            )

        normalized = []
        seen_skus = set()

        for item in items:
            sku = required(
                item.sku,
                "sku",
            )

            quantity = positive_int(
                item.quantity,
                "quantity",
            )

            unit_cost = money(
                item.unit_cost
            )

            if sku in seen_skus:
                raise ValueError(
                    "Duplicate SKU in order"
                )

            seen_skus.add(sku)

            normalized.append(
                ProcurementItem(
                    sku=sku,
                    quantity=quantity,
                    unit_cost=unit_cost,
                )
            )

        total = sum(
            (
                item.line_total
                for item in normalized
            ),
            Decimal("0.00"),
        )

        with self._lock:
            supplier = (
                self._suppliers.get(
                    supplier_id
                )
            )

            if (
                supplier is None
                or not supplier.active
            ):
                raise ValueError(
                    "Supplier unavailable"
                )

            existing = self._orders.get(
                order_id
            )

            if existing:
                if (
                    existing.supplier_id
                    != supplier_id
                    or existing.warehouse_id
                    != warehouse_id
                    or existing.items
                    != normalized
                ):
                    raise ValueError(
                        "Purchase order ID conflict"
                    )

                return copy.deepcopy(
                    existing
                )

            now = utc_now()

            order = PurchaseOrder(
                order_id=order_id,
                tenant_id=self.tenant_id,
                supplier_id=supplier_id,
                warehouse_id=warehouse_id,
                items=normalized,
                currency=self.currency,
                total_amount=total,
                status=ProcurementStatus.DRAFT,
                created_by=actor.user_id,
                created_at=now,
                updated_at=now,
                received_quantities={
                    item.sku: 0
                    for item in normalized
                },
            )

            self._orders[
                order_id
            ] = order

            self._audit_event(
                actor,
                order,
                "purchase_order_created",
                {
                    "total_amount": str(
                        total
                    ),
                },
            )

            return copy.deepcopy(
                order
            )

    def approve_order(
        self,
        actor: ProcurementActor,
        order_id: str,
        approval_reference: str,
    ) -> PurchaseOrder:
        approval_reference = required(
            approval_reference,
            "approval_reference",
        )

        with self._lock:
            order = self._order(
                actor,
                order_id,
                self.MANAGER_ROLES,
            )

            if order.status == (
                ProcurementStatus.APPROVED
            ):
                if order.approval_reference != (
                    approval_reference
                ):
                    raise ValueError(
                        "Approval reference conflict"
                    )

                return copy.deepcopy(
                    order
                )

            if order.status != (
                ProcurementStatus.DRAFT
            ):
                raise ValueError(
                    "Order is not awaiting approval"
                )

            if self.approval_verifier is None:
                raise RuntimeError(
                    "Approval verifier not configured"
                )

            approved = (
                self.approval_verifier(
                    approval_reference,
                    self.tenant_id,
                    order.order_id,
                    order.supplier_id,
                    order.warehouse_id,
                    order.total_amount,
                )
            )

            if approved is not True:
                raise PermissionError(
                    "Purchase approval not verified"
                )

            order.status = (
                ProcurementStatus.APPROVED
            )

            order.approval_reference = (
                approval_reference
            )

            order.updated_at = utc_now()

            self._audit_event(
                actor,
                order,
                "purchase_order_approved",
                {
                    "approval_reference": (
                        approval_reference
                    ),
                },
            )

            return copy.deepcopy(
                order
            )

    def mark_ordered(
        self,
        actor: ProcurementActor,
        order_id: str,
    ) -> PurchaseOrder:
        with self._lock:
            order = self._order(
                actor,
                order_id,
                self.MANAGER_ROLES,
            )

            if order.status == (
                ProcurementStatus.ORDERED
            ):
                return copy.deepcopy(
                    order
                )

            if order.status != (
                ProcurementStatus.APPROVED
            ):
                raise ValueError(
                    "Order must be approved"
                )

            # Records internal order status.
            # Does not send to supplier.
            order.status = (
                ProcurementStatus.ORDERED
            )

            order.ordered_at = utc_now()
            order.updated_at = (
                order.ordered_at
            )

            self._outbox_event(
                "procurement.order_ready",
                order.order_id,
                {
                    "order_id": order.order_id,
                    "supplier_id": (
                        order.supplier_id
                    ),
                    "warehouse_id": (
                        order.warehouse_id
                    ),
                    "approval_reference": (
                        order.approval_reference
                    ),
                },
            )

            self._audit_event(
                actor,
                order,
                "purchase_order_marked_ordered",
            )

            return copy.deepcopy(
                order
            )

    def receive_goods(
        self,
        actor: ProcurementActor,
        order_id: str,
        sku: str,
        quantity: int,
        receipt_reference: str,
    ) -> ProcurementReceipt:
        positive_int(
            quantity,
            "quantity",
        )

        sku = required(
            sku,
            "sku",
        )

        receipt_reference = required(
            receipt_reference,
            "receipt_reference",
        )

        with self._lock:
            order = self._order(
                actor,
                order_id,
                self.RECEIVER_ROLES,
            )

            key = (
                order_id,
                receipt_reference,
            )

            existing = (
                self._receipts.get(
                    key
                )
            )

            if existing:
                if (
                    existing.sku != sku
                    or existing.quantity
                    != quantity
                ):
                    raise ValueError(
                        "Receipt reference conflict"
                    )

                return existing

            if order.status not in {
                ProcurementStatus.ORDERED,
                ProcurementStatus.PARTIALLY_RECEIVED,
            }:
                raise ValueError(
                    "Order cannot receive goods"
                )

            item = next(
                (
                    item
                    for item in order.items
                    if item.sku == sku
                ),
                None,
            )

            if item is None:
                raise ValueError(
                    "SKU not present in purchase order"
                )

            already_received = (
                order.received_quantities[
                    sku
                ]
            )

            if (
                already_received
                + quantity
                > item.quantity
            ):
                raise ValueError(
                    "Receipt exceeds ordered quantity"
                )

            receipt = ProcurementReceipt(
                receipt_id=str(
                    uuid.uuid4()
                ),
                tenant_id=self.tenant_id,
                order_id=order_id,
                warehouse_id=(
                    order.warehouse_id
                ),
                sku=sku,
                quantity=quantity,
                receipt_reference=(
                    receipt_reference
                ),
                received_by=actor.user_id,
                received_at=utc_now(),
            )

            order.received_quantities[
                sku
            ] += quantity

            complete = all(
                order.received_quantities[
                    item.sku
                ] == item.quantity
                for item in order.items
            )

            order.status = (
                ProcurementStatus.RECEIVED
                if complete
                else ProcurementStatus.PARTIALLY_RECEIVED
            )

            order.updated_at = utc_now()

            self._receipts[
                key
            ] = receipt

            self._outbox_event(
                "procurement.goods_received",
                receipt.receipt_id,
                {
                    "order_id": order_id,
                    "warehouse_id": (
                        order.warehouse_id
                    ),
                    "sku": sku,
                    "quantity": quantity,
                    "receipt_reference": (
                        receipt_reference
                    ),
                },
            )

            self._audit_event(
                actor,
                order,
                "goods_received",
                {
                    "sku": sku,
                    "quantity": quantity,
                    "receipt_id": (
                        receipt.receipt_id
                    ),
                },
            )

            return receipt

    def cancel_order(
        self,
        actor: ProcurementActor,
        order_id: str,
    ) -> PurchaseOrder:
        with self._lock:
            order = self._order(
                actor,
                order_id,
                self.MANAGER_ROLES,
            )

            if order.status == (
                ProcurementStatus.CANCELLED
            ):
                return copy.deepcopy(
                    order
                )

            if order.status not in {
                ProcurementStatus.DRAFT,
                ProcurementStatus.APPROVED,
            }:
                raise ValueError(
                    "Order cannot be cancelled "
                    "without supplier coordination"
                )

            order.status = (
                ProcurementStatus.CANCELLED
            )

            order.updated_at = utc_now()

            self._audit_event(
                actor,
                order,
                "purchase_order_cancelled",
            )

            return copy.deepcopy(
                order
            )

    def get_order(
        self,
        actor: ProcurementActor,
        order_id: str,
    ) -> PurchaseOrder:
        with self._lock:
            return copy.deepcopy(
                self._order(
                    actor,
                    order_id,
                    self.READER_ROLES,
                )
            )

    def list_orders(
        self,
        actor: ProcurementActor,
        status: ProcurementStatus | None = None,
    ) -> list[PurchaseOrder]:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        with self._lock:
            return [
                copy.deepcopy(
                    order
                )
                for order in (
                    self._orders.values()
                )
                if (
                    (
                        "corporate_admin"
                        in actor.roles
                        or order.warehouse_id
                        in actor.warehouse_ids
                    )
                    and (
                        status is None
                        or order.status == status
                    )
                )
            ]

    def pending_events(
        self,
        actor: ProcurementActor,
    ) -> list[ProcurementOutboxEvent]:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
        )

        with self._lock:
            return [
                copy.deepcopy(event)
                for event in (
                    self._outbox.values()
                )
                if not event.delivered
                and (
                    "corporate_admin"
                    in actor.roles
                    or (
                        event.payload.get(
                            "warehouse_id"
                        )
                        in actor.warehouse_ids
                    )
                )
            ]

    def mark_event_delivered(
        self,
        actor: ProcurementActor,
        event_id: str,
    ) -> None:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
        )

        with self._lock:
            event = self._outbox.get(
                event_id
            )

            if event is None:
                raise KeyError(
                    "Outbox event not found"
                )

            warehouse_id = (
                event.payload.get(
                    "warehouse_id"
                )
            )

            self._authorize(
                actor,
                self.MANAGER_ROLES,
                warehouse_id,
            )

            event.delivered = True

    def metrics(
        self,
        actor: ProcurementActor,
    ) -> dict[str, Any]:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
        )

        with self._lock:
            orders = [
                order
                for order in (
                    self._orders.values()
                )
                if (
                    "corporate_admin"
                    in actor.roles
                    or order.warehouse_id
                    in actor.warehouse_ids
                )
            ]

            total_value = sum(
                (
                    order.total_amount
                    for order in orders
                    if order.status
                    != ProcurementStatus.CANCELLED
                ),
                Decimal("0.00"),
            )

            return {
                "tenant_id": self.tenant_id,
                "total_orders": len(
                    orders
                ),
                "total_order_value": (
                    str(total_value)
                ),
                "currency": self.currency,
                "status_counts": {
                    status.value: sum(
                        order.status == status
                        for order in orders
                    )
                    for status in ProcurementStatus
                },
            }

    def audit_events(
        self,
        actor: ProcurementActor,
        order_id: str,
    ) -> list[ProcurementAuditEvent]:
        with self._lock:
            self._order(
                actor,
                order_id,
                self.READER_ROLES,
            )

            return [
                copy.deepcopy(event)
                for event in self._audit
                if event.order_id == (
                    order_id
                )
            ]

    def export_json(
        self,
        actor: ProcurementActor,
        output_path: str | Path,
    ) -> Path:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
        )

        with self._lock:
            orders = [
                asdict(order)
                for order in (
                    self._orders.values()
                )
                if (
                    "corporate_admin"
                    in actor.roles
                    or order.warehouse_id
                    in actor.warehouse_ids
                )
            ]

        output = Path(
            output_path
        )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            json.dumps(
                orders,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        return output


if __name__ == "__main__":
    # Demo verifier only.
    # Production must consult the
    # real approval service and match
    # all purchase-order details.
    def demo_verify_approval(
        approval_reference,
        tenant_id,
        order_id,
        supplier_id,
        warehouse_id,
        total_amount,
    ) -> bool:
        return (
            approval_reference == "APPROVED-001"
            and tenant_id == "demo"
            and order_id == "PO001"
            and supplier_id == "SUP001"
            and warehouse_id == "WH001"
            and total_amount
            == Decimal("5000.00")
        )

    service = RetailProcurementService(
        tenant_id="demo",
        approval_verifier=(
            demo_verify_approval
        ),
    )

    manager = ProcurementActor(
        user_id="procurement-manager",
        tenant_id="demo",
        roles=frozenset({
            "procurement_manager",
            "warehouse_manager",
        }),
        warehouse_ids=frozenset({
            "WH001",
        }),
    )

    receiver = ProcurementActor(
        user_id="warehouse-worker",
        tenant_id="demo",
        roles=frozenset({
            "warehouse_staff",
        }),
        warehouse_ids=frozenset({
            "WH001",
        }),
    )

    service.register_supplier(
        manager,
        supplier_id="SUP001",
        name="Demo Supplier",
    )

    order = service.create_order(
        actor=manager,
        order_id="PO001",
        supplier_id="SUP001",
        warehouse_id="WH001",
        items=[
            ProcurementItem(
                sku="SKU001",
                quantity=100,
                unit_cost=Decimal("50.00"),
            )
        ],
    )

    service.approve_order(
        manager,
        order.order_id,
        approval_reference="APPROVED-001",
    )

    service.mark_ordered(
        manager,
        order.order_id,
    )

    service.receive_goods(
        receiver,
        order.order_id,
        sku="SKU001",
        quantity=40,
        receipt_reference="GRN001",
    )

    service.receive_goods(
        receiver,
        order.order_id,
        sku="SKU001",
        quantity=60,
        receipt_reference="GRN002",
    )

    print(
        service.get_order(
            manager,
            "PO001",
        ).status.value
    )

    print(
        service.metrics(
            manager
        )
    )
