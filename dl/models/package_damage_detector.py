"""Planned module: package damage detector. Implementation pending."""

"""
Package damage detection using a custom YOLO model.

Requires a trained object detection checkpoint.
Labels may include:
    dent, tear, crushed_box, hole, broken_seal

Predictions are visual evidence for human inspection.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from ultralytics import YOLO


class PackageDamageDetector:
    def __init__(
        self,
        model_path: str,
        confidence: float = 0.35,
        iou: float = 0.50,
        max_detections: int = 100,
    ):
        path = Path(model_path)

        if not path.is_file():
            raise FileNotFoundError(
                f"Model not found: {path}"
            )

        if not 0 <= confidence <= 1:
            raise ValueError("Invalid confidence")

        if not 0 <= iou <= 1:
            raise ValueError("Invalid IoU threshold")

        if (
            isinstance(max_detections, bool)
            or not isinstance(max_detections, int)
            or max_detections <= 0
        ):
            raise ValueError("Invalid max_detections")

        # Load only trusted model checkpoints.
        self.model = YOLO(str(path))
        self.confidence = confidence
        self.iou = iou
        self.max_detections = max_detections

    def detect(
        self,
        image_path: str,
        save_annotated: bool = False,
        output_dir: str = "outputs/package_damage",
    ) -> dict[str, Any]:

        path = Path(image_path)

        if not path.is_file():
            raise FileNotFoundError(path)

        results = self.model.predict(
            source=str(path),
            conf=self.confidence,
            iou=self.iou,
            max_det=self.max_detections,
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
            confidence = float(box.conf.item())

            x1, y1, x2, y2 = (
                float(value)
                for value in box.xyxy[0].tolist()
            )

            label = result.names[class_id]

            detections.append({
                "label": label,
                "confidence": round(confidence, 4),
                "bbox_xyxy": [
                    round(x1, 2),
                    round(y1, 2),
                    round(x2, 2),
                    round(y2, 2),
                ],
            })

        counts = dict(
            Counter(
                item["label"]
                for item in detections
            )
        )

        annotated_path = None

        if save_annotated:
            import cv2

            destination = Path(output_dir)
            destination.mkdir(
                parents=True,
                exist_ok=True,
            )

            annotated_path = destination / (
                path.stem + "_damage.jpg"
            )

            plotted = result.plot()

            if not cv2.imwrite(
                str(annotated_path),
                plotted,
            ):
                raise OSError(
                    "Could not save annotated image"
                )

        return {
            "image": str(path),
            "damage_detected": len(detections) > 0,
            "damage_count": len(detections),
            "damage_types": counts,
            "detections": detections,
            "annotated_image": (
                str(annotated_path)
                if annotated_path else None
            ),
            "inspection_status": (
                "review_required"
                if detections else "no_visible_damage_detected"
            ),
            "human_verification_required": True,
        }

    def detect_batch(
        self,
        image_paths: list[str],
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
            self.detect(image_path)
            for image_path in image_paths
        ]
