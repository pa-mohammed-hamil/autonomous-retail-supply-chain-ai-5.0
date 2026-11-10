"""Planned module: sparse retriever. Implementation pending."""

"""
ai/retrieval/sparse_retriever.py

Autonomous Retail Supply Chain AI 5.0
BM25 Sparse Retrieval Engine

Python 3.10+

Install:
    pip install rank-bm25

Features:
- BM25Okapi keyword retrieval
- Retail identifier-aware tokenization
- Tenant-isolated indexes
- Exact metadata filtering
- Document upsert and deletion
- Batch document ingestion
- Search result deduplication
- Stable ranking
- Optional minimum BM25 score
- JSON index persistence
- Query diagnostics

Security:
- Tenant ID is mandatory.
- Caller must enforce authentication.
- Indexing metadata must come from
  trusted ingestion services.
- Authorization must be applied before
  document content reaches the LLM.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading

from dataclasses import (
    asdict,
    dataclass,
    field,
)
from pathlib import Path
from typing import Any, Iterable

from rank_bm25 import BM25Okapi


@dataclass
class SparseDocument:
    document_id: str
    content: str
    title: str = ""
    metadata: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass
class SparseSearchResult:
    document_id: str
    title: str
    content: str
    metadata: dict[str, Any]
    score: float
    rank: int
    matched_terms: list[str]
    retrieval_method: str = "bm25_sparse"


@dataclass
class SparseSearchResponse:
    query: str
    tenant_id: str
    results: list[SparseSearchResult]
    total_documents: int
    matched_documents: int
    query_tokens: list[str]


class RetailSparseRetriever:
    """
    Tenant-isolated BM25 retrieval.

    Each tenant has its own:
    - document collection
    - tokenized corpus
    - BM25 index

    Document changes rebuild the
    affected tenant's BM25 index.

    Suitable for prototypes and
    moderate-size document collections.
    """

    TOKEN_PATTERN = re.compile(
        r"[A-Za-z0-9]+"
        r"(?:[-_./][A-Za-z0-9]+)*"
    )

    IDENTIFIER_PATTERN = re.compile(
        r"^(?:SKU|SUP|PO|INV|WH)"
        r"[-_]?[A-Z0-9]{2,20}$",
        re.IGNORECASE,
    )

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        title_boost: int = 2,
        max_documents_per_tenant: int = 100000,
        max_query_chars: int = 2000,
    ):
        if (
            not math.isfinite(k1)
            or k1 <= 0
        ):
            raise ValueError(
                "k1 must be positive"
            )

        if (
            not math.isfinite(b)
            or not 0 <= b <= 1
        ):
            raise ValueError(
                "b must be between 0 and 1"
            )

        if title_boost < 0:
            raise ValueError(
                "title_boost cannot be negative"
            )

        if max_documents_per_tenant <= 0:
            raise ValueError(
                "Invalid document limit"
            )

        self.k1 = k1
        self.b = b
        self.title_boost = title_boost

        self.max_documents_per_tenant = (
            max_documents_per_tenant
        )

        self.max_query_chars = (
            max_query_chars
        )

        self._documents: dict[
            str,
            dict[str, SparseDocument],
        ] = {}

        self._ids: dict[
            str,
            list[str],
        ] = {}

        self._tokens: dict[
            str,
            list[list[str]],
        ] = {}

        self._indexes: dict[
            str,
            BM25Okapi | None,
        ] = {}

        self._lock = threading.RLock()

    @staticmethod
    def _validate_tenant(
        tenant_id: str,
    ) -> None:
        if (
            not isinstance(tenant_id, str)
            or not tenant_id.strip()
        ):
            raise ValueError(
                "tenant_id is required"
            )

    @classmethod
    def tokenize(
        cls,
        text: str,
    ) -> list[str]:
        """
        Keep retail identifiers intact.

        Examples:
        SKU-001 -> sku-001
        SUP002  -> sup002
        PO-2026-001 -> po-2026-001
        """
        if not isinstance(text, str):
            raise TypeError(
                "Text must be a string"
            )

        tokens = [
            token.casefold()
            for token in cls.TOKEN_PATTERN.findall(
                text
            )
        ]

        return tokens

    def _document_tokens(
        self,
        document: SparseDocument,
    ) -> list[str]:
        title_tokens = self.tokenize(
            document.title
        )

        content_tokens = self.tokenize(
            document.content
        )

        return (
            title_tokens * self.title_boost
            + content_tokens
        )

    @staticmethod
    def _validate_document(
        document: SparseDocument,
        tenant_id: str,
    ) -> None:
        if (
            not isinstance(
                document.document_id,
                str,
            )
            or not document.document_id.strip()
        ):
            raise ValueError(
                "Invalid document_id"
            )

        if (
            not isinstance(
                document.content,
                str,
            )
            or not document.content.strip()
        ):
            raise ValueError(
                "Document content required"
            )

        if (
            document.metadata.get(
                "tenant_id"
            )
            != tenant_id
        ):
            raise ValueError(
                "Document tenant mismatch"
            )

    def _rebuild(
        self,
        tenant_id: str,
    ) -> None:
        documents = self._documents.get(
            tenant_id,
            {},
        )

        ids = sorted(
            documents
        )

        corpus = [
            self._document_tokens(
                documents[document_id]
            )
            for document_id in ids
        ]

        self._ids[tenant_id] = ids
        self._tokens[tenant_id] = corpus

        if corpus:
            self._indexes[
                tenant_id
            ] = BM25Okapi(
                corpus,
                k1=self.k1,
                b=self.b,
            )
        else:
            self._indexes[
                tenant_id
            ] = None

    def upsert(
        self,
        documents: Iterable[SparseDocument],
        tenant_id: str,
    ) -> int:
        self._validate_tenant(
            tenant_id
        )

        incoming_list = list(
            documents
        )

        if not incoming_list:
            return 0

        for document in incoming_list:
            self._validate_document(
                document,
                tenant_id,
            )

        incoming = {
            document.document_id: document
            for document in incoming_list
        }

        with self._lock:
            current = dict(
                self._documents.get(
                    tenant_id,
                    {},
                )
            )

            if (
                len(
                    set(current)
                    | set(incoming)
                )
                > self.max_documents_per_tenant
            ):
                raise ValueError(
                    "Tenant document limit exceeded"
                )

            current.update(
                incoming
            )

            self._documents[
                tenant_id
            ] = current

            self._rebuild(
                tenant_id
            )

        return len(incoming)

    def delete(
        self,
        document_id: str,
        tenant_id: str,
    ) -> bool:
        self._validate_tenant(
            tenant_id
        )

        with self._lock:
            documents = self._documents.get(
                tenant_id,
                {},
            )

            if document_id not in documents:
                return False

            del documents[
                document_id
            ]

            self._rebuild(
                tenant_id
            )

        return True

    @staticmethod
    def _matches_filters(
        metadata: dict[str, Any],
        filters: dict[str, Any] | None,
    ) -> bool:
        if not filters:
            return True

        return all(
            metadata.get(key) == value
            for key, value
            in filters.items()
        )

    def search(
        self,
        query: str,
        tenant_id: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
        min_score: float | None = None,
    ) -> SparseSearchResponse:
        self._validate_tenant(
            tenant_id
        )

        if (
            not isinstance(query, str)
            or not query.strip()
        ):
            raise ValueError(
                "Query required"
            )

        if (
            len(query)
            > self.max_query_chars
        ):
            raise ValueError(
                "Query exceeds length limit"
            )

        if top_k <= 0:
            raise ValueError(
                "top_k must be positive"
            )

        if (
            filters
            and "tenant_id" in filters
            and filters["tenant_id"]
            != tenant_id
        ):
            raise ValueError(
                "Conflicting tenant filter"
            )

        query_tokens = self.tokenize(
            query
        )

        with self._lock:
            documents = (
                self._documents.get(
                    tenant_id,
                    {},
                )
            )

            index = (
                self._indexes.get(
                    tenant_id
                )
            )

            if index is None:
                return SparseSearchResponse(
                    query=query,
                    tenant_id=tenant_id,
                    results=[],
                    total_documents=0,
                    matched_documents=0,
                    query_tokens=query_tokens,
                )

            scores = index.get_scores(
                query_tokens
            )

            ids = self._ids[
                tenant_id
            ]

            corpus = self._tokens[
                tenant_id
            ]

            candidates = []

            query_set = set(
                query_tokens
            )

            for position, score in enumerate(
                scores
            ):
                document_id = ids[
                    position
                ]

                document = documents[
                    document_id
                ]

                if not self._matches_filters(
                    document.metadata,
                    filters,
                ):
                    continue

                score = float(
                    score
                )

                if not math.isfinite(
                    score
                ):
                    continue

                matched = sorted(
                    query_set.intersection(
                        corpus[position]
                    )
                )

                # Require lexical overlap
                # rather than returning
                # arbitrary zero-score hits.
                if not matched:
                    continue

                if (
                    min_score is not None
                    and score < min_score
                ):
                    continue

                candidates.append(
                    (
                        document_id,
                        document,
                        score,
                        matched,
                    )
                )

            candidates.sort(
                key=lambda item: (
                    -item[2],
                    item[0],
                )
            )

            results = []

            for rank, (
                document_id,
                document,
                score,
                matched,
            ) in enumerate(
                candidates[:top_k],
                start=1,
            ):
                results.append(
                    SparseSearchResult(
                        document_id=document_id,
                        title=document.title,
                        content=document.content,
                        metadata=dict(
                            document.metadata
                        ),
                        score=round(
                            score,
                            6,
                        ),
                        rank=rank,
                        matched_terms=matched,
                    )
                )

            return SparseSearchResponse(
                query=query,
                tenant_id=tenant_id,
                results=results,
                total_documents=len(
                    documents
                ),
                matched_documents=len(
                    candidates
                ),
                query_tokens=query_tokens,
            )

    def stats(
        self,
        tenant_id: str,
    ) -> dict[str, Any]:
        self._validate_tenant(
            tenant_id
        )

        with self._lock:
            corpus = self._tokens.get(
                tenant_id,
                [],
            )

            return {
                "tenant_id": tenant_id,
                "document_count": len(
                    corpus
                ),
                "total_tokens": sum(
                    len(tokens)
                    for tokens in corpus
                ),
                "k1": self.k1,
                "b": self.b,
                "title_boost": (
                    self.title_boost
                ),
                "index_type": "BM25Okapi",
            }

    @staticmethod
    def _safe_tenant_name(
        tenant_id: str,
    ) -> str:
        return hashlib.sha256(
            tenant_id.encode(
                "utf-8"
            )
        ).hexdigest()[:32]

    def save(
        self,
        directory: str | Path,
        tenant_id: str,
    ) -> Path:
        self._validate_tenant(
            tenant_id
        )

        tenant_dir = (
            Path(directory)
            / self._safe_tenant_name(
                tenant_id
            )
        )

        tenant_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self._lock:
            payload = {
                "version": 1,
                "tenant_id": tenant_id,
                "k1": self.k1,
                "b": self.b,
                "title_boost": (
                    self.title_boost
                ),
                "documents": [
                    asdict(document)
                    for document in (
                        self._documents.get(
                            tenant_id,
                            {},
                        ).values()
                    )
                ],
            }

            path = (
                tenant_dir
                / "sparse_index.json"
            )

            path.write_text(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        return path

    def load(
        self,
        directory: str | Path,
        tenant_id: str,
    ) -> int:
        self._validate_tenant(
            tenant_id
        )

        path = (
            Path(directory)
            / self._safe_tenant_name(
                tenant_id
            )
            / "sparse_index.json"
        )

        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        if (
            payload["tenant_id"]
            != tenant_id
        ):
            raise ValueError(
                "Saved tenant mismatch"
            )

        if (
            payload["k1"] != self.k1
            or payload["b"] != self.b
            or payload["title_boost"]
            != self.title_boost
        ):
            raise ValueError(
                "BM25 configuration mismatch"
            )

        documents = {}

        for item in payload["documents"]:
            document = SparseDocument(
                **item
            )

            self._validate_document(
                document,
                tenant_id,
            )

            if (
                document.document_id
                in documents
            ):
                raise ValueError(
                    "Duplicate saved document ID"
                )

            documents[
                document.document_id
            ] = document

        if (
            len(documents)
            > self.max_documents_per_tenant
        ):
            raise ValueError(
                "Tenant document limit exceeded"
            )

        with self._lock:
            self._documents[
                tenant_id
            ] = documents

            self._rebuild(
                tenant_id
            )

        return len(documents)


if __name__ == "__main__":
    from dataclasses import asdict

    retriever = RetailSparseRetriever()

    documents = [
        SparseDocument(
            document_id="inventory-001",
            title="Inventory Stockout",
            content=(
                "SKU-001 has only 12 units "
                "remaining. Reorder point "
                "is 40 units."
            ),
            metadata={
                "tenant_id": "demo",
                "category": "inventory",
            },
        ),
        SparseDocument(
            document_id="supplier-001",
            title="Supplier Lead Time",
            content=(
                "Supplier SUP002 has an "
                "eight-day lead time."
            ),
            metadata={
                "tenant_id": "demo",
                "category": "supplier",
            },
        ),
        SparseDocument(
            document_id="logistics-001",
            title="Delivery Delay",
            content=(
                "Purchase order PO-2026-001 "
                "was delayed by three days."
            ),
            metadata={
                "tenant_id": "demo",
                "category": "logistics",
            },
        ),
    ]

    retriever.upsert(
        documents,
        tenant_id="demo",
    )

    response = retriever.search(
        query="SKU-001 reorder point",
        tenant_id="demo",
        top_k=3,
    )

    print(
        json.dumps(
            asdict(response),
            indent=2,
            ensure_ascii=False,
        )
    )

    retriever.save(
        "indexes/sparse",
        tenant_id="demo",
    )
