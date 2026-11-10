from __future__ import annotations

"""Planned module: agent runs. Implementation pending."""

"""
backend/agent_runs.py

Autonomous Retail Supply Chain AI 5.0

AI Agent Run Management

Python 3.10+
Dependencies:
    fastapi
    pydantic >= 2

Features:
    - Agent execution lifecycle
    - Multi-agent run tracking
    - Run status and progress
    - Agent handoff records
    - Tool execution records
    - Human approval requests
    - Run cancellation
    - Tenant-isolated access
    - Owner-scoped run visibility
    - Warehouse-scoped permissions
    - Bounded execution history
    - Idempotent run creation

Security:
    - Authenticated API access
    - No arbitrary tool execution
    - No automatic privileged actions
    - Human approval is a state transition,
      not permission to bypass authorization
    - No secrets in public run responses
    - No cross-tenant run access

This is an in-memory prototype.
Replace with durable storage and workers
for production.
"""


import asyncio
import hashlib
import json
import secrets

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
)

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


# ============================================================
# CONFIGURATION
# ============================================================

MAX_RUNS_PER_TENANT = 5000
MAX_EVENTS_PER_RUN = 500
MAX_HANDOFFS_PER_RUN = 100
MAX_TOOLS_PER_RUN = 200
MAX_APPROVALS_PER_RUN = 100

MAX_AGENT_NAME_LENGTH = 128
MAX_MESSAGE_LENGTH = 1000

TERMINAL_STATUSES = {
    "completed",
    "failed",
    "cancelled",
}


# ============================================================
# ENUMS
# ============================================================

class AgentRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentRunEventType(str, Enum):
    CREATED = "created"
    STARTED = "started"
    PROGRESS = "progress"
    AGENT_HANDOFF = "agent_handoff"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_REJECTED = "approval_rejected"
    RESUMED = "resumed"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ToolRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


# ============================================================
# REQUEST MODELS
# ============================================================

class AgentRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_type: str = Field(
        min_length=1,
        max_length=MAX_AGENT_NAME_LENGTH,
    )

    workflow_name: str = Field(
        min_length=1,
        max_length=200,
    )

    warehouse_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )

    source_request_id: str = Field(
        min_length=8,
        max_length=128,
    )

    input_reference_id: str | None = Field(
        default=None,
        max_length=128,
    )


class AgentProgressUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    progress_percent: float = Field(
        ge=0,
        le=100,
        allow_inf_nan=False,
    )

    message: str = Field(
        min_length=1,
        max_length=MAX_MESSAGE_LENGTH,
    )


class AgentHandoffCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_agent: str = Field(
        min_length=1,
        max_length=MAX_AGENT_NAME_LENGTH,
    )

    to_agent: str = Field(
        min_length=1,
        max_length=MAX_AGENT_NAME_LENGTH,
    )

    reason: str = Field(
        min_length=1,
        max_length=MAX_MESSAGE_LENGTH,
    )


class ToolRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(
        min_length=1,
        max_length=128,
    )

    operation_name: str = Field(
        min_length=1,
        max_length=128,
    )

    # Never accept raw tool arguments or secrets
    # in this tracking model.
    input_reference_id: str | None = None


class ApprovalRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: str = Field(
        min_length=1,
        max_length=128,
    )

    resource_id: str | None = Field(
        default=None,
        max_length=128,
    )

    reason: str = Field(
        min_length=1,
        max_length=MAX_MESSAGE_LENGTH,
    )


# ============================================================
# RESPONSE MODELS
# ============================================================

class AgentRunEventResponse(BaseModel):
    event_id: str
    run_id: str
    sequence: int
    event_type: AgentRunEventType
    message: str
    timestamp: datetime


class AgentHandoffResponse(BaseModel):
    handoff_id: str
    run_id: str
    from_agent: str
    to_agent: str
    reason: str
    created_at: datetime


class ToolRunResponse(BaseModel):
    tool_run_id: str
    run_id: str
    tool_name: str
    operation_name: str
    status: ToolRunStatus
    started_at: datetime
    completed_at: datetime | None = None
    error_code: str | None = None


class ApprovalResponse(BaseModel):
    approval_id: str
    run_id: str
    action_type: str
    resource_id: str | None
    status: ApprovalStatus
    requested_at: datetime
    decided_at: datetime | None = None
    decided_by: str | None = None


class AgentRunResponse(BaseModel):
    run_id: str
    agent_type: str
    workflow_name: str
    warehouse_id: str | None

    status: AgentRunStatus

    progress_percent: float

    current_agent: str | None

    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    error_code: str | None = None


class AgentRunDetailResponse(AgentRunResponse):
    events: list[AgentRunEventResponse]
    handoffs: list[AgentHandoffResponse]
    tools: list[ToolRunResponse]
    approvals: list[ApprovalResponse]


# ============================================================
# INTERNAL DATA
# ============================================================

@dataclass
class AgentRunRecord:
    run_id: str
    tenant_id: str
    owner_id: str

    agent_type: str
    workflow_name: str
    warehouse_id: str | None

    source_request_id: str
    payload_fingerprint: str

    input_reference_id: str | None

    status: AgentRunStatus = AgentRunStatus.PENDING

    progress_percent: float = 0.0

    current_agent: str | None = None

    created_at: datetime = field(
        default_factory=lambda: datetime.now(
            timezone.utc
        )
    )

    started_at: datetime | None = None
    completed_at: datetime | None = None

    error_code: str | None = None

    sequence: int = 0

    events: deque[AgentRunEventResponse] = field(
        default_factory=lambda: deque(
            maxlen=MAX_EVENTS_PER_RUN
        )
    )

    handoffs: list[AgentHandoffResponse] = field(
        default_factory=list
    )

    tools: list[ToolRunResponse] = field(
        default_factory=list
    )

    approvals: list[ApprovalResponse] = field(
        default_factory=list
    )


# ============================================================
# HELPERS
# ============================================================

def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint_request(
    payload: AgentRunCreate,
) -> str:

    canonical = json.dumps(
        payload.model_dump(
            mode="json",
            exclude={"source_request_id"},
        ),
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()


def to_response(
    run: AgentRunRecord,
) -> AgentRunResponse:

    return AgentRunResponse(
        run_id=run.run_id,
        agent_type=run.agent_type,
        workflow_name=run.workflow_name,
        warehouse_id=run.warehouse_id,
        status=run.status,
        progress_percent=run.progress_percent,
        current_agent=run.current_agent,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        error_code=run.error_code,
    )


def to_detail_response(
    run: AgentRunRecord,
) -> AgentRunDetailResponse:

    return AgentRunDetailResponse(
        **to_response(run).model_dump(),
        events=list(run.events),
        handoffs=list(run.handoffs),
        tools=list(run.tools),
        approvals=list(run.approvals),
    )


# ============================================================
# AUTHORIZATION
# ============================================================

def require_agent_access(
    principal: Principal,
    warehouse_id: str | None,
    *,
    execute: bool = False,
) -> None:

    permission = (
        Permission.AI_AGENT_EXECUTE
        if execute
        else Permission.AI_AGENT_READ
    )

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
            detail="Agent access denied",
        )

    allowed = principal.allowed_warehouse_ids

    if (
        warehouse_id is not None
        and allowed is not None
        and warehouse_id not in allowed
    ):
        raise HTTPException(
            status_code=403,
            detail="Warehouse access denied",
        )


# ============================================================
# AGENT RUN STORE
# ============================================================

class AgentRunStore:

    def __init__(self):
        self._runs: dict[
            str,
            AgentRunRecord,
        ] = {}

        self._idempotency: dict[
            tuple[str, str, str],
            str,
        ] = {}

        self._lock = asyncio.Lock()

    def _add_event(
        self,
        run: AgentRunRecord,
        event_type: AgentRunEventType,
        message: str,
    ) -> None:

        run.sequence += 1

        run.events.append(
            AgentRunEventResponse(
                event_id=secrets.token_urlsafe(16),
                run_id=run.run_id,
                sequence=run.sequence,
                event_type=event_type,
                message=message[:MAX_MESSAGE_LENGTH],
                timestamp=utc_now(),
            )
        )

    async def create(
        self,
        *,
        principal: Principal,
        payload: AgentRunCreate,
    ) -> AgentRunRecord:

        require_agent_access(
            principal,
            payload.warehouse_id,
            execute=True,
        )

        fingerprint = fingerprint_request(
            payload
        )

        idempotency_key = (
            principal.tenant_id,
            principal.principal_id,
            payload.source_request_id,
        )

        async with self._lock:

            existing_id = self._idempotency.get(
                idempotency_key
            )

            if existing_id is not None:

                existing = self._runs[
                    existing_id
                ]

                if (
                    existing.payload_fingerprint
                    != fingerprint
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict",
                    )

                return existing

            tenant_count = sum(
                run.tenant_id == principal.tenant_id
                for run in self._runs.values()
            )

            if tenant_count >= MAX_RUNS_PER_TENANT:
                raise HTTPException(
                    status_code=503,
                    detail="Agent run capacity reached",
                )

            run = AgentRunRecord(
                run_id=secrets.token_urlsafe(20),
                tenant_id=principal.tenant_id,
                owner_id=principal.principal_id,
                agent_type=payload.agent_type,
                workflow_name=payload.workflow_name,
                warehouse_id=payload.warehouse_id,
                source_request_id=payload.source_request_id,
                payload_fingerprint=fingerprint,
                input_reference_id=payload.input_reference_id,
                current_agent=payload.agent_type,
            )

            self._add_event(
                run,
                AgentRunEventType.CREATED,
                "Agent run created",
            )

            self._runs[run.run_id] = run

            self._idempotency[
                idempotency_key
            ] = run.run_id

            return run

    async def get(
        self,
        *,
        principal: Principal,
        run_id: str,
    ) -> AgentRunRecord:

        async with self._lock:

            run = self._runs.get(run_id)

            if (
                run is None
                or run.tenant_id != principal.tenant_id
            ):
                raise HTTPException(
                    status_code=404,
                    detail="Agent run not found",
                )

            if run.owner_id != principal.principal_id:
                raise HTTPException(
                    status_code=403,
                    detail="Run owner access required",
                )

            require_agent_access(
                principal,
                run.warehouse_id,
            )

            return run

    async def list_runs(
        self,
        *,
        principal: Principal,
        limit: int = 50,
    ) -> list[AgentRunRecord]:

        require_agent_access(
            principal,
            None,
        )

        async with self._lock:

            runs = [
                run
                for run in self._runs.values()
                if (
                    run.tenant_id == principal.tenant_id
                    and run.owner_id == principal.principal_id
                    and (
                        run.warehouse_id is None
                        or principal.allowed_warehouse_ids is None
                        or run.warehouse_id
                        in principal.allowed_warehouse_ids
                    )
                )
            ]

            runs.sort(
                key=lambda item: item.created_at,
                reverse=True,
            )

            return runs[:limit]

    async def start(
        self,
        run: AgentRunRecord,
    ) -> None:

        async with self._lock:

            if run.status != AgentRunStatus.PENDING:
                raise ValueError(
                    "Run is not pending"
                )

            run.status = AgentRunStatus.RUNNING
            run.started_at = utc_now()

            self._add_event(
                run,
                AgentRunEventType.STARTED,
                "Agent run started",
            )

    async def update_progress(
        self,
        run: AgentRunRecord,
        payload: AgentProgressUpdate,
    ) -> None:

        async with self._lock:

            if run.status != AgentRunStatus.RUNNING:
                raise ValueError(
                    "Run is not active"
                )

            run.progress_percent = (
                payload.progress_percent
            )

            self._add_event(
                run,
                AgentRunEventType.PROGRESS,
                payload.message,
            )

    async def handoff(
        self,
        run: AgentRunRecord,
        payload: AgentHandoffCreate,
    ) -> AgentHandoffResponse:

        async with self._lock:

            if run.status != AgentRunStatus.RUNNING:
                raise ValueError(
                    "Run is not active"
                )

            if len(run.handoffs) >= MAX_HANDOFFS_PER_RUN:
                raise ValueError(
                    "Handoff limit reached"
                )

            if run.current_agent != payload.from_agent:
                raise ValueError(
                    "Handoff source does not match "
                    "the current agent"
                )

            handoff = AgentHandoffResponse(
                handoff_id=secrets.token_urlsafe(16),
                run_id=run.run_id,
                from_agent=payload.from_agent,
                to_agent=payload.to_agent,
                reason=payload.reason,
                created_at=utc_now(),
            )

            run.handoffs.append(handoff)
            run.current_agent = payload.to_agent

            self._add_event(
                run,
                AgentRunEventType.AGENT_HANDOFF,
                "Agent handoff recorded",
            )

            return handoff

    async def start_tool(
        self,
        run: AgentRunRecord,
        payload: ToolRunCreate,
    ) -> ToolRunResponse:

        async with self._lock:

            if run.status != AgentRunStatus.RUNNING:
                raise ValueError(
                    "Run is not active"
                )

            if len(run.tools) >= MAX_TOOLS_PER_RUN:
                raise ValueError(
                    "Tool tracking limit reached"
                )

            tool = ToolRunResponse(
                tool_run_id=secrets.token_urlsafe(16),
                run_id=run.run_id,
                tool_name=payload.tool_name,
                operation_name=payload.operation_name,
                status=ToolRunStatus.RUNNING,
                started_at=utc_now(),
            )

            run.tools.append(tool)

            self._add_event(
                run,
                AgentRunEventType.TOOL_STARTED,
                "Tool execution started",
            )

            return tool

    async def finish_tool(
        self,
        run: AgentRunRecord,
        tool_run_id: str,
        *,
        success: bool,
        error_code: str | None = None,
    ) -> ToolRunResponse:

        async with self._lock:

            tool = next(
                (
                    item
                    for item in run.tools
                    if item.tool_run_id == tool_run_id
                ),
                None,
            )

            if tool is None:
                raise ValueError(
                    "Tool execution not found"
                )

            if tool.status != ToolRunStatus.RUNNING:
                raise ValueError(
                    "Tool execution already finished"
                )

            if run.status != AgentRunStatus.RUNNING:
                raise ValueError(
                    "Run is not active"
                )

            tool.status = (
                ToolRunStatus.COMPLETED
                if success
                else ToolRunStatus.FAILED
            )

            tool.completed_at = utc_now()
            tool.error_code = error_code

            self._add_event(
                run,
                AgentRunEventType.TOOL_COMPLETED,
                "Tool execution finished",
            )

            return tool

    async def request_approval(
        self,
        run: AgentRunRecord,
        payload: ApprovalRequestCreate,
    ) -> ApprovalResponse:

        async with self._lock:

            if run.status != AgentRunStatus.RUNNING:
                raise ValueError(
                    "Run is not active"
                )

            if len(run.approvals) >= MAX_APPROVALS_PER_RUN:
                raise ValueError(
                    "Approval limit reached"
                )

            approval = ApprovalResponse(
                approval_id=secrets.token_urlsafe(16),
                run_id=run.run_id,
                action_type=payload.action_type,
                resource_id=payload.resource_id,
                status=ApprovalStatus.PENDING,
                requested_at=utc_now(),
            )

            run.approvals.append(approval)

            run.status = AgentRunStatus.WAITING_APPROVAL

            self._add_event(
                run,
                AgentRunEventType.APPROVAL_REQUESTED,
                "Human approval requested",
            )

            return approval

    async def decide_approval(
        self,
        run: AgentRunRecord,
        approval_id: str,
        *,
        principal: Principal,
        approve: bool,
    ) -> ApprovalResponse:

        # Approval authority must be independently
        # verified by the actual approval service.
        # Run owners cannot approve their own
        # privileged actions through this store.

        raise NotImplementedError(
            "Use the authorized approval_service "
            "to verify approver eligibility, "
            "separation of duties, and action scope"
        )

    async def finish(
        self,
        run: AgentRunRecord,
        *,
        success: bool,
        error_code: str | None = None,
    ) -> None:

        async with self._lock:

            if run.status != AgentRunStatus.RUNNING:
                raise ValueError(
                    "Run is not active"
                )

            if any(
                tool.status == ToolRunStatus.RUNNING
                for tool in run.tools
            ):
                raise ValueError(
                    "Cannot finish with active tools"
                )

            run.status = (
                AgentRunStatus.COMPLETED
                if success
                else AgentRunStatus.FAILED
            )

            run.completed_at = utc_now()
            run.error_code = error_code

            if success:
                run.progress_percent = 100.0

            self._add_event(
                run,
                (
                    AgentRunEventType.COMPLETED
                    if success
                    else AgentRunEventType.FAILED
                ),
                "Agent run finished",
            )

    async def cancel(
        self,
        run: AgentRunRecord,
    ) -> None:

        async with self._lock:

            if run.status in {
                AgentRunStatus.COMPLETED,
                AgentRunStatus.FAILED,
                AgentRunStatus.CANCELLED,
            }:
                return

            run.status = AgentRunStatus.CANCELLED
            run.completed_at = utc_now()

            self._add_event(
                run,
                AgentRunEventType.CANCELLED,
                "Agent run cancellation recorded",
            )


agent_run_store = AgentRunStore()


# ============================================================
# API ROUTER
# ============================================================

router = APIRouter(
    prefix="/api/v1/agent-runs",
    tags=["Agent Runs"],
)


@router.post(
    "",
    response_model=AgentRunResponse,
    status_code=201,
)
async def create_agent_run(
    payload: AgentRunCreate,
    principal: CurrentPrincipal,
):

    run = await agent_run_store.create(
        principal=principal,
        payload=payload,
    )

    return to_response(run)


@router.get(
    "",
    response_model=list[AgentRunResponse],
)
async def list_agent_runs(
    principal: CurrentPrincipal,
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
    ),
):

    runs = await agent_run_store.list_runs(
        principal=principal,
        limit=limit,
    )

    return [
        to_response(run)
        for run in runs
    ]


@router.get(
    "/{run_id}",
    response_model=AgentRunDetailResponse,
)
async def get_agent_run(
    run_id: str,
    principal: CurrentPrincipal,
):

    run = await agent_run_store.get(
        principal=principal,
        run_id=run_id,
    )

    return to_detail_response(run)


@router.get(
    "/{run_id}/events",
    response_model=list[AgentRunEventResponse],
)
async def get_agent_run_events(
    run_id: str,
    principal: CurrentPrincipal,
):

    run = await agent_run_store.get(
        principal=principal,
        run_id=run_id,
    )

    return list(run.events)


@router.get(
    "/{run_id}/tools",
    response_model=list[ToolRunResponse],
)
async def get_agent_run_tools(
    run_id: str,
    principal: CurrentPrincipal,
):

    run = await agent_run_store.get(
        principal=principal,
        run_id=run_id,
    )

    return list(run.tools)


@router.get(
    "/{run_id}/approvals",
    response_model=list[ApprovalResponse],
)
async def get_agent_run_approvals(
    run_id: str,
    principal: CurrentPrincipal,
):

    run = await agent_run_store.get(
        principal=principal,
        run_id=run_id,
    )

    return list(run.approvals)


@router.post(
    "/{run_id}/cancel",
    response_model=AgentRunResponse,
)
async def cancel_agent_run(
    run_id: str,
    principal: CurrentPrincipal,
):

    run = await agent_run_store.get(
        principal=principal,
        run_id=run_id,
    )

    require_agent_access(
        principal,
        run.warehouse_id,
        execute=True,
    )

    await agent_run_store.cancel(run)

    return to_response(run)
