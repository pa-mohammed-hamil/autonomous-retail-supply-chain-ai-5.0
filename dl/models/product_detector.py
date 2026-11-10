"""Planned module: product detector. Implementation pending."""

"""
Retail product detection and counting.

Uses a trained YOLO object detection model.

Supports:
- Product bounding boxes
- SKU or category labels
- Visible product counts
- Shelf shortage warnings
- Annotated output images

Counts are image-visible estimates, not verified
inventory records.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from ultralytics import YOLO


class ProductDetector:

    def __init__(
        self,
        model_path: str,
        confidence: float = 0.40,
        iou: float = 0.50,
    ):
        path = Path(model_path)

        if not path.is_file():
            raise FileNotFoundError(path)

        if not 0 <= confidence <= 1:
            raise ValueError("Invalid confidence")

        if not 0 <= iou <= 1:
            raise ValueError("Invalid IoU threshold")

        self.model = YOLO(str(path))
        self.confidence = confidence
        self.iou = iou

    def detect(
        self,
        image_path: str,
        minimum_visible_stock: dict[str, int] | None = None,
        save_annotated: bool = False,
        output_dir: str = "outputs/product_detection",
    ) -> dict[str, Any]:

        path = Path(image_path)

        if not path.is_file():
            raise FileNotFoundError(path)

        thresholds = minimum_visible_stock or {}

        if not isinstance(thresholds, dict):
            raise ValueError(
                "minimum_visible_stock must be a dictionary"
            )

        for label, quantity in thresholds.items():
            if (
                not isinstance(label, str)
                or not label.strip()
                or isinstance(quantity, bool)
                or not isinstance(quantity, int)
                or quantity < 0
            ):
                raise ValueError(
                    "Invalid minimum stock threshold"
                )

        results = self.model.predict(
            source=str(path),
            conf=self.confidence,
            iou=self.iou,
            verbose=False,
        )

        if len(results) != 1:
            raise RuntimeError(
                "Expected one image result"
            )

        result = results[0]
        detections = []

        for box in result.boxes:
            class_id = int(box.cls.item())
            label = result.names[class_id]

            x1, y1, x2, y2 = (
                float(value)
                for value in box.xyxy[0].tolist()
            )

            detections.append({
                "product_class": label,
                "confidence": round(
                    float(box.conf.item()), 4
                ),
                "bbox_xyxy": [
                    round(x1, 2),
                    round(y1, 2),
                    round(x2, 2),
                    round(y2, 2),
                ],
            })

        counts = Counter(
            item["product_class"]
            for item in detections
        )

        low_stock_alerts = []

        for label, minimum in thresholds.items():
            visible_count = counts.get(label, 0)

            if visible_count < minimum:
                low_stock_alerts.append({
                    "product_class": label,
                    "visible_count": visible_count,
                    "minimum_visible_stock": minimum,
                    "estimated_shortfall": (
                        minimum - visible_count
                    ),
                })

        annotated_path = None

        if save_annotated:
            import cv2

            destination = Path(output_dir)
            destination.mkdir(
                parents=True,
                exist_ok=True,
            )

            annotated_path = destination / (
                path.stem + "_products.jpg"
            )

            if not cv2.imwrite(
                str(annotated_path),
                result.plot(),
            ):
                raise OSError(
                    "Could not save annotated image"
                )

        return {
            "image": str(path),
            "total_visible_detections": len(detections),
            "product_counts": dict(counts),
            "detections": detections,
            "low_visible_stock_alerts": low_stock_alerts,
            "annotated_image": (
                str(annotated_path)
                if annotated_path else None
            ),
            "inventory_verification_required": True,
        }

    def detect_batch(
        self,
        image_paths: list[str],
        minimum_visible_stock: dict[str, int] | None = None,
    ) -> list[dict]:

        if not isinstance(image_paths, list):
            raise ValueError(
                "image_paths must be a list"
            )

        if len(image_paths) > 100:
            raise ValueError(
                "Maximum 100 images per batch"
            )

        return [
            self.detect(
                image_path=image_path,
                minimum_visible_stock=minimum_visible_stock,
            )
            for image_path in image_paths
        ]
