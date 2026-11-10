"""Planned module: optimization benchmarks. Implementation pending."""

"""
ai/optimization/optimization_benchmarks.py

Reusable optimization benchmark runner.

Features:
- Multiple benchmark scenarios
- Baseline and candidate comparison
- Repeated optimizer execution
- Runtime statistics
- Output validation
- Feasibility checks
- CSV and JSON export

Benchmark functions must return dictionaries with:
    total_cost
    distance_km
    fulfilled_orders
    total_orders
    used_capacity
    available_capacity
    constraint_violations

Adapter functions can translate optimizer-specific
outputs into this common metric schema.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import time

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Any

from ai.optimization.objective_metrics import (
    OptimizationMetricsInput,
    ObjectiveMetrics,
)


@dataclass(frozen=True)
class BenchmarkScenario:
    scenario_id: str
    baseline: OptimizationMetricsInput
    optimizer: Callable[[], dict[str, Any]]


class OptimizationBenchmark:

    REQUIRED_KEYS = {
        "total_cost",
        "distance_km",
        "fulfilled_orders",
        "total_orders",
        "used_capacity",
        "available_capacity",
        "constraint_violations",
    }

    def run(
        self,
        scenarios: list[BenchmarkScenario],
        repetitions: int = 5,
    ) -> dict:

        if (
            isinstance(repetitions, bool)
            or not isinstance(repetitions, int)
            or repetitions <= 0
        ):
            raise ValueError(
                "Repetitions must be positive"
            )

        ids = [s.scenario_id for s in scenarios]

        if len(ids) != len(set(ids)):
            raise ValueError(
                "Duplicate scenario IDs"
            )

        results = []

        for scenario in scenarios:
            durations = []
            outputs = []
            errors = []

            for _ in range(repetitions):
                start = time.perf_counter()

                try:
                    output = scenario.optimizer()

                    if not isinstance(output, dict):
                        raise TypeError(
                            "Optimizer must return a dict"
                        )

                    missing = (
                        self.REQUIRED_KEYS - output.keys()
                    )

                    if missing:
                        raise ValueError(
                            f"Missing metric keys: "
                            f"{sorted(missing)}"
                        )

                    duration = (
                        time.perf_counter() - start
                    )

                    candidate = OptimizationMetricsInput(
                        solution_id=(
                            scenario.scenario_id
                            + "_candidate"
                        ),
                        total_cost=output["total_cost"],
                        distance_km=output["distance_km"],
                        runtime_seconds=duration,
                        fulfilled_orders=(
                            output["fulfilled_orders"]
                        ),
                        total_orders=(
                            output["total_orders"]
                        ),
                        used_capacity=(
                            output["used_capacity"]
                        ),
                        available_capacity=(
                            output["available_capacity"]
                        ),
                        constraint_violations=(
                            output["constraint_violations"]
                        ),
                    )

                    durations.append(duration)
                    outputs.append(candidate)

                except Exception as exc:
                    errors.append(
                        f"{type(exc).__name__}: {exc}"
                    )

            if not outputs:
                results.append({
                    "scenario_id": scenario.scenario_id,
                    "status": "failed",
                    "successful_runs": 0,
                    "failed_runs": repetitions,
                    "errors": errors,
                })
                continue

            # For repeated runs, report the lowest-cost
            # feasible candidate; otherwise the first run.
            feasible = [
                item for item in outputs
                if item.constraint_violations == 0
            ]

            representative = (
                min(
                    feasible,
                    key=lambda item: item.total_cost,
                )
                if feasible
                else outputs[0]
            )

            comparison = ObjectiveMetrics.compare(
                scenario.baseline,
                representative,
            )

            results.append({
                "scenario_id": scenario.scenario_id,
                "status": (
                    "completed"
                    if not errors
                    else "partially_completed"
                ),
                "successful_runs": len(outputs),
                "failed_runs": len(errors),
                "mean_runtime_seconds": round(
                    statistics.mean(durations), 6
                ),
                "median_runtime_seconds": round(
                    statistics.median(durations), 6
                ),
                "min_runtime_seconds": round(
                    min(durations), 6
                ),
                "max_runtime_seconds": round(
                    max(durations), 6
                ),
                "mean_candidate_cost": round(
                    statistics.mean(
                        item.total_cost
                        for item in outputs
                    ),
                    2,
                ),
                "feasible_run_rate": round(
                    len(feasible) / len(outputs),
                    4,
                ),
                "comparison": comparison,
                "errors": errors,
            })

        return {
            "scenario_count": len(scenarios),
            "repetitions_per_scenario": repetitions,
            "results": results,
            "benchmark_type": "offline",
        }

    @staticmethod
    def export_json(
        report: dict,
        path: str,
    ) -> None:
        Path(path).parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with open(path, "w", encoding="utf-8") as file:
            json.dump(
                report,
                file,
                indent=2,
                default=str,
            )

    @staticmethod
    def export_csv(
        report: dict,
        path: str,
    ) -> None:

        Path(path).parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        rows = []

        for result in report["results"]:
            comparison = result.get(
                "comparison", {}
            )

            rows.append({
                "scenario_id": result["scenario_id"],
                "status": result["status"],
                "successful_runs": result[
                    "successful_runs"
                ],
                "failed_runs": result[
                    "failed_runs"
                ],
                "mean_runtime_seconds": result.get(
                    "mean_runtime_seconds"
                ),
                "mean_candidate_cost": result.get(
                    "mean_candidate_cost"
                ),
                "feasible_run_rate": result.get(
                    "feasible_run_rate"
                ),
                "cost_savings": comparison.get(
                    "cost_savings"
                ),
                "cost_improvement_percent": (
                    comparison.get(
                        "cost_improvement_percent"
                    )
                ),
                "distance_reduction_km": (
                    comparison.get(
                        "distance_reduction_km"
                    )
                ),
            })

        if not rows:
            return

        with open(
            path, "w", newline="", encoding="utf-8"
        ) as file:
            writer = csv.DictWriter(
                file,
                fieldnames=list(rows[0].keys()),
            )
            writer.writeheader()
            writer.writerows(rows)
