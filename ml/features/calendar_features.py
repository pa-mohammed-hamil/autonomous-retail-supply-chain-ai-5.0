"""Planned module: calendar features. Implementation pending."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np


@dataclass(slots=True)
class VectorRecord:
    id: str
    vector: Sequence[float] | np.ndarray
    metadata: dict[str, Any] = field(
        default_factory=dict
    )
    document: str | None = None


@dataclass(slots=True)
class SearchResult:
    id: str
    score: float
    metadata: dict[str, Any] = field(
        default_factory=dict
    )
    document: str | None = None


class BaseVectorStore(ABC):
    """
    Common vector-store interface for CineVerse AI.

    All vectors within one collection must share:
    - The same embedding dimension
    - A compatible embedding model
    - The same similarity metric

    Authorization must be enforced by the
    application before calling the store.
    """

    @abstractmethod
    def create_collection(
        self,
        name: str,
        dimension: int,
        *,
        distance: str = "cosine",
    ) -> None:
        """Create or validate a collection."""
        raise NotImplementedError

    @abstractmethod
    def upsert(
        self,
        collection: str,
        records: Sequence[VectorRecord],
    ) -> int:
        """Insert or update vector records."""
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        collection: str,
        query_vector: Sequence[float] | np.ndarray,
        *,
        limit: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Return nearest-neighbor matches."""
        raise NotImplementedError

    @abstractmethod
    def get(
        self,
        collection: str,
        record_id: str,
    ) -> VectorRecord | None:
        """Retrieve a stored vector record."""
        raise NotImplementedError

    @abstractmethod
    def delete(
        self,
        collection: str,
        *,
        ids: Sequence[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> int:
        """Delete selected records."""
        raise NotImplementedError

    @abstractmethod
    def count(
        self,
        collection: str,
        *,
        filters: dict[str, Any] | None = None,
    ) -> int:
        """Count records, optionally filtered."""
        raise NotImplementedError

    @abstractmethod
    def list_collections(self) -> list[str]:
        """List available collections."""
        raise NotImplementedError

    @abstractmethod
    def delete_collection(
        self,
        name: str,
    ) -> None:
        """Delete an entire collection."""
        raise NotImplementedError

    @staticmethod
    def validate_vector(
        vector: Sequence[float] | np.ndarray,
        *,
        expected_dimension: int | None = None,
    ) -> list[float]:
        array = np.asarray(
            vector,
            dtype=np.float32,
        )

        if array.ndim != 1 or array.size == 0:
            raise ValueError(
                "Vector must be a non-empty 1D array."
            )

        if not np.all(np.isfinite(array)):
            raise ValueError(
                "Vector contains NaN or infinity."
            )

        if (
            expected_dimension is not None
            and array.size != expected_dimension
        ):
            raise ValueError(
                f"Expected dimension "
                f"{expected_dimension}, "
                f"received {array.size}."
            )

        return array.tolist()

    @staticmethod
    def validate_scope(
        tenant_id: str,
        owner_id: str,
    ) -> None:
        if not tenant_id or not owner_id:
            raise ValueError(
                "tenant_id and owner_id are required."
            )
