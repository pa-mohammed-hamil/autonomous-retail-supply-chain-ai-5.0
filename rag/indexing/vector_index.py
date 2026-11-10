"""Planned module: vector index. Implementation pending."""

"""
ai/retrieval/vector_index.py

Autonomous Retail Supply Chain AI 5.0
FAISS Vector Index

Install:
    pip install faiss-cpu numpy sentence-transformers

Run:
    python -m ai.retrieval.vector_index

Designed for small/medium RAG collections.
For production, add authentication, durable
transactional storage, and concurrency control.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


@dataclass
class VectorRecord:
    document_id: str
    content: str
    title: str = ""
    metadata: dict[str, Any] = field(
        default_factory=dict
    )


class RetailVectorIndex:
    def __init__(
        self,
        model_name=(
            "sentence-transformers/"
            "all-MiniLM-L6-v2"
        ),
        batch_size=32,
    ):
        self.model_name = model_name
        self.batch_size = batch_size

        self.encoder = SentenceTransformer(
            model_name
        )

        self.dimension = int(
            self.encoder.get_sentence_embedding_dimension()
        )

        self.index = faiss.IndexFlatIP(
            self.dimension
        )

        self.records = []
        self.vectors = np.empty(
            (0, self.dimension),
            dtype=np.float32,
        )

    def _encode(self, texts):
        if not texts:
            return np.empty(
                (0, self.dimension),
                dtype=np.float32,
            )

        vectors = self.encoder.encode(
            texts,
            batch_size=self.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

        vectors = np.asarray(
            vectors,
            dtype=np.float32,
        ).reshape(-1, self.dimension)

        if not np.isfinite(vectors).all():
            raise ValueError(
                "Embedding contains NaN or infinity"
            )

        # Explicit normalization guarantees
        # inner product == cosine similarity.
        faiss.normalize_L2(vectors)

        return vectors

    @staticmethod
    def _validate_record(record):
        if not record.document_id.strip():
            raise ValueError(
                "document_id is required"
            )

        if not record.content.strip():
            raise ValueError(
                "Document content is required"
            )

        tenant_id = record.metadata.get(
            "tenant_id"
        )

        if (
            not isinstance(tenant_id, str)
            or not tenant_id.strip()
        ):
            raise ValueError(
                "metadata.tenant_id is required"
            )

    def _rebuild_faiss(self):
        new_index = faiss.IndexFlatIP(
            self.dimension
        )

        if len(self.vectors):
            new_index.add(
                np.ascontiguousarray(
                    self.vectors
                )
            )

        self.index = new_index

    def upsert(self, records):
        """
        Insert or replace records.

        Uses a full FAISS rebuild after updates
        to maintain consistent row positions.
        """
        records = list(records)

        if not records:
            return

        for record in records:
            self._validate_record(record)

        ids = [
            record.document_id
            for record in records
        ]

        if len(ids) != len(set(ids)):
            raise ValueError(
                "Duplicate IDs in input batch"
            )

        existing = {
            record.document_id: index
            for index, record
            in enumerate(self.records)
        }

        # Prevent changing the tenant of an
        # existing ID by accident.
        for record in records:
            old_index = existing.get(
                record.document_id
            )

            if old_index is not None:
                old_tenant = (
                    self.records[old_index]
                    .metadata["tenant_id"]
                )

                if (
                    old_tenant
                    != record.metadata["tenant_id"]
                ):
                    raise ValueError(
                        "Cannot change document tenant"
                    )

        new_vectors = self._encode(
            [record.content for record in records]
        )

        replacement_ids = set(ids)

        keep_indices = [
            index
            for index, record
            in enumerate(self.records)
            if record.document_id
            not in replacement_ids
        ]

        kept_records = [
            self.records[index]
            for index in keep_indices
        ]

        kept_vectors = self.vectors[
            keep_indices
        ]

        combined_records = (
            kept_records + records
        )

        combined_vectors = np.vstack([
            kept_vectors,
            new_vectors,
        ]).astype(np.float32)

        # Build before replacing active state.
        replacement_index = (
            faiss.IndexFlatIP(
                self.dimension
            )
        )

        replacement_index.add(
            np.ascontiguousarray(
                combined_vectors
            )
        )

        self.records = combined_records
        self.vectors = combined_vectors
        self.index = replacement_index

    def delete(
        self,
        document_id,
        tenant_id,
    ):
        keep_indices = [
            index
            for index, record
            in enumerate(self.records)
            if not (
                record.document_id == document_id
                and record.metadata.get(
                    "tenant_id"
                ) == tenant_id
            )
        ]

        if len(keep_indices) == len(
            self.records
        ):
            return False

        self.records = [
            self.records[index]
            for index in keep_indices
        ]

        self.vectors = self.vectors[
            keep_indices
        ]

        self._rebuild_faiss()
        return True

    @staticmethod
    def _matches(
        record,
        tenant_id,
        filters,
    ):
        if (
            record.metadata.get("tenant_id")
            != tenant_id
        ):
            return False

        for key, expected in (
            filters or {}
        ).items():
            if (
                record.metadata.get(key)
                != expected
            ):
                return False

        return True

    def search(
        self,
        query,
        tenant_id,
        top_k=5,
        filters=None,
    ):
        if not tenant_id:
            raise ValueError(
                "Authenticated tenant_id required"
            )

        if top_k < 1:
            raise ValueError(
                "top_k must be positive"
            )

        if not query.strip():
            return []

        if not self.records:
            return []

        query_vector = self._encode(
            [query]
        )

        # Exact filtering first prevents
        # unrelated tenant documents from
        # entering the candidate ranking.
        eligible_indices = [
            i
            for i, record
            in enumerate(self.records)
            if self._matches(
                record,
                tenant_id,
                filters,
            )
        ]

        if not eligible_indices:
            return []

        # A filtered temporary FAISS index.
        # For large deployments use a vector
        # database with native payload filters.
        eligible_vectors = (
            np.ascontiguousarray(
                self.vectors[
                    eligible_indices
                ]
            )
        )

        filtered_index = (
            faiss.IndexFlatIP(
                self.dimension
            )
        )

        filtered_index.add(
            eligible_vectors
        )

        count = min(
            top_k,
            len(eligible_indices),
        )

        scores, positions = (
            filtered_index.search(
                query_vector,
                count,
            )
        )

        results = []

        for score, position in zip(
            scores[0],
            positions[0],
        ):
            if position < 0:
                continue

            original_index = (
                eligible_indices[
                    int(position)
                ]
            )

            record = self.records[
                original_index
            ]

            results.append({
                "document_id": (
                    record.document_id
                ),
                "title": record.title,
                "content": record.content,
                "metadata": record.metadata,
                "score": float(score),
                "retrieval_method": (
                    "faiss_cosine"
                ),
            })

        return results

    def stats(self):
        tenants = {
            record.metadata["tenant_id"]
            for record in self.records
        }

        return {
            "document_count": len(
                self.records
            ),
            "vector_count": int(
                self.index.ntotal
            ),
            "dimension": self.dimension,
            "tenant_count": len(tenants),
            "model_name": self.model_name,
            "index_type": "IndexFlatIP",
        }

    def save(
        self,
        directory="indexes/faiss",
    ):
        """
        Saves metadata and vectors.

        Loading reconstructs the FAISS
        index from vectors rather than
        deserializing a native FAISS file.
        """
        path = Path(directory)
        path.mkdir(
            parents=True,
            exist_ok=True,
        )

        np.save(
            path / "vectors.npy",
            self.vectors,
            allow_pickle=False,
        )

        payload = {
            "version": 1,
            "model_name": self.model_name,
            "dimension": self.dimension,
            "records": [
                {
                    "document_id": (
                        record.document_id
                    ),
                    "content": record.content,
                    "title": record.title,
                    "metadata": record.metadata,
                }
                for record in self.records
            ],
        }

        (
            path / "metadata.json"
        ).write_text(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return path

    @classmethod
    def load(
        cls,
        directory="indexes/faiss",
    ):
        path = Path(directory)

        payload = json.loads(
            (
                path / "metadata.json"
            ).read_text(
                encoding="utf-8"
            )
        )

        if payload.get("version") != 1:
            raise ValueError(
                "Unsupported index version"
            )

        instance = cls(
            model_name=payload[
                "model_name"
            ]
        )

        vectors = np.load(
            path / "vectors.npy",
            allow_pickle=False,
        )

        records = [
            VectorRecord(**item)
            for item in payload[
                "records"
            ]
        ]

        for record in records:
            instance._validate_record(
                record
            )

        if (
            vectors.ndim != 2
            or vectors.shape[1]
            != instance.dimension
            or len(vectors) != len(records)
        ):
            raise ValueError(
                "Stored vector shape mismatch"
            )

        if not np.isfinite(
            vectors
        ).all():
            raise ValueError(
                "Stored vectors contain "
                "invalid values"
            )

        ids = [
            record.document_id
            for record in records
        ]

        if len(ids) != len(set(ids)):
            raise ValueError(
                "Duplicate stored document IDs"
            )

        vectors = np.asarray(
            vectors,
            dtype=np.float32,
        )

        if len(vectors):
            norms = np.linalg.norm(
                vectors,
                axis=1,
            )

            if np.any(norms < 1e-12):
                raise ValueError(
                    "Zero-length stored vectors"
                )

            faiss.normalize_L2(
                vectors
            )

        instance.records = records
        instance.vectors = vectors
        instance._rebuild_faiss()

        return instance


if __name__ == "__main__":
    index = RetailVectorIndex()

    index.upsert([
        VectorRecord(
            document_id="INV001",
            title="Inventory Snapshot",
            content=(
                "SKU001 has 120 units "
                "available in warehouse A."
            ),
            metadata={
                "tenant_id": "demo",
                "category": "inventory",
            },
        ),
        VectorRecord(
            document_id="SUP002",
            title="Supplier Report",
            content=(
                "Supplier SUP002 has an "
                "average lead time "
                "of eight days."
            ),
            metadata={
                "tenant_id": "demo",
                "category": "supplier",
            },
        ),
        VectorRecord(
            document_id="LOG003",
            title="Logistics Report",
            content=(
                "Shipment SH003 was "
                "delayed by road traffic."
            ),
            metadata={
                "tenant_id": "demo",
                "category": "logistics",
            },
        ),
    ])

    results = index.search(
        query=(
            "Which supplier has "
            "a long delivery time?"
        ),
        tenant_id="demo",
        top_k=3,
    )

    print(
        json.dumps(
            results,
            indent=2,
        )
    )

    index.save()

    restored = RetailVectorIndex.load(
        "indexes/faiss"
    )

    print(
        json.dumps(
            restored.stats(),
            indent=2,
        )
    )

    removed = restored.delete(
        document_id="LOG003",
        tenant_id="demo",
    )

    print("Deleted:", removed)
