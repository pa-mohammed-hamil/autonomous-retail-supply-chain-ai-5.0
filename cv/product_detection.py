"""Planned module: product detection. Implementation pending."""

"""
ai/computer_vision/product_detection.py

Retail product detection using custom YOLO.

Features:
- Product detection
- Bounding boxes
- Confidence scores
- Visible product counts
- Optional SKU mapping
- Annotated image output
- Batch image inference

Model classes must match the training dataset.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import cv2


class ProductDetection:

    def __init__(
        self,
        model_path: str,
        confidence: float = 0.40,
        iou: float = 0.50,
        image_size: int = 640,
        sku_mapping: dict[str, str] | None = None,
    ):
        if not Path(model_path).is_file():
            raise FileNotFoundError(model_path)

        if not 0 <= confidence <= 1:
            raise ValueError("Invalid confidence")

        if not 0 <= iou <= 1:
            raise ValueError("Invalid IoU")

        if (
            not isinstance(image_size, int)
            or image_size <= 0
        ):
            raise ValueError("Invalid image size")

        from ultralytics import YOLO

        # Load checkpoints only from trusted sources.
        self.model = YOLO(model_path)

        self.confidence = confidence
        self.iou = iou
        self.image_size = image_size
        self.sku_mapping = sku_mapping or {}

    def detect(
        self,
        image_path: str,
        save_annotated: bool = False,
        output_path: str | None = None,
    ) -> dict[str, Any]:

        path = Path(image_path)

        if not path.is_file():
            raise FileNotFoundError(path)

        image = cv2.imread(str(path))

        if image is None:
            raise ValueError(
                "Unable to decode image"
            )

        height, width = image.shape[:2]

        results = self.model.predict(
            source=image,
            conf=self.confidence,
            iou=self.iou,
            imgsz=self.image_size,
            verbose=False,
        )

        result = results[0]
        detections = []

        if result.boxes is not None:
            for box in result.boxes:
                class_id = int(
                    box.cls[0].item()
                )

                class_name = str(
                    result.names[class_id]
                )

                detections.append({
                    "class_id": class_id,
                    "class_name": class_name,
                    "sku_candidate": (
                        self.sku_mapping.get(
                            class_name
                        )
                    ),
                    "confidence": round(
                        float(
                            box.conf[0].item()
                        ),
                        4,
                    ),
                    "bbox": [
                        round(float(v), 2)
                        for v in (
                            box.xyxy[0]
                            .cpu()
                            .tolist()
                        )
                    ],
                })

        counts = dict(
            Counter(
                item["class_name"]
                for item in detections
            )
        )

        annotated_path = None

        if save_annotated:
            if not output_path:
                raise ValueError(
                    "output_path is required"
                )

            destination = Path(output_path)

            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            if not cv2.imwrite(
                str(destination),
                result.plot(),
            ):
                raise RuntimeError(
                    "Could not save annotated image"
                )

            annotated_path = str(destination)

        return {
            "image_path": str(path),
            "image_size": {
                "width": width,
                "height": height,
            },
            "total_visible_detections": len(
                detections
            ),
            "product_counts": counts,
            "detections": detections,
            "annotated_image": annotated_path,
            "sku_identity_verified": False,
            "inventory_quantity_verified": False,
        }

    def detect_batch(
        self,
        image_paths: list[str],
        max_images: int = 100,
    ) -> list[dict]:
        if len(image_paths) > max_images:
            raise ValueError(
                "Batch exceeds max_images"
            )

        return [
            self.detect(path)
            for path in image_paths
        ]
