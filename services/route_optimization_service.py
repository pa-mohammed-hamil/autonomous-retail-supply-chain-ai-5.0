from __future__ import annotations

"""Planned module: route optimization service. Implementation pending."""

"""
Autonomous Retail Supply Chain AI 5.0
backend/services/route_optimization_service.py

Python 3.10+ | Standard library only.

Reference route-planning service.

Features:
- Tenant and warehouse RBAC
- Haversine distance calculations
- Vehicle load-capacity validation
- Delivery time windows
- Nearest-neighbor route planning
- 2-opt route improvement
- ETA and distance estimates
- Fuel/transport cost estimation
- Idempotent route plan creation
- Audit logging
- JSON export

Limitations:
- Straight-line geographic distance
- Constant assumed travel speed
- One vehicle per plan
- No live traffic or road restrictions
- No automatic dispatch

This is a prototype, not a production
navigation or fleet-dispatch engine.
"""


import copy
import json
import math
import threading
import uuid

from dataclasses import (
    asdict,
    dataclass,
    field,
)
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def required_text(
    value: str,
    name: str,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 200
    ):
        raise ValueError(
            f"Invalid {name}"
        )
    return value.strip()


def finite_nonnegative(
    value: float,
    name: str,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(
            f"{name} must be finite and nonnegative"
        )
    return float(value)


def parse_time(
    value: str,
) -> datetime:
    result = datetime.fromisoformat(
        value
    )

    if result.tzinfo is None:
        raise ValueError(
            "Timezone-aware datetime required"
        )

    return result.astimezone(
        timezone.utc
    )


def money(
    value: str | Decimal | float,
) -> Decimal:
    amount = Decimal(
        str(value)
    )

    if (
        not amount.is_finite()
        or amount < 0
    ):
        raise ValueError(
            "Invalid transport cost"
        )

    return amount


def haversine_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    radius = 6371.0088

    lat1, lon1, lat2, lon2 = map(
        math.radians,
        (lat1, lon1, lat2, lon2),
    )

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(delta_lon / 2) ** 2
    )

    return radius * 2 * math.asin(
        min(1.0, math.sqrt(a))
    )


class RouteStatus(str, Enum):
    PLANNED = "planned"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class RouteActor:
    user_id: str
    tenant_id: str
    roles: frozenset[str]
    warehouse_ids: frozenset[str] = (
        frozenset()
    )
    is_active: bool = True


@dataclass(frozen=True)
class RouteLocation:
    latitude: float
    longitude: float

    def __post_init__(self):
        if (
            not math.isfinite(self.latitude)
            or not -90 <= self.latitude <= 90
            or not math.isfinite(self.longitude)
            or not -180 <= self.longitude <= 180
        ):
            raise ValueError(
                "Invalid geographic coordinates"
            )


@dataclass(frozen=True)
class DeliveryStop:
    stop_id: str
    order_id: str
    location: RouteLocation
    demand_units: int
    service_minutes: int = 10
    earliest_at: str | None = None
    latest_at: str | None = None


@dataclass(frozen=True)
class DeliveryVehicle:
    vehicle_id: str
    tenant_id: str
    warehouse_id: str
    capacity_units: int
    cost_per_km: Decimal
    average_speed_kmh: float = 35.0


@dataclass(frozen=True)
class PlannedStop:
    stop_id: str
    order_id: str
    sequence: int
    arrival_at: str
    departure_at: str
    leg_distance_km: float
    cumulative_distance_km: float


@dataclass
class DeliveryRoutePlan:
    route_id: str
    tenant_id: str
    warehouse_id: str
    vehicle_id: str
    status: RouteStatus
    departure_at: str
    return_at: str
    stops: list[PlannedStop]
    total_distance_km: float
    estimated_cost: Decimal
    total_demand_units: int
    created_by: str
    created_at: str
    source_fingerprint: str


@dataclass(frozen=True)
class RouteAuditEvent:
    event_id: str
    tenant_id: str
    route_id: str
    actor_id: str
    action: str
    timestamp: str
    details: dict[str, Any] = field(
        default_factory=dict
    )


class RetailRouteOptimizationService:
    PLANNER_ROLES = frozenset({
        "route_planner",
        "logistics_manager",
        "operations_manager",
        "corporate_admin",
    })

    READER_ROLES = (
        PLANNER_ROLES
        | frozenset({
            "logistics_analyst",
            "warehouse_manager",
        })
    )

    def __init__(
        self,
        tenant_id: str,
    ):
        self.tenant_id = required_text(
            tenant_id,
            "tenant_id",
        )

        self._lock = threading.RLock()

        self._plans: dict[
            str, DeliveryRoutePlan
        ] = {}

        self._audit: list[
            RouteAuditEvent
        ] = []

    def _authorize(
        self,
        actor: RouteActor,
        roles: frozenset[str],
        warehouse_id: str | None = None,
    ) -> None:
        if (
            not actor.is_active
            or actor.tenant_id
            != self.tenant_id
            or not actor.user_id.strip()
            or not (actor.roles & roles)
        ):
            raise PermissionError(
                "Route service access denied"
            )

        if (
            warehouse_id is not None
            and "corporate_admin"
            not in actor.roles
            and warehouse_id
            not in actor.warehouse_ids
        ):
            raise PermissionError(
                "Warehouse access denied"
            )

    def _validate_vehicle(
        self,
        vehicle: DeliveryVehicle,
    ) -> None:
        if vehicle.tenant_id != (
            self.tenant_id
        ):
            raise PermissionError(
                "Cross-tenant vehicle"
            )

        required_text(
            vehicle.vehicle_id,
            "vehicle_id",
        )

        required_text(
            vehicle.warehouse_id,
            "warehouse_id",
        )

        if (
            isinstance(vehicle.capacity_units, bool)
            or not isinstance(
                vehicle.capacity_units,
                int,
            )
            or vehicle.capacity_units <= 0
        ):
            raise ValueError(
                "Vehicle capacity must be positive"
            )

        if (
            not math.isfinite(
                vehicle.average_speed_kmh
            )
            or vehicle.average_speed_kmh <= 0
        ):
            raise ValueError(
                "Invalid vehicle speed"
            )

        money(
            vehicle.cost_per_km
        )

    def _validate_stops(
        self,
        stops: list[DeliveryStop],
        departure: datetime,
    ) -> None:
        if not stops:
            raise ValueError(
                "At least one stop required"
            )

        if len(stops) > 100:
            raise ValueError(
                "Maximum 100 stops per plan"
            )

        ids = set()

        for stop in stops:
            required_text(
                stop.stop_id,
                "stop_id",
            )

            required_text(
                stop.order_id,
                "order_id",
            )

            if stop.stop_id in ids:
                raise ValueError(
                    "Duplicate stop ID"
                )

            ids.add(
                stop.stop_id
            )

            if (
                isinstance(stop.demand_units, bool)
                or not isinstance(
                    stop.demand_units,
                    int,
                )
                or stop.demand_units <= 0
            ):
                raise ValueError(
                    "Stop demand must be positive"
                )

            if (
                isinstance(stop.service_minutes, bool)
                or not isinstance(
                    stop.service_minutes,
                    int,
                )
                or stop.service_minutes < 0
            ):
                raise ValueError(
                    "Invalid service minutes"
                )

            if stop.earliest_at:
                earliest = parse_time(
                    stop.earliest_at
                )
            else:
                earliest = departure

            if stop.latest_at:
                latest = parse_time(
                    stop.latest_at
                )
            else:
                latest = None

            if (
                latest is not None
                and earliest > latest
            ):
                raise ValueError(
                    "Invalid delivery time window"
                )

    @staticmethod
    def _distance(
        a: RouteLocation,
        b: RouteLocation,
    ) -> float:
        return haversine_km(
            a.latitude,
            a.longitude,
            b.latitude,
            b.longitude,
        )

    def _route_distance(
        self,
        depot: RouteLocation,
        stops: list[DeliveryStop],
    ) -> float:
        current = depot
        total = 0.0

        for stop in stops:
            total += self._distance(
                current,
                stop.location,
            )
            current = stop.location

        total += self._distance(
            current,
            depot,
        )

        return total

    def _nearest_neighbor(
        self,
        depot: RouteLocation,
        stops: list[DeliveryStop],
    ) -> list[DeliveryStop]:
        remaining = stops.copy()
        ordered = []
        current = depot

        while remaining:
            next_stop = min(
                remaining,
                key=lambda stop: (
                    self._distance(
                        current,
                        stop.location,
                    ),
                    stop.stop_id,
                ),
            )

            ordered.append(
                next_stop
            )

            remaining.remove(
                next_stop
            )

            current = (
                next_stop.location
            )

        return ordered

    def _two_opt(
        self,
        depot: RouteLocation,
        stops: list[DeliveryStop],
    ) -> list[DeliveryStop]:
        best = stops.copy()

        if len(best) < 3:
            return best

        improved = True
        iterations = 0

        while improved and iterations < 30:
            improved = False
            iterations += 1

            best_distance = (
                self._route_distance(
                    depot,
                    best,
                )
            )

            for i in range(
                len(best) - 1
            ):
                for j in range(
                    i + 1,
                    len(best),
                ):
                    candidate = (
                        best[:i]
                        + list(
                            reversed(
                                best[i:j + 1]
                            )
                        )
                        + best[j + 1:]
                    )

                    candidate_distance = (
                        self._route_distance(
                            depot,
                            candidate,
                        )
                    )

                    if (
                        candidate_distance
                        < best_distance - 1e-9
                    ):
                        best = candidate
                        best_distance = (
                            candidate_distance
                        )
                        improved = True

            if not improved:
                break

        return best

    def _schedule(
        self,
        depot: RouteLocation,
        stops: list[DeliveryStop],
        vehicle: DeliveryVehicle,
        departure: datetime,
    ) -> tuple[
        list[PlannedStop],
        datetime,
        float,
    ]:
        current_location = depot
        current_time = departure
        distance_total = 0.0
        planned = []

        for sequence, stop in enumerate(
            stops,
            start=1,
        ):
            leg = self._distance(
                current_location,
                stop.location,
            )

            travel_minutes = (
                leg
                / vehicle.average_speed_kmh
                * 60
            )

            arrival = (
                current_time
                + timedelta(
                    minutes=travel_minutes
                )
            )

            if stop.earliest_at:
                earliest = parse_time(
                    stop.earliest_at
                )

                if arrival < earliest:
                    arrival = earliest

            if stop.latest_at:
                latest = parse_time(
                    stop.latest_at
                )

                if arrival > latest:
                    raise ValueError(
                        f"Delivery window missed: "
                        f"{stop.stop_id}"
                    )

            departure_stop = (
                arrival
                + timedelta(
                    minutes=stop.service_minutes
                )
            )

            distance_total += leg

            planned.append(
                PlannedStop(
                    stop_id=stop.stop_id,
                    order_id=stop.order_id,
                    sequence=sequence,
                    arrival_at=(
                        arrival.isoformat()
                    ),
                    departure_at=(
                        departure_stop.isoformat()
                    ),
                    leg_distance_km=round(
                        leg, 3
                    ),
                    cumulative_distance_km=round(
                        distance_total, 3
                    ),
                )
            )

            current_location = (
                stop.location
            )

            current_time = (
                departure_stop
            )

        return_leg = self._distance(
            current_location,
            depot,
        )

        distance_total += (
            return_leg
        )

        return_time = (
            current_time
            + timedelta(
                minutes=(
                    return_leg
                    / vehicle.average_speed_kmh
                    * 60
                )
            )
        )

        return (
            planned,
            return_time,
            distance_total,
        )

    def optimize_route(
        self,
        actor: RouteActor,
        route_id: str,
        warehouse_id: str,
        depot: RouteLocation,
        vehicle: DeliveryVehicle,
        stops: Iterable[DeliveryStop],
        departure_at: str,
    ) -> DeliveryRoutePlan:
        self._authorize(
            actor,
            self.PLANNER_ROLES,
            warehouse_id,
        )

        route_id = required_text(
            route_id,
            "route_id",
        )

        warehouse_id = required_text(
            warehouse_id,
            "warehouse_id",
        )

        self._validate_vehicle(
            vehicle
        )

        if vehicle.warehouse_id != (
            warehouse_id
        ):
            raise ValueError(
                "Vehicle warehouse mismatch"
            )

        departure = parse_time(
            departure_at
        )

        stops = list(
            stops
        )

        self._validate_stops(
            stops,
            departure,
        )

        demand = sum(
            stop.demand_units
            for stop in stops
        )

        if demand > (
            vehicle.capacity_units
        ):
            raise ValueError(
                "Vehicle capacity exceeded"
            )

        import hashlib

        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "warehouse_id": warehouse_id,
                    "depot": asdict(depot),
                    "vehicle": asdict(vehicle),
                    "stops": [
                        asdict(stop)
                        for stop in stops
                    ],
                    "departure": (
                        departure.isoformat()
                    ),
                },
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()

        with self._lock:
            existing = self._plans.get(
                route_id
            )

            if existing:
                if existing.source_fingerprint != (
                    fingerprint
                ):
                    raise ValueError(
                        "Route ID conflict"
                    )

                return copy.deepcopy(
                    existing
                )

        nearest = self._nearest_neighbor(
            depot,
            stops,
        )

        optimized = self._two_opt(
            depot,
            nearest,
        )

        # 2-opt minimizes distance and
        # may violate time windows.
        # If it does, try the initial
        # nearest-neighbor ordering.
        try:
            (
                planned,
                return_time,
                distance,
            ) = self._schedule(
                depot,
                optimized,
                vehicle,
                departure,
            )
        except ValueError:
            (
                planned,
                return_time,
                distance,
            ) = self._schedule(
                depot,
                nearest,
                vehicle,
                departure,
            )

        estimated_cost = (
            Decimal(
                str(round(distance, 3))
            )
            * money(
                vehicle.cost_per_km
            )
        ).quantize(
            Decimal("0.01")
        )

        plan = DeliveryRoutePlan(
            route_id=route_id,
            tenant_id=self.tenant_id,
            warehouse_id=warehouse_id,
            vehicle_id=(
                vehicle.vehicle_id
            ),
            status=RouteStatus.PLANNED,
            departure_at=(
                departure.isoformat()
            ),
            return_at=(
                return_time.isoformat()
            ),
            stops=planned,
            total_distance_km=round(
                distance, 3
            ),
            estimated_cost=(
                estimated_cost
            ),
            total_demand_units=demand,
            created_by=actor.user_id,
            created_at=utc_now(),
            source_fingerprint=(
                fingerprint
            ),
        )

        with self._lock:
            # Protect against concurrent
            # creation of the same route.
            existing = self._plans.get(
                route_id
            )

            if existing:
                if existing.source_fingerprint != (
                    fingerprint
                ):
                    raise ValueError(
                        "Route ID conflict"
                    )

                return copy.deepcopy(
                    existing
                )

            self._plans[
                route_id
            ] = plan

            self._audit.append(
                RouteAuditEvent(
                    event_id=str(
                        uuid.uuid4()
                    ),
                    tenant_id=self.tenant_id,
                    route_id=route_id,
                    actor_id=actor.user_id,
                    action="route_optimized",
                    timestamp=utc_now(),
                    details={
                        "stops": len(
                            planned
                        ),
                        "distance_km": (
                            plan.total_distance_km
                        ),
                    },
                )
            )

            return copy.deepcopy(
                plan
            )

    def get_route(
        self,
        actor: RouteActor,
        route_id: str,
    ) -> DeliveryRoutePlan:
        with self._lock:
            plan = self._plans.get(
                route_id
            )

            if plan is None:
                raise KeyError(
                    "Route not found"
                )

            self._authorize(
                actor,
                self.READER_ROLES,
                plan.warehouse_id,
            )

            return copy.deepcopy(
                plan
            )

    def cancel_route(
        self,
        actor: RouteActor,
        route_id: str,
    ) -> DeliveryRoutePlan:
        with self._lock:
            plan = self._plans.get(
                route_id
            )

            if plan is None:
                raise KeyError(
                    "Route not found"
                )

            self._authorize(
                actor,
                self.PLANNER_ROLES,
                plan.warehouse_id,
            )

            if plan.status == (
                RouteStatus.CANCELLED
            ):
                return copy.deepcopy(
                    plan
                )

            plan.status = (
                RouteStatus.CANCELLED
            )

            self._audit.append(
                RouteAuditEvent(
                    event_id=str(
                        uuid.uuid4()
                    ),
                    tenant_id=self.tenant_id,
                    route_id=route_id,
                    actor_id=actor.user_id,
                    action="route_cancelled",
                    timestamp=utc_now(),
                )
            )

            return copy.deepcopy(
                plan
            )

    def list_routes(
        self,
        actor: RouteActor,
    ) -> list[DeliveryRoutePlan]:
        self._authorize(
            actor,
            self.READER_ROLES,
        )

        with self._lock:
            return [
                copy.deepcopy(plan)
                for plan in (
                    self._plans.values()
                )
                if (
                    "corporate_admin"
                    in actor.roles
                    or plan.warehouse_id
                    in actor.warehouse_ids
                )
            ]

    def export_json(
        self,
        actor: RouteActor,
        route_id: str,
        output_path: str | Path,
    ) -> Path:
        plan = self.get_route(
            actor,
            route_id,
        )

        self._authorize(
            actor,
            self.PLANNER_ROLES,
            plan.warehouse_id,
        )

        output = Path(
            output_path
        )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output.write_text(
            json.dumps(
                asdict(plan),
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        return output


if __name__ == "__main__":
    service = RetailRouteOptimizationService(
        tenant_id="demo"
    )

    planner = RouteActor(
        user_id="route-planner",
        tenant_id="demo",
        roles=frozenset({
            "route_planner",
        }),
        warehouse_ids=frozenset({
            "WH001",
        }),
    )

    depot = RouteLocation(
        latitude=10.0159,
        longitude=76.3419,
    )

    vehicle = DeliveryVehicle(
        vehicle_id="VEH001",
        tenant_id="demo",
        warehouse_id="WH001",
        capacity_units=100,
        cost_per_km=Decimal("12.00"),
        average_speed_kmh=35.0,
    )

    stops = [
        DeliveryStop(
            stop_id="STOP001",
            order_id="ORDER001",
            location=RouteLocation(
                9.9816,
                76.2999,
            ),
            demand_units=20,
        ),
        DeliveryStop(
            stop_id="STOP002",
            order_id="ORDER002",
            location=RouteLocation(
                10.0261,
                76.3125,
            ),
            demand_units=25,
        ),
        DeliveryStop(
            stop_id="STOP003",
            order_id="ORDER003",
            location=RouteLocation(
                9.9680,
                76.3180,
            ),
            demand_units=15,
        ),
    ]

    plan = service.optimize_route(
        actor=planner,
        route_id="ROUTE001",
        warehouse_id="WH001",
        depot=depot,
        vehicle=vehicle,
        stops=stops,
        departure_at=(
            "2026-10-28T09:00:00+05:30"
        ),
    )

    print(
        "Optimized stop sequence:",
        [
            stop.stop_id
            for stop in plan.stops
        ],
    )

    print(
        "Estimated distance:",
        plan.total_distance_km,
        "km",
    )

    print(
        "Estimated transport cost:",
        plan.estimated_cost,
    )
