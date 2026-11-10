
"""
File: ai/llm/token_usage.py
Project: Autonomous Retail Supply Chain AI 5.0

Token accounting and context-window planning.

Python 3.10+
Standard library only.
"""

from __future__ import annotations

import math
import sqlite3
import threading

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


class TokenUsageError(ValueError):
    pass


class TokenLimitExceeded(TokenUsageError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TokenUsageError(
            f"{name} must be a nonempty string."
        )
    return value.strip()


def valid_count(value: int, name: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        raise TokenUsageError(
            f"{name} must be a nonnegative integer."
        )
    return value


@dataclass(frozen=True)
class TokenUsageRecord:
    usage_id: str
    tenant_id: str
    agent_id: str
    provider: str
    model: str
    request_id: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    source: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TokenUsageTracker:
    """
    Persist LLM token usage.

    Provider-reported usage should be preferred over
    locally estimated usage.

    Request IDs are unique within each tenant to help
    prevent duplicate accounting.
    """

    def __init__(
        self,
        database_path: str = "data/token_usage.db",
    ) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.path),
            timeout=30,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS token_usage (
                    usage_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    total_tokens INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(tenant_id, request_id)
                );

                CREATE INDEX IF NOT EXISTS
                idx_token_usage_tenant_date
                ON token_usage(tenant_id, created_at);
            """)

    @staticmethod
    def estimate_tokens(
        text: str,
        characters_per_token: float = 4.0,
    ) -> int:
        """
        Rough planning estimate only.

        Actual tokenization depends on the provider,
        model, language, formatting and tool payloads.
        """
        if not isinstance(text, str):
            raise TokenUsageError(
                "text must be a string."
            )

        if (
            isinstance(characters_per_token, bool)
            or not isinstance(
                characters_per_token, (int, float)
            )
            or not math.isfinite(characters_per_token)
            or characters_per_token <= 0
        ):
            raise TokenUsageError(
                "characters_per_token must be positive."
            )

        if not text:
            return 0

        return math.ceil(
            len(text) / characters_per_token
        )

    @staticmethod
    def check_context_window(
        estimated_input_tokens: int,
        requested_output_tokens: int,
        context_window: int,
        safety_margin_tokens: int = 512,
    ) -> dict[str, Any]:
        estimated_input_tokens = valid_count(
            estimated_input_tokens,
            "estimated_input_tokens",
        )

        requested_output_tokens = valid_count(
            requested_output_tokens,
            "requested_output_tokens",
        )

        safety_margin_tokens = valid_count(
            safety_margin_tokens,
            "safety_margin_tokens",
        )

        if (
            isinstance(context_window, bool)
            or not isinstance(context_window, int)
            or context_window <= 0
        ):
            raise TokenUsageError(
                "context_window must be positive."
            )

        required = (
            estimated_input_tokens
            + requested_output_tokens
            + safety_margin_tokens
        )

        return {
            "context_window": context_window,
            "estimated_input_tokens": (
                estimated_input_tokens
            ),
            "requested_output_tokens": (
                requested_output_tokens
            ),
            "safety_margin_tokens": (
                safety_margin_tokens
            ),
            "estimated_total_tokens": required,
            "fits_context_window": (
                required <= context_window
            ),
            "remaining_tokens": max(
                0,
                context_window - required,
            ),
        }

    def enforce_context_window(
        self,
        estimated_input_tokens: int,
        requested_output_tokens: int,
        context_window: int,
        safety_margin_tokens: int = 512,
    ) -> dict[str, Any]:
        result = self.check_context_window(
            estimated_input_tokens,
            requested_output_tokens,
            context_window,
            safety_margin_tokens,
        )

        if not result["fits_context_window"]:
            raise TokenLimitExceeded(
                "Estimated token usage exceeds "
                "the configured context window."
            )

        return result

    def record(
        self,
        tenant_id: str,
        agent_id: str,
        provider: str,
        model: str,
        request_id: str,
        input_tokens: int,
        output_tokens: int,
        source: str = "provider",
    ) -> dict[str, Any]:
        tenant_id = require_text(
            tenant_id, "tenant_id"
        )
        agent_id = require_text(
            agent_id, "agent_id"
        )
        provider = require_text(
            provider, "provider"
        )
        model = require_text(model, "model")
        request_id = require_text(
            request_id, "request_id"
        )

        input_tokens = valid_count(
            input_tokens, "input_tokens"
        )
        output_tokens = valid_count(
            output_tokens, "output_tokens"
        )

        if source not in {"provider", "estimated"}:
            raise TokenUsageError(
                "source must be provider or estimated."
            )

        with self._lock, self._connect() as conn:
            existing = conn.execute("""
                SELECT *
                FROM token_usage
                WHERE tenant_id=? AND request_id=?
            """, (
                tenant_id,
                request_id,
            )).fetchone()

            if existing is not None:
                matching = (
                    existing["agent_id"] == agent_id
                    and existing["provider"] == provider
                    and existing["model"] == model
                    and existing["input_tokens"] == input_tokens
                    and existing["output_tokens"] == output_tokens
                    and existing["source"] == source
                )

                if not matching:
                    raise TokenUsageError(
                        "Request ID already has "
                        "different usage data."
                    )

                return dict(existing)

            record = TokenUsageRecord(
                usage_id=str(uuid4()),
                tenant_id=tenant_id,
                agent_id=agent_id,
                provider=provider,
                model=model,
                request_id=request_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=(
                    input_tokens + output_tokens
                ),
                source=source,
                created_at=utc_now(),
            )

            try:
                conn.execute("""
                    INSERT INTO token_usage (
                        usage_id, tenant_id, agent_id,
                        provider, model, request_id,
                        input_tokens, output_tokens,
                        total_tokens, source, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    record.usage_id,
                    record.tenant_id,
                    record.agent_id,
                    record.provider,
                    record.model,
                    record.request_id,
                    record.input_tokens,
                    record.output_tokens,
                    record.total_tokens,
                    record.source,
                    record.created_at,
                ))
            except sqlite3.IntegrityError as exc:
                raise TokenUsageError(
                    "Concurrent request ID conflict."
                ) from exc

        return record.to_dict()

    def usage_report(
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
            raise TokenUsageError(
                "limit must be between 1 and 1000."
            )

        with self._connect() as conn:
            rows = conn.execute("""
                SELECT *
                FROM token_usage
                WHERE tenant_id=?
                ORDER BY created_at DESC
                LIMIT ?
            """, (
                tenant_id,
                limit,
            )).fetchall()

        return [dict(row) for row in rows]

    def summary(
        self,
        tenant_id: str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_text(
            tenant_id, "tenant_id"
        )

        with self._connect() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) AS request_count,
                    COALESCE(SUM(input_tokens), 0)
                        AS input_tokens,
                    COALESCE(SUM(output_tokens), 0)
                        AS output_tokens,
                    COALESCE(SUM(total_tokens), 0)
                        AS total_tokens
                FROM token_usage
                WHERE tenant_id=?
                  AND (? IS NULL OR agent_id=?)
            """, (
                tenant_id,
                agent_id,
                agent_id,
            )).fetchone()

        return {
            "tenant_id": tenant_id,
            "agent_id": agent_id,
            "request_count": row["request_count"],
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
            "total_tokens": row["total_tokens"],
        }

    def model_breakdown(
        self,
        tenant_id: str,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT
                    provider,
                    model,
                    COUNT(*) AS requests,
                    SUM(input_tokens) AS input_tokens,
                    SUM(output_tokens) AS output_tokens,
                    SUM(total_tokens) AS total_tokens
                FROM token_usage
                WHERE tenant_id=?
                GROUP BY provider, model
                ORDER BY total_tokens DESC
            """, (tenant_id,)).fetchall()

        return [dict(row) for row in rows]


if __name__ == "__main__":
    tracker = TokenUsageTracker()

    estimate = tracker.estimate_tokens(
        "Analyze SKU-1001 inventory demand."
    )

    print("Approximate tokens:", estimate)

    print(
        tracker.check_context_window(
            estimated_input_tokens=estimate,
            requested_output_tokens=500,
            context_window=8192,
        )
    )

    usage = tracker.record(
        tenant_id="retail_company_001",
        agent_id="inventory_agent",
        provider="example",
        model="demo-model",
        request_id="demo-request-001",
        input_tokens=120,
        output_tokens=80,
        source="estimated",
    )

    print("Recorded:", usage)
    print(
        "Summary:",
        tracker.summary("retail_company_001"),
    )
