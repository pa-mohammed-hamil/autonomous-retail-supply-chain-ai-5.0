"""Planned module: logistics dataset. Implementation pending."""

"""
ai/datasets/logistics_dataset.py

Autonomous Retail Supply Chain AI 5.0

Synthetic Logistics Dataset Generator

Features:
- Shipment and order IDs
- Store, warehouse and carrier IDs
- Delivery routes
- Vehicle types and capacities
- Shipment weights
- Route distance
- Planned and actual transport costs
- Promised and actual delivery timestamps
- On-time and late delivery labels
- Delivery delay minutes
- SLA compliance
- Fuel consumption
- Vehicle capacity utilization
- CSV and JSON export

Standard library only.
"""

from __future__ import annotations

import csv
import json
import math
import random

from datetime import datetime, timedelta, timezone
from pathlib import Path


class LogisticsDatasetGenerator:

    VEHICLES = {
        "bike": {
            "capacity_kg": 25,
            "speed_kmh": 30,
            "cost_per_km": 5.0,
            "fuel_l_per_100km": 2.0,
        },
        "van": {
            "capacity_kg": 800,
            "speed_kmh": 45,
            "cost_per_km": 15.0,
            "fuel_l_per_100km": 10.0,
        },
        "truck": {
            "capacity_kg": 5000,
            "speed_kmh": 40,
            "cost_per_km": 30.0,
            "fuel_l_per_100km": 25.0,
        },
    }

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

    def generate(
        self,
        n_shipments: int = 1000,
        n_stores: int = 5,
        n_warehouses: int = 3,
        n_carriers: int = 4,
        start_date: str = "2026-01-01",
    ) -> list[dict]:
        for field, value in {
            "n_shipments": n_shipments,
            "n_stores": n_stores,
            "n_warehouses": n_warehouses,
            "n_carriers": n_carriers,
        }.items():
            self._positive_int(value, field)

        start = datetime.fromisoformat(
            start_date
        )

        if start.tzinfo is None:
            start = start.replace(
                tzinfo=timezone.utc
            )

        records = []

        for index in range(n_shipments):
            vehicle_type = self.random.choice(
                list(self.VEHICLES)
            )

            vehicle = self.VEHICLES[
                vehicle_type
            ]

            distance_km = round(
                self.random.uniform(2, 250),
                2,
            )

            capacity_kg = vehicle[
                "capacity_kg"
            ]

            shipment_weight_kg = round(
                self.random.uniform(
                    capacity_kg * 0.1,
                    capacity_kg * 0.95,
                ),
                2,
            )

            utilization = (
                shipment_weight_kg
                / capacity_kg * 100
            )

            speed = vehicle["speed_kmh"]

            expected_duration_min = (
                distance_km / speed * 60
            )

            # Planned delivery window includes
            # a configurable synthetic buffer.
            promised_duration_min = (
                expected_duration_min
                + self.random.uniform(15, 90)
            )

            traffic_multiplier = max(
                0.6,
                self.random.gauss(1.1, 0.25),
            )

            handling_minutes = (
                self.random.uniform(5, 35)
            )

            actual_duration_min = (
                expected_duration_min
                * traffic_multiplier
                + handling_minutes
            )

            created_at = (
                start
                + timedelta(
                    days=self.random.randint(
                        0, 180
                    ),
                    hours=self.random.randint(
                        0, 23
                    ),
                )
            )

            promised_at = (
                created_at
                + timedelta(
                    minutes=promised_duration_min
                )
            )

            delivered_at = (
                created_at
                + timedelta(
                    minutes=actual_duration_min
                )
            )

            signed_delay = (
                delivered_at - promised_at
            ).total_seconds() / 60

            delay_minutes = max(
                0.0, signed_delay
            )

            on_time = signed_delay <= 0

            planned_cost = (
                distance_km
                * vehicle["cost_per_km"]
            )

            actual_cost = (
                planned_cost
                * traffic_multiplier
                + handling_minutes * 0.5
            )

            fuel_liters = (
                distance_km
                * vehicle["fuel_l_per_100km"]
                / 100
                * traffic_multiplier
            )

            records.append({
                "shipment_id": (
                    f"SHIP{index + 1:06d}"
                ),
                "order_id": (
                    f"ORD{index + 1:06d}"
                ),
                "warehouse_id": (
                    f"WH{self.random.randint(1, n_warehouses):03d}"
                ),
                "store_id": (
                    f"STORE{self.random.randint(1, n_stores):03d}"
                ),
                "carrier_id": (
                    f"CARRIER{self.random.randint(1, n_carriers):03d}"
                ),
                "route_id": (
                    f"ROUTE{index + 1:06d}"
                ),
                "vehicle_id": (
                    f"VEH{index + 1:06d}"
                ),
                "vehicle_type": vehicle_type,
                "distance_km": distance_km,
                "shipment_weight_kg": (
                    shipment_weight_kg
                ),
                "vehicle_capacity_kg": (
                    capacity_kg
                ),
                "capacity_utilization_percent": (
                    round(utilization, 2)
                ),
                "created_at": (
                    created_at.isoformat()
                ),
                "promised_at": (
                    promised_at.isoformat()
                ),
                "delivered_at": (
                    delivered_at.isoformat()
                ),
                "expected_duration_min": round(
                    expected_duration_min, 2
                ),
                "actual_duration_min": round(
                    actual_duration_min, 2
                ),
                "delay_minutes": round(
                    delay_minutes, 2
                ),
                "on_time": on_time,
                "delivery_status": (
                    "on_time"
                    if on_time else "late"
                ),
                "planned_cost": round(
                    planned_cost, 2
                ),
                "actual_cost": round(
                    actual_cost, 2
                ),
                "fuel_liters": round(
                    fuel_liters, 2
                ),
                "currency": "INR",
            })

        return records

    @staticmethod
    def save_csv(records, path):
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
    generator = LogisticsDatasetGenerator(
        seed=42
    )

    dataset = generator.generate(
        n_shipments=1000,
        n_stores=5,
        n_warehouses=3,
        n_carriers=4,
    )

    generator.save_csv(
        dataset,
        "data/synthetic/logistics_dataset.csv",
    )

    generator.save_json(
        dataset,
        "data/synthetic/logistics_dataset.json",
    )

    print(
        f"Generated {len(dataset)} "
        "synthetic logistics records"
    )
