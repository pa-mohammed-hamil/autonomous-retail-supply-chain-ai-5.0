"""Planned module: working memory. Implementation pending."""

"""
File: ai/memory/working_memory.py
Project: Autonomous Retail Supply Chain AI 5.0

Temporary working memory for multi-agent workflows.

Features:
- Agent/task/workflow-scoped working memory
- Thread-safe operations
- JSON-compatible values
- Time-to-live expiration
- Bounded workspace capacity
- Optimistic version control
- Atomic batch updates
- Persistent SQLite snapshots
- Workspace restoration
- Tenant-aware isolation
- Memory usage statistics

Python 3.10+
Standard library only

IMPORTANT:
- Active working memory is held in process memory.
- SQLite snapshots provide optional persistence.
- Separate worker processes do not share live memory.
- Authorization must be enforced at the API boundary.
"""

from __future__ import annotations

import copy
import json
import math
import sqlite3
import threading
import time

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


class WorkingMemoryError(Exception):
    """Base working memory error."""


class WorkspaceNotFound(WorkingMemoryError):
    """Requested workspace does not exist."""


class MemoryCapacityExceeded(WorkingMemoryError):
    """Workspace memory capacity exceeded."""


class MemoryVersionConflict(WorkingMemoryError):
    """Optimistic concurrency version mismatch."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkingMemoryError(
            f"{name} must be a nonempty string."
        )
    return value.strip()


def validate_positive_int(value: Any, name: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        raise WorkingMemoryError(
            f"{name} must be a positive integer."
        )
    return value


def json_copy(value: Any) -> Any:
    try:
        return json.loads(
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
            )
        )
    except (TypeError, ValueError) as exc:
        raise WorkingMemoryError(
            "Working memory values must be JSON serializable."
        ) from exc


def json_size(value: Any) -> int:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    return len(encoded.encode("utf-8"))


@dataclass
class WorkingMemoryEntry:
    key: str
    value: Any
    created_at: str
    updated_at: str
    expires_at: float | None = None


@dataclass
class WorkingWorkspace:
    workspace_id: str
    tenant_id: str
    agent_id: str
    task_id: str
    workflow_id: str
    max_entries: int
    max_bytes: int
    version: int = 1
    entries: dict[str, WorkingMemoryEntry] = field(
        default_factory=dict
    )
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


class WorkingMemory:
    """Thread-safe in-process working memory manager."""

    def __init__(
        self,
        database_path: str = "data/working_memory.db",
        default_max_entries: int = 100,
        default_max_bytes: int = 1_000_000,
    ) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.default_max_entries = validate_positive_int(
            default_max_entries,
            "default_max_entries",
        )

        self.default_max_bytes = validate_positive_int(
            default_max_bytes,
            "default_max_bytes",
        )

        self._workspaces: dict[
            str, WorkingWorkspace
        ] = {}

        self._lock = threading.RLock()
        self._initialize_database()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.database_path),
            timeout=30,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _initialize_database(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS
                working_memory_snapshots (
                    workspace_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    saved_at TEXT NOT NULL
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_working_memory_scope
                ON working_memory_snapshots (
                    tenant_id,
                    agent_id,
                    task_id
                )
            """)

    def _get_workspace(
        self,
        workspace_id: str,
        tenant_id: str,
        agent_id: str,
    ) -> WorkingWorkspace:
        workspace = self._workspaces.get(
            workspace_id
        )

        if (
            workspace is None
            or workspace.tenant_id != tenant_id
            or workspace.agent_id != agent_id
        ):
            raise WorkspaceNotFound(
                "Workspace not found or access denied."
            )

        return workspace

    def _check_version(
        self,
        workspace: WorkingWorkspace,
        expected_version: int | None,
    ) -> None:
        if (
            expected_version is not None
            and expected_version != workspace.version
        ):
            raise MemoryVersionConflict(
                "Working memory version conflict."
            )

    def _remove_expired(
        self,
        workspace: WorkingWorkspace,
    ) -> int:
        now = time.time()

        expired_keys = [
            key
            for key, entry in workspace.entries.items()
            if (
                entry.expires_at is not None
                and entry.expires_at <= now
            )
        ]

        for key in expired_keys:
            del workspace.entries[key]

        if expired_keys:
            workspace.version += 1
            workspace.updated_at = utc_now()

        return len(expired_keys)

    def _validate_capacity(
        self,
        workspace: WorkingWorkspace,
        entries: dict[str, WorkingMemoryEntry],
    ) -> None:
        if len(entries) > workspace.max_entries:
            raise MemoryCapacityExceeded(
                "Maximum workspace entries exceeded."
            )

        serialized = {
            key: entry.value
            for key, entry in entries.items()
        }

        if json_size(serialized) > workspace.max_bytes:
            raise MemoryCapacityExceeded(
                "Maximum workspace size exceeded."
            )

    def create_workspace(
        self,
        tenant_id: str,
        agent_id: str,
        task_id: str,
        workflow_id: str,
        max_entries: int | None = None,
        max_bytes: int | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_text(
            tenant_id, "tenant_id"
        )
        agent_id = require_text(
            agent_id, "agent_id"
        )
        task_id = require_text(
            task_id, "task_id"
        )
        workflow_id = require_text(
            workflow_id, "workflow_id"
        )

        entry_limit = validate_positive_int(
            max_entries
            if max_entries is not None
            else self.default_max_entries,
            "max_entries",
        )

        byte_limit = validate_positive_int(
            max_bytes
            if max_bytes is not None
            else self.default_max_bytes,
            "max_bytes",
        )

        workspace_id = str(uuid4())

        workspace = WorkingWorkspace(
            workspace_id=workspace_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            task_id=task_id,
            workflow_id=workflow_id,
            max_entries=entry_limit,
            max_bytes=byte_limit,
        )

        with self._lock:
            self._workspaces[workspace_id] = workspace

        return {
            "workspace_id": workspace_id,
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "task_id": task_id,
            "workflow_id": workflow_id,
            "version": workspace.version,
            "created_at": workspace.created_at,
        }

    def set(
        self,
        workspace_id: str,
        tenant_id: str,
        agent_id: str,
        key: str,
        value: Any,
        ttl_seconds: float | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        return self.update_many(
            workspace_id=workspace_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            updates={key: value},
            ttl_seconds=ttl_seconds,
            expected_version=expected_version,
        )

    def update_many(
        self,
        workspace_id: str,
        tenant_id: str,
        agent_id: str,
        updates: dict[str, Any],
        ttl_seconds: float | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        if not isinstance(updates, dict) or not updates:
            raise WorkingMemoryError(
                "updates must be a nonempty dictionary."
            )

        for key in updates:
            require_text(key, "memory key")

        if ttl_seconds is not None:
            if (
                isinstance(ttl_seconds, bool)
                or not isinstance(ttl_seconds, (int, float))
                or not math.isfinite(ttl_seconds)
                or ttl_seconds <= 0
            ):
                raise WorkingMemoryError(
                    "ttl_seconds must be positive and finite."
                )

        clean_updates = json_copy(updates)

        with self._lock:
            workspace = self._get_workspace(
                workspace_id,
                tenant_id,
                agent_id,
            )

            self._check_version(
                workspace,
                expected_version,
            )

            self._remove_expired(workspace)

            proposed = copy.deepcopy(
                workspace.entries
            )

            timestamp = utc_now()

            expires_at = (
                time.time() + ttl_seconds
                if ttl_seconds is not None
                else None
            )

            for key, value in clean_updates.items():
                previous = proposed.get(key)

                proposed[key] = WorkingMemoryEntry(
                    key=key,
                    value=value,
                    created_at=(
                        previous.created_at
                        if previous is not None
                        else timestamp
                    ),
                    updated_at=timestamp,
                    expires_at=expires_at,
                )

            self._validate_capacity(
                workspace,
                proposed,
            )

            workspace.entries = proposed
            workspace.version += 1
            workspace.updated_at = timestamp

            return {
                "workspace_id": workspace_id,
                "updated_keys": list(clean_updates),
                "version": workspace.version,
                "entry_count": len(workspace.entries),
            }

    def get(
        self,
        workspace_id: str,
        tenant_id: str,
        agent_id: str,
        key: str,
        default: Any = None,
    ) -> Any:
        with self._lock:
            workspace = self._get_workspace(
                workspace_id,
                tenant_id,
                agent_id,
            )

            self._remove_expired(workspace)

            entry = workspace.entries.get(key)

            if entry is None:
                return copy.deepcopy(default)

            return copy.deepcopy(entry.value)

    def get_all(
        self,
        workspace_id: str,
        tenant_id: str,
        agent_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            workspace = self._get_workspace(
                workspace_id,
                tenant_id,
                agent_id,
            )

            self._remove_expired(workspace)

            return {
                key: copy.deepcopy(entry.value)
                for key, entry in workspace.entries.items()
            }

    def delete(
        self,
        workspace_id: str,
        tenant_id: str,
        agent_id: str,
        key: str,
        expected_version: int | None = None,
    ) -> bool:
        with self._lock:
            workspace = self._get_workspace(
                workspace_id,
                tenant_id,
                agent_id,
            )

            self._check_version(
                workspace,
                expected_version,
            )

            self._remove_expired(workspace)

            if key not in workspace.entries:
                return False

            del workspace.entries[key]
            workspace.version += 1
            workspace.updated_at = utc_now()

            return True

    def clear(
        self,
        workspace_id: str,
        tenant_id: str,
        agent_id: str,
    ) -> int:
        with self._lock:
            workspace = self._get_workspace(
                workspace_id,
                tenant_id,
                agent_id,
            )

            count = len(workspace.entries)
            workspace.entries.clear()
            workspace.version += 1
            workspace.updated_at = utc_now()

            return count

    def snapshot(
        self,
        workspace_id: str,
        tenant_id: str,
        agent_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            workspace = self._get_workspace(
                workspace_id,
                tenant_id,
                agent_id,
            )

            self._remove_expired(workspace)

            return {
                "workspace_id": workspace.workspace_id,
                "tenant_id": workspace.tenant_id,
                "agent_id": workspace.agent_id,
                "task_id": workspace.task_id,
                "workflow_id": workspace.workflow_id,
                "max_entries": workspace.max_entries,
                "max_bytes": workspace.max_bytes,
                "version": workspace.version,
                "created_at": workspace.created_at,
                "updated_at": workspace.updated_at,
                "entries": {
                    key: {
                        "value": copy.deepcopy(entry.value),
                        "created_at": entry.created_at,
                        "updated_at": entry.updated_at,
                        "expires_at": entry.expires_at,
                    }
                    for key, entry in workspace.entries.items()
                },
            }

    def save_snapshot(
        self,
        workspace_id: str,
        tenant_id: str,
        agent_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            snapshot = self.snapshot(
                workspace_id,
                tenant_id,
                agent_id,
            )

            snapshot_json = json.dumps(
                snapshot,
                ensure_ascii=False,
                allow_nan=False,
            )

            with self._connect() as conn:
                row = conn.execute("""
                    SELECT version
                    FROM working_memory_snapshots
                    WHERE workspace_id=?
                      AND tenant_id=?
                      AND agent_id=?
                """, (
                    workspace_id,
                    tenant_id,
                    agent_id,
                )).fetchone()

                if (
                    row is not None
                    and row["version"] > snapshot["version"]
                ):
                    raise MemoryVersionConflict(
                        "A newer snapshot already exists."
                    )

                conn.execute("""
                    INSERT INTO working_memory_snapshots (
                        workspace_id,
                        tenant_id,
                        agent_id,
                        task_id,
                        workflow_id,
                        version,
                        snapshot_json,
                        saved_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workspace_id)
                    DO UPDATE SET
                        version=excluded.version,
                        snapshot_json=excluded.snapshot_json,
                        saved_at=excluded.saved_at
                """, (
                    workspace_id,
                    tenant_id,
                    agent_id,
                    snapshot["task_id"],
                    snapshot["workflow_id"],
                    snapshot["version"],
                    snapshot_json,
                    utc_now(),
                ))

            return {
                "workspace_id": workspace_id,
                "saved": True,
                "version": snapshot["version"],
            }

    def restore_snapshot(
        self,
        workspace_id: str,
        tenant_id: str,
        agent_id: str,
    ) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            row = conn.execute("""
                SELECT snapshot_json
                FROM working_memory_snapshots
                WHERE workspace_id=?
                  AND tenant_id=?
                  AND agent_id=?
            """, (
                workspace_id,
                tenant_id,
                agent_id,
            )).fetchone()

            if row is None:
                raise WorkspaceNotFound(
                    "Saved workspace not found."
                )

            data = json.loads(
                row["snapshot_json"]
            )

            if (
                data["workspace_id"] != workspace_id
                or data["tenant_id"] != tenant_id
                or data["agent_id"] != agent_id
            ):
                raise WorkingMemoryError(
                    "Snapshot identity mismatch."
                )

            entries = {}

            for key, item in data["entries"].items():
                entries[key] = WorkingMemoryEntry(
                    key=key,
                    value=item["value"],
                    created_at=item["created_at"],
                    updated_at=item["updated_at"],
                    expires_at=item["expires_at"],
                )

            restored = WorkingWorkspace(
                workspace_id=data["workspace_id"],
                tenant_id=data["tenant_id"],
                agent_id=data["agent_id"],
                task_id=data["task_id"],
                workflow_id=data["workflow_id"],
                max_entries=data["max_entries"],
                max_bytes=data["max_bytes"],
                version=data["version"],
                entries=entries,
                created_at=data["created_at"],
                updated_at=data["updated_at"],
            )

            self._remove_expired(restored)
            self._validate_capacity(
                restored,
                restored.entries,
            )

            existing = self._workspaces.get(workspace_id)

            if (
                existing is not None
                and existing.version > restored.version
            ):
                raise MemoryVersionConflict(
                    "Live workspace is newer than snapshot."
                )

            self._workspaces[workspace_id] = restored

            return self.snapshot(
                workspace_id,
                tenant_id,
                agent_id,
            )

    def close_workspace(
        self,
        workspace_id: str,
        tenant_id: str,
        agent_id: str,
        delete_snapshot: bool = False,
    ) -> bool:
        with self._lock:
            self._get_workspace(
                workspace_id,
                tenant_id,
                agent_id,
            )

            del self._workspaces[workspace_id]

            if delete_snapshot:
                with self._connect() as conn:
                    conn.execute("""
                        DELETE FROM working_memory_snapshots
                        WHERE workspace_id=?
                          AND tenant_id=?
                          AND agent_id=?
                    """, (
                        workspace_id,
                        tenant_id,
                        agent_id,
                    ))

            return True

    def stats(
        self,
        workspace_id: str,
        tenant_id: str,
        agent_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            workspace = self._get_workspace(
                workspace_id,
                tenant_id,
                agent_id,
            )

            self._remove_expired(workspace)

            values = {
                key: entry.value
                for key, entry in workspace.entries.items()
            }

            used_bytes = json_size(values)

            return {
                "workspace_id": workspace_id,
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "task_id": workspace.task_id,
                "workflow_id": workspace.workflow_id,
                "version": workspace.version,
                "entry_count": len(workspace.entries),
                "max_entries": workspace.max_entries,
                "used_bytes": used_bytes,
                "max_bytes": workspace.max_bytes,
                "utilization_percent": round(
                    used_bytes / workspace.max_bytes * 100,
                    2,
                ),
            }


if __name__ == "__main__":
    memory = WorkingMemory()

    workspace = memory.create_workspace(
        tenant_id="retail_company_001",
        agent_id="inventory_agent",
        task_id="TASK-001",
        workflow_id="WF-001",
    )

    workspace_id = workspace["workspace_id"]

    memory.update_many(
        workspace_id=workspace_id,
        tenant_id="retail_company_001",
        agent_id="inventory_agent",
        updates={
            "product_id": "SKU-1001",
            "current_stock": 80,
            "forecast_demand": 250,
            "reorder_point": 100,
        },
        ttl_seconds=3600,
    )

    print("Current memory:")
    print(
        memory.get_all(
            workspace_id,
            "retail_company_001",
            "inventory_agent",
        )
    )

    memory.set(
        workspace_id,
        "retail_company_001",
        "inventory_agent",
        "recommended_order",
        170,
    )

    print("Statistics:")
    print(
        memory.stats(
            workspace_id,
            "retail_company_001",
            "inventory_agent",
        )
    )

    print("Saving snapshot:")
    print(
        memory.save_snapshot(
            workspace_id,
            "retail_company_001",
            "inventory_agent",
        )
    )

    memory.close_workspace(
        workspace_id,
        "retail_company_001",
        "inventory_agent",
    )

    print("Restored snapshot:")
    print(
        memory.restore_snapshot(
            workspace_id,
            "retail_company_001",
            "inventory_agent",
        )
    )
