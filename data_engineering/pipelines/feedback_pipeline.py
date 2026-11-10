"""Planned module: feedback pipeline. Implementation pending."""

"""
Customer feedback intelligence pipeline.

Integrates:
- FeedbackIngestion
- FeedbackAggregator
- Customer satisfaction metrics
- Product complaint indicators
- Rating trend alerts
- Structured pipeline reporting

Read-only:
Does not contact customers, modify reviews,
or automatically change product listings.
"""

from __future__ import annotations

import os

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ai.ingestion.feedback_ingestion import (
    FeedbackIngestion,
)
from ai.analytics.feedback_aggregation import (
    FeedbackAggregator,
)


@dataclass(frozen=True)
class FeedbackPipelineConfig:
    period_days: int = 7
    minimum_reviews_for_alert: int = 5
    fail_on_rejected_records: bool = False

    def __post_init__(self):
        for name in (
            "period_days",
            "minimum_reviews_for_alert",
        ):
            value = getattr(self, name)

            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                raise ValueError(f"Invalid {name}")


class FeedbackPipeline:

    def __init__(
        self,
        config: FeedbackPipelineConfig | None = None,
        hmac_secret: str | None = None,
    ):
        self.config = config or FeedbackPipelineConfig()

        self.ingestion = FeedbackIngestion(
            secret=hmac_secret
        )

        self.aggregator = FeedbackAggregator()

    @staticmethod
    def _validate_as_of(
        as_of: datetime | None,
    ) -> datetime:
        if as_of is None:
            return datetime.now(timezone.utc)

        if (
            as_of.tzinfo is None
            or as_of.utcoffset() is None
        ):
            raise ValueError(
                "as_of must be timezone-aware"
            )

        return as_of.astimezone(timezone.utc)

    @staticmethod
    def _summarize_products(
        products: list[dict],
    ) -> dict:
        total_reviews = 0
        positive = 0
        negative = 0
        complaint_indicators = 0

        for product in products:
            recent = product["recent"]
            count = recent["count"]

            total_reviews += count

            if count == 0:
                continue

            positive += (
                recent["rating_distribution"]["4"]
                + recent["rating_distribution"]["5"]
            )

            negative += (
                recent["rating_distribution"]["1"]
                + recent["rating_distribution"]["2"]
            )

            # Aggregate estimated count from the
            # rounded product-level complaint rate.
            complaint_indicators += round(
                recent["complaint_indicator_rate"]
                * count
            )

        if total_reviews == 0:
            return {
                "recent_review_count": 0,
                "positive_rating_rate": None,
                "negative_rating_rate": None,
                "complaint_indicator_rate": None,
            }

        return {
            "recent_review_count": total_reviews,
            "positive_rating_rate": round(
                positive / total_reviews, 4
            ),
            "negative_rating_rate": round(
                negative / total_reviews, 4
            ),
            "complaint_indicator_rate": round(
                complaint_indicators / total_reviews,
                4,
            ),
        }

    def run(
        self,
        raw_feedback: list[dict[str, Any]],
        as_of: datetime | None = None,
    ) -> dict:

        if not isinstance(raw_feedback, list):
            raise ValueError(
                "raw_feedback must be a list"
            )

        as_of = self._validate_as_of(as_of)

        ingestion_result = self.ingestion.ingest(
            raw_feedback
        )

        rejected = ingestion_result["rejected"]

        if (
            rejected
            and self.config.fail_on_rejected_records
        ):
            return {
                "pipeline": "feedback_intelligence",
                "status": "failed_validation",
                "ingestion": {
                    "accepted_count": ingestion_result[
                        "accepted_count"
                    ],
                    "rejected_count": ingestion_result[
                        "rejected_count"
                    ],
                    "rejected": rejected,
                },
                "aggregation": None,
                "alerts": [],
                "actions_executed": False,
            }

        accepted = ingestion_result["records"]

        # The aggregator requires unique feedback IDs
        # and timezone-aware created_at values.
        aggregation = self.aggregator.aggregate(
            records=accepted,
            as_of=as_of,
            period_days=self.config.period_days,
            minimum_reviews_for_alert=(
                self.config.minimum_reviews_for_alert
            ),
        )

        summary = self._summarize_products(
            aggregation["products"]
        )

        return {
            "pipeline": "feedback_intelligence",
            "status": (
                "completed_with_rejections"
                if rejected
                else "completed"
            ),
            "generated_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "as_of": as_of.isoformat(),
            "ingestion": {
                "total": ingestion_result["total"],
                "accepted_count": ingestion_result[
                    "accepted_count"
                ],
                "rejected_count": ingestion_result[
                    "rejected_count"
                ],
                "rejected": rejected,
            },
            "summary": summary,
            "products": aggregation["products"],
            "alerts": aggregation["alerts"],
            "requires_human_review": bool(
                aggregation["alerts"]
            ),
            "persisted": False,
            "customer_contacted": False,
            "product_listings_modified": False,
        }


if __name__ == "__main__":
    from datetime import timedelta

    # For local development only.
    # Set CUSTOMER_HMAC_KEY securely in the environment
    # for real deployments.
    demo_secret = "demo-secret-not-for-production"

    now = datetime(
        2026, 10, 25, 12, 0,
        tzinfo=timezone.utc,
    )

    feedback = [
        {
            "feedback_id": f"FB-{i:03d}",
            "customer_id": f"CUSTOMER-{i}",
            "product_id": "SKU-101",
            "rating": rating,
            "review_text": (
                "Delivery delayed and item damaged"
                if rating <= 2
                else "Product received successfully"
            ),
            "source": "website",
            "created_at": (
                now - timedelta(days=i)
            ).isoformat(),
        }
        for i, rating in enumerate(
            [5, 4, 2, 1, 2, 3]
        )
    ]

    pipeline = FeedbackPipeline(
        hmac_secret=demo_secret,
    )

    report = pipeline.run(
        raw_feedback=feedback,
        as_of=now,
    )

    print("Status:", report["status"])
    print("Summary:", report["summary"])
    print("Alerts:", report["alerts"])
    