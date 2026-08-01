"""호출 API의 인증·중복·소유권·상태 테스트."""

from fastapi.testclient import TestClient

from backend.config import BackendSettings
from backend.main import create_app
from backend.repository import MemoryRideRepository


def make_client() -> TestClient:
    """개발 인증이 활성화된 격리 테스트 클라이언트를 생성한다."""

    settings = BackendSettings(
        allow_dev_auth=True,
        dev_auth_token="test-token",
        store_backend="memory",
    )
    return TestClient(create_app(settings=settings, repository=MemoryRideRepository()))


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
