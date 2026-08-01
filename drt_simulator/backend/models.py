"""Android 앱과 공유하는 API 요청·응답 모델."""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class RequestSource(str, Enum):
    """승객 호출 입력 장치."""

    ANDROID_APP = "ANDROID_APP"
    CAMERA_CARD = "CAMERA_CARD"
    STATION_DEVICE = "STATION_DEVICE"
    MODI_KIOSK = "MODI_KIOSK"
    MODI_APP = "MODI_APP"


class MobilitySupport(str, Enum):
    """승객에게 필요한 탑승 지원."""

    STANDARD = "STANDARD"
    SENIOR = "SENIOR"
    WHEELCHAIR = "WHEELCHAIR"
    VISUAL = "VISUAL"
    HEARING = "HEARING"


class RideStatus(str, Enum):
    """백엔드가 관리하는 호출 상태."""

    WAITING = "WAITING"
    ASSIGNED = "ASSIGNED"
    PICKED_UP = "PICKED_UP"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class Coordinate(BaseModel):
    """WGS84 위도·경도 좌표."""

    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)


class PlacePayload(BaseModel):
    """승차 또는 목적지 장소 정보."""

    place_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    location: Coordinate


class RideRequestCreate(BaseModel):
    """새 호출 생성 요청."""

    source: RequestSource = RequestSource.ANDROID_APP
    pickup: PlacePayload
    destination: PlacePayload
    passenger_count: int = Field(default=1, ge=1, le=6)
    mobility_support: MobilitySupport = MobilitySupport.STANDARD
    guardian_notification_enabled: bool = False

    @field_validator("destination")
    @classmethod
    def destination_must_differ(cls, destination: PlacePayload, info: object) -> PlacePayload:
        """출발지와 목적지가 같은 요청을 거부한다."""

        data = getattr(info, "data", {})
        pickup = data.get("pickup")
        if pickup and pickup.place_id == destination.place_id:
            raise ValueError("pickup and destination must be different")
        return destination


class ModiKioskRideRequestCreate(BaseModel):
    """동부아파트입구 MODI 키오스크에서 들어오는 간소화 호출."""

    device_id: str = Field(default="dongbu-kiosk-01", min_length=3, max_length=100)
    destination_place_id: str = Field(min_length=1, max_length=100)
    passenger_count: int = Field(default=1, ge=1, le=6)
    mobility_support: MobilitySupport = MobilitySupport.STANDARD


class RideRequestRecord(RideRequestCreate):
    """DB에 저장되고 앱에 반환되는 호출 문서."""

    request_id: str
    user_id: str
    status: RideStatus
    assigned_vehicle_id: Optional[str] = None
    demo_trip_id: Optional[str] = None
    # 여러 호출의 동반 인원까지 합산하므로 호출당 최대 인원(6)보다 커질 수 있다.
    matched_passenger_count: int = Field(default=0, ge=0, le=36)
    demo_group_size: int = Field(default=3, ge=2, le=6)
    demo_route_stops: List[PlacePayload] = Field(default_factory=list)
    demo_current_stop_index: int = Field(default=-1, ge=-1, le=12)
    demo_trip_phase: str = "WAITING"
    demo_vehicle_location: Optional[Coordinate] = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def new(cls, request_id: str, user_id: str, payload: RideRequestCreate) -> "RideRequestRecord":
        """검증된 입력으로 WAITING 상태 호출을 생성한다."""

        now = datetime.now(timezone.utc)
        return cls(
            **payload.model_dump(),
            request_id=request_id,
            user_id=user_id,
            status=RideStatus.WAITING,
            created_at=now,
            updated_at=now,
        )


class HealthResponse(BaseModel):
    """Render 상태 확인 응답."""

    status: str
    environment: str
    store_backend: str


class RoutePlace(BaseModel):
    """경로 후보 장소의 이름과 WGS84 좌표."""

    name: str = Field(min_length=1, max_length=100)
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)


class FindNearestRouteRequest(BaseModel):
    """Android 경로 미리보기 요청."""

    start_lat: float = Field(ge=-90.0, le=90.0)
    start_lon: float = Field(ge=-180.0, le=180.0)
    hospitals: List[RoutePlace] = Field(min_length=1, max_length=10)
    network_type: Literal["drive"] = "drive"
    buffer_m: int = Field(default=1200, ge=100, le=10_000)


class FindNearestRouteResponse(BaseModel):
    """가장 가까운 목적지까지의 OSM 도로 경로."""

    nearest_hospital: RoutePlace
    distance_m: float = Field(ge=0.0)
    map_url: str
    route_coords: List[List[float]]


class BusStopResponse(BaseModel):
    """Android에 제공하는 울산 버스 정류소 정보."""

    stop_id: str
    name: str
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    district: str
    distance_m: Optional[float] = Field(default=None, ge=0.0)


class PlaceSearchResponse(BaseModel):
    """Android 도착지 검색에 제공하는 울산 장소 정보."""

    place_id: str
    name: str
    address: str
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    category: str = "PLACE"


class VehicleRouteStep(BaseModel):
    """MODI 차량이 수행할 한 번의 승차·하차 경유지입니다."""

    request_id: str
    type: Literal["PICKUP", "DROPOFF"]
    order: int = Field(ge=1, le=6)
    place: PlacePayload


class VehicleTripResponse(BaseModel):
    """차량 제어기가 조회하는 공동 DRT 운행 정보입니다."""

    trip_id: str
    vehicle_id: str
    route_steps: List[VehicleRouteStep]
    simulation_started: bool = False
    phase: str = "READY"
    current_stop_index: int = Field(default=-1, ge=-1, le=12)


class VehicleTripPollResponse(BaseModel):
    """대기 중인 운행이 없을 수도 있는 차량 폴링 응답입니다."""

    trip: Optional[VehicleTripResponse] = None


class VehicleProgressRequest(BaseModel):
    """MODI 차량이 서버에 보고하는 경유지 진행 상태입니다."""

    stop_index: int = Field(ge=0, le=12)
    phase: Literal["EN_ROUTE", "ARRIVED", "BOARDED", "DROPPED_OFF", "COMPLETED"]
