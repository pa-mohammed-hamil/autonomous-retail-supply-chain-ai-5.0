"""Planned module: supervisor agent. Implementation pending."""

"""
File: ai/agents/supervisor_agent.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+ | Standard library only

Capabilities:
- list_registered_agents
- route_task
- execute_workflow

Workflow execution:
- Sequential tasks
- Dependency checks
- Approval checkpoints
- Failure handling
- Tenant-scoped workflow results

Important:
This is a lightweight supervisor prototype.
It does not replace the existing durable
WorkflowExecutor / HumanApprovalManager.
"""

from __future__ import annotations

import threading
from typing import Any
from uuid import uuid4

from .base_agent import (
    BaseAgent,
    AgentRequest,
    AgentValidationError,
    utc_now,
)


class SupervisorAgent(BaseAgent):

    def __init__(self, working_memory=None):
        super().__init__(
            agent_id="supervisor_agent",
            name="Retail Multi-Agent Supervisor",
            capabilities={
                "list_registered_agents",
                "route_task",
                "execute_workflow",
            },
            working_memory=working_memory,
        )

        self._agents: dict[str, BaseAgent] = {}
        self._history: dict[
            tuple[str, str], dict
        ] = {}

        self._lock = threading.RLock()

    def register_agent(
        self,
        agent: BaseAgent,
    ) -> None:
        if not isinstance(agent, BaseAgent):
            raise TypeError(
                "Registered agent must extend BaseAgent."
            )

        if agent.agent_id == self.agent_id:
            raise ValueError(
                "Supervisor cannot register itself."
            )

        with self._lock:
            if agent.agent_id in self._agents:
                raise ValueError(
                    "Agent already registered."
                )

            self._agents[agent.agent_id] = agent

    @staticmethod
    def _text(value: Any, name: str) -> str:
        if (
            not isinstance(value, str)
            or not value.strip()
        ):
            raise AgentValidationError(
                f"{name} is required."
            )
        return value.strip()

    def _resolve_agent(
        self,
        agent_id: str,
        task_type: str,
    ) -> BaseAgent:
        with self._lock:
            agent = self._agents.get(agent_id)

        if agent is None:
            raise AgentValidationError(
                "Agent not registered."
            )

        if task_type not in agent.capabilities:
            raise AgentValidationError(
                "Agent does not support task."
            )

        return agent

    def _list_agents(self) -> dict:
        with self._lock:
            agents = [
                agent.describe()
                for agent in self._agents.values()
            ]

        return {
            "agent_count": len(agents),
            "agents": agents,
        }

    def _route(
        self,
        request: AgentRequest,
    ) -> dict:
        payload = request.payload

        agent_id = self._text(
            payload.get("agent_id"),
            "agent_id",
        )
        task_type = self._text(
            payload.get("target_task_type"),
            "target_task_type",
        )
        task_payload = payload.get(
            "task_payload", {}
        )

        if not isinstance(task_payload, dict):
            raise AgentValidationError(
                "task_payload must be an object."
            )

        agent = self._resolve_agent(
            agent_id, task_type
        )

        child_request = AgentRequest(
            task_type=task_type,
            payload=task_payload,
            context=request.context,
        )

        response = agent.execute(child_request)

        return {
            "agent_id": agent_id,
            "task_type": task_type,
            "agent_response": response,
            "completed": response["success"],
        }

    def _workflow(
        self,
        request: AgentRequest,
    ) -> dict:
        payload = request.payload
        steps = payload.get("steps")

        if (
            not isinstance(steps, list)
            or not 1 <= len(steps) <= 50
        ):
            raise AgentValidationError(
                "Provide 1 to 50 workflow steps."
            )

        validated_steps = []
        step_ids = set()

        # Validate the entire plan before execution.
        for step in steps:
            if not isinstance(step, dict):
                raise AgentValidationError(
                    "Each step must be an object."
                )

            step_id = self._text(
                step.get("step_id"),
                "step_id",
            )
            agent_id = self._text(
                step.get("agent_id"),
                "agent_id",
            )
            task_type = self._text(
                step.get("task_type"),
                "task_type",
            )

            if step_id in step_ids:
                raise AgentValidationError(
                    "Duplicate step_id."
                )

            step_ids.add(step_id)

            self._resolve_agent(
                agent_id, task_type
            )

            dependencies = step.get(
                "depends_on", []
            )

            if (
                not isinstance(dependencies, list)
                or not all(
                    isinstance(dep, str)
                    for dep in dependencies
                )
            ):
                raise AgentValidationError(
                    "Invalid depends_on."
                )

            step_payload = step.get("payload", {})

            if not isinstance(step_payload, dict):
                raise AgentValidationError(
                    "Step payload must be an object."
                )

            requires_approval = step.get(
                "requires_approval", False
            )

            if not isinstance(
                requires_approval, bool
            ):
                raise AgentValidationError(
                    "requires_approval must be boolean."
                )

            # Dependencies must already exist
            # earlier in the sequential workflow.
            if not set(dependencies).issubset(
                step_ids - {step_id}
            ):
                raise AgentValidationError(
                    "Dependencies must precede their step."
                )

            validated_steps.append({
                "step_id": step_id,
                "agent_id": agent_id,
                "task_type": task_type,
                "payload": step_payload,
                "depends_on": dependencies,
                "requires_approval": (
                    requires_approval
                ),
            })

        workflow_id = str(uuid4())
        results = {}
        status = "completed"

        for step in validated_steps:
            step_id = step["step_id"]

            if step["requires_approval"]:
                status = "pending_approval"
                results[step_id] = {
                    "status": "pending_approval",
                    "executed": False,
                }
                break

            agent = self._resolve_agent(
                step["agent_id"],
                step["task_type"],
            )

            child_request = AgentRequest(
                task_type=step["task_type"],
                payload=step["payload"],
                context=request.context,
            )

            response = agent.execute(
                child_request
            )

            results[step_id] = response

            if not response["success"]:
                status = "failed"
                break

        workflow = {
            "workflow_id": workflow_id,
            "tenant_id": request.context.tenant_id,
            "status": status,
            "results": results,
            "created_at": utc_now(),
            "approval_resume_supported": False,
        }

        with self._lock:
            self._history[
                (
                    request.context.tenant_id,
                    workflow_id,
                )
            ] = workflow

        return workflow

    def process(
        self,
        request: AgentRequest,
    ) -> dict:
        task = request.task_type

        if task == "list_registered_agents":
            return self._list_agents()

        if task == "route_task":
            return self._route(request)

        if task == "execute_workflow":
            return self._workflow(request)

        raise AgentValidationError(
            "Unsupported supervisor task."
        )
