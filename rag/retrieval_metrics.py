"""Planned module: retrieval metrics. Implementation pending."""

"""
ai/evaluation/retrieval_metrics.py

Autonomous Retail Supply Chain AI 5.0
Information Retrieval Metrics

Python 3.10+
Dependencies: standard library only

Metrics:
- Precision@K
- Recall@K
- Hit Rate@K
- MRR@K
- MAP@K
- nDCG@K
- R-Precision
- F1@K
- Coverage
- Query-level evaluation
- Macro-averaged metrics
- JSON and CSV export

Ground truth:
    query_id -> {
        document_id: relevance_grade
    }

Relevance grades:
    0 = irrelevant
    1 = somewhat relevant
    2 = relevant
    3 = highly relevant

Binary relevance is defined by
a configurable relevance threshold.

IMPORTANT:
Ground-truth judgments should be
complete for the evaluated pool.
Unjudged retrieved documents are
not automatically irrelevant.
"""

from __future__ import annotations

import csv
import json
import math
import statistics

from dataclasses import (
    asdict,
    dataclass,
    field,
)
from pathlib import Path
from typing import Any, Iterable


@dataclass
class RetrievalMetricsConfig:
    k_values: tuple[int, ...] = (
        1, 3, 5, 10
    )
    relevance_threshold: float = 1.0
    require_complete_judgments: bool = True
    deduplicate: bool = True


@dataclass
class RetrievalQuery:
    query_id: str
    retrieved_ids: list[str]
    relevance_grades: dict[str, float]
    relevant_document_count: int | None = None
    judged_document_ids: set[str] | None = None


@dataclass
class QueryMetricsResult:
    query_id: str
    retrieved_count: int
    relevant_count: int
    unjudged_count: int
    metrics: dict[str, float | None]
    missing_relevant_ids: list[str]


@dataclass
class RetrievalMetricsReport:
    total_queries: int
    macro_metrics: dict[str, float | None]
    metric_query_counts: dict[str, int]
    query_results: list[
        QueryMetricsResult
    ]


class RetailRetrievalMetrics:
    """
    Standard information retrieval
    evaluation for ranked document IDs.

    Recall@K:
        relevant retrieved in top K /
        all relevant documents

    Precision@K:
        relevant retrieved in top K / K

    AP@K:
        sum precision at relevant ranks /
        min(number relevant, K)

    MRR@K:
        reciprocal rank of first
        relevant result within K

    nDCG@K:
        DCG@K / ideal DCG@K

    All calculations assume
    a fixed evaluation corpus.
    """

    def __init__(
        self,
        config: RetrievalMetricsConfig | None = None,
    ):
        self.config = (
            config or RetrievalMetricsConfig()
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
                "k_values must be "
                "positive integers"
            )

        threshold = (
            self.config.relevance_threshold
        )

        if (
            isinstance(threshold, bool)
            or not isinstance(
                threshold,
                (int, float),
            )
            or not math.isfinite(
                threshold
            )
            or threshold <= 0
        ):
            raise ValueError(
                "Invalid relevance threshold"
            )

    @staticmethod
    def _validate_grades(
        grades: dict[str, float],
    ) -> None:
        for document_id, grade in (
            grades.items()
        ):
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
                isinstance(grade, bool)
                or not isinstance(
                    grade,
                    (int, float),
                )
                or not math.isfinite(
                    grade
                )
                or grade < 0
            ):
                raise ValueError(
                    "Relevance grades must "
                    "be finite and nonnegative"
                )

    @staticmethod
    def _deduplicate(
        ids: Iterable[str],
    ) -> list[str]:
        seen = set()
        result = []

        for document_id in ids:
            if (
                not isinstance(
                    document_id,
                    str,
                )
                or not document_id.strip()
            ):
                raise ValueError(
                    "Invalid retrieved ID"
                )

            if document_id in seen:
                continue

            seen.add(document_id)
            result.append(document_id)

        return result

    @staticmethod
    def _precision(
        retrieved: list[str],
        relevant: set[str],
        k: int,
    ) -> float:
        hits = sum(
            document_id in relevant
            for document_id in retrieved[:k]
        )

        return hits / k

    @staticmethod
    def _recall(
        retrieved: list[str],
        relevant: set[str],
        total_relevant: int,
        k: int,
    ) -> float:
        if total_relevant == 0:
            return 0.0

        hits = sum(
            document_id in relevant
            for document_id in retrieved[:k]
        )

        return hits / total_relevant

    @staticmethod
    def _hit_rate(
        retrieved: list[str],
        relevant: set[str],
        k: int,
    ) -> float:
        return float(
            any(
                document_id in relevant
                for document_id in retrieved[:k]
            )
        )

    @staticmethod
    def _mrr(
        retrieved: list[str],
        relevant: set[str],
        k: int,
    ) -> float:
        for rank, document_id in enumerate(
            retrieved[:k],
            start=1,
        ):
            if document_id in relevant:
                return 1.0 / rank

        return 0.0

    @staticmethod
    def _average_precision(
        retrieved: list[str],
        relevant: set[str],
        total_relevant: int,
        k: int,
    ) -> float:
        if total_relevant == 0:
            return 0.0

        hits = 0
        total = 0.0

        for rank, document_id in enumerate(
            retrieved[:k],
            start=1,
        ):
            if document_id in relevant:
                hits += 1
                total += hits / rank

        return (
            total
            / min(total_relevant, k)
        )

    @staticmethod
    def _ndcg(
        retrieved: list[str],
        grades: dict[str, float],
        k: int,
    ) -> float:
        dcg = sum(
            (
                2 ** grades.get(
                    document_id,
                    0.0,
                ) - 1
            )
            / math.log2(rank + 1)
            for rank, document_id in enumerate(
                retrieved[:k],
                start=1,
            )
        )

        ideal_grades = sorted(
            grades.values(),
            reverse=True,
        )[:k]

        idcg = sum(
            (2 ** grade - 1)
            / math.log2(rank + 1)
            for rank, grade in enumerate(
                ideal_grades,
                start=1,
            )
        )

        if idcg == 0:
            return 0.0

        return dcg / idcg

    @staticmethod
    def _f1(
        precision: float,
        recall: float,
    ) -> float:
        if (
            precision + recall
        ) == 0:
            return 0.0

        return (
            2 * precision * recall
            / (precision + recall)
        )

    def evaluate_query(
        self,
        query: RetrievalQuery,
    ) -> QueryMetricsResult:
        if not query.query_id.strip():
            raise ValueError(
                "query_id required"
            )

        grades = dict(
            query.relevance_grades
        )

        self._validate_grades(
            grades
        )

        retrieved = (
            self._deduplicate(
                query.retrieved_ids
            )
            if self.config.deduplicate
            else list(
                query.retrieved_ids
            )
        )

        if not self.config.deduplicate:
            if len(retrieved) != len(
                set(retrieved)
            ):
                raise ValueError(
                    "Duplicate retrieval IDs"
                )

        relevant = {
            document_id
            for document_id, grade in (
                grades.items()
            )
            if grade >= (
                self.config.relevance_threshold
            )
        }

        total_relevant = (
            query.relevant_document_count
            if query.relevant_document_count
            is not None
            else len(relevant)
        )

        if (
            isinstance(
                total_relevant,
                bool,
            )
            or not isinstance(
                total_relevant,
                int,
            )
            or total_relevant
            < len(relevant)
        ):
            raise ValueError(
                "Invalid relevant count"
            )

        judged = (
            set(
                query.judged_document_ids
            )
            if query.judged_document_ids
            is not None
            else set(
                grades
            )
        )

        if not set(
            grades
        ).issubset(judged):
            raise ValueError(
                "Grades contain unjudged IDs"
            )

        unjudged = [
            document_id
            for document_id in retrieved
            if document_id not in judged
        ]

        metrics = {}

        for k in self.k_values:
            incomplete = any(
                document_id not in judged
                for document_id in (
                    retrieved[:k]
                )
            )

            if (
                incomplete
                and self.config.require_complete_judgments
            ):
                for name in (
                    "precision",
                    "recall",
                    "hit_rate",
                    "mrr",
                    "map",
                    "ndcg",
                    "f1",
                ):
                    metrics[
                        f"{name}@{k}"
                    ] = None

                continue

            precision = self._precision(
                retrieved,
                relevant,
                k,
            )

            recall = self._recall(
                retrieved,
                relevant,
                total_relevant,
                k,
            )

            metrics[
                f"precision@{k}"
            ] = round(
                precision,
                6,
            )

            metrics[
                f"recall@{k}"
            ] = round(
                recall,
                6,
            )

            metrics[
                f"hit_rate@{k}"
            ] = self._hit_rate(
                retrieved,
                relevant,
                k,
            )

            metrics[
                f"mrr@{k}"
            ] = round(
                self._mrr(
                    retrieved,
                    relevant,
                    k,
                ),
                6,
            )

            metrics[
                f"map@{k}"
            ] = round(
                self._average_precision(
                    retrieved,
                    relevant,
                    total_relevant,
                    k,
                ),
                6,
            )

            metrics[
                f"ndcg@{k}"
            ] = round(
                self._ndcg(
                    retrieved,
                    grades,
                    k,
                ),
                6,
            )

            metrics[
                f"f1@{k}"
            ] = round(
                self._f1(
                    precision,
                    recall,
                ),
                6,
            )

        r = total_relevant

        if r == 0:
            r_precision = 0.0
        elif (
            self.config.require_complete_judgments
            and any(
                document_id not in judged
                for document_id in (
                    retrieved[:r]
                )
            )
        ):
            r_precision = None
        else:
            r_precision = (
                self._precision(
                    retrieved,
                    relevant,
                    r,
                )
            )

        metrics[
            "r_precision"
        ] = (
            round(
                r_precision,
                6,
            )
            if r_precision is not None
            else None
        )

        return QueryMetricsResult(
            query_id=query.query_id,
            retrieved_count=len(
                retrieved
            ),
            relevant_count=total_relevant,
            unjudged_count=len(
                unjudged
            ),
            metrics=metrics,
            missing_relevant_ids=sorted(
                relevant - set(retrieved)
            ),
        )

    def evaluate(
        self,
        queries: Iterable[RetrievalQuery],
    ) -> RetrievalMetricsReport:
        queries = list(
            queries
        )

        if not queries:
            raise ValueError(
                "Evaluation queries required"
            )

        query_ids = [
            query.query_id
            for query in queries
        ]

        if len(query_ids) != len(
            set(query_ids)
        ):
            raise ValueError(
                "Duplicate query_id"
            )

        results = [
            self.evaluate_query(
                query
            )
            for query in queries
        ]

        metric_names = sorted({
            metric
            for result in results
            for metric in result.metrics
        })

        averages = {}
        counts = {}

        for metric in metric_names:
            values = [
                result.metrics[
                    metric
                ]
                for result in results
                if (
                    result.metrics.get(
                        metric
                    )
                    is not None
                )
            ]

            counts[
                metric
            ] = len(values)

            averages[
                metric
            ] = (
                round(
                    statistics.mean(
                        values
                    ),
                    6,
                )
                if values
                else None
            )

        return RetrievalMetricsReport(
            total_queries=len(
                results
            ),
            macro_metrics=averages,
            metric_query_counts=counts,
            query_results=results,
        )

    @staticmethod
    def export_json(
        report: RetrievalMetricsReport,
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
                asdict(report),
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return output

    @staticmethod
    def export_csv(
        report: RetrievalMetricsReport,
        output_path: str | Path,
    ) -> Path:
        output = Path(
            output_path
        )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        metrics = sorted({
            name
            for result in report.query_results
            for name in result.metrics
        })

        with output.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=[
                    "query_id",
                    "retrieved_count",
                    "relevant_count",
                    "unjudged_count",
                    *metrics,
                ],
            )

            writer.writeheader()

            for result in report.query_results:
                writer.writerow({
                    "query_id": result.query_id,
                    "retrieved_count": (
                        result.retrieved_count
                    ),
                    "relevant_count": (
                        result.relevant_count
                    ),
                    "unjudged_count": (
                        result.unjudged_count
                    ),
                    **result.metrics,
                })

        return output


if __name__ == "__main__":
    queries = [
        RetrievalQuery(
            query_id="stockout-001",
            retrieved_ids=[
                "inventory-001",
                "supplier-001",
                "inventory-002",
            ],
            relevance_grades={
                "inventory-001": 3,
                "supplier-001": 0,
                "inventory-002": 2,
            },
        ),
        RetrievalQuery(
            query_id="supplier-001",
            retrieved_ids=[
                "supplier-002",
                "supplier-003",
            ],
            relevance_grades={
                "supplier-002": 3,
                "supplier-003": 1,
            },
        ),
    ]

    evaluator = RetailRetrievalMetrics(
        RetrievalMetricsConfig(
            k_values=(1, 3, 5),
        )
    )

    report = evaluator.evaluate(
        queries
    )

    print(
        json.dumps(
            asdict(report),
            indent=2,
        )
    )

    evaluator.export_json(
        report,
        "reports/retrieval_metrics.json",
    )

    evaluator.export_csv(
        report,
        "reports/retrieval_metrics.csv",
    )
