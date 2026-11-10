from __future__ import annotations

"""Planned module: analytics service. Implementation pending."""
"""Planned module: approval service. Implementation pending."""

"""
backend/services/analytics_service.py

Autonomous Retail Supply Chain AI 5.0

Retail analytics business-logic service.

Python 3.10+
Dependencies: standard library only.

Features:
- Inventory KPIs
- Inventory turnover
- Stockout and low-stock detection
- Reorder recommendations
- Sales and revenue analytics
- Supplier performance
- Logistics performance
- Demand forecast accuracy
- RAG evaluation analytics
- Executive dashboard summary

Input: trusted, tenant-scoped records.
Output: JSON-serializable dictionaries.

This service performs deterministic
analytics; it does not train ML models.
"""


import math
import statistics

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable


def finite_nonnegative(
    value: float,
    field_name: str,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value < 0
    ):
        raise ValueError(
            f"{field_name} must be finite "
            "and nonnegative"
        )
    return float(value)


def percentage(
    numerator: float,
    denominator: float,
) -> float | None:
    if denominator == 0:
        return None
    return round(
        numerator / denominator * 100,
        2,
    )


@dataclass(frozen=True)
class InventoryRecord:
    sku: str
    tenant_id: str
    category: str
    quantity_on_hand: float
    reorder_point: float
    unit_cost: float
    daily_demand: float = 0.0
    safety_stock: float = 0.0
    lead_time_days: float = 0.0


@dataclass(frozen=True)
class SalesRecord:
    order_id: str
    tenant_id: str
    sku: str
    quantity: float
    unit_price: float
    unit_cost: float
    order_date: str
    status: str = "completed"


@dataclass(frozen=True)
class SupplierRecord:
    supplier_id: str
    tenant_id: str
    orders_total: int
    orders_on_time: int
    orders_accepted: int
    average_lead_time_days: float


@dataclass(frozen=True)
class ShipmentRecord:
    shipment_id: str
    tenant_id: str
    planned_delivery: str
    actual_delivery: str | None
    transport_cost: float
    delivered: bool = True


@dataclass(frozen=True)
class ForecastRecord:
    sku: str
    tenant_id: str
    actual_demand: float
    predicted_demand: float


class RetailAnalyticsService:
    """
    Pure analytics over authorized,
    tenant-scoped business records.

    The caller must authenticate the
    user and enforce row-level access
    before passing records here.

    Tenant checks provide an additional
    defense against accidental mixing.
    """

    def __init__(
        self,
        tenant_id: str,
    ):
        if (
            not isinstance(tenant_id, str)
            or not tenant_id.strip()
        ):
            raise ValueError(
                "tenant_id is required"
            )

        self.tenant_id = tenant_id

    def _validate_tenant(
        self,
        records: Iterable[Any],
    ) -> list[Any]:
        items = list(records)

        for item in items:
            record_tenant = (
                item.get("tenant_id")
                if isinstance(item, dict)
                else getattr(
                    item,
                    "tenant_id",
                    None,
                )
            )

            if record_tenant != self.tenant_id:
                raise PermissionError(
                    "Cross-tenant record detected"
                )

        return items

    @staticmethod
    def _parse_date(
        value: str,
    ) -> date:
        return date.fromisoformat(
            value
        )

    def inventory_analytics(
        self,
        records: Iterable[InventoryRecord],
        cost_of_goods_sold: float | None = None,
        average_inventory_value: float | None = None,
    ) -> dict[str, Any]:
        records = self._validate_tenant(
            records
        )

        total_units = 0.0
        inventory_value = 0.0
        low_stock = []
        stockouts = []
        reorder_recommendations = []
        categories = defaultdict(
            lambda: {
                "units": 0.0,
                "value": 0.0,
                "sku_count": 0,
            }
        )

        for item in records:
            if not item.sku.strip():
                raise ValueError(
                    "SKU is required"
                )

            for field_name in (
                "quantity_on_hand",
                "reorder_point",
                "unit_cost",
                "daily_demand",
                "safety_stock",
                "lead_time_days",
            ):
                finite_nonnegative(
                    getattr(item, field_name),
                    field_name,
                )

            quantity = item.quantity_on_hand
            value = quantity * item.unit_cost

            total_units += quantity
            inventory_value += value

            category = categories[
                item.category
            ]
            category["units"] += quantity
            category["value"] += value
            category["sku_count"] += 1

            if quantity == 0:
                stockouts.append(item.sku)

            if quantity <= item.reorder_point:
                low_stock.append(item.sku)

                target_stock = max(
                    item.reorder_point,
                    (
                        item.daily_demand
                        * item.lead_time_days
                        + item.safety_stock
                    ),
                )

                suggested_quantity = max(
                    0.0,
                    target_stock - quantity,
                )

                reorder_recommendations.append({
                    "sku": item.sku,
                    "current_stock": quantity,
                    "target_stock": round(
                        target_stock, 2
                    ),
                    "suggested_quantity": round(
                        suggested_quantity, 2
                    ),
                    "estimated_purchase_cost": round(
                        suggested_quantity
                        * item.unit_cost,
                        2,
                    ),
                })

        turnover = None

        if cost_of_goods_sold is not None:
            cogs = finite_nonnegative(
                cost_of_goods_sold,
                "cost_of_goods_sold",
            )

            avg_value = (
                inventory_value
                if average_inventory_value is None
                else finite_nonnegative(
                    average_inventory_value,
                    "average_inventory_value",
                )
            )

            if avg_value > 0:
                turnover = round(
                    cogs / avg_value,
                    4,
                )

        return {
            "tenant_id": self.tenant_id,
            "total_skus": len(records),
            "total_units": round(
                total_units, 2
            ),
            "inventory_value": round(
                inventory_value, 2
            ),
            "low_stock_count": len(low_stock),
            "stockout_count": len(stockouts),
            "low_stock_rate_pct": percentage(
                len(low_stock),
                len(records),
            ),
            "stockout_rate_pct": percentage(
                len(stockouts),
                len(records),
            ),
            "low_stock_skus": low_stock,
            "stockout_skus": stockouts,
            "inventory_turnover": turnover,
            "category_summary": dict(categories),
            "reorder_recommendations": (
                reorder_recommendations
            ),
        }

    def sales_analytics(
        self,
        records: Iterable[SalesRecord],
    ) -> dict[str, Any]:
        records = self._validate_tenant(
            records
        )

        revenue = 0.0
        cogs = 0.0
        units_sold = 0.0
        daily_revenue = defaultdict(float)
        sku_revenue = defaultdict(float)
        completed_orders = set()
        excluded_count = 0

        for item in records:
            if not item.order_id.strip():
                raise ValueError(
                    "order_id required"
                )

            for field_name in (
                "quantity",
                "unit_price",
                "unit_cost",
            ):
                finite_nonnegative(
                    getattr(item, field_name),
                    field_name,
                )

            order_day = self._parse_date(
                item.order_date
            )

            if item.status != "completed":
                excluded_count += 1
                continue

            line_revenue = (
                item.quantity
                * item.unit_price
            )

            line_cost = (
                item.quantity
                * item.unit_cost
            )

            revenue += line_revenue
            cogs += line_cost
            units_sold += item.quantity

            completed_orders.add(
                item.order_id
            )

            daily_revenue[
                order_day.isoformat()
            ] += line_revenue

            sku_revenue[
                item.sku
            ] += line_revenue

        gross_profit = revenue - cogs

        return {
            "tenant_id": self.tenant_id,
            "completed_orders": len(
                completed_orders
            ),
            "excluded_line_items": (
                excluded_count
            ),
            "units_sold": round(
                units_sold, 2
            ),
            "revenue": round(
                revenue, 2
            ),
            "cost_of_goods_sold": round(
                cogs, 2
            ),
            "gross_profit": round(
                gross_profit, 2
            ),
            "gross_margin_pct": (
                percentage(
                    gross_profit,
                    revenue,
                )
            ),
            "average_order_value": (
                round(
                    revenue
                    / len(completed_orders),
                    2,
                )
                if completed_orders
                else None
            ),
            "daily_revenue": {
                day: round(value, 2)
                for day, value in sorted(
                    daily_revenue.items()
                )
            },
            "top_skus_by_revenue": [
                {
                    "sku": sku,
                    "revenue": round(
                        value, 2
                    ),
                }
                for sku, value in sorted(
                    sku_revenue.items(),
                    key=lambda pair: (
                        -pair[1],
                        pair[0],
                    ),
                )[:10]
            ],
        }

    def supplier_analytics(
        self,
        records: Iterable[SupplierRecord],
    ) -> dict[str, Any]:
        records = self._validate_tenant(
            records
        )

        summaries = []

        total_orders = 0
        total_on_time = 0
        total_accepted = 0
        weighted_lead_time = 0.0

        for item in records:
            if not item.supplier_id.strip():
                raise ValueError(
                    "supplier_id required"
                )

            if (
                isinstance(item.orders_total, bool)
                or not isinstance(
                    item.orders_total, int
                )
                or item.orders_total < 0
                or not (
                    0 <= item.orders_on_time
                    <= item.orders_total
                )
                or not (
                    0 <= item.orders_accepted
                    <= item.orders_total
                )
            ):
                raise ValueError(
                    "Invalid supplier order counts"
                )

            finite_nonnegative(
                item.average_lead_time_days,
                "average_lead_time_days",
            )

            total_orders += item.orders_total
            total_on_time += item.orders_on_time
            total_accepted += item.orders_accepted

            weighted_lead_time += (
                item.average_lead_time_days
                * item.orders_total
            )

            summaries.append({
                "supplier_id": item.supplier_id,
                "orders_total": item.orders_total,
                "on_time_delivery_pct": (
                    percentage(
                        item.orders_on_time,
                        item.orders_total,
                    )
                ),
                "acceptance_rate_pct": (
                    percentage(
                        item.orders_accepted,
                        item.orders_total,
                    )
                ),
                "average_lead_time_days": (
                    item.average_lead_time_days
                ),
            })

        return {
            "tenant_id": self.tenant_id,
            "supplier_count": len(records),
            "orders_total": total_orders,
            "on_time_delivery_pct": percentage(
                total_on_time,
                total_orders,
            ),
            "acceptance_rate_pct": percentage(
                total_accepted,
                total_orders,
            ),
            "weighted_average_lead_time_days": (
                round(
                    weighted_lead_time
                    / total_orders,
                    2,
                )
                if total_orders
                else None
            ),
            "suppliers": summaries,
        }

    def logistics_analytics(
        self,
        records: Iterable[ShipmentRecord],
    ) -> dict[str, Any]:
        records = self._validate_tenant(
            records
        )

        delivered_count = 0
        on_time_count = 0
        late_count = 0
        total_cost = 0.0
        delay_days = []

        for item in records:
            finite_nonnegative(
                item.transport_cost,
                "transport_cost",
            )

            planned = self._parse_date(
                item.planned_delivery
            )

            total_cost += item.transport_cost

            if not item.delivered:
                continue

            if item.actual_delivery is None:
                raise ValueError(
                    "Delivered shipment requires "
                    "actual_delivery"
                )

            actual = self._parse_date(
                item.actual_delivery
            )

            delivered_count += 1

            delay = max(
                0,
                (actual - planned).days,
            )

            delay_days.append(delay)

            if delay == 0:
                on_time_count += 1
            else:
                late_count += 1

        return {
            "tenant_id": self.tenant_id,
            "total_shipments": len(records),
            "delivered_shipments": (
                delivered_count
            ),
            "undelivered_shipments": (
                len(records) - delivered_count
            ),
            "on_time_deliveries": (
                on_time_count
            ),
            "late_deliveries": late_count,
            "on_time_delivery_pct": percentage(
                on_time_count,
                delivered_count,
            ),
            "average_delay_days": (
                round(
                    statistics.mean(delay_days),
                    2,
                )
                if delay_days
                else None
            ),
            "total_transport_cost": round(
                total_cost, 2
            ),
            "average_transport_cost": (
                round(
                    total_cost / len(records),
                    2,
                )
                if records
                else None
            ),
        }

    def forecast_analytics(
        self,
        records: Iterable[ForecastRecord],
    ) -> dict[str, Any]:
        records = self._validate_tenant(
            records
        )

        errors = []
        squared_errors = []
        absolute_percentage_errors = []

        total_actual = 0.0
        total_absolute_error = 0.0

        for item in records:
            actual = finite_nonnegative(
                item.actual_demand,
                "actual_demand",
            )

            predicted = finite_nonnegative(
                item.predicted_demand,
                "predicted_demand",
            )

            error = predicted - actual
            absolute_error = abs(error)

            errors.append(
                absolute_error
            )

            squared_errors.append(
                error ** 2
            )

            total_actual += actual
            total_absolute_error += (
                absolute_error
            )

            if actual > 0:
                absolute_percentage_errors.append(
                    absolute_error / actual
                )

        count = len(records)

        return {
            "tenant_id": self.tenant_id,
            "evaluated_forecasts": count,
            "mae": (
                round(
                    statistics.mean(errors),
                    4,
                )
                if errors
                else None
            ),
            "rmse": (
                round(
                    math.sqrt(
                        statistics.mean(
                            squared_errors
                        )
                    ),
                    4,
                )
                if squared_errors
                else None
            ),
            "mape_pct": (
                round(
                    statistics.mean(
                        absolute_percentage_errors
                    ) * 100,
                    2,
                )
                if absolute_percentage_errors
                else None
            ),
            "mape_evaluated_count": len(
                absolute_percentage_errors
            ),
            "wape_pct": (
                percentage(
                    total_absolute_error,
                    total_actual,
                )
            ),
        }

    def rag_evaluation_analytics(
        self,
        reports: Iterable[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Aggregate numeric evaluation metrics.

        Expected records:
        {
            "tenant_id": "demo",
            "metrics": {
                "faithfulness": 0.91,
                "context_recall@5": 0.85
            }
        }

        Missing metrics are excluded.
        Metrics must be finite numbers.

        This method does not merge
        query-level or source-level data.
        """
        reports = self._validate_tenant(
            reports
        )

        metric_values = defaultdict(list)

        for report in reports:
            metrics = report.get(
                "metrics",
                {},
            )

            if not isinstance(metrics, dict):
                raise ValueError(
                    "metrics must be a dictionary"
                )

            for name, value in metrics.items():
                if value is None:
                    continue

                if (
                    isinstance(value, bool)
                    or not isinstance(
                        value,
                        (int, float),
                    )
                    or not math.isfinite(
                        value
                    )
                ):
                    raise ValueError(
                        f"Invalid metric: {name}"
                    )

                metric_values[name].append(
                    float(value)
                )

        return {
            "tenant_id": self.tenant_id,
            "report_count": len(reports),
            "average_metrics": {
                name: round(
                    statistics.mean(values),
                    6,
                )
                for name, values in sorted(
                    metric_values.items()
                )
            },
            "metric_sample_counts": {
                name: len(values)
                for name, values in sorted(
                    metric_values.items()
                )
            },
        }

    def executive_dashboard(
        self,
        inventory: Iterable[InventoryRecord],
        sales: Iterable[SalesRecord],
        suppliers: Iterable[SupplierRecord],
        shipments: Iterable[ShipmentRecord],
        forecasts: Iterable[ForecastRecord],
    ) -> dict[str, Any]:
        inventory_result = (
            self.inventory_analytics(inventory)
        )

        sales_result = (
            self.sales_analytics(sales)
        )

        supplier_result = (
            self.supplier_analytics(suppliers)
        )

        logistics_result = (
            self.logistics_analytics(shipments)
        )

        forecast_result = (
            self.forecast_analytics(forecasts)
        )

        return {
            "tenant_id": self.tenant_id,
            "inventory": inventory_result,
            "sales": sales_result,
            "suppliers": supplier_result,
            "logistics": logistics_result,
            "forecasting": forecast_result,
        }


if __name__ == "__main__":
    service = RetailAnalyticsService(
        tenant_id="demo"
    )

    inventory = [
        InventoryRecord(
            sku="SKU001",
            tenant_id="demo",
            category="electronics",
            quantity_on_hand=12,
            reorder_point=40,
            unit_cost=500,
            daily_demand=5,
            safety_stock=15,
            lead_time_days=7,
        ),
        InventoryRecord(
            sku="SKU002",
            tenant_id="demo",
            category="grocery",
            quantity_on_hand=0,
            reorder_point=20,
            unit_cost=80,
            daily_demand=4,
            safety_stock=10,
            lead_time_days=3,
        ),
    ]

    sales = [
        SalesRecord(
            order_id="ORD001",
            tenant_id="demo",
            sku="SKU001",
            quantity=3,
            unit_price=750,
            unit_cost=500,
            order_date="2026-10-27",
        )
    ]

    suppliers = [
        SupplierRecord(
            supplier_id="SUP001",
            tenant_id="demo",
            orders_total=20,
            orders_on_time=18,
            orders_accepted=19,
            average_lead_time_days=5,
        )
    ]

    shipments = [
        ShipmentRecord(
            shipment_id="SHIP001",
            tenant_id="demo",
            planned_delivery="2026-10-25",
            actual_delivery="2026-10-27",
            transport_cost=1200,
        )
    ]

    forecasts = [
        ForecastRecord(
            sku="SKU001",
            tenant_id="demo",
            actual_demand=100,
            predicted_demand=95,
        )
    ]

    dashboard = service.executive_dashboard(
        inventory=inventory,
        sales=sales,
        suppliers=suppliers,
        shipments=shipments,
        forecasts=forecasts,
    )

    import json

    print(
        json.dumps(
            dashboard,
            indent=2,
        )
    )
