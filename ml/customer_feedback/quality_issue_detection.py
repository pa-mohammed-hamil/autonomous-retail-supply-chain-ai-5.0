"""Planned module: quality issue detection. Implementation pending."""

"""
ai/feedback/quality_issue_detection.py

Autonomous Retail Supply Chain AI 5.0

Product Quality Issue Detection

Features:
- Damaged product detection
- Manufacturing defect detection
- Expired product detection
- Contamination detection
- Packaging issues
- Incorrect product detection
- Missing component detection
- Safety concern detection
- Severity classification
- Human-review recommendations
- Batch processing
- CSV/JSON reporting

Baseline: rule-based text classification.

Not a certified product safety system.
High-risk cases require human review.
"""

from __future__ import annotations

import csv
import json
import re

from collections import Counter
from pathlib import Path
from typing import Sequence


class QualityIssueDetector:

    ISSUE_PATTERNS = {
        "physical_damage": [
            r"\bbroken\b",
            r"\bcracked\b",
            r"\bdamaged\b",
            r"\bscratched\b",
            r"\bdented\b",
            r"\bshattered\b",
        ],
        "manufacturing_defect": [
            r"\bdefective\b",
            r"\bfaulty\b",
            r"\bmanufacturing defect\b",
            r"\bnot working\b",
            r"\bmalfunction(?:ing)?\b",
        ],
        "expired_product": [
            r"\bexpired\b",
            r"\bpast expiry\b",
            r"\bpast expiration\b",
            r"\bout of date\b",
        ],
        "contamination": [
            r"\bcontaminated\b",
            r"\bcontamination\b",
            r"\bmold\b",
            r"\bmould\b",
            r"\bforeign object\b",
            r"\binsect\b",
        ],
        "packaging_defect": [
            r"\bpackaging damaged\b",
            r"\bpackage torn\b",
            r"\bseal broken\b",
            r"\bleaking package\b",
            r"\bpoor packaging\b",
        ],
        "wrong_product": [
            r"\bwrong product\b",
            r"\bwrong item\b",
            r"\bincorrect product\b",
            r"\bincorrect item\b",
        ],
        "missing_component": [
            r"\bmissing part\b",
            r"\bmissing component\b",
            r"\bmissing accessory\b",
            r"\bincomplete product\b",
        ],
        "safety_concern": [
            r"\bunsafe\b",
            r"\belectric shock\b",
            r"\bfire hazard\b",
            r"\bcaused injury\b",
            r"\bburn(?:ed|t)?\b",
            r"\btoxic\b",
        ],
    }

    SEVERITY_LEVELS = {
        "physical_damage": "medium",
        "manufacturing_defect": "high",
        "expired_product": "high",
        "contamination": "critical",
        "packaging_defect": "medium",
        "wrong_product": "medium",
        "missing_component": "medium",
        "safety_concern": "critical",
    }

    SEVERITY_RANK = {
        "none": 0,
        "low": 1,
        "medium": 2,
        "high": 3,
        "critical": 4,
    }

    @classmethod
    def detect(
        cls,
        text: str,
        product_id: str | None = None,
    ) -> dict:
        if not isinstance(text, str):
            raise TypeError(
                "Text must be a string"
            )

        if not text.strip():
            raise ValueError(
                "Text cannot be empty"
            )

        normalized = text.lower()
        detected = {}

        for issue, patterns in (
            cls.ISSUE_PATTERNS.items()
        ):
            matches = []

            for pattern in patterns:
                found = re.findall(
                    pattern,
                    normalized,
                    flags=re.IGNORECASE,
                )

                matches.extend(found)

            if matches:
                detected[issue] = {
                    "matched_terms": sorted(
                        set(matches)
                    ),
                    "severity": (
                        cls.SEVERITY_LEVELS[issue]
                    ),
                }

        if detected:
            severity = max(
                (
                    item["severity"]
                    for item in detected.values()
                ),
                key=lambda value: (
                    cls.SEVERITY_RANK[value]
                ),
            )
        else:
            severity = "none"

        requires_human_review = (
            severity in {"high", "critical"}
        )

        if severity == "critical":
            action = (
                "Urgent human safety/quality review. "
                "Consider holding the affected batch "
                "under established procedures."
            )
        elif severity == "high":
            action = (
                "Create a high-priority quality "
                "investigation and inspect the product."
            )
        elif severity == "medium":
            action = (
                "Create a quality support ticket "
                "and request evidence if needed."
            )
        else:
            action = (
                "No keyword-based quality issue found; "
                "manual review may still be needed."
            )

        return {
            "product_id": product_id,
            "text": text,
            "quality_issue_detected": bool(
                detected
            ),
            "issue_count": len(detected),
            "issue_types": sorted(detected),
            "issue_details": detected,
            "severity": severity,
            "requires_human_review": (
                requires_human_review
            ),
            "recommended_action": action,
            "detection_method": (
                "rule_based_baseline"
            ),
        }

    @classmethod
    def detect_batch(
        cls,
        records: Sequence[dict],
    ) -> dict:
        if not records:
            raise ValueError(
                "Empty quality dataset"
            )

        results = []

        for record in records:
            results.append(
                cls.detect(
                    text=record["text"],
                    product_id=record.get(
                        "product_id"
                    ),
                )
            )

        issue_counts = Counter()
        severity_counts = Counter()

        for result in results:
            issue_counts.update(
                result["issue_types"]
            )
            severity_counts.update([
                result["severity"]
            ])

        return {
            "total_records": len(results),
            "records_with_quality_issues": sum(
                result["quality_issue_detected"]
                for result in results
            ),
            "records_requiring_human_review": sum(
                result["requires_human_review"]
                for result in results
            ),
            "issue_distribution": dict(
                issue_counts
            ),
            "severity_distribution": dict(
                severity_counts
            ),
            "results": results,
        }

    @classmethod
    def detect_csv(
        cls,
        path: str,
        text_column: str = "text",
        product_column: str = "product_id",
    ) -> dict:
        with open(
            path,
            newline="",
            encoding="utf-8-sig",
        ) as file:
            rows = list(csv.DictReader(file))

        records = [
            {
                "text": row[text_column],
                "product_id": row.get(
                    product_column
                ),
            }
            for row in rows
        ]

        return cls.detect_batch(records)

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
    feedback = [
        {
            "product_id": "SKU001",
            "text": (
                "The product arrived broken "
                "and scratched."
            ),
        },
        {
            "product_id": "SKU002",
            "text": (
                "The food package was "
                "contaminated with mold."
            ),
        },
        {
            "product_id": "SKU003",
            "text": (
                "The device is defective "
                "and not working."
            ),
        },
        {
            "product_id": "SKU004",
            "text": (
                "The product quality is excellent."
            ),
        },
    ]

    report = QualityIssueDetector.detect_batch(
        feedback
    )

    print(json.dumps(report, indent=2))
