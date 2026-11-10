"""Planned module: feature pipeline. Implementation pending."""

"""
ai/pipelines/feature_pipeline.py

Retail feature engineering pipeline.

Features:
- Daily SKU demand features
- Lag features
- Rolling demand statistics
- Sales volatility
- Calendar and weekend features
- Inventory coverage
- Supplier reliability features
- Time-ordered training datasets
- Missing-value indicators
- JSON-ready output

Uses historical information only for lagged
features to reduce target leakage.

No model training or operational actions.
"""

from __future__ import annotations

import math
import statistics

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any


@dataclass(frozen=True)
class FeatureConfig:
    lag_days: tuple[int, ...] = (1, 7, 14)
    rolling_windows: tuple[int, ...] = (7, 14, 28)
    min_history_days: int = 28

    def __post_init__(self):
        for collection in (
            self.lag_days,
            self.rolling_windows,
        ):
            if not collection or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                for value in collection
            ):
                raise ValueError(
                    "Feature windows must be positive"
                )

        if (
            isinstance(self.min_history_days, bool)
            or not isinstance(
                self.min_history_days, int
            )
            or self.min_history_days < 1
        ):
            raise ValueError(
                "Invalid min_history_days"
            )


@dataclass(frozen=True)
class DailyDemandRecord:
    sku: str
    day: date
    units: int

    def __post_init__(self):
        if not self.sku:
            raise ValueError("SKU required")

        if (
            isinstance(self.units, bool)
            or not isinstance(self.units, int)
            or self.units < 0
        ):
            raise ValueError(
                "units must be nonnegative integer"
            )


class FeaturePipeline:

    def __init__(
        self,
        config: FeatureConfig | None = None,
    ):
        self.config = config or FeatureConfig()

    @staticmethod
    def _finite_number(
        value: Any,
        name: str,
        minimum: float = 0.0,
    ) -> float:
        if isinstance(value, bool):
            raise ValueError(f"Invalid {name}")

        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid {name}"
            ) from exc

        if (
            not math.isfinite(number)
            or number < minimum
        ):
            raise ValueError(
                f"Invalid {name}"
            )

        return number

    @staticmethod
    def _validate_series(
        records: list[DailyDemandRecord],
    ) -> list[DailyDemandRecord]:
        history = sorted(
            records,
            key=lambda item: item.day,
        )

        if not history:
            return []

        sku = history[0].sku

        if any(item.sku != sku for item in history):
            raise ValueError(
                "Each series must contain one SKU"
            )

        if any(
            current.day - previous.day
            != timedelta(days=1)
            for previous, current in zip(
                history, history[1:]
            )
        ):
            raise ValueError(
                "History must contain consecutive days"
            )

        return history

    @staticmethod
    def _rolling_features(
        past_units: list[int],
        window: int,
    ) -> dict:

        if len(past_units) < window:
            return {
                f"rolling_mean_{window}": None,
                f"rolling_std_{window}": None,
                f"rolling_min_{window}": None,
                f"rolling_max_{window}": None,
            }

        values = past_units[-window:]

        return {
            f"rolling_mean_{window}": round(
                statistics.mean(values), 4
            ),
            f"rolling_std_{window}": round(
                statistics.pstdev(values), 4
            ),
            f"rolling_min_{window}": min(values),
            f"rolling_max_{window}": max(values),
        }

    def build_demand_features(
        self,
        records: list[DailyDemandRecord],
        include_target: bool = True,
    ) -> list[dict]:
        """
        Each feature row at date D uses demand
        observations strictly before D.

        target_units is the demand observed on D
        and is intended for supervised training.
        """

        history = self._validate_series(records)

        if (
            len(history)
            < self.config.min_history_days
        ):
            return []

        result = []

        for index, item in enumerate(history):
            past = [
                record.units
                for record in history[:index]
            ]

            features = {
                "sku": item.sku,
                "date": item.day.isoformat(),
                "day_of_week": item.day.weekday(),
                "month": item.day.month,
                "day_of_month": item.day.day,
                "is_weekend": int(
                    item.day.weekday() >= 5
                ),
            }

            for lag in self.config.lag_days:
                features[f"lag_{lag}"] = (
                    past[-lag]
                    if len(past) >= lag
                    else None
                )

            for window in self.config.rolling_windows:
                features.update(
                    self._rolling_features(
                        past, window
                    )
                )

            if len(past) >= 7:
                recent = past[-7:]

                features["zero_sales_days_7"] = sum(
                    quantity == 0
                    for quantity in recent
                )

                features["demand_change_7"] = (
                    round(
                        recent[-1] - recent[0],
                        4,
                    )
                )
            else:
                features["zero_sales_days_7"] = None
                features["demand_change_7"] = None

            features["history_days"] = len(past)

            if include_target:
                features["target_units"] = item.units

            result.append(features)

        return result

    def add_inventory_features(
        self,
        rows: list[dict],
        inventory_by_sku: dict[str, dict],
    ) -> list[dict]:
        """
        Inventory values must be historical snapshots
        known at each feature row's date.

        For training, do not supply today's stock
        to past historical rows.
        """

        enriched = []

        for row in rows:
            result = dict(row)
            sku = result["sku"]

            inventory = inventory_by_sku.get(sku)

            if inventory is None:
                result.update({
                    "available_stock": None,
                    "reserved_stock": None,
                    "inventory_coverage_days": None,
                    "inventory_data_missing": 1,
                })
            else:
                available = self._finite_number(
                    inventory["available"],
                    "available",
                )

                reserved = self._finite_number(
                    inventory.get("reserved", 0),
                    "reserved",
                )

                demand = result.get(
                    "rolling_mean_7"
                )

                coverage = (
                    round(available / demand, 3)
                    if demand is not None
                    and demand > 0
                    else None
                )

                result.update({
                    "available_stock": available,
                    "reserved_stock": reserved,
                    "inventory_coverage_days": coverage,
                    "inventory_data_missing": 0,
                })

            enriched.append(result)

        return enriched

    def add_supplier_features(
        self,
        rows: list[dict],
        supplier_by_sku: dict[str, dict],
    ) -> list[dict]:
        """
        Supplier observations must be point-in-time
        aligned with each feature date.
        """

        enriched = []

        for row in rows:
            result = dict(row)
            supplier = supplier_by_sku.get(
                result["sku"]
            )

            if supplier is None:
                result.update({
                    "supplier_lead_time_days": None,
                    "supplier_on_time_rate": None,
                    "supplier_quality_rate": None,
                    "supplier_data_missing": 1,
                })
            else:
                result.update({
                    "supplier_lead_time_days": (
                        self._finite_number(
                            supplier["lead_time_days"],
                            "lead_time_days",
                        )
                    ),
                    "supplier_on_time_rate": (
                        self._finite_number(
                            supplier["on_time_rate"],
                            "on_time_rate",
                        )
                    ),
                    "supplier_quality_rate": (
                        self._finite_number(
                            supplier["quality_rate"],
                            "quality_rate",
                        )
                    ),
                    "supplier_data_missing": 0,
                })

                if not (
                    0 <= result[
                        "supplier_on_time_rate"
                    ] <= 1
                    and 0 <= result[
                        "supplier_quality_rate"
                    ] <= 1
                ):
                    raise ValueError(
                        "Supplier rates must be 0-1"
                    )

            enriched.append(result)

        return enriched

    @staticmethod
    def time_split(
        rows: list[dict],
        validation_days: int = 14,
        test_days: int = 14,
    ) -> dict:
        """
        Chronological date-based split.

        All SKUs on the same date belong to the
        same split, reducing cross-SKU time leakage.
        """

        if (
            isinstance(validation_days, bool)
            or isinstance(test_days, bool)
            or not isinstance(validation_days, int)
            or not isinstance(test_days, int)
            or validation_days <= 0
            or test_days <= 0
        ):
            raise ValueError(
                "Invalid split configuration"
            )

        dates = sorted({
            row["date"] for row in rows
        })

        if len(dates) <= validation_days + test_days:
            raise ValueError(
                "Not enough dates for train/validation/test"
            )

        test_dates = set(
            dates[-test_days:]
        )

        validation_dates = set(
            dates[
                -(test_days + validation_days):
                -test_days
            ]
        )

        train = []
        validation = []
        test = []

        for row in rows:
            if row["date"] in test_dates:
                test.append(row)
            elif row["date"] in validation_dates:
                validation.append(row)
            else:
                train.append(row)

        return {
            "train": train,
            "validation": validation,
            "test": test,
            "split_type": "chronological",
        }

    def run(
        self,
        demand_records: list[DailyDemandRecord],
        inventory_by_sku: dict[str, dict] | None = None,
        supplier_by_sku: dict[str, dict] | None = None,
        include_target: bool = True,
    ) -> dict:

        grouped: dict[
            str, list[DailyDemandRecord]
        ] = {}

        for record in demand_records:
            grouped.setdefault(
                record.sku, []
            ).append(record)

        rows = []
        skipped = []

        for sku, records in sorted(
            grouped.items()
        ):
            try:
                features = self.build_demand_features(
                    records,
                    include_target=include_target,
                )

                if not features:
                    skipped.append({
                        "sku": sku,
                        "reason": "insufficient_history",
                    })
                    continue

                rows.extend(features)

            except ValueError as exc:
                skipped.append({
                    "sku": sku,
                    "reason": str(exc),
                })

        if inventory_by_sku is not None:
            rows = self.add_inventory_features(
                rows,
                inventory_by_sku,
            )

        if supplier_by_sku is not None:
            rows = self.add_supplier_features(
                rows,
                supplier_by_sku,
            )

        return {
            "pipeline": "retail_feature_engineering",
            "feature_rows": len(rows),
            "sku_count": len(grouped),
            "rows": rows,
            "skipped": skipped,
            "point_in_time_validation_required": (
                inventory_by_sku is not None
                or supplier_by_sku is not None
            ),
            "model_trained": False,
            "operational_actions_executed": False,
        }


if __name__ == "__main__":
    from datetime import timedelta

    start = date(2026, 8, 1)

    demand = [
        DailyDemandRecord(
            sku="SKU-101",
            day=start + timedelta(days=i),
            units=15 + (i % 7) * 3,
        )
        for i in range(85)
    ]

    pipeline = FeaturePipeline()

    result = pipeline.run(
        demand_records=demand,
    )

    print("Feature rows:", result["feature_rows"])
    print("First row:", result["rows"][0])

    split = pipeline.time_split(
        result["rows"],
        validation_days=14,
        test_days=14,
    )

    print("Training rows:", len(split["train"]))
    print(
        "Validation rows:",
        len(split["validation"]),
    )
    print("Test rows:", len(split["test"]))
