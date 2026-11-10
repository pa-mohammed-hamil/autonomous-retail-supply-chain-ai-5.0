"""Planned module: sales dataset. Implementation pending."""

"""
ai/datasets/sales_dataset.py

Autonomous Retail Supply Chain AI 5.0

Synthetic Sales Dataset Generator

Features:
- Multi-store daily sales
- SKU and product categories
- Actual customer demand
- Units sold and lost sales
- Product prices and discounts
- Promotional campaigns
- Gross and net revenue
- Product returns
- Cost of goods sold
- Gross profit and profit margin
- Sales channels
- Seasonal demand patterns
- CSV and JSON export

Python 3.10+
Standard library only.

All records are synthetic.
"""

from __future__ import annotations

import csv
import json
import math
import random

from datetime import date, timedelta
from pathlib import Path


class SalesDatasetGenerator:

    CATEGORIES = (
        "electronics",
        "groceries",
        "fashion",
        "home",
        "beauty",
        "sports",
    )

    CHANNELS = (
        "online",
        "in_store",
        "mobile_app",
    )

    def __init__(self, seed: int = 42):
        self.random = random.Random(seed)

    @staticmethod
    def _positive_int(value, name):
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
        ):
            raise ValueError(
                f"{name} must be a positive integer"
            )

    def generate(
        self,
        n_stores: int = 5,
        n_skus: int = 30,
        n_days: int = 90,
        start_date: str = "2026-01-01",
    ) -> list[dict]:

        for name, value in {
            "n_stores": n_stores,
            "n_skus": n_skus,
            "n_days": n_days,
        }.items():
            self._positive_int(value, name)

        start = date.fromisoformat(start_date)

        records = []

        # Global product metadata remains
        # consistent across stores.
        products = {}

        for sku_number in range(1, n_skus + 1):
            sku = f"SKU{sku_number:04d}"

            unit_cost = round(
                self.random.uniform(50, 1500),
                2,
            )

            base_price = round(
                unit_cost
                * self.random.uniform(1.2, 1.8),
                2,
            )

            products[sku] = {
                "category": self.random.choice(
                    self.CATEGORIES
                ),
                "unit_cost": unit_cost,
                "base_price": base_price,
                "base_daily_demand": (
                    self.random.randint(5, 50)
                ),
            }

        for store_number in range(
            1, n_stores + 1
        ):
            store_id = f"STORE{store_number:03d}"

            store_demand_factor = (
                self.random.uniform(0.7, 1.3)
            )

            for sku, product in products.items():
                phase = self.random.uniform(
                    0, 2 * math.pi
                )

                for day_index in range(n_days):
                    current_date = (
                        start
                        + timedelta(days=day_index)
                    )

                    weekend_factor = (
                        1.2
                        if current_date.weekday() >= 5
                        else 1.0
                    )

                    seasonal_factor = (
                        1
                        + 0.15 * math.sin(
                            2 * math.pi
                            * day_index / 30
                            + phase
                        )
                    )

                    promotion_active = (
                        self.random.random() < 0.15
                    )

                    discount_percent = (
                        self.random.choice(
                            [5, 10, 15, 20]
                        )
                        if promotion_active
                        else 0
                    )

                    selling_price = round(
                        product["base_price"]
                        * (
                            1 - discount_percent / 100
                        ),
                        2,
                    )

                    expected_demand = (
                        product["base_daily_demand"]
                        * store_demand_factor
                        * weekend_factor
                        * seasonal_factor
                        * (
                            1.25
                            if promotion_active
                            else 1.0
                        )
                    )

                    actual_demand = max(
                        0,
                        round(
                            self.random.gauss(
                                expected_demand,
                                max(
                                    1,
                                    expected_demand * 0.2
                                ),
                            )
                        ),
                    )

                    # Independent synthetic
                    # daily inventory availability.
                    available_inventory = max(
                        0,
                        round(
                            actual_demand
                            * self.random.uniform(
                                0.65, 1.6
                            )
                        ),
                    )

                    units_sold = min(
                        actual_demand,
                        available_inventory,
                    )

                    lost_sales_units = (
                        actual_demand - units_sold
                    )

                    return_rate = (
                        self.random.uniform(
                            0.0, 0.08
                        )
                    )

                    returned_units = min(
                        units_sold,
                        round(
                            units_sold * return_rate
                        ),
                    )

                    net_units = (
                        units_sold - returned_units
                    )

                    gross_revenue = round(
                        units_sold * selling_price,
                        2,
                    )

                    return_value = round(
                        returned_units
                        * selling_price,
                        2,
                    )

                    net_revenue = round(
                        gross_revenue - return_value,
                        2,
                    )

                    # Simplification: all returns
                    # are treated as recoverable
                    # inventory, so their COGS
                    # are reversed.
                    cogs = round(
                        net_units
                        * product["unit_cost"],
                        2,
                    )

                    gross_profit = round(
                        net_revenue - cogs,
                        2,
                    )

                    margin = (
                        100 * gross_profit
                        / net_revenue
                        if net_revenue > 0
                        else None
                    )

                    records.append({
                        "date": (
                            current_date.isoformat()
                        ),
                        "store_id": store_id,
                        "sku": sku,
                        "category": (
                            product["category"]
                        ),
                        "sales_channel": (
                            self.random.choice(
                                self.CHANNELS
                            )
                        ),
                        "promotion_active": (
                            promotion_active
                        ),
                        "discount_percent": (
                            discount_percent
                        ),
                        "unit_cost": (
                            product["unit_cost"]
                        ),
                        "base_price": (
                            product["base_price"]
                        ),
                        "selling_price": (
                            selling_price
                        ),
                        "actual_demand": (
                            actual_demand
                        ),
                        "available_inventory": (
                            available_inventory
                        ),
                        "units_sold": units_sold,
                        "lost_sales_units": (
                            lost_sales_units
                        ),
                        "returned_units": (
                            returned_units
                        ),
                        "net_units_sold": (
                            net_units
                        ),
                        "gross_revenue": (
                            gross_revenue
                        ),
                        "return_value": (
                            return_value
                        ),
                        "net_revenue": (
                            net_revenue
                        ),
                        "cogs": cogs,
                        "gross_profit": (
                            gross_profit
                        ),
                        "gross_margin_percent": (
                            round(margin, 4)
                            if margin is not None
                            else None
                        ),
                        "stockout_occurred": (
                            lost_sales_units > 0
                        ),
                        "currency": "INR",
                    })

        return records

    @staticmethod
    def save_csv(
        records: list[dict],
        path: str,
    ) -> None:
        if not records:
            raise ValueError(
                "Cannot export an empty dataset"
            )

        output = Path(path)
        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with output.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=list(records[0]),
            )
            writer.writeheader()
            writer.writerows(records)

    @staticmethod
    def save_json(
        records: list[dict],
        path: str,
    ) -> None:
        output = Path(path)
        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            json.dumps(
                records,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    generator = SalesDatasetGenerator(
        seed=42
    )

    dataset = generator.generate(
        n_stores=5,
        n_skus=30,
        n_days=90,
    )

    generator.save_csv(
        dataset,
        "data/synthetic/sales_dataset.csv",
    )

    generator.save_json(
        dataset,
        "data/synthetic/sales_dataset.json",
    )

    print(
        f"Generated {len(dataset)} "
        "synthetic sales records"
    )
    