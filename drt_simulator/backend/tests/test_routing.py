"""OSRM 응답 변환과 최단 도로 경로 선택 테스트."""

import httpx

from backend.models import FindNearestRouteRequest
from backend.routing import OsrmRoutingService


def request_payload() -> FindNearestRouteRequest:
    return FindNearestRouteRequest.model_validate(
        {
            "start_lat": 35.5514,
            "start_lon": 129.1387,
            "hospitals": [
                {"name": "먼 병원", "lat": 35.5202, "lon": 129.4284},
                {"name": "가까운 병원", "lat": 35.5438, "lon": 129.2563},
            ],
        }
    )


def test_osrm_response_is_converted_and_shortest_route_is_selected(monkeypatch) -> None:
    """GeoJSON 좌표를 Android 순서로 바꾸고 도로 거리가 짧은 후보를 고른다."""

    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        is_near = "129.2563,35.5438" in url
        destination = [129.2563, 35.5438] if is_near else [129.4284, 35.5202]
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "code": "Ok",
                "routes": [
                    {
                        "distance": 8_000.0 if is_near else 30_000.0,
                        "geometry": {
                            "coordinates": [[129.1387, 35.5514], destination],
                        },
                    }
                ],
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    result = OsrmRoutingService("https://router.example.test").find_nearest(request_payload())

    assert result.nearest_hospital.name == "가까운 병원"
    assert result.distance_m == 8_000.0
    assert result.route_coords == [[35.5514, 129.1387], [35.5438, 129.2563]]
    assert result.map_url.startswith("https://www.openstreetmap.org/directions?")
