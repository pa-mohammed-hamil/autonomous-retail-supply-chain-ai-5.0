"""Planned module: contextual compression. Implementation pending."""

"""
ai/ingestion/text_cleaner.py

Autonomous Retail Supply Chain AI 5.0

Retail Document Text Cleaning Engine

Python 3.10+
Standard library only.

Features:
- Unicode normalization
- HTML entity decoding
- Control-character cleanup
- Whitespace normalization
- PDF line-wrap repair
- Optional OCR corrections
- Repeated-line removal
- Optional PII masking
- Retail identifier preservation
- Cleaning statistics
- Batch document processing
- JSONL export

Important:
PII masking is heuristic and is not
a complete DLP or privacy solution.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CleaningConfig:
    unicode_form: str = "NFKC"

    decode_html_entities: bool = True
    remove_control_chars: bool = True
    normalize_whitespace: bool = True
    repair_line_wraps: bool = False
    fix_ocr_artifacts: bool = False
    remove_duplicate_lines: bool = False
    mask_pii: bool = False

    preserve_newlines: bool = True
    max_input_chars: int = 2_000_000
    max_output_chars: int = 2_000_000


@dataclass
class CleaningResult:
    original_length: int
    cleaned_length: int
    original_sha256: str
    cleaned_sha256: str
    cleaned_text: str
    changed: bool
    operations: list[str] = field(
        default_factory=list
    )


@dataclass
class CleanedDocument:
    document_id: str
    title: str
    content: str
    metadata: dict[str, Any] = field(
        default_factory=dict
    )


class RetailTextCleaner:

    EMAIL_PATTERN = re.compile(
        r"(?<![\w.+-])"
        r"[A-Z0-9._%+-]+@"
        r"[A-Z0-9.-]+\.[A-Z]{2,}"
        r"(?![\w.-])",
        re.IGNORECASE,
    )

    PHONE_PATTERN = re.compile(
        r"(?<!\w)"
        r"(?:\+91[\s-]?)?"
        r"[6-9]\d{9}"
        r"(?!\w)"
    )

    CONTROL_PATTERN = re.compile(
        r"[\x00-\x08\x0b\x0c"
        r"\x0e-\x1f\x7f]"
    )

    SPACE_PATTERN = re.compile(
        r"[^\S\n]+"
    )

    BLANK_LINES_PATTERN = re.compile(
        r"\n{3,}"
    )

    OCR_CORRECTIONS = {
        "\ufeff": "",
        "\u200b": "",
        "\u00ad": "",
        "\u00a0": " ",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
    }

    def __init__(
        self,
        config: CleaningConfig | None = None,
    ):
        self.config = (
            config or CleaningConfig()
        )

        if self.config.unicode_form not in {
            "NFC", "NFD", "NFKC", "NFKD"
        }:
            raise ValueError(
                "Invalid Unicode normalization"
            )

        if self.config.max_input_chars <= 0:
            raise ValueError(
                "max_input_chars must be positive"
            )

        if self.config.max_output_chars <= 0:
            raise ValueError(
                "max_output_chars must be positive"
            )

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _normalize_newlines(
        text: str,
    ) -> str:
        return (
            text.replace("\r\n", "\n")
            .replace("\r", "\n")
        )

    def _normalize_unicode(
        self,
        text: str,
    ) -> str:
        return unicodedata.normalize(
            self.config.unicode_form,
            text,
        )

    def _remove_controls(
        self,
        text: str,
    ) -> str:
        return self.CONTROL_PATTERN.sub(
            "",
            text,
        )

    def _normalize_spaces(
        self,
        text: str,
    ) -> str:
        text = "\n".join(
            self.SPACE_PATTERN.sub(
                " ",
                line,
            ).strip()
            for line in text.split("\n")
        )

        text = self.BLANK_LINES_PATTERN.sub(
            "\n\n",
            text,
        )

        if not self.config.preserve_newlines:
            text = " ".join(
                text.split()
            )

        return text.strip()

    @staticmethod
    def _repair_wrapped_lines(
        text: str,
    ) -> str:
        """
        Conservative line-wrap repair.

        Joins a line ending in a letter
        to the next line beginning with
        a lowercase letter.

        Does not alter hyphenated words,
        tables, or numbered lists.
        """
        return re.sub(
            r"(?<=[A-Za-z])\n"
            r"(?=[a-z])",
            " ",
            text,
        )

    def _fix_ocr(
        self,
        text: str,
    ) -> str:
        for wrong, correct in (
            self.OCR_CORRECTIONS.items()
        ):
            text = text.replace(
                wrong,
                correct,
            )

        # Intentionally avoid global
        # 0/O and 1/I substitutions:
        # these can corrupt SKU IDs,
        # invoice numbers, and prices.
        return text

    @staticmethod
    def _remove_repeated_lines(
        text: str,
    ) -> str:
        """
        Remove consecutive duplicate lines.

        Do not remove nonconsecutive lines:
        repeated SKU or transaction records
        may be legitimate.
        """
        lines = text.split("\n")
        result = []
        previous = None

        for line in lines:
            normalized = line.strip()

            if (
                normalized
                and normalized == previous
            ):
                continue

            result.append(line)
            previous = (
                normalized
                if normalized
                else None
            )

        return "\n".join(result)

    def _mask_pii(
        self,
        text: str,
    ) -> str:
        text = self.EMAIL_PATTERN.sub(
            "[EMAIL_REDACTED]",
            text,
        )

        text = self.PHONE_PATTERN.sub(
            "[PHONE_REDACTED]",
            text,
        )

        return text

    def clean(
        self,
        text: str,
    ) -> CleaningResult:

        if not isinstance(text, str):
            raise TypeError(
                "Expected string input"
            )

        if (
            len(text)
            > self.config.max_input_chars
        ):
            raise ValueError(
                "Text exceeds input limit"
            )

        original = text
        operations = []

        def apply(
            name,
            transform,
        ):
            nonlocal text

            updated = transform(text)

            if updated != text:
                operations.append(name)

            text = updated

        apply(
            "newline_normalization",
            self._normalize_newlines,
        )

        apply(
            "unicode_normalization",
            self._normalize_unicode,
        )

        if self.config.decode_html_entities:
            apply(
                "html_entity_decoding",
                html.unescape,
            )

        if self.config.remove_control_chars:
            apply(
                "control_character_removal",
                self._remove_controls,
            )

        if self.config.fix_ocr_artifacts:
            apply(
                "ocr_artifact_correction",
                self._fix_ocr,
            )

        if self.config.repair_line_wraps:
            apply(
                "line_wrap_repair",
                self._repair_wrapped_lines,
            )

        if self.config.remove_duplicate_lines:
            apply(
                "consecutive_duplicate_removal",
                self._remove_repeated_lines,
            )

        if self.config.mask_pii:
            apply(
                "pii_masking",
                self._mask_pii,
            )

        if self.config.normalize_whitespace:
            apply(
                "whitespace_normalization",
                self._normalize_spaces,
            )

        if (
            len(text)
            > self.config.max_output_chars
        ):
            raise ValueError(
                "Text exceeds output limit"
            )

        return CleaningResult(
            original_length=len(original),
            cleaned_length=len(text),
            original_sha256=self._hash(
                original
            ),
            cleaned_sha256=self._hash(
                text
            ),
            cleaned_text=text,
            changed=(original != text),
            operations=operations,
        )

    def clean_document(
        self,
        document: Any,
        tenant_id: str,
    ) -> CleanedDocument:

        if not tenant_id.strip():
            raise ValueError(
                "tenant_id required"
            )

        metadata = dict(
            getattr(
                document,
                "metadata",
                {},
            )
        )

        existing_tenant = (
            metadata.get("tenant_id")
        )

        if (
            existing_tenant is not None
            and existing_tenant != tenant_id
        ):
            raise ValueError(
                "Tenant metadata mismatch"
            )

        result = self.clean(
            document.content
        )

        metadata.update({
            "tenant_id": tenant_id,
            "cleaning_applied": True,
            "cleaning_changed": (
                result.changed
            ),
            "cleaning_operations": (
                result.operations
            ),
            "original_content_sha256": (
                result.original_sha256
            ),
            "cleaned_content_sha256": (
                result.cleaned_sha256
            ),
            "original_char_count": (
                result.original_length
            ),
            "cleaned_char_count": (
                result.cleaned_length
            ),
        })

        return CleanedDocument(
            document_id=(
                document.document_id
            ),
            title=getattr(
                document,
                "title",
                "",
            ),
            content=result.cleaned_text,
            metadata=metadata,
        )

    def clean_documents(
        self,
        documents,
        tenant_id: str,
    ) -> list[CleanedDocument]:
        return [
            self.clean_document(
                document,
                tenant_id,
            )
            for document in documents
        ]

    @staticmethod
    def export_jsonl(
        documents,
        output_path,
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
                        asdict(document),
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        return output


if __name__ == "__main__":
    sample = (
        "Retail  Inventory   Report\r\n"
        "\r\n"
        "SKU001   stock:  120 units\n"
        "SKU001   stock:  120 units\n"
        "Supplier SUP002 delivered "
        "on 2026-10-20.\n"
        "Contact: manager@example.com\n"
        "Price: ₹25,500.00\n"
        "Warehouse  WH-01"
    )

    cleaner = RetailTextCleaner(
        CleaningConfig(
            normalize_whitespace=True,
            fix_ocr_artifacts=True,
            remove_duplicate_lines=True,
            mask_pii=True,
        )
    )

    result = cleaner.clean(
        sample
    )

    print(
        json.dumps(
            asdict(result),
            indent=2,
            ensure_ascii=False,
        )
    )
