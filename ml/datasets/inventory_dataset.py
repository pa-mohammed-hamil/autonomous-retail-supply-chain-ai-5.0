"""Planned module: inventory dataset. Implementation pending."""

"""
ai/datasets/inventory_dataset.py

Autonomous Retail Supply Chain AI 5.0

Synthetic Inventory Dataset

Features:
- Multi-store inventory
- SKU demand history
- Daily sales and lost demand
- Inventory replenishment
- Supplier lead times
- Reorder points
- Safety stock
- Stockout labels
- Inventory holding costs
- Reproducible generation
- CSV/JSON export

Standard library only.

Simplified inventory simulator:
- Demand is generated synthetically.
- Replenishment orders arrive after lead time.
- Sales cannot exceed available inventory.
- Unfulfilled demand is treated as lost sales.
- No returns, cancellations or backorders.
"""

from __future__ import annotations

import csv
import json
import math
import random

from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path


class InventoryDatasetGenerator:

    def __init__(
        self,
        seed: int = 42,
    ):
        self.random = random.Random(seed)

    @staticmethod
    def _validate_positive_int(
        value: int,
        field: str,
    ) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
        ):
            raise ValueError(
                f"{field} must be positive"
            )

    def generate(
        self,
        n_stores: int = 5,
        n_skus: int = 30,
        n_days: int = 90,
        start_date: str = "2026-01-01",
    ) -> list[dict]:
        for field, value in {
            "n_stores": n_stores,
            "n_skus": n_skus,
            "n_days": n_days,
        }.items():
            self._validate_positive_int(
                value, field
            )

        start = date.fromisoformat(
            start_date
        )

        records = []

        for store_number in range(
            1, n_stores + 1
        ):
            store_id = (
                f"STORE{store_number:03d}"
            )

            for sku_number in range(
                1, n_skus + 1
            ):
                sku = f"SKU{sku_number:04d}"

                average_daily_demand = (
                    self.random.randint(5, 40)
                )

                lead_time_days = (
                    self.random.randint(2, 8)
                )

                safety_stock = math.ceil(
                    average_daily_demand
                    * lead_time_days
                    * 0.3
                )

                reorder_point = (
                    average_daily_demand
                    * lead_time_days
                    + safety_stock
                )

                order_quantity = max(
                    1,
                    average_daily_demand * 14
                )

                unit_cost = round(
                    self.random.uniform(
                        50, 1500
                    ),
                    2,
                )

                unit_price = round(
                    unit_cost
                    * self.random.uniform(
                        1.15, 1.6
                    ),
                    2,
                )

                inventory = (
                    reorder_point
                    + self.random.randint(
                        0, order_quantity
                    )
                )

                # Pending replenishments:
                # arrival_date -> quantity
                pending_orders = defaultdict(int)

                for day_index in range(n_days):
                    current_date = (
                        start
                        + timedelta(days=day_index)
                    )

                    arrivals = pending_orders.pop(
                        current_date, 0
                    )

                    opening_inventory = inventory
                    inventory += arrivals

                    day_of_week = (
                        current_date.weekday()
                    )

                    weekend_factor = (
                        1.2
                        if day_of_week >= 5
                        else 1.0
                    )

                    seasonality = (
                        1
                        + 0.15 * math.sin(
                            2 * math.pi
                            * day_index / 30
                        )
                    )

                    expected_demand = (
                        average_daily_demand
                        * weekend_factor
                        * seasonality
                    )

                    demand = max(
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

                    fulfilled = min(
                        inventory, demand
                    )

                    lost_sales = (
                        demand - fulfilled
                    )

                    inventory -= fulfilled

                    closing_inventory = inventory

                    # Inventory position includes
                    # outstanding replenishments.
                    outstanding = sum(
                        pending_orders.values()
                    )

                    inventory_position = (
                        closing_inventory
                        + outstanding
                    )

                    replenishment_ordered = 0

                    if (
                        inventory_position
                        <= reorder_point
                    ):
                        replenishment_ordered = (
                            order_quantity
                        )

                        arrival_date = (
                            current_date
                            + timedelta(
                                days=lead_time_days
                            )
                        )

                        pending_orders[
                            arrival_date
                        ] += order_quantity

                    stockout = (
                        lost_sales > 0
                    )

                    holding_cost = round(
                        closing_inventory
                        * unit_cost
                        * 0.0005,
                        2,
                    )

                    records.append({
                        "date": (
                            current_date.isoformat()
                        ),
                        "store_id": store_id,
                        "sku": sku,
                        "opening_inventory": (
                            opening_inventory
                        ),
                        "received_qty": arrivals,
                        "demand_qty": demand,
                        "fulfilled_qty": fulfilled,
                        "lost_sales_qty": lost_sales,
                        "closing_inventory": (
                            closing_inventory
                        ),
                        "stockout": stockout,
                        "average_daily_demand": (
                            average_daily_demand
                        ),
                        "lead_time_days": (
                            lead_time_days
                        ),
                        "safety_stock": safety_stock,
                        "reorder_point": reorder_point,
                        "replenishment_ordered": (
                            replenishment_ordered
                        ),
                        "outstanding_order_qty": sum(
                            pending_orders.values()
                        ),
                        "unit_cost": unit_cost,
                        "unit_price": unit_price,
                        "holding_cost": holding_cost,
                    })

        return records

    @staticmethod
    def save_csv(
        records: list[dict],
        path: str,
    ) -> None:
        if not records:
            raise ValueError(
                "Cannot export empty inventory dataset"
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
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    generator = InventoryDatasetGenerator(
        seed=42
    )

    dataset = generator.generate(
        n_stores=5,
        n_skus=30,
        n_days=90,
    )

    generator.save_csv(
        dataset,
        "data/synthetic/inventory_dataset.csv",
    )

    generator.save_json(
        dataset,
        "data/synthetic/inventory_dataset.json",
    )

    print(
        f"Generated {len(dataset)} "
        "synthetic inventory records"
    )
