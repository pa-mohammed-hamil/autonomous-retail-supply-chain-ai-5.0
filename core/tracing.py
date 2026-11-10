from __future__ import annotations

"""Planned module: tracing. Implementation pending."""

"""
backend/tracing.py

Autonomous Retail Supply Chain AI 5.0

Distributed tracing with OpenTelemetry.

Python 3.10+

Install:
    pip install \
        opentelemetry-api \
        opentelemetry-sdk \
        opentelemetry-exporter-otlp-proto-http \
        opentelemetry-instrumentation-fastapi \
        opentelemetry-instrumentation-sqlalchemy \
        opentelemetry-instrumentation-redis

Features:
    - Distributed tracing
    - OTLP HTTP export
    - Parent-based trace sampling
    - FastAPI instrumentation
    - SQLAlchemy instrumentation
    - Redis instrumentation
    - Agent execution tracing
    - LLM inference tracing
    - RAG pipeline tracing
    - Event publishing and consumption
    - W3C trace context propagation
    - Sync and async decorators
    - Safe error recording
    - Trace and span identifiers
    - Explicit flush and shutdown

Security:
    Never capture prompts, API keys,
    passwords, documents, SQL parameters,
    customer details, or raw tool outputs.
"""


import asyncio
import functools
import os
import re
import threading

from contextlib import contextmanager
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    Iterator,
    Mapping,
    ParamSpec,
    TypeVar,
)

from opentelemetry import (
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

from opentelemetry.sdk.trace.sampling import (
    ParentBased,
    TraceIdRatioBased,
)

from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)

from opentelemetry.trace import (
    SpanKind,
    Status,
    StatusCode,
)


P = ParamSpec("P")
R = TypeVar("R")


# ============================================================
# CONFIGURATION
# ============================================================

@dataclass(frozen=True)
class TracingConfig:

    service_name: str = (
        "autonomous-retail-ai"
    )

    service_version: str = "5.0"

    environment: str = "development"

    enabled: bool = True

    exporter: str = "console"

    otlp_endpoint: str = (
        "http://localhost:4318/v1/traces"
    )

    sample_ratio: float = 1.0

    export_timeout_seconds: int = 5

    @classmethod
    def from_env(cls) -> "TracingConfig":

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
            enabled=os.getenv(
                "TRACING_ENABLED",
                "true",
            ).lower() in {
                "true", "1", "yes"
            },
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

    def __post_init__(self):

        if not 0 <= self.sample_ratio <= 1:
            raise ValueError(
                "sample_ratio must be 0..1"
            )

        if self.exporter not in {
            "console",
            "otlp",
            "none",
        }:
            raise ValueError(
                "Invalid tracing exporter"
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
# SAFE SPAN ATTRIBUTES
# ============================================================

ALLOWED_ATTRIBUTES = frozenset({
    "component",
    "operation",
    "status",
    "agent.type",
    "agent.action",
    "agent.step",
    "rag.mode",
    "rag.stage",
    "rag.result_count",
    "llm.provider",
    "llm.task",
    "db.system",
    "db.operation",
    "cache.operation",
    "event.domain",
    "event.operation",
    "http.route",
    "http.request.method",
    "http.response.status_code",
})

SAFE_STRING = re.compile(
    r"^[A-Za-z0-9_.:/{}-]{1,100}$"
)


def safe_attributes(
    values: Mapping[str, Any] | None,
) -> dict[str, Any]:

    cleaned = {}

    for key, value in (
        values or {}
    ).items():

        if key not in ALLOWED_ATTRIBUTES:
            continue

        if isinstance(value, bool):
            cleaned[key] = value

        elif isinstance(value, int):
            cleaned[key] = value

        elif isinstance(value, float):
            cleaned[key] = value

        elif isinstance(value, str):

            if SAFE_STRING.fullmatch(value):
                cleaned[key] = value

    return cleaned


def safe_span_name(name: str) -> str:

    if not SAFE_STRING.fullmatch(name):
        raise ValueError(
            "Unsafe span name"
        )

    return name


# ============================================================
# TRACING MANAGER
# ============================================================

class TracingManager:

    def __init__(
        self,
        config: TracingConfig | None = None,
    ):

        self.config = (
            config or TracingConfig.from_env()
        )

        self._provider: (
            TracerProvider | None
        ) = None

        self._tracer = trace.get_tracer(
            self.config.service_name
        )

        self._initialized = False

        self._shutdown = False

        self._owns_provider = False

        self._lock = threading.RLock()

    def initialize(
        self,
        *,
        provider: TracerProvider | None = None,
    ) -> None:
        """
        Initialize once per process.

        Pass the existing provider from
        backend/observability.py when that
        module owns OpenTelemetry setup.

        If another global provider already
        exists, pass it explicitly.
        """

        with self._lock:

            if self._initialized:
                return

            if self._shutdown:
                raise RuntimeError(
                    "Tracing manager was shut down"
                )

            if not self.config.enabled:
                self._initialized = True
                return

            if provider is not None:

                self._provider = provider

                self._owns_provider = False

            else:

                current = (
                    trace.get_tracer_provider()
                )

                # The SDK exposes a real
                # TracerProvider after setup.
                if isinstance(
                    current,
                    TracerProvider,
                ):

                    self._provider = current

                    self._owns_provider = False

                else:

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

                    sampler = ParentBased(
                        TraceIdRatioBased(
                            self.config.sample_ratio
                        )
                    )

                    created = TracerProvider(
                        resource=resource,
                        sampler=sampler,
                    )

                    if self.config.exporter == "otlp":

                        exporter = OTLPSpanExporter(
                            endpoint=(
                                self.config.otlp_endpoint
                            ),
                            timeout=(
                                self.config
                                .export_timeout_seconds
                            ),
                        )

                        created.add_span_processor(
                            BatchSpanProcessor(
                                exporter
                            )
                        )

                    elif (
                        self.config.exporter
                        == "console"
                    ):

                        created.add_span_processor(
                            BatchSpanProcessor(
                                ConsoleSpanExporter()
                            )
                        )

                    trace.set_tracer_provider(
                        created
                    )

                    self._provider = created

                    self._owns_provider = True

            self._tracer = (
                self._provider.get_tracer(
                    self.config.service_name,
                    self.config.service_version,
                )
            )

            self._initialized = True

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

        if not self._initialized:
            raise RuntimeError(
                "Tracing is not initialized"
            )

        if not self.config.enabled:
            yield None
            return

        with self._tracer.start_as_current_span(
            safe_span_name(name),
            context=parent_context,
            kind=kind,
            attributes=safe_attributes(
                attributes
            ),
            record_exception=False,
            set_status_on_exception=False,
        ) as span:

            try:
                yield span

            except Exception as exc:

                # Record exception type only.
                # Exception messages may
                # contain private data.
                span.add_event(
                    "exception",
                    attributes={
                        "exception.type": (
                            type(exc).__name__
                        )
                    },
                )

                span.set_status(
                    Status(
                        StatusCode.ERROR,
                        "operation_failed",
                    )
                )

                raise

    def current_trace_ids(
        self,
    ) -> dict[str, str | None]:

        span = trace.get_current_span()

        context = span.get_span_context()

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

    def inject_context(
        self,
        carrier: dict[str, str],
    ) -> dict[str, str]:
        """
        Inject W3C traceparent and
        optional tracestate headers.
        """

        propagate.inject(carrier)

        return carrier

    def extract_context(
        self,
        carrier: Mapping[str, str],
    ):
        """
        Extract diagnostic trace context.

        Incoming trace headers are not
        authentication credentials.
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

            if self._shutdown:
                return

            if (
                self._owns_provider
                and self._provider is not None
            ):
                self._provider.shutdown()

            self._shutdown = True

            self._initialized = False


# ============================================================
# GLOBAL TRACER
# ============================================================

tracing = TracingManager()


# ============================================================
# GENERIC OPERATION TRACING
# ============================================================

@contextmanager
def trace_operation(
    name: str,
    *,
    component: str = "application",
    operation: str = "execute",
) -> Iterator[None]:

    with tracing.span(
        name,
        attributes={
            "component": component,
            "operation": operation,
        },
    ):
        yield


# ============================================================
# DATABASE TRACING
# ============================================================

@contextmanager
def trace_database(
    operation: str,
) -> Iterator[None]:

    with tracing.span(
        "database.operation",
        kind=SpanKind.CLIENT,
        attributes={
            "component": "database",
            "db.system": "postgresql",
            "db.operation": operation,
        },
    ):
        yield


# ============================================================
# REDIS TRACING
# ============================================================

@contextmanager
def trace_redis(
    operation: str,
) -> Iterator[None]:

    with tracing.span(
        "redis.operation",
        kind=SpanKind.CLIENT,
        attributes={
            "component": "cache",
            "cache.operation": operation,
        },
    ):
        yield


# ============================================================
# AI AGENT TRACING
# ============================================================

@contextmanager
def trace_agent(
    agent_type: str,
    action: str = "execute",
) -> Iterator[None]:

    with tracing.span(
        "agent.execution",
        attributes={
            "component": "agent",
            "agent.type": agent_type,
            "agent.action": action,
        },
    ):
        yield


@contextmanager
def trace_agent_step(
    agent_type: str,
    step: str,
) -> Iterator[None]:

    with tracing.span(
        "agent.step",
        attributes={
            "component": "agent",
            "agent.type": agent_type,
            "agent.step": step,
        },
    ):
        yield


# ============================================================
# LLM INFERENCE TRACING
# ============================================================

@contextmanager
def trace_llm(
    *,
    provider: str,
    task: str,
) -> Iterator[None]:

    with tracing.span(
        "llm.inference",
        attributes={
            "component": "llm",
            "llm.provider": provider,
            "llm.task": task,
        },
    ):
        yield


# ============================================================
# RAG PIPELINE TRACING
# ============================================================

@contextmanager
def trace_rag(
    mode: str,
    stage: str = "retrieval",
) -> Iterator[None]:

    with tracing.span(
        "rag.pipeline",
        attributes={
            "component": "rag",
            "rag.mode": mode,
            "rag.stage": stage,
        },
    ):
        yield


# ============================================================
# EVENT BUS TRACING
# ============================================================

@contextmanager
def trace_event_publish(
    domain: str,
    *,
    carrier: dict[str, str] | None = None,
) -> Iterator[dict[str, str]]:

    with tracing.span(
        "event.publish",
        kind=SpanKind.PRODUCER,
        attributes={
            "component": "event_bus",
            "event.domain": domain,
            "event.operation": "publish",
        },
    ):

        headers = (
            carrier
            if carrier is not None
            else {}
        )

        tracing.inject_context(
            headers
        )

        yield headers


@contextmanager
def trace_event_consume(
    domain: str,
    *,
    carrier: Mapping[str, str],
) -> Iterator[None]:

    parent = tracing.extract_context(
        carrier
    )

    with tracing.span(
        "event.consume",
        kind=SpanKind.CONSUMER,
        parent_context=parent,
        attributes={
            "component": "event_bus",
            "event.domain": domain,
            "event.operation": "consume",
        },
    ):
        yield


# ============================================================
# FUNCTION DECORATORS
# ============================================================

def traced(
    name: str,
    *,
    component: str = "application",
):
    """
    Trace synchronous and asynchronous
    functions without recording arguments.
    """

    def decorator(
        function: Callable[P, R],
    ) -> Callable[P, R]:

        if asyncio.iscoroutinefunction(
            function
        ):

            @functools.wraps(function)
            async def async_wrapper(
                *args: P.args,
                **kwargs: P.kwargs,
            ):

                with trace_operation(
                    name,
                    component=component,
                ):
                    return await function(
                        *args,
                        **kwargs,
                    )

            return async_wrapper

        @functools.wraps(function)
        def sync_wrapper(
            *args: P.args,
            **kwargs: P.kwargs,
        ):

            with trace_operation(
                name,
                component=component,
            ):
                return function(
                    *args,
                    **kwargs,
                )

        return sync_wrapper

    return decorator


# ============================================================
# FASTAPI INSTRUMENTATION
# ============================================================

def instrument_fastapi(
    app,
) -> None:

    from opentelemetry.instrumentation.fastapi import (
        FastAPIInstrumentor,
    )

    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls=(
            "health/live,"
            "health/ready,"
            "internal/metrics"
        ),
    )


# ============================================================
# SQLALCHEMY INSTRUMENTATION
# ============================================================

def instrument_sqlalchemy(
    engine,
) -> None:

    from opentelemetry.instrumentation.sqlalchemy import (
        SQLAlchemyInstrumentor,
    )

    SQLAlchemyInstrumentor().instrument(
        engine=engine,
        enable_commenter=False,
    )


# ============================================================
# REDIS INSTRUMENTATION
# ============================================================

def instrument_redis() -> None:

    from opentelemetry.instrumentation.redis import (
        RedisInstrumentor,
    )

    RedisInstrumentor().instrument()


# ============================================================
# HEALTH / DIAGNOSTICS
# ============================================================

def tracing_status() -> dict[str, Any]:

    return {
        "initialized": (
            tracing._initialized
        ),
        "enabled": (
            tracing.config.enabled
        ),
        "exporter": (
            tracing.config.exporter
        ),
        "service_name": (
            tracing.config.service_name
        ),
        "trace": (
            tracing.current_trace_ids()
        ),
    }
