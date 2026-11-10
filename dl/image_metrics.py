"""Planned module: image metrics. Implementation pending."""

"""
ai/evaluation/image_metrics.py

Classification metrics for retail image models.

Supports:
- Accuracy
- Precision / recall / F1
- Macro, micro and weighted averages
- Confusion matrix
- Per-class classification report
- Top-k accuracy
- Confidence-based abstention metrics
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from sklearn.metrics import (
    accuracy_score,
    precision_recall_fscore_support,
    confusion_matrix,
    classification_report,
)


class ImageMetrics:

    def __init__(
        self,
        class_names: list[str],
    ):
        if (
            not isinstance(class_names, list)
            or len(class_names) < 2
            or any(
                not isinstance(name, str)
                or not name.strip()
                for name in class_names
            )
            or len(set(class_names)) != len(class_names)
        ):
            raise ValueError(
                "Provide unique class names"
            )

        self.class_names = list(class_names)
        self.label_to_id = {
            name: index
            for index, name in enumerate(
                class_names
            )
        }

    def _encode(
        self,
        labels: list[str],
    ) -> np.ndarray:
        if not isinstance(labels, list):
            raise ValueError(
                "Labels must be a list"
            )

        if any(
            label not in self.label_to_id
            for label in labels
        ):
            raise ValueError(
                "Unknown classification label"
            )

        return np.asarray(
            [
                self.label_to_id[label]
                for label in labels
            ],
            dtype=np.int64,
        )

    def evaluate(
        self,
        true_labels: list[str],
        predicted_labels: list[str],
        probabilities: list[list[float]] | None = None,
        top_k: int = 2,
        confidence_threshold: float | None = None,
    ) -> dict[str, Any]:

        if (
            not isinstance(true_labels, list)
            or not isinstance(predicted_labels, list)
            or not true_labels
            or len(true_labels) != len(predicted_labels)
        ):
            raise ValueError(
                "Invalid label arrays"
            )

        y_true = self._encode(true_labels)
        y_pred = self._encode(predicted_labels)

        class_ids = list(
            range(len(self.class_names))
        )

        accuracy = accuracy_score(
            y_true, y_pred
        )

        averages = {}

        for average in (
            "macro",
            "micro",
            "weighted",
        ):
            precision, recall, f1, _ = (
                precision_recall_fscore_support(
                    y_true,
                    y_pred,
                    labels=class_ids,
                    average=average,
                    zero_division=0,
                )
            )

            averages[average] = {
                "precision": round(
                    float(precision), 4
                ),
                "recall": round(
                    float(recall), 4
                ),
                "f1": round(
                    float(f1), 4
                ),
            }

        matrix = confusion_matrix(
            y_true,
            y_pred,
            labels=class_ids,
        )

        class_report = classification_report(
            y_true,
            y_pred,
            labels=class_ids,
            target_names=self.class_names,
            zero_division=0,
            output_dict=True,
        )

        report = {
            "samples": len(y_true),
            "classes": self.class_names,
            "accuracy": round(
                float(accuracy), 4
            ),
            "averages": averages,
            "confusion_matrix": (
                matrix.tolist()
            ),
            "confusion_matrix_labels": (
                self.class_names
            ),
            "per_class": {
                name: {
                    key: round(float(value), 4)
                    for key, value in class_report[
                        name
                    ].items()
                }
                for name in self.class_names
            },
        }

        if probabilities is not None:
            probs = np.asarray(
                probabilities,
                dtype=np.float64,
            )

            expected_shape = (
                len(y_true),
                len(self.class_names),
            )

            if (
                probs.shape != expected_shape
                or not np.all(np.isfinite(probs))
                or np.any(probs < 0)
                or np.any(probs > 1)
                or not np.allclose(
                    probs.sum(axis=1),
                    1.0,
                    atol=1e-4,
                )
            ):
                raise ValueError(
                    "Invalid class probabilities"
                )

            if (
                isinstance(top_k, bool)
                or not isinstance(top_k, int)
                or not 1 <= top_k <= len(
                    self.class_names
                )
            ):
                raise ValueError("Invalid top_k")

            # Probability column order must match
            # class_names exactly.
            ranked = np.argsort(
                -probs, axis=1
            )[:, :top_k]

            correct_top_k = [
                int(target in row)
                for target, row in zip(
                    y_true, ranked
                )
            ]

            report["top_k_accuracy"] = round(
                float(np.mean(correct_top_k)),
                4,
            )

            report["top_k"] = top_k

            # Validate that predicted labels match
            # the supplied probability argmax.
            probability_predictions = (
                probs.argmax(axis=1)
            )

            if not np.array_equal(
                probability_predictions,
                y_pred,
            ):
                raise ValueError(
                    "Predicted labels do not match "
                    "probability argmax"
                )

            if confidence_threshold is not None:
                if (
                    isinstance(
                        confidence_threshold, bool
                    )
                    or not isinstance(
                        confidence_threshold,
                        (int, float),
                    )
                    or not math.isfinite(
                        confidence_threshold
                    )
                    or not 0 <= confidence_threshold <= 1
                ):
                    raise ValueError(
                        "Invalid confidence threshold"
                    )

                confidence = probs.max(
                    axis=1
                )

                accepted = (
                    confidence >= confidence_threshold
                )

                coverage = float(
                    accepted.mean()
                )

                selective_accuracy = (
                    float(
                        np.mean(
                            y_true[accepted]
                            == y_pred[accepted]
                        )
                    )
                    if accepted.any()
                    else None
                )

                report["confidence_review"] = {
                    "threshold": (
                        confidence_threshold
                    ),
                    "coverage": round(
                        coverage, 4
                    ),
                    "review_count": int(
                        (~accepted).sum()
                    ),
                    "accepted_accuracy": (
                        round(
                            selective_accuracy, 4
                        )
                        if selective_accuracy is not None
                        else None
                    ),
                }

        elif confidence_threshold is not None:
            raise ValueError(
                "Probabilities required for "
                "confidence threshold evaluation"
            )

        return report
