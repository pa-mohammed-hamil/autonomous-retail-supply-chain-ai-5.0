from __future__ import annotations

"""Planned module: escalation policy. Implementation pending."""

"""
backend/notifications/escalation_policy.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+

Features:
- Tenant-aware escalation evaluation
- Severity-based SLA policies
- Category-specific policy overrides
- Three configurable escalation levels
- Acknowledgment and resolution handling
- Recipient role and channel selection
- Deterministic idempotency keys
- Timezone-aware deadline calculations
- Immutable escalation decisions

No external dependencies.
"""


from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
import json


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def aware_utc(value: datetime, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(
            f"{field_name} must be timezone-aware"
        )
    return value.astimezone(timezone.utc)


class EscalationSeverity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EscalationCategory(str, Enum):
    INVENTORY = "inventory"
    STOCKOUT = "stockout"
    SUPPLIER = "supplier"
    WAREHOUSE = "warehouse"
    QUALITY = "quality"
    LOGISTICS = "logistics"
    FINANCE = "finance"
    SECURITY = "security"
    INCIDENT = "incident"


class EscalationChannel(str, Enum):
    DASHBOARD = "dashboard"
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"


class EscalationState(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    CLOSED = "closed"


@dataclass(frozen=True)
class EscalationStep:
    level: int
    after_minutes: int
    recipient_roles: tuple[str, ...]
    channels: tuple[EscalationChannel, ...]

    def __post_init__(self) -> None:
        if self.level < 1:
            raise ValueError("Level must be positive")

        if self.after_minutes < 0:
            raise ValueError(
                "Escalation delay cannot be negative"
            )

        if not self.recipient_roles:
            raise ValueError(
                "Recipient roles are required"
            )

        if not self.channels:
            raise ValueError(
                "At least one channel is required"
            )


@dataclass(frozen=True)
class EscalationPolicy:
    policy_id: str
    severity: EscalationSeverity
    steps: tuple[EscalationStep, ...]
    category: EscalationCategory | None = None
    stop_on_acknowledgment: bool = True

    def __post_init__(self) -> None:
        required(self.policy_id, "policy_id")

        if not self.steps:
            raise ValueError(
                "Escalation policy needs steps"
            )

        levels = [step.level for step in self.steps]
        delays = [
            step.after_minutes for step in self.steps
        ]

        if levels != list(range(1, len(levels) + 1)):
            raise ValueError(
                "Escalation levels must be sequential"
            )

        if delays != sorted(set(delays)):
            raise ValueError(
                "Escalation delays must increase"
            )


@dataclass(frozen=True)
class EscalationContext:
    tenant_id: str
    alert_id: str
    severity: EscalationSeverity
    category: EscalationCategory
    state: EscalationState
    created_at: datetime
    current_level: int = 0
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None

    def __post_init__(self) -> None:
        required(self.tenant_id, "tenant_id")
        required(self.alert_id, "alert_id")
        aware_utc(self.created_at, "created_at")

        if self.current_level < 0:
            raise ValueError(
                "current_level cannot be negative"
            )

        if self.acknowledged_at is not None:
            aware_utc(
                self.acknowledged_at,
                "acknowledged_at",
            )

        if self.resolved_at is not None:
            aware_utc(
                self.resolved_at,
                "resolved_at",
            )


@dataclass(frozen=True)
class EscalationDecision:
    tenant_id: str
    alert_id: str
    policy_id: str
    level: int
    recipient_roles: tuple[str, ...]
    channels: tuple[EscalationChannel, ...]
    due_at: datetime
    evaluated_at: datetime
    idempotency_key: str


class RetailEscalationPolicyEngine:
    def __init__(
        self,
        policies: tuple[EscalationPolicy, ...] | None = None,
    ) -> None:
        self.policies = (
            policies
            if policies is not None
            else self.default_policies()
        )

        keys = [
            (policy.severity, policy.category)
            for policy in self.policies
        ]

        if len(keys) != len(set(keys)):
            raise ValueError(
                "Duplicate severity/category policies"
            )

    @staticmethod
    def default_policies() -> tuple[EscalationPolicy, ...]:
        return (
            EscalationPolicy(
                policy_id="critical-default-v1",
                severity=EscalationSeverity.CRITICAL,
                steps=(
                    EscalationStep(
                        level=1,
                        after_minutes=0,
                        recipient_roles=(
                            "operations_manager",
                        ),
                        channels=(
                            EscalationChannel.DASHBOARD,
                            EscalationChannel.EMAIL,
                        ),
                    ),
                    EscalationStep(
                        level=2,
                        after_minutes=10,
                        recipient_roles=(
                            "department_head",
                        ),
                        channels=(
                            EscalationChannel.DASHBOARD,
                            EscalationChannel.EMAIL,
                            EscalationChannel.PUSH,
                        ),
                    ),
                    EscalationStep(
                        level=3,
                        after_minutes=30,
                        recipient_roles=(
                            "tenant_admin",
                        ),
                        channels=(
                            EscalationChannel.EMAIL,
                            EscalationChannel.SMS,
                            EscalationChannel.PUSH,
                        ),
                    ),
                ),
            ),
            EscalationPolicy(
                policy_id="high-default-v1",
                severity=EscalationSeverity.HIGH,
                steps=(
                    EscalationStep(
                        level=1,
                        after_minutes=15,
                        recipient_roles=(
                            "operations_manager",
                        ),
                        channels=(
                            EscalationChannel.DASHBOARD,
                            EscalationChannel.EMAIL,
                        ),
                    ),
                    EscalationStep(
                        level=2,
                        after_minutes=60,
                        recipient_roles=(
                            "department_head",
                        ),
                        channels=(
                            EscalationChannel.EMAIL,
                            EscalationChannel.PUSH,
                        ),
                    ),
                    EscalationStep(
                        level=3,
                        after_minutes=180,
                        recipient_roles=(
                            "tenant_admin",
                        ),
                        channels=(
                            EscalationChannel.EMAIL,
                        ),
                    ),
                ),
            ),
            EscalationPolicy(
                policy_id="medium-default-v1",
                severity=EscalationSeverity.MEDIUM,
                steps=(
                    EscalationStep(
                        level=1,
                        after_minutes=60,
                        recipient_roles=(
                            "operations_manager",
                        ),
                        channels=(
                            EscalationChannel.DASHBOARD,
                        ),
                    ),
                    EscalationStep(
                        level=2,
                        after_minutes=240,
                        recipient_roles=(
                            "department_head",
                        ),
                        channels=(
                            EscalationChannel.EMAIL,
                        ),
                    ),
                ),
            ),
        )

    def match_policy(
        self,
        severity: EscalationSeverity,
        category: EscalationCategory,
    ) -> EscalationPolicy | None:
        specific = next(
            (
                p for p in self.policies
                if p.severity == severity
                and p.category == category
            ),
            None,
        )

        if specific is not None:
            return specific

        return next(
            (
                p for p in self.policies
                if p.severity == severity
                and p.category is None
            ),
            None,
        )

    @staticmethod
    def _idempotency_key(
        tenant_id: str,
        alert_id: str,
        policy_id: str,
        level: int,
    ) -> str:
        canonical = json.dumps(
            {
                "tenant_id": tenant_id,
                "alert_id": alert_id,
                "policy_id": policy_id,
                "level": level,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

        return sha256(
            canonical.encode("utf-8")
        ).hexdigest()

    def evaluate(
        self,
        context: EscalationContext,
        *,
        now: datetime | None = None,
    ) -> EscalationDecision | None:
        evaluated_at = aware_utc(
            now or utc_now(),
            "now",
        )

        if context.state in {
            EscalationState.RESOLVED,
            EscalationState.CLOSED,
        }:
            return None

        policy = self.match_policy(
            context.severity,
            context.category,
        )

        if policy is None:
            return None

        if (
            policy.stop_on_acknowledgment
            and (
                context.state
                    == EscalationState.ACKNOWLEDGED
                or context.acknowledged_at is not None
            )
        ):
            return None

        for step in policy.steps:
            if step.level <= context.current_level:
                continue

            due_at = aware_utc(
                context.created_at,
                "created_at",
            ) + timedelta(
                minutes=step.after_minutes
            )

            if evaluated_at < due_at:
                return None

            return EscalationDecision(
                tenant_id=context.tenant_id,
                alert_id=context.alert_id,
                policy_id=policy.policy_id,
                level=step.level,
                recipient_roles=step.recipient_roles,
                channels=step.channels,
                due_at=due_at,
                evaluated_at=evaluated_at,
                idempotency_key=self._idempotency_key(
                    context.tenant_id,
                    context.alert_id,
                    policy.policy_id,
                    step.level,
                ),
            )

        return None

    def evaluate_batch(
        self,
        contexts: list[EscalationContext],
        *,
        now: datetime | None = None,
    ) -> list[EscalationDecision]:
        evaluated_at = aware_utc(
            now or utc_now(),
            "now",
        )

        decisions = []

        for context in contexts:
            decision = self.evaluate(
                context,
                now=evaluated_at,
            )

            if decision is not None:
                decisions.append(decision)

        return decisions

    def next_deadline(
        self,
        context: EscalationContext,
    ) -> datetime | None:
        if context.state in {
            EscalationState.RESOLVED,
            EscalationState.CLOSED,
        }:
            return None

        policy = self.match_policy(
            context.severity,
            context.category,
        )

        if policy is None:
            return None

        if (
            policy.stop_on_acknowledgment
            and (
                context.state
                    == EscalationState.ACKNOWLEDGED
                or context.acknowledged_at is not None
            )
        ):
            return None

        for step in policy.steps:
            if step.level > context.current_level:
                return aware_utc(
                    context.created_at,
                    "created_at",
                ) + timedelta(
                    minutes=step.after_minutes
                )

        return None


if __name__ == "__main__":
    engine = RetailEscalationPolicyEngine()

    context = EscalationContext(
        tenant_id="retail-demo",
        alert_id="ALERT001",
        severity=EscalationSeverity.CRITICAL,
        category=EscalationCategory.INVENTORY,
        state=EscalationState.OPEN,
        created_at=utc_now() - timedelta(
            minutes=12
        ),
        current_level=1,
    )

    decision = engine.evaluate(context)

    if decision is not None:
        print("Alert:", decision.alert_id)
        print("Escalation level:", decision.level)
        print("Roles:", decision.recipient_roles)
        print(
            "Channels:",
            [channel.value for channel in decision.channels],
        )
        print(
            "Idempotency:",
            decision.idempotency_key,
        )
