"""Planned module: logistics pipeline. Implementation pending."""

"""
Logistics intelligence pipeline.

Integrates:
- LogisticsIngestion
- Shipment event validation
- Vehicle GPS telemetry validation
- Latest shipment status
- Delivery performance metrics
- Delay and failed-delivery alerts
- Vehicle overspeed indicators
- Structured logistics reporting

Read-only:
Does not dispatch vehicles, change routes,
contact drivers or update shipment records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ai.ingestion.logistics_ingestion import (
    LogisticsIngestion,
)


@dataclass(frozen=True)
class LogisticsPipelineConfig:
    overspeed_threshold_kmh: float = 100.0
    fail_on_rejected_records: bool = False

    def __post_init__(self):
        if (
            isinstance(self.overspeed_threshold_kmh, bool)
            or not isinstance(
                self.overspeed_threshold_kmh,
                (int, float),
            )
            or not 0 < self.overspeed_threshold_kmh <= 350
        ):
            raise ValueError(
                "Invalid overspeed threshold"
            )


class LogisticsPipeline:

    TERMINAL_STATUSES = {
        "delivered",
        "delivery_failed",
        "returned",
        "cancelled",
    }

    def __init__(
        self,
        config: LogisticsPipelineConfig | None = None,
    ):
        self.config = config or LogisticsPipelineConfig()
        self.ingestion = LogisticsIngestion()

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        if not isinstance(value, str):
            raise ValueError("Invalid timestamp")

        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError(
                "Timezone-aware timestamp required"
            )

        return dt.astimezone(timezone.utc)

    def _analyze_shipments(
        self,
        records: list[dict],
    ) -> tuple[dict, list[dict], list[dict]]:

        grouped: dict[str, list[dict]] = {}

        for record in records:
            grouped.setdefault(
                record["shipment_id"], []
            ).append(record)

        shipments = []
        alerts = []
        status_counts = {}

        for shipment_id, events in sorted(
            grouped.items()
        ):
            events = sorted(
                events,
                key=lambda item: (
                    self._parse_timestamp(
                        item["occurred_at"]
                    ),
                    item["event_id"],
                ),
            )

            latest = events[-1]
            status = latest["event_type"]

            status_counts[status] = (
                status_counts.get(status, 0) + 1
            )

            vehicles = {
                event["vehicle_id"]
                for event in events
            }

            shipment = {
                "shipment_id": shipment_id,
                "latest_status": status,
                "latest_event_at": latest[
                    "occurred_at"
                ],
                "vehicle_ids": sorted(vehicles),
                "event_count": len(events),
                "terminal": (
                    status in self.TERMINAL_STATUSES
                ),
            }

            shipments.append(shipment)

            if status == "delayed":
                alerts.append({
                    "code": "SHIPMENT_DELAYED",
                    "shipment_id": shipment_id,
                    "requires_human_review": True,
                })

            elif status == "delivery_failed":
                alerts.append({
                    "code": "DELIVERY_FAILED",
                    "shipment_id": shipment_id,
                    "requires_human_review": True,
                })

        delivered = status_counts.get(
            "delivered", 0
        )

        total = len(shipments)

        summary = {
            "shipment_count": total,
            "delivered_count": delivered,
            "delivery_failed_count": (
                status_counts.get("delivery_failed", 0)
            ),
            "delayed_count": (
                status_counts.get("delayed", 0)
            ),
            "latest_status_counts": status_counts,
            "delivered_share": (
                round(delivered / total, 4)
                if total
                else None
            ),
            "on_time_delivery_rate": None,
        }

        return summary, shipments, alerts

    def _analyze_telemetry(
        self,
        records: list[dict],
    ) -> tuple[dict, list[dict], list[dict]]:

        latest_by_vehicle = {}
        alerts = []
        seen = set()

        for record in records:
            event_id = record["event_id"]

            if event_id in seen:
                raise ValueError(
                    "Duplicate telemetry event"
                )

            seen.add(event_id)

            vehicle_id = record["vehicle_id"]
            recorded_at = self._parse_timestamp(
                record["recorded_at"]
            )

            current = latest_by_vehicle.get(
                vehicle_id
            )

            if (
                current is None
                or recorded_at
                > self._parse_timestamp(
                    current["recorded_at"]
                )
            ):
                latest_by_vehicle[
                    vehicle_id
                ] = record

            if (
                record["speed_kmh"]
                > self.config.overspeed_threshold_kmh
            ):
                alerts.append({
                    "code": "SPEED_THRESHOLD_EXCEEDED",
                    "vehicle_id": vehicle_id,
                    "event_id": event_id,
                    "speed_kmh": record["speed_kmh"],
                    "configured_threshold_kmh": (
                        self.config.overspeed_threshold_kmh
                    ),
                    "requires_human_review": True,
                })

        vehicles = [
            {
                "vehicle_id": vehicle_id,
                "last_recorded_at": (
                    record["recorded_at"]
                ),
                "latitude": record["latitude"],
                "longitude": record["longitude"],
                "speed_kmh": record["speed_kmh"],
            }
            for vehicle_id, record in sorted(
                latest_by_vehicle.items()
            )
        ]

        summary = {
            "telemetry_event_count": len(records),
            "vehicle_count": len(vehicles),
            "speed_threshold_event_count": len(
                alerts
            ),
        }

        return summary, vehicles, alerts

    def run(
        self,
        shipment_events: list[dict[str, Any]],
        telemetry_events: list[dict[str, Any]] | None = None,
    ) -> dict:

        if not isinstance(shipment_events, list):
            raise ValueError(
                "shipment_events must be a list"
            )

        if telemetry_events is None:
            telemetry_events = []

        if not isinstance(telemetry_events, list):
            raise ValueError(
                "telemetry_events must be a list"
            )

        shipment_result = self.ingestion.ingest(
            shipment_events,
            mode="shipment",
        )

        telemetry_result = self.ingestion.ingest(
            telemetry_events,
            mode="telemetry",
        )

        rejected_count = (
            shipment_result["rejected_count"]
            + telemetry_result["rejected_count"]
        )

        if (
            rejected_count
            and self.config.fail_on_rejected_records
        ):
            return {
                "pipeline": "logistics_intelligence",
                "status": "failed_validation",
                "shipment_rejections": (
                    shipment_result["rejected"]
                ),
                "telemetry_rejections": (
                    telemetry_result["rejected"]
                ),
                "operational_actions_executed": False,
            }

        (
            shipment_summary,
            shipments,
            shipment_alerts,
        ) = self._analyze_shipments(
            shipment_result["records"]
        )

        (
            telemetry_summary,
            vehicles,
            telemetry_alerts,
        ) = self._analyze_telemetry(
            telemetry_result["records"]
        )

        alerts = shipment_alerts + telemetry_alerts

        return {
            "pipeline": "logistics_intelligence",
            "status": (
                "completed_with_rejections"
                if rejected_count
                else "completed"
            ),
            "generated_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "ingestion": {
                "shipment_events_accepted": (
                    shipment_result["accepted_count"]
                ),
                "shipment_events_rejected": (
                    shipment_result["rejected_count"]
                ),
                "telemetry_events_accepted": (
                    telemetry_result["accepted_count"]
                ),
                "telemetry_events_rejected": (
                    telemetry_result["rejected_count"]
                ),
                "shipment_rejections": (
                    shipment_result["rejected"]
                ),
                "telemetry_rejections": (
                    telemetry_result["rejected"]
                ),
            },
            "shipment_summary": shipment_summary,
            "telemetry_summary": telemetry_summary,
            "shipments": shipments,
            "vehicles": vehicles,
            "alerts": alerts,
            "requires_human_review": bool(alerts),
            "persisted": False,
            "shipment_status_updated": False,
            "routes_modified": False,
            "drivers_contacted": False,
        }


if __name__ == "__main__":
    shipment_events = [
        {
            "event_id": "SHIP-EVT-001",
            "shipment_id": "SHIP-101",
            "vehicle_id": "TRUCK-01",
            "event_type": "picked_up",
            "occurred_at": (
                "2026-10-25T09:00:00+05:30"
            ),
            "location_id": "WH-KOCHI",
        },
        {
            "event_id": "SHIP-EVT-002",
            "shipment_id": "SHIP-101",
            "vehicle_id": "TRUCK-01",
            "event_type": "delayed",
            "occurred_at": (
                "2026-10-25T11:00:00+05:30"
            ),
            "location_id": "ROUTE-01",
        },
    ]

    telemetry_events = [
        {
            "event_id": "GPS-001",
            "vehicle_id": "TRUCK-01",
            "latitude": 9.9312,
            "longitude": 76.2673,
            "speed_kmh": 105.0,
            "recorded_at": (
                "2026-10-25T11:05:00+05:30"
            ),
        }
    ]

    pipeline = LogisticsPipeline()

    result = pipeline.run(
        shipment_events=shipment_events,
        telemetry_events=telemetry_events,
    )

    print("Status:", result["status"])
    print(
        "Shipment summary:",
        result["shipment_summary"],
    )
    print(
        "Telemetry summary:",
        result["telemetry_summary"],
    )
    print("Alerts:", result["alerts"])
