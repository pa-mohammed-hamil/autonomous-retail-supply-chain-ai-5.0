"""Planned module: supplier dataset. Implementation pending."""

"""
ai/datasets/supplier_dataset.py

Autonomous Retail Supply Chain AI 5.0

Synthetic Supplier Dataset Generator

Features:
- Supplier master profiles
- Purchase order records
- Ordered and delivered quantities
- Promised and actual delivery dates
- Supplier lead times
- Delivery delays
- On-time delivery status
- Quantity fill rates
- Defective units
- Defect rates
- Procurement costs
- Supplier risk scores and labels
- CSV and JSON export

Python 3.10+
Standard library only.

All supplier performance and risk
labels are synthetic.
"""

from __future__ import annotations

import csv
import json
import math
import random

from datetime import date, timedelta
from pathlib import Path


class SupplierDatasetGenerator:

    CATEGORIES = (
        "electronics",
        "groceries",
        "fashion",
        "home",
        "beauty",
        "sports",
    )

    def __init__(self, seed: int = 42):
        self.random = random.Random(seed)

    @staticmethod
    def _positive_int(value, field):
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
        ):
            raise ValueError(
                f"{field} must be a positive integer"
            )

    @staticmethod
    def _risk_label(score: float) -> str:
        if score >= 75:
            return "critical"
        if score >= 50:
            return "high"
        if score >= 25:
            return "medium"
        return "low"

    def generate(
        self,
        n_suppliers: int = 20,
        n_orders: int = 1000,
        n_skus: int = 100,
        start_date: str = "2026-01-01",
    ) -> list[dict]:

        for field, value in {
            "n_suppliers": n_suppliers,
            "n_orders": n_orders,
            "n_skus": n_skus,
        }.items():
            self._positive_int(value, field)

        start = date.fromisoformat(
            start_date
        )

        supplier_profiles = {}

        for supplier_number in range(
            1, n_suppliers + 1
        ):
            supplier_id = (
                f"SUP{supplier_number:04d}"
            )

            supplier_profiles[supplier_id] = {
                "category": self.random.choice(
                    self.CATEGORIES
                ),
                "base_lead_time_days": (
                    self.random.randint(2, 14)
                ),
                "reliability": (
                    self.random.uniform(
                        0.65, 0.99
                    )
                ),
                "base_defect_rate": (
                    self.random.uniform(
                        0.001, 0.08
                    )
                ),
                "unit_cost": (
                    round(
                        self.random.uniform(
                            50, 2000
                        ),
                        2,
                    )
                ),
            }

        records = []

        for index in range(n_orders):
            supplier_id = self.random.choice(
                list(supplier_profiles)
            )

            profile = supplier_profiles[
                supplier_id
            ]

            order_date = (
                start
                + timedelta(
                    days=self.random.randint(
                        0, 180
                    )
                )
            )

            ordered_qty = (
                self.random.randint(20, 1000)
            )

            promised_lead_time = profile[
                "base_lead_time_days"
            ]

            promised_date = (
                order_date
                + timedelta(
                    days=promised_lead_time
                )
            )

            # Lower reliability increases
            # the chance of delivery delays.
            delayed = (
                self.random.random()
                > profile["reliability"]
            )

            if delayed:
                delay_days = (
                    self.random.randint(1, 10)
                )
            else:
                delay_days = 0

            delivered_date = (
                promised_date
                + timedelta(days=delay_days)
            )

            actual_lead_time = (
                delivered_date - order_date
            ).days

            if delayed:
                fill_fraction = (
                    self.random.uniform(
                        0.7, 0.98
                    )
                )
            else:
                fill_fraction = (
                    self.random.uniform(
                        0.95, 1.0
                    )
                )

            delivered_qty = min(
                ordered_qty,
                round(
                    ordered_qty
                    * fill_fraction
                ),
            )

            missing_qty = (
                ordered_qty - delivered_qty
            )

            defect_rate = min(
                1.0,
                max(
                    0.0,
                    self.random.gauss(
                        profile["base_defect_rate"],
                        0.01,
                    ),
                ),
            )

            defective_qty = min(
                delivered_qty,
                round(
                    delivered_qty
                    * defect_rate
                ),
            )

            accepted_qty = (
                delivered_qty
                - defective_qty
            )

            fill_rate_percent = (
                delivered_qty / ordered_qty
                * 100
            )

            accepted_fill_rate_percent = (
                accepted_qty / ordered_qty
                * 100
            )

            actual_defect_rate = (
                defective_qty / delivered_qty
                * 100
                if delivered_qty else 0.0
            )

            # Risk score is a synthetic
            # weighted heuristic.
            delay_risk = min(
                100,
                delay_days * 10,
            )

            fill_risk = (
                100 - fill_rate_percent
            )

            quality_risk = min(
                100,
                actual_defect_rate * 5,
            )

            risk_score = (
                0.4 * delay_risk
                + 0.3 * fill_risk
                + 0.3 * quality_risk
            )

            unit_cost = profile[
                "unit_cost"
            ]

            ordered_cost = (
                ordered_qty * unit_cost
            )

            delivered_cost = (
                delivered_qty * unit_cost
            )

            accepted_cost = (
                accepted_qty * unit_cost
            )

            records.append({
                "purchase_order_id": (
                    f"PO{index + 1:06d}"
                ),
                "supplier_id": supplier_id,
                "sku": (
                    f"SKU{self.random.randint(1, n_skus):04d}"
                ),
                "category": (
                    profile["category"]
                ),
                "order_date": (
                    order_date.isoformat()
                ),
                "promised_date": (
                    promised_date.isoformat()
                ),
                "delivered_date": (
                    delivered_date.isoformat()
                ),
                "promised_lead_time_days": (
                    promised_lead_time
                ),
                "actual_lead_time_days": (
                    actual_lead_time
                ),
                "delivery_delay_days": (
                    delay_days
                ),
                "on_time_delivery": (
                    delay_days == 0
                ),
                "ordered_qty": ordered_qty,
                "delivered_qty": delivered_qty,
                "missing_qty": missing_qty,
                "defective_qty": defective_qty,
                "accepted_qty": accepted_qty,
                "fill_rate_percent": round(
                    fill_rate_percent, 4
                ),
                "accepted_fill_rate_percent": round(
                    accepted_fill_rate_percent, 4
                ),
                "defect_rate_percent": round(
                    actual_defect_rate, 4
                ),
                "supplier_reliability": round(
                    profile["reliability"], 4
                ),
                "unit_cost": unit_cost,
                "ordered_cost": round(
                    ordered_cost, 2
                ),
                "delivered_cost": round(
                    delivered_cost, 2
                ),
                "accepted_cost": round(
                    accepted_cost, 2
                ),
                "risk_score": round(
                    risk_score, 4
                ),
                "risk_label": (
                    self._risk_label(
                        risk_score
                    )
                ),
                "currency": "INR",
            })

        return records

    @staticmethod
    def save_csv(records, path):
        if not records:
            raise ValueError(
                "Cannot export empty dataset"
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
    def save_json(records, path):
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
    generator = SupplierDatasetGenerator(
        seed=42
    )

    dataset = generator.generate(
        n_suppliers=20,
        n_orders=1000,
        n_skus=100,
    )

    generator.save_csv(
        dataset,
        "data/synthetic/supplier_dataset.csv",
    )

    generator.save_json(
        dataset,
        "data/synthetic/supplier_dataset.json",
    )

    print(
        f"Generated {len(dataset)} "
        "synthetic supplier records"
    )
