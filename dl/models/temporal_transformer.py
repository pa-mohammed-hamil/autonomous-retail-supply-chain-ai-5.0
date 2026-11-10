"""Planned module: temporal transformer. Implementation pending."""

"""
ai/forecasting/temporal_transformer.py

Autonomous Retail Supply Chain AI 5.0

Temporal Transformer for retail demand forecasting.

Python 3.10+
Dependencies: torch, numpy

Architecture:
- Input projection
- Positional embeddings
- Transformer Encoder
- Multi-horizon prediction head

Forecasts future demand from historical demand.
"""

from __future__ import annotations

from pathlib import Path
import copy
import math

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset


class TemporalTransformerNetwork(nn.Module):

    def __init__(
        self,
        lookback: int,
        horizon: int,
        d_model: int = 64,
        nhead: int = 4,
        num_layers: int = 2,
        dropout: float = 0.1,
    ):
        super().__init__()

        if d_model % nhead != 0:
            raise ValueError(
                "d_model must be divisible by nhead"
            )

        self.lookback = lookback
        self.horizon = horizon

        self.input_projection = nn.Linear(
            1, d_model
        )

        self.position_embedding = nn.Parameter(
            torch.zeros(1, lookback, d_model)
        )

        nn.init.normal_(
            self.position_embedding,
            mean=0,
            std=0.02,
        )

        layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=d_model * 4,
            dropout=dropout,
            batch_first=True,
            activation="gelu",
        )

        self.encoder = nn.TransformerEncoder(
            layer,
            num_layers=num_layers,
            enable_nested_tensor=False,
        )

        self.head = nn.Sequential(
            nn.LayerNorm(d_model),
            nn.Linear(d_model, d_model),
            nn.GELU(),
            nn.Linear(d_model, horizon),
        )

    def forward(
        self,
        x: torch.Tensor,
    ) -> torch.Tensor:

        embedded = (
            self.input_projection(x)
            + self.position_embedding
        )

        encoded = self.encoder(embedded)

        return self.head(encoded[:, -1, :])


class TemporalTransformerForecaster:

    def __init__(
        self,
        lookback: int = 30,
        horizon: int = 7,
        d_model: int = 64,
        nhead: int = 4,
        num_layers: int = 2,
        dropout: float = 0.1,
        device: str | None = None,
    ):
        for name, value in (
            ("lookback", lookback),
            ("horizon", horizon),
            ("d_model", d_model),
            ("nhead", nhead),
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

        if (
            not isinstance(dropout, (int, float))
            or isinstance(dropout, bool)
            or not math.isfinite(dropout)
            or not 0 <= dropout < 1
        ):
            raise ValueError("Invalid dropout")

        if d_model % nhead:
            raise ValueError(
                "d_model must be divisible by nhead"
            )

        self.config = {
            "lookback": lookback,
            "horizon": horizon,
            "d_model": d_model,
            "nhead": nhead,
            "num_layers": num_layers,
            "dropout": float(dropout),
        }

        self.lookback = lookback
        self.horizon = horizon

        self.device = torch.device(
            device or (
                "cuda"
                if torch.cuda.is_available()
                else "cpu"
            )
        )

        self.model = TemporalTransformerNetwork(
            **self.config
        ).to(self.device)

        self.mean = None
        self.std = None
        self.trained = False

    @staticmethod
    def _validate_series(values) -> np.ndarray:

        if not isinstance(
            values, (list, tuple, np.ndarray)
        ):
            raise ValueError(
                "Expected a demand sequence"
            )

        if any(
            isinstance(v, (bool, str))
            for v in values
        ):
            raise ValueError(
                "Demand must be numeric"
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
                "Demand must be finite and nonnegative"
            )

        return data

    def _make_windows(
        self,
        data: np.ndarray,
        start_target: int,
        end_target: int,
    ):
        x, y = [], []

        # end_target is exclusive.
        # Each target window spans horizon days.
        for target in range(
            start_target,
            end_target - self.horizon + 1,
        ):
            x.append(
                data[
                    target - self.lookback:target
                ]
            )
            y.append(
                data[
                    target:target + self.horizon
                ]
            )

        if not x:
            raise ValueError(
                "Insufficient windows for forecasting"
            )

        return (
            torch.tensor(
                np.asarray(x)[:, :, None],
                dtype=torch.float32,
            ),
            torch.tensor(
                np.asarray(y),
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

        values = self._validate_series(
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

        if (
            isinstance(seed, bool)
            or not isinstance(seed, int)
        ):
            raise ValueError("seed must be an integer")

        if (
            not math.isfinite(learning_rate)
            or not 0 < learning_rate < 1
        ):
            raise ValueError(
                "Invalid learning_rate"
            )

        if (
            not math.isfinite(validation_fraction)
            or not 0 < validation_fraction < 0.5
        ):
            raise ValueError(
                "Invalid validation_fraction"
            )

        split = int(
            len(values) * (1 - validation_fraction)
        )

        if (
            split < self.lookback + self.horizon
            or len(values) - split < self.horizon
        ):
            raise ValueError(
                "Insufficient train/validation history"
            )

        torch.manual_seed(seed)

        training_values = values[:split]

        self.mean = float(
            training_values.mean()
        )

        self.std = float(
            training_values.std()
        )

        if self.std < 1e-8:
            self.std = 1.0

        normalized = (
            values - self.mean
        ) / self.std

        x_train, y_train = self._make_windows(
            normalized,
            self.lookback,
            split,
        )

        x_val, y_val = self._make_windows(
            normalized,
            split,
            len(values),
        )

        loader = DataLoader(
            TensorDataset(x_train, y_train),
            batch_size=batch_size,
            shuffle=True,
        )

        optimizer = torch.optim.AdamW(
            self.model.parameters(),
            lr=learning_rate,
        )

        loss_function = nn.MSELoss()

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

                loss = loss_function(
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
                validation_predictions = (
                    self.model(x_val)
                )

                val_loss = loss_function(
                    validation_predictions,
                    y_val,
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
    ) -> dict:

        if not self.trained:
            raise RuntimeError(
                "Train or load a model first"
            )

        values = self._validate_series(
            recent_demand
        )

        if len(values) < self.lookback:
            raise ValueError(
                "Insufficient recent demand history"
            )

        normalized = (
            values[-self.lookback:] - self.mean
        ) / self.std

        x = torch.tensor(
            normalized.reshape(
                1, self.lookback, 1
            ),
            dtype=torch.float32,
            device=self.device,
        )

        self.model.eval()

        with torch.inference_mode():
            predicted = self.model(x)[0]

        output = (
            predicted.cpu().numpy()
            * self.std
            + self.mean
        )

        output = np.maximum(output, 0)

        if not np.all(np.isfinite(output)):
            raise RuntimeError(
                "Nonfinite forecast generated"
            )

        forecasts = [
            round(float(value), 2)
            for value in output
        ]

        return {
            "model": "TemporalTransformer",
            "forecast_method": "direct_multi_horizon",
            "horizon_days": self.horizon,
            "forecast_units": forecasts,
            "total_forecast_units": round(
                sum(forecasts), 2
            ),
            "simulation_only": True,
        }

    def save(self, checkpoint_path: str) -> None:

        if not self.trained:
            raise RuntimeError(
                "No trained model to save"
            )

        path = Path(checkpoint_path)
        path.parent.mkdir(
            parents=True, exist_ok=True
        )

        torch.save({
            "config": self.config,
            "model_state": self.model.state_dict(),
            "mean": self.mean,
            "std": self.std,
        }, path)

    @classmethod
    def load(
        cls,
        checkpoint_path: str,
        device: str | None = None,
    ) -> "TemporalTransformerForecaster":

        # Load only trusted model checkpoints.
        checkpoint = torch.load(
            checkpoint_path,
            map_location="cpu",
            weights_only=True,
        )

        forecaster = cls(
            **checkpoint["config"],
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

        if (
            not math.isfinite(forecaster.mean)
            or not math.isfinite(forecaster.std)
            or forecaster.std <= 0
        ):
            raise ValueError(
                "Invalid checkpoint normalization"
            )

        forecaster.model.eval()
        forecaster.trained = True

        return forecaster
