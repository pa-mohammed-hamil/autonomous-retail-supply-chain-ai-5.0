"""Planned module: supplier pipeline. Implementation pending."""

"""
Supplier intelligence pipeline.

Integrates:
- SupplierIngestion
- SupplierRiskRefresh
- Supplier delivery validation
- Supplier quality and reliability metrics
- Delivery shortage indicators
- Risk-based review alerts

Read-only: no purchase orders or supplier
accounts are changed.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ai.ingestion.supplier_ingestion import SupplierIngestion
from ai.risk.supplier_risk_refresh import SupplierRiskRefresh


@dataclass(frozen=True)
class SupplierPipelineConfig:
    fail_on_rejected_records: bool = False
    shortage_alert_threshold: float = 0.10

    def __post_init__(self):
        value = self.shortage_alert_threshold
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not 0 <= value <= 1
        ):
            raise ValueError("Invalid shortage threshold")


class SupplierPipeline:

    def __init__(
        self,
        config: SupplierPipelineConfig | None = None,
    ):
        self.config = config or SupplierPipelineConfig()
        self.ingestion = SupplierIngestion()
        self.risk_engine = SupplierRiskRefresh()

    @staticmethod
    def _parse_time(value: str) -> datetime:
        if not isinstance(value, str):
            raise ValueError("Timestamp must be text")

        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("Timezone required")

        return dt.astimezone(timezone.utc)

    def _delivery_summary(
        self,
        records: list[dict],
    ) -> tuple[list[dict], list[dict]]:

        grouped = defaultdict(
            lambda: {
                "deliveries": 0,
                "ordered_units": 0,
                "delivered_units": 0,
                "on_time_deliveries": 0,
            }
        )

        alerts = []

        for record in records:
            key = (
                record["supplier_id"],
                record["sku"],
            )

            group = grouped[key]

            ordered = record["ordered_quantity"]
            delivered = record["delivered_quantity"]

            on_time = (
                self._parse_time(record["delivered_at"])
                <= self._parse_time(record["promised_at"])
            )

            group["deliveries"] += 1
            group["ordered_units"] += ordered
            group["delivered_units"] += delivered
            group["on_time_deliveries"] += int(on_time)

            shortage = ordered - delivered

            if (
                ordered > 0
                and shortage / ordered
                >= self.config.shortage_alert_threshold
            ):
                alerts.append({
                    "code": "SUPPLIER_DELIVERY_SHORTAGE",
                    "supplier_id": record["supplier_id"],
                    "sku": record["sku"],
                    "delivery_id": record["delivery_id"],
                    "shortage_units": shortage,
                    "requires_human_review": True,
                })

        summaries = []

        for (supplier_id, sku), group in sorted(
            grouped.items()
        ):
            count = group["deliveries"]
            ordered = group["ordered_units"]
            delivered = group["delivered_units"]

            summaries.append({
                "supplier_id": supplier_id,
                "sku": sku,
                **group,
                "on_time_rate": round(
                    group["on_time_deliveries"] / count,
                    4,
                ),
                "fill_rate": round(
                    delivered / ordered, 4
                ) if ordered else None,
                "shortage_units": ordered - delivered,
            })

        return summaries, alerts

    def run(
        self,
        raw_suppliers: list[dict[str, Any]],
        raw_deliveries: list[dict[str, Any]],
        required_quantities: dict[str, int],
        as_of: datetime | None = None,
    ) -> dict:

        if not isinstance(raw_suppliers, list):
            raise ValueError("Suppliers must be a list")

        if not isinstance(raw_deliveries, list):
            raise ValueError("Deliveries must be a list")

        if not isinstance(required_quantities, dict):
            raise ValueError(
                "Required quantities must be a dictionary"
            )

        as_of = as_of or datetime.now(timezone.utc)

        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")

        as_of = as_of.astimezone(timezone.utc)

        supplier_result = self.ingestion.ingest(
            raw_suppliers,
            mode="supplier",
        )

        delivery_result = self.ingestion.ingest(
            raw_deliveries,
            mode="delivery",
        )

        rejected_count = (
            supplier_result["rejected_count"]
            + delivery_result["rejected_count"]
        )

        if (
            rejected_count
            and self.config.fail_on_rejected_records
        ):
            return {
                "pipeline": "supplier_intelligence",
                "status": "failed_validation",
                "supplier_rejections": (
                    supplier_result["rejected"]
                ),
                "delivery_rejections": (
                    delivery_result["rejected"]
                ),
                "operational_actions_executed": False,
            }

        accepted_suppliers = supplier_result["records"]
        accepted_deliveries = delivery_result["records"]

        risk_report = self.risk_engine.refresh_all(
            suppliers=accepted_suppliers,
            required_quantities=required_quantities,
            as_of=as_of,
        )

        delivery_summaries, delivery_alerts = (
            self._delivery_summary(
                accepted_deliveries
            )
        )

        risk_alerts = []

        for item in risk_report["results"]:
            for code in item["alerts"]:
                risk_alerts.append({
                    "code": code,
                    "supplier_id": item["supplier_id"],
                    "sku": item["sku"],
                    "risk_score": item["risk_score"],
                    "requires_human_review": True,
                })

        alerts = risk_alerts + delivery_alerts

        status = (
            "completed_with_rejections"
            if rejected_count or risk_report["rejected_count"]
            else "completed"
        )

        return {
            "pipeline": "supplier_intelligence",
            "status": status,
            "generated_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "as_of": as_of.isoformat(),
            "ingestion": {
                "suppliers_accepted": (
                    supplier_result["accepted_count"]
                ),
                "suppliers_rejected": (
                    supplier_result["rejected_count"]
                ),
                "deliveries_accepted": (
                    delivery_result["accepted_count"]
                ),
                "deliveries_rejected": (
                    delivery_result["rejected_count"]
                ),
                "supplier_rejections": (
                    supplier_result["rejected"]
                ),
                "delivery_rejections": (
                    delivery_result["rejected"]
                ),
            },
            "risk_results": risk_report["results"],
            "risk_rejections": risk_report["rejected"],
            "delivery_performance": delivery_summaries,
            "alerts": alerts,
            "requires_human_review": bool(alerts),
            "persisted": False,
            "purchase_orders_created": False,
            "supplier_status_changed": False,
        }


if __name__ == "__main__":
    as_of = datetime(
        2026, 10, 25, 12, 0,
        tzinfo=timezone.utc,
    )

    suppliers = [
        {
            "supplier_id": "SUP-001",
            "supplier_name": "Demo Supplier",
            "country": "India",
            "sku": "SKU-101",
            "unit_cost": 110,
            "available_capacity": 1000,
            "lead_time_days": 5,
            "on_time_rate": 0.97,
            "quality_rate": 0.99,
            "observed_at": (
                "2026-10-24T12:00:00+00:00"
            ),
        }
    ]

    deliveries = [
        {
            "delivery_id": "DEL-001",
            "purchase_order_id": "PO-001",
            "supplier_id": "SUP-001",
            "sku": "SKU-101",
            "ordered_quantity": 200,
            "delivered_quantity": 180,
            "promised_at": (
                "2026-10-24T10:00:00+00:00"
            ),
            "delivered_at": (
                "2026-10-24T12:00:00+00:00"
            ),
        }
    ]

    report = SupplierPipeline().run(
        raw_suppliers=suppliers,
        raw_deliveries=deliveries,
        required_quantities={"SKU-101": 800},
        as_of=as_of,
    )

    print(report)
