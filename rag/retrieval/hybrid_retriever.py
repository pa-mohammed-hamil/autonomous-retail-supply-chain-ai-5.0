
"""
ai/retrieval/hybrid_retriever.py

Autonomous Retail Supply Chain AI 5.0
Hybrid RAG Retrieval Engine

Python 3.10+

Dependencies:
    ai/retrieval/bm25_index.py
    ai/retrieval/dense_retriever.py

Install:
    pip install rank-bm25 numpy faiss-cpu sentence-transformers

Features:
- BM25 sparse retrieval
- FAISS dense retrieval
- Reciprocal Rank Fusion (RRF)
- Configurable fusion weights
- Tenant-aware indexing
- Metadata filters
- Stable document IDs
- Deduplicated search results
- Per-retriever rank tracking
- Parent-child chunk compatibility
- Index persistence
- Retrieval statistics

RRF scores are ranking scores,
not calibrated relevance probabilities.

Backend authorization must be checked
before invoking this retriever.
"""

from __future__ import annotations

import json
import math
import threading

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ai.retrieval.bm25_index import (
    BM25Index,
    SearchDocument,
)

from ai.retrieval.dense_retriever import (
    DenseDocument,
    RetailDenseRetriever,
)


@dataclass
class HybridDocument:
    document_id: str
    content: str
    title: str = ""
    metadata: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass
class HybridSearchResult:
    document_id: str
    title: str
    content: str
    metadata: dict[str, Any]
    score: float
    sparse_score: float | None = None
    dense_score: float | None = None
    sparse_rank: int | None = None
    dense_rank: int | None = None
    retrieval_method: str = "hybrid_rrf"


@dataclass
class HybridSearchResponse:
    query: str
    tenant_id: str
    results: list[HybridSearchResult]
    sparse_candidates: int
    dense_candidates: int
    fusion_method: str = "weighted_rrf"


class RetailHybridRetriever:
    """
    BM25 + FAISS hybrid retrieval.

    Sparse index:
        BM25Index from bm25_index.py

    Dense index:
        RetailDenseRetriever from
        dense_retriever.py

    Fusion:
        Weighted Reciprocal Rank Fusion

    RRF:
        score(d) = sum(
            weight / (k + rank(d))
        )
    """

    def __init__(
        self,
        dense_retriever: (
            RetailDenseRetriever | None
        ) = None,
        sparse_weight: float = 0.5,
        dense_weight: float = 0.5,
        rrf_k: int = 60,
        candidate_multiplier: int = 4,
        max_documents_per_tenant: int = 100000,
    ):
        if sparse_weight < 0:
            raise ValueError(
                "sparse_weight cannot be negative"
            )

        if dense_weight < 0:
            raise ValueError(
                "dense_weight cannot be negative"
            )

        total_weight = (
            sparse_weight + dense_weight
        )

        if total_weight <= 0:
            raise ValueError(
                "At least one retrieval weight "
                "must be positive"
            )

        if rrf_k <= 0:
            raise ValueError(
                "rrf_k must be positive"
            )

        if candidate_multiplier <= 0:
            raise ValueError(
                "candidate_multiplier must "
                "be positive"
            )

        self.sparse_weight = (
            sparse_weight / total_weight
        )

        self.dense_weight = (
            dense_weight / total_weight
        )

        self.rrf_k = rrf_k
        self.candidate_multiplier = (
            candidate_multiplier
        )

        self.max_documents_per_tenant = (
            max_documents_per_tenant
        )

        self.dense = (
            dense_retriever
            or RetailDenseRetriever()
        )

        self._documents: dict[
            str,
            dict[str, HybridDocument],
        ] = {}

        self._sparse_indexes: dict[
            str,
            BM25Index,
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

    @staticmethod
    def _validate_document(
        document: HybridDocument,
        tenant_id: str,
    ) -> None:
        if not document.document_id:
            raise ValueError(
                "document_id required"
            )

        if not document.content.strip():
            raise ValueError(
                "Document content is empty"
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

    def _build_sparse(
        self,
        tenant_id: str,
    ) -> None:
        documents = self._documents.get(
            tenant_id,
            {},
        )

        index = BM25Index()

        index.build([
            SearchDocument(
                document_id=doc.document_id,
                title=doc.title,
                content=doc.content,
                metadata=dict(
                    doc.metadata
                ),
            )
            for doc in documents.values()
        ])

        self._sparse_indexes[
            tenant_id
        ] = index

    def upsert(
        self,
        documents: Iterable[HybridDocument],
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
            doc.document_id: doc
            for doc in incoming_list
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

            # Dense indexing happens first.
            # If embedding fails, sparse
            # state remains unchanged.
            self.dense.upsert(
                [
                    DenseDocument(
                        document_id=doc.document_id,
                        title=doc.title,
                        content=doc.content,
                        metadata=dict(
                            doc.metadata
                        ),
                    )
                    for doc in incoming.values()
                ],
                tenant_id=tenant_id,
            )

            current.update(incoming)

            self._documents[
                tenant_id
            ] = current

            self._build_sparse(
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
            current = self._documents.get(
                tenant_id,
                {},
            )

            if document_id not in current:
                return False

            self.dense.delete(
                document_id=document_id,
                tenant_id=tenant_id,
            )

            del current[
                document_id
            ]

            self._build_sparse(
                tenant_id
            )

        return True

    def search(
        self,
        query: str,
        tenant_id: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
        sparse_weight: float | None = None,
        dense_weight: float | None = None,
    ) -> HybridSearchResponse:

        self._validate_tenant(
            tenant_id
        )

        if not query.strip():
            raise ValueError(
                "Search query required"
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

        sw = (
            self.sparse_weight
            if sparse_weight is None
            else sparse_weight
        )

        dw = (
            self.dense_weight
            if dense_weight is None
            else dense_weight
        )

        if (
            not math.isfinite(sw)
            or not math.isfinite(dw)
            or sw < 0
            or dw < 0
            or sw + dw <= 0
        ):
            raise ValueError(
                "Invalid retrieval weights"
            )

        total = sw + dw
        sw /= total
        dw /= total

        candidate_k = (
            top_k
            * self.candidate_multiplier
        )

        with self._lock:
            sparse_index = (
                self._sparse_indexes.get(
                    tenant_id
                )
            )

            sparse_results = []

            if (
                sw > 0
                and sparse_index is not None
            ):
                sparse_results = (
                    sparse_index.search(
                        query=query,
                        top_k=candidate_k,
                        filters={
                            **(filters or {}),
                            "tenant_id": tenant_id,
                        },
                    )
                )

            dense_results = []

            if dw > 0:
                dense_results = (
                    self.dense.search(
                        query=query,
                        tenant_id=tenant_id,
                        top_k=candidate_k,
                        filters=filters,
                    )
                )

            fused: dict[
                str,
                HybridSearchResult,
            ] = {}

            def ensure(
                document_id: str,
            ) -> HybridSearchResult:
                if document_id not in fused:
                    document = (
                        self._documents[
                            tenant_id
                        ][document_id]
                    )

                    fused[
                        document_id
                    ] = HybridSearchResult(
                        document_id=document_id,
                        title=document.title,
                        content=document.content,
                        metadata=dict(
                            document.metadata
                        ),
                        score=0.0,
                    )

                return fused[
                    document_id
                ]

            for rank, item in enumerate(
                sparse_results,
                start=1,
            ):
                document_id = (
                    item["document_id"]
                )

                if document_id not in (
                    self._documents.get(
                        tenant_id,
                        {},
                    )
                ):
                    continue

                result = ensure(
                    document_id
                )

                result.score += (
                    sw
                    / (self.rrf_k + rank)
                )

                result.sparse_score = float(
                    item["score"]
                )

                result.sparse_rank = rank

            for rank, item in enumerate(
                dense_results,
                start=1,
            ):
                document_id = (
                    item.document_id
                )

                if document_id not in (
                    self._documents.get(
                        tenant_id,
                        {},
                    )
                ):
                    continue

                result = ensure(
                    document_id
                )

                result.score += (
                    dw
                    / (self.rrf_k + rank)
                )

                result.dense_score = (
                    item.score
                )

                result.dense_rank = rank

            ranked = sorted(
                fused.values(),
                key=lambda item: (
                    -item.score,
                    item.document_id,
                ),
            )

            for result in ranked:
                result.score = round(
                    result.score,
                    8,
                )

            return HybridSearchResponse(
                query=query,
                tenant_id=tenant_id,
                results=ranked[:top_k],
                sparse_candidates=len(
                    sparse_results
                ),
                dense_candidates=len(
                    dense_results
                ),
            )

    def stats(
        self,
        tenant_id: str,
    ) -> dict[str, Any]:
        self._validate_tenant(
            tenant_id
        )

        with self._lock:
            return {
                "tenant_id": tenant_id,
                "document_count": len(
                    self._documents.get(
                        tenant_id,
                        {},
                    )
                ),
                "sparse_weight": (
                    self.sparse_weight
                ),
                "dense_weight": (
                    self.dense_weight
                ),
                "rrf_k": self.rrf_k,
                "candidate_multiplier": (
                    self.candidate_multiplier
                ),
                "dense": self.dense.stats(
                    tenant_id
                ),
            }

    def save(
        self,
        directory: str | Path,
        tenant_id: str,
    ) -> Path:
        self._validate_tenant(
            tenant_id
        )

        root = Path(directory)

        tenant_dir = (
            root
            / self.dense._safe_tenant_name(
                tenant_id
            )
        )

        with self._lock:
            self.dense.save(
                root / "dense",
                tenant_id=tenant_id,
            )

            tenant_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

            documents = (
                self._documents.get(
                    tenant_id,
                    {},
                )
            )

            payload = {
                "tenant_id": tenant_id,
                "documents": [
                    asdict(doc)
                    for doc in documents.values()
                ],
                "sparse_weight": (
                    self.sparse_weight
                ),
                "dense_weight": (
                    self.dense_weight
                ),
                "rrf_k": self.rrf_k,
                "candidate_multiplier": (
                    self.candidate_multiplier
                ),
            }

            (
                tenant_dir
                / "hybrid.json"
            ).write_text(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        return tenant_dir

    def load(
        self,
        directory: str | Path,
        tenant_id: str,
    ) -> int:
        self._validate_tenant(
            tenant_id
        )

        root = Path(directory)

        tenant_dir = (
            root
            / self.dense._safe_tenant_name(
                tenant_id
            )
        )

        payload = json.loads(
            (
                tenant_dir
                / "hybrid.json"
            ).read_text(
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

        documents = {}

        for item in payload["documents"]:
            document = HybridDocument(
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
                    "Duplicate document ID"
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
            self.dense.load(
                root / "dense",
                tenant_id=tenant_id,
            )

            self._documents[
                tenant_id
            ] = documents

            self._build_sparse(
                tenant_id
            )

        return len(documents)


if __name__ == "__main__":
    retriever = RetailHybridRetriever(
        sparse_weight=0.45,
        dense_weight=0.55,
        rrf_k=60,
    )

    documents = [
        HybridDocument(
            document_id="inventory-001",
            title="Inventory Stockout Report",
            content=(
                "SKU001 has only 15 units "
                "remaining. Reorder point "
                "is 40 units. This product "
                "has a high stockout risk."
            ),
            metadata={
                "tenant_id": "demo",
                "category": "inventory",
                "sku": "SKU001",
            },
        ),
        HybridDocument(
            document_id="supplier-001",
            title="Supplier Lead Time",
            content=(
                "Supplier SUP002 delivers "
                "SKU001 in eight days."
            ),
            metadata={
                "tenant_id": "demo",
                "category": "supplier",
                "supplier_id": "SUP002",
            },
        ),
        HybridDocument(
            document_id="logistics-001",
            title="Transport Delay",
            content=(
                "A warehouse shipment was "
                "delayed by three days."
            ),
            metadata={
                "tenant_id": "demo",
                "category": "logistics",
            },
        ),
    ]

    retriever.upsert(
        documents=documents,
        tenant_id="demo",
    )

    response = retriever.search(
        query=(
            "Which products may run "
            "out of stock?"
        ),
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
        "indexes/hybrid",
        tenant_id="demo",
    )
