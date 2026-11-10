from __future__ import annotations

"""Planned module: simulation. Implementation pending."""

"""
backend/services/simulation_service.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+ | Standard library only

Deterministic supply-chain what-if simulation:
- Tenant and warehouse RBAC
- Demand spike scenarios
- Supplier delivery delays
- Inventory projections
- Stockout detection
- Lost-sales estimates
- Shortage cost estimates
- Immutable scenario reports
- Audit events
- JSON export

No real inventory or purchase orders are modified.
"""


import json
import math
import threading
import uuid

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def finite_nonnegative(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(
        value, (int, float)
    ):
        raise ValueError(f"Invalid {name}")

    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"Invalid {name}")

    return result


def nonnegative_int(value: int, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"Invalid {name}")
    return value


def money(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("Invalid money")

    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            raise ValueError("Invalid money")
        return amount.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid money") from exc


@dataclass(frozen=True)
class SimulationActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str] = frozenset()
    is_active: bool = True


@dataclass(frozen=True)
class SimulationScenario:
    tenant_id: str
    warehouse_id: str
    sku: str
    initial_stock: int
    daily_demand: float
    demand_spike_pct: float
    supplier_lead_time_days: int
    supplier_delay_days: int
    incoming_quantity: int
    safety_stock: int
    horizon_days: int
    shortage_cost_per_unit: Decimal


@dataclass(frozen=True)
class SimulationDay:
    day: int
    opening_stock: float
    incoming_stock: float
    demand: float
    fulfilled_demand: float
    unmet_demand: float
    closing_stock: float


@dataclass(frozen=True)
class SimulationReport:
    report_id: str
    tenant_id: str
    warehouse_id: str
    sku: str
    scenario: SimulationScenario
    daily_results: tuple[SimulationDay, ...]
    ending_stock: float
    total_demand: float
    fulfilled_demand: float
    unmet_demand: float
    fill_rate_pct: float
    first_stockout_day: int | None
    supplier_arrival_day: int
    estimated_shortage_cost: Decimal
    created_by: str
    created_at: str


@dataclass(frozen=True)
class SimulationAuditEvent:
    event_id: str
    tenant_id: str
    actor_id: str
    report_id: str
    action: str
    timestamp: str


class RetailSimulationService:
    RUNNER_ROLES = frozenset({
        "inventory_manager",
        "demand_planner",
        "operations_manager",
        "supply_chain_analyst",
        "corporate_admin",
    })

    READER_ROLES = RUNNER_ROLES | frozenset({
        "inventory_analyst",
        "procurement_manager",
        "warehouse_manager",
    })

    def __init__(self, tenant_id: str):
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Invalid tenant_id")

        self.tenant_id = tenant_id
        self._lock = threading.RLock()
        self._reports: dict[str, SimulationReport] = {}
        self._audit: list[SimulationAuditEvent] = []

    def _authorize(
        self,
        actor: SimulationActor,
        roles: frozenset[str],
        warehouse_id: str,
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.user_id.strip()
            or not actor.roles.intersection(roles)
        ):
            raise PermissionError("Simulation access denied")

        if (
            "corporate_admin" not in actor.roles
            and warehouse_id not in actor.warehouse_ids
        ):
            raise PermissionError("Warehouse access denied")

    @staticmethod
    def _validate(s: SimulationScenario) -> None:
        if not s.warehouse_id.strip() or not s.sku.strip():
            raise ValueError("Warehouse and SKU required")

        for name in (
            "initial_stock",
            "supplier_lead_time_days",
            "supplier_delay_days",
            "incoming_quantity",
            "safety_stock",
            "horizon_days",
        ):
            nonnegative_int(getattr(s, name), name)

        finite_nonnegative(s.daily_demand, "daily_demand")
        finite_nonnegative(
            s.demand_spike_pct, "demand_spike_pct"
        )
        money(s.shortage_cost_per_unit)

        if not 1 <= s.horizon_days <= 365:
            raise ValueError("Horizon must be 1-365 days")

        if s.demand_spike_pct > 1000:
            raise ValueError("Demand spike too large")

    def run(
        self,
        actor: SimulationActor,
        scenario: SimulationScenario,
    ) -> SimulationReport:
        self._authorize(
            actor, self.RUNNER_ROLES,
            scenario.warehouse_id,
        )

        if scenario.tenant_id != self.tenant_id:
            raise PermissionError("Cross-tenant scenario")

        self._validate(scenario)

        demand_per_day = (
            scenario.daily_demand
            * (1 + scenario.demand_spike_pct / 100)
        )

        arrival_day = (
            scenario.supplier_lead_time_days
            + scenario.supplier_delay_days
        )

        remaining = float(scenario.initial_stock)
        results = []

        total_demand = 0.0
        fulfilled_total = 0.0
        unmet_total = 0.0
        first_stockout = None

        for day in range(1, scenario.horizon_days + 1):
            opening = remaining

            arrival = (
                float(scenario.incoming_quantity)
                if day == arrival_day
                else 0.0
            )

            available = opening + arrival
            fulfilled = min(available, demand_per_day)
            unmet = max(0.0, demand_per_day - fulfilled)
            remaining = max(0.0, available - fulfilled)

            total_demand += demand_per_day
            fulfilled_total += fulfilled
            unmet_total += unmet

            if unmet > 0 and first_stockout is None:
                first_stockout = day

            results.append(SimulationDay(
                day=day,
                opening_stock=round(opening, 4),
                incoming_stock=round(arrival, 4),
                demand=round(demand_per_day, 4),
                fulfilled_demand=round(fulfilled, 4),
                unmet_demand=round(unmet, 4),
                closing_stock=round(remaining, 4),
            ))

        fill_rate = (
            fulfilled_total / total_demand * 100
            if total_demand > 0
            else 100.0
        )

        shortage_cost = (
            Decimal(str(unmet_total))
            * money(scenario.shortage_cost_per_unit)
        ).quantize(Decimal("0.01"))

        report = SimulationReport(
            report_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            warehouse_id=scenario.warehouse_id,
            sku=scenario.sku,
            scenario=scenario,
            daily_results=tuple(results),
            ending_stock=round(remaining, 4),
            total_demand=round(total_demand, 4),
            fulfilled_demand=round(fulfilled_total, 4),
            unmet_demand=round(unmet_total, 4),
            fill_rate_pct=round(fill_rate, 2),
            first_stockout_day=first_stockout,
            supplier_arrival_day=arrival_day,
            estimated_shortage_cost=shortage_cost,
            created_by=actor.user_id,
            created_at=utc_now(),
        )

        with self._lock:
            self._reports[report.report_id] = report
            self._audit.append(SimulationAuditEvent(
                event_id=str(uuid.uuid4()),
                tenant_id=self.tenant_id,
                actor_id=actor.user_id,
                report_id=report.report_id,
                action="simulation_completed",
                timestamp=utc_now(),
            ))

        return report

    def get_report(
        self,
        actor: SimulationActor,
        report_id: str,
    ) -> SimulationReport:
        with self._lock:
            report = self._reports.get(report_id)

        if report is None:
            raise KeyError("Simulation report not found")

        self._authorize(
            actor, self.READER_ROLES,
            report.warehouse_id,
        )
        return report

    def list_reports(
        self,
        actor: SimulationActor,
    ) -> list[SimulationReport]:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.roles.intersection(self.READER_ROLES)
        ):
            raise PermissionError("Simulation access denied")

        with self._lock:
            return [
                report
                for report in self._reports.values()
                if (
                    "corporate_admin" in actor.roles
                    or report.warehouse_id in actor.warehouse_ids
                )
            ]

    def compare(
        self,
        actor: SimulationActor,
        report_ids: list[str],
    ) -> list[dict[str, Any]]:
        reports = [
            self.get_report(actor, report_id)
            for report_id in report_ids
        ]

        return sorted(
            [
                {
                    "report_id": report.report_id,
                    "sku": report.sku,
                    "fill_rate_pct": report.fill_rate_pct,
                    "unmet_demand": report.unmet_demand,
                    "ending_stock": report.ending_stock,
                    "estimated_shortage_cost": str(
                        report.estimated_shortage_cost
                    ),
                }
                for report in reports
            ],
            key=lambda item: (
                -item["fill_rate_pct"],
                item["unmet_demand"],
            ),
        )

    def audit_events(
        self,
        actor: SimulationActor,
    ) -> list[SimulationAuditEvent]:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or "corporate_admin" not in actor.roles
        ):
            raise PermissionError("Audit access denied")

        with self._lock:
            return list(self._audit)

    def export_json(
        self,
        actor: SimulationActor,
        report_id: str,
        output_path: str | Path,
    ) -> Path:
        report = self.get_report(actor, report_id)

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(
            json.dumps(
                asdict(report),
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    service = RetailSimulationService("demo")

    analyst = SimulationActor(
        user_id="analyst001",
        tenant_id="demo",
        roles=frozenset({"supply_chain_analyst"}),
        warehouse_ids=frozenset({"WH001"}),
    )

    scenario = SimulationScenario(
        tenant_id="demo",
        warehouse_id="WH001",
        sku="SKU001",
        initial_stock=300,
        daily_demand=25,
        demand_spike_pct=20,
        supplier_lead_time_days=7,
        supplier_delay_days=3,
        incoming_quantity=250,
        safety_stock=60,
        horizon_days=30,
        shortage_cost_per_unit=Decimal("100.00"),
    )

    report = service.run(analyst, scenario)

    print("Ending stock:", report.ending_stock)
    print("Unmet demand:", report.unmet_demand)
    print("Fill rate:", report.fill_rate_pct)
    print("Stockout day:", report.first_stockout_day)
    print("Shortage cost:", report.estimated_shortage_cost)
