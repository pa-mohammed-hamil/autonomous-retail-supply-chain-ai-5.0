"""Planned module: simulation agent. Implementation pending."""

"""
File: ai/agents/simulation_agent.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+ | Standard library only

Capabilities:
- simulate_demand_spike
- simulate_supplier_delay
- simulate_stockout
- simulate_replenishment
- compare_scenarios

All calculations are hypothetical.
No external systems are modified.
"""

from __future__ import annotations

import math
from typing import Any

from .base_agent import (
    BaseAgent,
    AgentRequest,
    AgentValidationError,
)


class SimulationAgent(BaseAgent):

    def __init__(self, working_memory=None):
        super().__init__(
            agent_id="simulation_agent",
            name="Retail Supply Chain Simulation Agent",
            capabilities={
                "simulate_demand_spike",
                "simulate_supplier_delay",
                "simulate_stockout",
                "simulate_replenishment",
                "compare_scenarios",
            },
            working_memory=working_memory,
        )

    @staticmethod
    def _number(
        value: Any,
        name: str,
        minimum: float = 0.0,
    ) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < minimum
        ):
            raise AgentValidationError(
                f"{name} must be finite and >= {minimum}."
            )
        return float(value)

    @staticmethod
    def _days(value: Any, name: str) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 1 <= value <= 365
        ):
            raise AgentValidationError(
                f"{name} must be 1 to 365."
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

    def _demand_spike(self, p: dict) -> dict:
        product_id = self._text(
            p.get("product_id"), "product_id"
        )
        stock = self._number(
            p.get("available_stock"),
            "available_stock",
        )
        daily_demand = self._number(
            p.get("daily_demand"),
            "daily_demand",
        )
        increase = self._number(
            p.get("demand_increase_percent"),
            "demand_increase_percent",
        )
        days = self._days(
            p.get("horizon_days", 7),
            "horizon_days",
        )

        projected_daily = daily_demand * (
            1 + increase / 100
        )
        projected_demand = projected_daily * days
        unmet = max(0, projected_demand - stock)

        return {
            "product_id": product_id,
            "scenario": "demand_spike",
            "original_daily_demand": daily_demand,
            "projected_daily_demand": round(
                projected_daily, 2
            ),
            "horizon_days": days,
            "projected_total_demand": round(
                projected_demand, 2
            ),
            "projected_remaining_stock": round(
                max(0, stock - projected_demand), 2
            ),
            "unmet_demand_units": round(unmet, 2),
            "stockout_expected": unmet > 0,
            "simulation_only": True,
        }

    def _supplier_delay(self, p: dict) -> dict:
        stock = self._number(
            p.get("available_stock"),
            "available_stock",
        )
        daily_demand = self._number(
            p.get("daily_demand"),
            "daily_demand",
        )
        lead_time = self._days(
            p.get("lead_time_days"),
            "lead_time_days",
        )
        additional_delay = self._number(
            p.get("additional_delay_days"),
            "additional_delay_days",
        )

        new_lead_time = (
            lead_time + additional_delay
        )
        demand_until_arrival = (
            daily_demand * new_lead_time
        )

        return {
            "scenario": "supplier_delay",
            "original_lead_time_days": lead_time,
            "new_lead_time_days": new_lead_time,
            "demand_until_arrival": round(
                demand_until_arrival, 2
            ),
            "projected_shortage_units": round(
                max(0, demand_until_arrival - stock),
                2,
            ),
            "stockout_before_arrival": (
                stock < demand_until_arrival
            ),
            "simulation_only": True,
        }

    def _stockout(self, p: dict) -> dict:
        stock = self._number(
            p.get("available_stock"),
            "available_stock",
        )
        demand = self._number(
            p.get("daily_demand"),
            "daily_demand",
        )
        horizon = self._days(
            p.get("horizon_days", 14),
            "horizon_days",
        )

        total_demand = demand * horizon

        days_of_cover = (
            stock / demand if demand > 0 else None
        )

        return {
            "scenario": "stockout",
            "available_stock": stock,
            "daily_demand": demand,
            "horizon_days": horizon,
            "days_of_cover": (
                round(days_of_cover, 2)
                if days_of_cover is not None else None
            ),
            "unmet_demand_units": round(
                max(0, total_demand - stock), 2
            ),
            "stockout_expected": (
                total_demand > stock
            ),
            "simulation_only": True,
        }

    def _replenishment(self, p: dict) -> dict:
        stock = self._number(
            p.get("available_stock"),
            "available_stock",
        )
        incoming = self._number(
            p.get("incoming_units"),
            "incoming_units",
        )
        demand = self._number(
            p.get("daily_demand"),
            "daily_demand",
        )
        horizon = self._days(
            p.get("horizon_days", 14),
            "horizon_days",
        )
        unit_cost = self._number(
            p.get("unit_cost", 0),
            "unit_cost",
        )

        arrival_day = p.get("arrival_day", 1)

        if (
            isinstance(arrival_day, bool)
            or not isinstance(arrival_day, int)
            or not 1 <= arrival_day <= horizon
        ):
            raise AgentValidationError(
                "arrival_day must fall within horizon."
            )

        # Incoming inventory becomes usable at
        # the start of the specified arrival day.
        remaining = stock
        unmet = 0.0
        daily_results = []

        for day in range(1, horizon + 1):
            if day == arrival_day:
                remaining += incoming

            served = min(remaining, demand)
            remaining -= served

            shortage = demand - served
            unmet += shortage

            daily_results.append({
                "day": day,
                "ending_stock": round(
                    remaining, 2
                ),
                "unmet_demand": round(
                    shortage, 2
                ),
            })

        return {
            "scenario": "replenishment",
            "incoming_units": incoming,
            "arrival_day": arrival_day,
            "horizon_days": horizon,
            "ending_stock": round(remaining, 2),
            "unmet_demand_units": round(unmet, 2),
            "estimated_purchase_cost": round(
                incoming * unit_cost, 2
            ),
            "daily_results": daily_results,
            "simulation_only": True,
        }

    def _compare(self, p: dict) -> dict:
        scenarios = p.get("scenarios")

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
                    "Scenario must be an object."
                )

            name = self._text(
                scenario.get("name"), "name"
            )

            if name in names:
                raise AgentValidationError(
                    "Scenario names must be unique."
                )

            names.add(name)

            scenario_type = scenario.get(
                "scenario_type"
            )

            if scenario_type == "demand_spike":
                result = self._demand_spike(scenario)
            elif scenario_type == "supplier_delay":
                result = self._supplier_delay(scenario)
            elif scenario_type == "stockout":
                result = self._stockout(scenario)
            elif scenario_type == "replenishment":
                result = self._replenishment(scenario)
            else:
                raise AgentValidationError(
                    "Unsupported scenario_type."
                )

            results.append({
                "name": name,
                "scenario_type": scenario_type,
                "unmet_demand_units": result.get(
                    "unmet_demand_units",
                    result.get(
                        "projected_shortage_units", 0
                    ),
                ),
                "result": result,
            })

        results.sort(
            key=lambda item: (
                item["unmet_demand_units"],
                item["name"],
            )
        )

        return {
            "ranked_scenarios": results,
            "lowest_shortage_scenario": (
                results[0]["name"]
            ),
            "ranking_note": (
                "Ranked only by unmet demand; "
                "cost and differing time horizons "
                "are not normalized."
            ),
            "simulation_only": True,
        }

    def process(self, request: AgentRequest) -> dict:
        task = request.task_type
        p = request.payload

        if task == "simulate_demand_spike":
            return self._demand_spike(p)

        if task == "simulate_supplier_delay":
            return self._supplier_delay(p)

        if task == "simulate_stockout":
            return self._stockout(p)

        if task == "simulate_replenishment":
            return self._replenishment(p)

        if task == "compare_scenarios":
            return self._compare(p)

        raise AgentValidationError(
            "Unsupported simulation task."
        )
