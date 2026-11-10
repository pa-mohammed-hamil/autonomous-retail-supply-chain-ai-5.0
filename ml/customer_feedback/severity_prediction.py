"""Planned module: severity prediction. Implementation pending."""

"""
ai/feedback/severity_prediction.py

Retail Complaint Severity Prediction

Features:
- Low / medium / high / critical
- Rule-based risk scoring
- Fraud and safety escalation
- Operational impact assessment
- Optional order value
- Human review recommendations
- Batch prediction
- CSV input
- JSON output

Severity scores are heuristics,
not calibrated probabilities.

High-risk decisions require
human verification.
"""

from __future__ import annotations

import csv
import json
import math
import re

from collections import Counter
from pathlib import Path
from typing import Sequence


class SeverityPredictor:

    RISK_PATTERNS = {
        "safety": {
            "patterns": [
                r"\binjury\b",
                r"\binjured\b",
                r"\belectric shock\b",
                r"\bfire hazard\b",
                r"\bcontaminated\b",
                r"\bunsafe\b",
                r"\btoxic\b",
            ],
            "score": 90,
        },
        "fraud_security": {
            "patterns": [
                r"\bfraud\b",
                r"\bscam\b",
                r"\bunauthorized\b",
                r"\baccount hacked\b",
                r"\bstolen payment\b",
                r"\bidentity theft\b",
            ],
            "score": 90,
        },
        "payment": {
            "patterns": [
                r"\bcharged twice\b",
                r"\bdouble charged\b",
                r"\bwrong charge\b",
                r"\bpayment failed\b",
                r"\bdebited\b",
            ],
            "score": 60,
        },
        "product_defect": {
            "patterns": [
                r"\bdefective\b",
                r"\bbroken\b",
                r"\bdamaged\b",
                r"\bfaulty\b",
                r"\bnot working\b",
            ],
            "score": 55,
        },
        "missing_order": {
            "patterns": [
                r"\bmissing order\b",
                r"\bmissing item\b",
                r"\border lost\b",
                r"\bnever delivered\b",
            ],
            "score": 50,
        },
        "refund": {
            "patterns": [
                r"\brefund\b",
                r"\breimbursement\b",
                r"\breturn rejected\b",
            ],
            "score": 40,
        },
        "delivery": {
            "patterns": [
                r"\bdelivery delayed\b",
                r"\blate delivery\b",
                r"\barrived late\b",
                r"\bshipment delayed\b",
            ],
            "score": 35,
        },
        "support": {
            "patterns": [
                r"\brude support\b",
                r"\bpoor service\b",
                r"\bunhelpful agent\b",
            ],
            "score": 25,
        },
    }

    SEVERITY_ORDER = {
        "unknown": 0,
        "low": 1,
        "medium": 2,
        "high": 3,
        "critical": 4,
    }

    @staticmethod
    def _number(
        value,
        field: str,
    ) -> float:
        if isinstance(value, bool):
            raise ValueError(
                f"Invalid {field}"
            )

        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid {field}"
            ) from exc

        if (
            not math.isfinite(result)
            or result < 0
        ):
            raise ValueError(
                f"{field} must be nonnegative"
            )

        return result

    @staticmethod
    def _severity(score: int) -> str:
        if score >= 80:
            return "critical"
        if score >= 55:
            return "high"
        if score >= 30:
            return "medium"
        if score > 0:
            return "low"
        return "unknown"

    @classmethod
    def predict(
        cls,
        text: str,
        order_value: float = 0.0,
        repeat_count: int = 0,
    ) -> dict:
        if not isinstance(text, str):
            raise TypeError(
                "Complaint text must be a string"
            )

        if not text.strip():
            raise ValueError(
                "Complaint text cannot be empty"
            )

        order_value = cls._number(
            order_value, "order_value"
        )

        if (
            isinstance(repeat_count, bool)
            or not isinstance(repeat_count, int)
            or repeat_count < 0
        ):
            raise ValueError(
                "repeat_count must be a "
                "nonnegative integer"
            )

        matched_categories = {}
        normalized = text.lower()

        for category, config in (
            cls.RISK_PATTERNS.items()
        ):
            matches = []

            for pattern in config["patterns"]:
                matches.extend(
                    re.findall(
                        pattern,
                        normalized,
                    )
                )

            if matches:
                matched_categories[category] = {
                    "matched_terms": sorted(
                        set(matches)
                    ),
                    "base_score": (
                        config["score"]
                    ),
                }

        base_score = max(
            (
                data["base_score"]
                for data in matched_categories.values()
            ),
            default=0,
        )

        # Optional impact adjustments.
        repeat_adjustment = min(
            repeat_count * 5,
            15,
        )

        if order_value >= 100000:
            value_adjustment = 15
        elif order_value >= 25000:
            value_adjustment = 10
        elif order_value >= 5000:
            value_adjustment = 5
        else:
            value_adjustment = 0

        # Unknown complaints stay unknown:
        # monetary value alone does not
        # establish an incident.
        if not matched_categories:
            score = 0
        else:
            score = min(
                100,
                base_score
                + repeat_adjustment
                + value_adjustment,
            )

        severity = cls._severity(score)

        urgent_categories = {
            "safety",
            "fraud_security",
        }

        urgent = bool(
            urgent_categories
            & set(matched_categories)
        )

        requires_human_review = (
            severity in {"high", "critical"}
            or urgent
        )

        if urgent:
            action = (
                "Urgent human review by the "
                "relevant safety or security team."
            )
        elif severity == "high":
            action = (
                "Escalate to senior customer "
                "support or operations."
            )
        elif severity == "medium":
            action = (
                "Create a priority support ticket."
            )
        elif severity == "low":
            action = (
                "Route to the standard support queue."
            )
        else:
            action = (
                "Request clarification or "
                "manual classification."
            )

        return {
            "text": text,
            "matched_categories": (
                matched_categories
            ),
            "base_risk_score": base_score,
            "repeat_adjustment": (
                repeat_adjustment
                if matched_categories else 0
            ),
            "order_value_adjustment": (
                value_adjustment
                if matched_categories else 0
            ),
            "risk_score": score,
            "severity": severity,
            "urgent": urgent,
            "requires_human_review": (
                requires_human_review
            ),
            "recommended_action": action,
            "prediction_method": (
                "rule_based_risk_scoring"
            ),
        }

    @classmethod
    def predict_batch(
        cls,
        records: Sequence[dict],
    ) -> dict:
        if not records:
            raise ValueError(
                "Empty complaint dataset"
            )

        results = []

        for record in records:
            results.append(
                cls.predict(
                    text=record["text"],
                    order_value=record.get(
                        "order_value", 0
                    ),
                    repeat_count=record.get(
                        "repeat_count", 0
                    ),
                )
            )

        distribution = Counter(
            result["severity"]
            for result in results
        )

        return {
            "total_complaints": len(results),
            "severity_distribution": dict(
                distribution
            ),
            "urgent_cases": sum(
                result["urgent"]
                for result in results
            ),
            "human_review_cases": sum(
                result["requires_human_review"]
                for result in results
            ),
            "results": results,
        }

    @classmethod
    def predict_csv(
        cls,
        path: str,
        text_column: str = "text",
    ) -> dict:
        with open(
            path,
            newline="",
            encoding="utf-8-sig",
        ) as file:
            rows = list(csv.DictReader(file))

        records = []

        for row in rows:
            records.append({
                "text": row[text_column],
                "order_value": (
                    row.get("order_value") or 0
                ),
                "repeat_count": int(
                    row.get("repeat_count") or 0
                ),
            })

        return cls.predict_batch(records)

    @staticmethod
    def save_report(
        report: dict,
        output_path: str,
    ) -> None:
        path = Path(output_path)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            json.dumps(
                report,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    complaints = [
        {
            "text": "The delivery was delayed.",
            "order_value": 1500,
            "repeat_count": 0,
        },
        {
            "text": "The product arrived broken.",
            "order_value": 8000,
            "repeat_count": 2,
        },
        {
            "text": "An unauthorized payment occurred.",
            "order_value": 12000,
            "repeat_count": 1,
        },
        {
            "text": "The product caused an injury.",
            "order_value": 2000,
            "repeat_count": 0,
        },
    ]

    report = SeverityPredictor.predict_batch(
        complaints
    )

    print(json.dumps(report, indent=2))
