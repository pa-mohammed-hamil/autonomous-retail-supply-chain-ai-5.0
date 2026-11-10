from __future__ import annotations

"""Planned module: products. Implementation pending."""

"""
backend/products.py

Autonomous Retail Supply Chain AI 5.0
Enterprise Product Catalog Management API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Tenant-isolated product catalog
    - Unique SKU and barcode validation
    - Product creation and modification
    - Product category assignment
    - Supplier associations
    - Product specifications and metadata
    - Product activation and deactivation
    - Soft archival
    - Product search and filtering
    - Product analytics
    - Optimistic concurrency
    - Idempotent product creation

Prototype limitations:
    - In-memory storage
    - No real supplier or category database checks
    - No actual inventory or pricing modifications
    - No persistent audit log
    - No external ERP synchronization
"""


import asyncio
import hashlib
import json
import secrets

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from backend.permissions import (
    CurrentPrincipal,
    Permission,
    Principal,
    ResourceContext,
    permission_engine,
)


API_PREFIX = "/api/v1/products"

MAX_PRODUCTS_PER_TENANT = 100000
MAX_SUPPLIERS_PER_PRODUCT = 50
MAX_ATTRIBUTES_PER_PRODUCT = 50
MAX_ATTRIBUTE_BYTES = 16000
MAX_IDEMPOTENCY_KEYS = 150000
MAX_LIST_LIMIT = 200


# ============================================================
# ENUMS
# ============================================================

class ProductStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"
    DISCONTINUED = "discontinued"
    ARCHIVED = "archived"


class ProductType(str, Enum):
    PHYSICAL = "physical"
    DIGITAL = "digital"
    SERVICE = "service"
    BUNDLE = "bundle"


class ProductUnit(str, Enum):
    PIECE = "piece"
    BOX = "box"
    PACK = "pack"
    KILOGRAM = "kilogram"
    GRAM = "gram"
    LITER = "liter"
    METER = "meter"


class ProductEventType(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    STATUS_CHANGED = "status_changed"
    SUPPLIER_ADDED = "supplier_added"
    SUPPLIER_REMOVED = "supplier_removed"
    ARCHIVED = "archived"


# ============================================================
# SHARED SCHEMAS
# ============================================================

class ProductDimensions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    length_cm: float = Field(gt=0, le=100000)
    width_cm: float = Field(gt=0, le=100000)
    height_cm: float = Field(gt=0, le=100000)

    weight_kg: float | None = Field(
        default=None,
        gt=0,
        le=100000,
    )


class ProductSpecification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(
        min_length=1,
        max_length=100,
    )

    value: str = Field(
        min_length=1,
        max_length=1000,
    )


class ProductSupplierInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_id: str = Field(
        min_length=1,
        max_length=128,
    )

    supplier_sku: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    preferred: bool = False


# ============================================================
# REQUEST SCHEMAS
# ============================================================

class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(
        min_length=2,
        max_length=100,
        pattern=r"^[A-Za-z0-9._-]+$",
    )

    barcode: str | None = Field(
        default=None,
        min_length=6,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )

    name: str = Field(
        min_length=2,
        max_length=250,
    )

    description: str = Field(
        default="",
        max_length=5000,
    )

    category_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    brand: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    product_type: ProductType = (
        ProductType.PHYSICAL
    )

    unit: ProductUnit = (
        ProductUnit.PIECE
    )

    dimensions: ProductDimensions | None = None

    specifications: list[
        ProductSpecification
    ] = Field(
        default_factory=list,
        max_length=MAX_ATTRIBUTES_PER_PRODUCT,
    )

    attributes: dict[str, Any] = Field(
        default_factory=dict,
    )

    suppliers: list[
        ProductSupplierInput
    ] = Field(
        default_factory=list,
        max_length=MAX_SUPPLIERS_PER_PRODUCT,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @field_validator("attributes")
    @classmethod
    def validate_attributes(
        cls,
        value: dict[str, Any],
    ) -> dict[str, Any]:

        if len(value) > MAX_ATTRIBUTES_PER_PRODUCT:
            raise ValueError(
                "Too many product attributes"
            )

        for key in value:

            if not isinstance(key, str):
                raise ValueError(
                    "Attribute keys must be strings"
                )

            if len(key) > 100:
                raise ValueError(
                    "Attribute key exceeds length limit"
                )

        serialized = json.dumps(
            value,
            allow_nan=False,
        )

        if (
            len(serialized.encode("utf-8"))
            > MAX_ATTRIBUTE_BYTES
        ):
            raise ValueError(
                "Product attributes exceed size limit"
            )

        return value

    @model_validator(mode="after")
    def validate_suppliers(self):

        supplier_ids = [
            item.supplier_id
            for item in self.suppliers
        ]

        if len(set(supplier_ids)) != len(supplier_ids):
            raise ValueError(
                "Duplicate supplier IDs"
            )

        preferred_count = sum(
            item.preferred
            for item in self.suppliers
        )

        if preferred_count > 1:
            raise ValueError(
                "Only one preferred supplier is allowed"
            )

        spec_keys = [
            item.key
            for item in self.specifications
        ]

        if len(set(spec_keys)) != len(spec_keys):
            raise ValueError(
                "Duplicate specification keys"
            )

        return self


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    name: str | None = Field(
        default=None,
        min_length=2,
        max_length=250,
    )

    description: str | None = Field(
        default=None,
        max_length=5000,
    )

    category_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    brand: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    dimensions: ProductDimensions | None = None

    specifications: list[
        ProductSpecification
    ] | None = Field(
        default=None,
        max_length=MAX_ATTRIBUTES_PER_PRODUCT,
    )

    attributes: dict[str, Any] | None = None

    @field_validator("attributes")
    @classmethod
    def validate_attributes(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:

        if value is None:
            return None

        if len(value) > MAX_ATTRIBUTES_PER_PRODUCT:
            raise ValueError(
                "Too many attributes"
            )

        for key in value:
            if len(key) > 100:
                raise ValueError(
                    "Attribute key exceeds length limit"
                )

        serialized = json.dumps(
            value,
            allow_nan=False,
        )

        if (
            len(serialized.encode("utf-8"))
            > MAX_ATTRIBUTE_BYTES
        ):
            raise ValueError(
                "Attributes exceed size limit"
            )

        return value


class ProductStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    status: ProductStatus

    reason: str = Field(
        min_length=3,
        max_length=500,
    )


class ProductSupplierAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    supplier: ProductSupplierInput


class ProductSupplierRemove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


# ============================================================
# RESPONSE SCHEMAS
# ============================================================

class ProductSupplierResponse(BaseModel):
    supplier_id: str
    supplier_sku: str | None
    preferred: bool


class ProductEventResponse(BaseModel):
    event_id: str

    event_type: ProductEventType

    actor_id: str
    details: str | None

    created_at: datetime


class ProductResponse(BaseModel):
    product_id: str

    sku: str
    barcode: str | None

    name: str
    description: str

    category_id: str | None
    brand: str | None

    product_type: ProductType
    unit: ProductUnit

    status: ProductStatus

    supplier_count: int
    specification_count: int

    version: int

    created_at: datetime
    updated_at: datetime


class ProductDetailResponse(ProductResponse):
    dimensions: ProductDimensions | None

    specifications: list[
        ProductSpecification
    ]

    attributes: dict[str, Any]

    suppliers: list[
        ProductSupplierResponse
    ]

    events: list[
        ProductEventResponse
    ]


class ProductAnalyticsResponse(BaseModel):
    total_products: int

    draft: int
    active: int
    inactive: int
    discontinued: int
    archived: int

    physical_products: int
    digital_products: int
    service_products: int
    bundles: int

    products_with_suppliers: int
    products_without_suppliers: int

    total_categories: int
    total_brands: int


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass
class ProductRecord:
    product_id: str
    tenant_id: str

    sku: str
    barcode: str | None

    name: str
    description: str

    category_id: str | None
    brand: str | None

    product_type: ProductType
    unit: ProductUnit

    dimensions: ProductDimensions | None

    specifications: list[
        ProductSpecification
    ]

    attributes: dict[str, Any]

    suppliers: dict[
        str,
        ProductSupplierInput,
    ]

    created_by: str

    status: ProductStatus = (
        ProductStatus.DRAFT
    )

    events: list[
        ProductEventResponse
    ] = field(default_factory=list)

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


def normalize_sku(value: str) -> str:
    return value.strip().upper()


def request_fingerprint(
    payload: ProductCreate,
) -> str:

    canonical = json.dumps(
        payload.model_dump(
            mode="json",
            exclude={"source_request_id"},
        ),
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def require_product_access(
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
            warehouse_id=None,
        ),
    )

    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail="Product catalog access denied",
        )

    # Product catalog is tenant-wide.
    # Restrict to tenant-wide principals.
    if principal.allowed_warehouse_ids is not None:
        raise HTTPException(
            status_code=403,
            detail="Tenant-wide catalog access required",
        )


def to_product(
    record: ProductRecord,
) -> ProductResponse:

    return ProductResponse(
        product_id=record.product_id,
        sku=record.sku,
        barcode=record.barcode,
        name=record.name,
        description=record.description,
        category_id=record.category_id,
        brand=record.brand,
        product_type=record.product_type,
        unit=record.unit,
        status=record.status,
        supplier_count=len(record.suppliers),
        specification_count=len(
            record.specifications
        ),
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def to_detail(
    record: ProductRecord,
) -> ProductDetailResponse:

    return ProductDetailResponse(
        **to_product(record).model_dump(),
        dimensions=record.dimensions,
        specifications=list(
            record.specifications
        ),
        attributes=dict(
            record.attributes
        ),
        suppliers=[
            ProductSupplierResponse(
                supplier_id=supplier.supplier_id,
                supplier_sku=supplier.supplier_sku,
                preferred=supplier.preferred,
            )
            for supplier in record.suppliers.values()
        ],
        events=list(record.events),
    )


# ============================================================
# PRODUCT STORE
# ============================================================

class ProductStore:

    def __init__(self):

        self._products: dict[
            str,
            ProductRecord,
        ] = {}

        self._sku_index: dict[
            tuple[str, str],
            str,
        ] = {}

        self._barcode_index: dict[
            tuple[str, str],
            str,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    def _get(
        self,
        principal: Principal,
        product_id: str,
        *,
        write: bool,
    ) -> ProductRecord:

        require_product_access(
            principal,
            write=write,
        )

        record = self._products.get(
            product_id
        )

        if (
            record is None
            or record.tenant_id
            != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Product not found",
            )

        return record

    @staticmethod
    def _check_version(
        record: ProductRecord,
        expected_version: int,
    ) -> None:

        if record.version != expected_version:
            raise HTTPException(
                status_code=409,
                detail="Product version conflict",
            )

    @staticmethod
    def _add_event(
        record: ProductRecord,
        event_type: ProductEventType,
        actor_id: str,
        details: str | None = None,
    ) -> None:

        record.events.append(
            ProductEventResponse(
                event_id=secrets.token_urlsafe(16),
                event_type=event_type,
                actor_id=actor_id,
                details=details,
                created_at=utc_now(),
            )
        )

    @staticmethod
    def _touch(
        record: ProductRecord,
    ) -> None:

        record.version += 1
        record.updated_at = utc_now()

    async def create(
        self,
        *,
        principal: Principal,
        payload: ProductCreate,
    ) -> ProductResponse:

        require_product_access(
            principal,
            write=True,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = request_fingerprint(
            payload
        )

        sku = normalize_sku(
            payload.sku
        )

        barcode = (
            payload.barcode.strip().upper()
            if payload.barcode
            else None
        )

        async with self._lock:

            previous = self._idempotency.get(
                key
            )

            if previous is not None:

                old_hash, product_id = previous

                if old_hash != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return to_product(
                    self._get(
                        principal,
                        product_id,
                        write=False,
                    )
                )

            sku_key = (
                principal.tenant_id,
                sku,
            )

            if sku_key in self._sku_index:
                raise HTTPException(
                    status_code=409,
                    detail="SKU already exists",
                )

            if barcode:

                barcode_key = (
                    principal.tenant_id,
                    barcode,
                )

                if barcode_key in self._barcode_index:
                    raise HTTPException(
                        status_code=409,
                        detail="Barcode already exists",
                    )

            tenant_count = sum(
                record.tenant_id
                == principal.tenant_id
                for record in self._products.values()
            )

            if (
                tenant_count
                >= MAX_PRODUCTS_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Product catalog capacity reached",
                )

            record = ProductRecord(
                product_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                sku=sku,
                barcode=barcode,
                name=payload.name,
                description=payload.description,
                category_id=payload.category_id,
                brand=payload.brand,
                product_type=payload.product_type,
                unit=payload.unit,
                dimensions=payload.dimensions,
                specifications=list(
                    payload.specifications
                ),
                attributes=dict(
                    payload.attributes
                ),
                suppliers={
                    item.supplier_id: item
                    for item in payload.suppliers
                },
                created_by=principal.principal_id,
            )

            self._add_event(
                record,
                ProductEventType.CREATED,
                principal.principal_id,
            )

            self._products[
                record.product_id
            ] = record

            self._sku_index[
                sku_key
            ] = record.product_id

            if barcode:

                self._barcode_index[
                    (
                        principal.tenant_id,
                        barcode,
                    )
                ] = record.product_id

            self._idempotency[key] = (
                request_hash,
                record.product_id,
            )

            return to_product(record)

    async def get(
        self,
        *,
        principal: Principal,
        product_id: str,
    ) -> ProductDetailResponse:

        async with self._lock:

            return to_detail(
                self._get(
                    principal,
                    product_id,
                    write=False,
                )
            )

    async def list_products(
        self,
        *,
        principal: Principal,
        search: str | None,
        category_id: str | None,
        status: ProductStatus | None,
        limit: int,
    ) -> list[ProductResponse]:

        require_product_access(
            principal,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._products.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and (
                        category_id is None
                        or record.category_id
                        == category_id
                    )
                    and (
                        status is None
                        or record.status == status
                    )
                )
            ]

            if search:

                query = search.casefold()

                records = [
                    record
                    for record in records
                    if (
                        query in record.name.casefold()
                        or query in record.sku.casefold()
                        or (
                            record.barcode is not None
                            and query
                            in record.barcode.casefold()
                        )
                    )
                ]

            records.sort(
                key=lambda item: item.created_at,
                reverse=True,
            )

            return [
                to_product(record)
                for record in records[:limit]
            ]

    async def update(
        self,
        *,
        principal: Principal,
        product_id: str,
        payload: ProductUpdate,
    ) -> ProductDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                product_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status == ProductStatus.ARCHIVED:
                raise HTTPException(
                    status_code=409,
                    detail="Archived products cannot be modified",
                )

            updates = payload.model_dump(
                exclude_unset=True,
                exclude={"expected_version"},
            )

            for field_name, value in updates.items():

                if field_name in {
                    "name",
                    "description",
                    "category_id",
                    "brand",
                    "dimensions",
                    "specifications",
                    "attributes",
                }:

                    setattr(
                        record,
                        field_name,
                        value,
                    )

            self._add_event(
                record,
                ProductEventType.UPDATED,
                principal.principal_id,
                "Product metadata updated",
            )

            self._touch(record)

            return to_detail(record)

    async def change_status(
        self,
        *,
        principal: Principal,
        product_id: str,
        payload: ProductStatusUpdate,
    ) -> ProductResponse:

        async with self._lock:

            record = self._get(
                principal,
                product_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status == ProductStatus.ARCHIVED:
                raise HTTPException(
                    status_code=409,
                    detail="Archived product is immutable",
                )

            allowed = {
                ProductStatus.DRAFT: {
                    ProductStatus.ACTIVE,
                    ProductStatus.INACTIVE,
                    ProductStatus.ARCHIVED,
                },
                ProductStatus.ACTIVE: {
                    ProductStatus.INACTIVE,
                    ProductStatus.DISCONTINUED,
                    ProductStatus.ARCHIVED,
                },
                ProductStatus.INACTIVE: {
                    ProductStatus.ACTIVE,
                    ProductStatus.DISCONTINUED,
                    ProductStatus.ARCHIVED,
                },
                ProductStatus.DISCONTINUED: {
                    ProductStatus.ARCHIVED,
                },
                ProductStatus.ARCHIVED: set(),
            }

            if payload.status not in allowed[record.status]:
                raise HTTPException(
                    status_code=409,
                    detail="Invalid product status transition",
                )

            self._add_event(
                record,
                (
                    ProductEventType.ARCHIVED
                    if payload.status
                    == ProductStatus.ARCHIVED
                    else ProductEventType.STATUS_CHANGED
                ),
                principal.principal_id,
                payload.reason,
            )

            record.status = payload.status

            self._touch(record)

            return to_product(record)

    async def add_supplier(
        self,
        *,
        principal: Principal,
        product_id: str,
        payload: ProductSupplierAdd,
    ) -> ProductDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                product_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status == ProductStatus.ARCHIVED:
                raise HTTPException(
                    status_code=409,
                    detail="Archived product is immutable",
                )

            supplier = payload.supplier

            if supplier.supplier_id in record.suppliers:
                raise HTTPException(
                    status_code=409,
                    detail="Supplier already associated",
                )

            if (
                len(record.suppliers)
                >= MAX_SUPPLIERS_PER_PRODUCT
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Supplier capacity reached",
                )

            if supplier.preferred and any(
                item.preferred
                for item in record.suppliers.values()
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Preferred supplier already exists",
                )

            self._add_event(
                record,
                ProductEventType.SUPPLIER_ADDED,
                principal.principal_id,
                supplier.supplier_id,
            )

            record.suppliers[
                supplier.supplier_id
            ] = supplier

            self._touch(record)

            return to_detail(record)

    async def remove_supplier(
        self,
        *,
        principal: Principal,
        product_id: str,
        supplier_id: str,
        expected_version: int,
    ) -> ProductDetailResponse:

        async with self._lock:

            record = self._get(
                principal,
                product_id,
                write=True,
            )

            self._check_version(
                record,
                expected_version,
            )

            if record.status == ProductStatus.ARCHIVED:
                raise HTTPException(
                    status_code=409,
                    detail="Archived product is immutable",
                )

            if supplier_id not in record.suppliers:
                raise HTTPException(
                    status_code=404,
                    detail="Supplier association not found",
                )

            self._add_event(
                record,
                ProductEventType.SUPPLIER_REMOVED,
                principal.principal_id,
                supplier_id,
            )

            del record.suppliers[supplier_id]

            self._touch(record)

            return to_detail(record)

    async def analytics(
        self,
        *,
        principal: Principal,
    ) -> ProductAnalyticsResponse:

        require_product_access(
            principal,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._products.values()
                if record.tenant_id
                == principal.tenant_id
            ]

            statuses = [
                record.status
                for record in records
            ]

            types = [
                record.product_type
                for record in records
            ]

            categories = {
                record.category_id
                for record in records
                if record.category_id
            }

            brands = {
                record.brand
                for record in records
                if record.brand
            }

            return ProductAnalyticsResponse(
                total_products=len(records),
                draft=statuses.count(
                    ProductStatus.DRAFT
                ),
                active=statuses.count(
                    ProductStatus.ACTIVE
                ),
                inactive=statuses.count(
                    ProductStatus.INACTIVE
                ),
                discontinued=statuses.count(
                    ProductStatus.DISCONTINUED
                ),
                archived=statuses.count(
                    ProductStatus.ARCHIVED
                ),
                physical_products=types.count(
                    ProductType.PHYSICAL
                ),
                digital_products=types.count(
                    ProductType.DIGITAL
                ),
                service_products=types.count(
                    ProductType.SERVICE
                ),
                bundles=types.count(
                    ProductType.BUNDLE
                ),
                products_with_suppliers=sum(
                    bool(record.suppliers)
                    for record in records
                ),
                products_without_suppliers=sum(
                    not record.suppliers
                    for record in records
                ),
                total_categories=len(categories),
                total_brands=len(brands),
            )


product_store = ProductStore()


# ============================================================
# SERVICE
# ============================================================

class ProductService:

    def __init__(
        self,
        store: ProductStore,
    ):
        self.store = store

    async def create(
        self,
        principal: Principal,
        payload: ProductCreate,
    ) -> ProductResponse:

        return await self.store.create(
            principal=principal,
            payload=payload,
        )


product_service = ProductService(
    product_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Product Management"],
)


@router.post(
    "",
    response_model=ProductResponse,
    status_code=201,
)
async def create_product(
    payload: ProductCreate,
    principal: CurrentPrincipal,
):
    return await product_service.create(
        principal,
        payload,
    )


@router.get(
    "",
    response_model=list[ProductResponse],
)
async def list_products(
    principal: CurrentPrincipal,
    search: str | None = Query(
        default=None,
        max_length=200,
    ),
    category_id: str | None = None,
    status: ProductStatus | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await product_store.list_products(
        principal=principal,
        search=search,
        category_id=category_id,
        status=status,
        limit=limit,
    )


@router.get(
    "/analytics",
    response_model=ProductAnalyticsResponse,
)
async def product_analytics(
    principal: CurrentPrincipal,
):
    return await product_store.analytics(
        principal=principal,
    )


@router.get(
    "/{product_id}",
    response_model=ProductDetailResponse,
)
async def get_product(
    product_id: str,
    principal: CurrentPrincipal,
):
    return await product_store.get(
        principal=principal,
        product_id=product_id,
    )


@router.patch(
    "/{product_id}",
    response_model=ProductDetailResponse,
)
async def update_product(
    product_id: str,
    payload: ProductUpdate,
    principal: CurrentPrincipal,
):
    return await product_store.update(
        principal=principal,
        product_id=product_id,
        payload=payload,
    )


@router.patch(
    "/{product_id}/status",
    response_model=ProductResponse,
)
async def change_product_status(
    product_id: str,
    payload: ProductStatusUpdate,
    principal: CurrentPrincipal,
):
    return await product_store.change_status(
        principal=principal,
        product_id=product_id,
        payload=payload,
    )


@router.post(
    "/{product_id}/suppliers",
    response_model=ProductDetailResponse,
)
async def add_product_supplier(
    product_id: str,
    payload: ProductSupplierAdd,
    principal: CurrentPrincipal,
):
    return await product_store.add_supplier(
        principal=principal,
        product_id=product_id,
        payload=payload,
    )


@router.delete(
    "/{product_id}/suppliers/{supplier_id}",
    response_model=ProductDetailResponse,
)
async def remove_product_supplier(
    product_id: str,
    supplier_id: str,
    payload: ProductSupplierRemove,
    principal: CurrentPrincipal,
):
    return await product_store.remove_supplier(
        principal=principal,
        product_id=product_id,
        supplier_id=supplier_id,
        expected_version=payload.expected_version,
    )


__all__ = [
    "ProductStatus",
    "ProductType",
    "ProductUnit",
    "ProductEventType",
    "ProductDimensions",
    "ProductSpecification",
    "ProductSupplierInput",
    "ProductCreate",
    "ProductUpdate",
    "ProductStatusUpdate",
    "ProductSupplierAdd",
    "ProductSupplierRemove",
    "ProductSupplierResponse",
    "ProductEventResponse",
    "ProductResponse",
    "ProductDetailResponse",
    "ProductAnalyticsResponse",
    "ProductStore",
    "ProductService",
    "product_store",
    "product_service",
    "router",
]
