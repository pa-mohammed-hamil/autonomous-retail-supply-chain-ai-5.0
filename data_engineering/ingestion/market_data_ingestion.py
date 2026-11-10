"""Planned module: market data ingestion. Implementation pending."""


"""
Market data ingestion.

Supports:
- Product and competitor price observations
- Market demand signals
- Source attribution
- Currency validation
- ISO timestamp normalization
- CSV and JSON ingestion
- Batch duplicate detection

External data must be obtained from authorized
sources and compliant integrations.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


def text_field(row: dict, key: str) -> str:
    value = row.get(key)

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid {key}")

    return value.strip()


def utc_timestamp(row: dict, key: str) -> str:
    value = text_field(row, key)

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


def nonnegative_number(
    row: dict,
    key: str,
) -> float:
    value = row.get(key)

    if isinstance(value, bool):
        raise ValueError(f"Invalid {key}")

    try:
        number = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Invalid {key}") from exc

    if not math.isfinite(number) or number < 0:
        raise ValueError(f"Invalid {key}")

    return number


@dataclass(frozen=True)
class MarketPriceRecord:
    observation_id: str
    sku: str
    seller_id: str
    market: str
    currency: str
    price: float
    observed_at: str
    source: str


@dataclass(frozen=True)
class MarketDemandRecord:
    observation_id: str
    sku: str
    market: str
    demand_index: float
    observed_at: str
    source: str


class MarketDataIngestion:

    def validate_price(
        self,
        row: dict,
    ) -> MarketPriceRecord:

        currency = text_field(
            row, "currency"
        ).upper()

        if not re.fullmatch(
            r"[A-Z]{3}", currency
        ):
            raise ValueError(
                "Currency must be a 3-letter code"
            )

        return MarketPriceRecord(
            observation_id=text_field(
                row, "observation_id"
            ),
            sku=text_field(row, "sku"),
            seller_id=text_field(
                row, "seller_id"
            ),
            market=text_field(row, "market"),
            currency=currency,
            price=nonnegative_number(
                row, "price"
            ),
            observed_at=utc_timestamp(
                row, "observed_at"
            ),
            source=text_field(row, "source"),
        )

    def validate_demand(
        self,
        row: dict,
    ) -> MarketDemandRecord:

        demand_index = nonnegative_number(
            row, "demand_index"
        )

        return MarketDemandRecord(
            observation_id=text_field(
                row, "observation_id"
            ),
            sku=text_field(row, "sku"),
            market=text_field(row, "market"),
            demand_index=demand_index,
            observed_at=utc_timestamp(
                row, "observed_at"
            ),
            source=text_field(row, "source"),
        )

    def ingest(
        self,
        rows: list[dict[str, Any]],
        mode: str = "price",
    ) -> dict:

        validators = {
            "price": self.validate_price,
            "demand": self.validate_demand,
        }

        if mode not in validators:
            raise ValueError(
                "mode must be price or demand"
            )

        if not isinstance(rows, list):
            raise ValueError("Expected a list")

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

                if record.observation_id in seen:
                    raise ValueError(
                        "Duplicate observation_id"
                    )

                seen.add(record.observation_id)
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
        }

    def ingest_json(
        self,
        text: str,
        mode: str = "price",
    ) -> dict:
        return self.ingest(
            json.loads(text),
            mode=mode,
        )

    def ingest_csv(
        self,
        text: str,
        mode: str = "price",
    ) -> dict:
        rows = list(
            csv.DictReader(io.StringIO(text))
        )
        return self.ingest(rows, mode=mode)

