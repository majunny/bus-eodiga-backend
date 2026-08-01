"""Tests for the replaceable route-provider boundary."""

import json

import networkx as nx
import pytest

from map.route_provider import RouteProvider
from map.virtual_map import VirtualMap, default_map_data


def test_shortest_path_between_existing_nodes(tmp_path):
    """Existing connected nodes have a finite routed path."""

    path = tmp_path / "map.json"
    path.write_text(json.dumps(default_map_data()), encoding="utf-8")
    provider = RouteProvider(VirtualMap(path))
    route = provider.get_shortest_path("stop_a", "hospital")
    assert route[0] == "stop_a"
    assert route[-1] == "hospital"
    assert provider.get_distance("stop_a", "hospital") > 0
    assert provider.get_travel_time("stop_a", "hospital") > 0


def test_unconnected_nodes_raise_no_path(tmp_path):
    """A known but disconnected node produces NetworkXNoPath."""

    data = default_map_data()
    data["nodes"].append({
        "node_id": "island", "name": "고립 지점", "x": 20, "y": 20,
        "node_type": "INTERSECTION", "passenger_demand_weight": 0,
    })
    path = tmp_path / "map.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    provider = RouteProvider(VirtualMap(path))
    with pytest.raises(nx.NetworkXNoPath):
        provider.get_shortest_path("depot", "island")

