"""Planned module: dense retriever. Implementation pending."""

"""
ai/retrieval/dense_retriever.py

Autonomous Retail Supply Chain AI 5.0
Dense Semantic Retriever

Python 3.10+

Install:
    pip install numpy faiss-cpu sentence-transformers

Features:
- Sentence Transformer embeddings
- FAISS cosine-similarity search
- Tenant-isolated retrieval
- Metadata filtering
- Batch document indexing
- Document upsert and deletion
- Normalized vector embeddings
- Deterministic result ordering
- Index persistence and recovery
- Search statistics

Security:
- Tenant ID is mandatory.
- Every indexed document requires
  matching tenant metadata.
- Authorization must be enforced
  by the calling backend.
- Do not load untrusted model files.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


@dataclass
class DenseDocument:
    document_id: str
    content: str
    title: str = ""
    metadata: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass
class DenseSearchResult:
    document_id: str
    title: str
    content: str
    metadata: dict[str, Any]
    score: float
    retrieval_method: str = "dense"


class RetailDenseRetriever:
    """
    FAISS-based dense retrieval.

    Uses one independent index per tenant.
    Inner product on normalized vectors
    is equivalent to cosine similarity.

    Thread-safe for calls made through
    this class within one process.
    """

    def __init__(
        self,
        model_name: str = (
            "sentence-transformers/"
            "all-MiniLM-L6-v2"
        ),
        batch_size: int = 32,
        max_documents_per_tenant: int = 100000,
    ):
        if batch_size <= 0:
            raise ValueError(
                "batch_size must be positive"
            )

        self.model_name = model_name
        self.batch_size = batch_size
        self.max_documents_per_tenant = (
            max_documents_per_tenant
        )

        self.model = SentenceTransformer(
            model_name
        )

        self.dimension = (
            self.model.get_sentence_embedding_dimension()
        )

        if not self.dimension:
            raise ValueError(
                "Unable to determine embedding dimension"
            )

        self._documents: dict[
            str,
            dict[str, DenseDocument],
        ] = {}

        self._vectors: dict[
            str,
            dict[str, np.ndarray],
        ] = {}

        self._indexes: dict[
            str,
            faiss.Index,
        ] = {}

        self._ids: dict[
            str,
            list[str],
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

    def _embed(
        self,
        texts: list[str],
    ) -> np.ndarray:
        vectors = self.model.encode(
            texts,
            batch_size=self.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

        vectors = np.asarray(
            vectors,
            dtype=np.float32,
        )

        if vectors.ndim == 1:
            vectors = vectors.reshape(
                1, -1
            )

        if (
            vectors.shape[1]
            != self.dimension
        ):
            raise ValueError(
                "Embedding dimension mismatch"
            )

        if not np.isfinite(
            vectors
        ).all():
            raise ValueError(
                "Non-finite embedding detected"
            )

        return np.ascontiguousarray(
            vectors
        )

    def _rebuild(
        self,
        tenant_id: str,
    ) -> None:
        documents = self._documents.get(
            tenant_id,
            {},
        )

        vectors = self._vectors.get(
            tenant_id,
            {},
        )

        ids = sorted(
            documents.keys()
        )

        index = faiss.IndexFlatIP(
            self.dimension
        )

        if ids:
            matrix = np.stack(
                [
                    vectors[document_id]
                    for document_id in ids
                ]
            ).astype(
                np.float32
            )

            matrix = np.ascontiguousarray(
                matrix
            )

            index.add(matrix)

        self._indexes[tenant_id] = index
        self._ids[tenant_id] = ids

    def upsert(
        self,
        documents: Iterable[DenseDocument],
        tenant_id: str,
    ) -> int:
        self._validate_tenant(
            tenant_id
        )

        documents = list(
            documents
        )

        if not documents:
            return 0

        for document in documents:
            if not document.document_id:
                raise ValueError(
                    "Document ID required"
                )

            if not document.content.strip():
                raise ValueError(
                    "Empty document content"
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

        # Last occurrence of a repeated
        # document ID wins in this batch.
        incoming = {
            document.document_id: document
            for document in documents
        }

        embeddings = self._embed(
            [
                document.content
                for document
                in incoming.values()
            ]
        )

        with self._lock:
            current_docs = dict(
                self._documents.get(
                    tenant_id,
                    {},
                )
            )

            current_vectors = dict(
                self._vectors.get(
                    tenant_id,
                    {},
                )
            )

            if (
                len(
                    set(current_docs)
                    | set(incoming)
                )
                > self.max_documents_per_tenant
            ):
                raise ValueError(
                    "Tenant document limit exceeded"
                )

            for (
                document_id,
                document,
            ), vector in zip(
                incoming.items(),
                embeddings,
            ):
                current_docs[
                    document_id
                ] = document

                current_vectors[
                    document_id
                ] = vector.copy()

            self._documents[
                tenant_id
            ] = current_docs

            self._vectors[
                tenant_id
            ] = current_vectors

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

            self._vectors[
                tenant_id
            ].pop(
                document_id,
                None,
            )

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
    ) -> list[DenseSearchResult]:
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

        query_vector = self._embed(
            [query]
        )

        with self._lock:
            index = self._indexes.get(
                tenant_id
            )

            if (
                index is None
                or index.ntotal == 0
            ):
                return []

            ids = self._ids[
                tenant_id
            ]

            documents = self._documents[
                tenant_id
            ]

            # Search all tenant-local
            # vectors before filtering.
            # This ensures filtered
            # top_k completeness.
            scores, positions = (
                index.search(
                    query_vector,
                    index.ntotal,
                )
            )

            results = []

            for score, position in zip(
                scores[0],
                positions[0],
            ):
                if position < 0:
                    continue

                document_id = ids[
                    int(position)
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

                if (
                    min_score is not None
                    and score < min_score
                ):
                    continue

                results.append(
                    DenseSearchResult(
                        document_id=(
                            document.document_id
                        ),
                        title=document.title,
                        content=document.content,
                        metadata=dict(
                            document.metadata
                        ),
                        score=round(
                            score,
                            6,
                        ),
                    )
                )

                if len(results) >= top_k:
                    break

            return results

    def stats(
        self,
        tenant_id: str,
    ) -> dict[str, Any]:
        self._validate_tenant(
            tenant_id
        )

        with self._lock:
            documents = self._documents.get(
                tenant_id,
                {},
            )

            return {
                "tenant_id": tenant_id,
                "document_count": len(
                    documents
                ),
                "embedding_dimension": (
                    self.dimension
                ),
                "model_name": self.model_name,
                "index_type": (
                    "FAISS IndexFlatIP"
                ),
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

        root = Path(directory)

        tenant_dir = (
            root
            / self._safe_tenant_name(
                tenant_id
            )
        )

        tenant_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        with self._lock:
            ids = list(
                self._ids.get(
                    tenant_id,
                    [],
                )
            )

            documents = self._documents.get(
                tenant_id,
                {},
            )

            vectors = self._vectors.get(
                tenant_id,
                {},
            )

            matrix = (
                np.stack(
                    [
                        vectors[
                            document_id
                        ]
                        for document_id
                        in ids
                    ]
                ).astype(
                    np.float32
                )
                if ids
                else np.empty(
                    (0, self.dimension),
                    dtype=np.float32,
                )
            )

            payload = {
                "version": 1,
                "tenant_id": tenant_id,
                "model_name": self.model_name,
                "dimension": self.dimension,
                "documents": [
                    {
                        "document_id": (
                            documents[
                                document_id
                            ].document_id
                        ),
                        "content": (
                            documents[
                                document_id
                            ].content
                        ),
                        "title": (
                            documents[
                                document_id
                            ].title
                        ),
                        "metadata": (
                            documents[
                                document_id
                            ].metadata
                        ),
                    }
                    for document_id in ids
                ],
            }

            (
                tenant_dir
                / "metadata.json"
            ).write_text(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            np.save(
                tenant_dir
                / "vectors.npy",
                matrix,
                allow_pickle=False,
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

        tenant_dir = (
            Path(directory)
            / self._safe_tenant_name(
                tenant_id
            )
        )

        metadata_path = (
            tenant_dir
            / "metadata.json"
        )

        vectors_path = (
            tenant_dir
            / "vectors.npy"
        )

        payload = json.loads(
            metadata_path.read_text(
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
            payload["model_name"]
            != self.model_name
        ):
            raise ValueError(
                "Embedding model mismatch"
            )

        if (
            payload["dimension"]
            != self.dimension
        ):
            raise ValueError(
                "Embedding dimension mismatch"
            )

        matrix = np.load(
            vectors_path,
            allow_pickle=False,
        )

        saved_documents = (
            payload["documents"]
        )

        if matrix.shape != (
            len(saved_documents),
            self.dimension,
        ):
            raise ValueError(
                "Saved vector shape mismatch"
            )

        if not np.isfinite(
            matrix
        ).all():
            raise ValueError(
                "Invalid saved embeddings"
            )

        documents = {}
        vectors = {}

        for item, vector in zip(
            saved_documents,
            matrix,
        ):
            if (
                item["metadata"].get(
                    "tenant_id"
                )
                != tenant_id
            ):
                raise ValueError(
                    "Saved document tenant mismatch"
                )

            document = DenseDocument(
                document_id=(
                    item["document_id"]
                ),
                content=item["content"],
                title=item["title"],
                metadata=item["metadata"],
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

            vectors[
                document.document_id
            ] = np.asarray(
                vector,
                dtype=np.float32,
            ).copy()

        with self._lock:
            self._documents[
                tenant_id
            ] = documents

            self._vectors[
                tenant_id
            ] = vectors

            self._rebuild(
                tenant_id
            )

        return len(documents)


if __name__ == "__main__":
    retriever = RetailDenseRetriever()

    documents = [
        DenseDocument(
            document_id="inventory-001",
            title="Inventory Report",
            content=(
                "SKU001 has 15 units remaining. "
                "The reorder point is 40 units. "
                "This item is at risk of stockout."
            ),
            metadata={
                "tenant_id": "demo",
                "category": "inventory",
                "sku": "SKU001",
            },
        ),
        DenseDocument(
            document_id="supplier-001",
            title="Supplier Report",
            content=(
                "Supplier SUP002 has an "
                "average delivery lead time "
                "of eight days."
            ),
            metadata={
                "tenant_id": "demo",
                "category": "supplier",
                "supplier_id": "SUP002",
            },
        ),
        DenseDocument(
            document_id="logistics-001",
            title="Delivery Report",
            content=(
                "The latest warehouse shipment "
                "was delayed by three days "
                "because of transport disruption."
            ),
            metadata={
                "tenant_id": "demo",
                "category": "logistics",
            },
        ),
    ]

    count = retriever.upsert(
        documents=documents,
        tenant_id="demo",
    )

    print("Indexed:", count)

    results = retriever.search(
        query=(
            "Which products are at "
            "risk of running out of stock?"
        ),
        tenant_id="demo",
        top_k=3,
    )

    for result in results:
        print(
            json.dumps(
                result.__dict__,
                indent=2,
            )
        )

    retriever.save(
        "indexes/dense",
        tenant_id="demo",
    )

    print(
        "Stats:",
        retriever.stats("demo"),
    )
