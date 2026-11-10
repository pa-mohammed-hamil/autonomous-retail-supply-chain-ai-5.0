"""Planned module: train models. Implementation pending."""

#!/usr/bin/env python3
"""
SupplyChainAI — Multi-Model Training Pipeline

File:
    scripts/train_models.py

Models:
    demand
    stockout
    supplier
    sentiment

Datasets:
    data/sales.csv
    data/inventory.csv
    data/products.csv
    data/suppliers.csv
    data/feedback.csv

Outputs:
    models/demand_forecasting/
    models/stockout_prediction/
    models/supplier_risk/
    models/sentiment_analysis/

    reports/forecasting/
    reports/stockout_prediction/
    reports/supplier_risk/
    reports/sentiment_analysis/
    reports/training/

Commands:
    python scripts/train_models.py
    python scripts/train_models.py --model demand
    python scripts/train_models.py --model stockout
    python scripts/train_models.py --model supplier
    python scripts/train_models.py --model sentiment
    python scripts/train_models.py --model all --seed 42

Important:
    Stockout and supplier classification use proxy labels
    derived from heuristics, not verified incident outcomes.
"""

import argparse
import json
import sys
import warnings

from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (
    HistGradientBoostingRegressor,
    RandomForestClassifier
)
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    classification_report,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    recall_score,
    roc_auc_score
)
from sklearn.model_selection import (
    GroupShuffleSplit,
    train_test_split
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import (
    OneHotEncoder,
    StandardScaler
)


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MODEL_DIR = ROOT / "models"
REPORT_DIR = ROOT / "reports"

SEED = 42


def now_iso():
    return datetime.now(
        timezone.utc
    ).isoformat()


def save_json(path, payload):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with path.open(
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            payload,
            file,
            indent=2,
            default=str
        )


def save_model(path, model):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    joblib.dump(
        model,
        path
    )


def load_csv(name, required):
    path = DATA_DIR / name

    if not path.exists():
        raise FileNotFoundError(
            f"Missing dataset: {path}. "
            "Run generate_demo_data.py first."
        )

    frame = pd.read_csv(path)

    missing = sorted(
        set(required) - set(frame.columns)
    )

    if missing:
        raise ValueError(
            f"{name}: missing columns {missing}"
        )

    return frame


def numeric(frame, columns):
    for column in columns:
        frame[column] = pd.to_numeric(
            frame[column],
            errors="coerce"
        )

    return frame


def make_one_hot_encoder():
    try:
        return OneHotEncoder(
            handle_unknown="ignore",
            sparse_output=False
        )
    except TypeError:
        return OneHotEncoder(
            handle_unknown="ignore",
            sparse=False
        )


def regression_metrics(actual, predicted):
    actual = np.asarray(
        actual,
        dtype=float
    )

    predicted = np.asarray(
        predicted,
        dtype=float
    )

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

    return {
        "MAE": round(float(mae), 4),
        "RMSE": round(float(rmse), 4),
        "WAPE_pct": (
            round(float(wape), 4)
            if wape is not None
            else None
        ),
        "Bias": round(
            float(np.mean(predicted - actual)),
            4
        )
    }


def binary_metrics(actual, predicted, probability):
    metrics = {
        "accuracy": float(
            accuracy_score(actual, predicted)
        ),
        "precision": float(
            precision_score(
                actual,
                predicted,
                zero_division=0
            )
        ),
        "recall": float(
            recall_score(
                actual,
                predicted,
                zero_division=0
            )
        ),
        "f1": float(
            f1_score(
                actual,
                predicted,
                zero_division=0
            )
        )
    }

    if len(np.unique(actual)) == 2:
        metrics["roc_auc"] = float(
            roc_auc_score(
                actual,
                probability
            )
        )

        metrics["average_precision"] = float(
            average_precision_score(
                actual,
                probability
            )
        )

        metrics["brier_score"] = float(
            brier_score_loss(
                actual,
                probability
            )
        )

    return metrics


# ============================================================
# 1. DEMAND FORECASTING
# ============================================================

def train_demand(seed):
    print("\n[1/4] Training demand forecasting...")

    sales = load_csv(
        "sales.csv",
        ["date", "quantity_sold"]
    )

    sales["date"] = pd.to_datetime(
        sales["date"],
        errors="coerce"
    )

    sales["quantity_sold"] = pd.to_numeric(
        sales["quantity_sold"],
        errors="coerce"
    )

    sales = sales.dropna(
        subset=["date", "quantity_sold"]
    )

    if (
        sales.empty
        or (sales["quantity_sold"] < 0).any()
    ):
        raise ValueError(
            "Invalid demand training data."
        )

    daily = (
        sales.groupby(
            sales["date"].dt.normalize()
        )["quantity_sold"]
        .sum()
        .sort_index()
    )

    daily = daily.asfreq(
        "D",
        fill_value=0
    )

    frame = daily.rename(
        "demand"
    ).reset_index()

    frame.columns = [
        "date",
        "demand"
    ]

    frame["day_of_week"] = (
        frame["date"].dt.dayofweek
    )

    frame["month"] = (
        frame["date"].dt.month
    )

    frame["day_of_month"] = (
        frame["date"].dt.day
    )

    frame["is_weekend"] = (
        frame["day_of_week"] >= 5
    ).astype(int)

    for lag in [1, 7, 14, 28]:
        frame[f"lag_{lag}"] = (
            frame["demand"].shift(lag)
        )

    for window in [7, 14, 28]:
        frame[f"rolling_mean_{window}"] = (
            frame["demand"]
            .shift(1)
            .rolling(window)
            .mean()
        )

    frame = frame.dropna().copy()

    if len(frame) < 60:
        raise ValueError(
            "Demand training requires at least "
            "60 usable daily observations."
        )

    features = [
        column
        for column in frame.columns
        if column not in [
            "date",
            "demand"
        ]
    ]

    test_size = max(
        14,
        int(len(frame) * 0.20)
    )

    train = frame.iloc[
        :-test_size
    ].copy()

    test = frame.iloc[
        -test_size:
    ].copy()

    model = HistGradientBoostingRegressor(
        max_iter=180,
        max_leaf_nodes=15,
        learning_rate=0.05,
        l2_regularization=0.1,
        random_state=seed
    )

    model.fit(
        train[features],
        train["demand"]
    )

    predictions = np.maximum(
        model.predict(
            test[features]
        ),
        0
    )

    metrics = regression_metrics(
        test["demand"],
        predictions
    )

    artifact = {
        "model": model,
        "feature_columns": features,
        "target": "daily_total_demand",
        "history_days": 28,
        "training_end_date": str(
            train["date"].max().date()
        ),
        "model_type": (
            "HistGradientBoostingRegressor"
        )
    }

    model_path = (
        MODEL_DIR
        / "demand_forecasting"
        / "demand_forecasting_model.joblib"
    )

    save_model(
        model_path,
        artifact
    )

    output = (
        REPORT_DIR / "forecasting"
    )

    output.mkdir(
        parents=True,
        exist_ok=True
    )

    predictions_df = pd.DataFrame({
        "date": test["date"],
        "actual": test["demand"].values,
        "predicted": predictions
    })

    predictions_df.to_csv(
        output / "test_predictions.csv",
        index=False
    )

    report = {
        "model": "demand_forecasting",
        "generated_at": now_iso(),
        "test_metrics": metrics,
        "train_samples": len(train),
        "test_samples": len(test),
        "feature_columns": features,
        "evaluation_method": (
            "Chronological holdout with observed "
            "historical lag features"
        ),
        "limitations": [
            "Forecasts aggregate daily sales only.",
            "Sales may be censored by stockouts.",
            "Test lag features include actual past "
            "observations, so metrics do not represent "
            "a fully recursive multi-day forecast.",
            "Synthetic sales metrics are not "
            "real-world performance evidence."
        ],
        "artifact_path": str(
            model_path.relative_to(ROOT)
        )
    }

    save_json(
        output / "forecast_report.json",
        report
    )

    print("Demand metrics:", metrics)

    return report


# ============================================================
# 2. STOCKOUT PREDICTION
# ============================================================

def train_stockout(seed):
    print("\n[2/4] Training stockout classifier...")

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

    products = load_csv(
        "products.csv",
        [
            "product_id",
            "category",
            "supplier_id"
        ]
    )

    suppliers = load_csv(
        "suppliers.csv",
        [
            "supplier_id",
            "lead_time_days",
            "risk_score"
        ]
    )

    sales["date"] = pd.to_datetime(
        sales["date"],
        errors="coerce"
    )

    sales["quantity_sold"] = pd.to_numeric(
        sales["quantity_sold"],
        errors="coerce"
    )

    sales = sales.dropna(
        subset=["date", "quantity_sold"]
    )

    latest = sales["date"].max()

    recent = sales[
        sales["date"] >= (
            latest - pd.Timedelta(days=27)
        )
    ]

    demand = (
        recent.groupby(
            ["product_id", "warehouse_id"],
            as_index=False
        )["quantity_sold"]
        .sum()
    )

    demand["avg_daily_demand"] = (
        demand["quantity_sold"] / 28
    )

    frame = inventory.merge(
        demand[
            [
                "product_id",
                "warehouse_id",
                "avg_daily_demand"
            ]
        ],
        on=["product_id", "warehouse_id"],
        how="left"
    )

    frame = frame.merge(
        products,
        on="product_id",
        how="left"
    )

    frame = frame.merge(
        suppliers,
        on="supplier_id",
        how="left"
    )

    numeric(
        frame,
        [
            "stock_on_hand",
            "reorder_point",
            "safety_stock",
            "avg_daily_demand",
            "lead_time_days",
            "risk_score"
        ]
    )

    frame["avg_daily_demand"] = (
        frame["avg_daily_demand"].fillna(0)
    )

    frame["lead_time_days"] = (
        frame["lead_time_days"].fillna(7)
    )

    frame["risk_score"] = (
        frame["risk_score"].fillna(0.5)
    )

    frame["demand_during_lead_time"] = (
        frame["avg_daily_demand"]
        * frame["lead_time_days"]
    )

    frame["stock_coverage_days"] = (
        frame["stock_on_hand"]
        / frame["avg_daily_demand"].clip(
            lower=0.01
        )
    )

    frame["stock_gap"] = (
        frame["stock_on_hand"]
        - frame["demand_during_lead_time"]
    )

    # Synthetic proxy target:
    # This is not a recorded historical stockout.
    frame["stockout_proxy"] = (
        frame["stock_on_hand"]
        < (
            frame["demand_during_lead_time"]
            + frame["safety_stock"]
        )
    ).astype(int)

    features = [
        "stock_on_hand",
        "reorder_point",
        "safety_stock",
        "avg_daily_demand",
        "lead_time_days",
        "risk_score",
        "demand_during_lead_time",
        "stock_coverage_days",
        "stock_gap"
    ]

    if (
        len(frame) < 30
        or frame["stockout_proxy"].nunique() < 2
    ):
        raise ValueError(
            "Insufficient samples or proxy-label "
            "diversity for stockout training."
        )

    x_train, x_test, y_train, y_test = (
        train_test_split(
            frame[features],
            frame["stockout_proxy"],
            test_size=0.25,
            random_state=seed,
            stratify=frame["stockout_proxy"]
        )
    )

    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=10,
        min_samples_leaf=2,
        class_weight="balanced",
        random_state=seed,
        n_jobs=-1
    )

    model.fit(
        x_train,
        y_train
    )

    predictions = model.predict(
        x_test
    )

    probabilities = (
        model.predict_proba(x_test)[:, 1]
    )

    metrics = binary_metrics(
        y_test,
        predictions,
        probabilities
    )

    model_path = (
        MODEL_DIR
        / "stockout_prediction"
        / "stockout_classifier.joblib"
    )

    save_model(
        model_path,
        model
    )

    report = {
        "model": "stockout_prediction",
        "generated_at": now_iso(),
        "test_metrics_on_simulated_labels": metrics,
        "label_source": (
            "Heuristic stockout proxy from inventory "
            "and estimated lead-time demand"
        ),
        "real_world_validation": False,
        "train_samples": len(x_train),
        "test_samples": len(x_test),
        "feature_columns": features,
        "limitations": [
            "Target labels are calculated from input "
            "features and are not observed stockouts.",
            "High test scores would only demonstrate "
            "learning the heuristic.",
            "The split is cross-sectional, not "
            "an out-of-time inventory evaluation.",
            "This model must not be presented as "
            "a validated production stockout predictor."
        ],
        "artifact_path": str(
            model_path.relative_to(ROOT)
        )
    }

    save_json(
        REPORT_DIR
        / "stockout_prediction"
        / "stockout_report.json",
        report
    )

    print("Stockout proxy metrics:", metrics)

    return report


# ============================================================
# 3. SUPPLIER RISK
# ============================================================

def train_supplier(seed):
    print("\n[3/4] Training supplier risk classifier...")

    suppliers = load_csv(
        "suppliers.csv",
        [
            "supplier_id",
            "lead_time_days",
            "on_time_delivery_rate",
            "defect_rate",
            "risk_score"
        ]
    )

    features = [
        "lead_time_days",
        "on_time_delivery_rate",
        "defect_rate"
    ]

    numeric(
        suppliers,
        features + ["risk_score"]
    )

    frame = suppliers.dropna(
        subset=features + ["risk_score"]
    ).copy()

    # The provided risk score is a heuristic.
    # The binary label below is therefore synthetic.
    threshold = frame[
        "risk_score"
    ].median()

    frame["risk_proxy"] = (
        frame["risk_score"] >= threshold
    ).astype(int)

    class_counts = (
        frame["risk_proxy"].value_counts()
    )

    if (
        len(frame) < 12
        or frame["risk_proxy"].nunique() < 2
        or class_counts.min() < 2
    ):
        raise ValueError(
            "Insufficient supplier samples "
            "for a stratified train/test split."
        )

    x_train, x_test, y_train, y_test = (
        train_test_split(
            frame[features],
            frame["risk_proxy"],
            test_size=0.30,
            stratify=frame["risk_proxy"],
            random_state=seed
        )
    )

    model = RandomForestClassifier(
        n_estimators=150,
        max_depth=5,
        min_samples_leaf=1,
        class_weight="balanced",
        random_state=seed,
        n_jobs=-1
    )

    model.fit(
        x_train,
        y_train
    )

    predicted = model.predict(
        x_test
    )

    probability = (
        model.predict_proba(x_test)[:, 1]
    )

    metrics = binary_metrics(
        y_test,
        predicted,
        probability
    )

    model_path = (
        MODEL_DIR
        / "supplier_risk"
        / "supplier_risk_classifier.joblib"
    )

    save_model(
        model_path,
        model
    )

    report = {
        "model": "supplier_risk",
        "generated_at": now_iso(),
        "ml_test_metrics": metrics,
        "risk_threshold": float(threshold),
        "label_source": (
            "Synthetic labels thresholded from "
            "existing supplier risk scores"
        ),
        "real_world_validation": False,
        "train_samples": len(x_train),
        "test_samples": len(x_test),
        "feature_columns": features,
        "limitations": [
            "Supplier labels are heuristic proxies.",
            "No actual supplier failure outcomes "
            "are used as targets.",
            "A small supplier dataset produces "
            "unstable evaluation estimates.",
            "Model metrics cannot establish "
            "real-world supplier failure accuracy."
        ],
        "artifact_path": str(
            model_path.relative_to(ROOT)
        )
    }

    save_json(
        REPORT_DIR
        / "supplier_risk"
        / "supplier_risk_report.json",
        report
    )

    print("Supplier proxy metrics:", metrics)

    return report


# ============================================================
# 4. SENTIMENT ANALYSIS
# ============================================================

def train_sentiment(seed):
    print("\n[4/4] Training sentiment classifier...")

    feedback = load_csv(
        "feedback.csv",
        [
            "feedback_id",
            "feedback_text"
        ]
    )

    feedback["feedback_text"] = (
        feedback["feedback_text"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    feedback = feedback[
        feedback["feedback_text"] != ""
    ].copy()

    if "sentiment_label" in feedback.columns:
        feedback["label"] = (
            feedback["sentiment_label"]
            .astype(str)
            .str.strip()
            .str.lower()
        )

        label_source = (
            "Provided sentiment labels"
        )

    elif "rating" in feedback.columns:
        ratings = pd.to_numeric(
            feedback["rating"],
            errors="coerce"
        )

        feedback["label"] = np.select(
            [
                ratings <= 2,
                ratings == 3,
                ratings >= 4
            ],
            [
                "negative",
                "neutral",
                "positive"
            ],
            default="unknown"
        )

        label_source = (
            "Rating-derived weak labels"
        )

    else:
        raise ValueError(
            "Feedback needs sentiment_label "
            "or rating."
        )

    feedback = feedback[
        feedback["label"].isin(
            ["negative", "neutral", "positive"]
        )
    ].copy()

    # Normalize duplicate templates to prevent
    # identical review texts appearing in both splits.
    feedback["normalized_text"] = (
        feedback["feedback_text"]
        .str.lower()
        .str.replace(
            r"\s+",
            " ",
            regex=True
        )
        .str.strip()
    )

    conflicting = (
        feedback.groupby(
            "normalized_text"
        )["label"]
        .nunique()
    )

    conflicting_texts = set(
        conflicting[
            conflicting > 1
        ].index
    )

    feedback = feedback[
        ~feedback["normalized_text"].isin(
            conflicting_texts
        )
    ].copy()

    # One sample per unique normalized text.
    feedback = feedback.drop_duplicates(
        subset=["normalized_text"]
    )

    counts = feedback[
        "label"
    ].value_counts()

    if (
        len(feedback) < 15
        or len(counts) < 2
        or counts.min() < 3
    ):
        raise ValueError(
            "Insufficient unique sentiment examples. "
            "Add more diverse labeled reviews. "
            "Repeating the same templates does not "
            "increase independent training samples."
        )

    x_train, x_test, y_train, y_test = (
        train_test_split(
            feedback["feedback_text"],
            feedback["label"],
            test_size=0.30,
            stratify=feedback["label"],
            random_state=seed
        )
    )

    model = Pipeline([
        (
            "tfidf",
            TfidfVectorizer(
                max_features=15000,
                ngram_range=(1, 2),
                min_df=1,
                sublinear_tf=True
            )
        ),
        (
            "classifier",
            LogisticRegression(
                max_iter=1500,
                class_weight="balanced",
                random_state=seed
            )
        )
    ])

    model.fit(
        x_train,
        y_train
    )

    predictions = model.predict(
        x_test
    )

    metrics = {
        "accuracy": float(
            accuracy_score(
                y_test,
                predictions
            )
        ),
        "macro_f1": float(
            f1_score(
                y_test,
                predictions,
                average="macro",
                zero_division=0
            )
        ),
        "test_samples": int(
            len(y_test)
        )
    }

    model_path = (
        MODEL_DIR
        / "sentiment_analysis"
        / "sentiment_classifier.joblib"
    )

    save_model(
        model_path,
        model
    )

    report = {
        "model": "sentiment_analysis",
        "generated_at": now_iso(),
        "metrics": metrics,
        "classification_report": (
            classification_report(
                y_test,
                predictions,
                output_dict=True,
                zero_division=0
            )
        ),
        "label_source": label_source,
        "data_source": "data/feedback.csv",
        "unique_training_samples": len(x_train),
        "unique_test_samples": len(x_test),
        "limitations": [
            "Repeated identical review templates "
            "were removed before splitting.",
            "Synthetic text may not generalize "
            "to real customer language.",
            "Rating-derived labels, when used, "
            "are weak supervision rather than "
            "verified sentiment annotations."
        ],
        "artifact_path": str(
            model_path.relative_to(ROOT)
        )
    }

    save_json(
        REPORT_DIR
        / "sentiment_analysis"
        / "sentiment_report.json",
        report
    )

    print("Sentiment metrics:", metrics)

    return report


# ============================================================
# 5. TRAINING ORCHESTRATION
# ============================================================

TRAINERS = {
    "demand": train_demand,
    "stockout": train_stockout,
    "supplier": train_supplier,
    "sentiment": train_sentiment
}


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Train SupplyChainAI machine learning models"
        )
    )

    parser.add_argument(
        "--model",
        choices=["all", *TRAINERS],
        default="all"
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=SEED
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with an error if any selected model fails"
    )

    return parser.parse_args()


def main():
    args = parse_args()

    print("=" * 75)
    print("SUPPLYCHAINAI — MODEL TRAINING PIPELINE")
    print("=" * 75)

    print(f"Model selection: {args.model}")
    print(f"Random seed: {args.seed}")

    selected = (
        list(TRAINERS)
        if args.model == "all"
        else [args.model]
    )

    results = {}
    failed = []

    for name in selected:
        trainer = TRAINERS[name]

        try:
            report = trainer(
                args.seed
            )

            results[name] = {
                "status": "trained",
                "report": report
            }

        except Exception as exc:
            print(
                f"\n[ERROR] {name}: "
                f"{type(exc).__name__}: {exc}"
            )

            failed.append(name)

            results[name] = {
                "status": "failed",
                "error": str(exc)
            }

    summary = {
        "project": "SupplyChainAI",
        "generated_at": now_iso(),
        "seed": args.seed,
        "selected_models": selected,
        "trained_models": [
            name
            for name in selected
            if name not in failed
        ],
        "failed_models": failed,
        "results": results,
        "production_approved": False
    }

    summary_path = (
        REPORT_DIR
        / "training"
        / "training_summary.json"
    )

    save_json(
        summary_path,
        summary
    )

    print("\nTRAINING SUMMARY")

    for name in selected:
        print(
            f"{name:<12} "
            f"{results[name]['status']}"
        )

    print(
        f"\nSummary: {summary_path}"
    )

    if failed:
        print(
            "\nSome models could not be trained. "
            "Review the error messages above."
        )

        if args.strict:
            return 1

    print("\nTraining pipeline finished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
