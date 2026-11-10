"""Planned module: lstm forecaster. Implementation pending."""

"""
ai/forecasting/lstm_forecaster.py

Retail daily demand forecasting with PyTorch LSTM.

Python 3.10+
Dependencies: torch, numpy

Univariate time-series forecasting.

Important:
- Use chronological data.
- Zero-sales days may represent stockouts.
- Evaluate against a seasonal naive baseline.
"""

from __future__ import annotations

from pathlib import Path
import copy
import math

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset


class LSTMNetwork(nn.Module):

    def __init__(
        self,
        hidden_size: int = 64,
        num_layers: int = 2,
    ):
        super().__init__()

        self.lstm = nn.LSTM(
            input_size=1,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
        )

        self.output = nn.Linear(
            hidden_size, 1
        )

    def forward(self, x: torch.Tensor):
        output, _ = self.lstm(x)
        return self.output(output[:, -1, :])


class LSTMDemandForecaster:

    def __init__(
        self,
        lookback: int = 30,
        hidden_size: int = 64,
        num_layers: int = 2,
        device: str | None = None,
    ):
        for name, value in (
            ("lookback", lookback),
            ("hidden_size", hidden_size),
            ("num_layers", num_layers),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                raise ValueError(
                    f"{name} must be positive"
                )

        self.lookback = lookback
        self.hidden_size = hidden_size
        self.num_layers = num_layers

        self.device = torch.device(
            device or (
                "cuda"
                if torch.cuda.is_available()
                else "cpu"
            )
        )

        self.model = LSTMNetwork(
            hidden_size=hidden_size,
            num_layers=num_layers,
        ).to(self.device)

        self.mean = None
        self.std = None
        self.trained = False

    @staticmethod
    def _series(values) -> np.ndarray:
        if not isinstance(values, (list, tuple, np.ndarray)):
            raise ValueError("Expected a sequence")

        if any(
            isinstance(value, (bool, str))
            for value in values
        ):
            raise ValueError(
                "Demand must contain numeric values"
            )

        data = np.asarray(
            values, dtype=np.float64
        )

        if (
            data.ndim != 1
            or not np.all(np.isfinite(data))
            or np.any(data < 0)
        ):
            raise ValueError(
                "Demand must be a nonnegative finite series"
            )

        return data

    def _windows(
        self,
        normalized: np.ndarray,
        target_start: int,
        target_end: int,
    ):
        x, y = [], []

        for target in range(
            target_start, target_end
        ):
            x.append(
                normalized[
                    target - self.lookback:target
                ]
            )
            y.append(normalized[target])

        return (
            torch.tensor(
                np.asarray(x)[:, :, None],
                dtype=torch.float32,
            ),
            torch.tensor(
                np.asarray(y)[:, None],
                dtype=torch.float32,
            ),
        )

    def fit(
        self,
        historical_demand,
        epochs: int = 100,
        batch_size: int = 32,
        learning_rate: float = 0.001,
        validation_fraction: float = 0.2,
        patience: int = 10,
        seed: int = 42,
    ) -> list[dict]:

        values = self._series(
            historical_demand
        )

        for name, value in (
            ("epochs", epochs),
            ("batch_size", batch_size),
            ("patience", patience),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                raise ValueError(
                    f"{name} must be positive"
                )

        if not 0 < learning_rate < 1:
            raise ValueError("Invalid learning rate")

        if not 0 < validation_fraction < 0.5:
            raise ValueError(
                "validation_fraction must be (0, 0.5)"
            )

        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("seed must be an integer")

        torch.manual_seed(seed)

        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)

        split = int(
            len(values) * (1 - validation_fraction)
        )

        if (
            split <= self.lookback
            or len(values) - split < 1
        ):
            raise ValueError(
                "Insufficient chronological training "
                "and validation observations"
            )

        # Fit scaler on training observations only.
        training_values = values[:split]

        self.mean = float(
            np.mean(training_values)
        )

        self.std = float(
            np.std(training_values)
        )

        if self.std < 1e-8:
            self.std = 1.0

        normalized = (
            values - self.mean
        ) / self.std

        x_train, y_train = self._windows(
            normalized,
            self.lookback,
            split,
        )

        # Validation targets are future observations.
        # Historical context may include train values.
        x_val, y_val = self._windows(
            normalized,
            split,
            len(values),
        )

        loader = DataLoader(
            TensorDataset(x_train, y_train),
            batch_size=batch_size,
            shuffle=True,
        )

        optimizer = torch.optim.Adam(
            self.model.parameters(),
            lr=learning_rate,
        )

        criterion = nn.MSELoss()

        best_loss = math.inf
        best_state = None
        stale_epochs = 0
        history = []

        x_val = x_val.to(self.device)
        y_val = y_val.to(self.device)

        for epoch in range(epochs):
            self.model.train()

            total_loss = 0.0
            count = 0

            for x_batch, y_batch in loader:
                x_batch = x_batch.to(
                    self.device
                )
                y_batch = y_batch.to(
                    self.device
                )

                optimizer.zero_grad()

                predictions = self.model(
                    x_batch
                )

                loss = criterion(
                    predictions, y_batch
                )

                loss.backward()

                nn.utils.clip_grad_norm_(
                    self.model.parameters(),
                    max_norm=1.0,
                )

                optimizer.step()

                total_loss += (
                    loss.item() * len(x_batch)
                )
                count += len(x_batch)

            self.model.eval()

            with torch.inference_mode():
                val_predictions = self.model(
                    x_val
                )

                val_loss = criterion(
                    val_predictions, y_val
                ).item()

            history.append({
                "epoch": epoch + 1,
                "train_mse_normalized": round(
                    total_loss / count, 6
                ),
                "val_mse_normalized": round(
                    val_loss, 6
                ),
            })

            if val_loss < best_loss - 1e-8:
                best_loss = val_loss
                best_state = copy.deepcopy(
                    self.model.state_dict()
                )
                stale_epochs = 0
            else:
                stale_epochs += 1

            if stale_epochs >= patience:
                break

        if best_state is not None:
            self.model.load_state_dict(
                best_state
            )

        self.model.eval()
        self.trained = True

        return history

    def forecast(
        self,
        recent_demand,
        horizon: int = 7,
    ) -> dict:

        if not self.trained:
            raise RuntimeError(
                "Train or load a model first"
            )

        if (
            isinstance(horizon, bool)
            or not isinstance(horizon, int)
            or not 1 <= horizon <= 365
        ):
            raise ValueError(
                "horizon must be 1 to 365"
            )

        values = self._series(recent_demand)

        if len(values) < self.lookback:
            raise ValueError(
                "Insufficient recent history"
            )

        window = (
            (values[-self.lookback:] - self.mean)
            / self.std
        ).astype(np.float32)

        predictions = []
        self.model.eval()

        with torch.inference_mode():
            for _ in range(horizon):
                tensor = torch.tensor(
                    window.reshape(
                        1, self.lookback, 1
                    ),
                    dtype=torch.float32,
                    device=self.device,
                )

                normalized_prediction = float(
                    self.model(tensor).item()
                )

                predicted = max(
                    0.0,
                    normalized_prediction * self.std
                    + self.mean,
                )

                if not math.isfinite(predicted):
                    raise RuntimeError(
                        "Nonfinite model prediction"
                    )

                predictions.append(
                    round(predicted, 2)
                )

                # Recursive multi-step forecast.
                normalized_next = (
                    predicted - self.mean
                ) / self.std

                window = np.concatenate([
                    window[1:],
                    np.array(
                        [normalized_next],
                        dtype=np.float32,
                    ),
                ])

        return {
            "horizon_days": horizon,
            "forecast_units": predictions,
            "total_forecast_units": round(
                sum(predictions), 2
            ),
            "model": "LSTM",
            "forecast_method": "recursive",
            "simulation_only": True,
        }

    def save(self, path: str) -> None:
        if not self.trained:
            raise RuntimeError(
                "No trained model to save"
            )

        target = Path(path)
        target.parent.mkdir(
            parents=True, exist_ok=True
        )

        torch.save({
            "model_state": self.model.state_dict(),
            "lookback": self.lookback,
            "hidden_size": self.hidden_size,
            "num_layers": self.num_layers,
            "mean": self.mean,
            "std": self.std,
        }, target)

    @classmethod
    def load(
        cls,
        path: str,
        device: str | None = None,
    ) -> "LSTMDemandForecaster":

        # Load trusted checkpoints only.
        checkpoint = torch.load(
            path,
            map_location="cpu",
            weights_only=True,
        )

        forecaster = cls(
            lookback=checkpoint["lookback"],
            hidden_size=checkpoint["hidden_size"],
            num_layers=checkpoint["num_layers"],
            device=device,
        )

        forecaster.model.load_state_dict(
            checkpoint["model_state"]
        )

        forecaster.mean = float(
            checkpoint["mean"]
        )
        forecaster.std = float(
            checkpoint["std"]
        )

        forecaster.model.eval()
        forecaster.trained = True

        return forecaster
