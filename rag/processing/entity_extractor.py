"""Planned module: entity extractor. Implementation pending."""

"""
ai/ingestion/entity_extractor.py

Autonomous Retail Supply Chain AI 5.0

Retail Entity Extraction Engine

Python standard library only.

Extracts:
- SKU identifiers
- Supplier identifiers
- Purchase order IDs
- Invoice IDs
- Warehouse IDs
- ISO dates
- Quantities with units
- Monetary amounts

Uses deterministic patterns.
Confidence values are heuristic.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RetailEntity:
    entity_id: str
    entity_type: str
    value: str
    normalized_value: str
    start: int
    end: int
    confidence: float
    metadata: dict[str, Any] = field(
        default_factory=dict
    )


@dataclass
class EntityExtractionResult:
    document_id: str
    tenant_id: str
    entities: list[RetailEntity]
    entity_counts: dict[str, int]


class RetailEntityExtractor:

    PATTERNS = {
        "sku": (
            r"\bSKU[-_]?[A-Z0-9]{3,20}\b"
        ),
        "supplier_id": (
            r"\bSUP[-_]?[A-Z0-9]{3,20}\b"
        ),
        "purchase_order_id": (
            r"\b(?:PO|PORD)[-_]?"
            r"[A-Z0-9]{3,20}\b"
        ),
        "invoice_id": (
            r"\b(?:INV|INVOICE)[-_]?"
            r"[A-Z0-9]{3,20}\b"
        ),
        "warehouse_id": (
            r"\b(?:WH|WAREHOUSE)[-_]?"
            r"[A-Z0-9]{2,20}\b"
        ),
        "date": (
            r"\b\d{4}-\d{2}-\d{2}\b"
        ),
        "quantity": (
            r"\b\d+(?:\.\d+)?\s*"
            r"(?:units?|pieces?|pcs|kg|"
            r"g|liters?|litres?|l)\b"
        ),
        "money": (
            r"(?<!\w)(?:₹|\$|€|£|INR\s*|"
            r"USD\s*|EUR\s*|GBP\s*)"
            r"\d[\d,]*(?:\.\d{1,2})?"
        ),
    }

    CONFIDENCE = {
        "sku": 0.95,
        "supplier_id": 0.95,
        "purchase_order_id": 0.95,
        "invoice_id": 0.95,
        "warehouse_id": 0.90,
        "date": 0.95,
        "quantity": 0.85,
        "money": 0.90,
    }

    def __init__(
        self,
        max_entities: int = 1000,
        context_chars: int = 45,
    ):
        if max_entities <= 0:
            raise ValueError(
                "max_entities must be positive"
            )

        self.max_entities = max_entities
        self.context_chars = context_chars

        self.compiled = {
            name: re.compile(
                pattern,
                re.IGNORECASE,
            )
            for name, pattern
            in self.PATTERNS.items()
        }

    @staticmethod
    def _make_id(
        tenant_id: str,
        document_id: str,
        entity_type: str,
        start: int,
        end: int,
    ) -> str:
        raw = "|".join([
            tenant_id,
            document_id,
            entity_type,
            str(start),
            str(end),
        ])

        return hashlib.sha256(
            raw.encode("utf-8")
        ).hexdigest()[:24]

    @staticmethod
    def _normalize(
        entity_type: str,
        value: str,
    ) -> str:
        value = " ".join(
            value.strip().split()
        )

        if entity_type in {
            "sku",
            "supplier_id",
            "purchase_order_id",
            "invoice_id",
            "warehouse_id",
        }:
            return value.upper()

        if entity_type == "quantity":
            return value.lower()

        return value

    @staticmethod
    def _valid_date(value: str) -> bool:
        from datetime import date

        try:
            date.fromisoformat(value)
            return True
        except ValueError:
            return False

    def extract(
        self,
        content: str,
        document_id: str,
        tenant_id: str,
    ) -> EntityExtractionResult:

        if not isinstance(content, str):
            raise TypeError(
                "content must be text"
            )

        if not document_id.strip():
            raise ValueError(
                "document_id required"
            )

        if not tenant_id.strip():
            raise ValueError(
                "tenant_id required"
            )

        entities = []

        for entity_type, pattern in (
            self.compiled.items()
        ):
            for match in pattern.finditer(
                content
            ):
                value = match.group()

                if (
                    entity_type == "date"
                    and not self._valid_date(
                        value
                    )
                ):
                    continue

                start, end = match.span()

                context_start = max(
                    0,
                    start - self.context_chars,
                )

                context_end = min(
                    len(content),
                    end + self.context_chars,
                )

                entities.append(
                    RetailEntity(
                        entity_id=self._make_id(
                            tenant_id,
                            document_id,
                            entity_type,
                            start,
                            end,
                        ),
                        entity_type=entity_type,
                        value=value,
                        normalized_value=(
                            self._normalize(
                                entity_type,
                                value,
                            )
                        ),
                        start=start,
                        end=end,
                        confidence=(
                            self.CONFIDENCE[
                                entity_type
                            ]
                        ),
                        metadata={
                            "context": content[
                                context_start:
                                context_end
                            ],
                            "extraction_method": (
                                "regex"
                            ),
                        },
                    )
                )

                if (
                    len(entities)
                    > self.max_entities
                ):
                    raise ValueError(
                        "Entity extraction limit "
                        "exceeded"
                    )

        entities.sort(
            key=lambda entity: (
                entity.start,
                entity.end,
                entity.entity_type,
            )
        )

        counts = {}

        for entity in entities:
            counts[entity.entity_type] = (
                counts.get(
                    entity.entity_type,
                    0,
                ) + 1
            )

        return EntityExtractionResult(
            document_id=document_id,
            tenant_id=tenant_id,
            entities=entities,
            entity_counts=counts,
        )

    def extract_documents(
        self,
        documents,
        tenant_id: str,
    ) -> list[EntityExtractionResult]:
        results = []

        for document in documents:
            metadata = getattr(
                document,
                "metadata",
                {},
            )

            source_tenant = (
                metadata.get("tenant_id")
            )

            if (
                source_tenant is not None
                and source_tenant != tenant_id
            ):
                raise ValueError(
                    "Document tenant mismatch"
                )

            results.append(
                self.extract(
                    content=document.content,
                    document_id=(
                        document.document_id
                    ),
                    tenant_id=tenant_id,
                )
            )

        return results

    @staticmethod
    def export_json(
        results,
        output_path,
    ):
        output = Path(output_path)

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            json.dumps(
                [
                    asdict(result)
                    for result in results
                ],
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return output


if __name__ == "__main__":
    text = (
        "Purchase order PO-10025 was "
        "issued to supplier SUP002 on "
        "2026-10-20. Warehouse WH-01 "
        "received 150 units of SKU001. "
        "Invoice INV-10025 totals "
        "INR 25,500.00."
    )

    extractor = RetailEntityExtractor()

    result = extractor.extract(
        content=text,
        document_id="retail-doc-001",
        tenant_id="demo",
    )

    print(
        json.dumps(
            asdict(result),
            indent=2,
            ensure_ascii=False,
        )
    )
    