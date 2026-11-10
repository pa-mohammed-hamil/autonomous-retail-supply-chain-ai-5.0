"""Planned module: freshness checks. Implementation pending."""

"""
ai/pipelines/freshness_checks.py

Data freshness monitoring for retail pipelines.

Features:
- Timestamp parsing and UTC normalization
- Per-record age calculation
- Dataset-level freshness assessment
- Stale record detection
- Missing and future timestamp detection
- Configurable freshness thresholds
- Dataset heartbeat checks
- JSON-ready alerts and reports

Read-only:
No ingestion jobs are restarted automatically.
No source data is modified.
"""

from __future__ import annotations

import math

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class FreshnessConfig:
    max_age_minutes: float = 60.0
    warning_age_minutes: float = 30.0
    allowed_future_skew_minutes: float = 2.0
    require_nonempty: bool = True

    def __post_init__(self):
        for name in (
            "max_age_minutes",
            "warning_age_minutes",
            "allowed_future_skew_minutes",
        ):
            value = getattr(self, name)

            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(
                    f"Invalid {name}"
                )

        if (
            self.warning_age_minutes
            > self.max_age_minutes
        ):
            raise ValueError(
                "Warning threshold cannot exceed "
                "maximum age"
            )


class FreshnessChecks:

    def __init__(
        self,
        config: FreshnessConfig | None = None,
    ):
        self.config = config or FreshnessConfig()

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime:
        if isinstance(value, datetime):
            dt = value

        elif isinstance(value, str):
            dt = datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )

        else:
            raise ValueError(
                "Timestamp must be datetime or ISO text"
            )

        if (
            dt.tzinfo is None
            or dt.utcoffset() is None
        ):
            raise ValueError(
                "Timezone-aware timestamp required"
            )

        return dt.astimezone(timezone.utc)

    @staticmethod
    def _validate_as_of(
        as_of: datetime | None,
    ) -> datetime:
        as_of = as_of or datetime.now(
            timezone.utc
        )

        if (
            as_of.tzinfo is None
            or as_of.utcoffset() is None
        ):
            raise ValueError(
                "as_of must be timezone-aware"
            )

        return as_of.astimezone(timezone.utc)

    def check_timestamp(
        self,
        timestamp: datetime | str,
        as_of: datetime | None = None,
    ) -> dict:

        as_of = self._validate_as_of(as_of)

        try:
            observed_at = self._parse_timestamp(
                timestamp
            )
        except (ValueError, TypeError, OverflowError) as exc:
            return {
                "status": "invalid",
                "age_minutes": None,
                "reason": str(exc),
            }

        age_minutes = (
            as_of - observed_at
        ).total_seconds() / 60

        if (
            age_minutes
            < -self.config.allowed_future_skew_minutes
        ):
            status = "future"
        elif age_minutes < 0:
            status = "fresh"
        elif age_minutes > self.config.max_age_minutes:
            status = "stale"
        elif (
            age_minutes
            > self.config.warning_age_minutes
        ):
            status = "warning"
        else:
            status = "fresh"

        return {
            "status": status,
            "age_minutes": round(
                age_minutes, 3
            ),
            "observed_at": (
                observed_at.isoformat()
            ),
            "checked_at": as_of.isoformat(),
        }

    def check_dataset(
        self,
        dataset: str,
        rows: list[dict[str, Any]],
        timestamp_column: str,
        as_of: datetime | None = None,
    ) -> dict:
        """
        Evaluate freshness of a dataset.

        The dataset status is determined from its
        latest valid timestamp, while record-level
        issues are reported separately.

        A fresh latest record does not imply that
        every record is fresh.
        """

        if not dataset:
            raise ValueError("Dataset name required")

        if not isinstance(rows, list):
            raise ValueError(
                "rows must be a list"
            )

        if any(
            not isinstance(row, dict)
            for row in rows
        ):
            raise ValueError(
                "Every row must be a dictionary"
            )

        as_of = self._validate_as_of(as_of)

        valid_timestamps = []
        record_issues = []
        status_counts = {
            "fresh": 0,
            "warning": 0,
            "stale": 0,
            "future": 0,
            "invalid": 0,
        }

        for index, row in enumerate(rows):
            value = row.get(timestamp_column)

            if value is None or value == "":
                status_counts["invalid"] += 1
                record_issues.append({
                    "row_index": index,
                    "code": "MISSING_TIMESTAMP",
                })
                continue

            result = self.check_timestamp(
                timestamp=value,
                as_of=as_of,
            )

            status = result["status"]
            status_counts[status] += 1

            if status in {"invalid", "future"}:
                record_issues.append({
                    "row_index": index,
                    "code": (
                        "INVALID_TIMESTAMP"
                        if status == "invalid"
                        else "FUTURE_TIMESTAMP"
                    ),
                })
                continue

            valid_timestamps.append(
                self._parse_timestamp(value)
            )

            if status in {"warning", "stale"}:
                record_issues.append({
                    "row_index": index,
                    "code": (
                        "STALE_RECORD"
                        if status == "stale"
                        else "AGING_RECORD"
                    ),
                    "age_minutes": result[
                        "age_minutes"
                    ],
                })

        latest = (
            max(valid_timestamps)
            if valid_timestamps
            else None
        )

        if latest is None:
            dataset_status = (
                "empty"
                if not rows
                else "invalid"
            )
            latest_age = None

        else:
            latest_result = self.check_timestamp(
                timestamp=latest,
                as_of=as_of,
            )
            dataset_status = latest_result[
                "status"
            ]
            latest_age = latest_result[
                "age_minutes"
            ]

        if (
            not rows
            and not self.config.require_nonempty
        ):
            passed = True
        else:
            passed = (
                dataset_status == "fresh"
                and status_counts["future"] == 0
                and status_counts["invalid"] == 0
            )

        return {
            "dataset": dataset,
            "row_count": len(rows),
            "timestamp_column": timestamp_column,
            "status": dataset_status,
            "passed": passed,
            "latest_observation_at": (
                latest.isoformat()
                if latest is not None
                else None
            ),
            "latest_age_minutes": latest_age,
            "record_status_counts": status_counts,
            "record_issues": record_issues,
            "checked_at": as_of.isoformat(),
            "source_modified": False,
        }

    def check_heartbeat(
        self,
        pipeline_name: str,
        last_success_at: datetime | str | None,
        expected_interval_minutes: float,
        as_of: datetime | None = None,
    ) -> dict:
        """
        Check whether a pipeline has completed
        recently enough.

        Example:
        An hourly ingestion job with a 60-minute
        expected interval can be monitored with
        a 15-minute grace period.
        """

        if not pipeline_name:
            raise ValueError(
                "Pipeline name required"
            )

        if (
            isinstance(expected_interval_minutes, bool)
            or not isinstance(
                expected_interval_minutes,
                (int, float),
            )
            or not math.isfinite(
                expected_interval_minutes
            )
            or expected_interval_minutes <= 0
        ):
            raise ValueError(
                "Invalid expected interval"
            )

        as_of = self._validate_as_of(as_of)

        if last_success_at is None:
            return {
                "pipeline": pipeline_name,
                "status": "never_completed",
                "passed": False,
                "last_success_at": None,
                "age_minutes": None,
            }

        result = self.check_timestamp(
            last_success_at,
            as_of=as_of,
        )

        if result["status"] in {
            "invalid",
            "future",
        }:
            return {
                "pipeline": pipeline_name,
                "status": result["status"],
                "passed": False,
                "last_success_at": str(
                    last_success_at
                ),
                "age_minutes": result.get(
                    "age_minutes"
                ),
            }

        grace_minutes = 15.0
        max_allowed_age = (
            expected_interval_minutes
            + grace_minutes
        )

        age_minutes = max(
            0.0,
            result["age_minutes"],
        )

        overdue = (
            age_minutes > max_allowed_age
        )

        return {
            "pipeline": pipeline_name,
            "status": (
                "overdue"
                if overdue
                else "healthy"
            ),
            "passed": not overdue,
            "last_success_at": (
                self._parse_timestamp(
                    last_success_at
                ).isoformat()
            ),
            "age_minutes": round(
                age_minutes, 3
            ),
            "expected_interval_minutes": (
                expected_interval_minutes
            ),
            "grace_minutes": grace_minutes,
            "checked_at": as_of.isoformat(),
        }


if __name__ == "__main__":
    from datetime import timedelta

    now = datetime(
        2026, 10, 25, 12, 0,
        tzinfo=timezone.utc,
    )

    rows = [
        {
            "event_id": "EVT-001",
            "recorded_at": (
                now - timedelta(minutes=10)
            ).isoformat(),
        },
        {
            "event_id": "EVT-002",
            "recorded_at": (
                now - timedelta(minutes=45)
            ).isoformat(),
        },
        {
            "event_id": "EVT-003",
            "recorded_at": (
                now - timedelta(minutes=120)
            ).isoformat(),
        },
    ]

    checker = FreshnessChecks(
        FreshnessConfig(
            max_age_minutes=60,
            warning_age_minutes=30,
        )
    )

    report = checker.check_dataset(
        dataset="warehouse_events",
        rows=rows,
        timestamp_column="recorded_at",
        as_of=now,
    )

    print("Dataset report:", report)

    heartbeat = checker.check_heartbeat(
        pipeline_name="warehouse_ingestion",
        last_success_at=(
            now - timedelta(minutes=75)
        ),
        expected_interval_minutes=60,
        as_of=now,
    )

    print("Pipeline heartbeat:", heartbeat)
