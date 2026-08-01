"""JSON-backed directed virtual road network."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import networkx as nx

from map.base_map import BaseMap


class VirtualMap(BaseMap):
    """Route on an editable JSON road graph using NetworkX internally."""

    def __init__(self, json_path: Path) -> None:
        """Load the graph, writing a default map if the file is missing."""

        self.json_path = Path(json_path)
        if not self.json_path.exists():
            self.create_default_json(self.json_path)
        self.graph = nx.DiGraph()
        self._load()

    def _load(self) -> None:
        """Load nodes and permitted directed road segments from JSON."""

        with self.json_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
        for node in payload["nodes"]:
            node_data = dict(node)
            node_id = node_data.pop("node_id")
            self.graph.add_node(node_id, **node_data)
        for road in payload["roads"]:
            road_data = dict(road)
            start = road_data.pop("start")
            end = road_data.pop("end")
            if not road_data.get("is_open", True):
                continue
            self._add_road(start, end, road_data)
            if not road_data.get("one_way", False):
                self._add_road(end, start, road_data)

    def _add_road(self, start: str, end: str, road: Dict[str, Any]) -> None:
        """Add one directed road with calculated travel time."""

        distance = float(road["distance_km"])
        speed = float(road["speed_limit_kmh"])
        congestion = float(road.get("congestion_factor", 1.0))
        if distance < 0 or speed <= 0 or congestion <= 0:
            raise ValueError("Road distance, speed, and congestion must be valid")
        travel_time = distance / speed * 60.0 * congestion
        self.graph.add_edge(
            start,
            end,
            distance_km=distance,
            speed_limit_kmh=speed,
            congestion_factor=congestion,
            travel_time_minutes=travel_time,
            one_way=bool(road.get("one_way", False)),
            is_open=True,
        )

    def _validate_nodes(self, start: str, end: str) -> None:
        """Raise a clear error when either endpoint is unknown."""

        missing = [node for node in (start, end) if node not in self.graph]
        if missing:
            raise KeyError("Unknown map node(s): {}".format(", ".join(missing)))

    def get_distance(self, start: str, end: str) -> float:
        """Return distance along the fastest path in kilometres."""

        path = self.get_shortest_path(start, end)
        return sum(
            float(self.graph.edges[a, b]["distance_km"])
            for a, b in zip(path, path[1:])
        )

    def get_travel_time(self, start: str, end: str) -> float:
        """Return shortest travel time in minutes."""

        self._validate_nodes(start, end)
        return float(nx.shortest_path_length(
            self.graph, start, end, weight="travel_time_minutes"
        ))

    def get_shortest_path(self, start: str, end: str) -> List[str]:
        """Return the fastest available path or raise NetworkXNoPath."""

        self._validate_nodes(start, end)
        return list(nx.shortest_path(
            self.graph, start, end, weight="travel_time_minutes"
        ))

    def get_node(self, node_id: str) -> Dict[str, Any]:
        """Return node attributes with its identifier."""

        if node_id not in self.graph:
            raise KeyError("Unknown map node: {}".format(node_id))
        result = dict(self.graph.nodes[node_id])
        result["node_id"] = node_id
        return result

    def get_all_locations(self) -> List[Dict[str, Any]]:
        """Return all nodes with identifiers in insertion order."""

        return [self.get_node(node_id) for node_id in self.graph.nodes]

    def get_road_segments(self) -> List[Dict[str, Any]]:
        """Return copies of all currently drivable directed segments."""

        segments = []
        for start, end, attributes in self.graph.edges(data=True):
            segment = dict(attributes)
            segment.update({"start": start, "end": end})
            segments.append(segment)
        return segments

    @staticmethod
    def create_default_json(path: Path) -> None:
        """Create the bundled rural-town example map at the requested path."""

        path.parent.mkdir(parents=True, exist_ok=True)
        payload = default_map_data()
        with path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)


def default_map_data() -> Dict[str, Any]:
    """Return an editable example with six places and ten intersections."""

    nodes = [
        ("depot", "차고지", 0.5, 1.0, "DEPOT", 0.0),
        ("stop_a", "스마트 정류장 A", 2.0, 2.0, "SMART_STOP", 1.2),
        ("stop_b", "스마트 정류장 B", 8.0, 2.0, "SMART_STOP", 1.0),
        ("hospital", "병원", 8.5, 7.5, "DESTINATION", 1.8),
        ("market", "시장", 5.5, 5.0, "DESTINATION", 1.0),
        ("welfare_center", "복지관", 2.0, 7.5, "DESTINATION", 1.5),
        ("community_center", "행정복지센터", 5.0, 8.7, "DESTINATION", 0.7),
        ("j1", "교차로 1", 1.5, 1.0, "INTERSECTION", 0.0),
        ("j2", "교차로 2", 3.3, 2.0, "INTERSECTION", 0.0),
        ("j3", "교차로 3", 5.2, 2.0, "INTERSECTION", 0.0),
        ("j4", "교차로 4", 7.0, 2.0, "INTERSECTION", 0.0),
        ("j5", "교차로 5", 3.3, 4.5, "INTERSECTION", 0.0),
        ("j6", "교차로 6", 7.0, 4.5, "INTERSECTION", 0.0),
        ("j7", "교차로 7", 3.3, 7.0, "INTERSECTION", 0.0),
        ("j8", "교차로 8", 7.0, 7.0, "INTERSECTION", 0.0),
        ("j9", "교차로 9", 5.2, 7.0, "INTERSECTION", 0.0),
        ("j10", "교차로 10", 5.2, 4.5, "INTERSECTION", 0.0),
    ]
    node_dicts = [
        {"node_id": item[0], "name": item[1], "x": item[2], "y": item[3],
         "node_type": item[4], "passenger_demand_weight": item[5]}
        for item in nodes
    ]
    road_specs = [
        ("depot", "j1", 0.8), ("j1", "stop_a", 0.9),
        ("stop_a", "j2", 1.0), ("j2", "j3", 1.4),
        ("j3", "j4", 1.3), ("j4", "stop_b", 0.8),
        ("j2", "j5", 1.7), ("j5", "j7", 1.8),
        ("j7", "welfare_center", 1.0), ("j7", "j9", 1.4),
        ("j9", "community_center", 1.2), ("j9", "j8", 1.3),
        ("j8", "hospital", 1.0), ("stop_b", "j6", 1.7),
        ("j6", "j8", 1.8), ("j5", "j10", 1.3),
        ("j10", "j6", 1.3), ("j10", "market", 0.7),
        ("j3", "j10", 1.7), ("market", "j9", 1.5),
        ("j1", "j5", 2.3), ("j6", "hospital", 2.1),
    ]
    roads = []
    for index, (start, end, distance) in enumerate(road_specs):
        roads.append({
            "start": start,
            "end": end,
            "distance_km": distance,
            "speed_limit_kmh": 35 if index % 4 else 25,
            "congestion_factor": 1.0 + (index % 3) * 0.1,
            "one_way": False,
            "is_open": True,
        })
    return {"units": {"distance": "km", "time": "minutes"},
            "nodes": node_dicts, "roads": roads}
