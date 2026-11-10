"""Planned module: data catalog. Implementation pending."""

"""
ai/pipelines/data_catalog.py

Metadata catalog for Autonomous Retail
Supply Chain AI 5.0.

Features:
- Dataset registration
- Schema and column metadata
- Dataset ownership
- Data classification
- Data source and storage references
- Freshness and quality metadata
- Dataset versioning
- Search and discovery
- Dataset lineage
- Impact analysis
- SQLite persistence
- Audit timestamps

Metadata only:
- Does not ingest or expose source records
- Does not store credentials
- Does not modify operational datasets

Standard library only. Python 3.10+.
"""

from __future__ import annotations

import json
import sqlite3

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CLASSIFICATIONS = {
    "public",
    "internal",
    "confidential",
    "restricted",
}

DATASET_STATUSES = {
    "active",
    "deprecated",
    "archived",
}


def now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


@dataclass(frozen=True)
class ColumnMetadata:
    name: str
    data_type: str
    nullable: bool = False
    description: str = ""
    classification: str = "internal"
    is_primary_key: bool = False

    def __post_init__(self):
        if not self.name.strip():
            raise ValueError(
                "Column name required"
            )

        if not self.data_type.strip():
            raise ValueError(
                "Column data type required"
            )

        if self.classification not in CLASSIFICATIONS:
            raise ValueError(
                "Invalid column classification"
            )


@dataclass(frozen=True)
class DatasetMetadata:
    dataset_id: str
    name: str
    description: str
    domain: str
    owner: str
    source_system: str
    storage_uri: str
    schema_version: str
    columns: tuple[ColumnMetadata, ...]
    classification: str = "internal"
    status: str = "active"
    tags: tuple[str, ...] = ()
    freshness_sla_minutes: int | None = None
    retention_days: int | None = None

    def __post_init__(self):
        for value in (
            self.dataset_id,
            self.name,
            self.domain,
            self.owner,
            self.source_system,
            self.schema_version,
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    "Required dataset metadata is missing"
                )

        if self.classification not in CLASSIFICATIONS:
            raise ValueError(
                "Invalid dataset classification"
            )

        if self.status not in DATASET_STATUSES:
            raise ValueError(
                "Invalid dataset status"
            )

        if not self.columns:
            raise ValueError(
                "At least one column required"
            )

        names = [column.name for column in self.columns]

        if len(names) != len(set(names)):
            raise ValueError(
                "Duplicate column names"
            )

        if (
            self.freshness_sla_minutes is not None
            and self.freshness_sla_minutes < 1
        ):
            raise ValueError(
                "Invalid freshness SLA"
            )

        if (
            self.retention_days is not None
            and self.retention_days < 1
        ):
            raise ValueError(
                "Invalid retention period"
            )

        # Prevent accidental credentials in metadata.
        if "@" in self.storage_uri and "://" in self.storage_uri:
            authority = self.storage_uri.split(
                "://", 1
            )[1].split("/", 1)[0]

            if "@" in authority:
                raise ValueError(
                    "Storage URI must not contain credentials"
                )


class DataCatalog:

    def __init__(
        self,
        database_path: str = "data/data_catalog.db",
    ):
        path = Path(database_path)
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.connection = sqlite3.connect(
            str(path),
            timeout=30,
        )

        self.connection.row_factory = sqlite3.Row

        self.connection.execute(
            "PRAGMA foreign_keys=ON"
        )

        self._initialize()

    def _initialize(self):
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS datasets (
                dataset_id TEXT PRIMARY KEY,
                metadata_json TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS lineage (
                upstream_dataset_id TEXT NOT NULL,
                downstream_dataset_id TEXT NOT NULL,
                transformation TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (
                    upstream_dataset_id,
                    downstream_dataset_id
                ),
                FOREIGN KEY (upstream_dataset_id)
                    REFERENCES datasets(dataset_id),
                FOREIGN KEY (downstream_dataset_id)
                    REFERENCES datasets(dataset_id)
            );

            CREATE TABLE IF NOT EXISTS quality_status (
                dataset_id TEXT PRIMARY KEY,
                quality_score REAL,
                freshness_status TEXT,
                last_observed_at TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (dataset_id)
                    REFERENCES datasets(dataset_id)
            );
            """
        )

        self.connection.commit()

    def register(
        self,
        metadata: DatasetMetadata,
        overwrite: bool = False,
    ) -> dict:
        payload = json.dumps(
            asdict(metadata),
            separators=(",", ":"),
        )

        now = now_iso()

        existing = self.connection.execute(
            """
            SELECT version
            FROM datasets
            WHERE dataset_id = ?
            """,
            (metadata.dataset_id,),
        ).fetchone()

        if existing is not None and not overwrite:
            raise ValueError(
                "Dataset already registered"
            )

        if existing is None:
            self.connection.execute(
                """
                INSERT INTO datasets (
                    dataset_id,
                    metadata_json,
                    version,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, 1, ?, ?)
                """,
                (
                    metadata.dataset_id,
                    payload,
                    now,
                    now,
                ),
            )
            version = 1

        else:
            version = existing["version"] + 1

            self.connection.execute(
                """
                UPDATE datasets
                SET metadata_json = ?,
                    version = ?,
                    updated_at = ?
                WHERE dataset_id = ?
                """,
                (
                    payload,
                    version,
                    now,
                    metadata.dataset_id,
                ),
            )

        self.connection.commit()

        return {
            "dataset_id": metadata.dataset_id,
            "catalog_version": version,
            "registered": True,
        }

    def get(
        self,
        dataset_id: str,
    ) -> dict | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM datasets
            WHERE dataset_id = ?
            """,
            (dataset_id,),
        ).fetchone()

        if row is None:
            return None

        return {
            **json.loads(row["metadata_json"]),
            "catalog_version": row["version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_datasets(
        self,
        domain: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        rows = self.connection.execute(
            """
            SELECT dataset_id
            FROM datasets
            ORDER BY dataset_id
            """
        ).fetchall()

        datasets = []

        for row in rows:
            dataset = self.get(
                row["dataset_id"]
            )

            if (
                domain is not None
                and dataset["domain"] != domain
            ):
                continue

            if (
                status is not None
                and dataset["status"] != status
            ):
                continue

            datasets.append(dataset)

        return datasets

    def search(
        self,
        query: str,
    ) -> list[dict]:
        """
        Search dataset metadata, descriptions,
        tags and column names.
        """

        query = query.strip().casefold()

        if not query:
            return []

        results = []

        for dataset in self.list_datasets():
            searchable = " ".join([
                dataset["name"],
                dataset["description"],
                dataset["domain"],
                dataset["owner"],
                dataset["source_system"],
                *dataset["tags"],
                *[
                    column["name"]
                    for column in dataset["columns"]
                ],
            ]).casefold()

            if query in searchable:
                results.append(dataset)

        return results

    def add_lineage(
        self,
        upstream_dataset_id: str,
        downstream_dataset_id: str,
        transformation: str,
    ) -> dict:
        if upstream_dataset_id == downstream_dataset_id:
            raise ValueError(
                "Dataset cannot depend on itself"
            )

        if not transformation.strip():
            raise ValueError(
                "Transformation description required"
            )

        for dataset_id in (
            upstream_dataset_id,
            downstream_dataset_id,
        ):
            if self.get(dataset_id) is None:
                raise ValueError(
                    f"Unknown dataset: {dataset_id}"
                )

        if upstream_dataset_id in self.impact_analysis(
            downstream_dataset_id
        )["downstream_datasets"]:
            raise ValueError(
                "Lineage relationship already exists"
            )

        if downstream_dataset_id in self.impact_analysis(
            upstream_dataset_id
        )["upstream_datasets"]:
            raise ValueError(
                "Lineage cycle detected"
            )

        self.connection.execute(
            """
            INSERT OR REPLACE INTO lineage (
                upstream_dataset_id,
                downstream_dataset_id,
                transformation,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                upstream_dataset_id,
                downstream_dataset_id,
                transformation,
                now_iso(),
            ),
        )

        self.connection.commit()

        return {
            "upstream": upstream_dataset_id,
            "downstream": downstream_dataset_id,
            "registered": True,
        }

    def lineage(
        self,
        dataset_id: str,
    ) -> dict:
        if self.get(dataset_id) is None:
            raise ValueError(
                "Unknown dataset"
            )

        upstream = self.connection.execute(
            """
            SELECT upstream_dataset_id, transformation
            FROM lineage
            WHERE downstream_dataset_id = ?
            """,
            (dataset_id,),
        ).fetchall()

        downstream = self.connection.execute(
            """
            SELECT downstream_dataset_id, transformation
            FROM lineage
            WHERE upstream_dataset_id = ?
            """,
            (dataset_id,),
        ).fetchall()

        return {
            "dataset_id": dataset_id,
            "upstream": [
                dict(row)
                for row in upstream
            ],
            "downstream": [
                dict(row)
                for row in downstream
            ],
        }

    def impact_analysis(
        self,
        dataset_id: str,
    ) -> dict:
        """
        Traverse upstream and downstream lineage.
        """

        if self.get(dataset_id) is None:
            raise ValueError(
                "Unknown dataset"
            )

        def traverse(
            starting_id: str,
            direction: str,
        ) -> list[str]:
            visited = set()
            pending = [starting_id]

            while pending:
                current = pending.pop()

                if direction == "downstream":
                    rows = self.connection.execute(
                        """
                        SELECT downstream_dataset_id
                        FROM lineage
                        WHERE upstream_dataset_id = ?
                        """,
                        (current,),
                    ).fetchall()

                    next_ids = [
                        row["downstream_dataset_id"]
                        for row in rows
                    ]

                else:
                    rows = self.connection.execute(
                        """
                        SELECT upstream_dataset_id
                        FROM lineage
                        WHERE downstream_dataset_id = ?
                        """,
                        (current,),
                    ).fetchall()

                    next_ids = [
                        row["upstream_dataset_id"]
                        for row in rows
                    ]

                for next_id in next_ids:
                    if (
                        next_id not in visited
                        and next_id != starting_id
                    ):
                        visited.add(next_id)
                        pending.append(next_id)

            return sorted(visited)

        return {
            "dataset_id": dataset_id,
            "upstream_datasets": traverse(
                dataset_id, "upstream"
            ),
            "downstream_datasets": traverse(
                dataset_id, "downstream"
            ),
        }

    def update_quality_status(
        self,
        dataset_id: str,
        quality_score: float | None = None,
        freshness_status: str | None = None,
        last_observed_at: str | None = None,
    ) -> dict:
        if self.get(dataset_id) is None:
            raise ValueError(
                "Unknown dataset"
            )

        if quality_score is not None:
            if (
                isinstance(quality_score, bool)
                or not isinstance(
                    quality_score, (int, float)
                )
                or not 0 <= quality_score <= 100
            ):
                raise ValueError(
                    "Quality score must be between 0 and 100"
                )

        if freshness_status is not None:
            if freshness_status not in {
                "fresh",
                "warning",
                "stale",
                "invalid",
                "empty",
            }:
                raise ValueError(
                    "Invalid freshness status"
                )

        if last_observed_at is not None:
            timestamp = datetime.fromisoformat(
                last_observed_at.replace(
                    "Z", "+00:00"
                )
            )

            if (
                timestamp.tzinfo is None
                or timestamp.utcoffset() is None
            ):
                raise ValueError(
                    "Observation timestamp needs timezone"
                )

            last_observed_at = timestamp.astimezone(
                timezone.utc
            ).isoformat()

        self.connection.execute(
            """
            INSERT INTO quality_status (
                dataset_id,
                quality_score,
                freshness_status,
                last_observed_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(dataset_id) DO UPDATE SET
                quality_score = excluded.quality_score,
                freshness_status = excluded.freshness_status,
                last_observed_at = excluded.last_observed_at,
                updated_at = excluded.updated_at
            """,
            (
                dataset_id,
                quality_score,
                freshness_status,
                last_observed_at,
                now_iso(),
            ),
        )

        self.connection.commit()

        return {
            "dataset_id": dataset_id,
            "updated": True,
        }

    def get_quality_status(
        self,
        dataset_id: str,
    ) -> dict | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM quality_status
            WHERE dataset_id = ?
            """,
            (dataset_id,),
        ).fetchone()

        return (
            dict(row)
            if row is not None
            else None
        )

    def close(self):
        self.connection.close()


if __name__ == "__main__":
    catalog = DataCatalog(
        "data/demo_data_catalog.db"
    )

    sales_dataset = DatasetMetadata(
        dataset_id="retail.pos_transactions",
        name="POS Transactions",
        description="Retail store sales and returns",
        domain="sales",
        owner="retail_data_team",
        source_system="pos_pipeline",
        storage_uri="s3://retail-data/pos/",
        schema_version="1.0",
        columns=(
            ColumnMetadata(
                name="transaction_id",
                data_type="string",
                is_primary_key=True,
            ),
            ColumnMetadata(
                name="store_id",
                data_type="string",
            ),
            ColumnMetadata(
                name="sku",
                data_type="string",
            ),
            ColumnMetadata(
                name="quantity",
                data_type="integer",
            ),
            ColumnMetadata(
                name="unit_price",
                data_type="decimal",
            ),
            ColumnMetadata(
                name="occurred_at",
                data_type="timestamp",
            ),
        ),
        tags=("sales", "pos", "retail"),
        freshness_sla_minutes=60,
        retention_days=365,
    )

    daily_sales = DatasetMetadata(
        dataset_id="retail.daily_sales",
        name="Daily Sales Aggregates",
        description="Aggregated daily store and SKU sales",
        domain="analytics",
        owner="retail_analytics_team",
        source_system="stream_aggregations",
        storage_uri="s3://retail-data/analytics/daily-sales/",
        schema_version="1.0",
        columns=(
            ColumnMetadata(
                name="store_id",
                data_type="string",
            ),
            ColumnMetadata(
                name="sku",
                data_type="string",
            ),
            ColumnMetadata(
                name="sales_date",
                data_type="date",
            ),
            ColumnMetadata(
                name="net_units",
                data_type="integer",
            ),
        ),
        tags=("analytics", "sales", "daily"),
    )

    catalog.register(
        sales_dataset,
        overwrite=True,
    )

    catalog.register(
        daily_sales,
        overwrite=True,
    )

    catalog.add_lineage(
        upstream_dataset_id="retail.pos_transactions",
        downstream_dataset_id="retail.daily_sales",
        transformation="Aggregate POS events by date, store and SKU",
    )

    catalog.update_quality_status(
        dataset_id="retail.pos_transactions",
        quality_score=98.5,
        freshness_status="fresh",
        last_observed_at=now_iso(),
    )

    print(
        json.dumps(
            catalog.impact_analysis(
                "retail.pos_transactions"
            ),
            indent=2,
        )
    )

    print(
        json.dumps(
            catalog.search("sales"),
            indent=2,
        )
    )

    catalog.close()
