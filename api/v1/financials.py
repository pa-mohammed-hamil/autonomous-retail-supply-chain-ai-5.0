from __future__ import annotations

"""Planned module: financials. Implementation pending."""

"""
backend/financials.py

Autonomous Retail Supply Chain AI 5.0
Financial Intelligence and Management API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Revenue and expense recording
    - Supplier payment tracking
    - Warehouse financial reporting
    - Budget planning
    - Budget variance analysis
    - Profitability metrics
    - Financial KPI dashboards
    - Decimal-based money calculations
    - Tenant and warehouse isolation
    - Idempotent transaction creation
    - Optimistic concurrency
    - Immutable transaction records
    - Bounded in-memory storage

IMPORTANT:
    This is a financial analytics prototype,
    not a general ledger or payment processor.

    It does not transfer funds, execute payments,
    calculate taxes, or produce audited statements.

    Production systems require:
        - PostgreSQL
        - Double-entry accounting
        - Accounting period controls
        - Reconciliation
        - Audit logs
        - Approved adjustments
        - Currency and tax policies
        - Transactional outbox
"""


import asyncio
import hashlib
import json
import secrets

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from backend.permissions import (
    CurrentPrincipal,
    Permission,
    Principal,
    ResourceContext,
    permission_engine,
)


# ============================================================
# CONFIGURATION
# ============================================================

API_PREFIX = "/api/v1/financials"

MAX_TRANSACTIONS_PER_TENANT = 100_000
MAX_BUDGETS_PER_TENANT = 10_000
MAX_IDEMPOTENCY_KEYS = 150_000
MAX_LIST_LIMIT = 200

MONEY_QUANTUM = Decimal("0.01")
MAX_MONEY = Decimal("999999999999.99")


# ============================================================
# ENUMS
# ============================================================

class FinancialTransactionType(str, Enum):
    REVENUE = "revenue"
    EXPENSE = "expense"


class FinancialCategory(str, Enum):
    PRODUCT_SALES = "product_sales"
    SERVICE_REVENUE = "service_revenue"
    OTHER_REVENUE = "other_revenue"

    INVENTORY_PURCHASE = "inventory_purchase"
    SUPPLIER_PAYMENT = "supplier_payment"
    TRANSPORTATION = "transportation"
    WAREHOUSE_RENT = "warehouse_rent"
    UTILITIES = "utilities"
    MAINTENANCE = "maintenance"
    LABOR = "labor"
    PACKAGING = "packaging"
    SOFTWARE = "software"
    OTHER_EXPENSE = "other_expense"


class FinancialTransactionStatus(str, Enum):
    POSTED = "posted"
    REVERSED = "reversed"


class BudgetStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    ARCHIVED = "archived"


class BudgetPeriod(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


REVENUE_CATEGORIES = {
    FinancialCategory.PRODUCT_SALES,
    FinancialCategory.SERVICE_REVENUE,
    FinancialCategory.OTHER_REVENUE,
}

EXPENSE_CATEGORIES = (
    set(FinancialCategory) - REVENUE_CATEGORIES
)


# ============================================================
# REQUEST MODELS
# ============================================================

class FinancialTransactionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    transaction_type: FinancialTransactionType

    category: FinancialCategory

    amount: Decimal = Field(
        gt=0,
        le=MAX_MONEY,
        max_digits=14,
        decimal_places=2,
    )

    currency: str = Field(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    )

    transaction_date: date

    description: str = Field(
        min_length=3,
        max_length=500,
    )

    supplier_id: str | None = Field(
        default=None,
        max_length=128,
    )

    order_id: str | None = Field(
        default=None,
        max_length=128,
    )

    invoice_id: str | None = Field(
        default=None,
        max_length=128,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_category(self):

        if (
            self.transaction_type
            == FinancialTransactionType.REVENUE
            and self.category not in REVENUE_CATEGORIES
        ):
            raise ValueError(
                "Revenue transaction requires revenue category"
            )

        if (
            self.transaction_type
            == FinancialTransactionType.EXPENSE
            and self.category not in EXPENSE_CATEGORIES
        ):
            raise ValueError(
                "Expense transaction requires expense category"
            )

        return self


class TransactionReverseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)

    reason: str = Field(
        min_length=5,
        max_length=500,
    )


class BudgetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: str = Field(
        min_length=1,
        max_length=128,
    )

    name: str = Field(
        min_length=3,
        max_length=150,
    )

    period: BudgetPeriod

    start_date: date
    end_date: date

    category: FinancialCategory

    allocated_amount: Decimal = Field(
        ge=0,
        le=MAX_MONEY,
        max_digits=14,
        decimal_places=2,
    )

    currency: str = Field(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_dates(self):

        if self.end_date < self.start_date:
            raise ValueError(
                "Budget end date must follow start date"
            )

        if self.category not in EXPENSE_CATEGORIES:
            raise ValueError(
                "Budgets currently support expense categories"
            )

        return self


class BudgetApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


# ============================================================
# RESPONSE MODELS
# ============================================================

class FinancialTransactionResponse(BaseModel):
    transaction_id: str

    warehouse_id: str

    transaction_type: FinancialTransactionType
    category: FinancialCategory

    amount: Decimal
    currency: str

    transaction_date: date
    description: str

    supplier_id: str | None
    order_id: str | None
    invoice_id: str | None

    status: FinancialTransactionStatus

    reversed_at: datetime | None
    reversal_reason: str | None

    version: int

    created_by: str
    created_at: datetime


class BudgetResponse(BaseModel):
    budget_id: str

    warehouse_id: str

    name: str
    period: BudgetPeriod

    start_date: date
    end_date: date

    category: FinancialCategory

    allocated_amount: Decimal
    currency: str

    status: BudgetStatus
    version: int

    created_by: str
    approved_by: str | None

    created_at: datetime
    approved_at: datetime | None


class FinancialKPIResponse(BaseModel):
    warehouse_id: str
    currency: str

    start_date: date
    end_date: date

    total_revenue: Decimal
    total_expenses: Decimal
    operating_result: Decimal

    operating_margin_percent: float | None

    transaction_count: int
    revenue_transaction_count: int
    expense_transaction_count: int

    expense_breakdown: dict[str, Decimal]


class BudgetVarianceResponse(BaseModel):
    budget_id: str

    warehouse_id: str
    category: FinancialCategory

    allocated_amount: Decimal
    actual_expenses: Decimal

    remaining_budget: Decimal
    variance_amount: Decimal

    utilization_percent: float | None

    over_budget: bool
    currency: str


class FinancialSummaryResponse(BaseModel):
    warehouse_id: str
    currency: str

    total_revenue: Decimal
    total_expenses: Decimal
    operating_result: Decimal

    total_transactions: int
    active_budgets: int


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass
class FinancialTransactionRecord:
    transaction_id: str
    tenant_id: str
    warehouse_id: str

    transaction_type: FinancialTransactionType
    category: FinancialCategory

    amount: Decimal
    currency: str

    transaction_date: date
    description: str

    supplier_id: str | None
    order_id: str | None
    invoice_id: str | None

    created_by: str

    status: FinancialTransactionStatus = (
        FinancialTransactionStatus.POSTED
    )

    version: int = 1

    created_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    reversed_at: datetime | None = None
    reversal_reason: str | None = None


@dataclass
class BudgetRecord:
    budget_id: str
    tenant_id: str
    warehouse_id: str

    name: str
    period: BudgetPeriod

    start_date: date
    end_date: date

    category: FinancialCategory

    allocated_amount: Decimal
    currency: str

    created_by: str

    status: BudgetStatus = BudgetStatus.DRAFT
    version: int = 1

    created_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    approved_by: str | None = None
    approved_at: datetime | None = None


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM)


def fingerprint(
    operation: str,
    payload: BaseModel,
) -> str:

    canonical = json.dumps(
        {
            "operation": operation,
            "payload": payload.model_dump(
                mode="json",
                exclude={"source_request_id"},
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def require_financial_access(
    principal: Principal,
    warehouse_id: str,
    *,
    write: bool,
) -> None:

    # FINANCE_WRITE must exist in
    # backend.permissions.Permission.
    permission = (
        Permission.FINANCE_WRITE
        if write
        else Permission.FINANCE_READ
    )

    decision = permission_engine.evaluate(
        principal,
        permission,
        ResourceContext(
            tenant_id=principal.tenant_id,
            warehouse_id=warehouse_id,
        ),
    )

    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail="Financial access denied",
        )

    allowed = principal.allowed_warehouse_ids

    if (
        allowed is not None
        and warehouse_id not in allowed
    ):
        raise HTTPException(
            status_code=403,
            detail="Warehouse access denied",
        )


def to_transaction_response(
    record: FinancialTransactionRecord,
) -> FinancialTransactionResponse:

    return FinancialTransactionResponse(
        transaction_id=record.transaction_id,
        warehouse_id=record.warehouse_id,
        transaction_type=record.transaction_type,
        category=record.category,
        amount=record.amount,
        currency=record.currency,
        transaction_date=record.transaction_date,
        description=record.description,
        supplier_id=record.supplier_id,
        order_id=record.order_id,
        invoice_id=record.invoice_id,
        status=record.status,
        reversed_at=record.reversed_at,
        reversal_reason=record.reversal_reason,
        version=record.version,
        created_by=record.created_by,
        created_at=record.created_at,
    )


def to_budget_response(
    record: BudgetRecord,
) -> BudgetResponse:

    return BudgetResponse(
        budget_id=record.budget_id,
        warehouse_id=record.warehouse_id,
        name=record.name,
        period=record.period,
        start_date=record.start_date,
        end_date=record.end_date,
        category=record.category,
        allocated_amount=record.allocated_amount,
        currency=record.currency,
        status=record.status,
        version=record.version,
        created_by=record.created_by,
        approved_by=record.approved_by,
        created_at=record.created_at,
        approved_at=record.approved_at,
    )


# ============================================================
# FINANCIAL STORE
# ============================================================

class FinancialStore:

    def __init__(self):

        self._transactions: dict[
            str,
            FinancialTransactionRecord,
        ] = {}

        self._budgets: dict[
            str,
            BudgetRecord,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self._lock = asyncio.Lock()

    def _get_transaction(
        self,
        principal: Principal,
        transaction_id: str,
        *,
        write: bool,
    ) -> FinancialTransactionRecord:

        record = self._transactions.get(
            transaction_id
        )

        if (
            record is None
            or record.tenant_id
            != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Financial transaction not found",
            )

        require_financial_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    def _get_budget(
        self,
        principal: Principal,
        budget_id: str,
        *,
        write: bool,
    ) -> BudgetRecord:

        record = self._budgets.get(
            budget_id
        )

        if (
            record is None
            or record.tenant_id
            != principal.tenant_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Budget not found",
            )

        require_financial_access(
            principal,
            record.warehouse_id,
            write=write,
        )

        return record

    def _check_idempotency(
        self,
        key: tuple[str, str, str],
        request_hash: str,
    ) -> str | None:

        previous = self._idempotency.get(
            key
        )

        if previous is None:
            return None

        old_hash, record_id = previous

        if old_hash != request_hash:
            raise HTTPException(
                status_code=409,
                detail="Idempotency conflict",
            )

        return record_id

    async def create_transaction(
        self,
        *,
        principal: Principal,
        payload: FinancialTransactionCreate,
    ) -> FinancialTransactionResponse:

        require_financial_access(
            principal,
            payload.warehouse_id,
            write=True,
        )

        if payload.transaction_date > date.today():
            raise HTTPException(
                status_code=422,
                detail="Future posted transactions are not allowed",
            )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = fingerprint(
            "transaction",
            payload,
        )

        async with self._lock:

            existing_id = self._check_idempotency(
                key,
                request_hash,
            )

            if existing_id is not None:
                return to_transaction_response(
                    self._get_transaction(
                        principal,
                        existing_id,
                        write=False,
                    )
                )

            tenant_count = sum(
                record.tenant_id == principal.tenant_id
                for record in self._transactions.values()
            )

            if (
                tenant_count >= MAX_TRANSACTIONS_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Financial transaction capacity reached",
                )

            record = FinancialTransactionRecord(
                transaction_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                transaction_type=payload.transaction_type,
                category=payload.category,
                amount=money(payload.amount),
                currency=payload.currency,
                transaction_date=payload.transaction_date,
                description=payload.description.strip(),
                supplier_id=payload.supplier_id,
                order_id=payload.order_id,
                invoice_id=payload.invoice_id,
                created_by=principal.principal_id,
            )

            self._transactions[
                record.transaction_id
            ] = record

            self._idempotency[key] = (
                request_hash,
                record.transaction_id,
            )

            return to_transaction_response(
                record
            )

    async def get_transaction(
        self,
        *,
        principal: Principal,
        transaction_id: str,
    ) -> FinancialTransactionResponse:

        async with self._lock:

            record = self._get_transaction(
                principal,
                transaction_id,
                write=False,
            )

            return to_transaction_response(
                record
            )

    async def reverse_transaction(
        self,
        *,
        principal: Principal,
        transaction_id: str,
        payload: TransactionReverseRequest,
    ) -> FinancialTransactionResponse:

        async with self._lock:

            record = self._get_transaction(
                principal,
                transaction_id,
                write=True,
            )

            if record.version != payload.expected_version:
                raise HTTPException(
                    status_code=409,
                    detail="Transaction version conflict",
                )

            if (
                record.status
                == FinancialTransactionStatus.REVERSED
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Transaction already reversed",
                )

            record.status = (
                FinancialTransactionStatus.REVERSED
            )

            record.reversed_at = utc_now()
            record.reversal_reason = (
                payload.reason.strip()
            )

            record.version += 1

            return to_transaction_response(
                record
            )

    async def list_transactions(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
        currency: str,
        start_date: date | None,
        end_date: date | None,
        limit: int,
    ) -> list[FinancialTransactionResponse]:

        require_financial_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._transactions.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and record.warehouse_id
                    == warehouse_id
                    and record.currency == currency
                    and (
                        start_date is None
                        or record.transaction_date
                        >= start_date
                    )
                    and (
                        end_date is None
                        or record.transaction_date
                        <= end_date
                    )
                )
            ]

            records.sort(
                key=lambda item: (
                    item.transaction_date,
                    item.created_at,
                ),
                reverse=True,
            )

            return [
                to_transaction_response(record)
                for record in records[:limit]
            ]

    async def create_budget(
        self,
        *,
        principal: Principal,
        payload: BudgetCreate,
    ) -> BudgetResponse:

        require_financial_access(
            principal,
            payload.warehouse_id,
            write=True,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        request_hash = fingerprint(
            "budget",
            payload,
        )

        async with self._lock:

            existing_id = self._check_idempotency(
                key,
                request_hash,
            )

            if existing_id is not None:
                return to_budget_response(
                    self._get_budget(
                        principal,
                        existing_id,
                        write=False,
                    )
                )

            tenant_count = sum(
                record.tenant_id == principal.tenant_id
                for record in self._budgets.values()
            )

            if (
                tenant_count >= MAX_BUDGETS_PER_TENANT
                or len(self._idempotency)
                >= MAX_IDEMPOTENCY_KEYS
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Budget capacity reached",
                )

            record = BudgetRecord(
                budget_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                warehouse_id=payload.warehouse_id,
                name=payload.name.strip(),
                period=payload.period,
                start_date=payload.start_date,
                end_date=payload.end_date,
                category=payload.category,
                allocated_amount=money(
                    payload.allocated_amount
                ),
                currency=payload.currency,
                created_by=principal.principal_id,
            )

            self._budgets[
                record.budget_id
            ] = record

            self._idempotency[key] = (
                request_hash,
                record.budget_id,
            )

            return to_budget_response(
                record
            )

    async def approve_budget(
        self,
        *,
        principal: Principal,
        budget_id: str,
        payload: BudgetApprovalRequest,
    ) -> BudgetResponse:

        async with self._lock:

            record = self._get_budget(
                principal,
                budget_id,
                write=True,
            )

            if record.version != payload.expected_version:
                raise HTTPException(
                    status_code=409,
                    detail="Budget version conflict",
                )

            if record.status != BudgetStatus.DRAFT:
                raise HTTPException(
                    status_code=409,
                    detail="Only draft budgets can be approved",
                )

            if record.created_by == principal.principal_id:
                raise HTTPException(
                    status_code=403,
                    detail="Budget creator cannot self-approve",
                )

            # Production:
            # Require a dedicated FINANCE_APPROVE
            # permission and approval workflow.

            record.status = BudgetStatus.APPROVED
            record.approved_by = principal.principal_id
            record.approved_at = utc_now()
            record.version += 1

            return to_budget_response(
                record
            )

    async def get_budget(
        self,
        *,
        principal: Principal,
        budget_id: str,
    ) -> BudgetResponse:

        async with self._lock:

            record = self._get_budget(
                principal,
                budget_id,
                write=False,
            )

            return to_budget_response(
                record
            )

    async def list_budgets(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
        currency: str,
        limit: int,
    ) -> list[BudgetResponse]:

        require_financial_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            records = [
                record
                for record in self._budgets.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and record.warehouse_id
                    == warehouse_id
                    and record.currency == currency
                )
            ]

            records.sort(
                key=lambda item: item.created_at,
                reverse=True,
            )

            return [
                to_budget_response(record)
                for record in records[:limit]
            ]

    async def financial_kpis(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
        currency: str,
        start_date: date,
        end_date: date,
    ) -> FinancialKPIResponse:

        require_financial_access(
            principal,
            warehouse_id,
            write=False,
        )

        if end_date < start_date:
            raise HTTPException(
                status_code=422,
                detail="Invalid reporting date range",
            )

        async with self._lock:

            records = [
                record
                for record in self._transactions.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and record.warehouse_id
                    == warehouse_id
                    and record.currency == currency
                    and record.status
                    == FinancialTransactionStatus.POSTED
                    and start_date
                    <= record.transaction_date
                    <= end_date
                )
            ]

            revenue = sum(
                (
                    record.amount
                    for record in records
                    if record.transaction_type
                    == FinancialTransactionType.REVENUE
                ),
                Decimal("0"),
            )

            expenses = sum(
                (
                    record.amount
                    for record in records
                    if record.transaction_type
                    == FinancialTransactionType.EXPENSE
                ),
                Decimal("0"),
            )

            breakdown = {}

            for record in records:

                if (
                    record.transaction_type
                    != FinancialTransactionType.EXPENSE
                ):
                    continue

                key = record.category.value

                breakdown[key] = (
                    breakdown.get(
                        key,
                        Decimal("0"),
                    )
                    + record.amount
                )

            operating_result = (
                revenue - expenses
            )

            margin = (
                float(
                    operating_result / revenue * 100
                )
                if revenue > 0
                else None
            )

            return FinancialKPIResponse(
                warehouse_id=warehouse_id,
                currency=currency,
                start_date=start_date,
                end_date=end_date,
                total_revenue=money(revenue),
                total_expenses=money(expenses),
                operating_result=money(
                    operating_result
                ),
                operating_margin_percent=(
                    round(margin, 2)
                    if margin is not None
                    else None
                ),
                transaction_count=len(records),
                revenue_transaction_count=sum(
                    record.transaction_type
                    == FinancialTransactionType.REVENUE
                    for record in records
                ),
                expense_transaction_count=sum(
                    record.transaction_type
                    == FinancialTransactionType.EXPENSE
                    for record in records
                ),
                expense_breakdown={
                    key: money(value)
                    for key, value in breakdown.items()
                },
            )

    async def budget_variance(
        self,
        *,
        principal: Principal,
        budget_id: str,
    ) -> BudgetVarianceResponse:

        async with self._lock:

            budget = self._get_budget(
                principal,
                budget_id,
                write=False,
            )

            actual = sum(
                (
                    record.amount
                    for record in self._transactions.values()
                    if (
                        record.tenant_id
                        == principal.tenant_id
                        and record.warehouse_id
                        == budget.warehouse_id
                        and record.currency
                        == budget.currency
                        and record.category
                        == budget.category
                        and record.status
                        == FinancialTransactionStatus.POSTED
                        and budget.start_date
                        <= record.transaction_date
                        <= budget.end_date
                    )
                ),
                Decimal("0"),
            )

            remaining = (
                budget.allocated_amount - actual
            )

            utilization = (
                float(
                    actual
                    / budget.allocated_amount
                    * 100
                )
                if budget.allocated_amount > 0
                else None
            )

            return BudgetVarianceResponse(
                budget_id=budget.budget_id,
                warehouse_id=budget.warehouse_id,
                category=budget.category,
                allocated_amount=budget.allocated_amount,
                actual_expenses=money(actual),
                remaining_budget=money(remaining),
                variance_amount=money(
                    actual - budget.allocated_amount
                ),
                utilization_percent=(
                    round(utilization, 2)
                    if utilization is not None
                    else None
                ),
                over_budget=(
                    actual > budget.allocated_amount
                ),
                currency=budget.currency,
            )

    async def summary(
        self,
        *,
        principal: Principal,
        warehouse_id: str,
        currency: str,
    ) -> FinancialSummaryResponse:

        require_financial_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self._lock:

            transactions = [
                record
                for record in self._transactions.values()
                if (
                    record.tenant_id
                    == principal.tenant_id
                    and record.warehouse_id
                    == warehouse_id
                    and record.currency == currency
                    and record.status
                    == FinancialTransactionStatus.POSTED
                )
            ]

            revenue = sum(
                (
                    record.amount
                    for record in transactions
                    if record.transaction_type
                    == FinancialTransactionType.REVENUE
                ),
                Decimal("0"),
            )

            expenses = sum(
                (
                    record.amount
                    for record in transactions
                    if record.transaction_type
                    == FinancialTransactionType.EXPENSE
                ),
                Decimal("0"),
            )

            active_budgets = sum(
                (
                    record.tenant_id
                    == principal.tenant_id
                    and record.warehouse_id
                    == warehouse_id
                    and record.currency == currency
                    and record.status
                    == BudgetStatus.APPROVED
                )
                for record in self._budgets.values()
            )

            return FinancialSummaryResponse(
                warehouse_id=warehouse_id,
                currency=currency,
                total_revenue=money(revenue),
                total_expenses=money(expenses),
                operating_result=money(
                    revenue - expenses
                ),
                total_transactions=len(transactions),
                active_budgets=active_budgets,
            )


financial_store = FinancialStore()


# ============================================================
# SERVICE
# ============================================================

class FinancialService:

    def __init__(
        self,
        store: FinancialStore,
    ):
        self.store = store

    async def record_transaction(
        self,
        principal: Principal,
        payload: FinancialTransactionCreate,
    ) -> FinancialTransactionResponse:

        return await self.store.create_transaction(
            principal=principal,
            payload=payload,
        )

    async def create_budget(
        self,
        principal: Principal,
        payload: BudgetCreate,
    ) -> BudgetResponse:

        return await self.store.create_budget(
            principal=principal,
            payload=payload,
        )


financial_service = FinancialService(
    financial_store
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Financial Intelligence"],
)


@router.post(
    "/transactions",
    response_model=FinancialTransactionResponse,
    status_code=201,
)
async def create_financial_transaction(
    payload: FinancialTransactionCreate,
    principal: CurrentPrincipal,
):
    return await financial_service.record_transaction(
        principal,
        payload,
    )


@router.get(
    "/transactions",
    response_model=list[FinancialTransactionResponse],
)
async def list_financial_transactions(
    principal: CurrentPrincipal,
    warehouse_id: str,
    currency: str = Query(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    ),
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await financial_store.list_transactions(
        principal=principal,
        warehouse_id=warehouse_id,
        currency=currency,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )


@router.get(
    "/transactions/{transaction_id}",
    response_model=FinancialTransactionResponse,
)
async def get_financial_transaction(
    transaction_id: str,
    principal: CurrentPrincipal,
):
    return await financial_store.get_transaction(
        principal=principal,
        transaction_id=transaction_id,
    )


@router.post(
    "/transactions/{transaction_id}/reverse",
    response_model=FinancialTransactionResponse,
)
async def reverse_financial_transaction(
    transaction_id: str,
    payload: TransactionReverseRequest,
    principal: CurrentPrincipal,
):
    return await financial_store.reverse_transaction(
        principal=principal,
        transaction_id=transaction_id,
        payload=payload,
    )


@router.post(
    "/budgets",
    response_model=BudgetResponse,
    status_code=201,
)
async def create_financial_budget(
    payload: BudgetCreate,
    principal: CurrentPrincipal,
):
    return await financial_service.create_budget(
        principal,
        payload,
    )


@router.get(
    "/budgets",
    response_model=list[BudgetResponse],
)
async def list_financial_budgets(
    principal: CurrentPrincipal,
    warehouse_id: str,
    currency: str = Query(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await financial_store.list_budgets(
        principal=principal,
        warehouse_id=warehouse_id,
        currency=currency,
        limit=limit,
    )


@router.get(
    "/budgets/{budget_id}",
    response_model=BudgetResponse,
)
async def get_financial_budget(
    budget_id: str,
    principal: CurrentPrincipal,
):
    return await financial_store.get_budget(
        principal=principal,
        budget_id=budget_id,
    )


@router.post(
    "/budgets/{budget_id}/approve",
    response_model=BudgetResponse,
)
async def approve_financial_budget(
    budget_id: str,
    payload: BudgetApprovalRequest,
    principal: CurrentPrincipal,
):
    return await financial_store.approve_budget(
        principal=principal,
        budget_id=budget_id,
        payload=payload,
    )


@router.get(
    "/budgets/{budget_id}/variance",
    response_model=BudgetVarianceResponse,
)
async def get_budget_variance(
    budget_id: str,
    principal: CurrentPrincipal,
):
    return await financial_store.budget_variance(
        principal=principal,
        budget_id=budget_id,
    )


@router.get(
    "/kpis/{warehouse_id}",
    response_model=FinancialKPIResponse,
)
async def get_financial_kpis(
    warehouse_id: str,
    principal: CurrentPrincipal,
    start_date: date,
    end_date: date,
    currency: str = Query(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    ),
):
    return await financial_store.financial_kpis(
        principal=principal,
        warehouse_id=warehouse_id,
        currency=currency,
        start_date=start_date,
        end_date=end_date,
    )


@router.get(
    "/summary/{warehouse_id}",
    response_model=FinancialSummaryResponse,
)
async def get_financial_summary(
    warehouse_id: str,
    principal: CurrentPrincipal,
    currency: str = Query(
        default="INR",
        pattern=r"^[A-Z]{3}$",
    ),
):
    return await financial_store.summary(
        principal=principal,
        warehouse_id=warehouse_id,
        currency=currency,
    )


__all__ = [
    "FinancialTransactionType",
    "FinancialCategory",
    "FinancialTransactionStatus",
    "BudgetStatus",
    "BudgetPeriod",
    "FinancialTransactionCreate",
    "TransactionReverseRequest",
    "BudgetCreate",
    "BudgetApprovalRequest",
    "FinancialTransactionResponse",
    "BudgetResponse",
    "FinancialKPIResponse",
    "BudgetVarianceResponse",
    "FinancialSummaryResponse",
    "FinancialStore",
    "FinancialService",
    "financial_store",
    "financial_service",
    "router",
]
