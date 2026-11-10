"""Planned module: rollback. Implementation pending."""

"""
ai/mlops/rollback.py

Model deployment rollback coordinator.

Uses DeploymentManager for version selection.

Important:
This changes deployment metadata only.
Actual serving traffic must be switched
by a separate deployment controller.
"""

from __future__ import annotations

import json
import uuid

from datetime import datetime, timezone
from pathlib import Path

from ai.mlops.deployment_manager import (
    DeploymentManager,
)


class RollbackManager:

    def __init__(
        self,
        deployment_manager: DeploymentManager,
        audit_dir: str = (
            "storage/mlops/rollback_audit"
        ),
    ):
        self.manager = deployment_manager
        self.audit_dir = Path(audit_dir)

        self.audit_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(
            timezone.utc
        ).isoformat()

    def rollback(
        self,
        model_name: str,
        target_version: str,
        environment: str,
        actor: str,
        reason: str,
        approval_reference: str | None = None,
        approval_verified: bool = False,
    ) -> dict:

        if not actor or not reason.strip():
            raise ValueError(
                "Actor and rollback reason required"
            )

        if environment not in {
            "staging",
            "production",
        }:
            raise ValueError(
                "Invalid deployment environment"
            )

        if environment == "production":
            if (
                not approval_reference
                or not approval_verified
            ):
                raise PermissionError(
                    "Verified production approval required"
                )

        current = (
            self.manager.current_deployment(
                model_name,
                environment,
            )
        )

        if current is None:
            raise ValueError(
                "No existing deployment to roll back"
            )

        if current["version"] == target_version:
            raise ValueError(
                "Target version is already selected"
            )

        if not self.manager.verify_model(
            model_name,
            target_version,
        ):
            raise ValueError(
                "Target artifact integrity check failed"
            )

        rollback_id = uuid.uuid4().hex

        audit = {
            "rollback_id": rollback_id,
            "model_name": model_name,
            "from_version": current["version"],
            "target_version": target_version,
            "environment": environment,
            "actor": actor,
            "reason": reason,
            "approval_reference": approval_reference,
            "requested_at": self._now(),
            "status": "pending",
        }

        audit_path = (
            self.audit_dir
            / f"{rollback_id}.json"
        )

        # Record the request before changing
        # the deployment selection.
        audit_path.write_text(
            json.dumps(audit, indent=2),
            encoding="utf-8",
        )

        try:
            deployment = self.manager.rollback(
                model_name=model_name,
                target_version=target_version,
                environment=environment,
                deployed_by=actor,
                approved=(
                    environment == "production"
                    and approval_verified
                ),
            )

            audit["status"] = (
                "deployment_selection_recorded"
            )
            audit["deployment_id"] = (
                deployment["deployment_id"]
            )

        except Exception as exc:
            audit["status"] = "failed"
            audit["error_type"] = (
                type(exc).__name__
            )

            audit_path.write_text(
                json.dumps(audit, indent=2),
                encoding="utf-8",
            )
            raise

        audit["finished_at"] = self._now()

        audit_path.write_text(
            json.dumps(audit, indent=2),
            encoding="utf-8",
        )

        return {
            **audit,
            "audit_path": str(audit_path),
            "serving_traffic_switched": False,
        }
