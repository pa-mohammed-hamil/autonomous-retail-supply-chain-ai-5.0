
"""
ai/optimization/fleet_assignment.py

Fleet assignment heuristic.

Features:
- Vehicle capacity and type matching
- Temperature-control requirements
- Vehicle availability
- Delivery deadlines
- Round-trip scheduling
- Estimated operating costs
- Unassigned delivery reporting

Assumptions:
- Each job is a separate depot-to-destination round trip.
- Jobs cannot be split across vehicles.
- Travel-time and distance estimates are supplied.
- No actual vehicle dispatch occurs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class FleetVehicle:
    vehicle_id: str
    depot_id: str
    capacity_kg: float
    capacity_m3: float
    available_at: datetime
    vehicle_type: str = "standard"
    refrigerated: bool = False
    cost_per_km: float = 15.0

    def __post_init__(self):
        if not self.vehicle_id or not self.depot_id:
            raise ValueError("Vehicle and depot IDs required")

        for name in (
            "capacity_kg",
            "capacity_m3",
            "cost_per_km",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"Invalid {name}")

        if self.capacity_kg <= 0 or self.capacity_m3 <= 0:
            raise ValueError("Vehicle capacities must be positive")

        if self.available_at.tzinfo is None:
            raise ValueError("Timezone-aware datetime required")


@dataclass(frozen=True)
class DeliveryJob:
    job_id: str
    destination_id: str
    weight_kg: float
    volume_m3: float
    ready_at: datetime
    deadline: datetime
    service_minutes: int = 15
    priority: int = 1
    refrigerated: bool = False
    required_vehicle_type: str | None = None

    def __post_init__(self):
        if not self.job_id or not self.destination_id:
            raise ValueError("Job identifiers required")

        for name in ("weight_kg", "volume_m3"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"Invalid {name}")

        if (
            self.ready_at.tzinfo is None
            or self.deadline.tzinfo is None
        ):
            raise ValueError("Timezone-aware datetimes required")

        if self.deadline < self.ready_at:
            raise ValueError("Invalid delivery deadline")

        if (
            isinstance(self.service_minutes, bool)
            or not isinstance(self.service_minutes, int)
            or self.service_minutes < 0
        ):
            raise ValueError("Invalid service duration")

        if (
            isinstance(self.priority, bool)
            or not isinstance(self.priority, int)
            or not 1 <= self.priority <= 10
        ):
            raise ValueError("Priority must be 1-10")


class FleetAssignmentOptimizer:

    def assign(
        self,
        vehicles: list[FleetVehicle],
        jobs: list[DeliveryJob],
        routes: dict[tuple[str, str], tuple[float, float]],
    ) -> dict:

        """
        routes[(origin, destination)] =
            (travel_minutes, distance_km)
        """

        vehicle_ids = [v.vehicle_id for v in vehicles]
        job_ids = [j.job_id for j in jobs]

        if len(vehicle_ids) != len(set(vehicle_ids)):
            raise ValueError("Duplicate vehicle ID")

        if len(job_ids) != len(set(job_ids)):
            raise ValueError("Duplicate job ID")

        for travel_time, distance in routes.values():
            if any(
                isinstance(v, bool)
                or not isinstance(v, (int, float))
                or not math.isfinite(v)
                or v < 0
                for v in (travel_time, distance)
            ):
                raise ValueError("Invalid route estimates")

        available_at = {
            vehicle.vehicle_id: vehicle.available_at
            for vehicle in vehicles
        }

        assignments = []
        unassigned = []

        sorted_jobs = sorted(
            jobs,
            key=lambda job: (
                job.deadline,
                -job.priority,
                job.ready_at,
                job.job_id,
            ),
        )

        for job in sorted_jobs:
            candidates = []

            for vehicle in vehicles:
                if job.weight_kg > vehicle.capacity_kg:
                    continue

                if job.volume_m3 > vehicle.capacity_m3:
                    continue

                if job.refrigerated and not vehicle.refrigerated:
                    continue

                if (
                    job.required_vehicle_type
                    and vehicle.vehicle_type
                    != job.required_vehicle_type
                ):
                    continue

                outward = routes.get(
                    (vehicle.depot_id, job.destination_id)
                )
                return_route = routes.get(
                    (job.destination_id, vehicle.depot_id)
                )

                if outward is None or return_route is None:
                    continue

                departure = max(
                    available_at[vehicle.vehicle_id],
                    job.ready_at,
                )

                arrival = departure + timedelta(
                    minutes=outward[0]
                )

                completion = arrival + timedelta(
                    minutes=job.service_minutes
                )

                if completion > job.deadline:
                    continue

                available_again = completion + timedelta(
                    minutes=return_route[0]
                )

                total_distance = (
                    outward[1] + return_route[1]
                )

                cost = (
                    total_distance * vehicle.cost_per_km
                )

                candidates.append({
                    "vehicle": vehicle,
                    "departure": departure,
                    "arrival": arrival,
                    "completion": completion,
                    "available_again": available_again,
                    "distance_km": total_distance,
                    "estimated_cost": cost,
                })

            if not candidates:
                unassigned.append({
                    "job_id": job.job_id,
                    "reason": "No feasible vehicle and time slot",
                })
                continue

            # Least-cost feasible candidate first.
            selected = min(
                candidates,
                key=lambda item: (
                    item["estimated_cost"],
                    item["completion"],
                    item["vehicle"].vehicle_id,
                ),
            )

            vehicle = selected["vehicle"]

            available_at[vehicle.vehicle_id] = (
                selected["available_again"]
            )

            assignments.append({
                "job_id": job.job_id,
                "vehicle_id": vehicle.vehicle_id,
                "destination_id": job.destination_id,
                "departure_at": selected[
                    "departure"
                ].isoformat(),
                "arrival_at": selected[
                    "arrival"
                ].isoformat(),
                "completion_at": selected[
                    "completion"
                ].isoformat(),
                "available_again_at": selected[
                    "available_again"
                ].isoformat(),
                "estimated_distance_km": round(
                    selected["distance_km"], 2
                ),
                "estimated_cost": round(
                    selected["estimated_cost"], 2
                ),
                "requires_approval": True,
            })

        return {
            "assignments": assignments,
            "unassigned_jobs": unassigned,
            "total_assigned": len(assignments),
            "total_unassigned": len(unassigned),
            "total_estimated_cost": round(
                sum(
                    item["estimated_cost"]
                    for item in assignments
                ),
                2,
            ),
            "recommendation_only": True,
            "vehicles_dispatched": False,
        }
