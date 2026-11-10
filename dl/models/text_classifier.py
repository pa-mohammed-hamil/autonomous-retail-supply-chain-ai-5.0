
"""
ai/nlp/text_classifier.py

Autonomous Retail Supply Chain AI 5.0

Transformer-based retail text classification.

Python 3.10+

Dependencies:
    torch
    transformers
    scikit-learn

Supports:
    - Fine-tuning
    - Validation
    - Single-text inference
    - Batch inference
    - Confidence thresholds
    - Model checkpointing

This model provides advisory predictions.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import torch

from torch import nn
from torch.utils.data import (
    Dataset,
    DataLoader,
)

from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
)

from sklearn.metrics import (
    accuracy_score,
    f1_score,
    classification_report,
)


DEFAULT_LABELS = [
    "billing_issue",
    "delivery_issue",
    "general_feedback",
    "product_quality",
    "supplier_issue",
]


class TextDataset(Dataset):

    def __init__(
        self,
        texts: list[str],
        labels: list[int],
        tokenizer,
        max_length: int = 256,
    ):
        if len(texts) != len(labels):
            raise ValueError(
                "Texts and labels length mismatch"
            )

        self.texts = texts
        self.labels = labels
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self):
        return len(self.texts)

    def __getitem__(self, index):

        encoded = self.tokenizer(
            self.texts[index],
            truncation=True,
            padding="max_length",
            max_length=self.max_length,
            return_tensors="pt",
        )

        return {
            "input_ids": encoded[
                "input_ids"
            ].squeeze(0),
            "attention_mask": encoded[
                "attention_mask"
            ].squeeze(0),
            "labels": torch.tensor(
                self.labels[index],
                dtype=torch.long,
            ),
        }


class RetailTextClassifier:

    def __init__(
        self,
        labels: list[str] | None = None,
        model_name: str = "distilbert-base-uncased",
        max_length: int = 256,
        device: str | None = None,
        initialize_model: bool = True,
    ):
        self.labels = (
            list(labels)
            if labels is not None
            else list(DEFAULT_LABELS)
        )

        if (
            len(self.labels) < 2
            or len(set(self.labels)) != len(self.labels)
            or any(
                not isinstance(label, str)
                or not label.strip()
                for label in self.labels
            )
        ):
            raise ValueError(
                "Provide at least two unique labels"
            )

        if (
            isinstance(max_length, bool)
            or not isinstance(max_length, int)
            or not 8 <= max_length <= 512
        ):
            raise ValueError(
                "max_length must be 8 to 512"
            )

        self.model_name = model_name
        self.max_length = max_length

        self.device = torch.device(
            device or (
                "cuda"
                if torch.cuda.is_available()
                else "cpu"
            )
        )

        self.label_to_id = {
            label: index
            for index, label in enumerate(
                self.labels
            )
        }

        self.id_to_label = {
            index: label
            for label, index in (
                self.label_to_id.items()
            )
        }

        self.tokenizer = None
        self.model = None
        self.trained = False

        if initialize_model:
            self._initialize()

    def _initialize(self):

        self.tokenizer = (
            AutoTokenizer.from_pretrained(
                self.model_name
            )
        )

        self.model = (
            AutoModelForSequenceClassification
            .from_pretrained(
                self.model_name,
                num_labels=len(self.labels),
                id2label=self.id_to_label,
                label2id=self.label_to_id,
            )
        )

        self.model.to(self.device)

    def _validate_examples(
        self,
        texts: list[str],
        labels: list[str],
    ) -> list[int]:

        if (
            not isinstance(texts, list)
            or not isinstance(labels, list)
            or len(texts) != len(labels)
            or not texts
        ):
            raise ValueError(
                "Invalid training examples"
            )

        if any(
            not isinstance(text, str)
            or not text.strip()
            for text in texts
        ):
            raise ValueError(
                "Texts must be nonempty strings"
            )

        if any(
            label not in self.label_to_id
            for label in labels
        ):
            raise ValueError(
                "Unknown classification label"
            )

        return [
            self.label_to_id[label]
            for label in labels
        ]

    def train(
        self,
        train_texts: list[str],
        train_labels: list[str],
        val_texts: list[str],
        val_labels: list[str],
        epochs: int = 3,
        batch_size: int = 8,
        learning_rate: float = 2e-5,
    ) -> list[dict]:

        if (
            isinstance(epochs, bool)
            or not isinstance(epochs, int)
            or epochs <= 0
        ):
            raise ValueError("Invalid epochs")

        if (
            isinstance(batch_size, bool)
            or not isinstance(batch_size, int)
            or batch_size <= 0
        ):
            raise ValueError("Invalid batch_size")

        if (
            isinstance(learning_rate, bool)
            or not isinstance(
                learning_rate, (int, float)
            )
            or not math.isfinite(
                learning_rate
            )
            or not 0 < learning_rate < 1
        ):
            raise ValueError(
                "Invalid learning_rate"
            )

        train_ids = self._validate_examples(
            train_texts,
            train_labels,
        )

        val_ids = self._validate_examples(
            val_texts,
            val_labels,
        )

        train_dataset = TextDataset(
            train_texts,
            train_ids,
            self.tokenizer,
            self.max_length,
        )

        val_dataset = TextDataset(
            val_texts,
            val_ids,
            self.tokenizer,
            self.max_length,
        )

        train_loader = DataLoader(
            train_dataset,
            batch_size=batch_size,
            shuffle=True,
        )

        val_loader = DataLoader(
            val_dataset,
            batch_size=batch_size,
            shuffle=False,
        )

        optimizer = torch.optim.AdamW(
            self.model.parameters(),
            lr=learning_rate,
        )

        history = []

        best_f1 = -1.0
        best_state = None

        for epoch in range(epochs):

            self.model.train()

            total_loss = 0.0
            total_examples = 0

            for batch in train_loader:

                optimizer.zero_grad()

                inputs = {
                    key: value.to(self.device)
                    for key, value in batch.items()
                }

                outputs = self.model(**inputs)

                loss = outputs.loss

                loss.backward()

                nn.utils.clip_grad_norm_(
                    self.model.parameters(),
                    max_norm=1.0,
                )

                optimizer.step()

                batch_size_actual = (
                    inputs["labels"].size(0)
                )

                total_loss += (
                    loss.item()
                    * batch_size_actual
                )

                total_examples += (
                    batch_size_actual
                )

            metrics = self._evaluate_loader(
                val_loader
            )

            history.append({
                "epoch": epoch + 1,
                "train_loss": round(
                    total_loss / total_examples,
                    5,
                ),
                "val_accuracy": metrics[
                    "accuracy"
                ],
                "val_macro_f1": metrics[
                    "macro_f1"
                ],
            })

            if metrics["macro_f1"] > best_f1:
                best_f1 = metrics["macro_f1"]

                best_state = {
                    key: value.detach()
                    .cpu()
                    .clone()
                    for key, value
                    in self.model.state_dict().items()
                }

        if best_state is not None:
            self.model.load_state_dict(
                best_state
            )

        self.model.to(self.device)
        self.model.eval()

        self.trained = True

        return history

    def _evaluate_loader(
        self,
        loader: DataLoader,
    ) -> dict:

        self.model.eval()

        actual = []
        predicted = []

        with torch.inference_mode():

            for batch in loader:

                inputs = {
                    key: value.to(self.device)
                    for key, value in batch.items()
                }

                outputs = self.model(**inputs)

                predictions = (
                    outputs.logits.argmax(
                        dim=-1
                    )
                )

                predicted.extend(
                    predictions.cpu().tolist()
                )

                actual.extend(
                    inputs["labels"]
                    .cpu()
                    .tolist()
                )

        return {
            "accuracy": round(
                accuracy_score(
                    actual, predicted
                ),
                4,
            ),
            "macro_f1": round(
                f1_score(
                    actual,
                    predicted,
                    average="macro",
                    zero_division=0,
                ),
                4,
            ),
            "classification_report": (
                classification_report(
                    actual,
                    predicted,
                    labels=list(
                        range(len(self.labels))
                    ),
                    target_names=self.labels,
                    zero_division=0,
                    output_dict=True,
                )
            ),
        }

    def predict(
        self,
        text: str,
        confidence_threshold: float = 0.70,
    ) -> dict:

        if not self.trained:
            raise RuntimeError(
                "Train or load a model first"
            )

        if (
            not isinstance(text, str)
            or not text.strip()
        ):
            raise ValueError(
                "Text cannot be empty"
            )

        if (
            isinstance(confidence_threshold, bool)
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

        encoded = self.tokenizer(
            text,
            truncation=True,
            padding=True,
            max_length=self.max_length,
            return_tensors="pt",
        )

        encoded = {
            key: value.to(self.device)
            for key, value in encoded.items()
        }

        self.model.eval()

        with torch.inference_mode():

            outputs = self.model(**encoded)

            probabilities = torch.softmax(
                outputs.logits,
                dim=-1,
            )[0]

        confidence, index = torch.max(
            probabilities,
            dim=0,
        )

        score = float(
            confidence.item()
        )

        label = self.id_to_label[
            index.item()
        ]

        return {
            "predicted_label": (
                label
                if score >= confidence_threshold
                else None
            ),
            "top_label": label,
            "confidence": round(score, 4),
            "requires_review": (
                score < confidence_threshold
            ),
            "probabilities": {
                name: round(
                    float(probability), 4
                )
                for name, probability in zip(
                    self.labels,
                    probabilities.cpu().tolist(),
                )
            },
            "model": self.model_name,
            "human_review_recommended": True,
        }

    def predict_batch(
        self,
        texts: list[str],
        confidence_threshold: float = 0.70,
    ) -> list[dict]:

        if (
            not isinstance(texts, list)
            or len(texts) > 100
        ):
            raise ValueError(
                "Maximum 100 texts per batch"
            )

        return [
            self.predict(
                text,
                confidence_threshold,
            )
            for text in texts
        ]

    def save(self, directory: str) -> None:

        if not self.trained:
            raise RuntimeError(
                "No trained model to save"
            )

        destination = Path(directory)
        destination.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.model.save_pretrained(
            destination,
            safe_serialization=True,
        )

        self.tokenizer.save_pretrained(
            destination
        )

        metadata = {
            "labels": self.labels,
            "max_length": self.max_length,
            "model_name": self.model_name,
        }

        (
            destination / "retail_metadata.json"
        ).write_text(
            json.dumps(
                metadata,
                indent=2,
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(
        cls,
        directory: str,
        device: str | None = None,
    ) -> "RetailTextClassifier":

        source = Path(directory)

        metadata = json.loads(
            (
                source / "retail_metadata.json"
            ).read_text(
                encoding="utf-8"
            )
        )

        classifier = cls(
            labels=metadata["labels"],
            model_name=metadata["model_name"],
            max_length=metadata["max_length"],
            device=device,
            initialize_model=False,
        )

        classifier.tokenizer = (
            AutoTokenizer.from_pretrained(
                str(source),
                local_files_only=True,
            )
        )

        classifier.model = (
            AutoModelForSequenceClassification
            .from_pretrained(
                str(source),
                local_files_only=True,
                use_safetensors=True,
            )
        )

        if (
            classifier.model.config.num_labels
            != len(classifier.labels)
        ):
            raise ValueError(
                "Checkpoint label mismatch"
            )

        classifier.model.to(
            classifier.device
        )

        classifier.model.eval()
        classifier.trained = True

        return classifier
