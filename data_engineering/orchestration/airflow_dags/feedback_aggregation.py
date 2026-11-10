"""Planned module: feedback aggregation. Implementation pending."""

"""
ai/analytics/feedback_aggregation.py

Customer feedback aggregation.

Features:
- Product-level feedback summaries
- Average rating and rating distribution
- Positive / neutral / negative rating proxies
- Complaint indicator detection
- Recent versus previous-period trends
- Duplicate feedback ID validation
- JSON-ready structured output

No external APIs or dependencies.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean


class FeedbackAggregator:

    COMPLAINT_TERMS = {
        "damaged",
        "broken",
        "late",
        "delayed",
        "missing",
        "defective",
        "refund",
        "expired",
        "poor quality",
        "wrong item",
    }

    @staticmethod
    def _parse_time(value: str) -> datetime:
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

    @classmethod
    def _has_complaint(cls, text: str) -> bool:
        normalized = text.lower()

        # Simple keyword matching.
        # Negation and context are not understood.
        return any(
            re.search(
                rf"\b{re.escape(term)}\b",
                normalized,
            )
            for term in cls.COMPLAINT_TERMS
        )

    @staticmethod
    def _summary(records: list[dict]) -> dict:
        if not records:
            return {
                "count": 0,
                "average_rating": None,
                "positive_rate": None,
                "negative_rate": None,
                "complaint_indicator_rate": None,
                "rating_distribution": {
                    str(i): 0 for i in range(1, 6)
                },
            }

        ratings = [r["rating"] for r in records]
        distribution = Counter(ratings)
        count = len(records)

        return {
            "count": count,
            "average_rating": round(
                mean(ratings), 3
            ),
            "positive_rate": round(
                sum(r >= 4 for r in ratings) / count,
                4,
            ),
            "negative_rate": round(
                sum(r <= 2 for r in ratings) / count,
                4,
            ),
            "complaint_indicator_rate": round(
                sum(
                    FeedbackAggregator._has_complaint(
                        r["review_text"]
                    )
                    for r in records
                ) / count,
                4,
            ),
            "rating_distribution": {
                str(i): distribution[i]
                for i in range(1, 6)
            },
        }

    def aggregate(
        self,
        records: list[dict],
        as_of: datetime | None = None,
        period_days: int = 7,
        minimum_reviews_for_alert: int = 5,
    ) -> dict:

        if (
            isinstance(period_days, bool)
            or not isinstance(period_days, int)
            or period_days <= 0
        ):
            raise ValueError("Invalid period_days")

        if (
            isinstance(minimum_reviews_for_alert, bool)
            or not isinstance(
                minimum_reviews_for_alert, int
            )
            or minimum_reviews_for_alert < 1
        ):
            raise ValueError(
                "Invalid minimum review count"
            )

        as_of = as_of or datetime.now(
            timezone.utc
        )

        if (
            as_of.tzinfo is None
            or as_of.utcoffset() is None
        ):
            raise ValueError(
                "as_of must be timezone-aware"
            )

        as_of = as_of.astimezone(timezone.utc)

        recent_start = as_of - timedelta(
            days=period_days
        )
        previous_start = recent_start - timedelta(
            days=period_days
        )

        grouped = defaultdict(
            lambda: {
                "recent": [],
                "previous": [],
            }
        )

        seen = set()

        for record in records:
            feedback_id = record["feedback_id"]
            sku = record["product_id"]
            rating = record["rating"]
            review_text = record["review_text"]

            if (
                not isinstance(feedback_id, str)
                or not feedback_id.strip()
                or not isinstance(sku, str)
                or not sku.strip()
                or isinstance(rating, bool)
                or not isinstance(rating, int)
                or not 1 <= rating <= 5
                or not isinstance(review_text, str)
            ):
                raise ValueError(
                    "Invalid feedback record"
                )

            if feedback_id in seen:
                raise ValueError(
                    f"Duplicate feedback ID: {feedback_id}"
                )

            seen.add(feedback_id)

            created_at = self._parse_time(
                record["created_at"]
            )

            if created_at > as_of:
                raise ValueError(
                    "Feedback timestamp is in the future"
                )

            if recent_start <= created_at <= as_of:
                grouped[sku]["recent"].append(record)

            elif previous_start <= created_at < recent_start:
                grouped[sku]["previous"].append(record)

        products = []
        alerts = []

        for sku in sorted(grouped):
            recent = self._summary(
                grouped[sku]["recent"]
            )
            previous = self._summary(
                grouped[sku]["previous"]
            )

            rating_change = None

            if (
                recent["average_rating"] is not None
                and previous["average_rating"] is not None
            ):
                rating_change = round(
                    recent["average_rating"]
                    - previous["average_rating"],
                    3,
                )

            product = {
                "sku": sku,
                "recent": recent,
                "previous": previous,
                "average_rating_change": rating_change,
            }

            products.append(product)

            if recent["count"] >= minimum_reviews_for_alert:
                if (
                    recent["negative_rate"] is not None
                    and recent["negative_rate"] >= 0.30
                ):
                    alerts.append({
                        "sku": sku,
                        "code": "HIGH_NEGATIVE_RATING_RATE",
                        "negative_rate": (
                            recent["negative_rate"]
                        ),
                    })

                if (
                    rating_change is not None
                    and rating_change <= -0.5
                ):
                    alerts.append({
                        "sku": sku,
                        "code": "RATING_DECLINE",
                        "rating_change": rating_change,
                    })

        return {
            "as_of": as_of.isoformat(),
            "period_days": period_days,
            "products": products,
            "alerts": alerts,
            "analysis_type": "rating_based_aggregation",
            "actions_executed": False,
        }
