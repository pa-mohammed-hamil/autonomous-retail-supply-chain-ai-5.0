from __future__ import annotations

"""Planned module: rag. Implementation pending."""

"""
backend/rag.py

Autonomous Retail Supply Chain AI 5.0
Enterprise Retrieval-Augmented Generation API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Architecture:
    FastAPI
       |
       v
    RAGService
       |
       +-- Permission-aware retrieval
       +-- Hybrid search (BM25 + vector)
       +-- Reranking
       +-- Citation formatting
       +-- Grounded answer generation
       +-- Session history
       +-- Evaluation hooks

This module defines API orchestration and an in-memory
demonstration adapter.

Production requires real vector/BM25 indexes, a model
provider, durable storage, and external authorization.
"""


import asyncio
import hashlib
import math
import re
import secrets

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

from fastapi import APIRouter, HTTPException, Query
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from backend.permissions import (
    CurrentPrincipal,
    Permission,
    Principal,
    ResourceContext,
    permission_engine,
)


API_PREFIX = "/api/v1/rag"

MAX_DOCUMENTS_PER_TENANT = 10000
MAX_CHUNKS_PER_DOCUMENT = 100
MAX_SESSIONS_PER_TENANT = 10000
MAX_MESSAGES_PER_SESSION = 100
MAX_DOCUMENT_CHARACTERS = 200000
MAX_CHUNK_CHARACTERS = 4000
MAX_QUERY_CHARACTERS = 4000
MAX_LIST_LIMIT = 100


# ============================================================
# ENUMS
# ============================================================

class DocumentType(str, Enum):
    POLICY = "policy"
    SOP = "sop"
    INVENTORY_REPORT = "inventory_report"
    SUPPLIER_CONTRACT = "supplier_contract"
    PROCUREMENT = "procurement"
    LOGISTICS = "logistics"
    FINANCIAL = "financial"
    PRODUCT = "product"
    QUALITY = "quality"
    OTHER = "other"


class RetrievalMode(str, Enum):
    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


class RAGSessionStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


# ============================================================
# REQUEST MODELS
# ============================================================

class RAGDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=250)

    document_type: DocumentType

    content: str = Field(
        min_length=10,
        max_length=MAX_DOCUMENT_CHARACTERS,
    )

    warehouse_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    source_reference: str = Field(
        min_length=1,
        max_length=500,
    )

    allowed_role_names: list[str] = Field(
        default_factory=list,
        max_length=20,
    )

    chunk_size: int = Field(
        default=1000,
        ge=200,
        le=MAX_CHUNK_CHARACTERS,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )


class RAGSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        min_length=3,
        max_length=MAX_QUERY_CHARACTERS,
    )

    warehouse_id: str | None = None

    document_types: list[DocumentType] = Field(
        default_factory=list,
        max_length=20,
    )

    retrieval_mode: RetrievalMode = RetrievalMode.HYBRID

    top_k: int = Field(default=5, ge=1, le=20)

    min_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
    )


class RAGChatRequest(RAGSearchRequest):
    session_id: str | None = None


class RAGSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        default="Supply Chain Assistant",
        min_length=1,
        max_length=150,
    )

    warehouse_id: str | None = None


class RAGVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


# ============================================================
# RESPONSE MODELS
# ============================================================

class RAGDocumentResponse(BaseModel):
    document_id: str
    title: str
    document_type: DocumentType
    warehouse_id: str | None
    source_reference: str
    chunk_count: int
    version: int
    created_at: datetime


class RAGCitation(BaseModel):
    citation_id: str
    document_id: str
    chunk_id: str
    title: str
    source_reference: str
    excerpt: str
    score: float


class RAGSearchResponse(BaseModel):
    query: str
    retrieval_mode: RetrievalMode
    citations: list[RAGCitation]
    total_results: int


class RAGAnswerResponse(BaseModel):
    query: str
    answer: str
    citations: list[RAGCitation]
    grounded: bool
    session_id: str | None
    model_used: str
    created_at: datetime


class RAGMessageResponse(BaseModel):
    message_id: str
    role: MessageRole
    content: str
    created_at: datetime


class RAGSessionResponse(BaseModel):
    session_id: str
    title: str
    warehouse_id: str | None
    status: RAGSessionStatus
    version: int
    message_count: int
    created_at: datetime


class RAGSessionDetailResponse(RAGSessionResponse):
    messages: list[RAGMessageResponse]


class RAGStatisticsResponse(BaseModel):
    document_count: int
    chunk_count: int
    session_count: int
    active_sessions: int


# ============================================================
# INTERNAL RECORDS
# ============================================================

@dataclass
class ChunkRecord:
    chunk_id: str
    document_id: str
    text: str
    position: int


@dataclass
class DocumentRecord:
    document_id: str
    tenant_id: str
    title: str
    document_type: DocumentType
    content: str
    warehouse_id: str | None
    source_reference: str
    allowed_role_names: frozenset[str]
    chunks: list[ChunkRecord]
    created_by: str
    version: int = 1
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class SessionRecord:
    session_id: str
    tenant_id: str
    owner_id: str
    title: str
    warehouse_id: str | None
    status: RAGSessionStatus = RAGSessionStatus.ACTIVE
    messages: list[RAGMessageResponse] = field(
        default_factory=list
    )
    version: int = 1
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ============================================================
# SECURITY
# ============================================================

def require_rag_access(
    principal: Principal,
    warehouse_id: str | None,
    *,
    write: bool,
) -> None:

    permission = (
        Permission.AI_AGENT_CONFIGURE
        if write
        else Permission.AI_AGENT_READ
    )

    if warehouse_id is None:
        if principal.allowed_warehouse_ids is not None:
            raise HTTPException(
                status_code=403,
                detail="Tenant-wide access required",
            )

    elif (
        principal.allowed_warehouse_ids is not None
        and warehouse_id not in principal.allowed_warehouse_ids
    ):
        raise HTTPException(
            status_code=403,
            detail="Warehouse access denied",
        )

    decision = permission_engine.evaluate(
        principal,
        permission,
        ResourceContext(
            tenant_id=principal.tenant_id,
            warehouse_id=warehouse_id,
        ),
    )

    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail="RAG access denied",
        )


def document_visible(
    principal: Principal,
    document: DocumentRecord,
) -> bool:

    if document.tenant_id != principal.tenant_id:
        return False

    if document.allowed_role_names:
        principal_roles = {
            str(getattr(role, "value", role))
            for role in principal.roles
        }

        if not (
            principal_roles
            & document.allowed_role_names
        ):
            return False

    try:
        require_rag_access(
            principal,
            document.warehouse_id,
            write=False,
        )
    except HTTPException:
        return False

    return True


# ============================================================
# TEXT PROCESSING
# ============================================================

TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_]+")


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.casefold())


def split_document(
    document_id: str,
    content: str,
    chunk_size: int,
) -> list[ChunkRecord]:

    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", content)
        if paragraph.strip()
    ]

    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:

        while len(paragraph) > chunk_size:

            if current:
                chunks.append(current)
                current = ""

            chunks.append(paragraph[:chunk_size])
            paragraph = paragraph[chunk_size:]

        if not paragraph:
            continue

        candidate = (
            f"{current}\n\n{paragraph}"
            if current
            else paragraph
        )

        if len(candidate) > chunk_size:
            if current:
                chunks.append(current)
            current = paragraph
        else:
            current = candidate

    if current:
        chunks.append(current)

    if len(chunks) > MAX_CHUNKS_PER_DOCUMENT:
        raise HTTPException(
            status_code=422,
            detail="Document exceeds maximum chunk count",
        )

    return [
        ChunkRecord(
            chunk_id=secrets.token_urlsafe(12),
            document_id=document_id,
            text=text,
            position=index,
        )
        for index, text in enumerate(chunks)
    ]


# ============================================================
# DEMONSTRATION RETRIEVER
# ============================================================

class RetrievalBackend(Protocol):

    async def search(
        self,
        query: str,
        documents: list[DocumentRecord],
        mode: RetrievalMode,
        top_k: int,
    ) -> list[tuple[DocumentRecord, ChunkRecord, float]]:
        ...


class InMemoryHybridRetriever:
    """
    Demonstration-only lexical retriever.

    'semantic' mode uses term-frequency cosine similarity,
    NOT neural embeddings.

    Replace with ai/retrieval/vector_index.py,
    bm25_index.py, hybrid_retriever.py, and reranker.py
    for actual production hybrid retrieval.
    """

    @staticmethod
    def keyword_score(
        query_tokens: list[str],
        chunk_tokens: list[str],
    ) -> float:

        if not query_tokens or not chunk_tokens:
            return 0.0

        query_set = set(query_tokens)
        chunk_set = set(chunk_tokens)

        return len(query_set & chunk_set) / len(query_set)

    @staticmethod
    def cosine_score(
        query_tokens: list[str],
        chunk_tokens: list[str],
    ) -> float:

        q = Counter(query_tokens)
        d = Counter(chunk_tokens)

        dot = sum(
            count * d.get(token, 0)
            for token, count in q.items()
        )

        q_norm = math.sqrt(
            sum(value * value for value in q.values())
        )

        d_norm = math.sqrt(
            sum(value * value for value in d.values())
        )

        if not q_norm or not d_norm:
            return 0.0

        return dot / (q_norm * d_norm)

    async def search(
        self,
        query: str,
        documents: list[DocumentRecord],
        mode: RetrievalMode,
        top_k: int,
    ) -> list[tuple[DocumentRecord, ChunkRecord, float]]:

        query_tokens = tokenize(query)
        results = []

        for document in documents:

            for chunk in document.chunks:

                chunk_tokens = tokenize(chunk.text)

                keyword = self.keyword_score(
                    query_tokens,
                    chunk_tokens,
                )

                cosine = self.cosine_score(
                    query_tokens,
                    chunk_tokens,
                )

                if mode == RetrievalMode.KEYWORD:
                    score = keyword

                elif mode == RetrievalMode.SEMANTIC:
                    score = cosine

                else:
                    score = (
                        0.55 * keyword
                        + 0.45 * cosine
                    )

                if score <= 0:
                    continue

                results.append(
                    (document, chunk, min(score, 1.0))
                )

        results.sort(
            key=lambda item: item[2],
            reverse=True,
        )

        return results[:top_k]


# ============================================================
# GROUNDED ANSWER GENERATOR
# ============================================================

class GroundedAnswerGenerator:
    """
    Deterministic extractive demonstration.

    Does not invoke an LLM.
    Does not execute instructions found in documents.
    """

    async def generate(
        self,
        query: str,
        citations: list[RAGCitation],
    ) -> str:

        if not citations:
            return (
                "I could not find sufficient authorized "
                "source material to answer this question."
            )

        lines = [
            "Relevant information from authorized sources:"
        ]

        for citation in citations[:5]:

            excerpt = " ".join(
                citation.excerpt.split()
            )[:450]

            lines.append(
                f"[{citation.citation_id}] {excerpt}"
            )

        lines.append(
            "These are retrieved excerpts, not a "
            "verified synthesized answer. Check the "
            "cited source documents before acting."
        )

        return "\n\n".join(lines)


# ============================================================
# RAG STORE
# ============================================================

class RAGStore:

    def __init__(self):

        self.documents: dict[str, DocumentRecord] = {}
        self.sessions: dict[str, SessionRecord] = {}

        self.idempotency: dict[
            tuple[str, str, str],
            tuple[str, str],
        ] = {}

        self.lock = asyncio.Lock()

    @staticmethod
    def fingerprint(
        payload: RAGDocumentCreate,
    ) -> str:

        data = payload.model_dump_json(
            exclude={"source_request_id"}
        )

        return hashlib.sha256(
            data.encode("utf-8")
        ).hexdigest()

    async def create_document(
        self,
        principal: Principal,
        payload: RAGDocumentCreate,
    ) -> RAGDocumentResponse:

        require_rag_access(
            principal,
            payload.warehouse_id,
            write=True,
        )

        key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        fingerprint = self.fingerprint(payload)

        async with self.lock:

            previous = self.idempotency.get(key)

            if previous:

                old_fingerprint, document_id = previous

                if old_fingerprint != fingerprint:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                record = self.documents[document_id]
                return self._document_response(record)

            count = sum(
                record.tenant_id == principal.tenant_id
                for record in self.documents.values()
            )

            if count >= MAX_DOCUMENTS_PER_TENANT:
                raise HTTPException(
                    status_code=503,
                    detail="Document capacity reached",
                )

            document_id = secrets.token_urlsafe(20)

            chunks = split_document(
                document_id,
                payload.content,
                payload.chunk_size,
            )

            record = DocumentRecord(
                document_id=document_id,
                tenant_id=principal.tenant_id,
                title=payload.title,
                document_type=payload.document_type,
                content=payload.content,
                warehouse_id=payload.warehouse_id,
                source_reference=payload.source_reference,
                allowed_role_names=frozenset(
                    payload.allowed_role_names
                ),
                chunks=chunks,
                created_by=principal.principal_id,
            )

            self.documents[document_id] = record
            self.idempotency[key] = (
                fingerprint,
                document_id,
            )

            return self._document_response(record)

    @staticmethod
    def _document_response(
        record: DocumentRecord,
    ) -> RAGDocumentResponse:

        return RAGDocumentResponse(
            document_id=record.document_id,
            title=record.title,
            document_type=record.document_type,
            warehouse_id=record.warehouse_id,
            source_reference=record.source_reference,
            chunk_count=len(record.chunks),
            version=record.version,
            created_at=record.created_at,
        )

    async def list_documents(
        self,
        principal: Principal,
        limit: int,
    ) -> list[RAGDocumentResponse]:

        async with self.lock:

            visible = [
                record
                for record in self.documents.values()
                if document_visible(principal, record)
            ]

            visible.sort(
                key=lambda item: item.created_at,
                reverse=True,
            )

            return [
                self._document_response(record)
                for record in visible[:limit]
            ]

    async def authorized_documents(
        self,
        principal: Principal,
        warehouse_id: str | None,
        document_types: list[DocumentType],
    ) -> list[DocumentRecord]:

        require_rag_access(
            principal,
            warehouse_id,
            write=False,
        )

        async with self.lock:

            return [
                record
                for record in self.documents.values()
                if (
                    document_visible(principal, record)
                    and (
                        warehouse_id is None
                        or record.warehouse_id == warehouse_id
                    )
                    and (
                        not document_types
                        or record.document_type in document_types
                    )
                )
            ]

    async def create_session(
        self,
        principal: Principal,
        payload: RAGSessionCreate,
    ) -> RAGSessionResponse:

        require_rag_access(
            principal,
            payload.warehouse_id,
            write=False,
        )

        async with self.lock:

            count = sum(
                record.tenant_id == principal.tenant_id
                for record in self.sessions.values()
            )

            if count >= MAX_SESSIONS_PER_TENANT:
                raise HTTPException(
                    status_code=503,
                    detail="Session capacity reached",
                )

            record = SessionRecord(
                session_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                owner_id=principal.principal_id,
                title=payload.title,
                warehouse_id=payload.warehouse_id,
            )

            self.sessions[record.session_id] = record

            return self._session_response(record)

    @staticmethod
    def _session_response(
        record: SessionRecord,
    ) -> RAGSessionResponse:

        return RAGSessionResponse(
            session_id=record.session_id,
            title=record.title,
            warehouse_id=record.warehouse_id,
            status=record.status,
            version=record.version,
            message_count=len(record.messages),
            created_at=record.created_at,
        )

    def _get_session(
        self,
        principal: Principal,
        session_id: str,
    ) -> SessionRecord:

        record = self.sessions.get(session_id)

        if (
            record is None
            or record.tenant_id != principal.tenant_id
            or record.owner_id != principal.principal_id
        ):
            raise HTTPException(
                status_code=404,
                detail="RAG session not found",
            )

        require_rag_access(
            principal,
            record.warehouse_id,
            write=False,
        )

        return record

    async def get_session(
        self,
        principal: Principal,
        session_id: str,
    ) -> RAGSessionDetailResponse:

        async with self.lock:

            record = self._get_session(
                principal,
                session_id,
            )

            return RAGSessionDetailResponse(
                **self._session_response(record).model_dump(),
                messages=list(record.messages),
            )

    async def add_exchange(
        self,
        principal: Principal,
        session_id: str,
        query: str,
        answer: str,
    ) -> None:

        async with self.lock:

            record = self._get_session(
                principal,
                session_id,
            )

            if record.status != RAGSessionStatus.ACTIVE:
                raise HTTPException(
                    status_code=409,
                    detail="Session is closed",
                )

            if len(record.messages) + 2 > MAX_MESSAGES_PER_SESSION:
                raise HTTPException(
                    status_code=409,
                    detail="Session message capacity reached",
                )

            now = datetime.now(timezone.utc)

            record.messages.extend([
                RAGMessageResponse(
                    message_id=secrets.token_urlsafe(12),
                    role=MessageRole.USER,
                    content=query,
                    created_at=now,
                ),
                RAGMessageResponse(
                    message_id=secrets.token_urlsafe(12),
                    role=MessageRole.ASSISTANT,
                    content=answer,
                    created_at=now,
                ),
            ])

            record.version += 1

    async def close_session(
        self,
        principal: Principal,
        session_id: str,
        expected_version: int,
    ) -> RAGSessionResponse:

        async with self.lock:

            record = self._get_session(
                principal,
                session_id,
            )

            if record.version != expected_version:
                raise HTTPException(
                    status_code=409,
                    detail="Session version conflict",
                )

            if record.status != RAGSessionStatus.ACTIVE:
                raise HTTPException(
                    status_code=409,
                    detail="Session already closed",
                )

            record.status = RAGSessionStatus.CLOSED
            record.version += 1

            return self._session_response(record)

    async def statistics(
        self,
        principal: Principal,
    ) -> RAGStatisticsResponse:

        async with self.lock:

            documents = [
                record
                for record in self.documents.values()
                if document_visible(principal, record)
            ]

            sessions = [
                record
                for record in self.sessions.values()
                if (
                    record.tenant_id == principal.tenant_id
                    and record.owner_id == principal.principal_id
                )
            ]

            return RAGStatisticsResponse(
                document_count=len(documents),
                chunk_count=sum(
                    len(record.chunks)
                    for record in documents
                ),
                session_count=len(sessions),
                active_sessions=sum(
                    record.status == RAGSessionStatus.ACTIVE
                    for record in sessions
                ),
            )


# ============================================================
# RAG SERVICE
# ============================================================

class RAGService:

    def __init__(
        self,
        store: RAGStore,
        retriever: RetrievalBackend,
        generator: GroundedAnswerGenerator,
    ):

        self.store = store
        self.retriever = retriever
        self.generator = generator

    async def search(
        self,
        principal: Principal,
        payload: RAGSearchRequest,
    ) -> RAGSearchResponse:

        documents = await self.store.authorized_documents(
            principal,
            payload.warehouse_id,
            payload.document_types,
        )

        results = await self.retriever.search(
            query=payload.query,
            documents=documents,
            mode=payload.retrieval_mode,
            top_k=payload.top_k,
        )

        citations = []

        for document, chunk, score in results:

            if score < payload.min_score:
                continue

            citations.append(
                RAGCitation(
                    citation_id=f"S{len(citations) + 1}",
                    document_id=document.document_id,
                    chunk_id=chunk.chunk_id,
                    title=document.title,
                    source_reference=document.source_reference,
                    excerpt=chunk.text[:1000],
                    score=round(score, 4),
                )
            )

        return RAGSearchResponse(
            query=payload.query,
            retrieval_mode=payload.retrieval_mode,
            citations=citations,
            total_results=len(citations),
        )

    async def chat(
        self,
        principal: Principal,
        payload: RAGChatRequest,
    ) -> RAGAnswerResponse:

        if payload.session_id:

            session = await self.store.get_session(
                principal,
                payload.session_id,
            )

            if session.status != RAGSessionStatus.ACTIVE:
                raise HTTPException(
                    status_code=409,
                    detail="Session is closed",
                )

            if session.warehouse_id != payload.warehouse_id:
                raise HTTPException(
                    status_code=409,
                    detail="Session warehouse scope mismatch",
                )

        search_request = RAGSearchRequest(
            **payload.model_dump(
                exclude={"session_id"}
            )
        )

        search_result = await self.search(
            principal,
            search_request,
        )

        answer = await self.generator.generate(
            payload.query,
            search_result.citations,
        )

        if payload.session_id:

            await self.store.add_exchange(
                principal,
                payload.session_id,
                payload.query,
                answer,
            )

        return RAGAnswerResponse(
            query=payload.query,
            answer=answer,
            citations=search_result.citations,
            grounded=bool(search_result.citations),
            session_id=payload.session_id,
            model_used="extractive-demo-v1",
            created_at=datetime.now(timezone.utc),
        )


rag_store = RAGStore()

rag_service = RAGService(
    store=rag_store,
    retriever=InMemoryHybridRetriever(),
    generator=GroundedAnswerGenerator(),
)


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Enterprise RAG"],
)


@router.post(
    "/documents",
    response_model=RAGDocumentResponse,
    status_code=201,
)
async def create_rag_document(
    payload: RAGDocumentCreate,
    principal: CurrentPrincipal,
):
    return await rag_store.create_document(
        principal,
        payload,
    )


@router.get(
    "/documents",
    response_model=list[RAGDocumentResponse],
)
async def list_rag_documents(
    principal: CurrentPrincipal,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):
    return await rag_store.list_documents(
        principal,
        limit,
    )


@router.post(
    "/search",
    response_model=RAGSearchResponse,
)
async def search_rag(
    payload: RAGSearchRequest,
    principal: CurrentPrincipal,
):
    return await rag_service.search(
        principal,
        payload,
    )


@router.post(
    "/chat",
    response_model=RAGAnswerResponse,
)
async def chat_with_rag(
    payload: RAGChatRequest,
    principal: CurrentPrincipal,
):
    return await rag_service.chat(
        principal,
        payload,
    )


@router.post(
    "/sessions",
    response_model=RAGSessionResponse,
    status_code=201,
)
async def create_rag_session(
    payload: RAGSessionCreate,
    principal: CurrentPrincipal,
):
    return await rag_store.create_session(
        principal,
        payload,
    )


@router.get(
    "/sessions/{session_id}",
    response_model=RAGSessionDetailResponse,
)
async def get_rag_session(
    session_id: str,
    principal: CurrentPrincipal,
):
    return await rag_store.get_session(
        principal,
        session_id,
    )


@router.post(
    "/sessions/{session_id}/close",
    response_model=RAGSessionResponse,
)
async def close_rag_session(
    session_id: str,
    payload: RAGVersionRequest,
    principal: CurrentPrincipal,
):
    return await rag_store.close_session(
        principal,
        session_id,
        payload.expected_version,
    )


@router.get(
    "/statistics",
    response_model=RAGStatisticsResponse,
)
async def rag_statistics(
    principal: CurrentPrincipal,
):
    return await rag_store.statistics(
        principal,
    )


__all__ = [
    "DocumentType",
    "RetrievalMode",
    "RAGSessionStatus",
    "MessageRole",
    "RAGDocumentCreate",
    "RAGSearchRequest",
    "RAGChatRequest",
    "RAGSessionCreate",
    "RAGVersionRequest",
    "RAGDocumentResponse",
    "RAGCitation",
    "RAGSearchResponse",
    "RAGAnswerResponse",
    "RAGMessageResponse",
    "RAGSessionResponse",
    "RAGSessionDetailResponse",
    "RAGStatisticsResponse",
    "RAGStore",
    "RAGService",
    "InMemoryHybridRetriever",
    "GroundedAnswerGenerator",
    "rag_store",
    "rag_service",
    "router",
]
