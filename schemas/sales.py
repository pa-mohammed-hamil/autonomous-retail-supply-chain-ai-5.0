from __future__ import annotations

"""Planned module: sales. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
backend/services/sales_service.py

Python 3.10+ | Standard library only

Features:
- Tenant / warehouse RBAC
- Multi-item customer orders
- Decimal-based pricing and discounts
- Draft -> confirmed -> paid lifecycle
- Externally verified payment recording
- Fulfillment request handoff
- Order cancellation
- Approval-controlled refunds
- Payment and refund idempotency
- Audit history
- Transactional outbox (in-memory prototype)
- Sales metrics and JSON export

This is reference code, not a real payment processor.
"""


import copy
import json
import threading
import uuid

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterable


CENT = Decimal("0.01")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid {field_name}")
    if len(value) > 255:
        raise ValueError(f"{field_name} is too long")
    return value.strip()


def money(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("Invalid money value")

    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            raise ValueError("Money must be nonnegative")
        return amount.quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid money value") from exc


def positive_quantity(value: int) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("Quantity must be a positive integer")
    return value


class SalesOrderStatus(str, Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    PAID = "paid"
    FULFILLMENT_REQUESTED = "fulfillment_requested"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class SalesActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str] = frozenset()
    is_active: bool = True


@dataclass(frozen=True)
class SalesItemInput:
    sku: str
    quantity: int
    unit_price: Decimal
    unit_cost: Decimal = Decimal("0.00")


@dataclass(frozen=True)
class SalesOrderItem:
    sku: str
    quantity: int
    unit_price: Decimal
    unit_cost: Decimal
    line_total: Decimal


@dataclass
class SalesOrder:
    order_id: str
    tenant_id: str
    customer_id: str
    warehouse_id: str
    items: tuple[SalesOrderItem, ...]
    subtotal: Decimal
    discount: Decimal
    total: Decimal
    status: SalesOrderStatus
    payment_reference: str | None
    fulfillment_reference: str | None
    refunded_amount: Decimal
    created_by: str
    created_at: str
    updated_at: str
    version: int = 1


@dataclass(frozen=True)
class SalesAuditEvent:
    event_id: str
    tenant_id: str
    order_id: str
    actor_id: str
    action: str
    timestamp: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SalesOutboxEvent:
    event_id: str
    tenant_id: str
    order_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: str
    delivered: bool = False


# Callbacks must use trusted external integrations.
PaymentVerifier = Callable[
    [str, str, Decimal, str], bool
]

ApprovalVerifier = Callable[
    [str, str, str, Decimal], bool
]


class RetailSalesService:
    WRITER_ROLES = frozenset({
        "sales_manager",
        "operations_manager",
        "corporate_admin",
    })

    READER_ROLES = WRITER_ROLES | frozenset({
        "sales_analyst",
        "finance_analyst",
        "warehouse_manager",
        "customer_service",
    })

    REFUND_ROLES = frozenset({
        "finance_manager",
        "corporate_admin",
    })

    def __init__(
        self,
        tenant_id: str,
        currency: str = "INR",
        payment_verifier: PaymentVerifier | None = None,
        approval_verifier: ApprovalVerifier | None = None,
    ):
        self.tenant_id = required(tenant_id, "tenant_id")
        self.currency = required(currency, "currency").upper()

        self.payment_verifier = payment_verifier
        self.approval_verifier = approval_verifier

        self._lock = threading.RLock()
        self._orders: dict[str, SalesOrder] = {}
        self._payment_index: dict[str, str] = {}
        self._refund_index: dict[
            str, tuple[str, Decimal]
        ] = {}
        self._audit: list[SalesAuditEvent] = []
        self._outbox: dict[str, SalesOutboxEvent] = {}

    def _authorize(
        self,
        actor: SalesActor,
        roles: frozenset[str],
        warehouse_id: str,
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.user_id.strip()
            or not actor.roles.intersection(roles)
        ):
            raise PermissionError("Sales access denied")

        if (
            "corporate_admin" not in actor.roles
            and warehouse_id not in actor.warehouse_ids
        ):
            raise PermissionError("Warehouse access denied")

    def _get(self, order_id: str) -> SalesOrder:
        order = self._orders.get(order_id)
        if order is None:
            raise KeyError("Sales order not found")
        return order

    def _record(
        self,
        actor_id: str,
        order: SalesOrder,
        action: str,
        details: dict | None = None,
    ) -> None:
        self._audit.append(SalesAuditEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            order_id=order.order_id,
            actor_id=actor_id,
            action=action,
            timestamp=utc_now(),
            details=copy.deepcopy(details or {}),
        ))

        event = SalesOutboxEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            order_id=order.order_id,
            event_type=f"sales.{action}",
            payload={
                "order_id": order.order_id,
                "warehouse_id": order.warehouse_id,
                "status": order.status.value,
                "total": str(order.total),
                "currency": self.currency,
            },
            created_at=utc_now(),
        )
        self._outbox[event.event_id] = event

    @staticmethod
    def _touch(order: SalesOrder) -> None:
        order.version += 1
        order.updated_at = utc_now()

    def create_order(
        self,
        actor: SalesActor,
        order_id: str,
        customer_id: str,
        warehouse_id: str,
        items: Iterable[SalesItemInput],
        discount: Any = "0.00",
    ) -> SalesOrder:
        self._authorize(actor, self.WRITER_ROLES, warehouse_id)

        order_id = required(order_id, "order_id")
        customer_id = required(customer_id, "customer_id")
        warehouse_id = required(warehouse_id, "warehouse_id")
        discount_amount = money(discount)

        prepared = []
        seen_skus = set()

        for item in items:
            sku = required(item.sku, "sku")
            qty = positive_quantity(item.quantity)

            if sku in seen_skus:
                raise ValueError("Duplicate SKU in order")
            seen_skus.add(sku)

            price = money(item.unit_price)
            cost = money(item.unit_cost)

            prepared.append(SalesOrderItem(
                sku=sku,
                quantity=qty,
                unit_price=price,
                unit_cost=cost,
                line_total=price * qty,
            ))

        if not prepared:
            raise ValueError("Order requires at least one item")

        subtotal = sum(
            (item.line_total for item in prepared),
            Decimal("0.00"),
        )

        if discount_amount > subtotal:
            raise ValueError("Discount exceeds subtotal")

        total = subtotal - discount_amount

        with self._lock:
            if order_id in self._orders:
                raise ValueError("Order ID already exists")

            current = utc_now()
            order = SalesOrder(
                order_id=order_id,
                tenant_id=self.tenant_id,
                customer_id=customer_id,
                warehouse_id=warehouse_id,
                items=tuple(prepared),
                subtotal=subtotal,
                discount=discount_amount,
                total=total,
                status=SalesOrderStatus.DRAFT,
                payment_reference=None,
                fulfillment_reference=None,
                refunded_amount=Decimal("0.00"),
                created_by=actor.user_id,
                created_at=current,
                updated_at=current,
            )

            self._orders[order_id] = order
            self._record(actor.user_id, order, "created")
            return copy.deepcopy(order)

    def confirm_order(
        self,
        actor: SalesActor,
        order_id: str,
        expected_version: int,
    ) -> SalesOrder:
        with self._lock:
            order = self._get(order_id)
            self._authorize(
                actor, self.WRITER_ROLES, order.warehouse_id
            )

            if order.version != expected_version:
                raise ValueError("Version conflict")

            if order.status != SalesOrderStatus.DRAFT:
                raise ValueError("Order cannot be confirmed")

            order.status = SalesOrderStatus.CONFIRMED
            self._touch(order)
            self._record(actor.user_id, order, "confirmed")
            return copy.deepcopy(order)

    def record_verified_payment(
        self,
        actor: SalesActor,
        order_id: str,
        expected_version: int,
        payment_reference: str,
    ) -> SalesOrder:
        payment_reference = required(
            payment_reference, "payment_reference"
        )

        with self._lock:
            order = self._get(order_id)
            self._authorize(
                actor, self.WRITER_ROLES, order.warehouse_id
            )

            previous = self._payment_index.get(payment_reference)
            if previous is not None:
                if previous != order_id:
                    raise ValueError("Payment reference already used")
                return copy.deepcopy(order)

            if order.version != expected_version:
                raise ValueError("Version conflict")

            if order.status != SalesOrderStatus.CONFIRMED:
                raise ValueError("Order is not awaiting payment")

            if self.payment_verifier is None:
                raise PermissionError(
                    "Payment verification is not configured"
                )

            if not self.payment_verifier(
                order_id,
                payment_reference,
                order.total,
                self.currency,
            ):
                raise PermissionError("Payment not verified")

            order.status = SalesOrderStatus.PAID
            order.payment_reference = payment_reference
            self._payment_index[payment_reference] = order_id
            self._touch(order)
            self._record(
                actor.user_id,
                order,
                "payment_verified",
                {"payment_reference": payment_reference},
            )
            return copy.deepcopy(order)

    def request_fulfillment(
        self,
        actor: SalesActor,
        order_id: str,
        expected_version: int,
        fulfillment_reference: str,
    ) -> SalesOrder:
        fulfillment_reference = required(
            fulfillment_reference, "fulfillment_reference"
        )

        with self._lock:
            order = self._get(order_id)
            self._authorize(
                actor, self.WRITER_ROLES, order.warehouse_id
            )

            if order.version != expected_version:
                raise ValueError("Version conflict")

            if order.status != SalesOrderStatus.PAID:
                raise ValueError("Order must be paid first")

            order.status = SalesOrderStatus.FULFILLMENT_REQUESTED
            order.fulfillment_reference = fulfillment_reference
            self._touch(order)
            self._record(
                actor.user_id,
                order,
                "fulfillment_requested",
                {"fulfillment_reference": fulfillment_reference},
            )
            return copy.deepcopy(order)

    def cancel_order(
        self,
        actor: SalesActor,
        order_id: str,
        expected_version: int,
        reason: str,
    ) -> SalesOrder:
        reason = required(reason, "reason")

        with self._lock:
            order = self._get(order_id)
            self._authorize(
                actor, self.WRITER_ROLES, order.warehouse_id
            )

            if order.version != expected_version:
                raise ValueError("Version conflict")

            if order.status not in {
                SalesOrderStatus.DRAFT,
                SalesOrderStatus.CONFIRMED,
            }:
                raise ValueError(
                    "Paid orders require a separate refund workflow"
                )

            order.status = SalesOrderStatus.CANCELLED
            self._touch(order)
            self._record(
                actor.user_id, order, "cancelled",
                {"reason": reason},
            )
            return copy.deepcopy(order)

    def record_refund(
        self,
        actor: SalesActor,
        order_id: str,
        expected_version: int,
        amount: Any,
        refund_reference: str,
        approval_reference: str,
    ) -> SalesOrder:
        refund_amount = money(amount)

        if refund_amount <= 0:
            raise ValueError("Refund must be positive")

        refund_reference = required(
            refund_reference, "refund_reference"
        )
        approval_reference = required(
            approval_reference, "approval_reference"
        )

        with self._lock:
            order = self._get(order_id)
            self._authorize(
                actor, self.REFUND_ROLES, order.warehouse_id
            )

            previous = self._refund_index.get(refund_reference)
            if previous is not None:
                if previous != (order_id, refund_amount):
                    raise ValueError("Conflicting refund reference")
                return copy.deepcopy(order)

            if order.version != expected_version:
                raise ValueError("Version conflict")

            if order.status not in {
                SalesOrderStatus.PAID,
                SalesOrderStatus.FULFILLMENT_REQUESTED,
            }:
                raise ValueError("Order is not refundable")

            remaining = order.total - order.refunded_amount

            if refund_amount > remaining:
                raise ValueError("Refund exceeds remaining payment")

            if self.approval_verifier is None:
                raise PermissionError(
                    "Refund approval verifier not configured"
                )

            if not self.approval_verifier(
                order_id,
                approval_reference,
                refund_reference,
                refund_amount,
            ):
                raise PermissionError("Refund approval denied")

            order.refunded_amount += refund_amount
            self._refund_index[refund_reference] = (
                order_id, refund_amount
            )
            self._touch(order)

            self._record(
                actor.user_id,
                order,
                "refund_recorded",
                {
                    "refund_reference": refund_reference,
                    "amount": str(refund_amount),
                },
            )
            return copy.deepcopy(order)

    def get_order(
        self,
        actor: SalesActor,
        order_id: str,
    ) -> SalesOrder:
        with self._lock:
            order = self._get(order_id)
            self._authorize(
                actor, self.READER_ROLES, order.warehouse_id
            )
            return copy.deepcopy(order)

    def list_orders(
        self,
        actor: SalesActor,
        status: SalesOrderStatus | None = None,
    ) -> list[SalesOrder]:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.roles.intersection(self.READER_ROLES)
        ):
            raise PermissionError("Sales access denied")

        with self._lock:
            return [
                copy.deepcopy(order)
                for order in self._orders.values()
                if (
                    (
                        "corporate_admin" in actor.roles
                        or order.warehouse_id in actor.warehouse_ids
                    )
                    and (
                        status is None
                        or order.status == status
                    )
                )
            ]

    def sales_metrics(
        self,
        actor: SalesActor,
    ) -> dict[str, Any]:
        orders = self.list_orders(actor)

        paid_orders = [
            o for o in orders
            if o.payment_reference is not None
        ]

        gross = sum(
            (o.subtotal for o in paid_orders),
            Decimal("0.00"),
        )
        discounts = sum(
            (o.discount for o in paid_orders),
            Decimal("0.00"),
        )
        refunds = sum(
            (o.refunded_amount for o in paid_orders),
            Decimal("0.00"),
        )
        cogs = sum(
            (
                item.unit_cost * item.quantity
                for order in paid_orders
                for item in order.items
            ),
            Decimal("0.00"),
        )

        net = gross - discounts - refunds

        return {
            "tenant_id": self.tenant_id,
            "currency": self.currency,
            "total_orders": len(orders),
            "paid_orders": len(paid_orders),
            "gross_sales": str(gross),
            "discounts": str(discounts),
            "refunds": str(refunds),
            "net_sales": str(net),
            "estimated_cogs": str(cogs),
            "estimated_gross_profit": str(net - cogs),
        }

    def pending_events(
        self,
        actor: SalesActor,
    ) -> list[SalesOutboxEvent]:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.roles.intersection(self.WRITER_ROLES)
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
                        or self._orders[
                            event.order_id
                        ].warehouse_id in actor.warehouse_ids
                    )
                )
            ]

    def mark_event_delivered(
        self,
        actor: SalesActor,
        event_id: str,
    ) -> None:
        with self._lock:
            event = self._outbox.get(event_id)
            if event is None:
                raise KeyError("Event not found")

            order = self._get(event.order_id)
            self._authorize(
                actor, self.WRITER_ROLES, order.warehouse_id
            )
            event.delivered = True

    def audit_events(
        self,
        actor: SalesActor,
        order_id: str,
    ) -> list[SalesAuditEvent]:
        self.get_order(actor, order_id)

        with self._lock:
            return [
                copy.deepcopy(event)
                for event in self._audit
                if event.order_id == order_id
            ]

    def export_json(
        self,
        actor: SalesActor,
        output_path: str | Path,
    ) -> Path:
        orders = self.list_orders(actor)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(
            json.dumps(
                [asdict(order) for order in orders],
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    def demo_payment(
        order_id: str,
        payment_reference: str,
        amount: Decimal,
        currency: str,
    ) -> bool:
        # Demo only; never use this in production.
        return payment_reference == "PAYMENT-DEMO"

    def demo_refund_approval(
        order_id: str,
        approval_reference: str,
        refund_reference: str,
        amount: Decimal,
    ) -> bool:
        # Demo only; never use this in production.
        return approval_reference == "APPROVED-DEMO"

    service = RetailSalesService(
        tenant_id="demo",
        payment_verifier=demo_payment,
        approval_verifier=demo_refund_approval,
    )

    manager = SalesActor(
        user_id="sales001",
        tenant_id="demo",
        roles=frozenset({"sales_manager"}),
        warehouse_ids=frozenset({"WH001"}),
    )

    finance = SalesActor(
        user_id="finance001",
        tenant_id="demo",
        roles=frozenset({"finance_manager"}),
        warehouse_ids=frozenset({"WH001"}),
    )

    order = service.create_order(
        actor=manager,
        order_id="ORDER001",
        customer_id="CUSTOMER001",
        warehouse_id="WH001",
        items=[
            SalesItemInput(
                sku="SKU001",
                quantity=2,
                unit_price=Decimal("1800.00"),
                unit_cost=Decimal("1200.00"),
            ),
            SalesItemInput(
                sku="SKU002",
                quantity=1,
                unit_price=Decimal("1400.00"),
                unit_cost=Decimal("850.00"),
            ),
        ],
        discount="200.00",
    )

    order = service.confirm_order(
        manager, order.order_id, order.version
    )

    order = service.record_verified_payment(
        manager,
        order.order_id,
        order.version,
        "PAYMENT-DEMO",
    )

    order = service.request_fulfillment(
        manager,
        order.order_id,
        order.version,
        "FULFILLMENT001",
    )

    order = service.record_refund(
        finance,
        order.order_id,
        order.version,
        amount="100.00",
        refund_reference="REFUND001",
        approval_reference="APPROVED-DEMO",
    )

    print("Order:", order.status.value)
    print("Total:", order.total)
    print("Refunded:", order.refunded_amount)
    print("Metrics:", service.sales_metrics(manager))
