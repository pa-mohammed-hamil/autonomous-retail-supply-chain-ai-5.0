"""Planned module: drift monitor. Implementation pending."""

"""
ai/mlops/drift_monitor.py

Numerical feature drift monitoring.

Features:
- Population Stability Index (PSI)
- Missing-value monitoring
- Fixed reference bins
- Drift alerts
- JSON report export

PSI is a descriptive drift heuristic,
not a statistical significance test.
"""

from __future__ import annotations

import json
import uuid

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


class DriftMonitor:

    def __init__(
        self,
        psi_warning: float = 0.10,
        psi_critical: float = 0.25,
        min_samples: int = 30,
        bins: int = 10,
        output_dir: str = (
            "storage/mlops/drift_reports"
        ),
    ):
        if not (
            0 < psi_warning < psi_critical
        ):
            raise ValueError(
                "Invalid PSI thresholds"
            )

        if min_samples < 2 or bins < 2:
            raise ValueError(
                "Invalid monitoring configuration"
            )

        self.psi_warning = psi_warning
        self.psi_critical = psi_critical
        self.min_samples = min_samples
        self.bins = bins
        self.output_dir = Path(output_dir)

    @staticmethod
    def _numeric_values(
        values: list,
    ) -> tuple[np.ndarray, float]:

        if not values:
            raise ValueError(
                "Feature values cannot be empty"
            )

        converted = []

        for value in values:
            if value is None:
                converted.append(np.nan)
            elif (
                isinstance(value, bool)
                or not isinstance(
                    value,
                    (int, float, np.number),
                )
            ):
                raise ValueError(
                    "Expected numeric values"
                )
            else:
                converted.append(float(value))

        array = np.asarray(
            converted,
            dtype=np.float64,
        )

        finite_mask = np.isfinite(array)

        missing_rate = float(
            1.0 - finite_mask.mean()
        )

        return array[finite_mask], missing_rate

    def _psi(
        self,
        reference: np.ndarray,
        current: np.ndarray,
    ) -> float:

        # Quantile-based reference bins.
        edges = np.quantile(
            reference,
            np.linspace(
                0,
                1,
                self.bins + 1,
            ),
        )

        # Remove duplicate edges.
        edges = np.unique(edges)

        if len(edges) < 2:
            # Constant reference distributions
            # need explicit change handling.
            return (
                0.0
                if np.all(
                    current == reference[0]
                )
                else float("inf")
            )

        # Include out-of-range observations
        # instead of silently discarding them.
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

        # Add smoothing to avoid log(0).
        epsilon = 1e-6

        ref_ratio = (
            ref_counts + epsilon
        ) / (
            ref_counts.sum()
            + epsilon * len(ref_counts)
        )

        cur_ratio = (
            cur_counts + epsilon
        ) / (
            cur_counts.sum()
            + epsilon * len(cur_counts)
        )

        psi = np.sum(
            (cur_ratio - ref_ratio)
            * np.log(
                cur_ratio / ref_ratio
            )
        )

        return float(psi)

    def evaluate_feature(
        self,
        feature_name: str,
        reference_values: list,
        current_values: list,
    ) -> dict[str, Any]:

        reference, ref_missing = (
            self._numeric_values(
                reference_values
            )
        )

        current, cur_missing = (
            self._numeric_values(
                current_values
            )
        )

        if (
            len(reference) < self.min_samples
            or len(current) < self.min_samples
        ):
            return {
                "feature": feature_name,
                "status": "insufficient_data",
                "reference_samples": len(reference),
                "current_samples": len(current),
                "reference_missing_rate": ref_missing,
                "current_missing_rate": cur_missing,
            }

        psi = self._psi(
            reference,
            current,
        )

        if psi >= self.psi_critical:
            status = "critical"
        elif psi >= self.psi_warning:
            status = "warning"
        else:
            status = "stable"

        return {
            "feature": feature_name,
            "status": status,
            "psi": (
                round(psi, 6)
                if np.isfinite(psi)
                else None
            ),
            "psi_infinite": bool(
                np.isinf(psi)
            ),
            "reference_samples": len(reference),
            "current_samples": len(current),
            "reference_mean": round(
                float(reference.mean()), 4
            ),
            "current_mean": round(
                float(current.mean()), 4
            ),
            "reference_missing_rate": round(
                ref_missing, 4
            ),
            "current_missing_rate": round(
                cur_missing, 4
            ),
        }

    def evaluate(
        self,
        reference_data: dict[str, list],
        current_data: dict[str, list],
        model_name: str,
        model_version: str,
        save_report: bool = True,
    ) -> dict:

        features = {}

        for name, reference in (
            reference_data.items()
        ):
            if name not in current_data:
                features[name] = {
                    "feature": name,
                    "status": "missing_feature",
                }
                continue

            features[name] = (
                self.evaluate_feature(
                    feature_name=name,
                    reference_values=reference,
                    current_values=current_data[name],
                )
            )

        statuses = {
            item["status"]
            for item in features.values()
        }

        if "critical" in statuses:
            overall = "critical"
        elif "warning" in statuses:
            overall = "warning"
        elif (
            "missing_feature" in statuses
            or "insufficient_data" in statuses
        ):
            overall = "incomplete"
        else:
            overall = "stable"

        report = {
            "report_id": uuid.uuid4().hex,
            "model_name": model_name,
            "model_version": model_version,
            "timestamp_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "overall_status": overall,
            "features": features,
            "automatic_retraining_allowed": False,
        }

        if save_report:
            self.output_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

            path = (
                self.output_dir
                / f"{report['report_id']}.json"
            )

            path.write_text(
                json.dumps(
                    report,
                    indent=2,
                    allow_nan=False,
                ),
                encoding="utf-8",
            )

            report["report_path"] = str(path)

        return report
