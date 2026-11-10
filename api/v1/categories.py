from __future__ import annotations

"""Planned module: categories. Implementation pending."""

"""
backend/categories.py

Autonomous Retail Supply Chain AI 5.0
Hierarchical Product Category Management API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Create product categories
    - Parent-child category hierarchy
    - Nested subcategories
    - Category slug uniqueness
    - Category activation/deactivation
    - Category updates
    - Product-category assignments
    - Product-category removal
    - Category tree API
    - Category statistics
    - Optimistic concurrency
    - Tenant isolation
    - RBAC authorization
    - Bounded in-memory storage

IMPORTANT:
    This is a prototype implementation.

    Product IDs must be validated against
    the authoritative product repository
    before assignments are accepted.

    Category changes should be persisted
    transactionally with audit/outbox events.
"""


import asyncio
import re
import secrets

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from backend.permissions import (
    CurrentPrincipal,
    Permission,
    Principal,
    ResourceContext,
    permission_engine,
)


# ============================================================
# CONFIGURATION
# ============================================================

API_PREFIX = "/api/v1/categories"

MAX_CATEGORIES_PER_TENANT = 5000
MAX_CATEGORY_DEPTH = 8
MAX_PRODUCTS_PER_CATEGORY = 100_000
MAX_LIST_LIMIT = 200


# ============================================================
# ENUMS
# ============================================================

class CategoryStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


# ============================================================
# REQUEST MODELS
# ============================================================

class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        min_length=2,
        max_length=150,
    )

    description: str | None = Field(
        default=None,
        max_length=1000,
    )

    parent_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    display_order: int = Field(
        default=0,
        ge=0,
        le=1_000_000,
    )


class CategoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    name: str | None = Field(
        default=None,
        min_length=2,
        max_length=150,
    )

    description: str | None = Field(
        default=None,
        max_length=1000,
    )

    display_order: int | None = Field(
        default=None,
        ge=0,
        le=1_000_000,
    )


class CategoryMove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    parent_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )


class CategoryStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    status: CategoryStatus


class CategoryProductAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(
        min_length=1,
        max_length=128,
    )

    expected_version: int = Field(ge=1)


# ============================================================
# RESPONSE MODELS
# ============================================================

class CategoryResponse(BaseModel):
    category_id: str
    name: str
    slug: str

    description: str | None

    parent_id: str | None
    depth: int
    path: str

    display_order: int
    status: CategoryStatus

    direct_product_count: int

    version: int

    created_at: datetime
    updated_at: datetime


class CategoryTreeNode(CategoryResponse):
    children: list["CategoryTreeNode"] = Field(
        default_factory=list
    )


class CategoryStatistics(BaseModel):
    total_categories: int
    active_categories: int
    inactive_categories: int
    root_categories: int
    total_product_assignments: int
    maximum_depth: int


class CategoryProductsResponse(BaseModel):
    category_id: str
    product_ids: list[str]
    total: int


# ============================================================
# INTERNAL RECORD
# ============================================================

@dataclass
class CategoryRecord:
    category_id: str
    tenant_id: str

    name: str
    slug: str

    description: str | None
    parent_id: str | None

    display_order: int

    status: CategoryStatus = CategoryStatus.ACTIVE

    product_ids: set[str] = field(
        default_factory=set
    )

    version: int = 1

    created_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def slugify(value: str) -> str:

    slug = re.sub(
        r"[^a-z0-9]+",
        "-",
        value.strip().lower(),
    ).strip("-")

    if not slug:
        raise HTTPException(
            status_code=422,
            detail="Category name cannot form a slug",
        )

    return slug


def require_category_permission(
    principal: Principal,
    *,
    write: bool,
) -> None:

    permission = (
        Permission.PRODUCT_WRITE
        if write
        else Permission.PRODUCT_READ
    )

    decision = permission_engine.evaluate(
        principal,
        permission,
        ResourceContext(
            tenant_id=principal.tenant_id,
        ),
    )

    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail="Category access denied",
        )

    # Categories are tenant-wide catalog data.
    # Write access should not be granted solely
    # through a warehouse-scoped permission.
    if (
        write
        and principal.allowed_warehouse_ids
        is not None
    ):
        raise HTTPException(
            status_code=403,
            detail="Tenant-wide catalog write required",
        )


# ============================================================
# CATEGORY STORE
# ============================================================

class CategoryStore:

    def __init__(self):

        self._records: dict[
            str,
            CategoryRecord,
        ] = {}

        self._lock = asyncio.Lock()

    def _get(
        self,
        tenant_id: str,
        category_id: str,
    ) -> CategoryRecord:

        record = self._records.get(
            category_id
        )

        if (
            record is None
            or record.tenant_id != tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Category not found",
            )

        return record

    def _tenant_records(
        self,
        tenant_id: str,
    ) -> list[CategoryRecord]:

        return [
            record
            for record in self._records.values()
            if record.tenant_id == tenant_id
        ]

    def _children(
        self,
        tenant_id: str,
        parent_id: str | None,
    ) -> list[CategoryRecord]:

        return [
            record
            for record in self._tenant_records(
                tenant_id
            )
            if record.parent_id == parent_id
        ]

    def _slug_exists(
        self,
        tenant_id: str,
        parent_id: str | None,
        slug: str,
        exclude_id: str | None = None,
    ) -> bool:

        return any(
            record.slug == slug
            and record.parent_id == parent_id
            and record.category_id != exclude_id
            for record in self._tenant_records(
                tenant_id
            )
        )

    def _ancestors(
        self,
        tenant_id: str,
        record: CategoryRecord,
    ) -> list[CategoryRecord]:

        ancestors = []
        visited = set()

        current = record

        while current.parent_id is not None:

            if current.category_id in visited:
                raise HTTPException(
                    status_code=409,
                    detail="Category hierarchy cycle detected",
                )

            visited.add(
                current.category_id
            )

            parent = self._get(
                tenant_id,
                current.parent_id,
            )

            ancestors.append(parent)
            current = parent

        ancestors.reverse()

        return ancestors

    def _depth(
        self,
        tenant_id: str,
        record: CategoryRecord,
    ) -> int:

        return len(
            self._ancestors(
                tenant_id,
                record,
            )
        )

    def _path(
        self,
        tenant_id: str,
        record: CategoryRecord,
    ) -> str:

        ancestors = self._ancestors(
            tenant_id,
            record,
        )

        return "/" + "/".join(
            item.slug
            for item in [
                *ancestors,
                record,
            ]
        )

    def _response(
        self,
        record: CategoryRecord,
    ) -> CategoryResponse:

        return CategoryResponse(
            category_id=record.category_id,
            name=record.name,
            slug=record.slug,
            description=record.description,
            parent_id=record.parent_id,
            depth=self._depth(
                record.tenant_id,
                record,
            ),
            path=self._path(
                record.tenant_id,
                record,
            ),
            display_order=record.display_order,
            status=record.status,
            direct_product_count=len(
                record.product_ids
            ),
            version=record.version,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _check_version(
        record: CategoryRecord,
        expected_version: int,
    ) -> None:

        if record.version != expected_version:
            raise HTTPException(
                status_code=409,
                detail="Category version conflict",
            )

    def _subtree_height(
        self,
        tenant_id: str,
        category_id: str,
    ) -> int:

        children = self._children(
            tenant_id,
            category_id,
        )

        if not children:
            return 0

        return 1 + max(
            self._subtree_height(
                tenant_id,
                child.category_id,
            )
            for child in children
        )

    async def create(
        self,
        *,
        principal: Principal,
        payload: CategoryCreate,
    ) -> CategoryResponse:

        require_category_permission(
            principal,
            write=True,
        )

        async with self._lock:

            tenant_id = principal.tenant_id

            if (
                len(self._tenant_records(tenant_id))
                >= MAX_CATEGORIES_PER_TENANT
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Category capacity reached",
                )

            if payload.parent_id is not None:

                parent = self._get(
                    tenant_id,
                    payload.parent_id,
                )

                if parent.status != CategoryStatus.ACTIVE:
                    raise HTTPException(
                        status_code=409,
                        detail="Parent category is inactive",
                    )

                depth = (
                    self._depth(
                        tenant_id,
                        parent,
                    ) + 1
                )

                if depth >= MAX_CATEGORY_DEPTH:
                    raise HTTPException(
                        status_code=409,
                        detail="Maximum category depth exceeded",
                    )

            slug = slugify(
                payload.name
            )

            if self._slug_exists(
                tenant_id,
                payload.parent_id,
                slug,
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Category slug already exists",
                )

            record = CategoryRecord(
                category_id=secrets.token_urlsafe(18),
                tenant_id=tenant_id,
                name=payload.name.strip(),
                slug=slug,
                description=payload.description,
                parent_id=payload.parent_id,
                display_order=payload.display_order,
            )

            self._records[
                record.category_id
            ] = record

            return self._response(
                record
            )

    async def get(
        self,
        *,
        principal: Principal,
        category_id: str,
    ) -> CategoryResponse:

        require_category_permission(
            principal,
            write=False,
        )

        async with self._lock:

            record = self._get(
                principal.tenant_id,
                category_id,
            )

            return self._response(
                record
            )

    async def list_categories(
        self,
        *,
        principal: Principal,
        parent_id: str | None,
        status: CategoryStatus | None,
        limit: int,
    ) -> list[CategoryResponse]:

        require_category_permission(
            principal,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._tenant_records(
                    principal.tenant_id
                )
                if (
                    parent_id is None
                    or record.parent_id == parent_id
                )
                and (
                    status is None
                    or record.status == status
                )
            ]

            records.sort(
                key=lambda item: (
                    item.display_order,
                    item.name.lower(),
                )
            )

            return [
                self._response(record)
                for record in records[:limit]
            ]

    async def update(
        self,
        *,
        principal: Principal,
        category_id: str,
        payload: CategoryUpdate,
    ) -> CategoryResponse:

        require_category_permission(
            principal,
            write=True,
        )

        async with self._lock:

            record = self._get(
                principal.tenant_id,
                category_id,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if payload.name is not None:

                new_slug = slugify(
                    payload.name
                )

                if self._slug_exists(
                    principal.tenant_id,
                    record.parent_id,
                    new_slug,
                    exclude_id=category_id,
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Category slug already exists",
                    )

                record.name = payload.name.strip()
                record.slug = new_slug

            if "description" in payload.model_fields_set:
                record.description = (
                    payload.description
                )

            if payload.display_order is not None:
                record.display_order = (
                    payload.display_order
                )

            record.version += 1
            record.updated_at = utc_now()

            return self._response(
                record
            )

    async def move(
        self,
        *,
        principal: Principal,
        category_id: str,
        payload: CategoryMove,
    ) -> CategoryResponse:

        require_category_permission(
            principal,
            write=True,
        )

        async with self._lock:

            tenant_id = principal.tenant_id

            record = self._get(
                tenant_id,
                category_id,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if payload.parent_id == category_id:
                raise HTTPException(
                    status_code=409,
                    detail="Category cannot parent itself",
                )

            new_depth = 0

            if payload.parent_id is not None:

                parent = self._get(
                    tenant_id,
                    payload.parent_id,
                )

                if parent.status != CategoryStatus.ACTIVE:
                    raise HTTPException(
                        status_code=409,
                        detail="Parent category is inactive",
                    )

                ancestors = self._ancestors(
                    tenant_id,
                    parent,
                )

                ancestor_ids = {
                    item.category_id
                    for item in ancestors
                }

                ancestor_ids.add(
                    parent.category_id
                )

                if category_id in ancestor_ids:
                    raise HTTPException(
                        status_code=409,
                        detail="Category cycle detected",
                    )

                new_depth = (
                    self._depth(
                        tenant_id,
                        parent,
                    ) + 1
                )

            height = self._subtree_height(
                tenant_id,
                category_id,
            )

            if (
                new_depth + height
                >= MAX_CATEGORY_DEPTH
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Maximum hierarchy depth exceeded",
                )

            if self._slug_exists(
                tenant_id,
                payload.parent_id,
                record.slug,
                exclude_id=category_id,
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Slug conflict in destination",
                )

            record.parent_id = payload.parent_id
            record.version += 1
            record.updated_at = utc_now()

            return self._response(
                record
            )

    async def update_status(
        self,
        *,
        principal: Principal,
        category_id: str,
        payload: CategoryStatusUpdate,
    ) -> CategoryResponse:

        require_category_permission(
            principal,
            write=True,
        )

        async with self._lock:

            record = self._get(
                principal.tenant_id,
                category_id,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if payload.status == CategoryStatus.INACTIVE:

                children = self._children(
                    principal.tenant_id,
                    category_id,
                )

                if any(
                    child.status == CategoryStatus.ACTIVE
                    for child in children
                ):
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Deactivate active child "
                            "categories first"
                        ),
                    )

            if payload.status == CategoryStatus.ACTIVE:

                if record.parent_id is not None:

                    parent = self._get(
                        principal.tenant_id,
                        record.parent_id,
                    )

                    if parent.status != CategoryStatus.ACTIVE:
                        raise HTTPException(
                            status_code=409,
                            detail="Parent category is inactive",
                        )

            record.status = payload.status
            record.version += 1
            record.updated_at = utc_now()

            return self._response(
                record
            )

    async def assign_product(
        self,
        *,
        principal: Principal,
        category_id: str,
        payload: CategoryProductAssignment,
        remove: bool = False,
    ) -> CategoryResponse:

        require_category_permission(
            principal,
            write=True,
        )

        async with self._lock:

            record = self._get(
                principal.tenant_id,
                category_id,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if (
                not remove
                and record.status != CategoryStatus.ACTIVE
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Cannot assign to inactive category",
                )

            if remove:

                if payload.product_id not in record.product_ids:
                    raise HTTPException(
                        status_code=404,
                        detail="Product assignment not found",
                    )

                record.product_ids.remove(
                    payload.product_id
                )

            else:

                if (
                    len(record.product_ids)
                    >= MAX_PRODUCTS_PER_CATEGORY
                    and payload.product_id
                    not in record.product_ids
                ):
                    raise HTTPException(
                        status_code=503,
                        detail="Category product capacity reached",
                    )

                record.product_ids.add(
                    payload.product_id
                )

            record.version += 1
            record.updated_at = utc_now()

            return self._response(
                record
            )

    async def products(
        self,
        *,
        principal: Principal,
        category_id: str,
    ) -> CategoryProductsResponse:

        require_category_permission(
            principal,
            write=False,
        )

        async with self._lock:

            record = self._get(
                principal.tenant_id,
                category_id,
            )

            product_ids = sorted(
                record.product_ids
            )

            return CategoryProductsResponse(
                category_id=category_id,
                product_ids=product_ids,
                total=len(product_ids),
            )

    async def tree(
        self,
        *,
        principal: Principal,
    ) -> list[CategoryTreeNode]:

        require_category_permission(
            principal,
            write=False,
        )

        async with self._lock:

            records = self._tenant_records(
                principal.tenant_id
            )

            children_map: dict[
                str | None,
                list[CategoryRecord],
            ] = defaultdict(list)

            for record in records:
                children_map[
                    record.parent_id
                ].append(record)

            for siblings in children_map.values():
                siblings.sort(
                    key=lambda item: (
                        item.display_order,
                        item.name.lower(),
                    )
                )

            def build_node(
                record: CategoryRecord,
            ) -> CategoryTreeNode:

                response = self._response(
                    record
                )

                return CategoryTreeNode(
                    **response.model_dump(),
                    children=[
                        build_node(child)
                        for child in children_map.get(
                            record.category_id,
                            [],
                        )
                    ],
                )

            return [
                build_node(root)
                for root in children_map.get(
                    None,
                    [],
                )
            ]

    async def statistics(
        self,
        *,
        principal: Principal,
    ) -> CategoryStatistics:

        require_category_permission(
            principal,
            write=False,
        )

        async with self._lock:

            records = self._tenant_records(
                principal.tenant_id
            )

            return CategoryStatistics(
                total_categories=len(records),
                active_categories=sum(
                    record.status == CategoryStatus.ACTIVE
                    for record in records
                ),
                inactive_categories=sum(
                    record.status == CategoryStatus.INACTIVE
                    for record in records
                ),
                root_categories=sum(
                    record.parent_id is None
                    for record in records
                ),
                total_product_assignments=sum(
                    len(record.product_ids)
                    for record in records
                ),
                maximum_depth=max(
                    (
                        self._depth(
                            principal.tenant_id,
                            record,
                        )
                        for record in records
                    ),
                    default=0,
                ),
            )


category_store = CategoryStore()


# ============================================================
# CATEGORY SERVICE
# ============================================================

class CategoryService:

    def __init__(
        self,
        store: CategoryStore,
    ):
        self.store = store

    async def create(
        self,
        principal: Principal,
        payload: CategoryCreate,
    ) -> CategoryResponse:

        return await self.store.create(
            principal=principal,
            payload=payload,
        )

    async def assign_product(
        self,
        principal: Principal,
        category_id: str,
        payload: CategoryProductAssignment,
    ) -> CategoryResponse:

        return await self.store.assign_product(
            principal=principal,
            category_id=category_id,
            payload=payload,
        )

    async def remove_product(
        self,
        principal: Principal,
        category_id: str,
        payload: CategoryProductAssignment,
    ) -> CategoryResponse:

        return await self.store.assign_product(
            principal=principal,
            category_id=category_id,
            payload=payload,
            remove=True,
        )


category_service = CategoryService(
    category_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Product Categories"],
)


@router.post(
    "",
    response_model=CategoryResponse,
    status_code=201,
)
async def create_category(
    payload: CategoryCreate,
    principal: CurrentPrincipal,
):
    return await category_service.create(
        principal,
        payload,
    )


@router.get(
    "",
    response_model=list[CategoryResponse],
)
async def list_categories(
    principal: CurrentPrincipal,
    parent_id: str | None = None,
    status: CategoryStatus | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await category_store.list_categories(
        principal=principal,
        parent_id=parent_id,
        status=status,
        limit=limit,
    )


@router.get(
    "/tree",
    response_model=list[CategoryTreeNode],
)
async def get_category_tree(
    principal: CurrentPrincipal,
):
    return await category_store.tree(
        principal=principal,
    )


@router.get(
    "/statistics",
    response_model=CategoryStatistics,
)
async def get_category_statistics(
    principal: CurrentPrincipal,
):
    return await category_store.statistics(
        principal=principal,
    )


@router.get(
    "/{category_id}",
    response_model=CategoryResponse,
)
async def get_category(
    category_id: str,
    principal: CurrentPrincipal,
):
    return await category_store.get(
        principal=principal,
        category_id=category_id,
    )


@router.patch(
    "/{category_id}",
    response_model=CategoryResponse,
)
async def update_category(
    category_id: str,
    payload: CategoryUpdate,
    principal: CurrentPrincipal,
):
    return await category_store.update(
        principal=principal,
        category_id=category_id,
        payload=payload,
    )


@router.post(
    "/{category_id}/move",
    response_model=CategoryResponse,
)
async def move_category(
    category_id: str,
    payload: CategoryMove,
    principal: CurrentPrincipal,
):
    return await category_store.move(
        principal=principal,
        category_id=category_id,
        payload=payload,
    )


@router.patch(
    "/{category_id}/status",
    response_model=CategoryResponse,
)
async def update_category_status(
    category_id: str,
    payload: CategoryStatusUpdate,
    principal: CurrentPrincipal,
):
    return await category_store.update_status(
        principal=principal,
        category_id=category_id,
        payload=payload,
    )


@router.get(
    "/{category_id}/products",
    response_model=CategoryProductsResponse,
)
async def get_category_products(
    category_id: str,
    principal: CurrentPrincipal,
):
    return await category_store.products(
        principal=principal,
        category_id=category_id,
    )


@router.post(
    "/{category_id}/products",
    response_model=CategoryResponse,
)
async def assign_product(
    category_id: str,
    payload: CategoryProductAssignment,
    principal: CurrentPrincipal,
):
    return await category_service.assign_product(
        principal,
        category_id,
        payload,
    )


@router.delete(
    "/{category_id}/products",
    response_model=CategoryResponse,
)
async def remove_product(
    category_id: str,
    payload: CategoryProductAssignment,
    principal: CurrentPrincipal,
):
    return await category_service.remove_product(
        principal,
        category_id,
        payload,
    )


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "CategoryStatus",
    "CategoryCreate",
    "CategoryUpdate",
    "CategoryMove",
    "CategoryStatusUpdate",
    "CategoryProductAssignment",
    "CategoryResponse",
    "CategoryTreeNode",
    "CategoryStatistics",
    "CategoryProductsResponse",
    "CategoryRecord",
    "CategoryStore",
    "CategoryService",
    "category_store",
    "category_service",
    "router",
]
