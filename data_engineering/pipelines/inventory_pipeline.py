"""Planned module: inventory pipeline. Implementation pending."""

"""
Inventory intelligence pipeline.

Integrates:
- InventoryIngestion
- Snapshot validation
- Inventory movement validation
- Stock availability calculations
- Reorder review indicators
- Inventory anomaly alerts
- Structured inventory reporting

Read-only:
Does not update stock balances, reserve stock,
transfer goods, or create purchase orders.

Movements are validated as separate events.
They are NOT applied to inventory snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ai.ingestion.inventory_ingestion import (
    InventoryIngestion,
)


@dataclass(frozen=True)
class InventoryPipelineConfig:
    low_stock_threshold: int = 50
    critical_stock_threshold: int = 10
    high_reservation_ratio: float = 0.80
    fail_on_rejected_records: bool = False

    def __post_init__(self):
        if (
            isinstance(self.low_stock_threshold, bool)
            or not isinstance(
                self.low_stock_threshold, int
            )
            or self.low_stock_threshold < 0
        ):
            raise ValueError(
                "Invalid low_stock_threshold"
            )

        if (
            isinstance(self.critical_stock_threshold, bool)
            or not isinstance(
                self.critical_stock_threshold, int
            )
            or self.critical_stock_threshold < 0
        ):
            raise ValueError(
                "Invalid critical_stock_threshold"
            )

        if (
            self.critical_stock_threshold
            > self.low_stock_threshold
        ):
            raise ValueError(
                "Critical threshold cannot exceed "
                "low stock threshold"
            )

        ratio = self.high_reservation_ratio

        if (
            isinstance(ratio, bool)
            or not isinstance(ratio, (int, float))
            or not 0 <= ratio <= 1
        ):
            raise ValueError(
                "Invalid high_reservation_ratio"
            )


class InventoryPipeline:

    def __init__(
        self,
        config: InventoryPipelineConfig | None = None,
    ):
        self.config = config or InventoryPipelineConfig()
        self.ingestion = InventoryIngestion()

    @staticmethod
    def _analyze_movements(
        records: list[dict],
    ) -> dict:
        by_type = {}
        net_quantity_delta = 0

        for record in records:
            movement_type = record["movement_type"]
            delta = record["quantity_delta"]

            by_type[movement_type] = (
                by_type.get(movement_type, 0) + 1
            )

            net_quantity_delta += delta

        return {
            "validated_movement_count": len(records),
            "movement_counts_by_type": by_type,
            "net_quantity_delta": net_quantity_delta,
            "applied_to_stock": False,
        }

    def _analyze_snapshots(
        self,
        records: list[dict],
    ) -> tuple[dict, list[dict], list[dict]]:

        seen = set()
        sku_totals = {}
        alerts = []

        total_on_hand = 0
        total_reserved = 0
        total_available = 0

        for record in records:
            sku = record["sku"]
            warehouse_id = record["warehouse_id"]

            key = (sku, warehouse_id)

            if key in seen:
                raise ValueError(
                    "Multiple snapshots for the same "
                    f"SKU and warehouse: {key}"
                )

            seen.add(key)

            on_hand = record["on_hand"]
            reserved = record["reserved"]
            available = on_hand - reserved

            total_on_hand += on_hand
            total_reserved += reserved
            total_available += available

            item = sku_totals.setdefault(
                sku,
                {
                    "sku": sku,
                    "on_hand": 0,
                    "reserved": 0,
                    "available": 0,
                    "warehouse_count": 0,
                },
            )

            item["on_hand"] += on_hand
            item["reserved"] += reserved
            item["available"] += available
            item["warehouse_count"] += 1

            if available <= self.config.critical_stock_threshold:
                alerts.append({
                    "code": "CRITICAL_STOCK",
                    "sku": sku,
                    "warehouse_id": warehouse_id,
                    "available": available,
                })

            elif available <= self.config.low_stock_threshold:
                alerts.append({
                    "code": "LOW_STOCK",
                    "sku": sku,
                    "warehouse_id": warehouse_id,
                    "available": available,
                })

            if on_hand > 0:
                reservation_ratio = (
                    reserved / on_hand
                )

                if (
                    reservation_ratio
                    >= self.config.high_reservation_ratio
                ):
                    alerts.append({
                        "code": "HIGH_RESERVATION_RATIO",
                        "sku": sku,
                        "warehouse_id": warehouse_id,
                        "reservation_ratio": round(
                            reservation_ratio, 4
                        ),
                    })

        summary = {
            "snapshot_count": len(records),
            "sku_count": len(sku_totals),
            "total_on_hand": total_on_hand,
            "total_reserved": total_reserved,
            "total_available": total_available,
        }

        return (
            summary,
            sorted(
                sku_totals.values(),
                key=lambda item: item["sku"],
            ),
            alerts,
        )

    def run(
        self,
        raw_snapshots: list[dict[str, Any]],
        raw_movements: list[dict[str, Any]] | None = None,
    ) -> dict:

        if not isinstance(raw_snapshots, list):
            raise ValueError(
                "raw_snapshots must be a list"
            )

        if raw_movements is None:
            raw_movements = []

        if not isinstance(raw_movements, list):
            raise ValueError(
                "raw_movements must be a list"
            )

        snapshot_result = self.ingestion.ingest(
            raw_snapshots,
            mode="snapshot",
        )

        movement_result = self.ingestion.ingest(
            raw_movements,
            mode="movement",
        )

        total_rejected = (
            snapshot_result["rejected_count"]
            + movement_result["rejected_count"]
        )

        if (
            total_rejected
            and self.config.fail_on_rejected_records
        ):
            return {
                "pipeline": "inventory_intelligence",
                "status": "failed_validation",
                "snapshot_rejections": (
                    snapshot_result["rejected"]
                ),
                "movement_rejections": (
                    movement_result["rejected"]
                ),
                "inventory_updated": False,
                "purchase_orders_created": False,
            }

        summary, sku_totals, alerts = (
            self._analyze_snapshots(
                snapshot_result["records"]
            )
        )

        movement_summary = (
            self._analyze_movements(
                movement_result["records"]
            )
        )

        reorder_reviews = [
            {
                "sku": item["sku"],
                "available": item["available"],
                "reason": "LOW_AGGREGATE_STOCK",
                "requires_approval": True,
            }
            for item in sku_totals
            if (
                item["available"]
                <= self.config.low_stock_threshold
            )
        ]

        return {
            "pipeline": "inventory_intelligence",
            "status": (
                "completed_with_rejections"
                if total_rejected
                else "completed"
            ),
            "generated_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "ingestion": {
                "snapshots_accepted": (
                    snapshot_result["accepted_count"]
                ),
                "snapshots_rejected": (
                    snapshot_result["rejected_count"]
                ),
                "movements_accepted": (
                    movement_result["accepted_count"]
                ),
                "movements_rejected": (
                    movement_result["rejected_count"]
                ),
                "snapshot_rejections": (
                    snapshot_result["rejected"]
                ),
                "movement_rejections": (
                    movement_result["rejected"]
                ),
            },
            "summary": summary,
            "sku_totals": sku_totals,
            "movement_summary": movement_summary,
            "alerts": alerts,
            "reorder_reviews": reorder_reviews,
            "requires_human_review": bool(
                alerts or reorder_reviews
            ),
            "persisted": False,
            "inventory_updated": False,
            "purchase_orders_created": False,
            "stock_transfers_executed": False,
        }


if __name__ == "__main__":
    from datetime import datetime, timezone

    now = datetime.now(
        timezone.utc
    ).isoformat()

    snapshots = [
        {
            "record_id": "SNAP-001",
            "sku": "SKU-101",
            "warehouse_id": "WH-KOCHI",
            "on_hand": 100,
            "reserved": 70,
            "updated_at": now,
        },
        {
            "record_id": "SNAP-002",
            "sku": "SKU-202",
            "warehouse_id": "WH-THRISSUR",
            "on_hand": 15,
            "reserved": 10,
            "updated_at": now,
        },
    ]

    movements = [
        {
            "event_id": "MOVE-001",
            "sku": "SKU-101",
            "warehouse_id": "WH-KOCHI",
            "movement_type": "purchase_receipt",
            "quantity_delta": 50,
            "occurred_at": now,
        },
        {
            "event_id": "MOVE-002",
            "sku": "SKU-202",
            "warehouse_id": "WH-THRISSUR",
            "movement_type": "sale",
            "quantity_delta": -5,
            "occurred_at": now,
        },
    ]

    pipeline = InventoryPipeline()

    report = pipeline.run(
        raw_snapshots=snapshots,
        raw_movements=movements,
    )

    print("Status:", report["status"])
    print("Summary:", report["summary"])
    print("Alerts:", report["alerts"])
    print(
        "Reorder reviews:",
        report["reorder_reviews"],
    )
