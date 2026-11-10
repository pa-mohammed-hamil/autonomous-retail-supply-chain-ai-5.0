"""Planned module: hallucination guard. Implementation pending."""

"""
ai/generation/hallucination_guard.py

Autonomous Retail Supply Chain AI 5.0

Hallucination Guard

Install:
    pip install pydantic

Run:
    python -m ai.generation.hallucination_guard
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import (
    BaseModel,
    Field,
)

from ai.generation.groundedness_checker import (
    Evidence,
    GroundednessChecker,
    GroundednessResult,
    demo_verifier,
)


class GuardDecision(BaseModel):
    allowed: bool
    status: str
    answer: str
    original_answer: str
    reasons: list[str] = Field(
        default_factory=list
    )
    groundedness_score: float = 0.0
    requires_human_review: bool = False
    evaluated_at: str


class HallucinationGuard:

    FALLBACK = (
        "I cannot verify this answer "
        "against the available sources. "
        "Please review the source data "
        "or provide additional evidence."
    )

    SENSITIVE_ACTIONS = [
        "approve payment",
        "transfer funds",
        "cancel purchase order",
        "delete inventory",
        "change supplier contract",
        "release shipment",
        "block supplier",
    ]

    def __init__(
        self,
        checker: GroundednessChecker,
        min_groundedness=0.90,
    ):
        if not 0 <= min_groundedness <= 1:
            raise ValueError(
                "Threshold must be 0-1"
            )

        self.checker = checker
        self.min_groundedness = (
            min_groundedness
        )

    @staticmethod
    def _sensitive_action_requested(
        text,
    ):
        normalized = text.lower()

        return any(
            phrase in normalized
            for phrase in (
                HallucinationGuard
                .SENSITIVE_ACTIONS
            )
        )

    def inspect(
        self,
        answer: str,
        evidence: list[Evidence],
        user_request: str = "",
    ):
        timestamp = datetime.now(
            timezone.utc
        ).isoformat()

        reasons = []

        if not answer.strip():
            reasons.append(
                "Empty answer"
            )

            return GuardDecision(
                allowed=False,
                status="blocked",
                answer=self.FALLBACK,
                original_answer=answer,
                reasons=reasons,
                evaluated_at=timestamp,
            )

        try:
            result = self.checker.check(
                answer,
                evidence,
            )
        except Exception as error:
            reasons.append(
                "Verification system error: "
                + type(error).__name__
            )

            return GuardDecision(
                allowed=False,
                status="blocked",
                answer=self.FALLBACK,
                original_answer=answer,
                reasons=reasons,
                evaluated_at=timestamp,
            )

        if (
            result.groundedness_score
            < self.min_groundedness
        ):
            reasons.append(
                "Groundedness below threshold"
            )

        if result.unsupported_claims:
            reasons.append(
                "Unsupported factual claims"
            )

        if result.contradicted_claims:
            reasons.append(
                "Contradictory factual claims"
            )

        if result.unverifiable_claims:
            reasons.append(
                "Unverifiable claims"
            )

        sensitive = (
            self._sensitive_action_requested(
                user_request
            )
        )

        if sensitive:
            reasons.append(
                "Sensitive business action "
                "requires human approval"
            )

        allowed = (
            not reasons
            and result.passed
        )

        if allowed:
            status = "approved"
            final_answer = answer
        elif sensitive:
            status = "human_review"
            final_answer = (
                self.FALLBACK
                + " Human approval is "
                "required for this action."
            )
        else:
            status = "blocked"
            final_answer = self.FALLBACK

        return GuardDecision(
            allowed=allowed,
            status=status,
            answer=final_answer,
            original_answer=answer,
            reasons=reasons,
            groundedness_score=(
                result.groundedness_score
            ),
            requires_human_review=sensitive,
            evaluated_at=timestamp,
        )

    @staticmethod
    def save_audit(
        decision: GuardDecision,
        output_path=(
            "reports/rag/"
            "hallucination_guard_audit.json"
        ),
    ):
        path = Path(output_path)

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            decision.model_dump_json(
                indent=2
            ),
            encoding="utf-8",
        )

        return path


if __name__ == "__main__":
    checker = GroundednessChecker(
        verifier=demo_verifier,
        min_groundedness=1.0,
    )

    guard = HallucinationGuard(
        checker=checker,
        min_groundedness=1.0,
    )

    evidence = [
        Evidence(
            citation_id="S1",
            document_id="inventory-001",
            title="Inventory Snapshot",
            text=(
                "SKU001 has 120 units "
                "in stock."
            ),
        )
    ]

    answer = (
        "SKU001 has 120 units "
        "in stock [S1]."
    )

    decision = guard.inspect(
        answer=answer,
        evidence=evidence,
        user_request=(
            "How much stock "
            "is available?"
        ),
    )

    print(
        decision.model_dump_json(
            indent=2
        )
    )

    guard.save_audit(
        decision
    )
