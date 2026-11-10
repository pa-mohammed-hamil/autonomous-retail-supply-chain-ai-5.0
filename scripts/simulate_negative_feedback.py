"""Planned module: simulate negative feedback. Implementation pending."""

#!/usr/bin/env python3
"""
SupplyChainAI — Negative Feedback Simulator

File:
    scripts/simulate_negative_feedback.py

Features:
    01. Load existing customer feedback
    02. Generate realistic synthetic complaints
    03. Detect negative sentiment
    04. Optional trained sentiment classifier
    05. Identify complaint topics
    06. Detect damaged, defective and missing products
    07. Detect delivery and refund complaints
    08. Assign complaint severity and priority
    09. Calculate product complaint rates
    10. Identify supplier-linked complaints
    11. Generate simulated corporate escalations
    12. Simulate SLA acknowledgement and resolution
    13. Recommend corrective actions
    14. Generate complaint and alert timelines
    15. Export CSV, JSON and HTML reports

Install:
    pip install pandas numpy

Optional ML:
    pip install scikit-learn joblib

Examples:
    python scripts/simulate_negative_feedback.py
    python scripts/simulate_negative_feedback.py --complaints 200
    python scripts/simulate_negative_feedback.py --scenario product_quality
    python scripts/simulate_negative_feedback.py --scenario delivery
    python scripts/simulate_negative_feedback.py --scenario refund
    python scripts/simulate_negative_feedback.py --scenario all
    python scripts/simulate_negative_feedback.py --use-model

Safety:
    - Synthetic simulation only
    - No actual customers are contacted
    - No real email or SMS is sent
    - No actual refunds are issued
    - No real supplier penalties are applied
    - No production database is modified
    - Original feedback.csv remains unchanged
"""

import argparse
import html
import json
import random
import sys

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


import numpy as np
import pandas as pd


# ============================================================
# 1. PROJECT CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"

OUTPUT_DIR = (
    ROOT / "reports" / "negative_feedback"
)

MODEL_PATH = (
    ROOT
    / "models"
    / "sentiment_analysis"
    / "sentiment_classifier.joblib"
)

SCENARIOS = {
    "product_quality": {
        "topic": "Product Quality",
        "department": "Quality Assurance",
        "complaints": [
            "The product stopped working after two days",
            "Poor product quality and defective components",
            "The item arrived damaged and unusable",
            "The product broke during normal use",
            "Product quality is far below expectations",
            "The product has a manufacturing defect"
        ]
    },
    "delivery": {
        "topic": "Delivery",
        "department": "Logistics",
        "complaints": [
            "Delivery was extremely late",
            "The package has not arrived",
            "Shipment tracking is not updating",
            "Delivery was delayed for several days",
            "The courier delivered to the wrong address",
            "My order was marked delivered but not received"
        ]
    },
    "refund": {
        "topic": "Refund",
        "department": "Customer Support",
        "complaints": [
            "My refund has not been processed",
            "Refund request was rejected without explanation",
            "I returned the item but have not received my money",
            "Customer support is not responding to my refund",
            "The refund is delayed for several weeks",
            "I was charged twice and have not been refunded"
        ]
    },
    "missing_items": {
        "topic": "Missing Items",
        "department": "Warehouse Operations",
        "complaints": [
            "One item is missing from my order",
            "The package arrived with missing products",
            "I received the wrong item",
            "The order quantity is incorrect",
            "Several items were missing from the delivery",
            "The box was empty when it arrived"
        ]
    },
    "customer_support": {
        "topic": "Customer Support",
        "department": "Customer Support",
        "complaints": [
            "Customer service is not responding",
            "The support team was very unhelpful",
            "Nobody has resolved my complaint",
            "I contacted support several times without success",
            "The customer support experience was terrible",
            "My complaint was closed without a solution"
        ]
    },
    "packaging": {
        "topic": "Packaging",
        "department": "Warehouse Operations",
        "complaints": [
            "Packaging was damaged during shipment",
            "The product was packed very poorly",
            "The box was torn and the product was exposed",
            "Protective packaging was missing",
            "The package arrived broken",
            "The product was damaged because of poor packing"
        ]
    }
}

TOPIC_KEYWORDS = {
    "Product Quality": [
        "defective", "broken", "stopped working",
        "manufacturing", "poor quality", "unusable"
    ],
    "Delivery": [
        "delivery", "delayed", "courier",
        "shipment", "tracking", "not arrived"
    ],
    "Refund": [
        "refund", "refunded", "charged twice",
        "money", "returned"
    ],
    "Missing Items": [
        "missing", "wrong item", "empty",
        "incorrect quantity"
    ],
    "Customer Support": [
        "support", "service", "not responding",
        "complaint", "unhelpful"
    ],
    "Packaging": [
        "packaging", "packed", "box",
        "packing", "torn"
    ]
}

PRIORITY_SLA_MINUTES = {
    "P1": 15,
    "P2": 60,
    "P3": 240,
    "P4": 1440
}

PRIORITY_RESOLUTION_HOURS = {
    "P1": 4,
    "P2": 12,
    "P3": 48,
    "P4": 72
}

DEPARTMENT_ROUTES = {
    "Product Quality": "Quality Assurance",
    "Delivery": "Logistics",
    "Refund": "Customer Support",
    "Missing Items": "Warehouse Operations",
    "Customer Support": "Customer Support",
    "Packaging": "Warehouse Operations",
    "Other": "Customer Support"
}

CORRECTIVE_ACTIONS = {
    "Product Quality": (
        "Inspect affected product batches, review "
        "defect trends, and request supplier QA review."
    ),
    "Delivery": (
        "Review carrier tracking, identify route delays, "
        "and investigate delivery SLA breaches."
    ),
    "Refund": (
        "Review refund eligibility and transaction status; "
        "request human approval for any financial action."
    ),
    "Missing Items": (
        "Audit picking and packing records and verify "
        "order fulfillment accuracy."
    ),
    "Customer Support": (
        "Assign a support supervisor and review "
        "unresolved customer interactions."
    ),
    "Packaging": (
        "Inspect packaging procedures and verify "
        "protective material compliance."
    ),
    "Other": (
        "Route to customer support for human review."
    )
}


# ============================================================
# 2. CLI
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "SupplyChainAI negative feedback simulator"
        )
    )

    parser.add_argument(
        "--complaints",
        type=int,
        default=100
    )

    parser.add_argument(
        "--scenario",
        choices=["all", *SCENARIOS],
        default="all"
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42
    )

    parser.add_argument(
        "--use-model",
        action="store_true",
        help=(
            "Load the trusted local sentiment "
            "classifier for inference."
        )
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_DIR
    )

    args = parser.parse_args()

    if not 1 <= args.complaints <= 100000:
        parser.error(
            "--complaints must be between 1 and 100000"
        )

    return args


# ============================================================
# 3. DATA LOADING
# ============================================================

def load_csv(filename, required):
    path = DATA_DIR / filename

    if not path.exists():
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
            f"{filename} missing columns: {missing}"
        )

    return df


def load_reference_data():
    products = load_csv(
        "products.csv",
        [
            "product_id",
            "product_name",
            "supplier_id",
            "category"
        ]
    )

    suppliers = load_csv(
        "suppliers.csv",
        [
            "supplier_id",
            "supplier_name"
        ]
    )

    feedback = load_csv(
        "feedback.csv",
        [
            "feedback_id",
            "product_id",
            "feedback_text"
        ]
    )

    if products["product_id"].duplicated().any():
        raise ValueError(
            "Duplicate product IDs."
        )

    if suppliers["supplier_id"].duplicated().any():
        raise ValueError(
            "Duplicate supplier IDs."
        )

    if not set(
        products["supplier_id"]
    ).issubset(
        set(suppliers["supplier_id"])
    ):
        raise ValueError(
            "Unknown supplier IDs in products."
        )

    if not set(
        feedback["product_id"]
    ).issubset(
        set(products["product_id"])
    ):
        raise ValueError(
            "Unknown product IDs in feedback."
        )

    return products, suppliers, feedback


# ============================================================
# 4. SENTIMENT CLASSIFIER
# ============================================================

def load_sentiment_model(enabled):
    if not enabled:
        return None

    if not MODEL_PATH.exists():
        print(
            "[WARNING] Sentiment model not found. "
            "Using synthetic complaint labels."
        )
        return None

    try:
        import joblib

        # Only load artifacts generated locally or
        # obtained from a trusted source. joblib uses
        # pickle and can execute arbitrary code.
        model = joblib.load(
            MODEL_PATH
        )

        if not hasattr(model, "predict"):
            raise ValueError(
                "Artifact has no predict() method."
            )

        print(
            "[MODEL] Loaded trusted sentiment classifier."
        )

        return model

    except Exception as exc:
        print(
            f"[WARNING] Model loading failed: {exc}"
        )
        return None


# ============================================================
# 5. TOPIC DETECTION
# ============================================================

def detect_topic(text, default_topic="Other"):
    normalized = str(text).lower()

    scores = {}

    for topic, keywords in TOPIC_KEYWORDS.items():
        scores[topic] = sum(
            keyword in normalized
            for keyword in keywords
        )

    best_topic = max(
        scores,
        key=scores.get
    )

    if scores[best_topic] == 0:
        return default_topic

    return best_topic


# ============================================================
# 6. PRIORITY CLASSIFICATION
# ============================================================

def classify_priority(
    text,
    topic,
    rating
):
    normalized = str(text).lower()

    critical_terms = [
        "injury",
        "fire",
        "dangerous",
        "data breach",
        "unauthorized charge"
    ]

    high_terms = [
        "charged twice",
        "not received",
        "unusable",
        "defective",
        "several weeks",
        "empty"
    ]

    if any(
        term in normalized
        for term in critical_terms
    ):
        return "P1"

    if (
        any(
            term in normalized
            for term in high_terms
        )
        or rating == 1
    ):
        return "P2"

    if rating == 2:
        return "P3"

    return "P4"


# ============================================================
# 7. SIMULATION ENGINE
# ============================================================

class NegativeFeedbackSimulator:

    def __init__(
        self,
        products,
        suppliers,
        feedback,
        seed=42,
        model=None
    ):
        self.rng = random.Random(seed)

        self.products = products.copy()
        self.suppliers = suppliers.copy()
        self.feedback = feedback.copy()

        self.model = model

        self.product_records = (
            products.merge(
                suppliers[
                    [
                        "supplier_id",
                        "supplier_name"
                    ]
                ],
                on="supplier_id",
                how="left",
                validate="many_to_one"
            )
            .to_dict("records")
        )

        self.complaints = []
        self.alerts = []
        self.escalations = []
        self.audit_events = []

        self.base_time = datetime(
            2026, 10, 30, 9, 0,
            tzinfo=timezone.utc
        )

    # ========================================================
    # 8. AUDIT EVENTS
    # ========================================================

    def audit(
        self,
        complaint_id,
        event_type,
        timestamp,
        details=None
    ):
        self.audit_events.append({
            "audit_id": (
                f"AUD-{len(self.audit_events) + 1:07d}"
            ),
            "complaint_id": complaint_id,
            "event_type": event_type,
            "timestamp": timestamp.isoformat(),
            "details": details or {}
        })

    # ========================================================
    # 9. CREATE COMPLAINT
    # ========================================================

    def create_complaint(
        self,
        index,
        scenario
    ):
        config = SCENARIOS[
            scenario
        ]

        product = self.rng.choice(
            self.product_records
        )

        complaint_text = self.rng.choice(
            config["complaints"]
        )

        rating = self.rng.choice(
            [1, 1, 2, 2, 2]
        )

        created_at = (
            self.base_time
            + timedelta(
                minutes=index * 3
            )
        )

        complaint_id = (
            f"CMP-{index + 1:07d}"
        )

        detected_topic = detect_topic(
            complaint_text,
            default_topic=config["topic"]
        )

        priority = classify_priority(
            complaint_text,
            detected_topic,
            rating
        )

        sentiment = "negative"
        sentiment_source = "synthetic_scenario"

        if self.model is not None:
            try:
                prediction = self.model.predict(
                    [complaint_text]
                )[0]

                sentiment = str(
                    prediction
                ).lower()

                sentiment_source = "model_prediction"

            except Exception as exc:
                print(
                    f"[WARNING] Sentiment prediction failed: {exc}"
                )

        complaint = {
            "complaint_id": complaint_id,
            "feedback_id": (
                f"SIM-FB-{index + 1:07d}"
            ),
            "created_at": created_at.isoformat(),
            "product_id": product["product_id"],
            "product_name": product["product_name"],
            "category": product["category"],
            "supplier_id": product["supplier_id"],
            "supplier_name": product["supplier_name"],
            "feedback_text": complaint_text,
            "rating": rating,
            "sentiment": sentiment,
            "sentiment_source": sentiment_source,
            "topic": detected_topic,
            "priority": priority,
            "department": DEPARTMENT_ROUTES[
                detected_topic
            ],
            "status": "Open",
            "ack_sla_minutes": (
                PRIORITY_SLA_MINUTES[priority]
            ),
            "resolution_sla_hours": (
                PRIORITY_RESOLUTION_HOURS[priority]
            ),
            "acknowledged_at": None,
            "resolved_at": None,
            "ack_sla_breached": False,
            "resolution_sla_breached": False,
            "escalation_level": 0,
            "corrective_action": (
                CORRECTIVE_ACTIONS[
                    detected_topic
                ]
            ),
            "simulation": True
        }

        self.complaints.append(
            complaint
        )

        self.audit(
            complaint_id,
            "COMPLAINT_CREATED",
            created_at,
            {
                "topic": detected_topic,
                "priority": priority,
                "product_id": product["product_id"]
            }
        )

        return complaint

    # ========================================================
    # 10. SIMULATE ACKNOWLEDGEMENT
    # ========================================================

    def simulate_acknowledgement(
        self,
        complaint
    ):
        created_at = datetime.fromisoformat(
            complaint["created_at"]
        )

        sla = complaint[
            "ack_sla_minutes"
        ]

        # Approximately 30% of demo complaints
        # exceed their acknowledgement SLA.
        if self.rng.random() < 0.70:
            delay = self.rng.randint(
                1,
                max(1, sla)
            )
        else:
            delay = self.rng.randint(
                sla + 1,
                sla + 120
            )

        acknowledged_at = (
            created_at
            + timedelta(minutes=delay)
        )

        complaint["acknowledged_at"] = (
            acknowledged_at.isoformat()
        )

        complaint["ack_sla_breached"] = (
            delay > sla
        )

        complaint["status"] = "Acknowledged"

        self.audit(
            complaint["complaint_id"],
            "COMPLAINT_ACKNOWLEDGED",
            acknowledged_at,
            {
                "delay_minutes": delay,
                "sla_breached": (
                    complaint["ack_sla_breached"]
                )
            }
        )

        if complaint["ack_sla_breached"]:
            self.create_escalation(
                complaint,
                acknowledged_at,
                reason="Acknowledgement SLA breached"
            )

    # ========================================================
    # 11. SIMULATE RESOLUTION
    # ========================================================

    def simulate_resolution(
        self,
        complaint
    ):
        acknowledged_at = datetime.fromisoformat(
            complaint["acknowledged_at"]
        )

        created_at = datetime.fromisoformat(
            complaint["created_at"]
        )

        resolution_sla = (
            complaint["resolution_sla_hours"]
        )

        resolution_hours = self.rng.uniform(
            1,
            resolution_sla * 1.5
        )

        resolved_at = (
            acknowledged_at
            + timedelta(
                hours=resolution_hours
            )
        )

        total_hours = (
            resolved_at - created_at
        ).total_seconds() / 3600

        complaint["resolution_sla_breached"] = (
            total_hours > resolution_sla
        )

        # A simulated complaint may remain unresolved.
        if self.rng.random() < 0.12:
            complaint["status"] = "Open"

            self.audit(
                complaint["complaint_id"],
                "COMPLAINT_REMAINS_OPEN",
                resolved_at,
                {
                    "simulated": True
                }
            )

            return

        complaint["resolved_at"] = (
            resolved_at.isoformat()
        )

        complaint["status"] = "Resolved"

        self.audit(
            complaint["complaint_id"],
            "COMPLAINT_RESOLVED",
            resolved_at,
            {
                "resolution_hours": round(
                    total_hours, 2
                ),
                "resolution_sla_breached": (
                    complaint[
                        "resolution_sla_breached"
                    ]
                )
            }
        )

        if complaint[
            "resolution_sla_breached"
        ]:
            self.create_escalation(
                complaint,
                resolved_at,
                reason="Resolution SLA breached"
            )

    # ========================================================
    # 12. ESCALATION
    # ========================================================

    def create_escalation(
        self,
        complaint,
        timestamp,
        reason
    ):
        complaint["escalation_level"] += 1

        level = complaint[
            "escalation_level"
        ]

        recipient = (
            "Department Manager"
            if level == 1
            else "Operations Director"
            if level == 2
            else "Executive Review"
        )

        escalation = {
            "escalation_id": (
                f"ESC-{len(self.escalations) + 1:07d}"
            ),
            "complaint_id": complaint["complaint_id"],
            "timestamp": timestamp.isoformat(),
            "priority": complaint["priority"],
            "department": complaint["department"],
            "escalation_level": level,
            "recipient_role": recipient,
            "reason": reason,
            "status": "Simulated"
        }

        self.escalations.append(
            escalation
        )

        self.audit(
            complaint["complaint_id"],
            "COMPLAINT_ESCALATED",
            timestamp,
            escalation
        )

    # ========================================================
    # 13. CORPORATE ALERTS
    # ========================================================

    def create_alert(
        self,
        complaint
    ):
        if complaint["priority"] not in [
            "P1",
            "P2"
        ]:
            return

        alert = {
            "alert_id": (
                f"ALERT-{len(self.alerts) + 1:07d}"
            ),
            "complaint_id": complaint["complaint_id"],
            "created_at": complaint["created_at"],
            "type": "NEGATIVE_CUSTOMER_FEEDBACK",
            "severity": (
                "Critical"
                if complaint["priority"] == "P1"
                else "High"
            ),
            "priority": complaint["priority"],
            "product_id": complaint["product_id"],
            "supplier_id": complaint["supplier_id"],
            "topic": complaint["topic"],
            "department": complaint["department"],
            "recipient_role": (
                "Operations Director"
                if complaint["priority"] == "P1"
                else "Department Manager"
            ),
            "message": (
                f"[SIMULATION] "
                f"{complaint['priority']} complaint: "
                f"{complaint['topic']} for "
                f"{complaint['product_id']}"
            ),
            "requires_human_review": True,
            "delivery_status": "Not Sent"
        }

        self.alerts.append(
            alert
        )

    # ========================================================
    # 14. RUN SIMULATION
    # ========================================================

    def run(
        self,
        count=100,
        scenario="all"
    ):
        available = (
            list(SCENARIOS)
            if scenario == "all"
            else [scenario]
        )

        for index in range(count):
            selected_scenario = self.rng.choice(
                available
            )

            complaint = self.create_complaint(
                index,
                selected_scenario
            )

            self.create_alert(
                complaint
            )

            self.simulate_acknowledgement(
                complaint
            )

            self.simulate_resolution(
                complaint
            )

        return pd.DataFrame(
            self.complaints
        )


# ============================================================
# 15. PRODUCT COMPLAINT ANALYSIS
# ============================================================

def analyze_products(
    complaints_df,
    products,
    feedback
):
    complaint_counts = (
        complaints_df.groupby(
            ["product_id", "product_name"],
            as_index=False
        )
        .agg(
            simulated_complaints=(
                "complaint_id",
                "count"
            ),
            critical_complaints=(
                "priority",
                lambda series: int(
                    (series == "P1").sum()
                )
            ),
            high_priority_complaints=(
                "priority",
                lambda series: int(
                    series.isin(["P1", "P2"]).sum()
                )
            )
        )
    )

    existing_feedback_counts = (
        feedback.groupby(
            "product_id",
            as_index=False
        )
        .size()
        .rename(
            columns={
                "size": "existing_feedback_count"
            }
        )
    )

    summary = complaint_counts.merge(
        existing_feedback_counts,
        on="product_id",
        how="left"
    )

    summary["existing_feedback_count"] = (
        summary["existing_feedback_count"]
        .fillna(0)
        .astype(int)
    )

    # A share of synthetic complaints in a combined
    # feedback sample. NOT a true customer complaint
    # rate because the denominator is not orders.
    denominator = (
        summary["simulated_complaints"]
        + summary["existing_feedback_count"]
    )

    summary["synthetic_feedback_share_pct"] = (
        summary["simulated_complaints"]
        / denominator.replace(0, np.nan)
        * 100
    ).fillna(0).round(2)

    return summary.sort_values(
        "simulated_complaints",
        ascending=False
    )


# ============================================================
# 16. SUPPLIER COMPLAINT ANALYSIS
# ============================================================

def analyze_suppliers(
    complaints_df
):
    summary = (
        complaints_df.groupby(
            ["supplier_id", "supplier_name"],
            as_index=False
        )
        .agg(
            simulated_complaints=(
                "complaint_id",
                "count"
            ),
            critical_complaints=(
                "priority",
                lambda values: int(
                    (values == "P1").sum()
                )
            ),
            high_priority_complaints=(
                "priority",
                lambda values: int(
                    values.isin(["P1", "P2"]).sum()
                )
            )
        )
    )

    return summary.sort_values(
        "simulated_complaints",
        ascending=False
    )


# ============================================================
# 17. KPI CALCULATION
# ============================================================

def calculate_kpis(
    complaints_df,
    simulator
):
    total = len(
        complaints_df
    )

    resolved = int(
        complaints_df["status"]
        .eq("Resolved")
        .sum()
    )

    ack_breaches = int(
        complaints_df["ack_sla_breached"]
        .sum()
    )

    resolution_breaches = int(
        complaints_df[
            "resolution_sla_breached"
        ].sum()
    )

    return {
        "total_simulated_complaints": total,
        "resolved_complaints": resolved,
        "open_complaints": total - resolved,
        "resolution_rate_pct": round(
            resolved / total * 100,
            2
        ) if total else 0,
        "ack_sla_breaches": ack_breaches,
        "resolution_sla_breaches": (
            resolution_breaches
        ),
        "ack_sla_compliance_pct": round(
            (total - ack_breaches) / total * 100,
            2
        ) if total else 0,
        "simulated_alerts": len(
            simulator.alerts
        ),
        "simulated_escalations": len(
            simulator.escalations
        ),
        "priority_distribution": (
            complaints_df["priority"]
            .value_counts()
            .to_dict()
        ),
        "topic_distribution": (
            complaints_df["topic"]
            .value_counts()
            .to_dict()
        ),
        "department_distribution": (
            complaints_df["department"]
            .value_counts()
            .to_dict()
        )
    }


# ============================================================
# 18. HTML DASHBOARD
# ============================================================

def create_dashboard(
    complaints_df,
    product_summary,
    supplier_summary,
    kpis,
    output_dir
):
    kpi_cards = ""

    for key, value in kpis.items():
        if isinstance(value, dict):
            continue

        label = html.escape(
            key.replace("_", " ").title()
        )

        display_value = html.escape(
            str(value)
        )

        kpi_cards += f"""
        <div class="kpi">
            <div class="label">{label}</div>
            <div class="value">{display_value}</div>
        </div>
        """

    complaint_table = (
        complaints_df[
            [
                "complaint_id",
                "product_id",
                "topic",
                "priority",
                "department",
                "status",
                "ack_sla_breached",
                "escalation_level"
            ]
        ]
        .head(100)
        .to_html(
            index=False,
            escape=True,
            border=0
        )
    )

    product_table = (
        product_summary.head(20)
        .to_html(
            index=False,
            escape=True,
            border=0
        )
    )

    supplier_table = (
        supplier_summary.head(20)
        .to_html(
            index=False,
            escape=True,
            border=0
        )
    )

    dashboard = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport"
content="width=device-width, initial-scale=1">
<title>SupplyChainAI — Negative Feedback Simulation</title>
<style>
:root {{
    color-scheme: dark;
    font-family: Inter, Arial, sans-serif;
}}
* {{
    box-sizing: border-box;
}}
body {{
    margin: 0;
    padding: 30px;
    background: #0a1020;
    color: #edf2ff;
}}
main {{
    max-width: 1450px;
    margin: auto;
}}
h1 {{
    font-size: 34px;
}}
.subtitle {{
    color: #9facc8;
}}
.grid {{
    display: grid;
    grid-template-columns:
        repeat(auto-fit, minmax(190px, 1fr));
    gap: 16px;
    margin: 28px 0;
}}
.kpi {{
    background: #16213a;
    border: 1px solid #304263;
    padding: 20px;
    border-radius: 14px;
}}
.label {{
    color: #9eafcf;
    font-size: 13px;
}}
.value {{
    font-size: 26px;
    font-weight: 700;
    margin-top: 8px;
}}
.card {{
    background: #151f35;
    border: 1px solid #304263;
    padding: 24px;
    border-radius: 16px;
    margin-bottom: 24px;
    overflow-x: auto;
}}
table {{
    border-collapse: collapse;
    width: 100%;
    font-size: 13px;
}}
th, td {{
    padding: 12px;
    text-align: left;
    border-bottom: 1px solid #34415d;
}}
th {{
    background: #23314e;
}}
.notice {{
    padding: 16px;
    background: #30281d;
    border-left: 4px solid #e9b75b;
    border-radius: 8px;
}}
</style>
</head>
<body>
<main>
<h1>SupplyChainAI — Negative Feedback Intelligence</h1>
<p class="subtitle">
Sentiment · Complaints · Product Quality · Escalations
</p>

<div class="notice">
All complaints, escalations and operational outcomes
on this dashboard are simulated. Supplier counts are
not verified defect or complaint rates.
</div>

<div class="grid">
{kpi_cards}
</div>

<section class="card">
<h2>Simulated Complaints</h2>
{complaint_table}
</section>

<section class="card">
<h2>Product Complaint Analysis</h2>
{product_table}
</section>

<section class="card">
<h2>Supplier Complaint Analysis</h2>
{supplier_table}
</section>

</main>
</body>
</html>
"""

    (
        output_dir / "negative_feedback_dashboard.html"
    ).write_text(
        dashboard,
        encoding="utf-8"
    )


# ============================================================
# 19. EXPORT
# ============================================================

def export_results(
    simulator,
    complaints_df,
    product_summary,
    supplier_summary,
    kpis,
    output_dir
):
    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    complaints_df.to_csv(
        output_dir / "simulated_negative_feedback.csv",
        index=False
    )

    pd.DataFrame(
        simulator.alerts
    ).to_csv(
        output_dir / "negative_feedback_alerts.csv",
        index=False
    )

    pd.DataFrame(
        simulator.escalations
    ).to_csv(
        output_dir / "feedback_escalations.csv",
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
        output_dir / "feedback_audit_log.csv",
        index=False
    )

    product_summary.to_csv(
        output_dir / "product_complaint_summary.csv",
        index=False
    )

    supplier_summary.to_csv(
        output_dir / "supplier_complaint_summary.csv",
        index=False
    )

    report = {
        "project": "SupplyChainAI",
        "module": "Negative Feedback Simulation",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "simulation_only": True,
        "kpis": kpis,
        "limitations": [
            "All generated complaints are synthetic.",
            "No real customer communication occurs.",
            "No actual refund or supplier penalty occurs.",
            "Complaint counts are not verified defect rates.",
            "Acknowledgement and resolution are simulated.",
            "No production database records are modified."
        ]
    }

    with (
        output_dir / "negative_feedback_report.json"
    ).open(
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            report,
            file,
            indent=2
        )

    create_dashboard(
        complaints_df,
        product_summary,
        supplier_summary,
        kpis,
        output_dir
    )


# ============================================================
# 20. MAIN
# ============================================================

def main():
    args = parse_args()

    print("=" * 75)
    print("SUPPLYCHAINAI — NEGATIVE FEEDBACK SIMULATOR")
    print("=" * 75)

    products, suppliers, feedback = (
        load_reference_data()
    )

    model = load_sentiment_model(
        args.use_model
    )

    simulator = NegativeFeedbackSimulator(
        products,
        suppliers,
        feedback,
        seed=args.seed,
        model=model
    )

    complaints_df = simulator.run(
        count=args.complaints,
        scenario=args.scenario
    )

    product_summary = analyze_products(
        complaints_df,
        products,
        feedback
    )

    supplier_summary = analyze_suppliers(
        complaints_df
    )

    kpis = calculate_kpis(
        complaints_df,
        simulator
    )

    export_results(
        simulator,
        complaints_df,
        product_summary,
        supplier_summary,
        kpis,
        args.output.resolve()
    )

    print("\nSIMULATION KPIs")
    print(
        json.dumps(
            kpis,
            indent=2
        )
    )

    print("\nTOP COMPLAINTS")
    print(
        complaints_df[
            [
                "complaint_id",
                "product_id",
                "topic",
                "priority",
                "status",
                "ack_sla_breached"
            ]
        ]
        .head(20)
        .to_string(index=False)
    )

    print("\nGenerated files:")
    for path in sorted(
        args.output.resolve().iterdir()
    ):
        if path.is_file():
            print(path)

    print("\nNegative feedback simulation completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
