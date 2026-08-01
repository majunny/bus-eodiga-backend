"""Capacity- and precedence-constrained DRT stop-order optimization."""

import time
from typing import Dict, List, Optional, Sequence, Set, Tuple

from config import SimulationConfig
from map.route_provider import RouteProvider
from models import (OptimizerType, PassengerRequest, RequestStatus, RoutePlan,
                    StopTask, StopTaskType, Vehicle)


TaskKey = Tuple[str, StopTaskType]


class RouteOptimizer:
    """Build feasible pickup/drop-off plans using exact or greedy search."""

    def __init__(self, routes: RouteProvider, config: SimulationConfig) -> None:
        """Store a vendor-independent routing service and cost settings."""

        self.routes = routes
        self.config = config

    def optimize(self, vehicle: Vehicle, requests: Sequence[PassengerRequest],
                 now: float, method: Optional[OptimizerType] = None) -> RoutePlan:
        """Return the lowest-cost feasible route found by the selected method."""

        started = time.perf_counter()
        request_map = {request.request_id: request for request in requests}
        serviceable = [request for request in requests
                       if request.passenger_count <= vehicle.capacity]
        missed_count = sum(request.passenger_count for request in requests
                           if request.passenger_count > vehicle.capacity)
        task_count = sum(1 if request.status == RequestStatus.PICKED_UP else 2
                         for request in serviceable)
        chosen = method or OptimizerType(self.config.optimizer.upper())
        if chosen == OptimizerType.BRUTE_FORCE and task_count > self.config.brute_force_max_tasks:
            chosen = OptimizerType.GREEDY
        if not serviceable:
            plan = self._evaluate(vehicle, [], request_map, now, missed_count)
        elif chosen == OptimizerType.BRUTE_FORCE:
            order = self._brute_force_order(vehicle, serviceable, now, missed_count)
            plan = self._evaluate(vehicle, order, request_map, now, missed_count)
        else:
            order = self._greedy_order(vehicle, serviceable, now)
            plan = self._evaluate(vehicle, order, request_map, now, missed_count)
        plan.computation_time_ms = (time.perf_counter() - started) * 1000.0
        return plan

    def compare_optimizers(self, vehicle: Vehicle,
                           requests: Sequence[PassengerRequest], now: float) -> Dict[str, RoutePlan]:
        """Run both algorithms on the same inputs for demonstration and timing."""

        return {
            "BRUTE_FORCE": self.optimize(vehicle, requests, now, OptimizerType.BRUTE_FORCE),
            "GREEDY": self.optimize(vehicle, requests, now, OptimizerType.GREEDY),
        }

    def _initial_state(self, vehicle: Vehicle,
                       requests: Sequence[PassengerRequest]) -> Tuple[Set[str], Set[str], int]:
        """Return picked, delivered, and current-load values for search."""

        picked = {request.request_id for request in requests
                  if request.status == RequestStatus.PICKED_UP}
        delivered: Set[str] = set()
        load = sum(request.passenger_count for request in requests
                   if request.request_id in picked)
        if vehicle.current_passengers and load != vehicle.current_passengers:
            load = vehicle.current_passengers
        return picked, delivered, load

    def _feasible_tasks(self, requests: Sequence[PassengerRequest], picked: Set[str],
                        delivered: Set[str], load: int, capacity: int) -> List[TaskKey]:
        """Return actions that preserve pickup precedence and capacity."""

        feasible: List[TaskKey] = []
        for request in requests:
            request_id = request.request_id
            if request_id in delivered:
                continue
            if request_id in picked:
                feasible.append((request_id, StopTaskType.DROPOFF))
            elif load + request.passenger_count <= capacity:
                feasible.append((request_id, StopTaskType.PICKUP))
        return feasible

    def _node_for(self, task: TaskKey,
                  request_map: Dict[str, PassengerRequest]) -> str:
        """Resolve a task to its origin or destination node."""

        request = request_map[task[0]]
        return request.origin if task[1] == StopTaskType.PICKUP else request.destination

    def _apply_task(self, task: TaskKey, request: PassengerRequest,
                    picked: Set[str], delivered: Set[str], load: int) -> int:
        """Mutate search sets and return the resulting load."""

        if task[1] == StopTaskType.PICKUP:
            picked.add(request.request_id)
            return load + request.passenger_count
        delivered.add(request.request_id)
        return load - request.passenger_count

    def _brute_force_order(self, vehicle: Vehicle,
                           requests: Sequence[PassengerRequest], now: float,
                           missed_count: int) -> List[TaskKey]:
        """Enumerate every feasible precedence/capacity order with branch-and-bound."""

        request_map = {request.request_id: request for request in requests}
        initial_picked, initial_delivered, initial_load = self._initial_state(vehicle, requests)
        best_cost = float("inf")
        best_order: List[TaskKey] = []

        def search(current_node: str, picked: Set[str], delivered: Set[str],
                   load: int, elapsed: float, order: List[TaskKey]) -> None:
            """Explore one feasible branch and prune travel-time lower bounds."""

            nonlocal best_cost, best_order
            if len(delivered) == len(requests):
                plan = self._evaluate(vehicle, order, request_map, now, missed_count)
                if plan.total_cost < best_cost:
                    best_cost = plan.total_cost
                    best_order = list(order)
                return
            if elapsed * self.config.route_cost_weights.travel_time >= best_cost:
                return
            feasible = self._feasible_tasks(
                requests, picked, delivered, load, vehicle.capacity
            )
            feasible.sort(key=lambda item: self.routes.get_travel_time(
                current_node, self._node_for(item, request_map)
            ))
            for task in feasible:
                node = self._node_for(task, request_map)
                travel = self.routes.get_travel_time(current_node, node)
                next_picked = set(picked)
                next_delivered = set(delivered)
                next_load = self._apply_task(
                    task, request_map[task[0]], next_picked, next_delivered, load
                )
                search(node, next_picked, next_delivered, next_load,
                       elapsed + travel, order + [task])

        search(vehicle.current_node, initial_picked, initial_delivered,
               initial_load, 0.0, [])
        return best_order

    def _greedy_order(self, vehicle: Vehicle,
                      requests: Sequence[PassengerRequest], now: float) -> List[TaskKey]:
        """Repeatedly choose a nearby feasible action, boosting urgent pickups."""

        request_map = {request.request_id: request for request in requests}
        picked, delivered, load = self._initial_state(vehicle, requests)
        current_node = vehicle.current_node
        current_time = now
        result: List[TaskKey] = []
        while len(delivered) < len(requests):
            feasible = self._feasible_tasks(requests, picked, delivered,
                                            load, vehicle.capacity)
            if not feasible:
                raise ValueError("No feasible task remains; vehicle state is inconsistent")

            def score(task: TaskKey) -> float:
                """Return travel time reduced by pickup urgency in minutes."""

                travel = self.routes.get_travel_time(
                    current_node, self._node_for(task, request_map)
                )
                if task[1] == StopTaskType.PICKUP:
                    request = request_map[task[0]]
                    urgency = request.waiting_time(current_time) / max(
                        request.maximum_wait_time, 0.001
                    )
                    travel -= min(5.0, urgency * 3.0)
                return travel

            task = min(feasible, key=score)
            node = self._node_for(task, request_map)
            current_time += self.routes.get_travel_time(current_node, node)
            load = self._apply_task(task, request_map[task[0]], picked, delivered, load)
            current_node = node
            result.append(task)
        return result

    def _evaluate(self, vehicle: Vehicle, order: Sequence[TaskKey],
                  request_map: Dict[str, PassengerRequest], now: float,
                  missed_count: int) -> RoutePlan:
        """Calculate and retain every route cost component separately."""

        current_node = vehicle.current_node
        current_time = now
        load = vehicle.current_passengers
        total_time = 0.0
        total_distance = 0.0
        empty_distance = 0.0
        wait_penalty = 0.0
        ride_penalty = 0.0
        pickup_times: Dict[str, float] = {
            request.request_id: request.picked_up_at or now
            for request in request_map.values()
            if request.status == RequestStatus.PICKED_UP
        }
        tasks: List[StopTask] = []
        for request_id, task_type in order:
            request = request_map[request_id]
            node = request.origin if task_type == StopTaskType.PICKUP else request.destination
            travel_time = self.routes.get_travel_time(current_node, node)
            distance = self.routes.get_distance(current_node, node)
            if load == 0:
                empty_distance += distance
            total_time += travel_time
            total_distance += distance
            current_time += travel_time
            if task_type == StopTaskType.PICKUP:
                load += request.passenger_count
                pickup_times[request_id] = current_time
                lateness = max(0.0, current_time - request.requested_at
                               - request.maximum_wait_time)
                wait_penalty += lateness * request.passenger_count
            else:
                load -= request.passenger_count
                direct_time = self.routes.get_travel_time(request.origin, request.destination)
                actual_ride = current_time - pickup_times[request_id]
                ride_penalty += max(0.0, actual_ride - direct_time) * request.passenger_count
            task = StopTask(node, task_type, [request_id], current_time)
            if (tasks and tasks[-1].node_id == task.node_id
                    and tasks[-1].task_type == task.task_type):
                tasks[-1].request_ids.append(request_id)
                tasks[-1].scheduled_arrival_time = current_time
            else:
                tasks.append(task)
            current_node = node
        missed_penalty = float(missed_count)
        weights = self.config.route_cost_weights
        total_cost = (
            weights.travel_time * total_time
            + weights.waiting_time_penalty * wait_penalty
            + weights.ride_time_penalty * ride_penalty
            + weights.missed_request_penalty * missed_penalty
            + weights.empty_distance_penalty * empty_distance
        )
        return RoutePlan(
            tasks=tasks,
            total_cost=total_cost,
            total_travel_time=total_time,
            total_distance=total_distance,
            waiting_time_penalty=wait_penalty,
            passenger_ride_time_penalty=ride_penalty,
            missed_request_penalty=missed_penalty,
            empty_distance_penalty=empty_distance,
        )

