
"""
ai/llmops/hallucination_monitor.py

Grounded-answer and hallucination monitoring for
Autonomous Retail Supply Chain AI 5.0.

Features:
- Claim-level evidence checking
- Citation reference validation
- Evidence coverage scoring
- Contradiction and unsupported-claim tracking
- Optional trusted NLI verification callback
- Confidence-based review decisions
- Hallucination risk estimation
- Human review escalation
- SQLite audit persistence
- Evaluation summaries

Standard library only.

Important:
Lexical similarity does not prove factual
entailment. Without a trusted verifier, the
monitor cannot confirm factual correctness.

This module never labels an answer "verified"
using keyword overlap alone.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import uuid

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Any


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(
            r"\b[a-zA-Z0-9]+\b",
            text.lower(),
        )
        if len(token) > 2
    }


@dataclass(frozen=True)
class EvidenceDocument:
    source_id: str
    text: str
    trusted: bool = True

    def __post_init__(self):
        if not self.source_id.strip():
            raise ValueError("Source ID required")

        if not isinstance(self.text, str):
            raise ValueError("Evidence text required")


@dataclass(frozen=True)
class Claim:
    claim_id: str
    text: str
    cited_source_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.claim_id.strip():
            raise ValueError("Claim ID required")

        if not self.text.strip():
            raise ValueError("Claim text required")


@dataclass(frozen=True)
class HallucinationConfig:
    database_path: str = (
        "data/llmops/hallucination_monitor.db"
    )
    lexical_similarity_threshold: float = 0.45
    maximum_unverified_ratio: float = 0.20
    require_citations: bool = True

    def __post_init__(self):
        for value in (
            self.lexical_similarity_threshold,
            self.maximum_unverified_ratio,
        ):
            if not 0 <= value <= 1:
                raise ValueError("Threshold must be 0-1")


# A verifier must return one of:
# "entailed", "contradicted", "unknown".
#
# It must independently assess whether the
# supplied evidence supports the claim.
Verifier = Callable[
    [str, str],
    str,
]


class HallucinationMonitor:

    def __init__(
        self,
        config: HallucinationConfig | None = None,
        verifier: Verifier | None = None,
    ):
        self.config = config or HallucinationConfig()
        self.verifier = verifier

        path = Path(self.config.database_path)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.db = sqlite3.connect(
            str(path),
            timeout=30,
        )
        self.db.row_factory = sqlite3.Row

        self.db.execute("""
            CREATE TABLE IF NOT EXISTS hallucination_checks (
                check_id TEXT PRIMARY KEY,
                trace_id TEXT,
                agent_name TEXT NOT NULL,
                claim_count INTEGER NOT NULL,
                supported_count INTEGER NOT NULL,
                contradicted_count INTEGER NOT NULL,
                unverified_count INTEGER NOT NULL,
                invalid_citation_count INTEGER NOT NULL,
                evidence_coverage REAL NOT NULL,
                risk_score REAL NOT NULL,
                status TEXT NOT NULL,
                checked_at TEXT NOT NULL
            )
        """)

        self.db.commit()

    @staticmethod
    def lexical_similarity(
        claim_text: str,
        evidence_text: str,
    ) -> float:
        claim_tokens = tokenize(claim_text)
        evidence_tokens = tokenize(evidence_text)

        if not claim_tokens:
            return 0.0

        return len(
            claim_tokens & evidence_tokens
        ) / len(claim_tokens)

    def evaluate_claim(
        self,
        claim: Claim,
        evidence: list[EvidenceDocument],
    ) -> dict:
        sources = {
            item.source_id: item
            for item in evidence
        }

        if len(sources) != len(evidence):
            raise ValueError(
                "Duplicate evidence source IDs"
            )

        invalid_citations = [
            source_id
            for source_id in claim.cited_source_ids
            if source_id not in sources
        ]

        if self.config.require_citations:
            selected = [
                sources[source_id]
                for source_id in claim.cited_source_ids
                if source_id in sources
                and sources[source_id].trusted
            ]
        else:
            selected = [
                item
                for item in evidence
                if item.trusted
            ]

        if not selected:
            return {
                "claim_id": claim.claim_id,
                "status": "unverified",
                "best_source_id": None,
                "lexical_similarity": 0.0,
                "invalid_citations": invalid_citations,
                "verification_method": "none",
            }

        ranked = sorted(
            (
                (
                    self.lexical_similarity(
                        claim.text,
                        item.text,
                    ),
                    item,
                )
                for item in selected
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )

        best_similarity, best_source = ranked[0]

        status = "unverified"
        method = "lexical_screening"

        if self.verifier is not None:
            # Assess every eligible source. One
            # source contradicting a claim is a
            # review signal even if another entails it.
            verdicts = []

            for _, source in ranked:
                verdict = self.verifier(
                    claim.text,
                    source.text,
                )

                if verdict not in {
                    "entailed",
                    "contradicted",
                    "unknown",
                }:
                    raise ValueError(
                        "Invalid verifier result"
                    )

                verdicts.append(verdict)

            method = "external_verifier"

            if "contradicted" in verdicts:
                status = "contradicted"
            elif "entailed" in verdicts:
                status = "supported"

        return {
            "claim_id": claim.claim_id,
            "status": status,
            "best_source_id": best_source.source_id,
            "lexical_similarity": round(
                best_similarity, 4
            ),
            "invalid_citations": invalid_citations,
            "verification_method": method,
            "needs_review": (
                status != "supported"
                or bool(invalid_citations)
            ),
        }

    def evaluate(
        self,
        agent_name: str,
        claims: list[Claim],
        evidence: list[EvidenceDocument],
        trace_id: str | None = None,
        persist: bool = True,
    ) -> dict:
        if not agent_name.strip():
            raise ValueError("Agent name required")

        if not claims:
            raise ValueError(
                "At least one claim required"
            )

        claim_ids = [item.claim_id for item in claims]

        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError(
                "Duplicate claim IDs"
            )

        results = [
            self.evaluate_claim(
                claim,
                evidence,
            )
            for claim in claims
        ]

        total = len(results)

        supported = sum(
            item["status"] == "supported"
            for item in results
        )

        contradicted = sum(
            item["status"] == "contradicted"
            for item in results
        )

        unverified = sum(
            item["status"] == "unverified"
            for item in results
        )

        invalid_citations = sum(
            len(item["invalid_citations"])
            for item in results
        )

        # Coverage means a claim has a valid,
        # trusted cited source. It does not
        # establish that the source supports it.
        coverage = sum(
            item["best_source_id"] is not None
            for item in results
        ) / total

        # Conservative review-priority score,
        # not a calibrated hallucination probability.
        risk_score = min(
            1.0,
            (
                unverified
                + contradicted * 1.5
            ) / total
            + min(
                invalid_citations / total * 0.2,
                0.2,
            ),
        )

        if contradicted > 0:
            status = "contradiction_detected"
        elif unverified / total > (
            self.config.maximum_unverified_ratio
        ):
            status = "human_review_required"
        elif invalid_citations:
            status = "citation_review_required"
        elif self.verifier is None:
            status = "verification_unavailable"
        else:
            status = "passed"

        check_id = uuid.uuid4().hex

        report = {
            "check_id": check_id,
            "trace_id": trace_id,
            "agent_name": agent_name,
            "claim_count": total,
            "supported_count": supported,
            "contradicted_count": contradicted,
            "unverified_count": unverified,
            "invalid_citation_count": invalid_citations,
            "evidence_coverage": round(coverage, 4),
            "risk_score": round(risk_score, 4),
            "risk_score_type": (
                "heuristic_review_priority"
            ),
            "status": status,
            "requires_human_review": (
                status != "passed"
            ),
            "claims": results,
            "checked_at": utc_now(),
        }

        if persist:
            self._persist(report)

        return report

    def _persist(self, report: dict) -> None:
        with self.db:
            self.db.execute(
                """
                INSERT INTO hallucination_checks (
                    check_id, trace_id, agent_name,
                    claim_count, supported_count,
                    contradicted_count, unverified_count,
                    invalid_citation_count,
                    evidence_coverage, risk_score,
                    status, checked_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report["check_id"],
                    report["trace_id"],
                    report["agent_name"],
                    report["claim_count"],
                    report["supported_count"],
                    report["contradicted_count"],
                    report["unverified_count"],
                    report["invalid_citation_count"],
                    report["evidence_coverage"],
                    report["risk_score"],
                    report["status"],
                    report["checked_at"],
                ),
            )

    def summary(
        self,
        agent_name: str | None = None,
    ) -> dict:
        query = (
            "SELECT * FROM hallucination_checks"
        )
        params = []

        if agent_name:
            query += " WHERE agent_name = ?"
            params.append(agent_name)

        rows = self.db.execute(
            query, params
        ).fetchall()

        total_claims = sum(
            row["claim_count"] for row in rows
        )

        return {
            "evaluation_count": len(rows),
            "claim_count": total_claims,
            "supported_count": sum(
                row["supported_count"]
                for row in rows
            ),
            "contradicted_count": sum(
                row["contradicted_count"]
                for row in rows
            ),
            "unverified_count": sum(
                row["unverified_count"]
                for row in rows
            ),
            "human_review_count": sum(
                row["status"] != "passed"
                for row in rows
            ),
            "average_risk_score": (
                round(
                    sum(
                        row["risk_score"]
                        for row in rows
                    ) / len(rows),
                    4,
                )
                if rows
                else None
            ),
            "raw_claim_text_stored": False,
        }

    def close(self):
        self.db.close()


if __name__ == "__main__":
    monitor = HallucinationMonitor()

    evidence = [
        EvidenceDocument(
            source_id="inventory-snapshot-001",
            text=(
                "SKU-101 has 160 available units "
                "at warehouse WH-KOCHI."
            ),
        )
    ]

    claims = [
        Claim(
            claim_id="claim-001",
            text="SKU-101 has 160 available units.",
            cited_source_ids=(
                "inventory-snapshot-001",
            ),
        ),
        Claim(
            claim_id="claim-002",
            text="SKU-101 will sell out tomorrow.",
            cited_source_ids=(
                "inventory-snapshot-001",
            ),
        ),
    ]

    # No trusted entailment verifier supplied.
    # Both claims remain unverified, even if
    # lexical similarity is high.
    result = monitor.evaluate(
        agent_name="inventory_agent",
        claims=claims,
        evidence=evidence,
        trace_id="trace-inventory-001",
    )

    print(
        json.dumps(
            result,
            indent=2,
        )
    )

    print(
        json.dumps(
            monitor.summary(),
            indent=2,
        )
    )

    monitor.close()
