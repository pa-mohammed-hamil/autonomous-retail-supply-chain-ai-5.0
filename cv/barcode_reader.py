
"""
ai/computer_vision/barcode_detection.py

Barcode region detection.

Modes:
    opencv
    yolo

Outputs bounding boxes in xyxy format.
OpenCV detections are geometric candidates,
not calibrated barcode probabilities.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np


class BarcodeDetector:

    def __init__(
        self,
        method: str = "opencv",
        model_path: str | None = None,
        confidence: float = 0.35,
        min_area: int = 300,
    ):
        if method not in {"opencv", "yolo"}:
            raise ValueError("Unsupported method")

        if not 0 <= confidence <= 1:
            raise ValueError("Invalid confidence")

        if min_area <= 0:
            raise ValueError("min_area must be positive")

        self.method = method
        self.confidence = confidence
        self.min_area = min_area
        self.model = None

        if method == "yolo":
            if not model_path:
                raise ValueError(
                    "YOLO requires model_path"
                )

            if not Path(model_path).is_file():
                raise FileNotFoundError(model_path)

            from ultralytics import YOLO

            # Only load checkpoints from trusted sources.
            self.model = YOLO(model_path)

    @staticmethod
    def _load_image(
        image_path: str,
    ) -> np.ndarray:

        path = Path(image_path)

        if not path.is_file():
            raise FileNotFoundError(path)

        image = cv2.imread(str(path))

        if image is None:
            raise ValueError(
                "Cannot decode image"
            )

        return image

    def _opencv_detect(
        self,
        image: np.ndarray,
    ) -> list[dict[str, Any]]:

        gray = cv2.cvtColor(
            image,
            cv2.COLOR_BGR2GRAY,
        )

        grad_x = cv2.Sobel(
            gray,
            cv2.CV_32F,
            1,
            0,
            ksize=-1,
        )

        grad_y = cv2.Sobel(
            gray,
            cv2.CV_32F,
            0,
            1,
            ksize=-1,
        )

        gradient = cv2.subtract(
            grad_x, grad_y
        )

        gradient = cv2.convertScaleAbs(
            gradient
        )

        blurred = cv2.blur(
            gradient,
            (9, 9),
        )

        _, threshold = cv2.threshold(
            blurred,
            0,
            255,
            cv2.THRESH_BINARY
            | cv2.THRESH_OTSU,
        )

        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (21, 7),
        )

        closed = cv2.morphologyEx(
            threshold,
            cv2.MORPH_CLOSE,
            kernel,
        )

        closed = cv2.erode(
            closed,
            None,
            iterations=2,
        )

        closed = cv2.dilate(
            closed,
            None,
            iterations=2,
        )

        contours, _ = cv2.findContours(
            closed,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        height, width = image.shape[:2]

        detections = []

        for contour in contours:
            x, y, w, h = cv2.boundingRect(
                contour
            )

            if w * h < self.min_area:
                continue

            if w <= 0 or h <= 0:
                continue

            # Broad shape filtering; rotated
            # or stacked codes may still be missed.
            aspect_ratio = max(
                w / h,
                h / w,
            )

            if aspect_ratio < 1.3:
                continue

            padding = 8

            x1 = max(0, x - padding)
            y1 = max(0, y - padding)
            x2 = min(
                width,
                x + w + padding,
            )
            y2 = min(
                height,
                y + h + padding,
            )

            detections.append({
                "bbox": [x1, y1, x2, y2],
                "method": "opencv",
                "confidence": None,
                "label": "barcode_candidate",
            })

        detections.sort(
            key=lambda item: (
                item["bbox"][1],
                item["bbox"][0],
            )
        )

        return detections

    def _yolo_detect(
        self,
        image: np.ndarray,
    ) -> list[dict[str, Any]]:

        results = self.model.predict(
            source=image,
            conf=self.confidence,
            verbose=False,
        )

        detections = []

        for result in results:
            if result.boxes is None:
                continue

            for box in result.boxes:
                xyxy = (
                    box.xyxy[0]
                    .cpu()
                    .tolist()
                )

                class_id = int(
                    box.cls[0].item()
                )

                detections.append({
                    "bbox": [
                        int(round(value))
                        for value in xyxy
                    ],
                    "method": "yolo",
                    "confidence": round(
                        float(
                            box.conf[0].item()
                        ),
                        4,
                    ),
                    "label": result.names[
                        class_id
                    ],
                })

        return detections

    def detect(
        self,
        image_path: str,
        save_annotated: bool = False,
        output_path: str | None = None,
    ) -> dict:

        image = self._load_image(
            image_path
        )

        if self.method == "opencv":
            detections = self._opencv_detect(
                image
            )
        else:
            detections = self._yolo_detect(
                image
            )

        annotated_path = None

        if save_annotated:
            if output_path is None:
                raise ValueError(
                    "Provide output_path"
                )

            annotated = image.copy()

            for item in detections:
                x1, y1, x2, y2 = item[
                    "bbox"
                ]

                cv2.rectangle(
                    annotated,
                    (x1, y1),
                    (x2, y2),
                    (0, 255, 0),
                    2,
                )

            destination = Path(
                output_path
            )

            destination.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            if not cv2.imwrite(
                str(destination),
                annotated,
            ):
                raise RuntimeError(
                    "Failed to save image"
                )

            annotated_path = str(
                destination
            )

        return {
            "image_path": image_path,
            "method": self.method,
            "candidate_count": len(
                detections
            ),
            "detections": detections,
            "annotated_image": annotated_path,
            "requires_decode_verification": True,
        }
