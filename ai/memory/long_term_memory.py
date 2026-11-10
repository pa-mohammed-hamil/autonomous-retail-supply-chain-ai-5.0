"""Planned module: long term memory. Implementation pending."""

"""
File: ai/memory/long_term_memory.py
Project: Autonomous Retail Supply Chain AI 5.0

Long-term knowledge management for retail AI agents.

Features:
- Persistent long-term agent knowledge
- Facts, patterns, preferences, and lessons
- Source references
- Knowledge confidence
- Memory importance
- Deduplication using fingerprints
- Knowledge search and retrieval
- Memory correction and invalidation
- Retention and expiration
- Tenant-aware storage

Python 3.10+
Standard library only
"""

from __future__ import annotations

import hashlib
import math
import re

from datetime import datetime, timezone
from typing import Any

from .memory_store import (
    MemoryStore,
    MemoryStoreError,
)


class LongTermMemoryError(ValueError):
    """Invalid long-term memory operation."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LongTermMemoryError(
            f"{name} must be a nonempty string."
        )
    return value.strip()


def validate_score(value: float, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise LongTermMemoryError(
            f"{name} must be between 0 and 1."
        )

    return float(value)


def fingerprint(
    category: str,
    content: str,
) -> str:
    normalized = re.sub(
        r"\s+",
        " ",
        content.strip().lower(),
    )

    payload = f"{category}:{normalized}"

    return hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()


class LongTermMemory:
    """High-level long-term memory service."""

    NAMESPACE = "long_term"

    VALID_CATEGORIES = {
        "fact",
        "pattern",
        "preference",
        "lesson",
        "procedure",
        "business_rule",
    }

    def __init__(
        self,
        store: MemoryStore | None = None,
    ) -> None:
        self.store = store or MemoryStore()

    def remember(
        self,
        tenant_id: str,
        agent_id: str,
        content: str,
        category: str = "fact",
        importance: float = 0.7,
        confidence: float = 0.8,
        source_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        ttl_seconds: int | None = None,
        verified: bool = False,
    ) -> dict[str, Any]:
        tenant_id = require_text(
            tenant_id, "tenant_id"
        )
        agent_id = require_text(
            agent_id, "agent_id"
        )
        content = require_text(
            content, "content"
        )

        if category not in self.VALID_CATEGORIES:
            raise LongTermMemoryError(
                f"Invalid category: {category}"
            )

        importance = validate_score(
            importance, "importance"
        )
        confidence = validate_score(
            confidence, "confidence"
        )

        if metadata is None:
            metadata = {}

        if not isinstance(metadata, dict):
            raise LongTermMemoryError(
                "Metadata must be a dictionary."
            )

        key = fingerprint(
            category, content
        )

        # Check existing memories for exact normalized
        # duplicates within the same agent scope.
        #
        # This is a best-effort application-level check,
        # not an atomic database uniqueness guarantee.
        existing = self.store.list(
            tenant_id=tenant_id,
            agent_id=agent_id,
            namespace=self.NAMESPACE,
            limit=1000,
        )

        for item in existing:
            if item["metadata"].get("fingerprint") == key:
                return {
                    "memory_id": item["memory_id"],
                    "created": False,
                    "duplicate": True,
                }

        full_metadata = {
            **metadata,
            "category": category,
            "confidence": confidence,
            "source_id": source_id,
            "verified": bool(verified),
            "fingerprint": key,
            "status": "active",
            "recorded_at": utc_now(),
        }

        saved = self.store.put(
            tenant_id=tenant_id,
            agent_id=agent_id,
            namespace=self.NAMESPACE,
            content=content,
            metadata=full_metadata,
            importance=importance,
            ttl_seconds=ttl_seconds,
        )

        return {
            **saved,
            "created": True,
            "duplicate": False,
        }

    def recall(
        self,
        tenant_id: str,
        agent_id: str,
        query: str,
        category: str | None = None,
        verified_only: bool = False,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        if (
            category is not None
            and category not in self.VALID_CATEGORIES
        ):
            raise LongTermMemoryError(
                "Invalid category."
            )

        results = self.store.search(
            tenant_id=tenant_id,
            agent_id=agent_id,
            namespace=self.NAMESPACE,
            query=query,
            limit=100,
        )

        filtered = []

        for item in results:
            metadata = item["metadata"]

            if metadata.get("status") != "active":
                continue

            if (
                category is not None
                and metadata.get("category") != category
            ):
                continue

            if (
                verified_only
                and not metadata.get("verified", False)
            ):
                continue

            confidence = metadata.get(
                "confidence", 0.0
            )

            item["knowledge_score"] = round(
                item["retrieval_score"] * 0.7
                + confidence * 0.3,
                4,
            )

            filtered.append(item)

        filtered.sort(
            key=lambda item: (
                -item["knowledge_score"],
                item["memory_id"],
            )
        )

        return filtered[:limit]

    def get(
        self,
        tenant_id: str,
        agent_id: str,
        memory_id: str,
    ) -> dict[str, Any] | None:
        result = self.store.get(
            tenant_id,
            agent_id,
            memory_id,
        )

        if (
            result is None
            or result["namespace"] != self.NAMESPACE
        ):
            return None

        return result

    def correct(
        self,
        tenant_id: str,
        agent_id: str,
        memory_id: str,
        corrected_content: str,
        correction_reason: str,
        source_id: str | None = None,
        verified: bool = False,
    ) -> dict[str, Any]:
        corrected_content = require_text(
            corrected_content, "corrected_content"
        )
        correction_reason = require_text(
            correction_reason, "correction_reason"
        )

        existing = self.get(
            tenant_id,
            agent_id,
            memory_id,
        )

        if existing is None:
            raise LongTermMemoryError(
                "Long-term memory not found."
            )

        metadata = dict(existing["metadata"])
        category = metadata.get("category", "fact")

        history = list(
            metadata.get("correction_history", [])
        )

        history.append({
            "previous_content": existing["content"],
            "reason": correction_reason,
            "corrected_at": utc_now(),
        })

        metadata.update({
            "fingerprint": fingerprint(
                category,
                corrected_content,
            ),
            "source_id": source_id,
            "verified": bool(verified),
            "status": "active",
            "correction_history": history,
        })

        return self.store.update(
            tenant_id=tenant_id,
            agent_id=agent_id,
            memory_id=memory_id,
            content=corrected_content,
            metadata=metadata,
            expected_version=existing["version"],
        )

    def invalidate(
        self,
        tenant_id: str,
        agent_id: str,
        memory_id: str,
        reason: str,
    ) -> dict[str, Any]:
        reason = require_text(
            reason, "reason"
        )

        existing = self.get(
            tenant_id,
            agent_id,
            memory_id,
        )

        if existing is None:
            raise LongTermMemoryError(
                "Long-term memory not found."
            )

        metadata = dict(existing["metadata"])

        metadata.update({
            "status": "invalidated",
            "verified": False,
            "invalidation_reason": reason,
            "invalidated_at": utc_now(),
        })

        return self.store.update(
            tenant_id=tenant_id,
            agent_id=agent_id,
            memory_id=memory_id,
            content=existing["content"],
            metadata=metadata,
            expected_version=existing["version"],
        )

    def forget(
        self,
        tenant_id: str,
        agent_id: str,
        memory_id: str,
    ) -> bool:
        existing = self.get(
            tenant_id,
            agent_id,
            memory_id,
        )

        if existing is None:
            return False

        return self.store.delete(
            tenant_id,
            agent_id,
            memory_id,
        )

    def list_knowledge(
        self,
        tenant_id: str,
        agent_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        records = self.store.list(
            tenant_id=tenant_id,
            agent_id=agent_id,
            namespace=self.NAMESPACE,
            limit=limit,
        )

        return [
            item
            for item in records
            if item["metadata"].get("status") == "active"
        ]

    def statistics(
        self,
        tenant_id: str,
        agent_id: str,
    ) -> dict[str, Any]:
        return self.store.stats(
            tenant_id,
            agent_id,
        )


if __name__ == "__main__":
    memory = LongTermMemory()

    saved = memory.remember(
        tenant_id="retail_company_001",
        agent_id="demand_agent",
        content=(
            "SKU-1001 demand increases during "
            "festival promotions."
        ),
        category="pattern",
        importance=0.95,
        confidence=0.85,
        source_id="sales_report_2026",
        verified=False,
        metadata={
            "product_id": "SKU-1001",
        },
    )

    print("Saved:", saved)

    recalled = memory.recall(
        tenant_id="retail_company_001",
        agent_id="demand_agent",
        query="festival promotions demand",
    )

    print("Recalled:", recalled)
