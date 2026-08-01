"""Time-step simulation engine for a single expandable DRT fleet."""

from typing import Dict, List, Optional, Sequence, Set

from algorithms.departure_policy import DeparturePolicy
from algorithms.dispatch import DispatchStrategy
from algorithms.request_manager import RequestManager
from algorithms.route_optimizer import RouteOptimizer
from config import SimulationConfig
from map.route_provider import RouteProvider
from models import (OptimizerType, PassengerRequest, RequestStatus,
                    SimulationEvent, SimulationResult, StopTask,
                    StopTaskType, Vehicle, VehicleStatus)


class DRTSimulator:
    """Advance request arrivals, planning, vehicle movement, and service events."""

    def __init__(self, routes: RouteProvider, config: SimulationConfig) -> None:
        """Build policy and routing collaborators from common configuration."""

        self.routes = routes
        self.config = config
        self.departure_policy = DeparturePolicy(config)
        self.dispatch = DispatchStrategy(routes, config)
        self.optimizer = RouteOptimizer(routes, config)

    def run(self, requests: Sequence[PassengerRequest],
            optimizer: Optional[OptimizerType] = None) -> SimulationResult:
        """Run one DRT vehicle and return requests, vehicle, and audit events."""

        manager = RequestManager()
        for request in requests:
            manager.register(request)
        vehicle = Vehicle("DRT-1", "depot", self.config.vehicle_capacity)
        events: List[SimulationEvent] = []
        emitted: Set[str] = set()
        overdue_emitted: Set[str] = set()
        now = 0.0
        active_task: Optional[StopTask] = None
        remaining_leg_time = 0.0
        end_time = float(self.config.simulation_duration_minutes)
        drain_until = end_time + self.config.post_simulation_drain_minutes

        while now <= drain_until:
            self._emit_arrivals(manager, now, emitted, events)
            self._emit_overdue(manager, now, overdue_emitted, events)

            if active_task is not None:
                remaining_leg_time -= self.config.step_minutes
                if remaining_leg_time <= 1e-9:
                    self._serve_task(active_task, manager, vehicle, now, events)
                    active_task = None
                now += self.config.step_minutes
                continue

            if vehicle.route:
                self._try_dynamic_insertion(manager, vehicle, now, optimizer, events)
                active_task = vehicle.route.pop(0)
                remaining_leg_time = self._begin_leg(
                    active_task, vehicle, now, events
                )
                if remaining_leg_time <= 1e-9:
                    self._serve_task(active_task, manager, vehicle, now, events)
                    active_task = None
                now += self.config.step_minutes
                continue

            if vehicle.current_node != "depot":
                vehicle.route = [StopTask(
                    "depot", StopTaskType.RETURN_TO_DEPOT, [], None
                )]
                vehicle.status = VehicleStatus.RETURNING
                events.append(SimulationEvent(
                    now, "VEHICLE_RETURNING", vehicle.vehicle_id,
                    node_id=vehicle.current_node,
                ))
                continue

            vehicle.status = VehicleStatus.WAITING_FOR_DEPARTURE
            waiting = manager.waiting(now)
            peak = 420 <= (now % 1440) <= 540 or 1020 <= (now % 1440) <= 1140
            decision = self.departure_policy.decide(waiting, vehicle, now, peak)
            if decision.should_depart:
                selected = self.dispatch.select(waiting, vehicle, now)
                if selected:
                    for request in selected:
                        manager.transition(request.request_id, RequestStatus.ASSIGNED,
                                           now, vehicle.vehicle_id)
                    plan = self.optimizer.optimize(
                        vehicle, selected, now,
                        optimizer or OptimizerType(self.config.optimizer.upper()),
                    )
                    vehicle.route = plan.tasks
                    vehicle.status = VehicleStatus.PLANNING
                    request_ids = [request.request_id for request in selected]
                    events.append(SimulationEvent(
                        now, "REQUESTS_ASSIGNED", vehicle.vehicle_id, request_ids,
                        vehicle.current_node, {"route_cost": plan.total_cost},
                    ))
                    events.append(SimulationEvent(
                        now, "VEHICLE_DEPARTED", vehicle.vehicle_id, request_ids,
                        vehicle.current_node, {"reason": decision.reason},
                    ))
            if now >= end_time and self._all_terminal_or_future(manager, end_time):
                break
            now += self.config.step_minutes

        for request in manager.all_requests():
            if request.status not in (RequestStatus.COMPLETED, RequestStatus.CANCELLED):
                events.append(SimulationEvent(
                    now, "REQUEST_UNSERVED", vehicle.vehicle_id,
                    [request.request_id], request.origin,
                ))
        return SimulationResult("DRT", manager.all_requests(), [vehicle], events, now)

    def _emit_arrivals(self, manager: RequestManager, now: float,
                       emitted: Set[str], events: List[SimulationEvent]) -> None:
        """Record newly visible requests once."""

        for request in manager.all_requests():
            if request.requested_at <= now and request.request_id not in emitted:
                emitted.add(request.request_id)
                events.append(SimulationEvent(
                    now, "REQUEST_CREATED", request_ids=[request.request_id],
                    node_id=request.origin,
                ))

    def _emit_overdue(self, manager: RequestManager, now: float,
                      emitted: Set[str], events: List[SimulationEvent]) -> None:
        """Record maximum-wait violations once per request."""

        for request in manager.overdue(now):
            if request.request_id not in emitted:
                emitted.add(request.request_id)
                events.append(SimulationEvent(
                    now, "MAX_WAIT_EXCEEDED", request_ids=[request.request_id],
                    node_id=request.origin,
                ))

    def _begin_leg(self, task: StopTask, vehicle: Vehicle, now: float,
                   events: List[SimulationEvent]) -> float:
        """Account for one routed leg and return its travel time."""

        distance = self.routes.get_distance(vehicle.current_node, task.node_id)
        travel_time = self.routes.get_travel_time(vehicle.current_node, task.node_id)
        vehicle.total_distance += distance
        if vehicle.current_passengers:
            vehicle.occupied_distance += distance
        else:
            vehicle.empty_distance += distance
        vehicle.total_vehicle_minutes += travel_time
        vehicle.total_passenger_minutes += vehicle.current_passengers * travel_time
        vehicle.status = (VehicleStatus.RETURNING
                          if task.task_type == StopTaskType.RETURN_TO_DEPOT
                          else VehicleStatus.MOVING)
        events.append(SimulationEvent(
            now, "VEHICLE_MOVING", vehicle.vehicle_id, task.request_ids,
            vehicle.current_node,
            {"destination": task.node_id, "distance_km": distance,
             "travel_time_minutes": travel_time},
        ))
        return travel_time

    def _serve_task(self, task: StopTask, manager: RequestManager,
                    vehicle: Vehicle, now: float,
                    events: List[SimulationEvent]) -> None:
        """Apply pickup, drop-off, or return action at leg completion."""

        vehicle.current_node = task.node_id
        if task.task_type == StopTaskType.PICKUP:
            vehicle.status = VehicleStatus.BOARDING
            for request_id in task.request_ids:
                request = manager.transition(request_id, RequestStatus.PICKED_UP, now)
                if vehicle.current_passengers + request.passenger_count > vehicle.capacity:
                    raise RuntimeError("Route violated vehicle capacity")
                vehicle.current_passengers += request.passenger_count
                vehicle.onboard_request_ids.append(request_id)
            events.append(SimulationEvent(
                now, "PASSENGERS_PICKED_UP", vehicle.vehicle_id,
                task.request_ids, task.node_id,
                {"onboard": vehicle.current_passengers},
            ))
        elif task.task_type == StopTaskType.DROPOFF:
            vehicle.status = VehicleStatus.ALIGHTING
            for request_id in task.request_ids:
                request = manager.transition(request_id, RequestStatus.COMPLETED, now)
                vehicle.current_passengers -= request.passenger_count
                vehicle.onboard_request_ids.remove(request_id)
            events.append(SimulationEvent(
                now, "PASSENGERS_DROPPED_OFF", vehicle.vehicle_id,
                task.request_ids, task.node_id,
                {"onboard": vehicle.current_passengers},
            ))
        else:
            vehicle.status = VehicleStatus.IDLE
            events.append(SimulationEvent(
                now, "VEHICLE_RETURNED", vehicle.vehicle_id,
                node_id=task.node_id,
            ))

    def _try_dynamic_insertion(self, manager: RequestManager, vehicle: Vehicle,
                               now: float, optimizer: Optional[OptimizerType],
                               events: List[SimulationEvent]) -> None:
        """Insert arrived requests only when route-cost increase stays bounded."""

        if not self.config.allow_dynamic_insertion:
            return
        waiting = manager.waiting(now)
        if not waiting:
            return
        existing_ids = {request_id for task in vehicle.route
                        for request_id in task.request_ids}
        existing_ids.update(vehicle.onboard_request_ids)
        existing = [manager.get(request_id) for request_id in existing_ids]
        candidates = [request for request in waiting
                      if request.passenger_count <= vehicle.capacity]
        if not candidates:
            return
        method = optimizer or OptimizerType(self.config.optimizer.upper())
        baseline = self.optimizer.optimize(vehicle, existing, now, method)
        proposed = self.optimizer.optimize(vehicle, existing + candidates, now, method)
        increase = proposed.total_travel_time - baseline.total_travel_time
        if increase <= self.config.dynamic_insertion_max_cost_minutes:
            for request in candidates:
                manager.transition(request.request_id, RequestStatus.ASSIGNED,
                                   now, vehicle.vehicle_id)
            vehicle.route = proposed.tasks
            events.append(SimulationEvent(
                now, "ROUTE_CHANGED", vehicle.vehicle_id,
                [request.request_id for request in candidates], vehicle.current_node,
                {"incremental_minutes": increase},
            ))

    @staticmethod
    def _all_terminal_or_future(manager: RequestManager, end_time: float) -> bool:
        """Return true once requests within the configured horizon are terminal."""

        relevant = [request for request in manager.all_requests()
                    if request.requested_at <= end_time]
        return all(request.status in (RequestStatus.COMPLETED, RequestStatus.CANCELLED)
                   for request in relevant)
