"""Planned module: package damage detection. Implementation pending."""

"""
ai/computer_vision/package_damage_detection.py

Package damage detection with custom YOLO.

Features:
- Image inference
- Damage classification
- Bounding boxes
- Confidence scores
- Configurable severity rules
- Annotated image output
- Human inspection recommendations

Severity rules are operational heuristics,
not verified structural safety assessments.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import cv2


DEFAULT_SEVERITY = {
    "dent": "low",
    "tear": "medium",
    "crushed_box": "high",
    "hole": "high",
    "broken_seal": "high",
}

SEVERITY_RANK = {
    "none": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}


class PackageDamageDetection:

    def __init__(
        self,
        model_path: str,
        confidence: float = 0.35,
        iou: float = 0.50,
        image_size: int = 640,
        severity_rules: dict[str, str] | None = None,
    ):
        if not Path(model_path).is_file():
            raise FileNotFoundError(model_path)

        if not 0 <= confidence <= 1:
            raise ValueError(
                "Invalid confidence"
            )

        if not 0 <= iou <= 1:
            raise ValueError(
                "Invalid IoU"
            )

        if image_size <= 0:
            raise ValueError(
                "Invalid image size"
            )

        from ultralytics import YOLO

        # Only load model weights from trusted sources.
        self.model = YOLO(model_path)

        self.confidence = confidence
        self.iou = iou
        self.image_size = image_size

        self.severity_rules = (
            severity_rules
            if severity_rules is not None
            else DEFAULT_SEVERITY.copy()
        )

        if any(
            severity not in SEVERITY_RANK
            for severity in self.severity_rules.values()
        ):
            raise ValueError(
                "Invalid severity configuration"
            )

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

        results = self.model.predict(
            source=image,
            conf=self.confidence,
            iou=self.iou,
            imgsz=self.image_size,
            verbose=False,
        )

        result = results[0]
        detections = []

        for box in result.boxes:
            class_id = int(
                box.cls[0].item()
            )

            label = result.names[
                class_id
            ]

            confidence = float(
                box.conf[0].item()
            )

            bbox = [
                round(float(value), 2)
                for value in (
                    box.xyxy[0]
                    .cpu()
                    .tolist()
                )
            ]

            severity = (
                self.severity_rules.get(
                    label, "medium"
                )
            )

            detections.append({
                "class_name": label,
                "confidence": round(
                    confidence, 4
                ),
                "bbox": bbox,
                "severity": severity,
            })

        damage_counts = dict(
            Counter(
                item["class_name"]
                for item in detections
            )
        )

        overall_severity = "none"

        for detection in detections:
            severity = detection[
                "severity"
            ]

            if (
                SEVERITY_RANK[severity]
                > SEVERITY_RANK[overall_severity]
            ):
                overall_severity = severity

        annotated_path = None

        if save_annotated:
            if not output_path:
                raise ValueError(
                    "output_path required"
                )

            destination = Path(
                output_path
            )

            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            annotated = result.plot()

            if not cv2.imwrite(
                str(destination),
                annotated,
            ):
                raise RuntimeError(
                    "Failed to save annotated image"
                )

            annotated_path = str(
                destination
            )

        return {
            "image_path": image_path,
            "damage_detected": bool(
                detections
            ),
            "damage_count": len(
                detections
            ),
            "damage_counts_by_class": (
                damage_counts
            ),
            "overall_severity": (
                overall_severity
            ),
            "detections": detections,
            "annotated_image": annotated_path,
            "human_inspection_required": (
                bool(detections)
            ),
            "packaging_integrity_verified": False,
        }
