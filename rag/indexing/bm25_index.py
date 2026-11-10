
"""
ai/retrieval/bm25_index.py

Autonomous Retail Supply Chain AI 5.0

BM25 Keyword Retrieval Engine

Install:
    pip install rank-bm25

Features:
- Keyword document indexing
- BM25 ranking
- Top-K retrieval
- Metadata preservation
- Persistent index saving/loading
- Optional metadata filtering

Only load trusted index files.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from rank_bm25 import BM25Okapi


@dataclass
class SearchDocument:
    document_id: str
    content: str
    title: str = ""
    metadata: dict = field(
        default_factory=dict
    )


class BM25Index:

    TOKEN_PATTERN = re.compile(
        r"\b\w+\b",
        re.UNICODE,
    )

    def __init__(self):
        self.documents = []
        self.bm25 = None

    @classmethod
    def tokenize(cls, text):
        return cls.TOKEN_PATTERN.findall(
            text.lower()
        )

    def build(self, documents):
        self.documents = list(
            documents
        )

        if not self.documents:
            raise ValueError(
                "Cannot build an empty index"
            )

        ids = [
            doc.document_id
            for doc in self.documents
        ]

        if len(ids) != len(set(ids)):
            raise ValueError(
                "Duplicate document IDs"
            )

        corpus = [
            self.tokenize(
                doc.content
            )
            for doc in self.documents
        ]

        if any(
            not tokens
            for tokens in corpus
        ):
            raise ValueError(
                "Documents must contain "
                "searchable text"
            )

        self.bm25 = BM25Okapi(
            corpus
        )

        return self

    @staticmethod
    def _matches_metadata(
        document,
        filters,
    ):
        if not filters:
            return True

        return all(
            document.metadata.get(key)
            == value
            for key, value
            in filters.items()
        )

    def search(
        self,
        query,
        top_k=5,
        filters=None,
    ):
        if self.bm25 is None:
            raise RuntimeError(
                "Build or load an index first"
            )

        if top_k < 1:
            raise ValueError(
                "top_k must be >= 1"
            )

        tokens = self.tokenize(
            query
        )

        if not tokens:
            return []

        scores = (
            self.bm25.get_scores(
                tokens
            )
        )

        candidates = []

        for index, score in enumerate(
            scores
        ):
            document = (
                self.documents[index]
            )

            if not self._matches_metadata(
                document,
                filters,
            ):
                continue

            candidates.append({
                "document_id": (
                    document.document_id
                ),
                "title": document.title,
                "content": document.content,
                "metadata": document.metadata,
                "score": float(score),
                "retrieval_method": "bm25",
            })

        candidates.sort(
            key=lambda item: (
                -item["score"],
                item["document_id"],
            )
        )

        return candidates[:top_k]

    def save(
        self,
        path="indexes/bm25_index.json",
    ):
        if self.bm25 is None:
            raise RuntimeError(
                "No index to save"
            )

        output = Path(path)

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        payload = {
            "version": 1,
            "documents": [
                {
                    "document_id": (
                        doc.document_id
                    ),
                    "title": doc.title,
                    "content": doc.content,
                    "metadata": doc.metadata,
                }
                for doc in self.documents
            ],
        }

        output.write_text(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return output

    @classmethod
    def load(cls, path):
        payload = json.loads(
            Path(path).read_text(
                encoding="utf-8"
            )
        )

        if payload.get("version") != 1:
            raise ValueError(
                "Unsupported index version"
            )

        documents = [
            SearchDocument(**item)
            for item in payload[
                "documents"
            ]
        ]

        return cls().build(
            documents
        )


if __name__ == "__main__":
    documents = [
        SearchDocument(
            document_id="INV001",
            title="Inventory Report",
            content=(
                "SKU001 has 120 units "
                "available in warehouse A."
            ),
            metadata={
                "department": "inventory",
                "tenant_id": "demo",
            },
        ),
        SearchDocument(
            document_id="SUP002",
            title="Supplier Performance",
            content=(
                "Supplier SUP002 has "
                "an average delivery "
                "lead time of eight days."
            ),
            metadata={
                "department": "suppliers",
                "tenant_id": "demo",
            },
        ),
        SearchDocument(
            document_id="LOG003",
            title="Logistics Report",
            content=(
                "Shipment SH003 was "
                "delayed by heavy traffic."
            ),
            metadata={
                "department": "logistics",
                "tenant_id": "demo",
            },
        ),
    ]

    index = BM25Index().build(
        documents
    )

    results = index.search(
        "supplier delivery lead time",
        top_k=3,
        filters={
            "tenant_id": "demo",
        },
    )

    print(
        json.dumps(
            results,
            indent=2,
        )
    )

    index.save()

    restored = BM25Index.load(
        "indexes/bm25_index.json"
    )

    print(
        restored.search(
            "warehouse inventory"
        )
    )
