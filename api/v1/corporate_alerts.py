from __future__ import annotations

"""Planned module: corporate alerts. Implementation pending."""

"""
backend/copilot.py

Autonomous Retail Supply Chain AI 5.0
Enterprise Supply Chain AI Copilot API

Python 3.11+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Conversational supply chain copilot
    - Tenant-isolated chat sessions
    - Warehouse-scoped conversations
    - Inventory, demand and logistics Q&A
    - Supplier and procurement assistance
    - Retrieval-grounded responses
    - Citation references
    - Permission-aware knowledge access
    - Conversation history
    - Source validation
    - Human approval for write actions
    - Idempotent user messages
    - Bounded in-memory prototype

SECURITY:
    - Never execute actions from chat text
    - Do not expose unauthorized documents
    - Treat retrieved content as untrusted
    - Do not accept tenant IDs from callers
    - Do not invent citations
    - Do not expose raw model reasoning

IMPORTANT:
    This module defines an integration-ready
    copilot interface.

    It does not contain a configured LLM,
    vector database, or retrieval pipeline.

    Configure the CopilotProvider adapter
    to connect approved RAG/LLM services.
"""


import asyncio
import hashlib
import json
import secrets

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

from backend.permissions import (
    CurrentPrincipal,
    Permission,
    Principal,
    ResourceContext,
    permission_engine,
)


# ============================================================
# CONFIGURATION
# ============================================================

API_PREFIX = "/api/v1/copilot"

MAX_SESSIONS_PER_TENANT = 5000
MAX_MESSAGES_PER_SESSION = 100
MAX_HISTORY_CONTEXT = 12
MAX_LIST_LIMIT = 100

MAX_QUESTION_LENGTH = 4000
MAX_ANSWER_LENGTH = 12000
MAX_SOURCES = 10


# ============================================================
# ENUMS
# ============================================================

class CopilotDomain(str, Enum):
    GENERAL = "general"
    INVENTORY = "inventory"
    DEMAND = "demand"
    PROCUREMENT = "procurement"
    SUPPLIER = "supplier"
    WAREHOUSE = "warehouse"
    LOGISTICS = "logistics"
    SALES = "sales"
    FINANCE = "finance"
    ANALYTICS = "analytics"


class CopilotRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class CopilotSessionStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"


class CopilotAnswerStatus(str, Enum):
    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = (
        "insufficient_evidence"
    )
    UNAVAILABLE = "unavailable"


# ============================================================
# DOMAIN PERMISSIONS
# ============================================================

DOMAIN_PERMISSIONS = {
    CopilotDomain.GENERAL:
        Permission.ANALYTICS_READ,

    CopilotDomain.INVENTORY:
        Permission.INVENTORY_READ,

    CopilotDomain.DEMAND:
        Permission.ANALYTICS_READ,

    CopilotDomain.PROCUREMENT:
        Permission.PROCUREMENT_READ,

    CopilotDomain.SUPPLIER:
        Permission.SUPPLIER_READ,

    CopilotDomain.WAREHOUSE:
        Permission.ANALYTICS_READ,

    CopilotDomain.LOGISTICS:
        Permission.LOGISTICS_READ,

    CopilotDomain.SALES:
        Permission.ANALYTICS_READ,

    CopilotDomain.FINANCE:
        Permission.FINANCE_READ,

    CopilotDomain.ANALYTICS:
        Permission.ANALYTICS_READ,
}


# ============================================================
# REQUEST MODELS
# ============================================================

class CopilotSessionCreate(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    title: str = Field(
        default="Supply Chain Copilot",
        min_length=1,
        max_length=150,
    )

    domain: CopilotDomain = (
        CopilotDomain.GENERAL
    )

    warehouse_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )


class CopilotMessageCreate(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    question: str = Field(
        min_length=1,
        max_length=MAX_QUESTION_LENGTH,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )


# ============================================================
# RESPONSE MODELS
# ============================================================

class CopilotSource(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    source_id: str
    title: str
    reference: str

    document_id: str | None = None

    excerpt: str | None = None


class CopilotMessageResponse(BaseModel):

    message_id: str
    session_id: str

    role: CopilotRole
    content: str

    answer_status: (
        CopilotAnswerStatus | None
    ) = None

    sources: list[CopilotSource] = Field(
        default_factory=list
    )

    created_at: datetime


class CopilotSessionResponse(BaseModel):

    session_id: str

    title: str
    domain: CopilotDomain
    warehouse_id: str | None

    status: CopilotSessionStatus

    message_count: int

    created_at: datetime
    updated_at: datetime


class CopilotConversationResponse(BaseModel):

    session: CopilotSessionResponse

    messages: list[
        CopilotMessageResponse
    ]


class CopilotChatResponse(BaseModel):

    session_id: str

    user_message: CopilotMessageResponse
    assistant_message: CopilotMessageResponse


class CopilotCapabilityResponse(BaseModel):

    domains: list[CopilotDomain]

    read_only: bool = True

    human_approval_required_for_actions: bool = True

    configured: bool


# ============================================================
# INTERNAL PROVIDER MODELS
# ============================================================

class RetrievedDocument(BaseModel):

    model_config = ConfigDict(
        extra="forbid"
    )

    source_id: str
    title: str
    reference: str

    document_id: str | None = None

    excerpt: str = Field(
        max_length=2000
    )


class CopilotGenerationResult(BaseModel):

    answer: str = Field(
        min_length=1,
        max_length=MAX_ANSWER_LENGTH,
    )

    cited_source_ids: list[str] = Field(
        default_factory=list
    )


class CopilotProvider(Protocol):
    """
    Implement using trusted RAG services.

    The provider must enforce:
        - Tenant isolation
        - Warehouse access scope
        - Document-level permissions
        - Prompt-injection defenses
        - Source provenance

    The application must not trust
    arbitrary source references returned
    by an LLM.
    """

    async def retrieve(
        self,
        *,
        tenant_id: str,
        principal_id: str,
        domain: CopilotDomain,
        warehouse_id: str | None,
        question: str,
    ) -> list[RetrievedDocument]:
        ...

    async def generate(
        self,
        *,
        question: str,
        conversation: list[
            CopilotMessageResponse
        ],
        documents: list[
            RetrievedDocument
        ],
    ) -> CopilotGenerationResult:
        ...


# ============================================================
# INTERNAL SESSION RECORD
# ============================================================

@dataclass
class CopilotSessionRecord:

    session_id: str

    tenant_id: str
    owner_id: str

    title: str
    domain: CopilotDomain

    warehouse_id: str | None

    status: CopilotSessionStatus = (
        CopilotSessionStatus.ACTIVE
    )

    messages: list[
        CopilotMessageResponse
    ] = field(
        default_factory=list
    )

    idempotency: dict[
        str,
        tuple[
            str,
            CopilotChatResponse,
        ],
    ] = field(
        default_factory=dict
    )

    created_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    updated_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint_question(
    question: str,
) -> str:

    return hashlib.sha256(
        question.encode("utf-8")
    ).hexdigest()


def require_copilot_access(
    principal: Principal,
    *,
    domain: CopilotDomain,
    warehouse_id: str | None,
) -> None:

    permission = DOMAIN_PERMISSIONS[
        domain
    ]

    resource = ResourceContext(
        tenant_id=principal.tenant_id,
        warehouse_id=warehouse_id,
    )

    decision = permission_engine.evaluate(
        principal,
        permission,
        resource,
    )

    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail="Copilot permission denied",
        )

    allowed = principal.allowed_warehouse_ids

    if warehouse_id is None:

        if allowed is not None:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Tenant-wide copilot access denied"
                ),
            )

    elif (
        allowed is not None
        and warehouse_id not in allowed
    ):
        raise HTTPException(
            status_code=403,
            detail="Warehouse access denied",
        )


def to_session_response(
    record: CopilotSessionRecord,
) -> CopilotSessionResponse:

    return CopilotSessionResponse(
        session_id=record.session_id,
        title=record.title,
        domain=record.domain,
        warehouse_id=record.warehouse_id,
        status=record.status,
        message_count=len(record.messages),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def validate_citations(
    result: CopilotGenerationResult,
    documents: list[RetrievedDocument],
) -> list[CopilotSource]:

    trusted_documents = {
        document.source_id: document
        for document in documents
    }

    sources = []
    seen = set()

    for source_id in result.cited_source_ids:

        if source_id in seen:
            continue

        document = trusted_documents.get(
            source_id
        )

        if document is None:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Copilot generated an "
                    "unverified source reference"
                ),
            )

        seen.add(source_id)

        sources.append(
            CopilotSource(
                source_id=document.source_id,
                title=document.title,
                reference=document.reference,
                document_id=document.document_id,
                excerpt=document.excerpt,
            )
        )

        if len(sources) >= MAX_SOURCES:
            break

    return sources


# ============================================================
# COPILOT SESSION STORE
# ============================================================

class CopilotStore:

    def __init__(self):

        self._sessions: dict[
            str,
            CopilotSessionRecord,
        ] = {}

        self._lock = asyncio.Lock()

    def _get_record(
        self,
        principal: Principal,
        session_id: str,
    ) -> CopilotSessionRecord:

        record = self._sessions.get(
            session_id
        )

        if (
            record is None
            or record.tenant_id
            != principal.tenant_id
            or record.owner_id
            != principal.principal_id
        ):
            raise HTTPException(
                status_code=404,
                detail="Copilot session not found",
            )

        require_copilot_access(
            principal,
            domain=record.domain,
            warehouse_id=record.warehouse_id,
        )

        return record

    async def create_session(
        self,
        *,
        principal: Principal,
        payload: CopilotSessionCreate,
    ) -> CopilotSessionResponse:

        require_copilot_access(
            principal,
            domain=payload.domain,
            warehouse_id=payload.warehouse_id,
        )

        async with self._lock:

            tenant_count = sum(
                record.tenant_id
                == principal.tenant_id
                for record in self._sessions.values()
            )

            if (
                tenant_count
                >= MAX_SESSIONS_PER_TENANT
            ):
                raise HTTPException(
                    status_code=503,
                    detail="Copilot session capacity reached",
                )

            record = CopilotSessionRecord(
                session_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                owner_id=principal.principal_id,
                title=payload.title,
                domain=payload.domain,
                warehouse_id=payload.warehouse_id,
            )

            self._sessions[
                record.session_id
            ] = record

            return to_session_response(
                record
            )

    async def list_sessions(
        self,
        *,
        principal: Principal,
        limit: int,
    ) -> list[CopilotSessionResponse]:

        async with self._lock:

            records = []

            for record in self._sessions.values():

                if (
                    record.tenant_id
                    != principal.tenant_id
                    or record.owner_id
                    != principal.principal_id
                ):
                    continue

                try:
                    require_copilot_access(
                        principal,
                        domain=record.domain,
                        warehouse_id=record.warehouse_id,
                    )
                except HTTPException:
                    continue

                records.append(record)

            records.sort(
                key=lambda item: item.updated_at,
                reverse=True,
            )

            return [
                to_session_response(record)
                for record in records[:limit]
            ]

    async def get_conversation(
        self,
        *,
        principal: Principal,
        session_id: str,
    ) -> CopilotConversationResponse:

        async with self._lock:

            record = self._get_record(
                principal,
                session_id,
            )

            return CopilotConversationResponse(
                session=to_session_response(
                    record
                ),
                messages=[
                    message.model_copy(deep=True)
                    for message in record.messages
                ],
            )

    async def close_session(
        self,
        *,
        principal: Principal,
        session_id: str,
    ) -> CopilotSessionResponse:

        async with self._lock:

            record = self._get_record(
                principal,
                session_id,
            )

            record.status = (
                CopilotSessionStatus.CLOSED
            )

            record.updated_at = utc_now()

            return to_session_response(
                record
            )


copilot_store = CopilotStore()


# ============================================================
# COPILOT SERVICE
# ============================================================

class CopilotService:

    def __init__(
        self,
        store: CopilotStore,
        provider: CopilotProvider,
    ):

        self.store = store
        self.provider = provider

        # Serializes chat writes in this
        # single-process prototype.
        self._chat_lock = asyncio.Lock()

    async def chat(
        self,
        *,
        principal: Principal,
        session_id: str,
        payload: CopilotMessageCreate,
    ) -> CopilotChatResponse:

        async with self._chat_lock:

            async with self.store._lock:

                record = self.store._get_record(
                    principal,
                    session_id,
                )

                fingerprint = fingerprint_question(
                    payload.question
                )

                previous = record.idempotency.get(
                    payload.source_request_id
                )

                if previous is not None:

                    old_fingerprint, response = previous

                    if old_fingerprint != fingerprint:
                        raise HTTPException(
                            status_code=409,
                            detail="Idempotency conflict",
                        )

                    return response.model_copy(
                        deep=True
                    )

                if (
                    record.status
                    != CopilotSessionStatus.ACTIVE
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Copilot session is closed",
                    )

                if (
                    len(record.messages) + 2
                    > MAX_MESSAGES_PER_SESSION
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Conversation message limit reached",
                    )

                tenant_id = record.tenant_id
                domain = record.domain
                warehouse_id = record.warehouse_id

                history = [
                    item.model_copy(deep=True)
                    for item in record.messages[
                        -MAX_HISTORY_CONTEXT:
                    ]
                ]

            # Retrieve outside the store lock.
            # Provider must enforce the same
            # authorization scope.

            documents = await self.provider.retrieve(
                tenant_id=tenant_id,
                principal_id=principal.principal_id,
                domain=domain,
                warehouse_id=warehouse_id,
                question=payload.question,
            )

            documents = documents[:MAX_SOURCES]

            if documents:

                result = await self.provider.generate(
                    question=payload.question,
                    conversation=history,
                    documents=documents,
                )

                sources = validate_citations(
                    result,
                    documents,
                )

                if not sources:
                    answer = (
                        "I found relevant information, "
                        "but cannot provide a verified "
                        "citation-grounded answer."
                    )

                    answer_status = (
                        CopilotAnswerStatus
                        .INSUFFICIENT_EVIDENCE
                    )

                else:
                    answer = result.answer
                    answer_status = (
                        CopilotAnswerStatus.ANSWERED
                    )

            else:

                answer = (
                    "I could not find authorized "
                    "supporting information for "
                    "this question."
                )

                sources = []

                answer_status = (
                    CopilotAnswerStatus
                    .INSUFFICIENT_EVIDENCE
                )

            now = utc_now()

            user_message = CopilotMessageResponse(
                message_id=secrets.token_urlsafe(18),
                session_id=session_id,
                role=CopilotRole.USER,
                content=payload.question,
                created_at=now,
            )

            assistant_message = CopilotMessageResponse(
                message_id=secrets.token_urlsafe(18),
                session_id=session_id,
                role=CopilotRole.ASSISTANT,
                content=answer,
                answer_status=answer_status,
                sources=sources,
                created_at=utc_now(),
            )

            response = CopilotChatResponse(
                session_id=session_id,
                user_message=user_message,
                assistant_message=assistant_message,
            )

            async with self.store._lock:

                record = self.store._get_record(
                    principal,
                    session_id,
                )

                if (
                    record.status
                    != CopilotSessionStatus.ACTIVE
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Copilot session was closed",
                    )

                record.messages.extend(
                    [
                        user_message,
                        assistant_message,
                    ]
                )

                record.idempotency[
                    payload.source_request_id
                ] = (
                    fingerprint,
                    response.model_copy(deep=True),
                )

                record.updated_at = utc_now()

            return response


# ============================================================
# PROVIDER DEPENDENCY
# ============================================================

def get_copilot_service(
    request: Request,
) -> CopilotService:

    service = getattr(
        request.app.state,
        "copilot_service",
        None,
    )

    if service is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Copilot provider is not configured"
            ),
        )

    return service


# ============================================================
# FASTAPI ROUTER
# ============================================================

router = APIRouter(
    prefix=API_PREFIX,
    tags=["Supply Chain AI Copilot"],
)


@router.get(
    "/capabilities",
    response_model=CopilotCapabilityResponse,
)
async def copilot_capabilities(
    principal: CurrentPrincipal,
    request: Request,
):

    configured = (
        getattr(
            request.app.state,
            "copilot_service",
            None,
        )
        is not None
    )

    allowed_domains = []

    for domain in CopilotDomain:

        try:
            require_copilot_access(
                principal,
                domain=domain,
                warehouse_id=None,
            )
            allowed_domains.append(domain)
        except HTTPException:
            continue

    return CopilotCapabilityResponse(
        domains=allowed_domains,
        configured=configured,
    )


@router.post(
    "/sessions",
    response_model=CopilotSessionResponse,
    status_code=201,
)
async def create_copilot_session(
    payload: CopilotSessionCreate,
    principal: CurrentPrincipal,
):

    return await copilot_store.create_session(
        principal=principal,
        payload=payload,
    )


@router.get(
    "/sessions",
    response_model=list[CopilotSessionResponse],
)
async def list_copilot_sessions(
    principal: CurrentPrincipal,
    limit: int = Query(
        default=50,
        ge=1,
        le=MAX_LIST_LIMIT,
    ),
):

    return await copilot_store.list_sessions(
        principal=principal,
        limit=limit,
    )


@router.get(
    "/sessions/{session_id}",
    response_model=CopilotConversationResponse,
)
async def get_copilot_conversation(
    session_id: str,
    principal: CurrentPrincipal,
):

    return await copilot_store.get_conversation(
        principal=principal,
        session_id=session_id,
    )


@router.post(
    "/sessions/{session_id}/messages",
    response_model=CopilotChatResponse,
)
async def send_copilot_message(
    session_id: str,
    payload: CopilotMessageCreate,
    principal: CurrentPrincipal,
    service: CopilotService = Depends(
        get_copilot_service
    ),
):

    return await service.chat(
        principal=principal,
        session_id=session_id,
        payload=payload,
    )


@router.post(
    "/sessions/{session_id}/close",
    response_model=CopilotSessionResponse,
)
async def close_copilot_session(
    session_id: str,
    principal: CurrentPrincipal,
):

    return await copilot_store.close_session(
        principal=principal,
        session_id=session_id,
    )


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "CopilotDomain",
    "CopilotRole",
    "CopilotSessionStatus",
    "CopilotAnswerStatus",
    "CopilotSessionCreate",
    "CopilotMessageCreate",
    "CopilotSource",
    "CopilotMessageResponse",
    "CopilotSessionResponse",
    "CopilotConversationResponse",
    "CopilotChatResponse",
    "CopilotCapabilityResponse",
    "RetrievedDocument",
    "CopilotGenerationResult",
    "CopilotProvider",
    "CopilotSessionRecord",
    "CopilotStore",
    "CopilotService",
    "copilot_store",
    "get_copilot_service",
    "router",
]
