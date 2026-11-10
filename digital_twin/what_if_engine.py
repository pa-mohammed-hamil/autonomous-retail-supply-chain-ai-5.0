"""Planned module: what if engine. Implementation pending."""

"""
ai/simulation/what_if_engine.py

Autonomous Retail Supply Chain AI 5.0

What-if scenario evaluation engine.
Python 3.10+ | Standard library only.

Model contract:
    model(parameters: dict) -> dict

Expected model output:
{
    "total_cost": "100000",
    "service_level_percent": "95",
    "delivery_delay_hours": "2",
    "stockout_units": "10"
}

All scenarios must use the same currency,
reporting period, and KPI definitions.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Callable
import copy
import json


METRICS = (
    "total_cost",
    "service_level_percent",
    "delivery_delay_hours",
    "stockout_units",
)

LOWER_BETTER = {
    "total_cost",
    "delivery_delay_hours",
    "stockout_units",
}


def decimal_value(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(
        value, (str, int, Decimal)
    ):
        raise ValueError(f"Invalid {name}")

    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid {name}") from exc

    if not result.is_finite() or result < 0:
        raise ValueError(f"Invalid {name}")
    return result


def json_copy(value: Any) -> Any:
    try:
        return json.loads(
            json.dumps(value, allow_nan=False)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Parameters must be JSON-compatible"
        ) from exc


class WhatIfEngine:

    def __init__(
        self,
        currency: str = "INR",
        period: str = "monthly",
        weights: dict[str, Any] | None = None,
    ):
        if not isinstance(currency, str) or not currency.strip():
            raise ValueError("currency required")
        if not isinstance(period, str) or not period.strip():
            raise ValueError("period required")

        self.currency = currency.strip().upper()
        self.period = period.strip()

        defaults = {
            "total_cost": "0.40",
            "service_level_percent": "0.30",
            "delivery_delay_hours": "0.15",
            "stockout_units": "0.15",
        }

        selected = defaults if weights is None else weights

        if not isinstance(selected, dict) or set(selected) != set(METRICS):
            raise ValueError(
                "Weights must include all four metrics"
            )

        parsed = {
            key: decimal_value(value, key)
            for key, value in selected.items()
        }

        total = sum(parsed.values(), Decimal("0"))

        if total <= 0:
            raise ValueError("Weight sum must be positive")

        self.weights = {
            key: value / total
            for key, value in parsed.items()
        }

    def _validate_result(self, result: dict) -> dict:
        if not isinstance(result, dict):
            raise ValueError(
                "Simulation model must return a dictionary"
            )

        parsed = {
            key: decimal_value(result[key], key)
            for key in METRICS
        }

        if parsed["service_level_percent"] > 100:
            raise ValueError(
                "Service level cannot exceed 100%"
            )

        return parsed

    def compare(
        self,
        model: Callable[[dict], dict],
        baseline_parameters: dict,
        alternatives: list[dict],
        max_cost: Any = None,
        min_service_level_percent: Any = None,
        max_delay_hours: Any = None,
    ) -> dict:

        if not callable(model):
            raise ValueError("model must be callable")

        if not isinstance(baseline_parameters, dict):
            raise ValueError(
                "baseline_parameters must be a dictionary"
            )

        if (
            not isinstance(alternatives, list)
            or not 1 <= len(alternatives) <= 49
        ):
            raise ValueError(
                "Provide 1 to 49 alternatives"
            )

        baseline = json_copy(baseline_parameters)

        configs = [{
            "name": "Baseline",
            "parameters": baseline,
        }]

        names = {"Baseline"}

        for alternative in alternatives:
            if not isinstance(alternative, dict):
                raise ValueError("Invalid alternative")

            name = alternative.get("name")
            changes = alternative.get("changes")

            if (
                not isinstance(name, str)
                or not name.strip()
                or name in names
            ):
                raise ValueError(
                    "Alternative names must be unique"
                )

            if not isinstance(changes, dict):
                raise ValueError(
                    "changes must be a dictionary"
                )

            names.add(name)

            params = copy.deepcopy(baseline)

            # Only known baseline keys may be modified.
            unknown = set(changes) - set(params)
            if unknown:
                raise ValueError(
                    f"Unknown parameters: {sorted(unknown)}"
                )

            params.update(json_copy(changes))

            configs.append({
                "name": name,
                "parameters": params,
            })

        rows = []

        for config in configs:
            result = model(
                copy.deepcopy(config["parameters"])
            )

            rows.append({
                "name": config["name"],
                "parameters": config["parameters"],
                "metrics": self._validate_result(result),
            })

        limits = {
            "max_cost": (
                decimal_value(max_cost, "max_cost")
                if max_cost is not None else None
            ),
            "min_service_level_percent": (
                decimal_value(
                    min_service_level_percent,
                    "min_service_level_percent",
                )
                if min_service_level_percent is not None
                else None
            ),
            "max_delay_hours": (
                decimal_value(
                    max_delay_hours,
                    "max_delay_hours",
                )
                if max_delay_hours is not None
                else None
            ),
        }

        if (
            limits["min_service_level_percent"]
            is not None
            and limits["min_service_level_percent"] > 100
        ):
            raise ValueError("Invalid service constraint")

        ranges = {
            key: (
                min(r["metrics"][key] for r in rows),
                max(r["metrics"][key] for r in rows),
            )
            for key in METRICS
        }

        for row in rows:
            metrics = row["metrics"]

            score = Decimal("0")

            for key in METRICS:
                low, high = ranges[key]

                if low == high:
                    normalized = Decimal("1")
                elif key in LOWER_BETTER:
                    normalized = (
                        high - metrics[key]
                    ) / (high - low)
                else:
                    normalized = (
                        metrics[key] - low
                    ) / (high - low)

                score += normalized * self.weights[key]

            row["score"] = score * 100

            row["feasible"] = (
                (
                    limits["max_cost"] is None
                    or metrics["total_cost"]
                    <= limits["max_cost"]
                )
                and (
                    limits["min_service_level_percent"]
                    is None
                    or metrics["service_level_percent"]
                    >= limits["min_service_level_percent"]
                )
                and (
                    limits["max_delay_hours"] is None
                    or metrics["delivery_delay_hours"]
                    <= limits["max_delay_hours"]
                )
            )

        baseline_metrics = rows[0]["metrics"]

        ranked = sorted(
            rows,
            key=lambda r: (
                not r["feasible"],
                -r["score"],
                r["metrics"]["total_cost"],
                r["name"],
            ),
        )

        output = []

        for row in ranked:
            result = {
                "name": row["name"],
                "feasible": row["feasible"],
                "score_percent": str(
                    row["score"].quantize(
                        Decimal("0.01")
                    )
                ),
                "metrics": {
                    key: str(value)
                    for key, value in row["metrics"].items()
                },
                "cost_savings_vs_baseline": str(
                    baseline_metrics["total_cost"]
                    - row["metrics"]["total_cost"]
                ),
                "service_change_percentage_points": str(
                    row["metrics"]["service_level_percent"]
                    - baseline_metrics["service_level_percent"]
                ),
            }

            output.append(result)

        feasible = [
            row for row in ranked if row["feasible"]
        ]

        return {
            "currency": self.currency,
            "period": self.period,
            "scenario_count": len(rows),
            "ranked_scenarios": output,
            "recommended_scenario": (
                feasible[0]["name"] if feasible else None
            ),
            "recommendation_only": True,
            "simulation_only": True,
            "scoring_note": (
                "Scores are relative to the scenario set. "
                "Changing alternatives can change rankings."
            ),
        }

    def sensitivity_analysis(
        self,
        model: Callable[[dict], dict],
        baseline_parameters: dict,
        parameter_name: str,
        candidate_values: list[Any],
    ) -> dict:

        if parameter_name not in baseline_parameters:
            raise ValueError("Unknown parameter")

        if (
            not isinstance(candidate_values, list)
            or not 1 <= len(candidate_values) <= 50
        ):
            raise ValueError(
                "Provide 1 to 50 candidate values"
            )

        baseline = json_copy(baseline_parameters)
        results = []

        for value in candidate_values:
            params = copy.deepcopy(baseline)
            params[parameter_name] = json_copy(value)

            metrics = self._validate_result(
                model(params)
            )

            results.append({
                "parameter_value": value,
                "metrics": {
                    key: str(v)
                    for key, v in metrics.items()
                },
            })

        return {
            "parameter": parameter_name,
            "currency": self.currency,
            "period": self.period,
            "results": results,
            "simulation_only": True,
        }
