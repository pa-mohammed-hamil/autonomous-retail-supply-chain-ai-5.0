"""Planned module: duplicate checks. Implementation pending."""


"""
ai/pipelines/duplicate_checks.py

Reusable duplicate detection for retail data pipelines.

Features:
- Single-column and composite-key duplicate checks
- Exact-record duplicate detection
- Missing-key validation
- Duplicate group reporting
- Configurable first/last record retention
- Optional deduplication
- JSON-ready quality reports

Read-only by default.
No database records are deleted or modified.
"""

from __future__ import annotations

import json

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable


@dataclass(frozen=True)
class DuplicateCheckConfig:
    keep: str = "first"
    missing_key_policy: str = "error"

    def __post_init__(self):
        if self.keep not in {"first", "last"}:
            raise ValueError(
                "keep must be 'first' or 'last'"
            )

        if self.missing_key_policy not in {
            "error",
            "skip",
        }:
            raise ValueError(
                "Invalid missing_key_policy"
            )


class DuplicateChecks:

    def __init__(
        self,
        config: DuplicateCheckConfig | None = None,
    ):
        self.config = config or DuplicateCheckConfig()

    @staticmethod
    def _normalize(value: Any) -> Any:
        """
        Convert supported values into a stable,
        hashable representation.

        JSON-like dictionaries and lists are
        supported as key values.
        """

        if value is None:
            return ("null",)

        if isinstance(value, bool):
            return ("bool", value)

        if isinstance(value, (int, float, Decimal)):
            return ("number", str(value))

        if isinstance(value, str):
            return ("string", value)

        if isinstance(value, (date, datetime)):
            return ("date", value.isoformat())

        if isinstance(value, dict):
            return (
                "dict",
                tuple(
                    (
                        str(key),
                        DuplicateChecks._normalize(item),
                    )
                    for key, item in sorted(
                        value.items(),
                        key=lambda pair: str(pair[0]),
                    )
                ),
            )

        if isinstance(value, (list, tuple)):
            return (
                "sequence",
                tuple(
                    DuplicateChecks._normalize(item)
                    for item in value
                ),
            )

        raise ValueError(
            f"Unsupported key type: {type(value).__name__}"
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

    def check(
        self,
        rows: list[dict[str, Any]],
        key_columns: Iterable[str] | None = None,
        exact_record: bool = False,
    ) -> dict:
        """
        Detect duplicate records.

        Parameters:
            rows:
                Source dataset.

            key_columns:
                Business keys, such as
                ["store_id", "transaction_id", "line_id"].

            exact_record:
                Compare all record fields instead
                of selected business keys.
        """

        if not isinstance(rows, list):
            raise ValueError("rows must be a list")

        if any(
            not isinstance(row, dict)
            for row in rows
        ):
            raise ValueError(
                "Every row must be a dictionary"
            )

        columns = (
            tuple(key_columns)
            if key_columns is not None
            else ()
        )

        if not exact_record and not columns:
            raise ValueError(
                "key_columns required unless "
                "exact_record=True"
            )

        if any(
            not isinstance(column, str)
            or not column.strip()
            for column in columns
        ):
            raise ValueError(
                "Invalid key column"
            )

        if len(columns) != len(set(columns)):
            raise ValueError(
                "Duplicate key column names"
            )

        groups = defaultdict(list)
        invalid_rows = []

        for index, row in enumerate(rows):
            if exact_record:
                key = self._normalize(row)
            else:
                missing_columns = [
                    column
                    for column in columns
                    if (
                        column not in row
                        or self._missing(row[column])
                    )
                ]

                if missing_columns:
                    invalid_rows.append({
                        "row_index": index,
                        "missing_columns": missing_columns,
                    })
                    continue

                key = tuple(
                    self._normalize(row[column])
                    for column in columns
                )

            groups[key].append(index)

        duplicate_groups = []
        duplicate_indices = set()
        retained_indices = set()

        for indices in groups.values():
            retained_index = (
                indices[0]
                if self.config.keep == "first"
                else indices[-1]
            )

            retained_indices.add(retained_index)

            if len(indices) <= 1:
                continue

            discarded = [
                index
                for index in indices
                if index != retained_index
            ]

            duplicate_indices.update(discarded)

            duplicate_groups.append({
                "row_indices": indices,
                "retained_index": retained_index,
                "duplicate_indices": discarded,
                "group_size": len(indices),
            })

        duplicate_groups.sort(
            key=lambda group: group["row_indices"][0]
        )

        return {
            "total_rows": len(rows),
            "unique_valid_keys": len(groups),
            "duplicate_group_count": len(
                duplicate_groups
            ),
            "duplicate_row_count": len(
                duplicate_indices
            ),
            "invalid_key_row_count": len(
                invalid_rows
            ),
            "duplicate_groups": duplicate_groups,
            "invalid_key_rows": invalid_rows,
            "duplicate_indices": sorted(
                duplicate_indices
            ),
            "retained_indices": sorted(
                retained_indices
            ),
            "passed": (
                not duplicate_indices
                and (
                    self.config.missing_key_policy
                    == "skip"
                    or not invalid_rows
                )
            ),
            "source_modified": False,
        }

    def deduplicate(
        self,
        rows: list[dict[str, Any]],
        key_columns: Iterable[str] | None = None,
        exact_record: bool = False,
    ) -> dict:
        """
        Return a deduplicated COPY.

        Invalid-key rows are preserved when
        missing_key_policy='skip'.

        When missing_key_policy='error',
        invalid keys prevent deduplication.
        """

        report = self.check(
            rows=rows,
            key_columns=key_columns,
            exact_record=exact_record,
        )

        if (
            report["invalid_key_row_count"] > 0
            and self.config.missing_key_policy
            == "error"
        ):
            raise ValueError(
                "Cannot deduplicate rows with "
                "missing business keys"
            )

        removed = set(
            report["duplicate_indices"]
        )

        cleaned = [
            dict(row)
            for index, row in enumerate(rows)
            if index not in removed
        ]

        return {
            "records": cleaned,
            "original_count": len(rows),
            "deduplicated_count": len(cleaned),
            "removed_count": len(removed),
            "report": report,
            "database_updated": False,
        }

    @staticmethod
    def recommended_keys() -> dict:
        return {
            "pos": [
                "store_id",
                "transaction_id",
                "line_id",
            ],
            "inventory_snapshot": [
                "sku",
                "warehouse_id",
                "updated_at",
            ],
            "inventory_movement": [
                "event_id",
            ],
            "supplier": [
                "supplier_id",
                "sku",
                "observed_at",
            ],
            "supplier_delivery": [
                "delivery_id",
                "sku",
            ],
            "warehouse_event": [
                "event_id",
            ],
            "shipment_event": [
                "event_id",
            ],
            "vehicle_telemetry": [
                "event_id",
            ],
            "feedback": [
                "feedback_id",
            ],
        }


if __name__ == "__main__":
    records = [
        {
            "store_id": "STORE-KOCHI",
            "transaction_id": "TXN-001",
            "line_id": "1",
            "sku": "SKU-101",
            "quantity": 3,
        },
        {
            "store_id": "STORE-KOCHI",
            "transaction_id": "TXN-001",
            "line_id": "1",
            "sku": "SKU-101",
            "quantity": 3,
        },
        {
            "store_id": "STORE-KOCHI",
            "transaction_id": "TXN-002",
            "line_id": "1",
            "sku": "SKU-202",
            "quantity": 5,
        },
    ]

    checker = DuplicateChecks()

    report = checker.check(
        rows=records,
        key_columns=[
            "store_id",
            "transaction_id",
            "line_id",
        ],
    )

    print(
        json.dumps(report, indent=2)
    )

    cleaned = checker.deduplicate(
        rows=records,
        key_columns=[
            "store_id",
            "transaction_id",
            "line_id",
        ],
    )

    print(
        "Original:", cleaned["original_count"]
    )
    print(
        "After deduplication:",
        cleaned["deduplicated_count"],
    )
