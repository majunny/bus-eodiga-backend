"""호출 API의 인증·중복·소유권·상태 테스트."""

from fastapi.testclient import TestClient

from backend.config import BackendSettings
from backend.main import create_app
from backend.models import (
    FindNearestRouteRequest,
    FindNearestRouteResponse,
    PlaceSearchResponse,
    RideRequestCreate,
    RideRequestRecord,
)
from backend.place_search import PlaceSearchError
from backend.repository import MemoryRideRepository
from backend.routing import RoutingServiceError
from backend.simulation import run_demo_trip_simulation


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


class StubPlaceSearchService:
    """외부 네트워크 없이 도착지 검색 계약을 검증하는 테스트 대역."""

    def search(self, query: str, limit: int) -> list[PlaceSearchResponse]:
        return [
            PlaceSearchResponse(
                place_id="osm-node-123",
                name=query,
                address="울산광역시 남구 대학로 93",
                latitude=35.5438,
                longitude=129.2564,
                category="AMENITY",
            )
        ][:limit]


class FailingPlaceSearchService:
    """외부 장소 검색 장애 응답을 검증하는 테스트 대역."""

    def search(self, query: str, limit: int) -> list[PlaceSearchResponse]:
        raise PlaceSearchError("울산 장소 검색 서버에 연결하지 못했습니다.")


def make_client(
    routing_service: object | None = None,
    place_search_service: object | None = None,
) -> TestClient:
    """개발 인증이 활성화된 격리 테스트 클라이언트를 생성한다."""

    settings = BackendSettings(
        allow_dev_auth=True,
        dev_auth_token="test-token",
        store_backend="memory",
        enable_demo_dispatch=True,
        demo_group_size=3,
    )
    return TestClient(
        create_app(
            settings=settings,
            repository=MemoryRideRepository(),
            routing_service=routing_service or StubRoutingService(),
            place_search_service=place_search_service or StubPlaceSearchService(),
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


def test_destination_place_search_is_public() -> None:
    """Android는 인증 없이 울산 목적지를 이름으로 조회할 수 있다."""

    response = make_client().get("/v1/places/search", params={"query": "울산대학교", "limit": 5})
    assert response.status_code == 200
    assert response.json() == [
        {
            "place_id": "osm-node-123",
            "name": "울산대학교",
            "address": "울산광역시 남구 대학로 93",
            "latitude": 35.5438,
            "longitude": 129.2564,
            "category": "AMENITY",
        }
    ]


def test_destination_place_search_reports_upstream_failure() -> None:
    """OSM 장소 검색 장애는 명확한 502 응답으로 변환해야 한다."""

    response = make_client(place_search_service=FailingPlaceSearchService()).get(
        "/v1/places/search",
        params={"query": "울산대학교"},
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "울산 장소 검색 서버에 연결하지 못했습니다."


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


def test_demo_assignment_waits_for_configured_group_and_assigns_shared_trip() -> None:
    """설정된 세 승객이 모이면 모두 같은 운행에 배정한다."""

    client = make_client()
    first_headers = {
        "Authorization": "Bearer test-token:phone-one",
        "Idempotency-Key": "request-key-demo-phone-one",
    }
    second_headers = {
        "Authorization": "Bearer test-token:phone-two",
        "Idempotency-Key": "request-key-demo-phone-two",
    }
    third_headers = {
        "Authorization": "Bearer test-token:phone-three",
        "Idempotency-Key": "request-key-demo-phone-three",
    }
    first = client.post("/v1/ride-requests", headers=first_headers, json=request_payload())
    second_payload = request_payload()
    second_payload["pickup"] = {
        "place_id": "taehwagang-station",
        "name": "태화강역(종점)",
        "location": {"latitude": 35.53843654, "longitude": 129.3528277},
    }
    second = client.post("/v1/ride-requests", headers=second_headers, json=second_payload)
    third_payload = request_payload()
    third_payload["pickup"] = {
        "place_id": "city-hall-stop",
        "name": "시청앞",
        "location": {"latitude": 35.53915699, "longitude": 129.3123405},
    }
    third = client.post("/v1/ride-requests", headers=third_headers, json=third_payload)

    waiting = client.post(
        "/v1/ride-requests/{}/demo-assign".format(first.json()["request_id"]),
        headers={"Authorization": "Bearer test-token:phone-one"},
    )
    assert waiting.status_code == 200
    assert waiting.json()["status"] == "WAITING"
    assert waiting.json()["matched_passenger_count"] == 1

    second_waiting = client.post(
        "/v1/ride-requests/{}/demo-assign".format(second.json()["request_id"]),
        headers={"Authorization": "Bearer test-token:phone-two"},
    )
    assert second_waiting.json()["status"] == "WAITING"
    assert second_waiting.json()["matched_passenger_count"] == 2

    assigned = client.post(
        "/v1/ride-requests/{}/demo-assign".format(third.json()["request_id"]),
        headers={"Authorization": "Bearer test-token:phone-three"},
    )
    refreshed_first = client.get(
        "/v1/ride-requests/{}".format(first.json()["request_id"]),
        headers={"Authorization": "Bearer test-token:phone-one"},
    )

    assert assigned.status_code == 200
    assert assigned.json()["status"] == "ASSIGNED"
    assert refreshed_first.json()["status"] == "ASSIGNED"
    assert assigned.json()["assigned_vehicle_id"] == "demo-bus-01"
    assert assigned.json()["demo_trip_id"] == refreshed_first.json()["demo_trip_id"]
    assert assigned.json()["matched_passenger_count"] == 3
    assert assigned.json()["demo_group_size"] == 3
    assert len(assigned.json()["demo_route_stops"]) == 6


def test_demo_assignment_counts_companions_toward_departure() -> None:
    """본인과 동반 인원의 합계가 기준에 도달하면 호출 수와 무관하게 출발한다."""

    client = make_client()
    first_payload = request_payload()
    first_payload["passenger_count"] = 2
    first = client.post(
        "/v1/ride-requests",
        headers={
            "Authorization": "Bearer test-token:family-one",
            "Idempotency-Key": "request-key-family-one",
        },
        json=first_payload,
    )
    first_waiting = client.post(
        f"/v1/ride-requests/{first.json()['request_id']}/demo-assign",
        headers={"Authorization": "Bearer test-token:family-one"},
    )
    assert first_waiting.json()["status"] == "WAITING"
    assert first_waiting.json()["matched_passenger_count"] == 2

    second_payload = request_payload()
    second_payload["pickup"] = {
        "place_id": "city-hall-stop",
        "name": "시청앞",
        "location": {"latitude": 35.53915699, "longitude": 129.3123405},
    }
    second = client.post(
        "/v1/ride-requests",
        headers={
            "Authorization": "Bearer test-token:solo-rider",
            "Idempotency-Key": "request-key-solo-rider",
        },
        json=second_payload,
    )
    assigned = client.post(
        f"/v1/ride-requests/{second.json()['request_id']}/demo-assign",
        headers={"Authorization": "Bearer test-token:solo-rider"},
    )
    refreshed_first = client.get(
        f"/v1/ride-requests/{first.json()['request_id']}",
        headers={"Authorization": "Bearer test-token:family-one"},
    )

    assert assigned.json()["status"] == "ASSIGNED"
    assert refreshed_first.json()["status"] == "ASSIGNED"
    assert assigned.json()["matched_passenger_count"] == 3
    assert len(assigned.json()["demo_route_stops"]) == 4


def test_demo_simulation_picks_up_and_drops_off_every_rider() -> None:
    """자동 운행은 모든 P 지점에서 탑승시키고 모든 D 지점에서 완료한다."""

    repository = MemoryRideRepository()
    records = []
    pickup_ids = ["ulsan", "taehwa", "cityhall"]
    pickup_longitudes = [129.1388, 129.3528, 129.3123]
    for index in range(3):
        payload = request_payload()
        payload["pickup"] = {
            "place_id": pickup_ids[index],
            "name": f"승차 {index + 1}",
            "location": {"latitude": 35.54 + index * 0.001, "longitude": pickup_longitudes[index]},
        }
        payload["destination"] = {
            "place_id": f"drop-{index}",
            "name": f"하차 {index + 1}",
            "location": {"latitude": 35.52 + index * 0.001, "longitude": 129.38 + index * 0.01},
        }
        record = RideRequestRecord.new(f"request-{index}", f"user-{index}", RideRequestCreate.model_validate(payload))
        repository.create(record, f"simulation-key-{index}")
        records.append(record)

    for record in records:
        matched = repository.join_demo_pool(record.request_id, record.user_id, "demo-bus-01", 3)
    trip_id = matched.demo_trip_id
    assert trip_id is not None

    run_demo_trip_simulation(repository, trip_id, travel_seconds=0, dwell_seconds=0)

    completed = [repository.get(record.request_id) for record in records]
    assert all(record is not None and record.status.value == "COMPLETED" for record in completed)
    assert all(record is not None and record.demo_trip_phase == "COMPLETED" for record in completed)
    assert all(record is not None and record.demo_current_stop_index == 5 for record in completed)
