
"""
ai/ingestion/ocr_loader.py

Autonomous Retail Supply Chain AI 5.0
OCR Loader

Dependencies:
    pip install pytesseract pillow pymupdf

Also install Tesseract OCR executable.

Linux:
    sudo apt install tesseract-ocr

Run:
    python -m ai.ingestion.ocr_loader

Notes:
- OCR is probabilistic and may misread
  quantities, dates, prices, and IDs.
- Never approve financial or inventory
  actions based solely on OCR text.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz
import pytesseract
from PIL import Image, ImageOps, ImageFilter


@dataclass
class OCRDocument:
    document_id: str
    title: str
    content: str
    metadata: dict[str, Any] = field(
        default_factory=dict
    )


class RetailOCRLoader:

    IMAGE_TYPES = {
        ".png", ".jpg", ".jpeg",
        ".tif", ".tiff", ".bmp",
        ".webp",
    }

    def __init__(
        self,
        language="eng",
        dpi=200,
        min_confidence=0.0,
        max_file_mb=25,
        max_pages=100,
        max_pixels=20_000_000,
        timeout=30,
    ):
        self.language = language
        self.dpi = dpi
        self.min_confidence = (
            min_confidence
        )
        self.max_file_mb = max_file_mb
        self.max_pages = max_pages
        self.max_pixels = max_pixels
        self.timeout = timeout

    @staticmethod
    def _make_id(
        tenant_id,
        source_key,
        unit_id,
    ):
        value = (
            f"{tenant_id}|{source_key}|"
            f"{unit_id}"
        )

        return hashlib.sha256(
            value.encode("utf-8")
        ).hexdigest()[:24]

    def _validate_path(self, path):
        if not path.is_file():
            raise FileNotFoundError(path)

        if (
            path.stat().st_size
            > self.max_file_mb * 1024 * 1024
        ):
            raise ValueError(
                "OCR file exceeds size limit"
            )

    def preprocess(self, image):
        image = ImageOps.exif_transpose(
            image
        )

        if (
            image.width * image.height
            > self.max_pixels
        ):
            raise ValueError(
                "Image pixel limit exceeded"
            )

        image = ImageOps.grayscale(
            image
        )

        image = ImageOps.autocontrast(
            image
        )

        image = image.filter(
            ImageFilter.MedianFilter(
                size=3
            )
        )

        return image

    def recognize(self, image):
        processed = self.preprocess(
            image
        )

        data = pytesseract.image_to_data(
            processed,
            lang=self.language,
            config="--psm 3",
            output_type=(
                pytesseract.Output.DICT
            ),
            timeout=self.timeout,
        )

        words = []
        confidences = []

        for text, confidence in zip(
            data["text"],
            data["conf"],
        ):
            text = text.strip()

            try:
                score = float(
                    confidence
                )
            except (
                ValueError,
                TypeError,
            ):
                continue

            if not text or score < 0:
                continue

            if (
                score
                < self.min_confidence
            ):
                continue

            words.append(text)
            confidences.append(score)

        content = " ".join(
            words
        )

        mean_confidence = (
            sum(confidences)
            / len(confidences)
            if confidences
            else 0.0
        )

        return {
            "text": content,
            "confidence": round(
                mean_confidence,
                2,
            ),
            "word_count": len(words),
        }

    def load_image(
        self,
        file_path,
        tenant_id,
        category="scanned_document",
        source_key=None,
    ):
        if not tenant_id:
            raise ValueError(
                "tenant_id required"
            )

        path = Path(file_path)
        self._validate_path(path)

        if (
            path.suffix.lower()
            not in self.IMAGE_TYPES
        ):
            raise ValueError(
                "Unsupported image format"
            )

        source_key = (
            source_key or path.name
        )

        with Image.open(path) as image:
            result = self.recognize(
                image
            )

        if not result["text"].strip():
            return []

        return [
            OCRDocument(
                document_id=self._make_id(
                    tenant_id,
                    source_key,
                    "image-1",
                ),
                title=path.stem,
                content=result["text"],
                metadata={
                    "tenant_id": tenant_id,
                    "category": category,
                    "source_type": "image_ocr",
                    "source_file": path.name,
                    "source_key": source_key,
                    "page": None,
                    "ocr_language": self.language,
                    "ocr_confidence": (
                        result["confidence"]
                    ),
                    "ocr_word_count": (
                        result["word_count"]
                    ),
                },
            )
        ]

    def load_pdf(
        self,
        file_path,
        tenant_id,
        category="scanned_pdf",
        source_key=None,
    ):
        if not tenant_id:
            raise ValueError(
                "tenant_id required"
            )

        path = Path(file_path)
        self._validate_path(path)

        if path.suffix.lower() != ".pdf":
            raise ValueError(
                "Expected PDF"
            )

        source_key = (
            source_key or path.name
        )

        documents = []

        with fitz.open(path) as pdf:
            if len(pdf) > self.max_pages:
                raise ValueError(
                    "PDF page limit exceeded"
                )

            for index, page in enumerate(
                pdf,
                start=1,
            ):
                pixmap = page.get_pixmap(
                    dpi=self.dpi,
                    alpha=False,
                )

                if (
                    pixmap.width
                    * pixmap.height
                    > self.max_pixels
                ):
                    raise ValueError(
                        "Rendered page too large"
                    )

                image = Image.frombytes(
                    "RGB",
                    [
                        pixmap.width,
                        pixmap.height,
                    ],
                    pixmap.samples,
                )

                result = self.recognize(
                    image
                )

                if not result["text"].strip():
                    continue

                documents.append(
                    OCRDocument(
                        document_id=self._make_id(
                            tenant_id,
                            source_key,
                            f"page-{index}",
                        ),
                        title=path.stem,
                        content=result["text"],
                        metadata={
                            "tenant_id": tenant_id,
                            "category": category,
                            "source_type": "pdf_ocr",
                            "source_file": path.name,
                            "source_key": source_key,
                            "page": index,
                            "ocr_language": self.language,
                            "ocr_confidence": (
                                result["confidence"]
                            ),
                            "ocr_word_count": (
                                result["word_count"]
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
                        document.__dict__,
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        return path


if __name__ == "__main__":
    loader = RetailOCRLoader()

    demo = Path(
        "data/documents/"
        "sample_invoice.png"
    )

    if demo.exists():
        documents = loader.load_image(
            demo,
            tenant_id="demo",
            category="invoice",
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
            "Place sample_invoice.png "
            "in data/documents/ to test OCR."
        )
