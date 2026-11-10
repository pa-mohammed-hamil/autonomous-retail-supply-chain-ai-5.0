"""Planned module: feedback features. Implementation pending."""

"""
ai/features/feedback_features.py

Autonomous Retail Supply Chain AI 5.0

Customer Feedback Feature Engineering

Features:
- Text normalization
- Tokenization
- Word and character counts
- Average word length
- Positive/negative keyword counts
- Negation indicators
- Complaint keyword counts
- Question/exclamation counts
- TF-IDF vectorization
- Fit/transform separation
- Batch processing
- CSV/JSON export

Python 3.10+
Standard library only.
"""

from __future__ import annotations

import csv
import json
import math
import re

from collections import Counter
from pathlib import Path
from typing import Sequence


class FeedbackFeatureEngineer:

    POSITIVE_WORDS = {
        "excellent", "amazing", "great",
        "good", "perfect", "happy",
        "satisfied", "helpful", "reliable",
        "fast", "affordable", "friendly",
    }

    NEGATIVE_WORDS = {
        "bad", "poor", "terrible",
        "awful", "broken", "damaged",
        "defective", "delayed", "late",
        "missing", "rude", "unsafe",
        "disappointed", "expensive",
    }

    NEGATION_WORDS = {
        "not", "never", "no", "cannot",
        "cant", "dont", "didnt",
        "isnt", "wasnt",
    }

    COMPLAINT_WORDS = {
        "refund", "return", "damaged",
        "broken", "defective", "delay",
        "delayed", "missing", "wrong",
        "fraud", "unsafe", "complaint",
        "unavailable", "cancelled",
    }

    def __init__(
        self,
        max_features: int = 100,
        min_df: int = 1,
    ):
        if (
            isinstance(max_features, bool)
            or not isinstance(max_features, int)
            or max_features < 1
        ):
            raise ValueError(
                "max_features must be positive"
            )

        if (
            isinstance(min_df, bool)
            or not isinstance(min_df, int)
            or min_df < 1
        ):
            raise ValueError(
                "min_df must be positive"
            )

        self.max_features = max_features
        self.min_df = min_df

        self.vocabulary = {}
        self.idf = {}
        self.fitted = False

    @staticmethod
    def tokenize(text: str) -> list[str]:
        if not isinstance(text, str):
            raise TypeError(
                "Feedback must be a string"
            )

        return re.findall(
            r"[a-z0-9]+",
            text.lower(),
        )

    @classmethod
    def basic_features(
        cls,
        text: str,
    ) -> dict:
        tokens = cls.tokenize(text)
        counts = Counter(tokens)

        word_count = len(tokens)
        unique_count = len(counts)

        average_word_length = (
            sum(len(token) for token in tokens)
            / word_count
            if word_count else 0.0
        )

        positive_count = sum(
            counts[word]
            for word in cls.POSITIVE_WORDS
        )

        negative_count = sum(
            counts[word]
            for word in cls.NEGATIVE_WORDS
        )

        complaint_count = sum(
            counts[word]
            for word in cls.COMPLAINT_WORDS
        )

        negation_count = sum(
            counts[word]
            for word in cls.NEGATION_WORDS
        )

        return {
            "character_count": len(text),
            "word_count": word_count,
            "unique_word_count": unique_count,
            "average_word_length": round(
                average_word_length, 4
            ),
            "lexical_diversity": round(
                unique_count / word_count,
                4,
            ) if word_count else 0.0,
            "positive_word_count": positive_count,
            "negative_word_count": negative_count,
            "complaint_word_count": complaint_count,
            "negation_count": negation_count,
            "exclamation_count": text.count("!"),
            "question_count": text.count("?"),
            "uppercase_ratio": round(
                sum(c.isupper() for c in text)
                / len(text),
                4,
            ) if text else 0.0,
        }

    def fit(
        self,
        texts: Sequence[str],
    ) -> "FeedbackFeatureEngineer":
        if isinstance(texts, (str, bytes)):
            raise TypeError(
                "Expected a sequence of strings"
            )

        if not texts:
            raise ValueError(
                "Cannot fit an empty dataset"
            )

        documents = [
            self.tokenize(text)
            for text in texts
        ]

        document_frequency = Counter()

        for tokens in documents:
            document_frequency.update(
                set(tokens)
            )

        candidates = [
            (term, frequency)
            for term, frequency
            in document_frequency.items()
            if frequency >= self.min_df
        ]

        candidates.sort(
            key=lambda item: (
                -item[1],
                item[0],
            )
        )

        selected = candidates[
            :self.max_features
        ]

        if not selected:
            raise ValueError(
                "No vocabulary terms meet min_df"
            )

        self.vocabulary = {
            term: index
            for index, (term, _)
            in enumerate(selected)
        }

        n_documents = len(documents)

        self.idf = {
            term: (
                math.log(
                    (1 + n_documents)
                    / (1 + document_frequency[term])
                ) + 1
            )
            for term in self.vocabulary
        }

        self.fitted = True
        return self

    def transform_one(
        self,
        text: str,
    ) -> dict:
        if not self.fitted:
            raise RuntimeError(
                "Call fit() before transform()"
            )

        features = self.basic_features(text)
        counts = Counter(
            self.tokenize(text)
        )

        weights = {}

        for term in self.vocabulary:
            tf = counts.get(term, 0)

            weights[term] = (
                (1 + math.log(tf))
                * self.idf[term]
                if tf > 0 else 0.0
            )

        norm = math.sqrt(
            sum(
                value * value
                for value in weights.values()
            )
        )

        for term, index in self.vocabulary.items():
            features[f"tfidf_{index}"] = round(
                weights[term] / norm,
                6,
            ) if norm else 0.0

        return features

    def transform(
        self,
        texts: Sequence[str],
    ) -> list[dict]:
        return [
            self.transform_one(text)
            for text in texts
        ]

    def fit_transform(
        self,
        texts: Sequence[str],
    ) -> list[dict]:
        self.fit(texts)
        return self.transform(texts)

    def enrich_records(
        self,
        records: Sequence[dict],
        text_column: str = "text",
    ) -> list[dict]:
        return [
            {
                **record,
                **self.transform_one(
                    record[text_column]
                ),
            }
            for record in records
        ]

    def feature_names(self) -> list[str]:
        if not self.fitted:
            raise RuntimeError(
                "Feature engineer not fitted"
            )

        return [
            term
            for term, _ in sorted(
                self.vocabulary.items(),
                key=lambda item: item[1],
            )
        ]

    @staticmethod
    def save_csv(
        records: list[dict],
        path: str,
    ) -> None:
        if not records:
            raise ValueError(
                "Cannot save empty records"
            )

        output = Path(path)
        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        fields = list(dict.fromkeys(
            key
            for record in records
            for key in record
        ))

        with output.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=fields,
            )
            writer.writeheader()
            writer.writerows(records)

    @staticmethod
    def save_json(
        records: list[dict],
        path: str,
    ) -> None:
        output = Path(path)
        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            json.dumps(
                records,
                indent=2,
                ensure_ascii=False,
                allow_nan=False,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    training_feedback = [
        "The product quality is excellent.",
        "The delivery was very late.",
        "The product arrived damaged.",
        "Customer support was helpful.",
        "My refund is delayed.",
    ]

    engineer = FeedbackFeatureEngineer(
        max_features=30
    )

    features = engineer.fit_transform(
        training_feedback
    )

    for text, row in zip(
        training_feedback, features
    ):
        print(text)
        print(json.dumps(row, indent=2))

    engineer.save_json(
        features,
        "data/features/feedback_features.json",
    )
