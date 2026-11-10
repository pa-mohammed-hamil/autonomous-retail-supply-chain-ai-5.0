"""Planned module: supplier ingestion. Implementation pending."""

"""
ai/ingestion/supplier_ingestion.py

Supplier and procurement delivery ingestion.

Features:
- Supplier master records
- Supplier performance observations
- Delivery and purchase-order records
- Capacity and lead-time validation
- CSV and JSON support
- Batch duplicate detection

Does not create purchase orders, update supplier
contracts, or confirm receipt of goods.
"""

from __future__ import annotations

import csv
import io
import json
import math

from dataclasses import asdict, dataclass
from datetime import datetime, timezone


def text_value(row: dict, key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid {key}")
    return value.strip()


def numeric(
    row: dict,
    key: str,
    minimum: float = 0,
    maximum: float = math.inf,
) -> float:
    value = row.get(key)

    if isinstance(value, bool):
        raise ValueError(f"Invalid {key}")

    try:
        number = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid {key}") from exc

    if (
        not math.isfinite(number)
        or not minimum <= number <= maximum
    ):
        raise ValueError(f"{key} out of range")

    return number


def whole_number(row: dict, key: str) -> int:
    value = row.get(key)

    if isinstance(value, bool):
        raise ValueError(f"Invalid {key}")

    if isinstance(value, str):
        try:
            value = int(value)
        except ValueError:
            pass

    if not isinstance(value, int) or value < 0:
        raise ValueError(
            f"{key} must be a nonnegative integer"
        )

    return value


def timestamp(row: dict, key: str) -> str:
    value = text_value(row, key)

    try:
        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError(
            f"Invalid timestamp: {key}"
        ) from exc

    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(
            "Timezone-aware timestamp required"
        )

    return dt.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class SupplierRecord:
    supplier_id: str
    supplier_name: str
    country: str
    sku: str
    unit_cost: float
    available_capacity: int
    lead_time_days: float
    on_time_rate: float
    quality_rate: float
    observed_at: str


@dataclass(frozen=True)
class SupplierDeliveryRecord:
    delivery_id: str
    purchase_order_id: str
    supplier_id: str
    sku: str
    ordered_quantity: int
    delivered_quantity: int
    promised_at: str
    delivered_at: str


class SupplierIngestion:

    def validate_supplier(
        self,
        row: dict,
    ) -> SupplierRecord:

        return SupplierRecord(
            supplier_id=text_value(
                row, "supplier_id"
            ),
            supplier_name=text_value(
                row, "supplier_name"
            ),
            country=text_value(row, "country"),
            sku=text_value(row, "sku"),
            unit_cost=numeric(
                row, "unit_cost"
            ),
            available_capacity=whole_number(
                row, "available_capacity"
            ),
            lead_time_days=numeric(
                row, "lead_time_days"
            ),
            on_time_rate=numeric(
                row, "on_time_rate", 0, 1
            ),
            quality_rate=numeric(
                row, "quality_rate", 0, 1
            ),
            observed_at=timestamp(
                row, "observed_at"
            ),
        )

    def validate_delivery(
        self,
        row: dict,
    ) -> SupplierDeliveryRecord:

        ordered = whole_number(
            row, "ordered_quantity"
        )
        delivered = whole_number(
            row, "delivered_quantity"
        )

        if ordered == 0:
            raise ValueError(
                "Ordered quantity must be positive"
            )

        if delivered > ordered:
            raise ValueError(
                "Delivered quantity exceeds ordered quantity"
            )

        promised_at = timestamp(
            row, "promised_at"
        )
        delivered_at = timestamp(
            row, "delivered_at"
        )

        return SupplierDeliveryRecord(
            delivery_id=text_value(
                row, "delivery_id"
            ),
            purchase_order_id=text_value(
                row, "purchase_order_id"
            ),
            supplier_id=text_value(
                row, "supplier_id"
            ),
            sku=text_value(row, "sku"),
            ordered_quantity=ordered,
            delivered_quantity=delivered,
            promised_at=promised_at,
            delivered_at=delivered_at,
        )

    def ingest(
        self,
        rows: list[dict],
        mode: str = "supplier",
    ) -> dict:

        validators = {
            "supplier": self.validate_supplier,
            "delivery": self.validate_delivery,
        }

        if mode not in validators:
            raise ValueError(
                "mode must be supplier or delivery"
            )

        if not isinstance(rows, list):
            raise ValueError("Expected list of records")

        accepted = []
        rejected = []
        seen = set()

        for index, row in enumerate(rows):
            try:
                if not isinstance(row, dict):
                    raise ValueError(
                        "Row must be an object"
                    )

                record = validators[mode](row)

                key = (
                    (record.supplier_id, record.sku)
                    if mode == "supplier"
                    else (record.delivery_id, record.sku)
                )

                if key in seen:
                    raise ValueError(
                        "Duplicate record in batch"
                    )

                seen.add(key)

                data = asdict(record)

                if mode == "delivery":
                    data["on_time"] = (
                        record.delivered_at
                        <= record.promised_at
                    )
                    data["short_quantity"] = (
                        record.ordered_quantity
                        - record.delivered_quantity
                    )

                accepted.append(data)

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
            "purchase_orders_updated": False,
        }

    def ingest_json(
        self,
        text: str,
        mode: str = "supplier",
    ) -> dict:
        return self.ingest(
            json.loads(text),
            mode,
        )

    def ingest_csv(
        self,
        text: str,
        mode: str = "supplier",
    ) -> dict:
        return self.ingest(
            list(csv.DictReader(io.StringIO(text))),
            mode,
        )
