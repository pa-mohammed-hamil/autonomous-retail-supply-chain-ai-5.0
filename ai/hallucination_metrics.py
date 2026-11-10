"""Planned module: hallucination metrics. Implementation pending."""

"""
File: ai/evaluation/hallucination_metrics.py
Python 3.10+ | Standard library only
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from .groundedness import GroundednessEvaluator


@dataclass(frozen=True)
class HallucinationEvaluation:
    tenant_id: str
    agent_id: str
    evaluation_id: str
    claim_count: int
    unsupported_claim_count: int
    unsupported_claim_rate: float | None
    timestamp: str


class HallucinationMetrics:

    def __init__(
        self,
        groundedness_evaluator: (
            GroundednessEvaluator | None
        ) = None,
    ):
        self.evaluator = (
            groundedness_evaluator
            or GroundednessEvaluator()
        )
        self._records: list[
            HallucinationEvaluation
        ] = []
        self._lock = threading.RLock()

    def evaluate_response(
        self,
        tenant_id: str,
        agent_id: str,
        evaluation_id: str,
        answer: str,
        evidence: list[dict[str, Any]],
    ) -> dict:

        for name, value in {
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "evaluation_id": evaluation_id,
        }.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} required")

        groundedness = self.evaluator.evaluate(
            answer, evidence
        )

        total = groundedness["claim_count"]
        unsupported = groundedness[
            "unsupported_claim_count"
        ]

        rate = (
            round(unsupported / total, 3)
            if total else None
        )

        record = HallucinationEvaluation(
            tenant_id=tenant_id,
            agent_id=agent_id,
            evaluation_id=evaluation_id,
            claim_count=total,
            unsupported_claim_count=unsupported,
            unsupported_claim_rate=rate,
            timestamp=datetime.now(
                timezone.utc
            ).isoformat(),
        )

        with self._lock:
            if any(
                r.tenant_id == tenant_id
                and r.evaluation_id == evaluation_id
                for r in self._records
            ):
                raise ValueError(
                    "Duplicate evaluation_id"
                )

            self._records.append(record)

        return {
            "evaluation": asdict(record),
            "groundedness": groundedness,
            "metric_type": "unsupported_claim_proxy",
        }

    def summary(
        self,
        tenant_id: str,
        agent_id: str | None = None,
    ) -> dict:

        with self._lock:
            records = [
                r for r in self._records
                if r.tenant_id == tenant_id
                and (
                    agent_id is None
                    or r.agent_id == agent_id
                )
            ]

        total_claims = sum(
            r.claim_count for r in records
        )
        unsupported = sum(
            r.unsupported_claim_count
            for r in records
        )

        return {
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "evaluation_count": len(records),
            "total_claims": total_claims,
            "unsupported_claims": unsupported,
            "unsupported_claim_rate": (
                round(
                    unsupported / total_claims, 3
                )
                if total_claims else None
            ),
            "actual_hallucination_rate_verified": False,
            "storage": "in_memory",
        }
