from __future__ import annotations

"""Planned module: product. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
backend/services/product_service.py

Python 3.10+ | Standard library only

Features:
- Multi-tenant product catalog
- Role-based access control
- Unique SKU enforcement
- Product lifecycle management
- Pricing and cost updates
- Margin analytics
- Search and filtering
- Optimistic version control
- Audit trail
- Notification outbox
- JSON export

Reference implementation:
in-memory storage, no external integrations.
"""


import copy
import json
import re
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


def required_text(
    value: str,
    field_name: str,
    limit: int = 255,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
    ):
        raise ValueError(f"Invalid {field_name}")
    return value.strip()


def validate_sku(value: str) -> str:
    sku = required_text(value, "sku", 64).upper()
    if not re.fullmatch(r"[A-Z0-9_-]+", sku):
        raise ValueError("Invalid SKU format")
    return sku


def monetary(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("Invalid money value")

    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0:
            raise ValueError("Money must be nonnegative")
        return result.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid monetary amount") from exc


class ProductStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    DISCONTINUED = "discontinued"
    ARCHIVED = "archived"


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
    description: str
    category: str
    supplier_id: str | None
    unit_cost: Decimal
    selling_price: Decimal
    currency: str
    status: ProductStatus
    created_by: str
    created_at: str
    updated_at: str
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProductAuditEvent:
    event_id: str
    tenant_id: str
    product_id: str
    actor_id: str
    action: str
    timestamp: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProductOutboxEvent:
    event_id: str
    tenant_id: str
    product_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: str
    delivered: bool = False


ApprovalVerifier = Callable[[str, str], bool]


class RetailProductService:
    WRITER_ROLES = frozenset({
        "product_manager",
        "catalog_manager",
        "operations_manager",
        "corporate_admin",
    })

    READER_ROLES = WRITER_ROLES | frozenset({
        "inventory_manager",
        "procurement_manager",
        "warehouse_manager",
        "business_analyst",
        "sales_manager",
    })

    PRICE_APPROVER_ROLES = frozenset({
        "product_manager",
        "corporate_admin",
    })

    STATUS_TRANSITIONS = {
        ProductStatus.DRAFT: {
            ProductStatus.ACTIVE,
            ProductStatus.ARCHIVED,
        },
        ProductStatus.ACTIVE: {
            ProductStatus.DISCONTINUED,
        },
        ProductStatus.DISCONTINUED: {
            ProductStatus.ACTIVE,
            ProductStatus.ARCHIVED,
        },
        ProductStatus.ARCHIVED: set(),
    }

    def __init__(
        self,
        tenant_id: str,
        currency: str = "INR",
        approval_verifier: ApprovalVerifier | None = None,
    ):
        self.tenant_id = required_text(
            tenant_id, "tenant_id"
        )
        self.currency = required_text(
            currency, "currency", 3
        ).upper()

        self.approval_verifier = approval_verifier
        self._lock = threading.RLock()
        self._products: dict[str, RetailProduct] = {}
        self._sku_index: dict[str, str] = {}
        self._audit: list[ProductAuditEvent] = []
        self._outbox: dict[str, ProductOutboxEvent] = {}

    def _authorize(
        self,
        actor: ProductActor,
        roles: frozenset[str],
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.user_id.strip()
            or not actor.roles.intersection(roles)
        ):
            raise PermissionError("Product access denied")

    def _get(self, product_id: str) -> RetailProduct:
        product = self._products.get(product_id)
        if product is None:
            raise KeyError("Product not found")
        return product

    def _record(
        self,
        actor_id: str,
        product: RetailProduct,
        action: str,
        details: dict | None = None,
    ) -> None:
        self._audit.append(ProductAuditEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            product_id=product.product_id,
            actor_id=actor_id,
            action=action,
            timestamp=utc_now(),
            details=copy.deepcopy(details or {}),
        ))

        event = ProductOutboxEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            product_id=product.product_id,
            event_type=f"product.{action}",
            payload={
                "product_id": product.product_id,
                "sku": product.sku,
                "status": product.status.value,
                "version": product.version,
            },
            created_at=utc_now(),
        )

        self._outbox[event.event_id] = event

    @staticmethod
    def _touch(product: RetailProduct) -> None:
        product.version += 1
        product.updated_at = utc_now()

    def create_product(
        self,
        actor: ProductActor,
        sku: str,
        name: str,
        description: str,
        category: str,
        unit_cost: Any,
        selling_price: Any,
        supplier_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RetailProduct:
        self._authorize(actor, self.WRITER_ROLES)

        sku = validate_sku(sku)
        name = required_text(name, "name")
        category = required_text(category, "category")
        description = required_text(
            description, "description", 5000
        ) if description else ""

        cost = monetary(unit_cost)
        price = monetary(selling_price)

        if supplier_id is not None:
            supplier_id = required_text(
                supplier_id, "supplier_id"
            )

        metadata_copy = json.loads(
            json.dumps(metadata or {}, allow_nan=False)
        )

        if not isinstance(metadata_copy, dict):
            raise ValueError("Metadata must be an object")

        with self._lock:
            if sku in self._sku_index:
                raise ValueError("SKU already exists")

            current = utc_now()

            product = RetailProduct(
                product_id=str(uuid.uuid4()),
                tenant_id=self.tenant_id,
                sku=sku,
                name=name,
                description=description,
                category=category,
                supplier_id=supplier_id,
                unit_cost=cost,
                selling_price=price,
                currency=self.currency,
                status=ProductStatus.DRAFT,
                created_by=actor.user_id,
                created_at=current,
                updated_at=current,
                metadata=metadata_copy,
            )

            self._products[product.product_id] = product
            self._sku_index[sku] = product.product_id

            self._record(
                actor.user_id, product, "created"
            )
            return copy.deepcopy(product)

    def get_product(
        self,
        actor: ProductActor,
        product_id: str,
    ) -> RetailProduct:
        self._authorize(actor, self.READER_ROLES)

        with self._lock:
            return copy.deepcopy(self._get(product_id))

    def get_by_sku(
        self,
        actor: ProductActor,
        sku: str,
    ) -> RetailProduct:
        self._authorize(actor, self.READER_ROLES)
        sku = validate_sku(sku)

        with self._lock:
            product_id = self._sku_index.get(sku)
            if product_id is None:
                raise KeyError("SKU not found")
            return copy.deepcopy(self._get(product_id))

    def update_product(
        self,
        actor: ProductActor,
        product_id: str,
        expected_version: int,
        *,
        name: str | None = None,
        description: str | None = None,
        category: str | None = None,
        supplier_id: str | None = None,
    ) -> RetailProduct:
        self._authorize(actor, self.WRITER_ROLES)

        with self._lock:
            product = self._get(product_id)

            if product.version != expected_version:
                raise ValueError("Version conflict")

            if product.status == ProductStatus.ARCHIVED:
                raise ValueError("Archived products cannot be edited")

            if name is not None:
                product.name = required_text(name, "name")

            if description is not None:
                product.description = required_text(
                    description, "description", 5000
                )

            if category is not None:
                product.category = required_text(
                    category, "category"
                )

            if supplier_id is not None:
                product.supplier_id = required_text(
                    supplier_id, "supplier_id"
                )

            self._touch(product)
            self._record(
                actor.user_id, product, "updated"
            )
            return copy.deepcopy(product)

    def update_pricing(
        self,
        actor: ProductActor,
        product_id: str,
        expected_version: int,
        unit_cost: Any,
        selling_price: Any,
        approval_reference: str,
    ) -> RetailProduct:
        self._authorize(
            actor, self.PRICE_APPROVER_ROLES
        )

        cost = monetary(unit_cost)
        price = monetary(selling_price)
        approval_reference = required_text(
            approval_reference, "approval_reference"
        )

        with self._lock:
            product = self._get(product_id)

            if product.version != expected_version:
                raise ValueError("Version conflict")

            if product.status == ProductStatus.ARCHIVED:
                raise ValueError("Archived product pricing is locked")

            if self.approval_verifier is None:
                raise PermissionError(
                    "Approval verifier not configured"
                )

            if not self.approval_verifier(
                "price_change", approval_reference
            ):
                raise PermissionError("Pricing approval denied")

            product.unit_cost = cost
            product.selling_price = price
            self._touch(product)

            self._record(
                actor.user_id,
                product,
                "pricing_updated",
                {"approval_reference": approval_reference},
            )
            return copy.deepcopy(product)

    def change_status(
        self,
        actor: ProductActor,
        product_id: str,
        expected_version: int,
        new_status: ProductStatus,
    ) -> RetailProduct:
        self._authorize(actor, self.WRITER_ROLES)

        with self._lock:
            product = self._get(product_id)

            if product.version != expected_version:
                raise ValueError("Version conflict")

            if new_status not in self.STATUS_TRANSITIONS[
                product.status
            ]:
                raise ValueError("Invalid product lifecycle transition")

            product.status = new_status
            self._touch(product)

            self._record(
                actor.user_id,
                product,
                "status_changed",
                {"new_status": new_status.value},
            )
            return copy.deepcopy(product)

    def search_products(
        self,
        actor: ProductActor,
        query: str = "",
        category: str | None = None,
        status: ProductStatus | None = None,
    ) -> list[RetailProduct]:
        self._authorize(actor, self.READER_ROLES)

        search = query.strip().lower()

        with self._lock:
            return [
                copy.deepcopy(p)
                for p in self._products.values()
                if (
                    (
                        search in p.name.lower()
                        or search in p.sku.lower()
                        or search in p.description.lower()
                    )
                    and (
                        category is None
                        or p.category == category
                    )
                    and (
                        status is None
                        or p.status == status
                    )
                )
            ]

    @staticmethod
    def margin_analysis(
        product: RetailProduct,
    ) -> dict[str, Any]:
        profit = (
            product.selling_price
            - product.unit_cost
        )

        margin_pct = (
            profit / product.selling_price * 100
            if product.selling_price > 0
            else None
        )

        markup_pct = (
            profit / product.unit_cost * 100
            if product.unit_cost > 0
            else None
        )

        return {
            "sku": product.sku,
            "currency": product.currency,
            "unit_cost": str(product.unit_cost),
            "selling_price": str(product.selling_price),
            "gross_profit_per_unit": str(profit),
            "gross_margin_pct": (
                round(float(margin_pct), 2)
                if margin_pct is not None
                else None
            ),
            "markup_pct": (
                round(float(markup_pct), 2)
                if markup_pct is not None
                else None
            ),
        }

    def product_metrics(
        self,
        actor: ProductActor,
    ) -> dict[str, Any]:
        products = self.search_products(actor)

        return {
            "tenant_id": self.tenant_id,
            "total_products": len(products),
            "active_products": sum(
                p.status == ProductStatus.ACTIVE
                for p in products
            ),
            "draft_products": sum(
                p.status == ProductStatus.DRAFT
                for p in products
            ),
            "discontinued_products": sum(
                p.status == ProductStatus.DISCONTINUED
                for p in products
            ),
            "categories": sorted({
                p.category for p in products
            }),
        }

    def pending_events(
        self,
        actor: ProductActor,
    ) -> list[ProductOutboxEvent]:
        self._authorize(actor, self.WRITER_ROLES)

        with self._lock:
            return [
                copy.deepcopy(e)
                for e in self._outbox.values()
                if not e.delivered
            ]

    def mark_event_delivered(
        self,
        actor: ProductActor,
        event_id: str,
    ) -> None:
        self._authorize(actor, self.WRITER_ROLES)

        with self._lock:
            event = self._outbox.get(event_id)
            if event is None:
                raise KeyError("Outbox event not found")
            event.delivered = True

    def audit_events(
        self,
        actor: ProductActor,
        product_id: str,
    ) -> list[ProductAuditEvent]:
        self.get_product(actor, product_id)

        with self._lock:
            return [
                copy.deepcopy(e)
                for e in self._audit
                if e.product_id == product_id
            ]

    def export_json(
        self,
        actor: ProductActor,
        output_path: str | Path,
    ) -> Path:
        products = self.search_products(actor)

        path = Path(output_path)
        path.parent.mkdir(
            parents=True, exist_ok=True
        )

        path.write_text(
            json.dumps(
                [asdict(p) for p in products],
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
            action == "price_change"
            and reference == "APPROVED-DEMO"
        )

    service = RetailProductService(
        tenant_id="demo",
        approval_verifier=demo_approval,
    )

    manager = ProductActor(
        user_id="manager001",
        tenant_id="demo",
        roles=frozenset({"product_manager"}),
    )

    product = service.create_product(
        actor=manager,
        sku="SKU001",
        name="Smart Retail Sensor",
        description="IoT inventory monitoring device",
        category="Electronics",
        unit_cost="1200.00",
        selling_price="1800.00",
        supplier_id="SUP001",
    )

    product = service.change_status(
        manager,
        product.product_id,
        product.version,
        ProductStatus.ACTIVE,
    )

    print("Product:", product.name)
    print("Margin:", service.margin_analysis(product))
    print("Catalog:", service.product_metrics(manager))
