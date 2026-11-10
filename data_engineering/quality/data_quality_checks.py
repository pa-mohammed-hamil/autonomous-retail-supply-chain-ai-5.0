
"""
Reusable data quality checks for retail pipelines.

Features:
- Required column checks
- Null / blank value checks
- Duplicate key checks
- Numeric range validation
- Timestamp validation
- Referential integrity checks
- Data freshness checks
- Quality scoring and detailed errors

Read-only. Does not modify input records.
"""

from __future__ import annotations

import math

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable


@dataclass(frozen=True)
class QualityIssue:
    code: str
    severity: str
    message: str
    row_index: int | None = None
    column: str | None = None


@dataclass
class QualityReport:
    dataset: str
    row_count: int
    issues: list[QualityIssue] = field(
        default_factory=list
    )

    def add(
        self,
        code: str,
        message: str,
        severity: str = "error",
        row_index: int | None = None,
        column: str | None = None,
    ) -> None:
        self.issues.append(
            QualityIssue(
                code=code,
                severity=severity,
                message=message,
                row_index=row_index,
                column=column,
            )
        )

    def to_dict(self) -> dict:
        errors = sum(
            issue.severity == "error"
            for issue in self.issues
        )

        warnings = sum(
            issue.severity == "warning"
            for issue in self.issues
        )

        affected_rows = {
            issue.row_index
            for issue in self.issues
            if (
                issue.severity == "error"
                and issue.row_index is not None
            )
        }

        dataset_errors = sum(
            issue.severity == "error"
            and issue.row_index is None
            for issue in self.issues
        )

        if self.row_count:
            quality_score = round(
                100 * (
                    1 - len(affected_rows)
                    / self.row_count
                ),
                2,
            )
        else:
            quality_score = (
                100.0 if errors == 0 else 0.0
            )

        if dataset_errors:
            quality_score = 0.0

        return {
            "dataset": self.dataset,
            "row_count": self.row_count,
            "error_count": errors,
            "warning_count": warnings,
            "quality_score": quality_score,
            "passed": errors == 0,
            "issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity,
                    "message": issue.message,
                    "row_index": issue.row_index,
                    "column": issue.column,
                }
                for issue in self.issues
            ],
        }


class DataQualityChecks:

    def __init__(
        self,
        dataset: str,
        rows: list[dict[str, Any]],
    ):
        if not dataset:
            raise ValueError("Dataset name required")

        if not isinstance(rows, list):
            raise ValueError("Rows must be a list")

        if any(
            not isinstance(row, dict)
            for row in rows
        ):
            raise ValueError(
                "Every row must be a dictionary"
            )

        self.rows = rows
        self.report = QualityReport(
            dataset=dataset,
            row_count=len(rows),
        )

    @staticmethod
    def _missing(value: Any) -> bool:
        return (
            value is None
            or (
                isinstance(value, str)
                and not value.strip()
            )
        )

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        if not isinstance(value, str):
            raise ValueError("Timestamp must be text")

        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError(
                "Timezone-aware timestamp required"
            )

        return dt.astimezone(timezone.utc)

    def required_columns(
        self,
        columns: Iterable[str],
    ) -> "DataQualityChecks":

        required = tuple(columns)

        for index, row in enumerate(self.rows):
            for column in required:
                if column not in row:
                    self.report.add(
                        code="MISSING_COLUMN",
                        message=(
                            f"Required column missing: {column}"
                        ),
                        row_index=index,
                        column=column,
                    )

        return self

    def not_null(
        self,
        columns: Iterable[str],
    ) -> "DataQualityChecks":

        for index, row in enumerate(self.rows):
            for column in columns:
                if self._missing(row.get(column)):
                    self.report.add(
                        code="NULL_VALUE",
                        message=(
                            f"Missing value in {column}"
                        ),
                        row_index=index,
                        column=column,
                    )

        return self

    def unique(
        self,
        columns: Iterable[str],
    ) -> "DataQualityChecks":

        columns = tuple(columns)

        if not columns:
            raise ValueError(
                "Unique key columns required"
            )

        seen = set()

        for index, row in enumerate(self.rows):
            values = tuple(
                row.get(column)
                for column in columns
            )

            if any(
                self._missing(value)
                for value in values
            ):
                continue

            try:
                if values in seen:
                    self.report.add(
                        code="DUPLICATE_KEY",
                        message=(
                            f"Duplicate key on {columns}"
                        ),
                        row_index=index,
                    )
                else:
                    seen.add(values)
            except TypeError:
                self.report.add(
                    code="UNHASHABLE_KEY",
                    message="Key values must be hashable",
                    row_index=index,
                )

        return self

    def numeric_range(
        self,
        column: str,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> "DataQualityChecks":

        for index, row in enumerate(self.rows):
            value = row.get(column)

            if self._missing(value):
                continue

            try:
                if isinstance(value, bool):
                    raise ValueError

                number = float(value)

                if not math.isfinite(number):
                    raise ValueError

                if (
                    minimum is not None
                    and number < minimum
                ):
                    raise ValueError

                if (
                    maximum is not None
                    and number > maximum
                ):
                    raise ValueError

            except (TypeError, ValueError, OverflowError):
                self.report.add(
                    code="INVALID_NUMERIC_RANGE",
                    message=(
                        f"{column} outside allowed range"
                    ),
                    row_index=index,
                    column=column,
                )

        return self

    def timestamps(
        self,
        column: str,
        as_of: datetime | None = None,
        max_age_days: float | None = None,
    ) -> "DataQualityChecks":

        as_of = as_of or datetime.now(timezone.utc)

        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError(
                "as_of must be timezone-aware"
            )

        as_of = as_of.astimezone(timezone.utc)

        if max_age_days is not None and (
            isinstance(max_age_days, bool)
            or not isinstance(max_age_days, (int, float))
            or not math.isfinite(max_age_days)
            or max_age_days < 0
        ):
            raise ValueError("Invalid max_age_days")

        for index, row in enumerate(self.rows):
            value = row.get(column)

            if self._missing(value):
                continue

            try:
                timestamp = self._timestamp(value)
            except (TypeError, ValueError, OverflowError):
                self.report.add(
                    code="INVALID_TIMESTAMP",
                    message="Invalid timezone-aware timestamp",
                    row_index=index,
                    column=column,
                )
                continue

            if timestamp > as_of:
                self.report.add(
                    code="FUTURE_TIMESTAMP",
                    message="Timestamp is in the future",
                    row_index=index,
                    column=column,
                )

            if max_age_days is not None:
                age_days = (
                    as_of - timestamp
                ).total_seconds() / 86400

                if age_days > max_age_days:
                    self.report.add(
                        code="STALE_DATA",
                        severity="warning",
                        message=(
                            f"Data older than {max_age_days} days"
                        ),
                        row_index=index,
                        column=column,
                    )

        return self

    def foreign_key(
        self,
        column: str,
        allowed_values: set,
    ) -> "DataQualityChecks":

        for index, row in enumerate(self.rows):
            value = row.get(column)

            if self._missing(value):
                continue

            try:
                exists = value in allowed_values
            except TypeError:
                exists = False

            if not exists:
                self.report.add(
                    code="FOREIGN_KEY_NOT_FOUND",
                    message=(
                        f"{column} does not exist "
                        "in reference dataset"
                    ),
                    row_index=index,
                    column=column,
                )

        return self

    def allowed_values(
        self,
        column: str,
        values: set,
    ) -> "DataQualityChecks":

        for index, row in enumerate(self.rows):
            value = row.get(column)

            if self._missing(value):
                continue

            try:
                valid = value in values
            except TypeError:
                valid = False

            if not valid:
                self.report.add(
                    code="INVALID_CATEGORY",
                    message=(
                        f"Unexpected value in {column}"
                    ),
                    row_index=index,
                    column=column,
                )

        return self

    def minimum_rows(
        self,
        count: int,
    ) -> "DataQualityChecks":

        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or count < 0
        ):
            raise ValueError("Invalid minimum row count")

        if len(self.rows) < count:
            self.report.add(
                code="INSUFFICIENT_ROWS",
                message=(
                    f"Expected at least {count} rows"
                ),
            )

        return self

    def run(self) -> dict:
        return self.report.to_dict()


if __name__ == "__main__":
    sample_rows = [
        {
            "event_id": "EVT-001",
            "supplier_id": "SUP-001",
            "sku": "SKU-101",
            "quantity": 100,
            "status": "received",
            "occurred_at": (
                "2026-10-24T09:00:00+00:00"
            ),
        },
        {
            "event_id": "EVT-001",
            "supplier_id": "SUP-999",
            "sku": "SKU-202",
            "quantity": -5,
            "status": "unknown",
            "occurred_at": (
                "2026-10-24T11:00:00+00:00"
            ),
        },
    ]

    quality = DataQualityChecks(
        dataset="supplier_warehouse_events",
        rows=sample_rows,
    )

    result = (
        quality
        .required_columns([
            "event_id",
            "supplier_id",
            "sku",
            "quantity",
            "status",
            "occurred_at",
        ])
        .not_null([
            "event_id",
            "supplier_id",
            "sku",
        ])
        .unique(["event_id"])
        .numeric_range(
            "quantity",
            minimum=0,
        )
        .allowed_values(
            "status",
            {"received", "pending", "rejected"},
        )
        .foreign_key(
            "supplier_id",
            {"SUP-001", "SUP-002"},
        )
        .timestamps(
            "occurred_at",
            as_of=datetime(
                2026, 10, 25, 12, 0,
                tzinfo=timezone.utc,
            ),
            max_age_days=7,
        )
        .minimum_rows(1)
        .run()
    )

    print(result)
