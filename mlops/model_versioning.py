"""Planned module: model versioning. Implementation pending."""

"""
ai/mlops/model_versioning.py

Local model artifact versioning.

Features:
- Versioned artifact snapshots
- SHA-256 content verification
- SQLite metadata registry
- Duplicate version protection
- Version comparison
- Model retrieval

Local filesystem snapshots are not tamper-proof.
Use immutable object storage in production.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import uuid

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ModelVersioning:

    SAFE_NAME = re.compile(
        r"^[A-Za-z0-9_.-]{1,128}$"
    )

    def __init__(
        self,
        storage_root: str = "storage/mlops/versions",
        database_path: str = "storage/mlops/versioning.db",
    ):
        self.storage_root = Path(storage_root)
        self.storage_root.mkdir(
            parents=True,
            exist_ok=True,
        )

        database = Path(database_path)
        database.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.database_path = str(database)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(
            self.database_path,
            timeout=10,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(
            "PRAGMA busy_timeout = 10000"
        )
        return connection

    def _initialize(self):
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS model_versions (
                    version_id TEXT PRIMARY KEY,
                    model_name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    artifact_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(model_name, version)
                )
            """)

    @staticmethod
    def sha256_file(path: Path) -> str:
        digest = hashlib.sha256()

        with path.open("rb") as file:
            for chunk in iter(
                lambda: file.read(1024 * 1024),
                b"",
            ):
                digest.update(chunk)

        return digest.hexdigest()

    def create_version(
        self,
        model_name: str,
        version: str,
        source_path: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict:

        if not self.SAFE_NAME.fullmatch(model_name):
            raise ValueError("Invalid model name")

        if not self.SAFE_NAME.fullmatch(version):
            raise ValueError("Invalid model version")

        source = Path(source_path).resolve()

        if not source.is_file():
            raise FileNotFoundError(source)

        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT 1 FROM model_versions
                WHERE model_name = ? AND version = ?
                """,
                (model_name, version),
            ).fetchone()

        if existing:
            raise ValueError(
                "Model version already exists"
            )

        version_id = uuid.uuid4().hex

        destination_dir = (
            self.storage_root / model_name / version
        )

        destination_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        # Unique snapshot name avoids accidental overwrite.
        destination = (
            destination_dir
            / f"{version_id}{source.suffix}"
        )

        shutil.copy2(source, destination)

        source_hash = self.sha256_file(source)
        stored_hash = self.sha256_file(destination)

        if source_hash != stored_hash:
            destination.unlink(missing_ok=True)
            raise RuntimeError(
                "Artifact copy integrity check failed"
            )

        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO model_versions (
                        version_id, model_name, version,
                        artifact_path, sha256,
                        metadata_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        version_id,
                        model_name,
                        version,
                        str(destination.resolve()),
                        stored_hash,
                        json.dumps(
                            metadata or {},
                            allow_nan=False,
                        ),
                        datetime.now(
                            timezone.utc
                        ).isoformat(),
                    ),
                )
        except Exception:
            destination.unlink(missing_ok=True)
            raise

        return {
            "version_id": version_id,
            "model_name": model_name,
            "version": version,
            "artifact_path": str(destination.resolve()),
            "sha256": stored_hash,
        }

    def get_version(
        self,
        model_name: str,
        version: str,
    ) -> dict:

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM model_versions
                WHERE model_name = ?
                  AND version = ?
                """,
                (model_name, version),
            ).fetchone()

        if row is None:
            raise ValueError(
                "Model version not found"
            )

        result = dict(row)
        result["metadata"] = json.loads(
            result.pop("metadata_json")
        )

        return result

    def verify_version(
        self,
        model_name: str,
        version: str,
    ) -> bool:

        record = self.get_version(
            model_name,
            version,
        )

        path = Path(record["artifact_path"])

        return (
            path.is_file()
            and self.sha256_file(path) == record["sha256"]
        )

    def list_versions(
        self,
        model_name: str,
    ) -> list[dict]:

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT version_id, version, sha256,
                       created_at
                FROM model_versions
                WHERE model_name = ?
                ORDER BY rowid DESC
                """,
                (model_name,),
            ).fetchall()

        return [dict(row) for row in rows]

    def compare_versions(
        self,
        model_name: str,
        version_a: str,
        version_b: str,
    ) -> dict:

        a = self.get_version(
            model_name,
            version_a,
        )

        b = self.get_version(
            model_name,
            version_b,
        )

        return {
            "model_name": model_name,
            "version_a": version_a,
            "version_b": version_b,
            "same_artifact": a["sha256"] == b["sha256"],
            "sha256_a": a["sha256"],
            "sha256_b": b["sha256"],
            "metadata_a": a["metadata"],
            "metadata_b": b["metadata"],
        }
