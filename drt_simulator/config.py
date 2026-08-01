"""Configuration models and defaults for the DRT simulation."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List


@dataclass
class PriorityWeights:
    """Weights for normalized passenger-request priority components."""

    waiting_time: float = 4.0
    passenger_count: float = 1.0
    destination_group: float = 1.5
    vehicle_distance: float = 1.0
    urgency_bonus: float = 8.0


@dataclass
class RouteCostWeights:
    """Weights used to combine route cost components measured in minutes or km."""

    travel_time: float = 1.0
    waiting_time_penalty: float = 3.0
    ride_time_penalty: float = 1.5
    missed_request_penalty: float = 100.0
    empty_distance_penalty: float = 2.0


@dataclass
class SimulationConfig:
    """Editable settings shared by generators, simulators, and experiments."""

    vehicle_capacity: int = 6
    minimum_departure_passengers: int = 3
    maximum_wait_time_minutes: float = 10.0
    same_destination_threshold: int = 2
    nearly_full_ratio: float = 0.85
    step_minutes: float = 1.0
    simulation_duration_minutes: int = 120
    post_simulation_drain_minutes: int = 120
    random_seed: int = 42
    optimizer: str = "GREEDY"
    brute_force_max_tasks: int = 8
    peak_fixed_route_mode: bool = True
    allow_dynamic_insertion: bool = True
    dynamic_insertion_max_cost_minutes: float = 8.0
    fixed_route_headway_minutes: int = 20
    fuel_efficiency_km_per_liter: float = 6.0
    fuel_price_per_liter: float = 1700.0
    driving_cost_per_minute: float = 300.0
    missed_passenger_penalty_cost: float = 5000.0
    on_time_threshold_minutes: float = 10.0
    demand_rates_per_hour: Dict[str, float] = field(default_factory=lambda: {
        "LOW_DEMAND": 3.0,
        "NORMAL_DEMAND": 8.0,
        "PEAK_DEMAND": 16.0,
        "DESTINATION_CONCENTRATED": 9.0,
        "RANDOM_SCATTERED": 8.0,
    })
    destination_weights: Dict[str, float] = field(default_factory=lambda: {
        "hospital": 0.40,
        "welfare_center": 0.30,
        "market": 0.20,
        "community_center": 0.10,
    })
    fixed_route: List[str] = field(default_factory=lambda: [
        "depot", "stop_a", "hospital", "market", "welfare_center",
        "stop_b", "community_center", "depot",
    ])
    priority_weights: PriorityWeights = field(default_factory=PriorityWeights)
    route_cost_weights: RouteCostWeights = field(default_factory=RouteCostWeights)


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_MAP_PATH = PROJECT_DIR / "data" / "virtual_map.json"
DEFAULT_RESULTS_DIR = PROJECT_DIR / "data" / "simulation_results"
