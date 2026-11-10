"""Planned module: docx loader. Implementation pending."""

"""
ai/ingestion/docx_loader.py

Autonomous Retail Supply Chain AI 5.0

Structured Microsoft Word Loader

Install:
    pip install python-docx

Run:
    python -m ai.ingestion.docx_loader

Supported:
    .docx

Does not support legacy .doc files.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph


@dataclass
class DOCXChunk:
    document_id: str
    title: str
    content: str
    metadata: dict[str, Any] = field(
        default_factory=dict
    )


class RetailDOCXLoader:

    def __init__(
        self,
        max_file_mb=25,
        max_chars=500000,
    ):
        self.max_file_mb = max_file_mb
        self.max_chars = max_chars

    @staticmethod
    def _make_id(
        tenant_id,
        source_key,
        block_number,
    ):
        raw = (
            f"{tenant_id}|{source_key}|"
            f"{block_number}"
        )

        return hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()[:24]

    @staticmethod
    def _normalize(text):
        return " ".join(
            text.split()
        )

    @staticmethod
    def _table_text(table):
        rows = []

        for row in table.rows:
            cells = [
                " ".join(cell.text.split())
                for cell in row.cells
            ]

            if any(cells):
                rows.append(
                    " | ".join(cells)
                )

        return "\n".join(rows)

    def load(
        self,
        file_path,
        tenant_id,
        category="business_document",
        source_key=None,
    ):
        if not tenant_id:
            raise ValueError(
                "tenant_id is required"
            )

        path = Path(file_path)

        if not path.is_file():
            raise FileNotFoundError(path)

        if path.suffix.lower() != ".docx":
            raise ValueError(
                "Only .docx files supported"
            )

        if (
            path.stat().st_size
            > self.max_file_mb * 1024 * 1024
        ):
            raise ValueError(
                "DOCX exceeds file size limit"
            )

        source_key = (
            source_key or path.name
        )

        document = Document(path)
        chunks = []
        total_chars = 0
        current_heading = ""
        block_number = 0

        # Iterates body paragraphs and
        # tables in document order.
        for block in document.iter_inner_content():

            if isinstance(block, Paragraph):
                text = self._normalize(
                    block.text
                )

                if not text:
                    continue

                style_name = (
                    block.style.name
                    if block.style
                    else ""
                )

                if style_name.lower().startswith(
                    "heading"
                ):
                    current_heading = text
                    block_type = "heading"
                else:
                    block_type = "paragraph"

            elif isinstance(block, Table):
                text = self._table_text(
                    block
                )

                if not text:
                    continue

                block_type = "table"

            else:
                continue

            total_chars += len(text)

            if total_chars > self.max_chars:
                raise ValueError(
                    "Extracted text exceeds limit"
                )

            block_number += 1

            chunks.append(
                DOCXChunk(
                    document_id=self._make_id(
                        tenant_id,
                        source_key,
                        block_number,
                    ),
                    title=path.stem,
                    content=text,
                    metadata={
                        "tenant_id": tenant_id,
                        "category": category,
                        "source_type": "docx",
                        "source_file": path.name,
                        "source_key": source_key,
                        "block_number": block_number,
                        "block_type": block_type,
                        "section": current_heading,
                    },
                )
            )

        return chunks

    @staticmethod
    def export_jsonl(
        chunks,
        output_path,
    ):
        output = Path(output_path)

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with output.open(
            "w",
            encoding="utf-8",
        ) as file:
            for chunk in chunks:
                file.write(
                    json.dumps(
                        chunk.__dict__,
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        return output


if __name__ == "__main__":
    demo = Path(
        "data/documents/"
        "supplier_agreement.docx"
    )

    demo.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not demo.exists():
        doc = Document()

        doc.add_heading(
            "Supplier Agreement",
            level=1,
        )

        doc.add_paragraph(
            "Supplier SUP002 must deliver "
            "goods within eight days."
        )

        doc.add_heading(
            "Delivery Terms",
            level=2,
        )

        doc.add_paragraph(
            "Late deliveries must be "
            "escalated after ten days."
        )

        table = doc.add_table(
            rows=1,
            cols=2,
        )

        table.rows[0].cells[0].text = (
            "Metric"
        )
        table.rows[0].cells[1].text = (
            "Target"
        )

        row = table.add_row()
        row.cells[0].text = (
            "On-time delivery"
        )
        row.cells[1].text = "95%"

        doc.save(demo)

    loader = RetailDOCXLoader()

    chunks = loader.load(
        demo,
        tenant_id="demo",
        category="supplier_agreement",
    )

    print(
        json.dumps(
            [
                chunk.__dict__
                for chunk in chunks
            ],
            indent=2,
        )
    )

    loader.export_jsonl(
        chunks,
        "data/processed/"
        "supplier_agreement.jsonl",
    )
