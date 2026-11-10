"""Planned module: verification agent. Implementation pending."""

"""
File: ai/agents/verification_agent.py
Autonomous Retail Supply Chain AI 5.0

Capabilities:
- verify_inventory_result
- verify_replenishment_result
- verify_purchase_proposal
- verify_evidence
- verify_agent_output

Verification is deterministic and rule-based.
It does not replace authentication or approval.
"""

from __future__ import annotations

import math
from typing import Any

from .base_agent import (
    BaseAgent, AgentRequest, AgentValidationError
)


class VerificationAgent(BaseAgent):

    def __init__(self, working_memory=None):
        super().__init__(
            agent_id="verification_agent",
            name="Retail Agent Verification",
            capabilities={
                "verify_inventory_result",
                "verify_replenishment_result",
                "verify_purchase_proposal",
                "verify_evidence",
                "verify_agent_output",
            },
            working_memory=working_memory,
        )

    @staticmethod
    def _number(value, name):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise AgentValidationError(
                f"Invalid {name}"
            )
        return float(value)

    @staticmethod
    def _integer(value, name):
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
        ):
            raise AgentValidationError(
                f"Invalid {name}"
            )
        return value

    @staticmethod
    def _result(checks, approval_required=False):
        passed = all(checks.values())

        return {
            "verified": passed,
            "status": (
                "rejected"
                if not passed
                else (
                    "pending_approval"
                    if approval_required
                    else "verified"
                )
            ),
            "checks": checks,
            "approval_required": approval_required,
            "approval_granted": False,
        }

    def _inventory(self, p):
        on_hand = self._integer(
            p.get("on_hand"), "on_hand"
        )
        reserved = self._integer(
            p.get("reserved"), "reserved"
        )
        available = self._integer(
            p.get("available"), "available"
        )

        return self._result({
            "reserved_within_stock": reserved <= on_hand,
            "available_matches": (
                available == on_hand - reserved
            ),
        })

    def _replenishment(self, p):
        quantity = self._integer(
            p.get("recommended_order_quantity"),
            "recommended_order_quantity",
        )
        available = self._integer(
            p.get("available_stock"), "available_stock"
        )
        incoming = self._integer(
            p.get("incoming_stock", 0),
            "incoming_stock",
        )
        target = self._integer(
            p.get("target_stock"), "target_stock"
        )
        multiple = self._integer(
            p.get("order_multiple", 1),
            "order_multiple",
        )

        if multiple == 0:
            raise AgentValidationError(
                "order_multiple must be positive"
            )

        required = max(
            0, target - available - incoming
        )

        return self._result(
            {
                "covers_required_quantity": (
                    quantity >= required
                ),
                "valid_order_multiple": (
                    quantity % multiple == 0
                ),
                "no_unnecessary_order": (
                    required > 0 or quantity == 0
                ),
            },
            approval_required=quantity > 0,
        )

    def _purchase(self, p):
        quantity = self._integer(
            p.get("quantity"), "quantity"
        )
        unit_cost = self._number(
            p.get("unit_cost"), "unit_cost"
        )
        total = self._number(
            p.get("estimated_total"),
            "estimated_total",
        )
        shipping = self._number(
            p.get("shipping_cost", 0),
            "shipping_cost",
        )
        budget = self._number(
            p.get("available_budget"),
            "available_budget",
        )

        calculated = quantity * unit_cost + shipping

        return self._result(
            {
                "positive_quantity": quantity > 0,
                "total_matches": math.isclose(
                    calculated,
                    total,
                    rel_tol=1e-9,
                    abs_tol=0.01,
                ),
                "within_budget": total <= budget,
            },
            approval_required=True,
        )

    def _evidence(self, p):
        evidence = p.get("evidence")

        if not isinstance(evidence, list):
            raise AgentValidationError(
                "evidence must be a list"
            )

        valid = (
            len(evidence) > 0
            and all(
                isinstance(item, dict)
                and isinstance(
                    item.get("source_id"), str
                )
                and bool(item["source_id"].strip())
                for item in evidence
            )
        )

        return self._result({
            "evidence_references_present": valid,
        })

    def process(self, request: AgentRequest) -> dict:
        task = request.task_type
        p = request.payload

        if task == "verify_inventory_result":
            return self._inventory(p)

        if task == "verify_replenishment_result":
            return self._replenishment(p)

        if task == "verify_purchase_proposal":
            return self._purchase(p)

        if task == "verify_evidence":
            return self._evidence(p)

        if task == "verify_agent_output":
            output = p.get("output")

            if not isinstance(output, dict):
                raise AgentValidationError(
                    "output must be an object"
                )

            return self._result({
                "output_not_empty": bool(output),
                "has_result_or_status": (
                    "result" in output
                    or "status" in output
                ),
            })

        raise AgentValidationError(
            "Unsupported verification task"
        )
