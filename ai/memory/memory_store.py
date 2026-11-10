"""Planned module: memory store. Implementation pending."""

"""
File: ai/memory/memory_store.py
Project: Autonomous Retail Supply Chain AI 5.0

Persistent multi-agent memory storage.

Python 3.10+
Standard library only.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import threading

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


class MemoryStoreError(Exception):
    """Memory storage operation failed."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MemoryStoreError(
            f"{name} must be a nonempty string."
        )
    return value.strip()


def validate_limit(value: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= 1000
    ):
        raise MemoryStoreError(
            "Limit must be between 1 and 1000."
        )
    return value


def encode_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise MemoryStoreError(
            "Value must be JSON serializable."
        ) from exc


def tokenize(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.lower()))


class MemoryStore:
    """
    Tenant- and agent-scoped SQLite memory store.

    Memory records are isolated by tenant_id and agent_id.

    The application must derive tenant and agent permissions
    from authenticated identity, not user-supplied claims.
    """

    def __init__(
        self,
        database_path: str = "data/memory_store.db",
    ) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.path),
            timeout=30,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    importance REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT,
                    version INTEGER NOT NULL DEFAULT 1
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_memories_scope
                ON memories (
                    tenant_id,
                    agent_id,
                    namespace
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_memories_expiry
                ON memories(expires_at)
            """)

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["metadata"] = json.loads(
            result.pop("metadata_json")
        )
        return result

    @staticmethod
    def _validate_importance(value: float) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1
        ):
            raise MemoryStoreError(
                "Importance must be between 0 and 1."
            )
        return float(value)

    def put(
        self,
        tenant_id: str,
        agent_id: str,
        namespace: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        importance: float = 0.5,
        ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_text(
            tenant_id, "tenant_id"
        )
        agent_id = require_text(
            agent_id, "agent_id"
        )
        namespace = require_text(
            namespace, "namespace"
        )
        content = require_text(
            content, "content"
        )

        importance = self._validate_importance(
            importance
        )

        if metadata is None:
            metadata = {}

        if not isinstance(metadata, dict):
            raise MemoryStoreError(
                "Metadata must be a dictionary."
            )

        metadata_json = encode_json(metadata)
        expires_at = None

        if ttl_seconds is not None:
            if (
                isinstance(ttl_seconds, bool)
                or not isinstance(ttl_seconds, int)
                or ttl_seconds <= 0
            ):
                raise MemoryStoreError(
                    "ttl_seconds must be positive."
                )

            expires_at = (
                utc_now()
                + timedelta(seconds=ttl_seconds)
            ).isoformat()

        memory_id = str(uuid4())
        timestamp = iso_now()

        with self._lock, self._connect() as conn:
            conn.execute("""
                INSERT INTO memories (
                    memory_id,
                    tenant_id,
                    agent_id,
                    namespace,
                    content,
                    metadata_json,
                    importance,
                    created_at,
                    updated_at,
                    expires_at,
                    version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                memory_id,
                tenant_id,
                agent_id,
                namespace,
                content,
                metadata_json,
                importance,
                timestamp,
                timestamp,
                expires_at,
            ))

        return {
            "memory_id": memory_id,
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "namespace": namespace,
            "importance": importance,
            "created_at": timestamp,
            "expires_at": expires_at,
            "version": 1,
        }

    def get(
        self,
        tenant_id: str,
        agent_id: str,
        memory_id: str,
    ) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("""
                SELECT *
                FROM memories
                WHERE memory_id=?
                  AND tenant_id=?
                  AND agent_id=?
                  AND (
                    expires_at IS NULL
                    OR expires_at > ?
                  )
            """, (
                memory_id,
                tenant_id,
                agent_id,
                iso_now(),
            )).fetchone()

        return self._decode(row) if row else None

    def list(
        self,
        tenant_id: str,
        agent_id: str,
        namespace: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        validate_limit(limit)

        with self._lock, self._connect() as conn:
            rows = conn.execute("""
                SELECT *
                FROM memories
                WHERE tenant_id=?
                  AND agent_id=?
                  AND (
                    ? IS NULL
                    OR namespace=?
                  )
                  AND (
                    expires_at IS NULL
                    OR expires_at > ?
                  )
                ORDER BY importance DESC, created_at DESC
                LIMIT ?
            """, (
                tenant_id,
                agent_id,
                namespace,
                namespace,
                iso_now(),
                limit,
            )).fetchall()

        return [
            self._decode(row)
            for row in rows
        ]

    def search(
        self,
        tenant_id: str,
        agent_id: str,
        query: str,
        namespace: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Keyword search with importance-aware ranking.

        Not semantic/vector similarity search.
        """
        validate_limit(limit)
        query = require_text(query, "query")

        query_tokens = tokenize(query)

        with self._lock, self._connect() as conn:
            rows = conn.execute("""
                SELECT *
                FROM memories
                WHERE tenant_id=?
                  AND agent_id=?
                  AND (
                    ? IS NULL
                    OR namespace=?
                  )
                  AND (
                    expires_at IS NULL
                    OR expires_at > ?
                  )
                ORDER BY created_at DESC
                LIMIT 5000
            """, (
                tenant_id,
                agent_id,
                namespace,
                namespace,
                iso_now(),
            )).fetchall()

        results = []

        for row in rows:
            item = self._decode(row)

            content_tokens = tokenize(
                item["content"]
            )

            matches = len(
                query_tokens & content_tokens
            )

            if matches == 0:
                continue

            relevance = matches / max(
                len(query_tokens), 1
            )

            score = (
                relevance * 0.8
                + item["importance"] * 0.2
            )

            item["retrieval_score"] = round(
                score, 4
            )
            results.append(item)

        results.sort(
            key=lambda item: (
                -item["retrieval_score"],
                item["memory_id"],
            )
        )

        return results[:limit]

    def update(
        self,
        tenant_id: str,
        agent_id: str,
        memory_id: str,
        content: str,
        importance: float | None = None,
        metadata: dict[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        content = require_text(
            content, "content"
        )

        with self._lock, self._connect() as conn:
            row = conn.execute("""
                SELECT *
                FROM memories
                WHERE memory_id=?
                  AND tenant_id=?
                  AND agent_id=?
                  AND (
                    expires_at IS NULL
                    OR expires_at > ?
                  )
            """, (
                memory_id,
                tenant_id,
                agent_id,
                iso_now(),
            )).fetchone()

            if row is None:
                raise MemoryStoreError(
                    "Memory not found."
                )

            if (
                expected_version is not None
                and expected_version != row["version"]
            ):
                raise MemoryStoreError(
                    "Memory version conflict."
                )

            new_importance = (
                row["importance"]
                if importance is None
                else self._validate_importance(
                    importance
                )
            )

            if metadata is None:
                metadata_json = row["metadata_json"]
            else:
                if not isinstance(metadata, dict):
                    raise MemoryStoreError(
                        "Metadata must be a dictionary."
                    )
                metadata_json = encode_json(metadata)

            new_version = row["version"] + 1

            conn.execute("""
                UPDATE memories
                SET content=?,
                    importance=?,
                    metadata_json=?,
                    updated_at=?,
                    version=?
                WHERE memory_id=?
                  AND tenant_id=?
                  AND agent_id=?
            """, (
                content,
                new_importance,
                metadata_json,
                iso_now(),
                new_version,
                memory_id,
                tenant_id,
                agent_id,
            ))

        result = self.get(
            tenant_id,
            agent_id,
            memory_id,
        )

        if result is None:
            raise MemoryStoreError(
                "Memory became unavailable."
            )

        return result

    def delete(
        self,
        tenant_id: str,
        agent_id: str,
        memory_id: str,
    ) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute("""
                DELETE FROM memories
                WHERE memory_id=?
                  AND tenant_id=?
                  AND agent_id=?
            """, (
                memory_id,
                tenant_id,
                agent_id,
            ))

            return cursor.rowcount > 0

    def clear_namespace(
        self,
        tenant_id: str,
        agent_id: str,
        namespace: str,
    ) -> int:
        with self._lock, self._connect() as conn:
            cursor = conn.execute("""
                DELETE FROM memories
                WHERE tenant_id=?
                  AND agent_id=?
                  AND namespace=?
            """, (
                tenant_id,
                agent_id,
                namespace,
            ))

            return cursor.rowcount

    def cleanup_expired(self) -> int:
        with self._lock, self._connect() as conn:
            cursor = conn.execute("""
                DELETE FROM memories
                WHERE expires_at IS NOT NULL
                  AND expires_at <= ?
            """, (iso_now(),))

            return cursor.rowcount

    def stats(
        self,
        tenant_id: str,
        agent_id: str,
    ) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("""
                SELECT namespace, COUNT(*) AS count
                FROM memories
                WHERE tenant_id=?
                  AND agent_id=?
                  AND (
                    expires_at IS NULL
                    OR expires_at > ?
                  )
                GROUP BY namespace
            """, (
                tenant_id,
                agent_id,
                iso_now(),
            )).fetchall()

        counts = {
            row["namespace"]: row["count"]
            for row in rows
        }

        return {
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "total_memories": sum(counts.values()),
            "by_namespace": counts,
        }


if __name__ == "__main__":
    store = MemoryStore()

    saved = store.put(
        tenant_id="retail_company_001",
        agent_id="inventory_agent",
        namespace="inventory",
        content=(
            "SKU-1001 demand rises during "
            "festival promotions."
        ),
        importance=0.9,
        metadata={
            "product_id": "SKU-1001",
        },
    )

    print("Saved:", saved)

    found = store.search(
        tenant_id="retail_company_001",
        agent_id="inventory_agent",
        namespace="inventory",
        query="festival demand SKU-1001",
    )

    print("Search:", found)
