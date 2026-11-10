"""Planned module: shelf stock detection. Implementation pending."""

"""
ai/computer_vision/shelf_stock_detection.py

Autonomous Retail Supply Chain AI 5.0

Shelf stock detection and replenishment intelligence.

Features:
- YOLO-based product detection
- Multiple shelf regions
- Visible product counts by class
- Product-to-SKU mapping
- Low-visible-stock alerts
- Empty shelf suspicion
- Planogram checks
- JSON reporting

Important:
Visible detections are NOT verified inventory.
A single image cannot reliably reveal products
hidden behind other products.
"""

from __future__ import annotations

import json
import math
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai.computer_vision.product_detection import (
    ProductDetection,
)

from ai.computer_vision.empty_shelf_detection import (
    EmptyShelfDetector,
)


class ShelfStockDetection:

    def __init__(
        self,
        model_path: str,
        confidence: float = 0.45,
        empty_threshold_percent: float = 5.0,
        low_coverage_threshold_percent: float = 25.0,
        sku_mapping: dict[str, str] | None = None,
        report_dir: str = "reports/shelf_stock",
    ):
        self.product_detector = ProductDetection(
            model_path=model_path,
            confidence=confidence,
            sku_mapping=sku_mapping,
        )

        self.empty_shelf_detector = EmptyShelfDetector(
            empty_threshold_percent=(
                empty_threshold_percent
            ),
            low_stock_threshold_percent=(
                low_coverage_threshold_percent
            ),
            min_confidence=confidence,
        )

        self.sku_mapping = sku_mapping or {}
        self.report_dir = Path(report_dir)

    @staticmethod
    def _validate_regions(
        regions: list[dict[str, Any]],
        image_width: int,
        image_height: int,
    ) -> None:

        if not isinstance(regions, list) or not regions:
            raise ValueError(
                "At least one shelf region is required"
            )

        ids = set()

        for region in regions:
            if not isinstance(region, dict):
                raise ValueError("Invalid shelf region")

            region_id = region.get("region_id")
            bbox = region.get("bbox")

            if (
                not isinstance(region_id, str)
                or not region_id
                or region_id in ids
            ):
                raise ValueError(
                    "Region IDs must be unique"
                )

            ids.add(region_id)

            if (
                not isinstance(bbox, (list, tuple))
                or len(bbox) != 4
                or any(
                    isinstance(v, bool)
                    or not isinstance(v, (int, float))
                    or not math.isfinite(v)
                    for v in bbox
                )
            ):
                raise ValueError(
                    f"Invalid bbox for {region_id}"
                )

            x1, y1, x2, y2 = bbox

            if not (
                0 <= x1 < x2 <= image_width
                and 0 <= y1 < y2 <= image_height
            ):
                raise ValueError(
                    f"Region {region_id} is outside image"
                )

            for field in ("minimum_visible_units",):
                if field in region:
                    value = region[field]

                    if (
                        isinstance(value, bool)
                        or not isinstance(value, int)
                        or value < 0
                    ):
                        raise ValueError(
                            f"Invalid {field}"
                        )

            expected_classes = region.get(
                "expected_classes", []
            )

            if (
                not isinstance(expected_classes, list)
                or any(
                    not isinstance(item, str)
                    or not item
                    for item in expected_classes
                )
            ):
                raise ValueError(
                    "Invalid expected_classes"
                )

    @staticmethod
    def _center_in_region(
        bbox: list[float],
        region: list[float],
    ) -> bool:

        x1, y1, x2, y2 = bbox
        rx1, ry1, rx2, ry2 = region

        center_x = (x1 + x2) / 2
        center_y = (y1 + y2) / 2

        return (
            rx1 <= center_x < rx2
            and ry1 <= center_y < ry2
        )

    def analyze(
        self,
        image_path: str,
        shelf_regions: list[dict[str, Any]],
        save_report: bool = False,
        report_name: str | None = None,
    ) -> dict[str, Any]:

        start = time.perf_counter()

        detection_result = (
            self.product_detector.detect(
                image_path=image_path
            )
        )

        image_width = detection_result[
            "image_size"
        ]["width"]

        image_height = detection_result[
            "image_size"
        ]["height"]

        self._validate_regions(
            shelf_regions,
            image_width,
            image_height,
        )

        detections = detection_result[
            "detections"
        ]

        # Bounding-box coverage is computed
        # independently by EmptyShelfDetector.
        occupancy_result = (
            self.empty_shelf_detector.analyze(
                detections=detections,
                shelf_regions=shelf_regions,
            )
        )

        occupancy_by_id = {
            item["region_id"]: item
            for item in occupancy_result["shelves"]
        }

        shelf_results = []
        alerts = []

        for region in shelf_regions:
            region_id = region["region_id"]
            region_bbox = region["bbox"]

            assigned_detections = [
                item
                for item in detections
                if self._center_in_region(
                    item["bbox"],
                    region_bbox,
                )
            ]

            class_counts = Counter(
                item["class_name"]
                for item in assigned_detections
            )

            sku_counts = Counter()

            for item in assigned_detections:
                sku = item.get("sku_candidate")

                if sku:
                    sku_counts[sku] += 1

            visible_count = len(
                assigned_detections
            )

            minimum_units = region.get(
                "minimum_visible_units"
            )

            expected_classes = set(
                region.get(
                    "expected_classes", []
                )
            )

            observed_classes = set(
                class_counts
            )

            missing_classes = sorted(
                expected_classes
                - observed_classes
            )

            unexpected_classes = sorted(
                observed_classes
                - expected_classes
            ) if expected_classes else []

            occupancy = occupancy_by_id[
                region_id
            ]

            coverage_status = occupancy[
                "status"
            ]

            below_visible_target = (
                minimum_units is not None
                and visible_count < minimum_units
            )

            suspected_empty = (
                coverage_status
                == "suspected_empty"
            )

            suspected_low_stock = (
                coverage_status
                == "suspected_low_stock"
                or below_visible_target
            )

            review_reasons = []

            if suspected_empty:
                review_reasons.append(
                    "Low product bounding-box coverage"
                )

            if below_visible_target:
                review_reasons.append(
                    "Visible detections below target"
                )

            if (
                coverage_status
                == "suspected_low_stock"
            ):
                review_reasons.append(
                    "Low visible shelf coverage"
                )

            if missing_classes:
                review_reasons.append(
                    "Expected product classes not visible"
                )

            if unexpected_classes:
                review_reasons.append(
                    "Unexpected product classes visible"
                )

            shelf_result = {
                "region_id": region_id,
                "visible_product_count": (
                    visible_count
                ),
                "visible_counts_by_class": dict(
                    class_counts
                ),
                "visible_counts_by_sku_candidate": (
                    dict(sku_counts)
                ),
                "occupancy_percent": occupancy[
                    "occupancy_percent"
                ],
                "coverage_status": (
                    coverage_status
                ),
                "minimum_visible_units": (
                    minimum_units
                ),
                "below_visible_target": (
                    below_visible_target
                ),
                "suspected_empty": (
                    suspected_empty
                ),
                "suspected_low_stock": (
                    suspected_low_stock
                ),
                "missing_expected_classes": (
                    missing_classes
                ),
                "unexpected_classes": (
                    unexpected_classes
                ),
                "review_required": bool(
                    review_reasons
                ),
                "review_reasons": review_reasons,
            }

            shelf_results.append(
                shelf_result
            )

            if review_reasons:
                alerts.append({
                    "region_id": region_id,
                    "type": (
                        "shelf_stock_review"
                    ),
                    "reasons": review_reasons,
                    "requires_human_review": True,
                })

        result = {
            "image_path": image_path,
            "timestamp_utc": (
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
            "shelves_analyzed": len(
                shelf_results
            ),
            "total_visible_detections": len(
                detections
            ),
            "shelves": shelf_results,
            "alerts": alerts,
            "processing_latency_ms": round(
                (
                    time.perf_counter()
                    - start
                ) * 1000,
                2,
            ),
            "inventory_quantity_verified": False,
            "automatic_replenishment_allowed": False,
        }

        if save_report:
            self.report_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

            if report_name is None:
                import uuid
                report_name = (
                    f"shelf_{uuid.uuid4().hex}.json"
                )

            # Only allow a simple JSON filename.
            import re

            if not re.fullmatch(
                r"[A-Za-z0-9_-]+\.json",
                report_name,
            ):
                raise ValueError(
                    "Invalid report filename"
                )

            destination = (
                self.report_dir / report_name
            )

            destination.write_text(
                json.dumps(
                    result,
                    indent=2,
                ),
                encoding="utf-8",
            )

            result["report_path"] = str(
                destination
            )

        return result
