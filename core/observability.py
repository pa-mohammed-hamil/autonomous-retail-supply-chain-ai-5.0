from __future__ import annotations

"""Planned module: observability. Implementation pending."""

"""
backend/observability.py

Autonomous Retail Supply Chain AI 5.0

Centralized observability and distributed tracing.

Python 3.10+

Dependencies:
    opentelemetry-api
    opentelemetry-sdk
    opentelemetry-exporter-otlp-proto-http
    opentelemetry-instrumentation-fastapi

Existing modules:
    backend.logging
    backend.metrics

Features:
- OpenTelemetry tracing
- OTLP HTTP span exporting
- FastAPI instrumentation
- Structured trace correlation
- Database operation spans
- Redis operation spans
- AI model inference spans
- RAG retrieval spans
- Agent workflow spans
- Event bus trace propagation
- Sanitized exception recording
- Explicit flush and shutdown

Security:
- No raw prompts or retrieved documents.
- No passwords, tokens, or API keys.
- No untrusted attributes on spans.
- No tenant/user IDs by default.
"""


import logging
import os
import re
import threading
import time

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

from opentelemetry import (
    context as otel_context,
    propagate,
    trace,
)

from opentelemetry.sdk.resources import (
    Resource,
)

from opentelemetry.sdk.trace import (
    TracerProvider,
)

from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)

from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)

from opentelemetry.instrumentation.fastapi import (
    FastAPIInstrumentor,
)

from opentelemetry.trace import (
    SpanKind,
    Status,
    StatusCode,
    TraceFlags,
)

from backend.logging import (
    get_logger,
    log_event,
)

from backend.metrics import (
    metrics,
    OperationStatus,
    AgentStatus,
)


logger = get_logger("observability")


# ============================================================
# CONFIGURATION
# ============================================================

@dataclass(frozen=True)
class ObservabilityConfig:

    service_name: str = (
        "autonomous-retail-ai"
    )

    service_version: str = "5.0"

    environment: str = "development"

    tracing_enabled: bool = True

    exporter: str = "console"

    otlp_endpoint: str = (
        "http://localhost:4318/v1/traces"
    )

    export_timeout_seconds: int = 5

    sample_ratio: float = 1.0

    @classmethod
    def from_env(
        cls,
    ) -> "ObservabilityConfig":

        return cls(
            service_name=os.getenv(
                "OTEL_SERVICE_NAME",
                "autonomous-retail-ai",
            ),
            service_version=os.getenv(
                "APP_VERSION",
                "5.0",
            ),
            environment=os.getenv(
                "APP_ENV",
                "development",
            ),
            tracing_enabled=(
                os.getenv(
                    "TRACING_ENABLED",
                    "true",
                ).lower()
                in {"true", "1", "yes"}
            ),
            exporter=os.getenv(
                "OTEL_EXPORTER",
                "console",
            ),
            otlp_endpoint=os.getenv(
                "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
                "http://localhost:4318/v1/traces",
            ),
            sample_ratio=float(
                os.getenv(
                    "OTEL_SAMPLE_RATIO",
                    "1.0",
                )
            ),
        )

    def __post_init__(self) -> None:

        if not 0.0 <= self.sample_ratio <= 1.0:
            raise ValueError(
                "sample_ratio must be between 0 and 1"
            )

        if self.exporter not in {
            "console",
            "otlp",
            "none",
        }:
            raise ValueError(
                "Unsupported exporter"
            )

        if self.export_timeout_seconds <= 0:
            raise ValueError(
                "Export timeout must be positive"
            )

        if (
            self.exporter == "otlp"
            and not self.otlp_endpoint.startswith(
                ("http://", "https://")
            )
        ):
            raise ValueError(
                "Invalid OTLP endpoint"
            )


# ============================================================
# ATTRIBUTE SAFETY
# ============================================================

ALLOWED_ATTRIBUTES = frozenset({
    "component",
    "operation",
    "status",
    "model.task",
    "model.provider",
    "rag.mode",
    "rag.result_count",
    "agent.type",
    "agent.step",
    "event.domain",
    "event.operation",
    "db.system",
    "db.operation",
    "cache.operation",
    "http.request.method",
    "http.route",
    "http.response.status_code",
})

SAFE_VALUE = re.compile(
    r"^[A-Za-z0-9_.:/{}-]{1,100}$"
)


def sanitize_attributes(
    attributes: Mapping[str, Any] | None,
) -> dict[str, str | int | float | bool]:

    result = {}

    for key, value in (
        attributes or {}
    ).items():

        if key not in ALLOWED_ATTRIBUTES:
            continue

        if isinstance(value, bool):
            result[key] = value

        elif isinstance(value, (int, float)):
            result[key] = value

        elif isinstance(value, str):

            if SAFE_VALUE.fullmatch(value):
                result[key] = value

    return result


# ============================================================
# TRACING MANAGER
# ============================================================

class ObservabilityManager:

    def __init__(
        self,
        config: ObservabilityConfig,
    ) -> None:

        self.config = config

        self._provider: (
            TracerProvider | None
        ) = None

        self._tracer = trace.get_tracer(
            config.service_name
        )

        self._initialized = False

        self._lock = threading.RLock()

    def initialize(self) -> None:

        with self._lock:

            if self._initialized:
                return

            if not self.config.tracing_enabled:
                self._initialized = True
                return

            resource = Resource.create({
                "service.name": (
                    self.config.service_name
                ),
                "service.version": (
                    self.config.service_version
                ),
                "deployment.environment.name": (
                    self.config.environment
                ),
            })

            from opentelemetry.sdk.trace.sampling import (
                ParentBased,
                TraceIdRatioBased,
            )

            sampler = ParentBased(
                TraceIdRatioBased(
                    self.config.sample_ratio
                )
            )

            provider = TracerProvider(
                resource=resource,
                sampler=sampler,
            )

            if self.config.exporter == "otlp":

                exporter = OTLPSpanExporter(
                    endpoint=(
                        self.config.otlp_endpoint
                    ),
                    timeout=(
                        self.config.export_timeout_seconds
                    ),
                )

                provider.add_span_processor(
                    BatchSpanProcessor(exporter)
                )

            elif self.config.exporter == "console":

                provider.add_span_processor(
                    BatchSpanProcessor(
                        ConsoleSpanExporter()
                    )
                )

            trace.set_tracer_provider(
                provider
            )

            self._provider = provider

            self._tracer = provider.get_tracer(
                self.config.service_name,
                self.config.service_version,
            )

            self._initialized = True

            log_event(
                logger,
                "observability.initialized",
                exporter=self.config.exporter,
                tracing_enabled=True,
            )

    @contextmanager
    def span(
        self,
        name: str,
        *,
        attributes: Mapping[
            str, Any
        ] | None = None,
        kind: SpanKind = SpanKind.INTERNAL,
        parent_context=None,
    ) -> Iterator[Any]:
        """
        Create an instrumented span.

        Only allowlisted attributes
        are recorded.
        """

        if not self._initialized:
            raise RuntimeError(
                "Observability is not initialized"
            )

        if not self.config.tracing_enabled:
            yield None
            return

        with self._tracer.start_as_current_span(
            name,
            context=parent_context,
            kind=kind,
            attributes=sanitize_attributes(
                attributes
            ),
            record_exception=False,
            set_status_on_exception=False,
        ) as current_span:

            try:
                yield current_span

            except Exception as exc:

                # Record only exception type.
                # Exception messages may contain
                # sensitive values.
                current_span.add_event(
                    "exception",
                    attributes={
                        "exception.type": (
                            type(exc).__name__
                        )
                    },
                )

                current_span.set_status(
                    Status(
                        StatusCode.ERROR,
                        "operation_failed",
                    )
                )

                raise

    def current_trace_ids(
        self,
    ) -> dict[str, str | None]:

        current_span = (
            trace.get_current_span()
        )

        context = (
            current_span.get_span_context()
        )

        if not context.is_valid:

            return {
                "trace_id": None,
                "span_id": None,
            }

        return {
            "trace_id": (
                f"{context.trace_id:032x}"
            ),
            "span_id": (
                f"{context.span_id:016x}"
            ),
        }

    def inject_trace_headers(
        self,
        carrier: dict[str, str],
    ) -> dict[str, str]:
        """
        Add W3C trace context to an
        outgoing trusted message.

        Never accept tenant authorization
        from trace headers.
        """

        propagate.inject(carrier)

        return carrier

    def extract_trace_context(
        self,
        carrier: Mapping[str, str],
    ):
        """
        Extract parent trace context from
        an incoming message.

        This is diagnostic context only,
        not proof of authentication.
        """

        return propagate.extract(
            dict(carrier)
        )

    def flush(
        self,
        timeout_ms: int = 5000,
    ) -> bool:

        if self._provider is None:
            return True

        return bool(
            self._provider.force_flush(
                timeout_millis=timeout_ms
            )
        )

    def shutdown(self) -> None:

        with self._lock:

            if self._provider is not None:

                self._provider.shutdown()

                self._provider = None

            self._initialized = False


# ============================================================
# GLOBAL MANAGER
# ============================================================

observability = ObservabilityManager(
    ObservabilityConfig.from_env()
)


# ============================================================
# DATABASE TRACING
# ============================================================

@contextmanager
def trace_database(
    operation: str,
) -> Iterator[None]:

    started = time.perf_counter()

    status = OperationStatus.SUCCESS

    with observability.span(
        "database.operation",
        attributes={
            "component": "database",
            "db.system": "postgresql",
            "db.operation": operation,
        },
        kind=SpanKind.CLIENT,
    ):

        try:
            yield

        except Exception:
            status = OperationStatus.ERROR
            raise

        finally:

            metrics.record_database(
                operation=operation,
                status=status,
                duration_seconds=(
                    time.perf_counter()
                    - started
                ),
            )


# ============================================================
# REDIS TRACING
# ============================================================

@contextmanager
def trace_cache(
    operation: str,
) -> Iterator[None]:

    with observability.span(
        "cache.operation",
        attributes={
            "component": "cache",
            "cache.operation": operation,
        },
        kind=SpanKind.CLIENT,
    ):
        yield


# ============================================================
# AI INFERENCE TRACING
# ============================================================

@contextmanager
def trace_ai_inference(
    *,
    task: str,
    provider: str,
) -> Iterator[None]:

    started = time.perf_counter()

    status = OperationStatus.SUCCESS

    with observability.span(
        "ai.inference",
        attributes={
            "component": "ai",
            "model.task": task,
            "model.provider": provider,
        },
    ):

        try:
            yield

        except Exception:
            status = OperationStatus.ERROR
            raise

        finally:

            metrics.record_ai_inference(
                task=task,
                status=status,
                duration_seconds=(
                    time.perf_counter()
                    - started
                ),
            )


# ============================================================
# RAG TRACING
# ============================================================

@contextmanager
def trace_rag(
    mode: str,
) -> Iterator[None]:

    started = time.perf_counter()

    with observability.span(
        "rag.retrieval",
        attributes={
            "component": "rag",
            "rag.mode": mode,
        },
    ):

        try:
            yield

        finally:

            metrics.record_rag_retrieval(
                mode=mode,
                duration_seconds=(
                    time.perf_counter()
                    - started
                ),
            )


# ============================================================
# AGENT TRACING
# ============================================================

@contextmanager
def trace_agent(
    agent_type: str,
) -> Iterator[None]:

    started = time.perf_counter()

    status = AgentStatus.SUCCESS

    with observability.span(
        "agent.execution",
        attributes={
            "component": "agent",
            "agent.type": agent_type,
        },
    ):

        try:
            yield

        except Exception:
            status = AgentStatus.FAILED
            raise

        finally:

            metrics.record_agent(
                agent=agent_type,
                status=status,
                duration_seconds=(
                    time.perf_counter()
                    - started
                ),
            )


# ============================================================
# EVENT BUS TRACING
# ============================================================

@contextmanager
def trace_event_publish(
    event_type: str,
) -> Iterator[None]:

    domain = event_type.split(
        ".", 1
    )[0]

    status = OperationStatus.SUCCESS

    with observability.span(
        "event.publish",
        attributes={
            "component": "event_bus",
            "event.domain": domain,
            "event.operation": "publish",
        },
        kind=SpanKind.PRODUCER,
    ):

        try:
            yield

        except Exception:
            status = OperationStatus.ERROR
            raise

        finally:

            metrics.record_event(
                event_type=event_type,
                operation="publish",
                status=status,
            )


# ============================================================
# FASTAPI INSTRUMENTATION
# ============================================================

def instrument_fastapi(
    app,
) -> None:
    """
    Instrument one FastAPI application.

    Call once during application setup.
    """

    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls=(
            "health/live,"
            "health/ready,"
            "internal/metrics"
        ),
    )


# ============================================================
# HEALTH DIAGNOSTICS
# ============================================================

def observability_health() -> dict[str, Any]:

    return {
        "initialized": (
            observability._initialized
        ),
        "tracing_enabled": (
            observability.config.tracing_enabled
        ),
        "exporter": (
            observability.config.exporter
        ),
        "service": (
            observability.config.service_name
        ),
        "trace_context": (
            observability.current_trace_ids()
        ),
    }
