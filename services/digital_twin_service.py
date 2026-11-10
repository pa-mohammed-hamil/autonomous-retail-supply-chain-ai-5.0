from __future__ import annotations

"""Planned module: digital twin service. Implementation pending."""

"""
backend/services/digital_twin_service.py

Autonomous Retail Supply Chain AI 5.0

Supply Chain Digital Twin Service

Python 3.10+
Dependencies: standard library only.

Features:
- Tenant-isolated simulation
- SKU/warehouse inventory state
- Multi-day demand simulation
- Demand spike scenarios
- Supplier purchase-order arrivals
- Warehouse-to-warehouse transfers
- Supplier delay scenarios
- Lost-sales and stockout metrics
- Inventory holding-cost estimation
- Daily simulation history
- Scenario comparison
- JSON export

All simulation runs use copied state.
No real-world stock, purchase orders,
or financial records are modified.

This is a deterministic discrete-day
reference model, not a calibrated
physical or operational twin.
"""


import copy
import json
import math

from dataclasses import (
    asdict,
    dataclass,
    field,
)
from pathlib import Path
from typing import Any, Iterable


def nonnegative(
    value: float,
    name: str,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(
            f"{name} must be a finite "
            "nonnegative number"
        )

    return float(value)


def positive_int(
    value: int,
    name: str,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
    ):
        raise ValueError(
            f"{name} must be a positive integer"
        )

    return value


@dataclass(frozen=True)
class TwinInventory:
    tenant_id: str
    sku: str
    warehouse_id: str
    opening_stock: float
    daily_demand: float
    unit_price: float
    unit_cost: float
    daily_holding_cost_per_unit: float = 0.0


@dataclass(frozen=True)
class TwinPurchaseOrder:
    tenant_id: str
    order_id: str
    sku: str
    warehouse_id: str
    quantity: float
    arrival_day: int


@dataclass(frozen=True)
class TwinTransfer:
    tenant_id: str
    transfer_id: str
    sku: str
    from_warehouse: str
    to_warehouse: str
    quantity: float
    departure_day: int
    transit_days: int = 1


@dataclass(frozen=True)
class TwinScenario:
    name: str
    horizon_days: int = 14
    demand_multiplier: float = 1.0
    supplier_delay_days: int = 0
    demand_multipliers_by_sku: dict[
        str, float
    ] = field(default_factory=dict)


@dataclass(frozen=True)
class TwinDailyState:
    day: int
    sku: str
    warehouse_id: str
    opening_stock: float
    receipts: float
    demand: float
    fulfilled_demand: float
    lost_sales_units: float
    ending_stock: float
    holding_cost: float


@dataclass(frozen=True)
class TwinSimulationResult:
    tenant_id: str
    scenario_name: str
    horizon_days: int
    total_demand: float
    fulfilled_demand: float
    lost_sales_units: float
    fill_rate_pct: float | None
    lost_revenue: float
    estimated_gross_profit: float
    holding_cost: float
    stockout_sku_days: int
    ending_inventory_units: float
    daily_states: list[TwinDailyState]
    warnings: list[str]


class RetailDigitalTwinService:
    """
    Deterministic daily supply-chain
    simulator.

    Timing:
    1. Scheduled receipts arrive.
    2. Warehouse transfers depart.
    3. Customer demand is served.
    4. Holding costs are calculated.

    Orders arriving on day 1 are
    available before day-1 demand.

    A transfer's destination receives
    stock on departure_day +
    transit_days.

    A transfer never creates stock:
    dispatched quantity is bounded
    by origin availability.
    """

    def __init__(
        self,
        tenant_id: str,
    ):
        if (
            not isinstance(tenant_id, str)
            or not tenant_id.strip()
        ):
            raise ValueError(
                "tenant_id is required"
            )

        self.tenant_id = tenant_id

    def _validate_inputs(
        self,
        inventories: list[TwinInventory],
        purchase_orders: list[TwinPurchaseOrder],
        transfers: list[TwinTransfer],
        scenario: TwinScenario,
    ) -> None:
        positive_int(
            scenario.horizon_days,
            "horizon_days",
        )

        if scenario.horizon_days > 365:
            raise ValueError(
                "Maximum horizon is 365 days"
            )

        nonnegative(
            scenario.demand_multiplier,
            "demand_multiplier",
        )

        if (
            isinstance(
                scenario.supplier_delay_days,
                bool,
            )
            or not isinstance(
                scenario.supplier_delay_days,
                int,
            )
            or scenario.supplier_delay_days < 0
        ):
            raise ValueError(
                "Invalid supplier delay"
            )

        if not scenario.name.strip():
            raise ValueError(
                "Scenario name required"
            )

        for multiplier in (
            scenario.demand_multipliers_by_sku.values()
        ):
            nonnegative(
                multiplier,
                "SKU demand multiplier",
            )

        inventory_keys = set()

        for item in inventories:
            if item.tenant_id != self.tenant_id:
                raise PermissionError(
                    "Cross-tenant inventory"
                )

            if (
                not item.sku.strip()
                or not item.warehouse_id.strip()
            ):
                raise ValueError(
                    "Invalid SKU or warehouse"
                )

            key = (
                item.sku,
                item.warehouse_id,
            )

            if key in inventory_keys:
                raise ValueError(
                    "Duplicate inventory state"
                )

            inventory_keys.add(key)

            for name in (
                "opening_stock",
                "daily_demand",
                "unit_price",
                "unit_cost",
                "daily_holding_cost_per_unit",
            ):
                nonnegative(
                    getattr(item, name),
                    name,
                )

        order_ids = set()

        for order in purchase_orders:
            if order.tenant_id != self.tenant_id:
                raise PermissionError(
                    "Cross-tenant purchase order"
                )

            if (
                not order.order_id.strip()
                or order.order_id in order_ids
            ):
                raise ValueError(
                    "Invalid or duplicate order ID"
                )

            order_ids.add(order.order_id)

            if (
                order.sku,
                order.warehouse_id,
            ) not in inventory_keys:
                raise ValueError(
                    "Purchase order destination "
                    "does not exist"
                )

            nonnegative(
                order.quantity,
                "purchase quantity",
            )

            positive_int(
                order.arrival_day,
                "arrival_day",
            )

        transfer_ids = set()

        for transfer in transfers:
            if transfer.tenant_id != self.tenant_id:
                raise PermissionError(
                    "Cross-tenant transfer"
                )

            if (
                not transfer.transfer_id.strip()
                or transfer.transfer_id
                in transfer_ids
            ):
                raise ValueError(
                    "Invalid or duplicate transfer ID"
                )

            transfer_ids.add(
                transfer.transfer_id
            )

            if (
                transfer.from_warehouse
                == transfer.to_warehouse
            ):
                raise ValueError(
                    "Transfer warehouses must differ"
                )

            for warehouse in (
                transfer.from_warehouse,
                transfer.to_warehouse,
            ):
                if (
                    transfer.sku,
                    warehouse,
                ) not in inventory_keys:
                    raise ValueError(
                        "Transfer warehouse/SKU "
                        "state missing"
                    )

            nonnegative(
                transfer.quantity,
                "transfer quantity",
            )

            positive_int(
                transfer.departure_day,
                "departure_day",
            )

            positive_int(
                transfer.transit_days,
                "transit_days",
            )

    def simulate(
        self,
        inventories: Iterable[TwinInventory],
        scenario: TwinScenario,
        purchase_orders: (
            Iterable[TwinPurchaseOrder] | None
        ) = None,
        transfers: (
            Iterable[TwinTransfer] | None
        ) = None,
    ) -> TwinSimulationResult:
        inventory_list = list(
            inventories
        )

        order_list = list(
            purchase_orders or []
        )

        transfer_list = list(
            transfers or []
        )

        self._validate_inputs(
            inventory_list,
            order_list,
            transfer_list,
            scenario,
        )

        # Simulation state is independent
        # of the supplied input objects.
        stock = {
            (
                item.sku,
                item.warehouse_id,
            ): float(item.opening_stock)
            for item in inventory_list
        }

        inventory_map = {
            (
                item.sku,
                item.warehouse_id,
            ): item
            for item in inventory_list
        }

        # Receipts are keyed by day
        # and SKU/warehouse.
        scheduled_receipts: dict[
            int,
            dict[tuple[str, str], float],
        ] = {}

        def schedule_receipt(
            day: int,
            key: tuple[str, str],
            quantity: float,
        ) -> None:
            day_receipts = (
                scheduled_receipts.setdefault(
                    day,
                    {},
                )
            )

            day_receipts[key] = (
                day_receipts.get(key, 0.0)
                + quantity
            )

        warnings = []

        for order in order_list:
            arrival = (
                order.arrival_day
                + scenario.supplier_delay_days
            )

            if arrival <= scenario.horizon_days:
                schedule_receipt(
                    arrival,
                    (
                        order.sku,
                        order.warehouse_id,
                    ),
                    order.quantity,
                )
            else:
                warnings.append(
                    f"Order {order.order_id} "
                    "arrives after the horizon"
                )

        transfers_by_day: dict[
            int,
            list[TwinTransfer],
        ] = {}

        for transfer in transfer_list:
            transfers_by_day.setdefault(
                transfer.departure_day,
                [],
            ).append(transfer)

        daily_states = []

        total_demand = 0.0
        fulfilled_total = 0.0
        lost_units_total = 0.0
        lost_revenue = 0.0
        gross_profit = 0.0
        holding_cost_total = 0.0
        stockout_sku_days = 0

        for day in range(
            1,
            scenario.horizon_days + 1,
        ):
            opening = dict(stock)

            receipts_today = (
                scheduled_receipts.get(
                    day,
                    {},
                )
            )

            for key, quantity in (
                receipts_today.items()
            ):
                stock[key] += quantity

            transfer_departures = {}

            for transfer in sorted(
                transfers_by_day.get(
                    day,
                    [],
                ),
                key=lambda item: (
                    item.transfer_id
                ),
            ):
                origin = (
                    transfer.sku,
                    transfer.from_warehouse,
                )

                destination = (
                    transfer.sku,
                    transfer.to_warehouse,
                )

                dispatched = min(
                    stock[origin],
                    transfer.quantity,
                )

                stock[origin] -= dispatched

                transfer_departures[origin] = (
                    transfer_departures.get(
                        origin,
                        0.0,
                    )
                    + dispatched
                )

                if dispatched < (
                    transfer.quantity
                ):
                    warnings.append(
                        f"Transfer {transfer.transfer_id} "
                        f"partially fulfilled on day {day}"
                    )

                arrival_day = (
                    day
                    + transfer.transit_days
                )

                if (
                    arrival_day
                    <= scenario.horizon_days
                    and dispatched > 0
                ):
                    schedule_receipt(
                        arrival_day,
                        destination,
                        dispatched,
                    )

            for key, item in sorted(
                inventory_map.items()
            ):
                multiplier = (
                    scenario.demand_multipliers_by_sku.get(
                        item.sku,
                        scenario.demand_multiplier,
                    )
                )

                demand = (
                    item.daily_demand
                    * multiplier
                )

                available = stock[key]

                fulfilled = min(
                    available,
                    demand,
                )

                lost = max(
                    0.0,
                    demand - fulfilled,
                )

                stock[key] -= fulfilled

                holding_cost = (
                    stock[key]
                    * item.daily_holding_cost_per_unit
                )

                total_demand += demand
                fulfilled_total += fulfilled
                lost_units_total += lost

                lost_revenue += (
                    lost * item.unit_price
                )

                gross_profit += (
                    fulfilled
                    * (
                        item.unit_price
                        - item.unit_cost
                    )
                )

                holding_cost_total += (
                    holding_cost
                )

                if lost > 0:
                    stockout_sku_days += 1

                daily_states.append(
                    TwinDailyState(
                        day=day,
                        sku=item.sku,
                        warehouse_id=(
                            item.warehouse_id
                        ),
                        opening_stock=round(
                            opening[key], 4
                        ),
                        receipts=round(
                            receipts_today.get(
                                key, 0.0
                            ),
                            4,
                        ),
                        demand=round(
                            demand, 4
                        ),
                        fulfilled_demand=round(
                            fulfilled, 4
                        ),
                        lost_sales_units=round(
                            lost, 4
                        ),
                        ending_stock=round(
                            stock[key], 4
                        ),
                        holding_cost=round(
                            holding_cost, 4
                        ),
                    )
                )

        fill_rate = (
            fulfilled_total
            / total_demand * 100
            if total_demand > 0
            else None
        )

        return TwinSimulationResult(
            tenant_id=self.tenant_id,
            scenario_name=scenario.name,
            horizon_days=scenario.horizon_days,
            total_demand=round(
                total_demand, 4
            ),
            fulfilled_demand=round(
                fulfilled_total, 4
            ),
            lost_sales_units=round(
                lost_units_total, 4
            ),
            fill_rate_pct=(
                round(fill_rate, 2)
                if fill_rate is not None
                else None
            ),
            lost_revenue=round(
                lost_revenue, 2
            ),
            estimated_gross_profit=round(
                gross_profit, 2
            ),
            holding_cost=round(
                holding_cost_total, 2
            ),
            stockout_sku_days=(
                stockout_sku_days
            ),
            ending_inventory_units=round(
                sum(stock.values()),
                4,
            ),
            daily_states=daily_states,
            warnings=warnings,
        )

    def compare_scenarios(
        self,
        inventories: Iterable[TwinInventory],
        scenarios: Iterable[TwinScenario],
        purchase_orders: (
            Iterable[TwinPurchaseOrder] | None
        ) = None,
        transfers: (
            Iterable[TwinTransfer] | None
        ) = None,
    ) -> list[dict[str, Any]]:
        # Materialize iterables once so
        # every scenario gets identical
        # starting inputs.
        inventory_list = list(
            inventories
        )

        order_list = list(
            purchase_orders or []
        )

        transfer_list = list(
            transfers or []
        )

        comparison = []

        for scenario in scenarios:
            result = self.simulate(
                inventories=inventory_list,
                scenario=scenario,
                purchase_orders=order_list,
                transfers=transfer_list,
            )

            comparison.append({
                "scenario": (
                    result.scenario_name
                ),
                "fill_rate_pct": (
                    result.fill_rate_pct
                ),
                "lost_sales_units": (
                    result.lost_sales_units
                ),
                "lost_revenue": (
                    result.lost_revenue
                ),
                "estimated_gross_profit": (
                    result.estimated_gross_profit
                ),
                "holding_cost": (
                    result.holding_cost
                ),
                "stockout_sku_days": (
                    result.stockout_sku_days
                ),
                "ending_inventory_units": (
                    result.ending_inventory_units
                ),
            })

        return comparison

    @staticmethod
    def export_json(
        result: TwinSimulationResult,
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
                allow_nan=False,
            ),
            encoding="utf-8",
        )

        return output


if __name__ == "__main__":
    service = RetailDigitalTwinService(
        tenant_id="demo"
    )

    inventories = [
        TwinInventory(
            tenant_id="demo",
            sku="SKU001",
            warehouse_id="WH001",
            opening_stock=100,
            daily_demand=20,
            unit_price=750,
            unit_cost=500,
            daily_holding_cost_per_unit=0.5,
        ),
        TwinInventory(
            tenant_id="demo",
            sku="SKU001",
            warehouse_id="WH002",
            opening_stock=200,
            daily_demand=10,
            unit_price=750,
            unit_cost=500,
            daily_holding_cost_per_unit=0.5,
        ),
    ]

    purchase_orders = [
        TwinPurchaseOrder(
            tenant_id="demo",
            order_id="PO001",
            sku="SKU001",
            warehouse_id="WH001",
            quantity=150,
            arrival_day=5,
        )
    ]

    transfers = [
        TwinTransfer(
            tenant_id="demo",
            transfer_id="TR001",
            sku="SKU001",
            from_warehouse="WH002",
            to_warehouse="WH001",
            quantity=50,
            departure_day=2,
            transit_days=1,
        )
    ]

    scenarios = [
        TwinScenario(
            name="Baseline",
            horizon_days=14,
        ),
        TwinScenario(
            name="Demand Spike 2x",
            horizon_days=14,
            demand_multiplier=2.0,
        ),
        TwinScenario(
            name="Supplier Delay",
            horizon_days=14,
            supplier_delay_days=5,
        ),
    ]

    comparison = service.compare_scenarios(
        inventories,
        scenarios,
        purchase_orders,
        transfers,
    )

    print(
        json.dumps(
            comparison,
            indent=2,
        )
    )

    result = service.simulate(
        inventories,
        scenarios[0],
        purchase_orders,
        transfers,
    )

    service.export_json(
        result,
        "reports/digital_twin_baseline.json",
    )
