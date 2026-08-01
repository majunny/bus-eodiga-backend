"""Repeatable paired experiments comparing fixed-route and DRT systems."""

from copy import deepcopy
from pathlib import Path
from typing import List, Sequence, Tuple

import pandas as pd

from config import DEFAULT_RESULTS_DIR, SimulationConfig
from map.route_provider import RouteProvider
from models import DemandScenario, OptimizerType, PassengerRequest
from simulation.drt_simulator import DRTSimulator
from simulation.fixed_route_simulator import FixedRouteSimulator
from simulation.metrics import MetricsCalculator
from simulation.passenger_generator import PassengerGenerator


def clone_requests_for_systems(
        requests: Sequence[PassengerRequest]) -> Tuple[List[PassengerRequest],
                                                       List[PassengerRequest]]:
    """Return independent but value-identical request lists for paired systems."""

    return deepcopy(list(requests)), deepcopy(list(requests))


class ExperimentRunner:
    """Run paired seeded trials, persist raw rows, and summarize distributions."""

    def __init__(self, routes: RouteProvider, config: SimulationConfig,
                 results_dir: Path = DEFAULT_RESULTS_DIR) -> None:
        """Create generators and simulators sharing one map and configuration."""

        self.routes = routes
        self.config = config
        self.results_dir = Path(results_dir)
        self.generator = PassengerGenerator(routes, config)
        self.metrics = MetricsCalculator(config)

    def run(self, runs: int = 100,
            scenario: DemandScenario = DemandScenario.NORMAL_DEMAND,
            optimizer: OptimizerType = OptimizerType.GREEDY,
            save_csv: bool = True) -> pd.DataFrame:
        """Run paired trials with recorded seeds and optionally save CSV output."""

        if runs <= 0:
            raise ValueError("runs must be positive")
        rows = []
        for experiment_id in range(1, runs + 1):
            seed = self.config.random_seed + experiment_id - 1
            originals = self.generator.generate(
                self.config.simulation_duration_minutes, scenario, seed=seed
            )
            fixed_requests, drt_requests = clone_requests_for_systems(originals)
            fixed_result = FixedRouteSimulator(self.routes, self.config).run(fixed_requests)
            drt_result = DRTSimulator(self.routes, self.config).run(drt_requests, optimizer)
            for system_type, result in (("FIXED_ROUTE", fixed_result), ("DRT", drt_result)):
                row = {
                    "experiment_id": experiment_id,
                    "seed": seed,
                    "scenario": scenario.value,
                    "system_type": system_type,
                }
                row.update(self.metrics.calculate(result))
                rows.append(row)
        frame = pd.DataFrame(rows)
        if save_csv:
            self.results_dir.mkdir(parents=True, exist_ok=True)
            path = self.results_dir / "comparison_{}_{}_runs.csv".format(
                scenario.value.lower(), runs
            )
            frame.to_csv(path, index=False)
        return frame

    @staticmethod
    def summarize(frame: pd.DataFrame) -> pd.DataFrame:
        """Calculate mean, median, and sample standard deviation by scenario/system."""

        numeric_columns = [
            column for column in frame.select_dtypes(include="number").columns
            if column not in ("experiment_id", "seed")
        ]
        return (frame.groupby(["scenario", "system_type"])[numeric_columns]
                .agg(["mean", "median", "std"]))

