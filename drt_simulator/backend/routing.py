"""OpenStreetMap 기반 도로 경로 계산 서비스."""

from typing import Protocol
from urllib.parse import urlencode

import httpx

from backend.models import (
    FindNearestRouteRequest,
    FindNearestRouteResponse,
    RoutePlace,
)


class RoutingServiceError(RuntimeError):
    """외부 라우팅 서비스가 정상 결과를 제공하지 못한 경우."""


class RoutingService(Protocol):
    """FastAPI에서 주입받는 경로 계산 계약."""

    def find_nearest(self, request: FindNearestRouteRequest) -> FindNearestRouteResponse:
        """도로 거리상 가장 가까운 후보와 전체 경로를 반환한다."""


class OsrmRoutingService:
    """OSM 데이터를 사용하는 OSRM HTTP API 클라이언트."""

    def __init__(self, base_url: str, timeout_seconds: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def find_nearest(self, request: FindNearestRouteRequest) -> FindNearestRouteResponse:
        """후보별 도로 경로를 조회해 최단 거리 결과를 Android 형식으로 변환한다."""

        results: list[FindNearestRouteResponse] = []
        for destination in request.hospitals:
            try:
                results.append(self._route(request.start_lat, request.start_lon, destination))
            except RoutingServiceError:
                continue

        if not results:
            raise RoutingServiceError("요청한 목적지까지 계산 가능한 도로 경로가 없습니다.")
        return min(results, key=lambda result: result.distance_m)

    def _route(self, start_lat: float, start_lon: float, destination: RoutePlace) -> FindNearestRouteResponse:
        coordinates = f"{start_lon},{start_lat};{destination.lon},{destination.lat}"
        url = f"{self.base_url}/route/v1/driving/{coordinates}"
        try:
            response = httpx.get(
                url,
                params={"overview": "full", "geometries": "geojson", "steps": "false"},
                headers={"User-Agent": "bus-eodiga-hackathon/0.1"},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise RoutingServiceError("OSM 라우팅 서버에 연결하지 못했습니다.") from error

        routes = payload.get("routes", []) if payload.get("code") == "Ok" else []
        if not routes:
            raise RoutingServiceError("목적지까지 연결된 도로 경로가 없습니다.")

        route = routes[0]
        geometry = route.get("geometry", {})
        coordinates = geometry.get("coordinates", [])
        if not coordinates:
            raise RoutingServiceError("도로 경로 좌표가 비어 있습니다.")

        # OSRM GeoJSON은 [경도, 위도]이며 Android 지도에서 쓰기 쉽게 [위도, 경도]로 변환한다.
        route_coords = [[float(lat), float(lon)] for lon, lat in coordinates]
        map_query = urlencode(
            {
                "engine": "fossgis_osrm_car",
                "route": f"{start_lat},{start_lon};{destination.lat},{destination.lon}",
            }
        )
        return FindNearestRouteResponse(
            nearest_hospital=destination,
            distance_m=float(route["distance"]),
            map_url=f"https://www.openstreetmap.org/directions?{map_query}",
            route_coords=route_coords,
        )
