"""Planned module: prompt versioning. Implementation pending."""

"""
ai/llmops/prompt_versioning.py

Prompt versioning and release management for
Autonomous Retail Supply Chain AI 5.0.

Features:
- Immutable prompt versions
- Semantic version identifiers
- Version history
- SHA-256 content integrity
- Draft and staging releases
- Evaluation-gated promotion
- Human approval workflow
- Production activation
- Production rollback
- Version comparison
- Audit history
- SQLite persistence

Safety:
- No automatic production deployment
- No silent prompt overwrites
- Approval must be verified externally
- Rollback requires explicit authorization
- Evaluation results must be trusted
- No raw user data stored

Standard library only. Python 3.10+.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import sqlite3
import uuid

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


VERSION_PATTERN = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+$"
)


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


@dataclass(frozen=True)
class PromptVersioningConfig:
    database_path: str = (
        "data/llmops/prompt_versions.db"
    )
    minimum_groundedness: float = 0.90
    minimum_task_success: float = 0.85
    minimum_safety_score: float = 0.95

    def __post_init__(self):
        for threshold in (
            self.minimum_groundedness,
            self.minimum_task_success,
            self.minimum_safety_score,
        ):
            if not 0 <= threshold <= 1:
                raise ValueError(
                    "Evaluation thresholds must be 0-1"
                )


class PromptVersioning:

    def __init__(
        self,
        config: PromptVersioningConfig | None = None,
    ):
        self.config = config or PromptVersioningConfig()

        path = Path(self.config.database_path)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.db = sqlite3.connect(
            str(path),
            timeout=30,
        )
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")

        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS prompt_versions (
                prompt_id TEXT NOT NULL,
                version TEXT NOT NULL,
                template TEXT NOT NULL,
                checksum TEXT NOT NULL,
                created_by TEXT NOT NULL,
                change_note TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (prompt_id, version)
            );

            CREATE TABLE IF NOT EXISTS prompt_evaluations (
                prompt_id TEXT NOT NULL,
                version TEXT NOT NULL,
                groundedness REAL NOT NULL,
                task_success REAL NOT NULL,
                safety_score REAL NOT NULL,
                dataset_version TEXT NOT NULL,
                evaluator TEXT NOT NULL,
                evaluated_at TEXT NOT NULL,
                PRIMARY KEY (prompt_id, version),
                FOREIGN KEY (prompt_id, version)
                    REFERENCES prompt_versions(prompt_id, version)
            );

            CREATE TABLE IF NOT EXISTS prompt_releases (
                prompt_id TEXT PRIMARY KEY,
                production_version TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS prompt_release_audit (
                audit_id TEXT PRIMARY KEY,
                prompt_id TEXT NOT NULL,
                version TEXT NOT NULL,
                action TEXT NOT NULL,
                approved_by TEXT NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)

        self.db.commit()

    @staticmethod
    def checksum(template: str) -> str:
        return hashlib.sha256(
            template.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _validate_version(version: str):
        if not VERSION_PATTERN.fullmatch(version):
            raise ValueError(
                "Version must use MAJOR.MINOR.PATCH"
            )

    def create_version(
        self,
        prompt_id: str,
        version: str,
        template: str,
        created_by: str,
        change_note: str,
    ) -> dict:
        self._validate_version(version)

        if not prompt_id.strip():
            raise ValueError("Prompt ID required")

        if not template.strip():
            raise ValueError("Template required")

        if not created_by.strip():
            raise ValueError("Creator required")

        if not change_note.strip():
            raise ValueError("Change note required")

        # Apply the same restricted template
        # syntax as prompt_registry.py.
        from ai.llmops.prompt_registry import PromptRegistry

        PromptRegistry.extract_variables(template)

        digest = self.checksum(template)

        with self.db:
            self.db.execute(
                """
                INSERT INTO prompt_versions (
                    prompt_id, version, template,
                    checksum, created_by,
                    change_note, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prompt_id,
                    version,
                    template,
                    digest,
                    created_by,
                    change_note,
                    utc_now(),
                ),
            )

        return {
            "prompt_id": prompt_id,
            "version": version,
            "checksum": digest,
            "created": True,
            "immutable": True,
        }

    def get_version(
        self,
        prompt_id: str,
        version: str,
    ) -> dict | None:
        row = self.db.execute(
            """
            SELECT *
            FROM prompt_versions
            WHERE prompt_id = ?
              AND version = ?
            """,
            (prompt_id, version),
        ).fetchone()

        if row is None:
            return None

        result = dict(row)

        if self.checksum(result["template"]) != (
            result["checksum"]
        ):
            raise RuntimeError(
                "Prompt version checksum mismatch"
            )

        return result

    def list_versions(
        self,
        prompt_id: str,
    ) -> list[dict]:
        rows = self.db.execute(
            """
            SELECT version
            FROM prompt_versions
            WHERE prompt_id = ?
            """,
            (prompt_id,),
        ).fetchall()

        versions = sorted(
            (row["version"] for row in rows),
            key=lambda value: tuple(
                int(part)
                for part in value.split(".")
            ),
        )

        return [
            self.get_version(prompt_id, version)
            for version in versions
        ]

    def record_evaluation(
        self,
        prompt_id: str,
        version: str,
        groundedness: float,
        task_success: float,
        safety_score: float,
        dataset_version: str,
        evaluator: str,
    ) -> dict:
        if self.get_version(prompt_id, version) is None:
            raise ValueError(
                "Unknown prompt version"
            )

        scores = {
            "groundedness": groundedness,
            "task_success": task_success,
            "safety_score": safety_score,
        }

        import math

        for name, score in scores.items():
            if (
                isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(score)
                or not 0 <= score <= 1
            ):
                raise ValueError(
                    f"Invalid {name} score"
                )

        if not dataset_version.strip() or not evaluator.strip():
            raise ValueError(
                "Evaluation provenance required"
            )

        with self.db:
            self.db.execute(
                """
                INSERT INTO prompt_evaluations (
                    prompt_id, version,
                    groundedness, task_success,
                    safety_score, dataset_version,
                    evaluator, evaluated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(prompt_id, version)
                DO UPDATE SET
                    groundedness = excluded.groundedness,
                    task_success = excluded.task_success,
                    safety_score = excluded.safety_score,
                    dataset_version = excluded.dataset_version,
                    evaluator = excluded.evaluator,
                    evaluated_at = excluded.evaluated_at
                """,
                (
                    prompt_id,
                    version,
                    groundedness,
                    task_success,
                    safety_score,
                    dataset_version,
                    evaluator,
                    utc_now(),
                ),
            )

        return {
            "prompt_id": prompt_id,
            "version": version,
            "evaluation_recorded": True,
            "passes_thresholds": (
                self.check_release_readiness(
                    prompt_id,
                    version,
                )["ready"]
            ),
        }

    def check_release_readiness(
        self,
        prompt_id: str,
        version: str,
    ) -> dict:
        row = self.db.execute(
            """
            SELECT *
            FROM prompt_evaluations
            WHERE prompt_id = ?
              AND version = ?
            """,
            (prompt_id, version),
        ).fetchone()

        if row is None:
            return {
                "ready": False,
                "reason": "evaluation_missing",
            }

        checks = {
            "groundedness": (
                row["groundedness"]
                >= self.config.minimum_groundedness
            ),
            "task_success": (
                row["task_success"]
                >= self.config.minimum_task_success
            ),
            "safety_score": (
                row["safety_score"]
                >= self.config.minimum_safety_score
            ),
        }

        return {
            "ready": all(checks.values()),
            "checks": checks,
            "dataset_version": row["dataset_version"],
            "evaluator": row["evaluator"],
        }

    def _audit(
        self,
        prompt_id: str,
        version: str,
        action: str,
        approved_by: str,
        reason: str,
    ):
        self.db.execute(
            """
            INSERT INTO prompt_release_audit (
                audit_id, prompt_id, version,
                action, approved_by, reason,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid.uuid4().hex,
                prompt_id,
                version,
                action,
                approved_by,
                reason,
                utc_now(),
            ),
        )

    def promote(
        self,
        prompt_id: str,
        version: str,
        approved_by: str,
        approval_verified: bool,
        reason: str,
    ) -> dict:
        """
        Promote a tested version to production.

        approval_verified must come from a
        trusted authentication/approval service,
        not from the LLM or client input.
        """

        if not approval_verified:
            raise PermissionError(
                "Verified human approval required"
            )

        if not approved_by.strip() or not reason.strip():
            raise ValueError(
                "Approver and reason required"
            )

        if self.get_version(prompt_id, version) is None:
            raise ValueError(
                "Unknown prompt version"
            )

        readiness = self.check_release_readiness(
            prompt_id,
            version,
        )

        if not readiness["ready"]:
            raise RuntimeError(
                "Prompt did not pass release evaluation"
            )

        with self.db:
            self.db.execute(
                """
                INSERT INTO prompt_releases (
                    prompt_id, production_version,
                    updated_at
                )
                VALUES (?, ?, ?)
                ON CONFLICT(prompt_id)
                DO UPDATE SET
                    production_version =
                        excluded.production_version,
                    updated_at = excluded.updated_at
                """,
                (
                    prompt_id,
                    version,
                    utc_now(),
                ),
            )

            self._audit(
                prompt_id,
                version,
                "promoted",
                approved_by,
                reason,
            )

        return {
            "prompt_id": prompt_id,
            "production_version": version,
            "promoted": True,
            "approved_by": approved_by,
        }

    def get_production(
        self,
        prompt_id: str,
    ) -> dict | None:
        row = self.db.execute(
            """
            SELECT production_version
            FROM prompt_releases
            WHERE prompt_id = ?
            """,
            (prompt_id,),
        ).fetchone()

        if row is None or row["production_version"] is None:
            return None

        return self.get_version(
            prompt_id,
            row["production_version"],
        )

    def rollback(
        self,
        prompt_id: str,
        target_version: str,
        approved_by: str,
        approval_verified: bool,
        reason: str,
    ) -> dict:
        """
        Restore a previous evaluated prompt.

        Rollback does not erase newer versions.
        """

        if not approval_verified:
            raise PermissionError(
                "Verified approval required"
            )

        if not approved_by.strip() or not reason.strip():
            raise ValueError(
                "Approver and reason required"
            )

        if self.get_version(
            prompt_id, target_version
        ) is None:
            raise ValueError(
                "Unknown rollback target"
            )

        readiness = self.check_release_readiness(
            prompt_id,
            target_version,
        )

        if not readiness["ready"]:
            raise RuntimeError(
                "Rollback target lacks passing evaluation"
            )

        current = self.get_production(prompt_id)

        if current is None:
            raise RuntimeError(
                "No production version exists"
            )

        with self.db:
            self.db.execute(
                """
                UPDATE prompt_releases
                SET production_version = ?,
                    updated_at = ?
                WHERE prompt_id = ?
                """,
                (
                    target_version,
                    utc_now(),
                    prompt_id,
                ),
            )

            self._audit(
                prompt_id,
                target_version,
                "rollback",
                approved_by,
                reason,
            )

        return {
            "prompt_id": prompt_id,
            "previous_version": current["version"],
            "restored_version": target_version,
            "rolled_back": True,
        }

    def compare(
        self,
        prompt_id: str,
        old_version: str,
        new_version: str,
    ) -> dict:
        old = self.get_version(
            prompt_id, old_version
        )

        new = self.get_version(
            prompt_id, new_version
        )

        if old is None or new is None:
            raise ValueError(
                "Both versions must exist"
            )

        diff = difflib.unified_diff(
            old["template"].splitlines(),
            new["template"].splitlines(),
            fromfile=old_version,
            tofile=new_version,
            lineterm="",
        )

        return {
            "prompt_id": prompt_id,
            "old_version": old_version,
            "new_version": new_version,
            "diff": "\n".join(diff),
        }

    def audit_history(
        self,
        prompt_id: str,
    ) -> list[dict]:
        rows = self.db.execute(
            """
            SELECT *
            FROM prompt_release_audit
            WHERE prompt_id = ?
            ORDER BY created_at, audit_id
            """,
            (prompt_id,),
        ).fetchall()

        return [dict(row) for row in rows]

    def close(self):
        self.db.close()


if __name__ == "__main__":
    manager = PromptVersioning()

    manager.create_version(
        prompt_id="inventory_analysis",
        version="1.0.0",
        template=(
            "Analyze inventory for {warehouse_id}. "
            "Use authorized data and cite evidence."
        ),
        created_by="mlops_engineer",
        change_note="Initial inventory prompt",
    )

    manager.create_version(
        prompt_id="inventory_analysis",
        version="1.1.0",
        template=(
            "Analyze inventory for {warehouse_id}. "
            "Use authorized data, cite evidence, "
            "and explain stockout risk."
        ),
        created_by="mlops_engineer",
        change_note="Added stockout risk explanation",
    )

    # Illustrative evaluation scores.
    # Replace with trusted evaluation results.
    manager.record_evaluation(
        prompt_id="inventory_analysis",
        version="1.1.0",
        groundedness=0.96,
        task_success=0.93,
        safety_score=0.99,
        dataset_version="retail-eval-2026-10",
        evaluator="human_evaluation_team",
    )

    print(
        json.dumps(
            manager.check_release_readiness(
                "inventory_analysis",
                "1.1.0",
            ),
            indent=2,
        )
    )

    print(
        json.dumps(
            manager.compare(
                "inventory_analysis",
                "1.0.0",
                "1.1.0",
            ),
            indent=2,
        )
    )

    # No production promotion in this demo.
    # A trusted approval workflow must verify
    # authorization before calling promote().

    manager.close()
