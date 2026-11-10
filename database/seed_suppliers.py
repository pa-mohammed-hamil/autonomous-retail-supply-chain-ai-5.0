from __future__ import annotations

"""Planned module: seed suppliers. Implementation pending."""

"""
backend/database/seed_suppliers.py

Autonomous Retail Supply Chain AI 5.0

Supplier master-data demo seeder.

Python 3.10+
SQLAlchemy 2.x
PostgreSQL

Features:
- Deterministic supplier records
- Supplier lead-time information
- Supplier operating status
- Tenant-scoped demo data
- Repeat-safe inserts
- Dry-run mode by default
- Explicit environment authorization
- Atomic database transaction
- Existing-record preservation

Requires:
    backend.database.engine
    backend.database.seed_demo

This module does not create database tables.
"""


import argparse
import re

from dataclasses import dataclass
from typing import Any

from sqlalchemy.dialects.postgresql import insert

from backend.database.engine import (
    database_transaction,
)

from backend.database.seed_demo import (
    DEMO_TENANT_ID,
    suppliers,
    require_demo_environment,
)


SAFE_ID = re.compile(r"^DEMO_SUP[0-9]{3}$")

ALLOWED_STATUSES = frozenset(
    {
        "active",
        "suspended",
        "inactive",
    }
)


@dataclass(frozen=True)
class SupplierSeedSpec:
    supplier_id: str
    name: str
    status: str
    lead_time_days: int

    def __post_init__(self) -> None:
        if not SAFE_ID.fullmatch(
            self.supplier_id
        ):
            raise ValueError(
                "Invalid demo supplier ID"
            )

        if not 1 <= len(self.name.strip()) <= 200:
            raise ValueError(
                "Invalid supplier name"
            )

        if self.status not in ALLOWED_STATUSES:
            raise ValueError(
                "Invalid supplier status"
            )

        if (
            isinstance(self.lead_time_days, bool)
            or not isinstance(
                self.lead_time_days, int
            )
            or not 0 <= self.lead_time_days <= 365
        ):
            raise ValueError(
                "Invalid supplier lead time"
            )


@dataclass(frozen=True)
class SupplierSeedResult:
    tenant_id: str
    planned: int
    inserted: int
    skipped: int
    dry_run: bool


SUPPLIER_CATALOG: tuple[SupplierSeedSpec, ...] = (
    # IDs 001-003 intentionally match
    # seed_demo.py and seed_products.py.
    SupplierSeedSpec(
        "DEMO_SUP001",
        "Demo Kerala Wholesale",
        "active",
        3,
    ),
    SupplierSeedSpec(
        "DEMO_SUP002",
        "Demo National Distributors",
        "active",
        7,
    ),
    SupplierSeedSpec(
        "DEMO_SUP003",
        "Demo Regional Suppliers",
        "active",
        5,
    ),
    SupplierSeedSpec(
        "DEMO_SUP004",
        "Demo Fresh Food Logistics",
        "active",
        2,
    ),
    SupplierSeedSpec(
        "DEMO_SUP005",
        "Demo Electronics Distribution",
        "active",
        9,
    ),
    SupplierSeedSpec(
        "DEMO_SUP006",
        "Demo Household Products Supply",
        "active",
        6,
    ),
    SupplierSeedSpec(
        "DEMO_SUP007",
        "Demo FMCG Distribution",
        "active",
        4,
    ),
    SupplierSeedSpec(
        "DEMO_SUP008",
        "Demo Dairy and Bakery Supply",
        "active",
        1,
    ),
    SupplierSeedSpec(
        "DEMO_SUP009",
        "Demo Seasonal Goods Supply",
        "suspended",
        12,
    ),
    SupplierSeedSpec(
        "DEMO_SUP010",
        "Demo International Imports",
        "inactive",
        21,
    ),
)


def build_supplier_rows() -> list[dict[str, Any]]:
    """
    Convert catalog entries to rows
    matching the demo_suppliers schema.
    """
    return [
        {
            "id": spec.supplier_id,
            "tenant_id": DEMO_TENANT_ID,
            "name": spec.name,
            "status": spec.status,
            "lead_time_days": spec.lead_time_days,
        }
        for spec in SUPPLIER_CATALOG
    ]


def validate_catalog() -> None:
    supplier_ids = [
        item.supplier_id
        for item in SUPPLIER_CATALOG
    ]

    if len(supplier_ids) != len(set(supplier_ids)):
        raise ValueError(
            "Duplicate supplier IDs in seed catalog"
        )


def seed_suppliers(
    *,
    dry_run: bool = True,
) -> SupplierSeedResult:
    validate_catalog()

    rows = build_supplier_rows()

    if dry_run:
        return SupplierSeedResult(
            tenant_id=DEMO_TENANT_ID,
            planned=len(rows),
            inserted=0,
            skipped=0,
            dry_run=True,
        )

    # Fail closed unless the environment
    # explicitly permits demo data writes.
    require_demo_environment()

    inserted = 0

    with database_transaction() as session:
        for row in rows:
            statement = (
                insert(suppliers)
                .values(**row)
                .on_conflict_do_nothing(
                    index_elements=["id"]
                )
                .returning(suppliers.c.id)
            )

            created_id = session.execute(
                statement
            ).scalar_one_or_none()

            if created_id is not None:
                inserted += 1

    return SupplierSeedResult(
        tenant_id=DEMO_TENANT_ID,
        planned=len(rows),
        inserted=inserted,
        skipped=len(rows) - inserted,
        dry_run=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Retail AI supplier demo seeder"
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Insert supplier demo records",
    )

    args = parser.parse_args()

    result = seed_suppliers(
        dry_run=not args.apply
    )

    print(f"Tenant: {result.tenant_id}")
    print(f"Planned: {result.planned}")
    print(f"Inserted: {result.inserted}")
    print(f"Skipped: {result.skipped}")
    print(f"Dry run: {result.dry_run}")


if __name__ == "__main__":
    main()
