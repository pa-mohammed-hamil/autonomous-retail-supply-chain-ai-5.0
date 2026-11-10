"""Planned module: context precision. Implementation pending."""

"""
ai/evaluation/context_precision.py

Autonomous Retail Supply Chain AI 5.0
RAG Context Precision Evaluator

Python 3.10+
Standard library only.

Features:
- Context Precision@K
- Average Precision@K
- Precision@K
- Relevant context count
- Irrelevant context count
- Missing relevance labels
- Rank-level evaluation
- Multiple-query aggregation
- JSON report export
- Retrieval result compatibility
- Optional custom relevance judge

Evaluation modes:
1. Human-labeled relevance
2. Custom automated relevance judge

IMPORTANT:
- Relevance labels are preferred.
- Automated relevance judges can be wrong.
- Missing labels must not be silently
  treated as irrelevant.
- Do not confuse context precision
  with factual answer faithfulness.
"""

from __future__ import annotations

import json
import math
import statistics

from dataclasses import (
    asdict,
    dataclass,
    field,
)
from pathlib import Path
from typing import Any, Callable, Iterable


@dataclass
class ContextDocument:
    document_id: str
    content: str
    title: str = ""
    metadata: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass
class ContextPrecisionConfig:
    k_values: tuple[int, ...] = (
        1, 3, 5, 10
    )
    relevance_threshold: float = 0.5
    require_complete_labels: bool = True
    deduplicate: bool = True


@dataclass
class RankedContextResult:
    rank: int
    document_id: str
    relevance: float | None
    relevant: bool | None
    precision_at_rank: float | None


@dataclass
class ContextPrecisionResult:
    query_id: str
    query: str
    tenant_id: str
    retrieved_count: int
    relevant_count: int
    irrelevant_count: int
    unjudged_count: int
    metrics: dict[str, float | None]
    ranked_contexts: list[
        RankedContextResult
    ]


@dataclass
class ContextPrecisionReport:
    total_queries: int
    evaluated_queries: int
    metrics: dict[str, float | None]
    results: list[
        ContextPrecisionResult
    ]


class RetailContextPrecisionEvaluator:
    """
    Evaluate ranked retrieved contexts.

    Context Precision@K:
        Sum of precision at each
        relevant rank, divided by
        number of relevant items
        retrieved within top K.

    AP@K:
        Sum of precision at relevant
        ranks, divided by the smaller
        of total relevant items and K.

    Precision@K:
        Relevant retrieved documents
        divided by K.

    A relevance judgment may be:
        0.0 = irrelevant
        1.0 = relevant

    Intermediate grades are allowed.
    """

    def __init__(
        self,
        config: ContextPrecisionConfig | None = None,
        relevance_judge: (
            Callable[
                [str, ContextDocument],
                float,
            ]
            | None
        ) = None,
    ):
        self.config = (
            config or ContextPrecisionConfig()
        )

        self.relevance_judge = (
            relevance_judge
        )

        self.k_values = tuple(
            sorted(
                set(
                    self.config.k_values
                )
            )
        )

        if (
            not self.k_values
            or any(
                isinstance(k, bool)
                or not isinstance(k, int)
                or k <= 0
                for k in self.k_values
            )
        ):
            raise ValueError(
                "Invalid k_values"
            )

        if not (
            0 <= self.config.relevance_threshold <= 1
        ):
            raise ValueError(
                "Invalid relevance threshold"
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
    ) -> list[ContextDocument]:
        normalized = []
        seen = set()

        for document in documents:
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

            if not isinstance(
                content,
                str,
            ):
                raise ValueError(
                    "Invalid document content"
                )

            if not isinstance(
                metadata,
                dict,
            ):
                raise ValueError(
                    "Invalid document metadata"
                )

            if (
                metadata.get(
                    "tenant_id"
                )
                != tenant_id
            ):
                raise PermissionError(
                    "Cross-tenant context detected"
                )

            if (
                self.config.deduplicate
                and document_id in seen
            ):
                continue

            seen.add(
                document_id
            )

            normalized.append(
                ContextDocument(
                    document_id=document_id,
                    content=content,
                    title=str(
                        title or ""
                    ),
                    metadata=dict(
                        metadata
                    ),
                )
            )

        return normalized

    @staticmethod
    def _validate_relevance(
        value: Any,
    ) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(
                value,
                (int, float),
            )
        ):
            raise ValueError(
                "Relevance must be numeric"
            )

        value = float(
            value
        )

        if (
            not math.isfinite(value)
            or not 0 <= value <= 1
        ):
            raise ValueError(
                "Relevance must be "
                "between 0 and 1"
            )

        return value

    def _get_relevance(
        self,
        query: str,
        document: ContextDocument,
        relevance_labels: dict[
            str,
            float,
        ],
    ) -> float | None:
        if (
            document.document_id
            in relevance_labels
        ):
            return self._validate_relevance(
                relevance_labels[
                    document.document_id
                ]
            )

        if self.relevance_judge is not None:
            return self._validate_relevance(
                self.relevance_judge(
                    query,
                    document,
                )
            )

        return None

    @staticmethod
    def _precision_at_k(
        relevant_flags: list[bool],
        k: int,
    ) -> float:
        hits = sum(
            relevant_flags[:k]
        )

        return hits / k

    @staticmethod
    def _context_precision_at_k(
        relevant_flags: list[bool],
        k: int,
    ) -> float:
        hits = 0
        precision_sum = 0.0

        for rank, is_relevant in enumerate(
            relevant_flags[:k],
            start=1,
        ):
            if is_relevant:
                hits += 1
                precision_sum += (
                    hits / rank
                )

        if hits == 0:
            return 0.0

        return (
            precision_sum / hits
        )

    @staticmethod
    def _average_precision_at_k(
        relevant_flags: list[bool],
        k: int,
        total_relevant: int,
    ) -> float:
        if total_relevant <= 0:
            return 0.0

        hits = 0
        precision_sum = 0.0

        for rank, is_relevant in enumerate(
            relevant_flags[:k],
            start=1,
        ):
            if is_relevant:
                hits += 1
                precision_sum += (
                    hits / rank
                )

        return (
            precision_sum
            / min(
                total_relevant,
                k,
            )
        )

    def evaluate(
        self,
        query: str,
        documents: Iterable[Any],
        tenant_id: str,
        relevance_labels: (
            dict[str, float] | None
        ) = None,
        query_id: str = "query-001",
        total_relevant: int | None = None,
    ) -> ContextPrecisionResult:
        if (
            not isinstance(
                query,
                str,
            )
            or not query.strip()
        ):
            raise ValueError(
                "Query required"
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

        labels = (
            relevance_labels or {}
        )

        for value in labels.values():
            self._validate_relevance(
                value
            )

        normalized = (
            self._normalize_documents(
                documents,
                tenant_id,
            )
        )

        ranked_contexts = []
        relevant_flags = []
        unjudged_ranks = []

        relevant_count = 0
        irrelevant_count = 0
        unjudged_count = 0

        for rank, document in enumerate(
            normalized,
            start=1,
        ):
            relevance = (
                self._get_relevance(
                    query,
                    document,
                    labels,
                )
            )

            if relevance is None:
                is_relevant = None
                unjudged_count += 1
                unjudged_ranks.append(
                    rank
                )
            else:
                is_relevant = (
                    relevance
                    >= self.config.relevance_threshold
                )

                if is_relevant:
                    relevant_count += 1
                else:
                    irrelevant_count += 1

            relevant_flags.append(
                bool(is_relevant)
            )

            precision_at_rank = (
                None
                if is_relevant is None
                else (
                    sum(
                        relevant_flags[:rank]
                    ) / rank
                )
            )

            ranked_contexts.append(
                RankedContextResult(
                    rank=rank,
                    document_id=(
                        document.document_id
                    ),
                    relevance=relevance,
                    relevant=is_relevant,
                    precision_at_rank=(
                        precision_at_rank
                    ),
                )
            )

        if total_relevant is not None:
            if (
                isinstance(
                    total_relevant,
                    bool,
                )
                or not isinstance(
                    total_relevant,
                    int,
                )
                or total_relevant < 0
            ):
                raise ValueError(
                    "Invalid total_relevant"
                )

            if total_relevant < relevant_count:
                raise ValueError(
                    "total_relevant is smaller "
                    "than retrieved relevant count"
                )

        metrics = {}

        for k in self.k_values:
            has_missing = any(
                rank <= k
                for rank in unjudged_ranks
            )

            if (
                has_missing
                and self.config.require_complete_labels
            ):
                metrics[
                    f"context_precision@{k}"
                ] = None

                metrics[
                    f"precision@{k}"
                ] = None

                metrics[
                    f"ap@{k}"
                ] = None

                continue

            metrics[
                f"context_precision@{k}"
            ] = round(
                self._context_precision_at_k(
                    relevant_flags,
                    k,
                ),
                6,
            )

            metrics[
                f"precision@{k}"
            ] = round(
                self._precision_at_k(
                    relevant_flags,
                    k,
                ),
                6,
            )

            metrics[
                f"ap@{k}"
            ] = (
                round(
                    self._average_precision_at_k(
                        relevant_flags,
                        k,
                        total_relevant,
                    ),
                    6,
                )
                if total_relevant is not None
                else None
            )

        return ContextPrecisionResult(
            query_id=query_id,
            query=query,
            tenant_id=tenant_id,
            retrieved_count=len(
                normalized
            ),
            relevant_count=relevant_count,
            irrelevant_count=irrelevant_count,
            unjudged_count=unjudged_count,
            metrics=metrics,
            ranked_contexts=ranked_contexts,
        )

    @staticmethod
    def aggregate(
        results: Iterable[
            ContextPrecisionResult
        ],
    ) -> ContextPrecisionReport:
        results = list(
            results
        )

        if not results:
            raise ValueError(
                "Evaluation results required"
            )

        metric_names = sorted({
            name
            for result in results
            for name in result.metrics
        })

        averages = {}

        for metric in metric_names:
            values = [
                result.metrics.get(
                    metric
                )
                for result in results
            ]

            valid = [
                value
                for value in values
                if value is not None
            ]

            averages[
                metric
            ] = (
                round(
                    statistics.mean(
                        valid
                    ),
                    6,
                )
                if valid
                else None
            )

        evaluated_queries = sum(
            any(
                value is not None
                for value in (
                    result.metrics.values()
                )
            )
            for result in results
        )

        return ContextPrecisionReport(
            total_queries=len(
                results
            ),
            evaluated_queries=(
                evaluated_queries
            ),
            metrics=averages,
            results=results,
        )

    @staticmethod
    def export_json(
        result: (
            ContextPrecisionResult
            | ContextPrecisionReport
        ),
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
        ContextDocument(
            document_id="inventory-001",
            title="Inventory Risk",
            content=(
                "SKU001 has 12 units left. "
                "Reorder point is 40 units."
            ),
            metadata={
                "tenant_id": "demo",
            },
        ),
        ContextDocument(
            document_id="supplier-001",
            title="Supplier Overview",
            content=(
                "Supplier SUP002 provides "
                "packaging materials."
            ),
            metadata={
                "tenant_id": "demo",
            },
        ),
        ContextDocument(
            document_id="inventory-002",
            title="Inventory Forecast",
            content=(
                "SKU002 is expected to "
                "run out of stock."
            ),
            metadata={
                "tenant_id": "demo",
            },
        ),
    ]

    evaluator = (
        RetailContextPrecisionEvaluator(
            ContextPrecisionConfig(
                k_values=(1, 3, 5),
            )
        )
    )

    result = evaluator.evaluate(
        query=(
            "Which SKUs are at "
            "risk of stockout?"
        ),
        documents=documents,
        tenant_id="demo",
        relevance_labels={
            "inventory-001": 1.0,
            "supplier-001": 0.0,
            "inventory-002": 1.0,
        },
        total_relevant=2,
    )

    print(
        json.dumps(
            asdict(result),
            indent=2,
        )
    )

    evaluator.export_json(
        result,
        "reports/context_precision.json",
    )
