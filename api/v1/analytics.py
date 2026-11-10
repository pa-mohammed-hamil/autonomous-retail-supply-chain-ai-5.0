from __future__ import annotations

"""Planned module: analytics. Implementation pending."""

"""
backend/analytics.py

Autonomous Retail Supply Chain AI 5.0
Centralized Supply Chain Analytics API

Python 3.10+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Executive KPI dashboard
    - Inventory analytics
    - Sales analytics
    - Demand analytics
    - Logistics analytics
    - Warehouse capacity analytics
    - Stockout risk indicators
    - Supply chain health indicators
    - Tenant isolation
    - Warehouse-scoped authorization
    - Time-window metadata
    - Partial-data transparency
    - No production data mutations

IMPORTANT:
    This is a read-only analytics API
    built on in-memory stream projections.

    It does not replace a data warehouse,
    financial ledger, or trained ML model.

    Historical reporting requires
    durable timestamped fact tables.
"""


from datetime import datetime, timezone
from decimal import Decimal
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
)

from backend.permissions import (
    CurrentPrincipal,
    Permission,
    Principal,
    ResourceContext,
    permission_engine,
)

from backend.inventory_stream import (
    inventory_stream,
    calculate_stock_status,
    StockStatus,
)

from backend.sales_stream import (
    sales_store,
    calculate_sales_summary,
    SalesOrderStatus,
)

from backend.demand_stream import (
    demand_stream,
)

from backend.logistics_stream import (
    logistics_stream,
    ShipmentStatus,
    shipment_is_delayed,
)

from backend.warehouse_stream import (
    warehouse_store,
    calculate_utilization,
)


# ============================================================
# CONFIGURATION
# ============================================================

DEFAULT_CURRENCY = "INR"

MAX_WAREHOUSES_PER_REQUEST = 100

MAX_PRODUCTS_PER_REQUEST = 500

DEFAULT_ANALYTICS_LIMIT = 100


# ============================================================
# ENUMS
# ============================================================

class AnalyticsPeriod(str, Enum):
    TODAY = "today"
    LAST_7_DAYS = "last_7_days"
    LAST_30_DAYS = "last_30_days"
    LAST_90_DAYS = "last_90_days"
    ALL_AVAILABLE = "all_available"


class AnalyticsHealth(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    INSUFFICIENT_DATA = "insufficient_data"


class AnalyticsDataQuality(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


# ============================================================
# RESPONSE MODELS
# ============================================================

class AnalyticsMetadata(BaseModel):
    generated_at: datetime
    requested_period: AnalyticsPeriod
    data_quality: AnalyticsDataQuality
    note: str


class InventoryAnalytics(BaseModel):
    warehouse_id: str

    tracked_products: int
    in_stock_products: int
    low_stock_products: int
    stockout_products: int

    total_quantity_on_hand: int
    total_quantity_reserved: int
    total_quantity_available: int

    stockout_rate_percent: Decimal


class SalesAnalytics(BaseModel):
    warehouse_id: str
    currency: str

    total_orders: int
    paid_orders: int
    fulfilled_orders: int
    cancelled_orders: int

    gross_sales: Decimal
    refunds: Decimal
    net_sales: Decimal

    average_order_value: Decimal


class DemandAnalytics(BaseModel):
    warehouse_id: str

    tracked_products: int
    observed_units: int
    forecasted_units: Decimal

    forecast_count: int

    note: str


class LogisticsAnalytics(BaseModel):
    warehouse_id: str

    tracked_shipments: int
    in_transit_shipments: int
    delivered_shipments: int
    failed_shipments: int
    delayed_shipments: int

    delivery_completion_rate_percent: Decimal


class WarehouseAnalytics(BaseModel):
    warehouse_id: str

    status: str

    capacity_units: int
    utilized_units: int
    reserved_capacity_units: int

    available_capacity_units: int

    utilization_percent: Decimal

    active_incident_count: int


class SupplyChainKPIs(BaseModel):
    inventory: InventoryAnalytics | None
    sales: SalesAnalytics | None
    demand: DemandAnalytics | None
    logistics: LogisticsAnalytics | None
    warehouse: WarehouseAnalytics | None


class SupplyChainHealthResponse(BaseModel):
    warehouse_id: str
    health: AnalyticsHealth
    reasons: list[str]
    metadata: AnalyticsMetadata


class AnalyticsDashboardResponse(BaseModel):
    warehouse_id: str
    kpis: SupplyChainKPIs
    health: AnalyticsHealth
    metadata: AnalyticsMetadata


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def percentage(
    numerator: int | Decimal,
    denominator: int | Decimal,
) -> Decimal:

    if denominator == 0:
        return Decimal("0")

    return (
        Decimal(numerator)
        / Decimal(denominator)
        * Decimal("100")
    ).quantize(Decimal("0.01"))


def money(
    value: Decimal,
) -> Decimal:

    return value.quantize(
        Decimal("0.01")
    )


def analytics_metadata(
    period: AnalyticsPeriod,
    quality: AnalyticsDataQuality,
) -> AnalyticsMetadata:

    return AnalyticsMetadata(
        generated_at=utc_now(),
        requested_period=period,
        data_quality=quality,
        note=(
            "Metrics reflect the latest available "
            "in-memory projections. Historical "
            "period filtering is not implemented."
        ),
    )


# ============================================================
# AUTHORIZATION
# ============================================================

def require_analytics_access(
    principal: Principal,
    warehouse_id: str,
) -> None:

    resource = ResourceContext(
        tenant_id=principal.tenant_id,
        warehouse_id=warehouse_id,
    )

    decision = permission_engine.evaluate(
        principal,
        Permission.ANALYTICS_READ,
        resource,
    )

    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail="Analytics access denied",
        )

    allowed = principal.allowed_warehouse_ids

    if (
        allowed is not None
        and warehouse_id not in allowed
    ):
        raise HTTPException(
            status_code=403,
            detail="Warehouse access denied",
        )


# ============================================================
# ANALYTICS SERVICE
# ============================================================

class AnalyticsService:

    async def inventory_analytics(
        self,
        *,
        tenant_id: str,
        warehouse_id: str,
    ) -> InventoryAnalytics | None:
        """
        Uses inventory projection snapshots.

        Access to internal store state is
        prototype-only and should be replaced
        with a repository query.
        """

        store = inventory_stream.store

        async with store._lock:

            states = [
                state
                for key, state in store._states.items()
                if (
                    key[0] == tenant_id
                    and key[2] == warehouse_id
                )
            ]

        if not states:
            return None

        in_stock = 0
        low_stock = 0
        stockout = 0

        on_hand = 0
        reserved = 0
        available = 0

        for state in states:

            quantity_available = max(
                0,
                state.quantity_on_hand
                - state.quantity_reserved,
            )

            status = calculate_stock_status(
                quantity_available,
                state.low_stock_threshold,
            )

            if status == StockStatus.IN_STOCK:
                in_stock += 1

            elif status == StockStatus.LOW_STOCK:
                low_stock += 1

            else:
                stockout += 1

            on_hand += state.quantity_on_hand
            reserved += state.quantity_reserved
            available += quantity_available

        return InventoryAnalytics(
            warehouse_id=warehouse_id,
            tracked_products=len(states),
            in_stock_products=in_stock,
            low_stock_products=low_stock,
            stockout_products=stockout,
            total_quantity_on_hand=on_hand,
            total_quantity_reserved=reserved,
            total_quantity_available=available,
            stockout_rate_percent=percentage(
                stockout,
                len(states),
            ),
        )

    async def sales_analytics(
        self,
        *,
        tenant_id: str,
        warehouse_id: str,
        currency: str,
    ) -> SalesAnalytics | None:

        orders = await sales_store.list_orders(
            tenant_id=tenant_id,
            warehouse_id=warehouse_id,
        )

        if not orders:
            return None

        summary = calculate_sales_summary(
            orders,
            warehouse_id,
            currency,
        )

        eligible_orders = (
            summary.paid_orders
            + summary.fulfilled_orders
        )

        average_order_value = (
            summary.gross_sales
            / Decimal(eligible_orders)
            if eligible_orders
            else Decimal("0")
        )

        return SalesAnalytics(
            warehouse_id=warehouse_id,
            currency=currency,
            total_orders=summary.total_orders,
            paid_orders=summary.paid_orders,
            fulfilled_orders=summary.fulfilled_orders,
            cancelled_orders=summary.cancelled_orders,
            gross_sales=summary.gross_sales,
            refunds=summary.refunds,
            net_sales=summary.net_sales,
            average_order_value=money(
                average_order_value
            ),
        )

    async def demand_analytics(
        self,
        *,
        tenant_id: str,
        warehouse_id: str,
    ) -> DemandAnalytics | None:

        store = demand_stream.store

        async with store._lock:

            observations = [
                (
                    key,
                    list(records),
                )
                for key, records
                in store._observations.items()
                if (
                    key[0] == tenant_id
                    and key[2] == warehouse_id
                )
            ]

            forecasts = [
                forecast
                for key, forecast
                in store._forecasts.items()
                if (
                    key[0] == tenant_id
                    and key[2] == warehouse_id
                )
            ]

        if not observations and not forecasts:
            return None

        observed_units = sum(
            observation.units_sold
            for _, records in observations
            for observation in records
        )

        forecasted_units = sum(
            (
                Decimal(
                    str(forecast.forecast_units)
                )
                for forecast in forecasts
            ),
            Decimal("0"),
        )

        products = {
            key[1]
            for key, _ in observations
        }

        return DemandAnalytics(
            warehouse_id=warehouse_id,
            tracked_products=len(products),
            observed_units=observed_units,
            forecasted_units=forecasted_units,
            forecast_count=len(forecasts),
            note=(
                "Observed units reflect retained "
                "events. Forecast horizons may differ "
                "and are not normalized."
            ),
        )

    async def logistics_analytics(
        self,
        *,
        tenant_id: str,
        warehouse_id: str,
    ) -> LogisticsAnalytics | None:

        store = logistics_stream.store

        async with store._lock:

            states = [
                state
                for state in store._states.values()
                if (
                    state.tenant_id == tenant_id
                    and state.warehouse_id
                    == warehouse_id
                )
            ]

        if not states:
            return None

        delivered = sum(
            state.status == ShipmentStatus.DELIVERED
            for state in states
        )

        in_transit = sum(
            state.status in {
                ShipmentStatus.PICKED_UP,
                ShipmentStatus.IN_TRANSIT,
                ShipmentStatus.OUT_FOR_DELIVERY,
            }
            for state in states
        )

        failed = sum(
            state.status
            == ShipmentStatus.DELIVERY_FAILED
            for state in states
        )

        delayed = sum(
            shipment_is_delayed(state)
            for state in states
        )

        return LogisticsAnalytics(
            warehouse_id=warehouse_id,
            tracked_shipments=len(states),
            in_transit_shipments=in_transit,
            delivered_shipments=delivered,
            failed_shipments=failed,
            delayed_shipments=delayed,
            delivery_completion_rate_percent=percentage(
                delivered,
                len(states),
            ),
        )

    async def warehouse_analytics(
        self,
        *,
        tenant_id: str,
        warehouse_id: str,
    ) -> WarehouseAnalytics | None:

        state = await warehouse_store.get_snapshot(
            tenant_id=tenant_id,
            warehouse_id=warehouse_id,
        )

        if state is None:
            return None

        available = max(
            0,
            state.capacity_units
            - state.utilized_units
            - state.reserved_capacity_units,
        )

        return WarehouseAnalytics(
            warehouse_id=warehouse_id,
            status=state.status.value,
            capacity_units=state.capacity_units,
            utilized_units=state.utilized_units,
            reserved_capacity_units=(
                state.reserved_capacity_units
            ),
            available_capacity_units=available,
            utilization_percent=calculate_utilization(
                state.utilized_units,
                state.capacity_units,
            ),
            active_incident_count=(
                state.active_incident_count
            ),
        )

    async def dashboard(
        self,
        *,
        tenant_id: str,
        warehouse_id: str,
        currency: str,
        period: AnalyticsPeriod,
    ) -> AnalyticsDashboardResponse:

        inventory = await self.inventory_analytics(
            tenant_id=tenant_id,
            warehouse_id=warehouse_id,
        )

        sales = await self.sales_analytics(
            tenant_id=tenant_id,
            warehouse_id=warehouse_id,
            currency=currency,
        )

        demand = await self.demand_analytics(
            tenant_id=tenant_id,
            warehouse_id=warehouse_id,
        )

        logistics = await self.logistics_analytics(
            tenant_id=tenant_id,
            warehouse_id=warehouse_id,
        )

        warehouse = await self.warehouse_analytics(
            tenant_id=tenant_id,
            warehouse_id=warehouse_id,
        )

        available_count = sum(
            item is not None
            for item in (
                inventory,
                sales,
                demand,
                logistics,
                warehouse,
            )
        )

        if available_count == 0:
            quality = AnalyticsDataQuality.UNAVAILABLE

        elif available_count < 5:
            quality = AnalyticsDataQuality.PARTIAL

        else:
            quality = AnalyticsDataQuality.COMPLETE

        health, _ = evaluate_supply_chain_health(
            inventory,
            logistics,
            warehouse,
        )

        if quality == AnalyticsDataQuality.UNAVAILABLE:
            health = AnalyticsHealth.INSUFFICIENT_DATA

        return AnalyticsDashboardResponse(
            warehouse_id=warehouse_id,
            kpis=SupplyChainKPIs(
                inventory=inventory,
                sales=sales,
                demand=demand,
                logistics=logistics,
                warehouse=warehouse,
            ),
            health=health,
            metadata=analytics_metadata(
                period,
                quality,
            ),
        )


# ============================================================
# HEALTH EVALUATION
# ============================================================

def evaluate_supply_chain_health(
    inventory: InventoryAnalytics | None,
    logistics: LogisticsAnalytics | None,
    warehouse: WarehouseAnalytics | None,
) -> tuple[AnalyticsHealth, list[str]]:

    reasons: list[str] = []

    critical = False
    warning = False

    if inventory is not None:

        if inventory.stockout_products > 0:
            critical = True
            reasons.append(
                "One or more products are out of stock."
            )

        elif inventory.low_stock_products > 0:
            warning = True
            reasons.append(
                "Some products have low inventory."
            )

    if logistics is not None:

        if logistics.failed_shipments > 0:
            warning = True
            reasons.append(
                "Delivery failures were detected."
            )

        if logistics.delayed_shipments > 0:
            warning = True
            reasons.append(
                "Delayed shipments were detected."
            )

    if warehouse is not None:

        if warehouse.active_incident_count > 0:
            critical = True
            reasons.append(
                "Active warehouse incidents detected."
            )

        if warehouse.utilization_percent >= 95:
            critical = True
            reasons.append(
                "Warehouse utilization is critical."
            )

        elif warehouse.utilization_percent >= 85:
            warning = True
            reasons.append(
                "Warehouse utilization is high."
            )

        if warehouse.status == "disrupted":
            critical = True
            reasons.append(
                "Warehouse operations are disrupted."
            )

    if critical:
        return AnalyticsHealth.CRITICAL, reasons

    if warning:
        return AnalyticsHealth.WARNING, reasons

    if (
        inventory is None
        and logistics is None
        and warehouse is None
    ):
        return (
            AnalyticsHealth.INSUFFICIENT_DATA,
            ["Insufficient operational data."],
        )

    return AnalyticsHealth.HEALTHY, reasons


analytics_service = AnalyticsService()


# ============================================================
# API ROUTER
# ============================================================

router = APIRouter(
    prefix="/api/v1/analytics",
    tags=["Supply Chain Analytics"],
)


@router.get(
    "/dashboard/{warehouse_id}",
    response_model=AnalyticsDashboardResponse,
)
async def get_analytics_dashboard(
    warehouse_id: str,
    principal: CurrentPrincipal,
    currency: str = Query(
        default=DEFAULT_CURRENCY,
        pattern=r"^[A-Z]{3}$",
    ),
    period: AnalyticsPeriod = AnalyticsPeriod.ALL_AVAILABLE,
):

    require_analytics_access(
        principal,
        warehouse_id,
    )

    return await analytics_service.dashboard(
        tenant_id=principal.tenant_id,
        warehouse_id=warehouse_id,
        currency=currency,
        period=period,
    )


@router.get(
    "/inventory/{warehouse_id}",
    response_model=InventoryAnalytics,
)
async def get_inventory_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
):

    require_analytics_access(
        principal,
        warehouse_id,
    )

    result = await analytics_service.inventory_analytics(
        tenant_id=principal.tenant_id,
        warehouse_id=warehouse_id,
    )

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Inventory analytics unavailable",
        )

    return result


@router.get(
    "/sales/{warehouse_id}",
    response_model=SalesAnalytics,
)
async def get_sales_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
    currency: str = Query(
        default=DEFAULT_CURRENCY,
        pattern=r"^[A-Z]{3}$",
    ),
):

    require_analytics_access(
        principal,
        warehouse_id,
    )

    result = await analytics_service.sales_analytics(
        tenant_id=principal.tenant_id,
        warehouse_id=warehouse_id,
        currency=currency,
    )

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Sales analytics unavailable",
        )

    return result


@router.get(
    "/demand/{warehouse_id}",
    response_model=DemandAnalytics,
)
async def get_demand_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
):

    require_analytics_access(
        principal,
        warehouse_id,
    )

    result = await analytics_service.demand_analytics(
        tenant_id=principal.tenant_id,
        warehouse_id=warehouse_id,
    )

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Demand analytics unavailable",
        )

    return result


@router.get(
    "/logistics/{warehouse_id}",
    response_model=LogisticsAnalytics,
)
async def get_logistics_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
):

    require_analytics_access(
        principal,
        warehouse_id,
    )

    result = await analytics_service.logistics_analytics(
        tenant_id=principal.tenant_id,
        warehouse_id=warehouse_id,
    )

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Logistics analytics unavailable",
        )

    return result


@router.get(
    "/warehouse/{warehouse_id}",
    response_model=WarehouseAnalytics,
)
async def get_warehouse_analytics(
    warehouse_id: str,
    principal: CurrentPrincipal,
):

    require_analytics_access(
        principal,
        warehouse_id,
    )

    result = await analytics_service.warehouse_analytics(
        tenant_id=principal.tenant_id,
        warehouse_id=warehouse_id,
    )

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Warehouse analytics unavailable",
        )

    return result


@router.get(
    "/health/{warehouse_id}",
    response_model=SupplyChainHealthResponse,
)
async def get_supply_chain_health(
    warehouse_id: str,
    principal: CurrentPrincipal,
):

    require_analytics_access(
        principal,
        warehouse_id,
    )

    inventory = await analytics_service.inventory_analytics(
        tenant_id=principal.tenant_id,
        warehouse_id=warehouse_id,
    )

    logistics = await analytics_service.logistics_analytics(
        tenant_id=principal.tenant_id,
        warehouse_id=warehouse_id,
    )

    warehouse = await analytics_service.warehouse_analytics(
        tenant_id=principal.tenant_id,
        warehouse_id=warehouse_id,
    )

    health, reasons = evaluate_supply_chain_health(
        inventory,
        logistics,
        warehouse,
    )

    quality = (
        AnalyticsDataQuality.UNAVAILABLE
        if all(
            item is None
            for item in (
                inventory,
                logistics,
                warehouse,
            )
        )
        else AnalyticsDataQuality.PARTIAL
    )

    return SupplyChainHealthResponse(
        warehouse_id=warehouse_id,
        health=health,
        reasons=reasons,
        metadata=analytics_metadata(
            AnalyticsPeriod.ALL_AVAILABLE,
            quality,
        ),
    )


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "AnalyticsPeriod",
    "AnalyticsHealth",
    "AnalyticsDataQuality",
    "AnalyticsMetadata",
    "InventoryAnalytics",
    "SalesAnalytics",
    "DemandAnalytics",
    "LogisticsAnalytics",
    "WarehouseAnalytics",
    "SupplyChainKPIs",
    "SupplyChainHealthResponse",
    "AnalyticsDashboardResponse",
    "AnalyticsService",
    "analytics_service",
    "router",
]
