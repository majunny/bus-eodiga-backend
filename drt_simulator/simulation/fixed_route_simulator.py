"""Scheduled cyclic fixed-route bus simulator used as a fair baseline."""

from typing import List, Optional, Sequence, Set

from algorithms.request_manager import RequestManager
from config import SimulationConfig
from map.route_provider import RouteProvider
from models import (PassengerRequest, RequestStatus, SimulationEvent,
                    SimulationResult, Vehicle, VehicleStatus)


class FixedRouteSimulator:
    """Operate one capacity-limited bus over a configured repeating loop."""

    def __init__(self, routes: RouteProvider, config: SimulationConfig) -> None:
        """Store routing and timetable settings."""

        self.routes = routes
        self.config = config

    def run(self, requests: Sequence[PassengerRequest]) -> SimulationResult:
        """Serve the supplied request objects on the fixed cyclic route."""

        manager = RequestManager()
        for request in requests:
            manager.register(request)
        vehicle = Vehicle("FIXED-1", self.config.fixed_route[0],
                          self.config.vehicle_capacity)
        events: List[SimulationEvent] = []
        emitted: Set[str] = set()
        route = self.config.fixed_route
        route_index = 0
        now = 0.0
        next_departure = 0.0
        target: Optional[str] = None
        remaining = 0.0
        end_time = float(self.config.simulation_duration_minutes)
        drain_until = end_time + self.config.post_simulation_drain_minutes

        while now <= drain_until:
            self._emit_arrivals(manager, now, emitted, events)
            if target is not None:
                remaining -= self.config.step_minutes
                if remaining <= 1e-9:
                    vehicle.current_node = target
                    self._serve_stop(manager, vehicle, now, events)
                    target = None
                now += self.config.step_minutes
                continue

            if route_index == 0 and now < next_departure:
                vehicle.status = VehicleStatus.IDLE
                now += self.config.step_minutes
                continue
            if route_index == 0:
                next_departure = max(next_departure + self.config.fixed_route_headway_minutes,
                                     now + self.config.fixed_route_headway_minutes)
                events.append(SimulationEvent(
                    now, "VEHICLE_DEPARTED", vehicle.vehicle_id,
                    node_id=vehicle.current_node, details={"mode": "FIXED_ROUTE"},
                ))
            route_index = (route_index + 1) % len(route)
            target = route[route_index]
            remaining = self._begin_leg(vehicle, target, now, events)
            if now >= end_time and not vehicle.onboard_request_ids:
                relevant_waiting = [request for request in manager.waiting(now)
                                    if request.requested_at <= end_time]
                if not relevant_waiting:
                    break
            now += self.config.step_minutes

        for request in manager.all_requests():
            if request.status != RequestStatus.COMPLETED:
                events.append(SimulationEvent(
                    now, "REQUEST_UNSERVED", vehicle.vehicle_id,
                    [request.request_id], request.origin,
                ))
        return SimulationResult("FIXED_ROUTE", manager.all_requests(),
                                [vehicle], events, now)

    def _begin_leg(self, vehicle: Vehicle, target: str, now: float,
                   events: List[SimulationEvent]) -> float:
        """Account for the next mandatory route segment."""

        distance = self.routes.get_distance(vehicle.current_node, target)
        travel_time = self.routes.get_travel_time(vehicle.current_node, target)
        vehicle.total_distance += distance
        if vehicle.current_passengers:
            vehicle.occupied_distance += distance
        else:
            vehicle.empty_distance += distance
        vehicle.total_vehicle_minutes += travel_time
        vehicle.total_passenger_minutes += vehicle.current_passengers * travel_time
        vehicle.status = VehicleStatus.MOVING
        events.append(SimulationEvent(
            now, "VEHICLE_MOVING", vehicle.vehicle_id,
            node_id=vehicle.current_node,
            details={"destination": target, "distance_km": distance,
                     "travel_time_minutes": travel_time},
        ))
        return travel_time

    def _serve_stop(self, manager: RequestManager, vehicle: Vehicle,
                    now: float, events: List[SimulationEvent]) -> None:
        """Alight first, then board waiting passengers up to capacity."""

        dropped: List[str] = []
        for request_id in list(vehicle.onboard_request_ids):
            request = manager.get(request_id)
            if request.destination == vehicle.current_node:
                manager.transition(request_id, RequestStatus.COMPLETED, now)
                vehicle.current_passengers -= request.passenger_count
                vehicle.onboard_request_ids.remove(request_id)
                dropped.append(request_id)
        if dropped:
            events.append(SimulationEvent(
                now, "PASSENGERS_DROPPED_OFF", vehicle.vehicle_id,
                dropped, vehicle.current_node,
                {"onboard": vehicle.current_passengers},
            ))
        boarded: List[str] = []
        for request in manager.waiting(now):
            if request.origin != vehicle.current_node:
                continue
            if vehicle.current_passengers + request.passenger_count > vehicle.capacity:
                continue
            manager.transition(request.request_id, RequestStatus.ASSIGNED,
                               now, vehicle.vehicle_id)
            manager.transition(request.request_id, RequestStatus.PICKED_UP, now)
            vehicle.current_passengers += request.passenger_count
            vehicle.onboard_request_ids.append(request.request_id)
            boarded.append(request.request_id)
        if boarded:
            events.append(SimulationEvent(
                now, "PASSENGERS_PICKED_UP", vehicle.vehicle_id,
                boarded, vehicle.current_node,
                {"onboard": vehicle.current_passengers},
            ))

    @staticmethod
    def _emit_arrivals(manager: RequestManager, now: float,
                       emitted: Set[str], events: List[SimulationEvent]) -> None:
        """Record request occurrence once as simulation time advances."""

        for request in manager.all_requests():
            if request.requested_at <= now and request.request_id not in emitted:
                emitted.add(request.request_id)
                events.append(SimulationEvent(
                    now, "REQUEST_CREATED", request_ids=[request.request_id],
                    node_id=request.origin,
                ))
