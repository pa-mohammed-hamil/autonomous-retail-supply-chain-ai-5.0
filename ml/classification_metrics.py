"""Planned module: classification metrics. Implementation pending."""

"""
ai/evaluation/classification_metrics.py

Autonomous Retail Supply Chain AI 5.0

Classification Model Evaluation

Features:
- Binary and multiclass evaluation
- Accuracy, balanced accuracy
- Precision, recall, F1
- Macro/weighted averages
- Confusion matrix
- ROC-AUC and average precision
- Log loss and Brier score
- CSV/JSON report export

Install:
    pip install numpy pandas scikit-learn
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    classification_report,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)


class ClassificationEvaluator:

    def __init__(
        self,
        labels,
        positive_label=None,
    ):
        self.labels = list(labels)

        if (
            len(self.labels) < 2
            or len(set(self.labels))
            != len(self.labels)
        ):
            raise ValueError(
                "Provide at least two unique labels"
            )

        self.positive_label = positive_label

        if (
            positive_label is not None
            and positive_label not in self.labels
        ):
            raise ValueError(
                "Positive label not in labels"
            )

        self.metrics = None
        self.confusion = None
        self.report = None

    def evaluate(
        self,
        y_true,
        y_pred,
        probabilities=None,
    ):
        actual = np.asarray(
            y_true
        )

        predicted = np.asarray(
            y_pred
        )

        if (
            actual.ndim != 1
            or predicted.ndim != 1
            or len(actual) == 0
            or len(actual) != len(predicted)
        ):
            raise ValueError(
                "Invalid prediction arrays"
            )

        if (
            not np.isin(
                actual,
                self.labels,
            ).all()
            or not np.isin(
                predicted,
                self.labels,
            ).all()
        ):
            raise ValueError(
                "Unknown class labels detected"
            )

        metrics = {
            "sample_count": int(
                len(actual)
            ),
            "accuracy": float(
                accuracy_score(
                    actual,
                    predicted,
                )
            ),
            "balanced_accuracy": float(
                balanced_accuracy_score(
                    actual,
                    predicted,
                )
            ),
            "macro_precision": float(
                precision_score(
                    actual,
                    predicted,
                    labels=self.labels,
                    average="macro",
                    zero_division=0,
                )
            ),
            "macro_recall": float(
                recall_score(
                    actual,
                    predicted,
                    labels=self.labels,
                    average="macro",
                    zero_division=0,
                )
            ),
            "macro_f1": float(
                f1_score(
                    actual,
                    predicted,
                    labels=self.labels,
                    average="macro",
                    zero_division=0,
                )
            ),
            "weighted_f1": float(
                f1_score(
                    actual,
                    predicted,
                    labels=self.labels,
                    average="weighted",
                    zero_division=0,
                )
            ),
        }

        self.confusion = (
            pd.DataFrame(
                confusion_matrix(
                    actual,
                    predicted,
                    labels=self.labels,
                ),
                index=self.labels,
                columns=self.labels,
            )
        )

        self.report = (
            classification_report(
                actual,
                predicted,
                labels=self.labels,
                output_dict=True,
                zero_division=0,
            )
        )

        if probabilities is not None:
            probs = np.asarray(
                probabilities,
                dtype=float,
            )

            n_classes = len(
                self.labels
            )

            if n_classes == 2:
                if probs.ndim == 2:
                    if probs.shape != (
                        len(actual), 2
                    ):
                        raise ValueError(
                            "Invalid probability matrix"
                        )

                    if not np.allclose(
                        probs.sum(axis=1),
                        1.0,
                        atol=1e-6,
                    ):
                        raise ValueError(
                            "Probabilities must sum to 1"
                        )

                    if self.positive_label is None:
                        pos_idx = 1
                    else:
                        pos_idx = (
                            self.labels.index(
                                self.positive_label
                            )
                        )

                    positive_probs = (
                        probs[:, pos_idx]
                    )

                elif probs.ndim == 1:
                    if self.positive_label is None:
                        raise ValueError(
                            "Specify positive_label "
                            "for 1D probabilities"
                        )

                    positive_probs = probs

                else:
                    raise ValueError(
                        "Invalid probability shape"
                    )

                if (
                    not np.isfinite(
                        positive_probs
                    ).all()
                    or (positive_probs < 0).any()
                    or (positive_probs > 1).any()
                ):
                    raise ValueError(
                        "Probabilities must be 0-1"
                    )

                positive = (
                    self.positive_label
                    if self.positive_label is not None
                    else self.labels[1]
                )

                binary_actual = (
                    actual == positive
                ).astype(int)

                metrics["brier_score"] = float(
                    brier_score_loss(
                        binary_actual,
                        positive_probs,
                    )
                )

                metrics["log_loss"] = float(
                    log_loss(
                        binary_actual,
                        np.column_stack([
                            1 - positive_probs,
                            positive_probs,
                        ]),
                        labels=[0, 1],
                    )
                )

                if (
                    len(np.unique(
                        binary_actual
                    )) == 2
                ):
                    metrics["roc_auc"] = float(
                        roc_auc_score(
                            binary_actual,
                            positive_probs,
                        )
                    )

                    metrics[
                        "average_precision"
                    ] = float(
                        average_precision_score(
                            binary_actual,
                            positive_probs,
                        )
                    )
                else:
                    metrics["roc_auc"] = None
                    metrics[
                        "average_precision"
                    ] = None

            else:
                if probs.shape != (
                    len(actual),
                    n_classes,
                ):
                    raise ValueError(
                        "Multiclass probabilities "
                        "must be N x C"
                    )

                if (
                    not np.isfinite(probs).all()
                    or (probs < 0).any()
                    or (probs > 1).any()
                    or not np.allclose(
                        probs.sum(axis=1),
                        1.0,
                        atol=1e-6,
                    )
                ):
                    raise ValueError(
                        "Invalid probability matrix"
                    )

                metrics["log_loss"] = float(
                    log_loss(
                        actual,
                        probs,
                        labels=self.labels,
                    )
                )

                # Multiclass ROC-AUC needs
                # every class represented.
                if (
                    len(np.unique(actual))
                    == n_classes
                ):
                    metrics["roc_auc_ovr"] = float(
                        roc_auc_score(
                            actual,
                            probs,
                            labels=self.labels,
                            multi_class="ovr",
                            average="macro",
                        )
                    )
                else:
                    metrics["roc_auc_ovr"] = None

        self.metrics = metrics

        return metrics

    def save(
        self,
        output_dir=(
            "reports/classification"
        ),
    ):
        if self.metrics is None:
            raise RuntimeError(
                "Run evaluation first"
            )

        directory = Path(
            output_dir
        )

        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        (
            directory / "metrics.json"
        ).write_text(
            json.dumps(
                self.metrics,
                indent=2,
            ),
            encoding="utf-8",
        )

        self.confusion.to_csv(
            directory
            / "confusion_matrix.csv"
        )

        (
            directory
            / "classification_report.json"
        ).write_text(
            json.dumps(
                self.report,
                indent=2,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    rng = np.random.default_rng(42)

    n = 500

    actual = rng.binomial(
        1,
        0.25,
        n,
    )

    probabilities = np.where(
        actual == 1,
        rng.beta(5, 3, n),
        rng.beta(2, 6, n),
    )

    predicted = (
        probabilities >= 0.5
    ).astype(int)

    evaluator = ClassificationEvaluator(
        labels=[0, 1],
        positive_label=1,
    )

    metrics = evaluator.evaluate(
        actual,
        predicted,
        probabilities,
    )

    print(
        json.dumps(
            metrics,
            indent=2,
        )
    )

    print(
        "\nConfusion matrix:"
    )

    print(
        evaluator.confusion
    )

    evaluator.save()
