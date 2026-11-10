"""Planned module: groundedness. Implementation pending."""

"""
File: ai/evaluation/groundedness.py
Python 3.10+ | Standard library only
"""

from __future__ import annotations

import re
from typing import Any


STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were",
    "to", "of", "and", "or", "for", "in", "on",
    "at", "by", "with", "from", "that", "this",
}


class GroundednessEvaluator:

    def __init__(self, threshold: float = 0.65):
        if not 0 <= threshold <= 1:
            raise ValueError("Invalid threshold")
        self.threshold = threshold

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {
            word
            for word in re.findall(
                r"[a-z0-9]+", text.lower()
            )
            if word not in STOPWORDS
        }

    @staticmethod
    def _claims(answer: str) -> list[str]:
        return [
            part.strip()
            for part in re.split(
                r"(?<=[.!?])\s+|\n+",
                answer,
            )
            if part.strip()
        ]

    def evaluate(
        self,
        answer: str,
        evidence: list[dict[str, Any]],
    ) -> dict:

        if not isinstance(answer, str):
            raise ValueError("answer must be string")

        if not isinstance(evidence, list):
            raise ValueError("evidence must be list")

        for item in evidence:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("text"), str)
                or not isinstance(
                    item.get("source_id"), str
                )
                or not item["source_id"].strip()
            ):
                raise ValueError(
                    "Each evidence item needs "
                    "source_id and text"
                )

        claims = self._claims(answer)
        evaluations = []

        for claim in claims:
            claim_tokens = self._tokens(claim)

            matches = []

            for item in evidence:
                evidence_tokens = self._tokens(
                    item["text"]
                )

                score = (
                    len(
                        claim_tokens & evidence_tokens
                    ) / len(claim_tokens)
                    if claim_tokens else 0.0
                )

                matches.append({
                    "source_id": item["source_id"],
                    "overlap_score": round(score, 3),
                })

            best = max(
                matches,
                key=lambda x: x["overlap_score"],
                default=None,
            )

            score = (
                best["overlap_score"]
                if best else 0.0
            )

            evaluations.append({
                "claim": claim,
                "overlap_score": score,
                "supported_by_overlap": (
                    score >= self.threshold
                ),
                "best_source_id": (
                    best["source_id"]
                    if best else None
                ),
            })

        total = len(evaluations)
        supported = sum(
            item["supported_by_overlap"]
            for item in evaluations
        )

        return {
            "claim_count": total,
            "supported_claim_count": supported,
            "unsupported_claim_count": total - supported,
            "groundedness_score": (
                round(supported / total, 3)
                if total else None
            ),
            "claims": evaluations,
            "method": "lexical_overlap",
            "semantic_entailment_verified": False,
            "note": (
                "Overlap does not prove factual "
                "support or detect contradictions."
            ),
        }
