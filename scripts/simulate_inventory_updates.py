"""Planned module: simulate inventory updates. Implementation pending."""

#!/usr/bin/env python3
"""
SupplyChainAI — Demand Spike Simulation

File:
    scripts/simulate_demand_spike.py

Features:
    01. Load products, sales, inventory and suppliers
    02. Select affected products and warehouses
    03. Simulate demand spikes
    04. Estimate baseline demand
    05. Project inventory depletion
    06. Calculate stockout risk
    07. Estimate lost sales and revenue exposure
    08. Calculate safety stock requirements
    09. Generate replenishment recommendations
    10. Assess supplier lead-time exposure
    11. Identify warehouse-level pressure
    12. Create simulated corporate alerts
    13. Export CSV and JSON reports
    14. Generate visualization charts

Install:
    pip install pandas numpy matplotlib

Examples:
    python scripts/simulate_demand_spike.py
    python scripts/simulate_demand_spike.py --spike 200
    python scripts/simulate_demand_spike.py --duration 14
    python scripts/simulate_demand_spike.py --category Electronics
    python scripts/simulate_demand_spike.py --warehouse WH-001
    python scripts/simulate_demand_spike.py --scenario festival
    python scripts/simulate_demand_spike.py --scenario viral
    python scripts/simulate_demand_spike.py --scenario supply_shock

Important:
    - Simulation only.
    - No real purchase orders are created.
    - No inventory database records are modified.
    - No real notifications are dispatched.
    - Revenue impact is an estimate, not realized loss.
    - Demand is based on historical sales, not verified
      unconstrained customer demand.
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
# 1. CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"

OUTPUT_DIR = (
    ROOT / "reports" / "demand_spike"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)

SCENARIOS = {
    "normal": {
        "spike_multiplier": 1.5,
        "duration_days": 7,
        "description": "Moderate unexpected demand increase"
    },
    "festival": {
        "spike_multiplier": 2.5,
        "duration_days": 14,
        "description": "Festival and seasonal shopping surge"
    },
    "viral": {
        "spike_multiplier": 4.0,
        "duration_days": 7,
        "description": "Viral product demand surge"
    },
    "promotion": {
        "spike_multiplier": 3.0,
        "duration_days": 10,
        "description": "Marketing campaign demand surge"
    },
    "supply_shock": {
        "spike_multiplier": 2.0,
        "duration_days": 21,
        "description": (
            "Demand increase combined with "
            "supplier lead-time disruption"
        )
    }
}

SERVICE_LEVEL_Z = 1.65
DEFAULT_LEAD_TIME_DAYS = 7
DEFAULT_HISTORY_DAYS = 28

RISK_LEVELS = [
    "Low",
    "Medium",
    "High",
    "Critical"
]


# ============================================================
# 2. CLI
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="SupplyChainAI demand spike simulator"
    )

    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS),
        default="festival"
    )

    parser.add_argument(
        "--spike",
        type=float,
        default=None,
        help="Demand increase percentage, e.g. 200 means +200%%"
    )

    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        help="Simulation duration in days"
    )

    parser.add_argument(
        "--category",
        type=str,
        default=None
    )

    parser.add_argument(
        "--warehouse",
        type=str,
        default=None
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

    args = parser.parse_args()

    if args.spike is not None:
        if not 0 <= args.spike <= 10000:
            parser.error(
                "--spike must be between 0 and 10000"
            )

    if args.duration is not None:
        if not 1 <= args.duration <= 365:
            parser.error(
                "--duration must be between 1 and 365"
            )

    if not 7 <= args.history_days <= 365:
        parser.error(
            "--history-days must be between 7 and 365"
        )

    return args


# ============================================================
# 3. DATA VALIDATION
# ============================================================

def require_columns(df, columns, name):
    missing = sorted(
        set(columns) - set(df.columns)
    )

    if missing:
        raise ValueError(
            f"{name} missing columns: {missing}"
        )


def load_csv(filename, required_columns):
    path = DATA_DIR / filename

    if not path.exists():
        raise FileNotFoundError(
            f"Missing dataset: {path}\n"
            "Run scripts/generate_demo_data.py first."
        )

    df = pd.read_csv(path)

    require_columns(
        df,
        required_columns,
        filename
    )

    return df


# ============================================================
# 4. LOAD DATA
# ============================================================

def load_datasets():
    products = load_csv(
        "products.csv",
        [
            "product_id",
            "product_name",
            "category",
            "supplier_id",
            "unit_price"
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

    suppliers = load_csv(
        "suppliers.csv",
        [
            "supplier_id",
            "lead_time_days"
        ]
    )

    sales["date"] = pd.to_datetime(
        sales["date"],
        errors="coerce"
    )

    if sales["date"].isna().any():
        raise ValueError(
            "Sales contains invalid dates."
        )

    for column in [
        "quantity_sold"
    ]:
        sales[column] = pd.to_numeric(
            sales[column],
            errors="raise"
        )

    for column in [
        "stock_on_hand",
        "reorder_point",
        "safety_stock"
    ]:
        inventory[column] = pd.to_numeric(
            inventory[column],
            errors="raise"
        )

    products["unit_price"] = pd.to_numeric(
        products["unit_price"],
        errors="raise"
    )

    suppliers["lead_time_days"] = pd.to_numeric(
        suppliers["lead_time_days"],
        errors="raise"
    )

    if (
        (sales["quantity_sold"] < 0).any()
        or (inventory["stock_on_hand"] < 0).any()
        or (products["unit_price"] < 0).any()
        or (suppliers["lead_time_days"] <= 0).any()
    ):
        raise ValueError(
            "Negative demand, stock, price, or invalid "
            "supplier lead time found."
        )

    if inventory.duplicated(
        ["product_id", "warehouse_id"]
    ).any():
        raise ValueError(
            "Inventory contains duplicate SKU/warehouse pairs."
        )

    if products["product_id"].duplicated().any():
        raise ValueError(
            "Products contains duplicate product IDs."
        )

    if suppliers["supplier_id"].duplicated().any():
        raise ValueError(
            "Suppliers contains duplicate supplier IDs."
        )

    return products, sales, inventory, suppliers


# ============================================================
# 5. BASELINE DEMAND
# ============================================================

def calculate_baseline_demand(
    sales,
    inventory,
    history_days
):
    """
    Calculate daily demand per product/warehouse.

    Missing sales days are treated as zero sales.
    This is not necessarily zero customer demand.

    The history window ends at the latest recorded
    sales date, rather than the current system date.
    """

    latest_date = sales["date"].max().normalize()

    start_date = (
        latest_date
        - pd.Timedelta(days=history_days - 1)
    )

    recent = sales[
        (sales["date"] >= start_date)
        & (sales["date"] <= latest_date)
    ].copy()

    daily = (
        recent.groupby(
            ["product_id", "warehouse_id"],
            as_index=False
        )["quantity_sold"]
        .sum()
    )

    daily["baseline_daily_demand"] = (
        daily["quantity_sold"] / history_days
    )

    baseline = inventory[
        ["product_id", "warehouse_id"]
    ].merge(
        daily[
            [
                "product_id",
                "warehouse_id",
                "baseline_daily_demand"
            ]
        ],
        on=["product_id", "warehouse_id"],
        how="left"
    )

    baseline["baseline_daily_demand"] = (
        baseline["baseline_daily_demand"]
        .fillna(0.0)
    )

    return baseline


# ============================================================
# 6. RISK CLASSIFICATION
# ============================================================

def classify_risk(
    stockout_day,
    duration_days,
    coverage_ratio
):
    if stockout_day is not None:
        if stockout_day <= 2:
            return "Critical"

        if stockout_day <= duration_days:
            return "High"

    if coverage_ratio < 1.25:
        return "Medium"

    return "Low"


# ============================================================
# 7. SPIKE SIMULATION
# ============================================================

def simulate_demand_spike(
    products,
    sales,
    inventory,
    suppliers,
    args
):
    scenario_config = SCENARIOS[
        args.scenario
    ]

    multiplier = (
        1.0 + args.spike / 100
        if args.spike is not None
        else scenario_config["spike_multiplier"]
    )

    duration = (
        args.duration
        if args.duration is not None
        else scenario_config["duration_days"]
    )

    baseline = calculate_baseline_demand(
        sales,
        inventory,
        args.history_days
    )

    frame = inventory.merge(
        baseline,
        on=["product_id", "warehouse_id"],
        how="left",
        validate="one_to_one"
    )

    frame = frame.merge(
        products[
            [
                "product_id",
                "product_name",
                "category",
                "supplier_id",
                "unit_price"
            ]
        ],
        on="product_id",
        how="left",
        validate="many_to_one"
    )

    frame = frame.merge(
        suppliers[
            [
                "supplier_id",
                "lead_time_days"
            ]
        ],
        on="supplier_id",
        how="left",
        validate="many_to_one"
    )

    if frame[
        ["product_name", "unit_price"]
    ].isna().any().any():
        raise ValueError(
            "Inventory references unknown products."
        )

    frame["lead_time_days"] = (
        frame["lead_time_days"]
        .fillna(DEFAULT_LEAD_TIME_DAYS)
    )

    if args.category:
        frame = frame[
            frame["category"].str.casefold()
            == args.category.casefold()
        ].copy()

    if args.warehouse:
        frame = frame[
            frame["warehouse_id"]
            == args.warehouse
        ].copy()

    if frame.empty:
        raise ValueError(
            "No inventory records match the selected filters."
        )

    rng = np.random.default_rng(
        args.seed
    )

    # In the supply-shock scenario, supplier lead times
    # increase by 50%. This affects replenishment risk,
    # not the immediate inventory-depletion trajectory.
    frame["effective_lead_time_days"] = (
        frame["lead_time_days"]
        * (
            1.5
            if args.scenario == "supply_shock"
            else 1.0
        )
    )

    frame["spike_multiplier"] = multiplier

    frame["spike_daily_demand"] = (
        frame["baseline_daily_demand"]
        * multiplier
    )

    # Optional stochastic daily variation.
    # Per-SKU daily variation remains reproducible.
    records = []
    daily_records = []

    for row in frame.itertuples(index=False):
        available_stock = float(
            row.stock_on_hand
        )

        baseline_daily = float(
            row.baseline_daily_demand
        )

        spike_daily = float(
            row.spike_daily_demand
        )

        total_requested = 0.0
        total_fulfilled = 0.0
        first_stockout_day = None

        daily_values = []

        for day in range(1, duration + 1):
            # Poisson approximation of daily units.
            requested = int(
                rng.poisson(
                    max(spike_daily, 0)
                )
            )

            fulfilled = min(
                available_stock,
                requested
            )

            lost_units = (
                requested - fulfilled
            )

            available_stock -= fulfilled

            total_requested += requested
            total_fulfilled += fulfilled

            if (
                lost_units > 0
                and first_stockout_day is None
            ):
                first_stockout_day = day

            daily_values.append(requested)

            daily_records.append({
                "day": day,
                "product_id": row.product_id,
                "warehouse_id": row.warehouse_id,
                "requested_units": requested,
                "fulfilled_units": fulfilled,
                "unfulfilled_units": lost_units,
                "ending_stock": available_stock
            })

        lost_sales_units = (
            total_requested - total_fulfilled
        )

        projected_baseline_demand = (
            baseline_daily * duration
        )

        projected_spike_demand = (
            spike_daily * duration
        )

        additional_demand = max(
            projected_spike_demand
            - projected_baseline_demand,
            0
        )

        # Estimate daily variability from simulated
        # spike demand. This is not historical volatility.
        daily_std = (
            float(np.std(daily_values, ddof=1))
            if len(daily_values) > 1
            else math.sqrt(
                max(spike_daily, 0)
            )
        )

        effective_lead_time = float(
            row.effective_lead_time_days
        )

        recommended_safety_stock = (
            SERVICE_LEVEL_Z
            * daily_std
            * math.sqrt(effective_lead_time)
        )

        reorder_point = (
            spike_daily * effective_lead_time
            + recommended_safety_stock
        )

        coverage_ratio = (
            float(row.stock_on_hand)
            / projected_spike_demand
            if projected_spike_demand > 0
            else float("inf")
        )

        risk = classify_risk(
            first_stockout_day,
            duration,
            coverage_ratio
        )

        # Planning quantity covers the greater of:
        # (a) remaining scenario demand, or
        # (b) replenishment lead-time demand,
        # plus safety stock.
        #
        # This is an illustrative policy, not a
        # constrained purchasing optimization.
        target_stock = (
            max(
                projected_spike_demand,
                spike_daily * effective_lead_time
            )
            + recommended_safety_stock
        )

        reorder_quantity = max(
            math.ceil(
                target_stock - float(row.stock_on_hand)
            ),
            0
        )

        revenue_exposure = (
            lost_sales_units
            * float(row.unit_price)
        )

        records.append({
            "product_id": row.product_id,
            "product_name": row.product_name,
            "category": row.category,
            "warehouse_id": row.warehouse_id,
            "supplier_id": row.supplier_id,
            "unit_price": float(row.unit_price),
            "stock_on_hand": float(row.stock_on_hand),
            "baseline_daily_demand": round(
                baseline_daily, 3
            ),
            "spike_daily_demand": round(
                spike_daily, 3
            ),
            "spike_multiplier": multiplier,
            "simulation_days": duration,
            "expected_additional_demand": round(
                additional_demand, 2
            ),
            "simulated_requested_units": int(
                total_requested
            ),
            "simulated_fulfilled_units": int(
                total_fulfilled
            ),
            "simulated_unfulfilled_units": int(
                lost_sales_units
            ),
            "projected_ending_stock": round(
                available_stock, 2
            ),
            "first_stockout_day": first_stockout_day,
            "effective_lead_time_days": round(
                effective_lead_time, 2
            ),
            "recommended_safety_stock": math.ceil(
                recommended_safety_stock
            ),
            "recommended_reorder_point": math.ceil(
                reorder_point
            ),
            "recommended_reorder_quantity": (
                reorder_quantity
            ),
            "estimated_revenue_exposure_inr": round(
                revenue_exposure, 2
            ),
            "risk_level": risk
        })

    results_df = pd.DataFrame(records)

    daily_df = pd.DataFrame(
        daily_records
    )

    return results_df, daily_df, multiplier, duration


# ============================================================
# 8. SIMULATED CORPORATE ALERTS
# ============================================================

def generate_alerts(results_df):
    rows = []

    alert_id = 1

    for row in results_df.itertuples():
        if row.risk_level not in [
            "High",
            "Critical"
        ]:
            continue

        severity = row.risk_level

        rows.append({
            "alert_id": f"DSP-{alert_id:06d}",
            "type": "DEMAND_SPIKE_STOCKOUT_RISK",
            "severity": severity,
            "product_id": row.product_id,
            "warehouse_id": row.warehouse_id,
            "supplier_id": row.supplier_id,
            "department": "Inventory Management",
            "recipient_role": (
                "Operations Director"
                if severity == "Critical"
                else "Inventory Manager"
            ),
            "message": (
                f"[SIMULATION] {severity} stockout risk "
                f"for {row.product_id} at "
                f"{row.warehouse_id}. "
                f"Suggested reorder: "
                f"{row.recommended_reorder_quantity} units."
            ),
            "requires_approval": (
                severity == "Critical"
            ),
            "delivery_status": "Not Sent",
            "created_at": datetime.now(
                timezone.utc
            ).isoformat()
        })

        alert_id += 1

    return pd.DataFrame(
        rows,
        columns=[
            "alert_id",
            "type",
            "severity",
            "product_id",
            "warehouse_id",
            "supplier_id",
            "department",
            "recipient_role",
            "message",
            "requires_approval",
            "delivery_status",
            "created_at"
        ]
    )


# ============================================================
# 9. WAREHOUSE PRESSURE
# ============================================================

def calculate_warehouse_pressure(results_df):
    warehouse = (
        results_df.groupby(
            "warehouse_id",
            as_index=False
        )
        .agg(
            products=("product_id", "nunique"),
            starting_stock=("stock_on_hand", "sum"),
            requested_units=(
                "simulated_requested_units",
                "sum"
            ),
            fulfilled_units=(
                "simulated_fulfilled_units",
                "sum"
            ),
            unfulfilled_units=(
                "simulated_unfulfilled_units",
                "sum"
            ),
            revenue_exposure_inr=(
                "estimated_revenue_exposure_inr",
                "sum"
            ),
            recommended_reorder_units=(
                "recommended_reorder_quantity",
                "sum"
            )
        )
    )

    warehouse["fulfillment_rate_pct"] = np.where(
        warehouse["requested_units"] > 0,
        warehouse["fulfilled_units"]
        / warehouse["requested_units"] * 100,
        100.0
    )

    return warehouse


# ============================================================
# 10. VISUALIZATIONS
# ============================================================

def create_charts(
    results_df,
    daily_df,
    warehouse_df
):
    risk_counts = (
        results_df["risk_level"]
        .value_counts()
        .reindex(
            RISK_LEVELS,
            fill_value=0
        )
    )

    plt.figure(figsize=(10, 5))
    plt.bar(
        risk_counts.index,
        risk_counts.values
    )
    plt.title(
        "Demand Spike — Stockout Risk Distribution"
    )
    plt.ylabel("SKU/Warehouse Combinations")
    plt.tight_layout()
    plt.savefig(
        OUTPUT_DIR / "stockout_risk.png",
        dpi=150
    )
    plt.close()

    daily_summary = (
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
        daily_summary["day"],
        daily_summary["requested_units"],
        label="Requested"
    )

    plt.plot(
        daily_summary["day"],
        daily_summary["fulfilled_units"],
        label="Fulfilled"
    )

    plt.plot(
        daily_summary["day"],
        daily_summary["unfulfilled_units"],
        label="Unfulfilled"
    )

    plt.title(
        "Demand Spike — Daily Fulfillment"
    )
    plt.xlabel("Simulation Day")
    plt.ylabel("Units")
    plt.legend()
    plt.tight_layout()

    plt.savefig(
        OUTPUT_DIR / "daily_fulfillment.png",
        dpi=150
    )
    plt.close()

    top_products = (
        results_df.sort_values(
            "estimated_revenue_exposure_inr",
            ascending=False
        )
        .head(15)
    )

    labels = (
        top_products["product_id"]
        + " / "
        + top_products["warehouse_id"]
    )

    plt.figure(figsize=(12, 6))

    plt.barh(
        labels,
        top_products[
            "estimated_revenue_exposure_inr"
        ]
    )

    plt.title(
        "Top 15 Estimated Revenue Exposures"
    )
    plt.xlabel("INR")
    plt.gca().invert_yaxis()
    plt.tight_layout()

    plt.savefig(
        OUTPUT_DIR / "revenue_exposure.png",
        dpi=150
    )
    plt.close()

    plt.figure(figsize=(11, 5))

    plt.bar(
        warehouse_df["warehouse_id"],
        warehouse_df["unfulfilled_units"]
    )

    plt.title(
        "Warehouse Demand Pressure"
    )
    plt.ylabel("Simulated Unfulfilled Units")
    plt.tight_layout()

    plt.savefig(
        OUTPUT_DIR / "warehouse_pressure.png",
        dpi=150
    )
    plt.close()


# ============================================================
# 11. KPIs
# ============================================================

def calculate_kpis(
    results_df,
    alerts_df,
    warehouse_df,
    multiplier,
    duration
):
    requested = int(
        results_df[
            "simulated_requested_units"
        ].sum()
    )

    fulfilled = int(
        results_df[
            "simulated_fulfilled_units"
        ].sum()
    )

    unfulfilled = int(
        results_df[
            "simulated_unfulfilled_units"
        ].sum()
    )

    return {
        "affected_sku_warehouse_pairs": int(
            len(results_df)
        ),
        "affected_products": int(
            results_df["product_id"].nunique()
        ),
        "affected_warehouses": int(
            len(warehouse_df)
        ),
        "spike_multiplier": multiplier,
        "duration_days": duration,
        "requested_units": requested,
        "fulfilled_units": fulfilled,
        "unfulfilled_units": unfulfilled,
        "fulfillment_rate_pct": round(
            fulfilled / requested * 100,
            2
        ) if requested > 0 else 100.0,
        "estimated_revenue_exposure_inr": round(
            float(
                results_df[
                    "estimated_revenue_exposure_inr"
                ].sum()
            ),
            2
        ),
        "recommended_reorder_units": int(
            results_df[
                "recommended_reorder_quantity"
            ].sum()
        ),
        "critical_risk_count": int(
            results_df["risk_level"]
            .eq("Critical")
            .sum()
        ),
        "high_risk_count": int(
            results_df["risk_level"]
            .eq("High")
            .sum()
        ),
        "simulated_alerts": int(
            len(alerts_df)
        )
    }


# ============================================================
# 12. EXPORT
# ============================================================

def export_results(
    results_df,
    daily_df,
    warehouse_df,
    alerts_df,
    kpis,
    args
):
    results_df.to_csv(
        OUTPUT_DIR / "demand_spike_predictions.csv",
        index=False
    )

    daily_df.to_csv(
        OUTPUT_DIR / "daily_demand_simulation.csv",
        index=False
    )

    warehouse_df.to_csv(
        OUTPUT_DIR / "warehouse_pressure.csv",
        index=False
    )

    alerts_df.to_csv(
        OUTPUT_DIR / "simulated_spike_alerts.csv",
        index=False
    )

    report = {
        "project": "SupplyChainAI",
        "script": "simulate_demand_spike.py",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "scenario": args.scenario,
        "simulation_only": True,
        "kpis": kpis,
        "limitations": [
            "Demand is estimated from historical sales.",
            "No incoming purchase orders are modeled.",
            "No actual inventory transactions occur.",
            "No supplier capacity constraints are modeled.",
            "Replenishment is a planning recommendation only.",
            "Revenue exposure is not realized revenue loss.",
            "Alerts are generated but not delivered.",
            "Simulation does not independently validate ML models."
        ]
    }

    with (
        OUTPUT_DIR / "demand_spike_report.json"
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

    print("=" * 75)
    print("SUPPLYCHAINAI — DEMAND SPIKE SIMULATION")
    print("=" * 75)

    print(f"Scenario: {args.scenario}")

    products, sales, inventory, suppliers = (
        load_datasets()
    )

    (
        results_df,
        daily_df,
        multiplier,
        duration
    ) = simulate_demand_spike(
        products,
        sales,
        inventory,
        suppliers,
        args
    )

    warehouse_df = calculate_warehouse_pressure(
        results_df
    )

    alerts_df = generate_alerts(
        results_df
    )

    kpis = calculate_kpis(
        results_df,
        alerts_df,
        warehouse_df,
        multiplier,
        duration
    )

    create_charts(
        results_df,
        daily_df,
        warehouse_df
    )

    export_results(
        results_df,
        daily_df,
        warehouse_df,
        alerts_df,
        kpis,
        args
    )

    print("\nSIMULATION KPIs")
    print(
        json.dumps(
            kpis,
            indent=2
        )
    )

    print("\nTOP STOCKOUT RISKS")

    print(
        results_df.sort_values(
            [
                "simulated_unfulfilled_units",
                "estimated_revenue_exposure_inr"
            ],
            ascending=False
        )[
            [
                "product_id",
                "warehouse_id",
                "risk_level",
                "first_stockout_day",
                "simulated_unfulfilled_units",
                "recommended_reorder_quantity"
            ]
        ].head(20).to_string(index=False)
    )

    print("\nGenerated files:")
    for path in sorted(
        OUTPUT_DIR.iterdir()
    ):
        print(
            path.relative_to(ROOT)
        )

    print("\nDemand spike simulation completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
