from __future__ import annotations

"""Planned module: suppliers. Implementation pending."""

"""
backend/api/v1/suppliers.py

Supplier Management API
Autonomous Retail Supply Chain AI 5.0

Dependencies:
    FastAPI
    SQLAlchemy 2.0
    Pydantic v2
    AsyncSession

Uses existing:
    backend.models.supplier.Supplier
    backend.database.session.get_db

Expected Supplier model fields:
    id, organization_id, code, name, email, phone,
    country, city, address, status, category,
    payment_terms, lead_time_days, rating,
    total_orders, on_time_orders, defective_orders,
    created_at, updated_at

Important:
    Replace get_current_organization_id with your
    actual authenticated tenant dependency.
"""


from datetime import datetime
from enum import Enum
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    model_validator,
)
from sqlalchemy import (
    func,
    or_,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.session import get_db
from backend.models.supplier import Supplier

# Implement this dependency in your authentication layer.
from backend.api.dependencies import (
    get_current_organization_id,
)


router = APIRouter(
    prefix="/suppliers",
    tags=["Supplier Management"],
)

DBSession = Annotated[
    AsyncSession,
    Depends(get_db),
]

OrganizationId = Annotated[
    str,
    Depends(get_current_organization_id),
]


# ============================================================
# ENUMS
# ============================================================

class SupplierStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    UNDER_REVIEW = "under_review"
    BLACKLISTED = "blacklisted"


class SupplierCategory(str, Enum):
    MANUFACTURER = "manufacturer"
    DISTRIBUTOR = "distributor"
    WHOLESALER = "wholesaler"
    LOGISTICS = "logistics"
    RAW_MATERIAL = "raw_material"
    SERVICE_PROVIDER = "service_provider"
    OTHER = "other"


# ============================================================
# REQUEST SCHEMAS
# ============================================================

class SupplierCreate(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True
    )

    code: str = Field(
        min_length=2,
        max_length=50,
    )

    name: str = Field(
        min_length=2,
        max_length=200,
    )

    email: EmailStr | None = None
    phone: str | None = Field(
        default=None,
        max_length=30,
    )

    country: str = Field(
        default="India",
        max_length=100,
    )

    city: str | None = None
    address: str | None = None

    category: SupplierCategory = (
        SupplierCategory.MANUFACTURER
    )

    payment_terms: str | None = None

    lead_time_days: int = Field(
        default=7,
        ge=0,
        le=3650,
    )


class SupplierUpdate(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True
    )

    name: str | None = Field(
        default=None,
        min_length=2,
        max_length=200,
    )

    email: EmailStr | None = None
    phone: str | None = None
    country: str | None = None
    city: str | None = None
    address: str | None = None
    category: SupplierCategory | None = None
    payment_terms: str | None = None

    lead_time_days: int | None = Field(
        default=None,
        ge=0,
        le=3650,
    )


class SupplierStatusUpdate(BaseModel):
    status: SupplierStatus
    reason: str | None = Field(
        default=None,
        max_length=1000,
    )


class SupplierPerformanceUpdate(BaseModel):
    total_orders: int = Field(ge=0)
    on_time_orders: int = Field(ge=0)
    defective_orders: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self):
        if self.on_time_orders > self.total_orders:
            raise ValueError(
                "On-time orders cannot exceed total orders"
            )

        if self.defective_orders > self.total_orders:
            raise ValueError(
                "Defective orders cannot exceed total orders"
            )

        return self


# ============================================================
# RESPONSE SCHEMAS
# ============================================================

class SupplierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    code: str
    name: str

    email: EmailStr | None
    phone: str | None

    country: str
    city: str | None
    address: str | None

    category: str
    status: str

    payment_terms: str | None
    lead_time_days: int

    rating: float

    total_orders: int
    on_time_orders: int
    defective_orders: int

    created_at: datetime
    updated_at: datetime


class SupplierPerformanceResponse(BaseModel):
    supplier_id: str
    supplier_name: str
    total_orders: int
    on_time_orders: int
    defective_orders: int
    on_time_delivery_rate: float
    defect_rate: float
    reliability_score: float
    rating: float


class SupplierSummaryResponse(BaseModel):
    total_suppliers: int
    active_suppliers: int
    inactive_suppliers: int
    suspended_suppliers: int
    under_review_suppliers: int
    blacklisted_suppliers: int
    average_rating: float
    average_reliability: float


class SupplierListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    suppliers: list[SupplierResponse]


# ============================================================
# HELPERS
# ============================================================

async def get_supplier_or_404(
    db: AsyncSession,
    supplier_id: str,
    organization_id: str,
    *,
    lock: bool = False,
) -> Supplier:

    statement = select(Supplier).where(
        Supplier.id == supplier_id,
        Supplier.organization_id == organization_id,
    )

    if lock:
        statement = statement.with_for_update()

    supplier = await db.scalar(statement)

    if supplier is None:
        raise HTTPException(
            status_code=404,
            detail="Supplier not found",
        )

    return supplier


def calculate_performance(
    supplier: Supplier,
) -> SupplierPerformanceResponse:

    total = supplier.total_orders or 0
    on_time = supplier.on_time_orders or 0
    defective = supplier.defective_orders or 0

    if total > 0:
        delivery_rate = on_time / total * 100
        defect_rate = defective / total * 100
    else:
        delivery_rate = 0.0
        defect_rate = 0.0

    # Explainable heuristic, not an ML prediction.
    reliability = (
        delivery_rate * 0.8
        + (100 - defect_rate) * 0.2
        if total > 0
        else 0.0
    )

    return SupplierPerformanceResponse(
        supplier_id=supplier.id,
        supplier_name=supplier.name,
        total_orders=total,
        on_time_orders=on_time,
        defective_orders=defective,
        on_time_delivery_rate=round(
            delivery_rate, 2
        ),
        defect_rate=round(defect_rate, 2),
        reliability_score=round(
            reliability, 2
        ),
        rating=float(supplier.rating or 0),
    )


async def commit_and_refresh(
    db: AsyncSession,
    supplier: Supplier,
) -> Supplier:

    try:
        await db.commit()
        await db.refresh(supplier)
        return supplier

    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Supplier data conflicts with an existing record",
        ) from exc


# ============================================================
# CREATE SUPPLIER
# ============================================================

@router.post(
    "/",
    response_model=SupplierResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_supplier(
    payload: SupplierCreate,
    db: DBSession,
    organization_id: OrganizationId,
):

    existing = await db.scalar(
        select(Supplier).where(
            Supplier.organization_id == organization_id,
            Supplier.code == payload.code,
        )
    )

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Supplier code already exists",
        )

    supplier = Supplier(
        organization_id=organization_id,
        **payload.model_dump(mode="json"),
        status=SupplierStatus.ACTIVE.value,
        rating=0.0,
        total_orders=0,
        on_time_orders=0,
        defective_orders=0,
    )

    db.add(supplier)

    return await commit_and_refresh(
        db,
        supplier,
    )


# ============================================================
# LIST / SEARCH SUPPLIERS
# ============================================================

@router.get(
    "/",
    response_model=SupplierListResponse,
)
async def list_suppliers(
    db: DBSession,
    organization_id: OrganizationId,
    search: str | None = Query(
        default=None,
        max_length=200,
    ),
    supplier_status: SupplierStatus | None = None,
    category: SupplierCategory | None = None,
    country: str | None = None,
    city: str | None = None,
    min_rating: float | None = Query(
        default=None,
        ge=0,
        le=5,
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):

    filters = [
        Supplier.organization_id == organization_id
    ]

    if search:
        term = f"%{search}%"
        filters.append(
            or_(
                Supplier.name.ilike(term),
                Supplier.code.ilike(term),
            )
        )

    if supplier_status:
        filters.append(
            Supplier.status == supplier_status.value
        )

    if category:
        filters.append(
            Supplier.category == category.value
        )

    if country:
        filters.append(
            Supplier.country == country
        )

    if city:
        filters.append(
            Supplier.city == city
        )

    if min_rating is not None:
        filters.append(
            Supplier.rating >= min_rating
        )

    total = await db.scalar(
        select(func.count(Supplier.id)).where(
            *filters
        )
    )

    result = await db.scalars(
        select(Supplier)
        .where(*filters)
        .order_by(Supplier.name, Supplier.id)
        .offset(offset)
        .limit(limit)
    )

    return SupplierListResponse(
        total=total or 0,
        limit=limit,
        offset=offset,
        suppliers=list(result.all()),
    )


# ============================================================
# SUPPLIER SUMMARY
# ============================================================

@router.get(
    "/summary",
    response_model=SupplierSummaryResponse,
)
async def supplier_summary(
    db: DBSession,
    organization_id: OrganizationId,
):

    result = await db.scalars(
        select(Supplier).where(
            Supplier.organization_id == organization_id
        )
    )

    suppliers = list(result.all())

    total = len(suppliers)

    reliabilities = [
        calculate_performance(s).reliability_score
        for s in suppliers
        if (s.total_orders or 0) > 0
    ]

    average_reliability = (
        sum(reliabilities) / len(reliabilities)
        if reliabilities
        else 0.0
    )

    average_rating = (
        sum(float(s.rating or 0) for s in suppliers)
        / total
        if total
        else 0.0
    )

    return SupplierSummaryResponse(
        total_suppliers=total,
        active_suppliers=sum(
            s.status == SupplierStatus.ACTIVE.value
            for s in suppliers
        ),
        inactive_suppliers=sum(
            s.status == SupplierStatus.INACTIVE.value
            for s in suppliers
        ),
        suspended_suppliers=sum(
            s.status == SupplierStatus.SUSPENDED.value
            for s in suppliers
        ),
        under_review_suppliers=sum(
            s.status == SupplierStatus.UNDER_REVIEW.value
            for s in suppliers
        ),
        blacklisted_suppliers=sum(
            s.status == SupplierStatus.BLACKLISTED.value
            for s in suppliers
        ),
        average_rating=round(average_rating, 2),
        average_reliability=round(
            average_reliability, 2
        ),
    )


# ============================================================
# SUPPLIER RANKINGS
# ============================================================

@router.get(
    "/rankings",
    response_model=list[SupplierPerformanceResponse],
)
async def rank_suppliers(
    db: DBSession,
    organization_id: OrganizationId,
    limit: int = Query(20, ge=1, le=100),
):

    result = await db.scalars(
        select(Supplier).where(
            Supplier.organization_id == organization_id,
            Supplier.status == SupplierStatus.ACTIVE.value,
        )
    )

    suppliers = [
        calculate_performance(s)
        for s in result.all()
        if (s.total_orders or 0) > 0
    ]

    suppliers.sort(
        key=lambda s: (
            s.reliability_score,
            s.on_time_delivery_rate,
            -s.defect_rate,
        ),
        reverse=True,
    )

    return suppliers[:limit]


# ============================================================
# SUPPLIER DETAILS
# ============================================================

@router.get(
    "/{supplier_id}",
    response_model=SupplierResponse,
)
async def get_supplier(
    supplier_id: str,
    db: DBSession,
    organization_id: OrganizationId,
):

    return await get_supplier_or_404(
        db,
        supplier_id,
        organization_id,
    )


# ============================================================
# UPDATE SUPPLIER
# ============================================================

@router.patch(
    "/{supplier_id}",
    response_model=SupplierResponse,
)
async def update_supplier(
    supplier_id: str,
    payload: SupplierUpdate,
    db: DBSession,
    organization_id: OrganizationId,
):

    supplier = await get_supplier_or_404(
        db,
        supplier_id,
        organization_id,
        lock=True,
    )

    changes = payload.model_dump(
        exclude_unset=True,
        mode="json",
    )

    for field, value in changes.items():
        setattr(supplier, field, value)

    return await commit_and_refresh(
        db,
        supplier,
    )


# ============================================================
# UPDATE SUPPLIER STATUS
# ============================================================

@router.patch(
    "/{supplier_id}/status",
    response_model=SupplierResponse,
)
async def update_supplier_status(
    supplier_id: str,
    payload: SupplierStatusUpdate,
    db: DBSession,
    organization_id: OrganizationId,
):

    supplier = await get_supplier_or_404(
        db,
        supplier_id,
        organization_id,
        lock=True,
    )

    supplier.status = payload.status.value

    # Persist payload.reason in the audit-log service
    # when integrating this route into production.

    return await commit_and_refresh(
        db,
        supplier,
    )


# ============================================================
# UPDATE PERFORMANCE METRICS
# ============================================================

@router.put(
    "/{supplier_id}/performance",
    response_model=SupplierPerformanceResponse,
)
async def update_supplier_performance(
    supplier_id: str,
    payload: SupplierPerformanceUpdate,
    db: DBSession,
    organization_id: OrganizationId,
):

    supplier = await get_supplier_or_404(
        db,
        supplier_id,
        organization_id,
        lock=True,
    )

    supplier.total_orders = payload.total_orders
    supplier.on_time_orders = payload.on_time_orders
    supplier.defective_orders = payload.defective_orders

    await commit_and_refresh(
        db,
        supplier,
    )

    return calculate_performance(supplier)


# ============================================================
# GET PERFORMANCE
# ============================================================

@router.get(
    "/{supplier_id}/performance",
    response_model=SupplierPerformanceResponse,
)
async def get_supplier_performance(
    supplier_id: str,
    db: DBSession,
    organization_id: OrganizationId,
):

    supplier = await get_supplier_or_404(
        db,
        supplier_id,
        organization_id,
    )

    return calculate_performance(supplier)


# ============================================================
# SUPPLIER RECOMMENDATIONS
# ============================================================

@router.get(
    "/{supplier_id}/recommendations",
)
async def supplier_recommendations(
    supplier_id: str,
    db: DBSession,
    organization_id: OrganizationId,
):

    supplier = await get_supplier_or_404(
        db,
        supplier_id,
        organization_id,
    )

    performance = calculate_performance(supplier)

    recommendations = []

    if performance.total_orders == 0:
        recommendations.append(
            "Collect delivery history before "
            "evaluating supplier reliability."
        )

    if performance.on_time_delivery_rate < 85:
        recommendations.append(
            "Review delivery delays and "
            "supplier lead times."
        )

    if performance.defect_rate > 5:
        recommendations.append(
            "Increase quality inspection frequency."
        )

    if supplier.lead_time_days > 30:
        recommendations.append(
            "Consider backup suppliers with "
            "shorter lead times."
        )

    if supplier.status != SupplierStatus.ACTIVE.value:
        recommendations.append(
            "Review supplier status before "
            "placing new purchase orders."
        )

    if not recommendations:
        recommendations.append(
            "Continue routine supplier monitoring."
        )

    return {
        "supplier_id": supplier.id,
        "supplier_name": supplier.name,
        "reliability_score": performance.reliability_score,
        "recommendations": recommendations,
    }


# ============================================================
# DELETE SUPPLIER
# ============================================================

@router.delete(
    "/{supplier_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_supplier(
    supplier_id: str,
    db: DBSession,
    organization_id: OrganizationId,
):

    supplier = await get_supplier_or_404(
        db,
        supplier_id,
        organization_id,
        lock=True,
    )

    # Prefer deactivation for suppliers referenced by
    # purchase orders, contracts, or risk assessments.
    # Database FK constraints may reject this deletion.
    await db.delete(supplier)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "Supplier has related records. "
                "Deactivate instead of deleting."
            ),
        ) from exc

    return Response(
        status_code=status.HTTP_204_NO_CONTENT
    )
