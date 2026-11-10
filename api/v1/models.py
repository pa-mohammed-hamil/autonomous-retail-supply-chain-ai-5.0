from __future__ import annotations

"""Planned module: models. Implementation pending."""

"""
backend/models.py

Autonomous Retail Supply Chain AI 5.0
Central Business Models & Resource Registry

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Responsibilities:
    - Shared business data models
    - Resource type validation
    - Tenant-isolated registry
    - Warehouse-scoped access
    - Resource creation and updates
    - Optimistic concurrency
    - Idempotent resource creation
    - Soft archival
    - Resource listing and statistics

This is a metadata registry, not a replacement for
the authoritative inventory, procurement, order,
warehouse, logistics, or MLOps databases.
"""


import asyncio
import hashlib
import json
import secrets

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from fastapi import APIRouter, HTTPException, Query

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


API_PREFIX = "/api/v1/models"

MAX_RESOURCES_PER_TENANT = 50000
MAX_IDEMPOTENCY_KEYS = 100000
MAX_LIST_LIMIT = 200
MAX_ATTRIBUTES = 40
MAX_ATTRIBUTES_JSON_BYTES = 12000


# ============================================================
# ENUMS
# ============================================================

class ResourceType(str, Enum):
    PRODUCT = "product"
    CATEGORY = "category"
    WAREHOUSE = "warehouse"
    SUPPLIER = "supplier"
    INVENTORY = "inventory"
    PURCHASE_ORDER = "purchase_order"
    SALES_ORDER = "sales_order"
    SHIPMENT = "shipment"
    DELIVERY = "delivery"
    FLEET_VEHICLE = "fleet_vehicle"
    AI_MODEL = "ai_model"
    DATASET = "dataset"


class ResourceStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class CurrencyCode(str, Enum):
    INR = "INR"
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    AED = "AED"


# ============================================================
# SHARED BUSINESS SCHEMAS
# ============================================================

class Money(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal = Field(
        ge=0,
        max_digits=14,
        decimal_places=2,
    )

    currency: CurrencyCode = CurrencyCode.INR


class ProductModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=128)
    sku: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    category_id: str = Field(min_length=1, max_length=128)

    selling_price: Money
    cost_price: Money | None = None

    active: bool = True


class WarehouseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=2, max_length=200)
    location_reference: str = Field(
        min_length=1,
        max_length=300,
    )

    capacity_units: int = Field(ge=0)
    active: bool = True


class SupplierModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=2, max_length=200)
    contact_reference: str | None = Field(
        default=None,
        max_length=200,
    )

    lead_time_days: int = Field(ge=0, le=365)
    active: bool = True


class InventoryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(min_length=1, max_length=128)
    product_id: str = Field(min_length=1, max_length=128)

    on_hand: int = Field(ge=0)
    reserved: int = Field(ge=0)

    reorder_point: int = Field(ge=0)
    safety_stock: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_stock(self):

        if self.reserved > self.on_hand:
            raise ValueError(
                "Reserved stock cannot exceed on-hand stock"
            )

        return self

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved


class OrderLineModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=128)
    quantity: int = Field(gt=0, le=100000)
    unit_price: Money


class SalesOrderModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=128)
    warehouse_id: str = Field(min_length=1, max_length=128)
    customer_reference: str = Field(
        min_length=1,
        max_length=200,
    )

    lines: list[OrderLineModel] = Field(
        min_length=1,
        max_length=100,
    )

    @model_validator(mode="after")
    def validate_lines(self):

        product_ids = [
            line.product_id
            for line in self.lines
        ]

        if len(product_ids) != len(set(product_ids)):
            raise ValueError(
                "Duplicate order products are not allowed"
            )

        currencies = {
            line.unit_price.currency
            for line in self.lines
        }

        if len(currencies) != 1:
            raise ValueError(
                "Order lines must share one currency"
            )

        return self


class ShipmentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shipment_id: str = Field(min_length=1, max_length=128)
    order_id: str = Field(min_length=1, max_length=128)
    warehouse_id: str = Field(min_length=1, max_length=128)

    carrier_reference: str | None = None
    tracking_reference: str | None = None

    expected_delivery_at: datetime | None = None


class AIModelReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, max_length=128)
    model_version_id: str = Field(min_length=1, max_length=128)

    artifact_reference: str = Field(
        min_length=3,
        max_length=500,
    )

    framework: str = Field(
        min_length=1,
        max_length=100,
    )

    task_type: str = Field(
        min_length=1,
        max_length=100,
    )


# ============================================================
# REGISTRY REQUESTS
# ============================================================

class ResourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_type: ResourceType

    external_id: str = Field(
        min_length=1,
        max_length=128,
    )

    name: str = Field(
        min_length=2,
        max_length=200,
    )

    warehouse_id: str | None = Field(
        default=None,
        max_length=128,
    )

    attributes: dict[str, Any] = Field(
        default_factory=dict,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_attributes(self):

        validate_attributes(self.attributes)

        return self


class ResourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    name: str | None = Field(
        default=None,
        min_length=2,
        max_length=200,
    )

    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_update(self):

        if (
            self.name is None
            and self.attributes is None
        ):
            raise ValueError(
                "At least one field must be updated"
            )

        if self.attributes is not None:
            validate_attributes(self.attributes)

        return self


class ResourceStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    status: ResourceStatus


# ============================================================
# RESPONSES
# ============================================================

class ResourceResponse(BaseModel):
    resource_id: str
    external_id: str

    resource_type: ResourceType
    name: str

    warehouse_id: str | None
    attributes: dict[str, Any]

    status: ResourceStatus

    version: int

    created_by: str
    created_at: datetime
    updated_at: datetime


class ResourceStatistics(BaseModel):
    total_resources: int
    active_resources: int
    inactive_resources: int
    archived_resources: int

    by_type: dict[str, int]


class ModelCatalogResponse(BaseModel):
    resource_types: list[ResourceType]
    statuses: list[ResourceStatus]
    supported_business_schemas: list[str]


# ============================================================
# INTERNAL RECORD
# ============================================================

@dataclass
class ResourceRecord:
    resource_id: str
    tenant_id: str

    external_id: str
    resource_type: ResourceType

    name: str
    warehouse_id: str | None

    attributes: dict[str, Any]

    created_by: str

    status: ResourceStatus = ResourceStatus.ACTIVE
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


def validate_attributes(
    attributes: dict[str, Any],
) -> None:

    if len(attributes) > MAX_ATTRIBUTES:
        raise ValueError(
            "Too many resource attributes"
        )

    for key in attributes:
        if not key or len(key) > 100:
            raise ValueError(
                "Invalid attribute name"
            )

    try:
        serialized = json.dumps(
            attributes,
            allow_nan=False,
        )

    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Attributes must contain valid JSON values"
        ) from exc

    if (
        len(serialized.encode("utf-8"))
        > MAX_ATTRIBUTES_JSON_BYTES
    ):
        raise ValueError(
            "Resource attributes exceed size limit"
        )


def fingerprint(
    payload: ResourceCreate,
) -> str:

    canonical = json.dumps(
        payload.model_dump(
            mode="json",
            exclude={"source_request_id"},
        ),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def require_model_access(
    principal: Principal,
    warehouse_id: str | None,
    *,
    write: bool,
) -> None:

    # Dedicated MODEL_REGISTRY_READ/WRITE
    # permissions are recommended.
    #
    # Current prototype uses PRODUCT_READ/WRITE.

    permission = (
        Permission.PRODUCT_WRITE
        if write
        else Permission.PRODUCT_READ
    )

    if warehouse_id is None:

        if principal.allowed_warehouse_ids is not None:
            raise HTTPException(
                status_code=403,
                detail="Global resource access denied",
            )

    elif (
        principal.allowed_warehouse_ids is not None
        and warehouse_id
        not in principal.allowed_warehouse_ids
    ):
        raise HTTPException(
            status_code=403,
            detail="Warehouse access denied",
        )

    decision = permission_engine.evaluate(
        principal,
        permission,
        ResourceContext(
            tenant_id=principal.tenant_id,
            warehouse_id=warehouse_id,
        ),
    )

    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail="Model registry access denied",
        )


def to_response(
    record: ResourceRecord,
) -> ResourceResponse:

    return ResourceResponse(
        resource_id=record.resource_id,
        external_id=record.external_id,
        resource_type=record.resource_type,
        name=record.name,
        warehouse_id=record.warehouse_id,
        attributes=json.loads(
            json.dumps(record.attributes)
        ),
        status=record.status,
        version=record.version,
        created_by=record.created_by,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


# ============================================================
# RESOURCE REGISTRY
# ============================================================

class ResourceRegistryStore:

    def __init__(self):

        self._records: dict[
            str, ResourceRecord
        ] = {}

        self._external_index: dict[
            tuple[str, ResourceType, str],
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
        resource_id: str,
        *,
        write: bool,
    ) -> ResourceRecord:

        record = self._records.get(
            resource_id
        )

        if (
            record is None
            or record.tenant_id
            != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Resource not found",
            )

        require_model_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    @staticmethod
    def _check_version(
        record: ResourceRecord,
        expected_version: int,
    ) -> None:

        if record.version != expected_version:
            raise HTTPException(
                status_code=409,
                detail="Resource version conflict",
            )

    async def create(
        self,
        *,
        principal: Principal,
        payload: ResourceCreate,
    ) -> ResourceResponse:

        require_model_access(
            principal,
            payload.warehouse_id,
            write=True,
        )

        idempotency_key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = fingerprint(payload)

        external_key = (
            principal.tenant_id,
            payload.resource_type,
            payload.external_id,
        )

        async with self._lock:

            previous = self._idempotency.get(
                idempotency_key
            )

            if previous is not None:

                old_hash, resource_id = previous

                if old_hash != request_hash:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return to_response(
                    self._get(
                        principal,
                        resource_id,
                        write=False,
                    )
                )

            if external_key in self._external_index:
                raise HTTPException(
                    status_code=409,
                    detail="External resource already registered",
                )

            tenant_count = sum(
                record.tenant_id
                == principal.tenant_id
                for record in self._records.values()
            )

            if (
                tenant_count >= MAX_RESOURCES_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Resource registry capacity reached",
                )

            record = ResourceRecord(
                resource_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                external_id=payload.external_id,
                resource_type=payload.resource_type,
                name=payload.name,
                warehouse_id=payload.warehouse_id,
                attributes=json.loads(
                    json.dumps(payload.attributes)
                ),
                created_by=principal.principal_id,
            )

            self._records[
                record.resource_id
            ] = record

            self._external_index[
                external_key
            ] = record.resource_id

            self._idempotency[
                idempotency_key
            ] = (
                request_hash,
                record.resource_id,
            )

            return to_response(record)

    async def get(
        self,
        *,
        principal: Principal,
        resource_id: str,
    ) -> ResourceResponse:

        async with self._lock:

            return to_response(
                self._get(
                    principal,
                    resource_id,
                    write=False,
                )
            )

    async def list_records(
        self,
        *,
        principal: Principal,
        resource_type: ResourceType | None,
        warehouse_id: str | None,
        status: ResourceStatus | None,
        limit: int,
    ) -> list[ResourceResponse]:

        if warehouse_id is not None:
            require_model_access(
                principal,
                warehouse_id,
                write=False,
            )

        async with self._lock:

            records = [
                record
                for record in self._records.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and (
                        resource_type is None
                        or record.resource_type
                        == resource_type
                    )
                    and (
                        warehouse_id is None
                        or record.warehouse_id
                        == warehouse_id
                    )
                    and (
                        status is None
                        or record.status == status
                    )
                )
            ]

            records.sort(
                key=lambda item: item.created_at,
                reverse=True,
            )

            results = []

            for record in records:

                try:
                    require_model_access(
                        principal,
                        record.warehouse_id,
                        write=False,
                    )

                except HTTPException:
                    continue

                results.append(
                    to_response(record)
                )

                if len(results) >= limit:
                    break

            return results

    async def update(
        self,
        *,
        principal: Principal,
        resource_id: str,
        payload: ResourceUpdate,
    ) -> ResourceResponse:

        async with self._lock:

            record = self._get(
                principal,
                resource_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if record.status == ResourceStatus.ARCHIVED:
                raise HTTPException(
                    status_code=409,
                    detail="Archived resources cannot be updated",
                )

            if payload.name is not None:
                record.name = payload.name

            if payload.attributes is not None:
                record.attributes = json.loads(
                    json.dumps(payload.attributes)
                )

            record.version += 1
            record.updated_at = utc_now()

            return to_response(record)

    async def update_status(
        self,
        *,
        principal: Principal,
        resource_id: str,
        payload: ResourceStatusUpdate,
    ) -> ResourceResponse:

        async with self._lock:

            record = self._get(
                principal,
                resource_id,
                write=True,
            )

            self._check_version(
                record,
                payload.expected_version,
            )

            if (
                record.status == ResourceStatus.ARCHIVED
                and payload.status
                != ResourceStatus.ARCHIVED
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Archived resources are terminal",
                )

            if record.status == payload.status:
                raise HTTPException(
                    status_code=409,
                    detail="Resource already has this status",
                )

            record.status = payload.status
            record.version += 1
            record.updated_at = utc_now()

            return to_response(record)

    async def statistics(
        self,
        *,
        principal: Principal,
    ) -> ResourceStatistics:

        async with self._lock:

            visible = []

            for record in self._records.values():

                if (
                    record.tenant_id
                    != principal.tenant_id
                ):
                    continue

                try:
                    require_model_access(
                        principal,
                        record.warehouse_id,
                        write=False,
                    )

                except HTTPException:
                    continue

                visible.append(record)

            by_type = {
                item.value: sum(
                    record.resource_type == item
                    for record in visible
                )
                for item in ResourceType
            }

            return ResourceStatistics(
                total_resources=len(visible),
                active_resources=sum(
                    record.status
                    == ResourceStatus.ACTIVE
                    for record in visible
                ),
                inactive_resources=sum(
                    record.status
                    == ResourceStatus.INACTIVE
                    for record in visible
                ),
                archived_resources=sum(
                    record.status
                    == ResourceStatus.ARCHIVED
                    for record in visible
                ),
                by_type=by_type,
            )


resource_registry_store = ResourceRegistryStore()


# ============================================================
# SERVICE
# ============================================================

class ResourceRegistryService:

    def __init__(
        self,
        store: ResourceRegistryStore,
    ):
        self.store = store

    async def register(
        self,
        principal: Principal,
        payload: ResourceCreate,
    ) -> ResourceResponse:

        return await self.store.create(
            principal=principal,
            payload=payload,
        )


resource_registry_service = ResourceRegistryService(
    resource_registry_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Business Models Registry"],
)


@router.get(
    "/catalog",
    response_model=ModelCatalogResponse,
)
async def get_model_catalog(
    principal: CurrentPrincipal,
):

    require_model_access(
        principal,
        None,
        write=False,
    )

    return ModelCatalogResponse(
        resource_types=list(ResourceType),
        statuses=list(ResourceStatus),
        supported_business_schemas=[
            "Money",
            "ProductModel",
            "WarehouseModel",
            "SupplierModel",
            "InventoryModel",
            "OrderLineModel",
            "SalesOrderModel",
            "ShipmentModel",
            "AIModelReference",
        ],
    )


@router.post(
    "",
    response_model=ResourceResponse,
    status_code=201,
)
async def register_resource(
    payload: ResourceCreate,
    principal: CurrentPrincipal,
):
    return await resource_registry_service.register(
        principal,
        payload,
    )


@router.get(
    "",
    response_model=list[ResourceResponse],
)
async def list_resources(
    principal: CurrentPrincipal,
    resource_type: ResourceType | None = None,
    warehouse_id: str | None = None,
    status: ResourceStatus | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await resource_registry_store.list_records(
        principal=principal,
        resource_type=resource_type,
        warehouse_id=warehouse_id,
        status=status,
        limit=limit,
    )


@router.get(
    "/statistics",
    response_model=ResourceStatistics,
)
async def resource_statistics(
    principal: CurrentPrincipal,
):
    return await resource_registry_store.statistics(
        principal=principal,
    )


@router.get(
    "/{resource_id}",
    response_model=ResourceResponse,
)
async def get_resource(
    resource_id: str,
    principal: CurrentPrincipal,
):
    return await resource_registry_store.get(
        principal=principal,
        resource_id=resource_id,
    )


@router.patch(
    "/{resource_id}",
    response_model=ResourceResponse,
)
async def update_resource(
    resource_id: str,
    payload: ResourceUpdate,
    principal: CurrentPrincipal,
):
    return await resource_registry_store.update(
        principal=principal,
        resource_id=resource_id,
        payload=payload,
    )


@router.patch(
    "/{resource_id}/status",
    response_model=ResourceResponse,
)
async def update_resource_status(
    resource_id: str,
    payload: ResourceStatusUpdate,
    principal: CurrentPrincipal,
):
    return await resource_registry_store.update_status(
        principal=principal,
        resource_id=resource_id,
        payload=payload,
    )


__all__ = [
    "ResourceType",
    "ResourceStatus",
    "CurrencyCode",
    "Money",
    "ProductModel",
    "WarehouseModel",
    "SupplierModel",
    "InventoryModel",
    "OrderLineModel",
    "SalesOrderModel",
    "ShipmentModel",
    "AIModelReference",
    "ResourceCreate",
    "ResourceUpdate",
    "ResourceStatusUpdate",
    "ResourceResponse",
    "ResourceStatistics",
    "ModelCatalogResponse",
    "ResourceRegistryStore",
    "ResourceRegistryService",
    "resource_registry_store",
    "resource_registry_service",
    "router",
]
