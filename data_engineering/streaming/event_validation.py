"""Planned module: event validation. Implementation pending."""

"""
ai/pipelines/event_validation.py

Event validation layer for the retail supply-chain
event-driven architecture.

Integrates:
- EventSchemas
- Event envelope validation
- Business event validation
- Duplicate detection within a batch
- Event timestamp checks
- Event payload size limits
- Event age and future-skew checks
- Structured rejection reports

Standard library only. Python 3.10+.

No events are published or executed.
"""

from __future__ import annotations

import json

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ai.pipelines.event_schemas import EventSchemas


@dataclass(frozen=True)
class EventValidationConfig:
    max_payload_bytes: int = 1_048_576
    max_event_age_hours: float = 72.0
    allowed_future_skew_seconds: float = 120.0
    reject_stale_events: bool = True

    def __post_init__(self):
        if (
            isinstance(self.max_payload_bytes, bool)
            or not isinstance(self.max_payload_bytes, int)
            or self.max_payload_bytes < 1
        ):
            raise ValueError(
                "Invalid max_payload_bytes"
            )

        if self.max_event_age_hours <= 0:
            raise ValueError(
                "max_event_age_hours must be positive"
            )

        if self.allowed_future_skew_seconds < 0:
            raise ValueError(
                "Future skew cannot be negative"
            )


class EventValidation:

    def __init__(
        self,
        config: EventValidationConfig | None = None,
    ):
        self.config = config or EventValidationConfig()

    @staticmethod
    def _as_of(
        value: datetime | None,
    ) -> datetime:
        value = value or datetime.now(timezone.utc)

        if (
            value.tzinfo is None
            or value.utcoffset() is None
        ):
            raise ValueError(
                "as_of must be timezone-aware"
            )

        return value.astimezone(timezone.utc)

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        if not isinstance(value, str):
            raise ValueError(
                "Timestamp must be ISO text"
            )

        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if (
            dt.tzinfo is None
            or dt.utcoffset() is None
        ):
            raise ValueError(
                "Timezone required"
            )

        return dt.astimezone(timezone.utc)

    def validate(
        self,
        event: dict[str, Any],
        as_of: datetime | None = None,
    ) -> dict:
        as_of = self._as_of(as_of)

        errors = []
        warnings = []

        if not isinstance(event, dict):
            return {
                "valid": False,
                "errors": ["Event must be a dictionary"],
                "warnings": [],
            }

        try:
            encoded = json.dumps(
                event,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")

            if len(encoded) > self.config.max_payload_bytes:
                errors.append(
                    "Event exceeds maximum serialized size"
                )

        except (TypeError, ValueError):
            errors.append(
                "Event is not valid JSON data"
            )

        schema_result = EventSchemas.validate(event)

        errors.extend(schema_result["errors"])

        if schema_result["valid"]:
            occurred_at = self._parse_timestamp(
                event["occurred_at"]
            )

            produced_at = self._parse_timestamp(
                event["produced_at"]
            )

            for field_name, timestamp in (
                ("occurred_at", occurred_at),
                ("produced_at", produced_at),
            ):
                future_seconds = (
                    timestamp - as_of
                ).total_seconds()

                if (
                    future_seconds
                    > self.config.allowed_future_skew_seconds
                ):
                    errors.append(
                        f"{field_name} exceeds future skew"
                    )

            age_hours = (
                as_of - occurred_at
            ).total_seconds() / 3600

            if age_hours > self.config.max_event_age_hours:
                message = (
                    "Event exceeds maximum permitted age"
                )

                if self.config.reject_stale_events:
                    errors.append(message)
                else:
                    warnings.append(message)

        return {
            "valid": not errors,
            "event_id": event.get("event_id"),
            "event_type": event.get("event_type"),
            "errors": errors,
            "warnings": warnings,
            "checked_at": as_of.isoformat(),
        }

    def validate_batch(
        self,
        events: list[dict[str, Any]],
        as_of: datetime | None = None,
    ) -> dict:
        if not isinstance(events, list):
            raise ValueError(
                "events must be a list"
            )

        as_of = self._as_of(as_of)

        accepted = []
        rejected = []
        seen_ids = set()

        for index, event in enumerate(events):
            result = self.validate(
                event,
                as_of=as_of,
            )

            event_id = result.get("event_id")

            if event_id is not None:
                if event_id in seen_ids:
                    result["errors"].append(
                        "Duplicate event_id in batch"
                    )
                    result["valid"] = False
                else:
                    seen_ids.add(event_id)

            if result["valid"]:
                accepted.append(event)
            else:
                rejected.append({
                    "row_index": index,
                    "event_id": event_id,
                    "errors": result["errors"],
                    "warnings": result["warnings"],
                })

        return {
            "total": len(events),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "passed": not rejected,
            "records": accepted,
            "rejected": rejected,
            "events_published": False,
        }


if __name__ == "__main__":
    event = EventSchemas.create(
        event_type="inventory.snapshot_updated",
        source="inventory_pipeline",
        payload={
            "sku": "SKU-101",
            "warehouse_id": "WH-KOCHI",
            "on_hand": 200,
            "reserved": 40,
            "available": 160,
        },
    )

    validator = EventValidation()

    print(validator.validate(event))

    print(
        validator.validate_batch([event])
    )
