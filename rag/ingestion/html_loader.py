"""Planned module: html loader. Implementation pending."""

"""
ai/ingestion/html_loader.py

Autonomous Retail Supply Chain AI 5.0

Structured HTML Document Loader

Install:
    pip install beautifulsoup4 lxml

Run:
    python -m ai.ingestion.html_loader

Supported:
    .html
    .htm

Processes local HTML files.
Does not fetch arbitrary web URLs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


@dataclass
class HTMLChunk:
    document_id: str
    title: str
    content: str
    metadata: dict[str, Any] = field(
        default_factory=dict
    )


class RetailHTMLLoader:

    BLOCK_TAGS = {
        "h1", "h2", "h3",
        "h4", "h5", "h6",
        "p", "li", "table",
    }

    def __init__(
        self,
        max_file_mb=10,
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

    @classmethod
    def _table_text(cls, table):
        lines = []

        for row in table.find_all(
            "tr"
        ):
            cells = row.find_all(
                ["th", "td"],
                recursive=False,
            )

            values = [
                cls._normalize(
                    cell.get_text(
                        separator=" ",
                        strip=True,
                    )
                )
                for cell in cells
            ]

            if any(values):
                lines.append(
                    " | ".join(values)
                )

        return "\n".join(lines)

    def load(
        self,
        file_path,
        tenant_id,
        category="web_document",
        source_key=None,
    ):
        if not tenant_id:
            raise ValueError(
                "tenant_id is required"
            )

        path = Path(file_path)

        if not path.is_file():
            raise FileNotFoundError(path)

        if path.suffix.lower() not in {
            ".html", ".htm"
        }:
            raise ValueError(
                "Expected HTML document"
            )

        if (
            path.stat().st_size
            > self.max_file_mb * 1024 * 1024
        ):
            raise ValueError(
                "HTML exceeds size limit"
            )

        source_key = (
            source_key or path.name
        )

        html = path.read_text(
            encoding="utf-8"
        )

        soup = BeautifulSoup(
            html,
            "lxml",
        )

        title = (
            soup.title.get_text(
                strip=True
            )
            if soup.title
            else path.stem
        )

        for tag in soup([
            "script",
            "style",
            "noscript",
            "svg",
            "iframe",
            "form",
        ]):
            tag.decompose()

        body = soup.body or soup

        chunks = []
        current_section = ""
        total_chars = 0
        block_number = 0

        # Process meaningful blocks while
        # avoiding duplicate text from
        # nested list/table structures.
        for element in body.find_all(
            list(self.BLOCK_TAGS)
        ):
            if element.name != "table":
                if element.find_parent(
                    "table"
                ):
                    continue

            if element.name == "li":
                if element.find_parent(
                    "li"
                ):
                    continue

            if element.name == "table":
                text = self._table_text(
                    element
                )
                block_type = "table"
            else:
                text = self._normalize(
                    element.get_text(
                        separator=" ",
                        strip=True,
                    )
                )
                block_type = (
                    "heading"
                    if element.name.startswith(
                        "h"
                    )
                    else element.name
                )

            if not text:
                continue

            if element.name in {
                "h1", "h2", "h3",
                "h4", "h5", "h6",
            }:
                current_section = text

            total_chars += len(text)

            if total_chars > self.max_chars:
                raise ValueError(
                    "Extracted HTML text "
                    "exceeds limit"
                )

            block_number += 1

            chunks.append(
                HTMLChunk(
                    document_id=self._make_id(
                        tenant_id,
                        source_key,
                        block_number,
                    ),
                    title=title,
                    content=text,
                    metadata={
                        "tenant_id": tenant_id,
                        "category": category,
                        "source_type": "html",
                        "source_file": path.name,
                        "source_key": source_key,
                        "block_number": block_number,
                        "block_type": block_type,
                        "section": current_section,
                        "html_tag": element.name,
                    },
                )
            )

        return chunks

    @staticmethod
    def export_jsonl(
        chunks,
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
        "supplier_portal.html"
    )

    demo.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not demo.exists():
        demo.write_text(
            """
            <!DOCTYPE html>
            <html>
              <head>
                <title>Supplier Portal</title>
              </head>
              <body>
                <h1>Supplier Performance</h1>
                <p>SUP002 delivers in
                   eight days on average.</p>
                <h2>Service Levels</h2>
                <table>
                  <tr>
                    <th>Metric</th>
                    <th>Value</th>
                  </tr>
                  <tr>
                    <td>On-time delivery</td>
                    <td>95%</td>
                  </tr>
                </table>
              </body>
            </html>
            """,
            encoding="utf-8",
        )

    loader = RetailHTMLLoader()

    chunks = loader.load(
        demo,
        tenant_id="demo",
        category="supplier_portal",
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
        "supplier_portal.jsonl",
    )
