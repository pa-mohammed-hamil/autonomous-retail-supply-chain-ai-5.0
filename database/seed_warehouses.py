from __future__ import annotations

"""Planned module: seed warehouses. Implementation pending."""

"""
backend/database/seed_warehouses.py

Autonomous Retail Supply Chain AI 5.0

Deterministic warehouse master-data seeder.

Python 3.10+
SQLAlchemy 2.x
PostgreSQL

Features:
- Fictional warehouse records
- Deterministic warehouse IDs
- Location and capacity validation
- Tenant-scoped inserts
- Idempotent PostgreSQL operations
- Dry-run mode by default
- Explicit environment authorization
- Atomic transaction
- No deletion or overwriting

Requires:
    backend.database.engine
    backend.database.seed_demo

The target demo_warehouses table must
already exist through a migration.
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
    warehouses,
    require_demo_environment,
)


WAREHOUSE_ID_PATTERN = re.compile(
    r"^DEMO_WH[0-9]{3}$"
)


@dataclass(frozen=True)
class WarehouseSeedSpec:
    warehouse_id: str
    name: str
    location: str
    capacity: int

    def __post_init__(self) -> None:
        if not WAREHOUSE_ID_PATTERN.fullmatch(
            self.warehouse_id
        ):
            raise ValueError(
                "Invalid demo warehouse ID"
            )

        if not 1 <= len(self.name.strip()) <= 200:
            raise ValueError(
                "Invalid warehouse name"
            )

        if not 1 <= len(self.location.strip()) <= 200:
            raise ValueError(
                "Invalid warehouse location"
            )

        if (
            isinstance(self.capacity, bool)
            or not isinstance(self.capacity, int)
            or not 1 <= self.capacity <= 10_000_000
        ):
            raise ValueError(
                "Warehouse capacity must be "
                "a positive integer"
            )


@dataclass(frozen=True)
class WarehouseSeedResult:
    tenant_id: str
    planned: int
    inserted: int
    skipped: int
    dry_run: bool


WAREHOUSE_CATALOG: tuple[
    WarehouseSeedSpec, ...
] = (
    # Existing seed_demo.py warehouses.
    WarehouseSeedSpec(
        warehouse_id="DEMO_WH001",
        name="Demo Kochi Warehouse",
        location="Kochi, Kerala",
        capacity=10000,
    ),
    WarehouseSeedSpec(
        warehouse_id="DEMO_WH002",
        name="Demo Thrissur Warehouse",
        location="Thrissur, Kerala",
        capacity=7000,
    ),
    WarehouseSeedSpec(
        warehouse_id="DEMO_WH003",
        name="Demo Kozhikode Warehouse",
        location="Kozhikode, Kerala",
        capacity=8000,
    ),

    # Additional demo warehouse locations.
    WarehouseSeedSpec(
        warehouse_id="DEMO_WH004",
        name="Demo Thiruvananthapuram Warehouse",
        location="Thiruvananthapuram, Kerala",
        capacity=12000,
    ),
    WarehouseSeedSpec(
        warehouse_id="DEMO_WH005",
        name="Demo Palakkad Warehouse",
        location="Palakkad, Kerala",
        capacity=6000,
    ),
    WarehouseSeedSpec(
        warehouse_id="DEMO_WH006",
        name="Demo Kannur Warehouse",
        location="Kannur, Kerala",
        capacity=5500,
    ),
    WarehouseSeedSpec(
        warehouse_id="DEMO_WH007",
        name="Demo Bengaluru Distribution Centre",
        location="Bengaluru, Karnataka",
        capacity=18000,
    ),
    WarehouseSeedSpec(
        warehouse_id="DEMO_WH008",
        name="Demo Chennai Distribution Centre",
        location="Chennai, Tamil Nadu",
        capacity=15000,
    ),
)


def validate_catalog() -> None:
    ids = [
        warehouse.warehouse_id
        for warehouse in WAREHOUSE_CATALOG
    ]

    if len(ids) != len(set(ids)):
        raise ValueError(
            "Duplicate warehouse IDs"
        )


def build_warehouse_rows() -> list[
    dict[str, Any]
]:
    """
    Match the existing demo_warehouses
    table columns exactly.
    """
    return [
        {
            "id": warehouse.warehouse_id,
            "tenant_id": DEMO_TENANT_ID,
            "name": warehouse.name,
            "location": warehouse.location,
            "capacity": warehouse.capacity,
        }
        for warehouse in WAREHOUSE_CATALOG
    ]


def seed_warehouses(
    *,
    dry_run: bool = True,
) -> WarehouseSeedResult:
    validate_catalog()

    rows = build_warehouse_rows()

    if dry_run:
        return WarehouseSeedResult(
            tenant_id=DEMO_TENANT_ID,
            planned=len(rows),
            inserted=0,
            skipped=0,
            dry_run=True,
        )

    require_demo_environment()

    inserted = 0

    with database_transaction() as session:
        for row in rows:
            statement = (
                insert(warehouses)
                .values(**row)
                .on_conflict_do_nothing(
                    index_elements=["id"]
                )
                .returning(warehouses.c.id)
            )

            created_id = session.execute(
                statement
            ).scalar_one_or_none()

            if created_id is not None:
                inserted += 1

    return WarehouseSeedResult(
        tenant_id=DEMO_TENANT_ID,
        planned=len(rows),
        inserted=inserted,
        skipped=len(rows) - inserted,
        dry_run=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Retail AI warehouse seeder"
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Insert demo warehouses",
    )

    args = parser.parse_args()

    result = seed_warehouses(
        dry_run=not args.apply
    )

    print(
        f"Tenant: {result.tenant_id}"
    )
    print(
        f"Planned warehouses: {result.planned}"
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
