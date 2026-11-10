from __future__ import annotations

"""Planned module: category. Implementation pending."""

"""
backend/models/category.py

Autonomous Retail Supply Chain AI 5.0
Product Category Database Model

Features:
    - Hierarchical categories
    - Parent-child relationships
    - Multi-tenant organization isolation
    - Category slug and code
    - Active/inactive status
    - Soft deletion
    - Category tree traversal
    - SEO metadata
    - Display ordering
    - Category images
    - Optimistic concurrency control
    - UTC timestamps

Dependencies:
    SQLAlchemy >= 2.0

Uses:
    backend.models.base.Base
"""


import re
import uuid

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
    selectinload,
)

from backend.models.base import Base


# ============================================================
# UTILITIES
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    return str(uuid.uuid4())


def generate_slug(value: str) -> str:
    """
    Convert category name into a URL-friendly slug.
    """
    value = value.strip().lower()

    value = re.sub(
        r"[^a-z0-9]+",
        "-",
        value,
    )

    return value.strip("-")


# ============================================================
# CATEGORY MODEL
# ============================================================

class Category(Base):
    __tablename__ = "categories"

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_category_org_id",
        ),
        UniqueConstraint(
            "organization_id",
            "code",
            name="uq_category_org_code",
        ),
        UniqueConstraint(
            "organization_id",
            "slug",
            name="uq_category_org_slug",
        ),
        ForeignKeyConstraint(
            ["organization_id", "parent_id"],
            [
                "categories.organization_id",
                "categories.id",
            ],
            name="fk_category_parent_same_org",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "display_order >= 0",
            name="category_display_order_nonnegative",
        ),
        CheckConstraint(
            "parent_id IS NULL OR parent_id <> id",
            name="category_not_self_parent",
        ),
        Index(
            "ix_category_org_parent",
            "organization_id",
            "parent_id",
        ),
        Index(
            "ix_category_org_active",
            "organization_id",
            "is_active",
        ),
        Index(
            "ix_category_org_deleted",
            "organization_id",
            "is_deleted",
        ),
    )

    # --------------------------------------------------------
    # PRIMARY IDENTIFIERS
    # --------------------------------------------------------

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )

    organization_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    # --------------------------------------------------------
    # CATEGORY INFORMATION
    # --------------------------------------------------------

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    slug: Mapped[str] = mapped_column(
        String(220),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    short_description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    # --------------------------------------------------------
    # CATEGORY HIERARCHY
    # --------------------------------------------------------

    parent_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    parent: Mapped["Category | None"] = relationship(
        "Category",
        remote_side=lambda: [
            Category.organization_id,
            Category.id,
        ],
        back_populates="children",
        foreign_keys=lambda: [
            Category.organization_id,
            Category.parent_id,
        ],
    )

    children: Mapped[list["Category"]] = relationship(
        "Category",
        back_populates="parent",
        foreign_keys=lambda: [
            Category.organization_id,
            Category.parent_id,
        ],
        passive_deletes=True,
    )

    # --------------------------------------------------------
    # CATEGORY DISPLAY
    # --------------------------------------------------------

    image_url: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    icon_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    display_order: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    is_featured: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    # --------------------------------------------------------
    # SEO
    # --------------------------------------------------------

    meta_title: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    meta_description: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    meta_keywords: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    # --------------------------------------------------------
    # SOFT DELETE
    # --------------------------------------------------------

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    deleted_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    # --------------------------------------------------------
    # AUDIT FIELDS
    # --------------------------------------------------------

    created_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    updated_by: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    __mapper_args__ = {
        "version_id_col": version,
    }

    # --------------------------------------------------------
    # PROPERTIES
    # --------------------------------------------------------

    @property
    def is_root(self) -> bool:
        return self.parent_id is None

    @property
    def is_subcategory(self) -> bool:
        return self.parent_id is not None

    @property
    def is_available(self) -> bool:
        return self.is_active and not self.is_deleted

    # --------------------------------------------------------
    # BUSINESS METHODS
    # --------------------------------------------------------

    def activate(self, user_id: str | None = None) -> None:
        if self.is_deleted:
            raise ValueError(
                "Cannot activate a deleted category"
            )

        self.is_active = True
        self.updated_by = user_id
        self.updated_at = utc_now()

    def deactivate(self, user_id: str | None = None) -> None:
        if self.is_deleted:
            raise ValueError(
                "Category is already deleted"
            )

        self.is_active = False
        self.updated_by = user_id
        self.updated_at = utc_now()

    def soft_delete(self, user_id: str) -> None:
        if self.is_deleted:
            raise ValueError(
                "Category is already deleted"
            )

        self.is_deleted = True
        self.is_active = False
        self.deleted_at = utc_now()
        self.deleted_by = user_id
        self.updated_by = user_id
        self.updated_at = utc_now()

    def restore(self, user_id: str) -> None:
        if not self.is_deleted:
            raise ValueError(
                "Category is not deleted"
            )

        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.is_active = False
        self.updated_by = user_id
        self.updated_at = utc_now()

    def rename(
        self,
        name: str,
        *,
        update_slug: bool = False,
        user_id: str | None = None,
    ) -> None:
        name = name.strip()

        if not name:
            raise ValueError(
                "Category name cannot be empty"
            )

        self.name = name

        if update_slug:
            slug = generate_slug(name)

            if not slug:
                raise ValueError(
                    "Cannot generate a valid slug"
                )

            self.slug = slug

        self.updated_by = user_id
        self.updated_at = utc_now()

    def set_parent(
        self,
        parent: "Category | None",
    ) -> None:
        """
        Basic parent assignment.

        The service layer must validate the full
        ancestor chain to prevent hierarchy cycles.
        """

        if parent is None:
            self.parent = None
            self.parent_id = None
            return

        if parent is self or (
            self.id is not None
            and parent.id == self.id
        ):
            raise ValueError(
                "A category cannot be its own parent"
            )

        if parent.organization_id != self.organization_id:
            raise ValueError(
                "Parent belongs to another organization"
            )

        if parent.is_deleted:
            raise ValueError(
                "Deleted category cannot be a parent"
            )

        self.parent = parent

    # --------------------------------------------------------
    # SERIALIZATION
    # --------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "code": self.code,
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "short_description": self.short_description,
            "parent_id": self.parent_id,
            "image_url": self.image_url,
            "icon_name": self.icon_name,
            "display_order": self.display_order,
            "is_featured": self.is_featured,
            "is_active": self.is_active,
            "is_deleted": self.is_deleted,
            "is_root": self.is_root,
            "is_available": self.is_available,
            "meta_title": self.meta_title,
            "meta_description": self.meta_description,
            "meta_keywords": self.meta_keywords,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "version": self.version,
            "created_at": (
                self.created_at.isoformat()
                if self.created_at else None
            ),
            "updated_at": (
                self.updated_at.isoformat()
                if self.updated_at else None
            ),
            "deleted_at": (
                self.deleted_at.isoformat()
                if self.deleted_at else None
            ),
        }

    def __repr__(self) -> str:
        return (
            f"<Category("
            f"id={self.id}, "
            f"name={self.name!r}, "
            f"parent_id={self.parent_id}"
            f")>"
        )


# ============================================================
# CATEGORY DATABASE HELPERS
# ============================================================

async def get_category(
    db: AsyncSession,
    organization_id: str,
    category_id: str,
    *,
    include_deleted: bool = False,
) -> Category | None:

    statement = select(Category).where(
        Category.organization_id == organization_id,
        Category.id == category_id,
    )

    if not include_deleted:
        statement = statement.where(
            Category.is_deleted.is_(False)
        )

    return await db.scalar(statement)


async def get_root_categories(
    db: AsyncSession,
    organization_id: str,
) -> list[Category]:

    result = await db.scalars(
        select(Category)
        .where(
            Category.organization_id == organization_id,
            Category.parent_id.is_(None),
            Category.is_deleted.is_(False),
        )
        .order_by(
            Category.display_order,
            Category.name,
        )
    )

    return list(result.all())


async def get_child_categories(
    db: AsyncSession,
    organization_id: str,
    parent_id: str,
) -> list[Category]:

    result = await db.scalars(
        select(Category)
        .where(
            Category.organization_id == organization_id,
            Category.parent_id == parent_id,
            Category.is_deleted.is_(False),
        )
        .order_by(
            Category.display_order,
            Category.name,
        )
    )

    return list(result.all())


async def get_category_ancestors(
    db: AsyncSession,
    organization_id: str,
    category_id: str,
    *,
    max_depth: int = 100,
) -> list[Category]:
    """
    Return ancestors from root to immediate parent.

    Detects cycles in existing database records.
    """

    current = await get_category(
        db,
        organization_id,
        category_id,
    )

    if current is None:
        raise ValueError("Category not found")

    ancestors: list[Category] = []
    visited = {current.id}

    for _ in range(max_depth):
        if current.parent_id is None:
            return list(reversed(ancestors))

        if current.parent_id in visited:
            raise ValueError(
                "Category hierarchy contains a cycle"
            )

        visited.add(current.parent_id)

        parent = await get_category(
            db,
            organization_id,
            current.parent_id,
        )

        if parent is None:
            raise ValueError(
                "Category parent is missing or deleted"
            )

        ancestors.append(parent)
        current = parent

    raise ValueError(
        "Maximum category hierarchy depth exceeded"
    )


async def validate_category_parent(
    db: AsyncSession,
    organization_id: str,
    category_id: str,
    new_parent_id: str | None,
) -> None:
    """
    Validate a proposed parent before updating.

    Call inside the same transaction as the update.
    Concurrent hierarchy modifications require
    additional serialization or locking.
    """

    if new_parent_id is None:
        return

    if category_id == new_parent_id:
        raise ValueError(
            "Category cannot be its own parent"
        )

    parent = await get_category(
        db,
        organization_id,
        new_parent_id,
    )

    if parent is None:
        raise ValueError(
            "Parent category not found"
        )

    ancestors = await get_category_ancestors(
        db,
        organization_id,
        new_parent_id,
    )

    ancestor_ids = {
        ancestor.id for ancestor in ancestors
    }

    if category_id in ancestor_ids:
        raise ValueError(
            "Cannot move category beneath its descendant"
        )


async def get_category_tree(
    db: AsyncSession,
    organization_id: str,
) -> list[dict[str, Any]]:
    """
    Build a complete category tree in memory.

    Uses one database query rather than recursively
    issuing queries for every category.
    """

    result = await db.scalars(
        select(Category)
        .where(
            Category.organization_id == organization_id,
            Category.is_deleted.is_(False),
        )
        .order_by(
            Category.display_order,
            Category.name,
        )
    )

    categories = list(result.all())

    nodes: dict[str, dict[str, Any]] = {
        category.id: {
            **category.to_dict(),
            "children": [],
        }
        for category in categories
    }

    roots: list[dict[str, Any]] = []

    for category in categories:
        node = nodes[category.id]

        if (
            category.parent_id is None
            or category.parent_id not in nodes
        ):
            roots.append(node)
        else:
            nodes[category.parent_id][
                "children"
            ].append(node)

    return roots
