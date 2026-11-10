
"""
ai/pipelines/pipeline_scheduler.py

Lightweight in-process pipeline scheduler.

Features:
- Fixed-interval scheduling
- Pipeline dependencies
- Retry with exponential backoff
- Execution history
- Manual pipeline triggering
- Failure reporting
- Thread-safe scheduling

Designed for single-process development.
For production, use durable orchestration
such as Airflow, Prefect or a queue-backed worker.
"""

from __future__ import annotations

import threading
import time

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Any


@dataclass
class PipelineTask:
    name: str
    function: Callable[[], Any]
    interval_seconds: float
    dependencies: tuple[str, ...] = ()
    max_retries: int = 2
    retry_delay_seconds: float = 1.0
    next_run: float = field(
        default_factory=time.monotonic
    )


class PipelineScheduler:

    def __init__(self):
        self.tasks: dict[str, PipelineTask] = {}
        self.history: list[dict] = []
        self._lock = threading.RLock()
        self._stop_event = threading.Event()

    def register(
        self,
        name: str,
        function: Callable[[], Any],
        interval_seconds: float,
        dependencies: tuple[str, ...] = (),
        max_retries: int = 2,
        retry_delay_seconds: float = 1.0,
    ) -> None:

        if not name or not callable(function):
            raise ValueError(
                "Valid task name and function required"
            )

        if interval_seconds <= 0:
            raise ValueError(
                "Interval must be positive"
            )

        if max_retries < 0 or retry_delay_seconds < 0:
            raise ValueError(
                "Invalid retry configuration"
            )

        with self._lock:
            if name in self.tasks:
                raise ValueError(
                    f"Task already registered: {name}"
                )

            self.tasks[name] = PipelineTask(
                name=name,
                function=function,
                interval_seconds=interval_seconds,
                dependencies=tuple(dependencies),
                max_retries=max_retries,
                retry_delay_seconds=retry_delay_seconds,
            )

    def _run_task(
        self,
        name: str,
        completed: set[str],
        visiting: set[str],
    ) -> bool:

        if name in completed:
            return True

        if name in visiting:
            raise ValueError(
                "Circular pipeline dependency"
            )

        if name not in self.tasks:
            raise ValueError(
                f"Unknown pipeline: {name}"
            )

        visiting.add(name)
        task = self.tasks[name]

        try:
            for dependency in task.dependencies:
                if not self._run_task(
                    dependency,
                    completed,
                    visiting,
                ):
                    return False

            for attempt in range(
                task.max_retries + 1
            ):
                started = datetime.now(
                    timezone.utc
                ).isoformat()

                start = time.perf_counter()

                try:
                    output = task.function()

                    duration = (
                        time.perf_counter() - start
                    )

                    with self._lock:
                        self.history.append({
                            "task": name,
                            "status": "success",
                            "attempt": attempt + 1,
                            "started_at": started,
                            "duration_seconds": round(
                                duration, 6
                            ),
                            "output": output,
                        })

                    completed.add(name)
                    return True

                except Exception as exc:
                    duration = (
                        time.perf_counter() - start
                    )

                    with self._lock:
                        self.history.append({
                            "task": name,
                            "status": "failed",
                            "attempt": attempt + 1,
                            "started_at": started,
                            "duration_seconds": round(
                                duration, 6
                            ),
                            "error": (
                                f"{type(exc).__name__}: {exc}"
                            ),
                        })

                    if attempt < task.max_retries:
                        delay = (
                            task.retry_delay_seconds
                            * (2 ** attempt)
                        )
                        if self._stop_event.wait(delay):
                            return False

            return False

        finally:
            visiting.remove(name)

    def run_once(self, name: str) -> bool:
        with self._lock:
            return self._run_task(
                name,
                completed=set(),
                visiting=set(),
            )

    def run_pending(self) -> None:
        now = time.monotonic()

        with self._lock:
            due = [
                task.name
                for task in self.tasks.values()
                if task.next_run <= now
            ]

            completed: set[str] = set()

            for name in due:
                self._run_task(
                    name,
                    completed,
                    visiting=set(),
                )

                self.tasks[name].next_run = (
                    time.monotonic()
                    + self.tasks[name].interval_seconds
                )

    def start(
        self,
        poll_interval_seconds: float = 1.0,
    ) -> None:

        if poll_interval_seconds <= 0:
            raise ValueError(
                "Polling interval must be positive"
            )

        self._stop_event.clear()

        while not self._stop_event.is_set():
            self.run_pending()
            self._stop_event.wait(
                poll_interval_seconds
            )

    def stop(self) -> None:
        self._stop_event.set()

    def get_history(self) -> list[dict]:
        with self._lock:
            return list(self.history)
