"""Planned module: product quality agent. Implementation pending."""

"""
File: ai/agents/planning_agent.py

Autonomous Retail Supply Chain AI 5.0

Capabilities:
- create_supply_plan
- analyze_capacity
- compare_plans
- build_execution_plan

Python 3.10+
Standard library only.
"""

from __future__ import annotations

import math
from typing import Any

from .base_agent import (
    BaseAgent,
    AgentRequest,
    AgentValidationError,
)


class PlanningAgent(BaseAgent):

    def __init__(self, working_memory=None):
        super().__init__(
            agent_id="planning_agent",
            name="Supply Chain Planning Agent",
            capabilities={
                "create_supply_plan",
                "analyze_capacity",
                "compare_plans",
                "build_execution_plan",
            },
            working_memory=working_memory,
        )

    @staticmethod
    def _number(
        value: Any,
        name: str,
    ) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise AgentValidationError(
                f"{name} must be finite and nonnegative."
            )
        return float(value)

    @staticmethod
    def _integer(
        value: Any,
        name: str,
        minimum: int = 0,
    ) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < minimum
        ):
            raise AgentValidationError(
                f"{name} must be an integer >= {minimum}."
            )
        return value

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

    def _supply_plan(self, payload: dict) -> dict:
        product_id = self._text(
            payload.get("product_id"), "product_id"
        )

        daily_demand = self._number(
            payload.get("daily_demand"),
            "daily_demand",
        )
        available_stock = self._integer(
            payload.get("available_stock"),
            "available_stock",
        )
        incoming_stock = self._integer(
            payload.get("incoming_stock", 0),
            "incoming_stock",
        )
        safety_stock = self._integer(
            payload.get("safety_stock", 0),
            "safety_stock",
        )
        lead_time = self._integer(
            payload.get("lead_time_days"),
            "lead_time_days",
            minimum=1,
        )
        planning_horizon = self._integer(
            payload.get("planning_horizon_days", 14),
            "planning_horizon_days",
            minimum=1,
        )

        if planning_horizon > 365:
            raise AgentValidationError(
                "Planning horizon exceeds 365 days."
            )

        target_demand = (
            daily_demand * planning_horizon
        )
        lead_time_demand = (
            daily_demand * lead_time
        )
        reorder_point = (
            lead_time_demand + safety_stock
        )

        projected_supply = (
            available_stock + incoming_stock
        )

        suggested_quantity = max(
            0,
            math.ceil(
                target_demand
                + safety_stock
                - projected_supply
            ),
        )

        stockout_before_replenishment = (
            available_stock < lead_time_demand
        )

        if available_stock < lead_time_demand:
            priority = "critical"
        elif available_stock < reorder_point:
            priority = "high"
        elif suggested_quantity > 0:
            priority = "medium"
        else:
            priority = "low"

        return {
            "product_id": product_id,
            "planning_horizon_days": planning_horizon,
            "daily_demand": daily_demand,
            "available_stock": available_stock,
            "incoming_stock": incoming_stock,
            "safety_stock": safety_stock,
            "lead_time_days": lead_time,
            "forecast_horizon_demand": round(
                target_demand, 2
            ),
            "reorder_point": round(
                reorder_point, 2
            ),
            "suggested_order_quantity": (
                suggested_quantity
            ),
            "stockout_before_replenishment": (
                stockout_before_replenishment
            ),
            "priority": priority,
            "approval_required": True,
            "recommendation_only": True,
            "assumptions": [
                "Daily demand is constant.",
                "Incoming stock is assumed usable "
                "within the planning horizon.",
                "Supplier order multiples and "
                "warehouse constraints are not "
                "applied automatically.",
            ],
        }

    def _capacity(self, payload: dict) -> dict:
        warehouse_id = self._text(
            payload.get("warehouse_id"),
            "warehouse_id",
        )
        capacity = self._integer(
            payload.get("capacity_units"),
            "capacity_units",
            minimum=1,
        )
        occupied = self._integer(
            payload.get("occupied_units"),
            "occupied_units",
        )
        incoming = self._integer(
            payload.get("incoming_units", 0),
            "incoming_units",
        )

        projected = occupied + incoming

        return {
            "warehouse_id": warehouse_id,
            "capacity_units": capacity,
            "occupied_units": occupied,
            "incoming_units": incoming,
            "projected_occupied_units": projected,
            "utilization_percent": round(
                projected / capacity * 100, 2
            ),
            "remaining_capacity_units": max(
                0, capacity - projected
            ),
            "capacity_violation": projected > capacity,
            "recommendation": (
                "Review storage or redistribution."
                if projected > capacity
                else "Capacity is sufficient."
            ),
        }

    def _compare(self, payload: dict) -> dict:
        scenarios = payload.get("scenarios")

        if (
            not isinstance(scenarios, list)
            or not 2 <= len(scenarios) <= 20
        ):
            raise AgentValidationError(
                "Provide 2 to 20 scenarios."
            )

        results = []
        names = set()

        for scenario in scenarios:
            if not isinstance(scenario, dict):
                raise AgentValidationError(
                    "Each scenario must be an object."
                )

            name = self._text(
                scenario.get("name"), "name"
            )
            if name in names:
                raise AgentValidationError(
                    "Duplicate scenario name."
                )
            names.add(name)

            unmet_demand = self._number(
                scenario.get("unmet_demand"),
                "unmet_demand",
            )
            estimated_cost = self._number(
                scenario.get("estimated_cost"),
                "estimated_cost",
            )
            delay_days = self._number(
                scenario.get("delay_days", 0),
                "delay_days",
            )

            results.append({
                "name": name,
                "unmet_demand": unmet_demand,
                "estimated_cost": estimated_cost,
                "delay_days": delay_days,
            })

        results.sort(
            key=lambda x: (
                x["unmet_demand"],
                x["delay_days"],
                x["estimated_cost"],
            )
        )

        return {
            "ranked_scenarios": results,
            "preferred_scenario": results[0]["name"],
            "ranking_basis": (
                "Lowest unmet demand, then "
                "lowest delay, then lowest cost."
            ),
        }

    def _execution_plan(self, payload: dict) -> dict:
        product_id = self._text(
            payload.get("product_id"),
            "product_id",
        )
        quantity = self._integer(
            payload.get("quantity"),
            "quantity",
            minimum=1,
        )

        return {
            "product_id": product_id,
            "quantity": quantity,
            "steps": [
                {
                    "step": 1,
                    "agent": "inventory_agent",
                    "task": "analyze_inventory",
                },
                {
                    "step": 2,
                    "agent": "supplier_agent",
                    "task": "evaluate_supplier",
                },
                {
                    "step": 3,
                    "agent": "finance_agent",
                    "task": "evaluate_purchase",
                },
                {
                    "step": 4,
                    "agent": "procurement_agent",
                    "task": "create_requisition",
                },
                {
                    "step": 5,
                    "agent": "human_approval",
                    "task": "approve_purchase",
                },
                {
                    "step": 6,
                    "agent": "procurement_agent",
                    "task": "create_purchase_order",
                },
                {
                    "step": 7,
                    "agent": "logistics_agent",
                    "task": "register_shipment",
                },
            ],
            "execution_started": False,
            "human_approval_required": True,
        }

    def process(self, request: AgentRequest) -> dict:
        task = request.task_type
        payload = request.payload

        if task == "create_supply_plan":
            return self._supply_plan(payload)

        if task == "analyze_capacity":
            return self._capacity(payload)

        if task == "compare_plans":
            return self._compare(payload)

        if task == "build_execution_plan":
            return self._execution_plan(payload)

        raise AgentValidationError(
            "Unsupported planning task."
        )
