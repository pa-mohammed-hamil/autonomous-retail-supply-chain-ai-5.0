"""Planned module: ocr loader. Implementation pending."""

"""
ai/ingestion/ingestion_pipeline.py

Autonomous Retail Supply Chain AI 5.0

Unified RAG Ingestion Pipeline

Install:
    pip install pandas pymupdf \
        python-docx beautifulsoup4 \
        lxml rank-bm25 numpy \
        sentence-transformers

Requires existing project modules:
    ai.ingestion.csv_loader
    ai.ingestion.document_loader
    ai.ingestion.docx_loader
    ai.ingestion.html_loader
    ai.ingestion.metadata_extractor
    ai.retrieval.bm25_index
    ai.retrieval.vector_index

Pipeline:
    Validate -> Load -> Enrich
    -> Chunk -> Build indexes -> Report

Prototype:
    Rebuilds complete indexes per run.
    Does not provide atomic persistence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai.ingestion.csv_loader import (
    RetailCSVLoader,
)
from ai.ingestion.document_loader import (
    RetailDocumentLoader,
)
from ai.ingestion.docx_loader import (
    RetailDOCXLoader,
)
from ai.ingestion.html_loader import (
    RetailHTMLLoader,
)
from ai.ingestion.metadata_extractor import (
    RetailMetadataExtractor,
)
from ai.retrieval.bm25_index import (
    BM25Index,
    SearchDocument,
)
from ai.retrieval.vector_index import (
    RetailVectorIndex,
    VectorRecord,
)


@dataclass
class IngestionResult:
    files_processed: int
    documents_loaded: int
    chunks_created: int
    skipped_empty: int
    status: str
    timestamp: str


class RetailIngestionPipeline:

    SUPPORTED = {
        ".csv",
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
        chunk_size=1000,
        chunk_overlap=150,
        max_files=100,
        max_file_mb=25,
    ):
        if chunk_size < 100:
            raise ValueError(
                "chunk_size must be >= 100"
            )

        if not (
            0 <= chunk_overlap < chunk_size
        ):
            raise ValueError(
                "Invalid chunk overlap"
            )

        self.chunk_size = chunk_size
        self.chunk_overlap = (
            chunk_overlap
        )
        self.max_files = max_files
        self.max_file_mb = max_file_mb

        self.csv_loader = RetailCSVLoader(
            max_file_mb=max_file_mb
        )

        self.document_loader = (
            RetailDocumentLoader(
                max_file_mb=max_file_mb
            )
        )

        self.docx_loader = (
            RetailDOCXLoader(
                max_file_mb=max_file_mb
            )
        )

        self.html_loader = (
            RetailHTMLLoader(
                max_file_mb=max_file_mb
            )
        )

        self.metadata_extractor = (
            RetailMetadataExtractor()
        )

        self.bm25 = None
        self.vector_index = None
        self.chunks = []

    @staticmethod
    def _make_chunk_id(
        tenant_id,
        parent_id,
        chunk_number,
    ):
        value = (
            f"{tenant_id}|{parent_id}|"
            f"{chunk_number}"
        )

        return hashlib.sha256(
            value.encode("utf-8")
        ).hexdigest()[:24]

    def _chunk_text(self, text):
        """
        Character-based overlapping chunks.
        A tokenizer-aware chunker is
        preferable for production.
        """
        if not text.strip():
            return []

        chunks = []
        step = (
            self.chunk_size
            - self.chunk_overlap
        )

        for start in range(
            0,
            len(text),
            step,
        ):
            piece = text[
                start:start + self.chunk_size
            ].strip()

            if piece:
                chunks.append(piece)

            if (
                start + self.chunk_size
                >= len(text)
            ):
                break

        return chunks

    def _validate_path(self, path):
        if not path.is_file():
            raise FileNotFoundError(
                path
            )

        if path.is_symlink():
            raise ValueError(
                "Symlinks are not accepted"
            )

        if (
            path.suffix.lower()
            not in self.SUPPORTED
        ):
            raise ValueError(
                f"Unsupported format: "
                f"{path.suffix}"
            )

        if (
            path.stat().st_size
            > self.max_file_mb * 1024 * 1024
        ):
            raise ValueError(
                "File exceeds size limit"
            )

    def _load_file(
        self,
        path,
        tenant_id,
        category,
        source_key,
    ):
        extension = path.suffix.lower()

        if extension == ".csv":
            return self.csv_loader.load_documents(
                file_path=path,
                tenant_id=tenant_id,
                category=category,
                source_key=source_key,
            )

        if extension == ".docx":
            return self.docx_loader.load(
                file_path=path,
                tenant_id=tenant_id,
                category=category,
                source_key=source_key,
            )

        if extension in (
            ".html",
            ".htm",
        ):
            return self.html_loader.load(
                file_path=path,
                tenant_id=tenant_id,
                category=category,
                source_key=source_key,
            )

        return self.document_loader.load(
            file_path=path,
            tenant_id=tenant_id,
            category=category,
            source_key=source_key,
        )

    def ingest(
        self,
        file_paths,
        tenant_id,
        category="general",
        output_dir="indexes/retail_ingestion",
    ):
        if not tenant_id:
            raise ValueError(
                "tenant_id required"
            )

        paths = [
            Path(item)
            for item in file_paths
        ]

        if not paths:
            raise ValueError(
                "No files supplied"
            )

        if len(paths) > self.max_files:
            raise ValueError(
                "Too many files"
            )

        for path in paths:
            self._validate_path(
                path
            )

        all_chunks = []
        documents_loaded = 0
        skipped_empty = 0

        for path in paths:
            # For production, source_key
            # should be a stable registered
            # file identifier, not only a
            # filename.
            source_key = path.name

            loaded = self._load_file(
                path=path,
                tenant_id=tenant_id,
                category=category,
                source_key=source_key,
            )

            documents_loaded += len(
                loaded
            )

            for document in loaded:
                if not document.content.strip():
                    skipped_empty += 1
                    continue

                extracted_metadata = (
                    self.metadata_extractor.extract(
                        content=document.content,
                        tenant_id=tenant_id,
                        source_path=path,
                        source_key=source_key,
                    )
                )

                # Preserve the original
                # loader's page/row/section
                # information.
                metadata = {
                    **extracted_metadata,
                    **document.metadata,
                }

                # Enforce trusted scope.
                metadata["tenant_id"] = (
                    tenant_id
                )

                pieces = self._chunk_text(
                    document.content
                )

                for index, piece in enumerate(
                    pieces,
                    start=1,
                ):
                    chunk_id = (
                        self._make_chunk_id(
                            tenant_id,
                            document.document_id,
                            index,
                        )
                    )

                    chunk_metadata = {
                        **metadata,
                        "parent_document_id": (
                            document.document_id
                        ),
                        "chunk_number": index,
                        "chunk_count": len(
                            pieces
                        ),
                        "chunk_sha256": (
                            hashlib.sha256(
                                piece.encode(
                                    "utf-8"
                                )
                            ).hexdigest()
                        ),
                    }

                    all_chunks.append(
                        SearchDocument(
                            document_id=chunk_id,
                            title=document.title,
                            content=piece,
                            metadata=chunk_metadata,
                        )
                    )

        if not all_chunks:
            raise ValueError(
                "No searchable text extracted"
            )

        ids = [
            chunk.document_id
            for chunk in all_chunks
        ]

        if len(ids) != len(set(ids)):
            raise ValueError(
                "Duplicate chunk IDs detected"
            )

        # Build both indexes locally first.
        new_bm25 = BM25Index().build(
            all_chunks
        )

        vector_records = [
            VectorRecord(
                document_id=chunk.document_id,
                title=chunk.title,
                content=chunk.content,
                metadata=chunk.metadata,
            )
            for chunk in all_chunks
        ]

        new_vector_index = (
            RetailVectorIndex()
        )

        new_vector_index.upsert(
            vector_records
        )

        # Publish in-memory indexes only
        # after both builds succeed.
        self.bm25 = new_bm25
        self.vector_index = (
            new_vector_index
        )
        self.chunks = all_chunks

        output = Path(
            output_dir
        )

        output.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.bm25.save(
            output / "bm25.json"
        )

        self.vector_index.save(
            output / "faiss"
        )

        result = IngestionResult(
            files_processed=len(paths),
            documents_loaded=(
                documents_loaded
            ),
            chunks_created=len(
                all_chunks
            ),
            skipped_empty=skipped_empty,
            status="completed",
            timestamp=(
                datetime.now(
                    timezone.utc
                ).isoformat()
            ),
        )

        (
            output / "ingestion_report.json"
        ).write_text(
            json.dumps(
                result.__dict__,
                indent=2,
            ),
            encoding="utf-8",
        )

        return result

    def search(
        self,
        query,
        tenant_id,
        top_k=5,
        method="semantic",
    ):
        if (
            self.bm25 is None
            or self.vector_index is None
        ):
            raise RuntimeError(
                "Run ingest() first"
            )

        if method == "bm25":
            return self.bm25.search(
                query,
                top_k=top_k,
                filters={
                    "tenant_id": tenant_id,
                },
            )

        if method == "semantic":
            return self.vector_index.search(
                query,
                tenant_id=tenant_id,
                top_k=top_k,
            )

        raise ValueError(
            "method must be bm25 or semantic"
        )


if __name__ == "__main__":
    sample = Path(
        "data/documents/"
        "retail_policy.txt"
    )

    sample.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not sample.exists():
        sample.write_text(
            "Retail Inventory Policy\n"
            "SKU001 stock is 120 units.\n"
            "Supplier SUP002 normally "
            "delivers within eight days.\n"
            "Replenishment requests must "
            "be reviewed before approval.",
            encoding="utf-8",
        )

    pipeline = (
        RetailIngestionPipeline()
    )

    result = pipeline.ingest(
        file_paths=[sample],
        tenant_id="demo",
        category="retail_policy",
    )

    print(
        json.dumps(
            result.__dict__,
            indent=2,
        )
    )

    print(
        "\nSemantic search:"
    )

    print(
        pipeline.search(
            query=(
                "How long does the "
                "supplier take to deliver?"
            ),
            tenant_id="demo",
            method="semantic",
        )
    )

    print(
        "\nBM25 search:"
    )

    print(
        pipeline.search(
            query="SKU001 stock",
            tenant_id="demo",
            method="bm25",
        )
    )
