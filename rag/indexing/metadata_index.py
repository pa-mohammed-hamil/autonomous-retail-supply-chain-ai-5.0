"""Planned module: metadata index. Implementation pending."""

"""
ai/retrieval/metadata_index.py

Autonomous Retail Supply Chain AI 5.0

Structured Metadata Index

Uses Python standard library only.

Supported operators:
    eq, ne, in, gte, lte,
    gt, lt, contains

Dates:
    Use ISO 8601 date strings:
    YYYY-MM-DD
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path


@dataclass
class MetadataRecord:
    document_id: str
    tenant_id: str
    metadata: dict = field(
        default_factory=dict
    )


class MetadataIndex:

    def __init__(self):
        self.records = {}

        # Inverted index for exact
        # string/numeric metadata matches.
        self.inverted = defaultdict(
            set
        )

    @staticmethod
    def _indexable(value):
        return isinstance(
            value,
            (str, int, float, bool),
        ) and not isinstance(
            value, (dict, list)
        )

    def _remove_from_inverted(
        self,
        record,
    ):
        for key, value in (
            record.metadata.items()
        ):
            if self._indexable(value):
                self.inverted[
                    (record.tenant_id, key, value)
                ].discard(
                    record.document_id
                )

    def upsert(
        self,
        record: MetadataRecord,
    ):
        if not record.document_id:
            raise ValueError(
                "document_id required"
            )

        if not record.tenant_id:
            raise ValueError(
                "tenant_id required"
            )

        existing = self.records.get(
            record.document_id
        )

        if existing is not None:
            self._remove_from_inverted(
                existing
            )

        self.records[
            record.document_id
        ] = record

        for key, value in (
            record.metadata.items()
        ):
            if self._indexable(value):
                self.inverted[
                    (record.tenant_id, key, value)
                ].add(
                    record.document_id
                )

    def delete(self, document_id):
        record = self.records.pop(
            document_id,
            None,
        )

        if record is None:
            return False

        self._remove_from_inverted(
            record
        )

        return True

    @staticmethod
    def _coerce_date(value):
        if isinstance(value, datetime):
            return value.date()

        if isinstance(value, date):
            return value

        if isinstance(value, str):
            try:
                return date.fromisoformat(
                    value
                )
            except ValueError:
                pass

        return None

    @classmethod
    def _compare(
        cls,
        actual,
        operator,
        expected,
    ):
        if operator == "eq":
            return actual == expected

        if operator == "ne":
            return actual != expected

        if operator == "in":
            return actual in expected

        if operator == "contains":
            if isinstance(
                actual, str
            ):
                return str(
                    expected
                ).lower() in actual.lower()

            if isinstance(
                actual, (list, tuple, set)
            ):
                return expected in actual

            return False

        actual_date = cls._coerce_date(
            actual
        )

        expected_date = cls._coerce_date(
            expected
        )

        if (
            actual_date is not None
            and expected_date is not None
        ):
            left = actual_date
            right = expected_date

        elif (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and isinstance(expected, (int, float))
            and not isinstance(expected, bool)
        ):
            left = actual
            right = expected

        else:
            return False

        if operator == "gte":
            return left >= right

        if operator == "lte":
            return left <= right

        if operator == "gt":
            return left > right

        if operator == "lt":
            return left < right

        raise ValueError(
            f"Unsupported operator: {operator}"
        )

    def search(
        self,
        tenant_id,
        filters=None,
        limit=100,
    ):
        if not tenant_id:
            raise ValueError(
                "tenant_id required"
            )

        if limit < 1:
            raise ValueError(
                "limit must be >= 1"
            )

        filters = filters or {}

        candidates = {
            document_id
            for document_id, record
            in self.records.items()
            if record.tenant_id == tenant_id
        }

        # Narrow candidates using the
        # inverted index for equality.
        for key, condition in (
            filters.items()
        ):
            if not isinstance(
                condition, dict
            ):
                condition = {
                    "eq": condition
                }

            if "eq" in condition:
                expected = condition[
                    "eq"
                ]

                if self._indexable(
                    expected
                ):
                    candidates &= (
                        self.inverted.get(
                            (
                                tenant_id,
                                key,
                                expected,
                            ),
                            set(),
                        )
                    )

        results = []

        for document_id in sorted(
            candidates
        ):
            record = self.records[
                document_id
            ]

            matched = True

            for key, condition in (
                filters.items()
            ):
                if not isinstance(
                    condition, dict
                ):
                    condition = {
                        "eq": condition
                    }

                actual = (
                    record.metadata.get(
                        key
                    )
                )

                if not all(
                    self._compare(
                        actual,
                        operator,
                        expected,
                    )
                    for operator, expected
                    in condition.items()
                ):
                    matched = False
                    break

            if matched:
                results.append(
                    document_id
                )

            if len(results) >= limit:
                break

        return results

    def stats(self):
        tenants = {
            record.tenant_id
            for record
            in self.records.values()
        }

        return {
            "document_count": len(
                self.records
            ),
            "tenant_count": len(
                tenants
            ),
            "indexed_keys": sorted({
                key
                for record
                in self.records.values()
                for key
                in record.metadata
            }),
        }

    def save(
        self,
        path="indexes/metadata.json",
    ):
        output = Path(path)

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        payload = {
            "version": 1,
            "records": [
                {
                    "document_id": (
                        record.document_id
                    ),
                    "tenant_id": (
                        record.tenant_id
                    ),
                    "metadata": (
                        record.metadata
                    ),
                }
                for record
                in self.records.values()
            ],
        }

        output.write_text(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return output

    @classmethod
    def load(cls, path):
        payload = json.loads(
            Path(path).read_text(
                encoding="utf-8"
            )
        )

        if payload.get("version") != 1:
            raise ValueError(
                "Unsupported metadata version"
            )

        index = cls()

        for item in payload["records"]:
            index.upsert(
                MetadataRecord(**item)
            )

        return index


if __name__ == "__main__":
    index = MetadataIndex()

    index.upsert(
        MetadataRecord(
            document_id="INV001",
            tenant_id="demo",
            metadata={
                "category": "inventory",
                "warehouse": "A",
                "stock": 120,
                "updated_at": "2026-10-27",
                "status": "active",
            },
        )
    )

    index.upsert(
        MetadataRecord(
            document_id="INV002",
            tenant_id="demo",
            metadata={
                "category": "inventory",
                "warehouse": "B",
                "stock": 15,
                "updated_at": "2026-10-25",
                "status": "active",
            },
        )
    )

    index.upsert(
        MetadataRecord(
            document_id="SUP003",
            tenant_id="demo",
            metadata={
                "category": "supplier",
                "risk_score": 0.85,
                "updated_at": "2026-10-26",
                "status": "active",
            },
        )
    )

    low_stock = index.search(
        tenant_id="demo",
        filters={
            "category": "inventory",
            "stock": {
                "lt": 20,
            },
            "status": "active",
        },
    )

    print(
        "Low-stock documents:",
        low_stock,
    )

    recent = index.search(
        tenant_id="demo",
        filters={
            "updated_at": {
                "gte": "2026-10-26",
            },
        },
    )

    print(
        "Recently updated:",
        recent,
    )

    print(
        json.dumps(
            index.stats(),
            indent=2,
        )
    )

    index.save()

    restored = MetadataIndex.load(
        "indexes/metadata.json"
    )

    print(
        restored.stats()
    )
