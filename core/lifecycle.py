from __future__ import annotations

"""Planned module: lifecycle. Implementation pending."""

"""
backend/lifecycle.py

Autonomous Retail Supply Chain AI 5.0

FastAPI application lifecycle management.

Python 3.10+
FastAPI
SQLAlchemy 2.x
Redis

Features:
- Startup and shutdown orchestration
- PostgreSQL initialization
- Redis cache initialization
- Event bus initialization
- Dependency health checks
- Readiness and liveness state
- Graceful resource cleanup
- Application lifecycle metrics
- FastAPI lifespan integration

Notes:
- External worker processes should be
  supervised independently.
- Startup does not execute migrations.
- Startup does not seed demo data.
- Startup does not enable autonomous agents.
"""


import logging
import threading
import time

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncIterator

from fastapi import FastAPI

from backend.database.engine import (
    close_database,
    database_health,
    get_database_manager,
)

from backend.database.caching import (
    get_cache_manager,
    close_cache,
)

from backend.event_bus import (
    RetailEventBus,
    create_event_bus,
)


logger = logging.getLogger(__name__)


class LifecycleError(RuntimeError):
    pass


class ApplicationStatus(str, Enum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class DependencyStatus(str, Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    NOT_CHECKED = "not_checked"


@dataclass
class LifecycleMetrics:
    startup_count: int = 0
    shutdown_count: int = 0
    health_check_count: int = 0
    startup_duration_seconds: float = 0.0
    shutdown_duration_seconds: float = 0.0


@dataclass
class LifecycleState:
    status: ApplicationStatus = (
        ApplicationStatus.CREATED
    )

    started_at: datetime | None = None
    stopped_at: datetime | None = None

    dependencies: dict[
        str, DependencyStatus
    ] = field(default_factory=dict)

    last_error: str | None = None

    metrics: LifecycleMetrics = field(
        default_factory=LifecycleMetrics
    )


class ApplicationLifecycleManager:
    """
    Manages resources owned by one
    FastAPI application process.

    The manager is not shared between
    independent worker processes.
    """

    def __init__(
        self,
        *,
        require_database: bool = True,
        require_cache: bool = False,
        require_event_bus: bool = False,
    ) -> None:
        self.require_database = require_database
        self.require_cache = require_cache
        self.require_event_bus = require_event_bus

        self.state = LifecycleState()

        self._lock = threading.RLock()

        self._event_bus: (
            RetailEventBus | None
        ) = None

        self._database_initialized = False
        self._cache_initialized = False

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _set_status(
        self,
        status: ApplicationStatus,
    ) -> None:
        with self._lock:
            self.state.status = status

    def _initialize_database(self) -> None:
        """
        Initialize existing SQLAlchemy engine.

        No schema creation or migration
        is performed.
        """
        get_database_manager()
        self._database_initialized = True

    def _initialize_cache(self) -> None:
        """
        Initialize Redis caching client.
        """
        get_cache_manager()
        self._cache_initialized = True

    def _initialize_event_bus(self) -> None:
        """
        Create a Redis Streams client.

        Does not start an event consumer.
        """
        self._event_bus = create_event_bus()

    def check_dependencies(
        self,
    ) -> dict[str, DependencyStatus]:
        """
        Check required and optional
        infrastructure dependencies.
        """
        results: dict[
            str, DependencyStatus
        ] = {}

        try:
            health = database_health()

            results["database"] = (
                DependencyStatus.HEALTHY
                if health.get("healthy", False)
                else DependencyStatus.UNHEALTHY
            )

        except Exception:
            logger.exception(
                "Database health check failed"
            )
            results["database"] = (
                DependencyStatus.UNHEALTHY
            )

        try:
            cache = get_cache_manager()

            results["cache"] = (
                DependencyStatus.HEALTHY
                if cache.health_check()
                else DependencyStatus.UNHEALTHY
            )

        except Exception:
            logger.exception(
                "Cache health check failed"
            )
            results["cache"] = (
                DependencyStatus.UNHEALTHY
            )

        try:
            if self._event_bus is None:
                results["event_bus"] = (
                    DependencyStatus.NOT_CHECKED
                )
            else:
                results["event_bus"] = (
                    DependencyStatus.HEALTHY
                    if self._event_bus.health_check()
                    else DependencyStatus.UNHEALTHY
                )

        except Exception:
            logger.exception(
                "Event bus health check failed"
            )
            results["event_bus"] = (
                DependencyStatus.UNHEALTHY
            )

        with self._lock:
            self.state.dependencies = results
            self.state.metrics.health_check_count += 1

        return results

    def _required_dependencies_healthy(
        self,
        results: dict[
            str, DependencyStatus
        ],
    ) -> bool:
        requirements = {
            "database": self.require_database,
            "cache": self.require_cache,
            "event_bus": self.require_event_bus,
        }

        return all(
            not required
            or results.get(name)
            == DependencyStatus.HEALTHY
            for name, required in requirements.items()
        )

    def startup(self) -> None:
        """
        Initialize infrastructure resources.

        On failure, attempt cleanup.
        """
        with self._lock:
            if self.state.status in {
                ApplicationStatus.STARTING,
                ApplicationStatus.RUNNING,
                ApplicationStatus.STOPPING,
            }:
                raise LifecycleError(
                    "Invalid startup state"
                )

            self.state.status = (
                ApplicationStatus.STARTING
            )
            self.state.last_error = None

        started = time.monotonic()

        try:
            self._initialize_database()
            self._initialize_cache()
            self._initialize_event_bus()

            dependencies = (
                self.check_dependencies()
            )

            if not self._required_dependencies_healthy(
                dependencies
            ):
                raise LifecycleError(
                    "Required infrastructure "
                    "is unavailable"
                )

            all_healthy = all(
                status == DependencyStatus.HEALTHY
                for status in dependencies.values()
            )

            with self._lock:
                self.state.status = (
                    ApplicationStatus.RUNNING
                    if all_healthy
                    else ApplicationStatus.DEGRADED
                )

                self.state.started_at = (
                    self._now()
                )
                self.state.stopped_at = None
                self.state.metrics.startup_count += 1
                self.state.metrics.startup_duration_seconds = (
                    time.monotonic() - started
                )

            logger.info(
                "Application lifecycle started"
            )

        except Exception as exc:
            with self._lock:
                self.state.status = (
                    ApplicationStatus.FAILED
                )
                self.state.last_error = (
                    type(exc).__name__
                )

            self._cleanup_resources()
            raise

    def _cleanup_resources(self) -> None:
        """
        Best-effort cleanup.

        Each resource is closed independently
        so one failure does not prevent
        cleanup of other resources.
        """
        if self._event_bus is not None:
            try:
                self._event_bus.close()
            except Exception:
                logger.exception(
                    "Event bus cleanup failed"
                )
            finally:
                self._event_bus = None

        if self._cache_initialized:
            try:
                close_cache()
            except Exception:
                logger.exception(
                    "Cache cleanup failed"
                )
            finally:
                self._cache_initialized = False

        if self._database_initialized:
            try:
                close_database()
            except Exception:
                logger.exception(
                    "Database cleanup failed"
                )
            finally:
                self._database_initialized = False

    def shutdown(self) -> None:
        """
        Gracefully release resources.
        """
        with self._lock:
            if self.state.status in {
                ApplicationStatus.CREATED,
                ApplicationStatus.STOPPED,
            }:
                return

            self.state.status = (
                ApplicationStatus.STOPPING
            )

        started = time.monotonic()

        self._cleanup_resources()

        with self._lock:
            self.state.status = (
                ApplicationStatus.STOPPED
            )
            self.state.stopped_at = (
                self._now()
            )
            self.state.metrics.shutdown_count += 1
            self.state.metrics.shutdown_duration_seconds = (
                time.monotonic() - started
            )

        logger.info(
            "Application lifecycle stopped"
        )

    def is_alive(self) -> bool:
        """
        Liveness means the application
        process is operational.

        Dependency outages do not
        automatically make it dead.
        """
        return self.state.status in {
            ApplicationStatus.RUNNING,
            ApplicationStatus.DEGRADED,
        }

    def is_ready(self) -> bool:
        """
        Readiness requires a running
        application and healthy required
        dependencies.
        """
        if self.state.status not in {
            ApplicationStatus.RUNNING,
            ApplicationStatus.DEGRADED,
        }:
            return False

        dependencies = (
            self.check_dependencies()
        )

        return self._required_dependencies_healthy(
            dependencies
        )

    def snapshot(self) -> dict[str, Any]:
        """
        Return application lifecycle state.
        """
        with self._lock:
            return {
                "status": self.state.status.value,
                "started_at": (
                    self.state.started_at.isoformat()
                    if self.state.started_at
                    else None
                ),
                "stopped_at": (
                    self.state.stopped_at.isoformat()
                    if self.state.stopped_at
                    else None
                ),
                "dependencies": {
                    name: status.value
                    for name, status
                    in self.state.dependencies.items()
                },
                "last_error": (
                    self.state.last_error
                ),
                "metrics": {
                    "startup_count": (
                        self.state.metrics.startup_count
                    ),
                    "shutdown_count": (
                        self.state.metrics.shutdown_count
                    ),
                    "health_check_count": (
                        self.state.metrics.health_check_count
                    ),
                    "startup_duration_seconds": (
                        self.state.metrics.startup_duration_seconds
                    ),
                    "shutdown_duration_seconds": (
                        self.state.metrics.shutdown_duration_seconds
                    ),
                },
            }


def create_lifespan(
    manager: ApplicationLifecycleManager,
):
    """
    Build a FastAPI lifespan context.
    """

    @asynccontextmanager
    async def lifespan(
        app: FastAPI,
    ) -> AsyncIterator[None]:

        manager.startup()
        app.state.lifecycle_manager = manager

        try:
            yield
        finally:
            manager.shutdown()

    return lifespan
