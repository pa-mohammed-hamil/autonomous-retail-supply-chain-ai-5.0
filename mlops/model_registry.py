"""Planned module: model registry. Implementation pending."""

"""
ai/mlops/model_registry.py

SQLite-backed AI model registry.

Features:
- Model version registration
- SHA-256 artifact verification
- Lifecycle transitions
- Evaluation metadata
- Model card references
- Approval metadata
- Audit history

This registry stores metadata and does not
execute or serve model checkpoints.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ModelRegistry:

    TRANSITIONS = {
        "registered": {"validated", "archived"},
        "validated": {"staging", "archived"},
        "staging": {"production", "archived"},
        "production": {"archived"},
        "archived": set(),
    }

    def __init__(
        self,
        database_path: str = (
            "storage/mlops/model_registry.db"
        ),
    ):
        path = Path(database_path)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.database_path = str(path)
        self._initialize()

    @staticmethod
    def _now():
        return datetime.now(
            timezone.utc
        ).isoformat()

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()

        with path.open("rb") as file:
            for chunk in iter(
                lambda: file.read(1024 * 1024),
                b"",
            ):
                digest.update(chunk)

        return digest.hexdigest()

    def _connect(self):
        conn = sqlite3.connect(
            self.database_path,
            timeout=10,
        )
        conn.row_factory = sqlite3.Row
        conn.execute(
            "PRAGMA foreign_keys = ON"
        )
        conn.execute(
            "PRAGMA busy_timeout = 10000"
        )
        return conn

    def _initialize(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS models (
                    model_id TEXT PRIMARY KEY,
                    model_name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    artifact_path TEXT NOT NULL,
                    artifact_sha256 TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    model_card_path TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(model_name, version)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS history (
                    event_id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    from_stage TEXT,
                    to_stage TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    approval_reference TEXT,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY(model_id)
                        REFERENCES models(model_id)
                )
            """)

    def register(
        self,
        model_name: str,
        version: str,
        artifact_path: str,
        metrics: dict[str, float],
        model_card_path: str | None = None,
        metadata: dict[str, Any] | None = None,
        actor: str = "system",
    ) -> dict:

        path = Path(artifact_path).resolve()

        if not path.is_file():
            raise FileNotFoundError(path)

        if not model_name or not version:
            raise ValueError(
                "Model name and version required"
            )

        model_id = uuid.uuid4().hex
        artifact_hash = self._hash_file(path)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO models (
                    model_id, model_name, version,
                    artifact_path, artifact_sha256,
                    stage, metrics_json,
                    model_card_path, metadata_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model_id,
                    model_name,
                    version,
                    str(path),
                    artifact_hash,
                    "registered",
                    json.dumps(
                        metrics,
                        allow_nan=False,
                    ),
                    model_card_path,
                    json.dumps(
                        metadata or {},
                        allow_nan=False,
                    ),
                    self._now(),
                ),
            )

            conn.execute(
                """
                INSERT INTO history (
                    event_id, model_id,
                    from_stage, to_stage,
                    actor, approval_reference,
                    timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    model_id,
                    None,
                    "registered",
                    actor,
                    None,
                    self._now(),
                ),
            )

        return {
            "model_id": model_id,
            "model_name": model_name,
            "version": version,
            "stage": "registered",
            "artifact_sha256": artifact_hash,
        }

    def get(
        self,
        model_name: str,
        version: str,
    ) -> dict:

        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM models
                WHERE model_name = ?
                  AND version = ?
                """,
                (model_name, version),
            ).fetchone()

        if row is None:
            raise ValueError(
                "Model not found"
            )

        result = dict(row)
        result["metrics"] = json.loads(
            result.pop("metrics_json")
        )
        result["metadata"] = json.loads(
            result.pop("metadata_json")
        )

        return result

    def verify_artifact(
        self,
        model_name: str,
        version: str,
    ) -> bool:

        model = self.get(
            model_name,
            version,
        )

        path = Path(
            model["artifact_path"]
        )

        return (
            path.is_file()
            and self._hash_file(path)
            == model["artifact_sha256"]
        )

    def transition(
        self,
        model_name: str,
        version: str,
        target_stage: str,
        actor: str,
        approval_reference: str | None = None,
    ) -> dict:

        if not actor:
            raise ValueError(
                "Actor required"
            )

        if target_stage not in {
            *self.TRANSITIONS.keys()
        }:
            raise ValueError(
                "Invalid lifecycle stage"
            )

        if not self.verify_artifact(
            model_name,
            version,
        ):
            raise ValueError(
                "Artifact verification failed"
            )

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")

            row = conn.execute(
                """
                SELECT model_id, stage
                FROM models
                WHERE model_name = ?
                  AND version = ?
                """,
                (model_name, version),
            ).fetchone()

            if row is None:
                raise ValueError(
                    "Model not found"
                )

            current_stage = row["stage"]

            if target_stage not in (
                self.TRANSITIONS[current_stage]
            ):
                raise ValueError(
                    "Invalid stage transition: "
                    f"{current_stage} -> {target_stage}"
                )

            if (
                target_stage == "production"
                and not approval_reference
            ):
                raise PermissionError(
                    "Production approval reference required"
                )

            conn.execute(
                """
                UPDATE models
                SET stage = ?
                WHERE model_id = ?
                """,
                (
                    target_stage,
                    row["model_id"],
                ),
            )

            conn.execute(
                """
                INSERT INTO history (
                    event_id, model_id,
                    from_stage, to_stage,
                    actor, approval_reference,
                    timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    row["model_id"],
                    current_stage,
                    target_stage,
                    actor,
                    approval_reference,
                    self._now(),
                ),
            )

        return {
            "model_name": model_name,
            "version": version,
            "previous_stage": current_stage,
            "stage": target_stage,
            "actor": actor,
        }

    def list_versions(
        self,
        model_name: str,
    ) -> list[dict]:

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT model_id, model_name,
                       version, stage, created_at
                FROM models
                WHERE model_name = ?
                ORDER BY created_at DESC
                """,
                (model_name,),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]

    def history(
        self,
        model_name: str,
        version: str,
    ) -> list[dict]:

        model = self.get(
            model_name,
            version,
        )

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM history
                WHERE model_id = ?
                ORDER BY rowid ASC
                """,
                (model["model_id"],),
            ).fetchall()

        return [
            dict(row)
            for row in rows
        ]
