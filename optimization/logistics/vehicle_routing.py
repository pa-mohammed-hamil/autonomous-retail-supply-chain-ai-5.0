"""Planned module: vehicle routing. Implementation pending."""

"""
ai/optimization/vehicle_routing.py

Capacitated Vehicle Routing with Time Windows.

Uses Google OR-Tools.

Features:
- Multiple vehicles and delivery stops
- Vehicle capacity constraints
- Delivery time windows
- Route distance optimization
- Optional dropping of nonmandatory stops
- Per-vehicle operating cost
- Route recommendations only

Units:
- Time: minutes from planning horizon start
- Distance: kilometers
- Load: integer capacity units

All vehicles start and finish at a shared depot.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ortools.constraint_solver import (
    pywrapcp,
    routing_enums_pb2,
)


@dataclass(frozen=True)
class RouteStop:
    stop_id: str
    demand_units: int
    earliest_minute: int
    latest_minute: int
    service_minutes: int = 10
    mandatory: bool = True
    drop_penalty: int = 100_000

    def __post_init__(self):
        if not self.stop_id:
            raise ValueError("Stop ID required")

        values = (
            self.demand_units,
            self.earliest_minute,
            self.latest_minute,
            self.service_minutes,
            self.drop_penalty,
        )

        if any(
            isinstance(v, bool)
            or not isinstance(v, int)
            or v < 0
            for v in values
        ):
            raise ValueError(
                "Stop values must be nonnegative integers"
            )

        if self.latest_minute < self.earliest_minute:
            raise ValueError("Invalid time window")


@dataclass(frozen=True)
class RouteVehicle:
    vehicle_id: str
    capacity_units: int
    cost_per_km: float = 15.0

    def __post_init__(self):
        if not self.vehicle_id:
            raise ValueError("Vehicle ID required")

        if (
            isinstance(self.capacity_units, bool)
            or not isinstance(self.capacity_units, int)
            or self.capacity_units <= 0
        ):
            raise ValueError("Invalid vehicle capacity")

        if (
            isinstance(self.cost_per_km, bool)
            or not isinstance(self.cost_per_km, (int, float))
            or not math.isfinite(self.cost_per_km)
            or self.cost_per_km < 0
        ):
            raise ValueError("Invalid cost per km")


class VehicleRoutingOptimizer:

    def optimize(
        self,
        stops: list[RouteStop],
        vehicles: list[RouteVehicle],
        distance_km: list[list[float]],
        travel_minutes: list[list[int]],
        depot_id: str = "DEPOT",
        horizon_minutes: int = 1440,
        max_solve_seconds: int = 10,
    ) -> dict:

        if not vehicles:
            raise ValueError("At least one vehicle required")

        if horizon_minutes <= 0:
            raise ValueError("Invalid planning horizon")

        if max_solve_seconds <= 0:
            raise ValueError("Invalid solve time")

        node_ids = [depot_id] + [
            stop.stop_id for stop in stops
        ]

        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Duplicate location IDs")

        if len({
            v.vehicle_id for v in vehicles
        }) != len(vehicles):
            raise ValueError("Duplicate vehicle IDs")

        size = len(node_ids)

        if (
            len(distance_km) != size
            or len(travel_minutes) != size
            or any(len(row) != size for row in distance_km)
            or any(len(row) != size for row in travel_minutes)
        ):
            raise ValueError(
                "Travel matrices must match node count"
            )

        for row in distance_km:
            for value in row:
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or value < 0
                ):
                    raise ValueError("Invalid distance")

        for row in travel_minutes:
            for value in row:
                if (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or value < 0
                ):
                    raise ValueError("Invalid travel time")

        manager = pywrapcp.RoutingIndexManager(
            size,
            len(vehicles),
            0,
        )

        routing = pywrapcp.RoutingModel(manager)

        # Monetary objective in integer cents.
        for vehicle_index, vehicle in enumerate(vehicles):

            def cost_callback(
                from_index,
                to_index,
                v=vehicle,
            ):
                from_node = manager.IndexToNode(
                    from_index
                )
                to_node = manager.IndexToNode(
                    to_index
                )

                return round(
                    distance_km[from_node][to_node]
                    * v.cost_per_km
                    * 100
                )

            callback_id = routing.RegisterTransitCallback(
                cost_callback
            )

            routing.SetArcCostEvaluatorOfVehicle(
                callback_id,
                vehicle_index,
            )

        def demand_callback(index):
            node = manager.IndexToNode(index)

            if node == 0:
                return 0

            return stops[node - 1].demand_units

        demand_id = routing.RegisterUnaryTransitCallback(
            demand_callback
        )

        routing.AddDimensionWithVehicleCapacity(
            demand_id,
            0,
            [
                vehicle.capacity_units
                for vehicle in vehicles
            ],
            True,
            "Capacity",
        )

        def time_callback(from_index, to_index):
            from_node = manager.IndexToNode(
                from_index
            )
            to_node = manager.IndexToNode(
                to_index
            )

            service_time = (
                0
                if from_node == 0
                else stops[from_node - 1].service_minutes
            )

            return (
                travel_minutes[from_node][to_node]
                + service_time
            )

        time_id = routing.RegisterTransitCallback(
            time_callback
        )

        routing.AddDimension(
            time_id,
            horizon_minutes,
            horizon_minutes,
            False,
            "Time",
        )

        time_dimension = routing.GetDimensionOrDie(
            "Time"
        )

        for node, stop in enumerate(stops, start=1):
            if stop.latest_minute > horizon_minutes:
                raise ValueError(
                    "Stop exceeds planning horizon"
                )

            index = manager.NodeToIndex(node)

            time_dimension.CumulVar(index).SetRange(
                stop.earliest_minute,
                stop.latest_minute,
            )

            if not stop.mandatory:
                routing.AddDisjunction(
                    [index],
                    stop.drop_penalty,
                )

        for vehicle_index in range(len(vehicles)):
            start = routing.Start(vehicle_index)
            end = routing.End(vehicle_index)

            time_dimension.CumulVar(start).SetRange(
                0,
                horizon_minutes,
            )
            time_dimension.CumulVar(end).SetRange(
                0,
                horizon_minutes,
            )

            routing.AddVariableMinimizedByFinalizer(
                time_dimension.CumulVar(start)
            )

            routing.AddVariableMinimizedByFinalizer(
                time_dimension.CumulVar(end)
            )

        parameters = (
            pywrapcp.DefaultRoutingSearchParameters()
        )

        parameters.first_solution_strategy = (
            routing_enums_pb2
            .FirstSolutionStrategy
            .PATH_CHEAPEST_ARC
        )

        parameters.local_search_metaheuristic = (
            routing_enums_pb2
            .LocalSearchMetaheuristic
            .GUIDED_LOCAL_SEARCH
        )

        parameters.time_limit.seconds = (
            max_solve_seconds
        )

        solution = routing.SolveWithParameters(
            parameters
        )

        if solution is None:
            return {
                "status": "no_feasible_solution_found",
                "routes": [],
                "recommendation_only": True,
            }

        routes = []
        total_cost = 0.0

        for vehicle_index, vehicle in enumerate(vehicles):
            index = routing.Start(vehicle_index)

            route_nodes = []
            route_distance = 0.0
            route_load = 0

            while not routing.IsEnd(index):
                node = manager.IndexToNode(index)

                arrival = solution.Value(
                    time_dimension.CumulVar(index)
                )

                route_nodes.append({
                    "location_id": node_ids[node],
                    "arrival_minute": arrival,
                })

                if node > 0:
                    route_load += (
                        stops[node - 1].demand_units
                    )

                next_index = solution.Value(
                    routing.NextVar(index)
                )

                next_node = manager.IndexToNode(
                    next_index
                )

                route_distance += (
                    distance_km[node][next_node]
                )

                index = next_index

            end_arrival = solution.Value(
                time_dimension.CumulVar(index)
            )

            route_nodes.append({
                "location_id": depot_id,
                "arrival_minute": end_arrival,
            })

            cost = (
                route_distance
                * vehicle.cost_per_km
            )

            total_cost += cost

            routes.append({
                "vehicle_id": vehicle.vehicle_id,
                "stops": route_nodes,
                "total_load_units": route_load,
                "distance_km": round(
                    route_distance, 2
                ),
                "estimated_cost": round(
                    cost, 2
                ),
            })

        dropped = []

        for node, stop in enumerate(stops, start=1):
            if stop.mandatory:
                continue

            index = manager.NodeToIndex(node)

            if solution.Value(
                routing.NextVar(index)
            ) == index:
                dropped.append(stop.stop_id)

        return {
            "status": "feasible_solution",
            "routes": routes,
            "dropped_optional_stops": dropped,
            "total_estimated_cost": round(
                total_cost, 2
            ),
            "objective_cost_cents": (
                solution.ObjectiveValue()
            ),
            "recommendation_only": True,
            "vehicles_dispatched": False,
        }
