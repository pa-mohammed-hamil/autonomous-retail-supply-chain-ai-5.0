"""Planned module: benchmark runner. Implementation pending."""

"""
ai/evaluation/benchmark_runner.py

Autonomous Retail Supply Chain AI 5.0
Retrieval Benchmark Runner

Python 3.10+
Standard library only.

Supported evaluation:
- Precision@K
- Recall@K
- Hit Rate@K
- MRR@K
- MAP@K
- nDCG@K
- Mean / P50 / P95 latency
- Error counts
- Per-query evaluation
- Multi-retriever comparisons
- JSON and CSV export

Expected adapter signature:

    search(
        query: str,
        tenant_id: str,
        top_k: int,
        filters: dict | None
    ) -> iterable of result objects

Result objects must expose
document_id or be dictionaries
containing document_id.

IMPORTANT:
- Benchmark only datasets and
  documents you are authorized
  to access.
- Use stable evaluation datasets.
- Do not benchmark on training data
  alone.
- Latency includes adapter calls.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import time

from dataclasses import (
    asdict,
    dataclass,
    field,
)
from pathlib import Path
from typing import Any, Callable, Iterable


@dataclass
class BenchmarkCase:
    query_id: str
    query: str
    tenant_id: str
    relevant_ids: list[str]
    relevance_grades: dict[str, int] = field(
        default_factory=dict
    )
    filters: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass
class BenchmarkConfig:
    k_values: tuple[int, ...] = (
        1, 3, 5, 10
    )
    fail_fast: bool = False
    include_per_query: bool = True


@dataclass
class QueryBenchmark:
    query_id: str
    tenant_id: str
    retrieved_ids: list[str]
    latency_ms: float
    metrics: dict[str, float]
    error: str | None = None


@dataclass
class RetrieverBenchmark:
    retriever_name: str
    queries_total: int
    queries_succeeded: int
    queries_failed: int
    mean_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    metrics: dict[str, float]
    per_query: list[QueryBenchmark]


@dataclass
class BenchmarkReport:
    benchmark_name: str
    results: list[RetrieverBenchmark]
    k_values: list[int]


class RetailBenchmarkRunner:
    """
    Evaluate retrieval systems against
    relevance judgments.

    Each retriever is registered using
    a callable adapter.

    Search results are deduplicated
    by document_id before scoring.

    Failed queries count as zero
    for retrieval-quality metrics.
    """

    def __init__(
        self,
        config: BenchmarkConfig | None = None,
    ):
        self.config = (
            config or BenchmarkConfig()
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
                k <= 0
                for k in self.k_values
            )
        ):
            raise ValueError(
                "k_values must contain "
                "positive integers"
            )

        self.retrievers: dict[
            str,
            Callable[..., Any],
        ] = {}

    def register(
        self,
        name: str,
        search_fn: Callable[..., Any],
    ) -> None:
        if not name.strip():
            raise ValueError(
                "Retriever name required"
            )

        if name in self.retrievers:
            raise ValueError(
                "Duplicate retriever name"
            )

        if not callable(search_fn):
            raise TypeError(
                "search_fn must be callable"
            )

        self.retrievers[
            name
        ] = search_fn

    @staticmethod
    def _extract_ids(
        response: Any,
    ) -> list[str]:
        """
        Accept:
        - list of dictionaries
        - list of result objects
        - response.results
        - response.documents
        """
        if hasattr(
            response,
            "results",
        ):
            response = response.results

        elif hasattr(
            response,
            "documents",
        ):
            response = response.documents

        if isinstance(
            response,
            dict,
        ):
            response = (
                response.get("results")
                or response.get("documents")
                or []
            )

        if not isinstance(
            response,
            (list, tuple),
        ):
            raise TypeError(
                "Unsupported retrieval response"
            )

        ids = []
        seen = set()

        for item in response:
            if isinstance(
                item,
                dict,
            ):
                document_id = item.get(
                    "document_id"
                )
            else:
                document_id = getattr(
                    item,
                    "document_id",
                    None,
                )

            if (
                not isinstance(
                    document_id,
                    str,
                )
                or not document_id.strip()
            ):
                raise ValueError(
                    "Invalid retrieved document ID"
                )

            if document_id in seen:
                continue

            seen.add(document_id)
            ids.append(document_id)

        return ids

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
        k: int,
    ) -> float:
        if not relevant:
            return 0.0

        hits = sum(
            document_id in relevant
            for document_id in retrieved[:k]
        )

        return hits / len(
            relevant
        )

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
    def _reciprocal_rank(
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
        k: int,
    ) -> float:
        if not relevant:
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

        return total / min(
            len(relevant),
            k,
        )

    @staticmethod
    def _ndcg(
        retrieved: list[str],
        relevance_grades: dict[str, int],
        k: int,
    ) -> float:
        def gain(
            relevance: int,
            rank: int,
        ) -> float:
            return (
                (2 ** relevance - 1)
                / math.log2(rank + 1)
            )

        dcg = sum(
            gain(
                relevance_grades.get(
                    document_id,
                    0,
                ),
                rank,
            )
            for rank, document_id in enumerate(
                retrieved[:k],
                start=1,
            )
        )

        ideal = sorted(
            relevance_grades.values(),
            reverse=True,
        )[:k]

        idcg = sum(
            gain(relevance, rank)
            for rank, relevance in enumerate(
                ideal,
                start=1,
            )
        )

        if idcg == 0:
            return 0.0

        return dcg / idcg

    def _evaluate_query(
        self,
        retrieved: list[str],
        case: BenchmarkCase,
    ) -> dict[str, float]:
        relevant = set(
            case.relevant_ids
        )

        grades = (
            case.relevance_grades
            or {
                document_id: 1
                for document_id in relevant
            }
        )

        metrics = {}

        for k in self.k_values:
            metrics[
                f"precision@{k}"
            ] = self._precision(
                retrieved,
                relevant,
                k,
            )

            metrics[
                f"recall@{k}"
            ] = self._recall(
                retrieved,
                relevant,
                k,
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
            ] = self._reciprocal_rank(
                retrieved,
                relevant,
                k,
            )

            metrics[
                f"map@{k}"
            ] = self._average_precision(
                retrieved,
                relevant,
                k,
            )

            metrics[
                f"ndcg@{k}"
            ] = self._ndcg(
                retrieved,
                grades,
                k,
            )

        return metrics

    @staticmethod
    def _percentile(
        values: list[float],
        percentile: float,
    ) -> float:
        if not values:
            return 0.0

        ordered = sorted(
            values
        )

        position = (
            (len(ordered) - 1)
            * percentile
        )

        lower = math.floor(
            position
        )

        upper = math.ceil(
            position
        )

        if lower == upper:
            return ordered[
                lower
            ]

        weight = (
            position - lower
        )

        return (
            ordered[lower]
            * (1 - weight)
            + ordered[upper]
            * weight
        )

    def _run_retriever(
        self,
        name: str,
        search_fn: Callable[..., Any],
        cases: list[BenchmarkCase],
    ) -> RetrieverBenchmark:
        per_query = []
        latencies = []

        max_k = max(
            self.k_values
        )

        metric_names = list(
            self._evaluate_query(
                [],
                cases[0],
            ).keys()
        )

        metric_totals = {
            metric: 0.0
            for metric in metric_names
        }

        failures = 0

        for case in cases:
            error = None
            retrieved = []

            started = (
                time.perf_counter()
            )

            try:
                response = search_fn(
                    query=case.query,
                    tenant_id=case.tenant_id,
                    top_k=max_k,
                    filters=(
                        case.filters or None
                    ),
                )

                retrieved = (
                    self._extract_ids(
                        response
                    )
                )

            except Exception as exc:
                failures += 1
                error = (
                    type(exc).__name__
                    + ": "
                    + str(exc)[:200]
                )

                if self.config.fail_fast:
                    raise

            elapsed_ms = (
                time.perf_counter()
                - started
            ) * 1000

            latencies.append(
                elapsed_ms
            )

            metrics = (
                self._evaluate_query(
                    retrieved,
                    case,
                )
            )

            for metric, value in (
                metrics.items()
            ):
                metric_totals[
                    metric
                ] += value

            if self.config.include_per_query:
                per_query.append(
                    QueryBenchmark(
                        query_id=case.query_id,
                        tenant_id=case.tenant_id,
                        retrieved_ids=retrieved,
                        latency_ms=round(
                            elapsed_ms,
                            3,
                        ),
                        metrics=metrics,
                        error=error,
                    )
                )

        count = len(
            cases
        )

        averages = {
            name: round(
                value / count,
                6,
            )
            for name, value in (
                metric_totals.items()
            )
        }

        return RetrieverBenchmark(
            retriever_name=name,
            queries_total=count,
            queries_succeeded=(
                count - failures
            ),
            queries_failed=failures,
            mean_latency_ms=round(
                statistics.mean(
                    latencies
                ),
                3,
            ),
            p50_latency_ms=round(
                self._percentile(
                    latencies,
                    0.50,
                ),
                3,
            ),
            p95_latency_ms=round(
                self._percentile(
                    latencies,
                    0.95,
                ),
                3,
            ),
            metrics=averages,
            per_query=per_query,
        )

    def run(
        self,
        cases: Iterable[BenchmarkCase],
        benchmark_name: str = (
            "retail_retrieval_benchmark"
        ),
    ) -> BenchmarkReport:
        cases = list(
            cases
        )

        if not cases:
            raise ValueError(
                "Benchmark cases required"
            )

        if not self.retrievers:
            raise ValueError(
                "No retrievers registered"
            )

        seen_ids = set()

        for case in cases:
            if (
                not case.query_id
                or not case.query.strip()
                or not case.tenant_id.strip()
            ):
                raise ValueError(
                    "Invalid benchmark case"
                )

            if case.query_id in seen_ids:
                raise ValueError(
                    "Duplicate query_id"
                )

            seen_ids.add(
                case.query_id
            )

            if not case.relevant_ids:
                raise ValueError(
                    "At least one relevant "
                    "document is required"
                )

            if any(
                grade < 0
                or not isinstance(grade, int)
                for grade in (
                    case.relevance_grades.values()
                )
            ):
                raise ValueError(
                    "Invalid relevance grades"
                )

        results = []

        for name, search_fn in (
            self.retrievers.items()
        ):
            result = (
                self._run_retriever(
                    name,
                    search_fn,
                    cases,
                )
            )

            results.append(
                result
            )

        return BenchmarkReport(
            benchmark_name=benchmark_name,
            results=results,
            k_values=list(
                self.k_values
            ),
        )

    @staticmethod
    def export_json(
        report: BenchmarkReport,
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
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return output

    @staticmethod
    def export_csv(
        report: BenchmarkReport,
        output_path: str | Path,
    ) -> Path:
        output = Path(
            output_path
        )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        metric_names = sorted({
            metric
            for result in report.results
            for metric in result.metrics
        })

        columns = [
            "retriever",
            "queries_total",
            "queries_succeeded",
            "queries_failed",
            "mean_latency_ms",
            "p50_latency_ms",
            "p95_latency_ms",
            *metric_names,
        ]

        with output.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=columns,
            )

            writer.writeheader()

            for result in report.results:
                writer.writerow({
                    "retriever": (
                        result.retriever_name
                    ),
                    "queries_total": (
                        result.queries_total
                    ),
                    "queries_succeeded": (
                        result.queries_succeeded
                    ),
                    "queries_failed": (
                        result.queries_failed
                    ),
                    "mean_latency_ms": (
                        result.mean_latency_ms
                    ),
                    "p50_latency_ms": (
                        result.p50_latency_ms
                    ),
                    "p95_latency_ms": (
                        result.p95_latency_ms
                    ),
                    **result.metrics,
                })

        return output


if __name__ == "__main__":
    # Deterministic example.
    # These are synthetic results,
    # not measured model performance.

    cases = [
        BenchmarkCase(
            query_id="q001",
            query=(
                "Which SKU is at "
                "risk of stockout?"
            ),
            tenant_id="demo",
            relevant_ids=[
                "inventory-001",
            ],
            relevance_grades={
                "inventory-001": 3,
                "inventory-002": 1,
            },
        ),
        BenchmarkCase(
            query_id="q002",
            query=(
                "What is the supplier "
                "delivery lead time?"
            ),
            tenant_id="demo",
            relevant_ids=[
                "supplier-001",
            ],
            relevance_grades={
                "supplier-001": 3,
            },
        ),
    ]

    def example_search(
        query: str,
        tenant_id: str,
        top_k: int,
        filters=None,
    ):
        if "stockout" in query.lower():
            ids = [
                "inventory-001",
                "inventory-002",
            ]
        else:
            ids = [
                "supplier-001",
                "inventory-001",
            ]

        return [
            {
                "document_id": document_id
            }
            for document_id in ids[:top_k]
        ]

    runner = RetailBenchmarkRunner()

    runner.register(
        "example_retriever",
        example_search,
    )

    report = runner.run(
        cases,
        benchmark_name="demo_benchmark",
    )

    runner.export_json(
        report,
        "reports/benchmark.json",
    )

    runner.export_csv(
        report,
        "reports/benchmark.csv",
    )

    print(
        json.dumps(
            asdict(report),
            indent=2,
        )
    )
