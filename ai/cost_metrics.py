"""Planned module: cost metrics. Implementation pending."""

"""
File: ai/observability/cost_metrics.py
Python 3.10+ | Standard library only

Prices are supplied by the application.
No live provider pricing is fetched.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


def decimal_value(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(
        value, (str, int, Decimal)
    ):
        raise ValueError(f"Invalid {name}")

    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid {name}") from exc

    if not number.is_finite() or number < 0:
        raise ValueError(f"Invalid {name}")

    return number


@dataclass(frozen=True)
class CostRecord:
    tenant_id: str
    agent_id: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: str
    timestamp: str


class CostMetrics:

    def __init__(self):
        self._prices: dict[
            tuple[str, str], tuple[Decimal, Decimal]
        ] = {}
        self._records: list[CostRecord] = []
        self._budgets: dict[str, Decimal] = {}
        self._lock = threading.RLock()

    def set_model_price(
        self,
        provider: str,
        model: str,
        input_usd_per_million: Any,
        output_usd_per_million: Any,
    ) -> None:

        if not provider or not model:
            raise ValueError("Provider and model required")

        with self._lock:
            self._prices[(provider, model)] = (
                decimal_value(
                    input_usd_per_million,
                    "input price",
                ),
                decimal_value(
                    output_usd_per_million,
                    "output price",
                ),
            )

    def set_tenant_budget(
        self,
        tenant_id: str,
        budget_usd: Any,
    ) -> None:
        with self._lock:
            self._budgets[tenant_id] = decimal_value(
                budget_usd, "budget_usd"
            )

    def record_usage(
        self,
        tenant_id: str,
        agent_id: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> dict:

        for value in (
            tenant_id, agent_id, provider, model
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("Invalid identifier")

        for count in (input_tokens, output_tokens):
            if (
                isinstance(count, bool)
                or not isinstance(count, int)
                or count < 0
            ):
                raise ValueError("Invalid token count")

        with self._lock:
            prices = self._prices.get(
                (provider, model)
            )

            if prices is None:
                raise ValueError(
                    "Model pricing not configured"
                )

            input_price, output_price = prices

            cost = (
                Decimal(input_tokens) * input_price
                + Decimal(output_tokens) * output_price
            ) / Decimal(1_000_000)

            record = CostRecord(
                tenant_id=tenant_id,
                agent_id=agent_id,
                provider=provider,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=str(cost),
                timestamp=datetime.now(
                    timezone.utc
                ).isoformat(),
            )

            self._records.append(record)

        return asdict(record)

    def summary(self, tenant_id: str) -> dict:
        with self._lock:
            records = [
                r for r in self._records
                if r.tenant_id == tenant_id
            ]
            budget = self._budgets.get(tenant_id)

        total = sum(
            (Decimal(r.cost_usd) for r in records),
            Decimal("0"),
        )

        by_agent = defaultdict(lambda: Decimal("0"))
        by_model = defaultdict(lambda: Decimal("0"))

        for record in records:
            cost = Decimal(record.cost_usd)
            by_agent[record.agent_id] += cost
            by_model[
                f"{record.provider}/{record.model}"
            ] += cost

        return {
            "tenant_id": tenant_id,
            "request_count": len(records),
            "input_tokens": sum(
                r.input_tokens for r in records
            ),
            "output_tokens": sum(
                r.output_tokens for r in records
            ),
            "total_cost_usd": str(total),
            "cost_by_agent_usd": {
                k: str(v) for k, v in by_agent.items()
            },
            "cost_by_model_usd": {
                k: str(v) for k, v in by_model.items()
            },
            "budget_usd": (
                str(budget)
                if budget is not None else None
            ),
            "budget_exceeded": (
                total > budget
                if budget is not None else None
            ),
            "note": (
                "Budget monitoring is informational. "
                "This class does not block requests."
            ),
        }
