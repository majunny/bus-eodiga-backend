"""MODI 백엔드 브리지의 미니맵 경로 계산 테스트."""

import pytest

from hardware.modi_backend_bridge import shortest_path
from hardware.generate_six_stop_model import build_model


def sample_map() -> dict:
    return {
        "nodes": {
            "depot": {"x": 0, "y": 0},
            "j1": {"x": 1, "y": 0},
            "stop_a": {"x": 2, "y": 0},
        },
        "roads": [
            {"start": "depot", "end": "j1", "distance": 1.0, "one_way": False},
            {"start": "j1", "end": "stop_a", "distance": 1.0, "one_way": False},
            {"start": "depot", "end": "stop_a", "distance": 5.0, "one_way": False},
        ],
    }


def test_shortest_path_uses_mini_map_roads() -> None:
    assert shortest_path(sample_map(), "depot", "stop_a") == ["depot", "j1", "stop_a"]


def test_shortest_path_rejects_unknown_mapping_node() -> None:
    with pytest.raises(KeyError, match="미니맵 노드"):
        shortest_path(sample_map(), "depot", "missing")


def test_six_osm_stops_create_thirty_directed_combinations() -> None:
    model, mapping, combinations = build_model(120.0, 80.0)

    assert len(model["nodes"]) == 6
    assert len(model["roads"]) == 15
    assert len(mapping["place_to_node"]) == 6
    assert len(combinations) == 30
    assert mapping["start_node"] == "stop_1"
    assert mapping["start_place_id"] == "31208"
    assert all(item["vehicle_start_place_id"] == "31208" for item in combinations)
    assert all(item["pickup_place_id"] != item["destination_place_id"] for item in combinations)
