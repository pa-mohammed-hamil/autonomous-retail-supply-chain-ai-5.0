from __future__ import annotations

"""Planned module: agents. Implementation pending."""

# ai/agents/inventory_agent.py


from dataclasses import dataclass
from typing import Any, Protocol


class InventoryReader(Protocol):
    def get_balance(
        self,
        actor: Any,
        warehouse_id: str,
        sku: str,
    ) -> Any:
        ...


@dataclass(frozen=True)
class InventoryAgentResult:
    warehouse_id: str
    sku: str
    on_hand: int
    reserved: int
    available: int
    reorder_point: int
    risk: str
    recommendation: str
    requires_approval: bool


class RetailInventoryAgent:
    """
    Read-only inventory decision agent.

    Uses an authorized inventory service
    to inspect stock and recommend action.

    Does not automatically create orders,
    reserve inventory or transfer stock.
    """

    def __init__(
        self,
        inventory_service: InventoryReader,
    ):
        self.inventory_service = (
            inventory_service
        )

    def analyze(
        self,
        actor: Any,
        warehouse_id: str,
        sku: str,
    ) -> InventoryAgentResult:

        balance = (
            self.inventory_service.get_balance(
                actor,
                warehouse_id,
                sku,
            )
        )

        available = (
            balance.on_hand
            - balance.reserved
        )

        if available <= 0:
            risk = "critical"
            recommendation = (
                "Stock unavailable. "
                "Escalate replenishment review."
            )

        elif available <= (
            balance.safety_stock
        ):
            risk = "high"
            recommendation = (
                "Available stock is at or "
                "below safety stock. "
                "Review replenishment."
            )

        elif available <= (
            balance.reorder_point
        ):
            risk = "medium"
            recommendation = (
                "Available stock is below "
                "the reorder threshold."
            )

        else:
            risk = "low"
            recommendation = (
                "Inventory is within "
                "configured thresholds."
            )

        return InventoryAgentResult(
            warehouse_id=warehouse_id,
            sku=sku,
            on_hand=balance.on_hand,
            reserved=balance.reserved,
            available=available,
            reorder_point=(
                balance.reorder_point
            ),
            risk=risk,
            recommendation=(
                recommendation
            ),
            requires_approval=(
                risk != "low"
            ),
        )
