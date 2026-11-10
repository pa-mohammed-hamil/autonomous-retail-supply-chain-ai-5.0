"""Planned module: csv loader. Implementation pending."""

"""
ai/ingestion/csv_loader.py

Autonomous Retail Supply Chain AI 5.0
CSV Data Ingestion Module

Install:
    pip install pandas

Run:
    python -m ai.ingestion.csv_loader

Supported:
- Sales and demand CSV
- Inventory CSV
- Supplier CSV
- Logistics CSV
- Product pricing CSV
- Customer feedback CSV

Security:
- Tenant IDs must come from trusted
  application authentication context.
- Do not load arbitrary filesystem paths
  directly from untrusted requests.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class CSVDocument:
    document_id: str
    content: str
    title: str
    metadata: dict[str, Any] = field(
        default_factory=dict
    )


class RetailCSVLoader:

    def __init__(
        self,
        encoding="utf-8-sig",
        max_rows=100000,
        max_file_mb=50,
    ):
        self.encoding = encoding
        self.max_rows = max_rows
        self.max_file_mb = max_file_mb

    @staticmethod
    def _normalize_value(value):
        if pd.isna(value):
            return None

        if isinstance(
            value,
            pd.Timestamp,
        ):
            return value.isoformat()

        if hasattr(value, "item"):
            try:
                return value.item()
            except (TypeError, ValueError):
                pass

        return value

    def load_dataframe(
        self,
        file_path,
        required_columns=None,
    ):
        path = Path(file_path)

        if not path.is_file():
            raise FileNotFoundError(path)

        if path.suffix.lower() != ".csv":
            raise ValueError(
                "Expected a CSV file"
            )

        if (
            path.stat().st_size
            > self.max_file_mb * 1024 * 1024
        ):
            raise ValueError(
                "CSV exceeds size limit"
            )

        # Keep identifiers such as SKU001
        # and leading-zero codes as strings.
        df = pd.read_csv(
            path,
            encoding=self.encoding,
            dtype=str,
            keep_default_na=False,
            nrows=self.max_rows + 1,
        )

        if len(df) > self.max_rows:
            raise ValueError(
                "CSV exceeds row limit"
            )

        if df.columns.duplicated().any():
            raise ValueError(
                "Duplicate column names"
            )

        df.columns = [
            str(column).strip()
            for column in df.columns
        ]

        if df.columns.duplicated().any():
            raise ValueError(
                "Duplicate normalized columns"
            )

        required_columns = (
            required_columns or []
        )

        missing = [
            column
            for column in required_columns
            if column not in df.columns
        ]

        if missing:
            raise ValueError(
                f"Missing columns: {missing}"
            )

        return df

    @staticmethod
    def _make_id(
        tenant_id,
        source_key,
        row_number,
    ):
        raw = (
            f"{tenant_id}|{source_key}|"
            f"{row_number}"
        )

        return hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()[:24]

    def load_documents(
        self,
        file_path,
        tenant_id,
        category,
        required_columns=None,
        id_column=None,
        source_key=None,
        metadata_columns=None,
    ):
        if not tenant_id:
            raise ValueError(
                "tenant_id required"
            )

        if not category:
            raise ValueError(
                "category required"
            )

        path = Path(file_path)

        df = self.load_dataframe(
            path,
            required_columns,
        )

        if (
            id_column
            and id_column not in df.columns
        ):
            raise ValueError(
                "id_column does not exist"
            )

        metadata_columns = (
            metadata_columns or []
        )

        missing_metadata = [
            key
            for key in metadata_columns
            if key not in df.columns
        ]

        if missing_metadata:
            raise ValueError(
                "Missing metadata columns: "
                + str(missing_metadata)
            )

        # Use a stable logical source key
        # for updates to the same dataset.
        source_key = (
            source_key or path.name
        )

        documents = []
        seen_ids = set()

        for row_index, row in (
            df.iterrows()
        ):
            values = {
                column: (
                    self._normalize_value(
                        value
                    )
                )
                for column, value
                in row.items()
            }

            # Empty fields are represented
            # as missing rather than facts.
            values = {
                key: value
                for key, value
                in values.items()
                if value not in ("", None)
            }

            if not values:
                continue

            row_number = (
                int(row_index) + 2
            )

            row_key = (
                str(values[id_column])
                if id_column
                and id_column in values
                else str(row_number)
            )

            document_id = self._make_id(
                tenant_id,
                source_key,
                row_key,
            )

            if document_id in seen_ids:
                raise ValueError(
                    "Duplicate row identity. "
                    "Check id_column."
                )

            seen_ids.add(
                document_id
            )

            content = "\n".join(
                f"{key}: {value}"
                for key, value
                in values.items()
            )

            metadata = {
                "tenant_id": tenant_id,
                "category": category,
                "source_type": "csv",
                "source_file": path.name,
                "source_key": source_key,
                "row_number": row_number,
            }

            for column in metadata_columns:
                metadata[column] = (
                    values.get(column)
                )

            documents.append(
                CSVDocument(
                    document_id=document_id,
                    title=(
                        f"{category} - "
                        f"{row_key}"
                    ),
                    content=content,
                    metadata=metadata,
                )
            )

        return documents

    @staticmethod
    def export_jsonl(
        documents,
        output_path,
    ):
        path = Path(output_path)

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with path.open(
            "w",
            encoding="utf-8",
        ) as file:
            for document in documents:
                file.write(
                    json.dumps(
                        {
                            "document_id": (
                                document.document_id
                            ),
                            "title": document.title,
                            "content": (
                                document.content
                            ),
                            "metadata": (
                                document.metadata
                            ),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        return path


if __name__ == "__main__":
    demo_path = Path(
        "data/inventory/demo_inventory.csv"
    )

    demo_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not demo_path.exists():
        demo_path.write_text(
            "sku,warehouse,stock,reorder_point\n"
            "SKU001,A,120,50\n"
            "SKU002,B,15,40\n",
            encoding="utf-8",
        )

    loader = RetailCSVLoader()

    documents = loader.load_documents(
        file_path=demo_path,
        tenant_id="demo",
        category="inventory",
        required_columns=[
            "sku",
            "warehouse",
            "stock",
        ],
        id_column="sku",
        metadata_columns=[
            "warehouse",
            "sku",
        ],
    )

    for document in documents:
        print(
            json.dumps(
                document.__dict__,
                indent=2,
            )
        )

    loader.export_jsonl(
        documents,
        "data/processed/inventory.jsonl",
    )
