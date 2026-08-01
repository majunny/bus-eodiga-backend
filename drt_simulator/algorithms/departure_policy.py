"""Rules for deciding when a waiting DRT vehicle should depart."""

from collections import Counter
from dataclasses import dataclass
from typing import List

from config import SimulationConfig
from models import PassengerRequest, Vehicle


@dataclass(frozen=True)
class DepartureDecision:
    """Machine-readable departure outcome and its principal reason."""

    should_depart: bool
    reason: str

    def as_dict(self) -> dict:
        """Return the JSON-friendly shape used by future integrations."""

        return {"should_depart": self.should_depart, "reason": self.reason}


class DeparturePolicy:
    """Evaluate demand, urgency, capacity, destination, and peak-mode rules."""

    def __init__(self, config: SimulationConfig) -> None:
        """Use threshold values from the central configuration."""

        self.config = config

    def decide(self, waiting: List[PassengerRequest], vehicle: Vehicle,
               now: float, is_peak_time: bool = False) -> DepartureDecision:
        """Return whether to depart and the highest-priority triggering rule."""

        if not waiting:
            return DepartureDecision(False, "NO_WAITING_REQUESTS")
        arrived = [request for request in waiting if request.requested_at <= now]
        if not arrived:
            return DepartureDecision(False, "NO_WAITING_REQUESTS")
        if any(request.waiting_time(now) >= request.maximum_wait_time
               for request in arrived):
            return DepartureDecision(True, "MAX_WAIT_TIME_REACHED")
        passenger_total = sum(request.passenger_count for request in arrived)
        if passenger_total >= self.config.vehicle_capacity * self.config.nearly_full_ratio:
            return DepartureDecision(True, "VEHICLE_NEARLY_FULL")
        destination_counts = Counter()
        for request in arrived:
            destination_counts[request.destination] += request.passenger_count
        if destination_counts and max(destination_counts.values()) >= self.config.same_destination_threshold:
            return DepartureDecision(True, "SAME_DESTINATION_THRESHOLD")
        if passenger_total >= self.config.minimum_departure_passengers:
            return DepartureDecision(True, "MINIMUM_PASSENGERS_REACHED")
        if is_peak_time and self.config.peak_fixed_route_mode:
            return DepartureDecision(True, "PEAK_FIXED_ROUTE_MODE")
        return DepartureDecision(False, "WAITING_FOR_MORE_PASSENGERS")

