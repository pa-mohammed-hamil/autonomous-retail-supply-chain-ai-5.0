"""Planned module: recovery. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
File: ai/orchestration/recovery.py

Workflow recovery and incident management.

Features:
- Checkpoint inspection
- Failed workflow diagnosis
- Interrupted workflow detection
- Recovery recommendations
- Manual retry authorization
- Recovery audit events
- Safe resume for waiting workflows

Python 3.10+
Standard library only.

Compatible with:
    checkpointing.py
    executor.py
    graph.py
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .checkpointing import CheckpointStore
from .executor import WorkflowExecutor
from .graph import WorkflowGraph


class RecoveryError(Exception):
    """Workflow recovery operation failed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowRecoveryManager:
    """Coordinate recovery of interrupted workflows."""

    def __init__(
        self,
        checkpoint_store: CheckpointStore,
        executor: WorkflowExecutor,
    ) -> None:
        self.checkpoints = checkpoint_store
        self.executor = executor

    def inspect(
        self,
        workflow_id: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        checkpoint = self.checkpoints.load(
            workflow_id, tenant_id
        )

        if checkpoint is None:
            raise RecoveryError(
                "Workflow checkpoint not found."
            )

        state = checkpoint["state"]
        status = checkpoint["status"]

        if status == "completed":
            recommendation = "no_action"

        elif status == "waiting_approval":
            recommendation = "await_human_decision"

        elif status == "rejected":
            recommendation = "manual_review"

        elif status == "failed":
            recommendation = "investigate_and_retry"

        elif status == "running":
            recommendation = (
                "verify_executor_inactive_before_resume"
            )

        else:
            recommendation = "manual_review"

        return {
            "workflow_id": workflow_id,
            "tenant_id": tenant_id,
            "status": status,
            "checkpoint_version": checkpoint["version"],
            "completed_nodes": state.get(
                "completed_nodes", []
            ),
            "pending_approval": state.get(
                "pending_approval"
            ),
            "errors": state.get("errors", []),
            "recommendation": recommendation,
            "last_updated": checkpoint["updated_at"],
        }

    def recover_waiting_workflow(
        self,
        graph: WorkflowGraph,
        workflow_id: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        checkpoint = self.checkpoints.load(
            workflow_id, tenant_id
        )

        if checkpoint is None:
            raise RecoveryError(
                "Workflow not found."
            )

        if checkpoint["status"] != "waiting_approval":
            raise RecoveryError(
                "Workflow is not waiting for approval."
            )

        # Executor checks the approval status.
        # This may remain paused if no decision exists.
        return self.executor.resume(
            graph=graph,
            workflow_id=workflow_id,
            tenant_id=tenant_id,
        )

    def retry_failed_workflow(
        self,
        graph: WorkflowGraph,
        workflow_id: str,
        tenant_id: str,
        operator_id: str,
        reason: str,
        confirmed_safe_to_retry: bool = False,
    ) -> dict[str, Any]:
        """
        Reset a failed workflow for a controlled retry.

        Requires external verification that the failed
        node did not already commit irreversible effects.
        """
        if not operator_id.strip():
            raise RecoveryError(
                "operator_id is required."
            )

        if not reason.strip():
            raise RecoveryError(
                "Recovery reason is required."
            )

        if confirmed_safe_to_retry is not True:
            raise RecoveryError(
                "Operator must verify retry safety."
            )

        checkpoint = self.checkpoints.load(
            workflow_id, tenant_id
        )

        if checkpoint is None:
            raise RecoveryError(
                "Workflow checkpoint not found."
            )

        if checkpoint["status"] != "failed":
            raise RecoveryError(
                "Only failed workflows can be retried."
            )

        state = checkpoint["state"]

        if state.get("graph_name") != graph.name:
            raise RecoveryError(
                "Workflow graph mismatch."
            )

        graph.validate()

        completed = state.get(
            "completed_nodes", []
        )

        valid_nodes = set(graph.nodes)

        if any(
            node_id not in valid_nodes
            for node_id in completed
        ):
            raise RecoveryError(
                "Checkpoint references unknown nodes."
            )

        # Keep completed nodes to avoid rerunning
        # operations that have already succeeded.
        state["status"] = "running"
        state["pending_approval"] = None

        state.setdefault(
            "recovery_history", []
        ).append({
            "operator_id": operator_id,
            "reason": reason,
            "recovered_at": utc_now(),
            "previous_status": "failed",
        })

        self.checkpoints.save(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            status="running",
            state=state,
            expected_version=checkpoint["version"],
        )

        self.checkpoints.append_event(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            event_type="workflow_recovery_requested",
            payload={
                "operator_id": operator_id,
                "reason": reason,
                "confirmed_safe_to_retry": True,
            },
        )

        return self.executor.resume(
            graph=graph,
            workflow_id=workflow_id,
            tenant_id=tenant_id,
        )

    def get_recovery_history(
        self,
        workflow_id: str,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        checkpoint = self.checkpoints.load(
            workflow_id, tenant_id
        )

        if checkpoint is None:
            raise RecoveryError(
                "Workflow checkpoint not found."
            )

        return checkpoint["state"].get(
            "recovery_history", []
        )
