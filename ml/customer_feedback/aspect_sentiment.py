"""Planned module: aspect sentiment. Implementation pending."""

"""
ai/feedback/aspect_sentiment.py

Autonomous Retail Supply Chain AI 5.0

Aspect-Based Sentiment Analysis

Features:
- Aspect extraction
- Positive / negative / neutral sentiment
- Delivery, product, quality, pricing,
  packaging, support, refund and inventory
- Sentence-level sentiment
- Aspect-level sentiment
- Batch processing
- CSV input
- JSON output

Baseline: lexicon and rule-based.
No external dependencies.
"""

from __future__ import annotations

import csv
import json
import re

from collections import Counter, defaultdict
from pathlib import Path
from typing import Sequence


class AspectSentimentAnalyzer:

    ASPECTS = {
        "delivery": {
            "delivery", "shipping", "shipment",
            "courier", "late", "delay", "arrived",
            "transport",
        },
        "product": {
            "product", "item", "goods",
            "purchase", "order",
        },
        "quality": {
            "quality", "defective", "broken",
            "damaged", "durable", "faulty",
        },
        "pricing": {
            "price", "pricing", "cost",
            "expensive", "cheap", "discount",
        },
        "packaging": {
            "packaging", "package", "packing",
            "box", "sealed",
        },
        "customer_support": {
            "support", "service", "agent",
            "staff", "representative",
            "helpdesk",
        },
        "refund": {
            "refund", "return", "reimbursement",
            "moneyback",
        },
        "inventory": {
            "stock", "availability",
            "unavailable", "outofstock",
            "restock", "inventory",
        },
    }

    POSITIVE = {
        "good", "great", "excellent",
        "amazing", "fast", "quick",
        "perfect", "reliable", "helpful",
        "friendly", "affordable",
        "satisfied", "happy", "smooth",
        "durable", "safe", "fresh",
    }

    NEGATIVE = {
        "bad", "poor", "terrible",
        "awful", "slow", "late",
        "delayed", "delay", "broken",
        "damaged", "defective", "faulty",
        "expensive", "unavailable",
        "rude", "worst", "missing",
        "unhappy", "disappointed",
        "unreliable", "unsafe",
    }

    NEGATIONS = {
        "not", "never", "no", "hardly",
        "barely", "isnt", "wasnt",
        "dont", "didnt",
    }

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return re.findall(
            r"[a-z0-9]+",
            text.lower(),
        )

    @staticmethod
    def _sentences(text: str) -> list[str]:
        return [
            sentence.strip()
            for sentence in re.split(
                r"(?<=[.!?])\s+|[;\n]+",
                text.strip(),
            )
            if sentence.strip()
        ]

    @classmethod
    def _sentiment_score(
        cls,
        tokens: list[str],
    ) -> int:
        score = 0

        for index, token in enumerate(tokens):
            polarity = 0

            if token in cls.POSITIVE:
                polarity = 1
            elif token in cls.NEGATIVE:
                polarity = -1

            if polarity == 0:
                continue

            # Simple local negation heuristic.
            window = tokens[
                max(0, index - 3):index
            ]

            if any(
                word in cls.NEGATIONS
                for word in window
            ):
                polarity *= -1

            score += polarity

        return score

    @staticmethod
    def _label(score: int) -> str:
        if score > 0:
            return "positive"
        if score < 0:
            return "negative"
        return "neutral"

    @classmethod
    def analyze(
        cls,
        text: str,
    ) -> dict:
        if not isinstance(text, str):
            raise TypeError(
                "Feedback must be a string"
            )

        if not text.strip():
            raise ValueError(
                "Feedback cannot be empty"
            )

        aspect_scores = defaultdict(list)
        sentence_reports = []

        for sentence in cls._sentences(text):
            tokens = cls._tokens(sentence)
            token_set = set(tokens)

            detected_aspects = [
                aspect
                for aspect, keywords
                in cls.ASPECTS.items()
                if token_set & keywords
            ]

            score = cls._sentiment_score(tokens)
            label = cls._label(score)

            sentence_reports.append({
                "sentence": sentence,
                "aspects": detected_aspects,
                "sentiment": label,
                "sentiment_score": score,
            })

            for aspect in detected_aspects:
                aspect_scores[aspect].append(score)

        aspect_results = {}

        for aspect, scores in aspect_scores.items():
            total_score = sum(scores)

            aspect_results[aspect] = {
                "sentiment": cls._label(
                    total_score
                ),
                "sentiment_score": total_score,
                "mentions": len(scores),
            }

        overall_score = sum(
            item["sentiment_score"]
            for item in sentence_reports
        )

        return {
            "text": text,
            "overall_sentiment": cls._label(
                overall_score
            ),
            "overall_sentiment_score": (
                overall_score
            ),
            "detected_aspects": sorted(
                aspect_results
            ),
            "aspect_sentiments": (
                aspect_results
            ),
            "sentence_reports": (
                sentence_reports
            ),
        }

    @classmethod
    def analyze_batch(
        cls,
        feedback: Sequence[str],
    ) -> dict:
        if not feedback:
            raise ValueError(
                "Empty feedback dataset"
            )

        results = [
            cls.analyze(text)
            for text in feedback
        ]

        counts = Counter(
            result["overall_sentiment"]
            for result in results
        )

        return {
            "total_feedback": len(results),
            "sentiment_distribution": dict(
                counts
            ),
            "results": results,
        }

    @classmethod
    def analyze_csv(
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

        feedback = [
            row[text_column]
            for row in rows
        ]

        return cls.analyze_batch(feedback)

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
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    examples = [
        (
            "The delivery was late, but "
            "the product quality was excellent."
        ),
        (
            "Customer support was helpful "
            "and the refund was quick."
        ),
        (
            "The package was damaged "
            "and the price was expensive."
        ),
    ]

    analyzer = AspectSentimentAnalyzer()

    report = analyzer.analyze_batch(examples)

    print(json.dumps(report, indent=2))
