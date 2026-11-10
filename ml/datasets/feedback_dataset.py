"""Planned module: feedback dataset. Implementation pending."""

"""
ai/datasets/feedback_dataset.py

Autonomous Retail Supply Chain AI 5.0

Synthetic Customer Feedback Dataset

Features:
- Positive, neutral, negative feedback
- Complaint categories
- Severity labels
- Topic labels
- Quality issue labels
- Customer, order and product IDs
- Repeated complaints for deduplication
- Reproducible random generation
- CSV and JSON export

Standard library only.
"""

from __future__ import annotations

import csv
import json
import random

from datetime import datetime, timedelta, timezone
from pathlib import Path


class FeedbackDatasetGenerator:

    TEMPLATES = [
        {
            "text": "The product quality is excellent.",
            "sentiment": "positive",
            "category": "product_quality",
            "severity": "none",
            "topic": "quality",
            "quality_issue": False,
        },
        {
            "text": "The delivery was fast and reliable.",
            "sentiment": "positive",
            "category": "delivery",
            "severity": "none",
            "topic": "delivery",
            "quality_issue": False,
        },
        {
            "text": "Customer support was helpful.",
            "sentiment": "positive",
            "category": "customer_support",
            "severity": "none",
            "topic": "support",
            "quality_issue": False,
        },
        {
            "text": "The product price was affordable.",
            "sentiment": "positive",
            "category": "pricing",
            "severity": "none",
            "topic": "pricing",
            "quality_issue": False,
        },
        {
            "text": "The order arrived today.",
            "sentiment": "neutral",
            "category": "order_status",
            "severity": "none",
            "topic": "delivery",
            "quality_issue": False,
        },
        {
            "text": "I checked the product details.",
            "sentiment": "neutral",
            "category": "product_information",
            "severity": "none",
            "topic": "product",
            "quality_issue": False,
        },
        {
            "text": "The delivery was delayed.",
            "sentiment": "negative",
            "category": "delivery_delay",
            "severity": "medium",
            "topic": "delivery",
            "quality_issue": False,
        },
        {
            "text": "The product arrived damaged.",
            "sentiment": "negative",
            "category": "damaged_product",
            "severity": "high",
            "topic": "quality",
            "quality_issue": True,
        },
        {
            "text": "The device is defective and not working.",
            "sentiment": "negative",
            "category": "manufacturing_defect",
            "severity": "high",
            "topic": "quality",
            "quality_issue": True,
        },
        {
            "text": "The package seal was broken.",
            "sentiment": "negative",
            "category": "packaging_issue",
            "severity": "medium",
            "topic": "packaging",
            "quality_issue": True,
        },
        {
            "text": "My refund has not arrived.",
            "sentiment": "negative",
            "category": "refund_issue",
            "severity": "medium",
            "topic": "refund",
            "quality_issue": False,
        },
        {
            "text": "I received the wrong product.",
            "sentiment": "negative",
            "category": "wrong_product",
            "severity": "medium",
            "topic": "fulfillment",
            "quality_issue": False,
        },
        {
            "text": "The item is missing from my order.",
            "sentiment": "negative",
            "category": "missing_product",
            "severity": "high",
            "topic": "fulfillment",
            "quality_issue": False,
        },
        {
            "text": "The product was contaminated.",
            "sentiment": "negative",
            "category": "contamination",
            "severity": "critical",
            "topic": "safety",
            "quality_issue": True,
        },
        {
            "text": "An unauthorized payment was made.",
            "sentiment": "negative",
            "category": "fraud_security",
            "severity": "critical",
            "topic": "security",
            "quality_issue": False,
        },
        {
            "text": "The product caused an injury.",
            "sentiment": "negative",
            "category": "safety_issue",
            "severity": "critical",
            "topic": "safety",
            "quality_issue": True,
        },
        {
            "text": "The product is too expensive.",
            "sentiment": "negative",
            "category": "pricing",
            "severity": "low",
            "topic": "pricing",
            "quality_issue": False,
        },
        {
            "text": "Customer support was rude.",
            "sentiment": "negative",
            "category": "customer_support",
            "severity": "medium",
            "topic": "support",
            "quality_issue": False,
        },
    ]

    def __init__(
        self,
        seed: int = 42,
    ):
        self.random = random.Random(seed)

    def generate(
        self,
        n_records: int = 1000,
        duplicate_rate: float = 0.08,
        start_date: str = "2026-01-01",
    ) -> list[dict]:
        if (
            isinstance(n_records, bool)
            or not isinstance(n_records, int)
            or n_records < 1
        ):
            raise ValueError(
                "n_records must be positive"
            )

        if not 0 <= duplicate_rate < 1:
            raise ValueError(
                "duplicate_rate must be in [0, 1)"
            )

        start = datetime.fromisoformat(
            start_date
        ).replace(tzinfo=timezone.utc)

        records = []
        duplicate_count = int(
            n_records * duplicate_rate
        )

        for index in range(n_records):
            if (
                index >= n_records - duplicate_count
                and records
            ):
                original = self.random.choice(
                    records[:n_records - duplicate_count]
                )

                record = {
                    **original,
                    "feedback_id": (
                        f"FB{index + 1:06d}"
                    ),
                    "duplicate_of": original[
                        "feedback_id"
                    ],
                    "created_at": (
                        start
                        + timedelta(
                            days=self.random.randint(
                                0, 180
                            )
                        )
                    ).isoformat(),
                }
            else:
                template = self.random.choice(
                    self.TEMPLATES
                )

                customer_number = (
                    self.random.randint(1, 200)
                )

                order_number = (
                    self.random.randint(1, 500)
                )

                record = {
                    "feedback_id": (
                        f"FB{index + 1:06d}"
                    ),
                    "customer_id": (
                        f"CUST{customer_number:05d}"
                    ),
                    "order_id": (
                        f"ORD{order_number:06d}"
                    ),
                    "product_id": (
                        f"SKU{self.random.randint(1, 100):04d}"
                    ),
                    **template,
                    "duplicate_of": None,
                    "created_at": (
                        start
                        + timedelta(
                            days=self.random.randint(
                                0, 180
                            )
                        )
                    ).isoformat(),
                }

            records.append(record)

        return records

    @staticmethod
    def save_json(
        records: list[dict],
        path: str,
    ) -> None:
        output = Path(path)
        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            json.dumps(
                records,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def save_csv(
        records: list[dict],
        path: str,
    ) -> None:
        if not records:
            raise ValueError(
                "Cannot export empty dataset"
            )

        output = Path(path)
        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with output.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=list(records[0]),
            )

            writer.writeheader()
            writer.writerows(records)


if __name__ == "__main__":
    generator = FeedbackDatasetGenerator(
        seed=42
    )

    dataset = generator.generate(
        n_records=1000,
        duplicate_rate=0.08,
    )

    generator.save_csv(
        dataset,
        "data/synthetic/feedback_dataset.csv",
    )

    generator.save_json(
        dataset,
        "data/synthetic/feedback_dataset.json",
    )

    print(
        f"Generated {len(dataset)} "
        "synthetic feedback records"
    )
