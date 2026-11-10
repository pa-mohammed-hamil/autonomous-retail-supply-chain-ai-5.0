"""Planned module: exponential smoothing. Implementation pending."""

"""
ai/features/supplier_features.py

Autonomous Retail Supply Chain AI 5.0

Supplier Feature Engineering

Features:
- Historical supplier on-time rate
- Historical delivery delays
- Lead-time averages and volatility
- Historical quantity fill rate
- Historical accepted fill rate
- Defect rate history
- Procurement unit-cost trends
- Previous purchase-order outcomes
- Historical supplier risk score
- Rolling supplier performance
- CSV and JSON export

Prediction assumption:
Features are generated when a new
purchase order is placed.

Only orders already delivered before
the new order date contribute to
historical features.

Standard library only.
Python 3.10+
"""

from __future__ import annotations

import csv
import heapq
import json
import math

from collections import defaultdict, deque
from datetime import date
from pathlib import Path
from statistics import mean, pstdev
from typing import Sequence


class SupplierFeatureEngineer:

    def __init__(
        self,
        history_window: int = 30,
    ):
        if (
            isinstance(history_window, bool)
            or not isinstance(history_window, int)
            or history_window < 1
        ):
            raise ValueError(
                "history_window must be positive"
            )

        self.history_window = history_window

    @staticmethod
    def _number(value, field):
        if isinstance(value, bool):
            raise ValueError(
                f"{field} must be numeric"
            )

        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid {field}"
            ) from exc

        if not math.isfinite(number):
            raise ValueError(
                f"{field} must be finite"
            )

        return number

    @staticmethod
    def _average(values):
        return (
            round(mean(values), 4)
            if values else None
        )

    @staticmethod
    def _std(values):
        return (
            round(pstdev(values), 4)
            if values else None
        )

    def transform(
        self,
        records: Sequence[dict],
    ) -> list[dict]:
        if not records:
            raise ValueError(
                "Supplier dataset is empty"
            )

        prepared = []

        for index, original in enumerate(records):
            row = dict(original)

            ordered_at = date.fromisoformat(
                str(row["order_date"])
            )

            delivered_at = date.fromisoformat(
                str(row["delivered_date"])
            )

            if delivered_at < ordered_at:
                raise ValueError(
                    "Delivery date precedes order date"
                )

            ordered_qty = self._number(
                row["ordered_qty"],
                "ordered_qty",
            )

            delivered_qty = self._number(
                row["delivered_qty"],
                "delivered_qty",
            )

            defective_qty = self._number(
                row["defective_qty"],
                "defective_qty",
            )

            unit_cost = self._number(
                row["unit_cost"],
                "unit_cost",
            )

            promised_lead = self._number(
                row["promised_lead_time_days"],
                "promised_lead_time_days",
            )

            if (
                ordered_qty <= 0
                or delivered_qty < 0
                or delivered_qty > ordered_qty
                or defective_qty < 0
                or defective_qty > delivered_qty
                or unit_cost < 0
                or promised_lead < 0
            ):
                raise ValueError(
                    "Invalid supplier quantities"
                )

            row["_index"] = index
            row["_ordered_at"] = ordered_at
            row["_delivered_at"] = delivered_at
            row["_ordered_qty"] = ordered_qty
            row["_delivered_qty"] = delivered_qty
            row["_defective_qty"] = defective_qty
            row["_unit_cost"] = unit_cost
            row["_promised_lead"] = promised_lead

            prepared.append(row)

        prepared.sort(
            key=lambda row: (
                row["_ordered_at"],
                row["_index"],
            )
        )

        histories = defaultdict(
            lambda: deque(
                maxlen=self.history_window
            )
        )

        # Completed orders become available
        # to future feature calculations.
        pending = []

        results = []

        for row in prepared:
            order_date = row["_ordered_at"]

            while (
                pending
                and pending[0][0] < order_date
            ):
                _, _, completed = (
                    heapq.heappop(pending)
                )

                ordered_qty = completed[
                    "_ordered_qty"
                ]

                delivered_qty = completed[
                    "_delivered_qty"
                ]

                accepted_qty = (
                    delivered_qty
                    - completed["_defective_qty"]
                )

                actual_lead = (
                    completed["_delivered_at"]
                    - completed["_ordered_at"]
                ).days

                delay = max(
                    0,
                    actual_lead
                    - completed["_promised_lead"],
                )

                observation = {
                    "actual_lead": actual_lead,
                    "delay": delay,
                    "on_time": int(delay == 0),
                    "fill_rate": (
                        delivered_qty
                        / ordered_qty
                    ),
                    "accepted_fill_rate": (
                        accepted_qty
                        / ordered_qty
                    ),
                    "defect_rate": (
                        completed["_defective_qty"]
                        / delivered_qty
                        if delivered_qty > 0
                        else 0.0
                    ),
                    "unit_cost": (
                        completed["_unit_cost"]
                    ),
                }

                histories[
                    completed["supplier_id"]
                ].append(observation)

            supplier_id = row["supplier_id"]

            history = list(
                histories[supplier_id]
            )

            def metric(name):
                return [
                    item[name]
                    for item in history
                ]

            lead_times = metric(
                "actual_lead"
            )

            delays = metric("delay")
            on_time = metric("on_time")
            fill_rates = metric("fill_rate")
            accepted_rates = metric(
                "accepted_fill_rate"
            )
            defect_rates = metric(
                "defect_rate"
            )
            costs = metric("unit_cost")

            historical_delay_rate = (
                1 - mean(on_time)
                if on_time else None
            )

            historical_fill = (
                mean(fill_rates)
                if fill_rates else None
            )

            historical_defect = (
                mean(defect_rates)
                if defect_rates else None
            )

            historical_risk_proxy = None

            if (
                historical_delay_rate is not None
                and historical_fill is not None
                and historical_defect is not None
            ):
                historical_risk_proxy = (
                    40 * historical_delay_rate
                    + 30 * (1 - historical_fill)
                    + 30 * historical_defect
                )

            features = {
                "purchase_order_id": (
                    row["purchase_order_id"]
                ),
                "supplier_id": supplier_id,
                "sku": row["sku"],
                "category": row.get("category"),
                "order_date": row["order_date"],
                "ordered_qty": (
                    row["_ordered_qty"]
                ),
                "promised_lead_time_days": (
                    row["_promised_lead"]
                ),
                "unit_cost": row["_unit_cost"],
                "ordered_cost": round(
                    row["_ordered_qty"]
                    * row["_unit_cost"],
                    2,
                ),
                "supplier_history_count": (
                    len(history)
                ),
                "historical_on_time_rate": (
                    self._average(on_time)
                ),
                "historical_delay_rate": (
                    round(
                        historical_delay_rate, 4
                    )
                    if historical_delay_rate is not None
                    else None
                ),
                "historical_mean_delay_days": (
                    self._average(delays)
                ),
                "historical_mean_lead_time": (
                    self._average(lead_times)
                ),
                "historical_lead_time_std": (
                    self._std(lead_times)
                ),
                "historical_fill_rate": (
                    self._average(fill_rates)
                ),
                "historical_accepted_fill_rate": (
                    self._average(accepted_rates)
                ),
                "historical_defect_rate": (
                    self._average(defect_rates)
                ),
                "historical_unit_cost_mean": (
                    self._average(costs)
                ),
                "previous_delivery_delay_days": (
                    delays[-1]
                    if delays else None
                ),
                "previous_actual_lead_time": (
                    lead_times[-1]
                    if lead_times else None
                ),
                "historical_risk_proxy": (
                    round(
                        historical_risk_proxy, 4
                    )
                    if historical_risk_proxy is not None
                    else None
                ),
            }

            results.append((
                row["_index"],
                features,
            ))

            heapq.heappush(
                pending,
                (
                    row["_delivered_at"],
                    row["_index"],
                    row,
                ),
            )

        results.sort(
            key=lambda pair: pair[0]
        )

        return [
            features
            for _, features in results
        ]

    def transform_csv(
        self,
        input_path: str,
        output_path: str,
    ) -> list[dict]:
        with open(
            input_path,
            newline="",
            encoding="utf-8-sig",
        ) as file:
            records = list(
                csv.DictReader(file)
            )

        features = self.transform(records)

        self.save_csv(
            features,
            output_path,
        )

        return features

    @staticmethod
    def save_csv(records, path):
        if not records:
            raise ValueError(
                "Cannot export empty features"
            )

        output = Path(path)
        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        fields = list(dict.fromkeys(
            key
            for row in records
            for key in row
        ))

        with output.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=fields,
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
    engineer = SupplierFeatureEngineer(
        history_window=30
    )

    features = engineer.transform_csv(
        "data/synthetic/supplier_dataset.csv",
        "data/features/supplier_features.csv",
    )

    engineer.save_json(
        features,
        "data/features/supplier_features.json",
    )

    print(
        f"Generated {len(features)} "
        "supplier feature records"
    )
