"""Planned module: sentiment classifier. Implementation pending."""

"""
ai/feedback/sentiment_classifier.py

Retail Customer Sentiment Classifier

Features:
- Positive / negative / neutral
- Local negation handling
- Intensifier handling
- Sentiment scores
- Confidence proxy
- Batch processing
- CSV input
- JSON output

Standard library only.
"""

from __future__ import annotations

import csv
import json
import re

from collections import Counter
from pathlib import Path
from typing import Sequence


class SentimentClassifier:

    POSITIVE = {
        "excellent": 3,
        "amazing": 3,
        "perfect": 3,
        "fantastic": 3,
        "great": 2,
        "good": 2,
        "happy": 2,
        "satisfied": 2,
        "helpful": 2,
        "reliable": 2,
        "fast": 1,
        "quick": 1,
        "affordable": 2,
        "smooth": 1,
        "fresh": 1,
        "friendly": 2,
        "love": 3,
    }

    NEGATIVE = {
        "terrible": -3,
        "awful": -3,
        "worst": -3,
        "horrible": -3,
        "bad": -2,
        "poor": -2,
        "broken": -3,
        "damaged": -3,
        "defective": -3,
        "faulty": -3,
        "disappointed": -2,
        "unhappy": -2,
        "rude": -2,
        "slow": -1,
        "late": -2,
        "delayed": -2,
        "expensive": -1,
        "missing": -2,
        "unreliable": -2,
        "unsafe": -3,
        "hate": -3,
    }

    NEGATIONS = {
        "not", "never", "no",
        "isnt", "wasnt", "dont",
        "didnt", "cannot", "cant",
    }

    INTENSIFIERS = {
        "very": 1.5,
        "extremely": 2.0,
        "really": 1.3,
        "super": 1.5,
        "slightly": 0.5,
        "somewhat": 0.7,
    }

    CONTRAST_WORDS = {
        "but", "however", "although",
    }

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return re.findall(
            r"[a-z0-9]+",
            text.lower(),
        )

    @staticmethod
    def _label(score: float) -> str:
        if score > 0:
            return "positive"
        if score < 0:
            return "negative"
        return "neutral"

    @classmethod
    def classify(cls, text: str) -> dict:
        if not isinstance(text, str):
            raise TypeError(
                "Text must be a string"
            )

        if not text.strip():
            raise ValueError(
                "Text cannot be empty"
            )

        tokens = cls._tokens(text)
        score = 0.0
        evidence = []

        # A simple contrast heuristic:
        # sentiment after "but" receives
        # greater weight.
        contrast_positions = [
            i for i, token in enumerate(tokens)
            if token in cls.CONTRAST_WORDS
        ]

        last_contrast = (
            contrast_positions[-1]
            if contrast_positions else None
        )

        for index, token in enumerate(tokens):
            polarity = cls.POSITIVE.get(
                token,
                cls.NEGATIVE.get(token, 0),
            )

            if polarity == 0:
                continue

            previous = tokens[
                max(0, index - 3):index
            ]

            negation_count = sum(
                word in cls.NEGATIONS
                for word in previous
            )

            if negation_count % 2 == 1:
                polarity *= -1

            if index > 0:
                multiplier = cls.INTENSIFIERS.get(
                    tokens[index - 1], 1.0
                )
                polarity *= multiplier

            if (
                last_contrast is not None
                and index > last_contrast
            ):
                polarity *= 1.5

            score += polarity

            evidence.append({
                "term": token,
                "contribution": round(
                    polarity, 3
                ),
            })

        # Heuristic strength, not a
        # calibrated model probability.
        absolute_evidence = sum(
            abs(item["contribution"])
            for item in evidence
        )

        confidence_proxy = (
            abs(score) / absolute_evidence
            if absolute_evidence else 0.0
        )

        return {
            "text": text,
            "sentiment": cls._label(score),
            "sentiment_score": round(
                score, 4
            ),
            "confidence_proxy": round(
                confidence_proxy, 4
            ),
            "matched_terms": evidence,
            "classification_method": (
                "rule_based_lexicon"
            ),
        }

    @classmethod
    def classify_batch(
        cls,
        texts: Sequence[str],
    ) -> dict:
        if not texts:
            raise ValueError(
                "Empty sentiment dataset"
            )

        results = [
            cls.classify(text)
            for text in texts
        ]

        distribution = Counter(
            item["sentiment"]
            for item in results
        )

        return {
            "total_feedback": len(results),
            "sentiment_distribution": {
                label: distribution[label]
                for label in (
                    "positive",
                    "neutral",
                    "negative",
                )
            },
            "results": results,
        }

    @classmethod
    def classify_csv(
        cls,
        path: str,
        text_column: str = "feedback",
    ) -> dict:
        with open(
            path,
            newline="",
            encoding="utf-8-sig",
        ) as file:
            rows = list(csv.DictReader(file))

        return cls.classify_batch([
            row[text_column]
            for row in rows
        ])

    @staticmethod
    def save_report(
        report: dict,
        output_path: str,
    ) -> None:
        path = Path(output_path)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            json.dumps(
                report,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    examples = [
        "The product quality is excellent.",
        "The delivery was very late.",
        "The support team was not helpful.",
        "The price was high but delivery was great.",
        "My order has arrived.",
    ]

    report = SentimentClassifier.classify_batch(
        examples
    )

    print(json.dumps(report, indent=2))
