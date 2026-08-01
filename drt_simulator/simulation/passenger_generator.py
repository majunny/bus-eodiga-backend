"""Seeded passenger-demand generation for repeatable experiments."""

import random
from typing import Dict, List, Optional, Sequence

from config import SimulationConfig
from map.route_provider import RouteProvider
from models import DemandScenario, PassengerRequest, RequestSource


class PassengerGenerator:
    """Generate time-ordered requests using a configurable Poisson process."""

    def __init__(self, route_provider: RouteProvider, config: SimulationConfig) -> None:
        """Store routing context and demand defaults."""

        self.route_provider = route_provider
        self.config = config

    def generate(
        self,
        duration_minutes: int,
        scenario: DemandScenario = DemandScenario.NORMAL_DEMAND,
        seed: Optional[int] = None,
        time_of_day: str = "DAY",
        origins: Optional[Sequence[str]] = None,
        destination_weights: Optional[Dict[str, float]] = None,
        frequency_per_hour: Optional[float] = None,
    ) -> List[PassengerRequest]:
        """Generate requests from demand weights and an exponential interarrival model."""

        rng = random.Random(self.config.random_seed if seed is None else seed)
        rate = frequency_per_hour or self.config.demand_rates_per_hour[scenario.value]
        if time_of_day.upper() in ("MORNING_PEAK", "EVENING_PEAK"):
            rate *= 1.25
        if rate <= 0:
            return []

        locations = self.route_provider.get_all_locations()
        if origins is None:
            origins = [
                node["node_id"] for node in locations
                if node["node_type"] == "SMART_STOP"
            ]
        origin_weights = [
            max(0.01, float(self.route_provider.get_node(node)["passenger_demand_weight"]))
            for node in origins
        ]
        weights = dict(destination_weights or self.config.destination_weights)
        if scenario == DemandScenario.DESTINATION_CONCENTRATED:
            weights = {"hospital": 0.65, "welfare_center": 0.25,
                       "market": 0.07, "community_center": 0.03}
        elif scenario == DemandScenario.RANDOM_SCATTERED:
            destination_ids = [
                node["node_id"] for node in locations
                if node["node_type"] in ("DESTINATION", "SMART_STOP")
            ]
            weights = {node_id: 1.0 for node_id in destination_ids}
        destination_ids = list(weights)
        destination_probabilities = [max(0.0, weights[key]) for key in destination_ids]

        requests: List[PassengerRequest] = []
        current_time = 0.0
        index = 1
        while True:
            current_time += rng.expovariate(rate / 60.0)
            if current_time > duration_minutes:
                break
            origin = rng.choices(list(origins), weights=origin_weights, k=1)[0]
            valid = [item for item in destination_ids if item != origin]
            valid_weights = [weights[item] for item in valid]
            destination = rng.choices(valid, weights=valid_weights, k=1)[0]
            passenger_count = rng.choices([1, 2, 3], weights=[0.78, 0.18, 0.04], k=1)[0]
            requests.append(PassengerRequest(
                request_id="REQ-{:04d}".format(index),
                origin=origin,
                destination=destination,
                requested_at=round(current_time, 3),
                passenger_count=passenger_count,
                source=RequestSource.SIMULATION,
                maximum_wait_time=self.config.maximum_wait_time_minutes,
            ))
            index += 1
        return requests

