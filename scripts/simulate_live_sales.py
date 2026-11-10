"""Planned module: simulate live sales. Implementation pending."""

#!/usr/bin/env python3
"""
SupplyChainAI — Inventory Update Simulator

File:
    scripts/simulate_inventory_updates.py

Features:
    01. Load existing inventory datasets
    02. Simulate retail sales and stock reductions
    03. Simulate purchase-order receipts
    04. Simulate customer returns
    05. Simulate inventory adjustments
    06. Simulate warehouse-to-warehouse transfers
    07. Prevent negative inventory
    08. Enforce unique transaction IDs
    09. Detect low stock and critical stock
    10. Generate simulated replenishment alerts
    11. Generate event-stream JSONL
    12. Record stock movement audit history
    13. Export updated inventory snapshots
    14. Produce inventory KPIs
    15. Optional timed event playback

Install:
    pip install pandas numpy

Run:
    python scripts/simulate_inventory_updates.py
    python scripts/simulate_inventory_updates.py --events 500
    python scripts/simulate_inventory_updates.py --events 1000 --seed 42
    python scripts/simulate_inventory_updates.py --realtime --interval 0.5

Safety:
    - Simulation only
    - Original inventory.csv is never modified
    - No production database writes
    - No actual purchase orders
    - No external notifications
    - No Kafka/Redis publishing
    - No real warehouse operations
"""

import argparse
import json
import random
import sys
import time

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


# ============================================================
# 1. PROJECT CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"

OUTPUT_DIR = (
    ROOT / "reports" / "inventory_simulation"
)

EVENT_TYPES = [
    "SALE",
    "PURCHASE_RECEIPT",
    "CUSTOMER_RETURN",
    "STOCK_ADJUSTMENT",
    "WAREHOUSE_TRANSFER"
]

EVENT_WEIGHTS = [
    0.45,
    0.20,
    0.10,
    0.10,
    0.15
]

MAX_EVENTS = 100000


# ============================================================
# 2. CLI
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "SupplyChainAI inventory update simulator"
        )
    )

    parser.add_argument(
        "--events",
        type=int,
        default=300,
        help="Number of simulated business events"
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42
    )

    parser.add_argument(
        "--realtime",
        action="store_true",
        help="Replay events with a configurable delay"
    )

    parser.add_argument(
        "--interval",
        type=float,
        default=0.1,
        help="Seconds between events in realtime mode"
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_DIR
    )

    args = parser.parse_args()

    if not 1 <= args.events <= MAX_EVENTS:
        parser.error(
            f"--events must be between 1 and {MAX_EVENTS}"
        )

    if not 0 <= args.interval <= 60:
        parser.error(
            "--interval must be between 0 and 60"
        )

    return args


# ============================================================
# 3. INPUT VALIDATION
# ============================================================

def load_csv(filename, required_columns):
    path = DATA_DIR / filename

    if not path.exists():
        raise FileNotFoundError(
            f"Missing dataset: {path}\n"
            "Run scripts/generate_demo_data.py first."
        )

    df = pd.read_csv(path)

    missing = (
        set(required_columns)
        - set(df.columns)
    )

    if missing:
        raise ValueError(
            f"{filename} missing columns: "
            f"{sorted(missing)}"
        )

    return df


def load_inventory_data():
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

    products = load_csv(
        "products.csv",
        [
            "product_id",
            "product_name",
            "unit_price"
        ]
    )

    warehouses = load_csv(
        "warehouses.csv",
        [
            "warehouse_id",
            "warehouse_name"
        ]
    )

    if inventory.duplicated(
        ["product_id", "warehouse_id"]
    ).any():
        raise ValueError(
            "Duplicate inventory SKU/warehouse records."
        )

    if products["product_id"].duplicated().any():
        raise ValueError(
            "Duplicate product IDs."
        )

    if warehouses["warehouse_id"].duplicated().any():
        raise ValueError(
            "Duplicate warehouse IDs."
        )

    for column in [
        "stock_on_hand",
        "reorder_point",
        "safety_stock"
    ]:
        values = pd.to_numeric(
            inventory[column],
            errors="raise"
        )

        if (
            values.isna().any()
            or (values < 0).any()
            or (values % 1 != 0).any()
        ):
            raise ValueError(
                f"Invalid inventory values: {column}"
            )

        inventory[column] = values.astype(int)

    product_ids = set(
        products["product_id"]
    )

    warehouse_ids = set(
        warehouses["warehouse_id"]
    )

    if not set(
        inventory["product_id"]
    ).issubset(product_ids):
        raise ValueError(
            "Inventory references unknown products."
        )

    if not set(
        inventory["warehouse_id"]
    ).issubset(warehouse_ids):
        raise ValueError(
            "Inventory references unknown warehouses."
        )

    return inventory, products, warehouses


# ============================================================
# 4. SIMULATION ENGINE
# ============================================================

class InventorySimulator:

    def __init__(
        self,
        inventory,
        products,
        warehouses,
        seed=42
    ):
        self.rng = random.Random(seed)

        self.inventory = inventory.copy()

        self.original_inventory = (
            inventory.copy()
        )

        self.products = products.copy()
        self.warehouses = warehouses.copy()

        self.stock = {}

        self.thresholds = {}

        for row in inventory.itertuples():
            key = (
                row.product_id,
                row.warehouse_id
            )

            self.stock[key] = int(
                row.stock_on_hand
            )

            self.thresholds[key] = {
                "reorder_point": int(
                    row.reorder_point
                ),
                "safety_stock": int(
                    row.safety_stock
                )
            }

        self.product_ids = sorted(
            products["product_id"].tolist()
        )

        self.warehouse_ids = sorted(
            warehouses["warehouse_id"].tolist()
        )

        self.keys = sorted(
            self.stock.keys()
        )

        self.transactions = []
        self.audit_events = []
        self.alerts = []
        self.stream_events = []

        self.processed_ids = set()

        self.event_counter = 0

        self.base_time = datetime(
            2026, 10, 30, 9, 0,
            tzinfo=timezone.utc
        )

    # ========================================================
    # 5. EVENT LOGGING
    # ========================================================

    def log_audit(
        self,
        transaction_id,
        event_type,
        timestamp,
        status,
        details
    ):
        self.audit_events.append({
            "audit_id": (
                f"AUD-{len(self.audit_events) + 1:07d}"
            ),
            "transaction_id": transaction_id,
            "event_type": event_type,
            "timestamp": timestamp.isoformat(),
            "status": status,
            "details": details
        })

    def emit_event(
        self,
        event_type,
        timestamp,
        payload
    ):
        event = {
            "event_id": (
                f"EVT-{len(self.stream_events) + 1:07d}"
            ),
            "event_type": event_type,
            "timestamp": timestamp.isoformat(),
            "simulation": True,
            "payload": payload
        }

        self.stream_events.append(event)

        return event

    # ========================================================
    # 6. STOCK STATUS
    # ========================================================

    def stock_status(self, key):
        quantity = self.stock[key]

        thresholds = self.thresholds[key]

        if quantity <= thresholds["safety_stock"]:
            return "Critical"

        if quantity <= thresholds["reorder_point"]:
            return "Low"

        return "Healthy"

    # ========================================================
    # 7. STOCK ALERTS
    # ========================================================

    def check_alert(
        self,
        key,
        timestamp,
        previous_status
    ):
        current_status = self.stock_status(key)

        if current_status not in [
            "Low",
            "Critical"
        ]:
            return

        # Generate alerts only when the stock status
        # changes into a low/critical state.
        if current_status == previous_status:
            return

        product_id, warehouse_id = key

        alert = {
            "alert_id": (
                f"ALERT-{len(self.alerts) + 1:06d}"
            ),
            "timestamp": timestamp.isoformat(),
            "type": "INVENTORY_THRESHOLD",
            "severity": (
                "Critical"
                if current_status == "Critical"
                else "High"
            ),
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "stock_on_hand": self.stock[key],
            "reorder_point": self.thresholds[
                key
            ]["reorder_point"],
            "safety_stock": self.thresholds[
                key
            ]["safety_stock"],
            "recipient_role": (
                "Operations Director"
                if current_status == "Critical"
                else "Inventory Manager"
            ),
            "message": (
                f"[SIMULATION] {current_status} stock "
                f"for {product_id} at {warehouse_id}"
            ),
            "delivery_status": "Not Sent"
        }

        self.alerts.append(alert)

        self.emit_event(
            "inventory.alert.created",
            timestamp,
            alert
        )

    # ========================================================
    # 8. TRANSACTION PROCESSING
    # ========================================================

    def process_transaction(
        self,
        transaction_id,
        event_type,
        timestamp,
        product_id,
        warehouse_id,
        quantity,
        destination_warehouse=None
    ):
        if transaction_id in self.processed_ids:
            self.log_audit(
                transaction_id,
                event_type,
                timestamp,
                "DUPLICATE",
                {
                    "reason": (
                        "Transaction already processed"
                    )
                }
            )
            return False

        # Mark attempted IDs as processed to prevent
        # replay of rejected events with the same ID.
        self.processed_ids.add(
            transaction_id
        )

        key = (
            product_id,
            warehouse_id
        )

        if key not in self.stock:
            self.log_audit(
                transaction_id,
                event_type,
                timestamp,
                "REJECTED",
                {
                    "reason": "Unknown inventory key"
                }
            )
            return False

        if (
            not isinstance(quantity, int)
            or isinstance(quantity, bool)
            or quantity <= 0
        ):
            self.log_audit(
                transaction_id,
                event_type,
                timestamp,
                "REJECTED",
                {
                    "reason": "Invalid quantity"
                }
            )
            return False

        if event_type not in EVENT_TYPES:
            self.log_audit(
                transaction_id,
                event_type,
                timestamp,
                "REJECTED",
                {
                    "reason": "Unknown event type"
                }
            )
            return False

        before = self.stock[key]
        previous_status = self.stock_status(key)

        destination_key = None
        destination_before = None
        destination_previous_status = None

        if event_type == "WAREHOUSE_TRANSFER":
            if not destination_warehouse:
                self.log_audit(
                    transaction_id,
                    event_type,
                    timestamp,
                    "REJECTED",
                    {
                        "reason": (
                            "Destination warehouse missing"
                        )
                    }
                )
                return False

            destination_key = (
                product_id,
                destination_warehouse
            )

            if (
                destination_key not in self.stock
                or destination_key == key
            ):
                self.log_audit(
                    transaction_id,
                    event_type,
                    timestamp,
                    "REJECTED",
                    {
                        "reason": (
                            "Invalid transfer destination"
                        )
                    }
                )
                return False

            destination_before = self.stock[
                destination_key
            ]

            destination_previous_status = (
                self.stock_status(
                    destination_key
                )
            )

        # Determine stock movement.
        if event_type == "SALE":
            delta = -quantity

        elif event_type == "PURCHASE_RECEIPT":
            delta = quantity

        elif event_type == "CUSTOMER_RETURN":
            delta = quantity

        elif event_type == "STOCK_ADJUSTMENT":
            delta = self.rng.choice(
                [-quantity, quantity]
            )

        elif event_type == "WAREHOUSE_TRANSFER":
            delta = -quantity

        else:
            return False

        if before + delta < 0:
            self.log_audit(
                transaction_id,
                event_type,
                timestamp,
                "REJECTED",
                {
                    "reason": "Insufficient stock",
                    "available": before,
                    "requested": quantity
                }
            )

            self.emit_event(
                "inventory.transaction.rejected",
                timestamp,
                {
                    "transaction_id": transaction_id,
                    "reason": "Insufficient stock",
                    "product_id": product_id,
                    "warehouse_id": warehouse_id
                }
            )

            return False

        # All validations complete. Apply the movement.
        self.stock[key] = before + delta

        if destination_key is not None:
            self.stock[destination_key] = (
                destination_before + quantity
            )

        transaction = {
            "transaction_id": transaction_id,
            "timestamp": timestamp.isoformat(),
            "event_type": event_type,
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "destination_warehouse": (
                destination_warehouse
            ),
            "quantity": quantity,
            "stock_before": before,
            "stock_after": self.stock[key],
            "stock_delta": delta,
            "destination_stock_before": (
                destination_before
            ),
            "destination_stock_after": (
                self.stock[destination_key]
                if destination_key is not None
                else None
            ),
            "status": "Applied",
            "simulation": True
        }

        self.transactions.append(
            transaction
        )

        self.log_audit(
            transaction_id,
            event_type,
            timestamp,
            "APPLIED",
            transaction
        )

        self.emit_event(
            "inventory.stock.updated",
            timestamp,
            transaction
        )

        self.check_alert(
            key,
            timestamp,
            previous_status
        )

        if destination_key is not None:
            self.check_alert(
                destination_key,
                timestamp,
                destination_previous_status
            )

        return True

    # ========================================================
    # 9. GENERATE RANDOM TRANSACTION
    # ========================================================

    def generate_transaction(self, index):
        event_type = self.rng.choices(
            EVENT_TYPES,
            weights=EVENT_WEIGHTS,
            k=1
        )[0]

        key = self.rng.choice(
            self.keys
        )

        product_id, warehouse_id = key

        timestamp = (
            self.base_time
            + timedelta(seconds=index * 10)
        )

        quantity = self.rng.randint(
            1, 30
        )

        destination = None

        if event_type == "PURCHASE_RECEIPT":
            quantity = self.rng.randint(
                20, 150
            )

        elif event_type == "STOCK_ADJUSTMENT":
            quantity = self.rng.randint(
                1, 15
            )

        elif event_type == "WAREHOUSE_TRANSFER":
            other_warehouses = [
                warehouse
                for warehouse in self.warehouse_ids
                if (
                    warehouse != warehouse_id
                    and (
                        product_id,
                        warehouse
                    ) in self.stock
                )
            ]

            if not other_warehouses:
                # Single-warehouse environments cannot
                # perform inter-warehouse transfers.
                event_type = "SALE"
            else:
                destination = self.rng.choice(
                    other_warehouses
                )

        return {
            "transaction_id": (
                f"TXN-{index + 1:08d}"
            ),
            "event_type": event_type,
            "timestamp": timestamp,
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "quantity": quantity,
            "destination_warehouse": destination
        }

    # ========================================================
    # 10. RUN SIMULATION
    # ========================================================

    def run(
        self,
        event_count,
        realtime=False,
        interval=0.1
    ):
        for index in range(event_count):
            event = self.generate_transaction(
                index
            )

            success = self.process_transaction(
                **event
            )

            status = (
                "APPLIED"
                if success
                else "REJECTED"
            )

            if realtime:
                print(
                    f"[{index + 1}/{event_count}] "
                    f"{event['event_type']:<20} "
                    f"{event['product_id']} "
                    f"{event['warehouse_id']} "
                    f"Qty={event['quantity']} "
                    f"{status}",
                    flush=True
                )

                time.sleep(
                    interval
                )

        return self.transactions

    # ========================================================
    # 11. INVENTORY SNAPSHOT
    # ========================================================

    def get_inventory_snapshot(self):
        snapshot = self.original_inventory.copy()

        snapshot["stock_on_hand"] = [
            self.stock[
                (
                    row.product_id,
                    row.warehouse_id
                )
            ]
            for row in snapshot.itertuples()
        ]

        snapshot["stock_status"] = [
            self.stock_status(
                (
                    row.product_id,
                    row.warehouse_id
                )
            )
            for row in snapshot.itertuples()
        ]

        return snapshot


# ============================================================
# 12. VALIDATION
# ============================================================

def validate_simulation(simulator):
    snapshot = simulator.get_inventory_snapshot()

    if (
        snapshot["stock_on_hand"] < 0
    ).any():
        raise AssertionError(
            "Negative inventory detected."
        )

    transaction_ids = [
        transaction["transaction_id"]
        for transaction in simulator.transactions
    ]

    if len(transaction_ids) != len(
        set(transaction_ids)
    ):
        raise AssertionError(
            "Duplicate applied transaction detected."
        )

    initial_total = sum(
        simulator.original_inventory[
            "stock_on_hand"
        ]
    )

    final_total = sum(
        snapshot["stock_on_hand"]
    )

    expected_delta = sum(
        transaction["stock_delta"]
        + (
            transaction["quantity"]
            if transaction["event_type"]
            == "WAREHOUSE_TRANSFER"
            else 0
        )
        for transaction in simulator.transactions
    )

    if (
        final_total - initial_total
        != expected_delta
    ):
        raise AssertionError(
            "Inventory conservation validation failed."
        )

    return True


# ============================================================
# 13. KPI CALCULATION
# ============================================================

def calculate_kpis(simulator):
    snapshot = simulator.get_inventory_snapshot()

    applied = len(
        simulator.transactions
    )

    rejected = sum(
        event["status"] == "REJECTED"
        for event in simulator.audit_events
    )

    return {
        "attempted_transactions": (
            applied + rejected
        ),
        "applied_transactions": applied,
        "rejected_transactions": rejected,
        "success_rate_pct": round(
            applied / (applied + rejected) * 100,
            2
        ) if applied + rejected else 0,
        "total_stock_before": int(
            simulator.original_inventory[
                "stock_on_hand"
            ].sum()
        ),
        "total_stock_after": int(
            snapshot["stock_on_hand"].sum()
        ),
        "low_stock_records": int(
            snapshot["stock_status"]
            .eq("Low")
            .sum()
        ),
        "critical_stock_records": int(
            snapshot["stock_status"]
            .eq("Critical")
            .sum()
        ),
        "simulated_alerts": len(
            simulator.alerts
        ),
        "stream_events": len(
            simulator.stream_events
        ),
        "transaction_type_distribution": dict(
            Counter(
                transaction["event_type"]
                for transaction in simulator.transactions
            )
        )
    }


# ============================================================
# 14. EXPORT
# ============================================================

def export_results(
    simulator,
    output_dir,
    kpis
):
    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    snapshot = (
        simulator.get_inventory_snapshot()
    )

    snapshot.to_csv(
        output_dir / "inventory_snapshot.csv",
        index=False
    )

    pd.DataFrame(
        simulator.transactions
    ).to_csv(
        output_dir / "inventory_transactions.csv",
        index=False
    )

    pd.DataFrame(
        simulator.alerts
    ).to_csv(
        output_dir / "inventory_alerts.csv",
        index=False
    )

    pd.DataFrame(
        [
            {
                **event,
                "details": json.dumps(
                    event["details"]
                )
            }
            for event in simulator.audit_events
        ]
    ).to_csv(
        output_dir / "inventory_audit_log.csv",
        index=False
    )

    stream_path = (
        output_dir / "inventory_events.jsonl"
    )

    with stream_path.open(
        "w",
        encoding="utf-8"
    ) as file:
        for event in simulator.stream_events:
            file.write(
                json.dumps(event)
                + "\n"
            )

    report = {
        "project": "SupplyChainAI",
        "module": "Inventory Update Simulation",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "simulation_only": True,
        "kpis": kpis,
        "limitations": [
            "Original inventory data remains unchanged.",
            "No real stock movement is performed.",
            "No Kafka or Redis messages are published.",
            "No real purchase orders are created.",
            "No real corporate alerts are delivered.",
            "Transactions are held in memory during simulation.",
            "No database-level concurrency is tested."
        ]
    }

    with (
        output_dir / "inventory_simulation_report.json"
    ).open(
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            report,
            file,
            indent=2
        )

    print("\nGenerated files:")

    for path in sorted(
        output_dir.iterdir()
    ):
        if path.is_file():
            print(
                path.relative_to(ROOT)
                if path.is_relative_to(ROOT)
                else path
            )


# ============================================================
# 15. MAIN
# ============================================================

def main():
    args = parse_args()

    print("=" * 75)
    print("SUPPLYCHAINAI — INVENTORY UPDATE SIMULATION")
    print("=" * 75)

    print(f"Events: {args.events}")
    print(f"Seed: {args.seed}")
    print(f"Realtime playback: {args.realtime}")

    inventory, products, warehouses = (
        load_inventory_data()
    )

    simulator = InventorySimulator(
        inventory,
        products,
        warehouses,
        seed=args.seed
    )

    simulator.run(
        event_count=args.events,
        realtime=args.realtime,
        interval=args.interval
    )

    validate_simulation(
        simulator
    )

    kpis = calculate_kpis(
        simulator
    )

    print("\nINVENTORY SIMULATION KPIs")

    print(
        json.dumps(
            kpis,
            indent=2
        )
    )

    export_results(
        simulator,
        args.output.resolve(),
        kpis
    )

    print("\nInventory simulation completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
