"""Planned module: hierarchical forecast. Implementation pending."""

"""
ai/forecasting/hierarchical_forecast.py

Hierarchical Retail Demand Forecasting

Hierarchy:
Enterprise
  -> Region
    -> Store
      -> SKU

Features:
- Bottom-up reconciliation
- Store forecasts
- Region forecasts
- Enterprise forecasts
- SKU forecasts
- Duplicate detection
- Hierarchy consistency checks
- CSV / JSON export

Standard library only.
Python 3.10+

Input records:
{
    "region_id": "REGION01",
    "store_id": "STORE01",
    "sku": "SKU001",
    "date": "2026-11-01",
    "predicted_demand": 50.0
}
"""

from __future__ import annotations

import csv
import json
import math

from collections import defaultdict
from pathlib import Path
from typing import Sequence


class HierarchicalForecaster:

    REQUIRED = (
        "region_id",
        "store_id",
        "sku",
        "date",
        "predicted_demand",
    )

    @staticmethod
    def _validate(
        records: Sequence[dict],
    ) -> list[dict]:
        if not records:
            raise ValueError(
                "Forecast records cannot be empty"
            )

        prepared = []
        seen = set()
        store_regions = {}

        for row in records:
            missing = [
                field
                for field in (
                    "region_id",
                    "store_id",
                    "sku",
                    "date",
                    "predicted_demand",
                )
                if field not in row
            ]

            if missing:
                raise ValueError(
                    f"Missing fields: {missing}"
                )

            region = str(row["region_id"])
            store = str(row["store_id"])
            sku = str(row["sku"])
            day = str(row["date"])

            if not all(
                (region, store, sku, day)
            ):
                raise ValueError(
                    "Hierarchy identifiers cannot be empty"
                )

            from datetime import date
            date.fromisoformat(day)

            value = float(
                row["predicted_demand"]
            )

            if (
                not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(
                    "Forecast must be finite "
                    "and nonnegative"
                )

            key = (
                region, store, sku, day
            )

            if key in seen:
                raise ValueError(
                    f"Duplicate forecast: {key}"
                )

            seen.add(key)

            if (
                store in store_regions
                and store_regions[store] != region
            ):
                raise ValueError(
                    f"Store {store} belongs "
                    "to multiple regions"
                )

            store_regions[store] = region

            prepared.append({
                "region_id": region,
                "store_id": store,
                "sku": sku,
                "date": day,
                "predicted_demand": value,
            })

        return prepared

    def reconcile(
        self,
        records: Sequence[dict],
    ) -> dict:
        rows = self._validate(records)

        store_totals = defaultdict(float)
        region_totals = defaultdict(float)
        enterprise_totals = defaultdict(float)

        for row in rows:
            region = row["region_id"]
            store = row["store_id"]
            day = row["date"]
            value = row["predicted_demand"]

            store_totals[
                (region, store, day)
            ] += value

            region_totals[
                (region, day)
            ] += value

            enterprise_totals[
                day
            ] += value

        sku_forecasts = sorted(
            rows,
            key=lambda row: (
                row["date"],
                row["region_id"],
                row["store_id"],
                row["sku"],
            )
        )

        store_forecasts = [
            {
                "region_id": region,
                "store_id": store,
                "date": day,
                "predicted_demand": round(
                    value, 4
                ),
            }
            for (
                region, store, day
            ), value in sorted(
                store_totals.items()
            )
        ]

        region_forecasts = [
            {
                "region_id": region,
                "date": day,
                "predicted_demand": round(
                    value, 4
                ),
            }
            for (
                region, day
            ), value in sorted(
                region_totals.items()
            )
        ]

        enterprise_forecasts = [
            {
                "date": day,
                "predicted_demand": round(
                    value, 4
                ),
            }
            for day, value in sorted(
                enterprise_totals.items()
            )
        ]

        return {
            "method": "bottom_up",
            "sku_forecasts": sku_forecasts,
            "store_forecasts": store_forecasts,
            "region_forecasts": region_forecasts,
            "enterprise_forecasts": (
                enterprise_forecasts
            ),
        }

    @staticmethod
    def validate_consistency(
        result: dict,
        tolerance: float = 1e-3,
    ) -> dict:
        sku_totals = defaultdict(float)
        store_totals = defaultdict(float)
        region_totals = defaultdict(float)

        for row in result["sku_forecasts"]:
            sku_totals[row["date"]] += (
                row["predicted_demand"]
            )

        for row in result["store_forecasts"]:
            store_totals[row["date"]] += (
                row["predicted_demand"]
            )

        for row in result["region_forecasts"]:
            region_totals[row["date"]] += (
                row["predicted_demand"]
            )

        enterprise_totals = {
            row["date"]: row["predicted_demand"]
            for row in result[
                "enterprise_forecasts"
            ]
        }

        all_dates = (
            set(sku_totals)
            | set(store_totals)
            | set(region_totals)
            | set(enterprise_totals)
        )

        violations = []

        for day in sorted(all_dates):
            values = [
                sku_totals.get(day, 0),
                store_totals.get(day, 0),
                region_totals.get(day, 0),
                enterprise_totals.get(day, 0),
            ]

            if (
                max(values) - min(values)
                > tolerance
            ):
                violations.append({
                    "date": day,
                    "totals": values,
                })

        return {
            "consistent": not violations,
            "tolerance": tolerance,
            "violations": violations,
        }

    @staticmethod
    def save_json(
        result: dict,
        path: str,
    ):
        output = Path(path)
        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            json.dumps(
                result,
                indent=2,
                allow_nan=False,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def save_csv(
        rows: Sequence[dict],
        path: str,
    ):
        if not rows:
            raise ValueError(
                "Cannot export empty rows"
            )

        output = Path(path)
        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        fields = list(dict.fromkeys(
            key for row in rows for key in row
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
            writer.writerows(rows)


if __name__ == "__main__":
    sample = [
        {
            "region_id": "SOUTH",
            "store_id": "STORE01",
            "sku": "SKU001",
            "date": "2026-11-01",
            "predicted_demand": 120,
        },
        {
            "region_id": "SOUTH",
            "store_id": "STORE01",
            "sku": "SKU002",
            "date": "2026-11-01",
            "predicted_demand": 80,
        },
        {
            "region_id": "SOUTH",
            "store_id": "STORE02",
            "sku": "SKU001",
            "date": "2026-11-01",
            "predicted_demand": 100,
        },
        {
            "region_id": "NORTH",
            "store_id": "STORE03",
            "sku": "SKU001",
            "date": "2026-11-01",
            "predicted_demand": 150,
        },
    ]

    forecaster = HierarchicalForecaster()

    result = forecaster.reconcile(sample)

    validation = (
        forecaster.validate_consistency(
            result
        )
    )

    forecaster.save_json(
        result,
        "data/forecasts/hierarchical_forecast.json",
    )

    forecaster.save_csv(
        result["enterprise_forecasts"],
        "data/forecasts/enterprise_forecast.csv",
    )

    print(json.dumps(
        validation,
        indent=2,
    ))

    print(json.dumps(
        result["enterprise_forecasts"],
        indent=2,
    ))
