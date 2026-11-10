"""Planned module: retention policy. Implementation pending."""

"""
ai/pipelines/retention_policy.py

Data retention and lifecycle management for
Autonomous Retail Supply Chain AI 5.0.

Features:
- Dataset-specific retention periods
- Expiration detection
- Legal-hold protection
- Dry-run retention planning
- Approval-gated deletion
- Safe root-path enforcement
- Symlink rejection
- Manifest-aware Parquet cleanup
- Append-only audit logging
- Deletion summaries

Standard library only. Python 3.10+.

Default mode is dry-run.

Deletion is irreversible and should be
restricted to authorized administrators.
Use backups and object-store lifecycle
policies for production deployments.
"""

from __future__ import annotations

import json
import os
import re

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DatasetRetentionRule:
    dataset: str
    retention_days: int
    legal_hold: bool = False
    enabled: bool = True

    def __post_init__(self):
        if (
            not isinstance(self.dataset, str)
            or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}",
                self.dataset,
            )
            or self.dataset in {".", ".."}
        ):
            raise ValueError(
                "Invalid dataset name"
            )

        if (
            isinstance(self.retention_days, bool)
            or not isinstance(self.retention_days, int)
            or self.retention_days < 1
        ):
            raise ValueError(
                "retention_days must be positive"
            )


@dataclass(frozen=True)
class RetentionConfig:
    storage_root: str = "data/lakehouse"
    audit_log_path: str = (
        "data/audit/retention_audit.jsonl"
    )
    dry_run: bool = True
    require_approval: bool = True
    max_deletions_per_run: int = 1000

    def __post_init__(self):
        if self.max_deletions_per_run < 1:
            raise ValueError(
                "Invalid deletion limit"
            )


class RetentionPolicy:

    def __init__(
        self,
        rules: list[DatasetRetentionRule],
        config: RetentionConfig | None = None,
    ):
        self.config = config or RetentionConfig()

        self.root = Path(
            self.config.storage_root
        ).resolve()

        self.root.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.audit_path = Path(
            self.config.audit_log_path
        ).resolve()

        self.audit_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.rules = {}

        for rule in rules:
            if rule.dataset in self.rules:
                raise ValueError(
                    "Duplicate dataset retention rule"
                )

            self.rules[rule.dataset] = rule

    @staticmethod
    def _now(
        as_of: datetime | None = None,
    ) -> datetime:
        as_of = as_of or datetime.now(
            timezone.utc
        )

        if (
            as_of.tzinfo is None
            or as_of.utcoffset() is None
        ):
            raise ValueError(
                "as_of must be timezone-aware"
            )

        return as_of.astimezone(
            timezone.utc
        )

    def _validate_path(
        self,
        path: Path,
    ) -> Path:
        """
        Ensure a file is inside the storage root.

        Symlinks are rejected rather than followed.
        """

        absolute = path.absolute()

        if absolute.is_symlink():
            raise ValueError(
                "Symlink deletion is not permitted"
            )

        resolved = absolute.resolve()

        if (
            not resolved.is_relative_to(self.root)
            or resolved == self.root
        ):
            raise ValueError(
                "Path outside allowed storage root"
            )

        current = absolute.parent

        while current != self.root:
            if current.is_symlink():
                raise ValueError(
                    "Symlinked directory is not permitted"
                )

            if current == current.parent:
                raise ValueError(
                    "Invalid directory hierarchy"
                )

            current = current.parent

        return resolved

    def _audit(
        self,
        record: dict[str, Any],
    ) -> None:
        payload = {
            **record,
            "audit_at": datetime.now(
                timezone.utc
            ).isoformat(),
        }

        # Append-only at application level.
        # Production systems should use an
        # immutable audit store with access controls.
        fd = os.open(
            self.audit_path,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT,
            0o600,
        )

        try:
            data = (
                json.dumps(
                    payload,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")

            os.write(fd, data)
            os.fsync(fd)

        finally:
            os.close(fd)

    @staticmethod
    def _file_timestamp(
        path: Path,
    ) -> datetime:
        """
        Use file modification time.

        For immutable data lakes, prefer an
        authoritative ingestion timestamp from
        a trusted manifest or catalog.
        """

        return datetime.fromtimestamp(
            path.stat().st_mtime,
            tz=timezone.utc,
        )

    def plan(
        self,
        as_of: datetime | None = None,
    ) -> dict:
        as_of = self._now(as_of)

        candidates = []
        protected = []
        skipped = []

        for dataset, rule in self.rules.items():
            directory = self.root / dataset

            if not directory.exists():
                continue

            cutoff = as_of - timedelta(
                days=rule.retention_days
            )

            for path in directory.rglob(
                "part-*.parquet"
            ):
                if not path.is_file():
                    continue

                safe_path = self._validate_path(
                    path
                )

                timestamp = self._file_timestamp(
                    safe_path
                )

                if timestamp >= cutoff:
                    continue

                item = {
                    "dataset": dataset,
                    "file_path": str(safe_path),
                    "modified_at": timestamp.isoformat(),
                    "retention_days": (
                        rule.retention_days
                    ),
                    "cutoff_at": cutoff.isoformat(),
                    "size_bytes": (
                        safe_path.stat().st_size
                    ),
                }

                if rule.legal_hold:
                    protected.append({
                        **item,
                        "reason": "legal_hold",
                    })

                elif not rule.enabled:
                    skipped.append({
                        **item,
                        "reason": "rule_disabled",
                    })

                else:
                    candidates.append(item)

        candidates.sort(
            key=lambda item: (
                item["modified_at"],
                item["file_path"],
            )
        )

        return {
            "generated_at": as_of.isoformat(),
            "candidate_count": len(candidates),
            "protected_count": len(protected),
            "skipped_count": len(skipped),
            "candidate_bytes": sum(
                item["size_bytes"]
                for item in candidates
            ),
            "candidates": candidates,
            "protected": protected,
            "skipped": skipped,
            "deletion_performed": False,
        }

    def execute(
        self,
        approved_by: str | None = None,
        as_of: datetime | None = None,
    ) -> dict:
        """
        Execute retention after approval.

        The candidate list is generated fresh
        immediately before execution.

        No deletion occurs when dry_run=True.
        """

        plan = self.plan(as_of=as_of)

        if self.config.dry_run:
            return {
                **plan,
                "status": "dry_run",
                "deleted_count": 0,
            }

        if (
            self.config.require_approval
            and (
                not isinstance(approved_by, str)
                or not approved_by.strip()
            )
        ):
            return {
                **plan,
                "status": "approval_required",
                "deleted_count": 0,
            }

        candidates = plan["candidates"][
            :self.config.max_deletions_per_run
        ]

        deleted = []
        failed = []

        for item in candidates:
            path = Path(item["file_path"])

            try:
                safe_path = self._validate_path(
                    path
                )

                if not safe_path.is_file():
                    raise FileNotFoundError(
                        str(safe_path)
                    )

                # Re-check age immediately before
                # deleting, to reduce TOCTOU risk.
                rule = self.rules[
                    item["dataset"]
                ]

                if rule.legal_hold or not rule.enabled:
                    raise PermissionError(
                        "Retention rule no longer permits deletion"
                    )

                cutoff = self._now(
                    as_of
                ) - timedelta(
                    days=rule.retention_days
                )

                if (
                    self._file_timestamp(safe_path)
                    >= cutoff
                ):
                    raise ValueError(
                        "File is no longer expired"
                    )

                # Record deletion intent first.
                self._audit({
                    "action": "delete_intent",
                    "dataset": item["dataset"],
                    "file_path": str(safe_path),
                    "approved_by": approved_by,
                })

                safe_path.unlink()

                # Remove the associated manifest
                # only if its matching Parquet file
                # was successfully deleted.
                manifest = safe_path.with_name(
                    safe_path.name.replace(
                        ".parquet",
                        ".manifest.json",
                    )
                )

                if manifest.exists():
                    self._validate_path(
                        manifest
                    )
                    manifest.unlink()

                self._audit({
                    "action": "deleted",
                    "dataset": item["dataset"],
                    "file_path": str(safe_path),
                    "approved_by": approved_by,
                })

                deleted.append(item)

            except Exception as exc:
                failed.append({
                    **item,
                    "error": str(exc),
                })

                self._audit({
                    "action": "deletion_failed",
                    "dataset": item["dataset"],
                    "file_path": item["file_path"],
                    "error": str(exc),
                    "approved_by": approved_by,
                })

        return {
            "status": (
                "completed"
                if not failed
                else "completed_with_errors"
            ),
            "planned_count": plan["candidate_count"],
            "deleted_count": len(deleted),
            "failed_count": len(failed),
            "deleted_bytes": sum(
                item["size_bytes"]
                for item in deleted
            ),
            "remaining_candidate_count": (
                plan["candidate_count"]
                - len(deleted)
            ),
            "deleted": deleted,
            "failed": failed,
            "approved_by": approved_by,
            "deletion_performed": bool(deleted),
        }


def default_retail_retention_rules() -> list[
    DatasetRetentionRule
]:
    """
    Example configuration only.

    Actual periods must follow applicable
    contractual, tax, privacy and legal rules.
    """

    return [
        DatasetRetentionRule(
            dataset="pos_transactions",
            retention_days=365,
        ),
        DatasetRetentionRule(
            dataset="inventory_snapshots",
            retention_days=180,
        ),
        DatasetRetentionRule(
            dataset="supplier_events",
            retention_days=365,
        ),
        DatasetRetentionRule(
            dataset="warehouse_events",
            retention_days=180,
        ),
        DatasetRetentionRule(
            dataset="logistics_telemetry",
            retention_days=30,
        ),
        DatasetRetentionRule(
            dataset="customer_feedback",
            retention_days=90,
        ),
        DatasetRetentionRule(
            dataset="legal_evidence",
            retention_days=365,
            legal_hold=True,
        ),
    ]


if __name__ == "__main__":
    import json

    policy = RetentionPolicy(
        rules=default_retail_retention_rules(),
        config=RetentionConfig(
            storage_root="data/lakehouse",
            audit_log_path=(
                "data/audit/retention_audit.jsonl"
            ),
            dry_run=True,
        ),
    )

    report = policy.execute(
        approved_by=None,
    )

    print(
        json.dumps(
            report,
            indent=2,
        )
    )
