"""Planned module: train text classifier. Implementation pending."""

"""
ai/training/train_text_classifier.py

Train and evaluate the retail NLP classifier.

CSV columns:
    text,label

Expected splits:
    train.csv
    val.csv
    test.csv

Run:
python -m ai.training.train_text_classifier \
    --data-dir datasets/retail_text
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd
import torch

from ai.nlp.text_classifier import (
    RetailTextClassifier,
    TextDataset,
)

from torch.utils.data import DataLoader


def load_dataset(
    path: Path,
) -> tuple[list[str], list[str]]:
    if not path.is_file():
        raise FileNotFoundError(path)

    df = pd.read_csv(path)

    required = {"text", "label"}

    if not required.issubset(df.columns):
        raise ValueError(
            f"{path} must contain text,label columns"
        )

    if df.empty:
        raise ValueError(f"Empty dataset: {path}")

    if df[["text", "label"]].isna().any().any():
        raise ValueError(
            f"Missing text or label in {path}"
        )

    texts = df["text"].tolist()
    labels = df["label"].tolist()

    if any(
        not isinstance(value, str)
        or not value.strip()
        for value in texts + labels
    ):
        raise ValueError(
            f"Invalid text or label in {path}"
        )

    return texts, labels


def train_text_classifier(
    data_dir: str = "datasets/retail_text",
    model_name: str = "distilbert-base-uncased",
    output_dir: str = "models/retail_text_classifier",
    report_path: str = "reports/text_classifier_metrics.json",
    epochs: int = 3,
    batch_size: int = 8,
    learning_rate: float = 2e-5,
    seed: int = 42,
) -> dict:

    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("Invalid seed")

    torch.manual_seed(seed)

    source = Path(data_dir)

    train_texts, train_labels = load_dataset(
        source / "train.csv"
    )

    val_texts, val_labels = load_dataset(
        source / "val.csv"
    )

    test_texts, test_labels = load_dataset(
        source / "test.csv"
    )

    classes = sorted(set(train_labels))

    if len(classes) < 2:
        raise ValueError(
            "At least two training classes required"
        )

    for split_name, labels in (
        ("validation", val_labels),
        ("test", test_labels),
    ):
        unknown = set(labels) - set(classes)

        if unknown:
            raise ValueError(
                f"Unknown {split_name} labels: {unknown}"
            )

    # Prevent exact duplicate text leakage.
    train_set = set(
        text.strip().casefold()
        for text in train_texts
    )
    val_set = set(
        text.strip().casefold()
        for text in val_texts
    )
    test_set = set(
        text.strip().casefold()
        for text in test_texts
    )

    if (
        train_set & val_set
        or train_set & test_set
        or val_set & test_set
    ):
        raise ValueError(
            "Duplicate texts across dataset splits"
        )

    classifier = RetailTextClassifier(
        labels=classes,
        model_name=model_name,
    )

    history = classifier.train(
        train_texts=train_texts,
        train_labels=train_labels,
        val_texts=val_texts,
        val_labels=val_labels,
        epochs=epochs,
        batch_size=batch_size,
        learning_rate=learning_rate,
    )

    test_ids = classifier._validate_examples(
        test_texts,
        test_labels,
    )

    test_dataset = TextDataset(
        texts=test_texts,
        labels=test_ids,
        tokenizer=classifier.tokenizer,
        max_length=classifier.max_length,
    )

    test_loader = DataLoader(
        test_dataset,
        batch_size=batch_size,
        shuffle=False,
    )

    test_metrics = classifier._evaluate_loader(
        test_loader
    )

    classifier.save(output_dir)

    report = {
        "task": "retail_text_classification",
        "model": model_name,
        "classes": classes,
        "train_samples": len(train_texts),
        "validation_samples": len(val_texts),
        "test_samples": len(test_texts),
        "training_history": history,
        "test_accuracy": test_metrics["accuracy"],
        "test_macro_f1": test_metrics["macro_f1"],
        "test_classification_report": (
            test_metrics["classification_report"]
        ),
        "model_directory": output_dir,
        "test_set_used_for_training": False,
    }

    destination = Path(report_path)
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    return report


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--data-dir",
        default="datasets/retail_text",
    )
    parser.add_argument(
        "--model",
        default="distilbert-base-uncased",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=3,
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=8,
    )
    parser.add_argument(
        "--lr",
        type=float,
        default=2e-5,
    )

    args = parser.parse_args()

    report = train_text_classifier(
        data_dir=args.data_dir,
        model_name=args.model,
        epochs=args.epochs,
        batch_size=args.batch,
        learning_rate=args.lr,
    )

    print(json.dumps({
        "test_accuracy": report["test_accuracy"],
        "test_macro_f1": report["test_macro_f1"],
        "model_directory": report["model_directory"],
    }, indent=2))


if __name__ == "__main__":
    main()
