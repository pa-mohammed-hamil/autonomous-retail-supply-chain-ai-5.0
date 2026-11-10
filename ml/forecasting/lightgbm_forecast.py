"""Planned module: lightgbm forecast. Implementation pending."""

"""
ai/forecasting/lightgbm_forecast.py

Autonomous Retail Supply Chain AI 5.0

LightGBM Demand Forecasting

Capabilities:
- Daily demand forecasting
- Lag and rolling features
- Calendar seasonality
- Optional price and promotion features
- Recursive multi-step forecasting
- Time-series backtesting
- Model save/load
- MAE, RMSE, WAPE
- CSV/JSON export

Dependencies:
pip install lightgbm numpy pandas joblib

Python 3.10+
"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor


class LightGBMForecaster:

    def __init__(
        self,
        lags=(1, 7, 14),
        windows=(7, 14),
        n_estimators=200,
        learning_rate=0.05,
        num_leaves=15,
        random_state=42,
    ):
        self.lags = tuple(sorted(set(lags)))
        self.windows = tuple(sorted(set(windows)))

        if (
            not self.lags
            or not self.windows
            or any(
                isinstance(v, bool)
                or not isinstance(v, int)
                or v < 1
                for v in self.lags + self.windows
            )
        ):
            raise ValueError(
                "Lags/windows must be positive integers"
            )

        if (
            not isinstance(n_estimators, int)
            or n_estimators < 1
            or not 0 < learning_rate <= 1
            or not isinstance(num_leaves, int)
            or num_leaves < 2
        ):
            raise ValueError(
                "Invalid LightGBM hyperparameters"
            )

        self.params = {
            "n_estimators": n_estimators,
            "learning_rate": learning_rate,
            "num_leaves": num_leaves,
            "random_state": random_state,
            "verbosity": -1,
            "n_jobs": 1,
        }

        self.model = None
        self.history = None
        self.last_date = None
        self.feature_columns = None
        self.use_exogenous = False

    @staticmethod
    def _validate_frame(frame, require_demand=True):
        required = {"date"}

        if require_demand:
            required.add("demand")

        missing = required - set(frame.columns)

        if missing:
            raise ValueError(
                f"Missing columns: {sorted(missing)}"
            )

        df = frame.copy()
        df["date"] = pd.to_datetime(
            df["date"], errors="raise"
        ).dt.normalize()

        if df["date"].duplicated().any():
            raise ValueError("Duplicate dates")

        df = df.sort_values("date").reset_index(
            drop=True
        )

        if require_demand:
            df["demand"] = pd.to_numeric(
                df["demand"], errors="raise"
            )

            if (
                not np.isfinite(df["demand"]).all()
                or (df["demand"] < 0).any()
            ):
                raise ValueError(
                    "Demand must be finite and nonnegative"
                )

        for column in ("price", "promotion"):
            if column in df:
                df[column] = pd.to_numeric(
                    df[column], errors="raise"
                )

                if not np.isfinite(df[column]).all():
                    raise ValueError(
                        f"{column} must be finite"
                    )

        if "price" in df and (
            df["price"] <= 0
        ).any():
            raise ValueError(
                "Prices must be positive"
            )

        if "promotion" in df and (
            ~df["promotion"].isin([0, 1])
        ).any():
            raise ValueError(
                "Promotion must be 0 or 1"
            )

        if len(df) > 1:
            gaps = df["date"].diff().dropna()

            if not (
                gaps == pd.Timedelta(days=1)
            ).all():
                raise ValueError(
                    "Daily series must have no missing dates"
                )

        return df

    @staticmethod
    def _calendar(day):
        day = pd.Timestamp(day)

        return {
            "day_of_week": day.dayofweek,
            "month": day.month,
            "day_of_year": day.dayofyear,
            "is_weekend": int(
                day.dayofweek >= 5
            ),
            "weekday_sin": math.sin(
                2 * math.pi
                * day.dayofweek / 7
            ),
            "weekday_cos": math.cos(
                2 * math.pi
                * day.dayofweek / 7
            ),
            "month_sin": math.sin(
                2 * math.pi
                * (day.month - 1) / 12
            ),
            "month_cos": math.cos(
                2 * math.pi
                * (day.month - 1) / 12
            ),
        }

    def _features(
        self,
        history,
        day,
        price=None,
        promotion=None,
    ):
        features = self._calendar(day)

        for lag in self.lags:
            features[f"lag_{lag}"] = (
                float(history[-lag])
            )

        for window in self.windows:
            recent = np.asarray(
                history[-window:],
                dtype=float,
            )

            features[
                f"rolling_mean_{window}"
            ] = float(recent.mean())

            features[
                f"rolling_std_{window}"
            ] = float(recent.std())

        if self.use_exogenous:
            if price is None or promotion is None:
                raise ValueError(
                    "Future price and promotion "
                    "are required for this model"
                )

            features["price"] = float(price)
            features["promotion"] = float(promotion)

        return features

    def fit(self, frame):
        df = self._validate_frame(frame)

        minimum_history = max(
            *self.lags,
            *self.windows,
        )

        if len(df) < minimum_history + 10:
            raise ValueError(
                "Insufficient training history"
            )

        has_price = "price" in df
        has_promotion = "promotion" in df

        if has_price != has_promotion:
            raise ValueError(
                "Provide both price and promotion "
                "or neither"
            )

        self.use_exogenous = has_price

        demand = df["demand"].to_numpy(
            dtype=float
        )

        feature_rows = []
        targets = []

        for index in range(
            minimum_history,
            len(df),
        ):
            row = df.iloc[index]

            features = self._features(
                demand[:index],
                row["date"],
                price=(
                    row["price"]
                    if has_price else None
                ),
                promotion=(
                    row["promotion"]
                    if has_promotion else None
                ),
            )

            feature_rows.append(features)
            targets.append(demand[index])

        X = pd.DataFrame(feature_rows)
        y = np.asarray(targets)

        self.feature_columns = list(X.columns)

        self.model = LGBMRegressor(
            **self.params
        )
        self.model.fit(X, y)

        self.history = demand.tolist()
        self.last_date = df["date"].iloc[-1]

        return self

    def predict(
        self,
        steps=7,
        future_features=None,
    ):
        if self.model is None:
            raise RuntimeError(
                "Fit or load the model first"
            )

        if (
            isinstance(steps, bool)
            or not isinstance(steps, int)
            or steps < 1
        ):
            raise ValueError(
                "steps must be positive"
            )

        future = None

        if self.use_exogenous:
            if future_features is None:
                raise ValueError(
                    "Future price and promotion "
                    "schedule is required"
                )

            future = self._validate_frame(
                pd.DataFrame(future_features),
                require_demand=False,
            )

            expected_dates = pd.date_range(
                self.last_date
                + pd.Timedelta(days=1),
                periods=steps,
                freq="D",
            )

            if (
                len(future) != steps
                or not future["date"].reset_index(
                    drop=True
                ).equals(
                    pd.Series(expected_dates)
                )
                or not {
                    "price", "promotion"
                }.issubset(future.columns)
            ):
                raise ValueError(
                    "Future features must contain "
                    "every forecast date with price "
                    "and promotion"
                )

        history = list(self.history)
        predictions = []

        for index in range(steps):
            day = (
                self.last_date
                + pd.Timedelta(days=index + 1)
            )

            row = (
                future.iloc[index]
                if future is not None
                else None
            )

            features = self._features(
                history,
                day,
                price=(
                    row["price"]
                    if row is not None else None
                ),
                promotion=(
                    row["promotion"]
                    if row is not None else None
                ),
            )

            X = pd.DataFrame(
                [features]
            )[self.feature_columns]

            prediction = float(
                self.model.predict(X)[0]
            )

            if not math.isfinite(prediction):
                raise RuntimeError(
                    "Nonfinite model prediction"
                )

            prediction = max(
                0.0, prediction
            )

            predictions.append(
                round(prediction, 4)
            )

            # Recursive forecast:
            # use prediction as future history.
            history.append(prediction)

        return predictions

    @staticmethod
    def metrics(actual, predicted):
        actual = np.asarray(
            actual, dtype=float
        )
        predicted = np.asarray(
            predicted, dtype=float
        )

        if (
            actual.shape != predicted.shape
            or actual.ndim != 1
            or len(actual) == 0
            or not np.isfinite(actual).all()
            or not np.isfinite(predicted).all()
        ):
            raise ValueError(
                "Invalid evaluation arrays"
            )

        error = actual - predicted

        denominator = np.abs(actual).sum()

        return {
            "mae": round(
                float(np.abs(error).mean()), 4
            ),
            "rmse": round(
                float(np.sqrt(
                    np.mean(error ** 2)
                )), 4
            ),
            "wape_percent": (
                round(
                    float(
                        np.abs(error).sum()
                        / denominator * 100
                    ),
                    4,
                )
                if denominator > 0
                else None
            ),
        }

    def backtest(
        self,
        frame,
        initial_train_size=42,
        horizon=7,
        step=7,
    ):
        df = self._validate_frame(frame)

        if any(
            isinstance(v, bool)
            or not isinstance(v, int)
            or v < 1
            for v in (
                initial_train_size,
                horizon,
                step,
            )
        ):
            raise ValueError(
                "Invalid backtest parameters"
            )

        if (
            initial_train_size + horizon
            > len(df)
        ):
            raise ValueError(
                "Insufficient backtest data"
            )

        folds = []
        all_actual = []
        all_predicted = []

        for end in range(
            initial_train_size,
            len(df) - horizon + 1,
            step,
        ):
            model = LightGBMForecaster(
                lags=self.lags,
                windows=self.windows,
                **{
                    k: self.params[k]
                    for k in (
                        "n_estimators",
                        "learning_rate",
                        "num_leaves",
                        "random_state",
                    )
                },
            )

            model.fit(df.iloc[:end])

            future = None

            if model.use_exogenous:
                future = df.iloc[
                    end:end + horizon
                ][[
                    "date", "price", "promotion"
                ]]

            predicted = model.predict(
                steps=horizon,
                future_features=future,
            )

            actual = df.iloc[
                end:end + horizon
            ]["demand"].tolist()

            folds.append({
                "train_end_index": end,
                "actual": actual,
                "predicted": predicted,
                "metrics": self.metrics(
                    actual, predicted
                ),
            })

            all_actual.extend(actual)
            all_predicted.extend(predicted)

        return {
            "model": "lightgbm",
            "fold_count": len(folds),
            "overall_metrics": self.metrics(
                all_actual, all_predicted
            ),
            "folds": folds,
        }

    def save_model(self, path):
        if self.model is None:
            raise RuntimeError(
                "No trained model to save"
            )

        output = Path(path)
        output.parent.mkdir(
            parents=True, exist_ok=True
        )

        joblib.dump({
            "model": self.model,
            "history": self.history,
            "last_date": self.last_date,
            "lags": self.lags,
            "windows": self.windows,
            "params": self.params,
            "feature_columns": (
                self.feature_columns
            ),
            "use_exogenous": (
                self.use_exogenous
            ),
        }, output)

    @classmethod
    def load_model(cls, path):
        # Load only trusted artifacts.
        data = joblib.load(path)

        model = cls(
            lags=data["lags"],
            windows=data["windows"],
            n_estimators=data["params"][
                "n_estimators"
            ],
            learning_rate=data["params"][
                "learning_rate"
            ],
            num_leaves=data["params"][
                "num_leaves"
            ],
            random_state=data["params"][
                "random_state"
            ],
        )

        model.model = data["model"]
        model.history = data["history"]
        model.last_date = data["last_date"]
        model.feature_columns = data[
            "feature_columns"
        ]
        model.use_exogenous = data[
            "use_exogenous"
        ]

        return model

    @staticmethod
    def save_forecast(predictions, path):
        output = Path(path)
        output.parent.mkdir(
            parents=True, exist_ok=True
        )

        output.write_text(
            json.dumps({
                "model": "lightgbm",
                "forecast": predictions,
            }, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    dates = pd.date_range(
        "2026-01-01",
        periods=120,
        freq="D",
    )

    demand = [
        100
        + 15 * math.sin(
            2 * math.pi * i / 7
        )
        + i * 0.15
        for i in range(120)
    ]

    frame = pd.DataFrame({
        "date": dates,
        "demand": demand,
    })

    model = LightGBMForecaster()
    model.fit(frame)

    predictions = model.predict(
        steps=7
    )

    model.save_forecast(
        predictions,
        "data/forecasts/lightgbm_forecast.json",
    )

    model.save_model(
        "models/lightgbm_forecast.joblib"
    )

    print("Forecast:", predictions)
