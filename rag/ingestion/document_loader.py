"""Planned module: document loader. Implementation pending."""

"""
ai/ingestion/document_loader.py

Autonomous Retail Supply Chain AI 5.0
Multi-Format Document Loader

Install:
    pip install pymupdf python-docx \
        beautifulsoup4

Run:
    python -m ai.ingestion.document_loader

Supported:
    .pdf .docx .txt .md .html .htm .json

Important:
- Scanned PDFs require OCR.
- Extraction does not validate document truth.
- Use sandboxing and malware scanning
  for untrusted uploads.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz
from bs4 import BeautifulSoup
from docx import Document


@dataclass
class LoadedDocument:
    document_id: str
    title: str
    content: str
    metadata: dict[str, Any] = field(
        default_factory=dict
    )


class RetailDocumentLoader:

    SUPPORTED_EXTENSIONS = {
        ".pdf",
        ".docx",
        ".txt",
        ".md",
        ".html",
        ".htm",
        ".json",
    }

    def __init__(
        self,
        max_file_mb=25,
        max_text_chars=500000,
    ):
        self.max_file_mb = max_file_mb
        self.max_text_chars = (
            max_text_chars
        )

    @staticmethod
    def _normalize_text(text):
        return "\n".join(
            line.strip()
            for line in text.splitlines()
            if line.strip()
        )

    @staticmethod
    def _document_id(
        tenant_id,
        source_key,
        unit_id,
    ):
        raw = (
            f"{tenant_id}|"
            f"{source_key}|"
            f"{unit_id}"
        )

        return hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()[:24]

    def _validate_file(self, path):
        if not path.is_file():
            raise FileNotFoundError(
                path
            )

        if (
            path.suffix.lower()
            not in self.SUPPORTED_EXTENSIONS
        ):
            raise ValueError(
                "Unsupported document format"
            )

        if (
            path.stat().st_size
            > self.max_file_mb * 1024 * 1024
        ):
            raise ValueError(
                "Document exceeds size limit"
            )

    @staticmethod
    def _load_pdf(path):
        pages = []

        with fitz.open(path) as pdf:
            for index, page in enumerate(
                pdf,
                start=1,
            ):
                text = page.get_text(
                    "text"
                )

                pages.append(
                    {
                        "unit_id": (
                            f"page-{index}"
                        ),
                        "page": index,
                        "text": text,
                    }
                )

        return pages

    @staticmethod
    def _load_docx(path):
        document = Document(
            path
        )

        paragraphs = [
            paragraph.text
            for paragraph
            in document.paragraphs
            if paragraph.text.strip()
        ]

        tables = []

        for table in document.tables:
            for row in table.rows:
                cells = [
                    cell.text.strip()
                    for cell in row.cells
                ]

                tables.append(
                    " | ".join(cells)
                )

        text = "\n".join(
            paragraphs + tables
        )

        return [
            {
                "unit_id": "document",
                "page": None,
                "text": text,
            }
        ]

    @staticmethod
    def _load_html(path):
        html = path.read_text(
            encoding="utf-8"
        )

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        for tag in soup([
            "script",
            "style",
            "noscript",
        ]):
            tag.decompose()

        text = soup.get_text(
            separator="\n"
        )

        return [
            {
                "unit_id": "document",
                "page": None,
                "text": text,
            }
        ]

    @staticmethod
    def _load_json(path):
        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        text = json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        )

        return [
            {
                "unit_id": "document",
                "page": None,
                "text": text,
            }
        ]

    @staticmethod
    def _load_text(path):
        text = path.read_text(
            encoding="utf-8"
        )

        return [
            {
                "unit_id": "document",
                "page": None,
                "text": text,
            }
        ]

    def _extract(self, path):
        extension = path.suffix.lower()

        if extension == ".pdf":
            return self._load_pdf(
                path
            )

        if extension == ".docx":
            return self._load_docx(
                path
            )

        if extension in (
            ".html",
            ".htm",
        ):
            return self._load_html(
                path
            )

        if extension == ".json":
            return self._load_json(
                path
            )

        return self._load_text(
            path
        )

    def load(
        self,
        file_path,
        tenant_id,
        category="general",
        source_key=None,
    ):
        if not tenant_id:
            raise ValueError(
                "tenant_id required"
            )

        path = Path(
            file_path
        )

        self._validate_file(
            path
        )

        source_key = (
            source_key or path.name
        )

        extracted = self._extract(
            path
        )

        documents = []

        total_chars = 0

        for unit in extracted:
            text = self._normalize_text(
                unit["text"]
            )

            if not text:
                continue

            total_chars += len(
                text
            )

            if (
                total_chars
                > self.max_text_chars
            ):
                raise ValueError(
                    "Extracted text exceeds limit"
                )

            unit_id = unit[
                "unit_id"
            ]

            document_id = (
                self._document_id(
                    tenant_id,
                    source_key,
                    unit_id,
                )
            )

            metadata = {
                "tenant_id": tenant_id,
                "category": category,
                "source_type": (
                    path.suffix.lower()
                    .lstrip(".")
                ),
                "source_file": path.name,
                "source_key": source_key,
                "page": unit["page"],
                "unit_id": unit_id,
            }

            documents.append(
                LoadedDocument(
                    document_id=document_id,
                    title=path.stem,
                    content=text,
                    metadata=metadata,
                )
            )

        return documents

    @staticmethod
    def export_jsonl(
        documents,
        output_path,
    ):
        path = Path(
            output_path
        )

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
                        document.__dict__,
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        return path


if __name__ == "__main__":
    demo_file = Path(
        "data/documents/"
        "supplier_policy.txt"
    )

    demo_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not demo_file.exists():
        demo_file.write_text(
            "Supplier Delivery Policy\n"
            "Standard delivery: 7 days.\n"
            "Escalate delays above 10 days.\n",
            encoding="utf-8",
        )

    loader = RetailDocumentLoader()

    documents = loader.load(
        file_path=demo_file,
        tenant_id="demo",
        category="supplier_policy",
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
        "data/processed/"
        "supplier_policy.jsonl",
    )
