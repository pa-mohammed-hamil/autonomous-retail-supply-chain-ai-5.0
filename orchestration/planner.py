"""Planned module: planner. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
File: ai/orchestration/planner.py

Multi-agent workflow planning engine.

Features:
- Agent capability registry
- Goal-based task planning
- Dependency resolution
- Cycle detection
- Human approval requirements
- WorkflowGraph compilation
- Plan validation
- Structured planning results

Python 3.10+
Standard library only.

Compatible with:
    ai/orchestration/graph.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from .graph import WorkflowGraph, WorkflowNode


class PlanningError(ValueError):
    """Raised when a workflow plan is invalid."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AgentCapability:
    agent_name: str
    description: str
    handler: Callable[[dict[str, Any]], Any]
    allowed_tasks: frozenset[str]
    requires_approval: bool = False
    max_retries: int = 0


@dataclass
class PlannedTask:
    task_id: str
    task_type: str
    agent_name: str
    description: str
    dependencies: list[str] = field(default_factory=list)
    requires_approval: bool = False
    max_retries: int = 0


@dataclass
class WorkflowPlan:
    plan_id: str
    goal: str
    tenant_id: str
    tasks: list[PlannedTask]
    created_at: str = field(default_factory=utc_now)


class AgentRegistry:
    """Registry of trusted application-defined agents."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentCapability] = {}

    def register(
        self,
        agent_name: str,
        description: str,
        handler: Callable[[dict[str, Any]], Any],
        allowed_tasks: set[str],
        requires_approval: bool = False,
        max_retries: int = 0,
    ) -> None:
        if not agent_name.strip():
            raise PlanningError("Agent name is required.")

        if not callable(handler):
            raise PlanningError("Agent handler must be callable.")

        if not allowed_tasks:
            raise PlanningError(
                "At least one allowed task is required."
            )

        if (
            isinstance(max_retries, bool)
            or not isinstance(max_retries, int)
            or not 0 <= max_retries <= 10
        ):
            raise PlanningError(
                "max_retries must be between 0 and 10."
            )

        self._agents[agent_name] = AgentCapability(
            agent_name=agent_name,
            description=description,
            handler=handler,
            allowed_tasks=frozenset(allowed_tasks),
            requires_approval=requires_approval,
            max_retries=max_retries,
        )

    def get(self, agent_name: str) -> AgentCapability:
        agent = self._agents.get(agent_name)

        if agent is None:
            raise PlanningError(
                f"Unknown agent: {agent_name}"
            )

        return agent

    def find_for_task(
        self,
        task_type: str,
    ) -> AgentCapability:
        candidates = [
            agent
            for agent in self._agents.values()
            if task_type in agent.allowed_tasks
        ]

        if not candidates:
            raise PlanningError(
                f"No registered agent handles: {task_type}"
            )

        # Deterministic selection; can later be replaced
        # by a policy-based or model-based router.
        return sorted(
            candidates,
            key=lambda agent: agent.agent_name,
        )[0]

    def list_agents(self) -> list[dict[str, Any]]:
        return [
            {
                "agent_name": agent.agent_name,
                "description": agent.description,
                "allowed_tasks": sorted(agent.allowed_tasks),
                "requires_approval": agent.requires_approval,
            }
            for agent in self._agents.values()
        ]


class WorkflowPlanner:
    """Create safe DAG plans from trusted task specifications."""

    def __init__(
        self,
        registry: AgentRegistry,
    ) -> None:
        self.registry = registry

    def create_plan(
        self,
        goal: str,
        tenant_id: str,
        task_specs: list[dict[str, Any]],
    ) -> WorkflowPlan:
        if not goal.strip():
            raise PlanningError("Goal is required.")

        if not tenant_id.strip():
            raise PlanningError("Tenant ID is required.")

        if not task_specs:
            raise PlanningError(
                "At least one task specification is required."
            )

        tasks: list[PlannedTask] = []
        seen: set[str] = set()

        for index, spec in enumerate(task_specs):
            if not isinstance(spec, dict):
                raise PlanningError(
                    "Task specifications must be dictionaries."
                )

            task_type = spec.get("task_type")
            if not isinstance(task_type, str) or not task_type:
                raise PlanningError(
                    "Every task requires task_type."
                )

            task_id = spec.get(
                "task_id", f"task_{index + 1}"
            )

            if not isinstance(task_id, str) or not task_id:
                raise PlanningError("Invalid task_id.")

            if task_id in seen:
                raise PlanningError(
                    f"Duplicate task ID: {task_id}"
                )

            seen.add(task_id)

            requested_agent = spec.get("agent_name")

            agent = (
                self.registry.get(requested_agent)
                if requested_agent
                else self.registry.find_for_task(task_type)
            )

            if task_type not in agent.allowed_tasks:
                raise PlanningError(
                    f"Agent {agent.agent_name} cannot "
                    f"execute {task_type}."
                )

            dependencies = spec.get("dependencies", [])

            if (
                not isinstance(dependencies, list)
                or any(
                    not isinstance(item, str)
                    for item in dependencies
                )
            ):
                raise PlanningError(
                    "Dependencies must be a list of strings."
                )

            retries = spec.get(
                "max_retries", agent.max_retries
            )

            if (
                isinstance(retries, bool)
                or not isinstance(retries, int)
                or not 0 <= retries <= 10
            ):
                raise PlanningError(
                    "Invalid retry count."
                )

            # Agent policy cannot be overridden to
            # disable mandatory human approval.
            approval_required = (
                agent.requires_approval
                or spec.get("requires_approval") is True
            )

            tasks.append(
                PlannedTask(
                    task_id=task_id,
                    task_type=task_type,
                    agent_name=agent.agent_name,
                    description=spec.get(
                        "description", task_type
                    ),
                    dependencies=list(dependencies),
                    requires_approval=approval_required,
                    max_retries=retries,
                )
            )

        plan = WorkflowPlan(
            plan_id=str(uuid4()),
            goal=goal,
            tenant_id=tenant_id,
            tasks=tasks,
        )

        self.validate_plan(plan)
        return plan

    def validate_plan(
        self,
        plan: WorkflowPlan,
    ) -> None:
        task_ids = {
            task.task_id for task in plan.tasks
        }

        if len(task_ids) != len(plan.tasks):
            raise PlanningError(
                "Duplicate task IDs in plan."
            )

        for task in plan.tasks:
            for dependency in task.dependencies:
                if dependency not in task_ids:
                    raise PlanningError(
                        f"Missing dependency: {dependency}"
                    )

                if dependency == task.task_id:
                    raise PlanningError(
                        "Task cannot depend on itself."
                    )

        self.topological_order(plan)

    def topological_order(
        self,
        plan: WorkflowPlan,
    ) -> list[str]:
        task_map = {
            task.task_id: task
            for task in plan.tasks
        }

        visited: set[str] = set()
        visiting: set[str] = set()
        order: list[str] = []

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise PlanningError(
                    "Circular dependency detected."
                )

            if task_id in visited:
                return

            visiting.add(task_id)

            for dependency in task_map[
                task_id
            ].dependencies:
                if dependency not in task_map:
                    raise PlanningError(
                        f"Unknown dependency: {dependency}"
                    )
                visit(dependency)

            visiting.remove(task_id)
            visited.add(task_id)
            order.append(task_id)

        for task in plan.tasks:
            visit(task.task_id)

        return order

    def compile_graph(
        self,
        plan: WorkflowPlan,
    ) -> WorkflowGraph:
        self.validate_plan(plan)

        graph = WorkflowGraph(
            name=f"plan_{plan.plan_id}"
        )

        for task in plan.tasks:
            agent = self.registry.get(
                task.agent_name
            )

            if task.task_type not in agent.allowed_tasks:
                raise PlanningError(
                    "Agent capability changed."
                )

            graph.add_node(
                WorkflowNode(
                    node_id=task.task_id,
                    handler=agent.handler,
                    dependencies=list(
                        task.dependencies
                    ),
                    requires_approval=(
                        task.requires_approval
                        or agent.requires_approval
                    ),
                    max_retries=task.max_retries,
                    description=task.description,
                )
            )

        graph.validate()
        return graph

    def describe_plan(
        self,
        plan: WorkflowPlan,
    ) -> dict[str, Any]:
        return {
            "plan_id": plan.plan_id,
            "goal": plan.goal,
            "tenant_id": plan.tenant_id,
            "created_at": plan.created_at,
            "execution_order": self.topological_order(
                plan
            ),
            "tasks": [
                {
                    "task_id": task.task_id,
                    "task_type": task.task_type,
                    "agent_name": task.agent_name,
                    "description": task.description,
                    "dependencies": task.dependencies,
                    "requires_approval": (
                        task.requires_approval
                    ),
                    "max_retries": task.max_retries,
                }
                for task in plan.tasks
            ],
        }


if __name__ == "__main__":
    registry = AgentRegistry()

    registry.register(
        agent_name="demand_agent",
        description="Forecast product demand.",
        handler=lambda state: {
            "forecast_demand": 250
        },
        allowed_tasks={"forecast_demand"},
    )

    registry.register(
        agent_name="inventory_agent",
        description="Analyze inventory shortage.",
        handler=lambda state: {
            "shortage": max(
                0,
                state["forecast_demand"]
                - state["available_stock"]
            )
        },
        allowed_tasks={"check_inventory"},
    )

    registry.register(
        agent_name="procurement_agent",
        description="Prepare purchase proposal.",
        handler=lambda state: {
            "purchase_proposal": {
                "quantity": state["shortage"],
                "status": "proposed",
            }
        },
        allowed_tasks={"prepare_procurement"},
        requires_approval=True,
    )

    planner = WorkflowPlanner(registry)

    plan = planner.create_plan(
        goal="Forecast demand and prepare procurement.",
        tenant_id="retail_company_001",
        task_specs=[
            {
                "task_id": "forecast",
                "task_type": "forecast_demand",
            },
            {
                "task_id": "inventory",
                "task_type": "check_inventory",
                "dependencies": ["forecast"],
            },
            {
                "task_id": "procurement",
                "task_type": "prepare_procurement",
                "dependencies": ["inventory"],
            },
        ],
    )

    print(planner.describe_plan(plan))

    graph = planner.compile_graph(plan)
    print(graph.describe())
