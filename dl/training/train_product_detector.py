"""Planned module: train product detector. Implementation pending."""

"""
Train a custom YOLO retail-product detector.

Run:
python -m ai.training.train_product_detector \
    --data datasets/retail_products/data.yaml \
    --epochs 60

Supports custom product classes from data.yaml.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import yaml
from ultralytics import YOLO


def read_product_classes(
    data_yaml: Path,
) -> list[str]:

    if not data_yaml.is_file():
        raise FileNotFoundError(data_yaml)

    config = yaml.safe_load(
        data_yaml.read_text(encoding="utf-8")
    )

    if not isinstance(config, dict):
        raise ValueError("Invalid data.yaml")

    names = config.get("names")

    if isinstance(names, dict):
        indices = sorted(int(k) for k in names)

        if indices != list(range(len(indices))):
            raise ValueError(
                "Class IDs must start at 0 and be contiguous"
            )

        names = [
            names[i] if i in names else names[str(i)]
            for i in indices
        ]

    if (
        not isinstance(names, list)
        or not names
        or any(
            not isinstance(name, str)
            or not name.strip()
            for name in names
        )
        or len(set(names)) != len(names)
    ):
        raise ValueError(
            "Invalid product class names"
        )

    return names


def train_product_detector(
    data_yaml: str,
    base_model: str = "yolo11n.pt",
    epochs: int = 60,
    image_size: int = 640,
    batch_size: int = 16,
    device: str = "cpu",
    output_model: str = "models/retail_product_best.pt",
    project: str = "runs/retail_products",
    seed: int = 42,
) -> dict:

    for name, value in (
        ("epochs", epochs),
        ("image_size", image_size),
        ("batch_size", batch_size),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
        ):
            raise ValueError(f"{name} must be positive")

    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("Invalid seed")

    data_path = Path(data_yaml).resolve()

    classes = read_product_classes(
        data_path
    )

    model = YOLO(base_model)

    model.train(
        data=str(data_path),
        epochs=epochs,
        imgsz=image_size,
        batch=batch_size,
        device=device,
        seed=seed,
        deterministic=True,
        patience=20,
        workers=0,
        project=project,
        name="training",
        exist_ok=True,
        plots=True,
        save=True,
        verbose=True,
    )

    best_checkpoint = Path(
        model.trainer.best
    )

    if not best_checkpoint.is_file():
        raise RuntimeError(
            "No best checkpoint generated"
        )

    best_model = YOLO(
        str(best_checkpoint)
    )

    metrics = best_model.val(
        data=str(data_path),
        imgsz=image_size,
        device=device,
        plots=True,
        verbose=False,
    )

    destination = Path(output_model)

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copy2(
        best_checkpoint,
        destination,
    )

    report = {
        "task": "retail_product_detection",
        "architecture": "YOLO",
        "product_classes": classes,
        "class_count": len(classes),
        "epochs_requested": epochs,
        "checkpoint": str(destination),
        "validation": {
            "precision": float(
                metrics.box.mp
            ),
            "recall": float(
                metrics.box.mr
            ),
            "map50": float(
                metrics.box.map50
            ),
            "map50_95": float(
                metrics.box.map
            ),
        },
        "training_complete": True,
    }

    report_path = destination.with_suffix(
        ".metrics.json"
    )

    report_path.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    return report


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--data",
        default="datasets/retail_products/data.yaml",
    )
    parser.add_argument(
        "--model",
        default="yolo11n.pt",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=60,
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=640,
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=16,
    )
    parser.add_argument(
        "--device",
        default="cpu",
    )

    args = parser.parse_args()

    report = train_product_detector(
        data_yaml=args.data,
        base_model=args.model,
        epochs=args.epochs,
        image_size=args.imgsz,
        batch_size=args.batch,
        device=args.device,
    )

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
