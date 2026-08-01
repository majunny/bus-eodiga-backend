"""Common service-quality, distance, fuel, and cost metrics."""

from typing import Dict, List

from config import SimulationConfig
from models import PassengerRequest, RequestStatus, SimulationResult


class MetricsCalculator:
    """Calculate comparable metrics from either simulation result type."""

    def __init__(self, config: SimulationConfig) -> None:
        """Use common fuel, service, and financial assumptions."""

        self.config = config

    def calculate(self, result: SimulationResult) -> Dict[str, float]:
        """Return one flat metrics row suitable for pandas and CSV."""

        requests = [request for request in result.requests
                    if request.requested_at <= self.config.simulation_duration_minutes]
        completed = [request for request in requests
                     if request.status == RequestStatus.COMPLETED]
        completed_passengers = sum(item.passenger_count for item in completed)
        total_passengers = sum(item.passenger_count for item in requests)
        missed_passengers = total_passengers - completed_passengers
        waits = self._expand_by_passenger(completed, "wait")
        rides = self._expand_by_passenger(completed, "ride")
        total_distance = sum(vehicle.total_distance for vehicle in result.vehicles)
        empty_distance = sum(vehicle.empty_distance for vehicle in result.vehicles)
        passenger_distance = sum(vehicle.occupied_distance for vehicle in result.vehicles)
        vehicle_minutes = sum(vehicle.total_vehicle_minutes for vehicle in result.vehicles)
        passenger_minutes = sum(vehicle.total_passenger_minutes for vehicle in result.vehicles)
        capacity_minutes = sum(vehicle.capacity * vehicle.total_vehicle_minutes
                               for vehicle in result.vehicles)
        on_time_passengers = sum(
            request.passenger_count for request in completed
            if request.waiting_time() <= self.config.on_time_threshold_minutes
        )
        fuel_used = total_distance / self.config.fuel_efficiency_km_per_liter
        fuel_cost = fuel_used * self.config.fuel_price_per_liter
        driving_time_cost = vehicle_minutes * self.config.driving_cost_per_minute
        missed_cost = missed_passengers * self.config.missed_passenger_penalty_cost
        return {
            "total_requests": float(len(requests)),
            "total_passengers": float(total_passengers),
            "completed_passengers": float(completed_passengers),
            "missed_passengers": float(missed_passengers),
            "average_wait_time": sum(waits) / len(waits) if waits else 0.0,
            "maximum_wait_time": max(waits) if waits else 0.0,
            "average_ride_time": sum(rides) / len(rides) if rides else 0.0,
            "total_distance": total_distance,
            "empty_distance": empty_distance,
            "passenger_distance": passenger_distance,
            "distance_per_passenger": (total_distance / completed_passengers
                                       if completed_passengers else 0.0),
            "average_occupancy": (passenger_minutes / capacity_minutes
                                  if capacity_minutes else 0.0),
            "on_time_service_rate": (on_time_passengers / total_passengers
                                     if total_passengers else 1.0),
            "fuel_used": fuel_used,
            "fuel_cost": fuel_cost,
            "driving_time_cost": driving_time_cost,
            "missed_passenger_cost": missed_cost,
            "operation_cost": fuel_cost + driving_time_cost + missed_cost,
        }

    @staticmethod
    def _expand_by_passenger(requests: List[PassengerRequest],
                             metric: str) -> List[float]:
        """Expand request-level times so group requests are passenger-weighted."""

        values: List[float] = []
        for request in requests:
            value = request.waiting_time() if metric == "wait" else request.ride_time()
            values.extend([value] * request.passenger_count)
        return values

