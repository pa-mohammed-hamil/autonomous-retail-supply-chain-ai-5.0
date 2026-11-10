"""Planned module: detection metrics. Implementation pending."""

"""
ai/evaluation/detection_metrics.py

Object detection evaluation for retail computer vision.

Input format per image:
{
    "image_id": "image_001",
    "ground_truth": [
        {"class": "damaged", "bbox": [10, 20, 100, 120]}
    ],
    "predictions": [
        {
            "class": "damaged",
            "bbox": [12, 22, 98, 118],
            "confidence": 0.92
        }
    ]
}

Bounding boxes use absolute xyxy coordinates.

AP uses all-point precision-envelope integration.
This is not a byte-for-byte replacement for the
Ultralytics/COCO evaluation implementation.
"""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Any

import numpy as np


class DetectionMetrics:

    def __init__(
        self,
        iou_threshold: float = 0.50,
        confidence_threshold: float = 0.25,
    ):
        for name, value in (
            ("iou_threshold", iou_threshold),
            ("confidence_threshold", confidence_threshold),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 1
            ):
                raise ValueError(f"Invalid {name}")

        self.iou_threshold = float(iou_threshold)
        self.confidence_threshold = float(
            confidence_threshold
        )

    @staticmethod
    def _bbox(box) -> tuple[float, float, float, float]:
        if (
            not isinstance(box, (list, tuple))
            or len(box) != 4
            or any(
                isinstance(v, bool)
                or not isinstance(v, (int, float))
                or not math.isfinite(v)
                for v in box
            )
        ):
            raise ValueError("Invalid bounding box")

        x1, y1, x2, y2 = map(float, box)

        if x2 <= x1 or y2 <= y1:
            raise ValueError(
                "Bounding boxes must have positive area"
            )

        return x1, y1, x2, y2

    @classmethod
    def iou(cls, box_a, box_b) -> float:
        ax1, ay1, ax2, ay2 = cls._bbox(box_a)
        bx1, by1, bx2, by2 = cls._bbox(box_b)

        intersection = (
            max(0.0, min(ax2, bx2) - max(ax1, bx1))
            * max(0.0, min(ay2, by2) - max(ay1, by1))
        )

        area_a = (ax2 - ax1) * (ay2 - ay1)
        area_b = (bx2 - bx1) * (by2 - by1)

        union = area_a + area_b - intersection

        return intersection / union if union else 0.0

    @staticmethod
    def _average_precision(
        recall: np.ndarray,
        precision: np.ndarray,
    ) -> float:
        if len(recall) == 0:
            return 0.0

        mrec = np.concatenate((
            [0.0], recall, [1.0]
        ))
        mpre = np.concatenate((
            [1.0], precision, [0.0]
        ))

        # Monotonic precision envelope.
        for index in range(
            len(mpre) - 2, -1, -1
        ):
            mpre[index] = max(
                mpre[index],
                mpre[index + 1],
            )

        changes = np.where(
            mrec[1:] != mrec[:-1]
        )[0]

        return float(np.sum(
            (mrec[changes + 1] - mrec[changes])
            * mpre[changes + 1]
        ))

    def _prepare(self, records: list[dict]):
        if not isinstance(records, list):
            raise ValueError("records must be a list")

        prepared = []
        seen_ids = set()
        classes = set()

        for record in records:
            if not isinstance(record, dict):
                raise ValueError("Invalid image record")

            image_id = record.get("image_id")

            if (
                not isinstance(image_id, str)
                or not image_id.strip()
                or image_id in seen_ids
            ):
                raise ValueError(
                    "Image IDs must be unique nonempty strings"
                )

            seen_ids.add(image_id)

            ground_truth = record.get(
                "ground_truth", []
            )
            predictions = record.get(
                "predictions", []
            )

            if (
                not isinstance(ground_truth, list)
                or not isinstance(predictions, list)
            ):
                raise ValueError(
                    "Ground truth and predictions must be lists"
                )

            gt_items = []
            pred_items = []

            for item in ground_truth:
                if not isinstance(item, dict):
                    raise ValueError("Invalid ground truth")

                label = item.get("class")
                if not isinstance(label, str) or not label:
                    raise ValueError("Invalid class label")

                classes.add(label)
                gt_items.append({
                    "class": label,
                    "bbox": self._bbox(item.get("bbox")),
                })

            for item in predictions:
                if not isinstance(item, dict):
                    raise ValueError("Invalid prediction")

                label = item.get("class")
                confidence = item.get("confidence")

                if (
                    not isinstance(label, str)
                    or not label
                    or isinstance(confidence, bool)
                    or not isinstance(
                        confidence, (int, float)
                    )
                    or not math.isfinite(confidence)
                    or not 0 <= confidence <= 1
                ):
                    raise ValueError(
                        "Invalid prediction label/confidence"
                    )

                classes.add(label)
                pred_items.append({
                    "class": label,
                    "bbox": self._bbox(item.get("bbox")),
                    "confidence": float(confidence),
                })

            prepared.append({
                "image_id": image_id,
                "ground_truth": gt_items,
                "predictions": pred_items,
            })

        return prepared, sorted(classes)

    def _class_evaluation(
        self,
        records: list[dict],
        class_name: str,
        iou_threshold: float,
        min_confidence: float,
    ) -> dict:

        gt_by_image = {}
        predictions = []
        gt_count = 0

        for record in records:
            image_id = record["image_id"]

            gt_boxes = [
                item["bbox"]
                for item in record["ground_truth"]
                if item["class"] == class_name
            ]

            gt_by_image[image_id] = gt_boxes
            gt_count += len(gt_boxes)

            for item in record["predictions"]:
                if (
                    item["class"] == class_name
                    and item["confidence"] >= min_confidence
                ):
                    predictions.append({
                        "image_id": image_id,
                        "bbox": item["bbox"],
                        "confidence": item["confidence"],
                    })

        predictions.sort(
            key=lambda item: -item["confidence"]
        )

        matched = {
            image_id: set()
            for image_id in gt_by_image
        }

        true_positives = []
        false_positives = []

        for prediction in predictions:
            image_id = prediction["image_id"]
            boxes = gt_by_image[image_id]

            best_iou = 0.0
            best_index = None

            for index, gt_box in enumerate(boxes):
                if index in matched[image_id]:
                    continue

                overlap = self.iou(
                    prediction["bbox"],
                    gt_box,
                )

                if overlap > best_iou:
                    best_iou = overlap
                    best_index = index

            if (
                best_index is not None
                and best_iou >= iou_threshold
            ):
                matched[image_id].add(best_index)
                true_positives.append(1)
                false_positives.append(0)
            else:
                true_positives.append(0)
                false_positives.append(1)

        tp = int(sum(true_positives))
        fp = int(sum(false_positives))
        fn = gt_count - tp

        precision = (
            tp / (tp + fp)
            if tp + fp else 0.0
        )

        recall = (
            tp / gt_count
            if gt_count else 0.0
        )

        f1 = (
            2 * precision * recall / (precision + recall)
            if precision + recall else 0.0
        )

        if gt_count:
            cumulative_tp = np.cumsum(
                true_positives
            )
            cumulative_fp = np.cumsum(
                false_positives
            )

            precision_curve = (
                cumulative_tp
                / np.maximum(
                    cumulative_tp + cumulative_fp,
                    1,
                )
            )

            recall_curve = (
                cumulative_tp / gt_count
            )

            ap = self._average_precision(
                recall_curve,
                precision_curve,
            )
        else:
            ap = None

        return {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "ground_truth_count": gt_count,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "ap": ap,
        }

    def evaluate(
        self,
        records: list[dict],
    ) -> dict[str, Any]:

        prepared, classes = self._prepare(records)

        thresholds = [
            round(float(v), 2)
            for v in np.arange(0.50, 1.00, 0.05)
        ]

        per_class = {}
        ap50_values = []
        ap5095_values = []

        totals = {
            "tp": 0,
            "fp": 0,
            "fn": 0,
        }

        for class_name in classes:
            # Thresholded operating-point metrics.
            current = self._class_evaluation(
                prepared,
                class_name,
                self.iou_threshold,
                self.confidence_threshold,
            )

            for key in totals:
                totals[key] += current[key]

            # AP is calculated from all predictions,
            # without the operating confidence cutoff.
            ap_results = [
                self._class_evaluation(
                    prepared,
                    class_name,
                    threshold,
                    min_confidence=0.0,
                )["ap"]
                for threshold in thresholds
            ]

            valid_aps = [
                value
                for value in ap_results
                if value is not None
            ]

            ap50 = ap_results[0]
            ap5095 = (
                float(np.mean(valid_aps))
                if valid_aps else None
            )

            if ap50 is not None:
                ap50_values.append(ap50)

            if ap5095 is not None:
                ap5095_values.append(ap5095)

            per_class[class_name] = {
                "tp": current["tp"],
                "fp": current["fp"],
                "fn": current["fn"],
                "precision": round(
                    current["precision"], 4
                ),
                "recall": round(
                    current["recall"], 4
                ),
                "f1": round(
                    current["f1"], 4
                ),
                "ap50": (
                    round(ap50, 4)
                    if ap50 is not None else None
                ),
                "ap50_95": (
                    round(ap5095, 4)
                    if ap5095 is not None else None
                ),
            }

        tp = totals["tp"]
        fp = totals["fp"]
        fn = totals["fn"]

        micro_precision = (
            tp / (tp + fp)
            if tp + fp else 0.0
        )

        micro_recall = (
            tp / (tp + fn)
            if tp + fn else 0.0
        )

        micro_f1 = (
            2 * micro_precision * micro_recall
            / (micro_precision + micro_recall)
            if micro_precision + micro_recall
            else 0.0
        )

        return {
            "images_evaluated": len(prepared),
            "classes": classes,
            "iou_threshold": self.iou_threshold,
            "confidence_threshold": (
                self.confidence_threshold
            ),
            "true_positives": tp,
            "false_positives": fp,
            "false_negatives": fn,
            "micro_precision": round(
                micro_precision, 4
            ),
            "micro_recall": round(
                micro_recall, 4
            ),
            "micro_f1": round(
                micro_f1, 4
            ),
            "map50": (
                round(float(np.mean(ap50_values)), 4)
                if ap50_values else None
            ),
            "map50_95": (
                round(float(np.mean(ap5095_values)), 4)
                if ap5095_values else None
            ),
            "per_class": per_class,
            "evaluation_method": (
                "class-aware greedy matching; "
                "all-point AP integration"
            ),
        }
