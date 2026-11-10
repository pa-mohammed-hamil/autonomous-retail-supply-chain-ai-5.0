"""Planned module: train damage detector. Implementation pending."""
"""
Train a custom YOLO package-damage detector.

Run:
python -m ai.training.train_damage_detector \
    --data datasets/package_damage/data.yaml \
    --epochs 50

Requires annotated YOLO-format detection data.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path

import yaml
from ultralytics import YOLO


EXPECTED_CLASSES = {
    "dent",
    "tear",
    "crushed_box",
    "hole",
    "broken_seal",
}


def validate_dataset(data_yaml: Path) -> dict:
    if not data_yaml.is_file():
        raise FileNotFoundError(data_yaml)

    config = yaml.safe_load(
        data_yaml.read_text(encoding="utf-8")
    )

    if not isinstance(config, dict):
        raise ValueError("Invalid dataset configuration")

    names = config.get("names")

    if isinstance(names, dict):
        names = [
            names[key]
            for key in sorted(names, key=int)
        ]

    if (
        not isinstance(names, list)
        or not names
        or len(names) != len(set(names))
        or any(not isinstance(x, str) for x in names)
    ):
        raise ValueError("Invalid class names")

    if set(names) != EXPECTED_CLASSES:
        raise ValueError(
            "Expected damage classes: "
            + ", ".join(sorted(EXPECTED_CLASSES))
        )

    # Relative dataset paths follow Ultralytics
    # dataset YAML conventions.
    return config


def train_damage_detector(
    data_yaml: str,
    base_model: str = "yolo11n.pt",
    epochs: int = 50,
    image_size: int = 640,
    batch_size: int = 16,
    device: str = "cpu",
    output_model: str = "models/package_damage_best.pt",
    project: str = "runs/package_damage",
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
        raise ValueError("seed must be an integer")

    data_path = Path(data_yaml).resolve()
    validate_dataset(data_path)

    model = YOLO(base_model)

    model.train(
        data=str(data_path),
        epochs=epochs,
        imgsz=image_size,
        batch=batch_size,
        device=device,
        seed=seed,
        deterministic=True,
        patience=15,
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
            "Training did not produce best.pt"
        )

    # Evaluate the best checkpoint, not merely
    # the model's final epoch.
    best_model = YOLO(str(best_checkpoint))

    metrics = best_model.val(
        data=str(data_path),
        imgsz=image_size,
        device=device,
        plots=True,
        verbose=False,
    )

    output_path = Path(output_model)
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copy2(
        best_checkpoint,
        output_path,
    )

    report = {
        "model_type": "YOLO object detection",
        "task": "package_damage_detection",
        "classes": sorted(EXPECTED_CLASSES),
        "epochs_requested": epochs,
        "checkpoint": str(output_path),
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

    report_path = output_path.with_suffix(
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
        default="datasets/package_damage/data.yaml",
    )
    parser.add_argument(
        "--model",
        default="yolo11n.pt",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=50,
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

    report = train_damage_detector(
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
