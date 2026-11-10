
"""
ai/optimization/workforce_scheduler.py

Warehouse workforce scheduling with OR-Tools CP-SAT.

Features:
- Employee availability
- Skill-based shift assignment
- Minimum staffing per shift
- Maximum weekly working hours
- Minimum rest between shifts
- Labor budget
- Minimum-cost feasible schedule

Assumptions:
- Shift timestamps are timezone-aware.
- A shift is assigned as a complete unit.
- Wages are expressed per hour.
- Hours limits apply to the supplied planning period.
- This is a planning tool, not payroll or attendance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from ortools.sat.python import cp_model


@dataclass(frozen=True)
class Employee:
    employee_id: str
    skills: frozenset[str]
    hourly_cost: float
    max_hours: float
    available_shift_ids: frozenset[str]

    def __post_init__(self):
        if not self.employee_id:
            raise ValueError("Employee ID required")

        for name in ("hourly_cost", "max_hours"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"Invalid {name}")


@dataclass(frozen=True)
class WorkShift:
    shift_id: str
    start: datetime
    end: datetime
    required_skill: str
    required_workers: int

    def __post_init__(self):
        if not self.shift_id or not self.required_skill:
            raise ValueError("Shift ID and skill required")

        if (
            self.start.tzinfo is None
            or self.end.tzinfo is None
            or self.start.utcoffset() is None
            or self.end.utcoffset() is None
        ):
            raise ValueError(
                "Timezone-aware timestamps required"
            )

        if self.end <= self.start:
            raise ValueError("Shift end must follow start")

        if (
            isinstance(self.required_workers, bool)
            or not isinstance(self.required_workers, int)
            or self.required_workers <= 0
        ):
            raise ValueError("Invalid staffing requirement")


class WorkforceScheduler:

    def optimize(
        self,
        employees: list[Employee],
        shifts: list[WorkShift],
        labor_budget: float | None = None,
        minimum_rest_hours: float = 11.0,
        max_solve_seconds: float = 10.0,
    ) -> dict:

        if len({e.employee_id for e in employees}) != len(employees):
            raise ValueError("Duplicate employee IDs")

        if len({s.shift_id for s in shifts}) != len(shifts):
            raise ValueError("Duplicate shift IDs")

        for name, value in (
            ("minimum_rest_hours", minimum_rest_hours),
            ("max_solve_seconds", max_solve_seconds),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"Invalid {name}")

        if max_solve_seconds == 0:
            raise ValueError("Solve time must be positive")

        if labor_budget is not None and (
            isinstance(labor_budget, bool)
            or not isinstance(labor_budget, (int, float))
            or not math.isfinite(labor_budget)
            or labor_budget < 0
        ):
            raise ValueError("Invalid labor budget")

        if not shifts:
            return {
                "status": "optimal",
                "assignments": [],
                "estimated_labor_cost": 0.0,
                "requires_approval": True,
            }

        model = cp_model.CpModel()
        assignments = {}

        # Integer minutes for precise working-hour limits.
        durations = [
            round(
                (shift.end - shift.start).total_seconds()
                / 60
            )
            for shift in shifts
        ]

        if any(minutes <= 0 for minutes in durations):
            raise ValueError("Shift duration too short")

        for i, employee in enumerate(employees):
            for j, shift in enumerate(shifts):
                eligible = (
                    shift.required_skill in employee.skills
                    and shift.shift_id
                    in employee.available_shift_ids
                )

                variable = model.NewBoolVar(
                    f"assign_{i}_{j}"
                )

                assignments[i, j] = variable

                if not eligible:
                    model.Add(variable == 0)

        # Every shift must have the required staffing.
        for j, shift in enumerate(shifts):
            model.Add(
                sum(
                    assignments[i, j]
                    for i in range(len(employees))
                ) == shift.required_workers
            )

        # Employee working-hours constraints.
        for i, employee in enumerate(employees):
            model.Add(
                sum(
                    assignments[i, j] * durations[j]
                    for j in range(len(shifts))
                ) <= math.floor(employee.max_hours * 60)
            )

        # Prevent overlapping shifts or insufficient rest.
        rest = timedelta(hours=minimum_rest_hours)

        for i in range(len(employees)):
            for j in range(len(shifts)):
                for k in range(j + 1, len(shifts)):
                    a = shifts[j]
                    b = shifts[k]

                    compatible = (
                        a.end + rest <= b.start
                        or b.end + rest <= a.start
                    )

                    if not compatible:
                        model.Add(
                            assignments[i, j]
                            + assignments[i, k]
                            <= 1
                        )

        # Monetary amounts converted to integer cents.
        costs = {
            (i, j): round(
                employee.hourly_cost
                * durations[j]
                / 60
                * 100
            )
            for i, employee in enumerate(employees)
            for j in range(len(shifts))
        }

        total_cost = sum(
            costs[i, j] * assignments[i, j]
            for i in range(len(employees))
            for j in range(len(shifts))
        )

        if labor_budget is not None:
            model.Add(
                total_cost <= round(labor_budget * 100)
            )

        model.Minimize(total_cost)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = (
            max_solve_seconds
        )

        status = solver.Solve(model)

        if status not in (
            cp_model.OPTIMAL,
            cp_model.FEASIBLE,
        ):
            return {
                "status": "no_feasible_schedule_found",
                "assignments": [],
                "requires_approval": True,
                "schedule_published": False,
            }

        result = []

        for i, employee in enumerate(employees):
            for j, shift in enumerate(shifts):
                if solver.Value(assignments[i, j]):
                    result.append({
                        "employee_id": employee.employee_id,
                        "shift_id": shift.shift_id,
                        "start": shift.start.isoformat(),
                        "end": shift.end.isoformat(),
                        "skill": shift.required_skill,
                        "estimated_cost": round(
                            costs[i, j] / 100, 2
                        ),
                    })

        return {
            "status": (
                "optimal"
                if status == cp_model.OPTIMAL
                else "feasible"
            ),
            "assignments": result,
            "estimated_labor_cost": round(
                sum(
                    row["estimated_cost"]
                    for row in result
                ),
                2,
            ),
            "requires_approval": True,
            "schedule_published": False,
        }
