"""Planned module: cv metrics. Implementation pending."""

"""
ai/computer_vision/cv_metrics.py

Runtime computer vision metrics.

Tracks:
- Frames processed
- Processing latency
- FPS / throughput
- Detection counts
- Class distribution
- Confidence statistics
- Error counts
- JSON reporting

These are operational metrics, not ground-truth
precision, recall, or mAP.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import json
import math
import statistics
import time


class CVMetrics:

    def __init__(
        self,
        max_latency_samples: int = 10000,
    ):
        if (
            isinstance(max_latency_samples, bool)
            or not isinstance(
                max_latency_samples, int
            )
            or max_latency_samples <= 0
        ):
            raise ValueError(
                "Invalid max_latency_samples"
            )

        self.started_at = time.perf_counter()
        self.max_latency_samples = (
            max_latency_samples
        )

        self.frames_processed = 0
        self.processing_errors = 0

        self.latencies_ms = []
        self.confidences = []

        self.detections_by_class = Counter()
        self.total_detections = 0

    def record_frame(
        self,
        latency_ms: float,
        detections: list[dict],
    ) -> None:

        if (
            isinstance(latency_ms, bool)
            or not isinstance(
                latency_ms, (int, float)
            )
            or not math.isfinite(latency_ms)
            or latency_ms < 0
        ):
            raise ValueError(
                "Invalid latency"
            )

        if not isinstance(detections, list):
            raise ValueError(
                "detections must be a list"
            )

        self.frames_processed += 1

        self.latencies_ms.append(
            float(latency_ms)
        )

        if (
            len(self.latencies_ms)
            > self.max_latency_samples
        ):
            self.latencies_ms.pop(0)

        for detection in detections:
            label = detection.get(
                "class_name", "unknown"
            )

            confidence = detection.get(
                "confidence"
            )

            self.detections_by_class[
                label
            ] += 1

            self.total_detections += 1

            if (
                isinstance(confidence, (int, float))
                and not isinstance(confidence, bool)
                and math.isfinite(confidence)
                and 0 <= confidence <= 1
            ):
                self.confidences.append(
                    float(confidence)
                )

                if (
                    len(self.confidences)
                    > self.max_latency_samples
                ):
                    self.confidences.pop(0)

    def record_error(self) -> None:
        self.processing_errors += 1

    @staticmethod
    def _percentile(
        values: list[float],
        percentile: float,
    ) -> float | None:

        if not values:
            return None

        ordered = sorted(values)

        position = (
            (len(ordered) - 1)
            * percentile / 100
        )

        lower = int(math.floor(position))
        upper = int(math.ceil(position))

        fraction = position - lower

        result = (
            ordered[lower]
            * (1 - fraction)
            + ordered[upper]
            * fraction
        )

        return round(result, 4)

    def summary(self) -> dict:

        elapsed_seconds = max(
            time.perf_counter()
            - self.started_at,
            1e-9,
        )

        latencies = self.latencies_ms

        mean_latency = (
            statistics.mean(latencies)
            if latencies else None
        )

        mean_confidence = (
            statistics.mean(
                self.confidences
            )
            if self.confidences
            else None
        )

        return {
            "frames_processed": (
                self.frames_processed
            ),
            "processing_errors": (
                self.processing_errors
            ),
            "elapsed_seconds": round(
                elapsed_seconds, 4
            ),
            "effective_fps": round(
                self.frames_processed
                / elapsed_seconds,
                4,
            ),
            "mean_processing_latency_ms": (
                round(mean_latency, 4)
                if mean_latency is not None
                else None
            ),
            "p50_latency_ms": (
                self._percentile(
                    latencies, 50
                )
            ),
            "p95_latency_ms": (
                self._percentile(
                    latencies, 95
                )
            ),
            "p99_latency_ms": (
                self._percentile(
                    latencies, 99
                )
            ),
            "total_detections": (
                self.total_detections
            ),
            "detections_by_class": dict(
                self.detections_by_class
            ),
            "average_detection_confidence": (
                round(mean_confidence, 4)
                if mean_confidence is not None
                else None
            ),
            "metrics_scope": (
                "runtime performance only"
            ),
        }

    def save_report(
        self,
        output_path: str,
    ) -> str:

        destination = Path(
            output_path
        )

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        destination.write_text(
            json.dumps(
                self.summary(),
                indent=2,
            ),
            encoding="utf-8",
        )

        return str(destination)
