from __future__ import annotations

"""Planned module: seed users. Implementation pending."""

"""
backend/database/seed_users.py

Autonomous Retail Supply Chain AI 5.0

Safe, deterministic user demo seeder.

Dependencies:
    SQLAlchemy >= 2.0
    psycopg >= 3

Features:
- Fictional demo identities
- Tenant-scoped user records
- Role-based access control data
- Warehouse assignments
- Disabled login by default
- Idempotent PostgreSQL inserts
- Explicit non-production authorization
- Dry-run mode
- Atomic transactions
- No default passwords or API tokens

Requires:
    backend.database.engine
    backend.database.seed_demo

Run schema migrations before applying.
"""


import argparse
from dataclasses import dataclass
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    select,
)
from sqlalchemy.dialects.postgresql import insert

from backend.database.engine import database_transaction
from backend.database.seed_demo import (
    DEMO_TENANT_ID,
    require_demo_environment,
    warehouses,
)


metadata = MetaData()

DEMO_ROLES = frozenset({
    "admin",
    "warehouse_manager",
    "inventory_manager",
    "procurement_manager",
    "logistics_manager",
    "analyst",
})

DEMO_WAREHOUSE_IDS = frozenset({
    "DEMO_WH001",
    "DEMO_WH002",
    "DEMO_WH003",
})


demo_users = Table(
    "demo_users",
    metadata,
    Column(
        "tenant_id",
        String(64),
        primary_key=True,
    ),
    Column(
        "id",
        String(64),
        primary_key=True,
    ),
    Column(
        "display_name",
        String(150),
        nullable=False,
    ),
    Column(
        "email",
        String(254),
        nullable=False,
    ),
    Column(
        "role",
        String(64),
        nullable=False,
    ),
    Column(
        "status",
        String(32),
        nullable=False,
    ),
    Column(
        "login_enabled",
        Boolean,
        nullable=False,
        default=False,
    ),
    UniqueConstraint(
        "tenant_id",
        "email",
        name="uq_demo_user_tenant_email",
    ),
    CheckConstraint(
        "status IN ('active', 'suspended', 'disabled')",
        name="ck_demo_user_status",
    ),
    CheckConstraint(
        "login_enabled = false",
        name="ck_demo_user_login_disabled",
    ),
)

demo_user_warehouses = Table(
    "demo_user_warehouses",
    metadata,
    Column(
        "tenant_id",
        String(64),
        primary_key=True,
    ),
    Column(
        "user_id",
        String(64),
        primary_key=True,
    ),
    Column(
        "warehouse_id",
        String(64),
        primary_key=True,
    ),
    ForeignKeyConstraint(
        ["tenant_id", "user_id"],
        [
            "demo_users.tenant_id",
            "demo_users.id",
        ],
        name="fk_demo_assignment_user",
    ),
)


@dataclass(frozen=True)
class DemoUserSpec:
    user_id: str
    display_name: str
    email: str
    role: str
    warehouse_ids: tuple[str, ...] = ()
    status: str = "active"

    def __post_init__(self) -> None:
        if not self.user_id.startswith("DEMO_USR"):
            raise ValueError("Invalid demo user ID")

        if self.role not in DEMO_ROLES:
            raise ValueError("Unsupported demo role")

        if self.status not in {
            "active", "suspended", "disabled"
        }:
            raise ValueError("Invalid user status")

        if (
            not self.email.endswith("@example.com")
            or len(self.email) > 254
        ):
            raise ValueError(
                "Use fictional example.com emails"
            )

        if not self.display_name.strip():
            raise ValueError("Display name is required")

        if len(set(self.warehouse_ids)) != len(
            self.warehouse_ids
        ):
            raise ValueError(
                "Duplicate warehouse assignments"
            )

        if not set(self.warehouse_ids).issubset(
            DEMO_WAREHOUSE_IDS
        ):
            raise ValueError(
                "Unknown demo warehouse"
            )


USER_CATALOG = (
    DemoUserSpec(
        "DEMO_USR001",
        "Demo System Administrator",
        "admin@example.com",
        "admin",
    ),
    DemoUserSpec(
        "DEMO_USR002",
        "Demo Kochi Warehouse Manager",
        "warehouse.kochi@example.com",
        "warehouse_manager",
        ("DEMO_WH001",),
    ),
    DemoUserSpec(
        "DEMO_USR003",
        "Demo Thrissur Warehouse Manager",
        "warehouse.thrissur@example.com",
        "warehouse_manager",
        ("DEMO_WH002",),
    ),
    DemoUserSpec(
        "DEMO_USR004",
        "Demo Inventory Manager",
        "inventory@example.com",
        "inventory_manager",
        (
            "DEMO_WH001",
            "DEMO_WH002",
            "DEMO_WH003",
        ),
    ),
    DemoUserSpec(
        "DEMO_USR005",
        "Demo Procurement Manager",
        "procurement@example.com",
        "procurement_manager",
    ),
    DemoUserSpec(
        "DEMO_USR006",
        "Demo Logistics Manager",
        "logistics@example.com",
        "logistics_manager",
        (
            "DEMO_WH001",
            "DEMO_WH003",
        ),
    ),
    DemoUserSpec(
        "DEMO_USR007",
        "Demo Retail Analyst",
        "analyst@example.com",
        "analyst",
    ),
    DemoUserSpec(
        "DEMO_USR008",
        "Demo Suspended Analyst",
        "suspended.analyst@example.com",
        "analyst",
        status="suspended",
    ),
)


@dataclass(frozen=True)
class UserSeedResult:
    tenant_id: str
    planned_users: int
    inserted_users: int
    skipped_users: int
    planned_assignments: int
    inserted_assignments: int
    skipped_assignments: int
    dry_run: bool


def build_user_rows() -> list[dict[str, Any]]:
    return [
        {
            "tenant_id": DEMO_TENANT_ID,
            "id": user.user_id,
            "display_name": user.display_name,
            "email": user.email,
            "role": user.role,
            "status": user.status,
            "login_enabled": False,
        }
        for user in USER_CATALOG
    ]


def build_assignment_rows() -> list[dict[str, str]]:
    return [
        {
            "tenant_id": DEMO_TENANT_ID,
            "user_id": user.user_id,
            "warehouse_id": warehouse_id,
        }
        for user in USER_CATALOG
        for warehouse_id in user.warehouse_ids
    ]


def validate_catalog() -> None:
    user_ids = [u.user_id for u in USER_CATALOG]
    emails = [u.email for u in USER_CATALOG]

    if len(user_ids) != len(set(user_ids)):
        raise ValueError("Duplicate user IDs")

    if len(emails) != len(set(emails)):
        raise ValueError("Duplicate user emails")


def validate_warehouses(
    session,
    assignment_rows: list[dict[str, str]],
) -> None:
    required = {
        row["warehouse_id"]
        for row in assignment_rows
    }

    existing = set(
        session.execute(
            select(warehouses.c.id).where(
                warehouses.c.tenant_id
                == DEMO_TENANT_ID,
                warehouses.c.id.in_(required),
            )
        ).scalars()
    )

    missing = required - existing

    if missing:
        raise RuntimeError(
            "Missing demo warehouses: "
            + ", ".join(sorted(missing))
            + ". Seed warehouses first."
        )


def seed_users(
    *,
    dry_run: bool = True,
) -> UserSeedResult:
    validate_catalog()

    user_rows = build_user_rows()
    assignment_rows = build_assignment_rows()

    if dry_run:
        return UserSeedResult(
            tenant_id=DEMO_TENANT_ID,
            planned_users=len(user_rows),
            inserted_users=0,
            skipped_users=0,
            planned_assignments=len(assignment_rows),
            inserted_assignments=0,
            skipped_assignments=0,
            dry_run=True,
        )

    require_demo_environment()

    inserted_users = 0
    inserted_assignments = 0

    with database_transaction() as session:
        validate_warehouses(
            session,
            assignment_rows,
        )

        for row in user_rows:
            stmt = (
                insert(demo_users)
                .values(**row)
                .on_conflict_do_nothing(
                    index_elements=[
                        "tenant_id",
                        "id",
                    ]
                )
                .returning(demo_users.c.id)
            )

            created = session.execute(
                stmt
            ).scalar_one_or_none()

            if created is not None:
                inserted_users += 1

        for row in assignment_rows:
            stmt = (
                insert(demo_user_warehouses)
                .values(**row)
                .on_conflict_do_nothing(
                    index_elements=[
                        "tenant_id",
                        "user_id",
                        "warehouse_id",
                    ]
                )
                .returning(
                    demo_user_warehouses.c.user_id
                )
            )

            created = session.execute(
                stmt
            ).scalar_one_or_none()

            if created is not None:
                inserted_assignments += 1

    return UserSeedResult(
        tenant_id=DEMO_TENANT_ID,
        planned_users=len(user_rows),
        inserted_users=inserted_users,
        skipped_users=(
            len(user_rows) - inserted_users
        ),
        planned_assignments=len(assignment_rows),
        inserted_assignments=inserted_assignments,
        skipped_assignments=(
            len(assignment_rows)
            - inserted_assignments
        ),
        dry_run=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed fictional retail users"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Insert demo users and assignments",
    )

    args = parser.parse_args()

    result = seed_users(
        dry_run=not args.apply
    )

    print(f"Tenant: {result.tenant_id}")
    print(f"Planned users: {result.planned_users}")
    print(f"Inserted users: {result.inserted_users}")
    print(f"Skipped users: {result.skipped_users}")
    print(
        "Planned warehouse assignments: "
        f"{result.planned_assignments}"
    )
    print(
        "Inserted warehouse assignments: "
        f"{result.inserted_assignments}"
    )
    print(
        "Skipped warehouse assignments: "
        f"{result.skipped_assignments}"
    )
    print(f"Dry run: {result.dry_run}")


if __name__ == "__main__":
    main()
