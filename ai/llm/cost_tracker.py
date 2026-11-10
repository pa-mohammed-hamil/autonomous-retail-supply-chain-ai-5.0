"""Planned module: cost tracker. Implementation pending."""

"""
File: ai/llm/cost_tracker.py
Project: Autonomous Retail Supply Chain AI 5.0

Persistent LLM token and cost tracking.

Features:
- Model pricing registry
- Input/output token accounting
- Estimated USD cost calculation
- Tenant-level budgets
- Atomic cost reservations
- Usage recording and reconciliation
- Daily/monthly spending summaries
- Agent/model/provider reporting
- SQLite persistence

Python 3.10+
Standard library only

Pricing is configured by the application.
Do not assume sample prices are current.
"""

from __future__ import annotations

import json
import sqlite3
import threading

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import uuid4


class CostTrackerError(Exception):
    pass


class BudgetExceeded(CostTrackerError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CostTrackerError(
            f"{name} must be a nonempty string."
        )
    return value.strip()


def decimal_value(value: Any) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CostTrackerError(
            "Invalid decimal amount."
        ) from exc

    if not number.is_finite() or number < 0:
        raise CostTrackerError(
            "Amount must be finite and nonnegative."
        )

    return number


def token_count(value: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        raise CostTrackerError(
            "Token count must be a nonnegative integer."
        )
    return value


@dataclass(frozen=True)
class ModelPricing:
    provider: str
    model: str
    input_per_million_usd: Decimal
    output_per_million_usd: Decimal


class CostTracker:
    """
    SQLite-backed LLM usage and budget tracker.

    Reservations prevent concurrent requests from
    exceeding the configured budget based on their
    estimated maximum cost.

    Budgets are not a provider-side hard spending cap.
    """

    def __init__(
        self,
        database_path: str = "data/llm_costs.db",
    ) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.path),
            timeout=30,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS model_pricing (
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    input_rate TEXT NOT NULL,
                    output_rate TEXT NOT NULL,
                    PRIMARY KEY(provider, model)
                );

                CREATE TABLE IF NOT EXISTS budgets (
                    tenant_id TEXT PRIMARY KEY,
                    monthly_limit_usd TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS reservations (
                    reservation_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    reserved_usd TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS usage_records (
                    usage_id TEXT PRIMARY KEY,
                    reservation_id TEXT UNIQUE,
                    tenant_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    cost_usd TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_usage_tenant_date
                ON usage_records(tenant_id, created_at);
            """)

    def register_pricing(
        self,
        provider: str,
        model: str,
        input_per_million_usd: Any,
        output_per_million_usd: Any,
    ) -> None:
        provider = require_text(provider, "provider")
        model = require_text(model, "model")

        input_rate = decimal_value(
            input_per_million_usd
        )
        output_rate = decimal_value(
            output_per_million_usd
        )

        with self._lock, self._connect() as conn:
            conn.execute("""
                INSERT INTO model_pricing
                    (provider, model, input_rate, output_rate)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(provider, model)
                DO UPDATE SET
                    input_rate=excluded.input_rate,
                    output_rate=excluded.output_rate
            """, (
                provider,
                model,
                str(input_rate),
                str(output_rate),
            ))

    def get_pricing(
        self,
        provider: str,
        model: str,
    ) -> ModelPricing:
        with self._connect() as conn:
            row = conn.execute("""
                SELECT *
                FROM model_pricing
                WHERE provider=? AND model=?
            """, (provider, model)).fetchone()

        if row is None:
            raise CostTrackerError(
                f"Pricing not configured: {provider}/{model}"
            )

        return ModelPricing(
            provider=row["provider"],
            model=row["model"],
            input_per_million_usd=Decimal(
                row["input_rate"]
            ),
            output_per_million_usd=Decimal(
                row["output_rate"]
            ),
        )

    def estimate_cost(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> Decimal:
        input_tokens = token_count(input_tokens)
        output_tokens = token_count(output_tokens)

        pricing = self.get_pricing(provider, model)

        million = Decimal("1000000")

        return (
            Decimal(input_tokens)
            * pricing.input_per_million_usd
            / million
            + Decimal(output_tokens)
            * pricing.output_per_million_usd
            / million
        )

    def set_monthly_budget(
        self,
        tenant_id: str,
        limit_usd: Any,
    ) -> None:
        tenant_id = require_text(
            tenant_id, "tenant_id"
        )
        amount = decimal_value(limit_usd)

        with self._lock, self._connect() as conn:
            conn.execute("""
                INSERT INTO budgets
                    (tenant_id, monthly_limit_usd)
                VALUES (?, ?)
                ON CONFLICT(tenant_id)
                DO UPDATE SET
                    monthly_limit_usd=excluded.monthly_limit_usd
            """, (tenant_id, str(amount)))

    def _month_prefix(self) -> str:
        return datetime.now(
            timezone.utc
        ).strftime("%Y-%m")

    def _month_totals(
        self,
        conn: sqlite3.Connection,
        tenant_id: str,
    ) -> tuple[Decimal, Decimal]:
        month = self._month_prefix()

        usage_rows = conn.execute("""
            SELECT cost_usd
            FROM usage_records
            WHERE tenant_id=?
              AND substr(created_at, 1, 7)=?
        """, (tenant_id, month)).fetchall()

        reserved_rows = conn.execute("""
            SELECT reserved_usd
            FROM reservations
            WHERE tenant_id=?
              AND status='active'
              AND substr(created_at, 1, 7)=?
        """, (tenant_id, month)).fetchall()

        spent = sum(
            (Decimal(row["cost_usd"]) for row in usage_rows),
            Decimal("0"),
        )

        reserved = sum(
            (Decimal(row["reserved_usd"]) for row in reserved_rows),
            Decimal("0"),
        )

        return spent, reserved

    def reserve(
        self,
        tenant_id: str,
        agent_id: str,
        provider: str,
        model: str,
        maximum_cost_usd: Any,
    ) -> str:
        tenant_id = require_text(
            tenant_id, "tenant_id"
        )
        agent_id = require_text(
            agent_id, "agent_id"
        )
        provider = require_text(
            provider, "provider"
        )
        model = require_text(model, "model")

        maximum = decimal_value(maximum_cost_usd)
        reservation_id = str(uuid4())

        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")

            try:
                budget = conn.execute("""
                    SELECT monthly_limit_usd
                    FROM budgets
                    WHERE tenant_id=?
                """, (tenant_id,)).fetchone()

                if budget is None:
                    raise CostTrackerError(
                        "Tenant budget is not configured."
                    )

                spent, reserved = self._month_totals(
                    conn, tenant_id
                )

                limit = Decimal(
                    budget["monthly_limit_usd"]
                )

                if spent + reserved + maximum > limit:
                    raise BudgetExceeded(
                        "LLM monthly budget exceeded."
                    )

                conn.execute("""
                    INSERT INTO reservations (
                        reservation_id,
                        tenant_id,
                        agent_id,
                        provider,
                        model,
                        reserved_usd,
                        status,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
                """, (
                    reservation_id,
                    tenant_id,
                    agent_id,
                    provider,
                    model,
                    str(maximum),
                    utc_now(),
                ))

                conn.execute("COMMIT")

            except Exception:
                conn.execute("ROLLBACK")
                raise

        return reservation_id

    def finalize(
        self,
        reservation_id: str,
        tenant_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> dict[str, Any]:
        input_tokens = token_count(input_tokens)
        output_tokens = token_count(output_tokens)

        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")

            try:
                row = conn.execute("""
                    SELECT *
                    FROM reservations
                    WHERE reservation_id=?
                      AND tenant_id=?
                """, (
                    reservation_id,
                    tenant_id,
                )).fetchone()

                if row is None or row["status"] != "active":
                    raise CostTrackerError(
                        "Active reservation not found."
                    )

                pricing_row = conn.execute("""
                    SELECT input_rate, output_rate
                    FROM model_pricing
                    WHERE provider=? AND model=?
                """, (
                    row["provider"],
                    row["model"],
                )).fetchone()

                if pricing_row is None:
                    raise CostTrackerError(
                        "Model pricing is missing."
                    )

                cost = (
                    Decimal(input_tokens)
                    * Decimal(pricing_row["input_rate"])
                    / Decimal("1000000")
                    + Decimal(output_tokens)
                    * Decimal(pricing_row["output_rate"])
                    / Decimal("1000000")
                )

                usage_id = str(uuid4())

                conn.execute("""
                    INSERT INTO usage_records (
                        usage_id,
                        reservation_id,
                        tenant_id,
                        agent_id,
                        provider,
                        model,
                        input_tokens,
                        output_tokens,
                        cost_usd,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    usage_id,
                    reservation_id,
                    tenant_id,
                    row["agent_id"],
                    row["provider"],
                    row["model"],
                    input_tokens,
                    output_tokens,
                    str(cost),
                    utc_now(),
                ))

                conn.execute("""
                    UPDATE reservations
                    SET status='finalized'
                    WHERE reservation_id=?
                      AND tenant_id=?
                """, (
                    reservation_id,
                    tenant_id,
                ))

                conn.execute("COMMIT")

            except Exception:
                conn.execute("ROLLBACK")
                raise

        return {
            "usage_id": usage_id,
            "reservation_id": reservation_id,
            "tenant_id": tenant_id,
            "provider": row["provider"],
            "model": row["model"],
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": str(cost),
            "reservation_exceeded": (
                cost > Decimal(row["reserved_usd"])
            ),
        }

    def release(
        self,
        reservation_id: str,
        tenant_id: str,
    ) -> bool:
        """
        Release unused reserved budget.

        Do not release an ambiguous request until
        provider usage has been reconciled.
        """
        with self._lock, self._connect() as conn:
            cursor = conn.execute("""
                UPDATE reservations
                SET status='released'
                WHERE reservation_id=?
                  AND tenant_id=?
                  AND status='active'
            """, (
                reservation_id,
                tenant_id,
            ))

            return cursor.rowcount > 0

    def budget_status(
        self,
        tenant_id: str,
    ) -> dict[str, str]:
        with self._connect() as conn:
            row = conn.execute("""
                SELECT monthly_limit_usd
                FROM budgets
                WHERE tenant_id=?
            """, (tenant_id,)).fetchone()

            if row is None:
                raise CostTrackerError(
                    "Budget not configured."
                )

            spent, reserved = self._month_totals(
                conn, tenant_id
            )

        limit = Decimal(
            row["monthly_limit_usd"]
        )

        return {
            "tenant_id": tenant_id,
            "month_utc": self._month_prefix(),
            "budget_usd": str(limit),
            "spent_usd": str(spent),
            "reserved_usd": str(reserved),
            "available_usd": str(
                max(
                    Decimal("0"),
                    limit - spent - reserved,
                )
            ),
        }

    def usage_report(
        self,
        tenant_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 1000
        ):
            raise CostTrackerError(
                "Invalid report limit."
            )

        with self._connect() as conn:
            rows = conn.execute("""
                SELECT *
                FROM usage_records
                WHERE tenant_id=?
                ORDER BY created_at DESC
                LIMIT ?
            """, (
                tenant_id,
                limit,
            )).fetchall()

        return [dict(row) for row in rows]


if __name__ == "__main__":
    tracker = CostTracker()

    # Example-only pricing; replace with verified rates.
    tracker.register_pricing(
        provider="example",
        model="demo-model",
        input_per_million_usd="1.00",
        output_per_million_usd="4.00",
    )

    tracker.set_monthly_budget(
        "retail_company_001",
        "20.00",
    )

    reservation = tracker.reserve(
        tenant_id="retail_company_001",
        agent_id="demand_agent",
        provider="example",
        model="demo-model",
        maximum_cost_usd="0.05",
    )

    result = tracker.finalize(
        reservation_id=reservation,
        tenant_id="retail_company_001",
        input_tokens=1500,
        output_tokens=500,
    )

    print(result)
    print(
        tracker.budget_status(
            "retail_company_001"
        )
    )
