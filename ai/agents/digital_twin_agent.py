"""Planned module: digital twin agent. Implementation pending."""

"""
File: ai/agents/digital_twin_agent.py
Project: Autonomous Retail Supply Chain AI 5.0

Warehouse and inventory digital twin.

Features:
- Tenant-isolated warehouse twins
- Virtual inventory snapshots
- Warehouse capacity monitoring
- Stock movement simulation
- What-if demand scenarios
- Replenishment projections
- Scenario comparison
- Optimistic version checks
- BaseAgent integration

Python 3.10+
Standard library only.

IMPORTANT:
- All simulations operate on virtual state.
- No real inventory changes are executed.
- Twin state is in memory.
- Input data must come from trusted systems.
"""

from __future__ import annotations

import copy
import math
import threading

from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

from .base_agent import (
    BaseAgent,
    AgentRequest,
    AgentValidationError,
    utc_now,
)


@dataclass
class WarehouseTwin:
    twin_id: str
    tenant_id: str
    warehouse_id: str
    capacity_units: int
    inventory: dict[str, int]
    version: int
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DigitalTwinAgent(BaseAgent):

    def __init__(
        self,
        working_memory: Any | None = None,
    ) -> None:
        super().__init__(
            agent_id="digital_twin_agent",
            name="Warehouse Digital Twin Agent",
            capabilities={
                "create_twin",
                "get_twin",
                "simulate_stock_movement",
                "simulate_demand",
                "simulate_replenishment",
                "compare_scenarios",
                "update_twin_snapshot",
            },
            working_memory=working_memory,
        )

        self._twins: dict[
            tuple[str, str], WarehouseTwin
        ] = {}

        self._lock = threading.RLock()

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

    def _inventory(
        self,
        value: Any,
    ) -> dict[str, int]:
        if not isinstance(value, dict):
            raise AgentValidationError(
                "inventory must be an object."
            )

        result = {}

        for sku, quantity in value.items():
            if (
                not isinstance(sku, str)
                or not sku.strip()
            ):
                raise AgentValidationError(
                    "Invalid SKU."
                )

            result[sku] = self._integer(
                quantity,
                f"inventory[{sku}]",
            )

        return result

    def _get(
        self,
        tenant_id: str,
        twin_id: str,
    ) -> WarehouseTwin:
        twin = self._twins.get(
            (tenant_id, twin_id)
        )

        if twin is None:
            raise AgentValidationError(
                "Digital twin not found."
            )

        return twin

    @staticmethod
    def _metrics(
        inventory: dict[str, int],
        capacity: int,
    ) -> dict[str, Any]:
        occupied = sum(inventory.values())

        return {
            "occupied_units": occupied,
            "capacity_units": capacity,
            "available_capacity_units": max(
                0, capacity - occupied
            ),
            "utilization_percent": round(
                occupied / capacity * 100,
                2,
            ),
            "over_capacity": occupied > capacity,
            "sku_count": len(inventory),
        }

    def _create(
        self,
        request: AgentRequest,
    ) -> dict[str, Any]:
        payload = request.payload

        warehouse_id = payload.get("warehouse_id")

        if (
            not isinstance(warehouse_id, str)
            or not warehouse_id.strip()
        ):
            raise AgentValidationError(
                "warehouse_id is required."
            )

        capacity = self._integer(
            payload.get("capacity_units"),
            "capacity_units",
            minimum=1,
        )

        inventory = self._inventory(
            payload.get("inventory", {})
        )

        if sum(inventory.values()) > capacity:
            raise AgentValidationError(
                "Initial inventory exceeds capacity."
            )

        timestamp = utc_now()

        twin = WarehouseTwin(
            twin_id=str(uuid4()),
            tenant_id=request.context.tenant_id,
            warehouse_id=warehouse_id,
            capacity_units=capacity,
            inventory=inventory,
            version=1,
            created_at=timestamp,
            updated_at=timestamp,
        )

        with self._lock:
            self._twins[
                (twin.tenant_id, twin.twin_id)
            ] = twin

        return {
            "twin": twin.to_dict(),
            "metrics": self._metrics(
                twin.inventory,
                twin.capacity_units,
            ),
        }

    def _simulate_movement(
        self,
        request: AgentRequest,
    ) -> dict[str, Any]:
        payload = request.payload
        tenant_id = request.context.tenant_id
        twin_id = payload.get("twin_id")

        sku = payload.get("sku")

        if not isinstance(sku, str) or not sku.strip():
            raise AgentValidationError(
                "sku is required."
            )

        movement_type = payload.get("movement_type")

        if movement_type not in {
            "inbound", "outbound"
        }:
            raise AgentValidationError(
                "movement_type must be inbound or outbound."
            )

        quantity = self._integer(
            payload.get("quantity"),
            "quantity",
            minimum=1,
        )

        with self._lock:
            twin = self._get(tenant_id, twin_id)
            simulated = copy.deepcopy(
                twin.inventory
            )
            version = twin.version
            capacity = twin.capacity_units

        current = simulated.get(sku, 0)

        if movement_type == "inbound":
            simulated[sku] = current + quantity
        else:
            if quantity > current:
                raise AgentValidationError(
                    "Insufficient virtual stock."
                )

            simulated[sku] = current - quantity

        return {
            "twin_id": twin_id,
            "base_version": version,
            "scenario_type": "stock_movement",
            "movement_type": movement_type,
            "sku": sku,
            "quantity": quantity,
            "previous_stock": current,
            "projected_stock": simulated[sku],
            "projected_inventory": simulated,
            "metrics": self._metrics(
                simulated, capacity
            ),
            "simulation_only": True,
        }

    def _simulate_demand(
        self,
        request: AgentRequest,
    ) -> dict[str, Any]:
        payload = request.payload
        tenant_id = request.context.tenant_id

        sku = payload.get("sku")

        if not isinstance(sku, str) or not sku.strip():
            raise AgentValidationError(
                "sku is required."
            )

        daily_demand = self._integer(
            payload.get("daily_demand"),
            "daily_demand",
        )

        horizon = self._integer(
            payload.get("horizon_days"),
            "horizon_days",
            minimum=1,
        )

        if horizon > 365:
            raise AgentValidationError(
                "horizon_days exceeds 365."
            )

        with self._lock:
            twin = self._get(
                tenant_id,
                payload.get("twin_id"),
            )

            available = twin.inventory.get(sku, 0)
            version = twin.version

        total_demand = daily_demand * horizon

        projected = max(
            0,
            available - total_demand,
        )

        unmet_demand = max(
            0,
            total_demand - available,
        )

        return {
            "twin_id": twin.twin_id,
            "base_version": version,
            "sku": sku,
            "available_stock": available,
            "daily_demand": daily_demand,
            "horizon_days": horizon,
            "expected_total_demand": total_demand,
            "projected_remaining_stock": projected,
            "projected_unmet_demand": unmet_demand,
            "stockout_expected": unmet_demand > 0,
            "simulation_only": True,
        }

    def _simulate_replenishment(
        self,
        request: AgentRequest,
    ) -> dict[str, Any]:
        payload = request.payload
        tenant_id = request.context.tenant_id

        sku = payload.get("sku")

        if not isinstance(sku, str) or not sku.strip():
            raise AgentValidationError(
                "sku is required."
            )

        incoming = self._integer(
            payload.get("incoming_units"),
            "incoming_units",
        )

        with self._lock:
            twin = self._get(
                tenant_id,
                payload.get("twin_id"),
            )

            inventory = copy.deepcopy(
                twin.inventory
            )

            capacity = twin.capacity_units
            version = twin.version

        inventory[sku] = (
            inventory.get(sku, 0) + incoming
        )

        return {
            "twin_id": twin.twin_id,
            "base_version": version,
            "sku": sku,
            "incoming_units": incoming,
            "projected_stock": inventory[sku],
            "metrics": self._metrics(
                inventory, capacity
            ),
            "simulation_only": True,
        }

    def _update_snapshot(
        self,
        request: AgentRequest,
    ) -> dict[str, Any]:
        payload = request.payload
        tenant_id = request.context.tenant_id

        expected_version = self._integer(
            payload.get("expected_version"),
            "expected_version",
            minimum=1,
        )

        inventory = self._inventory(
            payload.get("inventory")
        )

        with self._lock:
            twin = self._get(
                tenant_id,
                payload.get("twin_id"),
            )

            if twin.version != expected_version:
                raise AgentValidationError(
                    "Digital twin version conflict."
                )

            if (
                sum(inventory.values())
                > twin.capacity_units
            ):
                raise AgentValidationError(
                    "Inventory exceeds warehouse capacity."
                )

            twin.inventory = inventory
            twin.version += 1
            twin.updated_at = utc_now()

            return twin.to_dict()

    def _compare(
        self,
        request: AgentRequest,
    ) -> dict[str, Any]:
        scenarios = request.payload.get("scenarios")

        if (
            not isinstance(scenarios, list)
            or not 2 <= len(scenarios) <= 20
        ):
            raise AgentValidationError(
                "Provide 2 to 20 scenarios."
            )

        results = []

        for scenario in scenarios:
            if not isinstance(scenario, dict):
                raise AgentValidationError(
                    "Scenario must be an object."
                )

            name = scenario.get("name")
            projected_stock = self._integer(
                scenario.get("projected_stock"),
                "projected_stock",
            )

            unmet_demand = self._integer(
                scenario.get("unmet_demand"),
                "unmet_demand",
            )

            if (
                not isinstance(name, str)
                or not name.strip()
            ):
                raise AgentValidationError(
                    "Scenario name is required."
                )

            results.append({
                "name": name,
                "projected_stock": projected_stock,
                "unmet_demand": unmet_demand,
            })

        ranked = sorted(
            results,
            key=lambda item: (
                item["unmet_demand"],
                -item["projected_stock"],
            ),
        )

        return {
            "ranked_scenarios": ranked,
            "preferred_by_defined_metrics": (
                ranked[0]["name"]
            ),
            "comparison_basis": (
                "Lowest unmet demand, then "
                "highest projected stock."
            ),
            "limitations": (
                "Costs, capacity, expiry and "
                "supplier constraints are not scored."
            ),
        }

    def process(
        self,
        request: AgentRequest,
    ) -> dict[str, Any]:
        task = request.task_type

        if task == "create_twin":
            return self._create(request)

        if task == "get_twin":
            with self._lock:
                twin = self._get(
                    request.context.tenant_id,
                    request.payload.get("twin_id"),
                )
                return twin.to_dict()

        if task == "simulate_stock_movement":
            return self._simulate_movement(request)

        if task == "simulate_demand":
            return self._simulate_demand(request)

        if task == "simulate_replenishment":
            return self._simulate_replenishment(request)

        if task == "update_twin_snapshot":
            return self._update_snapshot(request)

        if task == "compare_scenarios":
            return self._compare(request)

        raise AgentValidationError(
            "Unsupported digital twin task."
        )


if __name__ == "__main__":
    from .base_agent import AgentContext

    agent = DigitalTwinAgent()

    context = AgentContext(
        tenant_id="retail_company_001",
        user_id="warehouse_manager_001",
        workflow_id="WF-TWIN-001",
        task_id="TASK-001",
    )

    created = agent.execute(
        AgentRequest(
            task_type="create_twin",
            context=context,
            payload={
                "warehouse_id": "WH-001",
                "capacity_units": 1000,
                "inventory": {
                    "SKU-1001": 80,
                    "SKU-1002": 150,
                },
            },
        )
    )

    print("Created:", created)

    if created["success"]:
        twin_id = created["result"]["twin"]["twin_id"]

        simulated = agent.execute(
            AgentRequest(
                task_type="simulate_demand",
                context=context,
                payload={
                    "twin_id": twin_id,
                    "sku": "SKU-1001",
                    "daily_demand": 25,
                    "horizon_days": 7,
                },
            )
        )

        print("Simulation:", simulated)
