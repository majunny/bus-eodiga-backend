"""Normalized priority scoring and capacity-aware request selection."""

from collections import Counter
from typing import Dict, List

from config import SimulationConfig
from map.route_provider import RouteProvider
from models import PassengerRequest, Vehicle


class DispatchStrategy:
    """Rank requests without exposing graph or coordinate implementation details."""

    def __init__(self, routes: RouteProvider, config: SimulationConfig) -> None:
        """Store the route service and adjustable scoring weights."""

        self.routes = routes
        self.config = config

    def priority_scores(self, requests: List[PassengerRequest], vehicle: Vehicle,
                        now: float) -> Dict[str, float]:
        """Calculate dimensionless scores with an urgency boost near max wait."""

        if not requests:
            return {}
        groups = Counter(request.destination for request in requests)
        max_group = max(groups.values())
        max_distance = max(
            self.routes.get_distance(vehicle.current_node, request.origin)
            for request in requests
        ) or 1.0
        weights = self.config.priority_weights
        scores: Dict[str, float] = {}
        for request in requests:
            wait_ratio = min(1.5, request.waiting_time(now) /
                             max(request.maximum_wait_time, 0.001))
            count_ratio = min(1.0, request.passenger_count / vehicle.capacity)
            group_ratio = groups[request.destination] / max_group
            distance = self.routes.get_distance(vehicle.current_node, request.origin)
            proximity = 1.0 - min(1.0, distance / max_distance)
            urgency = weights.urgency_bonus * max(0.0, (wait_ratio - 0.8) / 0.2)
            scores[request.request_id] = (
                weights.waiting_time * wait_ratio
                + weights.passenger_count * count_ratio
                + weights.destination_group * group_ratio
                + weights.vehicle_distance * proximity
                + urgency
            )
        return scores

    def select(self, requests: List[PassengerRequest], vehicle: Vehicle,
               now: float) -> List[PassengerRequest]:
        """Select a high-priority subset that fits the vehicle capacity."""

        scores = self.priority_scores(requests, vehicle, now)
        selected: List[PassengerRequest] = []
        load = vehicle.current_passengers
        for request in sorted(requests, key=lambda item: scores[item.request_id], reverse=True):
            if load + request.passenger_count <= vehicle.capacity:
                selected.append(request)
                load += request.passenger_count
        return selected

