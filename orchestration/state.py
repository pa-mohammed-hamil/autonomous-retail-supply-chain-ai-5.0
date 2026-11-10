"""Planned module: state. Implementation pending."""

"""
File: ai/orchestration/state.py
Project: Autonomous Retail Supply Chain AI 5.0

Multi-agent workflow state management.

Features:
- Workflow lifecycle management
- Node execution state tracking
- JSON-compatible shared state
- Immutable state snapshots
- State transition validation
- State event history
- Versioned state updates

Python 3.10+ | Standard library only
"""

from __future__ import annotations

import copy
import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


class StateError(ValueError):
    """Invalid workflow state operation."""


WORKFLOW_STATUSES = {
    "created",
    "running",
    "waiting_approval",
    "completed",
    "failed",
    "rejected",
    "cancelled",
}

NODE_STATUSES = {
    "pending",
    "running",
    "completed",
    "failed",
    "skipped",
}

WORKFLOW_TRANSITIONS = {
    "created": {"running", "cancelled"},
    "running": {
        "waiting_approval",
        "completed",
        "failed",
        "cancelled",
    },
    "waiting_approval": {
        "running",
        "rejected",
        "cancelled",
    },
    "failed": {"running", "cancelled"},
    "completed": set(),
    "rejected": set(),
    "cancelled": set(),
}

NODE_TRANSITIONS = {
    "pending": {"running", "skipped"},
    "running": {"completed", "failed"},
    "failed": {"running", "skipped"},
    "completed": set(),
    "skipped": set(),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_copy(value: Any) -> Any:
    """Copy and validate JSON-compatible data."""
    try:
        return json.loads(
            json.dumps(value, allow_nan=False)
        )
    except (TypeError, ValueError) as exc:
        raise StateError(
            "State values must be JSON serializable."
        ) from exc


@dataclass
class NodeExecutionState:
    node_id: str
    status: str = "pending"
    attempts: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    result: Any = None
    error: str | None = None


@dataclass
class WorkflowEvent:
    event_id: str
    event_type: str
    timestamp: str
    details: dict[str, Any]


@dataclass
class WorkflowState:
    workflow_id: str
    tenant_id: str
    graph_name: str
    status: str = "created"
    version: int = 1
    data: dict[str, Any] = field(default_factory=dict)
    nodes: dict[str, NodeExecutionState] = field(
        default_factory=dict
    )
    events: list[WorkflowEvent] = field(
        default_factory=list
    )
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


class WorkflowStateManager:
    """Thread-safe state manager for a single workflow."""

    def __init__(
        self,
        workflow_id: str,
        tenant_id: str,
        graph_name: str,
        initial_data: dict[str, Any] | None = None,
    ) -> None:
        if not workflow_id or not tenant_id or not graph_name:
            raise StateError(
                "Workflow ID, tenant ID and graph name are required."
            )

        self._lock = threading.RLock()

        self._state = WorkflowState(
            workflow_id=workflow_id,
            tenant_id=tenant_id,
            graph_name=graph_name,
            data=json_copy(initial_data or {}),
        )

        self._event(
            "workflow_created",
            {"graph_name": graph_name},
        )

    def _touch(self) -> None:
        self._state.version += 1
        self._state.updated_at = utc_now()

    def _event(
        self,
        event_type: str,
        details: dict[str, Any],
    ) -> None:
        self._state.events.append(
            WorkflowEvent(
                event_id=str(uuid4()),
                event_type=event_type,
                timestamp=utc_now(),
                details=json_copy(details),
            )
        )
        self._touch()

    def add_node(self, node_id: str) -> None:
        with self._lock:
            if not node_id:
                raise StateError("node_id is required.")

            if node_id in self._state.nodes:
                raise StateError(
                    f"Node already registered: {node_id}"
                )

            if self._state.status != "created":
                raise StateError(
                    "Nodes must be registered before execution."
                )

            self._state.nodes[node_id] = NodeExecutionState(
                node_id=node_id
            )

            self._event(
                "node_registered",
                {"node_id": node_id},
            )

    def transition_workflow(
        self,
        new_status: str,
    ) -> None:
        with self._lock:
            current = self._state.status

            if new_status not in WORKFLOW_STATUSES:
                raise StateError(
                    f"Unknown workflow status: {new_status}"
                )

            if new_status not in WORKFLOW_TRANSITIONS[current]:
                raise StateError(
                    f"Invalid workflow transition: "
                    f"{current} -> {new_status}"
                )

            self._state.status = new_status

            self._event(
                "workflow_status_changed",
                {
                    "from": current,
                    "to": new_status,
                },
            )

    def transition_node(
        self,
        node_id: str,
        new_status: str,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            node = self._state.nodes.get(node_id)

            if node is None:
                raise StateError(
                    f"Unknown node: {node_id}"
                )

            if new_status not in NODE_STATUSES:
                raise StateError(
                    "Unknown node status."
                )

            if new_status not in NODE_TRANSITIONS[node.status]:
                raise StateError(
                    f"Invalid node transition: "
                    f"{node.status} -> {new_status}"
                )

            old_status = node.status
            node.status = new_status

            if new_status == "running":
                node.attempts += 1
                node.started_at = utc_now()
                node.finished_at = None
                node.error = None

            elif new_status == "completed":
                node.finished_at = utc_now()
                node.result = json_copy(result)
                node.error = None

            elif new_status == "failed":
                node.finished_at = utc_now()
                node.error = error or "Unknown error"

            elif new_status == "skipped":
                node.finished_at = utc_now()

            self._event(
                "node_status_changed",
                {
                    "node_id": node_id,
                    "from": old_status,
                    "to": new_status,
                },
            )

    def update_data(
        self,
        updates: dict[str, Any],
        expected_version: int | None = None,
    ) -> None:
        if not isinstance(updates, dict):
            raise StateError(
                "updates must be a dictionary."
            )

        clean_updates = json_copy(updates)

        with self._lock:
            if (
                expected_version is not None
                and expected_version != self._state.version
            ):
                raise StateError(
                    "State version conflict."
                )

            if self._state.status != "running":
                raise StateError(
                    "Workflow must be running to update data."
                )

            self._state.data.update(clean_updates)

            self._event(
                "workflow_data_updated",
                {
                    "updated_keys": sorted(
                        clean_updates.keys()
                    )
                },
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json_copy(
                asdict(self._state)
            )

    def get_data(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(
                self._state.data
            )

    def get_node(
        self,
        node_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            node = self._state.nodes.get(node_id)

            if node is None:
                raise StateError(
                    f"Unknown node: {node_id}"
                )

            return json_copy(asdict(node))

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(
            self.snapshot(),
            indent=indent,
            ensure_ascii=False,
        )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: dict[str, Any],
    ) -> "WorkflowStateManager":
        """
        Reconstruct a manager from a trusted checkpoint.

        Validate checkpoint authenticity and tenant identity
        before calling this method.
        """
        data = json_copy(snapshot)

        manager = cls(
            workflow_id=data["workflow_id"],
            tenant_id=data["tenant_id"],
            graph_name=data["graph_name"],
            initial_data=data["data"],
        )

        nodes = {
            node_id: NodeExecutionState(**node_data)
            for node_id, node_data in data["nodes"].items()
        }

        events = [
            WorkflowEvent(**event)
            for event in data["events"]
        ]

        if data["status"] not in WORKFLOW_STATUSES:
            raise StateError(
                "Invalid restored workflow status."
            )

        for node in nodes.values():
            if node.status not in NODE_STATUSES:
                raise StateError(
                    "Invalid restored node status."
                )

        with manager._lock:
            manager._state = WorkflowState(
                workflow_id=data["workflow_id"],
                tenant_id=data["tenant_id"],
                graph_name=data["graph_name"],
                status=data["status"],
                version=data["version"],
                data=data["data"],
                nodes=nodes,
                events=events,
                created_at=data["created_at"],
                updated_at=data["updated_at"],
            )

        return manager


if __name__ == "__main__":
    manager = WorkflowStateManager(
        workflow_id="WF-001",
        tenant_id="retail_company_001",
        graph_name="inventory_replenishment",
        initial_data={
            "product_id": "SKU-1001",
            "available_stock": 80,
            "forecast_demand": 250,
        },
    )

    manager.add_node("demand_analysis")
    manager.add_node("inventory_analysis")
    manager.add_node("procurement_proposal")

    manager.transition_workflow("running")

    manager.transition_node(
        "demand_analysis", "running"
    )

    manager.transition_node(
        "demand_analysis",
        "completed",
        result={"forecast": 250},
    )

    manager.update_data({
        "shortage": 170
    })

    print(manager.to_json())
