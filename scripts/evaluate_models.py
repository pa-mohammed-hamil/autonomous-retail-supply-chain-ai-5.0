
#!/usr/bin/env python3
"""
SupplyChainAI — Model Evaluation CLI

File: scripts/evaluate_models.py

Features:
- Discover saved model artifacts
- Load existing evaluation reports
- Recalculate forecast metrics from held-out predictions
- Compare forecasting candidate metrics
- Summarize stockout classifier evaluation
- Summarize supplier risk classifier evaluation
- Summarize sentiment classifier evaluation
- Identify synthetic / weak labels
- Track missing model artifacts and evaluation data
- Export model registry, evaluation reports and HTML dashboard
- Fail CI checks when explicitly configured

Security:
- Does not load pickle/joblib models by default.
- Does not retrain or overwrite existing models.
- Does not invent missing evaluation metrics.
- Does not treat synthetic labels as real outcomes.

Install:
    pip install pandas numpy scikit-learn

Usage:
    python scripts/evaluate_models.py
    python scripts/evaluate_models.py --model all
    python scripts/evaluate_models.py --model demand
    python scripts/evaluate_models.py --model stockout
    python scripts/evaluate_models.py --model supplier
    python scripts/evaluate_models.py --model sentiment
    python scripts/evaluate_models.py --strict
    python scripts/evaluate_models.py --output reports/evaluations

Run from any directory.
"""

import argparse
import html
import json
import math
import sys

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error
)


# ============================================================
# 1. PROJECT PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

REPORTS_DIR = PROJECT_ROOT / "reports"
MODELS_DIR = PROJECT_ROOT / "models"

DEFAULT_OUTPUT_DIR = REPORTS_DIR / "evaluations"

MODEL_CONFIG = {
    "demand": {
        "display_name": "Demand Forecasting",
        "model_file": (
            MODELS_DIR
            / "demand_forecasting"
            / "demand_forecasting_model.joblib"
        ),
        "report_file": (
            REPORTS_DIR
            / "forecasting"
            / "forecast_report.json"
        )
    },
    "stockout": {
        "display_name": "Stockout Prediction",
        "model_file": (
            MODELS_DIR
            / "stockout_prediction"
            / "stockout_classifier.joblib"
        ),
        "report_file": (
            REPORTS_DIR
            / "stockout_prediction"
            / "stockout_report.json"
        )
    },
    "supplier": {
        "display_name": "Supplier Risk",
        "model_file": (
            MODELS_DIR
            / "supplier_risk"
            / "supplier_risk_classifier.joblib"
        ),
        "report_file": (
            REPORTS_DIR
            / "supplier_risk"
            / "supplier_risk_report.json"
        )
    },
    "sentiment": {
        "display_name": "Sentiment Analysis",
        "model_file": (
            MODELS_DIR
            / "sentiment_analysis"
            / "sentiment_classifier.joblib"
        ),
        "report_file": (
            REPORTS_DIR
            / "sentiment_analysis"
            / "sentiment_report.json"
        )
    }
}


# ============================================================
# 2. UTILITIES
# ============================================================

def utc_now():
    return datetime.now(
        timezone.utc
    ).isoformat()


def load_json(path):
    if not path.exists():
        return None

    try:
        with path.open(
            "r",
            encoding="utf-8"
        ) as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError(
                "Expected JSON object."
            )

        return data

    except (
        OSError,
        ValueError,
        json.JSONDecodeError
    ) as exc:
        print(
            f"[WARNING] Could not read {path}: {exc}"
        )
        return None


def safe_number(value):
    try:
        number = float(value)

        if math.isfinite(number):
            return number

    except (TypeError, ValueError):
        pass

    return None


def json_safe(value):
    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [
            json_safe(item)
            for item in value
        ]

    if isinstance(value, np.integer):
        return int(value)

    if isinstance(value, np.floating):
        return safe_number(value)

    if isinstance(value, np.bool_):
        return bool(value)

    if isinstance(value, float):
        return safe_number(value)

    return value


def save_json(path, data):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with path.open(
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            json_safe(data),
            file,
            indent=2,
            allow_nan=False
        )


def report_metric(report, *keys):
    current = report

    for key in keys:
        if not isinstance(current, dict):
            return None

        current = current.get(key)

    return safe_number(current)


def get_status(report, model_file):
    if report is None:
        return "missing_report"

    if not model_file.exists():
        return "report_only"

    return "artifact_and_report"


# ============================================================
# 3. FORECAST EVALUATION
# ============================================================

def evaluate_forecast_predictions():
    """
    Recalculate demand forecast metrics using saved
    held-out test predictions.

    Expected CSV:
        reports/forecasting/test_predictions.csv

    Required columns:
        actual
        predicted

    Alternative column names:
        actual_demand
        predicted_demand

    A saved test prediction file is assumed to be
    a previously generated held-out evaluation.
    This script does not verify its split provenance.
    """

    path = (
        REPORTS_DIR
        / "forecasting"
        / "test_predictions.csv"
    )

    if not path.exists():
        return {
            "available": False,
            "reason": "Test predictions CSV not found."
        }

    try:
        df = pd.read_csv(path)

        actual_col = next(
            (
                column
                for column in [
                    "actual",
                    "actual_demand",
                    "y_true"
                ]
                if column in df.columns
            ),
            None
        )

        predicted_col = next(
            (
                column
                for column in [
                    "predicted",
                    "predicted_demand",
                    "y_pred"
                ]
                if column in df.columns
            ),
            None
        )

        if not actual_col or not predicted_col:
            return {
                "available": False,
                "reason": (
                    "Actual/predicted columns missing."
                )
            }

        evaluation = df[
            [actual_col, predicted_col]
        ].copy()

        evaluation.columns = [
            "actual",
            "predicted"
        ]

        evaluation["actual"] = pd.to_numeric(
            evaluation["actual"],
            errors="coerce"
        )

        evaluation["predicted"] = pd.to_numeric(
            evaluation["predicted"],
            errors="coerce"
        )

        evaluation = evaluation.replace(
            [np.inf, -np.inf],
            np.nan
        ).dropna()

        if evaluation.empty:
            return {
                "available": False,
                "reason": "No valid prediction rows."
            }

        actual = evaluation["actual"].to_numpy()
        predicted = evaluation["predicted"].to_numpy()

        mae = mean_absolute_error(
            actual,
            predicted
        )

        rmse = np.sqrt(
            mean_squared_error(
                actual,
                predicted
            )
        )

        denominator = np.abs(actual).sum()

        wape = (
            np.abs(actual - predicted).sum()
            / denominator * 100
            if denominator > 0
            else None
        )

        bias = float(
            np.mean(predicted - actual)
        )

        return {
            "available": True,
            "sample_count": int(len(evaluation)),
            "MAE": float(mae),
            "RMSE": float(rmse),
            "WAPE_pct": (
                float(wape)
                if wape is not None
                else None
            ),
            "Bias": bias,
            "source": str(
                path.relative_to(PROJECT_ROOT)
            )
        }

    except (
        OSError,
        ValueError,
        KeyError
    ) as exc:
        return {
            "available": False,
            "reason": str(exc)
        }


def evaluate_demand(report):
    if report is None:
        return {
            "task": "demand",
            "metrics": {},
            "evaluation_status": "missing"
        }

    recalculated = evaluate_forecast_predictions()

    reported_metrics = report.get(
        "test_metrics", {}
    )

    if not isinstance(reported_metrics, dict):
        reported_metrics = {}

    metrics = {
        "MAE": report_metric(
            report, "test_metrics", "MAE"
        ),
        "RMSE": report_metric(
            report, "test_metrics", "RMSE"
        ),
        "WAPE_pct": report_metric(
            report, "test_metrics", "WAPE_pct"
        ),
        "Bias": report_metric(
            report, "test_metrics", "Bias"
        )
    }

    return {
        "task": "demand",
        "algorithm": report.get("model"),
        "metrics": metrics,
        "recalculated_metrics": recalculated,
        "evaluation_status": (
            "reported_holdout"
            if any(
                value is not None
                for value in metrics.values()
            )
            else "incomplete"
        ),
        "label_provenance": "observed_sales",
        "limitations": [
            "Aggregate rather than SKU-level forecasting.",
            "Recorded sales may underestimate demand.",
            "Forecast evaluation provenance depends on notebook."
        ]
    }


# ============================================================
# 4. STOCKOUT EVALUATION
# ============================================================

def evaluate_stockout(report):
    if report is None:
        return {
            "task": "stockout",
            "metrics": {},
            "evaluation_status": "missing"
        }

    source = report.get(
        "label_source",
        "simulated_inventory_trajectory"
    )

    metrics = report.get(
        "test_metrics_on_simulated_labels", {}
    )

    if not isinstance(metrics, dict):
        metrics = {}

    return {
        "task": "stockout",
        "algorithm": report.get(
            "classification_model"
        ),
        "metrics": {
            "roc_auc": safe_number(
                metrics.get("roc_auc")
            ),
            "average_precision": safe_number(
                metrics.get("average_precision")
            ),
            "brier_score": safe_number(
                metrics.get("brier_score")
            )
        },
        "evaluation_status": "simulation_only",
        "label_provenance": source,
        "real_world_validated": False,
        "limitations": [
            "Historical stockout labels were simulated.",
            "Metrics do not establish real-world stockout accuracy.",
            "Requires historical inventory and fulfillment outcomes."
        ]
    }


# ============================================================
# 5. SUPPLIER RISK EVALUATION
# ============================================================

def evaluate_supplier(report):
    if report is None:
        return {
            "task": "supplier",
            "metrics": {},
            "evaluation_status": "missing"
        }

    metrics = report.get(
        "ml_test_metrics", {}
    )

    if not isinstance(metrics, dict):
        metrics = {}

    return {
        "task": "supplier",
        "algorithm": report.get(
            "ml_model"
        ),
        "metrics": {
            "roc_auc": safe_number(
                metrics.get("roc_auc")
            ),
            "average_precision": safe_number(
                metrics.get("average_precision")
            ),
            "test_samples": metrics.get(
                "test_samples"
            )
        },
        "evaluation_status": "synthetic_labels",
        "label_provenance": report.get(
            "ml_label_source",
            "synthetic_heuristic"
        ),
        "real_world_validated": False,
        "limitations": [
            "Labels derive from heuristic scores.",
            "Evaluation does not measure real supplier failures.",
            "Requires verified supplier disruption outcomes."
        ]
    }


# ============================================================
# 6. SENTIMENT EVALUATION
# ============================================================

def evaluate_sentiment(report):
    if report is None:
        return {
            "task": "sentiment",
            "metrics": {},
            "evaluation_status": "missing"
        }

    metrics = report.get("metrics", {})

    if not isinstance(metrics, dict):
        metrics = {}

    label_source = report.get(
        "label_source",
        "unknown"
    )

    data_source = report.get(
        "data_source",
        "unknown"
    )

    if (
        label_source == "Provided sentiment labels"
        and data_source != "Synthetic demonstration feedback"
    ):
        status = "labeled_prototype"
    elif label_source == "Rating-derived weak labels":
        status = "weak_supervision"
    else:
        status = "demonstration_only"

    return {
        "task": "sentiment",
        "algorithm": report.get("model"),
        "metrics": {
            "accuracy": safe_number(
                metrics.get("accuracy")
            ),
            "macro_f1": safe_number(
                metrics.get("macro_f1")
            ),
            "test_samples": metrics.get(
                "test_samples"
            )
        },
        "evaluation_status": status,
        "label_provenance": label_source,
        "real_world_validated": False,
        "limitations": [
            "Text classification is primarily English-focused.",
            "Random unique-text holdout is not temporal validation.",
            "Requires representative real-world evaluation."
        ]
    }


# ============================================================
# 7. EVALUATION DISPATCH
# ============================================================

EVALUATORS = {
    "demand": evaluate_demand,
    "stockout": evaluate_stockout,
    "supplier": evaluate_supplier,
    "sentiment": evaluate_sentiment
}


def evaluate_one(model_name):
    config = MODEL_CONFIG[model_name]

    report = load_json(
        config["report_file"]
    )

    evaluation = EVALUATORS[
        model_name
    ](report)

    evaluation.update({
        "name": config["display_name"],
        "model_file": str(
            config["model_file"].relative_to(
                PROJECT_ROOT
            )
        ),
        "report_file": str(
            config["report_file"].relative_to(
                PROJECT_ROOT
            )
        ),
        "artifact_exists": (
            config["model_file"].exists()
        ),
        "report_exists": report is not None,
        "artifact_status": get_status(
            report,
            config["model_file"]
        ),
        "production_ready": False
    })

    return evaluation


# ============================================================
# 8. METRICS TABLE
# ============================================================

def build_metrics_table(evaluations):
    rows = []

    for evaluation in evaluations:
        for metric, value in (
            evaluation.get("metrics") or {}
        ).items():
            rows.append({
                "model": evaluation["name"],
                "metric": metric,
                "value": safe_number(value),
                "evaluation_status": evaluation.get(
                    "evaluation_status"
                ),
                "label_provenance": evaluation.get(
                    "label_provenance"
                )
            })

    return pd.DataFrame(
        rows,
        columns=[
            "model",
            "metric",
            "value",
            "evaluation_status",
            "label_provenance"
        ]
    )


# ============================================================
# 9. MODEL REGISTRY TABLE
# ============================================================

def build_registry_table(evaluations):
    rows = []

    for evaluation in evaluations:
        rows.append({
            "model": evaluation["name"],
            "algorithm": evaluation.get("algorithm"),
            "artifact_exists": evaluation["artifact_exists"],
            "report_exists": evaluation["report_exists"],
            "evaluation_status": evaluation.get(
                "evaluation_status"
            ),
            "label_provenance": evaluation.get(
                "label_provenance"
            ),
            "production_ready": False
        })

    return pd.DataFrame(rows)


# ============================================================
# 10. HTML REPORT
# ============================================================

def dataframe_html(df):
    if df.empty:
        return "<p>No evaluation data available.</p>"

    return df.to_html(
        index=False,
        escape=True,
        border=0,
        na_rep="N/A",
        classes="data-table"
    )


def create_html_dashboard(
    evaluations,
    registry_df,
    metrics_df,
    output_path
):
    generated_at = html.escape(utc_now())

    dashboard = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1">
<title>SupplyChainAI — Model Evaluation</title>
<style>
:root {{
    color-scheme: dark;
    font-family: Inter, Arial, sans-serif;
}}
* {{ box-sizing: border-box; }}
body {{
    background: #0a1020;
    color: #e8eef9;
    margin: 0;
    padding: 30px;
}}
main {{
    max-width: 1400px;
    margin: auto;
}}
h1 {{
    font-size: 34px;
    margin-bottom: 6px;
}}
.subtitle {{
    color: #9aabc8;
    margin-bottom: 30px;
}}
.card {{
    background: #151f35;
    border: 1px solid #293955;
    border-radius: 16px;
    padding: 24px;
    margin-bottom: 24px;
    overflow-x: auto;
}}
table {{
    border-collapse: collapse;
    width: 100%;
}}
th, td {{
    padding: 12px;
    text-align: left;
    border-bottom: 1px solid #34415d;
}}
th {{
    background: #22304a;
}}
.warning {{
    background: #332a1e;
    border-left: 4px solid #f1bb60;
    border-radius: 8px;
    padding: 18px;
    margin-bottom: 24px;
}}
footer {{
    color: #8d9ab2;
    margin-top: 30px;
}}
</style>
</head>
<body>
<main>
<h1>SupplyChainAI — Model Evaluation</h1>
<p class="subtitle">
Demand Forecasting · Stockout Prediction · Supplier Risk · Sentiment Analysis
</p>

<div class="warning">
Metrics are task-specific. Synthetic-label evaluations
must not be interpreted as real-world performance.
No model is automatically approved for production.
</div>

<section class="card">
<h2>Model Registry</h2>
{dataframe_html(registry_df)}
</section>

<section class="card">
<h2>Evaluation Metrics</h2>
{dataframe_html(metrics_df)}
</section>

<section class="card">
<h2>Model Limitations</h2>
"""

    for evaluation in evaluations:
        name = html.escape(
            evaluation["name"]
        )

        limitations = evaluation.get(
            "limitations", []
        )

        dashboard += f"<h3>{name}</h3><ul>"

        for limitation in limitations:
            dashboard += (
                f"<li>{html.escape(str(limitation))}</li>"
            )

        dashboard += "</ul>"

    dashboard += f"""
</section>
<footer>Generated: {generated_at}</footer>
</main>
</body>
</html>
"""

    output_path.write_text(
        dashboard,
        encoding="utf-8"
    )


# ============================================================
# 11. CLI
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate SupplyChainAI model artifacts "
            "and existing notebook reports."
        )
    )

    parser.add_argument(
        "--model",
        choices=[
            "all",
            "demand",
            "stockout",
            "supplier",
            "sentiment"
        ],
        default="all"
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Exit with status 1 when any selected "
            "model report or artifact is missing."
        )
    )

    return parser.parse_args()


# ============================================================
# 12. MAIN
# ============================================================

def main():
    args = parse_args()

    output_dir = args.output.resolve()
    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    selected_models = (
        list(MODEL_CONFIG)
        if args.model == "all"
        else [args.model]
    )

    print("=" * 75)
    print("SUPPLYCHAINAI — MODEL EVALUATION")
    print("=" * 75)

    evaluations = []

    for model_name in selected_models:
        print(
            f"\nEvaluating: "
            f"{MODEL_CONFIG[model_name]['display_name']}"
        )

        evaluation = evaluate_one(
            model_name
        )

        evaluations.append(evaluation)

        print(
            "Status:",
            evaluation["evaluation_status"]
        )

        print(
            "Model artifact:",
            "Found"
            if evaluation["artifact_exists"]
            else "Missing"
        )

        print(
            "Evaluation report:",
            "Found"
            if evaluation["report_exists"]
            else "Missing"
        )

        for metric, value in (
            evaluation.get("metrics") or {}
        ).items():
            if safe_number(value) is not None:
                print(
                    f"  {metric}: "
                    f"{safe_number(value):.4f}"
                )

    registry_df = build_registry_table(
        evaluations
    )

    metrics_df = build_metrics_table(
        evaluations
    )

    registry_df.to_csv(
        output_dir / "model_registry.csv",
        index=False
    )

    metrics_df.to_csv(
        output_dir / "evaluation_metrics.csv",
        index=False
    )

    summary = {
        "project": "SupplyChainAI",
        "generated_at": utc_now(),
        "models_requested": selected_models,
        "evaluations": evaluations,
        "production_ready_models": [],
        "notes": [
            "Model files are checked for existence only.",
            "Pickle/joblib models are not deserialized.",
            "Missing metrics are not estimated.",
            "Stockout and supplier evaluation use synthetic labels.",
            "Production approval requires independent validation."
        ]
    }

    save_json(
        output_dir / "evaluation_report.json",
        summary
    )

    create_html_dashboard(
        evaluations,
        registry_df,
        metrics_df,
        output_dir / "evaluation_dashboard.html"
    )

    print("\nMODEL REGISTRY")
    print(
        registry_df.to_string(index=False)
    )

    print("\nGENERATED FILES")
    print(output_dir / "model_registry.csv")
    print(output_dir / "evaluation_metrics.csv")
    print(output_dir / "evaluation_report.json")
    print(output_dir / "evaluation_dashboard.html")

    if args.strict:
        missing = [
            evaluation["name"]
            for evaluation in evaluations
            if not (
                evaluation["artifact_exists"]
                and evaluation["report_exists"]
            )
        ]

        if missing:
            print(
                "\nSTRICT CHECK FAILED:",
                ", ".join(missing)
            )
            return 1

    print("\nEvaluation completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
