"""Planned module: cost monitor. Implementation pending."""

"""
LLMOps cost monitoring.

Features:
- Per-model token pricing
- Input/output token accounting
- Estimated USD cost
- Agent-level cost tracking
- Daily cost summaries
- Budget alerts
- Idempotent usage records
- SQLite persistence

Pricing is configurable and illustrative.
Update rates using actual provider contracts.

No billing or payment operations are performed.
"""

from __future__ import annotations

import json
import sqlite3
import uuid

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


def money(value) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("Invalid monetary value")

    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Invalid decimal") from None

    if not result.is_finite():
        raise ValueError("Non-finite decimal")

    return result


@dataclass(frozen=True)
class ModelPricing:
    provider: str
    model: str
    input_per_million_usd: Decimal
    output_per_million_usd: Decimal

    def __post_init__(self):
        if not self.provider or not self.model:
            raise ValueError("Provider and model required")

        if (
            money(self.input_per_million_usd) < 0
            or money(self.output_per_million_usd) < 0
        ):
            raise ValueError("Negative pricing")


@dataclass(frozen=True)
class CostMonitorConfig:
    database_path: str = "data/llmops/costs.db"
    daily_budget_usd: Decimal = Decimal("10")
    warning_threshold: Decimal = Decimal("0.80")


class CostMonitor:

    def __init__(
        self,
        config: CostMonitorConfig | None = None,
    ):
        self.config = config or CostMonitorConfig()

        if money(self.config.daily_budget_usd) <= 0:
            raise ValueError("Budget must be positive")

        if not (
            Decimal("0")
            < money(self.config.warning_threshold)
            <= Decimal("1")
        ):
            raise ValueError("Invalid warning threshold")

        path = Path(self.config.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        self.db = sqlite3.connect(
            str(path),
            timeout=30,
        )
        self.db.row_factory = sqlite3.Row

        self.db.execute("""
            CREATE TABLE IF NOT EXISTS llm_usage (
                usage_id TEXT PRIMARY KEY,
                trace_id TEXT,
                agent_name TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                cost_usd TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        self.db.commit()

        self.pricing: dict[
            tuple[str, str], ModelPricing
        ] = {}

    def register_pricing(
        self,
        pricing: ModelPricing,
    ) -> None:
        self.pricing[
            (pricing.provider, pricing.model)
        ] = pricing

    def estimate_cost(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> Decimal:
        for value in (input_tokens, output_tokens):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ValueError("Invalid token count")

        pricing = self.pricing.get(
            (provider, model)
        )

        if pricing is None:
            raise ValueError(
                "Pricing not registered for model"
            )

        input_cost = (
            Decimal(input_tokens)
            * money(pricing.input_per_million_usd)
            / Decimal("1000000")
        )

        output_cost = (
            Decimal(output_tokens)
            * money(pricing.output_per_million_usd)
            / Decimal("1000000")
        )

        return input_cost + output_cost

    def record_usage(
        self,
        agent_name: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        trace_id: str | None = None,
        usage_id: str | None = None,
    ) -> dict:
        if not agent_name.strip():
            raise ValueError("Agent name required")

        usage_id = usage_id or uuid.uuid4().hex

        cost = self.estimate_cost(
            provider,
            model,
            input_tokens,
            output_tokens,
        )

        timestamp = datetime.now(
            timezone.utc
        ).isoformat()

        cursor = self.db.execute(
            """
            INSERT OR IGNORE INTO llm_usage (
                usage_id, trace_id, agent_name,
                provider, model, input_tokens,
                output_tokens, cost_usd, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                usage_id,
                trace_id,
                agent_name,
                provider,
                model,
                input_tokens,
                output_tokens,
                str(cost),
                timestamp,
            ),
        )

        self.db.commit()

        return {
            "usage_id": usage_id,
            "recorded": cursor.rowcount == 1,
            "estimated_cost_usd": str(cost),
            "currency": "USD",
        }

    def daily_summary(
        self,
        day: str | None = None,
    ) -> dict:
        day = day or datetime.now(
            timezone.utc
        ).date().isoformat()

        rows = self.db.execute(
            """
            SELECT *
            FROM llm_usage
            WHERE substr(created_at, 1, 10) = ?
            """,
            (day,),
        ).fetchall()

        total = sum(
            (
                Decimal(row["cost_usd"])
                for row in rows
            ),
            Decimal("0"),
        )

        budget = money(
            self.config.daily_budget_usd
        )

        utilization = total / budget

        if utilization >= Decimal("1"):
            status = "budget_exceeded"
        elif utilization >= money(
            self.config.warning_threshold
        ):
            status = "warning"
        else:
            status = "within_budget"

        agents = {}

        for row in rows:
            name = row["agent_name"]

            agents.setdefault(
                name,
                {
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": Decimal("0"),
                },
            )

            agents[name]["calls"] += 1
            agents[name]["input_tokens"] += (
                row["input_tokens"]
            )
            agents[name]["output_tokens"] += (
                row["output_tokens"]
            )
            agents[name]["cost_usd"] += Decimal(
                row["cost_usd"]
            )

        for metrics in agents.values():
            metrics["cost_usd"] = str(
                metrics["cost_usd"]
            )

        return {
            "date": day,
            "total_calls": len(rows),
            "total_cost_usd": str(total),
            "daily_budget_usd": str(budget),
            "budget_utilization_percent": str(
                utilization * 100
            ),
            "status": status,
            "agents": agents,
            "pricing_basis": "configured_estimates",
        }

    def close(self):
        self.db.close()


if __name__ == "__main__":
    monitor = CostMonitor()

    # Demonstration rates, not live provider prices.
    monitor.register_pricing(
        ModelPricing(
            provider="demo_provider",
            model="demo_llm",
            input_per_million_usd=Decimal("1.00"),
            output_per_million_usd=Decimal("4.00"),
        )
    )

    print(
        monitor.record_usage(
            agent_name="demand_agent",
            provider="demo_provider",
            model="demo_llm",
            input_tokens=1500,
            output_tokens=500,
            trace_id="trace-001",
            usage_id="usage-001",
        )
    )

    print(
        json.dumps(
            monitor.daily_summary(),
            indent=2,
        )
    )

    monitor.close()
