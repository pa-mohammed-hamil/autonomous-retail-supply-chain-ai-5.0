from __future__ import annotations

"""Planned module: financial service. Implementation pending."""

"""
backend/services/financial_service.py

Autonomous Retail Supply Chain AI 5.0

Retail Financial Intelligence Service

Python 3.10+
Dependencies: standard library only.

Features:
- Multi-tenant financial records
- Role-based access
- Immutable transaction records
- Idempotent transaction creation
- Revenue and refund tracking
- Cost of goods sold
- Operating expenses
- Supplier payments
- Cash-flow summary
- Profit and loss report
- Budget variance monitoring
- Financial risk indicators
- JSON export

Amounts use Decimal and INR by
default.

Reference implementation:
- In-memory records
- No actual bank/payment transfers
- No full double-entry general ledger
- No tax accounting
- No production-grade audit database

Production requires accounting
reconciliation, durable persistence,
and independently verified approvals.
"""


import json
import threading
import uuid

from dataclasses import (
    asdict,
    dataclass,
)
from datetime import date
from decimal import (
    Decimal,
    InvalidOperation,
    ROUND_HALF_UP,
)
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


MONEY = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(
            "Invalid monetary amount"
        )

    try:
        amount = Decimal(str(value))
    except (
        InvalidOperation,
        ValueError,
    ) as exc:
        raise ValueError(
            "Invalid monetary amount"
        ) from exc

    if not amount.is_finite():
        raise ValueError(
            "Amount must be finite"
        )

    return amount.quantize(
        MONEY,
        rounding=ROUND_HALF_UP,
    )


class TransactionType(str, Enum):
    SALE = "sale"
    REFUND = "refund"
    COGS = "cogs"
    OPERATING_EXPENSE = (
        "operating_expense"
    )
    SUPPLIER_PAYMENT = (
        "supplier_payment"
    )
    OTHER_INCOME = "other_income"
    OTHER_EXPENSE = "other_expense"


class FinancialRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class FinanceActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    is_active: bool = True


@dataclass(frozen=True)
class FinancialTransaction:
    transaction_id: str
    tenant_id: str
    transaction_date: str
    transaction_type: TransactionType
    amount: Decimal
    currency: str
    category: str
    reference_id: str
    description: str
    created_by: str


@dataclass(frozen=True)
class FinancialBudget:
    tenant_id: str
    period: str
    category: str
    allocated_amount: Decimal
    currency: str


@dataclass(frozen=True)
class ProfitLossReport:
    tenant_id: str
    start_date: str
    end_date: str
    currency: str

    gross_sales: Decimal
    refunds: Decimal
    net_revenue: Decimal

    cost_of_goods_sold: Decimal
    gross_profit: Decimal
    gross_margin_pct: Decimal

    operating_expenses: Decimal
    other_income: Decimal
    other_expenses: Decimal

    operating_profit: Decimal
    net_profit_before_tax: Decimal
    net_margin_pct: Decimal


class RetailFinancialService:
    WRITER_ROLES = frozenset({
        "finance_writer",
        "finance_manager",
        "corporate_admin",
    })

    READER_ROLES = frozenset({
        "finance_analyst",
        "finance_manager",
        "corporate_admin",
    })

    MANAGER_ROLES = frozenset({
        "finance_manager",
        "corporate_admin",
    })

    def __init__(
        self,
        tenant_id: str,
        currency: str = "INR",
    ):
        if (
            not isinstance(tenant_id, str)
            or not tenant_id.strip()
        ):
            raise ValueError(
                "tenant_id is required"
            )

        if (
            not isinstance(currency, str)
            or len(currency) != 3
            or not currency.isalpha()
        ):
            raise ValueError(
                "Currency must be ISO-like "
                "three-letter code"
            )

        self.tenant_id = tenant_id
        self.currency = currency.upper()

        self._lock = threading.RLock()

        self._transactions: dict[
            str, FinancialTransaction
        ] = {}

        self._references: dict[
            tuple[str, TransactionType, str],
            str,
        ] = {}

        self._budgets: dict[
            tuple[str, str],
            FinancialBudget,
        ] = {}

    def _authorize(
        self,
        actor: FinanceActor,
        roles: frozenset[str],
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id
            != self.tenant_id
            or not actor.user_id.strip()
            or not (
                actor.roles & roles
            )
        ):
            raise PermissionError(
                "Financial access denied"
            )

    @staticmethod
    def _validate_date(
        value: str,
    ) -> None:
        date.fromisoformat(
            value
        )

    def record_transaction(
        self,
        actor: FinanceActor,
        transaction_type: TransactionType,
        amount: Any,
        transaction_date: str,
        category: str,
        reference_id: str,
        description: str = "",
    ) -> FinancialTransaction:
        self._authorize(
            actor,
            self.WRITER_ROLES,
        )

        self._validate_date(
            transaction_date
        )

        amount = money(
            amount
        )

        if amount <= ZERO:
            raise ValueError(
                "Transaction amount "
                "must be positive"
            )

        if (
            not category.strip()
            or not reference_id.strip()
        ):
            raise ValueError(
                "Category and reference "
                "ID are required"
            )

        if (
            len(category) > 100
            or len(reference_id) > 200
            or len(description) > 1000
        ):
            raise ValueError(
                "Transaction field too long"
            )

        key = (
            self.tenant_id,
            transaction_type,
            reference_id,
        )

        with self._lock:
            existing_id = (
                self._references.get(
                    key
                )
            )

            if existing_id:
                existing = (
                    self._transactions[
                        existing_id
                    ]
                )

                if (
                    existing.amount != amount
                    or existing.transaction_date
                    != transaction_date
                    or existing.category
                    != category
                    or existing.description
                    != description
                ):
                    raise ValueError(
                        "Reference ID already used "
                        "with different transaction"
                    )

                return existing

            transaction = (
                FinancialTransaction(
                    transaction_id=str(
                        uuid.uuid4()
                    ),
                    tenant_id=self.tenant_id,
                    transaction_date=(
                        transaction_date
                    ),
                    transaction_type=(
                        transaction_type
                    ),
                    amount=amount,
                    currency=self.currency,
                    category=category,
                    reference_id=reference_id,
                    description=description,
                    created_by=actor.user_id,
                )
            )

            self._transactions[
                transaction.transaction_id
            ] = transaction

            self._references[
                key
            ] = transaction.transaction_id

            return transaction

    def list_transactions(
        self,
        actor: FinanceActor,
        start_date: str | None = None,
        end_date: str | None = None,
        transaction_type: (
            TransactionType | None
        ) = None,
    ) -> list[FinancialTransaction]:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        if start_date:
            self._validate_date(
                start_date
            )

        if end_date:
            self._validate_date(
                end_date
            )

        if (
            start_date
            and end_date
            and start_date > end_date
        ):
            raise ValueError(
                "Invalid date range"
            )

        with self._lock:
            results = []

            for transaction in (
                self._transactions.values()
            ):
                if (
                    start_date
                    and transaction.transaction_date
                    < start_date
                ):
                    continue

                if (
                    end_date
                    and transaction.transaction_date
                    > end_date
                ):
                    continue

                if (
                    transaction_type
                    and transaction.transaction_type
                    != transaction_type
                ):
                    continue

                results.append(
                    transaction
                )

            return sorted(
                results,
                key=lambda item: (
                    item.transaction_date,
                    item.transaction_id,
                ),
            )

    def profit_loss(
        self,
        actor: FinanceActor,
        start_date: str,
        end_date: str,
    ) -> ProfitLossReport:
        records = self.list_transactions(
            actor,
            start_date,
            end_date,
        )

        totals = {
            kind: ZERO
            for kind in TransactionType
        }

        for item in records:
            totals[
                item.transaction_type
            ] += item.amount

        gross_sales = totals[
            TransactionType.SALE
        ]

        refunds = totals[
            TransactionType.REFUND
        ]

        net_revenue = (
            gross_sales - refunds
        )

        cogs = totals[
            TransactionType.COGS
        ]

        gross_profit = (
            net_revenue - cogs
        )

        operating_expenses = totals[
            TransactionType.OPERATING_EXPENSE
        ]

        other_income = totals[
            TransactionType.OTHER_INCOME
        ]

        other_expenses = totals[
            TransactionType.OTHER_EXPENSE
        ]

        operating_profit = (
            gross_profit
            - operating_expenses
        )

        net_profit = (
            operating_profit
            + other_income
            - other_expenses
        )

        gross_margin = (
            gross_profit
            / net_revenue * 100
            if net_revenue != ZERO
            else ZERO
        )

        net_margin = (
            net_profit
            / net_revenue * 100
            if net_revenue != ZERO
            else ZERO
        )

        return ProfitLossReport(
            tenant_id=self.tenant_id,
            start_date=start_date,
            end_date=end_date,
            currency=self.currency,
            gross_sales=gross_sales,
            refunds=refunds,
            net_revenue=net_revenue,
            cost_of_goods_sold=cogs,
            gross_profit=gross_profit,
            gross_margin_pct=(
                gross_margin.quantize(
                    MONEY
                )
            ),
            operating_expenses=(
                operating_expenses
            ),
            other_income=other_income,
            other_expenses=other_expenses,
            operating_profit=operating_profit,
            net_profit_before_tax=net_profit,
            net_margin_pct=(
                net_margin.quantize(
                    MONEY
                )
            ),
        )

    def cash_flow_summary(
        self,
        actor: FinanceActor,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        records = self.list_transactions(
            actor,
            start_date,
            end_date,
        )

        inflow_types = {
            TransactionType.SALE,
            TransactionType.OTHER_INCOME,
        }

        outflow_types = {
            TransactionType.REFUND,
            TransactionType.SUPPLIER_PAYMENT,
            TransactionType.OPERATING_EXPENSE,
            TransactionType.OTHER_EXPENSE,
        }

        inflows = sum(
            (
                item.amount
                for item in records
                if item.transaction_type
                in inflow_types
            ),
            ZERO,
        )

        outflows = sum(
            (
                item.amount
                for item in records
                if item.transaction_type
                in outflow_types
            ),
            ZERO,
        )

        return {
            "tenant_id": self.tenant_id,
            "currency": self.currency,
            "start_date": start_date,
            "end_date": end_date,
            "cash_inflows": inflows,
            "cash_outflows": outflows,
            "net_cash_flow": (
                inflows - outflows
            ),
            "note": (
                "Cash-basis proxy. Transaction "
                "types are assumed paid."
            ),
        }

    def set_budget(
        self,
        actor: FinanceActor,
        period: str,
        category: str,
        allocated_amount: Any,
    ) -> FinancialBudget:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
        )

        if (
            len(period) != 7
            or period[4] != "-"
        ):
            raise ValueError(
                "Period must be YYYY-MM"
            )

        year, month = map(
            int,
            period.split("-"),
        )

        date(
            year, month, 1
        )

        if not category.strip():
            raise ValueError(
                "Budget category required"
            )

        allocated = money(
            allocated_amount
        )

        if allocated < ZERO:
            raise ValueError(
                "Budget cannot be negative"
            )

        budget = FinancialBudget(
            tenant_id=self.tenant_id,
            period=period,
            category=category,
            allocated_amount=allocated,
            currency=self.currency,
        )

        with self._lock:
            self._budgets[
                (period, category)
            ] = budget

        return budget

    def budget_variance(
        self,
        actor: FinanceActor,
        period: str,
        category: str,
    ) -> dict[str, Any]:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        with self._lock:
            budget = (
                self._budgets.get(
                    (period, category)
                )
            )

        if budget is None:
            raise KeyError(
                "Budget not found"
            )

        records = self.list_transactions(
            actor,
            start_date=f"{period}-01",
            end_date=f"{period}-31",
        )

        actual = sum(
            (
                item.amount
                for item in records
                if (
                    item.category == category
                    and item.transaction_type
                    in {
                        TransactionType.OPERATING_EXPENSE,
                        TransactionType.OTHER_EXPENSE,
                    }
                )
            ),
            ZERO,
        )

        variance = (
            budget.allocated_amount
            - actual
        )

        utilization = (
            actual
            / budget.allocated_amount
            * 100
            if budget.allocated_amount > ZERO
            else None
        )

        return {
            "period": period,
            "category": category,
            "currency": self.currency,
            "budget": (
                budget.allocated_amount
            ),
            "actual": actual,
            "variance": variance,
            "utilization_pct": (
                utilization.quantize(
                    MONEY
                )
                if utilization is not None
                else None
            ),
            "over_budget": (
                actual
                > budget.allocated_amount
            ),
        }

    def financial_risk(
        self,
        actor: FinanceActor,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        report = self.profit_loss(
            actor,
            start_date,
            end_date,
        )

        indicators = []

        if report.net_revenue <= ZERO:
            indicators.append(
                "No positive net revenue"
            )

        if report.net_profit_before_tax < ZERO:
            indicators.append(
                "Operating period is loss-making"
            )

        if report.gross_margin_pct < Decimal(
            "10"
        ):
            indicators.append(
                "Low gross margin"
            )

        if (
            report.net_revenue > ZERO
            and report.operating_expenses
            > report.net_revenue
        ):
            indicators.append(
                "Operating expenses exceed revenue"
            )

        if (
            report.net_profit_before_tax
            < ZERO
            and report.net_revenue <= ZERO
        ):
            risk = FinancialRisk.CRITICAL

        elif report.net_profit_before_tax < ZERO:
            risk = FinancialRisk.HIGH

        elif indicators:
            risk = FinancialRisk.MEDIUM

        else:
            risk = FinancialRisk.LOW

        return {
            "tenant_id": self.tenant_id,
            "risk_level": risk.value,
            "indicators": indicators,
            "net_profit_before_tax": (
                report.net_profit_before_tax
            ),
            "gross_margin_pct": (
                report.gross_margin_pct
            ),
        }

    def export_json(
        self,
        actor: FinanceActor,
        output_path: str | Path,
    ) -> Path:
        self._authorize(
            actor,
            self.MANAGER_ROLES,
        )

        with self._lock:
            records = [
                asdict(item)
                for item in (
                    self._transactions.values()
                )
            ]

        output = Path(
            output_path
        )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            json.dumps(
                records,
                indent=2,
                default=str,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return output


if __name__ == "__main__":
    service = RetailFinancialService(
        tenant_id="demo",
        currency="INR",
    )

    manager = FinanceActor(
        user_id="finance-manager",
        tenant_id="demo",
        roles=frozenset({
            "finance_manager",
        }),
    )

    entries = [
        (
            TransactionType.SALE,
            "150000",
            "sales",
            "SALE001",
        ),
        (
            TransactionType.REFUND,
            "5000",
            "refunds",
            "REF001",
        ),
        (
            TransactionType.COGS,
            "85000",
            "inventory",
            "COGS001",
        ),
        (
            TransactionType.OPERATING_EXPENSE,
            "20000",
            "logistics",
            "EXP001",
        ),
        (
            TransactionType.OPERATING_EXPENSE,
            "10000",
            "warehouse",
            "EXP002",
        ),
        (
            TransactionType.SUPPLIER_PAYMENT,
            "40000",
            "supplier",
            "PAY001",
        ),
    ]

    for (
        kind,
        amount,
        category,
        reference,
    ) in entries:
        service.record_transaction(
            actor=manager,
            transaction_type=kind,
            amount=amount,
            transaction_date="2026-10-27",
            category=category,
            reference_id=reference,
        )

    service.set_budget(
        actor=manager,
        period="2026-10",
        category="logistics",
        allocated_amount="25000",
    )

    report = service.profit_loss(
        manager,
        "2026-10-01",
        "2026-10-31",
    )

    print(
        json.dumps(
            asdict(report),
            indent=2,
            default=str,
        )
    )

    print(
        service.budget_variance(
            manager,
            "2026-10",
            "logistics",
        )
    )

    print(
        service.financial_risk(
            manager,
            "2026-10-01",
            "2026-10-31",
        )
    )
