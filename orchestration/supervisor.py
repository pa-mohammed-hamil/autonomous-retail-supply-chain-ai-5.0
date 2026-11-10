"""Planned module: supervisor. Implementation pending."""

"""
File: ai/orchestration/supervisor.py
Project: Autonomous Retail Supply Chain AI 5.0

Multi-agent supervisor and task coordinator.

Features:
- Task submission and routing
- Agent execution
- Retry integration
- Human approval gates
- Task status management
- Result aggregation
- Failure handling
- Tenant-aware task lookup

Python 3.10+ | Standard library only

Compatible with:
    task_router.py
    retries.py
    human_approval.py
"""

from __future__ import annotations

import copy
import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .human_approval import HumanApprovalManager
from .retries import (
    RetryExecutor,
    RetryPolicy,
    RetryExhaustedError,
)
from .task_router import (
    TaskRequest,
    TaskRouter,
    RoutingError,
)


class SupervisorError(Exception):
    """Supervisor operation failed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_copy(value: Any) -> Any:
    try:
        return json.loads(
            json.dumps(value, allow_nan=False)
        )
    except (TypeError, ValueError) as exc:
        raise SupervisorError(
            "Task payload and results must be JSON serializable."
        ) from exc


@dataclass
class SupervisedTask:
    task_id: str
    tenant_id: str
    task_type: str
    requested_by: str
    payload: dict[str, Any]
    priority: int
    status: str = "created"
    agent_id: str | None = None
    approval_id: str | None = None
    result: Any = None
    error: str | None = None
    attempts: int = 0
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


class MultiAgentSupervisor:
    """In-process task supervision with approval support."""

    def __init__(
        self,
        router: TaskRouter,
        approval_manager: HumanApprovalManager,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.router = router
        self.approvals = approval_manager
        self.retry_policy = retry_policy or RetryPolicy()
        self._tasks: dict[str, SupervisedTask] = {}
        self._lock = threading.RLock()

    def submit_task(
        self,
        task: TaskRequest,
        requested_by: str,
    ) -> dict[str, Any]:
        if not requested_by.strip():
            raise SupervisorError(
                "requested_by is required."
            )

        payload = json_copy(task.payload)

        with self._lock:
            if task.task_id in self._tasks:
                raise SupervisorError(
                    "Duplicate task ID."
                )

            record = SupervisedTask(
                task_id=task.task_id,
                tenant_id=task.tenant_id,
                task_type=task.task_type,
                requested_by=requested_by,
                payload=payload,
                priority=task.priority,
            )

            self._tasks[task.task_id] = record

        try:
            decision = self.router.route_task(task)

            with self._lock:
                record.agent_id = decision.agent_id

            if decision.requires_approval:
                request = self.approvals.create_request(
                    workflow_id=task.task_id,
                    tenant_id=task.tenant_id,
                    node_id=task.task_type,
                    requested_by=requested_by,
                    allowed_approver_roles={
                        "admin",
                        "operations_manager",
                    },
                    reason=(
                        f"Approval required for task "
                        f"{task.task_type}"
                    ),
                    payload={
                        "task_id": task.task_id,
                        "task_type": task.task_type,
                        "payload": payload,
                    },
                )

                with self._lock:
                    record.approval_id = request["approval_id"]
                    record.status = "waiting_approval"
                    record.updated_at = utc_now()

                # Do not reserve worker capacity while
                # waiting for a human decision.
                self.router.release_task(task.task_id)

                return self.get_task(
                    task.task_id, task.tenant_id
                )

            return self._execute(task.task_id, task.tenant_id)

        except Exception as exc:
            self.router.release_task(task.task_id)

            with self._lock:
                record.status = "failed"
                record.error = str(exc)
                record.updated_at = utc_now()

            return self.get_task(
                task.task_id, task.tenant_id
            )

    def _execute(
        self,
        task_id: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            record = self._tasks.get(task_id)

            if record is None or record.tenant_id != tenant_id:
                raise SupervisorError(
                    "Task not found."
                )

            if record.status in {
                "completed", "failed", "rejected"
            }:
                return self.get_task(task_id, tenant_id)

            if record.status == "running":
                raise SupervisorError(
                    "Task already running."
                )

            record.status = "running"
            record.updated_at = utc_now()

        try:
            if record.agent_id is None:
                raise SupervisorError(
                    "Task has no assigned agent."
                )

            handler = self.router.get_handler(
                task_id,
                record.agent_id,
            )

            retry_executor = RetryExecutor(
                policy=self.retry_policy
            )

            # The supervisor only enables retries for
            # read-only operations in this baseline.
            read_only_task_types = {
                "forecast_demand",
                "analyze_sales",
                "analyze_inventory",
                "evaluate_supplier",
                "generate_report",
                "search_knowledge",
            }

            idempotent = (
                record.task_type in read_only_task_types
            )

            if not idempotent:
                retry_executor = RetryExecutor(
                    RetryPolicy(max_attempts=1)
                )

            outcome = retry_executor.run(
                handler,
                copy.deepcopy(record.payload),
                idempotent=idempotent,
            )

            result = json_copy(outcome.value)

            with self._lock:
                record.result = result
                record.attempts = outcome.attempts
                record.status = "completed"
                record.updated_at = utc_now()

        except RetryExhaustedError as exc:
            with self._lock:
                record.status = "failed"
                record.attempts = exc.attempts
                record.error = str(exc.last_error)
                record.updated_at = utc_now()

        except Exception as exc:
            with self._lock:
                record.status = "failed"
                record.error = str(exc)
                record.updated_at = utc_now()

        finally:
            self.router.release_task(task_id)

        return self.get_task(task_id, tenant_id)

    def resume_approved_task(
        self,
        task_id: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            record = self._tasks.get(task_id)

            if record is None or record.tenant_id != tenant_id:
                raise SupervisorError(
                    "Task not found."
                )

            if record.status != "waiting_approval":
                raise SupervisorError(
                    "Task is not waiting for approval."
                )

            if record.approval_id is None:
                raise SupervisorError(
                    "Approval reference missing."
                )

            approval_id = record.approval_id

        approval = self.approvals.get_request(
            approval_id, tenant_id
        )

        if approval["status"] == "pending":
            return self.get_task(task_id, tenant_id)

        if approval["status"] == "rejected":
            with self._lock:
                record.status = "rejected"
                record.updated_at = utc_now()

            return self.get_task(task_id, tenant_id)

        if approval["status"] != "approved":
            raise SupervisorError(
                "Unexpected approval status."
            )

        task = TaskRequest(
            task_id=record.task_id,
            task_type=record.task_type,
            tenant_id=record.tenant_id,
            payload=copy.deepcopy(record.payload),
            priority=record.priority,
            requires_approval=True,
        )

        # Re-route because worker capacity was released
        # during the human approval wait.
        try:
            decision = self.router.route_task(task)
        except RoutingError as exc:
            raise SupervisorError(
                "No agent available after approval."
            ) from exc

        with self._lock:
            record.agent_id = decision.agent_id
            record.status = "created"
            record.updated_at = utc_now()

        return self._execute(task_id, tenant_id)

    def get_task(
        self,
        task_id: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            record = self._tasks.get(task_id)

            if record is None or record.tenant_id != tenant_id:
                raise SupervisorError(
                    "Task not found."
                )

            return json_copy(asdict(record))

    def list_tasks(
        self,
        tenant_id: str,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            return [
                json_copy(asdict(record))
                for record in self._tasks.values()
                if (
                    record.tenant_id == tenant_id
                    and (
                        status is None
                        or record.status == status
                    )
                )
            ]

    def summary(
        self,
        tenant_id: str,
    ) -> dict[str, Any]:
        tasks = self.list_tasks(tenant_id)

        statuses = {
            "created": 0,
            "running": 0,
            "waiting_approval": 0,
            "completed": 0,
            "failed": 0,
            "rejected": 0,
        }

        for task in tasks:
            statuses[task["status"]] += 1

        return {
            "tenant_id": tenant_id,
            "total_tasks": len(tasks),
            "statuses": statuses,
            "completion_rate_percent": (
                round(
                    statuses["completed"]
                    / len(tasks) * 100,
                    2,
                )
                if tasks else 0.0
            ),
        }


if __name__ == "__main__":
    router = TaskRouter()
    approvals = HumanApprovalManager()

    router.register_agent(
        name="Demand Forecast Agent",
        capabilities={"forecast_demand"},
        handler=lambda payload: {
            "product_id": payload["product_id"],
            "forecast_units": 250,
        },
        allowed_tenants={"retail_company_001"},
    )

    supervisor = MultiAgentSupervisor(
        router=router,
        approval_manager=approvals,
    )

    result = supervisor.submit_task(
        task=TaskRequest(
            task_id="TASK-001",
            task_type="forecast_demand",
            tenant_id="retail_company_001",
            payload={"product_id": "SKU-1001"},
            priority=8,
        ),
        requested_by="operations_user",
    )

    print(result)
    print(supervisor.summary("retail_company_001"))
