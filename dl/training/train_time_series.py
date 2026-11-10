"""Planned module: train time series. Implementation pending."""

"""
ai/training/train_time_series.py

Train LSTM and Temporal Transformer demand models.

CSV columns:
    date,product_id,units_sold

One daily observation per product.

Run:
python -m ai.training.train_time_series \
    --csv datasets/sales/daily_sales.csv \
    --product-id SKU-1001
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from ai.forecasting.lstm_forecaster import (
    LSTMDemandForecaster,
)

from ai.forecasting.temporal_transformer import (
    TemporalTransformerForecaster,
)


def load_sales(
    csv_path: str,
    product_id: str,
) -> tuple[list[str], np.ndarray]:

    path = Path(csv_path)

    if not path.is_file():
        raise FileNotFoundError(path)

    df = pd.read_csv(path)

    required = {
        "date",
        "product_id",
        "units_sold",
    }

    if not required.issubset(df.columns):
        raise ValueError(
            f"CSV requires columns: {required}"
        )

    df = df[
        df["product_id"] == product_id
    ].copy()

    if df.empty:
        raise ValueError(
            f"No sales data for {product_id}"
        )

    df["date"] = pd.to_datetime(
        df["date"],
        errors="raise",
    )

    df["units_sold"] = pd.to_numeric(
        df["units_sold"],
        errors="raise",
    )

    if (
        df["units_sold"].isna().any()
        or not np.isfinite(
            df["units_sold"].to_numpy()
        ).all()
        or (df["units_sold"] < 0).any()
    ):
        raise ValueError(
            "Sales must be finite and nonnegative"
        )

    df = df.sort_values("date")

    if df["date"].duplicated().any():
        raise ValueError(
            "Duplicate product-date observations"
        )

    expected_dates = pd.date_range(
        start=df["date"].min(),
        end=df["date"].max(),
        freq="D",
    )

    if len(expected_dates) != len(df):
        raise ValueError(
            "Missing daily observations; "
            "resolve gaps before training"
        )

    return (
        df["date"].dt.strftime(
            "%Y-%m-%d"
        ).tolist(),
        df["units_sold"].to_numpy(
            dtype=np.float64
        ),
    )


def forecast_metrics(
    actual,
    predicted,
) -> dict:

    y_true = np.asarray(
        actual, dtype=np.float64
    )
    y_pred = np.asarray(
        predicted, dtype=np.float64
    )

    if (
        y_true.shape != y_pred.shape
        or y_true.size == 0
        or not np.isfinite(y_pred).all()
    ):
        raise ValueError(
            "Invalid forecast evaluation arrays"
        )

    error = y_pred - y_true

    mae = float(
        np.mean(np.abs(error))
    )

    rmse = float(
        np.sqrt(np.mean(error ** 2))
    )

    denominator = float(
        np.sum(np.abs(y_true))
    )

    wape = (
        float(
            np.sum(np.abs(error))
            / denominator * 100
        )
        if denominator > 0
        else None
    )

    return {
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "wape_percent": (
            round(wape, 4)
            if wape is not None else None
        ),
        "bias": round(
            float(np.mean(error)),
            4,
        ),
    }


def seasonal_naive(
    history,
    horizon: int,
    season_length: int = 7,
) -> list[float]:

    values = list(history)

    if len(values) < season_length:
        raise ValueError(
            "Insufficient seasonal history"
        )

    season = values[-season_length:]

    return [
        float(season[i % season_length])
        for i in range(horizon)
    ]


def evaluate_rolling(
    model,
    series: np.ndarray,
    test_start: int,
    horizon: int,
    stride: int,
    model_name: str,
) -> dict:

    all_actual = []
    all_predicted = []
    origin_count = 0

    for origin in range(
        test_start,
        len(series) - horizon + 1,
        stride,
    ):
        history = series[:origin]
        actual = series[
            origin:origin + horizon
        ]

        if model_name == "seasonal_naive":
            prediction = seasonal_naive(
                history, horizon
            )

        elif model_name == "lstm":
            prediction = model.forecast(
                recent_demand=history[-model.lookback:],
                horizon=horizon,
            )["forecast_units"]

        elif model_name == "transformer":
            prediction = model.forecast(
                recent_demand=history[-model.lookback:]
            )["forecast_units"]

        else:
            raise ValueError("Unknown model")

        all_actual.extend(
            actual.tolist()
        )
        all_predicted.extend(
            prediction
        )

        origin_count += 1

    if not origin_count:
        raise ValueError(
            "Test period too short for rolling evaluation"
        )

    return {
        "model": model_name,
        "forecast_origins": origin_count,
        "evaluated_predictions": len(all_actual),
        "metrics": forecast_metrics(
            all_actual,
            all_predicted,
        ),
    }


def train_time_series(
    csv_path: str,
    product_id: str,
    lookback: int = 30,
    horizon: int = 7,
    epochs: int = 50,
    batch_size: int = 32,
    output_dir: str = "models",
    report_dir: str = "reports",
) -> dict:

    for name, value in (
        ("lookback", lookback),
        ("horizon", horizon),
        ("epochs", epochs),
        ("batch_size", batch_size),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
        ):
            raise ValueError(
                f"{name} must be positive"
            )

    dates, values = load_sales(
        csv_path, product_id
    )

    n = len(values)

    train_val_end = int(n * 0.8)
    test_start = train_val_end

    train_val = values[:train_val_end]

    # The model classes each reserve a chronological
    # validation tail within train_val.
    min_required = max(
        lookback + horizon + 1,
        60,
    )

    if (
        len(train_val) < min_required
        or len(values) - test_start < horizon
    ):
        raise ValueError(
            "Insufficient data for training and test"
        )

    lstm = LSTMDemandForecaster(
        lookback=lookback,
        hidden_size=64,
        num_layers=2,
    )

    lstm_history = lstm.fit(
        train_val.tolist(),
        epochs=epochs,
        batch_size=batch_size,
        patience=10,
    )

    transformer = TemporalTransformerForecaster(
        lookback=lookback,
        horizon=horizon,
        d_model=64,
        nhead=4,
        num_layers=2,
    )

    transformer_history = transformer.fit(
        train_val.tolist(),
        epochs=epochs,
        batch_size=batch_size,
        patience=10,
    )

    # Non-overlapping forecast horizons.
    # All models use the same forecast origins.
    results = [
        evaluate_rolling(
            None,
            values,
            test_start,
            horizon,
            stride=horizon,
            model_name="seasonal_naive",
        ),
        evaluate_rolling(
            lstm,
            values,
            test_start,
            horizon,
            stride=horizon,
            model_name="lstm",
        ),
        evaluate_rolling(
            transformer,
            values,
            test_start,
            horizon,
            stride=horizon,
            model_name="transformer",
        ),
    ]

    # Rank by MAE on the held-out test period.
    # For strict model selection, choose on validation
    # and reserve test for a single final assessment.
    ranked = sorted(
        results,
        key=lambda item: (
            item["metrics"]["mae"],
            item["metrics"]["rmse"],
        ),
    )

    model_dir = Path(output_dir)
    model_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    safe_product_id = "".join(
        char
        if char.isalnum() or char in "-_"
        else "_"
        for char in product_id
    )

    lstm_path = model_dir / (
        f"{safe_product_id}_demand_lstm.pt"
    )

    transformer_path = model_dir / (
        f"{safe_product_id}_temporal_transformer.pt"
    )

    lstm.save(str(lstm_path))
    transformer.save(str(transformer_path))

    report = {
        "product_id": product_id,
        "observations": n,
        "train_validation_end": dates[
            train_val_end - 1
        ],
        "test_start": dates[test_start],
        "lookback": lookback,
        "horizon": horizon,
        "results": results,
        "lowest_test_mae_model": ranked[0]["model"],
        "lstm_checkpoint": str(lstm_path),
        "transformer_checkpoint": str(
            transformer_path
        ),
        "lstm_training_history": lstm_history,
        "transformer_training_history": (
            transformer_history
        ),
        "evaluation_note": (
            "Models trained on first 80% of history. "
            "Rolling test forecasts use actual historical "
            "observations available at each origin."
        ),
    }

    destination = Path(report_dir)
    destination.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path = destination / (
        f"{safe_product_id}_time_series_metrics.json"
    )

    report_path.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    return report


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--csv",
        default="datasets/sales/daily_sales.csv",
    )
    parser.add_argument(
        "--product-id",
        required=True,
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=30,
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=7,
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=50,
    )

    args = parser.parse_args()

    report = train_time_series(
        csv_path=args.csv,
        product_id=args.product_id,
        lookback=args.lookback,
        horizon=args.horizon,
        epochs=args.epochs,
    )

    print(json.dumps({
        "product_id": report["product_id"],
        "results": report["results"],
        "lowest_test_mae_model": (
            report["lowest_test_mae_model"]
        ),
    }, indent=2))


if __name__ == "__main__":
    main()
