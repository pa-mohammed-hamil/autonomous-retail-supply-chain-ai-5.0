"""Planned module: working capital optimizer. Implementation pending."""

"""
ai/optimization/working_capital_optimizer.py

Working capital optimization for retail supply chains.

Features:
- Net working capital
- DIO / DSO / DPO
- Cash conversion cycle
- Inventory cash release
- Supplier payment-term scenarios
- Receivables collection scenarios
- Liquidity and operational risk flags
- Scenario comparison

All outputs are recommendations.
No financial transactions are executed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


def finite_nonnegative(value: float, name: str):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(
            f"{name} must be finite and nonnegative"
        )


@dataclass(frozen=True)
class WorkingCapitalInput:
    annual_revenue: float
    annual_cogs: float
    average_inventory_value: float
    accounts_receivable: float
    accounts_payable: float
    cash_balance: float
    other_current_assets: float = 0.0
    other_current_liabilities: float = 0.0
    minimum_cash_reserve: float = 0.0
    annual_inventory_holding_rate: float = 0.20

    def __post_init__(self):
        for name, value in vars(self).items():
            finite_nonnegative(value, name)


@dataclass(frozen=True)
class CapitalScenario:
    name: str
    inventory_reduction_percent: float = 0.0
    receivable_days_reduction: float = 0.0
    payable_days_extension: float = 0.0

    def __post_init__(self):
        if not self.name:
            raise ValueError("Scenario name required")

        if not (
            0 <= self.inventory_reduction_percent <= 100
        ):
            raise ValueError(
                "Inventory reduction must be 0-100%"
            )

        for name in (
            "receivable_days_reduction",
            "payable_days_extension",
        ):
            value = getattr(self, name)
            finite_nonnegative(value, name)


class WorkingCapitalOptimizer:

    DAYS = 365.0

    def analyze(
        self,
        data: WorkingCapitalInput,
    ) -> dict[str, Any]:

        dio = (
            data.average_inventory_value
            / data.annual_cogs
            * self.DAYS
            if data.annual_cogs > 0
            else None
        )

        dso = (
            data.accounts_receivable
            / data.annual_revenue
            * self.DAYS
            if data.annual_revenue > 0
            else None
        )

        dpo = (
            data.accounts_payable
            / data.annual_cogs
            * self.DAYS
            if data.annual_cogs > 0
            else None
        )

        ccc = (
            dio + dso - dpo
            if None not in (dio, dso, dpo)
            else None
        )

        current_assets = (
            data.cash_balance
            + data.average_inventory_value
            + data.accounts_receivable
            + data.other_current_assets
        )

        current_liabilities = (
            data.accounts_payable
            + data.other_current_liabilities
        )

        return {
            "days_inventory_outstanding": (
                round(dio, 2) if dio is not None else None
            ),
            "days_sales_outstanding": (
                round(dso, 2) if dso is not None else None
            ),
            "days_payables_outstanding": (
                round(dpo, 2) if dpo is not None else None
            ),
            "cash_conversion_cycle_days": (
                round(ccc, 2) if ccc is not None else None
            ),
            "net_working_capital": round(
                current_assets - current_liabilities, 2
            ),
            "operating_working_capital": round(
                data.average_inventory_value
                + data.accounts_receivable
                - data.accounts_payable,
                2,
            ),
            "cash_reserve_gap": round(
                max(
                    0,
                    data.minimum_cash_reserve
                    - data.cash_balance,
                ),
                2,
            ),
        }

    def evaluate_scenario(
        self,
        data: WorkingCapitalInput,
        scenario: CapitalScenario,
    ) -> dict:

        baseline = self.analyze(data)

        inventory_release = (
            data.average_inventory_value
            * scenario.inventory_reduction_percent
            / 100
        )

        daily_revenue = (
            data.annual_revenue / self.DAYS
        )

        daily_cogs = (
            data.annual_cogs / self.DAYS
        )

        current_dso = (
            baseline["days_sales_outstanding"]
        )

        current_dpo = (
            baseline["days_payables_outstanding"]
        )

        requested_receivable_release = (
            daily_revenue
            * scenario.receivable_days_reduction
        )

        receivable_release = min(
            data.accounts_receivable,
            requested_receivable_release,
        )

        # Treat extension as a financing scenario,
        # not a unilateral change to supplier terms.
        payable_financing = (
            daily_cogs
            * scenario.payable_days_extension
        )

        new_inventory = (
            data.average_inventory_value
            - inventory_release
        )

        new_receivables = (
            data.accounts_receivable
            - receivable_release
        )

        new_payables = (
            data.accounts_payable
            + payable_financing
        )

        # Simplified cash-release estimate.
        # Excludes tax, discounts, fees and
        # implementation costs.
        estimated_cash_release = (
            inventory_release
            + receivable_release
            + payable_financing
        )

        new_cash = (
            data.cash_balance
            + estimated_cash_release
        )

        projected = WorkingCapitalInput(
            annual_revenue=data.annual_revenue,
            annual_cogs=data.annual_cogs,
            average_inventory_value=new_inventory,
            accounts_receivable=new_receivables,
            accounts_payable=new_payables,
            cash_balance=new_cash,
            other_current_assets=(
                data.other_current_assets
            ),
            other_current_liabilities=(
                data.other_current_liabilities
            ),
            minimum_cash_reserve=(
                data.minimum_cash_reserve
            ),
            annual_inventory_holding_rate=(
                data.annual_inventory_holding_rate
            ),
        )

        projected_metrics = self.analyze(
            projected
        )

        annual_holding_savings = (
            inventory_release
            * data.annual_inventory_holding_rate
        )

        warnings = []

        if scenario.inventory_reduction_percent > 0:
            warnings.append(
                "Verify SKU-level safety stock and "
                "service levels before reducing inventory."
            )

        if scenario.payable_days_extension > 0:
            warnings.append(
                "Supplier approval and contractual "
                "payment terms must be verified."
            )

        if (
            current_dso is not None
            and scenario.receivable_days_reduction
            > current_dso
        ):
            warnings.append(
                "Receivable reduction capped at "
                "outstanding receivables."
            )

        return {
            "scenario": scenario.name,
            "baseline": baseline,
            "projected": projected_metrics,
            "inventory_cash_release": round(
                inventory_release, 2
            ),
            "receivable_cash_release": round(
                receivable_release, 2
            ),
            "payable_financing": round(
                payable_financing, 2
            ),
            "estimated_total_cash_release": round(
                estimated_cash_release, 2
            ),
            "estimated_annual_holding_savings": round(
                annual_holding_savings, 2
            ),
            "projected_cash_balance": round(
                new_cash, 2
            ),
            "supplier_terms_verified": False,
            "inventory_service_levels_verified": False,
            "warnings": warnings,
            "requires_approval": True,
            "transactions_executed": False,
        }

    def compare_scenarios(
        self,
        data: WorkingCapitalInput,
        scenarios: list[CapitalScenario],
    ) -> list[dict]:

        results = [
            self.evaluate_scenario(data, scenario)
            for scenario in scenarios
        ]

        return sorted(
            results,
            key=lambda item: (
                -item["estimated_total_cash_release"],
                item["scenario"],
            ),
        )
