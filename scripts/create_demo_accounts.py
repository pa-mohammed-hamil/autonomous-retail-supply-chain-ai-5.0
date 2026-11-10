"""Planned module: create demo accounts. Implementation pending."""

#!/usr/bin/env python3
"""
SupplyChainAI — Demo Account Creator

File: scripts/create_demo_accounts.py

Features:
- Creates demonstration user accounts
- Role-based access control (RBAC)
- Secure password hashing using bcrypt
- Random passwords for each account
- SQLAlchemy database integration
- SQLite and PostgreSQL support
- Duplicate email protection
- Idempotent account creation
- Development/test environment restriction
- Optional JSON credentials export
- Optional account listing
- No hardcoded default passwords

Install:
    pip install sqlalchemy "passlib[bcrypt]" "bcrypt<4"

Examples:
    python scripts/create_demo_accounts.py --init
    python scripts/create_demo_accounts.py --init --show-credentials
    python scripts/create_demo_accounts.py --list
    python scripts/create_demo_accounts.py --init --export-credentials

Environment:
    APP_ENV=development
    DATABASE_URL=sqlite:///./data/supplychain_demo.db

IMPORTANT:
This script uses a standalone demonstration user table.
It does not automatically integrate with an existing
backend.users SQLAlchemy model or JWT authentication flow.

Adapt the table and password verification to your
existing backend before using these accounts for login.
"""

import argparse
import json
import os
import secrets
import sys

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    create_engine,
    select
)

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import (
    declarative_base,
    sessionmaker
)

try:
    from passlib.context import CryptContext
except ImportError:
    print(
        "Missing dependency. Install:\n"
        'pip install sqlalchemy "passlib[bcrypt]" "bcrypt<4"'
    )
    sys.exit(1)


# ============================================================
# 1. PROJECT CONFIGURATION
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

APP_ENV = os.getenv(
    "APP_ENV",
    "development"
).strip().lower()

ALLOWED_ENVIRONMENTS = {
    "development",
    "dev",
    "testing",
    "test",
    "local"
}

if APP_ENV not in ALLOWED_ENVIRONMENTS:
    raise RuntimeError(
        "Demo account creation is disabled outside "
        "development and testing environments."
    )

DEFAULT_DB = (
    f"sqlite:///{DATA_DIR / 'supplychain_demo.db'}"
)

DATABASE_URL = os.getenv(
    "DEMO_DATABASE_URL",
    DEFAULT_DB
)

# Never use the production database by accident.
# Set DEMO_DATABASE_URL explicitly for a separate
# PostgreSQL demonstration database.

if DATABASE_URL.startswith(
    "postgresql://"
):
    DATABASE_URL = DATABASE_URL.replace(
        "postgresql://",
        "postgresql+psycopg://",
        1
    )

PASSWORD_CONTEXT = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)

# ============================================================
# 2. DATABASE
# ============================================================

Base = declarative_base()

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False
)


# ============================================================
# 3. USER MODEL
# ============================================================

class DemoUser(Base):
    __tablename__ = "demo_users"

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True
    )

    full_name = Column(
        String(150),
        nullable=False
    )

    email = Column(
        String(255),
        unique=True,
        index=True,
        nullable=False
    )

    hashed_password = Column(
        String(255),
        nullable=False
    )

    role = Column(
        String(80),
        nullable=False
    )

    department = Column(
        String(100),
        nullable=False
    )

    is_active = Column(
        Boolean,
        default=True,
        nullable=False
    )

    is_demo = Column(
        Boolean,
        default=True,
        nullable=False
    )

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )


# ============================================================
# 4. ROLE DEFINITIONS
# ============================================================

ROLE_PERMISSIONS = {
    "admin": [
        "dashboard:read",
        "users:manage",
        "inventory:manage",
        "suppliers:manage",
        "logistics:manage",
        "orders:manage",
        "reports:read",
        "ai:manage",
        "settings:manage",
        "audit:read"
    ],
    "manager": [
        "dashboard:read",
        "inventory:read",
        "suppliers:read",
        "logistics:read",
        "orders:read",
        "reports:read",
        "ai:read"
    ],
    "warehouse_manager": [
        "dashboard:read",
        "warehouse:manage",
        "inventory:manage",
        "orders:read",
        "reports:read"
    ],
    "inventory_manager": [
        "dashboard:read",
        "inventory:manage",
        "replenishment:manage",
        "products:read",
        "reports:read"
    ],
    "supplier_manager": [
        "dashboard:read",
        "suppliers:manage",
        "purchase_orders:manage",
        "supplier_risk:read",
        "reports:read"
    ],
    "logistics_manager": [
        "dashboard:read",
        "logistics:manage",
        "deliveries:manage",
        "fleet:manage",
        "reports:read"
    ],
    "data_analyst": [
        "dashboard:read",
        "analytics:read",
        "reports:read",
        "forecasting:read"
    ],
    "ai_engineer": [
        "dashboard:read",
        "ai:manage",
        "models:manage",
        "evaluations:read",
        "observability:read"
    ],
    "employee": [
        "dashboard:read",
        "tasks:read",
        "tasks:update",
        "notifications:read"
    ],
    "viewer": [
        "dashboard:read",
        "reports:read"
    ]
}


# ============================================================
# 5. DEMO USERS
# ============================================================

DEMO_ACCOUNTS = [
    {
        "full_name": "Demo Administrator",
        "email": "admin@demo.supplychain.test",
        "role": "admin",
        "department": "Administration"
    },
    {
        "full_name": "Demo Operations Manager",
        "email": "manager@demo.supplychain.test",
        "role": "manager",
        "department": "Operations"
    },
    {
        "full_name": "Demo Warehouse Manager",
        "email": "warehouse@demo.supplychain.test",
        "role": "warehouse_manager",
        "department": "Warehouse"
    },
    {
        "full_name": "Demo Inventory Manager",
        "email": "inventory@demo.supplychain.test",
        "role": "inventory_manager",
        "department": "Inventory"
    },
    {
        "full_name": "Demo Supplier Manager",
        "email": "supplier@demo.supplychain.test",
        "role": "supplier_manager",
        "department": "Procurement"
    },
    {
        "full_name": "Demo Logistics Manager",
        "email": "logistics@demo.supplychain.test",
        "role": "logistics_manager",
        "department": "Logistics"
    },
    {
        "full_name": "Demo Data Analyst",
        "email": "analyst@demo.supplychain.test",
        "role": "data_analyst",
        "department": "Analytics"
    },
    {
        "full_name": "Demo AI Engineer",
        "email": "ai@demo.supplychain.test",
        "role": "ai_engineer",
        "department": "AI Engineering"
    },
    {
        "full_name": "Demo Employee",
        "email": "employee@demo.supplychain.test",
        "role": "employee",
        "department": "Operations"
    },
    {
        "full_name": "Demo Viewer",
        "email": "viewer@demo.supplychain.test",
        "role": "viewer",
        "department": "General"
    }
]


# ============================================================
# 6. PASSWORD GENERATION
# ============================================================

def generate_password(length=24):
    alphabet = (
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789"
        "!@#$%^&*"
    )

    return "".join(
        secrets.choice(alphabet)
        for _ in range(length)
    )


def hash_password(password):
    return PASSWORD_CONTEXT.hash(password)


def verify_password(password, hashed_password):
    return PASSWORD_CONTEXT.verify(
        password,
        hashed_password
    )


# ============================================================
# 7. INITIALIZE DATABASE
# ============================================================

def initialize_database():
    Base.metadata.create_all(
        bind=engine
    )

    print("[OK] Demo database initialized.")


# ============================================================
# 8. CREATE ACCOUNTS
# ============================================================

def create_demo_accounts(
    show_credentials=False,
    export_credentials=False
):
    initialize_database()

    created = []
    skipped = []

    with SessionLocal() as session:
        for account in DEMO_ACCOUNTS:
            existing = session.scalar(
                select(DemoUser).where(
                    DemoUser.email == account["email"]
                )
            )

            if existing:
                skipped.append(account["email"])
                continue

            password = generate_password()

            user = DemoUser(
                full_name=account["full_name"],
                email=account["email"],
                hashed_password=hash_password(
                    password
                ),
                role=account["role"],
                department=account["department"],
                is_active=True,
                is_demo=True
            )

            session.add(user)

            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                skipped.append(account["email"])
                continue

            created.append({
                "email": account["email"],
                "password": password,
                "role": account["role"],
                "department": account["department"]
            })

            print(
                f"[CREATED] {account['email']} "
                f"({account['role']})"
            )

    print("\n" + "=" * 65)
    print("DEMO ACCOUNT CREATION SUMMARY")
    print("=" * 65)
    print(f"Created: {len(created)}")
    print(f"Already existed: {len(skipped)}")

    if show_credentials and created:
        print("\nNEW DEMO CREDENTIALS")
        print("-" * 65)

        for account in created:
            print(
                f"Email: {account['email']}\n"
                f"Password: {account['password']}\n"
                f"Role: {account['role']}\n"
            )

    if export_credentials and created:
        export_path = (
            DATA_DIR / "demo_credentials.json"
        )

        if export_path.exists():
            raise FileExistsError(
                f"Refusing to overwrite {export_path}"
            )

        # Exclusive creation avoids replacing existing
        # credentials. Use only on a trusted local machine.
        fd = os.open(
            export_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600
        )

        with os.fdopen(
            fd,
            "w",
            encoding="utf-8"
        ) as file:
            json.dump(
                {
                    "environment": APP_ENV,
                    "generated_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "accounts": created
                },
                file,
                indent=2
            )

        print(
            f"\n[EXPORTED] {export_path}"
        )

        print(
            "WARNING: This file contains plaintext "
            "demo passwords. Do not commit it to Git."
        )

    if created and not (
        show_credentials or export_credentials
    ):
        print(
            "\nWARNING: New passwords were not displayed "
            "or exported. Rerunning the script will not "
            "recover them."
        )

    return created


# ============================================================
# 9. LIST DEMO ACCOUNTS
# ============================================================

def list_demo_accounts():
    initialize_database()

    with SessionLocal() as session:
        users = session.scalars(
            select(DemoUser)
            .where(DemoUser.is_demo.is_(True))
            .order_by(DemoUser.id)
        ).all()

        if not users:
            print("No demo accounts found.")
            return

        print("\nDEMO ACCOUNTS")
        print("=" * 75)

        for user in users:
            print(
                f"{user.id:>3} | "
                f"{user.email:<38} | "
                f"{user.role:<20} | "
                f"{'Active' if user.is_active else 'Disabled'}"
            )

        print(f"\nTotal: {len(users)}")


# ============================================================
# 10. SHOW ROLE PERMISSIONS
# ============================================================

def list_role_permissions():
    print("\nROLE PERMISSIONS")
    print("=" * 65)

    for role, permissions in ROLE_PERMISSIONS.items():
        print(f"\n{role.upper()}")

        for permission in permissions:
            print(f"  - {permission}")


# ============================================================
# 11. CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "SupplyChainAI development-only "
            "demo account creator"
        )
    )

    parser.add_argument(
        "--init",
        action="store_true",
        help="Create demo accounts"
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List existing demo accounts"
    )

    parser.add_argument(
        "--roles",
        action="store_true",
        help="Show role permissions"
    )

    parser.add_argument(
        "--show-credentials",
        action="store_true",
        help="Print newly generated passwords"
    )

    parser.add_argument(
        "--export-credentials",
        action="store_true",
        help="Export newly generated credentials to JSON"
    )

    args = parser.parse_args()

    if args.init:
        create_demo_accounts(
            show_credentials=args.show_credentials,
            export_credentials=args.export_credentials
        )

    if args.list:
        list_demo_accounts()

    if args.roles:
        list_role_permissions()

    if not (
        args.init or args.list or args.roles
    ):
        parser.print_help()


if __name__ == "__main__":
    main()
