"""Planned module: feedback ingestion. Implementation pending."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class FeedbackRecord:
    feedback_id: str
    customer_token: str
    product_id: str
    rating: int
    review_text: str
    source: str
    created_at: str
    order_id: str | None = None


class FeedbackIngestion:

    def __init__(self, secret: str | None = None):
        self.secret = secret or os.getenv(
            "CUSTOMER_HMAC_KEY"
        )
        if not self.secret:
            raise ValueError(
                "Set CUSTOMER_HMAC_KEY securely"
            )

    def customer_token(self, customer_id: str) -> str:
        return hmac.new(
            self.secret.encode(),
            customer_id.encode(),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def parse_timestamp(value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError(
                "created_at must be ISO 8601 text"
            )

        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
        if dt.tzinfo is None:
            raise ValueError(
                "Timezone-aware timestamp required"
            )
        return dt.astimezone(
            timezone.utc
        ).isoformat()

    def validate(self, row: dict) -> FeedbackRecord:
        required = (
            "feedback_id",
            "customer_id",
            "product_id",
            "rating",
            "review_text",
            "source",
            "created_at",
        )

        for key in required:
            if key not in row:
                raise ValueError(f"Missing {key}")

        for key in (
            "feedback_id",
            "customer_id",
            "product_id",
            "source",
        ):
            if (
                not isinstance(row[key], str)
                or not row[key].strip()
            ):
                raise ValueError(f"Invalid {key}")

        rating = row["rating"]
        if (
            isinstance(rating, bool)
            or not isinstance(rating, int)
            or not 1 <= rating <= 5
        ):
            raise ValueError(
                "rating must be an integer from 1 to 5"
            )

        review = row["review_text"]
        if not isinstance(review, str):
            raise ValueError(
                "review_text must be a string"
            )

        review = self.normalize_text(review)

        if not review or len(review) > 10000:
            raise ValueError(
                "Review length must be 1-10000"
            )

        order_id = row.get("order_id")
        if order_id is not None and not isinstance(
            order_id, str
        ):
            raise ValueError("Invalid order_id")

        return FeedbackRecord(
            feedback_id=row["feedback_id"].strip(),
            customer_token=self.customer_token(
                row["customer_id"].strip()
            ),
            product_id=row["product_id"].strip(),
            rating=rating,
            review_text=review,
            source=row["source"].strip(),
            created_at=self.parse_timestamp(
                row["created_at"]
            ),
            order_id=order_id,
        )

    def ingest(self, rows: list[dict]) -> dict:
        accepted = []
        rejected = []
        seen = set()

        for index, row in enumerate(rows):
            try:
                record = self.validate(row)

                if record.feedback_id in seen:
                    raise ValueError(
                        "Duplicate feedback_id in batch"
                    )

                seen.add(record.feedback_id)
                accepted.append(asdict(record))

            except (ValueError, TypeError, KeyError) as exc:
                rejected.append({
                    "row_index": index,
                    "reason": str(exc),
                })

        return {
            "total": len(rows),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "records": accepted,
            "rejected": rejected,
            "persisted": False,
        }

    def ingest_json(self, text: str) -> dict:
        rows = json.loads(text)
        if not isinstance(rows, list):
            raise ValueError(
                "Expected a JSON array"
            )
        return self.ingest(rows)

    def ingest_csv(self, text: str) -> dict:
        rows = list(
            csv.DictReader(io.StringIO(text))
        )

        for row in rows:
            if row.get("rating", "").isdigit():
                row["rating"] = int(row["rating"])

        return self.ingest(rows)
