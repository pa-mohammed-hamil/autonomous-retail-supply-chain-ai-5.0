"""Planned module: base agent. Implementation pending."""

"""
File: ai/agents/base_agent.py
Project: Autonomous Retail Supply Chain AI 5.0

Reusable agent execution framework.

Features:
- Typed agent requests and responses
- Agent capability registration
- Input validation
- Tenant-scoped execution context
- Execution lifecycle management
- Safe error reporting
- Thread-safe audit history
- Optional working memory integration
- Extension points for specialized agents

Python 3.10+
Standard library only.
"""

from __future__ import annotations

import copy
import json
import threading
import time

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


class AgentError(Exception):
    """Base agent exception."""


class AgentValidationError(AgentError):
    """Invalid agent input."""


class AgentExecutionError(AgentError):
    """Agent execution failure."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentValidationError(
            f"{name} must be a nonempty string."
        )
    return value.strip()


def json_copy(value: Any) -> Any:
    try:
        return json.loads(
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
            )
        )
    except (TypeError, ValueError) as exc:
        raise AgentValidationError(
            "Payload must be JSON serializable."
        ) from exc


@dataclass(frozen=True)
class AgentContext:
    tenant_id: str
    user_id: str
    workflow_id: str
    task_id: str
    roles: frozenset[str] = field(
        default_factory=frozenset
    )
    correlation_id: str = field(
        default_factory=lambda: str(uuid4())
    )


@dataclass(frozen=True)
class AgentRequest:
    task_type: str
    payload: dict[str, Any]
    context: AgentContext


@dataclass
class AgentResponse:
    execution_id: str
    agent_id: str
    task_type: str
    tenant_id: str
    status: str
    success: bool
    result: dict[str, Any] | None
    error_code: str | None
    duration_ms: float
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BaseAgent(ABC):
    """
    Base class for specialized retail AI agents.

    Each subclass implements process().

    Tenant/user identity must come from a trusted
    authentication layer, not LLM-generated text.
    """

    def __init__(
        self,
        agent_id: str,
        name: str,
        capabilities: set[str],
        working_memory: Any | None = None,
        max_history: int = 1000,
    ) -> None:
        self.agent_id = require_text(
            agent_id, "agent_id"
        )
        self.name = require_text(name, "name")

        if not capabilities:
            raise AgentValidationError(
                "At least one capability is required."
            )

        self.capabilities = frozenset(
            require_text(c, "capability")
            for c in capabilities
        )

        if (
            isinstance(max_history, bool)
            or not isinstance(max_history, int)
            or max_history <= 0
        ):
            raise AgentValidationError(
                "max_history must be positive."
            )

        self.working_memory = working_memory
        self.max_history = max_history

        self._history: list[AgentResponse] = []
        self._lock = threading.RLock()

    def validate_request(
        self,
        request: AgentRequest,
    ) -> None:
        if not isinstance(request, AgentRequest):
            raise AgentValidationError(
                "Expected AgentRequest."
            )

        require_text(
            request.task_type, "task_type"
        )

        if request.task_type not in self.capabilities:
            raise AgentValidationError(
                "Unsupported task type."
            )

        if not isinstance(request.payload, dict):
            raise AgentValidationError(
                "Payload must be a dictionary."
            )

        context = request.context

        for name in (
            "tenant_id",
            "user_id",
            "workflow_id",
            "task_id",
        ):
            require_text(
                getattr(context, name),
                name,
            )

        json_copy(request.payload)

    def save_working_context(
        self,
        request: AgentRequest,
        values: dict[str, Any],
        ttl_seconds: int = 1800,
    ) -> str | None:
        """
        Save context in the existing WorkingMemory API.

        Returns the workspace ID when configured.
        """
        if self.working_memory is None:
            return None

        workspace = self.working_memory.create_workspace(
            tenant_id=request.context.tenant_id,
            agent_id=self.agent_id,
            task_id=request.context.task_id,
            workflow_id=request.context.workflow_id,
        )

        workspace_id = workspace["workspace_id"]

        self.working_memory.update_many(
            workspace_id=workspace_id,
            tenant_id=request.context.tenant_id,
            agent_id=self.agent_id,
            updates=json_copy(values),
            ttl_seconds=ttl_seconds,
        )

        return workspace_id

    @abstractmethod
    def process(
        self,
        request: AgentRequest,
    ) -> dict[str, Any]:
        """
        Implement specialized agent behavior.

        Must return a JSON-serializable dictionary.
        """

    def execute(
        self,
        request: AgentRequest,
    ) -> dict[str, Any]:
        started = time.monotonic()
        execution_id = str(uuid4())
        created_at = utc_now()

        task_type = (
            request.task_type
            if isinstance(request, AgentRequest)
            else "unknown"
        )

        tenant_id = (
            request.context.tenant_id
            if isinstance(request, AgentRequest)
            and isinstance(request.context, AgentContext)
            else "unknown"
        )

        try:
            self.validate_request(request)

            result = self.process(request)

            if not isinstance(result, dict):
                raise AgentExecutionError(
                    "Agent must return a dictionary."
                )

            result = json_copy(result)

            response = AgentResponse(
                execution_id=execution_id,
                agent_id=self.agent_id,
                task_type=task_type,
                tenant_id=tenant_id,
                status="completed",
                success=True,
                result=result,
                error_code=None,
                duration_ms=round(
                    (time.monotonic() - started) * 1000,
                    2,
                ),
                created_at=created_at,
            )

        except AgentValidationError:
            response = AgentResponse(
                execution_id=execution_id,
                agent_id=self.agent_id,
                task_type=task_type,
                tenant_id=tenant_id,
                status="rejected",
                success=False,
                result=None,
                error_code="VALIDATION_ERROR",
                duration_ms=round(
                    (time.monotonic() - started) * 1000,
                    2,
                ),
                created_at=created_at,
            )

        except Exception:
            response = AgentResponse(
                execution_id=execution_id,
                agent_id=self.agent_id,
                task_type=task_type,
                tenant_id=tenant_id,
                status="failed",
                success=False,
                result=None,
                error_code="EXECUTION_ERROR",
                duration_ms=round(
                    (time.monotonic() - started) * 1000,
                    2,
                ),
                created_at=created_at,
            )

        with self._lock:
            self._history.append(response)

            if len(self._history) > self.max_history:
                self._history = self._history[
                    -self.max_history:
                ]

        return response.to_dict()

    def history(
        self,
        tenant_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        tenant_id = require_text(
            tenant_id, "tenant_id"
        )

        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 1000
        ):
            raise AgentValidationError(
                "Invalid history limit."
            )

        with self._lock:
            records = [
                item
                for item in self._history
                if item.tenant_id == tenant_id
            ]

        return [
            item.to_dict()
            for item in records[-limit:]
        ]

    def describe(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "capabilities": sorted(self.capabilities),
            "working_memory_enabled": (
                self.working_memory is not None
            ),
        }
