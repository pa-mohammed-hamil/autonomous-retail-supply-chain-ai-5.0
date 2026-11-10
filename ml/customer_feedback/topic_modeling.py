"""Planned module: topic modeling. Implementation pending."""

"""
ai/feedback/topic_modeling.py

Autonomous Retail Supply Chain AI 5.0

Customer Feedback Topic Modeling

Features:
- Unsupervised topic discovery
- TF-IDF vectorization
- NMF topic modeling
- Top keywords per topic
- Dominant topic per feedback
- Topic distribution
- Topic diversity
- Representative feedback examples
- Batch analysis
- CSV input
- JSON report export

Dependencies:
    pip install numpy scikit-learn

Python 3.10+
"""

from __future__ import annotations

import csv
import json
import math

from collections import Counter
from pathlib import Path
from typing import Sequence

import numpy as np

from sklearn.decomposition import NMF
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize


class FeedbackTopicModeler:

    def __init__(
        self,
        n_topics: int = 5,
        top_words: int = 8,
        max_features: int = 5000,
        min_df: int = 1,
        max_df: float = 1.0,
        random_state: int = 42,
    ):
        if n_topics < 1:
            raise ValueError(
                "n_topics must be positive"
            )

        if top_words < 1:
            raise ValueError(
                "top_words must be positive"
            )

        if max_features < 1:
            raise ValueError(
                "max_features must be positive"
            )

        if min_df < 1:
            raise ValueError(
                "min_df must be positive"
            )

        if not 0 < max_df <= 1:
            raise ValueError(
                "max_df must be in (0, 1]"
            )

        self.n_topics = n_topics
        self.top_words = top_words
        self.random_state = random_state

        self.vectorizer = TfidfVectorizer(
            stop_words="english",
            lowercase=True,
            strip_accents="unicode",
            ngram_range=(1, 2),
            max_features=max_features,
            min_df=min_df,
            max_df=max_df,
            sublinear_tf=True,
        )

        self.model = NMF(
            n_components=n_topics,
            init="nndsvda",
            random_state=random_state,
            max_iter=500,
        )

        self._fitted = False

    @staticmethod
    def _validate_texts(
        texts: Sequence[str],
    ) -> list[str]:
        if isinstance(texts, (str, bytes)):
            raise TypeError(
                "Expected a sequence of feedback strings"
            )

        if not texts:
            raise ValueError(
                "Feedback dataset cannot be empty"
            )

        cleaned = []

        for text in texts:
            if not isinstance(text, str):
                raise TypeError(
                    "Each feedback item must be text"
                )

            if not text.strip():
                raise ValueError(
                    "Feedback cannot be empty"
                )

            cleaned.append(text.strip())

        return cleaned

    def fit(
        self,
        texts: Sequence[str],
    ) -> "FeedbackTopicModeler":
        documents = self._validate_texts(texts)

        try:
            matrix = self.vectorizer.fit_transform(
                documents
            )
        except ValueError as exc:
            raise ValueError(
                "Cannot build vocabulary from feedback"
            ) from exc

        max_components = min(matrix.shape)

        if self.n_topics > max_components:
            raise ValueError(
                f"n_topics={self.n_topics} exceeds "
                f"maximum feasible components "
                f"({max_components}) for this dataset"
            )

        self.document_topics_ = (
            self.model.fit_transform(matrix)
        )

        self.feature_names_ = (
            self.vectorizer.get_feature_names_out()
        )

        self.documents_ = documents
        self._fitted = True

        return self

    def get_topics(self) -> list[dict]:
        if not self._fitted:
            raise RuntimeError(
                "Fit the topic model first"
            )

        topics = []

        for index, weights in enumerate(
            self.model.components_
        ):
            top_indices = np.argsort(
                weights
            )[::-1][:self.top_words]

            keywords = [
                {
                    "term": str(
                        self.feature_names_[i]
                    ),
                    "weight": round(
                        float(weights[i]), 6
                    ),
                }
                for i in top_indices
            ]

            topics.append({
                "topic_id": index,
                "topic_name": (
                    " / ".join(
                        keyword["term"]
                        for keyword in keywords[:3]
                    )
                ),
                "keywords": keywords,
            })

        return topics

    def transform(
        self,
        texts: Sequence[str],
    ) -> list[dict]:
        if not self._fitted:
            raise RuntimeError(
                "Fit the topic model first"
            )

        documents = self._validate_texts(texts)

        matrix = self.vectorizer.transform(
            documents
        )

        weights = self.model.transform(matrix)

        # Normalize topic weights to sum to 1.
        # These are relative topic weights,
        # not calibrated probabilities.
        row_sums = weights.sum(
            axis=1,
            keepdims=True,
        )

        normalized_weights = np.divide(
            weights,
            row_sums,
            out=np.zeros_like(weights),
            where=row_sums != 0,
        )

        results = []

        for index, text in enumerate(documents):
            scores = normalized_weights[index]

            if float(scores.sum()) == 0:
                dominant_topic = None
                dominant_weight = 0.0
            else:
                dominant_topic = int(
                    np.argmax(scores)
                )
                dominant_weight = float(
                    np.max(scores)
                )

            results.append({
                "feedback_id": index,
                "text": text,
                "dominant_topic": dominant_topic,
                "dominant_topic_weight": round(
                    dominant_weight, 6
                ),
                "topic_weights": {
                    f"topic_{i}": round(
                        float(score), 6
                    )
                    for i, score in enumerate(scores)
                },
            })

        return results

    def analyze(
        self,
        texts: Sequence[str],
        representative_count: int = 3,
    ) -> dict:
        if representative_count < 1:
            raise ValueError(
                "representative_count must be positive"
            )

        self.fit(texts)

        results = self.transform(
            self.documents_
        )

        topics = self.get_topics()

        distribution = Counter(
            result["dominant_topic"]
            for result in results
            if result["dominant_topic"] is not None
        )

        topic_reports = []

        for topic in topics:
            topic_id = topic["topic_id"]

            matching = [
                result
                for result in results
                if result["dominant_topic"] == topic_id
            ]

            matching.sort(
                key=lambda result: result[
                    "dominant_topic_weight"
                ],
                reverse=True,
            )

            topic_reports.append({
                **topic,
                "feedback_count": (
                    distribution[topic_id]
                ),
                "feedback_percent": round(
                    100 * distribution[topic_id]
                    / len(results),
                    4,
                ),
                "representative_feedback": [
                    {
                        "text": item["text"],
                        "topic_weight": item[
                            "dominant_topic_weight"
                        ],
                    }
                    for item in matching[
                        :representative_count
                    ]
                ],
            })

        # Keyword overlap-based diversity proxy.
        keyword_sets = [
            {
                item["term"]
                for item in topic["keywords"]
            }
            for topic in topics
        ]

        all_keywords = set().union(
            *keyword_sets
        )

        keyword_slots = sum(
            len(words)
            for words in keyword_sets
        )

        diversity = (
            len(all_keywords) / keyword_slots
            if keyword_slots else None
        )

        unassigned = sum(
            item["dominant_topic"] is None
            for item in results
        )

        return {
            "total_feedback": len(results),
            "number_of_topics": self.n_topics,
            "model": "TF-IDF + NMF",
            "topic_diversity_proxy": (
                round(diversity, 6)
                if diversity is not None
                else None
            ),
            "unassigned_feedback": unassigned,
            "topic_distribution": {
                f"topic_{i}": distribution[i]
                for i in range(self.n_topics)
            },
            "topics": topic_reports,
            "feedback_results": results,
        }

    def analyze_csv(
        self,
        path: str,
        text_column: str = "feedback",
    ) -> dict:
        with open(
            path,
            newline="",
            encoding="utf-8-sig",
        ) as file:
            rows = list(csv.DictReader(file))

        return self.analyze([
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
    feedback = [
        "My delivery was late and shipping was slow.",
        "The courier delayed my package again.",
        "Shipping was fast and delivery was excellent.",
        "The product arrived damaged and broken.",
        "Product quality is poor and defective.",
        "The item stopped working after one day.",
        "Customer support was rude and unhelpful.",
        "The support agent solved my problem quickly.",
        "Customer service never answered my complaint.",
        "The refund is delayed and money was not returned.",
        "I requested a return but received no refund.",
        "The refund process was slow and frustrating.",
        "The item price is too expensive.",
        "The product costs more than other stores.",
        "The discount and pricing are excellent.",
    ]

    modeler = FeedbackTopicModeler(
        n_topics=5,
        top_words=6,
    )

    report = modeler.analyze(
        feedback,
        representative_count=2,
    )

    print(json.dumps(
        report,
        indent=2,
        ensure_ascii=False,
    ))

    modeler.save_report(
        report,
        "reports/topic_modeling.json",
    )
    