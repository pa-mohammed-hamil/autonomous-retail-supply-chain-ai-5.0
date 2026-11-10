"""Planned module: drift detection. Implementation pending."""

"""
ai/evaluation/drift_detection.py

Autonomous Retail Supply Chain AI 5.0

Data Drift Detection Engine

Features:
- Numeric feature drift
- Categorical feature drift
- Population Stability Index (PSI)
- Kolmogorov-Smirnov test
- Jensen-Shannon divergence
- Missing-value drift
- Drift reports
- CSV/JSON export

Install:
    pip install numpy pandas scipy
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from scipy.spatial.distance import (
    jensenshannon,
)
from scipy.stats import ks_2samp


class RetailDriftDetector:

    def __init__(
        self,
        psi_threshold=0.20,
        js_threshold=0.10,
        ks_alpha=0.01,
        n_bins=10,
    ):
        if psi_threshold <= 0:
            raise ValueError(
                "PSI threshold must be positive"
            )

        if not 0 <= js_threshold <= 1:
            raise ValueError(
                "JS threshold must be 0-1"
            )

        if not 0 < ks_alpha < 1:
            raise ValueError(
                "KS alpha must be 0-1"
            )

        if n_bins < 2:
            raise ValueError(
                "At least two bins required"
            )

        self.psi_threshold = psi_threshold
        self.js_threshold = js_threshold
        self.ks_alpha = ks_alpha
        self.n_bins = n_bins

        self.report = None

    @staticmethod
    def _psi(
        reference,
        current,
        n_bins,
    ):
        reference = np.asarray(
            reference,
            dtype=float,
        )

        current = np.asarray(
            current,
            dtype=float,
        )

        if (
            len(reference) == 0
            or len(current) == 0
        ):
            return None

        edges = np.unique(
            np.quantile(
                reference,
                np.linspace(
                    0, 1, n_bins + 1
                ),
            )
        )

        if len(edges) < 2:
            # Constant reference feature.
            return (
                0.0
                if np.all(
                    current == reference[0]
                )
                else float("inf")
            )

        edges[0] = -np.inf
        edges[-1] = np.inf

        ref_counts, _ = np.histogram(
            reference,
            bins=edges,
        )

        cur_counts, _ = np.histogram(
            current,
            bins=edges,
        )

        epsilon = 1e-6

        ref_p = (
            ref_counts + epsilon
        ) / (
            ref_counts.sum()
            + epsilon * len(ref_counts)
        )

        cur_p = (
            cur_counts + epsilon
        ) / (
            cur_counts.sum()
            + epsilon * len(cur_counts)
        )

        return float(
            np.sum(
                (cur_p - ref_p)
                * np.log(
                    cur_p / ref_p
                )
            )
        )

    @staticmethod
    def _categorical_js(
        reference,
        current,
    ):
        ref = (
            reference.fillna(
                "__missing__"
            ).astype(str)
        )

        cur = (
            current.fillna(
                "__missing__"
            ).astype(str)
        )

        categories = sorted(
            set(ref)
            | set(cur)
        )

        ref_freq = (
            ref.value_counts(
                normalize=True
            )
            .reindex(
                categories,
                fill_value=0,
            )
            .to_numpy()
        )

        cur_freq = (
            cur.value_counts(
                normalize=True
            )
            .reindex(
                categories,
                fill_value=0,
            )
            .to_numpy()
        )

        # scipy returns JS distance;
        # square it to obtain divergence.
        return float(
            jensenshannon(
                ref_freq,
                cur_freq,
                base=2,
            ) ** 2
        )

    def detect(
        self,
        reference,
        current,
        numeric_features=None,
        categorical_features=None,
    ):
        ref = reference.copy()
        cur = current.copy()

        numeric_features = (
            numeric_features or []
        )

        categorical_features = (
            categorical_features or []
        )

        features = (
            numeric_features
            + categorical_features
        )

        if len(features) != len(set(features)):
            raise ValueError(
                "Duplicate feature names"
            )

        missing = [
            feature
            for feature in features
            if (
                feature not in ref
                or feature not in cur
            )
        ]

        if missing:
            raise ValueError(
                f"Missing features: {missing}"
            )

        if ref.empty or cur.empty:
            raise ValueError(
                "Reference/current data is empty"
            )

        rows = []

        for feature in numeric_features:
            ref_values = pd.to_numeric(
                ref[feature],
                errors="coerce",
            )

            cur_values = pd.to_numeric(
                cur[feature],
                errors="coerce",
            )

            if (
                np.isinf(
                    ref_values.to_numpy(
                        dtype=float
                    )
                ).any()
                or np.isinf(
                    cur_values.to_numpy(
                        dtype=float
                    )
                ).any()
            ):
                raise ValueError(
                    f"Infinite values in {feature}"
                )

            ref_missing = float(
                ref_values.isna().mean()
            )

            cur_missing = float(
                cur_values.isna().mean()
            )

            ref_clean = (
                ref_values.dropna()
            )

            cur_clean = (
                cur_values.dropna()
            )

            if (
                ref_clean.empty
                or cur_clean.empty
            ):
                psi = None
                ks_stat = None
                ks_pvalue = None
                drift = True
            else:
                psi = self._psi(
                    ref_clean,
                    cur_clean,
                    self.n_bins,
                )

                ks = ks_2samp(
                    ref_clean,
                    cur_clean,
                )

                ks_stat = float(
                    ks.statistic
                )

                ks_pvalue = float(
                    ks.pvalue
                )

                drift = bool(
                    psi >= self.psi_threshold
                    or ks_pvalue < self.ks_alpha
                )

            missing_shift = abs(
                cur_missing - ref_missing
            )

            if missing_shift >= 0.10:
                drift = True

            rows.append({
                "feature": feature,
                "feature_type": "numeric",
                "psi": psi,
                "ks_statistic": ks_stat,
                "ks_pvalue": ks_pvalue,
                "js_divergence": None,
                "reference_missing_rate": (
                    ref_missing
                ),
                "current_missing_rate": (
                    cur_missing
                ),
                "missing_rate_shift": (
                    missing_shift
                ),
                "drift_detected": drift,
            })

        for feature in categorical_features:
            js = self._categorical_js(
                ref[feature],
                cur[feature],
            )

            ref_missing = float(
                ref[feature].isna().mean()
            )

            cur_missing = float(
                cur[feature].isna().mean()
            )

            missing_shift = abs(
                cur_missing - ref_missing
            )

            drift = bool(
                js >= self.js_threshold
                or missing_shift >= 0.10
            )

            rows.append({
                "feature": feature,
                "feature_type": "categorical",
                "psi": None,
                "ks_statistic": None,
                "ks_pvalue": None,
                "js_divergence": js,
                "reference_missing_rate": (
                    ref_missing
                ),
                "current_missing_rate": (
                    cur_missing
                ),
                "missing_rate_shift": (
                    missing_shift
                ),
                "drift_detected": drift,
            })

        self.report = pd.DataFrame(
            rows
        )

        return self.report

    def summary(self):
        if self.report is None:
            raise RuntimeError(
                "Run drift detection first"
            )

        total = len(
            self.report
        )

        drifted = int(
            self.report[
                "drift_detected"
            ].sum()
        )

        return {
            "total_features": total,
            "drifted_features": drifted,
            "drift_percentage": (
                100 * drifted / total
                if total > 0
                else 0.0
            ),
            "drift_detected": (
                drifted > 0
            ),
        }

    def save(
        self,
        output_dir="reports/drift",
    ):
        if self.report is None:
            raise RuntimeError(
                "Run drift detection first"
            )

        directory = Path(
            output_dir
        )

        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.report.to_csv(
            directory
            / "feature_drift.csv",
            index=False,
        )

        (
            directory
            / "drift_summary.json"
        ).write_text(
            json.dumps(
                self.summary(),
                indent=2,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    rng = np.random.default_rng(42)

    reference = pd.DataFrame({
        "daily_demand": rng.normal(
            100, 15, 1000
        ),
        "lead_time_days": rng.normal(
            5, 1, 1000
        ),
        "supplier_region": rng.choice(
            ["North", "South", "West"],
            1000,
            p=[0.3, 0.5, 0.2],
        ),
    })

    current = pd.DataFrame({
        "daily_demand": rng.normal(
            130, 20, 500
        ),
        "lead_time_days": rng.normal(
            5.2, 1.2, 500
        ),
        "supplier_region": rng.choice(
            ["North", "South", "West"],
            500,
            p=[0.5, 0.2, 0.3],
        ),
    })

    detector = RetailDriftDetector()

    report = detector.detect(
        reference,
        current,
        numeric_features=[
            "daily_demand",
            "lead_time_days",
        ],
        categorical_features=[
            "supplier_region",
        ],
    )

    print("\nDrift report:")
    print(
        report.to_string(
            index=False
        )
    )

    print("\nSummary:")
    print(
        json.dumps(
            detector.summary(),
            indent=2,
        )
    )

    detector.save()
