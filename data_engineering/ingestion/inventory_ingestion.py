"""Planned module: inventory ingestion. Implementation pending."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class InventorySnapshot:
    record_id: str
    sku: str
    warehouse_id: str
    on_hand: int
    reserved: int
    updated_at: str

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved


@dataclass(frozen=True)
class InventoryMovement:
    event_id: str
    sku: str
    warehouse_id: str
    movement_type: str
    quantity_delta: int
    occurred_at: str


class InventoryIngestion:

    MOVEMENT_TYPES = {
        "purchase_receipt",
        "sale",
        "return",
        "transfer_in",
        "transfer_out",
        "adjustment",
    }

    @staticmethod
    def required_text(
        row: dict,
        key: str,
    ) -> str:
        value = row.get(key)
        if not isinstance(value, str):
            raise ValueError(f"Invalid {key}")

        value = value.strip()
        if not value:
            raise ValueError(f"Missing {key}")

        return value

    @staticmethod
    def integer(
        row: dict,
        key: str,
        allow_negative: bool = False,
    ) -> int:
        value = row.get(key)

        if (
            isinstance(value, bool)
            or not isinstance(value, int)
        ):
            raise ValueError(f"{key} must be integer")

        if not allow_negative and value < 0:
            raise ValueError(
                f"{key} cannot be negative"
            )

        return value

    @staticmethod
    def timestamp(
        row: dict,
        key: str,
    ) -> str:
        value = InventoryIngestion.required_text(
            row, key
        )

        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            raise ValueError(
                f"{key} must include timezone"
            )

        return dt.astimezone(
            timezone.utc
        ).isoformat()

    def validate_snapshot(
        self,
        row: dict,
    ) -> InventorySnapshot:

        on_hand = self.integer(row, "on_hand")
        reserved = self.integer(row, "reserved")

        if reserved > on_hand:
            raise ValueError(
                "Reserved quantity exceeds on-hand"
            )

        return InventorySnapshot(
            record_id=self.required_text(
                row, "record_id"
            ),
            sku=self.required_text(row, "sku"),
            warehouse_id=self.required_text(
                row, "warehouse_id"
            ),
            on_hand=on_hand,
            reserved=reserved,
            updated_at=self.timestamp(
                row, "updated_at"
            ),
        )

    def validate_movement(
        self,
        row: dict,
    ) -> InventoryMovement:

        movement_type = self.required_text(
            row, "movement_type"
        )

        if movement_type not in self.MOVEMENT_TYPES:
            raise ValueError(
                "Unsupported movement type"
            )

        delta = self.integer(
            row,
            "quantity_delta",
            allow_negative=True,
        )

        if delta == 0:
            raise ValueError(
                "Movement delta cannot be zero"
            )

        positive_types = {
            "purchase_receipt",
            "return",
            "transfer_in",
        }

        negative_types = {
            "sale",
            "transfer_out",
        }

        if (
            movement_type in positive_types
            and delta <= 0
        ):
            raise ValueError(
                "Expected positive quantity delta"
            )

        if (
            movement_type in negative_types
            and delta >= 0
        ):
            raise ValueError(
                "Expected negative quantity delta"
            )

        return InventoryMovement(
            event_id=self.required_text(
                row, "event_id"
            ),
            sku=self.required_text(row, "sku"),
            warehouse_id=self.required_text(
                row, "warehouse_id"
            ),
            movement_type=movement_type,
            quantity_delta=delta,
            occurred_at=self.timestamp(
                row, "occurred_at"
            ),
        )

    def ingest(
        self,
        rows: list[dict],
        mode: str = "snapshot",
    ) -> dict:

        if mode not in {"snapshot", "movement"}:
            raise ValueError(
                "mode must be snapshot or movement"
            )

        validator = (
            self.validate_snapshot
            if mode == "snapshot"
            else self.validate_movement
        )

        id_field = (
            "record_id"
            if mode == "snapshot"
            else "event_id"
        )

        accepted = []
        rejected = []
        seen = set()

        for index, row in enumerate(rows):
            try:
                record = validator(row)
                identifier = getattr(record, id_field)

                if identifier in seen:
                    raise ValueError(
                        f"Duplicate {id_field} in batch"
                    )

                seen.add(identifier)

                data = asdict(record)

                if mode == "snapshot":
                    data["available"] = record.available

                accepted.append(data)

            except (
                ValueError,
                TypeError,
                KeyError,
            ) as exc:
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
            "inventory_updated": False,
        }

    def ingest_json(
        self,
        text: str,
        mode: str = "snapshot",
    ) -> dict:
        rows = json.loads(text)
        if not isinstance(rows, list):
            raise ValueError(
                "Expected JSON array"
            )
        return self.ingest(rows, mode)

    def ingest_csv(
        self,
        text: str,
        mode: str = "snapshot",
    ) -> dict:

        rows = list(
            csv.DictReader(io.StringIO(text))
        )

        numeric_fields = (
            ("on_hand", "reserved")
            if mode == "snapshot"
            else ("quantity_delta",)
        )

        for row in rows:
            for key in numeric_fields:
                value = row.get(key)

                if value is not None:
                    try:
                        row[key] = int(value)
                    except ValueError:
                        pass

        return self.ingest(rows, mode)
