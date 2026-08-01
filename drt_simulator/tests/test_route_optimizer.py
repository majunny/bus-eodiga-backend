"""Constraint tests for both route-optimization strategies."""

from algorithms.route_optimizer import RouteOptimizer
from config import DEFAULT_MAP_PATH, SimulationConfig
from map.route_provider import RouteProvider
from map.virtual_map import VirtualMap
from models import OptimizerType, PassengerRequest, StopTaskType, Vehicle


def _optimizer():
    """Create an optimizer over the bundled virtual map."""

    routes = RouteProvider(VirtualMap(DEFAULT_MAP_PATH))
    return RouteOptimizer(routes, SimulationConfig())


def test_dropoff_never_precedes_pickup():
    """Every request is picked up before it appears in a drop-off task."""

    requests = [PassengerRequest("r1", "stop_a", "hospital", 0),
                PassengerRequest("r2", "stop_b", "market", 0)]
    plan = _optimizer().optimize(Vehicle("v1", "depot", 6), requests, 0,
                                 OptimizerType.BRUTE_FORCE)
    seen = set()
    for task in plan.tasks:
        if task.task_type == StopTaskType.PICKUP:
            seen.update(task.request_ids)
        elif task.task_type == StopTaskType.DROPOFF:
            assert set(task.request_ids).issubset(seen)


def test_vehicle_capacity_is_never_exceeded():
    """The planned sequence never carries more riders than capacity."""

    requests = [PassengerRequest("r1", "stop_a", "hospital", 0, passenger_count=4),
                PassengerRequest("r2", "stop_b", "market", 0, passenger_count=4)]
    plan = _optimizer().optimize(Vehicle("v1", "depot", 6), requests, 0,
                                 OptimizerType.GREEDY)
    counts = {request.request_id: request.passenger_count for request in requests}
    load = 0
    for task in plan.tasks:
        change = sum(counts[item] for item in task.request_ids)
        load += change if task.task_type == StopTaskType.PICKUP else -change
        assert 0 <= load <= 6

