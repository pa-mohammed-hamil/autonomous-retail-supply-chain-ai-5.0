"""Planned module: quality inspection. Implementation pending."""

"""
ai/computer_vision/quality_inspection.py

Retail package and product quality inspection.

Combines:
- Product detection
- Package damage detection
- Label OCR

Produces:
- Structured inspection report
- Damage findings
- Product identity candidates
- Label information
- Review reasons
- JSON report

No automatic rejection or inventory mutation.
"""

from __future__ import annotations

import json
import time
import uuid

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai.computer_vision.product_detection import (
    ProductDetection,
)

from ai.computer_vision.package_damage_detection import (
    PackageDamageDetection,
)

from ai.computer_vision.label_ocr import (
    LabelOCR,
)


class QualityInspection:

    def __init__(
        self,
        product_model_path: str,
        damage_model_path: str,
        enable_ocr: bool = True,
        confidence: float = 0.40,
        report_directory: str = (
            "reports/quality_inspections"
        ),
    ):
        self.product_detector = ProductDetection(
            model_path=product_model_path,
            confidence=confidence,
        )

        self.damage_detector = (
            PackageDamageDetection(
                model_path=damage_model_path,
                confidence=confidence,
            )
        )

        self.ocr = (
            LabelOCR()
            if enable_ocr
            else None
        )

        self.report_directory = Path(
            report_directory
        )

    @staticmethod
    def _run_stage(
        function,
    ) -> dict:
        start = time.perf_counter()

        try:
            result = function()

            return {
                "status": "completed",
                "latency_ms": round(
                    (
                        time.perf_counter()
                        - start
                    ) * 1000,
                    2,
                ),
                "result": result,
            }

        except Exception as exc:
            return {
                "status": "failed",
                "latency_ms": round(
                    (
                        time.perf_counter()
                        - start
                    ) * 1000,
                    2,
                ),
                "error_type": type(exc).__name__,
            }

    def inspect(
        self,
        image_path: str,
        tenant_id: str,
        expected_sku: str | None = None,
        save_report: bool = True,
    ) -> dict[str, Any]:

        path = Path(image_path)

        if not path.is_file():
            raise FileNotFoundError(path)

        if not tenant_id or not tenant_id.strip():
            raise ValueError(
                "tenant_id is required"
            )

        inspection_id = uuid.uuid4().hex

        stages = {
            "product_detection": self._run_stage(
                lambda: (
                    self.product_detector.detect(
                        str(path)
                    )
                )
            ),
            "damage_detection": self._run_stage(
                lambda: (
                    self.damage_detector.detect(
                        str(path)
                    )
                )
            ),
        }

        if self.ocr is not None:
            stages["label_ocr"] = self._run_stage(
                lambda: self.ocr.extract(
                    str(path)
                )
            )

        reasons = []

        product_stage = stages[
            "product_detection"
        ]

        damage_stage = stages[
            "damage_detection"
        ]

        if (
            product_stage["status"]
            == "completed"
        ):
            product_result = product_stage[
                "result"
            ]

            if (
                product_result[
                    "total_visible_detections"
                ] == 0
            ):
                reasons.append(
                    "No visible products detected"
                )

            if expected_sku is not None:
                candidate_skus = {
                    item["sku_candidate"]
                    for item in product_result[
                        "detections"
                    ]
                    if item.get(
                        "sku_candidate"
                    ) is not None
                }

                if expected_sku not in candidate_skus:
                    reasons.append(
                        "Expected SKU not confirmed "
                        "by product detection"
                    )

        if (
            damage_stage["status"]
            == "completed"
        ):
            damage_result = damage_stage[
                "result"
            ]

            if damage_result[
                "damage_detected"
            ]:
                reasons.append(
                    "Potential package damage detected"
                )

            if damage_result[
                "overall_severity"
            ] == "high":
                reasons.append(
                    "High-severity damage heuristic"
                )

        if self.ocr is not None:
            ocr_stage = stages["label_ocr"]

            if ocr_stage["status"] == "completed":
                if ocr_stage["result"][
                    "requires_review"
                ]:
                    reasons.append(
                        "Label OCR requires verification"
                    )

        failed_stages = [
            name
            for name, stage in stages.items()
            if stage["status"] == "failed"
        ]

        if failed_stages:
            reasons.append(
                "One or more inspection stages failed"
            )

        # This is an inspection recommendation,
        # not an automatic quality certification.
        review_required = bool(reasons)

        report = {
            "inspection_id": inspection_id,
            "tenant_id": tenant_id,
            "timestamp_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "image_path": str(path),
            "expected_sku": expected_sku,
            "stages": stages,
            "review_reasons": reasons,
            "review_required": review_required,
            "inspection_status": (
                "incomplete"
                if failed_stages
                else (
                    "review_required"
                    if review_required
                    else "no_issues_flagged"
                )
            ),
            "product_quality_verified": False,
            "automatic_rejection_allowed": False,
            "inventory_mutation_allowed": False,
        }

        if save_report:
            # Restrict tenant directory names to
            # prevent path traversal.
            import re

            if not re.fullmatch(
                r"[A-Za-z0-9_-]{1,64}",
                tenant_id,
            ):
                raise ValueError(
                    "Invalid tenant_id"
                )

            destination = (
                self.report_directory
                / tenant_id
                / f"{inspection_id}.json"
            )

            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            destination.write_text(
                json.dumps(
                    report,
                    indent=2,
                ),
                encoding="utf-8",
            )

            report["report_path"] = str(
                destination
            )

        return report
