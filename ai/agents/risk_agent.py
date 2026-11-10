
"""
File: ai/agents/risk_agent.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+ | Standard library only

Capabilities:
- assess_supply_chain_risk
- assess_supplier_risk
- assess_inventory_risk
- assess_logistics_risk
- compare_risk_scenarios

All outputs are recommendations.
No operational actions are executed.
"""

from __future__ import annotations

import math
from typing import Any

from .base_agent import (
    BaseAgent,
    AgentRequest,
    AgentValidationError,
)


class RiskAgent(BaseAgent):

    def __init__(self, working_memory=None):
        super().__init__(
            agent_id="risk_agent",
            name="Supply Chain Risk Intelligence Agent",
            capabilities={
                "assess_supply_chain_risk",
                "assess_supplier_risk",
                "assess_inventory_risk",
                "assess_logistics_risk",
                "compare_risk_scenarios",
            },
            working_memory=working_memory,
        )

    @staticmethod
    def _number(
        value: Any,
        name: str,
        minimum: float = 0.0,
        maximum: float | None = None,
    ) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < minimum
            or (maximum is not None and value > maximum)
        ):
            raise AgentValidationError(
                f"Invalid {name}."
            )
        return float(value)

    @staticmethod
    def _bool(value: Any, name: str) -> bool:
        if not isinstance(value, bool):
            raise AgentValidationError(
                f"{name} must be boolean."
            )
        return value

    @staticmethod
    def _level(score: float) -> str:
        if score >= 80:
            return "critical"
        if score >= 60:
            return "high"
        if score >= 35:
            return "medium"
        return "low"

    def _supplier(self, payload: dict) -> dict:
        on_time = self._number(
            payload.get("on_time_delivery_percent"),
            "on_time_delivery_percent",
            maximum=100,
        )

        defect_rate = self._number(
            payload.get("defect_rate_percent"),
            "defect_rate_percent",
            maximum=100,
        )

        financial_risk = self._number(
            payload.get("financial_risk_score", 0),
            "financial_risk_score",
            maximum=100,
        )

        score = (
            (100 - on_time) * 0.45
            + defect_rate * 0.35
            + financial_risk * 0.20
        )

        return {
            "supplier_id": payload.get("supplier_id"),
            "risk_score": round(score, 2),
            "risk_level": self._level(score),
            "risk_factors": {
                "late_delivery": round(
                    100 - on_time, 2
                ),
                "defect_rate": defect_rate,
                "financial_risk": financial_risk,
            },
            "recommendation": (
                "Review supplier performance "
                "and alternative sourcing."
                if score >= 35
                else "Continue routine monitoring."
            ),
        }

    def _inventory(self, payload: dict) -> dict:
        available = self._number(
            payload.get("available_stock"),
            "available_stock",
        )

        daily_demand = self._number(
            payload.get("daily_demand"),
            "daily_demand",
        )

        lead_time = self._number(
            payload.get("lead_time_days"),
            "lead_time_days",
            minimum=1,
        )

        safety_stock = self._number(
            payload.get("safety_stock", 0),
            "safety_stock",
        )

        required = (
            daily_demand * lead_time
            + safety_stock
        )

        shortage = max(0, required - available)

        if required == 0:
            score = 0.0
        else:
            score = min(
                100.0,
                shortage / required * 100,
            )

        return {
            "product_id": payload.get("product_id"),
            "required_stock": round(required, 2),
            "available_stock": available,
            "shortage_units": round(shortage, 2),
            "risk_score": round(score, 2),
            "risk_level": self._level(score),
            "stockout_possible": (
                available < daily_demand * lead_time
            ),
            "recommendation": (
                "Review urgent replenishment."
                if score >= 60
                else "Monitor inventory coverage."
            ),
        }

    def _logistics(self, payload: dict) -> dict:
        delay = self._number(
            payload.get("delay_hours", 0),
            "delay_hours",
        )

        damage = self._bool(
            payload.get("cargo_damaged", False),
            "cargo_damaged",
        )

        temperature = self._bool(
            payload.get("temperature_breach", False),
            "temperature_breach",
        )

        delay_score = min(
            100.0,
            delay / 24 * 100,
        )

        score = min(
            100.0,
            delay_score * 0.5
            + (30 if damage else 0)
            + (30 if temperature else 0),
        )

        # Safety-related flags override numeric scoring.
        if damage or temperature:
            score = max(score, 80.0)

        return {
            "shipment_id": payload.get("shipment_id"),
            "risk_score": round(score, 2),
            "risk_level": self._level(score),
            "delay_hours": delay,
            "cargo_damaged": damage,
            "temperature_breach": temperature,
            "escalation_recommended": (
                score >= 60
            ),
        }

    def _overall(self, payload: dict) -> dict:
        supplier = self._supplier(
            payload.get("supplier", {})
        )
        inventory = self._inventory(
            payload.get("inventory", {})
        )
        logistics = self._logistics(
            payload.get("logistics", {})
        )

        weights = {
            "supplier": 0.30,
            "inventory": 0.40,
            "logistics": 0.30,
        }

        score = (
            supplier["risk_score"] * weights["supplier"]
            + inventory["risk_score"] * weights["inventory"]
            + logistics["risk_score"] * weights["logistics"]
        )

        # Do not dilute a critical safety signal.
        if (
            logistics["cargo_damaged"]
            or logistics["temperature_breach"]
        ):
            score = max(score, 80.0)

        level = self._level(score)

        return {
            "overall_risk_score": round(score, 2),
            "overall_risk_level": level,
            "component_risks": {
                "supplier": supplier,
                "inventory": inventory,
                "logistics": logistics,
            },
            "escalation_recommended": (
                level in {"high", "critical"}
            ),
            "recommendation_only": True,
            "method": "weighted_rule_based_scoring",
        }

    def _compare(self, payload: dict) -> dict:
        scenarios = payload.get("scenarios")

        if (
            not isinstance(scenarios, list)
            or not 2 <= len(scenarios) <= 20
        ):
            raise AgentValidationError(
                "Provide 2 to 20 risk scenarios."
            )

        results = []
        seen = set()

        for scenario in scenarios:
            if not isinstance(scenario, dict):
                raise AgentValidationError(
                    "Scenario must be an object."
                )

            name = scenario.get("name")

            if (
                not isinstance(name, str)
                or not name.strip()
                or name in seen
            ):
                raise AgentValidationError(
                    "Scenario names must be unique."
                )

            seen.add(name)

            risk = self._overall(scenario)

            results.append({
                "name": name,
                "risk_score": risk[
                    "overall_risk_score"
                ],
                "risk_level": risk[
                    "overall_risk_level"
                ],
            })

        results.sort(
            key=lambda item: item["risk_score"]
        )

        return {
            "ranked_scenarios": results,
            "lowest_risk_scenario": (
                results[0]["name"]
            ),
        }

    def process(self, request: AgentRequest) -> dict:
        task = request.task_type
        payload = request.payload

        if task == "assess_supplier_risk":
            return self._supplier(payload)

        if task == "assess_inventory_risk":
            return self._inventory(payload)

        if task == "assess_logistics_risk":
            return self._logistics(payload)

        if task == "assess_supply_chain_risk":
            return self._overall(payload)

        if task == "compare_risk_scenarios":
            return self._compare(payload)

        raise AgentValidationError(
            "Unsupported risk task."
        )
