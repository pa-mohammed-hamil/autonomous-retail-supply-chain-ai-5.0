from __future__ import annotations

"""Planned module: seed demo. Implementation pending."""

"""
backend/database/seed_demo.py

Autonomous Retail Supply Chain AI 5.0

Safe demonstration-data seeder.

Requires:
    backend/database/engine.py
    SQLAlchemy 2.x
    PostgreSQL

Design:
- Blocks production environments
- Requires explicit seeding permission
- Uses deterministic demo IDs
- Restricts data to a demo tenant
- Uses one database transaction
- Avoids deleting existing records
- Uses PostgreSQL ON CONFLICT DO NOTHING
- Does not overwrite existing data

IMPORTANT:
This is a standalone demo-schema example.
Adapt table mappings to your actual
SQLAlchemy models before integration.
"""


import argparse
import os
import sys

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Column,
    select,
)
from sqlalchemy.dialects.postgresql import insert

from backend.database.engine import (
    database_transaction,
)


DEMO_TENANT_ID = "retail-demo"
DEMO_PREFIX = "DEMO_"

metadata = MetaData()


suppliers = Table(
    "demo_suppliers",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    Column("name", String(200), nullable=False),
    Column("status", String(32), nullable=False),
    Column("lead_time_days", Integer, nullable=False),
)

products = Table(
    "demo_products",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    Column("name", String(200), nullable=False),
    Column("category", String(100), nullable=False),
    Column("unit_price", Numeric(14, 2), nullable=False),
    Column("supplier_id", String(64), nullable=False),
)

warehouses = Table(
    "demo_warehouses",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    Column("name", String(200), nullable=False),
    Column("location", String(200), nullable=False),
    Column("capacity", Integer, nullable=False),
)

inventory = Table(
    "demo_inventory",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    Column("product_id", String(64), nullable=False),
    Column("warehouse_id", String(64), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("reorder_point", Integer, nullable=False),
)

sales = Table(
    "demo_sales",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    Column("product_id", String(64), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("total_amount", Numeric(14, 2), nullable=False),
    Column(
        "occurred_at",
        DateTime(timezone=True),
        nullable=False,
    ),
)

purchase_orders = Table(
    "demo_purchase_orders",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    Column("supplier_id", String(64), nullable=False),
    Column("product_id", String(64), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("status", String(32), nullable=False),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
    ),
)


@dataclass(frozen=True)
class SeedResult:
    tenant_id: str
    inserted: dict[str, int]
    skipped: dict[str, int]

    @property
    def total_inserted(self) -> int:
        return sum(self.inserted.values())

    @property
    def total_skipped(self) -> int:
        return sum(self.skipped.values())


def require_demo_environment() -> None:
    environment = os.getenv(
        "APP_ENV", ""
    ).strip().lower()

    allowed = {
        "development",
        "dev",
        "test",
        "testing",
        "demo",
        "local",
    }

    if environment not in allowed:
        raise RuntimeError(
            "Demo seeding is permitted only "
            "in an explicitly configured "
            "non-production environment."
        )

    if os.getenv(
        "ALLOW_DEMO_SEED", ""
    ).lower() != "true":
        raise RuntimeError(
            "Set ALLOW_DEMO_SEED=true "
            "to authorize demo seeding."
        )

    database_url = os.getenv(
        "DATABASE_URL", ""
    )

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is required"
        )

    # This is only a preliminary safeguard.
    # Production systems should additionally
    # verify the actual database identity.
    if environment in {"dev", "development", "local"}:
        print(
            "Warning: demo seeding is enabled "
            "for a development database."
        )


def build_demo_data() -> dict[str, list[dict[str, Any]]]:
    """
    Deterministic sample records.

    The fixed reference date makes the
    dataset reproducible across runs.
    """
    reference_time = datetime(
        2026, 10, 1, 9, 0,
        tzinfo=timezone.utc,
    )

    supplier_rows = [
        {
            "id": "DEMO_SUP001",
            "tenant_id": DEMO_TENANT_ID,
            "name": "Demo Kerala Wholesale",
            "status": "active",
            "lead_time_days": 3,
        },
        {
            "id": "DEMO_SUP002",
            "tenant_id": DEMO_TENANT_ID,
            "name": "Demo National Distributors",
            "status": "active",
            "lead_time_days": 7,
        },
        {
            "id": "DEMO_SUP003",
            "tenant_id": DEMO_TENANT_ID,
            "name": "Demo Regional Suppliers",
            "status": "active",
            "lead_time_days": 5,
        },
    ]

    product_specs = [
        ("Rice 5 kg", "Grocery", "350.00", "DEMO_SUP001"),
        ("Cooking Oil 1 L", "Grocery", "180.00", "DEMO_SUP001"),
        ("Milk 1 L", "Dairy", "65.00", "DEMO_SUP003"),
        ("Bread", "Bakery", "45.00", "DEMO_SUP003"),
        ("Soap Pack", "Personal Care", "120.00", "DEMO_SUP002"),
        ("Shampoo 500 ml", "Personal Care", "280.00", "DEMO_SUP002"),
        ("Tea 500 g", "Beverages", "210.00", "DEMO_SUP001"),
        ("Coffee 200 g", "Beverages", "240.00", "DEMO_SUP002"),
        ("Biscuits Pack", "Snacks", "40.00", "DEMO_SUP003"),
        ("Detergent 1 kg", "Household", "160.00", "DEMO_SUP002"),
    ]

    product_rows = []

    for index, (
        name,
        category,
        price,
        supplier_id,
    ) in enumerate(product_specs, start=1):
        product_rows.append(
            {
                "id": f"DEMO_PRD{index:03d}",
                "tenant_id": DEMO_TENANT_ID,
                "name": name,
                "category": category,
                "unit_price": Decimal(price),
                "supplier_id": supplier_id,
            }
        )

    warehouse_rows = [
        {
            "id": "DEMO_WH001",
            "tenant_id": DEMO_TENANT_ID,
            "name": "Demo Kochi Warehouse",
            "location": "Kochi, Kerala",
            "capacity": 10000,
        },
        {
            "id": "DEMO_WH002",
            "tenant_id": DEMO_TENANT_ID,
            "name": "Demo Thrissur Warehouse",
            "location": "Thrissur, Kerala",
            "capacity": 7000,
        },
        {
            "id": "DEMO_WH003",
            "tenant_id": DEMO_TENANT_ID,
            "name": "Demo Kozhikode Warehouse",
            "location": "Kozhikode, Kerala",
            "capacity": 8000,
        },
    ]

    inventory_rows = []

    for warehouse_index, warehouse in enumerate(
        warehouse_rows
    ):
        for product_index, product in enumerate(
            product_rows
        ):
            quantity = (
                30
                + (product_index * 17)
                + (warehouse_index * 11)
            )

            # Intentionally create low-stock
            # scenarios for AI demonstrations.
            if product_index in (2, 6):
                quantity = 8 + warehouse_index

            inventory_rows.append(
                {
                    "id": (
                        f"DEMO_INV"
                        f"{warehouse_index + 1:02d}"
                        f"{product_index + 1:03d}"
                    ),
                    "tenant_id": DEMO_TENANT_ID,
                    "product_id": product["id"],
                    "warehouse_id": warehouse["id"],
                    "quantity": quantity,
                    "reorder_point": 20,
                }
            )

    sales_rows = []

    for day in range(30):
        for product_index, product in enumerate(
            product_rows
        ):
            quantity = (
                2
                + (day % 5)
                + (product_index % 3)
            )

            sales_rows.append(
                {
                    "id": (
                        f"DEMO_SALE"
                        f"{day + 1:02d}"
                        f"{product_index + 1:03d}"
                    ),
                    "tenant_id": DEMO_TENANT_ID,
                    "product_id": product["id"],
                    "quantity": quantity,
                    "total_amount": (
                        product["unit_price"]
                        * quantity
                    ),
                    "occurred_at": (
                        reference_time
                        + timedelta(days=day)
                    ),
                }
            )

    purchase_order_rows = [
        {
            "id": "DEMO_PO001",
            "tenant_id": DEMO_TENANT_ID,
            "supplier_id": "DEMO_SUP003",
            "product_id": "DEMO_PRD003",
            "quantity": 150,
            "status": "pending",
            "created_at": reference_time,
        },
        {
            "id": "DEMO_PO002",
            "tenant_id": DEMO_TENANT_ID,
            "supplier_id": "DEMO_SUP001",
            "product_id": "DEMO_PRD007",
            "quantity": 100,
            "status": "approved",
            "created_at": (
                reference_time
                + timedelta(days=1)
            ),
        },
        {
            "id": "DEMO_PO003",
            "tenant_id": DEMO_TENANT_ID,
            "supplier_id": "DEMO_SUP002",
            "product_id": "DEMO_PRD005",
            "quantity": 200,
            "status": "received",
            "created_at": (
                reference_time
                + timedelta(days=2)
            ),
        },
    ]

    return {
        "suppliers": supplier_rows,
        "products": product_rows,
        "warehouses": warehouse_rows,
        "inventory": inventory_rows,
        "sales": sales_rows,
        "purchase_orders": purchase_order_rows,
    }


TABLES = {
    "suppliers": suppliers,
    "products": products,
    "warehouses": warehouses,
    "inventory": inventory,
    "sales": sales,
    "purchase_orders": purchase_orders,
}


def seed_demo_data(
    *,
    dry_run: bool = True,
) -> SeedResult:
    """
    Default behavior: preview only.

    Writes require:
    - dry_run=False
    - approved environment
    - ALLOW_DEMO_SEED=true
    - existing demo schema

    The seeder never creates tables.
    """
    data = build_demo_data()

    if dry_run:
        return SeedResult(
            tenant_id=DEMO_TENANT_ID,
            inserted={
                name: 0
                for name in data
            },
            skipped={
                name: len(rows)
                for name, rows in data.items()
            },
        )

    require_demo_environment()

    inserted_counts: dict[str, int] = {}
    skipped_counts: dict[str, int] = {}

    with database_transaction() as session:
        for name, rows in data.items():
            table = TABLES[name]

            inserted = 0

            for row in rows:
                statement = (
                    insert(table)
                    .values(**row)
                    .on_conflict_do_nothing(
                        index_elements=["id"]
                    )
                    .returning(table.c.id)
                )

                result = session.execute(
                    statement
                ).scalar_one_or_none()

                if result is not None:
                    inserted += 1

            inserted_counts[name] = inserted
            skipped_counts[name] = (
                len(rows) - inserted
            )

    return SeedResult(
        tenant_id=DEMO_TENANT_ID,
        inserted=inserted_counts,
        skipped=skipped_counts,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Retail AI demo data seeder"
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write demo data to the database",
    )

    args = parser.parse_args()

    result = seed_demo_data(
        dry_run=not args.apply
    )

    print(
        f"Tenant: {result.tenant_id}"
    )

    print(
        f"Inserted: {result.total_inserted}"
    )

    print(
        f"Skipped / previewed: "
        f"{result.total_skipped}"
    )

    for name in result.inserted:
        print(
            f"{name}: "
            f"inserted={result.inserted[name]}, "
            f"skipped={result.skipped[name]}"
        )


if __name__ == "__main__":
    main()
