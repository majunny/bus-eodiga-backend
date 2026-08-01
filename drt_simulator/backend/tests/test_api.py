"""호출 API의 인증·중복·소유권·상태 테스트."""

from fastapi.testclient import TestClient

from backend.config import BackendSettings
from backend.main import create_app
from backend.models import FindNearestRouteRequest, FindNearestRouteResponse
from backend.repository import MemoryRideRepository
from backend.routing import RoutingServiceError


class StubRoutingService:
    """외부 네트워크 없이 Android 경로 계약을 검증하는 테스트 대역."""

    def find_nearest(self, request: FindNearestRouteRequest) -> FindNearestRouteResponse:
        destination = request.hospitals[0]
        return FindNearestRouteResponse(
            nearest_hospital=destination,
            distance_m=12_345.6,
            map_url="https://www.openstreetmap.org/directions?demo=1",
            route_coords=[
                [request.start_lat, request.start_lon],
                [destination.lat, destination.lon],
            ],
        )


class FailingRoutingService:
    """외부 라우팅 장애 응답을 검증하는 테스트 대역."""

    def find_nearest(self, request: FindNearestRouteRequest) -> FindNearestRouteResponse:
        raise RoutingServiceError("경로를 계산할 수 없습니다.")


def make_client(routing_service: object | None = None) -> TestClient:
    """개발 인증이 활성화된 격리 테스트 클라이언트를 생성한다."""

    settings = BackendSettings(
        allow_dev_auth=True,
        dev_auth_token="test-token",
        store_backend="memory",
    )
    return TestClient(
        create_app(
            settings=settings,
            repository=MemoryRideRepository(),
            routing_service=routing_service or StubRoutingService(),
        )
    )


def request_payload() -> dict:
    """유효한 울산역-울산대학교병원 호출을 반환한다."""

    return {
        "source": "ANDROID_APP",
        "pickup": {
            "place_id": "ulsan-station",
            "name": "울산역",
            "location": {"latitude": 35.5514, "longitude": 129.1387},
        },
        "destination": {
            "place_id": "uh-hospital",
            "name": "울산대학교병원",
            "location": {"latitude": 35.5202, "longitude": 129.4284},
        },
        "passenger_count": 1,
        "mobility_support": "SENIOR",
    }


def test_health_is_public() -> None:
    """Render 상태 확인은 인증 없이 성공해야 한다."""

    response = make_client().get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def route_payload() -> dict:
    """Android OsmRouteClient와 동일한 경로 요청을 반환한다."""

    return {
        "start_lat": 35.5514,
        "start_lon": 129.1387,
        "hospitals": [
            {"name": "울산대학교병원", "lat": 35.5202, "lon": 129.4284},
        ],
        "network_type": "drive",
        "buffer_m": 1200,
    }


def test_find_nearest_route_matches_android_contract() -> None:
    """경로 API는 인증 없이 Android DTO 형식으로 응답해야 한다."""

    response = make_client().post("/api/find_nearest", json=route_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["nearest_hospital"]["name"] == "울산대학교병원"
    assert body["distance_m"] == 12_345.6
    assert body["route_coords"][0] == [35.5514, 129.1387]


def test_find_nearest_route_validates_request() -> None:
    """목적지 후보가 없는 요청은 라우팅 서버를 호출하기 전에 거부한다."""

    payload = route_payload()
    payload["hospitals"] = []
    response = make_client().post("/api/find_nearest", json=payload)
    assert response.status_code == 422


def test_find_nearest_route_reports_upstream_failure() -> None:
    """OSM 라우팅 장애는 명확한 502 응답으로 변환해야 한다."""

    response = make_client(FailingRoutingService()).post("/api/find_nearest", json=route_payload())
    assert response.status_code == 502
    assert response.json()["detail"] == "경로를 계산할 수 없습니다."


def test_bus_stop_search_and_nearby_are_public() -> None:
    """Android는 인증 없이 정류장 이름과 현재 위치 주변을 조회할 수 있다."""

    client = make_client()
    search = client.get("/v1/bus-stops", params={"query": "태화강역", "limit": 10})
    assert search.status_code == 200
    assert search.json()
    assert all("태화강역" in stop["name"] for stop in search.json())

    nearby = client.get(
        "/v1/bus-stops/nearby",
        params={"latitude": 35.53937, "longitude": 129.35194, "radius_m": 1000},
    )
    assert nearby.status_code == 200
    assert nearby.json()[0]["distance_m"] == 0.0


def test_authentication_is_required() -> None:
    """호출 생성에는 Bearer 토큰이 필요하다."""

    response = make_client().post(
        "/v1/ride-requests",
        headers={"Idempotency-Key": "request-key-0001"},
        json=request_payload(),
    )
    assert response.status_code == 401


def test_idempotent_create_and_cancel() -> None:
    """같은 키는 한 호출만 만들고 WAITING 호출은 취소할 수 있다."""

    client = make_client()
    headers = {
        "Authorization": "Bearer test-token",
        "Idempotency-Key": "request-key-0001",
    }
    first = client.post("/v1/ride-requests", headers=headers, json=request_payload())
    second = client.post("/v1/ride-requests", headers=headers, json=request_payload())
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["request_id"] == second.json()["request_id"]
    assert first.json()["status"] == "WAITING"

    request_id = first.json()["request_id"]
    cancelled = client.post(
        "/v1/ride-requests/{}/cancel".format(request_id),
        headers={"Authorization": "Bearer test-token"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
