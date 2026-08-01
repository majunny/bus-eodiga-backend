"""Domain models used throughout the transport simulation."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class RequestSource(str, Enum):
    """Originating channel of a passenger request."""

    CAMERA_CARD = "CAMERA_CARD"
    ANDROID_APP = "ANDROID_APP"
    SIMULATION = "SIMULATION"


class RequestStatus(str, Enum):
    """Lifecycle states of a passenger request."""

    WAITING = "WAITING"
    ASSIGNED = "ASSIGNED"
    PICKED_UP = "PICKED_UP"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class VehicleStatus(str, Enum):
    """Operational states of a vehicle."""

    IDLE = "IDLE"
    WAITING_FOR_DEPARTURE = "WAITING_FOR_DEPARTURE"
    PLANNING = "PLANNING"
    MOVING = "MOVING"
    BOARDING = "BOARDING"
    ALIGHTING = "ALIGHTING"
    RETURNING = "RETURNING"


class StopTaskType(str, Enum):
    """Action performed by a vehicle at a stop."""

    PICKUP = "PICKUP"
    DROPOFF = "DROPOFF"
    RETURN_TO_DEPOT = "RETURN_TO_DEPOT"


class DemandScenario(str, Enum):
    """Supported passenger demand patterns."""

    LOW_DEMAND = "LOW_DEMAND"
    NORMAL_DEMAND = "NORMAL_DEMAND"
    PEAK_DEMAND = "PEAK_DEMAND"
    DESTINATION_CONCENTRATED = "DESTINATION_CONCENTRATED"
    RANDOM_SCATTERED = "RANDOM_SCATTERED"


class OptimizerType(str, Enum):
    """Available constrained-route solution strategies."""

    BRUTE_FORCE = "BRUTE_FORCE"
    GREEDY = "GREEDY"


@dataclass
class PassengerRequest:
    """A request to carry one or more passengers between two map nodes."""

    request_id: str
    origin: str
    destination: str
    requested_at: float
    passenger_count: int = 1
    source: RequestSource = RequestSource.SIMULATION
    status: RequestStatus = RequestStatus.WAITING
    assigned_vehicle_id: Optional[str] = None
    picked_up_at: Optional[float] = None
    completed_at: Optional[float] = None
    maximum_wait_time: float = 10.0

    def waiting_time(self, now: Optional[float] = None) -> float:
        """Return minutes waited until pickup, completion, or the supplied time."""

        endpoint = self.picked_up_at
        if endpoint is None:
            endpoint = self.completed_at if self.completed_at is not None else now
        if endpoint is None:
            return 0.0
        return max(0.0, endpoint - self.requested_at)

    def ride_time(self) -> float:
        """Return minutes spent aboard after a completed trip."""

        if self.picked_up_at is None or self.completed_at is None:
            return 0.0
        return max(0.0, self.completed_at - self.picked_up_at)


@dataclass
class StopTask:
    """One pickup, drop-off, or depot-return action in a vehicle plan."""

    node_id: str
    task_type: StopTaskType
    request_ids: List[str] = field(default_factory=list)
    scheduled_arrival_time: Optional[float] = None


@dataclass
class Vehicle:
    """Mutable vehicle state designed to support multiple vehicles later."""

    vehicle_id: str
    current_node: str
    capacity: int
    current_passengers: int = 0
    status: VehicleStatus = VehicleStatus.IDLE
    route: List[StopTask] = field(default_factory=list)
    total_distance: float = 0.0
    empty_distance: float = 0.0
    occupied_distance: float = 0.0
    available_at: float = 0.0
    onboard_request_ids: List[str] = field(default_factory=list)
    total_passenger_minutes: float = 0.0
    total_vehicle_minutes: float = 0.0


@dataclass
class RoutePlan:
    """A feasible task order and its separately reported cost components."""

    tasks: List[StopTask]
    total_cost: float
    total_travel_time: float
    total_distance: float
    waiting_time_penalty: float
    passenger_ride_time_penalty: float
    missed_request_penalty: float
    empty_distance_penalty: float
    computation_time_ms: float = 0.0


@dataclass
class SimulationEvent:
    """A timestamped audit event produced during a simulation."""

    time: float
    event_type: str
    vehicle_id: Optional[str] = None
    request_ids: List[str] = field(default_factory=list)
    node_id: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SimulationResult:
    """Raw state returned by a simulator for common metric calculation."""

    system_type: str
    requests: List[PassengerRequest]
    vehicles: List[Vehicle]
    events: List[SimulationEvent]
    duration_minutes: float

