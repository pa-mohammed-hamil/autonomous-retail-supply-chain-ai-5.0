"""Planned module: complaint classifier. Implementation pending."""

"""
ai/feedback/complaint_classifier.py

Autonomous Retail Supply Chain AI 5.0

Customer Complaint Classifier

Features:
- Complaint category classification
- Multi-label category detection
- Severity estimation
- Priority scoring
- Escalation recommendations
- Batch classification
- CSV input
- JSON report export

Baseline: deterministic keyword rules.
Severity and priority are heuristic,
not calibrated probabilities.

Critical complaints should be routed
to human review rather than resolved
autonomously.
"""

from __future__ import annotations

import csv
import json
import re

from collections import Counter
from pathlib import Path
from typing import Sequence


class ComplaintClassifier:

    CATEGORIES = {
        "delivery_delay": {
            "late", "delayed", "delay",
            "shipping", "courier",
        },
        "damaged_product": {
            "damaged", "broken",
            "defective", "faulty",
        },
        "wrong_product": {
            "wrong", "incorrect",
            "different", "mismatch",
        },
        "missing_product": {
            "missing", "incomplete",
            "lost", "shortage",
        },
        "refund_issue": {
            "refund", "reimbursement",
            "moneyback", "return",
        },
        "payment_issue": {
            "payment", "charged",
            "billing", "transaction",
            "debited",
        },
        "customer_support": {
            "support", "service",
            "agent", "staff",
            "representative",
        },
        "inventory_issue": {
            "stock", "outofstock",
            "unavailable", "restock",
        },
        "packaging_issue": {
            "packaging", "package",
            "packing", "box",
        },
        "fraud_security": {
            "fraud", "scam",
            "unauthorized", "stolen",
            "hacked", "phishing",
        },
        "safety_issue": {
            "unsafe", "injury",
            "fire", "hazard",
            "dangerous", "contaminated",
        },
    }

    CRITICAL_TERMS = {
        "fraud", "scam", "unauthorized",
        "stolen", "hacked", "phishing",
        "injury", "fire", "hazard",
        "dangerous", "contaminated",
    }

    HIGH_TERMS = {
        "broken", "damaged",
        "defective", "missing",
        "lost", "charged",
        "debited",
    }

    MEDIUM_TERMS = {
        "late", "delayed", "delay",
        "wrong", "refund",
        "unavailable", "incorrect",
    }

    CATEGORY_WEIGHTS = {
        "fraud_security": 40,
        "safety_issue": 40,
        "payment_issue": 20,
        "damaged_product": 15,
        "missing_product": 15,
        "wrong_product": 10,
        "refund_issue": 10,
        "delivery_delay": 5,
        "inventory_issue": 5,
        "customer_support": 5,
        "packaging_issue": 5,
    }

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return set(
            re.findall(
                r"[a-z0-9]+",
                text.lower(),
            )
        )

    @classmethod
    def classify(
        cls,
        text: str,
    ) -> dict:
        if not isinstance(text, str):
            raise TypeError(
                "Complaint must be a string"
            )

        if not text.strip():
            raise ValueError(
                "Complaint cannot be empty"
            )

        tokens = cls._tokens(text)

        category_matches = {}

        for category, keywords in (
            cls.CATEGORIES.items()
        ):
            matches = sorted(
                tokens & keywords
            )

            if matches:
                category_matches[category] = matches

        categories = sorted(
            category_matches,
            key=lambda category: (
                -cls.CATEGORY_WEIGHTS.get(
                    category, 0
                ),
                category,
            ),
        )

        if tokens & cls.CRITICAL_TERMS:
            severity = "critical"
            base_priority = 80

        elif tokens & cls.HIGH_TERMS:
            severity = "high"
            base_priority = 60

        elif tokens & cls.MEDIUM_TERMS:
            severity = "medium"
            base_priority = 40

        elif categories:
            severity = "low"
            base_priority = 20

        else:
            severity = "unknown"
            base_priority = 0

        # Category risk is added to the base.
        category_risk = max(
            (
                cls.CATEGORY_WEIGHTS.get(
                    category, 0
                )
                for category in categories
            ),
            default=0,
        )

        priority_score = min(
            100,
            base_priority + category_risk,
        )

        requires_escalation = (
            severity in {"high", "critical"}
            or "fraud_security" in categories
            or "safety_issue" in categories
        )

        if severity == "critical":
            recommended_action = (
                "Urgent human review; follow "
                "the relevant safety or "
                "security incident procedure."
            )
        elif severity == "high":
            recommended_action = (
                "Escalate to customer support "
                "or the responsible operations team."
            )
        elif severity == "medium":
            recommended_action = (
                "Create a support ticket "
                "and request investigation."
            )
        elif severity == "low":
            recommended_action = (
                "Route to standard support queue."
            )
        else:
            recommended_action = (
                "Request clarification or "
                "manual classification."
            )

        return {
            "text": text,
            "primary_category": (
                categories[0]
                if categories else "unknown"
            ),
            "categories": categories,
            "matched_keywords": (
                category_matches
            ),
            "severity": severity,
            "priority_score": priority_score,
            "requires_escalation": (
                requires_escalation
            ),
            "recommended_action": (
                recommended_action
            ),
            "classification_method": (
                "rule_based_baseline"
            ),
        }

    @classmethod
    def classify_batch(
        cls,
        complaints: Sequence[str],
    ) -> dict:
        if not complaints:
            raise ValueError(
                "Empty complaint dataset"
            )

        results = [
            cls.classify(text)
            for text in complaints
        ]

        severity_counts = Counter(
            result["severity"]
            for result in results
        )

        category_counts = Counter()

        for result in results:
            category_counts.update(
                result["categories"]
            )

        return {
            "total_complaints": len(results),
            "severity_distribution": dict(
                severity_counts
            ),
            "category_distribution": dict(
                category_counts
            ),
            "escalation_required": sum(
                result["requires_escalation"]
                for result in results
            ),
            "results": results,
        }

    @classmethod
    def classify_csv(
        cls,
        path: str,
        text_column: str = "complaint",
    ) -> dict:
        with open(
            path,
            newline="",
            encoding="utf-8-sig",
        ) as file:
            rows = list(csv.DictReader(file))

        complaints = [
            row[text_column]
            for row in rows
        ]

        return cls.classify_batch(
            complaints
        )

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
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    complaints = [
        "My order was delayed by three days.",
        "The product arrived broken and damaged.",
        "I was charged twice for my payment.",
        "Someone made an unauthorized transaction.",
        "The product is unsafe and caused an injury.",
    ]

    classifier = ComplaintClassifier()

    report = classifier.classify_batch(
        complaints
    )

    print(json.dumps(report, indent=2))
