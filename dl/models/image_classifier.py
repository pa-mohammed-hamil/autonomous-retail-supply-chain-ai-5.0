"""Planned module: image classifier. Implementation pending."""

"""
ai/computer_vision/image_classifier.py

Retail product image classification using ResNet18.

Python 3.10+
Dependencies: torch, torchvision, Pillow

Requires labeled training data.
Predictions are advisory, not proof of authenticity.
"""

from __future__ import annotations

from pathlib import Path
import json

import torch
from PIL import Image, UnidentifiedImageError
from torch import nn
from torch.utils.data import DataLoader
from torchvision import datasets, models, transforms


IMAGE_SIZE = 224


class RetailImageClassifier:

    def __init__(
        self,
        class_names: list[str],
        pretrained: bool = True,
        device: str | None = None,
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
                "Provide at least two unique class names"
            )

        self.class_names = list(class_names)

        self.device = torch.device(
            device or (
                "cuda"
                if torch.cuda.is_available()
                else "cpu"
            )
        )

        weights = (
            models.ResNet18_Weights.DEFAULT
            if pretrained else None
        )

        self.model = models.resnet18(weights=weights)

        self.model.fc = nn.Linear(
            self.model.fc.in_features,
            len(self.class_names),
        )

        self.model.to(self.device)

        self.train_transform = transforms.Compose([
            transforms.Resize((256, 256)),
            transforms.RandomResizedCrop(
                IMAGE_SIZE,
                scale=(0.8, 1.0),
            ),
            transforms.RandomHorizontalFlip(),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225],
            ),
        ])

        self.eval_transform = transforms.Compose([
            transforms.Resize((256, 256)),
            transforms.CenterCrop(IMAGE_SIZE),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225],
            ),
        ])

        self.trained = False

    def train(
        self,
        train_dir: str,
        val_dir: str,
        epochs: int = 5,
        batch_size: int = 16,
        learning_rate: float = 0.0001,
    ) -> list[dict]:

        if (
            isinstance(epochs, bool)
            or not isinstance(epochs, int)
            or epochs <= 0
        ):
            raise ValueError("epochs must be positive")

        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or batch_size <= 0
        ):
            raise ValueError("batch_size must be positive")

        if not 0 < learning_rate < 1:
            raise ValueError("Invalid learning_rate")

        train_dataset = datasets.ImageFolder(
            train_dir,
            transform=self.train_transform,
        )

        val_dataset = datasets.ImageFolder(
            val_dir,
            transform=self.eval_transform,
        )

        if train_dataset.classes != self.class_names:
            raise ValueError(
                "Training folder classes must match "
                "class_names in alphabetical order"
            )

        if val_dataset.classes != self.class_names:
            raise ValueError(
                "Validation classes must match training"
            )

        if not len(train_dataset) or not len(val_dataset):
            raise ValueError("Datasets cannot be empty")

        train_loader = DataLoader(
            train_dataset,
            batch_size=batch_size,
            shuffle=True,
            num_workers=0,
        )

        val_loader = DataLoader(
            val_dataset,
            batch_size=batch_size,
            shuffle=False,
            num_workers=0,
        )

        criterion = nn.CrossEntropyLoss()

        optimizer = torch.optim.AdamW(
            self.model.parameters(),
            lr=learning_rate,
        )

        history = []
        best_accuracy = -1.0
        best_state = None

        for epoch in range(epochs):

            self.model.train()

            training_loss = 0.0

            for images, labels in train_loader:
                images = images.to(self.device)
                labels = labels.to(self.device)

                optimizer.zero_grad()

                logits = self.model(images)
                loss = criterion(logits, labels)

                loss.backward()
                optimizer.step()

                training_loss += (
                    loss.item() * images.size(0)
                )

            self.model.eval()

            correct = 0
            total = 0

            with torch.inference_mode():
                for images, labels in val_loader:
                    images = images.to(self.device)
                    labels = labels.to(self.device)

                    predictions = self.model(
                        images
                    ).argmax(dim=1)

                    correct += (
                        predictions == labels
                    ).sum().item()

                    total += labels.size(0)

            accuracy = correct / total

            history.append({
                "epoch": epoch + 1,
                "train_loss": round(
                    training_loss / len(train_dataset),
                    5,
                ),
                "val_accuracy": round(accuracy, 5),
            })

            if accuracy > best_accuracy:
                best_accuracy = accuracy

                best_state = {
                    key: value.detach().cpu().clone()
                    for key, value
                    in self.model.state_dict().items()
                }

        if best_state is not None:
            self.model.load_state_dict(best_state)

        self.model.to(self.device)
        self.model.eval()
        self.trained = True

        return history

    def predict(
        self,
        image_path: str,
        confidence_threshold: float = 0.70,
    ) -> dict:

        if not self.trained:
            raise RuntimeError(
                "Train or load a checkpoint first"
            )

        if not 0 <= confidence_threshold <= 1:
            raise ValueError(
                "Threshold must be between 0 and 1"
            )

        path = Path(image_path)

        if not path.is_file():
            raise FileNotFoundError(path)

        try:
            with Image.open(path) as source:
                image = source.convert("RGB")
                tensor = self.eval_transform(image)
        except (
            UnidentifiedImageError,
            OSError,
        ) as exc:
            raise ValueError(
                "Unsupported or invalid image"
            ) from exc

        tensor = tensor.unsqueeze(0).to(
            self.device
        )

        self.model.eval()

        with torch.inference_mode():
            logits = self.model(tensor)
            probabilities = torch.softmax(
                logits, dim=1
            )[0]

        confidence, index = torch.max(
            probabilities, dim=0
        )

        score = float(confidence.item())
        label = self.class_names[index.item()]

        return {
            "predicted_class": (
                label
                if score >= confidence_threshold
                else None
            ),
            "top_class": label,
            "confidence": round(score, 4),
            "requires_review": (
                score < confidence_threshold
            ),
            "class_probabilities": {
                name: round(float(prob), 4)
                for name, prob in zip(
                    self.class_names,
                    probabilities.cpu().tolist(),
                )
            },
            "model_type": "resnet18",
            "human_verification_required": True,
        }

    def save(self, checkpoint_path: str) -> None:
        if not self.trained:
            raise RuntimeError(
                "No trained model to save"
            )

        path = Path(checkpoint_path)
        path.parent.mkdir(
            parents=True, exist_ok=True
        )

        torch.save({
            "model_state": self.model.state_dict(),
            "class_names": self.class_names,
            "architecture": "resnet18",
        }, path)

    @classmethod
    def load(
        cls,
        checkpoint_path: str,
        device: str | None = None,
    ) -> "RetailImageClassifier":

        # Only load checkpoints from trusted sources.
        checkpoint = torch.load(
            checkpoint_path,
            map_location="cpu",
            weights_only=True,
        )

        if checkpoint.get("architecture") != "resnet18":
            raise ValueError("Unsupported architecture")

        classifier = cls(
            class_names=checkpoint["class_names"],
            pretrained=False,
            device=device,
        )

        classifier.model.load_state_dict(
            checkpoint["model_state"]
        )

        classifier.model.eval()
        classifier.trained = True

        return classifier
