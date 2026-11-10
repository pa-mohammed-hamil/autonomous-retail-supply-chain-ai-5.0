"""Planned module: generate demo data. Implementation pending."""

#!/usr/bin/env python3
"""
SupplyChainAI — Synthetic Demo Data Generator

File: scripts/generate_demo_data.py

Generates:
  data/products.csv
  data/suppliers.csv
  data/warehouses.csv
  data/inventory.csv
  data/sales.csv
  data/feedback.csv
  data/purchase_orders.csv
  data/delivery_orders.csv
  data/fleet.csv
  data/shipments.csv
  data/returns.csv
  data/employees.csv
  data/warehouse_operations.csv
  data/market_trends.csv
  data/notifications.csv

Features:
- Deterministic random seed
- Connected product/supplier/warehouse IDs
- Historical sales with seasonality
- Inventory and reorder thresholds
- Supplier risk indicators
- Synthetic customer feedback
- Purchase order records
- Logistics orders and fleet
- Delivery and return records
- Warehouse operations
- Employee assignments
- Business alerts
- Dataset validation
- Generation manifest

Install:
    pip install pandas numpy

Run:
    python scripts/generate_demo_data.py
    python scripts/generate_demo_data.py --days 365
    python scripts/generate_demo_data.py --products 200
    python scripts/generate_demo_data.py --force

Safety:
- Demo data only
- No production database writes
- No API requests
- Existing CSV files are not overwritten unless --force
"""

import argparse
import json
import math
import sys

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# 1. PROJECT CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SEED = 42

CATEGORIES = [
    "Electronics",
    "Groceries",
    "Fashion",
    "Home & Kitchen",
    "Beauty",
    "Sports",
    "Automotive",
    "Office Supplies"
]

PRODUCT_NAMES = {
    "Electronics": [
        "Wireless Headphones",
        "Bluetooth Speaker",
        "Smart Watch",
        "USB-C Charger",
        "Power Bank",
        "Wireless Mouse",
        "Keyboard",
        "Webcam"
    ],
    "Groceries": [
        "Rice Pack",
        "Cooking Oil",
        "Coffee Powder",
        "Tea Pack",
        "Breakfast Cereal",
        "Pasta",
        "Snack Box",
        "Spice Mix"
    ],
    "Fashion": [
        "Cotton T-Shirt",
        "Denim Jeans",
        "Casual Shirt",
        "Sports Shoes",
        "Jacket",
        "Backpack",
        "Cap",
        "Hoodie"
    ],
    "Home & Kitchen": [
        "Electric Kettle",
        "Storage Container",
        "Cookware Set",
        "Table Lamp",
        "Water Bottle",
        "Kitchen Scale",
        "Bedsheet",
        "Cleaning Kit"
    ],
    "Beauty": [
        "Face Wash",
        "Shampoo",
        "Body Lotion",
        "Sunscreen",
        "Hair Oil",
        "Face Cream",
        "Soap Pack",
        "Skin Serum"
    ],
    "Sports": [
        "Yoga Mat",
        "Football",
        "Dumbbell Set",
        "Resistance Band",
        "Gym Gloves",
        "Skipping Rope",
        "Cricket Bat",
        "Sports Bottle"
    ],
    "Automotive": [
        "Car Phone Holder",
        "Car Charger",
        "Cleaning Cloth",
        "Tyre Inflator",
        "Dashboard Cleaner",
        "Seat Cushion",
        "Emergency Light",
        "Car Vacuum"
    ],
    "Office Supplies": [
        "Notebook",
        "Ballpoint Pen",
        "Desk Organizer",
        "Printer Paper",
        "Stapler",
        "File Folder",
        "Marker Set",
        "Desk Calendar"
    ]
}

WAREHOUSE_LOCATIONS = [
    ("Kochi", 9.9816, 76.2999),
    ("Bengaluru", 12.9716, 77.5946),
    ("Chennai", 13.0827, 80.2707),
    ("Hyderabad", 17.3850, 78.4867),
    ("Pune", 18.5204, 73.8567),
    ("Mumbai", 19.0760, 72.8777),
    ("Kozhikode", 11.2588, 75.7804),
    ("Thrissur", 10.5276, 76.2144)
]

POSITIVE_REVIEWS = [
    "Excellent product quality and fast delivery",
    "Very satisfied with the purchase",
    "Great value and reliable product",
    "Amazing quality and excellent packaging",
    "Product works perfectly and arrived on time",
    "Good service and wonderful product",
    "Highly recommended for the price",
    "Fast delivery and excellent customer experience"
]

NEUTRAL_REVIEWS = [
    "Average product and standard delivery",
    "Product is acceptable for the price",
    "The item works as expected",
    "Normal quality and regular packaging",
    "Product matches the basic description",
    "The purchase experience was okay"
]

NEGATIVE_REVIEWS = [
    "Product arrived damaged and packaging was poor",
    "Very late delivery and bad customer service",
    "Poor product quality and disappointing experience",
    "Received the wrong product",
    "Product stopped working after two days",
    "Missing items and delayed refund",
    "The product is defective and unreliable",
    "Delivery was delayed and the package was broken"
]


# ============================================================
# 2. CLI ARGUMENTS
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate SupplyChainAI synthetic datasets"
    )

    parser.add_argument(
        "--products",
        type=int,
        default=120
    )

    parser.add_argument(
        "--suppliers",
        type=int,
        default=20
    )

    parser.add_argument(
        "--warehouses",
        type=int,
        default=5
    )

    parser.add_argument(
        "--days",
        type=int,
        default=180
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing generated CSV files"
    )

    args = parser.parse_args()

    if not 1 <= args.products <= 10000:
        parser.error("--products must be between 1 and 10000")

    if not 1 <= args.suppliers <= 1000:
        parser.error("--suppliers must be between 1 and 1000")

    if not 1 <= args.warehouses <= len(WAREHOUSE_LOCATIONS):
        parser.error(
            f"--warehouses must be between 1 and "
            f"{len(WAREHOUSE_LOCATIONS)}"
        )

    if not 30 <= args.days <= 1095:
        parser.error("--days must be between 30 and 1095")

    return args


# ============================================================
# 3. DATA GENERATOR
# ============================================================

class DemoDataGenerator:

    def __init__(self, args):
        self.args = args
        self.rng = np.random.default_rng(args.seed)

        self.today = pd.Timestamp.now(
            tz="UTC"
        ).normalize().tz_localize(None)

        self.start_date = (
            self.today
            - pd.Timedelta(days=args.days - 1)
        )

        self.datasets = {}

    def choice(self, values):
        return self.rng.choice(values)

    def random_date(self):
        offset = int(
            self.rng.integers(
                0,
                self.args.days
            )
        )

        return self.start_date + pd.Timedelta(
            days=offset
        )

    # ========================================================
    # 4. SUPPLIERS
    # ========================================================

    def generate_suppliers(self):
        rows = []

        for i in range(self.args.suppliers):
            supplier_id = f"SUP-{i + 1:04d}"

            on_time_rate = float(
                self.rng.uniform(0.65, 0.99)
            )

            defect_rate = float(
                self.rng.uniform(0.005, 0.12)
            )

            lead_time = int(
                self.rng.integers(2, 22)
            )

            risk_score = (
                (1 - on_time_rate) * 45
                + defect_rate * 200
                + min(lead_time / 30, 1) * 30
            )

            rows.append({
                "supplier_id": supplier_id,
                "supplier_name": (
                    f"Demo Supplier {i + 1}"
                ),
                "lead_time_days": lead_time,
                "on_time_delivery_rate": round(
                    on_time_rate, 4
                ),
                "defect_rate": round(
                    defect_rate, 4
                ),
                "risk_score": round(
                    min(risk_score, 100), 2
                ),
                "country": "India",
                "is_active": True
            })

        df = pd.DataFrame(rows)
        self.datasets["suppliers"] = df
        return df

    # ========================================================
    # 5. PRODUCTS
    # ========================================================

    def generate_products(self):
        suppliers = self.datasets["suppliers"]
        supplier_ids = suppliers[
            "supplier_id"
        ].tolist()

        rows = []

        for i in range(self.args.products):
            category = str(
                self.choice(CATEGORIES)
            )

            base_name = str(
                self.choice(
                    PRODUCT_NAMES[category]
                )
            )

            unit_cost = round(
                float(
                    self.rng.uniform(80, 4000)
                ),
                2
            )

            margin = float(
                self.rng.uniform(0.15, 0.50)
            )

            unit_price = round(
                unit_cost * (1 + margin),
                2
            )

            rows.append({
                "product_id": f"SKU-{i + 1:04d}",
                "product_name": (
                    f"{base_name} - Model {i + 1}"
                ),
                "category": category,
                "supplier_id": str(
                    self.choice(supplier_ids)
                ),
                "unit_price": unit_price,
                "unit_cost": unit_cost,
                "is_active": True
            })

        df = pd.DataFrame(rows)
        self.datasets["products"] = df
        return df

    # ========================================================
    # 6. WAREHOUSES
    # ========================================================

    def generate_warehouses(self):
        rows = []

        for i, location in enumerate(
            WAREHOUSE_LOCATIONS[
                :self.args.warehouses
            ]
        ):
            city, latitude, longitude = location

            rows.append({
                "warehouse_id": f"WH-{i + 1:03d}",
                "warehouse_name": (
                    f"{city} Distribution Center"
                ),
                "city": city,
                "latitude": latitude,
                "longitude": longitude,
                "capacity_units": int(
                    self.rng.integers(
                        25000, 100000
                    )
                ),
                "is_active": True
            })

        df = pd.DataFrame(rows)
        self.datasets["warehouses"] = df
        return df

    # ========================================================
    # 7. INVENTORY
    # ========================================================

    def generate_inventory(self):
        products = self.datasets["products"]
        warehouses = self.datasets["warehouses"]

        rows = []

        for product in products.itertuples():
            for warehouse in warehouses.itertuples():
                reorder_point = int(
                    self.rng.integers(30, 180)
                )

                safety_stock = int(
                    self.rng.integers(10, 60)
                )

                stock = int(
                    self.rng.integers(0, 350)
                )

                rows.append({
                    "product_id": product.product_id,
                    "warehouse_id": warehouse.warehouse_id,
                    "stock_on_hand": stock,
                    "reorder_point": reorder_point,
                    "safety_stock": safety_stock
                })

        df = pd.DataFrame(rows)
        self.datasets["inventory"] = df
        return df

    # ========================================================
    # 8. SALES HISTORY
    # ========================================================

    def generate_sales(self):
        products = self.datasets["products"]
        warehouses = self.datasets["warehouses"]

        rows = []
        sale_number = 1

        dates = pd.date_range(
            self.start_date,
            periods=self.args.days,
            freq="D"
        )

        for product in products.itertuples():
            base_demand = float(
                self.rng.uniform(1.5, 14)
            )

            for warehouse in warehouses.itertuples():
                warehouse_factor = float(
                    self.rng.uniform(0.65, 1.40)
                )

                for day in dates:
                    weekday = day.weekday()

                    weekend_factor = (
                        1.20
                        if weekday >= 5
                        else 1.0
                    )

                    seasonal_factor = (
                        1.0
                        + 0.18
                        * math.sin(
                            2 * math.pi
                            * day.dayofyear
                            / 365
                        )
                    )

                    expected_demand = (
                        base_demand
                        * warehouse_factor
                        * weekend_factor
                        * seasonal_factor
                    )

                    quantity = int(
                        self.rng.poisson(
                            max(expected_demand, 0.1)
                        )
                    )

                    if quantity == 0:
                        continue

                    rows.append({
                        "sale_id": f"SALE-{sale_number:08d}",
                        "date": day,
                        "product_id": product.product_id,
                        "warehouse_id": warehouse.warehouse_id,
                        "quantity_sold": quantity,
                        "unit_price": product.unit_price,
                        "revenue": round(
                            quantity * product.unit_price,
                            2
                        )
                    })

                    sale_number += 1

        df = pd.DataFrame(rows)
        self.datasets["sales"] = df
        return df

    # ========================================================
    # 9. CUSTOMER FEEDBACK
    # ========================================================

    def generate_feedback(self):
        products = self.datasets["products"]

        n_feedback = max(
            200,
            self.args.products * 5
        )

        rows = []

        for i in range(n_feedback):
            sentiment = str(
                self.rng.choice(
                    ["positive", "neutral", "negative"],
                    p=[0.55, 0.20, 0.25]
                )
            )

            if sentiment == "positive":
                text = str(
                    self.choice(POSITIVE_REVIEWS)
                )
                rating = int(
                    self.choice([4, 5])
                )

            elif sentiment == "neutral":
                text = str(
                    self.choice(NEUTRAL_REVIEWS)
                )
                rating = 3

            else:
                text = str(
                    self.choice(NEGATIVE_REVIEWS)
                )
                rating = int(
                    self.choice([1, 2])
                )

            rows.append({
                "feedback_id": f"FB-{i + 1:06d}",
                "date": self.random_date(),
                "product_id": str(
                    self.choice(
                        products["product_id"].tolist()
                    )
                ),
                "feedback_text": text,
                "rating": rating,
                "sentiment_label": sentiment
            })

        df = pd.DataFrame(rows)
        self.datasets["feedback"] = df
        return df

    # ========================================================
    # 10. PURCHASE ORDERS
    # ========================================================

    def generate_purchase_orders(self):
        products = self.datasets["products"]
        warehouses = self.datasets["warehouses"]

        rows = []

        n_orders = max(
            100,
            self.args.products * 2
        )

        for i in range(n_orders):
            product = products.iloc[
                int(
                    self.rng.integers(
                        0, len(products)
                    )
                )
            ]

            warehouse = warehouses.iloc[
                int(
                    self.rng.integers(
                        0, len(warehouses)
                    )
                )
            ]

            quantity = int(
                self.rng.integers(20, 250)
            )

            rows.append({
                "purchase_order_id": (
                    f"PO-{i + 1:06d}"
                ),
                "order_date": self.random_date(),
                "product_id": product["product_id"],
                "supplier_id": product["supplier_id"],
                "warehouse_id": warehouse["warehouse_id"],
                "quantity": quantity,
                "unit_cost": product["unit_cost"],
                "total_cost": round(
                    quantity * product["unit_cost"],
                    2
                ),
                "status": str(
                    self.rng.choice(
                        [
                            "Pending",
                            "Approved",
                            "Shipped",
                            "Delivered"
                        ],
                        p=[0.15, 0.20, 0.25, 0.40]
                    )
                )
            })

        df = pd.DataFrame(rows)
        self.datasets["purchase_orders"] = df
        return df

    # ========================================================
    # 11. DELIVERY ORDERS
    # ========================================================

    def generate_delivery_orders(self):
        # Use one depot area for the VRP notebook.
        # All orders are geographically near Kochi.
        depot_lat = 9.9816
        depot_lon = 76.2999

        rows = []

        for i in range(30):
            start = int(
                self.choice([0, 60, 120, 180])
            )

            end = min(
                start + 300,
                600
            )

            rows.append({
                "order_id": f"ORD-{i + 1:04d}",
                "customer_name": (
                    f"Demo Customer {i + 1}"
                ),
                "latitude": round(
                    depot_lat
                    + float(
                        self.rng.uniform(
                            -0.10, 0.10
                        )
                    ),
                    6
                ),
                "longitude": round(
                    depot_lon
                    + float(
                        self.rng.uniform(
                            -0.10, 0.10
                        )
                    ),
                    6
                ),
                "demand_kg": int(
                    self.rng.integers(5, 35)
                ),
                "service_minutes": 10,
                "window_start_min": start,
                "window_end_min": end,
                "priority": str(
                    self.rng.choice(
                        ["Normal", "High", "Critical"],
                        p=[0.70, 0.20, 0.10]
                    )
                )
            })

        df = pd.DataFrame(rows)
        self.datasets["delivery_orders"] = df
        return df

    # ========================================================
    # 12. FLEET
    # ========================================================

    def generate_fleet(self):
        rows = []

        for i in range(5):
            is_truck = i >= 2

            rows.append({
                "vehicle_id": f"VEH-{i + 1:03d}",
                "vehicle_type": (
                    "Truck" if is_truck else "Van"
                ),
                "capacity_kg": (
                    650 if is_truck else 350
                ),
                "fuel_efficiency_kmpl": (
                    8.0 if is_truck else 12.0
                ),
                "fixed_cost_inr": (
                    1200 if is_truck else 700
                ),
                "status": "Available"
            })

        df = pd.DataFrame(rows)
        self.datasets["fleet"] = df
        return df

    # ========================================================
    # 13. SHIPMENTS
    # ========================================================

    def generate_shipments(self):
        purchase_orders = self.datasets[
            "purchase_orders"
        ]

        rows = []

        for i, po in enumerate(
            purchase_orders.itertuples(),
            start=1
        ):
            if po.status not in [
                "Shipped",
                "Delivered"
            ]:
                continue

            rows.append({
                "shipment_id": f"SHP-{i:06d}",
                "purchase_order_id": (
                    po.purchase_order_id
                ),
                "supplier_id": po.supplier_id,
                "warehouse_id": po.warehouse_id,
                "shipment_date": (
                    pd.Timestamp(po.order_date)
                    + pd.Timedelta(days=2)
                ),
                "status": (
                    "Delivered"
                    if po.status == "Delivered"
                    else "In Transit"
                )
            })

        df = pd.DataFrame(rows)
        self.datasets["shipments"] = df
        return df

    # ========================================================
    # 14. RETURNS
    # ========================================================

    def generate_returns(self):
        products = self.datasets["products"]

        rows = []

        for i in range(
            max(40, self.args.products // 2)
        ):
            rows.append({
                "return_id": f"RET-{i + 1:05d}",
                "product_id": str(
                    self.choice(
                        products["product_id"].tolist()
                    )
                ),
                "date": self.random_date(),
                "quantity": int(
                    self.rng.integers(1, 5)
                ),
                "reason": str(
                    self.choice([
                        "Damaged",
                        "Wrong Item",
                        "Defective",
                        "Customer Preference",
                        "Late Delivery"
                    ])
                ),
                "status": str(
                    self.choice([
                        "Requested",
                        "Approved",
                        "Completed"
                    ])
                )
            })

        df = pd.DataFrame(rows)
        self.datasets["returns"] = df
        return df

    # ========================================================
    # 15. EMPLOYEES
    # ========================================================

    def generate_employees(self):
        warehouses = self.datasets["warehouses"]

        roles = [
            "Warehouse Operator",
            "Inventory Analyst",
            "Logistics Coordinator",
            "Quality Inspector",
            "Warehouse Supervisor"
        ]

        rows = []

        for i in range(50):
            rows.append({
                "employee_id": f"EMP-{i + 1:04d}",
                "employee_name": (
                    f"Demo Employee {i + 1}"
                ),
                "warehouse_id": str(
                    self.choice(
                        warehouses["warehouse_id"].tolist()
                    )
                ),
                "role": str(
                    self.choice(roles)
                ),
                "status": "Active"
            })

        df = pd.DataFrame(rows)
        self.datasets["employees"] = df
        return df

    # ========================================================
    # 16. WAREHOUSE OPERATIONS
    # ========================================================

    def generate_warehouse_operations(self):
        employees = self.datasets["employees"]
        products = self.datasets["products"]

        rows = []

        for i in range(300):
            employee = employees.iloc[
                int(
                    self.rng.integers(
                        0, len(employees)
                    )
                )
            ]

            rows.append({
                "operation_id": f"OPS-{i + 1:06d}",
                "date": self.random_date(),
                "warehouse_id": employee["warehouse_id"],
                "employee_id": employee["employee_id"],
                "product_id": str(
                    self.choice(
                        products["product_id"].tolist()
                    )
                ),
                "operation_type": str(
                    self.choice([
                        "Picking",
                        "Packing",
                        "Receiving",
                        "Inspection",
                        "Stock Transfer"
                    ])
                ),
                "quantity": int(
                    self.rng.integers(1, 80)
                ),
                "duration_minutes": int(
                    self.rng.integers(5, 90)
                )
            })

        df = pd.DataFrame(rows)
        self.datasets["warehouse_operations"] = df
        return df

    # ========================================================
    # 17. MARKET TRENDS
    # ========================================================

    def generate_market_trends(self):
        rows = []

        for category in CATEGORIES:
            for day in pd.date_range(
                self.start_date,
                periods=self.args.days,
                freq="D"
            ):
                rows.append({
                    "date": day,
                    "category": category,
                    "demand_index": round(
                        float(
                            self.rng.uniform(
                                75, 140
                            )
                        ),
                        2
                    ),
                    "price_index": round(
                        float(
                            self.rng.uniform(
                                90, 120
                            )
                        ),
                        2
                    ),
                    "trend_score": round(
                        float(
                            self.rng.uniform(
                                0, 100
                            )
                        ),
                        2
                    )
                })

        df = pd.DataFrame(rows)
        self.datasets["market_trends"] = df
        return df

    # ========================================================
    # 18. NOTIFICATIONS
    # ========================================================

    def generate_notifications(self):
        inventory = self.datasets["inventory"]

        rows = []

        low_stock = inventory[
            inventory["stock_on_hand"]
            <= inventory["reorder_point"]
        ]

        for i, record in enumerate(
            low_stock.itertuples(),
            start=1
        ):
            rows.append({
                "notification_id": f"NTF-{i:06d}",
                "created_at": self.today,
                "type": "LOW_STOCK",
                "severity": (
                    "Critical"
                    if record.stock_on_hand
                    <= record.safety_stock
                    else "High"
                ),
                "product_id": record.product_id,
                "warehouse_id": record.warehouse_id,
                "message": (
                    f"Low stock detected for "
                    f"{record.product_id} at "
                    f"{record.warehouse_id}"
                ),
                "status": "Unread"
            })

        df = pd.DataFrame(
            rows,
            columns=[
                "notification_id",
                "created_at",
                "type",
                "severity",
                "product_id",
                "warehouse_id",
                "message",
                "status"
            ]
        )

        self.datasets["notifications"] = df
        return df

    # ========================================================
    # 19. GENERATE ALL DATASETS
    # ========================================================

    def generate_all(self):
        print("\nGenerating synthetic datasets...")

        generators = [
            self.generate_suppliers,
            self.generate_products,
            self.generate_warehouses,
            self.generate_inventory,
            self.generate_sales,
            self.generate_feedback,
            self.generate_purchase_orders,
            self.generate_delivery_orders,
            self.generate_fleet,
            self.generate_shipments,
            self.generate_returns,
            self.generate_employees,
            self.generate_warehouse_operations,
            self.generate_market_trends,
            self.generate_notifications
        ]

        for generator in generators:
            df = generator()

            print(
                f"[GENERATED] "
                f"{generator.__name__:<34}"
                f"{len(df):>8,} rows"
            )

        return self.datasets


# ============================================================
# 20. VALIDATION
# ============================================================

def validate_datasets(datasets):
    products = datasets["products"]
    suppliers = datasets["suppliers"]
    warehouses = datasets["warehouses"]
    inventory = datasets["inventory"]
    sales = datasets["sales"]
    feedback = datasets["feedback"]

    supplier_ids = set(
        suppliers["supplier_id"]
    )

    product_ids = set(
        products["product_id"]
    )

    warehouse_ids = set(
        warehouses["warehouse_id"]
    )

    assert set(
        products["supplier_id"]
    ).issubset(supplier_ids)

    assert set(
        inventory["product_id"]
    ).issubset(product_ids)

    assert set(
        inventory["warehouse_id"]
    ).issubset(warehouse_ids)

    assert set(
        sales["product_id"]
    ).issubset(product_ids)

    assert set(
        sales["warehouse_id"]
    ).issubset(warehouse_ids)

    assert set(
        feedback["product_id"]
    ).issubset(product_ids)

    assert not products[
        "product_id"
    ].duplicated().any()

    assert not suppliers[
        "supplier_id"
    ].duplicated().any()

    assert not warehouses[
        "warehouse_id"
    ].duplicated().any()

    assert not inventory.duplicated(
        ["product_id", "warehouse_id"]
    ).any()

    assert (
        inventory["stock_on_hand"] >= 0
    ).all()

    assert (
        sales["quantity_sold"] > 0
    ).all()

    print("\n[OK] Dataset validation passed.")


# ============================================================
# 21. SAVE DATASETS
# ============================================================

def save_datasets(datasets, force=False):
    written = []
    skipped = []

    # Preflight: do not partially overwrite a dataset
    # collection unless the user explicitly requests it.
    existing = [
        DATA_DIR / f"{name}.csv"
        for name in datasets
        if (DATA_DIR / f"{name}.csv").exists()
    ]

    if existing and not force:
        print(
            "\n[STOPPED] Existing dataset files detected."
        )

        print(
            "No files were written. Use --force to "
            "overwrite generated CSVs."
        )

        for path in existing:
            print(f"  {path}")

        return written, list(existing)

    for name, df in datasets.items():
        path = DATA_DIR / f"{name}.csv"

        df.to_csv(
            path,
            index=False
        )

        written.append(path)

        print(
            f"[SAVED] {path.name:<30}"
            f"{len(df):>8,} rows"
        )

    return written, skipped


# ============================================================
# 22. GENERATION MANIFEST
# ============================================================

def save_manifest(generator, written):
    manifest = {
        "project": "SupplyChainAI",
        "generator": "scripts/generate_demo_data.py",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "synthetic_data": True,
        "seed": generator.args.seed,
        "configuration": {
            "products": generator.args.products,
            "suppliers": generator.args.suppliers,
            "warehouses": generator.args.warehouses,
            "days": generator.args.days
        },
        "datasets": {
            name: {
                "rows": int(len(df)),
                "columns": df.columns.tolist(),
                "file": f"data/{name}.csv"
            }
            for name, df in generator.datasets.items()
        },
        "written_files": [
            str(path.relative_to(ROOT))
            for path in written
        ],
        "limitations": [
            "All records are synthetic.",
            "Sales are generated independently of stock availability.",
            "Inventory is a simulated snapshot.",
            "Supplier risk is a heuristic estimate.",
            "Customer sentiment labels are synthetic.",
            "Delivery locations are fictional demonstration points.",
            "Market indices are simulated.",
            "No production data or actual customers are represented."
        ]
    }

    path = DATA_DIR / "demo_data_manifest.json"

    with path.open(
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            manifest,
            file,
            indent=2
        )

    print(f"\n[MANIFEST] {path}")


# ============================================================
# 23. MAIN
# ============================================================

def main():
    args = parse_args()

    print("=" * 75)
    print("SUPPLYCHAINAI — DEMO DATA GENERATOR")
    print("=" * 75)

    print(f"Products: {args.products}")
    print(f"Suppliers: {args.suppliers}")
    print(f"Warehouses: {args.warehouses}")
    print(f"Historical days: {args.days}")
    print(f"Random seed: {args.seed}")

    generator = DemoDataGenerator(args)

    datasets = generator.generate_all()

    validate_datasets(datasets)

    written, skipped = save_datasets(
        datasets,
        force=args.force
    )

    if skipped:
        print(
            "\nGeneration completed in memory, "
            "but existing files were preserved."
        )
        return 1

    save_manifest(
        generator,
        written
    )

    print("\n" + "=" * 75)
    print("DEMO DATA GENERATION COMPLETED")
    print("=" * 75)

    print(f"Datasets generated: {len(datasets)}")

    total_rows = sum(
        len(df)
        for df in datasets.values()
    )

    print(f"Total records: {total_rows:,}")

    print("\nNext steps:")
    print("1. Run 01_data_exploration.ipynb")
    print("2. Run 02_demand_forecasting.ipynb")
    print("3. Run 03_stockout_prediction.ipynb")
    print("4. Run 04_supplier_risk.ipynb")
    print("5. Run 05_sentiment_analysis.ipynb")
    print("6. Run 06_logistics_optimization.ipynb")
    print("7. Run scripts/evaluate_models.py")

    return 0


if __name__ == "__main__":
    sys.exit(main())
