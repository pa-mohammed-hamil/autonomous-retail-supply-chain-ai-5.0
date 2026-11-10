"""Planned module: hybrid retriever. Implementation pending."""

"""
ai/ingestion/contextual_compression.py

Autonomous Retail Supply Chain AI 5.0

Contextual Compression for Retail RAG

Python 3.10+
Standard library only.

Features:
- Query-aware passage selection
- Retail identifier preservation
- Sentence-level relevance scoring
- Keyword and numeric matching
- Context token-budget estimation
- Deduplication
- Source and citation preservation
- Tenant isolation
- Configurable compression ratio
- Compression statistics
- Batch retrieval-result processing
- JSONL export

This is an extractive compressor.
It does not generate new factual claims.

Relevance scores are heuristic.
Token counts are estimates, not exact
LLM tokenizer counts.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CompressionConfig:
    max_context_chars: int = 12000
    max_passage_chars: int = 3000
    max_documents: int = 8
    min_sentence_score: float = 0.0
    target_compression_ratio: float = 0.65
    preserve_identifiers: bool = True
    preserve_numbers: bool = True
    deduplicate: bool = True
    estimated_chars_per_token: float = 4.0


@dataclass
class CompressedDocument:
    document_id: str
    title: str
    content: str
    original_content: str
    metadata: dict[str, Any] = field(
        default_factory=dict
    )
    relevance_score: float = 0.0
    compression_ratio: float = 1.0
    original_chars: int = 0
    compressed_chars: int = 0


@dataclass
class CompressionResult:
    query: str
    tenant_id: str
    documents: list[CompressedDocument]
    original_characters: int
    compressed_characters: int
    compression_ratio: float
    estimated_tokens: int
    documents_received: int
    documents_retained: int


class RetailContextualCompressor:

    STOPWORDS = {
        "a", "an", "and", "are", "as",
        "at", "be", "by", "for", "from",
        "has", "have", "how", "in", "is",
        "it", "of", "on", "or", "that",
        "the", "their", "this", "to",
        "was", "were", "what", "when",
        "where", "which", "who", "with",
        "would", "should", "could",
        "does", "do", "did", "can",
        "please", "tell", "me", "about",
    }

    TOKEN_PATTERN = re.compile(
        r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*"
    )

    SENTENCE_PATTERN = re.compile(
        r"(?<=[.!?])\s+|\n+"
    )

    RETAIL_ID_PATTERN = re.compile(
        r"\b(?:SKU|SUP|PO|INV|WH)"
        r"[-_]?[A-Z0-9]{2,20}\b",
        re.IGNORECASE,
    )

    NUMBER_PATTERN = re.compile(
        r"(?<!\w)"
        r"(?:₹|\$|€|£)?"
        r"\d[\d,]*(?:\.\d+)?"
        r"%?"
        r"(?!\w)"
    )

    def __init__(
        self,
        config: CompressionConfig | None = None,
    ):
        self.config = (
            config or CompressionConfig()
        )

        if self.config.max_context_chars <= 0:
            raise ValueError(
                "max_context_chars must be positive"
            )

        if self.config.max_passage_chars <= 0:
            raise ValueError(
                "max_passage_chars must be positive"
            )

        if self.config.max_documents <= 0:
            raise ValueError(
                "max_documents must be positive"
            )

        if not (
            0 < self.config.target_compression_ratio
            <= 1
        ):
            raise ValueError(
                "Compression ratio must be "
                "between 0 and 1"
            )

        if (
            self.config.estimated_chars_per_token
            <= 0
        ):
            raise ValueError(
                "Invalid token estimate"
            )

    @classmethod
    def _tokens(cls, text: str) -> set[str]:
        return {
            token.lower()
            for token in cls.TOKEN_PATTERN.findall(
                text
            )
            if token.lower()
            not in cls.STOPWORDS
        }

    @classmethod
    def _identifiers(
        cls,
        text: str,
    ) -> set[str]:
        return {
            match.upper()
            for match in cls.RETAIL_ID_PATTERN.findall(
                text
            )
        }

    @classmethod
    def _numbers(
        cls,
        text: str,
    ) -> set[str]:
        return set(
            cls.NUMBER_PATTERN.findall(
                text
            )
        )

    @staticmethod
    def _split_sentences(
        text: str,
    ) -> list[str]:
        return [
            sentence.strip()
            for sentence in re.split(
                RetailContextualCompressor
                .SENTENCE_PATTERN,
                text,
            )
            if sentence.strip()
        ]

    @staticmethod
    def _hash(
        text: str,
    ) -> str:
        return hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest()

    def _sentence_score(
        self,
        query: str,
        sentence: str,
    ) -> float:
        query_tokens = self._tokens(
            query
        )

        sentence_tokens = self._tokens(
            sentence
        )

        overlap = (
            query_tokens
            & sentence_tokens
        )

        lexical_score = (
            len(overlap)
            / len(query_tokens)
            if query_tokens
            else 0.0
        )

        score = lexical_score

        if self.config.preserve_identifiers:
            query_ids = self._identifiers(
                query
            )

            sentence_ids = self._identifiers(
                sentence
            )

            if query_ids:
                matches = (
                    query_ids
                    & sentence_ids
                )

                score += (
                    2.0
                    * len(matches)
                    / len(query_ids)
                )

        if self.config.preserve_numbers:
            query_numbers = self._numbers(
                query
            )

            sentence_numbers = self._numbers(
                sentence
            )

            if query_numbers:
                score += (
                    0.5
                    * len(
                        query_numbers
                        & sentence_numbers
                    )
                    / len(query_numbers)
                )

        # Modest preference for passages
        # containing concrete retail data.
        if (
            self._identifiers(sentence)
            and overlap
        ):
            score += 0.1

        return round(score, 6)

    def _compress_text(
        self,
        query: str,
        content: str,
        max_chars: int,
    ) -> tuple[str, float]:
        if not content.strip():
            return "", 0.0

        sentences = self._split_sentences(
            content
        )

        if not sentences:
            return "", 0.0

        scored = []

        for index, sentence in enumerate(
            sentences
        ):
            score = self._sentence_score(
                query,
                sentence,
            )

            scored.append(
                (
                    index,
                    sentence,
                    score,
                )
            )

        ranked = sorted(
            scored,
            key=lambda item: (
                -item[2],
                item[0],
            ),
        )

        target_chars = max(
            1,
            min(
                max_chars,
                math.ceil(
                    len(content)
                    * self.config
                    .target_compression_ratio
                ),
            ),
        )

        selected = []
        used_chars = 0

        for index, sentence, score in ranked:
            if (
                score
                < self.config.min_sentence_score
            ):
                continue

            separator = (
                1 if selected else 0
            )

            remaining = (
                target_chars
                - used_chars
                - separator
            )

            if remaining <= 0:
                break

            if len(sentence) <= remaining:
                selected.append(
                    (
                        index,
                        sentence,
                        score,
                    )
                )

                used_chars += (
                    len(sentence)
                    + separator
                )

        # No relevant sentence fits:
        # abstain instead of truncating
        # a sentence or identifier.
        if not selected:
            return "", 0.0

        selected.sort(
            key=lambda item: item[0]
        )

        compressed = " ".join(
            sentence
            for _, sentence, _
            in selected
        )

        best_score = max(
            item[2]
            for item in selected
        )

        return compressed, best_score

    @staticmethod
    def _read_document(
        document: Any,
    ) -> dict[str, Any]:
        if isinstance(document, dict):
            return {
                "document_id": document.get(
                    "document_id",
                    "",
                ),
                "title": document.get(
                    "title",
                    "",
                ),
                "content": document.get(
                    "content",
                    "",
                ),
                "metadata": dict(
                    document.get(
                        "metadata",
                        {},
                    )
                ),
            }

        return {
            "document_id": getattr(
                document,
                "document_id",
                "",
            ),
            "title": getattr(
                document,
                "title",
                "",
            ),
            "content": getattr(
                document,
                "content",
                "",
            ),
            "metadata": dict(
                getattr(
                    document,
                    "metadata",
                    {},
                )
            ),
        }

    def compress(
        self,
        query: str,
        documents,
        tenant_id: str,
    ) -> CompressionResult:

        if not query.strip():
            raise ValueError(
                "query is required"
            )

        if not tenant_id.strip():
            raise ValueError(
                "tenant_id is required"
            )

        incoming = [
            self._read_document(
                document
            )
            for document in documents
        ]

        original_chars = sum(
            len(item["content"])
            for item in incoming
        )

        # Fail closed on missing or
        # mismatched tenant metadata.
        for item in incoming:
            if (
                item["metadata"].get(
                    "tenant_id"
                )
                != tenant_id
            ):
                raise ValueError(
                    "Missing or mismatched "
                    "tenant metadata"
                )

        ranked_documents = sorted(
            incoming,
            key=lambda item: (
                -max(
                    (
                        self._sentence_score(
                            query,
                            sentence,
                        )
                        for sentence
                        in self._split_sentences(
                            item["content"]
                        )
                    ),
                    default=0.0,
                ),
                item["document_id"],
            ),
        )

        compressed_documents = []
        seen_content = set()
        remaining_budget = (
            self.config.max_context_chars
        )

        for item in ranked_documents:
            if (
                len(compressed_documents)
                >= self.config.max_documents
            ):
                break

            if remaining_budget <= 0:
                break

            available = min(
                remaining_budget,
                self.config.max_passage_chars,
            )

            content, relevance = (
                self._compress_text(
                    query=query,
                    content=item["content"],
                    max_chars=available,
                )
            )

            if not content:
                continue

            content_hash = self._hash(
                content
            )

            if (
                self.config.deduplicate
                and content_hash in seen_content
            ):
                continue

            seen_content.add(
                content_hash
            )

            metadata = {
                **item["metadata"],
                "compression_method": (
                    "extractive_query_aware"
                ),
                "compressed_sha256": (
                    content_hash
                ),
                "original_document_id": (
                    item["document_id"]
                ),
            }

            compressed_documents.append(
                CompressedDocument(
                    document_id=(
                        item["document_id"]
                    ),
                    title=item["title"],
                    content=content,
                    original_content=(
                        item["content"]
                    ),
                    metadata=metadata,
                    relevance_score=relevance,
                    compression_ratio=round(
                        len(content)
                        / len(item["content"]),
                        4,
                    ),
                    original_chars=len(
                        item["content"]
                    ),
                    compressed_chars=len(
                        content
                    ),
                )
            )

            remaining_budget -= len(
                content
            )

        compressed_chars = sum(
            len(document.content)
            for document
            in compressed_documents
        )

        overall_ratio = (
            compressed_chars
            / original_chars
            if original_chars
            else 0.0
        )

        estimated_tokens = math.ceil(
            compressed_chars
            / self.config
            .estimated_chars_per_token
        )

        return CompressionResult(
            query=query,
            tenant_id=tenant_id,
            documents=compressed_documents,
            original_characters=(
                original_chars
            ),
            compressed_characters=(
                compressed_chars
            ),
            compression_ratio=round(
                overall_ratio,
                4,
            ),
            estimated_tokens=(
                estimated_tokens
            ),
            documents_received=len(
                incoming
            ),
            documents_retained=len(
                compressed_documents
            ),
        )

    @staticmethod
    def export_jsonl(
        result: CompressionResult,
        output_path,
        include_original=False,
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
            for document in result.documents:
                data = asdict(
                    document
                )

                if not include_original:
                    data.pop(
                        "original_content",
                        None,
                    )

                file.write(
                    json.dumps(
                        data,
                        ensure_ascii=False,
                    )
                    + "\n"
                )

        return output


if __name__ == "__main__":
    documents = [
        {
            "document_id": "doc-001",
            "title": "Supplier Delivery Report",
            "content": (
                "Supplier SUP002 delivers "
                "SKU001 within eight days. "
                "The warehouse receives "
                "goods every Monday. "
                "Supplier SUP002 has an "
                "on-time delivery rate "
                "of 95%. "
                "The annual warehouse "
                "inspection is scheduled "
                "for December."
            ),
            "metadata": {
                "tenant_id": "demo",
                "category": "supplier",
                "source_file": (
                    "supplier_report.pdf"
                ),
                "page": 2,
            },
        },
        {
            "document_id": "doc-002",
            "title": "Inventory Policy",
            "content": (
                "SKU001 has a reorder "
                "point of 50 units. "
                "Safety stock is "
                "maintained to reduce "
                "stockout risk. "
                "The retail store opens "
                "at nine in the morning."
            ),
            "metadata": {
                "tenant_id": "demo",
                "category": "inventory",
                "source_file": (
                    "inventory_policy.docx"
                ),
            },
        },
    ]

    compressor = (
        RetailContextualCompressor(
            CompressionConfig(
                max_context_chars=500,
                max_passage_chars=300,
                max_documents=5,
                target_compression_ratio=0.75,
            )
        )
    )

    result = compressor.compress(
        query=(
            "What is the delivery time "
            "for supplier SUP002 "
            "and SKU001?"
        ),
        documents=documents,
        tenant_id="demo",
    )

    print(
        json.dumps(
            asdict(result),
            indent=2,
            ensure_ascii=False,
        )
    )

    compressor.export_jsonl(
        result,
        "data/processed/"
        "compressed_context.jsonl",
    )
