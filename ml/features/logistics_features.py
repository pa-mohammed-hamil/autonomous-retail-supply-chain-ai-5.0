"""Planned module: logistics features. Implementation pending."""

"""
ai/features/logistics_features.py

Autonomous Retail Supply Chain AI 5.0

Logistics Feature Engineering

Features:
- Route distance and planned duration
- Shipment weight
- Vehicle capacity utilization
- Planned transportation cost per km
- Carrier historical delay rate
- Carrier historical on-time rate
- Carrier historical average delay
- Carrier historical average cost/km
- Vehicle-type historical performance
- Previous shipment delay
- Historical rolling statistics
- Leakage-aware sequential processing
- CSV and JSON export

Standard library only.
Python 3.10+

Prediction assumption:
Features are calculated at shipment creation.
Only previously completed shipments whose
delivery timestamps are <= current shipment
creation time contribute to historical features.
"""

from __future__ import annotations

import csv
import heapq
import json
import math

from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Sequence


class LogisticsFeatureEngineer:

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
    def _timestamp(value) -> datetime:
        if isinstance(value, datetime):
            result = value
        elif isinstance(value, str):
            result = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        else:
            raise TypeError(
                "Invalid timestamp"
            )

        if result.tzinfo is None:
            raise ValueError(
                "Timestamps must be timezone-aware"
            )

        return result.astimezone(timezone.utc)

    @staticmethod
    def _number(value, field: str) -> float:
        if isinstance(value, bool):
            raise ValueError(
                f"{field} must be numeric"
            )

        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid {field}"
            ) from exc

        if not math.isfinite(result):
            raise ValueError(
                f"{field} must be finite"
            )

        return result

    @staticmethod
    def _mean_or_none(values):
        return (
            round(mean(values), 4)
            if values else None
        )

    def transform(
        self,
        records: Sequence[dict],
    ) -> list[dict]:
        if not records:
            raise ValueError(
                "Logistics records cannot be empty"
            )

        shipments = []

        for index, row in enumerate(records):
            item = dict(row)

            created = self._timestamp(
                item["created_at"]
            )

            delivered = self._timestamp(
                item["delivered_at"]
            )

            if delivered < created:
                raise ValueError(
                    "Delivery precedes shipment creation"
                )

            distance = self._number(
                item["distance_km"],
                "distance_km",
            )

            capacity = self._number(
                item["vehicle_capacity_kg"],
                "vehicle_capacity_kg",
            )

            weight = self._number(
                item["shipment_weight_kg"],
                "shipment_weight_kg",
            )

            planned_cost = self._number(
                item["planned_cost"],
                "planned_cost",
            )

            actual_cost = self._number(
                item["actual_cost"],
                "actual_cost",
            )

            delay = self._number(
                item["delay_minutes"],
                "delay_minutes",
            )

            if (
                distance <= 0
                or capacity <= 0
                or weight < 0
                or weight > capacity
                or planned_cost < 0
                or actual_cost < 0
                or delay < 0
            ):
                raise ValueError(
                    "Invalid shipment quantities"
                )

            item["_created"] = created
            item["_delivered"] = delivered
            item["_index"] = index
            item["_distance"] = distance
            item["_capacity"] = capacity
            item["_weight"] = weight
            item["_planned_cost"] = planned_cost
            item["_actual_cost"] = actual_cost
            item["_delay"] = delay

            shipments.append(item)

        shipments.sort(
            key=lambda row: (
                row["_created"],
                row["_index"],
            )
        )

        carrier_history = defaultdict(
            lambda: deque(
                maxlen=self.history_window
            )
        )

        vehicle_history = defaultdict(
            lambda: deque(
                maxlen=self.history_window
            )
        )

        # Heap of completed shipments:
        # (delivered_at, unique_index, shipment)
        pending = []

        results = []

        for item in shipments:
            created = item["_created"]

            # Only incorporate deliveries that
            # were already completed by the
            # current shipment's creation time.
            while (
                pending
                and pending[0][0] <= created
            ):
                _, _, completed = (
                    heapq.heappop(pending)
                )

                distance = completed["_distance"]

                observation = {
                    "delay": completed["_delay"],
                    "late": int(
                        completed["_delay"] > 0
                    ),
                    "cost_per_km": (
                        completed["_actual_cost"]
                        / distance
                    ),
                }

                carrier_history[
                    completed["carrier_id"]
                ].append(observation)

                vehicle_history[
                    completed["vehicle_type"]
                ].append(observation)

            carrier = list(
                carrier_history[
                    item["carrier_id"]
                ]
            )

            vehicle = list(
                vehicle_history[
                    item["vehicle_type"]
                ]
            )

            carrier_delay_rate = (
                mean(
                    row["late"]
                    for row in carrier
                )
                if carrier else None
            )

            features = {
                "shipment_id": item["shipment_id"],
                "carrier_id": item["carrier_id"],
                "vehicle_type": item["vehicle_type"],
                "created_at": item["created_at"],
                "distance_km": item["_distance"],
                "shipment_weight_kg": (
                    item["_weight"]
                ),
                "vehicle_capacity_kg": (
                    item["_capacity"]
                ),
                "capacity_utilization_percent": (
                    round(
                        item["_weight"]
                        / item["_capacity"]
                        * 100,
                        4,
                    )
                ),
                "planned_cost_per_km": round(
                    item["_planned_cost"]
                    / item["_distance"],
                    4,
                ),
                "planned_cost_per_kg": (
                    round(
                        item["_planned_cost"]
                        / item["_weight"],
                        4,
                    )
                    if item["_weight"] > 0
                    else None
                ),
                "carrier_history_count": (
                    len(carrier)
                ),
                "carrier_late_rate": (
                    round(
                        carrier_delay_rate, 4
                    )
                    if carrier_delay_rate is not None
                    else None
                ),
                "carrier_on_time_rate": (
                    round(
                        1 - carrier_delay_rate,
                        4,
                    )
                    if carrier_delay_rate is not None
                    else None
                ),
                "carrier_mean_delay_minutes": (
                    self._mean_or_none(
                        [
                            row["delay"]
                            for row in carrier
                        ]
                    )
                ),
                "carrier_mean_cost_per_km": (
                    self._mean_or_none(
                        [
                            row["cost_per_km"]
                            for row in carrier
                        ]
                    )
                ),
                "carrier_previous_delay_minutes": (
                    carrier[-1]["delay"]
                    if carrier else None
                ),
                "vehicle_history_count": (
                    len(vehicle)
                ),
                "vehicle_mean_delay_minutes": (
                    self._mean_or_none(
                        [
                            row["delay"]
                            for row in vehicle
                        ]
                    )
                ),
                "vehicle_mean_cost_per_km": (
                    self._mean_or_none(
                        [
                            row["cost_per_km"]
                            for row in vehicle
                        ]
                    )
                ),
            }

            if "expected_duration_min" in item:
                features[
                    "expected_duration_min"
                ] = self._number(
                    item["expected_duration_min"],
                    "expected_duration_min",
                )

            results.append((
                item["_index"],
                features,
            ))

            heapq.heappush(
                pending,
                (
                    item["_delivered"],
                    item["_index"],
                    item,
                ),
            )

        # Restore original input order.
        results.sort(
            key=lambda pair: pair[0]
        )

        return [
            row for _, row in results
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
    engineer = LogisticsFeatureEngineer(
        history_window=30
    )

    features = engineer.transform_csv(
        "data/synthetic/logistics_dataset.csv",
        "data/features/logistics_features.csv",
    )

    engineer.save_json(
        features,
        "data/features/logistics_features.json",
    )

    print(
        f"Generated {len(features)} "
        "logistics feature records"
    )
