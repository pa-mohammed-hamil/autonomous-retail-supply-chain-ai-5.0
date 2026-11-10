"""Planned module: checkpointing. Implementation pending."""

"""
File: ai/orchestration/checkpointing.py

SQLite checkpoint storage for multi-agent workflows.
Python 3.10+ | Standard library only
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class CheckpointError(Exception):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CheckpointStore:
    def __init__(
        self,
        database_path: str = "data/workflow_checkpoints.db",
    ) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
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
                CREATE TABLE IF NOT EXISTS checkpoints (
                    workflow_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS checkpoint_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workflow_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

    def save(
        self,
        workflow_id: str,
        tenant_id: str,
        status: str,
        state: dict[str, Any],
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        if not workflow_id or not tenant_id:
            raise CheckpointError(
                "workflow_id and tenant_id are required."
            )

        try:
            serialized = json.dumps(
                state,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise CheckpointError(
                "Workflow state must be JSON serializable."
            ) from exc

        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT version, tenant_id FROM checkpoints "
                "WHERE workflow_id = ?",
                (workflow_id,),
            ).fetchone()

            if existing:
                if existing["tenant_id"] != tenant_id:
                    raise CheckpointError(
                        "Workflow belongs to another tenant."
                    )

                if (
                    expected_version is not None
                    and existing["version"] != expected_version
                ):
                    raise CheckpointError(
                        "Checkpoint version conflict."
                    )

                version = existing["version"] + 1

                conn.execute("""
                    UPDATE checkpoints
                    SET status=?, state_json=?, version=?,
                        updated_at=?
                    WHERE workflow_id=?
                """, (
                    status,
                    serialized,
                    version,
                    utc_now(),
                    workflow_id,
                ))

            else:
                if expected_version not in (None, 0):
                    raise CheckpointError(
                        "Checkpoint does not exist."
                    )

                version = 1

                conn.execute("""
                    INSERT INTO checkpoints (
                        workflow_id, tenant_id, status,
                        state_json, version, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    workflow_id,
                    tenant_id,
                    status,
                    serialized,
                    version,
                    utc_now(),
                ))

        return {
            "workflow_id": workflow_id,
            "tenant_id": tenant_id,
            "status": status,
            "version": version,
        }

    def load(
        self,
        workflow_id: str,
        tenant_id: str,
    ) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM checkpoints "
                "WHERE workflow_id=? AND tenant_id=?",
                (workflow_id, tenant_id),
            ).fetchone()

        if row is None:
            return None

        return {
            "workflow_id": row["workflow_id"],
            "tenant_id": row["tenant_id"],
            "status": row["status"],
            "state": json.loads(row["state_json"]),
            "version": row["version"],
            "updated_at": row["updated_at"],
        }

    def append_event(
        self,
        workflow_id: str,
        tenant_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        with self._lock, self._connect() as conn:
            owner = conn.execute(
                "SELECT tenant_id FROM checkpoints "
                "WHERE workflow_id=?",
                (workflow_id,),
            ).fetchone()

            if owner is None or owner["tenant_id"] != tenant_id:
                raise CheckpointError(
                    "Workflow not found for tenant."
                )

            conn.execute("""
                INSERT INTO checkpoint_events (
                    workflow_id, event_type,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?)
            """, (
                workflow_id,
                event_type,
                json.dumps(payload, allow_nan=False),
                utc_now(),
            ))

    def history(
        self,
        workflow_id: str,
        tenant_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise CheckpointError("Invalid history limit.")

        with self._lock, self._connect() as conn:
            owner = conn.execute(
                "SELECT tenant_id FROM checkpoints "
                "WHERE workflow_id=?",
                (workflow_id,),
            ).fetchone()

            if owner is None or owner["tenant_id"] != tenant_id:
                raise CheckpointError(
                    "Workflow not found for tenant."
                )

            rows = conn.execute("""
                SELECT event_type, payload_json, created_at
                FROM checkpoint_events
                WHERE workflow_id=?
                ORDER BY id DESC
                LIMIT ?
            """, (workflow_id, limit)).fetchall()

        return [
            {
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
