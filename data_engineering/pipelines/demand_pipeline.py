"""Planned module: demand pipeline. Implementation pending."""

"""
Daily demand forecasting pipeline.

Integrates:
- POS sales ingestion
- Inventory snapshots
- DailyForecaster
- Forecast quality reporting
- Replenishment review indicators

Read-only: no purchase orders or inventory changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ai.forecasting.daily_forecasting import (
    DailyForecaster,
    DailySale,
)


@dataclass(frozen=True)
class DemandPipelineConfig:
    horizon_days: int = 7
    window_days: int = 14
    lead_time_days: int = 5
    safety_stock_units: int = 20
    minimum_history_days: int = 28

    def __post_init__(self):
        for name in (
            "horizon_days",
            "window_days",
            "minimum_history_days",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                raise ValueError(f"Invalid {name}")

        for name in (
            "lead_time_days",
            "safety_stock_units",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ValueError(f"Invalid {name}")

        if self.minimum_history_days < self.window_days + 7:
            raise ValueError(
                "minimum_history_days must be at least "
                "window_days + 7"
            )


class DemandPipeline:

    def __init__(
        self,
        config: DemandPipelineConfig | None = None,
    ):
        self.config = config or DemandPipelineConfig()
        self.forecaster = DailyForecaster()

    @staticmethod
    def _parse_utc(value: str) -> datetime:
        if not isinstance(value, str):
            raise ValueError("Invalid timestamp")

        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError(
                "Timestamp must include timezone"
            )

        return dt.astimezone(timezone.utc)

    @staticmethod
    def _positive_integer(
        value: Any,
        field: str,
    ) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
        ):
            raise ValueError(
                f"{field} must be a positive integer"
            )
        return value

    def prepare_sales(
        self,
        pos_records: list[dict],
        cutoff_date: date,
    ) -> dict[str, list[DailySale]]:
        """
        Convert validated POS records into daily
        net-unit demand by SKU.

        Sales add units; returns subtract units.
        Negative net daily quantities are rejected.

        The business date is UTC in this reference
        implementation. Convert to the store's
        local timezone upstream when needed.
        """

        if not isinstance(pos_records, list):
            raise ValueError("Expected POS records list")

        daily_units: dict[
            tuple[str, date], int
        ] = {}

        seen_lines = set()

        for record in pos_records:
            if not isinstance(record, dict):
                raise ValueError("Invalid POS record")

            sku = record["sku"]
            store_id = record["store_id"]
            transaction_id = record["transaction_id"]
            line_id = record["line_id"]

            if any(
                not isinstance(value, str) or not value
                for value in (
                    sku,
                    store_id,
                    transaction_id,
                    line_id,
                )
            ):
                raise ValueError(
                    "Invalid POS identifiers"
                )

            unique_key = (
                store_id,
                transaction_id,
                line_id,
            )

            if unique_key in seen_lines:
                raise ValueError(
                    f"Duplicate POS line: {unique_key}"
                )

            seen_lines.add(unique_key)

            transaction_day = self._parse_utc(
                record["occurred_at"]
            ).date()

            if transaction_day > cutoff_date:
                continue

            quantity = self._positive_integer(
                record["quantity"],
                "quantity",
            )

            transaction_type = record[
                "transaction_type"
            ]

            if transaction_type == "sale":
                delta = quantity
            elif transaction_type == "return":
                delta = -quantity
            else:
                raise ValueError(
                    "Unsupported transaction type"
                )

            key = (sku, transaction_day)
            daily_units[key] = (
                daily_units.get(key, 0) + delta
            )

        by_sku: dict[str, dict[date, int]] = {}

        for (sku, day), quantity in daily_units.items():
            if quantity < 0:
                raise ValueError(
                    f"Negative net units for {sku} on {day}"
                )

            by_sku.setdefault(sku, {})[day] = quantity

        result = {}

        for sku, observations in by_sku.items():
            first_day = min(observations)

            history = []
            current_day = first_day

            while current_day <= cutoff_date:
                history.append(
                    DailySale(
                        sku=sku,
                        day=current_day,
                        quantity=observations.get(
                            current_day, 0
                        ),
                    )
                )
                current_day += timedelta(days=1)

            result[sku] = history

        return result

    @staticmethod
    def prepare_inventory(
        snapshots: list[dict],
    ) -> dict[str, int]:
        """
        Aggregate latest supplied inventory snapshots
        by SKU. Caller must provide one authoritative
        snapshot per SKU/warehouse.
        """

        inventory: dict[str, int] = {}
        seen = set()

        for record in snapshots:
            sku = record["sku"]
            warehouse_id = record["warehouse_id"]

            if (
                not isinstance(sku, str)
                or not sku
                or not isinstance(warehouse_id, str)
                or not warehouse_id
            ):
                raise ValueError(
                    "Invalid inventory identifiers"
                )

            key = (sku, warehouse_id)

            if key in seen:
                raise ValueError(
                    "Duplicate SKU/warehouse snapshot"
                )

            seen.add(key)

            available = record["available"]

            if (
                isinstance(available, bool)
                or not isinstance(available, int)
                or available < 0
            ):
                raise ValueError(
                    "Invalid available stock"
                )

            inventory[sku] = (
                inventory.get(sku, 0) + available
            )

        return inventory

    def run(
        self,
        pos_records: list[dict],
        inventory_snapshots: list[dict],
        cutoff_date: date,
    ) -> dict:

        if not isinstance(cutoff_date, date):
            raise ValueError(
                "cutoff_date must be a date"
            )

        sales_by_sku = self.prepare_sales(
            pos_records,
            cutoff_date,
        )

        inventory = self.prepare_inventory(
            inventory_snapshots
        )

        forecasts = []
        skipped = []

        for sku, history in sorted(
            sales_by_sku.items()
        ):
            if (
                len(history)
                < self.config.minimum_history_days
            ):
                skipped.append({
                    "sku": sku,
                    "reason": "insufficient_history",
                    "history_days": len(history),
                })
                continue

            try:
                result = self.forecaster.forecast(
                    sales=history,
                    sku=sku,
                    horizon_days=(
                        self.config.horizon_days
                    ),
                    window=self.config.window_days,
                    current_available_stock=(
                        inventory.get(sku)
                    ),
                    lead_time_days=(
                        self.config.lead_time_days
                    ),
                    safety_stock=(
                        self.config.safety_stock_units
                    ),
                )

                forecasts.append(result)

            except (ValueError, TypeError) as exc:
                skipped.append({
                    "sku": sku,
                    "reason": str(exc),
                })

        reorder_reviews = [
            {
                "sku": item["sku"],
                "inventory_indicator": item[
                    "inventory_indicator"
                ],
            }
            for item in forecasts
            if (
                item.get("inventory_indicator", {})
                .get("reorder_review_recommended")
            )
        ]

        return {
            "pipeline": "daily_demand_forecasting",
            "cutoff_date": cutoff_date.isoformat(),
            "generated_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "forecast_count": len(forecasts),
            "skipped_count": len(skipped),
            "forecasts": forecasts,
            "skipped": skipped,
            "reorder_reviews": reorder_reviews,
            "requires_approval": True,
            "purchase_orders_created": False,
        }


if __name__ == "__main__":
    from datetime import timedelta

    cutoff = date(2026, 10, 25)
    start = cutoff - timedelta(days=44)

    pos_records = []

    for i in range(45):
        day = start + timedelta(days=i)

        pos_records.append({
            "transaction_id": f"TX-{i:03d}",
            "line_id": "1",
            "store_id": "STORE-KOCHI",
            "sku": "SKU-101",
            "transaction_type": "sale",
            "quantity": 20 + (i % 7) * 2,
            "occurred_at": (
                f"{day.isoformat()}T12:00:00+00:00"
            ),
        })

    inventory_snapshots = [
        {
            "sku": "SKU-101",
            "warehouse_id": "WH-KOCHI",
            "available": 90,
        }
    ]

    pipeline = DemandPipeline()

    report = pipeline.run(
        pos_records=pos_records,
        inventory_snapshots=inventory_snapshots,
        cutoff_date=cutoff,
    )

    print(report)
