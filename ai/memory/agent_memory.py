"""Planned module: agent memory. Implementation pending."""

"""
File: ai/memory/agent_memory.py
Project: Autonomous Retail Supply Chain AI 5.0

Persistent multi-agent memory.

Features:
- Short-term and long-term memory
- Agent-specific and tenant-specific storage
- Importance scoring
- Keyword retrieval
- Memory expiration
- Memory updates and deletion
- SQLite persistence
- Structured agent-friendly results

Python 3.10+ | Standard library only
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


class AgentMemoryError(ValueError):
    """Invalid agent memory operation."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def validate_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentMemoryError(
            f"{name} must be a nonempty string."
        )
    return value.strip()


def json_encode(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise AgentMemoryError(
            "Metadata must be JSON serializable."
        ) from exc


class AgentMemory:
    """Persistent memory manager for AI agents."""

    VALID_TYPES = {"short_term", "long_term"}

    def __init__(
        self,
        database_path: str = "data/agent_memory.db",
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
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_memories (
                    memory_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    importance REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_agent_memory_scope
                ON agent_memories (
                    tenant_id, agent_id, memory_type
                )
            """)

    def _row_to_dict(
        self,
        row: sqlite3.Row,
    ) -> dict[str, Any]:
        result = dict(row)
        result["metadata"] = json.loads(
            result.pop("metadata_json")
        )
        return result

    def remember(
        self,
        tenant_id: str,
        agent_id: str,
        content: str,
        memory_type: str = "short_term",
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
        ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        tenant_id = validate_text(
            tenant_id, "tenant_id"
        )
        agent_id = validate_text(
            agent_id, "agent_id"
        )
        content = validate_text(
            content, "content"
        )

        if memory_type not in self.VALID_TYPES:
            raise AgentMemoryError(
                "Invalid memory type."
            )

        if (
            isinstance(importance, bool)
            or not isinstance(importance, (int, float))
            or not math.isfinite(importance)
            or not 0 <= importance <= 1
        ):
            raise AgentMemoryError(
                "Importance must be between 0 and 1."
            )

        if metadata is not None and not isinstance(metadata, dict):
            raise AgentMemoryError(
                "Metadata must be a dictionary."
            )

        expires_at = None

        if ttl_seconds is not None:
            if (
                isinstance(ttl_seconds, bool)
                or not isinstance(ttl_seconds, int)
                or ttl_seconds <= 0
            ):
                raise AgentMemoryError(
                    "ttl_seconds must be positive."
                )

            expires_at = (
                utc_now() + timedelta(seconds=ttl_seconds)
            ).isoformat()

        memory_id = str(uuid4())
        timestamp = iso_now()

        with self._lock, self._connect() as conn:
            conn.execute("""
                INSERT INTO agent_memories (
                    memory_id, tenant_id, agent_id,
                    memory_type, content, metadata_json,
                    importance, created_at, updated_at,
                    expires_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                memory_id,
                tenant_id,
                agent_id,
                memory_type,
                content,
                json_encode(metadata or {}),
                float(importance),
                timestamp,
                timestamp,
                expires_at,
            ))

        return {
            "memory_id": memory_id,
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "memory_type": memory_type,
            "importance": importance,
            "expires_at": expires_at,
            "created_at": timestamp,
        }

    def get_memory(
        self,
        tenant_id: str,
        agent_id: str,
        memory_id: str,
    ) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("""
                SELECT *
                FROM agent_memories
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

        return (
            self._row_to_dict(row)
            if row is not None
            else None
        )

    def search(
        self,
        tenant_id: str,
        agent_id: str,
        query: str,
        memory_type: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Simple keyword-based memory retrieval.

        This is not vector semantic search.
        """
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise AgentMemoryError(
                "limit must be between 1 and 100."
            )

        if (
            memory_type is not None
            and memory_type not in self.VALID_TYPES
        ):
            raise AgentMemoryError(
                "Invalid memory type."
            )

        query = validate_text(query, "query")
        tokens = set(
            re.findall(r"\w+", query.lower())
        )

        with self._lock, self._connect() as conn:
            rows = conn.execute("""
                SELECT *
                FROM agent_memories
                WHERE tenant_id=?
                  AND agent_id=?
                  AND (
                    expires_at IS NULL
                    OR expires_at > ?
                  )
                  AND (
                    ? IS NULL
                    OR memory_type=?
                  )
                ORDER BY importance DESC, created_at DESC
                LIMIT 5000
            """, (
                tenant_id,
                agent_id,
                iso_now(),
                memory_type,
                memory_type,
            )).fetchall()

        ranked = []

        for row in rows:
            memory = self._row_to_dict(row)

            content_tokens = set(
                re.findall(
                    r"\w+",
                    memory["content"].lower(),
                )
            )

            overlap = len(
                tokens & content_tokens
            )

            if overlap == 0:
                continue

            relevance = (
                overlap / max(len(tokens), 1)
            )

            score = (
                relevance * 0.75
                + memory["importance"] * 0.25
            )

            memory["retrieval_score"] = round(
                score, 4
            )

            ranked.append(memory)

        ranked.sort(
            key=lambda item: (
                -item["retrieval_score"],
                item["memory_id"],
            )
        )

        return ranked[:limit]

    def list_memories(
        self,
        tenant_id: str,
        agent_id: str,
        memory_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise AgentMemoryError(
                "Invalid limit."
            )

        with self._lock, self._connect() as conn:
            rows = conn.execute("""
                SELECT *
                FROM agent_memories
                WHERE tenant_id=?
                  AND agent_id=?
                  AND (
                    expires_at IS NULL
                    OR expires_at > ?
                  )
                  AND (
                    ? IS NULL
                    OR memory_type=?
                  )
                ORDER BY created_at DESC
                LIMIT ?
            """, (
                tenant_id,
                agent_id,
                iso_now(),
                memory_type,
                memory_type,
                limit,
            )).fetchall()

        return [
            self._row_to_dict(row)
            for row in rows
        ]

    def update_memory(
        self,
        tenant_id: str,
        agent_id: str,
        memory_id: str,
        content: str,
        importance: float | None = None,
    ) -> bool:
        content = validate_text(
            content, "content"
        )

        with self._lock, self._connect() as conn:
            row = conn.execute("""
                SELECT importance
                FROM agent_memories
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
                return False

            new_importance = (
                row["importance"]
                if importance is None
                else importance
            )

            if (
                isinstance(new_importance, bool)
                or not isinstance(new_importance, (int, float))
                or not math.isfinite(new_importance)
                or not 0 <= new_importance <= 1
            ):
                raise AgentMemoryError(
                    "Invalid importance."
                )

            conn.execute("""
                UPDATE agent_memories
                SET content=?, importance=?, updated_at=?
                WHERE memory_id=?
                  AND tenant_id=?
                  AND agent_id=?
            """, (
                content,
                float(new_importance),
                iso_now(),
                memory_id,
                tenant_id,
                agent_id,
            ))

        return True

    def delete_memory(
        self,
        tenant_id: str,
        agent_id: str,
        memory_id: str,
    ) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute("""
                DELETE FROM agent_memories
                WHERE memory_id=?
                  AND tenant_id=?
                  AND agent_id=?
            """, (
                memory_id,
                tenant_id,
                agent_id,
            ))

            return cursor.rowcount > 0

    def clear_agent_memory(
        self,
        tenant_id: str,
        agent_id: str,
        memory_type: str | None = None,
    ) -> int:
        if (
            memory_type is not None
            and memory_type not in self.VALID_TYPES
        ):
            raise AgentMemoryError(
                "Invalid memory type."
            )

        with self._lock, self._connect() as conn:
            cursor = conn.execute("""
                DELETE FROM agent_memories
                WHERE tenant_id=?
                  AND agent_id=?
                  AND (
                    ? IS NULL
                    OR memory_type=?
                  )
            """, (
                tenant_id,
                agent_id,
                memory_type,
                memory_type,
            ))

            return cursor.rowcount

    def cleanup_expired(self) -> int:
        with self._lock, self._connect() as conn:
            cursor = conn.execute("""
                DELETE FROM agent_memories
                WHERE expires_at IS NOT NULL
                  AND expires_at <= ?
            """, (iso_now(),))

            return cursor.rowcount


if __name__ == "__main__":
    memory = AgentMemory()

    saved = memory.remember(
        tenant_id="retail_company_001",
        agent_id="inventory_agent",
        content=(
            "SKU-1001 has high demand "
            "during seasonal promotions."
        ),
        memory_type="long_term",
        importance=0.9,
        metadata={
            "product_id": "SKU-1001",
            "category": "inventory",
        },
    )

    print("Saved:", saved)

    results = memory.search(
        tenant_id="retail_company_001",
        agent_id="inventory_agent",
        query="seasonal demand SKU-1001",
    )

    print("Retrieved:", results)
