"""Planned module: rag copilot agent. Implementation pending."""

"""
File: ai/agents/rag_copilot_agent.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+ | Standard library only

Capabilities:
- ingest_document
- search_knowledge
- ask_copilot
- list_documents
- delete_document

Retrieval:
- Keyword overlap with basic term frequency
- Tenant and role-aware document filtering
- Source citations

This implementation is extractive RAG:
it returns grounded passages rather than
calling an external generative LLM.
"""

from __future__ import annotations

import re
import threading
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

from .base_agent import (
    BaseAgent,
    AgentRequest,
    AgentValidationError,
    utc_now,
)


STOPWORDS = {
    "the", "a", "an", "is", "are", "to", "of",
    "and", "or", "for", "in", "on", "at", "by",
    "what", "how", "when", "where", "which",
    "does", "do", "can", "with", "from",
}


@dataclass
class KnowledgeDocument:
    document_id: str
    tenant_id: str
    title: str
    source: str
    allowed_roles: list[str]
    chunks: list[str]
    created_at: str


class RAGCopilotAgent(BaseAgent):

    def __init__(
        self,
        working_memory: Any | None = None,
        chunk_size: int = 600,
        chunk_overlap: int = 100,
    ) -> None:
        super().__init__(
            agent_id="rag_copilot_agent",
            name="Retail Knowledge RAG Copilot",
            capabilities={
                "ingest_document",
                "search_knowledge",
                "ask_copilot",
                "list_documents",
                "delete_document",
            },
            working_memory=working_memory,
        )

        if (
            not isinstance(chunk_size, int)
            or isinstance(chunk_size, bool)
            or chunk_size < 100
            or not isinstance(chunk_overlap, int)
            or isinstance(chunk_overlap, bool)
            or not 0 <= chunk_overlap < chunk_size
        ):
            raise ValueError(
                "Invalid chunk configuration."
            )

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        self._documents: dict[
            tuple[str, str], KnowledgeDocument
        ] = {}

        self._lock = threading.RLock()

    @staticmethod
    def _text(value: Any, name: str) -> str:
        if (
            not isinstance(value, str)
            or not value.strip()
        ):
            raise AgentValidationError(
                f"{name} is required."
            )
        return value.strip()

    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [
            token
            for token in re.findall(
                r"[a-z0-9]+",
                text.lower(),
            )
            if token not in STOPWORDS
        ]

    def _chunk_text(self, text: str) -> list[str]:
        chunks = []
        step = self.chunk_size - self.chunk_overlap

        for start in range(0, len(text), step):
            chunk = text[
                start:start + self.chunk_size
            ].strip()

            if chunk:
                chunks.append(chunk)

            if start + self.chunk_size >= len(text):
                break

        return chunks

    @staticmethod
    def _authorized(
        document: KnowledgeDocument,
        roles: frozenset[str],
    ) -> bool:
        return bool(
            set(document.allowed_roles) & set(roles)
        )

    def _ingest(
        self,
        request: AgentRequest,
    ) -> dict:
        payload = request.payload

        title = self._text(
            payload.get("title"), "title"
        )
        source = self._text(
            payload.get("source"), "source"
        )
        content = self._text(
            payload.get("content"), "content"
        )

        allowed_roles = payload.get(
            "allowed_roles"
        )

        if (
            not isinstance(allowed_roles, list)
            or not allowed_roles
            or not all(
                isinstance(role, str)
                and role.strip()
                for role in allowed_roles
            )
        ):
            raise AgentValidationError(
                "Nonempty allowed_roles list required."
            )

        if len(content) > 1_000_000:
            raise AgentValidationError(
                "Document exceeds size limit."
            )

        document = KnowledgeDocument(
            document_id=str(uuid4()),
            tenant_id=request.context.tenant_id,
            title=title,
            source=source,
            allowed_roles=sorted(
                set(allowed_roles)
            ),
            chunks=self._chunk_text(content),
            created_at=utc_now(),
        )

        with self._lock:
            self._documents[
                (
                    document.tenant_id,
                    document.document_id,
                )
            ] = document

        return {
            "document_id": document.document_id,
            "title": document.title,
            "chunk_count": len(document.chunks),
            "ingested": True,
        }

    def _search(
        self,
        request: AgentRequest,
    ) -> dict:
        payload = request.payload

        query = self._text(
            payload.get("query"), "query"
        )

        top_k = payload.get("top_k", 5)

        if (
            isinstance(top_k, bool)
            or not isinstance(top_k, int)
            or not 1 <= top_k <= 20
        ):
            raise AgentValidationError(
                "top_k must be between 1 and 20."
            )

        query_tokens = set(
            self._tokens(query)
        )

        if not query_tokens:
            return {
                "query": query,
                "results": [],
                "result_count": 0,
            }

        tenant_id = request.context.tenant_id
        roles = request.context.roles

        with self._lock:
            documents = [
                document
                for document in self._documents.values()
                if document.tenant_id == tenant_id
                and self._authorized(
                    document, roles
                )
            ]

        results = []

        for document in documents:
            for index, chunk in enumerate(
                document.chunks
            ):
                frequencies = Counter(
                    self._tokens(chunk)
                )

                score = sum(
                    frequencies[token]
                    for token in query_tokens
                )

                if score <= 0:
                    continue

                results.append({
                    "document_id": document.document_id,
                    "title": document.title,
                    "source": document.source,
                    "chunk_index": index,
                    "score": score,
                    "text": chunk,
                    "citation": (
                        f"[{document.document_id}"
                        f":chunk-{index}]"
                    ),
                })

        results.sort(
            key=lambda item: (
                -item["score"],
                item["document_id"],
                item["chunk_index"],
            )
        )

        selected = results[:top_k]

        return {
            "query": query,
            "results": selected,
            "result_count": len(selected),
            "retrieval_method": (
                "keyword_term_frequency"
            ),
        }

    def _answer(
        self,
        request: AgentRequest,
    ) -> dict:
        search = self._search(request)
        results = search["results"]

        if not results:
            return {
                "answer": (
                    "I could not find supporting "
                    "information in the accessible "
                    "knowledge documents."
                ),
                "citations": [],
                "grounded": False,
                "requires_human_review": True,
            }

        passages = [
            (
                f"{item['text']} "
                f"{item['citation']}"
            )
            for item in results[:3]
        ]

        return {
            "answer": "\n\n".join(passages),
            "citations": [
                {
                    "document_id": item["document_id"],
                    "title": item["title"],
                    "source": item["source"],
                    "chunk_index": item["chunk_index"],
                    "citation": item["citation"],
                }
                for item in results[:3]
            ],
            "grounded": True,
            "answer_type": "extractive",
            "generated_by_llm": False,
            "requires_human_review": False,
        }

    def _list(
        self,
        request: AgentRequest,
    ) -> dict:
        tenant_id = request.context.tenant_id
        roles = request.context.roles

        with self._lock:
            documents = [
                {
                    "document_id": doc.document_id,
                    "title": doc.title,
                    "source": doc.source,
                    "chunk_count": len(doc.chunks),
                }
                for doc in self._documents.values()
                if doc.tenant_id == tenant_id
                and self._authorized(doc, roles)
            ]

        return {"documents": documents}

    def _delete(
        self,
        request: AgentRequest,
    ) -> dict:
        document_id = self._text(
            request.payload.get("document_id"),
            "document_id",
        )

        key = (
            request.context.tenant_id,
            document_id,
        )

        with self._lock:
            document = self._documents.get(key)

            if document is None or not self._authorized(
                document,
                request.context.roles,
            ):
                raise AgentValidationError(
                    "Document not found or inaccessible."
                )

            del self._documents[key]

        return {
            "document_id": document_id,
            "deleted": True,
        }

    def process(
        self,
        request: AgentRequest,
    ) -> dict:
        task = request.task_type

        if task == "ingest_document":
            return self._ingest(request)

        if task == "search_knowledge":
            return self._search(request)

        if task == "ask_copilot":
            return self._answer(request)

        if task == "list_documents":
            return self._list(request)

        if task == "delete_document":
            return self._delete(request)

        raise AgentValidationError(
            "Unsupported RAG copilot task."
        )
