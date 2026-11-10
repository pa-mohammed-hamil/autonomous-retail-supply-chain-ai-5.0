"""Planned module: simulation engine. Implementation pending."""

"""
ai/simulation/simulation_engine.py

Autonomous Retail Supply Chain AI 5.0

Scenario orchestration for supply-chain simulation.

Python 3.10+ | Standard library only.

Registered handlers receive:
    environment: SimulationEnvironment
    parameters: dict

Handlers return JSON-compatible dictionaries.

No real purchase orders, deliveries, or payments
are executed by this module.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from threading import RLock
from time import perf_counter
from typing import Any, Callable
import copy
import json
import uuid

from .environment import SimulationEnvironment


ScenarioHandler = Callable[
    [SimulationEnvironment, dict[str, Any]],
    dict[str, Any],
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_json(value: Any) -> Any:
    try:
        return json.loads(
            json.dumps(
                value,
                allow_nan=False,
                sort_keys=True,
            )
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Value must be JSON-compatible"
        ) from exc


@dataclass(frozen=True)
class SimulationRun:
    run_id: str
    tenant_id: str
    scenario_name: str
    status: str
    seed: int
    started_at: str
    duration_ms: float
    parameters: dict
    result: dict
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class SimulationEngine:

    def __init__(
        self,
        max_history_per_tenant: int = 1000,
        max_events_per_run: int = 100000,
    ):
        if (
            isinstance(max_history_per_tenant, bool)
            or not isinstance(max_history_per_tenant, int)
            or max_history_per_tenant <= 0
        ):
            raise ValueError(
                "max_history_per_tenant must be positive"
            )

        if (
            isinstance(max_events_per_run, bool)
            or not isinstance(max_events_per_run, int)
            or max_events_per_run <= 0
        ):
            raise ValueError(
                "max_events_per_run must be positive"
            )

        self.max_history = max_history_per_tenant
        self.max_events = max_events_per_run

        self._handlers: dict[str, ScenarioHandler] = {}
        self._history: dict[
            str, list[SimulationRun]
        ] = {}
        self._lock = RLock()

    def register_scenario(
        self,
        name: str,
        handler: ScenarioHandler,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Scenario name required")

        if not callable(handler):
            raise ValueError("Handler must be callable")

        with self._lock:
            if name in self._handlers:
                raise ValueError(
                    f"Scenario already registered: {name}"
                )

            self._handlers[name] = handler

    def available_scenarios(self) -> list[str]:
        with self._lock:
            return sorted(self._handlers)

    def run(
        self,
        tenant_id: str,
        scenario_name: str,
        parameters: dict,
        seed: int = 42,
    ) -> dict:

        if (
            not isinstance(tenant_id, str)
            or not tenant_id.strip()
        ):
            raise ValueError("tenant_id required")

        if (
            isinstance(seed, bool)
            or not isinstance(seed, int)
        ):
            raise ValueError("seed must be an integer")

        params = safe_json(parameters)

        if not isinstance(params, dict):
            raise ValueError(
                "parameters must be a dictionary"
            )

        with self._lock:
            handler = self._handlers.get(scenario_name)

        if handler is None:
            raise ValueError(
                f"Unknown scenario: {scenario_name}"
            )

        run_id = str(uuid.uuid4())
        started_at = utc_now()
        start = perf_counter()

        environment = SimulationEnvironment(
            tenant_id=tenant_id,
            simulation_id=run_id,
            seed=seed,
        )

        status = "completed"
        result: dict = {}
        error = None

        try:
            output = handler(
                environment,
                copy.deepcopy(params),
            )

            if not isinstance(output, dict):
                raise TypeError(
                    "Scenario handler must return dict"
                )

            # Handlers may schedule events and run the
            # environment themselves. Alternatively,
            # specify until_day for engine execution.
            until_day = params.get("until_day")

            if until_day is not None:
                environment.run(
                    until_day=until_day,
                    max_events=self.max_events,
                )

            result = safe_json(output)

            # Capture final state after event execution.
            result["environment"] = {
                "current_day": environment.current_day,
                "pending_events": (
                    environment.describe()[
                        "pending_events"
                    ]
                ),
                "state": safe_json(environment.state),
            }

        except Exception as exc:
            status = "failed"
            error = (
                f"{type(exc).__name__}: {exc}"
            )

        duration_ms = (
            perf_counter() - start
        ) * 1000

        record = SimulationRun(
            run_id=run_id,
            tenant_id=tenant_id,
            scenario_name=scenario_name,
            status=status,
            seed=seed,
            started_at=started_at,
            duration_ms=round(duration_ms, 3),
            parameters=params,
            result=result,
            error=error,
        )

        with self._lock:
            history = self._history.setdefault(
                tenant_id, []
            )

            history.append(record)

            if len(history) > self.max_history:
                del history[:-self.max_history]

        return record.to_dict()

    def run_batch(
        self,
        tenant_id: str,
        scenarios: list[dict],
        seed: int = 42,
    ) -> dict:

        if (
            not isinstance(scenarios, list)
            or not 1 <= len(scenarios) <= 50
        ):
            raise ValueError(
                "Provide 1 to 50 scenarios"
            )

        results = []

        for index, scenario in enumerate(scenarios):
            if not isinstance(scenario, dict):
                raise ValueError("Invalid scenario")

            results.append(
                self.run(
                    tenant_id=tenant_id,
                    scenario_name=scenario["name"],
                    parameters=scenario.get(
                        "parameters", {}
                    ),
                    seed=seed + index,
                )
            )

        return {
            "tenant_id": tenant_id,
            "total_runs": len(results),
            "completed": sum(
                r["status"] == "completed"
                for r in results
            ),
            "failed": sum(
                r["status"] == "failed"
                for r in results
            ),
            "runs": results,
        }

    def history(
        self,
        tenant_id: str,
        limit: int = 100,
    ) -> list[dict]:

        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 0
        ):
            raise ValueError("Invalid limit")

        with self._lock:
            records = self._history.get(
                tenant_id, []
            )

            return [
                record.to_dict()
                for record in records[-limit:]
            ]

    def get_run(
        self,
        tenant_id: str,
        run_id: str,
    ) -> dict | None:

        with self._lock:
            for record in self._history.get(
                tenant_id, []
            ):
                if record.run_id == run_id:
                    return record.to_dict()

        return None
