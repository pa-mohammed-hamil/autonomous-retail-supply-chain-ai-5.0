from __future__ import annotations

"""Planned module: sales service. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
backend/services/sales_service.py

Python 3.10+ | Standard library only

Reference sales transaction service.

Features:
- Multi-tenant, warehouse-scoped RBAC
- Product price/cost snapshots
- Sales order creation
- Decimal-based discounts and tax
- Order confirmation
- Payment confirmation reference
- Fulfillment handoff outbox
- Partial and full refunds
- Refund quantity tracking
- Sales KPIs and revenue reporting
- Idempotent order/refund references
- Audit events and JSON export

Limitations:
- In-memory persistence
- No payment gateway connection
- No inventory reservation
- No external fulfillment execution
- No real payment verification
- Simplified tax and refund policies

Never treat client-supplied payment
references as proof of payment.
"""


import copy
import json
import threading
import uuid

from dataclasses import (
    asdict,
    dataclass,
    field,
)
from datetime import (
    datetime,
    timezone,
)
from decimal import (
    Decimal,
    InvalidOperation,
    ROUND_HALF_UP,
)
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


CENT = Decimal("0.01")


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def required_text(
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


def money(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(
            "Invalid monetary value"
        )

    try:
        result = Decimal(str(value))
    except (
        InvalidOperation,
        ValueError,
    ) as exc:
        raise ValueError(
            "Invalid monetary value"
        ) from exc

    if (
        not result.is_finite()
        or result < 0
    ):
        raise ValueError(
            "Money must be finite and nonnegative"
        )

    return result.quantize(
        CENT,
        rounding=ROUND_HALF_UP,
    )


def rate(value: Any) -> Decimal:
    result = Decimal(
        str(value)
    )

    if (
        not result.is_finite()
        or result < 0
        or result > 100
    ):
        raise ValueError(
            "Rate must be between 0 and 100"
        )

    return result


def positive_quantity(
    value: int,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        raise ValueError(
            "Quantity must be positive integer"
        )

    return value


class SalesStatus(str, Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    PAID = "paid"
    FULFILLMENT_REQUESTED = (
        "fulfillment_requested"
    )
    CANCELLED = "cancelled"


class RefundStatus(str, Enum):
    RECORDED = "recorded"


@dataclass(frozen=True)
class SalesActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str] = (
        frozenset()
    )
    is_active: bool = True


@dataclass(frozen=True)
class SalesItem:
    sku: str
    quantity: int
    unit_price: Decimal
    unit_cost: Decimal
    discount_pct: Decimal = Decimal("0")
    tax_pct: Decimal = Decimal("0")


@dataclass(frozen=True)
class SalesLine:
    sku: str
    quantity: int
    unit_price: Decimal
    unit_cost: Decimal
    discount_pct: Decimal
    tax_pct: Decimal
    subtotal: Decimal
    discount_amount: Decimal
    taxable_amount: Decimal
    tax_amount: Decimal
    total: Decimal


@dataclass
class SalesOrder:
    order_id: str
    tenant_id: str
    warehouse_id: str
    customer_id: str
    currency: str
    status: SalesStatus
    items: list[SalesLine]
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    grand_total: Decimal
    created_by: str
    created_at: str
    updated_at: str
    payment_reference: str | None = None
    fulfillment_reference: str | None = None
    refunded_amount: Decimal = Decimal("0.00")
    refunded_quantities: dict[
        str, int
    ] = field(default_factory=dict)


@dataclass(frozen=True)
class SalesRefund:
    refund_id: str
    tenant_id: str
    order_id: str
    sku: str
    quantity: int
    refund_amount: Decimal
    reason: str
    reference: str
    created_by: str
    created_at: str
    status: RefundStatus = (
        RefundStatus.RECORDED
    )


@dataclass(frozen=True)
class SalesAuditEvent:
    event_id: str
    tenant_id: str
    order_id: str
    actor_id: str
    action: str
    timestamp: str
    details: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass
class SalesOutboxEvent:
    event_id: str
    tenant_id: str
    order_id: str
    warehouse_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: str
    delivered: bool = False


class RetailSalesService:
    SALES_ROLES = frozenset({
        "sales_operator",
        "sales_manager",
        "operations_manager",
        "corporate_admin",
    })

    MANAGER_ROLES = frozenset({
        "sales_manager",
        "operations_manager",
        "corporate_admin",
    })

    READER_ROLES = (
        SALES_ROLES
        | frozenset({
            "sales_analyst",
            "finance_analyst",
            "warehouse_manager",
        })
    )

    def __init__(
        self,
        tenant_id: str,
        currency: str = "INR",
    ):
        self.tenant_id = required_text(
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

        self.currency = currency.upper()

        self._lock = threading.RLock()

        self._orders: dict[
            str, SalesOrder
        ] = {}

        self._refunds: dict[
            str, SalesRefund
        ] = {}

        self._refund_reference_index: dict[
            str, str
        ] = {}

        self._audit: list[
            SalesAuditEvent
        ] = []

        self._outbox: dict[
            str, SalesOutboxEvent
        ] = {}

    def _authorize(
        self,
        actor: SalesActor,
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
                "Sales access denied"
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

    def _get_order(
        self,
        actor: SalesActor,
        order_id: str,
        roles: frozenset[str],
    ) -> SalesOrder:
        order = self._orders.get(
            order_id
        )

        if order is None:
            raise KeyError(
                "Sales order not found"
            )

        self._authorize(
            actor,
            roles,
            order.warehouse_id,
        )

        return order

    @staticmethod
    def _build_line(
        item: SalesItem,
    ) -> SalesLine:
        sku = required_text(
            item.sku,
            "sku",
        )

        quantity = positive_quantity(
            item.quantity
        )

        price = money(
            item.unit_price
        )

        cost = money(
            item.unit_cost
        )

        discount = rate(
            item.discount_pct
        )

        tax = rate(
            item.tax_pct
        )

        subtotal = money(
            price * quantity
        )

        discount_amount = money(
            subtotal
            * discount
            / Decimal("100")
        )

        taxable = (
            subtotal
            - discount_amount
        )

        tax_amount = money(
            taxable
            * tax
            / Decimal("100")
        )

        return SalesLine(
            sku=sku,
            quantity=quantity,
            unit_price=price,
            unit_cost=cost,
            discount_pct=discount,
            tax_pct=tax,
            subtotal=subtotal,
            discount_amount=discount_amount,
            taxable_amount=taxable,
            tax_amount=tax_amount,
            total=taxable + tax_amount,
        )

    def _audit_event(
        self,
        actor: SalesActor,
        order: SalesOrder,
        action: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._audit.append(
            SalesAuditEvent(
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

    def _emit(
        self,
        order: SalesOrder,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        event = SalesOutboxEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            order_id=order.order_id,
            warehouse_id=order.warehouse_id,
            event_type=event_type,
            payload=copy.deepcopy(
                payload
            ),
            created_at=utc_now(),
        )

        self._outbox[
            event.event_id
        ] = event

    def create_order(
        self,
        actor: SalesActor,
        order_id: str,
        warehouse_id: str,
        customer_id: str,
        items: Iterable[SalesItem],
    ) -> SalesOrder:
        self._authorize(
            actor,
            self.SALES_ROLES,
            warehouse_id,
        )

        order_id = required_text(
            order_id,
            "order_id",
        )

        warehouse_id = required_text(
            warehouse_id,
            "warehouse_id",
        )

        customer_id = required_text(
            customer_id,
            "customer_id",
        )

        lines = [
            self._build_line(item)
            for item in items
        ]

        if not lines:
            raise ValueError(
                "Sales order requires items"
            )

        if len({
            line.sku
            for line in lines
        }) != len(lines):
            raise ValueError(
                "Duplicate SKU in order"
            )

        subtotal = sum(
            (
                line.subtotal
                for line in lines
            ),
            Decimal("0.00"),
        )

        discount_total = sum(
            (
                line.discount_amount
                for line in lines
            ),
            Decimal("0.00"),
        )

        tax_total = sum(
            (
                line.tax_amount
                for line in lines
            ),
            Decimal("0.00"),
        )

        grand_total = (
            subtotal
            - discount_total
            + tax_total
        )

        with self._lock:
            existing = self._orders.get(
                order_id
            )

            if existing:
                if (
                    existing.warehouse_id
                    != warehouse_id
                    or existing.customer_id
                    != customer_id
                    or existing.items
                    != lines
                ):
                    raise ValueError(
                        "Sales order ID conflict"
                    )

                return copy.deepcopy(
                    existing
                )

            timestamp = utc_now()

            order = SalesOrder(
                order_id=order_id,
                tenant_id=self.tenant_id,
                warehouse_id=warehouse_id,
                customer_id=customer_id,
                currency=self.currency,
                status=SalesStatus.DRAFT,
                items=lines,
                subtotal=subtotal,
                discount_total=(
                    discount_total
                ),
                tax_total=tax_total,
                grand_total=grand_total,
                created_by=actor.user_id,
                created_at=timestamp,
                updated_at=timestamp,
            )

            self._orders[
                order_id
            ] = order

            self._audit_event(
                actor,
                order,
                "sales_order_created",
            )

            return copy.deepcopy(
                order
            )

    def confirm_order(
        self,
        actor: SalesActor,
        order_id: str,
    ) -> SalesOrder:
        with self._lock:
            order = self._get_order(
                actor,
                order_id,
                self.SALES_ROLES,
            )

            if order.status == (
                SalesStatus.CONFIRMED
            ):
                return copy.deepcopy(
                    order
                )

            if order.status != (
                SalesStatus.DRAFT
            ):
                raise ValueError(
                    "Only draft orders can be confirmed"
                )

            order.status = (
                SalesStatus.CONFIRMED
            )

            order.updated_at = (
                utc_now()
            )

            self._audit_event(
                actor,
                order,
                "sales_order_confirmed",
            )

            return copy.deepcopy(
                order
            )

    def record_verified_payment(
        self,
        actor: SalesActor,
        order_id: str,
        payment_reference: str,
        verified_amount: Any,
    ) -> SalesOrder:
        """
        Trusted payment-webhook adapter only.

        This method assumes the caller has
        independently authenticated the
        payment provider and verified:
        - payment settlement status
        - tenant and order ownership
        - payment amount and currency
        - non-reuse of transaction reference

        The service does not perform these
        external checks itself.
        """
        payment_reference = required_text(
            payment_reference,
            "payment_reference",
        )

        verified_amount = money(
            verified_amount
        )

        with self._lock:
            order = self._get_order(
                actor,
                order_id,
                self.MANAGER_ROLES,
            )

            if order.status == (
                SalesStatus.PAID
            ):
                if (
                    order.payment_reference
                    != payment_reference
                ):
                    raise ValueError(
                        "Payment reference conflict"
                    )

                return copy.deepcopy(
                    order
                )

            if order.status != (
                SalesStatus.CONFIRMED
            ):
                raise ValueError(
                    "Order must be confirmed"
                )

            if verified_amount != (
                order.grand_total
            ):
                raise ValueError(
                    "Payment amount mismatch"
                )

            order.payment_reference = (
                payment_reference
            )

            order.status = (
                SalesStatus.PAID
            )

            order.updated_at = (
                utc_now()
            )

            self._emit(
                order,
                "sales.payment_recorded",
                {
                    "order_id": order_id,
                    "amount": str(
                        verified_amount
                    ),
                    "payment_reference": (
                        payment_reference
                    ),
                },
            )

            self._audit_event(
                actor,
                order,
                "payment_recorded",
            )

            return copy.deepcopy(
                order
            )

    def request_fulfillment(
        self,
        actor: SalesActor,
        order_id: str,
    ) -> SalesOrder:
        with self._lock:
            order = self._get_order(
                actor,
                order_id,
                self.MANAGER_ROLES,
            )

            if order.status == (
                SalesStatus.FULFILLMENT_REQUESTED
            ):
                return copy.deepcopy(
                    order
                )

            if order.status != (
                SalesStatus.PAID
            ):
                raise ValueError(
                    "Payment required before fulfillment"
                )

            order.status = (
                SalesStatus.FULFILLMENT_REQUESTED
            )

            order.updated_at = (
                utc_now()
            )

            self._emit(
                order,
                "sales.fulfillment_requested",
                {
                    "order_id": order.order_id,
                    "warehouse_id": (
                        order.warehouse_id
                    ),
                    "customer_id": (
                        order.customer_id
                    ),
                    "items": [
                        {
                            "sku": line.sku,
                            "quantity": (
                                line.quantity
                            ),
                        }
                        for line in order.items
                    ],
                },
            )

            self._audit_event(
                actor,
                order,
                "fulfillment_requested",
            )

            return copy.deepcopy(
                order
            )

    def cancel_order(
        self,
        actor: SalesActor,
        order_id: str,
    ) -> SalesOrder:
        with self._lock:
            order = self._get_order(
                actor,
                order_id,
                self.MANAGER_ROLES,
            )

            if order.status == (
                SalesStatus.CANCELLED
            ):
                return copy.deepcopy(
                    order
                )

            if order.status not in {
                SalesStatus.DRAFT,
                SalesStatus.CONFIRMED,
            }:
                raise ValueError(
                    "Paid orders require refund workflow"
                )

            order.status = (
                SalesStatus.CANCELLED
            )

            order.updated_at = (
                utc_now()
            )

            self._audit_event(
                actor,
                order,
                "sales_order_cancelled",
            )

            return copy.deepcopy(
                order
            )

    def record_refund(
        self,
        actor: SalesActor,
        refund_id: str,
        order_id: str,
        sku: str,
        quantity: int,
        refund_amount: Any,
        reason: str,
        reference: str,
    ) -> SalesRefund:
        """
        Records an externally verified refund.

        Does not send money or approve
        the refund. The caller must
        validate the payment provider
        refund event and refund policy.
        """
        refund_id = required_text(
            refund_id,
            "refund_id",
        )

        sku = required_text(
            sku,
            "sku",
        )

        quantity = positive_quantity(
            quantity
        )

        reason = required_text(
            reason,
            "reason",
        )

        reference = required_text(
            reference,
            "reference",
        )

        refund_amount = money(
            refund_amount
        )

        with self._lock:
            order = self._get_order(
                actor,
                order_id,
                self.MANAGER_ROLES,
            )

            existing = self._refunds.get(
                refund_id
            )

            if existing:
                if (
                    existing.order_id != order_id
                    or existing.sku != sku
                    or existing.quantity
                    != quantity
                    or existing.refund_amount
                    != refund_amount
                    or existing.reference
                    != reference
                    or existing.reason
                    != reason
                ):
                    raise ValueError(
                        "Refund ID conflict"
                    )

                return existing

            if reference in (
                self._refund_reference_index
            ):
                raise ValueError(
                    "Refund reference already used"
                )

            if order.status not in {
                SalesStatus.PAID,
                SalesStatus.FULFILLMENT_REQUESTED,
            }:
                raise ValueError(
                    "Order is not paid"
                )

            line = next(
                (
                    item
                    for item in order.items
                    if item.sku == sku
                ),
                None,
            )

            if line is None:
                raise ValueError(
                    "SKU not in order"
                )

            previously_refunded = (
                order.refunded_quantities.get(
                    sku,
                    0,
                )
            )

            if (
                previously_refunded
                + quantity
                > line.quantity
            ):
                raise ValueError(
                    "Refund quantity exceeds sold quantity"
                )

            # Prorated maximum is derived
            # from the original line total.
            maximum_refundable = money(
                line.total
                * quantity
                / line.quantity
            )

            if refund_amount > (
                maximum_refundable
            ):
                raise ValueError(
                    "Refund exceeds prorated line amount"
                )

            if (
                order.refunded_amount
                + refund_amount
                > order.grand_total
            ):
                raise ValueError(
                    "Refund exceeds order total"
                )

            refund = SalesRefund(
                refund_id=refund_id,
                tenant_id=self.tenant_id,
                order_id=order_id,
                sku=sku,
                quantity=quantity,
                refund_amount=(
                    refund_amount
                ),
                reason=reason,
                reference=reference,
                created_by=actor.user_id,
                created_at=utc_now(),
            )

            self._refunds[
                refund_id
            ] = refund

            self._refund_reference_index[
                reference
            ] = refund_id

            order.refunded_amount += (
                refund_amount
            )

            order.refunded_quantities[
                sku
            ] = (
                previously_refunded
                + quantity
            )

            order.updated_at = (
                utc_now()
            )

            self._emit(
                order,
                "sales.refund_recorded",
                {
                    "refund_id": refund_id,
                    "sku": sku,
                    "quantity": quantity,
                    "amount": str(
                        refund_amount
                    ),
                    "reference": reference,
                },
            )

            self._audit_event(
                actor,
                order,
                "refund_recorded",
                {
                    "refund_id": refund_id,
                },
            )

            return refund

    def get_order(
        self,
        actor: SalesActor,
        order_id: str,
    ) -> SalesOrder:
        with self._lock:
            return copy.deepcopy(
                self._get_order(
                    actor,
                    order_id,
                    self.READER_ROLES,
                )
            )

    def list_orders(
        self,
        actor: SalesActor,
        status: SalesStatus | None = None,
    ) -> list[SalesOrder]:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        with self._lock:
            return [
                copy.deepcopy(order)
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

    def sales_metrics(
        self,
        actor: SalesActor,
    ) -> dict[str, Any]:
        orders = self.list_orders(
            actor
        )

        paid_orders = [
            order
            for order in orders
            if order.status in {
                SalesStatus.PAID,
                SalesStatus.FULFILLMENT_REQUESTED,
            }
        ]

        gross_sales = sum(
            (
                order.grand_total
                for order in paid_orders
            ),
            Decimal("0.00"),
        )

        refunds = sum(
            (
                order.refunded_amount
                for order in paid_orders
            ),
            Decimal("0.00"),
        )

        units_sold = sum(
            line.quantity
            for order in paid_orders
            for line in order.items
        )

        return {
            "tenant_id": self.tenant_id,
            "total_orders": len(orders),
            "paid_orders": len(
                paid_orders
            ),
            "gross_sales": str(
                gross_sales
            ),
            "refunds": str(
                refunds
            ),
            "net_sales": str(
                gross_sales - refunds
            ),
            "units_sold": units_sold,
            "currency": self.currency,
        }

    def pending_events(
        self,
        actor: SalesActor,
    ) -> list[SalesOutboxEvent]:
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
                if (
                    not event.delivered
                    and (
                        "corporate_admin"
                        in actor.roles
                        or event.warehouse_id
                        in actor.warehouse_ids
                    )
                )
            ]

    def mark_event_delivered(
        self,
        actor: SalesActor,
        event_id: str,
    ) -> None:
        with self._lock:
            event = self._outbox.get(
                event_id
            )

            if event is None:
                raise KeyError(
                    "Event not found"
                )

            self._authorize(
                actor,
                self.MANAGER_ROLES,
                event.warehouse_id,
            )

            event.delivered = True

    def audit_events(
        self,
        actor: SalesActor,
        order_id: str,
    ) -> list[SalesAuditEvent]:
        with self._lock:
            self._get_order(
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
        actor: SalesActor,
        output_path: str | Path,
    ) -> Path:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
        )

        with self._lock:
            payload = [
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
                payload,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        return output


if __name__ == "__main__":
    service = RetailSalesService(
        tenant_id="demo"
    )

    manager = SalesActor(
        user_id="sales-manager",
        tenant_id="demo",
        roles=frozenset({
            "sales_manager",
        }),
        warehouse_ids=frozenset({
            "WH001",
        }),
    )

    order = service.create_order(
        actor=manager,
        order_id="SALE001",
        warehouse_id="WH001",
        customer_id="CUSTOMER001",
        items=[
            SalesItem(
                sku="SKU001",
                quantity=2,
                unit_price=Decimal("1500.00"),
                unit_cost=Decimal("1100.00"),
                discount_pct=Decimal("10"),
                tax_pct=Decimal("18"),
            ),
            SalesItem(
                sku="SKU002",
                quantity=1,
                unit_price=Decimal("2500.00"),
                unit_cost=Decimal("1800.00"),
            ),
        ],
    )

    print(
        "Order total:",
        order.grand_total,
    )

    service.confirm_order(
        manager,
        order.order_id,
    )

    # Demo only: this simulates a trusted
    # payment adapter. No payment occurred.
    service.record_verified_payment(
        manager,
        order.order_id,
        payment_reference="PAY001",
        verified_amount=(
            order.grand_total
        ),
    )

    service.request_fulfillment(
        manager,
        order.order_id,
    )

    print(
        "Sales metrics:",
        service.sales_metrics(
            manager
        ),
    )

    print(
        "Integration events:",
        len(
            service.pending_events(
                manager
            )
        ),
    )
