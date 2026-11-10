"""Planned module: pdf loader. Implementation pending."""

"""
ai/ingestion/pdf_loader.py

Autonomous Retail Supply Chain AI 5.0
PDF Loader with OCR Fallback

Dependencies:
    pip install pymupdf pillow pytesseract

Requires:
    ai.ingestion.ocr_loader

Run:
    python -m ai.ingestion.pdf_loader

Features:
- Native PDF text extraction
- OCR fallback for scanned pages
- Page-level source tracking
- Basic table extraction
- Content hashing
- Tenant metadata
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz
from PIL import Image

from ai.ingestion.ocr_loader import (
    RetailOCRLoader,
)


@dataclass
class PDFDocument:
    document_id: str
    title: str
    content: str
    metadata: dict[str, Any] = field(
        default_factory=dict
    )


class RetailPDFLoader:

    def __init__(
        self,
        min_native_chars=40,
        max_file_mb=25,
        max_pages=100,
        ocr_dpi=200,
    ):
        self.min_native_chars = (
            min_native_chars
        )
        self.max_file_mb = max_file_mb
        self.max_pages = max_pages
        self.ocr_dpi = ocr_dpi

        self.ocr_loader = RetailOCRLoader(
            dpi=ocr_dpi,
            max_file_mb=max_file_mb,
            max_pages=max_pages,
        )

    @staticmethod
    def _make_id(
        tenant_id,
        source_key,
        page_number,
    ):
        value = (
            f"{tenant_id}|{source_key}|"
            f"page-{page_number}"
        )

        return hashlib.sha256(
            value.encode("utf-8")
        ).hexdigest()[:24]

    @staticmethod
    def _normalize(text):
        return "\n".join(
            line.strip()
            for line in text.splitlines()
            if line.strip()
        )

    @staticmethod
    def _extract_tables(page):
        tables = []

        try:
            found = page.find_tables()

            for table in found.tables:
                rows = table.extract()

                formatted_rows = []

                for row in rows:
                    formatted_rows.append(
                        " | ".join(
                            str(cell or "").strip()
                            for cell in row
                        )
                    )

                if formatted_rows:
                    tables.append(
                        "\n".join(
                            formatted_rows
                        )
                    )

        except (
            AttributeError,
            ValueError,
            RuntimeError,
        ):
            # Table extraction is best effort.
            pass

        return tables

    def _ocr_page(self, page):
        pixmap = page.get_pixmap(
            dpi=self.ocr_dpi,
            alpha=False,
        )

        if (
            pixmap.width * pixmap.height
            > self.ocr_loader.max_pixels
        ):
            raise ValueError(
                "Rendered PDF page too large"
            )

        image = Image.frombytes(
            "RGB",
            [
                pixmap.width,
                pixmap.height,
            ],
            pixmap.samples,
        )

        return self.ocr_loader.recognize(
            image
        )

    def load(
        self,
        file_path,
        tenant_id,
        category="pdf_document",
        source_key=None,
    ):
        if not tenant_id:
            raise ValueError(
                "tenant_id required"
            )

        path = Path(file_path)

        if not path.is_file():
            raise FileNotFoundError(path)

        if path.suffix.lower() != ".pdf":
            raise ValueError(
                "Expected PDF"
            )

        if (
            path.stat().st_size
            > self.max_file_mb * 1024 * 1024
        ):
            raise ValueError(
                "PDF exceeds size limit"
            )

        source_key = (
            source_key or path.name
        )

        documents = []

        with fitz.open(path) as pdf:
            if pdf.needs_pass:
                raise ValueError(
                    "Password-protected PDF"
                )

            if len(pdf) > self.max_pages:
                raise ValueError(
                    "PDF exceeds page limit"
                )

            for page_number, page in enumerate(
                pdf,
                start=1,
            ):
                native_text = (
                    self._normalize(
                        page.get_text(
                            "text"
                        )
                    )
                )

                tables = (
                    self._extract_tables(
                        page
                    )
                )

                extraction_method = (
                    "native"
                )
                ocr_confidence = None

                if (
                    len(native_text)
                    < self.min_native_chars
                ):
                    ocr_result = (
                        self._ocr_page(
                            page
                        )
                    )

                    if ocr_result[
                        "text"
                    ].strip():
                        native_text = (
                            ocr_result[
                                "text"
                            ]
                        )

                        extraction_method = (
                            "ocr"
                        )

                        ocr_confidence = (
                            ocr_result[
                                "confidence"
                            ]
                        )

                if not native_text and not tables:
                    continue

                content = native_text

                if tables:
                    content += (
                        "\n\nExtracted tables:\n"
                        + "\n\n".join(
                            tables
                        )
                    )

                content = content.strip()

                content_sha256 = (
                    hashlib.sha256(
                        content.encode(
                            "utf-8"
                        )
                    ).hexdigest()
                )

                documents.append(
                    PDFDocument(
                        document_id=self._make_id(
                            tenant_id,
                            source_key,
                            page_number,
                        ),
                        title=path.stem,
                        content=content,
                        metadata={
                            "tenant_id": tenant_id,
                            "category": category,
                            "source_type": "pdf",
                            "source_file": path.name,
                            "source_key": source_key,
                            "page": page_number,
                            "extraction_method": (
                                extraction_method
                            ),
                            "ocr_confidence": (
                                ocr_confidence
                            ),
                            "table_count": len(
                                tables
                            ),
                            "content_sha256": (
                                content_sha256
                            ),
                        },
                    )
                )

        return documents

    @staticmethod
    def export_jsonl(
        documents,
        output_path,
    ):
        output = Path(
            output_path
        )

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
                        document.__dict__,
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        return output


if __name__ == "__main__":
    sample = Path(
        "data/documents/"
        "supplier_contract.pdf"
    )

    if sample.exists():
        loader = RetailPDFLoader()

        documents = loader.load(
            sample,
            tenant_id="demo",
            category="supplier_contract",
        )

        print(
            json.dumps(
                [
                    doc.__dict__
                    for doc in documents
                ],
                indent=2,
            )
        )
    else:
        print(
            "Place supplier_contract.pdf "
            "in data/documents/ to test."
        )
