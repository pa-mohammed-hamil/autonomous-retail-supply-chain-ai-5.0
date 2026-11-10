"""Planned module: faithfulness. Implementation pending."""

"""
ai/evaluation/faithfulness.py

Autonomous Retail Supply Chain AI 5.0
RAG Faithfulness Evaluator

Python 3.10+
Standard library only.

Features:
- Claim extraction
- Source-grounded claim evaluation
- Pluggable semantic entailment verifier
- Lexical evidence screening
- Numeric contradiction detection
- Citation validation
- Multi-tenant source validation
- Unsupported claim reporting
- Faithfulness scoring
- JSON report export

Evaluation modes:
1. Heuristic baseline (default)
2. Semantic verifier (recommended)

IMPORTANT:
The heuristic mode is not proof
of factual entailment.

For production-grade faithfulness,
use an independent NLI model or
LLM verifier with structured output
and human-reviewed evaluation data.
"""

from __future__ import annotations

import json
import math
import re

from dataclasses import (
    asdict,
    dataclass,
    field,
)
from pathlib import Path
from typing import (
    Any,
    Callable,
    Iterable,
    Literal,
)


Verdict = Literal[
    "supported",
    "contradicted",
    "insufficient_evidence",
]


@dataclass
class FaithfulnessDocument:
    document_id: str
    content: str
    title: str = ""
    metadata: dict[str, Any] = field(
        default_factory=dict
    )
    source_id: str | None = None


@dataclass
class FaithfulnessConfig:
    min_lexical_overlap: float = 0.65
    max_documents: int = 30
    max_answer_chars: int = 50000
    max_document_chars: int = 20000
    max_claims: int = 100
    require_citations: bool = False


@dataclass
class ClaimFaithfulnessResult:
    claim: str
    verdict: Verdict
    confidence: float
    evidence_document_id: str | None
    evidence_source_id: str | None
    cited_source_ids: list[str]
    lexical_overlap: float
    reason: str
    evaluation_method: str


@dataclass
class FaithfulnessResult:
    answer: str
    tenant_id: str
    total_claims: int
    supported_claims: int
    contradicted_claims: int
    insufficient_evidence_claims: int
    faithfulness_score: float | None
    evaluation_method: str
    claim_results: list[
        ClaimFaithfulnessResult
    ]


class RetailFaithfulnessEvaluator:
    """
    Evaluate whether generated claims
    are grounded in retrieved evidence.

    semantic_verifier signature:

        verifier(
            claim: str,
            evidence: str,
        ) -> dict

    Expected verifier response:

        {
            "verdict": "supported",
            "confidence": 0.95,
            "reason": "Evidence entails claim"
        }

    A semantic verifier must evaluate
    the entire meaning of the claim,
    including quantities, negation,
    dates, units, and entities.

    A verifier's confidence is not
    automatically calibrated.
    """

    CITATION_PATTERN = re.compile(
        r"\[(S\d+)\]"
    )

    TOKEN_PATTERN = re.compile(
        r"[A-Za-z0-9]+"
        r"(?:[-_][A-Za-z0-9]+)*"
    )

    NUMBER_PATTERN = re.compile(
        r"(?<![A-Za-z0-9])"
        r"\d+(?:,\d{3})*(?:\.\d+)?"
        r"(?![A-Za-z0-9])"
    )

    STOPWORDS = {
        "a", "an", "and", "are",
        "as", "at", "be", "by",
        "for", "from", "has",
        "have", "in", "is",
        "it", "of", "on", "or",
        "that", "the", "their",
        "this", "to", "was",
        "were", "with", "which",
    }

    NEGATIONS = {
        "not", "no", "never",
        "without", "none",
        "cannot", "n't",
    }

    def __init__(
        self,
        config: FaithfulnessConfig | None = None,
        semantic_verifier: (
            Callable[
                [str, str],
                dict[str, Any],
            ]
            | None
        ) = None,
    ):
        self.config = (
            config or FaithfulnessConfig()
        )

        self.semantic_verifier = (
            semantic_verifier
        )

        if not (
            0 <= self.config.min_lexical_overlap <= 1
        ):
            raise ValueError(
                "Invalid lexical threshold"
            )

        for limit in (
            self.config.max_documents,
            self.config.max_answer_chars,
            self.config.max_document_chars,
            self.config.max_claims,
        ):
            if limit <= 0:
                raise ValueError(
                    "Limits must be positive"
                )

    @classmethod
    def extract_citations(
        cls,
        text: str,
    ) -> list[str]:
        return list(
            dict.fromkeys(
                cls.CITATION_PATTERN.findall(
                    text
                )
            )
        )

    @classmethod
    def clean_claim(
        cls,
        text: str,
    ) -> str:
        return cls.CITATION_PATTERN.sub(
            "",
            text,
        ).strip()

    @classmethod
    def extract_claims(
        cls,
        answer: str,
    ) -> list[str]:
        """
        Simple sentence-based extraction.

        This is not full atomic claim
        decomposition. Compound claims
        may require a dedicated LLM
        claim extractor.
        """
        parts = re.split(
            r"(?<=[.!?])\s+|\n+",
            answer.strip(),
        )

        return [
            part.strip()
            for part in parts
            if cls.clean_claim(
                part
            )
        ]

    @classmethod
    def tokens(
        cls,
        text: str,
    ) -> set[str]:
        return {
            token.casefold()
            for token in cls.TOKEN_PATTERN.findall(
                text
            )
            if token.casefold()
            not in cls.STOPWORDS
        }

    @classmethod
    def lexical_overlap(
        cls,
        claim: str,
        evidence: str,
    ) -> float:
        claim_tokens = cls.tokens(
            claim
        )

        evidence_tokens = cls.tokens(
            evidence
        )

        if not claim_tokens:
            return 0.0

        return (
            len(
                claim_tokens
                & evidence_tokens
            )
            / len(claim_tokens)
        )

    @classmethod
    def numeric_values(
        cls,
        text: str,
    ) -> set[str]:
        return {
            value.replace(
                ",",
                "",
            )
            for value in cls.NUMBER_PATTERN.findall(
                text
            )
        }

    @classmethod
    def numeric_mismatch(
        cls,
        claim: str,
        evidence: str,
    ) -> bool:
        """
        Conservative numeric screening.

        A mismatch is flagged when
        claim numbers are absent from
        the candidate evidence.

        This does NOT establish a
        contradiction, since evidence
        may contain multiple records,
        different units, or arithmetic.
        """
        claim_numbers = (
            cls.numeric_values(
                claim
            )
        )

        evidence_numbers = (
            cls.numeric_values(
                evidence
            )
        )

        return bool(
            claim_numbers
            - evidence_numbers
        )

    @staticmethod
    def _field(
        document: Any,
        name: str,
        default: Any = None,
    ) -> Any:
        if isinstance(
            document,
            dict,
        ):
            return document.get(
                name,
                default,
            )

        return getattr(
            document,
            name,
            default,
        )

    def _normalize_documents(
        self,
        documents: Iterable[Any],
        tenant_id: str,
    ) -> list[FaithfulnessDocument]:
        normalized = []
        seen = set()
        seen_sources = set()

        for document in documents:
            if (
                len(normalized)
                >= self.config.max_documents
            ):
                raise ValueError(
                    "Document limit exceeded"
                )

            document_id = self._field(
                document,
                "document_id",
            )

            content = self._field(
                document,
                "content",
                "",
            )

            title = self._field(
                document,
                "title",
                "",
            )

            metadata = self._field(
                document,
                "metadata",
                {},
            )

            source_id = self._field(
                document,
                "source_id",
            )

            if (
                not isinstance(
                    document_id,
                    str,
                )
                or not document_id.strip()
            ):
                raise ValueError(
                    "Invalid document ID"
                )

            if (
                not isinstance(
                    content,
                    str,
                )
                or not content.strip()
            ):
                raise ValueError(
                    "Invalid evidence content"
                )

            if not isinstance(
                metadata,
                dict,
            ):
                raise ValueError(
                    "Invalid metadata"
                )

            if (
                metadata.get(
                    "tenant_id"
                )
                != tenant_id
            ):
                raise PermissionError(
                    "Cross-tenant evidence"
                )

            if document_id in seen:
                continue

            seen.add(document_id)

            if source_id is not None:
                if (
                    not isinstance(
                        source_id,
                        str,
                    )
                    or not re.fullmatch(
                        r"S\d+",
                        source_id,
                    )
                ):
                    raise ValueError(
                        "Invalid source ID"
                    )

                if source_id in seen_sources:
                    raise ValueError(
                        "Duplicate source ID"
                    )

                seen_sources.add(
                    source_id
                )

            normalized.append(
                FaithfulnessDocument(
                    document_id=document_id,
                    content=content[
                        :self.config.max_document_chars
                    ],
                    title=str(
                        title or ""
                    ),
                    metadata=dict(
                        metadata
                    ),
                    source_id=source_id,
                )
            )

        return normalized

    def _semantic_evaluate(
        self,
        claim: str,
        evidence: str,
    ) -> tuple[
        Verdict,
        float,
        str,
    ]:
        if self.semantic_verifier is None:
            raise RuntimeError(
                "Semantic verifier unavailable"
            )

        response = (
            self.semantic_verifier(
                claim,
                evidence,
            )
        )

        if not isinstance(
            response,
            dict,
        ):
            raise ValueError(
                "Verifier must return a dict"
            )

        verdict = response.get(
            "verdict"
        )

        if verdict not in (
            "supported",
            "contradicted",
            "insufficient_evidence",
        ):
            raise ValueError(
                "Invalid verifier verdict"
            )

        confidence = response.get(
            "confidence",
            0.0,
        )

        if (
            isinstance(
                confidence,
                bool,
            )
            or not isinstance(
                confidence,
                (int, float),
            )
            or not math.isfinite(
                confidence
            )
            or not 0 <= confidence <= 1
        ):
            raise ValueError(
                "Invalid verifier confidence"
            )

        reason = str(
            response.get(
                "reason",
                "",
            )
        )[:1000]

        return (
            verdict,
            float(confidence),
            reason,
        )

    def _heuristic_evaluate(
        self,
        claim: str,
        evidence: str,
    ) -> tuple[
        Verdict,
        float,
        str,
    ]:
        overlap = (
            self.lexical_overlap(
                claim,
                evidence,
            )
        )

        if self.numeric_mismatch(
            claim,
            evidence,
        ):
            return (
                "insufficient_evidence",
                0.0,
                "Claim numbers are not "
                "fully present in evidence.",
            )

        if (
            overlap
            >= self.config.min_lexical_overlap
        ):
            return (
                "supported",
                overlap,
                "Lexical screening passed; "
                "semantic entailment "
                "has not been verified.",
            )

        return (
            "insufficient_evidence",
            overlap,
            "Insufficient lexical overlap.",
        )

    def _evaluate_claim(
        self,
        claim_text: str,
        documents: list[
            FaithfulnessDocument
        ],
    ) -> ClaimFaithfulnessResult:
        citations = (
            self.extract_citations(
                claim_text
            )
        )

        claim = self.clean_claim(
            claim_text
        )

        source_map = {
            document.source_id: document
            for document in documents
            if document.source_id
        }

        invalid_citations = [
            citation
            for citation in citations
            if citation not in source_map
        ]

        if invalid_citations:
            return ClaimFaithfulnessResult(
                claim=claim,
                verdict="insufficient_evidence",
                confidence=0.0,
                evidence_document_id=None,
                evidence_source_id=None,
                cited_source_ids=citations,
                lexical_overlap=0.0,
                reason=(
                    "Unknown citation IDs: "
                    + ", ".join(
                        invalid_citations
                    )
                ),
                evaluation_method="validation",
            )

        if (
            self.config.require_citations
            and not citations
        ):
            return ClaimFaithfulnessResult(
                claim=claim,
                verdict="insufficient_evidence",
                confidence=0.0,
                evidence_document_id=None,
                evidence_source_id=None,
                cited_source_ids=[],
                lexical_overlap=0.0,
                reason="Claim has no citation.",
                evaluation_method="validation",
            )

        candidates = (
            [
                source_map[citation]
                for citation in citations
            ]
            if citations
            else documents
        )

        if not candidates:
            return ClaimFaithfulnessResult(
                claim=claim,
                verdict="insufficient_evidence",
                confidence=0.0,
                evidence_document_id=None,
                evidence_source_id=None,
                cited_source_ids=citations,
                lexical_overlap=0.0,
                reason="No evidence available.",
                evaluation_method="validation",
            )

        evaluations = []

        for document in candidates:
            overlap = (
                self.lexical_overlap(
                    claim,
                    document.content,
                )
            )

            if self.semantic_verifier:
                verdict, confidence, reason = (
                    self._semantic_evaluate(
                        claim,
                        document.content,
                    )
                )

                method = "semantic_verifier"
            else:
                verdict, confidence, reason = (
                    self._heuristic_evaluate(
                        claim,
                        document.content,
                    )
                )

                method = "lexical_heuristic"

            evaluations.append(
                (
                    document,
                    verdict,
                    confidence,
                    reason,
                    overlap,
                    method,
                )
            )

        # Prefer supporting evidence.
        # Otherwise report contradiction
        # if a verifier found one.
        # Finally report insufficient
        # evidence.
        verdict_priority = {
            "supported": 2,
            "contradicted": 1,
            "insufficient_evidence": 0,
        }

        evaluations.sort(
            key=lambda item: (
                verdict_priority[
                    item[1]
                ],
                item[2],
                item[4],
            ),
            reverse=True,
        )

        (
            best_document,
            verdict,
            confidence,
            reason,
            overlap,
            method,
        ) = evaluations[0]

        return ClaimFaithfulnessResult(
            claim=claim,
            verdict=verdict,
            confidence=round(
                confidence,
                4,
            ),
            evidence_document_id=(
                best_document.document_id
            ),
            evidence_source_id=(
                best_document.source_id
            ),
            cited_source_ids=citations,
            lexical_overlap=round(
                overlap,
                4,
            ),
            reason=reason,
            evaluation_method=method,
        )

    def evaluate(
        self,
        answer: str,
        documents: Iterable[Any],
        tenant_id: str,
    ) -> FaithfulnessResult:
        if (
            not isinstance(
                answer,
                str,
            )
            or not answer.strip()
        ):
            raise ValueError(
                "Answer required"
            )

        if (
            len(answer)
            > self.config.max_answer_chars
        ):
            raise ValueError(
                "Answer too long"
            )

        if (
            not isinstance(
                tenant_id,
                str,
            )
            or not tenant_id.strip()
        ):
            raise ValueError(
                "Tenant ID required"
            )

        documents = (
            self._normalize_documents(
                documents,
                tenant_id,
            )
        )

        claims = self.extract_claims(
            answer
        )

        if (
            len(claims)
            > self.config.max_claims
        ):
            raise ValueError(
                "Claim limit exceeded"
            )

        results = [
            self._evaluate_claim(
                claim,
                documents,
            )
            for claim in claims
        ]

        supported = sum(
            item.verdict == "supported"
            for item in results
        )

        contradicted = sum(
            item.verdict == "contradicted"
            for item in results
        )

        insufficient = sum(
            item.verdict
            == "insufficient_evidence"
            for item in results
        )

        score = (
            supported / len(results)
            if results
            else None
        )

        return FaithfulnessResult(
            answer=answer,
            tenant_id=tenant_id,
            total_claims=len(results),
            supported_claims=supported,
            contradicted_claims=contradicted,
            insufficient_evidence_claims=(
                insufficient
            ),
            faithfulness_score=(
                round(score, 4)
                if score is not None
                else None
            ),
            evaluation_method=(
                "semantic_verifier"
                if self.semantic_verifier
                else "lexical_heuristic"
            ),
            claim_results=results,
        )

    @staticmethod
    def export_json(
        result: FaithfulnessResult,
        output_path: str | Path,
    ) -> Path:
        output = Path(
            output_path
        )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            json.dumps(
                asdict(result),
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return output


if __name__ == "__main__":
    documents = [
        FaithfulnessDocument(
            document_id="inventory-001",
            source_id="S1",
            title="Inventory Report",
            content=(
                "SKU001 has 12 units remaining. "
                "The reorder point is 40 units."
            ),
            metadata={
                "tenant_id": "demo",
            },
        ),
        FaithfulnessDocument(
            document_id="supplier-001",
            source_id="S2",
            title="Supplier Report",
            content=(
                "Supplier SUP002 has an "
                "eight-day delivery lead time."
            ),
            metadata={
                "tenant_id": "demo",
            },
        ),
    ]

    answer = (
        "SKU001 has 12 units remaining [S1]. "
        "The reorder point is 40 units [S1]. "
        "Supplier SUP002 has an "
        "eight-day lead time [S2]."
    )

    evaluator = (
        RetailFaithfulnessEvaluator(
            FaithfulnessConfig(
                require_citations=True,
            )
        )
    )

    result = evaluator.evaluate(
        answer=answer,
        documents=documents,
        tenant_id="demo",
    )

    print(
        json.dumps(
            asdict(result),
            indent=2,
        )
    )

    evaluator.export_json(
        result,
        "reports/faithfulness.json",
    )
