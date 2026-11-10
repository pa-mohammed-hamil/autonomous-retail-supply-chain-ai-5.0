
"""
ai/mlops/model_cards.py

Generate and validate retail AI model cards.

Supported tasks:
- Object detection
- Image classification
- Demand forecasting
- Text classification

Exports JSON and Markdown documentation.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class ModelCard:
    model_name: str
    version: str
    task: str
    description: str
    intended_use: list[str]
    limitations: list[str]
    dataset_id: str
    dataset_version: str
    metrics: dict[str, float]

    framework: str = "unknown"
    model_architecture: str = "unknown"
    training_method: str = "unknown"
    evaluation_protocol: str = "not_documented"

    excluded_uses: list[str] = field(
        default_factory=list
    )
    risks: list[str] = field(
        default_factory=list
    )
    mitigations: list[str] = field(
        default_factory=list
    )
    fairness_evaluation: dict[str, Any] = field(
        default_factory=dict
    )
    monitoring_plan: list[str] = field(
        default_factory=list
    )

    created_at: str = field(
        default_factory=lambda: (
            datetime.now(timezone.utc).isoformat()
        )
    )


class ModelCardManager:

    ALLOWED_TASKS = {
        "object_detection",
        "image_classification",
        "demand_forecasting",
        "text_classification",
    }

    SAFE_NAME = re.compile(
        r"^[A-Za-z0-9_.-]{1,128}$"
    )

    def __init__(
        self,
        output_dir: str = (
            "storage/mlops/model_cards"
        ),
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    def validate(
        self,
        card: ModelCard,
    ) -> None:

        if not self.SAFE_NAME.fullmatch(
            card.model_name
        ):
            raise ValueError(
                "Invalid model name"
            )

        if not self.SAFE_NAME.fullmatch(
            card.version
        ):
            raise ValueError(
                "Invalid model version"
            )

        if card.task not in self.ALLOWED_TASKS:
            raise ValueError(
                "Unsupported model task"
            )

        if not card.description.strip():
            raise ValueError(
                "Description is required"
            )

        if not card.intended_use:
            raise ValueError(
                "Intended use is required"
            )

        if not card.limitations:
            raise ValueError(
                "Model limitations are required"
            )

        if not card.dataset_id or not card.dataset_version:
            raise ValueError(
                "Dataset provenance is required"
            )

        if not card.metrics:
            raise ValueError(
                "Evaluation metrics are required"
            )

        for name, value in card.metrics.items():
            if (
                not isinstance(name, str)
                or not name
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(
                    "Invalid evaluation metric"
                )

    def save(
        self,
        card: ModelCard,
    ) -> dict:

        self.validate(card)

        model_dir = (
            self.output_dir
            / card.model_name
            / card.version
        )

        model_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        json_path = model_dir / "model_card.json"
        markdown_path = model_dir / "README.md"

        data = asdict(card)

        json_path.write_text(
            json.dumps(
                data,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            ),
            encoding="utf-8",
        )

        def lines(items):
            return "\n".join(
                f"- {item}"
                for item in items
            ) or "- Not documented"

        metrics_md = "\n".join(
            f"- **{name}:** {value}"
            for name, value in card.metrics.items()
        )

        markdown = f"""# {card.model_name}

**Version:** {card.version}
**Task:** {card.task}
**Framework:** {card.framework}
**Architecture:** {card.model_architecture}

## Description

{card.description}

## Intended Use

{lines(card.intended_use)}

## Excluded Uses

{lines(card.excluded_uses)}

## Dataset

- Dataset: {card.dataset_id}
- Version: {card.dataset_version}
- Training method: {card.training_method}
- Evaluation protocol: {card.evaluation_protocol}

## Evaluation Metrics

{metrics_md}

## Limitations

{lines(card.limitations)}

## Risks

{lines(card.risks)}

## Mitigations

{lines(card.mitigations)}

## Monitoring Plan

{lines(card.monitoring_plan)}

## Fairness Evaluation

```json
{json.dumps(card.fairness_evaluation, indent=2)}
```

## Documentation Timestamp

{card.created_at}
"""

        markdown_path.write_text(
            markdown,
            encoding="utf-8",
        )

        return {
            "model_name": card.model_name,
            "version": card.version,
            "json_path": str(json_path),
            "markdown_path": str(markdown_path),
        }

    def load(
        self,
        model_name: str,
        version: str,
    ) -> ModelCard:

        if (
            not self.SAFE_NAME.fullmatch(model_name)
            or not self.SAFE_NAME.fullmatch(version)
        ):
            raise ValueError(
                "Invalid model identifier"
            )

        path = (
            self.output_dir
            / model_name
            / version
            / "model_card.json"
        )

        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        return ModelCard(**data)
