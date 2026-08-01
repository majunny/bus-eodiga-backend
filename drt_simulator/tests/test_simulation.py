"""Integration tests for generation, simulation fairness, and result persistence."""

from dataclasses import asdict

from config import DEFAULT_MAP_PATH, SimulationConfig
from map.route_provider import RouteProvider
from map.virtual_map import VirtualMap
from models import (DemandScenario, PassengerRequest, RequestStatus,
                    SimulationResult, Vehicle)
from simulation.experiment_runner import ExperimentRunner, clone_requests_for_systems
from simulation.metrics import MetricsCalculator
from simulation.passenger_generator import PassengerGenerator


def _routes():
    """Create a provider over the bundled test map."""

    return RouteProvider(VirtualMap(DEFAULT_MAP_PATH))


def test_same_seed_generates_same_requests():
    """Seeded generators produce byte-for-byte equivalent dataclass values."""

    config = SimulationConfig(simulation_duration_minutes=60)
    generator = PassengerGenerator(_routes(), config)
    first = generator.generate(60, DemandScenario.NORMAL_DEMAND, seed=123)
    second = generator.generate(60, DemandScenario.NORMAL_DEMAND, seed=123)
    assert [asdict(item) for item in first] == [asdict(item) for item in second]


def test_fixed_and_drt_receive_same_requests():
    """Paired systems receive equal inputs with independent mutable state."""

    originals = [PassengerRequest("r1", "stop_a", "hospital", 2.0)]
    fixed, drt = clone_requests_for_systems(originals)
    assert fixed == drt
    assert fixed[0] is not drt[0]


def test_completed_request_waiting_time():
    """Waiting time stops at pickup rather than completion."""

    request = PassengerRequest("r1", "stop_a", "hospital", 2.0)
    request.status = RequestStatus.COMPLETED
    request.picked_up_at = 7.0
    request.completed_at = 15.0
    result = SimulationResult("TEST", [request], [Vehicle("v1", "depot", 6)], [], 20)
    metrics = MetricsCalculator(SimulationConfig()).calculate(result)
    assert request.waiting_time() == 5.0
    assert metrics["average_wait_time"] == 5.0


def test_result_csv_is_created(tmp_path):
    """A one-run paired experiment writes both systems to CSV."""

    config = SimulationConfig(simulation_duration_minutes=15,
                              post_simulation_drain_minutes=30)
    runner = ExperimentRunner(_routes(), config, tmp_path)
    frame = runner.run(1, DemandScenario.LOW_DEMAND)
    files = list(tmp_path.glob("*.csv"))
    assert len(files) == 1
    assert set(frame["system_type"]) == {"FIXED_ROUTE", "DRT"}
    assert len(frame) == 2

