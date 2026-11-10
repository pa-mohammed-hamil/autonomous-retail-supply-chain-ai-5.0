from __future__ import annotations

"""Planned module: product service. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
backend/services/product_service.py

Python 3.10+ | Standard library only

Product catalog reference service.

Features:
- Tenant-scoped product catalog
- SKU uniqueness
- Category and brand metadata
- Supplier association
- Decimal price/cost validation
- Product lifecycle transitions
- Optimistic version checking
- Idempotent product registration
- Search and filtering
- Price and margin analytics
- Audit events
- Integration outbox
- JSON export

No inventory, procurement, or payment
actions are executed automatically.
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
)
from enum import Enum
from pathlib import Path
from typing import Any


def now_utc() -> str:
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


def amount(value: Any) -> Decimal:
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
        or result != result.quantize(
            Decimal("0.01")
        )
    ):
        raise ValueError(
            "Money must be nonnegative "
            "with at most two decimal places"
        )

    return result


class ProductStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"
    DISCONTINUED = "discontinued"


@dataclass(frozen=True)
class ProductActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    is_active: bool = True


@dataclass
class RetailProduct:
    product_id: str
    tenant_id: str
    sku: str
    name: str
    category: str
    brand: str
    supplier_id: str
    unit_price: Decimal
    unit_cost: Decimal
    currency: str
    status: ProductStatus
    description: str
    created_by: str
    created_at: str
    updated_at: str
    version: int = 1
    attributes: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class ProductAuditEvent:
    event_id: str
    tenant_id: str
    product_id: str
    actor_id: str
    action: str
    timestamp: str
    details: dict[str, Any]


@dataclass
class ProductOutboxEvent:
    event_id: str
    tenant_id: str
    product_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: str
    delivered: bool = False


class RetailProductService:
    MANAGER_ROLES = frozenset({
        "product_manager",
        "corporate_admin",
    })

    EDITOR_ROLES = (
        MANAGER_ROLES
        | frozenset({
            "catalog_editor",
        })
    )

    READER_ROLES = (
        EDITOR_ROLES
        | frozenset({
            "product_analyst",
            "inventory_manager",
            "procurement_manager",
            "quality_manager",
            "operations_manager",
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

        self._products: dict[
            str, RetailProduct
        ] = {}

        self._sku_index: dict[
            str, str
        ] = {}

        self._audit: list[
            ProductAuditEvent
        ] = []

        self._outbox: dict[
            str, ProductOutboxEvent
        ] = {}

    def _authorize(
        self,
        actor: ProductActor,
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
                "Product access denied"
            )

    def _get(
        self,
        product_id: str,
    ) -> RetailProduct:
        product = self._products.get(
            product_id
        )

        if product is None:
            raise KeyError(
                "Product not found"
            )

        return product

    def _audit_event(
        self,
        actor: ProductActor,
        product: RetailProduct,
        action: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._audit.append(
            ProductAuditEvent(
                event_id=str(uuid.uuid4()),
                tenant_id=self.tenant_id,
                product_id=product.product_id,
                actor_id=actor.user_id,
                action=action,
                timestamp=now_utc(),
                details=copy.deepcopy(
                    details or {}
                ),
            )
        )

    def _emit(
        self,
        product: RetailProduct,
        event_type: str,
    ) -> None:
        event = ProductOutboxEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            product_id=product.product_id,
            event_type=event_type,
            payload={
                "product_id": product.product_id,
                "sku": product.sku,
                "status": product.status.value,
                "version": product.version,
            },
            created_at=now_utc(),
        )

        self._outbox[
            event.event_id
        ] = event

    def create_product(
        self,
        actor: ProductActor,
        product_id: str,
        sku: str,
        name: str,
        category: str,
        brand: str,
        supplier_id: str,
        unit_price: Any,
        unit_cost: Any,
        description: str = "",
        attributes: dict[str, Any] | None = None,
    ) -> RetailProduct:
        self._authorize(
            actor,
            self.EDITOR_ROLES,
        )

        product_id = required_text(
            product_id,
            "product_id",
        )

        sku = required_text(
            sku,
            "sku",
        ).upper()

        name = required_text(
            name,
            "name",
        )

        category = required_text(
            category,
            "category",
        )

        brand = required_text(
            brand,
            "brand",
        )

        supplier_id = required_text(
            supplier_id,
            "supplier_id",
        )

        if (
            not isinstance(description, str)
            or len(description) > 5000
        ):
            raise ValueError(
                "Invalid description"
            )

        price = amount(unit_price)
        cost = amount(unit_cost)

        attributes = attributes or {}

        if not isinstance(
            attributes,
            dict,
        ):
            raise ValueError(
                "Attributes must be a dictionary"
            )

        # Require JSON-compatible attributes.
        attributes_copy = json.loads(
            json.dumps(
                attributes,
                allow_nan=False,
            )
        )

        with self._lock:
            if product_id in self._products:
                existing = self._products[
                    product_id
                ]

                if (
                    existing.sku != sku
                    or existing.name != name
                    or existing.category
                    != category
                    or existing.brand != brand
                    or existing.supplier_id
                    != supplier_id
                    or existing.unit_price
                    != price
                    or existing.unit_cost
                    != cost
                    or existing.description
                    != description
                    or existing.attributes
                    != attributes_copy
                ):
                    raise ValueError(
                        "Product ID conflict"
                    )

                return copy.deepcopy(
                    existing
                )

            if sku in self._sku_index:
                raise ValueError(
                    "SKU already registered"
                )

            timestamp = now_utc()

            product = RetailProduct(
                product_id=product_id,
                tenant_id=self.tenant_id,
                sku=sku,
                name=name,
                category=category,
                brand=brand,
                supplier_id=supplier_id,
                unit_price=price,
                unit_cost=cost,
                currency=self.currency,
                status=ProductStatus.DRAFT,
                description=description,
                created_by=actor.user_id,
                created_at=timestamp,
                updated_at=timestamp,
                attributes=attributes_copy,
            )

            self._products[
                product_id
            ] = product

            self._sku_index[
                sku
            ] = product_id

            self._audit_event(
                actor,
                product,
                "product_created",
            )

            self._emit(
                product,
                "product.created",
            )

            return copy.deepcopy(
                product
            )

    def get_product(
        self,
        actor: ProductActor,
        product_id: str,
    ) -> RetailProduct:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        with self._lock:
            return copy.deepcopy(
                self._get(product_id)
            )

    def get_by_sku(
        self,
        actor: ProductActor,
        sku: str,
    ) -> RetailProduct:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        sku = required_text(
            sku,
            "sku",
        ).upper()

        with self._lock:
            product_id = (
                self._sku_index.get(
                    sku
                )
            )

            if product_id is None:
                raise KeyError(
                    "SKU not found"
                )

            return copy.deepcopy(
                self._products[
                    product_id
                ]
            )

    def update_product(
        self,
        actor: ProductActor,
        product_id: str,
        expected_version: int,
        *,
        name: str | None = None,
        category: str | None = None,
        brand: str | None = None,
        supplier_id: str | None = None,
        description: str | None = None,
    ) -> RetailProduct:
        self._authorize(
            actor,
            self.EDITOR_ROLES,
        )

        updates = {}

        for key, value in {
            "name": name,
            "category": category,
            "brand": brand,
            "supplier_id": supplier_id,
        }.items():
            if value is not None:
                updates[key] = required_text(
                    value,
                    key,
                )

        if description is not None:
            if (
                not isinstance(
                    description,
                    str,
                )
                or len(description) > 5000
            ):
                raise ValueError(
                    "Invalid description"
                )

            updates[
                "description"
            ] = description

        if not updates:
            raise ValueError(
                "No updates supplied"
            )

        with self._lock:
            product = self._get(
                product_id
            )

            if product.version != (
                expected_version
            ):
                raise ValueError(
                    "Product version conflict"
                )

            if product.status == (
                ProductStatus.DISCONTINUED
            ):
                raise ValueError(
                    "Discontinued product is immutable"
                )

            changed = False

            for key, value in updates.items():
                if getattr(
                    product,
                    key,
                ) != value:
                    setattr(
                        product,
                        key,
                        value,
                    )

                    changed = True

            if changed:
                product.version += 1
                product.updated_at = (
                    now_utc()
                )

                self._audit_event(
                    actor,
                    product,
                    "product_updated",
                    {
                        "fields": list(
                            updates
                        ),
                    },
                )

                self._emit(
                    product,
                    "product.updated",
                )

            return copy.deepcopy(
                product
            )

    def update_pricing(
        self,
        actor: ProductActor,
        product_id: str,
        expected_version: int,
        unit_price: Any,
        unit_cost: Any,
        approval_reference: str | None = None,
    ) -> RetailProduct:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
        )

        price = amount(
            unit_price
        )

        cost = amount(
            unit_cost
        )

        # Approval reference is recorded,
        # not externally verified.
        # A production system must use
        # approval_service verification.
        if approval_reference is not None:
            approval_reference = required_text(
                approval_reference,
                "approval_reference",
            )

        with self._lock:
            product = self._get(
                product_id
            )

            if product.version != (
                expected_version
            ):
                raise ValueError(
                    "Product version conflict"
                )

            if product.status == (
                ProductStatus.DISCONTINUED
            ):
                raise ValueError(
                    "Cannot reprice discontinued product"
                )

            if (
                product.unit_price == price
                and product.unit_cost == cost
            ):
                return copy.deepcopy(
                    product
                )

            product.unit_price = price
            product.unit_cost = cost
            product.version += 1
            product.updated_at = (
                now_utc()
            )

            self._audit_event(
                actor,
                product,
                "product_pricing_updated",
                {
                    "approval_reference": (
                        approval_reference
                    ),
                },
            )

            self._emit(
                product,
                "product.pricing_updated",
            )

            return copy.deepcopy(
                product
            )

    def change_status(
        self,
        actor: ProductActor,
        product_id: str,
        expected_version: int,
        new_status: ProductStatus,
    ) -> RetailProduct:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
        )

        if not isinstance(
            new_status,
            ProductStatus,
        ):
            raise ValueError(
                "Invalid status"
            )

        transitions = {
            ProductStatus.DRAFT: {
                ProductStatus.ACTIVE,
                ProductStatus.DISCONTINUED,
            },
            ProductStatus.ACTIVE: {
                ProductStatus.INACTIVE,
                ProductStatus.DISCONTINUED,
            },
            ProductStatus.INACTIVE: {
                ProductStatus.ACTIVE,
                ProductStatus.DISCONTINUED,
            },
            ProductStatus.DISCONTINUED: set(),
        }

        with self._lock:
            product = self._get(
                product_id
            )

            if product.version != (
                expected_version
            ):
                raise ValueError(
                    "Product version conflict"
                )

            if new_status == product.status:
                return copy.deepcopy(
                    product
                )

            if new_status not in (
                transitions[
                    product.status
                ]
            ):
                raise ValueError(
                    "Invalid product status transition"
                )

            previous = (
                product.status
            )

            product.status = (
                new_status
            )

            product.version += 1
            product.updated_at = (
                now_utc()
            )

            self._audit_event(
                actor,
                product,
                "product_status_changed",
                {
                    "from": previous.value,
                    "to": new_status.value,
                },
            )

            self._emit(
                product,
                "product.status_changed",
            )

            return copy.deepcopy(
                product
            )

    def search_products(
        self,
        actor: ProductActor,
        query: str = "",
        category: str | None = None,
        status: ProductStatus | None = None,
        limit: int = 50,
    ) -> list[RetailProduct]:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 500
        ):
            raise ValueError(
                "Invalid result limit"
            )

        query = query.casefold()

        with self._lock:
            products = [
                copy.deepcopy(product)
                for product in (
                    self._products.values()
                )
                if (
                    (
                        not query
                        or query in (
                            product.name.casefold()
                        )
                        or query in (
                            product.sku.casefold()
                        )
                        or query in (
                            product.brand.casefold()
                        )
                    )
                    and (
                        category is None
                        or product.category
                        == category
                    )
                    and (
                        status is None
                        or product.status
                        == status
                    )
                )
            ]

        return sorted(
            products,
            key=lambda p: p.sku,
        )[:limit]

    def product_metrics(
        self,
        actor: ProductActor,
    ) -> dict[str, Any]:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        with self._lock:
            products = list(
                self._products.values()
            )

            return {
                "tenant_id": self.tenant_id,
                "total_products": len(
                    products
                ),
                "status_counts": {
                    status.value: sum(
                        product.status == status
                        for product in products
                    )
                    for status in ProductStatus
                },
                "category_counts": {
                    category: sum(
                        product.category == category
                        for product in products
                    )
                    for category in sorted({
                        product.category
                        for product in products
                    })
                },
            }

    def margin_analysis(
        self,
        actor: ProductActor,
        product_id: str,
    ) -> dict[str, Any]:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        with self._lock:
            product = self._get(
                product_id
            )

            margin_amount = (
                product.unit_price
                - product.unit_cost
            )

            margin_pct = (
                (
                    margin_amount
                    / product.unit_price
                    * Decimal("100")
                )
                if product.unit_price > 0
                else None
            )

            return {
                "product_id": product_id,
                "sku": product.sku,
                "currency": product.currency,
                "unit_price": str(
                    product.unit_price
                ),
                "unit_cost": str(
                    product.unit_cost
                ),
                "gross_margin_amount": str(
                    margin_amount
                ),
                "gross_margin_pct": (
                    str(
                        margin_pct.quantize(
                            Decimal("0.01")
                        )
                    )
                    if margin_pct
                    is not None
                    else None
                ),
            }

    def pending_events(
        self,
        actor: ProductActor,
    ) -> list[ProductOutboxEvent]:
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
            ]

    def mark_event_delivered(
        self,
        actor: ProductActor,
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
                    "Event not found"
                )

            event.delivered = True

    def audit_events(
        self,
        actor: ProductActor,
        product_id: str,
    ) -> list[ProductAuditEvent]:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        with self._lock:
            self._get(
                product_id
            )

            return [
                copy.deepcopy(event)
                for event in self._audit
                if event.product_id
                == product_id
            ]

    def export_json(
        self,
        actor: ProductActor,
        output_path: str | Path,
    ) -> Path:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
        )

        with self._lock:
            payload = [
                asdict(product)
                for product in (
                    self._products.values()
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
    service = RetailProductService(
        tenant_id="demo"
    )

    manager = ProductActor(
        user_id="product-manager",
        tenant_id="demo",
        roles=frozenset({
            "product_manager",
        }),
    )

    product = service.create_product(
        actor=manager,
        product_id="PROD001",
        sku="SKU001",
        name="Smart Device",
        category="Electronics",
        brand="DemoBrand",
        supplier_id="SUP001",
        unit_price="1500.00",
        unit_cost="1100.00",
        description=(
            "Demo retail product"
        ),
        attributes={
            "warranty_months": 12,
            "color": "Black",
        },
    )

    product = service.change_status(
        actor=manager,
        product_id=product.product_id,
        expected_version=product.version,
        new_status=ProductStatus.ACTIVE,
    )

    print(
        "Product:",
        product.sku,
        product.status.value,
    )

    print(
        "Margin:",
        service.margin_analysis(
            manager,
            product.product_id,
        ),
    )

    print(
        "Catalog metrics:",
        service.product_metrics(
            manager
        ),
    )

    print(
        "Pending integration events:",
        len(
            service.pending_events(
                manager
            )
        ),
    )
