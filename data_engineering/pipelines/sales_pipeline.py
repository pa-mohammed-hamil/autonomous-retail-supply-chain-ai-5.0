"""Planned module: sales pipeline. Implementation pending."""

"""
Retail sales intelligence pipeline.

Integrates:
- POSIngestion
- Sales and return aggregation
- Daily revenue reporting
- SKU-level sales performance
- Store-level sales performance
- Average transaction value
- Return-rate indicators
- Structured financial reporting

Read-only:
Does not process payments, issue refunds,
update stock or change product prices.

Revenue is grouped by currency and is not
converted between currencies.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from ai.ingestion.pos_ingestion import (
    POSIngestion,
)


@dataclass(frozen=True)
class SalesPipelineConfig:
    high_return_rate_threshold: float = 0.20
    minimum_sales_units_for_alert: int = 10
    fail_on_rejected_records: bool = False

    def __post_init__(self):
        ratio = self.high_return_rate_threshold

        if (
            isinstance(ratio, bool)
            or not isinstance(ratio, (int, float))
            or not 0 <= ratio <= 1
        ):
            raise ValueError(
                "Invalid return rate threshold"
            )

        minimum = self.minimum_sales_units_for_alert

        if (
            isinstance(minimum, bool)
            or not isinstance(minimum, int)
            or minimum < 1
        ):
            raise ValueError(
                "Invalid minimum sales units"
            )


class SalesPipeline:

    def __init__(
        self,
        config: SalesPipelineConfig | None = None,
    ):
        self.config = config or SalesPipelineConfig()
        self.ingestion = POSIngestion()

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError(
                "Timezone-aware timestamp required"
            )

        return dt.astimezone(timezone.utc)

    @staticmethod
    def _new_metrics() -> dict:
        return {
            "sales_units": 0,
            "return_units": 0,
            "gross_sales": Decimal("0"),
            "discounts": Decimal("0"),
            "taxes": Decimal("0"),
            "net_revenue": Decimal("0"),
            "transaction_ids": set(),
        }

    @staticmethod
    def _finalize_metrics(
        metrics: dict,
    ) -> dict:
        transaction_count = len(
            metrics["transaction_ids"]
        )

        sales_units = metrics["sales_units"]
        return_units = metrics["return_units"]

        return_rate = (
            return_units / sales_units
            if sales_units > 0
            else None
        )

        average_transaction_value = (
            metrics["net_revenue"]
            / Decimal(transaction_count)
            if transaction_count > 0
            else None
        )

        return {
            "sales_units": sales_units,
            "return_units": return_units,
            "net_units": sales_units - return_units,
            "gross_sales": str(
                metrics["gross_sales"]
            ),
            "discounts": str(
                metrics["discounts"]
            ),
            "taxes": str(
                metrics["taxes"]
            ),
            "net_revenue": str(
                metrics["net_revenue"]
            ),
            "transaction_count": transaction_count,
            "return_units_per_sale_unit": (
                round(return_rate, 4)
                if return_rate is not None
                else None
            ),
            "average_net_value_per_transaction": (
                str(
                    average_transaction_value.quantize(
                        Decimal("0.01")
                    )
                )
                if average_transaction_value is not None
                else None
            ),
        }

    def _update_metrics(
        self,
        metrics: dict,
        record: dict,
    ) -> None:

        quantity = record["quantity"]
        unit_price = Decimal(
            record["unit_price"]
        )
        discount = Decimal(
            record["discount_amount"]
        )
        tax = Decimal(
            record["tax_amount"]
        )
        net = Decimal(
            record["net_amount"]
        )

        transaction_type = record[
            "transaction_type"
        ]

        if transaction_type == "sale":
            metrics["sales_units"] += quantity
            sign = Decimal("1")

        elif transaction_type == "return":
            metrics["return_units"] += quantity
            sign = Decimal("-1")

        else:
            raise ValueError(
                "Unsupported transaction type"
            )

        metrics["gross_sales"] += (
            sign * unit_price * quantity
        )

        metrics["discounts"] += (
            sign * discount
        )

        metrics["taxes"] += sign * tax

        metrics["net_revenue"] += net

        metrics["transaction_ids"].add(
            (
                record["store_id"],
                record["transaction_id"],
            )
        )

    def run(
        self,
        raw_pos_records: list[dict[str, Any]],
    ) -> dict:

        if not isinstance(raw_pos_records, list):
            raise ValueError(
                "raw_pos_records must be a list"
            )

        ingestion_result = self.ingestion.ingest(
            raw_pos_records
        )

        rejected = ingestion_result["rejected"]

        if (
            rejected
            and self.config.fail_on_rejected_records
        ):
            return {
                "pipeline": "sales_intelligence",
                "status": "failed_validation",
                "rejected": rejected,
                "payments_processed": False,
                "refunds_executed": False,
            }

        records = ingestion_result["records"]

        daily = defaultdict(
            self._new_metrics
        )
        by_store = defaultdict(
            self._new_metrics
        )
        by_sku = defaultdict(
            self._new_metrics
        )
        totals = defaultdict(
            self._new_metrics
        )

        for record in records:
            day = self._parse_timestamp(
                record["occurred_at"]
            ).date().isoformat()

            currency = record["currency"]
            store_id = record["store_id"]
            sku = record["sku"]

            keys = [
                (daily, (day, currency)),
                (
                    by_store,
                    (store_id, currency),
                ),
                (by_sku, (sku, currency)),
                (totals, currency),
            ]

            for collection, key in keys:
                self._update_metrics(
                    collection[key],
                    record,
                )

        daily_reports = [
            {
                "date": day,
                "currency": currency,
                **self._finalize_metrics(metrics),
            }
            for (day, currency), metrics in sorted(
                daily.items()
            )
        ]

        store_reports = [
            {
                "store_id": store_id,
                "currency": currency,
                **self._finalize_metrics(metrics),
            }
            for (store_id, currency), metrics in sorted(
                by_store.items()
            )
        ]

        sku_reports = [
            {
                "sku": sku,
                "currency": currency,
                **self._finalize_metrics(metrics),
            }
            for (sku, currency), metrics in sorted(
                by_sku.items()
            )
        ]

        total_reports = [
            {
                "currency": currency,
                **self._finalize_metrics(metrics),
            }
            for currency, metrics in sorted(
                totals.items()
            )
        ]

        alerts = []

        for report in sku_reports:
            sales_units = report["sales_units"]
            return_rate = report[
                "return_units_per_sale_unit"
            ]

            if (
                sales_units
                >= self.config.minimum_sales_units_for_alert
                and return_rate is not None
                and return_rate
                >= self.config.high_return_rate_threshold
            ):
                alerts.append({
                    "code": "HIGH_RETURN_UNIT_RATIO",
                    "sku": report["sku"],
                    "currency": report["currency"],
                    "sales_units": sales_units,
                    "return_units": report["return_units"],
                    "return_unit_ratio": return_rate,
                    "requires_human_review": True,
                })

        return {
            "pipeline": "sales_intelligence",
            "status": (
                "completed_with_rejections"
                if rejected
                else "completed"
            ),
            "generated_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "ingestion": {
                "total": ingestion_result["total"],
                "accepted_count": ingestion_result[
                    "accepted_count"
                ],
                "rejected_count": ingestion_result[
                    "rejected_count"
                ],
                "rejected": rejected,
            },
            "totals_by_currency": total_reports,
            "daily_reports": daily_reports,
            "store_reports": store_reports,
            "sku_reports": sku_reports,
            "alerts": alerts,
            "requires_human_review": bool(alerts),
            "persisted": False,
            "payments_processed": False,
            "refunds_executed": False,
            "inventory_updated": False,
            "prices_modified": False,
        }


if __name__ == "__main__":
    transactions = [
        {
            "transaction_id": "TXN-001",
            "line_id": "1",
            "store_id": "STORE-KOCHI",
            "sku": "SKU-101",
            "transaction_type": "sale",
            "quantity": 10,
            "currency": "INR",
            "unit_price": "500.00",
            "discount_amount": "100.00",
            "tax_amount": "250.00",
            "occurred_at": (
                "2026-10-25T10:00:00+05:30"
            ),
        },
        {
            "transaction_id": "TXN-002",
            "line_id": "1",
            "store_id": "STORE-KOCHI",
            "sku": "SKU-101",
            "transaction_type": "return",
            "quantity": 3,
            "currency": "INR",
            "unit_price": "500.00",
            "discount_amount": "0.00",
            "tax_amount": "75.00",
            "original_transaction_id": "TXN-001",
            "occurred_at": (
                "2026-10-25T12:00:00+05:30"
            ),
        },
        {
            "transaction_id": "TXN-003",
            "line_id": "1",
            "store_id": "STORE-THRISSUR",
            "sku": "SKU-202",
            "transaction_type": "sale",
            "quantity": 5,
            "currency": "INR",
            "unit_price": "250.00",
            "discount_amount": "0.00",
            "tax_amount": "62.50",
            "occurred_at": (
                "2026-10-25T14:00:00+05:30"
            ),
        },
    ]

    pipeline = SalesPipeline()

    result = pipeline.run(
        raw_pos_records=transactions
    )

    print("Status:", result["status"])
    print(
        "Totals:",
        result["totals_by_currency"],
    )
    print(
        "Daily reports:",
        result["daily_reports"],
    )
    print(
        "SKU reports:",
        result["sku_reports"],
    )
    print("Alerts:", result["alerts"])
