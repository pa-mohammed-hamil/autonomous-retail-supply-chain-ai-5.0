"""Planned module: simulate supplier failure. Implementation pending."""

#!/usr/bin/env python3
"""
SupplyChainAI — Supplier Failure Simulator

File: scripts/simulate_supplier_failure.py

Features:
    01. Supplier failure scenarios
    02. Supplier risk analysis
    03. Production shutdown simulation
    04. Delivery disruption simulation
    05. Quality recall simulation
    06. Supplier capacity reduction
    07. Historical sales-based demand estimates
    08. Warehouse stockout projections
    09. Delayed purchase order analysis
    10. Estimated revenue exposure
    11. Alternative supplier recommendations
    12. Replenishment recommendations
    13. Corporate escalation alerts
    14. Incident audit logs
    15. JSON and CSV reporting
    16. Performance visualization

Simulation only:
    No production inventory, suppliers,
    purchase orders, or notifications are changed.

Install:
    pip install pandas numpy matplotlib

Examples:
    python scripts/simulate_supplier_failure.py

    python scripts/simulate_supplier_failure.py \
        --scenario production_shutdown

    python scripts/simulate_supplier_failure.py \
        --scenario delivery_failure --duration 14

    python scripts/simulate_supplier_failure.py \
        --scenario capacity_reduction --capacity-loss 70

    python scripts/simulate_supplier_failure.py \
        --supplier SUP-001
"""

import argparse
import json
import math
import sys

from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


# ============================================================
# 1. PROJECT CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"

DEFAULT_OUTPUT = (
    ROOT / "reports" / "supplier_failure"
)

SCENARIOS = {
    "delivery_failure": {
        "description": "Supplier shipments delayed",
        "default_duration": 14,
        "capacity_loss": 100,
        "quality_hold": False
    },
    "production_shutdown": {
        "description": "Supplier production unavailable",
        "default_duration": 30,
        "capacity_loss": 100,
        "quality_hold": False
    },
    "quality_recall": {
        "description": "Supplier products held for QA",
        "default_duration": 21,
        "capacity_loss": 100,
        "quality_hold": True
    },
    "capacity_reduction": {
        "description": "Supplier production capacity reduced",
        "default_duration": 21,
        "capacity_loss": 50,
        "quality_hold": False
    },
    "logistics_disruption": {
        "description": "Supplier transportation disrupted",
        "default_duration": 10,
        "capacity_loss": 100,
        "quality_hold": False
    }
}

SERVICE_LEVEL_Z = 1.65

DEFAULT_HISTORY_DAYS = 30

DEFAULT_LEAD_TIME = 7


# ============================================================
# 2. CLI ARGUMENTS
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="SupplyChainAI supplier failure simulator"
    )

    parser.add_argument(
        "--scenario",
        choices=SCENARIOS.keys(),
        default="production_shutdown"
    )

    parser.add_argument(
        "--supplier",
        default=None,
        help="Specific supplier ID"
    )

    parser.add_argument(
        "--duration",
        type=int,
        default=None
    )

    parser.add_argument(
        "--capacity-loss",
        type=float,
        default=None,
        help="Percentage of capacity unavailable"
    )

    parser.add_argument(
        "--history-days",
        type=int,
        default=DEFAULT_HISTORY_DAYS
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT
    )

    args = parser.parse_args()

    if args.duration is not None:
        if not 1 <= args.duration <= 365:
            parser.error(
                "--duration must be 1-365 days"
            )

    if args.capacity_loss is not None:
        if not 0 <= args.capacity_loss <= 100:
            parser.error(
                "--capacity-loss must be 0-100"
            )

    if not 7 <= args.history_days <= 365:
        parser.error(
            "--history-days must be 7-365"
        )

    return args


# ============================================================
# 3. DATA LOADING
# ============================================================

def load_csv(name, required, optional=False):
    path = DATA_DIR / name

    if not path.exists():
        if optional:
            return None

        raise FileNotFoundError(
            f"Missing {path}. "
            "Run scripts/generate_demo_data.py first."
        )

    df = pd.read_csv(path)

    missing = sorted(
        set(required) - set(df.columns)
    )

    if missing:
        raise ValueError(
            f"{name} missing columns: {missing}"
        )

    return df


def load_datasets():
    suppliers = load_csv(
        "suppliers.csv",
        [
            "supplier_id",
            "supplier_name",
            "lead_time_days",
            "on_time_delivery_rate",
            "defect_rate",
            "risk_score"
        ]
    )

    products = load_csv(
        "products.csv",
        [
            "product_id",
            "product_name",
            "category",
            "supplier_id",
            "unit_price",
            "unit_cost"
        ]
    )

    inventory = load_csv(
        "inventory.csv",
        [
            "product_id",
            "warehouse_id",
            "stock_on_hand",
            "reorder_point",
            "safety_stock"
        ]
    )

    sales = load_csv(
        "sales.csv",
        [
            "date",
            "product_id",
            "warehouse_id",
            "quantity_sold"
        ]
    )

    purchase_orders = load_csv(
        "purchase_orders.csv",
        [
            "purchase_order_id",
            "supplier_id",
            "product_id",
            "quantity",
            "status"
        ],
        optional=True
    )

    for name, frame, keys in [
        ("suppliers", suppliers, ["supplier_id"]),
        ("products", products, ["product_id"]),
        (
            "inventory",
            inventory,
            ["product_id", "warehouse_id"]
        )
    ]:
        if frame.duplicated(keys).any():
            raise ValueError(
                f"Duplicate keys in {name}"
            )

    numeric_fields = [
        (suppliers, "lead_time_days"),
        (suppliers, "on_time_delivery_rate"),
        (suppliers, "defect_rate"),
        (suppliers, "risk_score"),
        (products, "unit_price"),
        (products, "unit_cost"),
        (inventory, "stock_on_hand"),
        (inventory, "reorder_point"),
        (inventory, "safety_stock"),
        (sales, "quantity_sold")
    ]

    for frame, column in numeric_fields:
        frame[column] = pd.to_numeric(
            frame[column],
            errors="raise"
        )

        if (
            frame[column].isna().any()
            or not np.isfinite(frame[column]).all()
            or (frame[column] < 0).any()
        ):
            raise ValueError(
                f"Invalid values in {column}"
            )

    if (
        suppliers["lead_time_days"] <= 0
    ).any():
        raise ValueError(
            "Supplier lead times must be positive."
        )

    sales["date"] = pd.to_datetime(
        sales["date"],
        errors="coerce"
    )

    if sales["date"].isna().any():
        raise ValueError(
            "Invalid sales dates."
        )

    if not set(
        products["supplier_id"]
    ).issubset(
        set(suppliers["supplier_id"])
    ):
        raise ValueError(
            "Products reference unknown suppliers."
        )

    if not set(
        inventory["product_id"]
    ).issubset(
        set(products["product_id"])
    ):
        raise ValueError(
            "Inventory references unknown products."
        )

    return {
        "suppliers": suppliers,
        "products": products,
        "inventory": inventory,
        "sales": sales,
        "purchase_orders": purchase_orders
    }


# ============================================================
# 4. SELECT AFFECTED SUPPLIER
# ============================================================

def select_supplier(
    suppliers,
    supplier_id=None
):
    if supplier_id:
        matches = suppliers[
            suppliers["supplier_id"].astype(str)
            == str(supplier_id)
        ]

        if matches.empty:
            raise ValueError(
                f"Unknown supplier: {supplier_id}"
            )

        return matches.iloc[0]

    # Default: highest recorded supplier risk.
    return (
        suppliers.sort_values(
            "risk_score",
            ascending=False
        )
        .iloc[0]
    )


# ============================================================
# 5. HISTORICAL DEMAND
# ============================================================

def calculate_daily_demand(
    sales,
    inventory,
    history_days
):
    latest = sales["date"].max().normalize()

    start = (
        latest
        - pd.Timedelta(days=history_days - 1)
    )

    recent = sales[
        (sales["date"] >= start)
        & (sales["date"] <= latest)
    ].copy()

    demand = (
        recent.groupby(
            ["product_id", "warehouse_id"],
            as_index=False
        )["quantity_sold"]
        .sum()
    )

    demand["daily_demand"] = (
        demand["quantity_sold"]
        / history_days
    )

    result = inventory[
        ["product_id", "warehouse_id"]
    ].merge(
        demand[
            [
                "product_id",
                "warehouse_id",
                "daily_demand"
            ]
        ],
        on=["product_id", "warehouse_id"],
        how="left"
    )

    result["daily_demand"] = (
        result["daily_demand"]
        .fillna(0)
    )

    return result


# ============================================================
# 6. SUPPLIER FAILURE IMPACT
# ============================================================

def simulate_supplier_failure(
    data,
    supplier,
    scenario,
    duration,
    capacity_loss,
    history_days
):
    products = data["products"]
    inventory = data["inventory"]
    sales = data["sales"]

    affected_products = products[
        products["supplier_id"]
        == supplier["supplier_id"]
    ].copy()

    if affected_products.empty:
        raise ValueError(
            "Selected supplier has no linked products."
        )

    demand = calculate_daily_demand(
        sales,
        inventory,
        history_days
    )

    frame = inventory.merge(
        affected_products[
            [
                "product_id",
                "product_name",
                "category",
                "supplier_id",
                "unit_price",
                "unit_cost"
            ]
        ],
        on="product_id",
        how="inner",
        validate="many_to_one"
    )

    frame = frame.merge(
        demand,
        on=["product_id", "warehouse_id"],
        how="left",
        validate="one_to_one"
    )

    records = []
    daily_records = []

    loss_fraction = capacity_loss / 100

    for row in frame.itertuples(index=False):
        daily_demand = max(
            float(row.daily_demand),
            0
        )

        starting_stock = float(
            row.stock_on_hand
        )

        # This is a simplified steady-state assumption:
        # under normal conditions, inbound supply matches
        # daily demand. The failure reduces that supply.
        #
        # It is not a purchase-order arrival schedule.
        baseline_daily_inbound = daily_demand

        disrupted_daily_inbound = (
            baseline_daily_inbound
            * (1 - loss_fraction)
        )

        if scenario == "quality_recall":
            # Illustrative complete quarantine of
            # affected supplier inventory.
            available_stock = 0.0
            quarantined_stock = starting_stock
        else:
            available_stock = starting_stock
            quarantined_stock = 0.0

        total_requested = 0.0
        total_fulfilled = 0.0
        total_inbound = 0.0

        first_stockout_day = None

        for day in range(1, duration + 1):
            inbound = disrupted_daily_inbound

            available_stock += inbound

            requested = daily_demand

            fulfilled = min(
                requested,
                available_stock
            )

            unfulfilled = max(
                requested - fulfilled,
                0
            )

            available_stock -= fulfilled

            total_requested += requested
            total_fulfilled += fulfilled
            total_inbound += inbound

            if (
                unfulfilled > 0.000001
                and first_stockout_day is None
            ):
                first_stockout_day = day

            daily_records.append({
                "day": day,
                "product_id": row.product_id,
                "warehouse_id": row.warehouse_id,
                "requested_units": round(
                    requested, 3
                ),
                "inbound_units": round(
                    inbound, 3
                ),
                "fulfilled_units": round(
                    fulfilled, 3
                ),
                "unfulfilled_units": round(
                    unfulfilled, 3
                ),
                "ending_stock": round(
                    available_stock, 3
                )
            })

        unfulfilled_units = max(
            total_requested - total_fulfilled,
            0
        )

        expected_lost_inbound = (
            baseline_daily_inbound
            - disrupted_daily_inbound
        ) * duration

        # Planning recommendation only.
        recommended_replenishment = math.ceil(
            max(
                total_requested
                + float(row.safety_stock)
                - starting_stock
                - total_inbound,
                0
            )
        )

        if first_stockout_day is not None:
            risk_level = (
                "Critical"
                if first_stockout_day <= 3
                else "High"
            )
        elif available_stock <= float(row.safety_stock):
            risk_level = "Medium"
        else:
            risk_level = "Low"

        revenue_exposure = (
            unfulfilled_units
            * float(row.unit_price)
        )

        records.append({
            "supplier_id": supplier["supplier_id"],
            "product_id": row.product_id,
            "product_name": row.product_name,
            "category": row.category,
            "warehouse_id": row.warehouse_id,
            "scenario": scenario,
            "duration_days": duration,
            "capacity_loss_pct": capacity_loss,
            "stock_on_hand": starting_stock,
            "quarantined_stock": quarantined_stock,
            "daily_demand": round(
                daily_demand, 3
            ),
            "baseline_daily_inbound": round(
                baseline_daily_inbound, 3
            ),
            "disrupted_daily_inbound": round(
                disrupted_daily_inbound, 3
            ),
            "estimated_lost_inbound_units": round(
                expected_lost_inbound, 2
            ),
            "simulated_requested_units": round(
                total_requested, 2
            ),
            "simulated_fulfilled_units": round(
                total_fulfilled, 2
            ),
            "simulated_unfulfilled_units": round(
                unfulfilled_units, 2
            ),
            "projected_ending_stock": round(
                available_stock, 2
            ),
            "first_stockout_day": first_stockout_day,
            "recommended_replenishment_units": (
                recommended_replenishment
            ),
            "estimated_revenue_exposure_inr": round(
                revenue_exposure, 2
            ),
            "risk_level": risk_level
        })

    return (
        pd.DataFrame(records),
        pd.DataFrame(daily_records)
    )


# ============================================================
# 7. PURCHASE ORDER IMPACT
# ============================================================

def analyze_purchase_orders(
    purchase_orders,
    supplier_id,
    scenario,
    duration
):
    columns = [
        "purchase_order_id",
        "supplier_id",
        "product_id",
        "quantity",
        "status",
        "scenario",
        "estimated_delay_days",
        "simulated_status"
    ]

    if purchase_orders is None:
        return pd.DataFrame(columns=columns)

    orders = purchase_orders[
        purchase_orders["supplier_id"]
        == supplier_id
    ].copy()

    if orders.empty:
        return pd.DataFrame(columns=columns)

    active_statuses = {
        "pending",
        "approved",
        "ordered",
        "processing",
        "in_transit",
        "shipped"
    }

    orders["scenario"] = scenario

    orders["estimated_delay_days"] = (
        orders["status"].astype(str)
        .str.lower()
        .isin(active_statuses)
        .astype(int)
        * duration
    )

    orders["simulated_status"] = np.where(
        orders["estimated_delay_days"] > 0,
        "At Risk",
        "Not Affected"
    )

    return orders[
        columns
    ]


# ============================================================
# 8. ALTERNATIVE SUPPLIERS
# ============================================================

def recommend_alternatives(
    suppliers,
    affected_supplier_id
):
    """
    Rank alternative suppliers by recorded risk,
    delivery reliability, defects and lead time.

    IMPORTANT:
    The source datasets do not contain supplier-to-SKU
    capability mappings. These are screening candidates,
    NOT verified substitutes for affected products.
    """

    alternatives = suppliers[
        suppliers["supplier_id"]
        != affected_supplier_id
    ].copy()

    if alternatives.empty:
        return alternatives

    alternatives = alternatives.sort_values(
        [
            "risk_score",
            "defect_rate",
            "lead_time_days"
        ],
        ascending=[True, True, True]
    )

    alternatives["verification_required"] = True

    alternatives["recommendation_note"] = (
        "Candidate only: verify product compatibility, "
        "capacity, price, quality and contract eligibility."
    )

    return alternatives.head(10)


# ============================================================
# 9. CORPORATE ESCALATION ALERTS
# ============================================================

def generate_alerts(
    impact_df,
    supplier
):
    alerts = []

    for index, row in enumerate(
        impact_df.itertuples(index=False),
        start=1
    ):
        if row.risk_level not in [
            "High",
            "Critical"
        ]:
            continue

        alerts.append({
            "alert_id": f"SUP-ALERT-{index:06d}",
            "created_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "type": "SUPPLIER_FAILURE",
            "severity": row.risk_level,
            "supplier_id": supplier["supplier_id"],
            "supplier_name": supplier["supplier_name"],
            "product_id": row.product_id,
            "warehouse_id": row.warehouse_id,
            "scenario": row.scenario,
            "recipient_role": (
                "Operations Director"
                if row.risk_level == "Critical"
                else "Procurement Manager"
            ),
            "department": "Procurement",
            "estimated_revenue_exposure_inr": (
                row.estimated_revenue_exposure_inr
            ),
            "message": (
                f"[SIMULATION] Supplier disruption: "
                f"{supplier['supplier_name']} / "
                f"{row.product_id} / {row.warehouse_id}"
            ),
            "requires_human_approval": True,
            "delivery_status": "Not Sent"
        })

    return pd.DataFrame(
        alerts,
        columns=[
            "alert_id",
            "created_at",
            "type",
            "severity",
            "supplier_id",
            "supplier_name",
            "product_id",
            "warehouse_id",
            "scenario",
            "recipient_role",
            "department",
            "estimated_revenue_exposure_inr",
            "message",
            "requires_human_approval",
            "delivery_status"
        ]
    )


# ============================================================
# 10. KPI CALCULATION
# ============================================================

def calculate_kpis(
    impact_df,
    purchase_orders_df,
    alerts_df,
    supplier
):
    requested = float(
        impact_df[
            "simulated_requested_units"
        ].sum()
    )

    fulfilled = float(
        impact_df[
            "simulated_fulfilled_units"
        ].sum()
    )

    return {
        "supplier_id": str(
            supplier["supplier_id"]
        ),
        "supplier_name": str(
            supplier["supplier_name"]
        ),
        "affected_products": int(
            impact_df["product_id"].nunique()
        ),
        "affected_warehouses": int(
            impact_df["warehouse_id"].nunique()
        ),
        "affected_sku_warehouse_pairs": int(
            len(impact_df)
        ),
        "simulated_requested_units": round(
            requested, 2
        ),
        "simulated_fulfilled_units": round(
            fulfilled, 2
        ),
        "simulated_unfulfilled_units": round(
            float(
                impact_df[
                    "simulated_unfulfilled_units"
                ].sum()
            ),
            2
        ),
        "fulfillment_rate_pct": round(
            fulfilled / requested * 100,
            2
        ) if requested > 0 else 100.0,
        "estimated_revenue_exposure_inr": round(
            float(
                impact_df[
                    "estimated_revenue_exposure_inr"
                ].sum()
            ),
            2
        ),
        "recommended_replenishment_units": int(
            impact_df[
                "recommended_replenishment_units"
            ].sum()
        ),
        "critical_risk_count": int(
            impact_df["risk_level"]
            .eq("Critical")
            .sum()
        ),
        "high_risk_count": int(
            impact_df["risk_level"]
            .eq("High")
            .sum()
        ),
        "purchase_orders_at_risk": int(
            purchase_orders_df[
                "simulated_status"
            ].eq("At Risk").sum()
        ),
        "simulated_alerts": int(
            len(alerts_df)
        )
    }


# ============================================================
# 11. VISUALIZATION
# ============================================================

def create_charts(
    impact_df,
    daily_df,
    output_dir
):
    daily = (
        daily_df.groupby(
            "day",
            as_index=False
        )[
            [
                "requested_units",
                "fulfilled_units",
                "unfulfilled_units"
            ]
        ].sum()
    )

    plt.figure(figsize=(11, 5))

    plt.plot(
        daily["day"],
        daily["requested_units"],
        label="Requested"
    )

    plt.plot(
        daily["day"],
        daily["fulfilled_units"],
        label="Fulfilled"
    )

    plt.plot(
        daily["day"],
        daily["unfulfilled_units"],
        label="Unfulfilled"
    )

    plt.title(
        "Supplier Failure — Daily Fulfillment"
    )
    plt.xlabel("Simulation Day")
    plt.ylabel("Units")
    plt.legend()
    plt.tight_layout()

    plt.savefig(
        output_dir / "daily_fulfillment.png",
        dpi=150
    )

    plt.close()

    top = (
        impact_df.sort_values(
            "estimated_revenue_exposure_inr",
            ascending=False
        )
        .head(15)
    )

    labels = (
        top["product_id"].astype(str)
        + " / "
        + top["warehouse_id"].astype(str)
    )

    plt.figure(figsize=(12, 6))

    plt.barh(
        labels,
        top[
            "estimated_revenue_exposure_inr"
        ]
    )

    plt.gca().invert_yaxis()
    plt.title(
        "Estimated Revenue Exposure by SKU/Warehouse"
    )
    plt.xlabel("INR")
    plt.tight_layout()

    plt.savefig(
        output_dir / "revenue_exposure.png",
        dpi=150
    )

    plt.close()

    risk_counts = (
        impact_df["risk_level"]
        .value_counts()
        .reindex(
            ["Low", "Medium", "High", "Critical"],
            fill_value=0
        )
    )

    plt.figure(figsize=(9, 5))

    plt.bar(
        risk_counts.index,
        risk_counts.values
    )

    plt.title(
        "Supplier Failure — Inventory Risk Distribution"
    )
    plt.ylabel("SKU/Warehouse Combinations")
    plt.tight_layout()

    plt.savefig(
        output_dir / "risk_distribution.png",
        dpi=150
    )

    plt.close()


# ============================================================
# 12. EXPORT REPORTS
# ============================================================

def export_results(
    impact_df,
    daily_df,
    purchase_orders_df,
    alternatives_df,
    alerts_df,
    kpis,
    args,
    output_dir
):
    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    impact_df.to_csv(
        output_dir / "supplier_failure_impact.csv",
        index=False
    )

    daily_df.to_csv(
        output_dir / "supplier_failure_daily.csv",
        index=False
    )

    purchase_orders_df.to_csv(
        output_dir / "purchase_orders_at_risk.csv",
        index=False
    )

    alternatives_df.to_csv(
        output_dir / "alternative_suppliers.csv",
        index=False
    )

    alerts_df.to_csv(
        output_dir / "supplier_failure_alerts.csv",
        index=False
    )

    audit = pd.DataFrame([
        {
            "event_id": "SUP-EVT-000001",
            "event_type": "SUPPLIER_FAILURE_SIMULATED",
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
            "supplier_id": kpis["supplier_id"],
            "scenario": args.scenario,
            "details": (
                "Synthetic disruption scenario executed"
            ),
            "simulation": True
        },
        {
            "event_id": "SUP-EVT-000002",
            "event_type": "IMPACT_ASSESSMENT_COMPLETED",
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
            "supplier_id": kpis["supplier_id"],
            "scenario": args.scenario,
            "details": (
                f"Affected products: "
                f"{kpis['affected_products']}"
            ),
            "simulation": True
        },
        {
            "event_id": "SUP-EVT-000003",
            "event_type": "ESCALATION_ALERTS_GENERATED",
            "timestamp": datetime.now(
                timezone.utc
            ).isoformat(),
            "supplier_id": kpis["supplier_id"],
            "scenario": args.scenario,
            "details": (
                f"Alerts generated: "
                f"{kpis['simulated_alerts']}"
            ),
            "simulation": True
        }
    ])

    audit.to_csv(
        output_dir / "supplier_failure_audit_log.csv",
        index=False
    )

    report = {
        "project": "SupplyChainAI",
        "module": "Supplier Failure Simulation",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "simulation_only": True,
        "scenario": args.scenario,
        "scenario_description": (
            SCENARIOS[args.scenario]["description"]
        ),
        "kpis": kpis,
        "limitations": [
            "Demand is estimated from historical sales.",
            "Baseline inbound supply is assumed to match demand.",
            "No actual inbound shipment schedule is simulated.",
            "Purchase order delays are hypothetical.",
            "Alternative suppliers are unverified candidates.",
            "No real procurement action is performed.",
            "Revenue exposure is not realized revenue loss.",
            "Alerts are not sent.",
            "No production records are modified."
        ]
    }

    with (
        output_dir / "supplier_failure_report.json"
    ).open(
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            report,
            file,
            indent=2
        )


# ============================================================
# 13. MAIN
# ============================================================

def main():
    args = parse_args()

    config = SCENARIOS[
        args.scenario
    ]

    duration = (
        args.duration
        if args.duration is not None
        else config["default_duration"]
    )

    capacity_loss = (
        args.capacity_loss
        if args.capacity_loss is not None
        else config["capacity_loss"]
    )

    output_dir = (
        args.output.resolve()
    )

    print("=" * 75)
    print("SUPPLYCHAINAI — SUPPLIER FAILURE SIMULATION")
    print("=" * 75)

    print(f"Scenario: {args.scenario}")
    print(f"Duration: {duration} days")
    print(f"Capacity loss: {capacity_loss}%")

    data = load_datasets()

    supplier = select_supplier(
        data["suppliers"],
        args.supplier
    )

    print(
        f"Selected supplier: "
        f"{supplier['supplier_name']} "
        f"({supplier['supplier_id']})"
    )

    impact_df, daily_df = (
        simulate_supplier_failure(
            data=data,
            supplier=supplier,
            scenario=args.scenario,
            duration=duration,
            capacity_loss=capacity_loss,
            history_days=args.history_days
        )
    )

    purchase_orders_df = analyze_purchase_orders(
        data["purchase_orders"],
        supplier["supplier_id"],
        args.scenario,
        duration
    )

    alternatives_df = recommend_alternatives(
        data["suppliers"],
        supplier["supplier_id"]
    )

    alerts_df = generate_alerts(
        impact_df,
        supplier
    )

    kpis = calculate_kpis(
        impact_df,
        purchase_orders_df,
        alerts_df,
        supplier
    )

    create_charts(
        impact_df,
        daily_df,
        output_dir
    )

    export_results(
        impact_df,
        daily_df,
        purchase_orders_df,
        alternatives_df,
        alerts_df,
        kpis,
        args,
        output_dir
    )

    print("\nSUPPLIER FAILURE KPIs")
    print(
        json.dumps(
            kpis,
            indent=2
        )
    )

    print("\nTOP AFFECTED PRODUCTS")

    print(
        impact_df.sort_values(
            "estimated_revenue_exposure_inr",
            ascending=False
        )[
            [
                "product_id",
                "warehouse_id",
                "risk_level",
                "first_stockout_day",
                "simulated_unfulfilled_units",
                "recommended_replenishment_units"
            ]
        ].head(20).to_string(index=False)
    )

    print("\nGenerated reports:")

    for path in sorted(
        output_dir.iterdir()
    ):
        if path.is_file():
            print(path)

    print("\nSupplier failure simulation completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
