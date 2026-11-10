from __future__ import annotations

"""Planned module: analytics. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
backend/services/analytics_service.py

Reference retail analytics implementation.

Features:
- Tenant and warehouse RBAC
- Sales, inventory, supplier and logistics KPIs
- Warehouse capacity analytics
- Stockout and sentiment analytics
- Financial analytics
- Executive dashboard
- Snapshot history and JSON export
- Audit logging and input validation

This is an in-memory prototype.
No live database or model is connected.
"""


import copy
import json
import math
import threading
import uuid

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid {name}")
    return value.strip()


def money(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("Invalid monetary value")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid monetary value") from exc
    if not result.is_finite() or result < 0:
        raise ValueError("Money must be finite and nonnegative")
    return result


def number(value: Any, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"Invalid {name}")
    return float(value)


def count(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Invalid {name}")
    return value


def ratio(numerator: float, denominator: float) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 2)


class AnalyticsDomain(str, Enum):
    SALES = "sales"
    INVENTORY = "inventory"
    SUPPLIER = "supplier"
    WAREHOUSE = "warehouse"
    LOGISTICS = "logistics"
    STOCKOUT = "stockout"
    SENTIMENT = "sentiment"
    FINANCE = "finance"


@dataclass(frozen=True)
class AnalyticsActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str] = frozenset()
    is_active: bool = True


@dataclass(frozen=True)
class SalesMetricsInput:
    orders: int
    units_sold: int
    gross_revenue: Decimal
    discounts: Decimal
    refunds: Decimal
    cogs: Decimal


@dataclass(frozen=True)
class InventoryMetricsInput:
    sku_count: int
    on_hand_units: int
    reserved_units: int
    low_stock_skus: int
    inventory_value: Decimal


@dataclass(frozen=True)
class SupplierMetricsInput:
    total_suppliers: int
    active_suppliers: int
    total_deliveries: int
    on_time_deliveries: int
    high_risk_suppliers: int


@dataclass(frozen=True)
class WarehouseMetricsInput:
    capacity_units: int
    occupied_units: int
    bins: int


@dataclass(frozen=True)
class LogisticsMetricsInput:
    shipments: int
    delivered: int
    on_time_deliveries: int
    delayed_shipments: int
    transport_cost: Decimal


@dataclass(frozen=True)
class StockoutMetricsInput:
    assessed_skus: int
    high_risk_skus: int
    critical_risk_skus: int


@dataclass(frozen=True)
class SentimentMetricsInput:
    total_feedback: int
    positive: int
    neutral: int
    negative: int


@dataclass(frozen=True)
class FinanceMetricsInput:
    revenue: Decimal
    cogs: Decimal
    operating_expenses: Decimal
    refunds: Decimal


@dataclass(frozen=True)
class AnalyticsSnapshot:
    snapshot_id: str
    tenant_id: str
    warehouse_id: str | None
    domain: AnalyticsDomain
    metrics: dict[str, Any]
    source_reference: str
    created_by: str
    created_at: str


@dataclass(frozen=True)
class AnalyticsAuditEvent:
    event_id: str
    tenant_id: str
    snapshot_id: str
    actor_id: str
    action: str
    timestamp: str


class RetailAnalyticsService:
    WRITER_ROLES = frozenset({
        "analytics_engineer",
        "operations_manager",
        "corporate_admin",
    })

    READER_ROLES = WRITER_ROLES | frozenset({
        "business_analyst",
        "inventory_analyst",
        "finance_analyst",
        "warehouse_manager",
        "procurement_manager",
    })

    def __init__(self, tenant_id: str, currency: str = "INR"):
        self.tenant_id = required_text(tenant_id, "tenant_id")
        self.currency = required_text(currency, "currency").upper()
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValueError("Invalid currency")

        self._lock = threading.RLock()
        self._snapshots: dict[str, AnalyticsSnapshot] = {}
        self._audit: list[AnalyticsAuditEvent] = []

    def _authorize(
        self,
        actor: AnalyticsActor,
        roles: frozenset[str],
        warehouse_id: str | None = None,
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.user_id.strip()
            or not actor.roles.intersection(roles)
        ):
            raise PermissionError("Analytics access denied")

        if warehouse_id is None:
            # Corporate-wide data is restricted.
            if "corporate_admin" not in actor.roles:
                raise PermissionError("Corporate scope required")
        elif (
            "corporate_admin" not in actor.roles
            and warehouse_id not in actor.warehouse_ids
        ):
            raise PermissionError("Warehouse scope denied")

    @staticmethod
    def sales(data: SalesMetricsInput) -> dict:
        count(data.orders, "orders")
        count(data.units_sold, "units_sold")
        gross = money(data.gross_revenue)
        discounts = money(data.discounts)
        refunds = money(data.refunds)
        cogs = money(data.cogs)

        if discounts + refunds > gross:
            raise ValueError("Discounts and refunds exceed gross revenue")

        net = gross - discounts - refunds
        profit = net - cogs

        return {
            "orders": data.orders,
            "units_sold": data.units_sold,
            "gross_revenue": str(gross),
            "net_revenue": str(net),
            "gross_profit": str(profit),
            "gross_margin_pct": (
                round(float(profit / net * 100), 2)
                if net > 0 else None
            ),
            "average_order_value": (
                str(round(net / data.orders, 2))
                if data.orders else None
            ),
        }

    @staticmethod
    def inventory(data: InventoryMetricsInput) -> dict:
        for key in (
            "sku_count", "on_hand_units",
            "reserved_units", "low_stock_skus"
        ):
            count(getattr(data, key), key)

        if data.reserved_units > data.on_hand_units:
            raise ValueError("Reserved stock exceeds on-hand stock")
        if data.low_stock_skus > data.sku_count:
            raise ValueError("Low-stock SKUs exceed SKU count")

        return {
            "sku_count": data.sku_count,
            "on_hand_units": data.on_hand_units,
            "reserved_units": data.reserved_units,
            "available_units": data.on_hand_units - data.reserved_units,
            "low_stock_skus": data.low_stock_skus,
            "low_stock_pct": ratio(data.low_stock_skus, data.sku_count),
            "inventory_value": str(money(data.inventory_value)),
        }

    @staticmethod
    def supplier(data: SupplierMetricsInput) -> dict:
        for key in (
            "total_suppliers", "active_suppliers",
            "total_deliveries", "on_time_deliveries",
            "high_risk_suppliers"
        ):
            count(getattr(data, key), key)

        if data.active_suppliers > data.total_suppliers:
            raise ValueError("Active suppliers exceed total")
        if data.high_risk_suppliers > data.total_suppliers:
            raise ValueError("High-risk suppliers exceed total")
        if data.on_time_deliveries > data.total_deliveries:
            raise ValueError("On-time deliveries exceed total")

        return {
            "total_suppliers": data.total_suppliers,
            "active_suppliers": data.active_suppliers,
            "high_risk_suppliers": data.high_risk_suppliers,
            "on_time_delivery_pct": ratio(
                data.on_time_deliveries,
                data.total_deliveries
            ),
        }

    @staticmethod
    def warehouse(data: WarehouseMetricsInput) -> dict:
        count(data.capacity_units, "capacity_units")
        count(data.occupied_units, "occupied_units")
        count(data.bins, "bins")

        if data.occupied_units > data.capacity_units:
            raise ValueError("Warehouse over capacity")

        return {
            "capacity_units": data.capacity_units,
            "occupied_units": data.occupied_units,
            "available_capacity": (
                data.capacity_units - data.occupied_units
            ),
            "utilization_pct": ratio(
                data.occupied_units,
                data.capacity_units
            ),
            "bin_count": data.bins,
        }

    @staticmethod
    def logistics(data: LogisticsMetricsInput) -> dict:
        for key in (
            "shipments", "delivered",
            "on_time_deliveries", "delayed_shipments"
        ):
            count(getattr(data, key), key)

        if data.delivered > data.shipments:
            raise ValueError("Delivered exceeds shipments")
        if data.on_time_deliveries > data.delivered:
            raise ValueError("On-time deliveries exceed delivered")
        if data.delayed_shipments > data.shipments:
            raise ValueError("Delayed shipments exceed shipments")

        return {
            "shipments": data.shipments,
            "delivered": data.delivered,
            "delivery_completion_pct": ratio(
                data.delivered, data.shipments
            ),
            "on_time_delivery_pct": ratio(
                data.on_time_deliveries, data.delivered
            ),
            "delayed_shipments": data.delayed_shipments,
            "transport_cost": str(money(data.transport_cost)),
        }

    @staticmethod
    def stockout(data: StockoutMetricsInput) -> dict:
        for key in (
            "assessed_skus", "high_risk_skus",
            "critical_risk_skus"
        ):
            count(getattr(data, key), key)

        if (
            data.high_risk_skus + data.critical_risk_skus
            > data.assessed_skus
        ):
            raise ValueError("Risk counts exceed assessed SKUs")

        return {
            "assessed_skus": data.assessed_skus,
            "high_risk_skus": data.high_risk_skus,
            "critical_risk_skus": data.critical_risk_skus,
            "at_risk_pct": ratio(
                data.high_risk_skus + data.critical_risk_skus,
                data.assessed_skus
            ),
        }

    @staticmethod
    def sentiment(data: SentimentMetricsInput) -> dict:
        for key in ("total_feedback", "positive", "neutral", "negative"):
            count(getattr(data, key), key)

        if (
            data.positive + data.neutral + data.negative
            != data.total_feedback
        ):
            raise ValueError("Sentiment counts do not match total")

        return {
            "total_feedback": data.total_feedback,
            "positive_pct": ratio(data.positive, data.total_feedback),
            "neutral_pct": ratio(data.neutral, data.total_feedback),
            "negative_pct": ratio(data.negative, data.total_feedback),
        }

    @staticmethod
    def finance(data: FinanceMetricsInput) -> dict:
        revenue = money(data.revenue)
        cogs = money(data.cogs)
        expenses = money(data.operating_expenses)
        refunds = money(data.refunds)

        if refunds > revenue:
            raise ValueError("Refunds exceed revenue")

        net_revenue = revenue - refunds
        gross_profit = net_revenue - cogs
        operating_profit = gross_profit - expenses

        return {
            "net_revenue": str(net_revenue),
            "gross_profit": str(gross_profit),
            "operating_profit": str(operating_profit),
            "operating_margin_pct": (
                round(float(operating_profit / net_revenue * 100), 2)
                if net_revenue > 0 else None
            ),
        }

    CALCULATORS = {
        AnalyticsDomain.SALES: sales.__func__,
        AnalyticsDomain.INVENTORY: inventory.__func__,
        AnalyticsDomain.SUPPLIER: supplier.__func__,
        AnalyticsDomain.WAREHOUSE: warehouse.__func__,
        AnalyticsDomain.LOGISTICS: logistics.__func__,
        AnalyticsDomain.STOCKOUT: stockout.__func__,
        AnalyticsDomain.SENTIMENT: sentiment.__func__,
        AnalyticsDomain.FINANCE: finance.__func__,
    }

    def create_snapshot(
        self,
        actor: AnalyticsActor,
        snapshot_id: str,
        domain: AnalyticsDomain,
        data: Any,
        source_reference: str,
        warehouse_id: str | None = None,
    ) -> AnalyticsSnapshot:
        self._authorize(actor, self.WRITER_ROLES, warehouse_id)
        snapshot_id = required_text(snapshot_id, "snapshot_id")
        source_reference = required_text(source_reference, "source_reference")

        if domain not in self.CALCULATORS:
            raise ValueError("Unsupported analytics domain")

        calculated = self.CALCULATORS[domain](data)

        with self._lock:
            if snapshot_id in self._snapshots:
                raise ValueError("Snapshot ID already exists")

            snapshot = AnalyticsSnapshot(
                snapshot_id=snapshot_id,
                tenant_id=self.tenant_id,
                warehouse_id=warehouse_id,
                domain=domain,
                metrics=calculated,
                source_reference=source_reference,
                created_by=actor.user_id,
                created_at=utc_now(),
            )

            self._snapshots[snapshot_id] = snapshot
            self._audit.append(
                AnalyticsAuditEvent(
                    event_id=str(uuid.uuid4()),
                    tenant_id=self.tenant_id,
                    snapshot_id=snapshot_id,
                    actor_id=actor.user_id,
                    action="analytics_snapshot_created",
                    timestamp=utc_now(),
                )
            )

            return copy.deepcopy(snapshot)

    def get_snapshot(
        self,
        actor: AnalyticsActor,
        snapshot_id: str,
    ) -> AnalyticsSnapshot:
        with self._lock:
            snapshot = self._snapshots.get(snapshot_id)
            if snapshot is None:
                raise KeyError("Snapshot not found")

            self._authorize(
                actor,
                self.READER_ROLES,
                snapshot.warehouse_id,
            )
            return copy.deepcopy(snapshot)

    def list_snapshots(
        self,
        actor: AnalyticsActor,
        domain: AnalyticsDomain | None = None,
    ) -> list[AnalyticsSnapshot]:
        if not actor.is_active or actor.tenant_id != self.tenant_id:
            raise PermissionError("Analytics access denied")
        if not actor.roles.intersection(self.READER_ROLES):
            raise PermissionError("Analytics reader role required")

        with self._lock:
            return [
                copy.deepcopy(s)
                for s in self._snapshots.values()
                if (
                    (domain is None or s.domain == domain)
                    and (
                        (s.warehouse_id is None and
                         "corporate_admin" in actor.roles)
                        or (
                            s.warehouse_id is not None
                            and (
                                "corporate_admin" in actor.roles
                                or s.warehouse_id in actor.warehouse_ids
                            )
                        )
                    )
                )
            ]

    def executive_dashboard(
        self,
        actor: AnalyticsActor,
    ) -> dict[str, Any]:
        snapshots = self.list_snapshots(actor)

        # Latest snapshot per domain and scope.
        latest: dict[tuple[str, str | None], AnalyticsSnapshot] = {}

        for snapshot in snapshots:
            key = (snapshot.domain.value, snapshot.warehouse_id)
            previous = latest.get(key)
            if previous is None or (
                snapshot.created_at, snapshot.snapshot_id
            ) > (
                previous.created_at, previous.snapshot_id
            ):
                latest[key] = snapshot

        return {
            "tenant_id": self.tenant_id,
            "currency": self.currency,
            "generated_at": utc_now(),
            "domains": [
                {
                    "domain": s.domain.value,
                    "warehouse_id": s.warehouse_id,
                    "metrics": copy.deepcopy(s.metrics),
                    "source_reference": s.source_reference,
                }
                for s in latest.values()
            ],
            "snapshot_count": len(snapshots),
        }

    def audit_events(
        self,
        actor: AnalyticsActor,
        snapshot_id: str,
    ) -> list[AnalyticsAuditEvent]:
        self.get_snapshot(actor, snapshot_id)

        with self._lock:
            return [
                copy.deepcopy(event)
                for event in self._audit
                if event.snapshot_id == snapshot_id
            ]

    def export_json(
        self,
        actor: AnalyticsActor,
        output_path: str | Path,
    ) -> Path:
        dashboard = self.executive_dashboard(actor)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(dashboard, indent=2),
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    service = RetailAnalyticsService("demo")

    admin = AnalyticsActor(
        user_id="executive",
        tenant_id="demo",
        roles=frozenset({"corporate_admin"}),
    )

    service.create_snapshot(
        actor=admin,
        snapshot_id="SALES-001",
        domain=AnalyticsDomain.SALES,
        data=SalesMetricsInput(
            orders=1250,
            units_sold=3200,
            gross_revenue=Decimal("1250000"),
            discounts=Decimal("50000"),
            refunds=Decimal("20000"),
            cogs=Decimal("720000"),
        ),
        source_reference="DEMO-SALES",
    )

    service.create_snapshot(
        actor=admin,
        snapshot_id="STOCK-001",
        domain=AnalyticsDomain.INVENTORY,
        data=InventoryMetricsInput(
            sku_count=450,
            on_hand_units=12000,
            reserved_units=1500,
            low_stock_skus=32,
            inventory_value=Decimal("1850000"),
        ),
        source_reference="DEMO-INVENTORY",
        warehouse_id="WH001",
    )

    print(
        json.dumps(
            service.executive_dashboard(admin),
            indent=2,
        )
    )
