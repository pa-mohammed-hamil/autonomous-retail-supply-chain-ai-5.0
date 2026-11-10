"""Planned module: shelf detector. Implementation pending."""

"""
ai/computer_vision/shelf_detector.py

Autonomous Retail Supply Chain AI 5.0

YOLO-based retail shelf intelligence.

Features:
- Product detection and counting
- Shelf-region filtering
- Visible stock thresholds
- Empty shelf alerts
- Shelf occupancy estimation
- Annotated image output

Requires a trained YOLO detection model.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
import math

from ultralytics import YOLO


class ShelfDetector:

    def __init__(
        self,
        model_path: str,
        confidence: float = 0.40,
        iou: float = 0.50,
        max_detections: int = 300,
    ):
        path = Path(model_path)

        if not path.is_file():
            raise FileNotFoundError(path)

        for name, value in (
            ("confidence", confidence),
            ("iou", iou),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 1
            ):
                raise ValueError(
                    f"{name} must be between 0 and 1"
                )

        if (
            isinstance(max_detections, bool)
            or not isinstance(max_detections, int)
            or max_detections <= 0
        ):
            raise ValueError("Invalid max_detections")

        # Use trusted model checkpoints only.
        self.model = YOLO(str(path))
        self.confidence = confidence
        self.iou = iou
        self.max_detections = max_detections

    @staticmethod
    def _intersection_area(a, b) -> float:
        x1 = max(a[0], b[0])
        y1 = max(a[1], b[1])
        x2 = min(a[2], b[2])
        y2 = min(a[3], b[3])

        return max(0, x2 - x1) * max(0, y2 - y1)

    @staticmethod
    def _union_area(boxes: list[list[float]]) -> float:
        """Calculate union area without double-counting overlap."""
        if not boxes:
            return 0.0

        xs = sorted({
            x for box in boxes for x in (box[0], box[2])
        })

        area = 0.0

        for left, right in zip(xs, xs[1:]):
            if right <= left:
                continue

            intervals = [
                (box[1], box[3])
                for box in boxes
                if box[0] < right and box[2] > left
            ]

            intervals.sort()

            merged_length = 0.0
            start = end = None

            for low, high in intervals:
                if start is None:
                    start, end = low, high
                elif low <= end:
                    end = max(end, high)
                else:
                    merged_length += end - start
                    start, end = low, high

            if start is not None:
                merged_length += end - start

            area += (right - left) * merged_length

        return area

    def detect(
        self,
        image_path: str,
        shelf_region: list[int] | None = None,
        minimum_visible_stock: dict[str, int] | None = None,
        empty_shelf_threshold_percent: float = 5.0,
        save_annotated: bool = False,
        output_dir: str = "outputs/shelf_detection",
    ) -> dict[str, Any]:

        path = Path(image_path)

        if not path.is_file():
            raise FileNotFoundError(path)

        if (
            isinstance(empty_shelf_threshold_percent, bool)
            or not isinstance(
                empty_shelf_threshold_percent,
                (int, float),
            )
            or not math.isfinite(
                empty_shelf_threshold_percent
            )
            or not 0 <= empty_shelf_threshold_percent <= 100
        ):
            raise ValueError("Invalid empty shelf threshold")

        thresholds = (
            minimum_visible_stock
            if minimum_visible_stock is not None
            else {}
        )

        if not isinstance(thresholds, dict):
            raise ValueError("Invalid stock thresholds")

        for label, count in thresholds.items():
            if (
                not isinstance(label, str)
                or not label.strip()
                or isinstance(count, bool)
                or not isinstance(count, int)
                or count < 0
            ):
                raise ValueError("Invalid stock threshold")

        results = self.model.predict(
            source=str(path),
            conf=self.confidence,
            iou=self.iou,
            max_det=self.max_detections,
            verbose=False,
        )

        if len(results) != 1:
            raise RuntimeError("Expected one image")

        result = results[0]
        height, width = result.orig_shape

        if shelf_region is None:
            region = [0, 0, width, height]
        else:
            if (
                not isinstance(shelf_region, list)
                or len(shelf_region) != 4
                or any(
                    isinstance(v, bool)
                    or not isinstance(v, int)
                    for v in shelf_region
                )
            ):
                raise ValueError(
                    "shelf_region must be [x1,y1,x2,y2]"
                )

            x1, y1, x2, y2 = shelf_region

            if not (
                0 <= x1 < x2 <= width
                and 0 <= y1 < y2 <= height
            ):
                raise ValueError(
                    "Shelf region outside image"
                )

            region = shelf_region

        detections = []
        clipped_boxes = []

        for box in result.boxes:
            raw_box = [
                float(v)
                for v in box.xyxy[0].tolist()
            ]

            x1 = max(region[0], raw_box[0])
            y1 = max(region[1], raw_box[1])
            x2 = min(region[2], raw_box[2])
            y2 = min(region[3], raw_box[3])

            if x2 <= x1 or y2 <= y1:
                continue

            class_id = int(box.cls.item())
            label = result.names[class_id]

            clipped = [x1, y1, x2, y2]
            clipped_boxes.append(clipped)

            detections.append({
                "product_class": label,
                "confidence": round(
                    float(box.conf.item()), 4
                ),
                "bbox_xyxy": [
                    round(v, 2) for v in raw_box
                ],
            })

        counts = Counter(
            detection["product_class"]
            for detection in detections
        )

        region_area = (
            (region[2] - region[0])
            * (region[3] - region[1])
        )

        occupied_area = self._union_area(
            clipped_boxes
        )

        occupancy = (
            occupied_area / region_area * 100
        )

        alerts = []

        for label, minimum in thresholds.items():
            actual = counts.get(label, 0)

            if actual < minimum:
                alerts.append({
                    "product_class": label,
                    "visible_count": actual,
                    "minimum_visible_stock": minimum,
                    "estimated_shortfall": minimum - actual,
                })

        annotated_path = None

        if save_annotated:
            import cv2

            output = Path(output_dir)
            output.mkdir(
                parents=True, exist_ok=True
            )

            annotated_path = output / (
                path.stem + "_shelf.jpg"
            )

            annotated = result.plot()

            cv2.rectangle(
                annotated,
                (region[0], region[1]),
                (region[2], region[3]),
                (255, 255, 0),
                2,
            )

            if not cv2.imwrite(
                str(annotated_path),
                annotated,
            ):
                raise OSError(
                    "Could not save annotated image"
                )

        return {
            "image_path": str(path),
            "shelf_region_xyxy": region,
            "total_visible_products": len(detections),
            "product_counts": dict(counts),
            "shelf_occupancy_percent": round(
                occupancy, 2
            ),
            "empty_shelf_suspected": (
                occupancy
                <= empty_shelf_threshold_percent
            ),
            "replenishment_alerts": alerts,
            "detections": detections,
            "annotated_image": (
                str(annotated_path)
                if annotated_path else None
            ),
            "human_verification_required": True,
        }
