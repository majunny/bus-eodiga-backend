"""Tests for configurable DRT departure rules."""

from algorithms.departure_policy import DeparturePolicy
from config import SimulationConfig
from models import PassengerRequest, Vehicle


def _request(request_id, requested_at=0.0, passengers=1, destination="hospital"):
    """Build a compact waiting-request fixture."""

    return PassengerRequest(request_id, "stop_a", destination, requested_at,
                            passenger_count=passengers, maximum_wait_time=10.0)


def test_depart_at_maximum_wait_time():
    """One urgent rider triggers departure regardless of group size."""

    policy = DeparturePolicy(SimulationConfig())
    decision = policy.decide([_request("r1")], Vehicle("v1", "depot", 6), 10.0)
    assert decision.should_depart
    assert decision.reason == "MAX_WAIT_TIME_REACHED"


def test_depart_at_minimum_passenger_count():
    """Enough passengers trigger the configured minimum rule."""

    config = SimulationConfig(same_destination_threshold=99)
    policy = DeparturePolicy(config)
    waiting = [_request("r1", passengers=2),
               _request("r2", destination="market")]
    decision = policy.decide(waiting, Vehicle("v1", "depot", 6), 1.0)
    assert decision.should_depart
    assert decision.reason == "MINIMUM_PASSENGERS_REACHED"

