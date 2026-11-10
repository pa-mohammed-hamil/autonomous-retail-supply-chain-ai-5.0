"""Planned module: feature store. Implementation pending."""

from __future__ import annotations

import os
from typing import Any, Sequence

import chromadb
import numpy as np

from app.vectorstores.base_vector_store import (
    BaseVectorStore,
    SearchResult,
    VectorRecord,
)


class ChromaVectorStore(BaseVectorStore):
    """
    Persistent ChromaDB vector store.

    Use separate collections for incompatible
    embedding models or dimensions.

    Supported distances:
        cosine, l2, ip
    """

    def __init__(
        self,
        persist_directory: str | None = None,
    ):
        self.persist_directory = (
            persist_directory
            or os.getenv(
                "CHROMA_PERSIST_DIR",
                "./data/chroma",
            )
        )

        self.client = chromadb.PersistentClient(
            path=self.persist_directory
        )

    @staticmethod
    def _collection_name(name: str) -> str:
        if not name or not name.strip():
            raise ValueError(
                "Collection name cannot be empty."
            )
        return name.strip()

    def _collection(self, name: str):
        return self.client.get_collection(
            name=self._collection_name(name)
        )

    @staticmethod
    def _where(
        filters: dict[str, Any] | None,
    ) -> dict | None:
        if not filters:
            return None

        conditions = [
            {key: value}
            for key, value in filters.items()
        ]

        if len(conditions) == 1:
            return conditions[0]

        return {"$and": conditions}

    @staticmethod
    def _clean_metadata(
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Chroma metadata should contain supported
        scalar values. Convert unsupported objects
        before indexing.
        """
        cleaned = {}

        for key, value in metadata.items():
            if value is None:
                continue

            if isinstance(value, (str, int, float, bool)):
                if (
                    isinstance(value, float)
                    and not np.isfinite(value)
                ):
                    raise ValueError(
                        f"Invalid metadata value: {key}"
                    )

                cleaned[key] = value

            else:
                raise TypeError(
                    f"Unsupported metadata type "
                    f"for '{key}': {type(value).__name__}"
                )

        return cleaned

    def create_collection(
        self,
        name: str,
        dimension: int,
        *,
        distance: str = "cosine",
    ) -> None:
        if dimension <= 0:
            raise ValueError(
                "Dimension must be positive."
            )

        if distance not in {"cosine", "l2", "ip"}:
            raise ValueError(
                "Unsupported distance metric."
            )

        name = self._collection_name(name)

        try:
            collection = self.client.get_collection(
                name=name
            )
        except chromadb.errors.NotFoundError:
            collection = self.client.create_collection(
                name=name,
                metadata={
                    "hnsw:space": distance,
                    "embedding_dimension": dimension,
                },
            )

        metadata = collection.metadata or {}

        existing_dimension = metadata.get(
            "embedding_dimension"
        )

        if (
            existing_dimension is not None
            and int(existing_dimension) != dimension
        ):
            raise ValueError(
                "Collection dimension mismatch."
            )

        existing_distance = metadata.get(
            "hnsw:space", "l2"
        )

        if existing_distance != distance:
            raise ValueError(
                "Collection distance mismatch."
            )

        if existing_dimension is None:
            raise ValueError(
                "Existing collection lacks explicit "
                "dimension metadata. Migrate or "
                "validate it before reuse."
            )

    def upsert(
        self,
        collection: str,
        records: Sequence[VectorRecord],
    ) -> int:
        if not records:
            return 0

        target = self._collection(collection)

        expected_dimension = (
            (target.metadata or {}).get(
                "embedding_dimension"
            )
        )

        ids = []
        embeddings = []
        metadatas = []
        documents = []

        for record in records:
            if not record.id:
                raise ValueError(
                    "Record ID cannot be empty."
                )

            ids.append(record.id)

            embeddings.append(
                self.validate_vector(
                    record.vector,
                    expected_dimension=(
                        int(expected_dimension)
                        if expected_dimension is not None
                        else None
                    ),
                )
            )

            metadatas.append(
                self._clean_metadata(
                    record.metadata
                )
            )

            documents.append(
                record.document or ""
            )

        if len(ids) != len(set(ids)):
            raise ValueError(
                "Duplicate IDs in upsert batch."
            )

        target.upsert(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
        )

        return len(records)

    def search(
        self,
        collection: str,
        query_vector: Sequence[float] | np.ndarray,
        *,
        limit: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        if not 1 <= limit <= 100:
            raise ValueError(
                "limit must be between 1 and 100."
            )

        target = self._collection(collection)

        if target.count() == 0:
            return []

        expected_dimension = (
            (target.metadata or {}).get(
                "embedding_dimension"
            )
        )

        vector = self.validate_vector(
            query_vector,
            expected_dimension=(
                int(expected_dimension)
                if expected_dimension is not None
                else None
            ),
        )

        result = target.query(
            query_embeddings=[vector],
            n_results=limit,
            where=self._where(filters),
            include=[
                "metadatas",
                "documents",
                "distances",
            ],
        )

        ids = result["ids"][0]
        distances = result["distances"][0]
        metadata = result["metadatas"][0]
        documents = result["documents"][0]

        metric = (target.metadata or {}).get(
            "hnsw:space", "l2"
        )

        matches = []

        for index, record_id in enumerate(ids):
            distance = float(distances[index])

            # For cosine distance, similarity = 1 - d.
            # For l2/ip, return negative distance as
            # a ranking score (not a probability).
            score = (
                1.0 - distance
                if metric == "cosine"
                else -distance
            )

            matches.append(
                SearchResult(
                    id=record_id,
                    score=score,
                    metadata=metadata[index] or {},
                    document=documents[index],
                )
            )

        return matches

    def get(
        self,
        collection: str,
        record_id: str,
    ) -> VectorRecord | None:
        target = self._collection(collection)

        result = target.get(
            ids=[record_id],
            include=[
                "embeddings",
                "metadatas",
                "documents",
            ],
        )

        if not result["ids"]:
            return None

        embeddings = result.get("embeddings")

        if embeddings is None or len(embeddings) == 0:
            raise RuntimeError(
                "Stored vector was not returned."
            )

        return VectorRecord(
            id=result["ids"][0],
            vector=np.asarray(
                embeddings[0],
                dtype=np.float32,
            ),
            metadata=(
                result["metadatas"][0] or {}
            ),
            document=result["documents"][0],
        )

    def delete(
        self,
        collection: str,
        *,
        ids: Sequence[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> int:
        if not ids and not filters:
            raise ValueError(
                "Provide IDs or filters for deletion."
            )

        target = self._collection(collection)

        existing = target.get(
            ids=list(ids) if ids else None,
            where=self._where(filters),
            include=[],
        )

        matched_ids = existing["ids"]

        if not matched_ids:
            return 0

        target.delete(ids=matched_ids)

        return len(matched_ids)

    def count(
        self,
        collection: str,
        *,
        filters: dict[str, Any] | None = None,
    ) -> int:
        target = self._collection(collection)

        if not filters:
            return target.count()

        result = target.get(
            where=self._where(filters),
            include=[],
        )

        return len(result["ids"])

    def list_collections(self) -> list[str]:
        collections = self.client.list_collections()

        return [
            item if isinstance(item, str)
            else item.name
            for item in collections
        ]

    def delete_collection(
        self,
        name: str,
    ) -> None:
        self.client.delete_collection(
            name=self._collection_name(name)
        )


if __name__ == "__main__":
    store = ChromaVectorStore()

    store.create_collection(
        "cineverse_demo",
        dimension=3,
        distance="cosine",
    )

    store.upsert(
        "cineverse_demo",
        [
            VectorRecord(
                id="example-001",
                vector=[0.1, 0.8, 0.3],
                document="A futuristic city at night",
                metadata={
                    "tenant_id": "demo",
                    "owner_id": "user-1",
                    "modality": "text",
                },
            ),
            VectorRecord(
                id="example-002",
                vector=[0.7, 0.1, 0.2],
                document="A peaceful mountain landscape",
                metadata={
                    "tenant_id": "demo",
                    "owner_id": "user-1",
                    "modality": "text",
                },
            ),
        ],
    )

    matches = store.search(
        "cineverse_demo",
        query_vector=[0.2, 0.9, 0.2],
        filters={
            "tenant_id": "demo",
            "owner_id": "user-1",
        },
    )

    for match in matches:
        print(match)
