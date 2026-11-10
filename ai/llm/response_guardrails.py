"""Planned module: response guardrails. Implementation pending."""

"""
File: ai/llm/response_guardrails.py
Project: Autonomous Retail Supply Chain AI 5.0

LLM response guardrails.

Features:
- Response length limits
- Empty response detection
- Suspicious instruction detection
- Basic secret and PII pattern detection
- Operational action risk checks
- Human approval requirements
- Custom guardrail rules
- Structured inspection reports
- Tenant-scoped inspection history

Python 3.10+
Standard library only

IMPORTANT:
Pattern-based checks are not comprehensive
security, privacy, or factuality verification.

Never use these checks as the sole authorization
boundary for executing operational actions.
"""

from __future__ import annotations

import re
import threading

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4


class GuardrailError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GuardrailError(
            f"{name} must be a nonempty string."
        )
    return value.strip()


@dataclass(frozen=True)
class GuardrailPolicy:
    max_characters: int = 20000
    block_suspicious_instructions: bool = True
    block_sensitive_data: bool = True
    block_operational_actions: bool = True


@dataclass
class GuardrailIssue:
    code: str
    message: str
    severity: str
    category: str


@dataclass
class GuardrailResult:
    inspection_id: str
    tenant_id: str
    agent_id: str
    task_type: str
    status: str
    allowed: bool
    requires_human_review: bool
    issues: list[GuardrailIssue] = field(
        default_factory=list
    )
    checked_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict:
        return asdict(self)


CustomGuardrail = Callable[
    [str, str],
    list[GuardrailIssue],
]


class ResponseGuardrails:
    """
    Inspect generated text before display or
    downstream processing.

    Outputs:
        allowed
        blocked
        review_required

    This component never authorizes tool execution.
    """

    SUSPICIOUS_PATTERNS = (
        re.compile(
            r"ignore\s+(all\s+)?previous\s+instructions",
            re.IGNORECASE,
        ),
        re.compile(
            r"reveal\s+(your\s+)?(system|developer)\s+prompt",
            re.IGNORECASE,
        ),
        re.compile(
            r"disable\s+(all\s+)?(security|safety)\s+checks",
            re.IGNORECASE,
        ),
        re.compile(
            r"bypass\s+(the\s+)?(approval|authorization)",
            re.IGNORECASE,
        ),
    )

    SENSITIVE_PATTERNS = {
        "private_key": re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?"
            r"PRIVATE KEY-----"
        ),
        "bearer_token": re.compile(
            r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}\b",
            re.IGNORECASE,
        ),
        "email_address": re.compile(
            r"\b[A-Za-z0-9._%+-]+@"
            r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
        ),
    }

    HIGH_RISK_TASKS = frozenset({
        "create_purchase_order",
        "approve_payment",
        "change_supplier_bank_details",
        "delete_inventory",
        "adjust_inventory",
        "change_product_price",
        "warehouse_transfer",
    })

    def __init__(
        self,
        policy: GuardrailPolicy | None = None,
    ) -> None:
        self.policy = policy or GuardrailPolicy()

        if (
            isinstance(self.policy.max_characters, bool)
            or not isinstance(
                self.policy.max_characters, int
            )
            or self.policy.max_characters <= 0
        ):
            raise GuardrailError(
                "max_characters must be positive."
            )

        self._rules: list[CustomGuardrail] = []
        self._history: list[GuardrailResult] = []
        self._lock = threading.RLock()

    def register_rule(
        self,
        rule: CustomGuardrail,
    ) -> None:
        if not callable(rule):
            raise GuardrailError(
                "Guardrail rule must be callable."
            )

        with self._lock:
            self._rules.append(rule)

    def inspect(
        self,
        tenant_id: str,
        agent_id: str,
        task_type: str,
        response_text: str,
    ) -> dict:
        tenant_id = require_text(
            tenant_id, "tenant_id"
        )
        agent_id = require_text(
            agent_id, "agent_id"
        )
        task_type = require_text(
            task_type, "task_type"
        )

        if not isinstance(response_text, str):
            raise GuardrailError(
                "response_text must be a string."
            )

        issues: list[GuardrailIssue] = []

        if not response_text.strip():
            issues.append(
                GuardrailIssue(
                    code="EMPTY_RESPONSE",
                    message="LLM response is empty.",
                    severity="block",
                    category="format",
                )
            )

        if len(response_text) > self.policy.max_characters:
            issues.append(
                GuardrailIssue(
                    code="RESPONSE_TOO_LONG",
                    message="Response exceeds size limit.",
                    severity="block",
                    category="format",
                )
            )

        if self.policy.block_suspicious_instructions:
            for pattern in self.SUSPICIOUS_PATTERNS:
                if pattern.search(response_text):
                    issues.append(
                        GuardrailIssue(
                            code="SUSPICIOUS_INSTRUCTION",
                            message=(
                                "Response contains an "
                                "instruction-manipulation pattern."
                            ),
                            severity="review",
                            category="prompt_injection",
                        )
                    )
                    break

        if self.policy.block_sensitive_data:
            for category, pattern in (
                self.SENSITIVE_PATTERNS.items()
            ):
                if pattern.search(response_text):
                    issues.append(
                        GuardrailIssue(
                            code="SENSITIVE_DATA_PATTERN",
                            message=(
                                "Potential sensitive data "
                                f"detected: {category}."
                            ),
                            severity="block",
                            category="privacy",
                        )
                    )

        if (
            self.policy.block_operational_actions
            and task_type in self.HIGH_RISK_TASKS
        ):
            issues.append(
                GuardrailIssue(
                    code="HUMAN_APPROVAL_REQUIRED",
                    message=(
                        "This operation requires "
                        "authorized human approval."
                    ),
                    severity="review",
                    category="operations",
                )
            )

        with self._lock:
            rules = list(self._rules)

        for rule in rules:
            try:
                result = rule(
                    response_text,
                    task_type,
                )

                if (
                    not isinstance(result, list)
                    or not all(
                        isinstance(item, GuardrailIssue)
                        for item in result
                    )
                ):
                    raise GuardrailError(
                        "Invalid custom guardrail result."
                    )

                issues.extend(result)

            except Exception:
                issues.append(
                    GuardrailIssue(
                        code="GUARDRAIL_RULE_FAILURE",
                        message=(
                            "A custom guardrail check failed."
                        ),
                        severity="block",
                        category="system",
                    )
                )

        blocked = any(
            issue.severity == "block"
            for issue in issues
        )

        review = any(
            issue.severity == "review"
            for issue in issues
        )

        if blocked:
            status = "blocked"
        elif review:
            status = "review_required"
        else:
            status = "allowed"

        report = GuardrailResult(
            inspection_id=str(uuid4()),
            tenant_id=tenant_id,
            agent_id=agent_id,
            task_type=task_type,
            status=status,
            allowed=(status == "allowed"),
            requires_human_review=review,
            issues=issues,
        )

        with self._lock:
            self._history.append(report)

        return report.to_dict()

    def history(
        self,
        tenant_id: str,
        limit: int = 100,
    ) -> list[dict]:
        tenant_id = require_text(
            tenant_id, "tenant_id"
        )

        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 1000
        ):
            raise GuardrailError(
                "Invalid history limit."
            )

        with self._lock:
            records = [
                record
                for record in self._history
                if record.tenant_id == tenant_id
            ]

        return [
            record.to_dict()
            for record in records[-limit:]
        ]

    def summary(
        self,
        tenant_id: str,
    ) -> dict:
        tenant_id = require_text(
            tenant_id, "tenant_id"
        )

        with self._lock:
            records = [
                record
                for record in self._history
                if record.tenant_id == tenant_id
            ]

        return {
            "tenant_id": tenant_id,
            "total_inspections": len(records),
            "allowed": sum(
                r.status == "allowed"
                for r in records
            ),
            "blocked": sum(
                r.status == "blocked"
                for r in records
            ),
            "review_required": sum(
                r.status == "review_required"
                for r in records
            ),
        }


if __name__ == "__main__":
    guardrails = ResponseGuardrails()

    normal = guardrails.inspect(
        tenant_id="retail_company_001",
        agent_id="inventory_agent",
        task_type="analyze_inventory",
        response_text=(
            "Current stock is 80 units. "
            "The reorder point is 100 units."
        ),
    )

    print("Normal response:", normal)

    risky = guardrails.inspect(
        tenant_id="retail_company_001",
        agent_id="procurement_agent",
        task_type="create_purchase_order",
        response_text=(
            "Proposed order: 200 units. "
            "Estimated cost: 24000 INR."
        ),
    )

    print("Procurement response:", risky)
