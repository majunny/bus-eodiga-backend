"""OSM 정류장 6개를 미니모형 좌표와 30개 방향 조합으로 변환합니다."""

from __future__ import annotations

import argparse
import json
import math
from itertools import permutations
from pathlib import Path

from backend.modi_stops import MODI_BUS_STOPS as BUS_STOPS


def build_model(width_cm: float, height_cm: float, margin_cm: float = 8.0) -> tuple[dict, dict, list[dict]]:
    """위·경도 상대 배치를 지정한 모형 크기 안의 cm 좌표로 투영합니다."""

    if width_cm <= margin_cm * 2 or height_cm <= margin_cm * 2:
        raise ValueError("모형 크기는 양쪽 여백보다 커야 합니다.")

    center_latitude = sum(stop["latitude"] for stop in BUS_STOPS) / len(BUS_STOPS)
    latitude_scale = 110_540.0
    longitude_scale = 111_320.0 * math.cos(math.radians(center_latitude))
    projected = []
    for index, stop in enumerate(BUS_STOPS, start=1):
        projected.append(
            {
                **stop,
                "node_id": f"stop_{index}",
                "east_m": stop["longitude"] * longitude_scale,
                "north_m": stop["latitude"] * latitude_scale,
            }
        )

    min_east = min(stop["east_m"] for stop in projected)
    max_east = max(stop["east_m"] for stop in projected)
    min_north = min(stop["north_m"] for stop in projected)
    max_north = max(stop["north_m"] for stop in projected)
    east_range = max(max_east - min_east, 1.0)
    north_range = max(max_north - min_north, 1.0)
    usable_width = width_cm - margin_cm * 2
    usable_height = height_cm - margin_cm * 2
    scale = min(usable_width / east_range, usable_height / north_range)
    drawn_width = east_range * scale
    drawn_height = north_range * scale
    x_offset = (width_cm - drawn_width) / 2.0
    y_offset = (height_cm - drawn_height) / 2.0

    nodes = {}
    for stop in projected:
        x = x_offset + (stop["east_m"] - min_east) * scale
        # PNG/모형 좌표는 아래쪽으로 갈수록 y가 증가합니다.
        y = y_offset + (max_north - stop["north_m"]) * scale
        nodes[stop["node_id"]] = {
            "name": stop["name"],
            "x": round(x, 3),
            "y": round(y, 3),
            "place_id": stop["stop_id"],
            "latitude": stop["latitude"],
            "longitude": stop["longitude"],
        }

    roads = []
    for first_index in range(1, len(BUS_STOPS) + 1):
        for second_index in range(first_index + 1, len(BUS_STOPS) + 1):
            start = f"stop_{first_index}"
            end = f"stop_{second_index}"
            dx = nodes[end]["x"] - nodes[start]["x"]
            dy = nodes[end]["y"] - nodes[start]["y"]
            roads.append(
                {
                    "start": start,
                    "end": end,
                    "distance": round(math.hypot(dx, dy), 3),
                    "one_way": False,
                }
            )

    combinations = [
        {
            "vehicle_start_place_id": BUS_STOPS[0]["stop_id"],
            "vehicle_start_name": BUS_STOPS[0]["name"],
            "pickup_place_id": pickup["stop_id"],
            "pickup_name": pickup["name"],
            "destination_place_id": destination["stop_id"],
            "destination_name": destination["name"],
        }
        for pickup, destination in permutations(BUS_STOPS, 2)
    ]
    model = {
        "units": {"coordinates": "cm", "distance": "cm"},
        "board": {"width_cm": width_cm, "height_cm": height_cm, "margin_cm": margin_cm},
        "nodes": nodes,
        "roads": roads,
    }
    mapping = {
        "start_place_id": BUS_STOPS[0]["stop_id"],
        "start_name": BUS_STOPS[0]["name"],
        "start_node": "stop_1",
        "place_to_node": {
            stop["stop_id"]: f"stop_{index}"
            for index, stop in enumerate(BUS_STOPS, start=1)
        },
        "name_to_node": {
            stop["name"]: f"stop_{index}"
            for index, stop in enumerate(BUS_STOPS, start=1)
        },
    }
    return model, mapping, combinations


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="OSM 정류장 6개용 MODI 미니맵 파일을 생성합니다.")
    parser.add_argument("--width-cm", type=float, default=120.0)
    parser.add_argument("--height-cm", type=float, default=80.0)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()

    model, mapping, combinations = build_model(args.width_cm, args.height_cm)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.output_dir / "six_stop_mini_map.json", model)
    write_json(args.output_dir / "modi_stop_mapping.json", mapping)
    write_json(args.output_dir / "six_stop_combinations.json", combinations)
    print(f"6개 노드, 양방향 조합 {len(combinations)}개를 생성했습니다: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
