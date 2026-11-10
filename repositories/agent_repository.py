from __future__ import annotations

"""Planned module: agent repository. Implementation pending."""

"""
ai/agents/agent_repository.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+ | Standard library only

Features:
- Tenant-isolated AI agent registry
- Agent metadata and capability discovery
- Semantic version registration
- Role-based agent access
- Enable / disable lifecycle
- Active-version selection
- Optimistic concurrency
- Agent inventory metrics
- Audit trail
- JSON export

Reference implementation.
No dynamic code loading or real agent execution.
"""


import copy
import json
import re
import threading
import uuid

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def required(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 255
    ):
        raise ValueError(f"Invalid {name}")
    return value.strip()


def validate_version(value: str) -> str:
    value = required(value, "version")

    if not re.fullmatch(
        r"0|[1-9]\d*"
        r"\.(?:0|[1-9]\d*)"
        r"\.(?:0|[1-9]\d*)",
        value,
    ):
        raise ValueError(
            "Version must use MAJOR.MINOR.PATCH"
        )

    return value


class AgentStatus(str, Enum):
    REGISTERED = "registered"
    ACTIVE = "active"
    DISABLED = "disabled"


@dataclass(frozen=True)
class AgentActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    is_active: bool = True


@dataclass(frozen=True)
class AgentVersion:
    version: str
    description: str
    capabilities: frozenset[str]
    allowed_roles: frozenset[str]
    requires_approval: bool
    registered_at: str


@dataclass
class AgentRecord:
    agent_id: str
    tenant_id: str
    name: str
    module_path: str
    status: AgentStatus
    versions: dict[str, AgentVersion]
    active_version: str | None
    created_at: str
    updated_at: str
    revision: int = 1


@dataclass(frozen=True)
class AgentAuditEvent:
    event_id: str
    tenant_id: str
    agent_id: str
    actor_id: str
    action: str
    timestamp: str
    details: dict[str, Any] = field(
        default_factory=dict
    )


class RetailAgentRepository:
    ADMIN_ROLES = frozenset({
        "corporate_admin",
        "ai_platform_admin",
    })

    READER_ROLES = ADMIN_ROLES | frozenset({
        "ai_engineer",
        "operations_manager",
        "business_analyst",
    })

    def __init__(self, tenant_id: str):
        self.tenant_id = required(
            tenant_id, "tenant_id"
        )

        self._lock = threading.RLock()
        self._agents: dict[str, AgentRecord] = {}
        self._audit: list[AgentAuditEvent] = []

    def _authorize(
        self,
        actor: AgentActor,
        roles: frozenset[str],
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id != self.tenant_id
            or not actor.user_id.strip()
            or not actor.roles.intersection(roles)
        ):
            raise PermissionError(
                "Agent repository access denied"
            )

    def _get(self, agent_id: str) -> AgentRecord:
        record = self._agents.get(agent_id)

        if record is None:
            raise KeyError("Agent not found")

        return record

    def _record(
        self,
        actor: AgentActor,
        agent_id: str,
        action: str,
        details: dict | None = None,
    ) -> None:
        self._audit.append(AgentAuditEvent(
            event_id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            agent_id=agent_id,
            actor_id=actor.user_id,
            action=action,
            timestamp=utc_now(),
            details=copy.deepcopy(details or {}),
        ))

    @staticmethod
    def _touch(record: AgentRecord) -> None:
        record.revision += 1
        record.updated_at = utc_now()

    @staticmethod
    def _validate_version_data(
        version: AgentVersion,
    ) -> None:
        validate_version(version.version)

        if not version.capabilities:
            raise ValueError(
                "Agent requires at least one capability"
            )

        if not version.allowed_roles:
            raise ValueError(
                "Agent requires allowed roles"
            )

        for capability in version.capabilities:
            required(capability, "capability")

        for role in version.allowed_roles:
            required(role, "role")

    def register_agent(
        self,
        actor: AgentActor,
        agent_id: str,
        name: str,
        module_path: str,
        version: str,
        description: str,
        capabilities: frozenset[str],
        allowed_roles: frozenset[str],
        requires_approval: bool = False,
    ) -> AgentRecord:
        self._authorize(actor, self.ADMIN_ROLES)

        agent_id = required(agent_id, "agent_id")
        name = required(name, "name")
        module_path = required(
            module_path, "module_path"
        )
        version = validate_version(version)

        if not isinstance(requires_approval, bool):
            raise ValueError("Invalid approval flag")

        agent_version = AgentVersion(
            version=version,
            description=required(
                description, "description"
            ),
            capabilities=capabilities,
            allowed_roles=allowed_roles,
            requires_approval=requires_approval,
            registered_at=utc_now(),
        )

        self._validate_version_data(agent_version)

        with self._lock:
            if agent_id in self._agents:
                raise ValueError("Agent already exists")

            current = utc_now()

            record = AgentRecord(
                agent_id=agent_id,
                tenant_id=self.tenant_id,
                name=name,
                module_path=module_path,
                status=AgentStatus.REGISTERED,
                versions={version: agent_version},
                active_version=None,
                created_at=current,
                updated_at=current,
            )

            self._agents[agent_id] = record

            self._record(
                actor, agent_id, "registered",
                {"version": version},
            )

            return copy.deepcopy(record)

    def add_version(
        self,
        actor: AgentActor,
        agent_id: str,
        expected_revision: int,
        version: str,
        description: str,
        capabilities: frozenset[str],
        allowed_roles: frozenset[str],
        requires_approval: bool = False,
    ) -> AgentRecord:
        self._authorize(actor, self.ADMIN_ROLES)

        version = validate_version(version)

        new_version = AgentVersion(
            version=version,
            description=required(
                description, "description"
            ),
            capabilities=capabilities,
            allowed_roles=allowed_roles,
            requires_approval=requires_approval,
            registered_at=utc_now(),
        )

        self._validate_version_data(new_version)

        with self._lock:
            record = self._get(agent_id)

            if record.revision != expected_revision:
                raise ValueError("Revision conflict")

            if version in record.versions:
                raise ValueError("Version already exists")

            record.versions[version] = new_version
            self._touch(record)

            self._record(
                actor, agent_id, "version_added",
                {"version": version},
            )

            return copy.deepcopy(record)

    def activate_agent(
        self,
        actor: AgentActor,
        agent_id: str,
        version: str,
        expected_revision: int,
    ) -> AgentRecord:
        self._authorize(actor, self.ADMIN_ROLES)

        with self._lock:
            record = self._get(agent_id)

            if record.revision != expected_revision:
                raise ValueError("Revision conflict")

            if version not in record.versions:
                raise ValueError("Unknown agent version")

            record.active_version = version
            record.status = AgentStatus.ACTIVE
            self._touch(record)

            self._record(
                actor, agent_id, "activated",
                {"version": version},
            )

            return copy.deepcopy(record)

    def disable_agent(
        self,
        actor: AgentActor,
        agent_id: str,
        expected_revision: int,
        reason: str,
    ) -> AgentRecord:
        self._authorize(actor, self.ADMIN_ROLES)
        reason = required(reason, "reason")

        with self._lock:
            record = self._get(agent_id)

            if record.revision != expected_revision:
                raise ValueError("Revision conflict")

            if record.status != AgentStatus.ACTIVE:
                raise ValueError("Agent is not active")

            record.status = AgentStatus.DISABLED
            self._touch(record)

            self._record(
                actor, agent_id, "disabled",
                {"reason": reason},
            )

            return copy.deepcopy(record)

    def get_agent(
        self,
        actor: AgentActor,
        agent_id: str,
    ) -> AgentRecord:
        self._authorize(actor, self.READER_ROLES)

        with self._lock:
            return copy.deepcopy(self._get(agent_id))

    def list_agents(
        self,
        actor: AgentActor,
        status: AgentStatus | None = None,
    ) -> list[AgentRecord]:
        self._authorize(actor, self.READER_ROLES)

        with self._lock:
            return [
                copy.deepcopy(record)
                for record in self._agents.values()
                if (
                    status is None
                    or record.status == status
                )
            ]

    def discover_agents(
        self,
        actor: AgentActor,
        capability: str,
    ) -> list[AgentRecord]:
        self._authorize(actor, self.READER_ROLES)
        capability = required(
            capability, "capability"
        )

        with self._lock:
            results = []

            for record in self._agents.values():
                if (
                    record.status != AgentStatus.ACTIVE
                    or record.active_version is None
                ):
                    continue

                version = record.versions[
                    record.active_version
                ]

                if (
                    capability in version.capabilities
                    and bool(
                        actor.roles.intersection(
                            version.allowed_roles
                        )
                    )
                ):
                    results.append(copy.deepcopy(record))

            return results

    def check_access(
        self,
        actor: AgentActor,
        agent_id: str,
    ) -> dict[str, Any]:
        self._authorize(actor, self.READER_ROLES)

        with self._lock:
            record = self._get(agent_id)

            if (
                record.status != AgentStatus.ACTIVE
                or record.active_version is None
            ):
                return {
                    "allowed": False,
                    "reason": "Agent not active",
                }

            version = record.versions[
                record.active_version
            ]

            allowed = bool(
                actor.roles.intersection(
                    version.allowed_roles
                )
            )

            return {
                "allowed": allowed,
                "agent_id": agent_id,
                "version": version.version,
                "requires_approval": (
                    version.requires_approval
                ),
                "reason": (
                    "Access permitted"
                    if allowed else "Role not permitted"
                ),
            }

    def metrics(
        self,
        actor: AgentActor,
    ) -> dict[str, Any]:
        agents = self.list_agents(actor)

        return {
            "tenant_id": self.tenant_id,
            "total_agents": len(agents),
            "active_agents": sum(
                a.status == AgentStatus.ACTIVE
                for a in agents
            ),
            "disabled_agents": sum(
                a.status == AgentStatus.DISABLED
                for a in agents
            ),
            "registered_agents": sum(
                a.status == AgentStatus.REGISTERED
                for a in agents
            ),
            "total_versions": sum(
                len(a.versions) for a in agents
            ),
        }

    def audit_events(
        self,
        actor: AgentActor,
        agent_id: str,
    ) -> list[AgentAuditEvent]:
        self._authorize(actor, self.ADMIN_ROLES)

        with self._lock:
            self._get(agent_id)

            return [
                copy.deepcopy(event)
                for event in self._audit
                if event.agent_id == agent_id
            ]

    def export_json(
        self,
        actor: AgentActor,
        output_path: str | Path,
    ) -> Path:
        agents = self.list_agents(actor)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        path.write_text(
            json.dumps(
                [asdict(agent) for agent in agents],
                indent=2,
                default=lambda obj: (
                    sorted(obj)
                    if isinstance(obj, (set, frozenset))
                    else (
                        obj.value
                        if isinstance(obj, Enum)
                        else str(obj)
                    )
                ),
            ),
            encoding="utf-8",
        )

        return path


if __name__ == "__main__":
    repo = RetailAgentRepository("demo")

    admin = AgentActor(
        user_id="ADMIN001",
        tenant_id="demo",
        roles=frozenset({
            "corporate_admin",
            "inventory_manager",
        }),
    )

    agent = repo.register_agent(
        actor=admin,
        agent_id="inventory_agent",
        name="Inventory Intelligence Agent",
        module_path="ai.agents.inventory_agent",
        version="1.0.0",
        description="Inventory monitoring and analysis",
        capabilities=frozenset({
            "inventory_analysis",
            "stockout_detection",
            "reorder_recommendation",
        }),
        allowed_roles=frozenset({
            "inventory_manager",
            "corporate_admin",
        }),
    )

    agent = repo.activate_agent(
        admin,
        agent.agent_id,
        version="1.0.0",
        expected_revision=agent.revision,
    )

    print(
        "Discovered:",
        [
            a.agent_id
            for a in repo.discover_agents(
                admin, "inventory_analysis"
            )
        ],
    )

    print("Metrics:", repo.metrics(admin))
