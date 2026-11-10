"""Planned module: sales tools. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
File: ai/tools/sales_tools.py

Sales analytics and transaction intelligence.
Python 3.10+ | Standard library only
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from typing import Any
import math
import uuid


class SalesError(ValueError):
    """Invalid sales operation."""


def validate_amount(
    value: Any,
    name: str
) -> float:

    if isinstance(value, bool) or not isinstance(
        value, (int, float)
    ):
        raise SalesError(
            f"{name} must be numeric."
        )

    try:
        number = float(value)
    except (ValueError, OverflowError) as exc:
        raise SalesError(
            f"Invalid {name}."
        ) from exc

    if not math.isfinite(number) or number < 0:
        raise SalesError(
            f"{name} must be finite and non-negative."
        )

    return number


def validate_quantity(
    value: int
) -> int:

    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        raise SalesError(
            "Quantity must be a positive integer."
        )

    return value


@dataclass
class SaleTransaction:
    transaction_id: str
    product_id: str
    store_id: str
    quantity: int
    unit_price: float
    unit_cost: float
    sold_at: str
    discount_percent: float = 0.0


class SalesLedger:
    """In-memory sales transaction ledger."""

    def __init__(self) -> None:
        self.transactions: dict[
            str, SaleTransaction
        ] = {}

    def record_sale(
        self,
        product_id: str,
        store_id: str,
        quantity: int,
        unit_price: float,
        unit_cost: float,
        discount_percent: float = 0
    ) -> dict[str, Any]:

        if not product_id or not store_id:
            raise SalesError(
                "Product and store IDs are required."
            )

        quantity = validate_quantity(quantity)

        price = validate_amount(
            unit_price, "unit_price"
        )

        cost = validate_amount(
            unit_cost, "unit_cost"
        )

        discount = validate_amount(
            discount_percent,
            "discount_percent"
        )

        if discount > 100:
            raise SalesError(
                "Discount cannot exceed 100%."
            )

        transaction = SaleTransaction(
            transaction_id=str(uuid.uuid4()),
            product_id=product_id,
            store_id=store_id,
            quantity=quantity,
            unit_price=price,
            unit_cost=cost,
            sold_at=datetime.now(
                timezone.utc
            ).isoformat(),
            discount_percent=discount
        )

        self.transactions[
            transaction.transaction_id
        ] = transaction

        return {
            "success": True,
            "transaction": asdict(transaction),
            "metrics": calculate_transaction_metrics(
                transaction
            )
        }

    def list_sales(
        self,
        store_id: str | None = None,
        product_id: str | None = None
    ) -> list[SaleTransaction]:

        results = list(
            self.transactions.values()
        )

        if store_id is not None:
            results = [
                sale for sale in results
                if sale.store_id == store_id
            ]

        if product_id is not None:
            results = [
                sale for sale in results
                if sale.product_id == product_id
            ]

        return results


def calculate_transaction_metrics(
    sale: SaleTransaction
) -> dict[str, Any]:

    quantity = validate_quantity(
        sale.quantity
    )

    price = validate_amount(
        sale.unit_price, "unit_price"
    )

    cost = validate_amount(
        sale.unit_cost, "unit_cost"
    )

    discount = validate_amount(
        sale.discount_percent,
        "discount_percent"
    )

    if discount > 100:
        raise SalesError(
            "Discount cannot exceed 100%."
        )

    gross_revenue = quantity * price

    discount_amount = (
        gross_revenue * discount / 100
    )

    net_revenue = (
        gross_revenue - discount_amount
    )

    cost_of_goods = quantity * cost

    gross_profit = (
        net_revenue - cost_of_goods
    )

    return {
        "transaction_id": sale.transaction_id,
        "gross_revenue": round(
            gross_revenue, 2
        ),
        "discount_amount": round(
            discount_amount, 2
        ),
        "net_revenue": round(
            net_revenue, 2
        ),
        "cost_of_goods": round(
            cost_of_goods, 2
        ),
        "gross_profit": round(
            gross_profit, 2
        ),
        "gross_margin_percent": (
            round(
                gross_profit / net_revenue * 100,
                2
            )
            if net_revenue > 0 else None
        ),
        "currency": "INR"
    }


def generate_sales_summary(
    transactions: list[SaleTransaction]
) -> dict[str, Any]:

    total_revenue = 0.0
    total_cost = 0.0
    total_profit = 0.0
    total_units = 0

    for sale in transactions:
        metrics = calculate_transaction_metrics(
            sale
        )

        total_revenue += metrics["net_revenue"]
        total_cost += metrics["cost_of_goods"]
        total_profit += metrics["gross_profit"]
        total_units += sale.quantity

    count = len(transactions)

    return {
        "transaction_count": count,
        "total_units_sold": total_units,
        "total_revenue": round(
            total_revenue, 2
        ),
        "total_cost": round(
            total_cost, 2
        ),
        "gross_profit": round(
            total_profit, 2
        ),
        "average_transaction_value": (
            round(total_revenue / count, 2)
            if count > 0 else None
        ),
        "gross_margin_percent": (
            round(
                total_profit / total_revenue * 100,
                2
            )
            if total_revenue > 0 else None
        ),
        "currency": "INR"
    }


def get_top_selling_products(
    transactions: list[SaleTransaction],
    limit: int = 10
) -> list[dict[str, Any]]:

    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or limit <= 0
    ):
        raise SalesError(
            "Limit must be a positive integer."
        )

    product_totals = defaultdict(
        lambda: {
            "units_sold": 0,
            "revenue": 0.0
        }
    )

    for sale in transactions:
        metrics = calculate_transaction_metrics(
            sale
        )

        product = product_totals[
            sale.product_id
        ]

        product["units_sold"] += (
            sale.quantity
        )

        product["revenue"] += (
            metrics["net_revenue"]
        )

    results = [
        {
            "product_id": product_id,
            "units_sold": values["units_sold"],
            "revenue": round(
                values["revenue"], 2
            )
        }
        for product_id, values
        in product_totals.items()
    ]

    return sorted(
        results,
        key=lambda item: (
            -item["units_sold"],
            -item["revenue"]
        )
    )[:limit]


def generate_daily_sales_report(
    transactions: list[SaleTransaction]
) -> list[dict[str, Any]]:

    grouped = defaultdict(list)

    for sale in transactions:
        try:
            sale_date = datetime.fromisoformat(
                sale.sold_at.replace(
                    "Z", "+00:00"
                )
            ).date().isoformat()
        except ValueError as exc:
            raise SalesError(
                "Invalid sold_at timestamp."
            ) from exc

        grouped[sale_date].append(sale)

    return [
        {
            "date": day,
            **generate_sales_summary(
                grouped[day]
            )
        }
        for day in sorted(grouped)
    ]


def calculate_sales_growth(
    previous_revenue: float,
    current_revenue: float
) -> dict[str, Any]:

    previous = validate_amount(
        previous_revenue,
        "previous_revenue"
    )

    current = validate_amount(
        current_revenue,
        "current_revenue"
    )

    if previous == 0:
        return {
            "growth_percent": None,
            "reason": (
                "Previous revenue is zero."
            )
        }

    growth = (
        (current - previous)
        / previous * 100
    )

    return {
        "previous_revenue": previous,
        "current_revenue": current,
        "growth_percent": round(
            growth, 2
        ),
        "trend": (
            "increasing" if growth > 0
            else "decreasing" if growth < 0
            else "stable"
        )
    }


def detect_sales_spike(
    historical_daily_sales: list[float],
    current_daily_sales: float,
    multiplier: float = 1.5
) -> dict[str, Any]:

    if len(historical_daily_sales) < 3:
        raise SalesError(
            "At least three historical values required."
        )

    history = [
        validate_amount(
            value, "historical_sale"
        )
        for value in historical_daily_sales
    ]

    current = validate_amount(
        current_daily_sales,
        "current_daily_sales"
    )

    multiplier = validate_amount(
        multiplier, "multiplier"
    )

    if multiplier <= 1:
        raise SalesError(
            "Multiplier must exceed 1."
        )

    average = sum(history) / len(history)
    threshold = average * multiplier

    spike = (
        current > threshold
        if average > 0
        else current > 0
    )

    return {
        "historical_average": round(
            average, 2
        ),
        "current_sales": current,
        "spike_threshold": round(
            threshold, 2
        ),
        "spike_detected": spike,
        "increase_percent": (
            round(
                (current - average)
                / average * 100, 2
            )
            if average > 0 else None
        ),
        "method": "historical_average_baseline"
    }


def generate_sales_alert(
    historical_daily_sales: list[float],
    current_daily_sales: float,
    store_id: str
) -> dict[str, Any] | None:

    result = detect_sales_spike(
        historical_daily_sales,
        current_daily_sales
    )

    if not result["spike_detected"]:
        return None

    return {
        "alert_type": "sales_demand_spike",
        "store_id": store_id,
        "severity": "high",
        "message": (
            "Sales significantly exceed "
            "the historical baseline."
        ),
        "current_sales": current_daily_sales,
        "historical_average": (
            result["historical_average"]
        ),
        "requires_review": True,
        "status": "pending",
        "created_at": datetime.now(
            timezone.utc
        ).isoformat()
    }


if __name__ == "__main__":
    ledger = SalesLedger()

    ledger.record_sale(
        product_id="SKU-1001",
        store_id="STORE-001",
        quantity=5,
        unit_price=999,
        unit_cost=650,
        discount_percent=10
    )

    ledger.record_sale(
        product_id="SKU-1002",
        store_id="STORE-001",
        quantity=3,
        unit_price=1499,
        unit_cost=950
    )

    sales = ledger.list_sales(
        store_id="STORE-001"
    )

    print(generate_sales_summary(sales))
    print(get_top_selling_products(sales))
    print(generate_daily_sales_report(sales))
