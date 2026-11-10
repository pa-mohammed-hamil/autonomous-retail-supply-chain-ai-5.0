"""Planned module: logistics ingestion. Implementation pending."""

"""
Logistics data ingestion.

Supports:
- Shipment events
- Delivery status updates
- Vehicle GPS telemetry
- CSV and JSON ingestion
- Row-level validation
- Batch duplicate detection

No fleet commands or shipment changes are executed.
"""

from __future__ import annotations

import csv
import io
import json
import math

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


def required_text(row: dict, key: str) -> str:
    value = row.get(key)

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid {key}")

    return value.strip()


def timestamp_utc(row: dict, key: str) -> str:
    value = required_text(row, key)

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError(
            f"Invalid ISO 8601 timestamp: {key}"
        ) from exc

    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(
            f"{key} must include timezone"
        )

    return dt.astimezone(timezone.utc).isoformat()


def finite_number(
    row: dict,
    key: str,
    minimum: float,
    maximum: float,
) -> float:
    value = row.get(key)

    if isinstance(value, bool):
        raise ValueError(f"Invalid {key}")

    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {key}") from exc

    if (
        not math.isfinite(number)
        or not minimum <= number <= maximum
    ):
        raise ValueError(f"{key} out of range")

    return number


@dataclass(frozen=True)
class ShipmentEvent:
    event_id: str
    shipment_id: str
    vehicle_id: str
    event_type: str
    occurred_at: str
    location_id: str | None = None


@dataclass(frozen=True)
class VehicleTelemetry:
    event_id: str
    vehicle_id: str
    latitude: float
    longitude: float
    speed_kmh: float
    recorded_at: str


class LogisticsIngestion:

    EVENT_TYPES = {
        "created",
        "picked_up",
        "in_transit",
        "out_for_delivery",
        "delivered",
        "delivery_failed",
        "returned",
        "cancelled",
        "delayed",
    }

    def validate_shipment(
        self,
        row: dict,
    ) -> ShipmentEvent:

        event_type = required_text(
            row, "event_type"
        )

        if event_type not in self.EVENT_TYPES:
            raise ValueError(
                f"Unsupported event_type: {event_type}"
            )

        location_id = row.get("location_id")

        if location_id is not None:
            if not isinstance(location_id, str):
                raise ValueError("Invalid location_id")
            location_id = location_id.strip() or None

        return ShipmentEvent(
            event_id=required_text(row, "event_id"),
            shipment_id=required_text(
                row, "shipment_id"
            ),
            vehicle_id=required_text(
                row, "vehicle_id"
            ),
            event_type=event_type,
            occurred_at=timestamp_utc(
                row, "occurred_at"
            ),
            location_id=location_id,
        )

    def validate_telemetry(
        self,
        row: dict,
    ) -> VehicleTelemetry:

        return VehicleTelemetry(
            event_id=required_text(row, "event_id"),
            vehicle_id=required_text(
                row, "vehicle_id"
            ),
            latitude=finite_number(
                row, "latitude", -90, 90
            ),
            longitude=finite_number(
                row, "longitude", -180, 180
            ),
            speed_kmh=finite_number(
                row, "speed_kmh", 0, 350
            ),
            recorded_at=timestamp_utc(
                row, "recorded_at"
            ),
        )

    def ingest(
        self,
        rows: list[dict[str, Any]],
        mode: str = "shipment",
    ) -> dict:

        validators = {
            "shipment": self.validate_shipment,
            "telemetry": self.validate_telemetry,
        }

        if mode not in validators:
            raise ValueError(
                "mode must be shipment or telemetry"
            )

        if not isinstance(rows, list):
            raise ValueError("Expected a list")

        validator = validators[mode]
        accepted = []
        rejected = []
        seen = set()

        for index, row in enumerate(rows):
            try:
                if not isinstance(row, dict):
                    raise ValueError(
                        "Row must be an object"
                    )

                record = validator(row)

                if record.event_id in seen:
                    raise ValueError(
                        "Duplicate event_id in batch"
                    )

                seen.add(record.event_id)
                accepted.append(asdict(record))

            except (ValueError, TypeError) as exc:
                rejected.append({
                    "row_index": index,
                    "reason": str(exc),
                })

        return {
            "mode": mode,
            "total": len(rows),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "records": accepted,
            "rejected": rejected,
            "persisted": False,
            "operational_state_updated": False,
        }

    def ingest_json(
        self,
        text: str,
        mode: str = "shipment",
    ) -> dict:
        return self.ingest(
            json.loads(text),
            mode=mode,
        )

    def ingest_csv(
        self,
        text: str,
        mode: str = "shipment",
    ) -> dict:
        rows = list(
            csv.DictReader(io.StringIO(text))
        )
        return self.ingest(rows, mode=mode)
