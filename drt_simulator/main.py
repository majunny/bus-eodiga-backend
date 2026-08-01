"""Command-line entry point for demos and paired comparison experiments."""

import argparse
from copy import deepcopy
from pathlib import Path
from typing import Sequence

import pandas as pd

from algorithms.route_optimizer import RouteOptimizer
from config import DEFAULT_MAP_PATH, DEFAULT_RESULTS_DIR, SimulationConfig
from map.route_provider import RouteProvider
from map.virtual_map import VirtualMap
from models import DemandScenario, OptimizerType, PassengerRequest
from simulation.drt_simulator import DRTSimulator
from simulation.experiment_runner import ExperimentRunner
from simulation.fixed_route_simulator import FixedRouteSimulator
from simulation.metrics import MetricsCalculator
from simulation.passenger_generator import PassengerGenerator
from visualization.map_visualizer import MapVisualizer


def parse_args() -> argparse.Namespace:
    """Parse documented command-line modes and settings."""

    parser = argparse.ArgumentParser(description="하이브리드 DRT 교통 시뮬레이터")
    parser.add_argument("--mode", choices=["demo", "compare"], default="demo")
    parser.add_argument("--runs", type=int, default=100)
    parser.add_argument(
        "--scenario",
        choices=[item.value.lower() for item in DemandScenario],
        default=DemandScenario.NORMAL_DEMAND.value.lower(),
    )
    parser.add_argument("--optimizer", choices=["brute_force", "greedy"],
                        default="greedy")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--duration", type=int, default=120)
    return parser.parse_args()


def create_context(args: argparse.Namespace) -> tuple:
    """Create central configuration and route provider from CLI values."""

    config = SimulationConfig(
        random_seed=args.seed,
        simulation_duration_minutes=args.duration,
        optimizer=args.optimizer.upper(),
    )
    routes = RouteProvider(VirtualMap(DEFAULT_MAP_PATH))
    return config, routes


def demo(config: SimulationConfig, routes: RouteProvider,
         scenario: DemandScenario, optimizer: OptimizerType) -> None:
    """Run both systems once and save a map, metrics CSV, and comparison image."""

    generator = PassengerGenerator(routes, config)
    requests = generator.generate(config.simulation_duration_minutes,
                                  scenario, seed=config.random_seed)
    drt_result = DRTSimulator(routes, config).run(deepcopy(requests), optimizer)
    fixed_result = FixedRouteSimulator(routes, config).run(deepcopy(requests))
    calculator = MetricsCalculator(config)
    rows = []
    for system_type, result in (("FIXED_ROUTE", fixed_result), ("DRT", drt_result)):
        row = {"system_type": system_type, "seed": config.random_seed,
               "scenario": scenario.value}
        row.update(calculator.calculate(result))
        rows.append(row)
    frame = pd.DataFrame(rows)
    DEFAULT_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = DEFAULT_RESULTS_DIR / "demo_results.csv"
    frame.to_csv(csv_path, index=False)
    visualizer = MapVisualizer(routes)
    map_path = visualizer.plot_map(
        DEFAULT_RESULTS_DIR / "demo_map.png", drt_result.vehicles[0],
        drt_result.requests, drt_result.vehicles[0].route,
    )
    chart_path = visualizer.plot_comparison(
        frame, DEFAULT_RESULTS_DIR / "demo_comparison.png"
    )
    _print_optimizer_example(routes, config, requests, optimizer)
    display = frame[["system_type", "completed_passengers", "average_wait_time",
                     "total_distance", "empty_distance", "operation_cost"]].copy()
    display["system_type"] = display["system_type"].map({
        "FIXED_ROUTE": "기존 고정노선", "DRT": "수요응답형 DRT"
    })
    display.columns = ["시스템", "완료 승객", "평균 대기시간", "총 운행거리",
                       "공차 운행거리", "예상 운행비용"]
    print(display.to_string(index=False))
    print("저장 완료: {}, {}, {}".format(csv_path, map_path, chart_path))


def _print_optimizer_example(routes: RouteProvider, config: SimulationConfig,
                             requests: Sequence[PassengerRequest],
                             selected: OptimizerType) -> None:
    """Print selected optimizer cost/time and a small exact-vs-greedy comparison."""

    sample: Sequence[PassengerRequest] = requests[:3]
    if not sample:
        print("경로 최적화 비교 생략: 생성된 요청이 없습니다.")
        return
    from models import Vehicle
    optimizer = RouteOptimizer(routes, config)
    plans = optimizer.compare_optimizers(
        Vehicle("COMPARE", "depot", config.vehicle_capacity), sample, 0.0
    )
    optimizer_labels = {"BRUTE_FORCE": "완전탐색", "GREEDY": "탐욕법"}
    print("경로 최적화 비교 (선택 방식={}):".format(
        optimizer_labels[selected.value]
    ))
    for name, plan in plans.items():
        print("  {} 비용={:.2f}, 이동시간={:.2f}분, 계산시간={:.3f}ms".format(
            optimizer_labels[name], plan.total_cost, plan.total_travel_time,
            plan.computation_time_ms,
        ))


def compare(config: SimulationConfig, routes: RouteProvider, runs: int,
            scenario: DemandScenario, optimizer: OptimizerType) -> None:
    """Run repeated paired experiments and save raw, summary, and chart outputs."""

    runner = ExperimentRunner(routes, config)
    frame = runner.run(runs, scenario, optimizer)
    summary = runner.summarize(frame)
    summary_path = DEFAULT_RESULTS_DIR / "summary_{}_{}_runs.csv".format(
        scenario.value.lower(), runs
    )
    summary.to_csv(summary_path)
    chart_path = MapVisualizer.plot_comparison(
        frame, DEFAULT_RESULTS_DIR / "comparison_{}_{}_runs.png".format(
            scenario.value.lower(), runs
        ),
    )
    display = frame.groupby("system_type")[[
        "completed_passengers", "missed_passengers", "average_wait_time",
        "total_distance", "empty_distance", "average_occupancy",
        "operation_cost",
    ]].mean()
    display = display.rename(
        index={"FIXED_ROUTE": "기존 고정노선", "DRT": "수요응답형 DRT"},
        columns={
            "completed_passengers": "완료 승객",
            "missed_passengers": "미수송 승객",
            "average_wait_time": "평균 대기시간",
            "total_distance": "총 운행거리",
            "empty_distance": "공차 운행거리",
            "average_occupancy": "평균 탑승률",
            "operation_cost": "예상 운행비용",
        },
    )
    print(display.to_string())
    print("요약 CSV 저장 완료: {}".format(summary_path))
    print("비교 그래프 저장 완료: {}".format(chart_path))


def main() -> None:
    """Dispatch the requested CLI mode."""

    args = parse_args()
    config, routes = create_context(args)
    scenario = DemandScenario(args.scenario.upper())
    optimizer = OptimizerType(args.optimizer.upper())
    if args.mode == "demo":
        demo(config, routes, scenario, optimizer)
    else:
        compare(config, routes, args.runs, scenario, optimizer)


if __name__ == "__main__":
    main()
