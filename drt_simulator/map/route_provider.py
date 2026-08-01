"""Stable routing facade consumed by scheduling and simulation code."""

from typing import Any, Dict, List

from map.base_map import BaseMap


class RouteProvider:
    """Delegate routing calls to a replaceable map backend."""

    def __init__(self, backend: BaseMap) -> None:
        """Create a provider backed by a virtual or future OSM map."""

        self.backend = backend

    def get_distance(self, start: str, end: str) -> float:
        """Return shortest drivable distance in kilometres."""

        return self.backend.get_distance(start, end)

    def get_travel_time(self, start: str, end: str) -> float:
        """Return shortest expected travel time in minutes."""

        return self.backend.get_travel_time(start, end)

    def get_shortest_path(self, start: str, end: str) -> List[str]:
        """Return the fastest path between two nodes."""

        return self.backend.get_shortest_path(start, end)

    def get_node(self, node_id: str) -> Dict[str, Any]:
        """Return node attributes."""

        return self.backend.get_node(node_id)

    def get_all_locations(self) -> List[Dict[str, Any]]:
        """Return all locations."""

        return self.backend.get_all_locations()

    def get_road_segments(self) -> List[Dict[str, Any]]:
        """Return road segments without exposing the backend graph object."""

        return self.backend.get_road_segments()
