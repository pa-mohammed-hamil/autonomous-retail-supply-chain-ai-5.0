"""Planned module: empty shelf detection. Implementation pending."""

"""
ai/computer_vision/empty_shelf_detection.py

Estimate visible shelf occupancy from product detections.

Input detections:
[
    {
        "class_name": "bottled_water",
        "confidence": 0.92,
        "bbox": [x1, y1, x2, y2]
    }
]

Important:
Bounding-box coverage is only a visual proxy.
It is NOT actual shelf capacity or inventory.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any


class EmptyShelfDetector:

    def __init__(
        self,
        empty_threshold_percent: float = 5.0,
        low_stock_threshold_percent: float = 25.0,
        min_confidence: float = 0.40,
    ):
        if not (
            0 <= empty_threshold_percent
            < low_stock_threshold_percent
            <= 100
        ):
            raise ValueError(
                "Require 0 <= empty threshold "
                "< low stock threshold <= 100"
            )

        if not 0 <= min_confidence <= 1:
            raise ValueError("Invalid confidence threshold")

        self.empty_threshold = float(
            empty_threshold_percent
        )
        self.low_stock_threshold = float(
            low_stock_threshold_percent
        )
        self.min_confidence = float(min_confidence)

    @staticmethod
    def _validate_region(
        region: list[float],
    ) -> tuple[float, float, float, float]:
        if (
            not isinstance(region, (list, tuple))
            or len(region) != 4
            or any(
                isinstance(v, bool)
                or not isinstance(v, (int, float))
                or not math.isfinite(v)
                for v in region
            )
        ):
            raise ValueError("Invalid shelf region")

        x1, y1, x2, y2 = map(float, region)

        if x2 <= x1 or y2 <= y1:
            raise ValueError(
                "Shelf region must have positive area"
            )

        return x1, y1, x2, y2

    @staticmethod
    def _union_area(
        boxes: list[tuple[float, float, float, float]],
    ) -> float:
        """
        Exact union area of axis-aligned rectangles.
        Prevents double-counting overlapping boxes.
        """
        if not boxes:
            return 0.0

        x_edges = sorted({
            x
            for x1, _, x2, _ in boxes
            for x in (x1, x2)
        })

        area = 0.0

        for left, right in zip(
            x_edges[:-1], x_edges[1:]
        ):
            if right <= left:
                continue

            intervals = [
                (y1, y2)
                for x1, y1, x2, y2 in boxes
                if x1 < right and x2 > left
            ]

            if not intervals:
                continue

            intervals.sort()
            start, end = intervals[0]
            covered_y = 0.0

            for y1, y2 in intervals[1:]:
                if y1 > end:
                    covered_y += end - start
                    start, end = y1, y2
                else:
                    end = max(end, y2)

            covered_y += end - start
            area += (right - left) * covered_y

        return area

    def analyze(
        self,
        detections: list[dict[str, Any]],
        shelf_regions: list[dict[str, Any]],
    ) -> dict[str, Any]:

        if not isinstance(detections, list):
            raise ValueError("Detections must be a list")

        if not isinstance(shelf_regions, list):
            raise ValueError("Shelf regions must be a list")

        results = []
        seen_region_ids = set()

        for shelf in shelf_regions:
            if not isinstance(shelf, dict):
                raise ValueError("Invalid shelf entry")

            region_id = shelf.get("region_id")
            region = shelf.get("bbox")

            if (
                not isinstance(region_id, str)
                or not region_id
                or region_id in seen_region_ids
            ):
                raise ValueError(
                    "Shelf region IDs must be unique"
                )

            seen_region_ids.add(region_id)

            sx1, sy1, sx2, sy2 = (
                self._validate_region(region)
            )

            clipped_boxes = []
            product_counts = Counter()

            for detection in detections:
                if not isinstance(detection, dict):
                    raise ValueError("Invalid detection")

                confidence = detection.get(
                    "confidence", 0.0
                )

                if (
                    not isinstance(confidence, (int, float))
                    or isinstance(confidence, bool)
                    or not math.isfinite(confidence)
                    or not 0 <= confidence <= 1
                ):
                    raise ValueError(
                        "Invalid detection confidence"
                    )

                if confidence < self.min_confidence:
                    continue

                label = detection.get(
                    "class_name",
                    detection.get("class"),
                )

                if not isinstance(label, str) or not label:
                    raise ValueError(
                        "Invalid detection class"
                    )

                x1, y1, x2, y2 = (
                    self._validate_region(
                        detection.get("bbox")
                    )
                )

                cx1 = max(sx1, x1)
                cy1 = max(sy1, y1)
                cx2 = min(sx2, x2)
                cy2 = min(sy2, y2)

                if cx2 <= cx1 or cy2 <= cy1:
                    continue

                clipped_boxes.append(
                    (cx1, cy1, cx2, cy2)
                )

                product_counts[label] += 1

            shelf_area = (
                (sx2 - sx1) * (sy2 - sy1)
            )

            covered_area = self._union_area(
                clipped_boxes
            )

            occupancy = min(
                100.0,
                covered_area / shelf_area * 100,
            )

            if occupancy <= self.empty_threshold:
                status = "suspected_empty"
            elif occupancy <= self.low_stock_threshold:
                status = "suspected_low_stock"
            else:
                status = "visually_occupied"

            results.append({
                "region_id": region_id,
                "status": status,
                "occupancy_percent": round(
                    occupancy, 2
                ),
                "uncovered_percent": round(
                    100 - occupancy, 2
                ),
                "visible_product_detections": (
                    len(clipped_boxes)
                ),
                "product_counts": dict(
                    product_counts
                ),
                "replenishment_review_recommended": (
                    status != "visually_occupied"
                ),
                "human_verification_required": True,
            })

        return {
            "shelves_analyzed": len(results),
            "suspected_empty_count": sum(
                item["status"] == "suspected_empty"
                for item in results
            ),
            "suspected_low_stock_count": sum(
                item["status"] == "suspected_low_stock"
                for item in results
            ),
            "shelves": results,
            "measurement_type": (
                "product bounding-box coverage proxy"
            ),
            "inventory_quantity_verified": False,
        }
