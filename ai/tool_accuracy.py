"""Planned module: tool accuracy. Implementation pending."""

"""
File: ai/observability/tool_accuracy.py

Autonomous Retail Supply Chain AI 5.0
Python 3.10+ | Standard library only

Features:
- Tool selection accuracy
- Argument accuracy
- Execution success rate
- Tool output accuracy
- Verified tool-call success
- Per-agent and per-tool reports
- Tenant isolation
- Duplicate evaluation protection

Expected values must come from trusted
test cases or independent verification.
"""

from __future__ import annotations

import json
import threading
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def canonical_json(value: Any) -> str:
    """Compare JSON-compatible structures consistently."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True)
class ToolAccuracyRecord:
    evaluation_id: str
    tenant_id: str
    agent_id: str
    expected_tool: str
    actual_tool: str
    selection_correct: bool
    arguments_correct: bool
    execution_success: bool
    output_correct: bool | None
    verified_success: bool | None
    timestamp: str


class ToolAccuracyMetrics:

    def __init__(self, max_records: int = 100000):
        if (
            isinstance(max_records, bool)
            or not isinstance(max_records, int)
            or max_records < 1
        ):
            raise ValueError(
                "max_records must be a positive integer"
            )

        self.max_records = max_records
        self._records: dict[
            tuple[str, str], ToolAccuracyRecord
        ] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _text(value: Any, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} is required")
        return value.strip()

    def evaluate_call(
        self,
        tenant_id: str,
        agent_id: str,
        expected_tool: str,
        actual_tool: str,
        expected_arguments: dict,
        actual_arguments: dict,
        execution_success: bool,
        expected_output: Any = None,
        actual_output: Any = None,
        verify_output: bool = False,
        evaluation_id: str | None = None,
    ) -> dict:

        tenant_id = self._text(tenant_id, "tenant_id")
        agent_id = self._text(agent_id, "agent_id")

        expected_tool = self._text(
            expected_tool, "expected_tool"
        )
        actual_tool = self._text(
            actual_tool, "actual_tool"
        )

        if not isinstance(expected_arguments, dict):
            raise ValueError(
                "expected_arguments must be a dictionary"
            )

        if not isinstance(actual_arguments, dict):
            raise ValueError(
                "actual_arguments must be a dictionary"
            )

        if not isinstance(execution_success, bool):
            raise ValueError(
                "execution_success must be boolean"
            )

        if not isinstance(verify_output, bool):
            raise ValueError(
                "verify_output must be boolean"
            )

        evaluation_id = (
            self._text(evaluation_id, "evaluation_id")
            if evaluation_id is not None
            else str(uuid4())
        )

        selection_correct = (
            expected_tool == actual_tool
        )

        arguments_correct = (
            canonical_json(expected_arguments)
            == canonical_json(actual_arguments)
        )

        output_correct = (
            canonical_json(expected_output)
            == canonical_json(actual_output)
            if verify_output
            else None
        )

        # Without output verification, overall
        # accuracy remains unverified.
        verified_success = (
            selection_correct
            and arguments_correct
            and execution_success
            and output_correct
            if verify_output
            else None
        )

        record = ToolAccuracyRecord(
            evaluation_id=evaluation_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            expected_tool=expected_tool,
            actual_tool=actual_tool,
            selection_correct=selection_correct,
            arguments_correct=arguments_correct,
            execution_success=execution_success,
            output_correct=output_correct,
            verified_success=verified_success,
            timestamp=datetime.now(
                timezone.utc
            ).isoformat(),
        )

        with self._lock:
            key = (tenant_id, evaluation_id)

            if key in self._records:
                raise ValueError(
                    "Duplicate evaluation_id"
                )

            self._records[key] = record

            while len(self._records) > self.max_records:
                oldest_key = next(iter(self._records))
                del self._records[oldest_key]

        return asdict(record)

    @staticmethod
    def _rate(
        numerator: int,
        denominator: int,
    ) -> float | None:
        if denominator == 0:
            return None

        return round(
            numerator / denominator * 100,
            2,
        )

    def summary(
        self,
        tenant_id: str,
        agent_id: str | None = None,
        tool_name: str | None = None,
    ) -> dict:

        tenant_id = self._text(
            tenant_id, "tenant_id"
        )

        with self._lock:
            records = [
                record
                for record in self._records.values()
                if record.tenant_id == tenant_id
                and (
                    agent_id is None
                    or record.agent_id == agent_id
                )
                and (
                    tool_name is None
                    or record.actual_tool == tool_name
                )
            ]

        total = len(records)

        selected = sum(
            r.selection_correct for r in records
        )

        arguments = sum(
            r.arguments_correct for r in records
        )

        executed = sum(
            r.execution_success for r in records
        )

        output_evaluated = [
            r for r in records
            if r.output_correct is not None
        ]

        output_correct = sum(
            r.output_correct
            for r in output_evaluated
        )

        verified = sum(
            r.verified_success is True
            for r in output_evaluated
        )

        return {
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "tool_name": tool_name,
            "evaluated_calls": total,
            "selection_accuracy_percent": (
                self._rate(selected, total)
            ),
            "argument_accuracy_percent": (
                self._rate(arguments, total)
            ),
            "execution_success_rate_percent": (
                self._rate(executed, total)
            ),
            "tool_error_rate_percent": (
                self._rate(total - executed, total)
            ),
            "output_evaluated_calls": len(
                output_evaluated
            ),
            "output_accuracy_percent": self._rate(
                output_correct,
                len(output_evaluated),
            ),
            "verified_tool_success_rate_percent": (
                self._rate(
                    verified,
                    len(output_evaluated),
                )
            ),
            "actual_tool_counts": dict(
                Counter(
                    r.actual_tool for r in records
                )
            ),
            "comparison_method": (
                "exact_json_equality"
            ),
        }

    def agent_breakdown(
        self,
        tenant_id: str,
    ) -> dict:

        with self._lock:
            agent_ids = sorted({
                r.agent_id
                for r in self._records.values()
                if r.tenant_id == tenant_id
            })

        return {
            "tenant_id": tenant_id,
            "agents": [
                self.summary(
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                )
                for agent_id in agent_ids
            ],
        }

    def tool_breakdown(
        self,
        tenant_id: str,
    ) -> dict:

        with self._lock:
            tools = sorted({
                r.actual_tool
                for r in self._records.values()
                if r.tenant_id == tenant_id
            })

        return {
            "tenant_id": tenant_id,
            "tools": [
                self.summary(
                    tenant_id=tenant_id,
                    tool_name=tool,
                )
                for tool in tools
            ],
        }

    def failed_evaluations(
        self,
        tenant_id: str,
        limit: int = 50,
    ) -> dict:

        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise ValueError(
                "limit must be between 1 and 100"
            )

        with self._lock:
            failures = [
                asdict(r)
                for r in self._records.values()
                if r.tenant_id == tenant_id
                and (
                    not r.selection_correct
                    or not r.arguments_correct
                    or not r.execution_success
                    or r.output_correct is False
                )
            ]

        return {
            "tenant_id": tenant_id,
            "failure_count": len(failures),
            "failures": failures[-limit:],
        }
