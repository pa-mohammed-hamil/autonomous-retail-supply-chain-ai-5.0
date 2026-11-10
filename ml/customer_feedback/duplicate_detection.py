"""Planned module: duplicate detection. Implementation pending."""

"""
ai/feedback/duplicate_detection.py

Autonomous Retail Supply Chain AI 5.0

Duplicate Customer Complaint Detection

Features:
- Exact duplicate detection
- Near-duplicate detection
- TF-IDF cosine similarity
- Complaint grouping
- Customer/order scoping
- Duplicate pair reports
- JSON/CSV input
- JSON output

No external dependencies.

Limitations:
- Lexical similarity is not semantic similarity.
- Similar complaints from different orders
  may describe separate real incidents.
"""

from __future__ import annotations

import csv
import json
import math
import re

from collections import Counter, defaultdict
from pathlib import Path
from typing import Sequence


class DuplicateDetection:

    @staticmethod
    def normalize(text: str) -> str:
        if not isinstance(text, str):
            raise TypeError("Text must be a string")

        return " ".join(
            re.findall(r"[a-z0-9]+", text.lower())
        )

    @classmethod
    def _tokens(cls, text: str) -> list[str]:
        return cls.normalize(text).split()

    @classmethod
    def _tfidf_vectors(
        cls,
        texts: Sequence[str],
    ) -> list[dict[str, float]]:
        documents = [
            cls._tokens(text)
            for text in texts
        ]

        n = len(documents)
        document_frequency = Counter()

        for tokens in documents:
            document_frequency.update(set(tokens))

        vectors = []

        for tokens in documents:
            counts = Counter(tokens)
            vector = {}

            for token, frequency in counts.items():
                tf = frequency / len(tokens)

                idf = (
                    math.log(
                        (1 + n)
                        / (1 + document_frequency[token])
                    ) + 1
                )

                vector[token] = tf * idf

            norm = math.sqrt(
                sum(value * value
                    for value in vector.values())
            )

            if norm:
                vector = {
                    token: value / norm
                    for token, value in vector.items()
                }

            vectors.append(vector)

        return vectors

    @staticmethod
    def cosine_similarity(
        vector_a: dict[str, float],
        vector_b: dict[str, float],
    ) -> float:
        if len(vector_a) > len(vector_b):
            vector_a, vector_b = vector_b, vector_a

        return sum(
            value * vector_b.get(token, 0.0)
            for token, value in vector_a.items()
        )

    @staticmethod
    def _find(
        parent: list[int],
        index: int,
    ) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]

        return index

    @classmethod
    def _union(
        cls,
        parent: list[int],
        a: int,
        b: int,
    ) -> None:
        root_a = cls._find(parent, a)
        root_b = cls._find(parent, b)

        if root_a != root_b:
            parent[root_b] = root_a

    @classmethod
    def detect(
        cls,
        records: Sequence[dict],
        threshold: float = 0.8,
        scope: str = "customer_order",
    ) -> dict:
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not math.isfinite(threshold)
            or not 0 <= threshold <= 1
        ):
            raise ValueError(
                "Threshold must be between 0 and 1"
            )

        if scope not in {
            "global",
            "customer",
            "customer_order",
        }:
            raise ValueError("Invalid scope")

        if not records:
            raise ValueError("Empty complaint dataset")

        ids = set()
        texts = []
        normalized = []

        for record in records:
            complaint_id = str(
                record["complaint_id"]
            ).strip()

            text = str(
                record["text"]
            ).strip()

            if not complaint_id or complaint_id in ids:
                raise ValueError(
                    "Invalid or duplicate complaint ID"
                )

            if not text:
                raise ValueError(
                    "Complaint text cannot be empty"
                )

            if scope in {"customer", "customer_order"}:
                if not str(
                    record.get("customer_id", "")
                ).strip():
                    raise ValueError(
                        "customer_id required for scope"
                    )

            if scope == "customer_order":
                if not str(
                    record.get("order_id", "")
                ).strip():
                    raise ValueError(
                        "order_id required for scope"
                    )

            ids.add(complaint_id)
            texts.append(text)
            normalized.append(cls.normalize(text))

        vectors = cls._tfidf_vectors(texts)
        parent = list(range(len(records)))
        duplicate_pairs = []

        def same_scope(a: dict, b: dict) -> bool:
            if scope == "global":
                return True

            if (
                str(a["customer_id"])
                != str(b["customer_id"])
            ):
                return False

            if scope == "customer_order":
                return (
                    str(a["order_id"])
                    == str(b["order_id"])
                )

            return True

        for i in range(len(records)):
            for j in range(i + 1, len(records)):
                if not same_scope(records[i], records[j]):
                    continue

                exact = (
                    normalized[i] == normalized[j]
                )

                similarity = (
                    1.0 if exact
                    else cls.cosine_similarity(
                        vectors[i], vectors[j]
                    )
                )

                if similarity >= threshold:
                    cls._union(parent, i, j)

                    duplicate_pairs.append({
                        "complaint_id_1": records[i][
                            "complaint_id"
                        ],
                        "complaint_id_2": records[j][
                            "complaint_id"
                        ],
                        "similarity": round(
                            similarity, 6
                        ),
                        "match_type": (
                            "exact"
                            if exact else "near_duplicate"
                        ),
                    })

        groups = defaultdict(list)

        for index, record in enumerate(records):
            root = cls._find(parent, index)
            groups[root].append(
                record["complaint_id"]
            )

        duplicate_groups = [
            members
            for members in groups.values()
            if len(members) > 1
        ]

        grouped_ids = {
            complaint_id
            for group in duplicate_groups
            for complaint_id in group
        }

        return {
            "total_complaints": len(records),
            "scope": scope,
            "similarity_threshold": threshold,
            "duplicate_pairs_count": len(
                duplicate_pairs
            ),
            "duplicate_groups_count": len(
                duplicate_groups
            ),
            "complaints_in_duplicate_groups": len(
                grouped_ids
            ),
            "unique_complaints_estimate": (
                len(groups)
            ),
            "duplicate_pairs": duplicate_pairs,
            "duplicate_groups": duplicate_groups,
        }

    @classmethod
    def detect_csv(
        cls,
        path: str,
        threshold: float = 0.8,
        scope: str = "customer_order",
    ) -> dict:
        with open(
            path,
            newline="",
            encoding="utf-8-sig",
        ) as file:
            records = list(csv.DictReader(file))

        return cls.detect(
            records,
            threshold=threshold,
            scope=scope,
        )

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
    complaints = [
        {
            "complaint_id": "C001",
            "customer_id": "U001",
            "order_id": "O001",
            "text": "My order arrived damaged.",
        },
        {
            "complaint_id": "C002",
            "customer_id": "U001",
            "order_id": "O001",
            "text": "My order arrived damaged!",
        },
        {
            "complaint_id": "C003",
            "customer_id": "U002",
            "order_id": "O002",
            "text": "The delivery was delayed.",
        },
        {
            "complaint_id": "C004",
            "customer_id": "U001",
            "order_id": "O001",
            "text": "My product was damaged on arrival.",
        },
    ]

    report = DuplicateDetection.detect(
        complaints,
        threshold=0.65,
    )

    print(json.dumps(report, indent=2))
