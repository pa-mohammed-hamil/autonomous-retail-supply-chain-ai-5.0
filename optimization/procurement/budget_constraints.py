"""Planned module: budget constraints. Implementation pending."""

"""
ai/optimization/budget_constraints.py

Budget-constrained proposal selection.

Features:
- Total budget
- Category-specific budgets
- Mandatory proposals
- Expected benefit maximization
- Priority scoring
- Selected/rejected proposal reporting

Costs and benefits are in currency units.
Internally converted to integer cents.

No payments or purchase orders are executed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ortools.sat.python import cp_model


@dataclass(frozen=True)
class BudgetProposal:
    proposal_id: str
    category: str
    cost: float
    expected_benefit: float
    priority: int = 1
    mandatory: bool = False

    def __post_init__(self):
        if not self.proposal_id or not self.category:
            raise ValueError(
                "Proposal ID and category required"
            )

        for name in ("cost", "expected_benefit"):
            value = getattr(self, name)

            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"Invalid {name}")

        if (
            isinstance(self.priority, bool)
            or not isinstance(self.priority, int)
            or not 1 <= self.priority <= 10
        ):
            raise ValueError(
                "Priority must be between 1 and 10"
            )


class BudgetConstraintsOptimizer:

    @staticmethod
    def to_cents(amount: float) -> int:
        return round(amount * 100)

    def optimize(
        self,
        proposals: list[BudgetProposal],
        total_budget: float,
        category_budgets: dict[str, float] | None = None,
        max_solve_seconds: float = 10.0,
    ) -> dict:

        if (
            isinstance(total_budget, bool)
            or not math.isfinite(total_budget)
            or total_budget < 0
        ):
            raise ValueError("Invalid total budget")

        if not (
            math.isfinite(max_solve_seconds)
            and max_solve_seconds > 0
        ):
            raise ValueError("Invalid solve time")

        ids = [
            proposal.proposal_id
            for proposal in proposals
        ]

        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate proposal IDs")

        limits = category_budgets or {}

        for category, amount in limits.items():
            if (
                not category
                or isinstance(amount, bool)
                or not math.isfinite(amount)
                or amount < 0
            ):
                raise ValueError(
                    "Invalid category budget"
                )

        model = cp_model.CpModel()

        selected = [
            model.NewBoolVar(
                f"proposal_{index}"
            )
            for index in range(len(proposals))
        ]

        costs = [
            self.to_cents(p.cost)
            for p in proposals
        ]

        benefits = [
            self.to_cents(p.expected_benefit)
            for p in proposals
        ]

        model.Add(
            sum(
                costs[i] * selected[i]
                for i in range(len(proposals))
            )
            <= self.to_cents(total_budget)
        )

        for category, budget in limits.items():
            model.Add(
                sum(
                    costs[i] * selected[i]
                    for i, proposal in enumerate(proposals)
                    if proposal.category == category
                )
                <= self.to_cents(budget)
            )

        for index, proposal in enumerate(proposals):
            if proposal.mandatory:
                model.Add(selected[index] == 1)

        # Maximize estimated net financial benefit.
        # Priority is a tie-breaker, not a substitute
        # for monetary value.
        n = len(proposals)
        tie_break_weight = 10 * n + 1

        model.Maximize(
            sum(
                (
                    (benefits[i] - costs[i])
                    * tie_break_weight
                    + proposals[i].priority
                )
                * selected[i]
                for i in range(n)
            )
        )

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = (
            max_solve_seconds
        )

        status = solver.Solve(model)

        if status not in (
            cp_model.OPTIMAL,
            cp_model.FEASIBLE,
        ):
            return {
                "status": "no_feasible_solution_found",
                "selected_proposals": [],
                "rejected_proposals": [],
                "requires_approval": True,
            }

        chosen = []
        rejected = []

        for index, proposal in enumerate(proposals):
            record = {
                "proposal_id": proposal.proposal_id,
                "category": proposal.category,
                "cost": proposal.cost,
                "expected_benefit": (
                    proposal.expected_benefit
                ),
                "priority": proposal.priority,
                "mandatory": proposal.mandatory,
            }

            if solver.Value(selected[index]):
                chosen.append(record)
            else:
                rejected.append(record)

        total_spend = sum(
            item["cost"]
            for item in chosen
        )

        total_benefit = sum(
            item["expected_benefit"]
            for item in chosen
        )

        return {
            "status": (
                "optimal"
                if status == cp_model.OPTIMAL
                else "feasible"
            ),
            "selected_proposals": chosen,
            "rejected_proposals": rejected,
            "total_budget": total_budget,
            "allocated_budget": round(
                total_spend, 2
            ),
            "remaining_budget": round(
                total_budget - total_spend, 2
            ),
            "estimated_total_benefit": round(
                total_benefit, 2
            ),
            "estimated_net_benefit": round(
                total_benefit - total_spend, 2
            ),
            "requires_approval": True,
            "transactions_executed": False,
        }
