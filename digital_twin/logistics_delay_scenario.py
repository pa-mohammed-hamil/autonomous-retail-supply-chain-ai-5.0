"""Planned module: logistics delay scenario. Implementation pending."""

"""
ai/simulation/logistics_delay_scenario.py

Autonomous Retail Supply Chain AI 5.0

Deterministic logistics disruption simulator.
Python 3.10+ | Standard library only.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


CENT = Decimal("0.01")


def number(value: Any, name: str) -> Decimal:
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


def money(value: Decimal) -> str:
    return str(
        value.quantize(
            CENT, rounding=ROUND_HALF_UP
        )
    )


class LogisticsDelayScenario:

    def __init__(self, currency: str = "INR"):
        if (
            not isinstance(currency, str)
            or not currency.strip()
        ):
            raise ValueError("currency is required")

        self.currency = currency.strip().upper()

    def simulate(
        self,
        shipment_id: str,
        planned_delivery_hours: Any,
        supplier_delay_hours: Any = "0",
        traffic_delay_hours: Any = "0",
        weather_delay_hours: Any = "0",
        warehouse_delay_hours: Any = "0",
        recovery_hours: Any = "0",
        delivery_deadline_hours: Any = None,
        affected_demand_units: Any = "0",
        available_inventory_units: Any = "0",
        contribution_margin_per_unit: Any = "0",
        recoverable_fraction: Any = "0",
        penalty_per_late_hour: Any = "0",
        emergency_transport_cost: Any = "0",
        other_incremental_cost: Any = "0",
    ) -> dict:

        if (
            not isinstance(shipment_id, str)
            or not shipment_id.strip()
        ):
            raise ValueError("shipment_id required")

        planned = number(
            planned_delivery_hours,
            "planned_delivery_hours",
        )

        supplier = number(
            supplier_delay_hours,
            "supplier_delay_hours",
        )
        traffic = number(
            traffic_delay_hours,
            "traffic_delay_hours",
        )
        weather = number(
            weather_delay_hours,
            "weather_delay_hours",
        )
        warehouse = number(
            warehouse_delay_hours,
            "warehouse_delay_hours",
        )
        recovery = number(
            recovery_hours, "recovery_hours"
        )

        gross_delay = (
            supplier + traffic + weather + warehouse
        )

        net_delay = max(
            Decimal("0"),
            gross_delay - recovery,
        )

        actual_delivery = planned + net_delay

        deadline_met = None
        hours_late = Decimal("0")

        if delivery_deadline_hours is not None:
            deadline = number(
                delivery_deadline_hours,
                "delivery_deadline_hours",
            )
            hours_late = max(
                Decimal("0"),
                actual_delivery - deadline,
            )
            deadline_met = hours_late == 0

        demand = number(
            affected_demand_units,
            "affected_demand_units",
        )
        available = number(
            available_inventory_units,
            "available_inventory_units",
        )
        margin = number(
            contribution_margin_per_unit,
            "contribution_margin_per_unit",
        )

        recoverable = number(
            recoverable_fraction,
            "recoverable_fraction",
        )

        if recoverable > 1:
            raise ValueError(
                "recoverable_fraction must be 0 to 1"
            )

        # Demand and stock refer only to the
        # additional period caused by the delay.
        shortage = max(
            Decimal("0"),
            demand - available,
        )

        # No disruption-induced shortage if the
        # shipment arrives on its original schedule.
        if net_delay == 0:
            shortage = Decimal("0")

        lost_units = shortage * (1 - recoverable)
        lost_contribution = lost_units * margin

        penalty_rate = number(
            penalty_per_late_hour,
            "penalty_per_late_hour",
        )
        emergency = number(
            emergency_transport_cost,
            "emergency_transport_cost",
        )
        other = number(
            other_incremental_cost,
            "other_incremental_cost",
        )

        penalty = hours_late * penalty_rate

        total_impact = (
            lost_contribution
            + penalty
            + emergency
            + other
        )

        return {
            "shipment_id": shipment_id.strip(),
            "currency": self.currency,
            "planned_delivery_hours": str(planned),
            "gross_delay_hours": str(gross_delay),
            "recovered_hours": str(
                min(recovery, gross_delay)
            ),
            "net_delay_hours": str(net_delay),
            "estimated_delivery_hours": str(
                actual_delivery
            ),
            "deadline_met": deadline_met,
            "hours_late": str(hours_late),
            "delay_related_shortage_units": str(
                shortage
            ),
            "estimated_permanently_lost_units": str(
                lost_units
            ),
            "lost_contribution": money(
                lost_contribution
            ),
            "late_delivery_penalty": money(penalty),
            "emergency_transport_cost": money(
                emergency
            ),
            "other_incremental_cost": money(other),
            "estimated_total_impact": money(
                total_impact
            ),
            "disruption_detected": net_delay > 0,
            "simulation_only": True,
            "assumptions": (
                "Delay components are additive. "
                "Affected demand is supplied externally "
                "and represents demand during the delay."
            ),
        }

    def compare_disruptions(
        self,
        scenarios: list[dict],
    ) -> dict:

        if (
            not isinstance(scenarios, list)
            or not 2 <= len(scenarios) <= 50
        ):
            raise ValueError(
                "Provide 2 to 50 disruption scenarios"
            )

        results = [
            self.simulate(**scenario)
            for scenario in scenarios
        ]

        ids = [r["shipment_id"] for r in results]

        if len(set(ids)) != len(ids):
            raise ValueError(
                "shipment_id must be unique"
            )

        results.sort(
            key=lambda r: (
                Decimal(r["estimated_total_impact"]),
                Decimal(r["net_delay_hours"]),
            )
        )

        return {
            "currency": self.currency,
            "scenario_count": len(results),
            "ranked_scenarios": results,
            "lowest_impact_scenario": (
                results[0]["shipment_id"]
            ),
            "recommendation_only": True,
        }
