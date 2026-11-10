"""Planned module: inventory features. Implementation pending."""

"""
ai/features/inventory_features.py

Autonomous Retail Supply Chain AI 5.0

Inventory Feature Engineering

Features:
- Demand lag features
- Rolling demand averages
- Rolling demand volatility
- Historical stockout frequency
- Inventory coverage days
- Inventory-to-demand ratio
- Lead-time demand estimate
- Reorder point gap
- Safety stock coverage
- Replenishment indicator
- Multi-store / multi-SKU grouping
- CSV and JSON export

Python 3.10+
Standard library only.

Historical demand and stockout
features exclude the current row
to reduce target leakage.
"""

from __future__ import annotations

import csv
import json
import math

from collections import defaultdict, deque
from datetime import date
from pathlib import Path
from statistics import mean, pstdev
from typing import Sequence


class InventoryFeatureEngineer:

    def __init__(
        self,
        lags: tuple[int, ...] = (1, 7, 14),
        windows: tuple[int, ...] = (7, 14, 30),
    ):
        if (
            not lags
            or not windows
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 1
                for value in (*lags, *windows)
            )
        ):
            raise ValueError(
                "Lags and windows must contain "
                "positive integers"
            )

        self.lags = tuple(sorted(set(lags)))
        self.windows = tuple(
            sorted(set(windows))
        )

    @staticmethod
    def _number(
        value,
        field: str,
    ) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid numeric field: {field}"
            ) from exc

        if not math.isfinite(number):
            raise ValueError(
                f"{field} must be finite"
            )

        return number

    @staticmethod
    def _boolean(value) -> bool:
        if isinstance(value, bool):
            return value

        if isinstance(value, (int, float)):
            if value in (0, 1):
                return bool(value)

        if isinstance(value, str):
            normalized = value.strip().lower()

            if normalized in {
                "true", "1", "yes"
            }:
                return True

            if normalized in {
                "false", "0", "no"
            }:
                return False

        raise ValueError(
            f"Invalid boolean: {value}"
        )

    def transform(
        self,
        records: Sequence[dict],
        demand_column: str = "demand_qty",
        inventory_column: str = "closing_inventory",
    ) -> list[dict]:
        if not records:
            raise ValueError(
                "Inventory dataset is empty"
            )

        groups = defaultdict(list)

        for record in records:
            key = (
                record["store_id"],
                record["sku"],
            )

            groups[key].append(
                dict(record)
            )

        output = []

        max_history = max(
            *self.lags,
            *self.windows,
        )

        for key, group in groups.items():
            group.sort(
                key=lambda row: date.fromisoformat(
                    str(row["date"])
                )
            )

            seen_dates = set()
            demand_history = deque(
                maxlen=max_history
            )

            stockout_history = deque(
                maxlen=max_history
            )

            for record in group:
                record_date = date.fromisoformat(
                    str(record["date"])
                )

                if record_date in seen_dates:
                    raise ValueError(
                        "Duplicate store-SKU-date: "
                        f"{key} {record_date}"
                    )

                seen_dates.add(record_date)

                current_demand = self._number(
                    record[demand_column],
                    demand_column,
                )

                inventory = self._number(
                    record[inventory_column],
                    inventory_column,
                )

                lead_time = self._number(
                    record["lead_time_days"],
                    "lead_time_days",
                )

                safety_stock = self._number(
                    record["safety_stock"],
                    "safety_stock",
                )

                reorder_point = self._number(
                    record["reorder_point"],
                    "reorder_point",
                )

                if min(
                    current_demand,
                    inventory,
                    lead_time,
                    safety_stock,
                    reorder_point,
                ) < 0:
                    raise ValueError(
                        "Inventory quantities and "
                        "lead times must be nonnegative"
                    )

                history = list(
                    demand_history
                )

                features = {}

                for lag in self.lags:
                    features[
                        f"demand_lag_{lag}"
                    ] = (
                        history[-lag]
                        if len(history) >= lag
                        else None
                    )

                for window in self.windows:
                    values = (
                        history[-window:]
                        if len(history) >= window
                        else []
                    )

                    features[
                        f"demand_rolling_mean_{window}"
                    ] = (
                        round(mean(values), 4)
                        if values else None
                    )

                    features[
                        f"demand_rolling_std_{window}"
                    ] = (
                        round(pstdev(values), 4)
                        if values else None
                    )

                    stockouts = list(
                        stockout_history
                    )

                    recent_stockouts = (
                        stockouts[-window:]
                        if len(stockouts) >= window
                        else []
                    )

                    features[
                        f"stockout_rate_{window}"
                    ] = (
                        round(
                            sum(recent_stockouts)
                            / len(recent_stockouts),
                            4,
                        )
                        if recent_stockouts
                        else None
                    )

                historical_average = (
                    mean(history[-7:])
                    if len(history) >= 7
                    else None
                )

                features[
                    "historical_average_demand_7"
                ] = (
                    round(historical_average, 4)
                    if historical_average is not None
                    else None
                )

                if (
                    historical_average is not None
                    and historical_average > 0
                ):
                    coverage_days = (
                        inventory
                        / historical_average
                    )

                    inventory_demand_ratio = (
                        inventory
                        / historical_average
                    )

                    lead_time_demand = (
                        historical_average
                        * lead_time
                    )
                else:
                    coverage_days = None
                    inventory_demand_ratio = None
                    lead_time_demand = None

                features[
                    "inventory_coverage_days"
                ] = (
                    round(coverage_days, 4)
                    if coverage_days is not None
                    else None
                )

                features[
                    "inventory_to_daily_demand_ratio"
                ] = (
                    round(inventory_demand_ratio, 4)
                    if inventory_demand_ratio is not None
                    else None
                )

                features[
                    "estimated_lead_time_demand"
                ] = (
                    round(lead_time_demand, 4)
                    if lead_time_demand is not None
                    else None
                )

                features[
                    "reorder_point_gap"
                ] = round(
                    inventory - reorder_point,
                    4,
                )

                features[
                    "below_reorder_point"
                ] = int(
                    inventory <= reorder_point
                )

                features[
                    "below_safety_stock"
                ] = int(
                    inventory < safety_stock
                )

                features[
                    "safety_stock_coverage_ratio"
                ] = (
                    round(
                        inventory / safety_stock,
                        4,
                    )
                    if safety_stock > 0
                    else None
                )

                # These current-row inventory
                # features are appropriate for
                # decisions made after the
                # inventory snapshot is available.
                output.append({
                    **record,
                    **features,
                })

                demand_history.append(
                    current_demand
                )

                stockout_history.append(
                    int(
                        self._boolean(
                            record["stockout"]
                        )
                    )
                )

        output.sort(
            key=lambda row: (
                str(row["date"]),
                str(row["store_id"]),
                str(row["sku"]),
            )
        )

        return output

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

        enriched = self.transform(records)

        self.save_csv(
            enriched,
            output_path,
        )

        return enriched

    @staticmethod
    def save_csv(
        records: list[dict],
        path: str,
    ) -> None:
        if not records:
            raise ValueError(
                "Cannot save empty records"
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
    engineer = InventoryFeatureEngineer()

    enriched = engineer.transform_csv(
        "data/synthetic/inventory_dataset.csv",
        "data/features/inventory_features.csv",
    )

    engineer.save_json(
        enriched,
        "data/features/inventory_features.json",
    )

    print(
        f"Engineered {len(enriched)} "
        "inventory feature records"
    )
