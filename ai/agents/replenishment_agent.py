
"""
File: ai/agents/replenishment_agent.py

Autonomous Retail Supply Chain AI 5.0

Capabilities:
- calculate_reorder_point
- recommend_replenishment
- analyze_stockout_risk
- batch_replenishment_plan

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


class ReplenishmentAgent(BaseAgent):

    def __init__(self, working_memory=None):
        super().__init__(
            agent_id="replenishment_agent",
            name="Retail Replenishment Intelligence Agent",
            capabilities={
                "calculate_reorder_point",
                "recommend_replenishment",
                "analyze_stockout_risk",
                "batch_replenishment_plan",
            },
            working_memory=working_memory,
        )

    @staticmethod
    def _number(
        value: Any,
        name: str,
        minimum: float = 0,
    ) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < minimum
        ):
            raise AgentValidationError(
                f"{name} must be a finite number >= {minimum}."
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

    def _inputs(self, payload: dict) -> dict:
        return {
            "product_id": self._text(
                payload.get("product_id"),
                "product_id",
            ),
            "available_stock": self._integer(
                payload.get("available_stock"),
                "available_stock",
            ),
            "daily_demand": self._number(
                payload.get("daily_demand"),
                "daily_demand",
            ),
            "lead_time_days": self._integer(
                payload.get("lead_time_days"),
                "lead_time_days",
                minimum=1,
            ),
            "safety_stock": self._integer(
                payload.get("safety_stock", 0),
                "safety_stock",
            ),
            "incoming_stock": self._integer(
                payload.get("incoming_stock", 0),
                "incoming_stock",
            ),
        }

    def _reorder_point(self, payload: dict) -> dict:
        values = self._inputs(payload)

        lead_demand = (
            values["daily_demand"]
            * values["lead_time_days"]
        )

        reorder_point = math.ceil(
            lead_demand + values["safety_stock"]
        )

        return {
            **values,
            "lead_time_demand": round(
                lead_demand, 2
            ),
            "reorder_point": reorder_point,
            "reorder_triggered": (
                values["available_stock"]
                <= reorder_point
            ),
            "method": (
                "Average demand during lead time "
                "plus safety stock."
            ),
        }

    def _stockout_risk(self, payload: dict) -> dict:
        values = self._inputs(payload)

        lead_demand = (
            values["daily_demand"]
            * values["lead_time_days"]
        )

        available = values["available_stock"]

        if available < lead_demand:
            risk = "high"
        elif available <= (
            lead_demand + values["safety_stock"]
        ):
            risk = "medium"
        else:
            risk = "low"

        days_cover = (
            available / values["daily_demand"]
            if values["daily_demand"] > 0
            else None
        )

        return {
            "product_id": values["product_id"],
            "stockout_risk": risk,
            "estimated_days_of_cover": (
                round(days_cover, 2)
                if days_cover is not None else None
            ),
            "expected_lead_time_demand": round(
                lead_demand, 2
            ),
            "potential_shortage_units": max(
                0,
                math.ceil(lead_demand - available),
            ),
            "assumption": (
                "Incoming stock is excluded from "
                "lead-time risk because its arrival "
                "date is unknown."
            ),
        }

    def _recommend(self, payload: dict) -> dict:
        values = self._inputs(payload)

        target_days = self._integer(
            payload.get("target_cover_days", 14),
            "target_cover_days",
            minimum=1,
        )

        if target_days > 365:
            raise AgentValidationError(
                "target_cover_days exceeds 365."
            )

        target_stock = math.ceil(
            values["daily_demand"] * target_days
            + values["safety_stock"]
        )

        net_stock = (
            values["available_stock"]
            + values["incoming_stock"]
        )

        required = max(
            0,
            target_stock - net_stock,
        )

        minimum_order = self._integer(
            payload.get("minimum_order_quantity", 1),
            "minimum_order_quantity",
            minimum=1,
        )

        order_multiple = self._integer(
            payload.get("order_multiple", 1),
            "order_multiple",
            minimum=1,
        )

        if required == 0:
            recommended = 0
        else:
            recommended = max(
                required, minimum_order
            )

            recommended = (
                math.ceil(
                    recommended / order_multiple
                ) * order_multiple
            )

        unit_cost = self._number(
            payload.get("unit_cost", 0),
            "unit_cost",
        )

        estimated_cost = recommended * unit_cost

        budget = payload.get("available_budget")

        budget_sufficient = None

        if budget is not None:
            budget_sufficient = (
                estimated_cost <= self._number(
                    budget, "available_budget"
                )
            )

        free_capacity = payload.get(
            "free_capacity_units"
        )

        capacity_sufficient = None

        if free_capacity is not None:
            capacity_sufficient = (
                recommended <= self._integer(
                    free_capacity,
                    "free_capacity_units",
                )
            )

        constraints_satisfied = (
            budget_sufficient is not False
            and capacity_sufficient is not False
        )

        return {
            "product_id": values["product_id"],
            "target_cover_days": target_days,
            "target_stock": target_stock,
            "net_stock": net_stock,
            "minimum_order_quantity": minimum_order,
            "order_multiple": order_multiple,
            "recommended_order_quantity": recommended,
            "estimated_purchase_cost": round(
                estimated_cost, 2
            ),
            "budget_sufficient": budget_sufficient,
            "capacity_sufficient": capacity_sufficient,
            "constraints_satisfied": (
                constraints_satisfied
            ),
            "approval_required": True,
            "recommendation_only": True,
            "purchase_order_created": False,
        }

    def _batch(self, payload: dict) -> dict:
        products = payload.get("products")

        if (
            not isinstance(products, list)
            or not 1 <= len(products) <= 500
        ):
            raise AgentValidationError(
                "Provide 1 to 500 products."
            )

        recommendations = []
        seen = set()

        # Validate the complete batch before
        # returning any recommendations.
        for product in products:
            if not isinstance(product, dict):
                raise AgentValidationError(
                    "Each product must be an object."
                )

            recommendation = self._recommend(
                product
            )

            product_id = recommendation[
                "product_id"
            ]

            if product_id in seen:
                raise AgentValidationError(
                    "Duplicate product_id."
                )

            seen.add(product_id)
            recommendations.append(
                recommendation
            )

        return {
            "product_count": len(recommendations),
            "products_requiring_orders": sum(
                item["recommended_order_quantity"] > 0
                for item in recommendations
            ),
            "recommendations": recommendations,
            "all_orders_require_approval": True,
        }

    def process(self, request: AgentRequest) -> dict:
        task = request.task_type
        payload = request.payload

        if task == "calculate_reorder_point":
            return self._reorder_point(payload)

        if task == "recommend_replenishment":
            return self._recommend(payload)

        if task == "analyze_stockout_risk":
            return self._stockout_risk(payload)

        if task == "batch_replenishment_plan":
            return self._batch(payload)

        raise AgentValidationError(
            "Unsupported replenishment task."
        )
