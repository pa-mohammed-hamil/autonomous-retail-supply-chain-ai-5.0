from __future__ import annotations

"""Planned module: warehouses. Implementation pending."""

"""
backend/api/v1/warehouses.py

Autonomous Retail Supply Chain AI 5.0
Warehouse Management REST API

Requires:
    fastapi
    sqlalchemy[asyncio]
    pydantic>=2

Endpoints:
    POST   /warehouses/
    GET    /warehouses/
    GET    /warehouses/summary
    GET    /warehouses/available
    GET    /warehouses/{warehouse_id}
    PATCH  /warehouses/{warehouse_id}
    DELETE /warehouses/{warehouse_id}
    POST   /warehouses/{warehouse_id}/allocate
    POST   /warehouses/{warehouse_id}/release
    GET    /warehouses/{warehouse_id}/capacity
    GET    /warehouses/{warehouse_id}/analytics
    PATCH  /warehouses/{warehouse_id}/status
"""


from datetime import datetime, timezone
from enum import Enum
from typing import Annotated
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    select,
    func,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.session import get_db
from backend.models.base import Base


router = APIRouter(
    prefix="/warehouses",
    tags=["Warehouse Management"],
)


# ============================================================
# ENUMS
# ============================================================

class WarehouseStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"
    FULL = "full"


class WarehouseType(str, Enum):
    DISTRIBUTION = "distribution"
    FULFILLMENT = "fulfillment"
    COLD_STORAGE = "cold_storage"
    REGIONAL = "regional"
    CENTRAL = "central"
    AUTOMATED = "automated"


# ============================================================
# DATABASE MODEL
# Move to backend/models/warehouse.py in production.
# ============================================================

class Warehouse(Base):
    __tablename__ = "warehouses"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    organization_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
    )

    code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    warehouse_type: Mapped[str] = mapped_column(
        String(50),
        default=WarehouseType.DISTRIBUTION.value,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        default=WarehouseStatus.ACTIVE.value,
    )

    country: Mapped[str] = mapped_column(
        String(100),
        default="India",
    )

    state: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    city: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    address: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    latitude: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    longitude: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    total_capacity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    used_capacity: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    manager_name: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    contact_email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


# ============================================================
# PYDANTIC SCHEMAS
# ============================================================

class WarehouseCreate(BaseModel):
    organization_id: str = Field(min_length=1)
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=2, max_length=200)

    warehouse_type: WarehouseType = (
        WarehouseType.DISTRIBUTION
    )

    country: str = "India"
    state: str | None = None
    city: str | None = None
    address: str | None = None

    latitude: float | None = Field(
        default=None,
        ge=-90,
        le=90,
    )

    longitude: float | None = Field(
        default=None,
        ge=-180,
        le=180,
    )

    total_capacity: int = Field(gt=0)
    manager_name: str | None = None
    contact_email: str | None = None


class WarehouseUpdate(BaseModel):
    name: str | None = Field(
        default=None,
        min_length=2,
        max_length=200,
    )

    warehouse_type: WarehouseType | None = None
    country: str | None = None
    state: str | None = None
    city: str | None = None
    address: str | None = None

    latitude: float | None = Field(
        default=None,
        ge=-90,
        le=90,
    )

    longitude: float | None = Field(
        default=None,
        ge=-180,
        le=180,
    )

    total_capacity: int | None = Field(
        default=None,
        gt=0,
    )

    manager_name: str | None = None
    contact_email: str | None = None


class WarehouseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    code: str
    name: str
    warehouse_type: str
    status: str

    country: str
    state: str | None
    city: str | None
    address: str | None

    latitude: float | None
    longitude: float | None

    total_capacity: int
    used_capacity: int

    manager_name: str | None
    contact_email: str | None

    created_at: datetime
    updated_at: datetime


class CapacityRequest(BaseModel):
    quantity: int = Field(gt=0)


class CapacityResponse(BaseModel):
    warehouse_id: str
    total_capacity: int
    used_capacity: int
    available_capacity: int
    utilization_percentage: float
    status: str


class StatusUpdate(BaseModel):
    status: WarehouseStatus


class WarehouseSummary(BaseModel):
    total_warehouses: int
    active_warehouses: int
    inactive_warehouses: int
    maintenance_warehouses: int
    full_warehouses: int
    total_capacity: int
    used_capacity: int
    available_capacity: int
    utilization_percentage: float


# ============================================================
# DEPENDENCIES
# ============================================================

DBSession = Annotated[
    AsyncSession,
    Depends(get_db),
]


async def get_warehouse_or_404(
    db: AsyncSession,
    warehouse_id: str,
) -> Warehouse:

    warehouse = await db.get(
        Warehouse,
        warehouse_id,
    )

    if warehouse is None:
        raise HTTPException(
            status_code=404,
            detail="Warehouse not found",
        )

    return warehouse


def capacity_metrics(
    warehouse: Warehouse,
) -> CapacityResponse:

    available = max(
        warehouse.total_capacity - warehouse.used_capacity,
        0,
    )

    utilization = (
        warehouse.used_capacity
        / warehouse.total_capacity
        * 100
        if warehouse.total_capacity
        else 0.0
    )

    return CapacityResponse(
        warehouse_id=warehouse.id,
        total_capacity=warehouse.total_capacity,
        used_capacity=warehouse.used_capacity,
        available_capacity=available,
        utilization_percentage=round(
            utilization, 2
        ),
        status=warehouse.status,
    )


def sync_capacity_status(
    warehouse: Warehouse,
) -> None:

    if warehouse.status in {
        WarehouseStatus.INACTIVE.value,
        WarehouseStatus.MAINTENANCE.value,
    }:
        return

    if warehouse.used_capacity >= warehouse.total_capacity:
        warehouse.status = WarehouseStatus.FULL.value
    else:
        warehouse.status = WarehouseStatus.ACTIVE.value


# ============================================================
# CREATE WAREHOUSE
# ============================================================

@router.post(
    "/",
    response_model=WarehouseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_warehouse(
    payload: WarehouseCreate,
    db: DBSession,
):

    existing = await db.scalar(
        select(Warehouse).where(
            Warehouse.organization_id
            == payload.organization_id,
            Warehouse.code == payload.code,
        )
    )

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Warehouse code already exists",
        )

    warehouse = Warehouse(
        **payload.model_dump(
            mode="json"
        )
    )

    db.add(warehouse)

    await db.commit()
    await db.refresh(warehouse)

    return warehouse


# ============================================================
# LIST WAREHOUSES
# ============================================================

@router.get(
    "/",
    response_model=list[WarehouseResponse],
)
async def list_warehouses(
    db: DBSession,
    organization_id: str,
    city: str | None = None,
    warehouse_status: WarehouseStatus | None = None,
    warehouse_type: WarehouseType | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):

    query = select(Warehouse).where(
        Warehouse.organization_id == organization_id
    )

    if city:
        query = query.where(
            Warehouse.city == city
        )

    if warehouse_status:
        query = query.where(
            Warehouse.status == warehouse_status.value
        )

    if warehouse_type:
        query = query.where(
            Warehouse.warehouse_type
            == warehouse_type.value
        )

    query = (
        query
        .order_by(Warehouse.name)
        .offset(offset)
        .limit(limit)
    )

    result = await db.scalars(query)

    return list(result.all())


# ============================================================
# WAREHOUSE SUMMARY
# ============================================================

@router.get(
    "/summary",
    response_model=WarehouseSummary,
)
async def warehouse_summary(
    db: DBSession,
    organization_id: str,
):

    result = await db.scalars(
        select(Warehouse).where(
            Warehouse.organization_id
            == organization_id
        )
    )

    warehouses = list(result.all())

    total_capacity = sum(
        w.total_capacity for w in warehouses
    )

    used_capacity = sum(
        w.used_capacity for w in warehouses
    )

    utilization = (
        used_capacity / total_capacity * 100
        if total_capacity
        else 0.0
    )

    return WarehouseSummary(
        total_warehouses=len(warehouses),
        active_warehouses=sum(
            w.status == WarehouseStatus.ACTIVE.value
            for w in warehouses
        ),
        inactive_warehouses=sum(
            w.status == WarehouseStatus.INACTIVE.value
            for w in warehouses
        ),
        maintenance_warehouses=sum(
            w.status == WarehouseStatus.MAINTENANCE.value
            for w in warehouses
        ),
        full_warehouses=sum(
            w.status == WarehouseStatus.FULL.value
            for w in warehouses
        ),
        total_capacity=total_capacity,
        used_capacity=used_capacity,
        available_capacity=(
            total_capacity - used_capacity
        ),
        utilization_percentage=round(
            utilization, 2
        ),
    )


# ============================================================
# AVAILABLE WAREHOUSES
# ============================================================

@router.get(
    "/available",
    response_model=list[WarehouseResponse],
)
async def available_warehouses(
    db: DBSession,
    organization_id: str,
    required_capacity: int = Query(1, gt=0),
):

    result = await db.scalars(
        select(Warehouse).where(
            Warehouse.organization_id
            == organization_id,
            Warehouse.status
            == WarehouseStatus.ACTIVE.value,
            (
                Warehouse.total_capacity
                - Warehouse.used_capacity
            ) >= required_capacity,
        )
    )

    return list(result.all())


# ============================================================
# GET WAREHOUSE
# ============================================================

@router.get(
    "/{warehouse_id}",
    response_model=WarehouseResponse,
)
async def get_warehouse(
    warehouse_id: str,
    db: DBSession,
):

    return await get_warehouse_or_404(
        db,
        warehouse_id,
    )


# ============================================================
# UPDATE WAREHOUSE
# ============================================================

@router.patch(
    "/{warehouse_id}",
    response_model=WarehouseResponse,
)
async def update_warehouse(
    warehouse_id: str,
    payload: WarehouseUpdate,
    db: DBSession,
):

    warehouse = await get_warehouse_or_404(
        db,
        warehouse_id,
    )

    changes = payload.model_dump(
        exclude_unset=True,
        mode="json",
    )

    if (
        "total_capacity" in changes
        and changes["total_capacity"]
        < warehouse.used_capacity
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Total capacity cannot be lower "
                "than currently used capacity"
            ),
        )

    for field, value in changes.items():
        setattr(warehouse, field, value)

    sync_capacity_status(warehouse)

    await db.commit()
    await db.refresh(warehouse)

    return warehouse


# ============================================================
# DELETE WAREHOUSE
# ============================================================

@router.delete(
    "/{warehouse_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_warehouse(
    warehouse_id: str,
    db: DBSession,
):

    warehouse = await get_warehouse_or_404(
        db,
        warehouse_id,
    )

    if warehouse.used_capacity > 0:
        raise HTTPException(
            status_code=409,
            detail=(
                "Cannot delete warehouse "
                "with allocated capacity"
            ),
        )

    await db.delete(warehouse)
    await db.commit()

    return Response(
        status_code=status.HTTP_204_NO_CONTENT
    )


# ============================================================
# ALLOCATE CAPACITY
# ============================================================

@router.post(
    "/{warehouse_id}/allocate",
    response_model=CapacityResponse,
)
async def allocate_capacity(
    warehouse_id: str,
    payload: CapacityRequest,
    db: DBSession,
):

    # Row lock prevents concurrent over-allocation
    # on databases supporting SELECT FOR UPDATE.
    result = await db.execute(
        select(Warehouse)
        .where(Warehouse.id == warehouse_id)
        .with_for_update()
    )

    warehouse = result.scalar_one_or_none()

    if warehouse is None:
        raise HTTPException(
            status_code=404,
            detail="Warehouse not found",
        )

    if warehouse.status != WarehouseStatus.ACTIVE.value:
        raise HTTPException(
            status_code=409,
            detail="Warehouse is not available",
        )

    available = (
        warehouse.total_capacity
        - warehouse.used_capacity
    )

    if payload.quantity > available:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Insufficient warehouse capacity",
                "available_capacity": available,
                "requested_capacity": payload.quantity,
            },
        )

    warehouse.used_capacity += payload.quantity

    sync_capacity_status(warehouse)

    await db.commit()
    await db.refresh(warehouse)

    return capacity_metrics(warehouse)


# ============================================================
# RELEASE CAPACITY
# ============================================================

@router.post(
    "/{warehouse_id}/release",
    response_model=CapacityResponse,
)
async def release_capacity(
    warehouse_id: str,
    payload: CapacityRequest,
    db: DBSession,
):

    result = await db.execute(
        select(Warehouse)
        .where(Warehouse.id == warehouse_id)
        .with_for_update()
    )

    warehouse = result.scalar_one_or_none()

    if warehouse is None:
        raise HTTPException(
            status_code=404,
            detail="Warehouse not found",
        )

    if payload.quantity > warehouse.used_capacity:
        raise HTTPException(
            status_code=409,
            detail="Release quantity exceeds used capacity",
        )

    warehouse.used_capacity -= payload.quantity

    sync_capacity_status(warehouse)

    await db.commit()
    await db.refresh(warehouse)

    return capacity_metrics(warehouse)


# ============================================================
# CAPACITY MONITORING
# ============================================================

@router.get(
    "/{warehouse_id}/capacity",
    response_model=CapacityResponse,
)
async def get_warehouse_capacity(
    warehouse_id: str,
    db: DBSession,
):

    warehouse = await get_warehouse_or_404(
        db,
        warehouse_id,
    )

    return capacity_metrics(warehouse)


# ============================================================
# WAREHOUSE ANALYTICS
# ============================================================

@router.get(
    "/{warehouse_id}/analytics",
)
async def warehouse_analytics(
    warehouse_id: str,
    db: DBSession,
):

    warehouse = await get_warehouse_or_404(
        db,
        warehouse_id,
    )

    capacity = capacity_metrics(warehouse)

    utilization = capacity.utilization_percentage

    if utilization >= 95:
        capacity_risk = "critical"
    elif utilization >= 85:
        capacity_risk = "high"
    elif utilization >= 70:
        capacity_risk = "medium"
    else:
        capacity_risk = "low"

    recommendations = []

    if utilization >= 95:
        recommendations.append(
            "Immediately redistribute inventory "
            "to alternative warehouses."
        )

    elif utilization >= 85:
        recommendations.append(
            "Plan additional capacity or "
            "stock transfers."
        )

    elif utilization < 30:
        recommendations.append(
            "Review underutilized warehouse space."
        )

    else:
        recommendations.append(
            "Warehouse capacity is within "
            "normal operating thresholds."
        )

    return {
        "warehouse_id": warehouse.id,
        "warehouse_name": warehouse.name,
        "warehouse_type": warehouse.warehouse_type,
        "status": warehouse.status,
        "capacity": capacity.model_dump(),
        "capacity_risk": capacity_risk,
        "recommendations": recommendations,
        "evaluated_at": datetime.now(
            timezone.utc
        ).isoformat(),
    }


# ============================================================
# UPDATE STATUS
# ============================================================

@router.patch(
    "/{warehouse_id}/status",
    response_model=WarehouseResponse,
)
async def update_warehouse_status(
    warehouse_id: str,
    payload: StatusUpdate,
    db: DBSession,
):

    warehouse = await get_warehouse_or_404(
        db,
        warehouse_id,
    )

    if payload.status == WarehouseStatus.FULL:
        if warehouse.used_capacity < warehouse.total_capacity:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Cannot mark warehouse full "
                    "while capacity remains"
                ),
            )

    if payload.status == WarehouseStatus.ACTIVE:
        if warehouse.used_capacity >= warehouse.total_capacity:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Cannot activate a warehouse "
                    "with no available capacity"
                ),
            )

    warehouse.status = payload.status.value

    await db.commit()
    await db.refresh(warehouse)

    return warehouse
