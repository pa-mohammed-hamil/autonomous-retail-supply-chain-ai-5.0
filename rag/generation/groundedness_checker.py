
"""
ai/generation/groundedness_checker.py

Autonomous Retail Supply Chain AI 5.0

Claim-Level Groundedness Checker

Install:
    pip install pydantic

The verifier is injected through a
callable. No external API is required
for the included demonstration.

Important:
    A verifier's judgment is an estimate,
    not proof of factual correctness.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from pydantic import (
    BaseModel,
    Field,
)


class Evidence(BaseModel):
    citation_id: str
    document_id: str
    text: str
    title: str = ""


class ClaimAssessment(BaseModel):
    claim: str
    citations: list[str]
    verdict: str
    explanation: str = ""
    evidence_ids: list[str] = Field(
        default_factory=list
    )


class GroundednessResult(BaseModel):
    groundedness_score: float
    supported_claims: int
    unsupported_claims: int
    contradicted_claims: int
    unverifiable_claims: int
    total_claims: int
    assessments: list[ClaimAssessment]
    passed: bool


class GroundednessChecker:

    CITATION_RE = re.compile(
        r"\[(S[1-9]\d*)\]"
    )

    VALID_VERDICTS = {
        "supported",
        "unsupported",
        "contradicted",
        "unverifiable",
    }

    def __init__(
        self,
        verifier: Callable[
            [str, list[Evidence]], dict
        ],
        min_groundedness=0.90,
    ):
        if not 0 <= min_groundedness <= 1:
            raise ValueError(
                "Threshold must be 0-1"
            )

        self.verifier = verifier
        self.min_groundedness = (
            min_groundedness
        )

    @staticmethod
    def split_claims(answer):
        # Lightweight sentence splitter.
        # Production use should replace
        # this with a robust claim extractor.
        sentences = re.split(
            r"(?<=[.!?])\s+",
            answer.strip(),
        )

        return [
            sentence.strip()
            for sentence in sentences
            if sentence.strip()
        ]

    def check(
        self,
        answer: str,
        evidence: list[Evidence],
    ):
        if not answer.strip():
            raise ValueError(
                "Answer cannot be empty"
            )

        evidence_map = {
            item.citation_id: item
            for item in evidence
        }

        if len(evidence_map) != len(evidence):
            raise ValueError(
                "Duplicate citation IDs"
            )

        claims = self.split_claims(
            answer
        )

        assessments = []

        for sentence in claims:
            cited = list(
                dict.fromkeys(
                    self.CITATION_RE.findall(
                        sentence
                    )
                )
            )

            clean_claim = (
                self.CITATION_RE.sub(
                    "",
                    sentence,
                ).strip()
            )

            unknown = [
                citation
                for citation in cited
                if citation not in evidence_map
            ]

            if not cited or unknown:
                assessments.append(
                    ClaimAssessment(
                        claim=clean_claim,
                        citations=cited,
                        verdict="unverifiable",
                        explanation=(
                            "Missing or unknown "
                            "source citation"
                        ),
                    )
                )
                continue

            sources = [
                evidence_map[citation]
                for citation in cited
            ]

            try:
                judgment = self.verifier(
                    clean_claim,
                    sources,
                )

                verdict = judgment.get(
                    "verdict",
                    "unverifiable",
                )

                if (
                    verdict
                    not in self.VALID_VERDICTS
                ):
                    verdict = "unverifiable"

                explanation = str(
                    judgment.get(
                        "explanation",
                        "",
                    )
                )

            except Exception as error:
                verdict = "unverifiable"
                explanation = (
                    "Verification failed: "
                    + type(error).__name__
                )

            assessments.append(
                ClaimAssessment(
                    claim=clean_claim,
                    citations=cited,
                    verdict=verdict,
                    explanation=explanation,
                    evidence_ids=[
                        item.citation_id
                        for item in sources
                    ],
                )
            )

        supported = sum(
            item.verdict == "supported"
            for item in assessments
        )

        unsupported = sum(
            item.verdict == "unsupported"
            for item in assessments
        )

        contradicted = sum(
            item.verdict == "contradicted"
            for item in assessments
        )

        unverifiable = sum(
            item.verdict == "unverifiable"
            for item in assessments
        )

        total = len(assessments)

        score = (
            supported / total
            if total
            else 0.0
        )

        passed = (
            score >= self.min_groundedness
            and contradicted == 0
            and unsupported == 0
            and unverifiable == 0
        )

        return GroundednessResult(
            groundedness_score=round(
                score, 4
            ),
            supported_claims=supported,
            unsupported_claims=unsupported,
            contradicted_claims=contradicted,
            unverifiable_claims=unverifiable,
            total_claims=total,
            assessments=assessments,
            passed=passed,
        )

    @staticmethod
    def save(
        result: GroundednessResult,
        output_path=(
            "reports/rag/"
            "groundedness_report.json"
        ),
    ):
        path = Path(output_path)

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            result.model_dump_json(
                indent=2
            ),
            encoding="utf-8",
        )

        return path


def demo_verifier(
    claim: str,
    sources: list[Evidence],
):
    """
    Demonstration only.

    Exact normalized sentence matching
    can verify a copied statement but
    cannot establish general entailment.
    """
    normalized_claim = re.sub(
        r"\s+",
        " ",
        claim.lower().strip(" ."),
    )

    for source in sources:
        normalized_source = re.sub(
            r"\s+",
            " ",
            source.text.lower(),
        )

        if (
            normalized_claim
            in normalized_source
        ):
            return {
                "verdict": "supported",
                "explanation": (
                    "Exact text match "
                    "in cited evidence"
                ),
            }

    return {
        "verdict": "unverifiable",
        "explanation": (
            "No exact match. "
            "Semantic verification needed."
        ),
    }


if __name__ == "__main__":
    checker = GroundednessChecker(
        verifier=demo_verifier,
        min_groundedness=1.0,
    )

    sources = [
        Evidence(
            citation_id="S1",
            document_id="inventory-001",
            title="Inventory Snapshot",
            text=(
                "SKU001 has 120 units "
                "in stock."
            ),
        ),
        Evidence(
            citation_id="S2",
            document_id="supplier-002",
            title="Supplier Report",
            text=(
                "Supplier SUP002 has "
                "an average lead time "
                "of eight days."
            ),
        ),
    ]

    answer = (
        "SKU001 has 120 units "
        "in stock [S1]. "
        "Supplier SUP002 has an "
        "average lead time "
        "of eight days [S2]."
    )

    result = checker.check(
        answer,
        sources,
    )

    print(
        result.model_dump_json(
            indent=2
        )
    )

    checker.save(result)
