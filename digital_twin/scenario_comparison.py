"""Planned module: scenario comparison. Implementation pending."""

"""
ai/simulation/scenario_comparison.py

Autonomous Retail Supply Chain AI 5.0

Multi-criteria supply-chain scenario comparison.

Python 3.10+ | Standard library only.

Supports:
- Total cost
- Delivery delay
- Service level
- Stockout quantity
- Feasibility constraints
- Weighted scoring
- Pareto-dominance checks
- Baseline comparisons
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


METRICS = (
    "total_cost",
    "delivery_delay_hours",
    "service_level_percent",
    "stockout_units",
)

LOWER_IS_BETTER = {
    "total_cost",
    "delivery_delay_hours",
    "stockout_units",
}


def dec(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(
        value, (str, int, Decimal)
    ):
        raise ValueError(
            f"{name} must be an integer or decimal string"
        )

    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid {name}") from exc

    if not result.is_finite() or result < 0:
        raise ValueError(f"Invalid {name}")

    return result


class ScenarioComparison:

    def __init__(
        self,
        currency: str = "INR",
        weights: dict[str, Any] | None = None,
    ):
        if (
            not isinstance(currency, str)
            or not currency.strip()
        ):
            raise ValueError("currency required")

        self.currency = currency.strip().upper()

        default_weights = {
            "total_cost": "0.40",
            "delivery_delay_hours": "0.20",
            "service_level_percent": "0.25",
            "stockout_units": "0.15",
        }

        raw = (
            default_weights
            if weights is None else weights
        )

        if (
            not isinstance(raw, dict)
            or set(raw) != set(METRICS)
        ):
            raise ValueError(
                "Weights must cover all four metrics"
            )

        self.weights = {
            key: dec(value, key)
            for key, value in raw.items()
        }

        total = sum(
            self.weights.values(), Decimal("0")
        )

        if total <= 0:
            raise ValueError(
                "At least one weight must be positive"
            )

        self.weights = {
            key: value / total
            for key, value in self.weights.items()
        }

    @staticmethod
    def _dominates(a: dict, b: dict) -> bool:
        """True when a is no worse on every metric
        and strictly better on at least one."""

        better_or_equal = True
        strictly_better = False

        for metric in METRICS:
            av = a["_values"][metric]
            bv = b["_values"][metric]

            if metric in LOWER_IS_BETTER:
                if av > bv:
                    better_or_equal = False
                if av < bv:
                    strictly_better = True
            else:
                if av < bv:
                    better_or_equal = False
                if av > bv:
                    strictly_better = True

        return better_or_equal and strictly_better

    def compare(
        self,
        scenarios: list[dict],
        baseline_name: str | None = None,
        max_cost: Any = None,
        max_delay_hours: Any = None,
        min_service_level_percent: Any = None,
    ) -> dict:

        if (
            not isinstance(scenarios, list)
            or not 2 <= len(scenarios) <= 50
        ):
            raise ValueError(
                "Provide 2 to 50 scenarios"
            )

        parsed = []
        names = set()

        for scenario in scenarios:
            if not isinstance(scenario, dict):
                raise ValueError("Invalid scenario")

            name = scenario.get("name")

            if (
                not isinstance(name, str)
                or not name.strip()
                or name in names
            ):
                raise ValueError(
                    "Scenario names must be unique"
                )

            names.add(name)

            values = {
                metric: dec(
                    scenario[metric], metric
                )
                for metric in METRICS
            }

            if values["service_level_percent"] > 100:
                raise ValueError(
                    "Service level cannot exceed 100%"
                )

            parsed.append({
                "name": name,
                "_values": values,
            })

        constraints = {
            "max_cost": (
                dec(max_cost, "max_cost")
                if max_cost is not None else None
            ),
            "max_delay_hours": (
                dec(
                    max_delay_hours,
                    "max_delay_hours",
                )
                if max_delay_hours is not None
                else None
            ),
            "min_service_level_percent": (
                dec(
                    min_service_level_percent,
                    "min_service_level_percent",
                )
                if min_service_level_percent is not None
                else None
            ),
        }

        if (
            constraints["min_service_level_percent"]
            is not None
            and constraints[
                "min_service_level_percent"
            ] > 100
        ):
            raise ValueError(
                "Minimum service level exceeds 100%"
            )

        ranges = {}

        for metric in METRICS:
            metric_values = [
                row["_values"][metric]
                for row in parsed
            ]
            ranges[metric] = (
                min(metric_values),
                max(metric_values),
            )

        for row in parsed:
            values = row["_values"]
            scores = {}

            for metric in METRICS:
                low, high = ranges[metric]

                if low == high:
                    score = Decimal("1")
                elif metric in LOWER_IS_BETTER:
                    score = (
                        high - values[metric]
                    ) / (high - low)
                else:
                    score = (
                        values[metric] - low
                    ) / (high - low)

                scores[metric] = score

            weighted_score = sum(
                (
                    scores[metric]
                    * self.weights[metric]
                    for metric in METRICS
                ),
                Decimal("0"),
            )

            feasible = (
                (
                    constraints["max_cost"] is None
                    or values["total_cost"]
                    <= constraints["max_cost"]
                )
                and (
                    constraints[
                        "max_delay_hours"
                    ] is None
                    or values["delivery_delay_hours"]
                    <= constraints["max_delay_hours"]
                )
                and (
                    constraints[
                        "min_service_level_percent"
                    ] is None
                    or values["service_level_percent"]
                    >= constraints[
                        "min_service_level_percent"
                    ]
                )
            )

            row["weighted_score"] = weighted_score
            row["feasible"] = feasible
            row["metric_scores"] = scores

        for row in parsed:
            row["pareto_dominated"] = any(
                self._dominates(other, row)
                for other in parsed
                if other is not row
            )

        baseline = None

        if baseline_name is not None:
            baseline = next(
                (
                    row for row in parsed
                    if row["name"] == baseline_name
                ),
                None,
            )

            if baseline is None:
                raise ValueError(
                    "baseline_name not found"
                )

        ranked = sorted(
            parsed,
            key=lambda row: (
                not row["feasible"],
                -row["weighted_score"],
                row["_values"]["total_cost"],
                row["name"],
            ),
        )

        feasible_rows = [
            row for row in ranked
            if row["feasible"]
        ]

        output = []

        for row in ranked:
            result = {
                "name": row["name"],
                "metrics": {
                    key: str(value)
                    for key, value
                    in row["_values"].items()
                },
                "weighted_score_percent": str(
                    (
                        row["weighted_score"] * 100
                    ).quantize(Decimal("0.01"))
                ),
                "feasible": row["feasible"],
                "pareto_dominated": (
                    row["pareto_dominated"]
                ),
            }

            if baseline is not None:
                result["cost_savings_vs_baseline"] = str(
                    baseline["_values"]["total_cost"]
                    - row["_values"]["total_cost"]
                )

                result[
                    "delay_reduction_vs_baseline_hours"
                ] = str(
                    baseline["_values"][
                        "delivery_delay_hours"
                    ]
                    - row["_values"][
                        "delivery_delay_hours"
                    ]
                )

            output.append(result)

        return {
            "currency": self.currency,
            "scenario_count": len(parsed),
            "weights": {
                key: str(value)
                for key, value in self.weights.items()
            },
            "ranked_scenarios": output,
            "recommended_scenario": (
                feasible_rows[0]["name"]
                if feasible_rows else None
            ),
            "recommendation_only": True,
            "scoring_note": (
                "Min-max scores are relative to "
                "the supplied scenario set. Adding "
                "a scenario can change the ranking."
            ),
        }
