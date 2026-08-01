"""Map contract that keeps routing algorithms independent from map vendors."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class BaseMap(ABC):
    """Abstract route and location API implemented by virtual or OSM maps."""

    @abstractmethod
    def get_distance(self, start: str, end: str) -> float:
        """Return shortest drivable distance in kilometres."""

    @abstractmethod
    def get_travel_time(self, start: str, end: str) -> float:
        """Return shortest expected travel time in minutes."""

    @abstractmethod
    def get_shortest_path(self, start: str, end: str) -> List[str]:
        """Return node identifiers on the fastest path, including endpoints."""

    @abstractmethod
    def get_node(self, node_id: str) -> Dict[str, Any]:
        """Return a copy of the node attributes."""

    @abstractmethod
    def get_all_locations(self) -> List[Dict[str, Any]]:
        """Return copies of all nodes and their identifiers."""

    @abstractmethod
    def get_road_segments(self) -> List[Dict[str, Any]]:
        """Return directed road segments for presentation and diagnostics."""
