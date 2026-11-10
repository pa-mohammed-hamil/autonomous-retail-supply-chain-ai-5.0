
"""
ai/optimization/picking_route_optimizer.py

Warehouse picking route optimization.

Features:
- Warehouse pick-location coordinates
- Multi-SKU picking lists
- Cart capacity validation
- Nearest-neighbor route construction
- 2-opt route improvement
- Return-to-depot routing
- Estimated picking time

Important:
Coordinates use an abstract warehouse grid.
Euclidean distance is only a planning approximation.
Production routes need aisle-aware walkable paths.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class PickLocation:
    location_id: str
    x: float
    y: float

    def __post_init__(self):
        if not self.location_id:
            raise ValueError("Location ID required")

        if not all(
            isinstance(v, (int, float))
            and not isinstance(v, bool)
            and math.isfinite(v)
            for v in (self.x, self.y)
        ):
            raise ValueError("Invalid coordinates")


@dataclass(frozen=True)
class PickItem:
    sku: str
    location_id: str
    quantity: int
    unit_weight_kg: float = 1.0
    pick_seconds_per_unit: float = 5.0

    def __post_init__(self):
        if not self.sku or not self.location_id:
            raise ValueError("SKU and location required")

        if (
            isinstance(self.quantity, bool)
            or not isinstance(self.quantity, int)
            or self.quantity <= 0
        ):
            raise ValueError("Invalid quantity")

        for value in (
            self.unit_weight_kg,
            self.pick_seconds_per_unit,
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError("Invalid pick-item value")


class PickingRouteOptimizer:

    @staticmethod
    def distance(a: PickLocation, b: PickLocation):
        return math.hypot(a.x - b.x, a.y - b.y)

    def route_distance(self, route, locations):
        return sum(
            self.distance(
                locations[route[i]],
                locations[route[i + 1]],
            )
            for i in range(len(route) - 1)
        )

    def optimize(
        self,
        locations: list[PickLocation],
        items: list[PickItem],
        depot_id: str,
        cart_capacity_kg: float,
        walking_speed_m_per_sec: float = 1.2,
    ) -> dict:

        if (
            not math.isfinite(cart_capacity_kg)
            or cart_capacity_kg <= 0
        ):
            raise ValueError("Invalid cart capacity")

        if (
            not math.isfinite(walking_speed_m_per_sec)
            or walking_speed_m_per_sec <= 0
        ):
            raise ValueError("Invalid walking speed")

        location_map = {
            location.location_id: location
            for location in locations
        }

        if len(location_map) != len(locations):
            raise ValueError("Duplicate location IDs")

        if depot_id not in location_map:
            raise ValueError("Depot location not found")

        total_weight = sum(
            item.quantity * item.unit_weight_kg
            for item in items
        )

        if total_weight > cart_capacity_kg:
            return {
                "status": "capacity_exceeded",
                "total_weight_kg": round(total_weight, 2),
                "route": [],
                "recommendation_only": True,
            }

        for item in items:
            if item.location_id not in location_map:
                raise ValueError(
                    f"Unknown location: {item.location_id}"
                )

        remaining = {
            item.location_id
            for item in items
            if item.location_id != depot_id
        }

        route = [depot_id]
        current = depot_id

        # Nearest-neighbor construction.
        while remaining:
            next_location = min(
                remaining,
                key=lambda loc: (
                    self.distance(
                        location_map[current],
                        location_map[loc],
                    ),
                    loc,
                ),
            )

            route.append(next_location)
            remaining.remove(next_location)
            current = next_location

        route.append(depot_id)

        # 2-opt improvement.
        improved = True

        while improved:
            improved = False
            best_distance = self.route_distance(
                route, location_map
            )

            for i in range(1, len(route) - 2):
                for j in range(i + 1, len(route) - 1):
                    candidate = (
                        route[:i]
                        + route[i:j + 1][::-1]
                        + route[j + 1:]
                    )

                    candidate_distance = self.route_distance(
                        candidate, location_map
                    )

                    if candidate_distance < best_distance - 1e-9:
                        route = candidate
                        best_distance = candidate_distance
                        improved = True

        distance_m = self.route_distance(
            route, location_map
        )

        walking_seconds = (
            distance_m / walking_speed_m_per_sec
        )

        picking_seconds = sum(
            item.quantity * item.pick_seconds_per_unit
            for item in items
        )

        return {
            "status": "route_recommended",
            "route": route,
            "total_distance_m": round(distance_m, 2),
            "total_weight_kg": round(total_weight, 2),
            "estimated_walking_minutes": round(
                walking_seconds / 60, 2
            ),
            "estimated_picking_minutes": round(
                picking_seconds / 60, 2
            ),
            "estimated_total_minutes": round(
                (walking_seconds + picking_seconds) / 60,
                2,
            ),
            "requires_approval": True,
            "route_executed": False,
        }
