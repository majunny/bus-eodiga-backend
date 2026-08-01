"""Render 공동 DRT 운행을 MODI+ 미니 자동차로 실행합니다.

안전한 연결 확인(모터 미구동):
    python -m hardware.modi_backend_bridge --dry-run

실제 BLE 차량 구동:
    python -m hardware.modi_backend_bridge \
        --hardware \
        --controller-module modi_car_v4 \
        --route-map mini_route_map.json \
        --stop-mapping hardware/modi_stop_mapping.json
"""

from __future__ import annotations

import argparse
import heapq
import importlib
import json
import os
import signal
import time
from pathlib import Path
from typing import Any, Protocol

import httpx


DEFAULT_API_URL = "https://bus-eodiga-api.onrender.com"


class VehicleApiClient:
    """MODI 차량 전용 Render API 클라이언트."""

    def __init__(self, base_url: str, vehicle_id: str, api_key: str) -> None:
        self.vehicle_id = vehicle_id
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"X-Vehicle-Key": api_key},
            timeout=20.0,
        )

    def poll_trip(self) -> dict[str, Any] | None:
        response = self._client.get(f"/v1/vehicles/{self.vehicle_id}/trips/next")
        response.raise_for_status()
        return response.json().get("trip")

    def claim_trip(self, trip_id: str) -> dict[str, Any]:
        response = self._client.post(f"/v1/vehicles/{self.vehicle_id}/trips/{trip_id}/claim")
        response.raise_for_status()
        return response.json()

    def report_progress(self, trip_id: str, stop_index: int, phase: str) -> dict[str, Any]:
        response = self._client.post(
            f"/v1/vehicles/{self.vehicle_id}/trips/{trip_id}/progress",
            json={"stop_index": stop_index, "phase": phase},
        )
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self._client.close()


class RouteDriver(Protocol):
    """백엔드 경유지를 미니맵에서 주행하는 드라이버 계약."""

    def connect(self) -> None: ...

    def prepare_for_trip(self) -> None: ...

    def drive_to(self, place: dict[str, Any]) -> None: ...

    def emergency_stop(self) -> None: ...


class DryRunDriver:
    """BLE 없이 운행 순서와 API 연결만 확인합니다."""

    def connect(self) -> None:
        print("DRY-RUN 드라이버 준비: 모터는 움직이지 않습니다.")

    def drive_to(self, place: dict[str, Any]) -> None:
        print(f"  [DRY-RUN] 주행: {place['name']} ({place['place_id']})")
        time.sleep(0.3)

    def prepare_for_trip(self) -> None:
        print("  [DRY-RUN] 동부아파트입구 출발 위치 확인")

    def emergency_stop(self) -> None:
        print("  [DRY-RUN] 정지")


class ModiV4Driver:
    """친구가 제공한 V4 함수들을 사용해 미니맵 노드 사이를 주행합니다."""

    def __init__(
        self,
        controller_module: str,
        route_map_path: Path,
        stop_mapping_path: Path,
    ) -> None:
        self.controller = importlib.import_module(controller_module)
        self.car_route_v2 = self.controller.car_route_v2
        self.route_map = json.loads(route_map_path.read_text(encoding="utf-8"))
        mapping = json.loads(stop_mapping_path.read_text(encoding="utf-8"))
        self.place_to_node = dict(mapping.get("place_to_node") or {})
        self.name_to_node = dict(mapping.get("name_to_node") or {})
        self.start_node = str(mapping.get("start_node") or "stop_1")
        self.current_node = self.start_node
        self.left_motor = None
        self.right_motor = None

    def connect(self) -> None:
        self.controller.load_turn_calibration()
        bundle = self.controller.connect_ble_with_imu()

        # V4의 네 바퀴 함수가 car_route_v2의 기존 좌우 모터 함수를 대체합니다.
        self.car_route_v2.set_motor_speeds = self.controller.set_four_wheel_speeds
        self.car_route_v2.stop_motors = self.controller.stop_four_wheels
        self.car_route_v2.follow_path = self.controller.follow_path_by_real_heading
        self.left_motor = bundle.motors[0]
        self.right_motor = bundle.motors[1]
        print(f"MODI 차량 준비 완료 · 시작 노드: {self.current_node}")

    def prepare_for_trip(self) -> None:
        """모든 운행을 동부아파트입구 고정 출발점에서 시작합니다."""
        if self.current_node == self.start_node:
            print("  고정 출발지 확인: 동부아파트입구")
            return
        print(f"  다음 운행 준비: {self.current_node} → 동부아파트입구({self.start_node}) 복귀")
        path = shortest_path(self.route_map, self.current_node, self.start_node)
        self.controller.follow_path_by_real_heading(
            self.left_motor,
            self.right_motor,
            self.route_map,
            path,
            self.controller.current_real_heading(),
        )
        self.current_node = self.start_node

    def drive_to(self, place: dict[str, Any]) -> None:
        target_node = self.place_to_node.get(str(place["place_id"])) or self.name_to_node.get(str(place["name"]))
        if not target_node:
            raise KeyError(
                f"'{place['name']}'({place['place_id']})의 미니맵 노드 매핑이 없습니다. "
                "modi_stop_mapping.json을 확인하세요."
            )
        path = shortest_path(self.route_map, self.current_node, str(target_node))
        print(f"  미니맵 경로: {' → '.join(path)}")
        self.controller.follow_path_by_real_heading(
            self.left_motor,
            self.right_motor,
            self.route_map,
            path,
            self.controller.current_real_heading(),
        )
        self.current_node = str(target_node)

    def emergency_stop(self) -> None:
        if self.left_motor is not None and self.right_motor is not None:
            self.controller.stop_four_wheels(self.left_motor, self.right_motor)


def shortest_path(route_map: dict[str, Any], start: str, end: str) -> list[str]:
    """친구의 미니맵 JSON에서 거리 기준 최단 노드 경로를 계산합니다."""

    nodes = route_map.get("nodes") or {}
    if start not in nodes or end not in nodes:
        raise KeyError(f"미니맵 노드가 없습니다: {start} 또는 {end}")

    graph: dict[str, list[tuple[str, float]]] = {str(node_id): [] for node_id in nodes}
    roads = route_map.get("roads") or route_map.get("edges") or []
    for road in roads:
        road_start = str(road["start"])
        road_end = str(road["end"])
        distance = float(road.get("distance") or road.get("distance_km") or 1.0)
        graph.setdefault(road_start, []).append((road_end, distance))
        if not road.get("one_way", False):
            graph.setdefault(road_end, []).append((road_start, distance))

    queue: list[tuple[float, str, list[str]]] = [(0.0, start, [start])]
    best = {start: 0.0}
    while queue:
        distance, node, path = heapq.heappop(queue)
        if node == end:
            return path
        if distance > best.get(node, float("inf")):
            continue
        for neighbour, road_distance in graph.get(node, []):
            candidate = distance + road_distance
            if candidate < best.get(neighbour, float("inf")):
                best[neighbour] = candidate
                heapq.heappush(queue, (candidate, neighbour, path + [neighbour]))
    raise RuntimeError(f"미니맵에서 연결되지 않은 노드입니다: {start} → {end}")


def execute_trip(
    client: VehicleApiClient,
    driver: RouteDriver,
    trip: dict[str, Any],
    dwell_seconds: float,
) -> None:
    """운행 경유지를 순서대로 주행하고 서버·Android 상태를 갱신합니다."""

    trip_id = str(trip["trip_id"])
    driver.prepare_for_trip()
    claimed = client.claim_trip(trip_id)
    steps = list(claimed.get("route_steps") or [])
    print(f"운행 선점 완료: {trip_id} · 경유지 {len(steps)}곳")

    for stop_index, step in enumerate(steps):
        place = dict(step["place"])
        stop_type = str(step["type"])
        print(f"[{stop_index + 1}/{len(steps)}] {stop_type} · {place['name']}")
        client.report_progress(trip_id, stop_index, "EN_ROUTE")
        driver.drive_to(place)
        client.report_progress(trip_id, stop_index, "ARRIVED")
        time.sleep(dwell_seconds)
        completed_phase = "BOARDED" if stop_type == "PICKUP" else "DROPPED_OFF"
        client.report_progress(trip_id, stop_index, completed_phase)

    if steps:
        client.report_progress(trip_id, len(steps) - 1, "COMPLETED")
    print(f"공동 DRT 운행 완료: {trip_id}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render DRT 운행을 MODI+ 자동차와 연결합니다.")
    parser.add_argument("--api-url", default=os.getenv("BUS_EODIGA_API_URL", DEFAULT_API_URL))
    parser.add_argument("--vehicle-id", default=os.getenv("BUS_EODIGA_VEHICLE_ID", "modi-bus-01"))
    parser.add_argument("--api-key", default=os.getenv("BUS_EODIGA_VEHICLE_KEY", ""))
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--dwell-seconds", type=float, default=2.0)
    parser.add_argument("--dry-run", action="store_true", help="모터 없이 API 연결만 확인합니다.")
    parser.add_argument("--hardware", action="store_true", help="실제 MODI BLE 모터를 구동합니다.")
    parser.add_argument("--controller-module", default="hardware.modi_car_v4")
    parser.add_argument("--route-map", type=Path)
    parser.add_argument("--stop-mapping", type=Path)
    parser.add_argument("--once", action="store_true", help="운행 하나를 완료한 뒤 종료합니다.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.api_key:
        raise SystemExit("BUS_EODIGA_VEHICLE_KEY 또는 --api-key가 필요합니다.")
    if args.hardware == args.dry_run:
        raise SystemExit("안전을 위해 --dry-run 또는 --hardware 중 하나만 지정하세요.")
    if args.hardware and (args.route_map is None or args.stop_mapping is None):
        raise SystemExit("--hardware에는 --route-map과 --stop-mapping이 필요합니다.")

    driver: RouteDriver = (
        ModiV4Driver(args.controller_module, args.route_map, args.stop_mapping)
        if args.hardware
        else DryRunDriver()
    )
    client = VehicleApiClient(args.api_url, args.vehicle_id, args.api_key)
    stopping = False

    def request_stop(_signal_number: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True
        driver.emergency_stop()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    try:
        driver.connect()
        print(f"Render 운행 대기 중: {args.api_url} · 차량 {args.vehicle_id}")
        while not stopping:
            trip = client.poll_trip()
            if trip is None:
                time.sleep(args.poll_seconds)
                continue
            execute_trip(client, driver, trip, args.dwell_seconds)
            if args.once:
                break
    except Exception:
        driver.emergency_stop()
        raise
    finally:
        driver.emergency_stop()
        client.close()


if __name__ == "__main__":
    main()
