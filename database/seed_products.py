from __future__ import annotations

"""Planned module: seed products. Implementation pending."""

"""
backend/database/seed_products.py

Autonomous Retail Supply Chain AI 5.0

Product catalog demo seeder.

Python 3.10+
SQLAlchemy 2.x
PostgreSQL

Features:
- Deterministic product records
- Retail category coverage
- Supplier assignments
- Decimal financial values
- Duplicate-safe PostgreSQL inserts
- Tenant-scoped seed data
- Dry-run mode by default
- Production environment guard
- Transactional writes
- Repeatable results

Requires:
- backend/database/engine.py
- backend/database/seed_demo.py
- Existing migrated demo_products table
- Existing demo supplier records

This seeder does not create tables.
"""


import argparse
import logging
import os

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from backend.database.engine import (
    database_transaction,
)

from backend.database.seed_demo import (
    DEMO_TENANT_ID,
    products,
    suppliers,
    require_demo_environment,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProductSeedSpec:
    name: str
    category: str
    selling_price: Decimal
    supplier_id: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError(
                "Product name is required"
            )

        if not self.category.strip():
            raise ValueError(
                "Product category is required"
            )

        if (
            not self.selling_price.is_finite()
            or self.selling_price < 0
        ):
            raise ValueError(
                "Invalid selling price"
            )

        if not self.supplier_id:
            raise ValueError(
                "Supplier ID is required"
            )


@dataclass(frozen=True)
class ProductSeedResult:
    tenant_id: str
    planned: int
    inserted: int
    skipped: int
    dry_run: bool


PRODUCT_CATALOG: tuple[ProductSeedSpec, ...] = (
    # Grocery
    ProductSeedSpec(
        "Rice 5 kg",
        "Grocery",
        Decimal("350.00"),
        "DEMO_SUP001",
    ),
    ProductSeedSpec(
        "Wheat Flour 5 kg",
        "Grocery",
        Decimal("280.00"),
        "DEMO_SUP001",
    ),
    ProductSeedSpec(
        "Sugar 1 kg",
        "Grocery",
        Decimal("55.00"),
        "DEMO_SUP001",
    ),
    ProductSeedSpec(
        "Cooking Oil 1 L",
        "Grocery",
        Decimal("180.00"),
        "DEMO_SUP001",
    ),
    ProductSeedSpec(
        "Salt 1 kg",
        "Grocery",
        Decimal("25.00"),
        "DEMO_SUP001",
    ),

    # Dairy
    ProductSeedSpec(
        "Milk 1 L",
        "Dairy",
        Decimal("65.00"),
        "DEMO_SUP003",
    ),
    ProductSeedSpec(
        "Curd 500 g",
        "Dairy",
        Decimal("45.00"),
        "DEMO_SUP003",
    ),
    ProductSeedSpec(
        "Butter 200 g",
        "Dairy",
        Decimal("130.00"),
        "DEMO_SUP003",
    ),
    ProductSeedSpec(
        "Cheese 200 g",
        "Dairy",
        Decimal("160.00"),
        "DEMO_SUP003",
    ),

    # Bakery
    ProductSeedSpec(
        "Bread",
        "Bakery",
        Decimal("45.00"),
        "DEMO_SUP003",
    ),
    ProductSeedSpec(
        "Bun Pack",
        "Bakery",
        Decimal("60.00"),
        "DEMO_SUP003",
    ),
    ProductSeedSpec(
        "Cake 500 g",
        "Bakery",
        Decimal("280.00"),
        "DEMO_SUP003",
    ),

    # Beverages
    ProductSeedSpec(
        "Tea 500 g",
        "Beverages",
        Decimal("210.00"),
        "DEMO_SUP001",
    ),
    ProductSeedSpec(
        "Coffee 200 g",
        "Beverages",
        Decimal("240.00"),
        "DEMO_SUP002",
    ),
    ProductSeedSpec(
        "Fruit Juice 1 L",
        "Beverages",
        Decimal("120.00"),
        "DEMO_SUP003",
    ),
    ProductSeedSpec(
        "Mineral Water 1 L",
        "Beverages",
        Decimal("25.00"),
        "DEMO_SUP003",
    ),

    # Snacks
    ProductSeedSpec(
        "Biscuits Pack",
        "Snacks",
        Decimal("40.00"),
        "DEMO_SUP003",
    ),
    ProductSeedSpec(
        "Potato Chips",
        "Snacks",
        Decimal("50.00"),
        "DEMO_SUP003",
    ),
    ProductSeedSpec(
        "Chocolate Bar",
        "Snacks",
        Decimal("80.00"),
        "DEMO_SUP002",
    ),
    ProductSeedSpec(
        "Mixed Nuts 250 g",
        "Snacks",
        Decimal("320.00"),
        "DEMO_SUP002",
    ),

    # Personal Care
    ProductSeedSpec(
        "Soap Pack",
        "Personal Care",
        Decimal("120.00"),
        "DEMO_SUP002",
    ),
    ProductSeedSpec(
        "Shampoo 500 ml",
        "Personal Care",
        Decimal("280.00"),
        "DEMO_SUP002",
    ),
    ProductSeedSpec(
        "Toothpaste 150 g",
        "Personal Care",
        Decimal("110.00"),
        "DEMO_SUP002",
    ),
    ProductSeedSpec(
        "Hand Wash 250 ml",
        "Personal Care",
        Decimal("95.00"),
        "DEMO_SUP002",
    ),

    # Household
    ProductSeedSpec(
        "Detergent 1 kg",
        "Household",
        Decimal("160.00"),
        "DEMO_SUP002",
    ),
    ProductSeedSpec(
        "Dishwash Liquid 500 ml",
        "Household",
        Decimal("120.00"),
        "DEMO_SUP002",
    ),
    ProductSeedSpec(
        "Floor Cleaner 1 L",
        "Household",
        Decimal("180.00"),
        "DEMO_SUP002",
    ),
    ProductSeedSpec(
        "Tissue Box",
        "Household",
        Decimal("90.00"),
        "DEMO_SUP002",
    ),

    # Electronics
    ProductSeedSpec(
        "USB-C Cable",
        "Electronics",
        Decimal("299.00"),
        "DEMO_SUP002",
    ),
    ProductSeedSpec(
        "LED Bulb 9 W",
        "Electronics",
        Decimal("149.00"),
        "DEMO_SUP002",
    ),
    ProductSeedSpec(
        "Power Bank",
        "Electronics",
        Decimal("1299.00"),
        "DEMO_SUP002",
    ),
    ProductSeedSpec(
        "Wireless Mouse",
        "Electronics",
        Decimal("699.00"),
        "DEMO_SUP002",
    ),
)


def build_product_rows() -> list[dict[str, Any]]:
    """
    Convert product specifications to the
    existing demo_products schema.

    Cost price and reorder thresholds are
    not stored because the current demo
    table does not contain those columns.
    """
    rows: list[dict[str, Any]] = []

    for index, spec in enumerate(
        PRODUCT_CATALOG,
        start=1,
    ):
        rows.append(
            {
                "id": f"DEMO_CAT{index:04d}",
                "tenant_id": DEMO_TENANT_ID,
                "name": spec.name,
                "category": spec.category,
                "unit_price": spec.selling_price.quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP,
                ),
                "supplier_id": spec.supplier_id,
            }
        )

    return rows


def validate_supplier_references(
    session,
    rows: list[dict[str, Any]],
) -> None:
    """
    Verify that all referenced suppliers
    exist in the same demo tenant.
    """
    required_ids = {
        row["supplier_id"]
        for row in rows
    }

    existing_ids = set(
        session.execute(
            select(suppliers.c.id).where(
                suppliers.c.tenant_id
                == DEMO_TENANT_ID,
                suppliers.c.id.in_(
                    required_ids
                ),
            )
        ).scalars()
    )

    missing = required_ids - existing_ids

    if missing:
        raise RuntimeError(
            "Missing demo suppliers: "
            + ", ".join(sorted(missing))
            + ". Run seed_demo.py first."
        )


def seed_products(
    *,
    dry_run: bool = True,
) -> ProductSeedResult:
    rows = build_product_rows()

    if dry_run:
        return ProductSeedResult(
            tenant_id=DEMO_TENANT_ID,
            planned=len(rows),
            inserted=0,
            skipped=0,
            dry_run=True,
        )

    require_demo_environment()

    inserted = 0

    with database_transaction() as session:
        validate_supplier_references(
            session,
            rows,
        )

        for row in rows:
            statement = (
                insert(products)
                .values(**row)
                .on_conflict_do_nothing(
                    index_elements=["id"]
                )
                .returning(products.c.id)
            )

            result = session.execute(
                statement
            ).scalar_one_or_none()

            if result is not None:
                inserted += 1

    return ProductSeedResult(
        tenant_id=DEMO_TENANT_ID,
        planned=len(rows),
        inserted=inserted,
        skipped=len(rows) - inserted,
        dry_run=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Retail AI product catalog seeder"
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Insert demo products",
    )

    args = parser.parse_args()

    result = seed_products(
        dry_run=not args.apply
    )

    print(
        f"Tenant: {result.tenant_id}"
    )
    print(
        f"Planned products: {result.planned}"
    )
    print(
        f"Inserted: {result.inserted}"
    )
    print(
        f"Skipped: {result.skipped}"
    )
    print(
        f"Dry run: {result.dry_run}"
    )


if __name__ == "__main__":
    main()
