"""Planned module: spreadsheet loader. Implementation pending."""

"""
ai/ingestion/spreadsheet_loader.py

Autonomous Retail Supply Chain AI 5.0

Excel Spreadsheet Loader for RAG

Install:
    pip install openpyxl

Run:
    python -m ai.ingestion.spreadsheet_loader

Supported:
    .xlsx
    .xlsm (read-only, macros never executed)

Features:
    - Multiple worksheet extraction
    - Row-level RAG documents
    - Tenant-aware document IDs
    - Header validation
    - Formula cached-value reading
    - Row and sheet metadata
    - JSONL export
    - File and row limits

Notes:
    - Does not calculate formulas.
    - Does not execute macros.
    - Does not support legacy .xls.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable

from openpyxl import load_workbook


@dataclass
class SpreadsheetDocument:
    document_id: str
    title: str
    content: str
    metadata: dict[str, Any] = field(
        default_factory=dict
    )


class RetailSpreadsheetLoader:

    SUPPORTED_EXTENSIONS = {
        ".xlsx",
        ".xlsm",
    }

    def __init__(
        self,
        max_file_mb: int = 25,
        max_sheets: int = 50,
        max_rows_per_sheet: int = 100000,
        max_columns: int = 200,
        max_cell_chars: int = 10000,
    ):
        self.max_file_mb = max_file_mb
        self.max_sheets = max_sheets
        self.max_rows_per_sheet = (
            max_rows_per_sheet
        )
        self.max_columns = max_columns
        self.max_cell_chars = max_cell_chars

    @staticmethod
    def _make_id(
        tenant_id: str,
        source_key: str,
        sheet_name: str,
        row_key: str,
    ) -> str:
        raw = "|".join([
            tenant_id,
            source_key,
            sheet_name,
            row_key,
        ])

        return hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()[:24]

    @staticmethod
    def _normalize_value(
        value: Any,
    ) -> Any:
        if value is None:
            return None

        if isinstance(
            value,
            (datetime, date, time),
        ):
            return value.isoformat()

        if isinstance(value, float):
            if not math.isfinite(value):
                return None

        if isinstance(value, str):
            value = value.strip()
            return value if value else None

        if isinstance(
            value,
            (int, float, bool),
        ):
            return value

        return str(value)

    @staticmethod
    def _as_text(value: Any) -> str:
        if value is None:
            return ""

        if isinstance(value, bool):
            return (
                "true" if value else "false"
            )

        return str(value)

    def _validate_file(
        self,
        path: Path,
    ) -> None:
        if not path.is_file():
            raise FileNotFoundError(path)

        if path.is_symlink():
            raise ValueError(
                "Symlink files are not accepted"
            )

        if (
            path.suffix.lower()
            not in self.SUPPORTED_EXTENSIONS
        ):
            raise ValueError(
                "Only .xlsx and .xlsm supported"
            )

        if (
            path.stat().st_size
            > self.max_file_mb * 1024 * 1024
        ):
            raise ValueError(
                "Spreadsheet exceeds size limit"
            )

    def _read_headers(
        self,
        row: Iterable[Any],
    ) -> list[str]:
        headers = []

        for index, value in enumerate(
            row,
            start=1,
        ):
            normalized = (
                self._normalize_value(value)
            )

            if normalized is None:
                header = (
                    f"column_{index}"
                )
            else:
                header = str(normalized)

            headers.append(header)

        if len(headers) > self.max_columns:
            raise ValueError(
                "Too many spreadsheet columns"
            )

        if len(headers) != len(
            set(headers)
        ):
            raise ValueError(
                "Duplicate spreadsheet headers"
            )

        return headers

    def load(
        self,
        file_path: str | Path,
        tenant_id: str,
        category: str = "spreadsheet",
        sheet_names: list[str] | None = None,
        required_columns: list[str] | None = None,
        id_column: str | None = None,
        source_key: str | None = None,
        metadata_columns: list[str] | None = None,
    ) -> list[SpreadsheetDocument]:

        if (
            not isinstance(tenant_id, str)
            or not tenant_id.strip()
        ):
            raise ValueError(
                "tenant_id is required"
            )

        if not category.strip():
            raise ValueError(
                "category is required"
            )

        path = Path(file_path)
        self._validate_file(path)

        source_key = (
            source_key or path.name
        )

        required_columns = (
            required_columns or []
        )

        metadata_columns = (
            metadata_columns or []
        )

        documents = []
        seen_ids = set()

        workbook = load_workbook(
            filename=path,
            read_only=True,
            data_only=True,
            keep_links=False,
        )

        try:
            available_sheets = (
                workbook.sheetnames
            )

            selected_sheets = (
                sheet_names
                if sheet_names is not None
                else available_sheets
            )

            if len(selected_sheets) > self.max_sheets:
                raise ValueError(
                    "Too many worksheets"
                )

            if len(selected_sheets) != len(
                set(selected_sheets)
            ):
                raise ValueError(
                    "Duplicate worksheet selection"
                )

            unknown = [
                name
                for name in selected_sheets
                if name not in available_sheets
            ]

            if unknown:
                raise ValueError(
                    f"Unknown worksheets: {unknown}"
                )

            for sheet_name in selected_sheets:
                sheet = workbook[
                    sheet_name
                ]

                row_iterator = sheet.iter_rows(
                    values_only=True
                )

                try:
                    header_row = next(
                        row_iterator
                    )
                except StopIteration:
                    continue

                headers = self._read_headers(
                    header_row
                )

                if not headers:
                    continue

                missing = [
                    name
                    for name in required_columns
                    if name not in headers
                ]

                if missing:
                    raise ValueError(
                        f"Sheet {sheet_name}: "
                        f"missing columns {missing}"
                    )

                if (
                    id_column
                    and id_column not in headers
                ):
                    raise ValueError(
                        f"Sheet {sheet_name}: "
                        "ID column not found"
                    )

                missing_metadata = [
                    name
                    for name in metadata_columns
                    if name not in headers
                ]

                if missing_metadata:
                    raise ValueError(
                        f"Sheet {sheet_name}: "
                        "metadata columns missing: "
                        f"{missing_metadata}"
                    )

                # Header is row 1.
                # Data starts at Excel row 2.
                for row_number, row in enumerate(
                    row_iterator,
                    start=2,
                ):
                    if (
                        row_number - 1
                        > self.max_rows_per_sheet
                    ):
                        raise ValueError(
                            f"Sheet {sheet_name}: "
                            "row limit exceeded"
                        )

                    if len(row) > self.max_columns:
                        raise ValueError(
                            "Column limit exceeded"
                        )

                    values = {}

                    for index, header in enumerate(
                        headers
                    ):
                        raw = (
                            row[index]
                            if index < len(row)
                            else None
                        )

                        normalized = (
                            self._normalize_value(
                                raw
                            )
                        )

                        if normalized is None:
                            continue

                        if (
                            len(
                                self._as_text(
                                    normalized
                                )
                            )
                            > self.max_cell_chars
                        ):
                            raise ValueError(
                                "Cell text too long: "
                                f"{sheet_name}!{row_number}"
                            )

                        values[header] = normalized

                    if not values:
                        continue

                    if id_column:
                        raw_key = values.get(
                            id_column
                        )

                        if raw_key is None:
                            raise ValueError(
                                f"Missing row ID at "
                                f"{sheet_name}!{row_number}"
                            )

                        row_key = self._as_text(
                            raw_key
                        )
                    else:
                        row_key = str(
                            row_number
                        )

                    document_id = (
                        self._make_id(
                            tenant_id,
                            source_key,
                            sheet_name,
                            row_key,
                        )
                    )

                    if document_id in seen_ids:
                        raise ValueError(
                            "Duplicate spreadsheet "
                            f"row ID: {row_key}"
                        )

                    seen_ids.add(
                        document_id
                    )

                    content = "\n".join(
                        f"{key}: "
                        f"{self._as_text(value)}"
                        for key, value
                        in values.items()
                    )

                    metadata = {
                        "tenant_id": tenant_id,
                        "category": category,
                        "source_type": (
                            "spreadsheet"
                        ),
                        "source_file": path.name,
                        "source_key": source_key,
                        "sheet_name": sheet_name,
                        "row_number": row_number,
                        "row_key": row_key,
                    }

                    for column in metadata_columns:
                        metadata[column] = (
                            values.get(column)
                        )

                    documents.append(
                        SpreadsheetDocument(
                            document_id=document_id,
                            title=(
                                f"{path.stem} / "
                                f"{sheet_name} / "
                                f"{row_key}"
                            ),
                            content=content,
                            metadata=metadata,
                        )
                    )

        finally:
            workbook.close()

        return documents

    @staticmethod
    def export_jsonl(
        documents: list[
            SpreadsheetDocument
        ],
        output_path: str | Path,
    ) -> Path:

        output = Path(output_path)

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with output.open(
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
                            "content": document.content,
                            "metadata": (
                                document.metadata
                            ),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        return output


if __name__ == "__main__":
    from openpyxl import Workbook

    demo = Path(
        "data/spreadsheets/"
        "retail_inventory.xlsx"
    )

    demo.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not demo.exists():
        workbook = Workbook()

        inventory = workbook.active
        inventory.title = "Inventory"

        inventory.append([
            "sku",
            "warehouse",
            "stock",
            "reorder_point",
        ])

        inventory.append([
            "SKU001", "A", 120, 50
        ])

        inventory.append([
            "SKU002", "B", 15, 40
        ])

        suppliers = (
            workbook.create_sheet(
                "Suppliers"
            )
        )

        suppliers.append([
            "supplier_id",
            "supplier_name",
            "lead_time_days",
        ])

        suppliers.append([
            "SUP002",
            "Retail Supplier Ltd",
            8,
        ])

        workbook.save(
            demo
        )

    loader = RetailSpreadsheetLoader()

    documents = loader.load(
        file_path=demo,
        tenant_id="demo",
        category="retail_operations",
        metadata_columns=[],
    )

    print(
        json.dumps(
            [
                document.__dict__
                for document in documents
            ],
            indent=2,
        )
    )

    loader.export_jsonl(
        documents,
        "data/processed/"
        "retail_spreadsheet.jsonl",
    )
