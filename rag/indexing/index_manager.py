"""Planned module: index manager. Implementation pending."""

"""
ai/retrieval/index_manager.py

Autonomous Retail Supply Chain AI 5.0

Hybrid RAG Index Lifecycle Manager

Dependencies:
    pip install numpy rank-bm25 \
        sentence-transformers

Requires:
    ai/retrieval/bm25_index.py
    ai/retrieval/embeddings.py

Notes:
- Uses full index rebuilds after changes.
- Suitable for prototype/small datasets.
- Index updates are not transactional.
- Use trusted storage and server-side
  authorization in production.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from ai.retrieval.bm25_index import (
    BM25Index,
    SearchDocument,
)

from ai.retrieval.embeddings import (
    EmbeddingIndex,
    VectorDocument,
)


class IndexManager:

    def __init__(
        self,
        root_dir="indexes/retail",
        embedding_model=(
            "sentence-transformers/"
            "all-MiniLM-L6-v2"
        ),
    ):
        self.root_dir = Path(root_dir)
        self.embedding_model = embedding_model

        self.documents: dict[
            str, SearchDocument
        ] = {}

        self.bm25 = None
        self.vector_index = None

        self.version = 0
        self.updated_at = None
        self.dirty = True

    @staticmethod
    def _validate_document(doc):
        if not isinstance(
            doc, SearchDocument
        ):
            raise TypeError(
                "Expected SearchDocument"
            )

        if not doc.document_id.strip():
            raise ValueError(
                "document_id cannot be empty"
            )

        if not doc.content.strip():
            raise ValueError(
                "Document content cannot be empty"
            )

        if not isinstance(
            doc.metadata, dict
        ):
            raise TypeError(
                "metadata must be a dictionary"
            )

        # Every indexed document must
        # belong to a tenant.
        tenant_id = doc.metadata.get(
            "tenant_id"
        )

        if (
            not isinstance(
                tenant_id, str
            )
            or not tenant_id.strip()
        ):
            raise ValueError(
                "A nonempty tenant_id is required"
            )

    def upsert(self, document):
        self._validate_document(
            document
        )

        self.documents[
            document.document_id
        ] = document

        self.dirty = True

    def upsert_many(
        self,
        documents: Iterable[
            SearchDocument
        ],
    ):
        for document in documents:
            self.upsert(
                document
            )

    def delete(self, document_id):
        if document_id not in self.documents:
            return False

        del self.documents[
            document_id
        ]

        self.dirty = True
        return True

    def rebuild(self):
        if not self.documents:
            self.bm25 = None
            self.vector_index = None
            self.dirty = False
            self.version += 1
            self.updated_at = (
                datetime.now(
                    timezone.utc
                ).isoformat()
            )
            return

        ordered = [
            self.documents[key]
            for key in sorted(
                self.documents
            )
        ]

        new_bm25 = BM25Index().build(
            ordered
        )

        vector_documents = [
            VectorDocument(
                document_id=doc.document_id,
                title=doc.title,
                content=doc.content,
                metadata=doc.metadata,
            )
            for doc in ordered
        ]

        new_vectors = EmbeddingIndex(
            model_name=self.embedding_model
        ).build(
            vector_documents
        )

        # Publish both only after both
        # builds have succeeded.
        self.bm25 = new_bm25
        self.vector_index = new_vectors

        self.version += 1
        self.updated_at = (
            datetime.now(
                timezone.utc
            ).isoformat()
        )
        self.dirty = False

    def _require_fresh_indexes(self):
        if self.dirty:
            raise RuntimeError(
                "Indexes are stale. "
                "Call rebuild() first."
            )

    def search(
        self,
        query,
        tenant_id,
        top_k=5,
        method="bm25",
        extra_filters=None,
    ):
        self._require_fresh_indexes()

        if not tenant_id:
            raise ValueError(
                "tenant_id is required"
            )

        if top_k < 1:
            raise ValueError(
                "top_k must be >= 1"
            )

        filters = dict(
            extra_filters or {}
        )

        # A caller cannot override the
        # authenticated tenant scope.
        filters["tenant_id"] = tenant_id

        if not self.documents:
            return []

        if method == "bm25":
            return self.bm25.search(
                query,
                top_k=top_k,
                filters=filters,
            )

        if method == "semantic":
            return self.vector_index.search(
                query,
                top_k=top_k,
                filters=filters,
            )

        raise ValueError(
            "method must be bm25 or semantic"
        )

    def stats(self):
        return {
            "document_count": len(
                self.documents
            ),
            "version": self.version,
            "updated_at": self.updated_at,
            "dirty": self.dirty,
            "bm25_ready": (
                self.bm25 is not None
                and not self.dirty
            ),
            "semantic_ready": (
                self.vector_index is not None
                and not self.dirty
            ),
            "embedding_model": (
                self.embedding_model
            ),
        }

    def save(self):
        self._require_fresh_indexes()

        root = self.root_dir
        root.mkdir(
            parents=True,
            exist_ok=True,
        )

        manifest = {
            "schema_version": 1,
            "version": self.version,
            "updated_at": self.updated_at,
            "embedding_model": (
                self.embedding_model
            ),
            "documents": [
                {
                    "document_id": (
                        doc.document_id
                    ),
                    "title": doc.title,
                    "content": doc.content,
                    "metadata": doc.metadata,
                }
                for doc in self.documents.values()
            ],
        }

        (
            root / "manifest.json"
        ).write_text(
            json.dumps(
                manifest,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        if self.documents:
            self.bm25.save(
                root / "bm25.json"
            )

            self.vector_index.save(
                root / "vectors"
            )

        return root

    @classmethod
    def load(
        cls,
        root_dir="indexes/retail",
    ):
        root = Path(root_dir)

        manifest = json.loads(
            (
                root / "manifest.json"
            ).read_text(
                encoding="utf-8"
            )
        )

        if manifest.get(
            "schema_version"
        ) != 1:
            raise ValueError(
                "Unsupported schema version"
            )

        manager = cls(
            root_dir=root,
            embedding_model=manifest[
                "embedding_model"
            ],
        )

        documents = [
            SearchDocument(**item)
            for item in manifest[
                "documents"
            ]
        ]

        manager.upsert_many(
            documents
        )

        if documents:
            manager.bm25 = (
                BM25Index.load(
                    root / "bm25.json"
                )
            )

            manager.vector_index = (
                EmbeddingIndex.load(
                    root / "vectors",
                    model_name=(
                        manager.embedding_model
                    ),
                )
            )

            expected_ids = set(
                manager.documents
            )

            bm25_ids = {
                doc.document_id
                for doc in (
                    manager.bm25.documents
                )
            }

            vector_ids = {
                doc.document_id
                for doc in (
                    manager.vector_index.documents
                )
            }

            if (
                bm25_ids != expected_ids
                or vector_ids != expected_ids
            ):
                raise ValueError(
                    "Index/document mismatch"
                )

        manager.version = manifest[
            "version"
        ]

        manager.updated_at = manifest[
            "updated_at"
        ]

        manager.dirty = False

        return manager


if __name__ == "__main__":
    manager = IndexManager()

    manager.upsert_many([
        SearchDocument(
            document_id="INV001",
            title="Inventory Snapshot",
            content=(
                "SKU001 has 120 units "
                "in warehouse A."
            ),
            metadata={
                "tenant_id": "demo",
                "category": "inventory",
            },
        ),
        SearchDocument(
            document_id="SUP002",
            title="Supplier Performance",
            content=(
                "Supplier SUP002 has "
                "an average lead time "
                "of eight days."
            ),
            metadata={
                "tenant_id": "demo",
                "category": "supplier",
            },
        ),
    ])

    manager.rebuild()

    print(
        json.dumps(
            manager.stats(),
            indent=2,
        )
    )

    print(
        manager.search(
            "supplier lead time",
            tenant_id="demo",
            method="bm25",
        )
    )

    print(
        manager.search(
            "How long does delivery take?",
            tenant_id="demo",
            method="semantic",
        )
    )

    manager.save()

    restored = IndexManager.load(
        "indexes/retail"
    )

    print(
        restored.stats()
    )
